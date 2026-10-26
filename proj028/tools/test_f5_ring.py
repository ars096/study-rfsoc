#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-5 — pynq/f5.py のリングの読み手（Ring.read）を、ボード無しで偽のバッファに対して確かめる（python3 tools/test_f5_ring.py）

s45_ring の書き方（proj024 の src/common/s45_ring.v の注釈）をまねて書く: 端に入らなければ PAD（w0 = {1 << 32, "S45R"}、w7 = 端まで）→ 頭 8 語 →
本体 → 尾（w0 = {頭の w1 の下位 32 bit, "S45E"}、w1 = 頭 ＋ 本体の CRC-32）。レコード 10 個（4 MiB のリングで 1 回折り返す）。
陽性対照: 7 番目のレコードの本体を 1 bit 壊す → その 1 個だけ CRC が落ちる
"""
import os
import sys
import zlib

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pynq"))
import f5  # noqa: E402


class FakeRegs:
    def __init__(self):
        self.r = {}

    def rd(self, a):
        return self.r.get(a, 0)

    def wr(self, a, v):
        self.r[a] = v


def main():
    size = 4 << 20
    R = f5.Ring.__new__(f5.Ring)
    R.g, R.size, R.bo_sync, R.r = FakeRegs(), size, None, 0
    R.prof = dict(inval=0.0, parse=0.0, crc=0.0, copy=0.0, n=0)
    R.a64 = np.zeros(size // 8, np.uint64)
    R.a8 = R.a64.view(np.uint8)
    R._inval = lambda p, n: None
    W = 0
    got = []
    for n in range(10):
        k, c = n % 32, n // 4
        L = 64 + f5.REC_BYTES + 64
        p = W % size
        if L > size - p:
            R.a64[p // 8:p // 8 + 8] = [(1 << 32) | f5.MAGIC_R, 0, 0, 0, 0, 0, 0, size - p]
            W += size - p
            p = 0
        i = p // 8
        R.a64[i:i + 8] = [(f5.ID_REC << 32) | f5.NKEEP, (k << 32) | c, 160, (14 * k + 7) % 16, 0, 0, 0, f5.REC_BYTES]
        R.a64[i + 8:i + 8 + f5.NKEEP] = np.arange(f5.NKEEP, dtype=np.uint64) + k * 1000
        crc = zlib.crc32(R.a8[p:p + 64 + f5.REC_BYTES])
        t = i + 8 + f5.NKEEP
        R.a64[t:t + 8] = [(c << 32) | f5.MAGIC_E, crc, 0, 0, 0, 0, 0, 0]
        if n == 7:
            R.a8[p + 64 + 100] ^= 1
        W += L
        R.g.r[f5.Ring.R_W] = W & 0xFFFFFFFF
        got += [(n, r) for r in R.read()]
    ok = len(got) == 10
    for n, (kk, c, na, sk, body, crc_ok, tail_ok, hdr_ok) in got:
        want_crc = n != 7
        good = (kk, c, na, sk) == (n % 32, n // 4, 160, (14 * (n % 32) + 7) % 16) and int(body[1]) == 1 + 1000 * kk \
            and crc_ok == want_crc and tail_ok and hdr_ok
        ok &= good
        print(f"レコード {n}: k {kk}・c {c}・CRC {'○' if crc_ok else '×'}（期待 {'○' if want_crc else '×'}）・尾 {tail_ok}・頭 {hdr_ok} → {'OK' if good else 'NG'}")
    print(f"R = {R.r}（W = {W & 0xFFFFFFFF}）")
    ok &= R.r == W & 0xFFFFFFFF
    print("結果: " + ("全部通過（陽性対照のレコード 7 は CRC で落ちた）" if ok else "不合格"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
