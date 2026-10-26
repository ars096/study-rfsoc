#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj030 P-1 — s2_sep の単体の sim の入力を書き、出口を模型（model/s2_model.py の lane_fft_s2）と bit 単位で照らす。

  python3 sim/check_s2.py gen   <dir>            # <dir>/zre.hex・zim.hex（1 行 = 1 ビートの IP 8 個の Z、28 bit × 8）
  python3 sim/check_s2.py check <dir> <tb.log>   # <dir>/y.txt を照らし、最後に「結果: 全部通過 / 不合格」
"""
import os
import re
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import g24_fixed as F  # noqa: E402
import s2_model as S  # noqa: E402

ZW, YW, NF = 28, 29, 3


def frames():
    """M-1b と同じ入力（CW 1000 LSB @ ch 20000 ＋ 雑音 σ 100）の PFB の出口、フレーム 2〜4。"""
    N = F.N
    rng = np.random.default_rng(8)
    n = np.arange(5 * N)
    x = np.clip(np.round(1000 * np.cos(2 * np.pi * 20000 * n / N) + rng.normal(0, 100, 5 * N)), -8191, 8191).astype(np.int64)
    y, _ = F.pfb_int(x, F.coef_interp())
    return [y[f] for f in (2, 3, 4)]


def zfft(yf):
    yp = yf.reshape(F.M, F.LANES).T.astype(np.float64)
    Z = np.fft.fft(yp[:S.NQ] + 1j * yp[S.NQ:], axis=1)
    return np.rint(Z.real).astype(np.int64), np.rint(Z.imag).astype(np.int64)


def pack(v, w):
    out = 0
    for i, a in enumerate(v):
        out |= (int(a) & ((1 << w) - 1)) << (w * i)
    return out


def gen(d):
    os.makedirs(d, exist_ok=True)
    br = F.bitrev(np.arange(F.M), F.KB)
    nd = (S.NQ * ZW + 3) // 4
    with open(os.path.join(d, "zre.hex"), "w") as fr, open(os.path.join(d, "zim.hex"), "w") as fi:
        for yf in frames():
            Zr, Zi = zfft(yf)
            assert max(np.abs(Zr).max(), np.abs(Zi).max()) < (1 << (ZW - 1)), "Z が 28 bit に入らない"
            for i in range(F.M):
                k = br[i]
                fr.write("%0*x\n" % (nd, pack(Zr[:, k], ZW)))
                fi.write("%0*x\n" % (nd, pack(Zi[:, k], ZW)))
    print(f"gen: {NF * F.M} ビート")


def expect():
    """フレームごとに、組がそろう順の (行 r, 2Y の re 16 個, im 16 個)。"""
    br = F.bitrev(np.arange(F.M), F.KB)
    out = []
    for yf in frames():
        Y2r, Y2i = S.lane_fft_s2(yf)
        for n in range(F.M):
            h = 1 << (n.bit_length() - 1) if n else 0
            if n >= 2 and n < h + h // 2:
                continue
            k = int(br[n])
            r = min(k, F.M - k)
            out.append((r, pack(Y2r[:, r], YW), pack(Y2i[:, r], YW)))
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
    cover = all(sorted(e[0] for e in exp[f * 2049:(f + 1) * 2049]) == list(range(2049)) for f in range(NF))
    ok = len(rows) == len(exp) and nbad == 0 and pos_mis == 0 and cover
    print(f"出口 {len(rows)} 行（期待 {len(exp)}）・値か行の違い {nbad}・行 0〜2048 がフレームごとに 1 回ずつ {cover}・pos_mis {pos_mis}")
    if first:
        print(f"  最初の違い: {first[0]} 行目（出た行 {first[1]}・期待 {first[2]}）")
    print("結果: " + ("全部通過" if ok else "不合格"))


if __name__ == "__main__":
    {"gen": lambda: gen(sys.argv[2]), "check": lambda: check(sys.argv[2], sys.argv[3])}[sys.argv[1]]()
