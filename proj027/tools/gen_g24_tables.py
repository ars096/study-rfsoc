#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj025 — 2G-2 の ROM の中身（PFB の係数の補間の表・ひねり係数の 2 つの表）を生成し、読み返して模型と照らす。

    python3 tools/gen_g24_tables.py [出力先（既定 build-gen/）]

値は model/g24_fixed.py の定義そのもの。**手で直さない**。proj024 の gen_g21_tables.py を写し、長さを 2G-2 に。生成物は src/g24/ に写してコミットする。
  g24_coef_lo.hex・g24_coef_hi.hex: 各 2048 行 × 36 bit = {S[13], V[23]}（V が [0 +: 23]、S が [23 +: 13]、2 の補数）。
      lo は区間 s = 0..2047（タップ t 0・3 が引く）、hi は s = 2048..4095（t 1・2 が引く）。番地は s − 2048·(hi)
  g24_tw_a.hex: 64 行 × 576 bit、g24_tw_b.hex: 128 行 × 576 bit。レーン p が [36p +: 36] = {im[18], re[18]}（Wide の wide_tw.hex と同じ並び）。
      A の行 = hi（k1 >> 7）、B の行 = lo（k1 & 127）
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import g24_fixed as F  # noqa: E402

VW, SW = 23, 13


def tc(v, w):
    assert -(1 << (w - 1)) <= v < (1 << (w - 1)), (v, w)
    return v & ((1 << w) - 1)


def sx(v, w):
    return v - (1 << w) if v >> (w - 1) else v


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "build-gen")
    os.makedirs(out, exist_ok=True)
    V, S = F.coef_tables()
    H = F.NSEG // 2
    assert len(V) == 4096
    for name, rng in (("lo", range(0, H)), ("hi", range(H, 2 * H))):
        with open(os.path.join(out, f"g24_coef_{name}.hex"), "w") as fo:
            for s in rng:
                fo.write("%09x\n" % ((tc(int(S[s]), SW) << VW) | tc(int(V[s]), VW)))
    Ar, Ai, Br, Bi = F.tw_tables()
    for name, (re, im) in (("a", (Ar, Ai)), ("b", (Br, Bi))):
        with open(os.path.join(out, f"g24_tw_{name}.hex"), "w") as fo:
            for r in range(re.shape[1]):
                word = 0
                for p in range(F.LANES):
                    word |= ((tc(int(im[p, r]), 18) << 18) | tc(int(re[p, r]), 18)) << (36 * p)
                fo.write("%0144x\n" % word)

    # ---- 読み返して模型と照らす ----
    rd = lambda n: [int(l, 16) for l in open(os.path.join(out, n))]
    words = rd("g24_coef_lo.hex") + rd("g24_coef_hi.hex")
    V2 = np.array([sx(w & ((1 << VW) - 1), VW) for w in words], dtype=np.int64)
    S2 = np.array([sx(w >> VW, SW) for w in words], dtype=np.int64)
    ok_c = np.array_equal(F.coef_beat(V2, S2).reshape(-1), F.coef_interp())
    tab = {}
    for name in ("a", "b"):
        ws = rd(f"g24_tw_{name}.hex")
        re = np.array([[sx((w >> (36 * p)) & 0x3FFFF, 18) for w in ws] for p in range(F.LANES)], dtype=np.int64)
        im = np.array([[sx((w >> (36 * p + 18)) & 0x3FFFF, 18) for w in ws] for p in range(F.LANES)], dtype=np.int64)
        tab[name] = (re, im)
    k1 = np.arange(F.M)
    hi, lo = k1 >> 7, k1 & 127
    wr, wi = F.cmul_q(tab["a"][0][:, hi], tab["a"][1][:, hi], tab["b"][0][:, lo], tab["b"][1][:, lo], 16)
    pr, pi = F.tw_prod()
    ok_t = np.array_equal(wr, pr) and np.array_equal(wi, pi)
    print(f"書いた先: {os.path.abspath(out)}")
    print(f"読み返し: 係数（ビートの式で {F.L:,} タップ）{'一致' if ok_c else '不一致'}・ひねり係数（16 × {F.M}）{'一致' if ok_t else '不一致'}")
    sys.exit(0 if ok_c and ok_t else 1)


if __name__ == "__main__":
    main()
