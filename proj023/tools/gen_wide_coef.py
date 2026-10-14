#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj023 — SAM45-Wide の PFB の係数 ROM の中身 src/sam45wide/wide_coef.hex を生成する。

    python3 tools/gen_wide_coef.py > src/sam45wide/wide_coef.hex

1 行 = 番地 m（0..2047）の 1152 bit = 16 レーン × 72 bit（レーン p が [72p +: 72]、レーン 15 が行の左端）。
レーンの 72 bit = 4 タップ × 18 bit（タップ t が [18t +: 18]）= c[t·32768 + 16m + p]。
値は sim/check_wide.py の coef_words()（= model/wide_model.py の原型を 18 bit に量子化したもの）。**手で直さない**。
**生成物もコミットする**（ビルドサーバで Python を走らせないため・係数が変わったことを git の差分で見るため。tools/gen_tw_rom.py と同じ）。

URAM は初期値を持てない（UltraScale+ の URAM288 に INIT は無い）ので、係数は BRAM の ROM（$readmemh）に置く（README 手順 2b）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sim"))
import check_wide as C                                    # noqa: E402

w = C.coef_words()
for m in range(C.M):
    word = 0
    for p in range(C.P):
        word |= int(w[p, m]) << (72 * p)
    sys.stdout.write("%0288x\n" % word)
