#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-1 — fine_pfb を iverilog で回し、model/fine_fixed.py と bit 単位で比べる。

  python3 tools/sim_fine_pfb.py [--gap] [--frac-err] [--no-ch-reset]
  ch A（5 フレーム）→ ch B（4 フレーム、頭で s_first）。出口の y の全部・m・fr を模型（ch ごとに履歴 0 から）と比べる
  --frac-err・--no-ch-reset は陽性対照（落ちるべき）
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, "model")
import fine_fixed as F  # noqa: E402

gap = "--gap" in sys.argv
ferr = "--frac-err" in sys.argv
nor = "--no-ch-reset" in sys.argv
tag = "ok" + ("_gap" if gap else "") + ("_frac" if ferr else "") + ("_noreset" if nor else "")
od = "build-sim"
os.makedirs(od, exist_ok=True)
FR = [5, 4]
rng = np.random.default_rng(31)
chans = []
for nf in FR:
    n = nf * F.N
    xr = np.clip(np.round(rng.standard_normal(n) * 12), -127, 127).astype(np.int64)
    xi = np.clip(np.round(rng.standard_normal(n) * 12), -127, 127).astype(np.int64)
    xr[F.N: F.N + 4096] = 127                         # 満杯の区間
    xi[F.N: F.N + 4096] = -127
    chans.append((xr, xi))
V, S = F.coef_tables()
c = F.coef_beat(V, S)
inhex = os.path.abspath(os.path.join(od, "fpfb_in.hex"))
outtxt = os.path.abspath(os.path.join(od, "fpfb_out_%s.txt" % tag))
nbeat = 0
with open(inhex, "w") as f:
    for xr, xi in chans:
        for b in range(len(xr) // 16):
            v = 0
            for p in range(16):
                v |= ((int(xi[16 * b + p]) & 0xFF) << (16 * p + 8)) | ((int(xr[16 * b + p]) & 0xFF) << (16 * p))
            if b == 0:
                v |= 1 << 256
            f.write("%065x\n" % v)
            nbeat += 1
lo = os.path.abspath("src/fine/fine_coef_lo.hex")
hi = os.path.abspath("src/fine/fine_coef_hi.hex")
vvp = os.path.join(od, "tb_fpfb_%s.vvp" % tag)
cmd = ["iverilog", "-g2012", "-o", vvp, "-DNBEAT=%d" % nbeat, '-DIN_HEX="%s"' % inhex, '-DOUT_TXT="%s"' % outtxt,
       '-DLO_HEX="%s"' % lo, '-DHI_HEX="%s"' % hi]
if gap:
    cmd.append("-DGAP")
if ferr:
    cmd.append("-DCOEF_FRAC_ERR")
if nor:
    cmd.append("-DNO_CH_RESET")
subprocess.run(cmd + ["tb/tb_fine_pfb.v", "src/fine/fine_pfb.v", "src/fine/fine_coef.v"], check=True)
p = subprocess.run(["vvp", "-n", vvp], check=True, capture_output=True, text=True)
print(p.stdout.strip().splitlines()[-1])
got = np.loadtxt(outtxt, dtype=np.int64)
# 期待: ch ごとに履歴 0 から
exp_m, exp_fr, exp_y = [], [], []
for nf, (xr, xi) in zip(FR, chans):
    yr, yi, _ = F.pfb_frames(xr, xi, c)
    for fi in range(nf):
        frv = min(fi, 3)
        for m in range(F.M):
            exp_m.append(m)
            exp_fr.append(frv)
            row = np.empty(32, np.int64)
            row[0::2] = yr[fi, 16 * m:16 * m + 16]
            row[1::2] = yi[fi, 16 * m:16 * m + 16]
            exp_y.append(row)
exp_y = np.array(exp_y)
n = min(len(got), len(exp_y))
dm = np.sum(got[:n, 0] != np.array(exp_m[:n]))
dfr = np.sum(got[:n, 1] != np.array(exp_fr[:n]))
dy = np.sum(got[:n, 2:] != exp_y[:n])
print("fine_pfb（%s）: 拍 %d（期待 %d）、違う m %d・fr %d・y %d / %d" % (tag, len(got), len(exp_y), dm, dfr, dy, exp_y.size))
ok = len(got) == len(exp_y) and dm == 0 and dfr == 0 and dy == 0
if ferr or nor:
    print("結果: %s" % ("不合格（陽性対照として正しく落ちた）" if not ok else "全部通過（陽性対照が落ちない: 照合が効いていない）"))
else:
    print("結果: %s" % ("全部通過" if ok else "不合格"))
