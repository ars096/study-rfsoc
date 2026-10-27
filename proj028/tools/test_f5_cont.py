#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""pynq/f5_cont.py の状態の見分け（Runs）を作り物の電力の列で確かめる（ボード無し）
  python3 tools/test_f5_cont.py
本体: ON 6・混ざり 1・OFF 6・混ざり 1・ON 5 → 区間 3 つ（ON・OFF・ON）、混ざり 2 つは捨てる、各区間の頭の 2 つは立ち上がりで捨てる（最初の区間を除く）
陽性対照: --mix-db を 20 dB に緩めると、混ざりのチャンクが区間として残る（区間 5 つ）
"""
import os
import sys
import types

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pynq"))
sys.modules["f5_seg"] = types.ModuleType("f5_seg")   # 実機の部品（pynq）は読まない
import f5_cont as C  # noqa: E402

C.NTOT, C.NKEEP, C.NCH = 4, 1, 4


def run(ps, mix):
    R = C.Runs(types.SimpleNamespace(step_db=3.0, mix_db=mix, settle=2))
    for i, p in enumerate(ps, start=1):
        R.push((i, p, np.full(4, p), np.full(4, 160), np.full(4, p)))
    R.flush()
    return [(r["first"], r["last"], r["n"]) for r in R.runs], [c for c, why in R.dropped if why == "混ざり"]


on, off = 1000.0, 1.0
seq = [on] * 6 + [300.0] + [off] * 6 + [2.0] + [on] * 5
got = run(seq, 0.3)
ok = got == ([(1, 6, 6), (8, 13, 4), (15, 19, 3)], [7, 14])
pc = run(seq, 20.0)
pc_ok = len(pc[0]) == 5
print(f"本体: {got} → {'通過' if ok else '不合格'}")
print(f"陽性対照（mix 20 dB）: 区間 {len(pc[0])} → {'正しく落ちた' if pc_ok else '落ちない（見張りが効いていない）'}")
sys.exit(0 if ok and pc_ok else 1)
