#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-3 — fine_acc ＋ fine_rdo を iverilog で回し、出口（頭 ＋ 114,688 語 × 2）を Python の和と並べ替えと比べる。

  python3 tools/sim_fine_acc.py [--first-err] [--k2-err]
  ch A（k 5、面 0）: 積む 3 フレーム（1 フレーム目は first）＋ 積まないフレーム 1。ch B（k 12、面 1）: 同じ
  --first-err（-DACC_FIRST_ERR）・--k2-err（-DRDO_K2_ERR）は陽性対照
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, "model")
import fine_fixed as F  # noqa: E402

ferr = "--first-err" in sys.argv
kerr = "--k2-err" in sys.argv
tag = "ok" + ("_first" if ferr else "") + ("_k2" if kerr else "")
od = "build-sim"
os.makedirs(od, exist_ok=True)
KA, KB = 5, 12
rng = np.random.default_rng(41)
k1o = F.bitrev(np.arange(F.M), 13)
inhex = os.path.abspath(os.path.join(od, "facc_in_%s.hex" % tag))   # 変種ごとに分ける（make sim-facc は 3 本を同時に回す。同じ名前だと書きかけを読んで不定になった。F-5a）
outtxt = os.path.abspath(os.path.join(od, "facc_out_%s.txt" % tag))
lines = []
sums = {}
for ch, (k, pl) in enumerate(((KA, 0), (KB, 1))):
    acc = np.zeros((16, F.M), dtype=np.int64)
    # 前の面の残りを作るため、ch B の面 1 は最初に積まないフレームで汚さない（first で消えることは A で見る）
    for fr, (act, first) in enumerate(((1, 1), (1, 0), (0, 0), (1, 0))):
        P = rng.integers(0, 1 << 35, size=(16, F.M), dtype=np.int64)
        if act:
            acc = P.copy() if first else acc + P
        for k1 in k1o:
            v = (pl << (16 * 37 + 15)) | (first << (16 * 37 + 14)) | (act << (16 * 37 + 13)) | (int(k1) << (16 * 37))
            for b in range(16):
                v |= int(P[b, k1]) << (37 * b)
            lines.append(v)
    sums[k] = acc
with open(inhex, "w") as f:
    for v in lines:
        f.write("%x\n" % v)
NA = len(lines) // 2
vvp = os.path.join(od, "tb_facc_%s.vvp" % tag)
cmd = ["iverilog", "-g2012", "-o", vvp, "-DNBEAT=%d" % len(lines), "-DNA=%d" % NA, "-DKA=%d" % KA, "-DKB=%d" % KB,
       '-DIN_HEX="%s"' % inhex, '-DOUT_TXT="%s"' % outtxt]
if ferr:
    cmd.append("-DACC_FIRST_ERR")
if kerr:
    cmd.append("-DRDO_K2_ERR")
subprocess.run(cmd + ["tb/tb_fine_acc.v", "src/fine/fine_acc.v", "src/fine/fine_rdo.v"], check=True)
p = subprocess.run(["vvp", "-n", vvp], check=True, capture_output=True, text=True)
print(p.stdout.strip().splitlines()[-1])
got = [ln.split() for ln in open(outtxt) if ln.strip()]
exp = []
for k, c in ((KA, 7), (KB, 8)):
    s = (14 * k + 7) % 16
    hdr = [(0x028000F5 << 32) | 114688, (k << 32) | c, 3, s, 0, 0, 0, 917504]
    exp += [(0, w) for w in hdr]
    acc = sums[k]
    for i in range(114688):
        j, k1 = i // 8192, i % 8192
        k2 = (j + s - 7) % 16
        exp.append((1 if i == 114687 else 0, int(acc[k2, k1])))
n = min(len(got), len(exp))
def word(t):
    return None if ("x" in t or "X" in t) else int(t, 16)          # 不定（初期化していない記憶を足した）は違う語として数える


dif = sum(1 for a in range(n) if int(got[a][0]) != exp[a][0] or word(got[a][1]) != exp[a][1])
print("出口: %d 語（期待 %d）、違う語 %d" % (len(got), len(exp), dif))
ok = len(got) == len(exp) and dif == 0 and "drop 0" in p.stdout
if ferr or kerr:
    print("結果: %s" % ("不合格（陽性対照として正しく落ちた）" if not ok else "全部通過（陽性対照が落ちない: 照合が効いていない）"))
else:
    print("結果: %s" % ("全部通過" if ok else "不合格"))
