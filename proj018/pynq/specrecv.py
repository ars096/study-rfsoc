#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj018 — ダウンロード PC の側の道具: specd のデータの口から記録を受け、照合し、ファイルに書く（numpy と s45proto.py）

    python3 specrecv.py --host <board> --out run1.s45 --seconds 3600     # 受けて書く。60 秒ごとに数を出す
    python3 specrecv.py --file run1.s45                                  # 書いたファイルを読み直して同じ照合をする

照合（P-1・P-1b・P-4）:
  - 記録ごとの CRC-32（取得の側が PL から読んだ値で計算したもの）が一致する
  - seq の欠けが、DROP / SKIP の EVENT の範囲で全部説明できる（説明できない欠け = 0 が合格）
  - SPEC: (ADC, 窓) ごとに DUMP_K が 1 ずつ、DUMP_T が N_ACC·L ずつ進む（START の後。START をまたぐと番号は 0 から）
  - TP: ADC ごとに区切りの頭のビートが 262,144 ずつ進む
書いたファイルは受けた記録をそのまま続けたもの（同じ形。--file で読める）。送り直された記録（seq が前と同じか小さい）は書かない。
ACK: 書き終えた最後の seq を 0.2 秒おきに <Q の 8 バイトで返す（specd はそこまでを溜まりから消す）
"""
import argparse
import json
import select
import socket
import sys
import time

import numpy as np

import s45proto as P

TP_BEATS = 512 * 512


class Check:
    def __init__(self):
        self.n = {t: 0 for t in P.T_NAMES}
        self.bytes = 0
        self.crc_bad = 0
        self.last_seq = None
        self.gaps = []                # 観測した欠け (a, b)
        self.declared = []            # DROP / SKIP が言った範囲 (a, b)
        self.seq_back = 0
        self.k = {}
        self.kgap = 0
        self.tdev = 0
        self.tp_t = {}
        self.tp_gap = 0
        self.h_or = 0
        self.sat = 0
        self.flags_or = 0
        self.events = []
        self.spec_ok_shapes = 0
        self.first_t = None
        self.epoch = 0
        self.dup = 0

    def record(self, rtype, crc, seq, payload):
        self.n[rtype] = self.n.get(rtype, 0) + 1
        self.bytes += P.HDR.size + len(payload)
        if P.crc32(payload) != crc:
            self.crc_bad += 1
            return
        if seq:
            if self.last_seq is not None:
                if seq > self.last_seq + 1:
                    self.gaps.append((self.last_seq + 1, seq - 1))
                    self.epoch += 1               # 欠けの後は (ADC, 窓)・TP の連続を数え直す（捨てた記録の分は seq の照合が受け持つ）
                elif seq <= self.last_seq:
                    self.seq_back += 1
            self.last_seq = seq
        d = P.decode(rtype, payload)
        if rtype == P.T_SPEC:
            key = (d["adc"], d["win"])
            L = 4096 << (d["ns"] - 1)
            if key in self.k and self.k[key][2] == self.epoch:
                k0, t0, _ = self.k[key]
                if d["k"] != k0 + 1:
                    self.kgap += 1
                elif d["dump_t"] - t0 != d["nacc"] * L:
                    self.tdev += 1
            self.k[key] = (d["k"], d["dump_t"], self.epoch)
            self.h_or |= d["health"]; self.sat += d["sat"]; self.flags_or |= d["flags"]
        elif rtype == P.T_TP:
            e = d["e"]
            if len(e):
                t = e["t_beat"].astype(np.int64)
                if d["adc"] in self.tp_t and self.tp_t[d["adc"]][1] == self.epoch and t[0] - self.tp_t[d["adc"]][0] != TP_BEATS:
                    self.tp_gap += 1
                self.tp_gap += int(np.sum(np.diff(t) != TP_BEATS))
                self.tp_t[d["adc"]] = (int(t[-1]), self.epoch)
        elif rtype == P.T_EVENT:
            self.events.append(d)
            ev = d.get("ev")
            if ev in ("DROP", "SKIP"):
                self.declared.append((d["from"], d["to"]))
            if ev == "START":
                self.k.clear(); self.tp_t.clear()
            print(f"  EVENT seq {seq}: {json.dumps(d, ensure_ascii=False)[:300]}", flush=True)

    def unexplained(self):
        n = 0
        for a, b in self.gaps:
            for x in range(a, b + 1):
                if not any(c <= x <= e for c, e in self.declared):
                    n += 1
        return n

    def summary(self):
        return dict(spec=self.n[P.T_SPEC], tp=self.n[P.T_TP], event=self.n[P.T_EVENT], mb=round(self.bytes / 2**20, 1),
                    crc_bad=self.crc_bad, gaps=sum(b - a + 1 for a, b in self.gaps), declared=sum(b - a + 1 for a, b in self.declared),
                    unexplained=self.unexplained(), seq_back=self.seq_back, dup=self.dup, kgap=self.kgap, tdev=self.tdev, tp_gap=self.tp_gap,
                    health=f"{self.h_or:#x}", sat=self.sat, flags=f"{self.flags_or:#x}", last_seq=self.last_seq)


def read_exact(src, n, buf):
    mv = memoryview(buf)[:n]
    got = 0
    while got < n:
        k = src(mv[got:])
        if k == 0:
            raise EOFError
        got += k
    return mv


def run(src, chk, out, seconds, report, ready=None, ack=None):
    hb = bytearray(P.HDR.size)
    pb = bytearray(1 << 20)
    t0 = time.time()
    t_rep = t0 + report
    t_ack = t0
    while True:
        if ack is not None and chk.last_seq and time.time() > t_ack:
            if out:
                out.flush()
            ack(chk.last_seq)                                 # 書き終えた最後の seq を返す（サーバーはそこまでを溜まりから消す）
            t_ack = time.time() + 0.2
        if seconds and time.time() - t0 > seconds:
            break
        if ready is not None and not ready(0.5):           # 記録の頭の手前でだけ待つ（記録の途中では待たない）
            continue
        try:
            h = read_exact(src, P.HDR.size, hb)
        except EOFError:
            break
        rtype, plen, crc, seq = P.parse_header(h)
        if plen > len(pb):
            pb = bytearray(plen)
        pl = read_exact(src, plen, pb)
        if seq and chk.last_seq is not None and seq <= chk.last_seq:
            chk.dup += 1                                      # 送り直された記録（前の接続で受けたが ACK が間に合わなかった）
            continue
        if out:
            out.write(h); out.write(pl)
        chk.record(rtype, crc, seq, bytes(pl) if rtype != P.T_SPEC else pl)
        if report and time.time() > t_rep:
            t_rep += report
            print(f"  {time.time() - t0:7.0f} s: {json.dumps(chk.summary(), ensure_ascii=False)}", flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=51001)
    p.add_argument("--file", default=None, help="ソケットの代わりに、書いたファイルを読む")
    p.add_argument("--out", default=None)
    p.add_argument("--seconds", type=float, default=0, help="この秒数で止める（0 = 切れるまで）")
    p.add_argument("--report", type=float, default=60.0)
    p.add_argument("--json", default=None, help="最後のまとめを JSON で書く（試験の台本用）")
    p.add_argument("--rcvbuf", type=int, default=4 << 20)
    a = p.parse_args()
    chk = Check()
    out = open(a.out, "ab") if a.out else None
    if a.file:
        f = open(a.file, "rb")
        run(f.readinto, chk, out, 0, 0)
    else:
        s = socket.create_connection((a.host, a.port))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, a.rcvbuf)
        s.settimeout(30.0)
        run(s.recv_into, chk, out, a.seconds, a.report, ready=lambda t: bool(select.select([s], [], [], t)[0]),
            ack=lambda q: s.sendall(q.to_bytes(8, "little")))
        if chk.last_seq:
            if out:
                out.flush()
            s.sendall(chk.last_seq.to_bytes(8, "little"))
            time.sleep(0.1)
        s.close()
    if out:
        out.close()
    sm = chk.summary()
    print("まとめ: " + json.dumps(sm, ensure_ascii=False), flush=True)
    if a.json:
        json.dump(dict(summary=sm, events=chk.events), open(a.json, "w"), ensure_ascii=False, indent=1)
    ok = sm["crc_bad"] == 0 and sm["unexplained"] == 0 and sm["kgap"] == 0 and sm["tdev"] == 0 and sm["tp_gap"] == 0
    print(f"照合: {'通過' if ok else '失敗'}", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
