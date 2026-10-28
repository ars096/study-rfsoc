#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj036: specrecv の --out のファイルから、窓ごとに SPEC の「中身の平均 / nacc」（1 フレームあたりの電力）の中央値を出す。
tint を変えても同じ値になるはず（束ねが正しく足していれば）。--posctl-noacc（足さずに写す）では 1 / n_sum に落ちる。
  python3 level.py <file.s45> [...]
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pynq"))
import s45proto as P   # noqa: E402


def levels(path):
    by = {}
    with open(path, "rb") as f:
        while True:
            h = f.read(P.HDR.size)
            if len(h) < P.HDR.size:
                break
            rtype, plen, crc, seq = P.parse_header(h)
            pl = f.read(plen)
            if rtype != P.T_SPEC:
                continue
            d = P.decode(rtype, pl, P.header_ver(h))
            x = np.asarray(d["data"], np.float64)
            n = x.size
            v = float(np.mean(x[n // 20: n - n // 20])) / d["nacc"]      # 両端 5 % を除く
            by.setdefault((d["core"], d["n_sum"]), []).append(v)
    return by


def main():
    for path in sys.argv[1:]:
        for (core, n_sum), v in sorted(levels(path).items()):
            a = np.array(v)
            print(f"{os.path.basename(path)}  コア {core}  n_sum {n_sum}  記録 {a.size}  平均/nacc の中央値 {np.median(a):.6g}  （相対 σ {np.std(a) / np.mean(a):.2e}）")


if __name__ == "__main__":
    main()
