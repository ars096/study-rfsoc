#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 C-3 — ct_wr を iverilog で回し、DDR の模型の中身を ch ごとに並べ替えた入力と比べる。

  python3 tools/sim_ct_wr.py [--bad] [--stall] [--qb N]
  ふつう（QB 4・GPD 3・3 面・7 チャンク）: 最後の 3 チャンクの中身が全部一致・chunk_done が 0..6 の順・CHUNKS 7・OVF 0・GROUPS 21
  --bad（陽性対照: 入口の回しを 1 ずらす）: 中身が違う
  --stall（途中で wready を長く落とす）: OVF ≧ 1
"""
import os
import subprocess
import sys

import numpy as np

bad = "--bad" in sys.argv
stall = "--stall" in sys.argv
QB = int(sys.argv[sys.argv.index("--qb") + 1]) if "--qb" in sys.argv else 4
GPD, NP, BASE, NCH = 3, 3, 4096, 7
tag = ("bad" if bad else "ok") + ("_stall" if stall else "") + "_qb%d" % QB
od = "build-sim"
os.makedirs(od, exist_ok=True)
rtl = "src/ct_wr.v"
if bad:
    rtl = os.path.join(od, "ct_wr_bad.v")
    t = open("src/ct_wr.v").read()
    a = "kj = j - bq;"
    assert a in t
    open(rtl, "w").write(t.replace(a, "kj = j - bq + 1;"))
G = 32 * QB
NBLK = NCH * GPD * G
CHS = GPD * QB * 64
PS = 32 * CHS
MB = (BASE + NP * PS) // 64
rng = np.random.default_rng(17)
y = rng.integers(0, 1 << 16, size=(NBLK, 32), dtype=np.int64)
inhex = os.path.abspath(os.path.join(od, "ctw_in_qb%d.hex" % QB))
outtxt = os.path.abspath(os.path.join(od, "ctw_out_%s.txt" % tag))
chk = os.path.abspath(os.path.join(od, "ctw_chk_%s.txt" % tag))
with open(inhex, "w") as f:
    for b in range(NBLK):
        v = 0
        for k in range(32):
            v |= int(y[b, k]) << (16 * k)
        f.write("%0128x\n" % v)
vvp = os.path.join(od, "tb_ctw_%s.vvp" % tag)
cmd = ["iverilog", "-g2012", "-o", vvp, "-DQB=%d" % QB, "-DGPD=%d" % GPD, "-DNBLK=%d" % NBLK,
       '-DIN_HEX="%s"' % inhex, '-DOUT_TXT="%s"' % outtxt, '-DCHK_TXT="%s"' % chk]
if stall:
    cmd.append("-DSTALL")
subprocess.run(cmd + ["tb/tb_ct_wr.v", rtl], check=True)
p = subprocess.run(["vvp", "-n", vvp], check=True, capture_output=True, text=True)
print(p.stdout.strip().splitlines()[-1])
# 模型の中身を 16 bit の列に
words = [ln.strip() for ln in open(outtxt) if ln.strip()]
memv = np.zeros(MB * 32, np.int64) - 1
for a, h in enumerate(words):
    if "x" in h or "X" in h:
        continue
    v = int(h, 16)
    for i in range(32):
        memv[a * 32 + i] = (v >> (16 * i)) & 0xFFFF
diff = 0
tot = 0
for c in range(NCH - NP, NCH):
    pl = c % NP
    for k in range(32):
        base16 = (BASE + pl * PS + k * CHS) // 2
        exp = y[c * GPD * G:(c + 1) * GPD * G, k]
        got = memv[base16: base16 + GPD * G]
        diff += int(np.sum(got != exp))
        tot += exp.size
lines = open(chk).read().split("\n")
idx = [int(l) for l in lines if l.strip().isdigit()]
reg = dict(l.split() for l in lines if l and not l.strip().isdigit())
print("中身: 最後の %d チャンクで違う値 %d / %d・chunk_done %s・%s" % (NP, diff, tot, idx, " ".join("%s %s" % kv for kv in reg.items())))
ok = diff == 0 and idx == list(range(NCH)) and reg["CHUNKS"] == str(NCH) and reg["OVF"] == "0" and reg["GROUPS"] == str(NCH * GPD) \
    and reg["FLAGS"] == "0" and reg["BUSY"] == "0" and reg["ERRS"] == "0"
if bad:
    print("結果: %s" % ("不合格（陽性対照として正しく落ちた）" if diff > 0 else "全部通過（陽性対照が落ちない: 照合が効いていない）"))
elif stall:
    print("結果: %s" % ("陽性対照（STALL）: 溢れを数えた（OVF %s）" % reg["OVF"] if int(reg["OVF"]) >= 1 and reg["FLAGS"] == "1" else "不合格（溢れを数えない）"))
else:
    print("結果: %s" % ("全部通過" if ok else "不合格"))
