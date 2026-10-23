#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 C-2 — coarse_post の整数の模型（RTL と bit 単位で同じ）。

  Y_{2m} = F_m（m < 16）、Y_{2m+1} = conj(F_{31−m})
  y = clip((Y·g + 2^15) >> 16, −127, 127)（成分ごと、>> は床の算術シフト）。飽和の数えは |·| > 127 の成分の数
"""
import numpy as np


def ymap(fr, fi):
    nb = fr.shape[0]
    yr = np.empty((nb, 32), np.int64)
    yi = np.empty((nb, 32), np.int64)
    for k in range(32):
        m = k // 2 if k % 2 == 0 else 31 - (k - 1) // 2
        yr[:, k] = fr[:, m]
        yi[:, k] = fi[:, m] if k % 2 == 0 else -fi[:, m]
    return yr, yi


def post(fr, fi, gains):
    yr, yi = ymap(fr, fi)
    g = np.asarray(gains, np.int64)[None, :]
    rr = (yr * g + (1 << 15)) >> 16
    ri = (yi * g + (1 << 15)) >> 16
    clip = (np.abs(rr) > 127).astype(np.int64) + (np.abs(ri) > 127).astype(np.int64)
    return np.clip(rr, -127, 127), np.clip(ri, -127, 127), clip, yr, yi
