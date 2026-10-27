#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj031 M — 共有の係数 URAM（g24_cu）の中身・2 ポートの読み・CRC の模型（README の M）。

PS の側の作り（pynq/g24cu.py）と CRC の式の生成器（tools/gen_crc32.py）を import して、proj030 の定義（g24_fixed.coef_beat）と照らす。
  python3 model/cu_model.py
"""
import os
import sys
import time
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "pynq"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import g24_fixed as gf  # noqa: E402
import g24cu  # noqa: E402
import gen_crc32  # noqa: E402

LO = os.path.join(ROOT, "src", "g24", "g24_coef_lo.hex")
HI = os.path.join(ROOT, "src", "g24", "g24_coef_hi.hex")
VH = os.path.join(ROOT, "src", "g24", "crc32_d32.vh")
M = g24cu.M


def read_all(r, mirror_off=0, rev=True):
    """2 ポートの読みを全部の m で組み立てる → [t, m, p]（coef_beat と同じ並び）。陽性対照の口つき。"""
    out = np.empty((4, M, 16), dtype=np.int64)
    for m in range(M):
        A = r[m]
        B = r[(M - 1 - m - mirror_off) % M]
        if rev:
            B = B[::-1]
        out[0, m], out[1, m], out[2, m], out[3, m] = A[:, 0], A[:, 1], B[:, 1], B[:, 0]
    return out


def crc_bitwise(r):
    c = 0xFFFFFFFF
    for b in g24cu.row_bytes(r).ravel():
        c = gen_crc32.step_bits(c, int(b), 8)
    return c ^ 0xFFFFFFFF


def crc_matrix(r):
    mx = gen_crc32.matrix()
    c = 0xFFFFFFFF
    for w in g24cu.words(r).ravel():
        c = gen_crc32.step_matrix(c, int(w), mx)
    return c ^ 0xFFFFFFFF


def main():
    t0 = time.time()
    ok = {}

    # a 表
    V, S = gf.coef_tables()
    Vl, Sl = g24cu.read_table(LO)
    Vh, Sh = g24cu.read_table(HI)
    a_ok = np.array_equal(Vl, V[:1024]) and np.array_equal(Sl, S[:1024]) and np.array_equal(Vh, V[1024:]) and np.array_equal(Sh, S[1024:])
    print(f"M-a 表: 前半・後半の V・S が coef_tables（G {gf.G}）と一致 {a_ok}")
    ok["M-a"] = a_ok

    # b 行の組み立て
    r = g24cu.rows(LO, HI)
    ref = gf.coef_beat(V, S)
    got = read_all(r)
    nd = int((got != ref).sum())
    m7 = 1234
    one = np.array_equal(g24cu.read2(r, m7).T, ref[:, m7, :])
    pc1 = read_all(r, mirror_off=1)
    pc2 = read_all(r, rev=False)
    f1 = float((pc1[2:] != ref[2:]).mean())
    f2 = float((pc2[2:] != ref[2:]).mean())
    print(f"M-b 2 ポートの組み立て: coef_beat と違う個 {nd} / {ref.size}（g24cu.read2 の 1 行 m {m7} も一致 {one}）")
    print(f"    陽性対照 鏡の番地 4094 − m: t 2・3 の違う割合 {f1:.4f} / レーンを逆順にしない: {f2:.4f}")
    # 予言は「陽性対照で 99 % 以上が違う」だったが外れた（README の M の結果: 隣のレーンの係数の約 50 % が同じ値）。成否は本体の一致と陽性対照が落ちることで読む
    ok["M-b"] = nd == 0 and one and f1 > 0 and f2 > 0

    # c 18 語の詰め
    w = g24cu.words(r)
    back = g24cu.unwords(w)
    rt = np.array_equal(back, r)
    lo_, hi_ = int(r.min()), int(r.max())
    rng = -(1 << 17) <= lo_ and hi_ < (1 << 17)
    print(f"M-c 18 語: 形 {w.shape} {w.dtype}・往復 {rt}・値の範囲 {lo_}〜{hi_}（18 bit 符号つき {rng}）")
    ok["M-c"] = rt and rng and w.shape == (M, 18)

    # d CRC
    cz = g24cu.crc(r)
    cb = crc_bitwise(r)
    cm = crc_matrix(r)
    with open(VH) as f:
        vh_same = f.read() == gen_crc32.verilog()
    print(f"M-d CRC: zlib 0x{cz:08X}・1 bit ずつ 0x{cb:08X}・32 bit の行列 0x{cm:08X}（src/g24/crc32_d32.vh が生成器の出力と同じ {vh_same}）")
    r1 = r.copy(); r1[100, 3, 1] ^= 1 << 5
    r2 = r.copy(); r2[[7, 8]] = r2[[8, 7]]
    r3 = np.zeros_like(r)
    pcs = {"1 bit 反転": g24cu.crc(r1), "2 行の入れ替え": g24cu.crc(r2), "全部 0": g24cu.crc(r3)}
    print("    陽性対照: " + "・".join(f"{k} 0x{v:08X}" for k, v in pcs.items()))
    ok["M-d"] = cz == cb == cm and vh_same and all(v != cz for v in pcs.values())

    print(f"  [{time.time() - t0:.1f} s]")
    print("まとめ: " + "  ".join(f"{k} {'通過' if v else '不合格'}" for k, v in ok.items()))
    print(f"COEF_CRC 0x{cz:08X}")
    return 0 if all(ok.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
