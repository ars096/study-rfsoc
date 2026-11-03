#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 W-1f — 巡ごとの RAW の形を W-1e と Y-4 の P-on に比べる（runs/ のある所で、README W-1f）

  python3 w1f_cmp.py [巡の数 12]

巡ごとの 2 MHz の格子は w1e_cmp.grid（RAW 132 本）。物差しは 2 つ:
  d_lo: 比（dB、50〜2000 MHz の中央値を 0）の 128 MHz ごとの平均を、50〜1024 MHz の 8 区間で rms（1 GHz より下の広いうねり）
  尺: W-1d の尺（y8_ripple.shape）を床を引いて
対照: W-1e の 11 回を奇数回・偶数回に分けた 2 つの d_lo（取り直しの揺れ）と、W-1e / Y-4 の P-on（陽性対照、昨日との違い）
"""
import sys

import numpy as np

import y8_ripple as y8
from w1e_cmp import grid

F = np.arange(1025) * 2.0
M = (F >= 50) & (F <= 2000)
BANDS = [(F >= max(lo, 50)) & (F < lo + 128) for lo in range(0, 1024, 128)]


def d_lo(a, b):
    r = 10 * np.log10(a / b)
    r = r - np.median(r[M])
    return float(np.sqrt(np.mean([r[s].mean() ** 2 for s in BANDS])))


def sub(a, b, fa, fb):
    x = y8.shape(a, b)
    return np.sqrt(max(x ** 2 - fa ** 2 - fb ** 2, 0))


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    e = np.load("runs/w1e_grid.npz")
    Pe, fe = e["P_e"], float(e["fl_e"])
    z = np.load("runs/y4_grid.npz")
    Pp, fp = z["P_pon"], float(z["fl_pon"])
    Po, fo, _ = grid([f"runs/w1e_{i}" for i in range(1, 12, 2)])
    Pv, fv, _ = grid([f"runs/w1e_{i}" for i in range(2, 12, 2)])
    print(f"対照 W-1e 奇数回 / 偶数回: d_lo {d_lo(Po, Pv):.3f} dB・尺（床を引いて）{sub(Po, Pv, fo, fv):.4f}")
    print(f"陽性対照 W-1e / Y-4 P-on: d_lo {d_lo(Pe, Pp):.3f} dB・尺 {sub(Pe, Pp, fe, fp):.4f}")
    env = {}
    try:
        for s in open("runs/w1f_env.txt"):
            w = s.split()
            env[int(w[0])] = f"{w[1]}・PL {w[3]} ℃・PS {w[5]} ℃"
    except OSError:
        pass
    print("巡: 対 W-1e の d_lo・尺 / 対 Y-4 P-on の d_lo・尺 / 時刻・温度")
    G = {}
    for r in range(1, n + 1):
        try:
            P, fl, ns = grid([f"runs/w1f_{r}_{i}" for i in range(1, 12)])
        except OSError:
            break
        G[r] = P
        print(f"{r:2d}: {d_lo(P, Pe):.3f} dB・{sub(P, Pe, fl, fe):.4f} / {d_lo(P, Pp):.3f} dB・{sub(P, Pp, fl, fp):.4f}"
              f"（SNAP {ns}・床 {fl:.4f}）  {env.get(r, '')}")
    np.savez("runs/w1f_grid.npz", **{f"P_{r}": P for r, P in G.items()})


if __name__ == "__main__":
    main()
