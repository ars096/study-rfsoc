#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 U-d — s2_s45_core（fine_core はスタブ）→ s45_ring → 記憶。リングのレコードの頭・本体・尾（CRC）を照らす。

  python3 tools/sim_s2_ring.py [--bad]
    B_C 64・BASE 224・N_DUMP 3・START_AT 2800（U-c と同じ）。STAGE2 の本体は REC_W 4 語（スタブ）、RAW は N_ACC 1・N_DUMP 2。
    細かい側に (c, k) = (0, 0)・(1, 1)・(2, 31)・(5, 3) を流す（(5, 3) は帳簿に無い → コアの出口で tuser 1 → リングが捨てる）
    予言: リングのレコード = コアの出口の tuser 0 のレコード（順も語も同じ、STAGE2 3・RAW 2）・尾 w0 = {SEQ, "S45E"}・
          w1 = zlib.crc32（頭 ＋ 本体）・残り 0・DROP_CNT 1・REC_CNT 5・ERR 0・記憶の見張りの NG 0・STAGE2 の語 7 = {k·114,688, 32}
    --bad: -DRING_FLIP（記憶の最初のレコードの本体の語 0 の bit 0 を反転）→ CRC の外れ 1・語の違い 1 で落ちる
"""
import os
import struct
import subprocess
import sys
import zlib

bad = "--bad" in sys.argv
od = "build-sim"
os.makedirs(od, exist_ok=True)
B_C, BASE, NDUMP, T_BEGIN, SA = 64, 224, 3, 1000, 7 * 400
SRC = ["tb/tb_s2_ring.v", "src/s2_s45_core.v", "src/s2_strm.v", "src/coarse_pfb.v", "src/cfft32.v", "src/coarse_post.v",
       "tb/fine_core_stub.v", "src/common/core_cmn.v", "src/common/tp_core.v", "src/common/raw_core.v", "src/common/rec_arb.v",
       "src/common/adc_ev.v", "src/common/s45_ring.v"]
MAGIC_R, MAGIC_E = 0x52353453, 0x45353453

tag = "ud_bad" if bad else "ud"
out = {k: os.path.abspath(os.path.join(od, "s2_%s_%s.txt" % (tag, k))) for k in ("rec", "ring", "reg")}
vvp = os.path.join(od, "tb_s2_%s.vvp" % tag)
feeds = [(0, 0, 0, 4), (1, 1, 3, 2), (2, 31, 3, 2), (5, 3, 3, 2)]
# コアの出口の数で待つ（RAW の 2 本は feed の前に出ている）
fl = " ".join("feed(%d,%d,%d,%d); wait_rec(%d);" % (c, k, nt, nb, 2 + i + 1) for i, (c, k, nt, nb) in enumerate(feeds))
cmd = ["iverilog", "-g2012", "-o", vvp, "-DB_C=%d" % B_C, "-DBASE=%d" % BASE, "-DNDUMP=%d" % NDUMP, "-DT_BEGIN=%d" % T_BEGIN,
       "-DSTART_AT=%d" % SA, "-DFEED_LIST=%s" % fl] + ['-DOUT_%s="%s"' % (k.upper(), v) for k, v in out.items()]
if bad:
    cmd.append("-DRING_FLIP")
subprocess.run(cmd + SRC, check=True)
p = subprocess.run(["vvp", "-n", vvp], check=True, capture_output=True, text=True)
for ln in p.stdout.strip().splitlines():
    if "NG" in ln or ln.startswith("done"):
        print("  " + ln)

reg = {a: int(b) for a, b in (ln.split() for ln in open(out["reg"]) if ln.strip())}
# コアの出口のレコード
recs, cur = [], []
for ln in open(out["rec"]):
    t = ln.split()
    if not t:
        continue
    cur.append(int(t[2], 16))
    if int(t[0]):
        recs.append((int(t[1]), cur))
        cur = []
good = [w for u, w in recs if u == 0]
nbad_core = sum(1 for u, _ in recs if u)
# リングのレコード
ring = []
for ln in open(out["ring"]):
    t = ln.split()
    if t and t[0] == "R":
        ring.append((int(t[1]), [int(x, 16) for x in t[2:]]))


def kind(w):
    return (w[0] >> 40) & 0xFF, (w[0] >> 56) & 0xFF


print("コアの出口: レコード %d（tuser 1 が %d）・種類 %s" % (len(recs), nbad_core, [kind(w) for _, w in recs]))
print("リング: レコード %d・W %d・DROP_CNT %d・REC_CNT %d・CTRL 0x%x・ERR_STAT %d・IF_ID 0x%08x・記憶の見張りの NG %d・バースト %d"
      % (len(ring), reg["W"], reg["DROP_CNT"], reg["REC_CNT"], reg["CTRL"], reg["ERR_STAT"], reg["IF_ID"], reg["NERR"], reg["NBURST"]))
ok = True
n_crc_bad = n_word_diff = 0
if len(ring) != len(good):
    print("NG レコードの数が違う（リング %d・コア %d）" % (len(ring), len(good)))
    ok = False
for i, ((pos, rw), cw) in enumerate(zip(ring, good)):
    n = len(cw)
    hb = rw[:n]
    tail = rw[n:]
    diff = sum(1 for a, b in zip(hb, cw) if a != b)
    n_word_diff += diff
    seq = cw[1] & 0xFFFFFFFF
    crc = zlib.crc32(b"".join(struct.pack("<Q", x) for x in hb))
    t_ok = len(tail) == 8 and tail[0] == (seq << 32 | MAGIC_E) and tail[1] == crc and all(x == 0 for x in tail[2:])
    if not t_ok:
        n_crc_bad += 1
    ty, s = kind(cw)
    extra = ""
    if ty == 1 and s == 0:
        k = cw[1] >> 32
        w7 = cw[7]
        extra = "・語 7 {S0 %d, P %d}" % (w7 >> 32, w7 & 0xFFFFFFFF)
        if w7 & 0xFFFFFFFF != 32 or n != 8 + 4:
            ok = False
    print("  %d: 位置 %d・s %d type %d・SEQ %d・語 %d（違い %d）・尾 %s（CRC 0x%08x、zlib 0x%08x）%s"
          % (i, pos, s, ty, seq, n, diff, "○" if t_ok else "×", tail[1] if len(tail) > 1 else -1, crc, extra))
    if rw[0] & 0xFFFFFFFF != MAGIC_R:
        ok = False
types = sorted(kind(w) for w in good)
print("CRC の外れ %d・語の違い %d・種類 %s" % (n_crc_bad, n_word_diff, types))
ok = ok and n_crc_bad == 0 and n_word_diff == 0 and types == [(1, 0)] * 3 + [(4, 1)] * 2 and nbad_core == 1
ok = ok and reg["DROP_CNT"] == 1 and reg["REC_CNT"] == 5 and (reg["CTRL"] >> 2) & 1 == 0 and reg["NERR"] == 0
if bad:
    print("結果: %s" % ("不合格（陽性対照として正しく落ちた）" if (not ok and n_crc_bad == 1 and n_word_diff == 1) else "不合格（陽性対照が落ちない／落ち方が違う）"))
else:
    print("結果: %s" % ("全部通過" if ok else "不合格"))
