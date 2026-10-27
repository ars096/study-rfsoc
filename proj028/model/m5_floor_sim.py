#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-5f の切り分け: 荒い段の bit 単位の模型（coarse_pfb_ref → cfft32_ref → ymap）に白い雑音 σx を入れ、Y を保存する
  python3 model/m5_floor_sim.py <σx> <ブロック数> <種> <出力.npy>   （OFF 相当 σx 4.9 → g ≒ 6 万、ON 相当 145 → g ≒ 2080）
"""
import os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from coarse_pfb_ref import zblocks
from cfft32_ref import cfft32
from coarse_post_ref import ymap
sx = float(sys.argv[1]); nblk = int(sys.argv[2])
rng = np.random.default_rng(int(sys.argv[3]) if len(sys.argv) > 3 else 1)
x = np.clip(np.round(rng.normal(0, sx, 56 * nblk + 2000)), -8192, 8191).astype(np.int64)
t = time.time(); z = zblocks(x, nblk); fr, fi = cfft32(z); yr, yi = ymap(fr, fi)
Y = (yr + 1j * yi)[30:]                                 # 頭の立ち上がりを捨てる
sY = np.sqrt((np.abs(Y) ** 2).mean(0) / 2)
g = np.minimum(np.round(12 * 65536 / sY), 131071)
print(f"σx {sx}: σY {sY.min():.2f}〜{sY.max():.2f}・g {g.min():.0f}〜{g.max():.0f}（{time.time()-t:.0f} s）", file=sys.stderr)
np.save(sys.argv[4], dict(Y=Y, g=g), allow_pickle=True)
