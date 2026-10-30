#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 T-4 — 2G-1-Fine の D_eff（ダンプの矩形の中心と、入力のサンプルがダンプの電力に効く重みの重心との差）

  python3 model/t4_deff.py [N_f ...]      既定は 256 と 1024（予言の式は N_f に依らない形）

  重み w(t) = Σ_b W_f(b)·g²[56b + 55 − t]
    g: 荒い PFB の係数（gtable、1728 個。ブロック b は最も新しいサンプル 56b + 55 から g[j] を掛ける）
    W_f(b) = Σ_{f=0}^{K-1} h²[(f + 1)·N_f − 1 − b]（細かい PFB の窓 h = design(N_f)、4·N_f 個。範囲の外は 0）
  ブロック b はチャンクの頭を 0 とした番号（前のチャンクの末尾 3 フレームは b < 0）。サンプル t もチャンクの頭が 0
  予言（README の T-4）: 重心 − 矩形の中心 = −(1.5·N_f·56 + 836) サンプル
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from coarse_pfb_ref import gtable  # noqa: E402
from m4_stitch import design  # noqa: E402

K = 6


def shift(nf, asym=False):
    g2 = gtable().astype(np.float64) ** 2
    h = design(nf)
    if asym:
        h = h.copy()
        h[: len(h) // 2] *= 2.0                       # 陽性対照: 対称でない窓
    h2 = h ** 2
    b0 = -3 * nf                                       # 最も古いブロック
    nb = (K + 3) * nf
    W = np.zeros(nb)
    for f in range(K):
        newest = (f + 1) * nf - 1
        n = np.arange(4 * nf)
        W[newest - n - b0] += h2[n]
    # u[s] = W(b) を s = 56b + 55 に置く（s はチャンクの頭からのサンプル、s0 だけずらして非負に）
    s0 = 56 * b0
    u = np.zeros(56 * nb)
    u[56 * np.arange(nb) + 55] = W
    # w(t) = Σ_s u[s]·g2[s − t]（t = s − j、j = 0..1727）
    w = np.convolve(u, g2[::-1])                        # 添字 i ↔ t = s0 + i − 1727
    t = s0 + np.arange(len(w)) - (len(g2) - 1)
    cen = np.sum(t * w) / np.sum(w)
    rect = (56 * K * nf - 1) / 2.0
    return cen - rect


def main():
    nfs = [int(a) for a in sys.argv[1:]] or [256, 1024]
    ok = True
    for nf in nfs:
        pred = -(1.5 * nf * 56 + 836)
        d = shift(nf)
        e = d - pred
        bad = shift(nf, asym=True) - pred
        print(f"N_f {nf}: 重心 − 矩形の中心 = {d:+.4f} サンプル（予言 {pred:+.1f}、差 {e:+.2e}）／陽性対照（対称でない窓）の差 {bad:+.1f}")
        ok = ok and abs(e) < 1e-6 and abs(bad) > 1.0
    nf = 131072
    deff = 1.5 * nf * 56 + 836
    print(f"N_f 131072 の D_eff = {deff:.0f} サンプル = {deff / 16:.2f} ビート = {deff / 4.096:.1f} ns")
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
