#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 C-1 — 荒い PFB の整数の模型（RTL の coarse_pfb と bit 単位で同じ）。numpy だけ。

  係数 g[n] = (−1)^(n // 64)·hq[n]（n = 0..1727、hq は M-3 の 18 bit の係数）
  ブロック m の最も新しいサンプル t0 = 56m + 55、z_r(m) = sat18((Σ_t g[r + 64t]·x[t0 − r − 64t] + 2^17) >> 18)
  （>> は床への算術シフト。x は 0 番より前を 0 とする）
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from m3_coarse_fixed import coeffs  # noqa: E402

M, TC, D, SH, ZW = 64, 27, 56, 18, 18
L = M * TC


def gtable():
    _, hq, _ = coeffs()
    g = hq.astype(np.int64) * ((-1) ** (np.arange(L) // M))
    return g


def zblocks(x, nblk, g=None):
    if g is None:
        g = gtable()
    x = np.asarray(x, np.int64)
    xp = np.concatenate([np.zeros(L, np.int64), x])
    z = np.empty((nblk, M), np.int64)
    n = np.arange(L)
    lim = 2 ** (ZW - 1) - 1
    for m in range(nblk):
        t0 = 56 * m + 55
        acc = g * xp[L + t0 - n]                         # 積の n 番 = g[n]·x[t0 − n]
        s = acc.reshape(TC, M).sum(axis=0)               # r = n mod 64 ごとに 27 個の和
        z[m] = np.clip((s + (1 << (SH - 1))) >> SH, -lim, lim)
    return z
