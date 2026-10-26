#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-4 — fine_core を iverilog で回し、(1) IP の出口と PFB の模型の FFT (2) レコードと「記録した IP の出口を模型に通した値」を比べる。

  python3 tools/sim_fine_core.py [--act-err] [--no-sim]
  ch: (c 0, k 7) 本体 5（積む 2）、(c 1, k 5) 末尾 3 ＋ 本体 4（積む 4）、(c 1, k 6) 同じ
  --act-err（-DCORE_ACT_ERR）は陽性対照
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, "model")
import fine_fixed as F  # noqa: E402

aerr = "--act-err" in sys.argv
tag = "ok" + ("_act" if aerr else "")
od = "build-sim"
os.makedirs(od, exist_ok=True)
SHIFT = 7
CH = [(0, 7, 0, 5), (1, 5, 3, 4), (1, 6, 3, 4)]       # (c, k, 末尾のフレーム, 本体のフレーム)
rng = np.random.default_rng(43)
V, S = F.coef_tables()
coef = F.coef_beat(V, S)
lines = []
streams = []
for c, k, nt, nb in CH:
    n = (nt + nb) * F.N
    xr = np.clip(np.round(rng.standard_normal(n) * 12), -127, 127).astype(np.int64)
    xi = np.clip(np.round(rng.standard_normal(n) * 12), -127, 127).astype(np.int64)
    streams.append((c, k, nt, nb, xr, xi))
    nbeat = n // 32
    for b in range(nbeat):
        v = 0
        for i in range(32):
            v |= ((int(xi[32 * b + i]) & 0xFF) << (16 * i + 8)) | ((int(xr[32 * b + i]) & 0xFF) << (16 * i))
        tail = 1 if b < nt * F.N // 32 else 0
        tuser = ((c & 0xFFFF) << 6) | (k << 1) | tail
        v |= tuser << 512
        if b == nbeat - 1:
            v |= 1 << 534
        lines.append(v)
inhex = os.path.abspath(os.path.join(od, "fcore_in_%s.hex" % tag))
iptxt = os.path.abspath(os.path.join(od, "fcore_ip_%s.txt" % tag))
rectxt = os.path.abspath(os.path.join(od, "fcore_rec_%s.txt" % tag))
with open(inhex, "w") as f:
    for v in lines:
        f.write("%x\n" % v)
nrec = len(CH) * (8 + 114688)
src = ["tb/tb_fine_core.v"] + ["src/fine/%s.v" % m for m in ("fine_core", "fine_pfb", "fine_coef", "fine_chain", "fine_tw", "fine_acc", "fine_rdo", "cmul", "dft16f")] \
    + ["sim/lane_fft_f_model.v"]
A = os.path.abspath("src/fine")
vvp = os.path.join(od, "tb_fcore_%s.vvp" % tag)
cmd = ["iverilog", "-g2012", "-o", vvp, "-DNBEAT=%d" % len(lines), "-DNREC=%d" % nrec, "-DTMAX=8000000", "-DCHGAP=150000", "-DFFT_STALL_AT=5000",
       '-DIN_HEX="%s"' % inhex, '-DIP_TXT="%s"' % iptxt, '-DREC_TXT="%s"' % rectxt,
       '-DLO_HEX="%s/fine_coef_lo.hex"' % A, '-DHI_HEX="%s/fine_coef_hi.hex"' % A, '-DTA_HEX="%s/fine_tw_a.hex"' % A, '-DTB_HEX="%s/fine_tw_b.hex"' % A]
if aerr:
    cmd.append("-DCORE_ACT_ERR")
if "--no-sim" in sys.argv:                       # 記録済みの出口だけを照らす（sim は 40 分以上かかる）
    last = open(os.path.join(od, "sim_fcore_last_%s.txt" % tag)).read().strip()
else:
    subprocess.run(cmd + src, check=True)
    p = subprocess.run(["vvp", "-n", vvp], check=True, capture_output=True, text=True)
    last = p.stdout.strip().splitlines()[-1]
    open(os.path.join(od, "sim_fcore_last_%s.txt" % tag), "w").write(last + "\n")
print(last)
ip = np.loadtxt(iptxt, dtype=np.int64)
# 空のフレーム（全部 0）を除く: フレームごとに見て、全部 0 のものは捨てる（本物のフレームが全部 0 になることは無い）
ip = ip[: len(ip) // F.M * F.M]                 # sim の終わりに出かけていた途中のフレーム（空）を捨てる
fr_all = ip.reshape(-1, F.M, ip.shape[1])
keep = [i for i in range(len(fr_all)) if np.any(fr_all[i][:, 1:] != 0)]
print("IP の出口のフレーム: %d（うち空 %d）" % (len(fr_all), len(fr_all) - len(keep)))
ip = fr_all[keep].reshape(-1, ip.shape[1])
nfr_ip = len(ip) // F.M
print("IP の出口: %d 拍 = %d フレーム（期待 %d）" % (len(ip), nfr_ip, sum(nt + nb for _, _, nt, nb, _, _ in streams)))
# (1) IP の出口と PFB の模型の FFT
twr, twi = F.tw_prod()
fidx = 0
max_d = 0
recs = []
for c, k, nt, nb, xr, xi in streams:
    yr, yi, _ = F.pfb_frames(xr, xi, coef)
    acc = None
    nact = 0
    for f in range(nt + nb):
        blk = ip[fidx * F.M:(fidx + 1) * F.M]
        fidx += 1
        Yr = np.zeros((16, F.M), np.int64)
        Yi = np.zeros((16, F.M), np.int64)
        Yr[:, blk[:, 0]] = blk[:, 1::2].T
        Yi[:, blk[:, 0]] = blk[:, 2::2].T
        Er, Ei = F.lane_fft(yr[f], yi[f])
        max_d = max(max_d, int(np.abs(Yr - Er).max()), int(np.abs(Yi - Ei).max()))
        act = (f >= nt) and (f >= 3)
        if act:
            Zr, Zi = F.chain_Y(Yr, Yi, twr, twi)
            P, _ = F.power(Zr, Zi, SHIFT)
            acc = P.copy() if acc is None else acc + P
            nact += 1
    s = (14 * k + 7) % 16
    rec = [(0, (0x028000F5 << 32) | 114688), (0, (k << 32) | c), (0, nact), (0, s), (0, 0), (0, 0), (0, 0), (0, 917504)]
    for i in range(114688):
        j, k1 = i // 8192, i % 8192
        rec.append((1 if i == 114687 else 0, int(acc[(j + s - 7) % 16, k1])))
    recs += rec
print("(1) IP の出口 − PFB の模型の FFT: 最大 %d" % max_d)
got = [ln.split() for ln in open(rectxt) if ln.strip()]


def word(t):
    return None if ("x" in t or "X" in t) else int(t, 16)


n = min(len(got), len(recs))
dif = sum(1 for a in range(n) if int(got[a][0]) != recs[a][0] or word(got[a][1]) != recs[a][1])
print("(2) レコード: %d 語（期待 %d）、違う語 %d" % (len(got), len(recs), dif))
ok = max_d <= 1 and len(got) == len(recs) and dif == 0 and last.startswith("flags 0 n_rec 3")
if aerr:
    print("結果: %s" % ("不合格（陽性対照として正しく落ちた）" if dif > 0 else "全部通過（陽性対照が落ちない: 照合が効いていない）"))
else:
    print("結果: %s" % ("全部通過" if ok else "不合格"))
