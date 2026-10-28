#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj033 P-1 — s2_sep の単体の sim の入力を書き、出口を模型（model/s2_model.py の lane_ip → sep_Z）と bit 単位で照らす。
proj030 の sim/check_s2.py を 2G-1-Fast の寸法（M 16384・Z 30 bit・2Y 31 bit）と proj033 の模型に直したもの。

  python3 sim/check_s2.py gen   <dir>            # <dir>/zre.hex・zim.hex（1 行 = 1 ビートの IP 8 個の Z、30 bit × 8）
  python3 sim/check_s2.py check <dir> <tb.log>   # <dir>/y.txt を照らし、最後に「結果: 全部通過 / 不合格」
"""
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import g21_fixed as F  # noqa: E402
import s2_model as S  # noqa: E402

ZW, YW, NF = S.ZW, S.ZW + 1, 3
NROW = F.M // 2 + 1        # 1 フレームの出口の行（0..M/2）


def frames():
    """M-1b と同じ入力（CW 1000 LSB @ ch 40000 ＋ 雑音 σ 100）の PFB の出口、フレーム 2〜4。"""
    x, _ = S.test_input()
    y, _ = F.pfb_int(x, F.coef_interp())
    return [y[f] for f in (2, 3, 4)]


def pack(v, w):
    out = 0
    for i, a in enumerate(v):
        out |= (int(a) & ((1 << w) - 1)) << (w * i)
    return out


def gen(d):
    os.makedirs(d, exist_ok=True)
    br = F.bitrev(np.arange(F.M), S.KB)
    nd = (S.NQ * ZW + 3) // 4
    with open(os.path.join(d, "zre.hex"), "w") as fr, open(os.path.join(d, "zim.hex"), "w") as fi:
        for yf in frames():
            Zr, Zi = S.lane_ip(yf)
            assert max(np.abs(Zr).max(), np.abs(Zi).max()) < (1 << (ZW - 1)), f"Z が {ZW} bit に入らない"
            for i in range(F.M):
                k = br[i]
                fr.write("%0*x\n" % (nd, pack(Zr[:, k], ZW)))
                fi.write("%0*x\n" % (nd, pack(Zi[:, k], ZW)))
    print(f"gen: {NF * F.M} ビート")


def expect():
    """フレームごとに、組がそろう順の (行 r, 2Y の re 16 個, im 16 個)。"""
    rr = S.ready_rows()
    out = []
    for yf in frames():
        Y2r, Y2i = S.sep_Z(*S.lane_ip(yf))
        for r in rr[rr >= 0]:
            out.append((int(r), pack(Y2r[:, r], YW), pack(Y2i[:, r], YW)))
    return out


def check(d, tblog):
    exp = expect()
    rows = [l.split() for l in open(os.path.join(d, "y.txt"))]
    log = open(tblog, encoding="utf-8", errors="replace").read()
    m = re.search(r"pos_mis (\d+)", log)
    pos_mis = int(m.group(1)) if m else -1
    nbad = 0
    first = None
    for j, (ks, hr, hi) in enumerate(rows[: len(exp)]):
        r, er, ei = exp[j]
        try:
            same = int(ks) == r and int(hr, 16) == er and int(hi, 16) == ei
        except ValueError:          # x・z（書かれていない溜めの番地を読んだ）は違いとして数える
            same = False
        if not same:
            nbad += 1
            if first is None:
                first = (j, ks, r)
    cover = all(sorted(e[0] for e in exp[f * NROW:(f + 1) * NROW]) == list(range(NROW)) for f in range(NF))
    ok = len(rows) == len(exp) and nbad == 0 and pos_mis == 0 and cover
    print(f"出口 {len(rows)} 行（期待 {len(exp)}）・値か行の違い {nbad}・行 0〜{NROW - 1} がフレームごとに 1 回ずつ {cover}・pos_mis {pos_mis}")
    if first:
        print(f"  最初の違い: {first[0]} 行目（出た行 {first[1]}・期待 {first[2]}）")
    print("結果: " + ("全部通過" if ok else "不合格"))


if __name__ == "__main__":
    {"gen": lambda: gen(sys.argv[2]), "check": lambda: check(sys.argv[2], sys.argv[3])}[sys.argv[1]]()
