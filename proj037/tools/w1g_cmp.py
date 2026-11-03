#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 W-1g — ノイズを入れ直してからの巡ごとに、RAW の形と水準を、巡 0（切る前）と Y-4 の P-on に比べる（runs/ のある所で、README W-1g）

  python3 w1g_cmp.py

巡ごとの格子は w1e_cmp.grid（RAW 48 本）。d_lo は w1f_cmp.d_lo（1 GHz より下の 128 MHz ごとの平均の rms）。
水準 = 比（dB）の 50〜2000 MHz の中央値（ノイズの強さの変化）。電源の電流は runs/w1g_env.txt から。
対照: 巡 0 / W-1f の巡 12（同じ温まった状態どうし）。
"""
import re

import numpy as np

from w1e_cmp import grid
from w1f_cmp import M, d_lo


def lvl(a, b):
    return float(np.median(10 * np.log10(a[M] / b[M])))


def main():
    env = {}
    for s in open("runs/w1g_env.txt"):
        w = s.split()
        if w[0].isdigit():
            ma = re.search(r"([0-9.]+) mA）", s)
            env[int(w[0])] = (w[1], w[2], w[4], ma.group(1) + " mA" if ma else "?")
    z = np.load("runs/y4_grid.npz")
    Pp = z["P_pon"]
    P0 = grid([f"runs/w1g_0_{i}" for i in (1, 2, 3, 4)])[0]
    Pf = grid([f"runs/w1f_12_{i}" for i in range(1, 12)])[0]
    print(f"対照 巡 0 / W-1f 巡 12: d_lo {d_lo(P0, Pf):.3f} dB・水準 {lvl(P0, Pf):+.3f} dB")
    print(f"巡 0 / Y-4 P-on: d_lo {d_lo(P0, Pp):.3f} dB")
    print("巡: 入れてから s・時刻・PL ℃・電流 / 対 巡 0 の d_lo・水準 / 対 Y-4 の d_lo")
    G = {}
    for r in sorted(env):
        if r == 0:
            continue
        try:
            P = grid([f"runs/w1g_{r}_{i}" for i in (1, 2, 3, 4)])[0]
        except OSError:
            break
        G[r] = P
        t, hm, pl, ma = env[r]
        print(f"{r:2d}: {t:>5s} s・{hm}・{pl}・{ma} / {d_lo(P, P0):.3f} dB・{lvl(P, P0):+.3f} dB / {d_lo(P, Pp):.3f} dB")
    np.savez("runs/w1g_grid.npz", P_0=P0, **{f"P_{r}": P for r, P in G.items()})


if __name__ == "__main__":
    main()
