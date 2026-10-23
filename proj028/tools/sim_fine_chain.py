#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-2 — fine_tw ＋ fine_chain を iverilog で回し、model/fine_fixed.py の chain_Y ＋ power と bit 単位で比べる。

  python3 tools/sim_fine_chain.py [--norm] [--tw-hi-err]
  入力: ランダムな y（15 bit、複素）の 2 フレーム → 模型の lane_fft の出口 Y を bit 反転順の k1 で
  --norm（-DCHAIN_NORND）・--tw-hi-err（-DTW_HI_ERR）は陽性対照
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, "model")
import fine_fixed as F  # noqa: E402

nornd = "--norm" in sys.argv
twerr = "--tw-hi-err" in sys.argv
tag = "ok" + ("_nornd" if nornd else "") + ("_twerr" if twerr else "")
od = "build-sim"
os.makedirs(od, exist_ok=True)
SHIFT = 7
rng = np.random.default_rng(37)
NF = 2
twr, twi = F.tw_prod()
k1o = F.bitrev(np.arange(F.M), 13)                  # IP の出る順
inhex = os.path.abspath(os.path.join(od, "fch_in.hex"))
outtxt = os.path.abspath(os.path.join(od, "fch_out_%s.txt" % tag))
exp = []
with open(inhex, "w") as f:
    for fr in range(NF):
        yr = np.round(rng.standard_normal(F.N) * 192).astype(np.int64)
        yi = np.round(rng.standard_normal(F.N) * 192).astype(np.int64)
        if fr == 1:
            yr[:2000] = 16383                         # 満杯
        Yr, Yi = F.lane_fft(yr, yi)
        Zr, Zi = F.chain_Y(Yr, Yi, twr, twi)
        P, _ = F.power(Zr, Zi, SHIFT)                 # (16, M)
        for k1 in k1o:
            v = int(k1) << (16 * 56)
            for p in range(16):
                v |= ((int(Yi[p, k1]) & ((1 << 28) - 1)) << (56 * p + 28)) | ((int(Yr[p, k1]) & ((1 << 28) - 1)) << (56 * p))
            f.write("%x\n" % v)
            exp.append([k1] + [int(P[k2, k1]) for k2 in range(16)])
exp = np.array(exp, dtype=np.int64)
A = os.path.abspath("src/fine/fine_tw_a.hex")
B = os.path.abspath("src/fine/fine_tw_b.hex")
vvp = os.path.join(od, "tb_fch_%s.vvp" % tag)
cmd = ["iverilog", "-g2012", "-o", vvp, "-DNBEAT=%d" % len(exp), '-DIN_HEX="%s"' % inhex, '-DOUT_TXT="%s"' % outtxt,
       '-DA_HEX="%s"' % A, '-DB_HEX="%s"' % B]
if nornd:
    cmd.append("-DCHAIN_NORND")
if twerr:
    cmd.append("-DTW_HI_ERR")
subprocess.run(cmd + ["tb/tb_fine_chain.v", "src/fine/fine_chain.v", "src/fine/fine_tw.v", "src/fine/cmul.v", "src/fine/dft16f.v"], check=True)
p = subprocess.run(["vvp", "-n", vvp], check=True, capture_output=True, text=True)
last = p.stdout.strip().splitlines()[-1]
print(last)
got = np.loadtxt(outtxt, dtype=np.int64)
n = min(len(got), len(exp))
dk = np.sum(got[:n, 0] != exp[:n, 0])
dp = np.sum(got[:n, 1:] != exp[:n, 1:])
print("fine_chain（%s）: 拍 %d（期待 %d）、違う k1 %d・電力 %d / %d" % (tag, len(got), len(exp), dk, dp, exp[:, 1:].size))
ok = len(got) == len(exp) and dk == 0 and dp == 0 and "tw_mis 0" in last
if nornd or twerr:
    print("結果: %s" % ("不合格（陽性対照として正しく落ちた）" if not ok else "全部通過（陽性対照が落ちない: 照合が効いていない）"))
else:
    print("結果: %s" % ("全部通過" if ok else "不合格"))
