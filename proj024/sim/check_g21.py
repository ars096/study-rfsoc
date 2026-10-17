#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj024 — 2G-1 の部品の sim の判定（model/g21_fixed.py の定義と bit 単位で比べる）。

    python3 sim/check_g21.py coef <sim の出力ディレクトリ> [tb のログ]
成否は最後の「結果:」の行で読む（make の成功を信用しない）。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import g21_fixed as F  # noqa: E402


def sx(v, w):
    return v - (1 << w) if v >> (w - 1) else v


def coef(outdir, tblog=None):
    V, S = F.coef_tables()
    ref = F.coef_beat(V, S)                       # [t, m, p]
    seen = {}
    nbad = nline = 0
    first = None
    for line in open(os.path.join(outdir, "coef.txt")):
        ms, hx = line.split()
        m = int(ms)
        w = int(hx, 16)
        got = np.array([[sx((w >> (72 * p + 18 * t)) & 0x3FFFF, 18) for p in range(16)] for t in range(4)])
        d = got != ref[:, m, :]
        if d.any():
            nbad += 1
            if first is None:
                t, p = np.argwhere(d)[0]
                first = (m, t, p, int(got[t, p]), int(ref[t, m, p]))
        seen[m] = seen.get(m, 0) + 1
        nline += 1
    cover = len(seen) == F.M
    print(f"check coef: {nline} 行・m の種類 {len(seen)} / {F.M}・模型と違う行 {nbad}"
          + (f"（最初: m {first[0]}・t {first[1]}・p {first[2]}: RTL {first[3]} / 模型 {first[4]}）" if first else ""))
    tb_ok = True
    if tblog:
        tb_ok = "tb: 口の振る舞い OK" in open(tblog, encoding="utf-8", errors="replace").read()
        print(f"check coef: tb の口の振る舞い {'OK' if tb_ok else 'NG'}")
    ok = nbad == 0 and cover and tb_ok
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "coef":
        sys.exit(0 if coef(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None) else 1)
    sys.exit(2)
