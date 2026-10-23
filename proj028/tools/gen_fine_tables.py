#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F — 細かい側の ROM の中身を書く（model/fine_fixed.py から）。
  src/fine/fine_coef_lo.hex・fine_coef_hi.hex: 係数の表（前半 s = 0..2047・後半 s = 2048..4095）、1 行 = {S 13 bit, V 23 bit}（36 bit）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "model"))
import fine_fixed as F  # noqa: E402

V, S = F.coef_tables()
half = F.NSEG // 2
for name, rng in (("lo", range(0, half)), ("hi", range(half, F.NSEG))):
    with open(os.path.join("src", "fine", "fine_coef_%s.hex" % name), "w") as f:
        for s in rng:
            w = ((int(S[s]) & ((1 << F.SW) - 1)) << F.VW) | (int(V[s]) & ((1 << F.VW) - 1))
            f.write("%09x\n" % w)
print("wrote src/fine/fine_coef_lo.hex・fine_coef_hi.hex（各 %d 行 × %d bit）" % (half, F.VW + F.SW))

# ひねり係数の表（fine_tw）: A（64 行）・B（128 行）、各 576 bit = 16 レーン × {im 18, re 18}
Ar, Ai, Br, Bi = F.tw_tables()
for name, (Xr, Xi) in (("a", (Ar, Ai)), ("b", (Br, Bi))):
    with open(os.path.join("src", "fine", "fine_tw_%s.hex" % name), "w") as f:
        for r in range(Xr.shape[1]):
            v = 0
            for p in range(16):
                v |= (((int(Xi[p, r]) & 0x3FFFF) << 18) | (int(Xr[p, r]) & 0x3FFFF)) << (36 * p)
            f.write("%0144x\n" % v)
print("wrote src/fine/fine_tw_a.hex（%d 行）・fine_tw_b.hex（%d 行）" % (Ar.shape[1], Br.shape[1]))
