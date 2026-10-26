#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 C-1 — coarse_pfb を iverilog で回し、model/coarse_pfb_ref.py と bit 単位で比べる。

  python3 tools/sim_coarse_pfb.py [--bad] [--gap]
  ふつう: ブロック m ≧ 30（履歴が満ちた後）で違う数 0 → 「結果: 全部通過」
  --bad（陽性対照: 係数 g[100] の符号が逆の RTL）: 違いが出る → 「結果: 不合格（陽性対照として正しく落ちた）」
  --gap: 入力の valid を時々落とす（拍の数えとブロックの位相が valid の拍だけで進むか）
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, "model")
from coarse_pfb_ref import zblocks  # noqa: E402

bad = "--bad" in sys.argv
gap = "--gap" in sys.argv
tag = ("bad" if bad else "ok") + ("_gap" if gap else "")
od = "build-sim"
os.makedirs(od, exist_ok=True)
rtl = "src/coarse_pfb.v"
if bad:
    rtl = os.path.join(od, "coarse_pfb_bad.v")
    subprocess.run([sys.executable, "tools/gen_coarse_pfb.py", "--bad", "--out", rtl], check=True)
NB = 7 * 60                                            # 60 × 7 拍 = 120 ブロック
rng = np.random.default_rng(11)
lim = (1 << 13) - 1
x = np.round(rng.standard_normal(16 * NB) * 1031).astype(np.int64)
x[16 * 120: 16 * 130] = lim                            # 満杯の区間（LESSONS: ±最大値を入れる）
x[16 * 130: 16 * 140] = -lim
x = np.clip(x, -lim, lim)
inhex = os.path.abspath(os.path.join(od, "cpfb_in_%s.hex" % tag))
outtxt = os.path.abspath(os.path.join(od, "cpfb_out_%s.txt" % tag))
with open(inhex, "w") as f:
    for b in range(NB):
        v = 0
        for p in range(16):
            v |= ((int(x[16 * b + p]) << 2) & 0xFFFF) << (16 * p)
        f.write("%064x\n" % v)
vvp = os.path.join(od, "tb_cpfb_%s.vvp" % tag)
cmd = ["iverilog", "-g2012", "-o", vvp, "-DNBEAT=%d" % NB, '-DIN_HEX="%s"' % inhex, '-DOUT_TXT="%s"' % outtxt]
if gap:
    cmd.append("-DGAP")
subprocess.run(cmd + ["tb/tb_coarse_pfb.v", rtl], check=True)
p = subprocess.run(["vvp", "-n", vvp], check=True, capture_output=True, text=True)
print(p.stdout.strip().splitlines()[-1])
# 履歴が満ちる前のブロックは x（不定）を含む → 目印の値に
got = np.array([[int(t) if t.lstrip("-").isdigit() else -(1 << 40) for t in ln.split()] for ln in open(outtxt) if ln.strip()], np.int64)
nx = np.sum(got == -(1 << 40), axis=1)
print("x を含むブロック: %s" % (np.nonzero(nx)[0].tolist() if nx.any() else "なし"))
nblk = NB * 16 // 56
ref = zblocks(x, nblk)
n = min(len(got), nblk)
m0 = 30
diff = np.sum(got[m0:n] != ref[m0:n])
print("coarse_pfb（%s）: ブロック %d（期待 %d）、m ≧ %d で違う値 %d / %d、ref の |z| 最大 %d"
      % (tag, len(got), nblk, m0, diff, (n - m0) * 64, np.abs(ref).max()))
okn = len(got) == nblk
if bad:
    print("結果: %s" % ("不合格（陽性対照として正しく落ちた）" if diff > 0 else "全部通過（陽性対照が落ちない: 照合が効いていない）"))
else:
    print("結果: %s" % ("全部通過" if okn and diff == 0 else "不合格"))
