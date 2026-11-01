#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 U-a — coarse_pfb のブロックの位相が T に固定されるか。

  python3 tools/sim_cpfb_ph.py [--bad | --gapt]
  ふつう: 拍のラベルの始まり T0 = 0..6 の 7 通り。lock の後のブロックで (1) 位相 B のブロックの o_t0 ≡ 0 (mod 7)、
          (2) o_t0・位相から決まるサンプルの位置で model/coarse_pfb_ref.py の式と z が bit 単位で同じ、(3) ph_lock = 1・ph_err = 0
  --bad（-DCPFB_PH_ERR、陽性対照）: 7 通りとも (1) が外れる
  --gapt: valid を落とした拍も T を進める（本物の T）。ph_err が立つ（見張りの陽性対照）
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, "model")
from coarse_pfb_ref import gtable, L, M, TC, SH, ZW  # noqa: E402

bad = "--bad" in sys.argv
gapt = "--gapt" in sys.argv
tag = "bad" if bad else "gapt" if gapt else "ok"
od = "build-sim"
os.makedirs(od, exist_ok=True)
NB = 7 * 50
rng = np.random.default_rng(12)
lim = (1 << 13) - 1
x = np.clip(np.round(rng.standard_normal(16 * NB) * 1031), -lim, lim).astype(np.int64)
x[16 * 150: 16 * 160] = lim
inhex = os.path.abspath(os.path.join(od, "cpfbph_in_%s.hex" % tag))   # 変種ごとに分ける（sim-all は同時に回す）
with open(inhex, "w") as f:
    for b in range(NB):
        v = 0
        for p in range(16):
            v |= ((int(x[16 * b + p]) << 2) & 0xFFFF) << (16 * p)
        f.write("%064x\n" % v)
g = gtable()
n = np.arange(L)
zl = 2 ** (ZW - 1) - 1


def zat(newest):
    if newest - (L - 1) < 0:
        return None
    s = (g * x[newest - n]).reshape(TC, M).sum(axis=0)
    return np.clip((s + (1 << (SH - 1))) >> SH, -zl, zl)


T0S = [0] if gapt else list(range(7))
bad_t = 0
okall = True
for T0 in T0S:
    outtxt = os.path.abspath(os.path.join(od, "cpfbph_out_%s_%d.txt" % (tag, T0)))
    vvp = os.path.join(od, "tb_cpfbph_%s_%d.vvp" % (tag, T0))
    cmd = ["iverilog", "-g2012", "-o", vvp, "-DNBEAT=%d" % NB, "-DT0=%d" % T0, '-DIN_HEX="%s"' % inhex, '-DOUT_TXT="%s"' % outtxt]
    if bad:
        cmd.append("-DCPFB_PH_ERR")
    if gapt:
        cmd.append("-DGAPT")
    subprocess.run(cmd + ["tb/tb_coarse_pfb.v", "src/coarse_pfb.v"], check=True)
    p = subprocess.run(["vvp", "-n", vvp], check=True, capture_output=True, text=True)
    last = p.stdout.strip().splitlines()[-1]
    lock = int(last.split(" lock ")[1].split()[0])
    err = int(last.split(" err ")[1].split()[0])
    nphase = nz = nchk = 0
    for ln in open(outtxt):
        t = ln.split()
        if not t:
            continue
        b, t0 = int(t[0]), int(t[1])
        beat = t0 - T0
        if beat < 14:                                   # lock の前（最初の合わせまで）は見ない
            continue
        if b and t0 % 7 != 0:
            nphase += 1
        s0 = 16 * beat + (0 if b else 8)
        ref = None if gapt else zat(s0 + 55)
        if ref is None or any(not v.lstrip("-").isdigit() for v in t[2:]):
            continue
        got = np.array([int(v) for v in t[2:]], np.int64)
        nchk += 1
        nz += int(np.any(got != ref))
    print("T0 %d: 位相の外れ %d・z の違うブロック %d / %d・lock %d・err %d" % (T0, nphase, nz, nchk, lock, err))
    if gapt:
        okall = err == 1
    elif bad:
        bad_t += int(nphase > 0)
    else:
        okall = okall and nphase == 0 and nz == 0 and nchk > 50 and lock == 1 and err == 0
if bad:
    print("結果: %s" % ("不合格（陽性対照として正しく落ちた）" if bad_t == 7 else "全部通過（陽性対照が落ちない: 照合が効いていない）"))
elif gapt:
    print("結果: %s" % ("全部通過（見張りが立った）" if okall else "不合格（見張りが立たない）"))
else:
    print("結果: %s" % ("全部通過" if okall else "不合格"))
