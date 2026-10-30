#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-8 — 荒い段の bit 単位の模型に、実機と同じ振幅・雑音の CW を長く入れ（ブロック 131072 = 刻み 558 Hz）、f ± k·FO の線の高さを見る
  python3 model/m8_cw_long.py <振幅> <σ> <種> [ブロック数]"""
import sys, time; import numpy as np
sys.path.insert(0, "model")
from coarse_pfb_ref import zblocks
from cfft32_ref import cfft32
from coarse_post_ref import ymap
FS = 4.096e9; FO = FS / 56; F = 1151.999442e6
A, sx, seed = float(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3]); nb = int(sys.argv[4]) if len(sys.argv) > 4 else 131072
rng = np.random.default_rng(seed); t0 = time.time()
ph = rng.uniform(0, 2 * np.pi)
t = np.arange(56 * (nb + 64))
x = np.clip(np.round(A * np.cos(2 * np.pi * F / FS * t + ph) + rng.normal(0, sx, len(t))), -8192, 8191).astype(np.int64)
fr, fi = cfft32(zblocks(x, nb + 32)); yr, yi = ymap(fr, fi)
Y = (yr + 1j * yi)[32:]
del x
n = Y.shape[0]; t_ = 2 * np.pi * np.arange(n) / n
w = 0.35875 - 0.48829 * np.cos(t_) + 0.14128 * np.cos(2 * t_) - 0.01168 * np.cos(3 * t_)
P = np.abs(np.fft.fft(Y * w[:, None], axis=0)) ** 2
nu = (F - 17 * FO + FO / 2) % FO - FO / 2; b = int(round(nu / (FO / n))) % n
lv = lambda c: P[[(b + d) % n for d in range(-4, 5)], c].sum()
pt = lv(17); row = []
for c in range(32):
    u = (F - 64e6 * c) % FO; k = int(round((64e6 * c + u - F) / FO))
    if u < 64e6 and c not in (17, 18) and abs(k) <= 8:
        row.append((k, 10 * np.log10(lv(c) / pt), 10 * np.log10(lv(c) / (np.median(P[:, c]) * 9))))
print(f"A {A}・σ {sx}・ブロック {n}（刻み {FO/n:.0f} Hz）・{time.time()-t0:.0f} s")
print("  " + " ".join(f"k{k:+d}:{d:+.1f}({e:+.0f})" for k, d, e in sorted(row)))
