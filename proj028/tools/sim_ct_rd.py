#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 C-4 — ct_rd を iverilog で回し、出口の拍の並び・中身・tuser・tlast を期待と比べる。

  python3 tools/sim_ct_rd.py [--bad]
  配置: CHS 8 KiB（128 拍）・HB 4 KiB（64 拍）・3 面。チャンク 0（末尾なし）・1（読み途中に閉じる → 待ち）・2
  --bad（陽性対照: 末尾の番地を 1 拍ずらした RTL）: 中身が違う
"""
import os
import subprocess
import sys

import numpy as np

bad = "--bad" in sys.argv
tag = "bad" if bad else "ok"
od = "build-sim"
os.makedirs(od, exist_ok=True)
rtl = "src/ct_rd.v"
if bad:
    rtl = os.path.join(od, "ct_rd_bad.v")
    t = open("src/ct_rd.v").read()
    a = "(chp + off)"
    assert a in t
    open(rtl, "w").write(t.replace(a, "(chp + off + 64)"))
BASE, CHS, HB, NP = 4096, 8192, 4096, 3
PS = 32 * CHS
MB = (BASE + NP * PS) // 64 + 64
rng = np.random.default_rng(23)
mem = [int(rng.integers(0, 1 << 62)) << 448 | int(rng.integers(0, 1 << 62)) for _ in range(MB)]
for a in range(MB):                                  # 拍ごとに違う中身（番地を下に埋める）
    mem[a] = (mem[a] & ~0xFFFFFFFF) | a
inhex = os.path.abspath(os.path.join(od, "ctr_mem_%s.hex" % tag))
outtxt = os.path.abspath(os.path.join(od, "ctr_out_%s.txt" % tag))
with open(inhex, "w") as f:
    for v in mem:
        f.write("%0128x\n" % v)
# 期待の並び
exp = []
for c in range(3):
    pc = BASE + (c % NP) * PS
    pp = BASE + ((c - 1) % NP) * PS
    for k in range(32):
        if c >= 1:
            for o in range(0, HB, 64):
                exp.append(((c << 6) | (k << 1) | 1, 0, mem[(pp + k * CHS + CHS - HB + o) // 64]))
        for o in range(0, CHS, 64):
            exp.append(((c << 6) | (k << 1) | 0, 1 if o == CHS - 64 else 0, mem[(pc + k * CHS + o) // 64]))
n2 = 32 * (CHS // 64) + 32 * ((CHS + HB) // 64)
vvp = os.path.join(od, "tb_ctr_%s.vvp" % tag)
subprocess.run(["iverilog", "-g2012", "-o", vvp, "-DMB=%d" % MB, "-DBASE=%d" % BASE, "-DCHS=%d" % CHS, "-DPS=%d" % PS, "-DHB=%d" % HB,
                "-DNEXP=%d" % len(exp), "-DNEXP2=%d" % n2, '-DIN_HEX="%s"' % inhex, '-DOUT_TXT="%s"' % outtxt,
                "tb/tb_ct_rd.v", rtl], check=True)
p = subprocess.run(["vvp", "-n", vvp], check=True, capture_output=True, text=True)
out = p.stdout.strip().splitlines()
print("\n".join(out[-7:]))
got = [ln.split() for ln in open(outtxt) if ln.strip()]
ndiff = 0
first = None
for i, (e, g) in enumerate(zip(exp, got)):
    if int(g[0]) != e[0] or int(g[1]) != e[1] or int(g[2], 16) != e[2]:
        ndiff += 1
        if first is None:
            first = (i, e[0], int(g[0]), e[1], int(g[1]))
reg = {l.split()[0]: l.split()[1] for l in out if l.split() and l.split()[0] in ("DONE", "DROP", "FLAGS", "ERRS")}
print("拍: %d（期待 %d）、違う拍 %d、最初の違い %s" % (len(got), len(exp), ndiff, first))
ok = len(got) == len(exp) and ndiff == 0 and reg.get("DONE") == "3" and reg.get("DROP") == "0" and reg.get("FLAGS") == "0" and reg.get("ERRS") == "0" \
    and any("STATUS（チャンク 1 の直後）3" in l for l in out)
if bad:
    print("結果: %s" % ("不合格（陽性対照として正しく落ちた）" if ndiff > 0 else "全部通過（陽性対照が落ちない: 照合が効いていない）"))
else:
    print("結果: %s" % ("全部通過" if ok else "不合格"))
