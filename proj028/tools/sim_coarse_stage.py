#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 C-2 — coarse_stage（荒い PFB → cfft32 → coarse_post）を iverilog で回し、整数の模型と bit 単位で比べる。

  python3 tools/sim_coarse_stage.py [--bad]
  判定: (1) 出口の 8 bit の y がブロック m ≧ 30 で模型と全部一致 (2) POW・CLIP（最後に閉じた区切り）が RTL の出口から数え直した値と一致する
        区切りの頭が在る (3) 強い CW の ch で飽和を数えた
  --bad（陽性対照）: 奇数の ch の共役を抜いた coarse_post で落ちる
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, "model")
from coarse_pfb_ref import zblocks  # noqa: E402
from cfft32_ref import cfft32  # noqa: E402
from coarse_post_ref import post, ymap  # noqa: E402

bad = "--bad" in sys.argv
tag = "bad" if bad else "ok"
od = "build-sim"
os.makedirs(od, exist_ok=True)
post_v = "src/coarse_post.v"
if bad:
    post_v = os.path.join(od, "coarse_post_bad.v")
    t = open("src/coarse_post.v").read()
    a = "yi <= (k % 2 == 0) ? fi : -fi;"
    assert a in t
    open(post_v, "w").write(t.replace(a, "yi <= fi;"))
NB, WARM, NACC, CWCH = 7 * 300, 40, 100, 5
nblk = NB * 16 // 56
rng = np.random.default_rng(13)
lim = (1 << 13) - 1
sig = 1031.0
n = np.arange(16 * NB)
x = rng.standard_normal(16 * NB) * sig
x += 10 ** (24 / 20) * sig * np.sqrt(2 / 64) * np.sqrt(2) * np.cos(2 * np.pi * (CWCH + 0.5) / 64 * n)   # ch 5 に +24 dB の CW
x = np.clip(np.round(x), -lim, lim).astype(np.int64)
z = zblocks(x, nblk)
fr, fi = cfft32(z)
yr, yi = ymap(fr, fi)
sg = np.sqrt(np.mean(yr[30:].astype(float) ** 2 + yi[30:].astype(float) ** 2, axis=0) / 2)
gains = np.clip(np.round(12.0 / sg * 2 ** 16), 1, 2 ** 17 - 1).astype(np.int64)
gains[CWCH] = gains[(CWCH + 2) % 32]                  # 強い CW の ch は雑音の ch の利得のまま → 飽和する
qr, qi, clip, _, _ = post(fr, fi, gains)
inhex = os.path.abspath(os.path.join(od, "cst_in.hex"))
ghex = os.path.abspath(os.path.join(od, "cst_gain.hex"))
outtxt = os.path.abspath(os.path.join(od, "cst_out_%s.txt" % tag))
regtxt = os.path.abspath(os.path.join(od, "cst_reg_%s.txt" % tag))
with open(inhex, "w") as f:
    for b in range(NB):
        v = 0
        for p in range(16):
            v |= ((int(x[16 * b + p]) << 2) & 0xFFFF) << (16 * p)
        f.write("%064x\n" % v)
with open(ghex, "w") as f:
    for g in gains:
        f.write("%05x\n" % int(g))
vvp = os.path.join(od, "tb_cst_%s.vvp" % tag)
subprocess.run(["iverilog", "-g2012", "-o", vvp, "-DNBEAT=%d" % NB, "-DWARM=%d" % WARM, "-DNACC=%d" % NACC,
                '-DIN_HEX="%s"' % inhex, '-DGAIN_HEX="%s"' % ghex, '-DOUT_TXT="%s"' % outtxt, '-DREG_TXT="%s"' % regtxt,
                "tb/tb_coarse_stage.v", "src/coarse_stage.v", "src/coarse_pfb.v", "src/cfft32.v", post_v], check=True)
p = subprocess.run(["vvp", "-n", vvp], check=True, capture_output=True, text=True)
print(p.stdout.strip().splitlines()[-1])
rows = [ln.split() for ln in open(outtxt) if ln.strip()]
ok = len(rows) == nblk
gr = np.full((len(rows), 32), 999, np.int64)
gi = np.full((len(rows), 32), 999, np.int64)
for b, (_, h) in enumerate(rows):
    if "x" in h or "X" in h:
        continue
    v = int(h, 16)
    for k in range(32):
        w = (v >> (16 * k)) & 0xFFFF
        gr[b, k] = ((w & 0xFF) ^ 0x80) - 0x80
        gi[b, k] = ((w >> 8) ^ 0x80) - 0x80
m0 = 30
dif = np.sum(gr[m0:nblk] != qr[m0:]) + np.sum(gi[m0:nblk] != qi[m0:])
print("y: ブロック %d（期待 %d）、m ≧ %d で違う値 %d / %d" % (len(rows), nblk, m0, dif, 2 * 32 * (nblk - m0)))
ok &= dif == 0
reg = open(regtxt).read().split("\n")
seq = int(reg[0].split()[1])
pw = np.array([int(l.split()[2]) | (int(l.split()[3]) << 32) for l in reg[1:33]])
cl = np.array([int(l.split()[5]) for l in reg[1:33]])
# 区切りの頭 s0 を探す: 最後に閉じた区切り [s0 + (seq−1)·NACC, s0 + seq·NACC) の RTL の出口の Σ|y|² と飽和が POW・CLIP と一致
p2 = gr.astype(np.int64) ** 2 + gi.astype(np.int64) ** 2
clr = (np.abs(gr) >= 127).astype(np.int64) + (np.abs(gi) >= 127).astype(np.int64)
hits = []
for s0 in range(m0, nblk):
    a, b = s0 + (seq - 1) * NACC, s0 + seq * NACC
    if b > len(rows):
        break
    if np.all(p2[a:b].sum(axis=0) == pw):
        hits.append(s0)
print("SEQ %d・POW が出口の和と合う区切りの頭: %s・CLIP（ch %d）%d（ほかの ch の最大 %d）"
      % (seq, hits[:3], CWCH, cl[CWCH], np.delete(cl, CWCH).max()))
ok &= seq >= 3 and len(hits) == 1 and cl[CWCH] > 0
if hits:
    a, b = hits[0] + (seq - 1) * NACC, hits[0] + seq * NACC
    # CLIP は「|·| > 127 の前の値」なので、出口の ±127 の数（以上）と模型の clip で照らす
    ok &= np.all(clip[a:b].sum(axis=0) == cl)
    print("CLIP が模型（飽和の前の値で数える）と一致: %s" % np.all(clip[a:b].sum(axis=0) == cl))
if bad:
    print("結果: %s" % ("不合格（陽性対照として正しく落ちた）" if not ok else "全部通過（陽性対照が落ちない: 照合が効いていない）"))
else:
    print("結果: %s" % ("全部通過" if ok else "不合格"))
