#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj018 — 試験用: Jupyter から specd に繋ぎ、制御とデータの受け取りを 1 つの物で行う（numpy、図は matplotlib があれば）

    from s45client import S45
    s = S45("<board>")                       # 制御の口とデータの口の両方に繋ぐ（データは裏のスレッドで受け、ACK を返す）
    s.status()                              # STATUS を辞書で
    s.set(A0_bw=256, A1_bw=8, all_shift=9)  # 鍵の "." は "_" で書ける（"A0.bw" と同じ）。s.set("A0.if=2900") の形も可
    d = s.acquire(25)                       # SEND ON → START n=25 → 8 窓とも 25 ダンプ届くまで待つ（≒ 1 秒）
    d.spec("A0").shape                      # (25, 4096) の float64（生の積分値、IF の昇順）
    d.freq("A0")                            # IF [MHz]（昇順）
    d.tp("A")                               # ADC_A の TP（t_beat・utc_ns・sum・nfr・flags の構造化配列）
    s.plot("A0")                            # 平均のスペクトル（dB）。s.plot(["A0", "A1"], db=False)
    s.check()                               # 受けた記録の照合（CRC・番号の欠け・DUMP_K・DUMP_T・TP の連続）
    s.close()

- 受けた記録は窓ごとに直近 keep 個（既定 500 ダンプ ≒ 20 秒、8 窓で ≒ 130 MB）、TP は ADC ごとに直近 keep_tp 区切りを手元に持つ。
  out= を渡せば全部をファイルにも書く（specrecv.py --file で読める）
- s.clear_local() で手元の記録を空にする。acquire() は呼ぶたびに手元を空にしてから始める（clear=False で残す）
- 制御の口は同時に 1 接続なので、これを開いている間は specctl.py は ERR BUSY になる（s.cmd("...") で同じ命令を打てる）
- ボードの上の Jupyter で動かすと、受けの処理（≒ 6.5 MB/s）がボードの CPU を使う。読み出しの余裕を測る試験（P-1）では使わない
"""
import collections
import select
import socket
import threading
import time

import numpy as np

import s45proto as P
from specctl import Ctl
from specrecv import Check

KEYS = [f"{a}{w}" for a in "ABCD" for w in "01"]


def _key(adc, win):
    return f"{'ABCD'[adc]}{win}"


def _adc_index(a):
    return "ABCD".index(a[0].upper()) if isinstance(a, str) else int(a)


class Data:
    """受けた記録の手元の写し（その時点のもの）。窓は "A0"〜"D1"、ADC は "A"〜"D"（か 0〜3）"""

    def __init__(self, wins, tps, events):
        self._w, self._t, self.events = wins, tps, events

    def keys(self):
        return [k for k in KEYS if self._w.get(k)]

    def meta(self, key):
        """窓 key のダンプごとのメタ（k・dump_t・utc_ns・health・sat・flags・shift・nacc・ns・if_mhz・cfg）の構造化配列"""
        recs = self._w.get(key, [])
        dt = [("k", "i8"), ("dump_t", "i8"), ("utc_ns", "i8"), ("health", "u4"), ("sat", "u4"), ("flags", "u4"),
              ("shift", "u1"), ("nacc", "u4"), ("ns", "u1"), ("g", "u1"), ("if_mhz", "f8"), ("cfg", "u4")]
        m = np.zeros(len(recs), dt)
        for i, (d, _) in enumerate(recs):
            for f in m.dtype.names:
                m[f][i] = d[f]
        return m

    def spec(self, key, raw=False):
        """窓 key のスペクトル (ダンプ数, 4096)。既定は float64、raw=True で uint64（PL の値そのまま）。IF の昇順"""
        recs = self._w.get(key, [])
        if not recs:
            return np.zeros((0, P.NCH), np.uint64 if raw else np.float64)
        a = np.stack([x for _, x in recs])
        return a if raw else a.astype(np.float64)

    def freq(self, key):
        """窓 key の ch ごとの IF [MHz]（昇順。window.ch_if と同じ式を、記録の if_mhz・ns から）"""
        recs = self._w.get(key, [])
        if not recs:
            raise KeyError(f"{key} の記録が無い")
        d = recs[-1][0]
        w = 512.0 / (1 << d["ns"])
        b = P.IF_ORDER
        nu = np.where(b < P.NCH // 2, b, b - P.NCH) * (w / P.NCH)
        return d["if_mhz"] - nu

    def tp(self, adc):
        """ADC の TP（区切りごと: t_beat・utc_ns・sum・nfr・flags）。1 サンプルあたりの電力は sum / (nfr·8192)（16 bit の生値の二乗）"""
        parts = self._t.get(_adc_index(adc), [])
        return np.concatenate(parts) if parts else np.zeros(0, P.TP_E)


class S45:
    def __init__(self, host, ctrl_port=51000, data_port=51001, keep=500, keep_tp=200_000, out=None, timeout=60.0,
                 send_from="oldest"):
        self.host, self.keep, self.keep_tp = host, keep, keep_tp
        self.ctl = Ctl(host, ctrl_port, timeout=timeout)
        self._lock = threading.Lock()
        self._w = {k: collections.deque(maxlen=keep) for k in KEYS}
        self._t = {i: collections.deque() for i in range(4)}
        self._tn = {i: 0 for i in range(4)}
        self.events = []
        self.chk = Check(verbose=False)
        self._out = open(out, "ab") if out else None
        self._stop = threading.Event()
        self._err = None
        self.ds = socket.create_connection((host, data_port), timeout=timeout)
        self.ds.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 << 20)
        self._th = threading.Thread(target=self._recv_loop, daemon=True, name="s45recv")
        self._th.start()
        self.send_from = send_from
        # 繋いだ直後に確かめる: 制御の口が ERR BUSY でないこと・データの口が BUSY で切られていないこと
        try:
            self.id()
        except Exception as e:
            self.close()
            raise RuntimeError(f"制御の口に繋げない（他の specctl・S45 が繋いだままでは？）: {e}") from None
        time.sleep(0.3)
        if self._err:
            msg = self._err
            self.close()
            raise RuntimeError(f"データの口に繋げない: {msg}")

    # ---------------------------------------------------------------- 制御
    def cmd(self, line):
        """命令を 1 行打って応答の文字列を返す（specctl と同じ）"""
        return self.ctl.cmd(line)

    def _kv(self, line):
        r = self.ctl.cmd(line)
        if not r.startswith("OK"):
            raise RuntimeError(r)
        out = {}
        for x in r.split()[1:]:
            if "=" in x:
                k, v = x.split("=", 1)
                out[k] = _num(v)
        return out

    def id(self):
        return self._kv("ID")

    def status(self):
        return self._kv("STATUS")

    def get(self):
        return self._kv("GET")

    def set(self, *args, **kw):
        """s.set(A0_bw=256, all_shift=9) / s.set("A0.if=2900", "B1.bw=8")。IDLE のときだけ"""
        items = list(args) + [f"{k.replace('_', '.')}={v}" for k, v in kw.items()]
        if not items:
            raise ValueError("何も設定していない")
        return self._kv("SET " + " ".join(items))

    def start(self, n=0, at=None, force=False):
        line = f"START n={int(n)}"
        if at is not None:
            line += f" at={at}"
        if force:
            line += " force=1"
        return self._kv(line)

    def stop(self):
        return self._kv("STOP")

    def send(self, on=True, from_=None):
        if not on:
            return self._kv("SEND OFF")
        return self._kv(f"SEND ON from={from_ or self.send_from}")

    def clear(self):
        """サーバーの溜まりを捨てる（手元は clear_local）"""
        return self._kv("CLEAR")

    def anchor(self):
        return self._kv("ANCHOR")

    def wait_idle(self, timeout=600.0, poll=0.5):
        t_e = time.time() + timeout
        while time.time() < t_e:
            st = self.status()
            if st["state"] in ("IDLE", "ERROR"):
                return st
            time.sleep(poll)
        raise TimeoutError("IDLE にならない")

    def acquire(self, n, clear=True, timeout=None, settle=1.0, **setkw):
        """n ダンプを取って手元の写し（Data）を返す: [SET] → SEND ON → START n → 8 窓とも n 個届くまで待つ。
        clear=True なら、始める前にサーバーの溜まりと手元を空にする（前の残りを混ぜない）"""
        st = self.status()
        if st["state"] in ("ARMED", "RUN"):
            raise RuntimeError(f"サーバーが {st['state']}（先に stop()）")
        if setkw:
            self.set(**setkw)
        if clear:
            self.clear()
            self.clear_local()
        self.send(True)
        r = self.start(n=n)
        tint = float(self.get()["tint"])
        t_e = time.time() + (timeout or (n * tint + 10.0))
        while time.time() < t_e:
            with self._lock:
                got = min(sum(1 for d, _ in self._w[k] if d["_run"] == r["start_at"]) for k in KEYS)
                stopped = any(e.get("ev") == "STOP" for e in self.events[-4:])
            if got >= min(n, self.keep):
                break
            if self._err:
                raise RuntimeError(f"受けのスレッドが止まった: {self._err}")
            time.sleep(0.05)
        else:
            raise TimeoutError(f"{n} ダンプが届かない（届いたのは 8 窓の最小で {got}）")
        time.sleep(settle if not stopped else 0)        # TP の最後の記録・STOP の EVENT を待つ
        return self.data()

    # ---------------------------------------------------------------- データ
    def data(self):
        """今の手元の写し（Data）。受けは裏で続いている"""
        with self._lock:
            w = {k: list(v) for k, v in self._w.items()}
            t = {i: list(v) for i, v in self._t.items()}
            ev = list(self.events)
        return Data(w, t, ev)

    def clear_local(self):
        with self._lock:
            for v in self._w.values():
                v.clear()
            for i in self._t:
                self._t[i].clear(); self._tn[i] = 0
            self.events.clear()

    def check(self):
        """受けた記録の照合（specrecv と同じ）。unexplained・crc_bad・kgap・tdev・tp_gap が 0 なら良い"""
        with self._lock:
            return self.chk.summary()

    def plot(self, keys="A0", db=True, avg=True, ax=None):
        import matplotlib.pyplot as plt
        d = self.data()
        keys = [keys] if isinstance(keys, str) else list(keys)
        if ax is None:
            _, ax = plt.subplots(figsize=(9, 4))
        for k in keys:
            sp = d.spec(k)
            if not len(sp):
                continue
            y = sp.mean(0) if avg else sp[-1]
            y = y / d.meta(k)["nacc"][-1]                  # 1 フレームあたり
            ax.plot(d.freq(k), 10 * np.log10(np.maximum(y, 1e-30)) if db else y, lw=0.7,
                    label=f"{k} ({512 >> int(d.meta(k)['ns'][-1])} MHz, {'mean of ' if avg else 'last of '}{len(sp)})")
        ax.set_xlabel("IF [MHz]")                          # 図の文字は英語（ボードの matplotlib に日本語のフォントが無いことがある）
        ax.set_ylabel("sum |q|^2 per frame" + (" [dB]" if db else ""))
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
        return ax

    # ---------------------------------------------------------------- 受けのスレッド
    def _recv_loop(self):
        s = self.ds
        hb = bytearray(P.HDR.size)
        run = None
        t_ack = time.time()
        try:
            while not self._stop.is_set():
                if self.chk.last_seq and time.time() > t_ack:
                    if self._out:
                        self._out.flush()
                    s.sendall(self.chk.last_seq.to_bytes(8, "little"))
                    t_ack = time.time() + 0.2
                if not select.select([s], [], [], 0.2)[0]:
                    continue
                _read_exact(s, hb)
                rtype, plen, crc, seq = P.parse_header(hb)
                pb = bytearray(plen)
                _read_exact(s, pb)
                with self._lock:
                    if seq and self.chk.last_seq is not None and seq <= self.chk.last_seq:
                        self.chk.dup += 1
                        continue
                    if self._out:
                        self._out.write(hb); self._out.write(pb)
                    self.chk.record(rtype, crc, seq, bytes(pb))
                    if P.crc32(pb) != crc:
                        continue
                    if rtype == P.T_SPEC:
                        d = P.decode(rtype, pb)
                        d["_run"] = run
                        x = d.pop("data").copy()
                        self._w[_key(d["adc"], d["win"])].append((d, x))
                    elif rtype == P.T_TP:
                        d = P.decode(rtype, pb)
                        i = d["adc"]
                        self._t[i].append(d["e"].copy())
                        self._tn[i] += d["n"]
                        while self._tn[i] - len(self._t[i][0]) >= self.keep_tp:
                            self._tn[i] -= len(self._t[i].popleft())
                    elif rtype == P.T_EVENT:
                        d = P.decode(rtype, pb)
                        self.events.append(d)
                        if d.get("ev") == "START":
                            run = d["start_at"]
        except Exception as e:          # 切断など。サーバーが理由を EVENT で言っていれば添える
            if not self._stop.is_set():
                last = self.events[-1] if self.events else None
                why = f"（サーバー: {last.get('ev')} {last.get('msg', '')}）" if last and last.get("ev") in ("BUSY", "ERROR") else ""
                self._err = f"{type(e).__name__}: {e}{why}"

    def close(self):
        self._stop.set()
        try:
            if self.chk.last_seq:
                self.ds.sendall(self.chk.last_seq.to_bytes(8, "little"))
        except OSError:
            pass
        self._th.join(2)
        self.ds.close()
        self.ctl.close()
        if self._out:
            self._out.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def __repr__(self):
        with self._lock:
            n = {k: len(v) for k, v in self._w.items()}
        return f"S45({self.host}, 手元 {sum(n.values())} ダンプ、受けの誤り {self._err or 'なし'})"


def _read_exact(s, buf):
    mv = memoryview(buf)
    got = 0
    while got < len(buf):
        k = s.recv_into(mv[got:])
        if k == 0:
            raise ConnectionError("サーバーが切った")
        got += k


def _num(v):
    for f in (int, float):
        try:
            return f(v)
        except ValueError:
            pass
    if "," in v:
        return [_num(x) for x in v.split(",")]
    return v
