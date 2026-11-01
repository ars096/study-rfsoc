#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 U-b・U-c・U-e — s2_strm を B_C 64 ブロック（BASE 224 ビート）に縮めて iverilog で回す。

  python3 tools/sim_s2_strm.py ub [--bad]   U-b: ARM_RUN の START_AT 3 通り（7 の倍数）。印 1 回・出口のブロック 3·64・RUN_T = START_AT・FLAGS 0
                                            --bad: START_AT ＋ 1（7 の倍数でない）で RUN を受けず（出口 0 ブロック）FLAGS[1]
  python3 tools/sim_s2_strm.py ue [--bad]   U-e: 孤立したサンプルを START_AT ＋ 50 ビートの 5 番に。coarse_pfb の出口の z から、
                                            「DUMP_T（= RUN_T）と印のブロックから数えたサンプルの位置」と入口の本当の位置の差 D_S を出す
                                            --bad: -DS2_MARK_LATE（印を 1 ブロック遅らせる。D_S が 56 サンプル = 3.5 ビート動くべき）
  python3 tools/sim_s2_strm.py uc [--bad]   U-c: 3 チャンクの後、細かい側に (c, k) = (0, 0)・(1, 1)・(2, 31)・(5, 3) の ch を流し、頭を式と照らす。
                                            (5, 3) は帳簿に無いチャンク: tuser = 1・FLAGS[3]・REC_LATE 1
                                            --bad: -DS2_S0_ERR（語 7 の S0 を 1 本ずらす）で落ちる
                                            **fine_core は tb/fine_core_stub.v**（口だけ同じ。DUMP_N = 本体のフレームの数・本体 4 語）。
                                            本物は荒い段と回すと 1 レコードに数十分（iverilog で ≒ 86 拍/秒）。中身の道は sim-fcore・sim-facc が見る
"""
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, "model")
from coarse_pfb_ref import gtable, SH  # noqa: E402

mode = sys.argv[1]
bad = "--bad" in sys.argv
od = "build-sim"
os.makedirs(od, exist_ok=True)
B_C, BASE, NDUMP, T_BEGIN = 64, 224, 3, 1000
SRC = ["tb/tb_s2_strm.v", "src/s2_strm.v", "src/coarse_pfb.v", "src/cfft32.v", "src/coarse_post.v", "src/common/adc_ev.v",
       "src/fine/fine_core.v", "src/fine/fine_pfb.v", "src/fine/fine_coef.v", "src/fine/fine_chain.v", "src/fine/fine_tw.v",
       "src/fine/fine_acc.v", "src/fine/fine_rdo.v", "src/fine/cmul.v", "src/fine/dft16f.v", "sim/lane_fft_f_model.v"]
A = os.path.abspath("src/fine")


STUB = ["tb/tb_s2_strm.v", "src/s2_strm.v", "src/coarse_pfb.v", "src/cfft32.v", "src/coarse_post.v", "src/common/adc_ev.v",
        "tb/fine_core_stub.v"]


def run(tag, start_at, defs, src=SRC):
    out = {k: os.path.abspath(os.path.join(od, "s2_%s_%s.txt" % (tag, k))) for k in ("blk", "z", "sat", "rec", "reg")}
    vvp = os.path.join(od, "tb_s2_%s.vvp" % tag)
    cmd = ["iverilog", "-g2012", "-o", vvp, "-DB_C=%d" % B_C, "-DBASE=%d" % BASE, "-DNDUMP=%d" % NDUMP, "-DT_BEGIN=%d" % T_BEGIN,
           "-DSTART_AT=%d" % start_at] + ['-DOUT_%s="%s"' % (k.upper(), v) for k, v in out.items()] + defs
    cmd += ["-Ptb_s2_strm.dut.LO_FILE=\"%s/fine_coef_lo.hex\"" % A, "-Ptb_s2_strm.dut.HI_FILE=\"%s/fine_coef_hi.hex\"" % A,
            "-Ptb_s2_strm.dut.TA_FILE=\"%s/fine_tw_a.hex\"" % A, "-Ptb_s2_strm.dut.TB_FILE=\"%s/fine_tw_b.hex\"" % A]
    subprocess.run(cmd + src, check=True)
    p = subprocess.run(["vvp", "-n", vvp], check=True, capture_output=True, text=True)
    print("  " + p.stdout.strip().splitlines()[-1])
    reg = {int(a): int(b) for a, b in (ln.split() for ln in open(out["reg"]) if ln.strip())}
    blk = [tuple(map(int, ln.split())) for ln in open(out["blk"]) if ln.strip()]
    return out, reg, blk


ok = True
if mode == "ub":
    starts = [7 * 400 + (1 if bad else 0), 7 * 401 + (1 if bad else 0), 7 * 437 + (1 if bad else 0)]
    for sa in starts:
        out, reg, blk = run("ub%s_%d" % ("_bad" if bad else "", sa), sa, ["-DNOISE"])
        nmark = sum(u for _, u in blk)
        first = blk[0][1] if blk else None
        run_t = reg[0x60] | (reg[0x64] << 32)
        fl = reg[0x18]
        print("START_AT %d: 出口 %d ブロック・印 %d（最初の拍 %s）・RUN_T %d・FLAGS 0x%x・CTRL 0x%x" % (sa, len(blk), nmark, first, run_t, fl, reg[0x08]))
        if bad:
            ok = ok and len(blk) == 0 and (fl >> 1) & 1 == 1
        else:
            ok = ok and len(blk) == NDUMP * B_C and nmark == 1 and first == 1 and run_t == sa and fl == 0 and reg[0x08] == 0
elif mode == "ue":
    sa = 7 * 400
    IA, ID, IP = 8000, 50, 5
    out, reg, blk = run("ue%s" % ("_bad" if bad else ""), sa,
                        ["-DIMP_A=%d" % IA, "-DIMP_T=%d" % (sa + ID), "-DIMP_P=%d" % IP] + (["-DS2_MARK_LATE"] if bad else []))
    n_run = reg[9999]
    run_t = reg[0x60] | (reg[0x64] << 32)
    g = gtable()
    lim = 2 ** 17 - 1
    zl = []
    for ln in open(out["z"]):
        t = ln.split()
        if len(t) > 1:
            m = int(t[0]) - n_run
            zl.append((m, [(int(t[i]), int(t[i + 1])) for i in range(1, len(t), 2)]))
    # サンプルの位置 s（DUMP_T の拍の 0 番から）を仮に置き、0 でない z が全部 g[56m + 55 − s]·A の丸めと合う s を探す
    def zval(n):
        return int(np.clip((int(g[n]) * IA + (1 << (SH - 1))) >> SH, -lim, lim))
    cand = []
    for s in range(-2000, 6000):
        good = True
        for m, lst in zl:
            n = 56 * m + 55 - s
            if not (0 <= n < 1728) or len(lst) != 1 or lst[0][0] != n % 64 or lst[0][1] != zval(n):
                good = False
                break
        if good:
            cand.append(s)
    s_true = 16 * (sa + ID - run_t) + IP
    print("RUN_T %d（START_AT %d）・0 でない z のブロック %d・合う s %s・本当の s %d" % (run_t, sa, len(zl), cand, s_true))
    if len(cand) == 1:
        d_s = s_true - cand[0]
        print("D_S = %d サンプル = %.2f ビート（入口の本当の位置 − DUMP_T と印から数えた位置）" % (d_s, d_s / 16))
        ok = d_s == 0 and run_t == sa           # --bad はこれが外れて「正しく落ちた」になる
    else:
        ok = False
elif mode == "uc":
    sa = 7 * 400
    feeds = [(0, 0, 0, 4), (1, 1, 3, 2), (2, 31, 3, 2), (5, 3, 3, 2)]
    fl = " ".join("feed(%d,%d,%d,%d); wait_rec(%d);" % (c, k, nt, nb, i + 1) for i, (c, k, nt, nb) in enumerate(feeds))
    out, reg, blk = run("uc%s" % ("_bad" if bad else ""), sa, ["-DNOISE", "-DFEED", "-DFEED_LIST=%s" % fl] + (["-DS2_S0_ERR"] if bad else []), STUB)
    sat = {}
    for ln in open(out["sat"]):
        t = list(map(int, ln.split()))
        sat[t[0]] = t[1:]
    words = [ln.split() for ln in open(out["rec"]) if ln.strip()]
    recs, cur = [], []
    for l, u, w in words:
        cur.append((int(l), int(u), int(w, 16)))
        if int(l):
            recs.append(cur)
            cur = []
    print("レコード %d 本（語 %s）" % (len(recs), [len(r) for r in recs]))
    exp_n = [nb for _, _, _, nb in feeds]                 # スタブの DUMP_N = 本体のフレームの数
    for i, (c, k, nt, nb) in enumerate(feeds[:3]):
        r = recs[i] if i < len(recs) else []
        hw = [w for _, _, w in r[:8]]
        exp = [(1 << 40) | (1 << 32) | 0x52353453, (c << 32) | i, c * B_C, sa + c * BASE,
               (7 << 16) | (6 << 8) | 17, (sat[c][k] << 32) | exp_n[i], 0xCF01, ((k * 114688) << 32) | 917504]
        nd = sum(1 for a, b in zip(hw, exp) if a != b)
        tus = [u for _, u, _ in r]
        print("(c %d, k %d): 頭の違う語 %d / 8・語 %d・tuser %d・DUMP_SAT %d%s" % (c, k, nd, len(r), sum(tus), sat[c][k],
              "" if nd == 0 else "  got %s exp %s" % ([hex(x) for x in hw], [hex(x) for x in exp])))
        ok = ok and nd == 0 and len(r) == 8 + 4 and sum(tus) == 0
    r = recs[3] if len(recs) > 3 else []
    print("(c 5, k 3): 語 %d・最後の tuser %s・FLAGS 0x%x・REC_LATE %d" % (len(r), r[-1][1] if r else None, reg[0x18], reg[0x88]))
    ok = ok and len(recs) == 4 and r and r[-1][1] == 1 and (reg[0x18] >> 3) & 1 == 1 and reg[0x88] == 1
    print("流れのブロック: SEQ %d・DUMP_K %d・RUN_T %d・CTRL 0x%x" % (reg[0x1C], reg[0x3C], reg[0x60], reg[0x08]))
    ok = ok and reg[0x1C] == 3 and reg[0x3C] == 2           # DUMP_K は最後の捨てなかったレコード（c 2）
if bad:
    print("結果: %s" % ("不合格（陽性対照として正しく落ちた）" if not ok and mode != "ub" else
                       "全部通過（陽性対照が落ちない: 照合が効いていない）" if mode != "ub" else
                       "全部通過（7 の倍数でない START_AT を受けなかった）" if ok else "不合格"))
else:
    print("結果: %s" % ("全部通過" if ok else "不合格"))
