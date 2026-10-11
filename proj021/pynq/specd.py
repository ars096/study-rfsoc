#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj018 — SAM45-Fine のデータ取得サーバー（PS）。制御 PC の命令で取得し、ダウンロード PC へ送る。

    sudo -E $(which python3) specd.py --clkin 0 --ref 10            # 実機（proj021.bit）
    python3 specd.py --fake                                          # PL なし（通信・溜まりの試験。偽の記録を同じ間隔で作る）

プロセスは 2 つ（README の方針）:
  取得（s45acq、子）: PL を持ち、読み出しの環だけを回す。GC 停止・CPU 固定・可能なら SCHED_FIFO
  通信（このプロセス）: 制御の口（テキスト）・データの口（バイナリ）・送信。PYNQ を import しない
  間は 共有メモリの溜まり（s45ring）と命令のパイプ

制御の口（既定 51000、同時に 1 接続）: 1 行の命令に 1 行の応答 `OK key=value ...` / `ERR <符号> <説明>`
  ID | STATUS | GET | SET key=val ... | ANCHOR | START [at=<UTC>] [n=<ダンプ数>] [force=1] | STOP |
  SEND ON [from=oldest|now] | SEND OFF | CLEAR | BYE | HELP | SHUTDOWN confirm=1（サーバーを止める） |
  SNAP adc=A|B|C|D [n=1] [every=20]（proj019: ADC の生サンプル 8192 個 = 2 µs を n 個、every ms おき。IDLE のときだけ。記録は T_SNAP）
データの口（既定 51001、同時に 1 接続）: s45proto の記録を続けて送る。SEND ON の間だけ。
  **受け側は ACK（<Q の 8 バイト、受け取って書き終えた最後の seq）を返す**（0.2 秒おき程度）。ACK のあった記録だけを溜まりから消し、
  切れたら ACK の無い記録を次の接続で送り直す（受け側は seq で重複を除く）。ACK を返さない受け側では溜まりが溢れ、DROP になる
"""
import argparse
import collections
import datetime as dt
import multiprocessing as mp
import os
import re
import signal
import socket
import sys
import threading
import time

import s45proto as P
import s45ring as R

HELP = ("ID | STATUS | GET | GET CAL | SET key=val ...（tint cfg A0.if A0.ns A0.bw A0.shift all.shift …） | ANCHOR | "
        "START [at=<UTC ISO8601 か unix 秒>] [n=<ダンプ数>] [force=1] | STOP | SEND ON [from=oldest|now] | SEND OFF | CLEAR | BYE | "
        "SHUTDOWN confirm=1 | SNAP adc=A|B|C|D [n=1] [every=20]")


def log(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def fmt_val(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if v is None:
        return "-"
    if isinstance(v, (list, tuple)):
        return ",".join(fmt_val(x) for x in v)
    if isinstance(v, float):
        return f"{v:.6g}"
    s = str(v)
    return s.replace(" ", "_") if s else "-"


def kv_line(d):
    return " ".join(f"{k}={fmt_val(v)}" for k, v in d.items())


def parse_utc(s):
    try:
        return int(round(float(s) * 1e9))
    except ValueError:
        pass
    s = s.replace("Z", "+00:00")
    m = re.match(r"^(.*T\d\d:\d\d:\d\d)(\.\d+)?(.*)$", s)        # Python 3.10 は小数を 3・6 桁しか読まない
    if m and m.group(2):
        s = m.group(1) + (m.group(2) + "000000")[:7] + m.group(3)
    t = dt.datetime.fromisoformat(s)
    if t.tzinfo is None:
        raise ValueError("at= の ISO 8601 には時間帯（Z か +09:00）を付ける")
    d = t - dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
    return (d.days * 86400 + d.seconds) * 10**9 + d.microseconds * 1000


class Server:
    def __init__(self, a):
        self.a = a
        self.ring = R.Ring(a.buf_mb << 20)
        self.pipe, child = mp.Pipe()
        ctx = mp.get_context("fork")
        import s45acq
        self.acq = ctx.Process(target=s45acq.main, args=(child, self.ring, a), daemon=True, name="s45acq")
        self.acq.start()
        try:
            if not self.pipe.poll(a.boot_timeout):
                raise SystemExit("取得のプロセスが起動の結果を返さない")
            r = self.pipe.recv()
            if not r.get("ok"):
                raise SystemExit(r.get("msg"))
        except BaseException:
            self.acq.join(5)
            self.ring.close()                      # 起動に失敗しても共有メモリを残さない
            raise
        self.ids = r
        self.plock = threading.Lock()
        self.send_on = False
        self.dsock = None
        self.dpeer = None
        self.dlock = threading.Lock()
        self.sent = 0
        self.sent_bytes = 0
        self.skip = 0
        self.t_up = time.time()
        self.stop_ev = threading.Event()
        self._pending_ev = None
        self.quit_ev = threading.Event()        # 制御の口の SHUTDOWN
        self.inflight = collections.deque()     # 送ったが ACK の無い記録 (seq, 溜まりの終わりの位置)
        self.acked = 0
        self.last_drop = None                    # 最後にデータの口を切った時刻・相手・理由

    # ---- 取得への命令
    def acq_cmd(self, d, timeout=30.0):
        with self.plock:
            self.pipe.send(d)
            if not self.pipe.poll(timeout):
                return dict(ok=False, code="ACQ", msg="取得のプロセスが応えない")
            return self.pipe.recv()

    # ---- 制御
    def control(self, line):
        w = line.strip().split()
        if not w:
            return None
        cmd, args = w[0].upper(), w[1:]
        kv = {}
        for x in args:
            if "=" in x:
                k, v = x.split("=", 1)
                kv[k] = v
        if cmd == "HELP":
            return "OK " + HELP
        if cmd == "ID":
            r = self.acq_cmd(dict(op="id"))
            return self._rep(r, lambda r: kv_line(dict(version=r["version"], win_id=r["ids"]["win"], adc_id=r["ids"]["adc"],
                                                       time_id=r["ids"]["time"], lmx_vco=r["ids"].get("lmx_vco", "-"), lmx_pwr=r["ids"].get("lmx_pwr", "-"),
                                                       adcs=r["adcs"], nw=r["nw"], fake=r["fake"],
                                                       proto=P.VERSION)))
        if cmd == "STATUS":
            r = self.acq_cmd(dict(op="status"))
            def f(r):
                d = {k: r[k] for k in ("state", "time_ok", "start_at", "dumps", "miss", "kgap", "tp", "tp_lost", "tp_bad", "tp_ovr", "tp_dbfs", "tp_dbm",
                                       "sat", "loop_max_ms", "loop_p99_ms", "seq", "drop", "forced")}
                d["health"] = f"{r['health']:#06x}"
                d["flags"] = f"{r['flags']:#05x}"
                d["buf_used_mb"] = round(r["ring_used"] / 2**20, 1)
                d["buf_cap_mb"] = round(r["ring_cap"] / 2**20, 1)
                d["data_client"] = self.dpeer or "none"
                d["send"] = "on" if self.send_on else "off"
                d["sent"] = self.sent
                d["acked"] = self.acked
                d["inflight"] = len(self.inflight)
                d["sent_mb"] = round(self.sent_bytes / 2**20, 1)
                d["skip"] = self.skip
                d["data_drop"] = self.last_drop or "-"
                if r.get("err"):
                    d["err"] = r["err"]
                if r.get("time_err"):
                    d["time_err"] = r["time_err"]
                return kv_line(d)
            return self._rep(r, f)
        if cmd == "GET" and args and args[0].upper() == "CAL":
            r = self.acq_cmd(dict(op="cal"))
            def f(r):
                c = r.get("cal")
                if not c:
                    return kv_line(dict(cal="none", msg=r.get("msg")))
                d = dict(file=c.get("file"), bit=c.get("bit_id_win"), unit=c.get("unit"))
                for a, v in sorted(c["adc"].items()):
                    d[f"{a}.k"] = round(v["k_db"], 3); d[f"{a}.prov"] = bool(v.get("provisional")); d[f"{a}.date"] = v.get("date")
                return kv_line(d)
            return self._rep(r, f)
        if cmd == "GET":
            r = self.acq_cmd(dict(op="get"))
            def f(r):
                st = r["settings"]
                d = dict(tint=st["tint"], cfg=f"{st['cfg']:#x}")
                for j, ws in enumerate(st["wins"]):
                    key = f"{'ABCD'[j // 2]}{j % 2}"
                    d[f"{key}.if"] = ws["if_mhz"]; d[f"{key}.ns"] = ws["ns"]; d[f"{key}.bw"] = 512 >> ws["ns"]; d[f"{key}.shift"] = ws["shift"]
                return kv_line(d)
            return self._rep(r, f)
        if cmd == "SET":
            if not kv:
                return "ERR ARG SET key=val ..."
            return self._rep(self.acq_cmd(dict(op="set", kv=kv)), lambda r: "")
        if cmd == "ANCHOR":
            return self._rep(self.acq_cmd(dict(op="anchor")), lambda r: "")
        if cmd == "START":
            bad = [x for x in args if "=" not in x or x.split("=", 1)[0] not in ("at", "n", "force")]
            if bad:
                return f"ERR ARG START に知らない引数 {' '.join(bad)}（at= n= force=）"
            d = dict(op="start", n=int(kv.get("n", 0)), force=kv.get("force", "0") not in ("0", ""))
            if "at" in kv:
                try:
                    d["at_utc_ns"] = parse_utc(kv["at"])
                except ValueError as e:
                    return f"ERR ARG {e}"
            return self._rep(self.acq_cmd(d), lambda r: kv_line(dict(start_at=r["start_at"], utc_ns=r["utc_ns"],
                                                                     utc=_iso(r["utc_ns"]))))
        if cmd == "STOP":
            return self._rep(self.acq_cmd(dict(op="stop")), lambda r: "")
        if cmd == "SNAP":
            bad = [x for x in args if "=" not in x or x.split("=", 1)[0] not in ("adc", "n", "every")]
            if bad or "adc" not in kv:
                return "ERR ARG SNAP adc=A|B|C|D [n=1] [every=20]"
            a = kv["adc"].upper()
            adc = "ABCD".index(a) if a in ("A", "B", "C", "D") else int(a) if a.isdigit() else -1
            try:
                d = dict(op="snap", adc=adc, n=int(kv.get("n", 1)), every_ms=float(kv.get("every", 20)))
            except ValueError as e:
                return f"ERR ARG {e}"
            tmo = 10.0 + d["n"] * d["every_ms"] * 1e-3 * 1.5
            return self._rep(self.acq_cmd(d, timeout=tmo), lambda r: kv_line(dict(n=r["n"], nacc=r["nacc"], every_ms=r["every_ms"])))
        if cmd == "SEND":
            if not args or args[0].upper() not in ("ON", "OFF"):
                return "ERR ARG SEND ON [from=oldest|now] / SEND OFF"
            if args[0].upper() == "OFF":
                self.send_on = False
                return "OK send=off"
            fr = kv.get("from", "oldest")
            if fr not in ("oldest", "now"):
                return "ERR ARG from=oldest|now"
            with self.dlock:
                if fr == "now":
                    self._skip_all("SEND ON from=now")
                self.send_on = True
            return f"OK send=on data_client={self.dpeer or 'none'}"
        if cmd == "CLEAR":
            with self.dlock:
                n = self._skip_all("CLEAR")
            return f"OK skipped={n}"
        if cmd in ("BYE", "QUIT"):
            return "OK bye"
        if cmd == "SHUTDOWN":
            if kv.get("confirm") != "1":
                return "ERR ARG サーバーを止めるときは SHUTDOWN confirm=1（RUN なら STOP してから止める）"
            self.quit_ev.set()
            return "OK shutdown"
        return f"ERR CMD 知らない命令 {cmd}（HELP）"

    def _skip_all(self, why):
        """溜まりを捨てる（dlock を持って呼ぶ）。捨てた範囲は SKIP の EVENT（seq 0）でデータの口へ先に知らせる"""
        self.inflight.clear()
        r = self.ring.skip_all()
        if r is None:
            return 0
        a, b, n = r
        self.skip += n
        self._pending_ev = dict(ev="SKIP", why=why, **{"from": a, "to": b, "n": n})
        log(f"溜まりを捨てた（{why}）: seq {a}〜{b}（{n} 個）")
        return n

    @staticmethod
    def _rep(r, f):
        if not r.get("ok"):
            return f"ERR {r.get('code', 'FAIL')} {r.get('msg') or ''}".rstrip()
        s = f(r)
        return "OK" + (" " + s if s else "")

    def serve_control(self):
        srv = _listen(self.a.host, self.a.ctrl_port)
        log(f"制御の口: {self.a.host}:{self.a.ctrl_port}")
        busy = threading.Lock()
        while not self.stop_ev.is_set():
            try:
                s, peer = srv.accept()
            except OSError:
                break
            if not busy.acquire(blocking=False):
                try:
                    s.sendall("ERR BUSY 制御の口は 1 接続まで\n".encode())
                finally:
                    s.close()
                continue
            threading.Thread(target=self._ctl_conn, args=(s, peer, busy), daemon=True).start()

    def _ctl_conn(self, s, peer, busy):
        log(f"制御: 接続 {peer[0]}:{peer[1]}")
        try:
            f = s.makefile("rwb", buffering=0)
            for raw in f:
                try:
                    line = raw.decode("utf-8", "replace")
                except Exception:
                    line = ""
                try:
                    rep = self.control(line)
                except Exception as e:
                    rep = f"ERR FAIL {type(e).__name__}: {e}"
                if rep is None:
                    continue
                log(f"制御: {line.strip()} → {rep[:160]}")
                s.sendall((rep.replace("\n", " ") + "\n").encode())
                if rep == "OK bye":
                    break
        except OSError:
            pass
        finally:
            s.close()
            busy.release()
            log(f"制御: 切断 {peer[0]}:{peer[1]}")

    # ---- データ
    def serve_data(self):
        srv = _listen(self.a.host, self.a.data_port)
        log(f"データの口: {self.a.host}:{self.a.data_port}")
        while not self.stop_ev.is_set():
            try:
                s, peer = srv.accept()
            except OSError:
                break
            with self.dlock:
                if self.dsock is not None:
                    try:
                        s.sendall(P.event_record(dict(ev="BUSY", msg="データの口は 1 接続まで")))
                    finally:
                        s.close()
                    continue
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
                s.settimeout(self.a.send_timeout)
                self.dsock, self.dpeer = s, f"{peer[0]}:{peer[1]}"
            log(f"データ: 接続 {self.dpeer}")
            threading.Thread(target=self._watch_data, args=(s,), daemon=True).start()

    def _watch_data(self, s):
        """受け側からは ACK（<Q、受け取って書き終えた最後の seq）だけが来る。ACK の seq までの記録を溜まりから消す。
        0 バイト（切断）・読めない → 切る。切れたら、送ったが ACK の無い記録は次の接続で送り直す（受け側は seq で重複を除く）"""
        rest = b""
        try:
            while True:
                b = s.recv(4096)
                if not b:
                    break
                rest += b
                n = len(rest) // 8
                if n:
                    seq = int.from_bytes(rest[8 * (n - 1):8 * n], "little")
                    rest = rest[8 * n:]
                    with self.dlock:
                        if self.dsock is s:
                            end = None
                            while self.inflight and self.inflight[0][0] <= seq:
                                end = self.inflight.popleft()[1]
                            if end is not None:
                                self.ring.ack_to(end)
                                self.acked = seq
        except OSError:
            pass
        self._drop_data(s, "受け側が閉じた")

    def _drop_data(self, s, why):
        with self.dlock:
            if self.dsock is s:
                log(f"データ: 切断 {self.dpeer}（{why}）。ACK の無い記録 {len(self.inflight)} 個は次の接続で送り直す")
                self.last_drop = f"{time.strftime('%H:%M:%S')} {self.dpeer} {why}"   # STATUS の data_drop（受け側が理由を知るため）
                self.dsock, self.dpeer = None, None
                self.inflight.clear()
                self.ring.rewind()
        try:
            s.close()
        except OSError:
            pass

    def sender(self):
        while not self.stop_ev.is_set():
            with self.dlock:
                s = self.dsock if self.send_on else None
                ev, self._pending_ev = (self._pending_ev, None) if s is not None else (None, self._pending_ev)
                r = self.ring.next_record() if s is not None else None
            if s is None:
                time.sleep(0.01)
                continue
            try:
                if ev is not None:
                    s.sendall(P.event_record(ev))
                if r is None:
                    time.sleep(0.002)
                    continue
                mv, seq, end = r
                s.sendall(mv)
                n = len(mv)
                mv.release()
                with self.dlock:
                    if self.dsock is s:
                        self.ring.advance(end)
                        self.inflight.append((seq, end))
                self.sent += 1
                self.sent_bytes += n
            except (OSError, socket.timeout) as e:
                self._drop_data(s, f"送れない: {e}")

    def run(self):
        threading.Thread(target=self.serve_control, daemon=True).start()
        threading.Thread(target=self.serve_data, daemon=True).start()
        threading.Thread(target=self.sender, daemon=True).start()
        try:
            while self.acq.is_alive() and not self.quit_ev.is_set():
                time.sleep(0.5)
            if self.quit_ev.is_set():
                log("止める（制御の口の SHUTDOWN）")
            else:
                log("取得のプロセスが止まった")
        except KeyboardInterrupt:
            log("止める（Ctrl-C / TERM）。もう一度 Ctrl-C ですぐ抜ける")
            signal.signal(signal.SIGINT, lambda *_: os._exit(1))
        self._shutdown()

    def _shutdown(self):
        """取得に quit を頼み（RUN なら STOP してから抜ける）、来なければ terminate → kill。最後に共有メモリを片付ける。
        取得のプロセスは SIGINT を無視している（端末の Ctrl-C は親と子の両方に届く。子が先に落ちると親の片付けが止まった。2026-10-05 実機）"""
        if self.plock.acquire(timeout=3.0):         # 制御の口の命令が取得の応答を待っている途中なら、少し待つ
            try:
                self.pipe.send(dict(op="quit"))
                if self.pipe.poll(10.0):
                    self.pipe.recv()
            except (OSError, EOFError):
                pass
            finally:
                self.plock.release()
        self.acq.join(5)
        if self.acq.is_alive():
            log("取得のプロセスが quit で抜けない → terminate")
            self.acq.terminate(); self.acq.join(3)
        if self.acq.is_alive():
            self.acq.kill(); self.acq.join(2)
        self.stop_ev.set()
        try:
            with self.dlock:
                self.inflight.clear()
            self.ring.close()
        except BufferError:
            log("共有メモリの片付け: 送信の途中の参照が残っていた（OS が片付ける）")
        log("止めた")


def _iso(ns):
    if not ns:
        return "-"
    return dt.datetime.fromtimestamp(ns // 10**9, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + f".{ns % 10**9:09d}Z"


def _listen(host, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((host, port))
    s.listen(2)
    return s


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--ctrl-port", type=int, default=51000)
    p.add_argument("--data-port", type=int, default=51001)
    p.add_argument("--buf-mb", type=int, default=256, help="溜まりの大きさ [MiB]（256 で ≒ 38 秒ぶん）")
    p.add_argument("--send-timeout", type=float, default=10.0, help="データの口の送信がこの秒数進まなければ切る")
    p.add_argument("--bitfile", default="proj021.bit", help="proj021 の .bit（同じ名前の .hwh が同じ場所に要る）")
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--lmx-chdiv", type=int, default=16, choices=(16, 24),
                   help="LMX2594 の CHDIV（出力 491.52 は同じ）。16 = 出荷時（VCO 7864.32 MHz）、24 = VCO 11796.48 MHz（櫛の出どころの試験）")
    p.add_argument("--lmx-pwr", type=int, default=3,
                   help="LMX2594 の OUTA・OUTB の強さ（0〜63）。既定 3（proj019: 櫛 n×163.84 MHz の和が −5.7 dB、ロック・位相雑音は"
                        " PWR 0 まで問題なし）。出荷時は 31")
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--path", default="trig", choices=("trig", "comp"))
    p.add_argument("--cpu", type=int, default=3, help="取得のプロセスを固定する CPU（-1 で固定しない）")
    p.add_argument("--rt", type=int, default=10, help="取得のプロセスの SCHED_FIFO の優先度（0 で使わない）")
    p.add_argument("--loop-sleep", type=float, default=0.003, help="読み出しの 1 周の後に寝る秒数（proj017 F-4 と同じ 3 ms）")
    p.add_argument("--boot-timeout", type=float, default=120.0)
    p.add_argument("--fake", action="store_true", help="PL を使わない（偽の記録。通信の試験）")
    p.add_argument("--tp-cal", default="tp_cal.json", help="TP の dBm の較正ファイル（無ければ使わない。s45cal.py）")
    p.add_argument("--fake-notime", action="store_true", help="偽物で 1PPS が無い（時刻を答えられない）状態を作る")
    p.add_argument("--fake-stall", type=int, default=0, help="偽物の陽性対照: 窓 A0 の k がこの倍数のとき読み出しを 50 ms 止める")
    p.add_argument("--posctl-corrupt", type=int, default=0, help="陽性対照: seq がこの倍数の記録の中身を CRC の後に 1 bit 反転")
    p.add_argument("--posctl-gap", type=int, default=0, help="陽性対照: seq がこの倍数の記録を黙って捨てる（DROP を出さない）")
    p.add_argument("--read", default="ring", choices=("ring", "axi"),
                   help="proj021 2-3a: PL からの読み口（ring = PL が書くリングのレコード / axi = 仮の読み窓、2-2d まで）")
    p.add_argument("--ring-mib", type=int, default=32, help="PL が書くリングの大きさ [MiB]（--read ring）")
    p.add_argument("--posctl-ring-stall", type=float, default=0.0, help="陽性対照: RUN の 100 周目にこの秒数リングを読まない")
    a = p.parse_args()
    a.cpu = None if a.cpu < 0 else a.cpu
    if a.cpu is not None and a.cpu >= os.cpu_count():
        a.cpu = os.cpu_count() - 1
    if a.posctl_corrupt or a.posctl_gap or a.fake_stall:
        log(f"注意: 陽性対照の変種で動いている（corrupt {a.posctl_corrupt}・gap {a.posctl_gap}・fake_stall {a.fake_stall}）")
    def _on_sig(signum, _frm):
        log(f"信号 {signal.Signals(signum).name} を受けた")
        raise KeyboardInterrupt
    # SIGINT も明示して受ける（起動のされ方で SIGINT が無視の状態で引き継がれていると、Python は Ctrl-C を受けない）。TERM も同じに片付ける
    signal.signal(signal.SIGINT, _on_sig)
    signal.signal(signal.SIGTERM, _on_sig)
    log(f"specd の PID {os.getpid()}（止める: Ctrl-C・kill {os.getpid()}・制御の口の SHUTDOWN confirm=1）")
    cal_path, a.tp_cal = a.tp_cal, None
    if cal_path and os.path.exists(cal_path):
        import s45cal
        try:
            a.tp_cal = s45cal.load(cal_path)
            log(f"TP の較正ファイル: {a.tp_cal['_file']}（bit の ID は取得の起動の後に照らす）")
        except (ValueError, OSError) as e:
            log(f"TP の較正ファイルを読めない（使わない）: {e}")
            a.tp_cal = None
    else:
        log(f"TP の較正ファイル {cal_path} が無い（STATUS の tp_dbm は出さない）")
    Server(a).run()
    sys.stdout.flush()
    os._exit(0)                                   # 受け・送りのスレッド（daemon）や multiprocessing の後始末を待たない


if __name__ == "__main__":
    main()
