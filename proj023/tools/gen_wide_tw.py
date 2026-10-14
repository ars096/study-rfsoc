#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj023 — SAM45-Wide のひねり係数 ROM の中身 src/sam45wide/wide_tw.hex を生成する。

    python3 tools/gen_wide_tw.py > src/sam45wide/wide_tw.hex

1 行 = 番地 k1（0..2047）の 576 bit = 16 レーン × 36 bit（レーン p が [36p +: 36]）。レーンの 36 bit = {im[17:0], re[17:0]}（tw_rom と同じ並び）。
値は W_32768^(p·k1) = round(2^16·cos(2πpk1/32768)), round(−2^16·sin(…))。sim/check_wide.py の TWR・TWI と**同じ式**（_tw）。**手で直さない**。
生成物もコミットする（tools/gen_wide_coef.py と同じ）。4 ADC で 1 つ（wide_tw_rom、番地 k1 は 4 ADC で同じ。README D-6・D-7）。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sim"))
import check_wide as C                                    # noqa: E402

for k1 in range(C.M):
    word = 0
    for p in range(C.P):
        wr, wi = int(C.TWR[p, k1]), int(C.TWI[p, k1])
        word |= (((wi & 0x3FFFF) << 18) | (wr & 0x3FFFF)) << (36 * p)
    sys.stdout.write("%0144x\n" % word)
