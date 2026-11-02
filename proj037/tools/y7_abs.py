#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-7 — CW の利得の比を荒い ch で割らずに dB で並べ、64 MHz の境をなめらかにまたぐかを見る（ボードの上で、runs/y7_cmp.json から）

  python3 y7_abs.py
"""
import json, numpy as np
R = json.load(open("runs/y7_cmp.json"))
f = np.array([o["f"] for o in R["pon1"]])
P = {t: np.array([o["p"] for o in R[t]]) for t in R}
db = lambda x: 10 * np.log10(x)
pon = (P["pon1"] + P["pon2"]) / 2
for s in ("pa", "a1"):
    g = db((P[s + "1"] + P[s + "2"]) / 2 / pon)
    for k in (7, 8, 23, 24):
        sel = (f // 64).astype(int) == k
        print(f"{s}/pon ch {k:2d} dB: " + " ".join(f"{v:+.2f}" for v in g[sel]))
print("pon1 の CW の電力（dB、ch 7・8・23・24、中央値に対して）")
for k in (7, 8, 23, 24):
    sel = (f // 64).astype(int) == k
    print(f"  ch {k:2d}: " + " ".join(f"{v:+.2f}" for v in db(P['pon1'][sel] / np.median(P['pon1']))))
    print(f"  a11 ch {k:2d}: " + " ".join(f"{v:+.2f}" for v in db(P['a11'][sel] / np.median(P['pon1']))))
