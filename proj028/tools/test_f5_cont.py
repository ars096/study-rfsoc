#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""pynq/f5_cont.py の状態の見分け（Runs）を作り物の電力の列で確かめる（ボード無し）
  python3 tools/test_f5_cont.py
本体: ON 6・混ざり 1・OFF 6・混ざり 1・ON 5 → 区間 3 つ（ON・OFF・ON）、混ざり 2 つは捨てる、各区間の頭の 2 つは立ち上がりで捨てる（最初の区間を除く）
陽性対照: --mix-db を 20 dB に緩めると、混ざりのチャンクが区間として残る（区間 5 つ）
切り替えの形（--switch）: 状態 0 ×5・切り替え 2・状態 1 ×5・切り替え 2・状態 0 ×4（生の電力は利得で揃って同じ）
  → 区間 3 つ（状態 0・1・0）、切り替えの 4 つは捨てる。陽性対照: 状態 1 の中ほどに電力の違う 1 つ（記録から漏れた切り替え）→ 混ざりで捨てる
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
        R.push((i, p, np.full(4, int(p), np.uint64), np.full(4, 160), np.full(4, p), None))
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


def run_l(items):
    R = C.Runs(types.SimpleNamespace(step_db=3.0, mix_db=0.3, settle=2))
    for i, (lab, p) in enumerate(items, start=1):
        R.push((i, p, np.full(4, int(p), np.uint64), np.full(4, 160), np.full(4, p), lab))
    R.flush()
    return [(r["first"], r["last"], r["n"], r["state"]) for r in R.runs], R.dropped


X = "切り替え"
seq_l = [(0, 1000.0)] * 5 + [(X, 900.0)] * 2 + [(1, 1001.0)] * 5 + [(X, 950.0)] * 2 + [(0, 1000.0)] * 4
got_l = run_l(seq_l)
ok_l = got_l == ([(1, 5, 5, 0), (8, 12, 5, 1), (15, 18, 4, 0)], [(6, X), (7, X), (13, X), (14, X)])
bad = list(seq_l)
bad[9] = (1, 300000.0)
got_b = run_l(bad)
pc_l = (10, "混ざり") in got_b[1]
print(f"切り替えの形: {got_l} → {'通過' if ok_l else '不合格'}")
print(f"陽性対照（状態 1 の中に違う電力）: 捨てた {got_b[1]} → {'正しく落ちた' if pc_l else '落ちない'}")
sys.exit(0 if ok and pc_ok and ok_l and pc_l else 1)
