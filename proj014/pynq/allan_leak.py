#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj014 — W-9 の後処理: (f)・(c) の長い τ の床が「入力の帯域の形の揺らぎ (e) の漏れ」かどうかを見る（ボードは要らない）。

  python3 allan_leak.py allan256_1h.allan.npz [--bin 100]

2 つの分光計は周波数の重み（通過域のリップル・ch の形・端の ch）が少し違うので、入力の帯域の傾きが大きく揺らぐと、
(d) / (e) で消し切れずに一部が残る: log f ≒ ε · log e。ε を、--bin 個ずつ平均した時系列（白色雑音を落とし、ゆっくりした揺らぎで決める）
の最小二乗で出し、f / e^ε のアラン分散と比べる。**漏れなら床が下がる**（下がらなければ窓の分光計そのものの揺らぎ）。
(c) 窓 / 全帯域 も同じく (e) への回帰を見る。
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from winallan import allan  # noqa: E402


def fit(y, x, nb):
    """log y = ε · log x + 定数 を、nb 個ずつ平均した系列で最小二乗。"""
    n = len(y) // nb * nb
    ly = np.log(y[:n]).reshape(-1, nb).mean(axis=1); lx = np.log(x[:n]).reshape(-1, nb).mean(axis=1)
    ly -= ly.mean(); lx -= lx.mean()
    eps = float(np.dot(lx, ly) / np.dot(lx, lx))
    r = float(np.corrcoef(lx, ly)[0, 1])
    return eps, r


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("npz")
    p.add_argument("--bin", type=int, default=100, help="回帰に使う平均の個数（τ0 = 0.1 s なら 100 = 10 s）")
    a = p.parse_args()
    z = np.load(a.npz)
    tau0 = float(z["tau0"])
    d = z["sa"] / z["sb"]; e = z["fa"] / z["fb"]; c = z["win"] / z["full"]
    d, e, c = d / d.mean(), e / e.mean(), c / c.mean()
    f = d / e
    ef, rf = fit(f, e, a.bin)
    ec, rc = fit(c, e, a.bin)
    f2 = f / e ** ef; c2 = c / e ** ec
    nmax = len(f) // 4
    ns = np.unique(np.round(np.logspace(0, np.log10(max(nmax, 1)), 16)).astype(int))
    av = {k: allan(v / v.mean(), ns) for k, v in (("(e)", e), ("(f)", f), ("(f)/e^ε", f2), ("(c)", c), ("(c)/e^ε", c2))}
    print(f"{a.npz}: ダンプ {len(f)}（τ0 {tau0} s）・回帰の平均 {a.bin} 個（{a.bin * tau0:g} s）")
    print(f"  (f) の (e) への漏れ ε = {ef:+.4f}（相関 {rf:+.3f}）/ (c) の (e) への漏れ ε = {ec:+.4f}（相関 {rc:+.3f}）")
    print("τ [s]    " + "".join(f"{k:>12s}" for k in av))
    for i, n in enumerate(ns):
        print(f"{n * tau0:7.1f}  " + "".join(f"{np.sqrt(av[k][i]):12.3e}" for k in av))
    lg = ns * tau0 >= 100
    if lg.any():
        for k0, k1 in (("(f)", "(f)/e^ε"), ("(c)", "(c)/e^ε")):
            r = np.sqrt(np.nanmean(av[k1][lg] / av[k0][lg]))
            print(f"  τ ≧ 100 s で {k1} / {k0}（アラン偏差の比の見当）: {r:.2f}（1 より十分小さければ、床は (e) の漏れ）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
