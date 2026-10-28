#!/usr/bin/env python3
"""proj032 K-2 — f32cv の照合。

  python3 sim/check_f32cv.py gen IN            # 入力を作る（端の値 ＋ 乱数）
  python3 sim/check_f32cv.py check IN OUT      # 出力と照らす

期待値:
  u < 2^53: np.float32(np.float64(u))（PS の proj029 と同じ u64 → double → float）
  u ≧ 2^53: 1 回の最近接・偶数（Python の整数で丸める）
"""
import random
import sys

import numpy as np


def rne32(u):
    """u64 → f32 の bit（1 回の最近接・偶数）"""
    if u == 0:
        return 0
    e = u.bit_length() - 1                  # 値 = 1.m × 2^e
    if e <= 23:
        m = u << (23 - e)
    else:
        sh = e - 23
        m = u >> sh
        rem = u - (m << sh)
        half = 1 << (sh - 1)
        if rem > half or (rem == half and (m & 1)):
            m += 1
        if m >> 24:
            m >>= 1; e += 1
    return ((127 + e) << 23) | (m & 0x7FFFFF)


def expect(u):
    if u < (1 << 53):
        return int(np.array([np.float32(np.float64(u))]).view(np.uint32)[0])
    return rne32(u)


def gen(path):
    rnd = random.Random(32012)
    v = [0, 1, 2, 3, (1 << 24) - 1, 1 << 24, (1 << 24) + 1, (1 << 24) + 2, (1 << 24) + 3, (1 << 25) + 2, (1 << 25) + 6,
         (1 << 53) - 1, 1 << 53, (1 << 53) + 1, (1 << 64) - 1, (1 << 63), (1 << 63) + (1 << 39), (1 << 63) + (3 << 39)]
    for e in range(64):                      # 2 のべきとその前後、丸めのちょうど半分
        for d in (-1, 0, 1):
            x = (1 << e) + d
            if 0 <= x < (1 << 64):
                v.append(x)
        if e >= 25:
            base = rnd.getrandbits(24) | (1 << 23)
            sh = e - 23
            v += [(base << sh) | (1 << (sh - 1)), ((base | 1) << sh) | (1 << (sh - 1)), ((base & ~1) << sh) | (1 << (sh - 1))]
    while len(v) < 20000:
        b = rnd.choice([16, 24, 30, 37, 40, 47, 52, 53, 54, 60, 64])
        v.append(rnd.getrandbits(b))
    with open(path, "w") as f:
        for x in v:
            f.write("%016x\n" % x)


def check(pin, pout):
    u = [int(l, 16) for l in open(pin)]
    o = [int(l, 16) for l in open(pout)]
    if len(o) != len(u):
        print("数が違う: 入力 %d・出力 %d" % (len(u), len(o)))
        print("結果: 不合格"); return 1
    bad = [(i, x, y) for i, (x, y) in enumerate(zip(u, o)) if expect(x) != y]
    for i, x, y in bad[:5]:
        print("  %d: u %016x → %08x（期待 %08x）" % (i, x, y, expect(x)))
    big = sum(1 for x in u if x >= (1 << 53))
    print("照合 %d 個（うち 2^53 以上 %d）・不一致 %d" % (len(u), big, len(bad)))
    print("結果: " + ("全部通過" if not bad else "不合格"))
    return 0 if not bad else 1


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        gen(sys.argv[2])
    else:
        sys.exit(check(sys.argv[2], sys.argv[3]))
