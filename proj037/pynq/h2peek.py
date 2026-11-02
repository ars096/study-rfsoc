#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj023 H-2 の切り分け: wide.py --tone-ch の npz の各流れで、CW が乗っているかを見る（ボードで: python3 h2peek.py h2b1.wide.npz 1234）
各流れ・各相（center・edge）について、最大の ch・その IF・最大 / 中央値 [dB]・ch i の電力 / 中央値 [dB] を出す。
CW が届いていれば、どこかの流れで最大 / 中央値が 30 dB を越えるはず。雑音だけなら数 dB"""
import json
import sys
import numpy as np

path, i = sys.argv[1], int(sys.argv[2])
z = np.load(path)
meta = json.loads(str(z["meta"]))
print("tone:", meta.get("tone"))
for k in sorted(x[:-5] for x in z.files if x.endswith("_spec")):
    p = z[k + "_spec"].astype(float)
    f = z[k + "_if_mhz"]
    med = np.median(p)
    m = int(np.argmax(p))
    print(f"{k:12s} 最大 ch {m:4d}（IF {f[m]:9.4f}）最大/中央値 {10*np.log10(p[m]/med):6.1f} dB / ch {i}（IF {f[i]:9.4f}）/中央値 {10*np.log10(max(p[i],1e-30)/med):6.1f} dB")
