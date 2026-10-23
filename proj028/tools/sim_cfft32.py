#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 S-1 — cfft32 の RTL を iverilog で回し、浮動小数点の模型（M-1d の F）と比べる。

  ふつう（src/cfft32.v）: 相対の誤差（出口の最大の大きさに対する最大の差）≦ 1e-4 で通過
  陽性対照（--bad、build-sim/cfft32_bad.v）: ≧ 1e-2 で落ちる（落ちなければ照合が効いていない）
使い方: python3 tools/sim_cfft32.py [--bad]
"""
import os
import subprocess
import sys

import numpy as np

ZW, NB = 18, 200
bad = "--bad" in sys.argv
od = "build-sim"
os.makedirs(od, exist_ok=True)
rtl = os.path.join(od, "cfft32_bad.v") if bad else "src/cfft32.v"
if bad:
    subprocess.run([sys.executable, "tools/gen_cfft32.py", "--bad", "--out", rtl], check=True)
tag = "bad" if bad else "ok"
rng = np.random.default_rng(5)
lim = (1 << (ZW - 1)) - 1
z = rng.integers(-lim, lim + 1, size=(NB, 64))
z[0] = lim                                                   # 満杯の区間（LESSONS: 刺激に ±最大値を入れる）
z[1] = -lim
inhex = os.path.abspath(os.path.join(od, "cfft32_in.hex"))
outtxt = os.path.abspath(os.path.join(od, "cfft32_out_%s.txt" % tag))
with open(inhex, "w") as f:
    for row in z:
        v = 0
        for r in range(64):
            v |= (int(row[r]) & ((1 << ZW) - 1)) << (r * ZW)
        f.write("%0*x\n" % (64 * ZW // 4, v))
vvp = os.path.join(od, "tb_cfft32_%s.vvp" % tag)
subprocess.run(["iverilog", "-g2012", "-o", vvp, '-DIN_HEX="%s"' % inhex, '-DOUT_TXT="%s"' % outtxt,
                "tb/tb_cfft32.v", rtl], check=True)
p = subprocess.run(["vvp", "-n", vvp], check=True, capture_output=True, text=True)
print(p.stdout.strip().splitlines()[-1])
got = np.loadtxt(outtxt).reshape(-1, 32, 2)
got = got[..., 0] + 1j * got[..., 1]
n = np.arange(32)
w = (z[:, :32] + 1j * z[:, 32:]) * np.exp(1j * np.pi * n / 64)
F = 32 * np.fft.ifft(w, axis=1)
ok_n = got.shape[0] == NB
err = np.max(np.abs(got[:NB] - F)) / np.max(np.abs(F)) if ok_n else float("inf")
print("cfft32（%s）: ブロック %d / %d、相対の誤差 %.2e" % (tag, got.shape[0], NB, err))
if bad:
    print("結果: %s" % ("不合格（陽性対照として正しく落ちた）" if err > 1e-2 else "全部通過（陽性対照が落ちない: 照合が効いていない）"))
else:
    print("結果: %s" % ("全部通過" if ok_n and err <= 1e-4 else "不合格"))
