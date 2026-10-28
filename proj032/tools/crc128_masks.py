#!/usr/bin/env python3
"""proj032 K-2 — CRC-32（zlib）を 128 bit ずつ 1 クロックで進める式の係数（ring128 の crc128）。
出力 bit j = ^(c & MC[j]) ^ ^(d & MD[j])。d は 16 バイト、バイト 0 が bit 0..7（リトルエンディアン）。zlib.crc32 と照らしてから出す。

  python3 tools/crc128_masks.py      # Verilog の関数を出す
"""
import random
import zlib

P = 0xEDB88320


def step(c, d, nbits=128):
    for i in range(nbits):
        b = (d >> i) & 1
        c = (c >> 1) ^ (P if (c ^ b) & 1 else 0)
    return c


def masks():
    mc, md = [0] * 32, [0] * 32
    for k in range(32):
        o = step(1 << k, 0)
        for j in range(32):
            if (o >> j) & 1:
                mc[j] |= 1 << k
    for k in range(128):
        o = step(0, 1 << k)
        for j in range(32):
            if (o >> j) & 1:
                md[j] |= 1 << k
    return mc, md


def par(x):
    return bin(x).count("1") & 1


def apply(mc, md, c, d):
    return sum((par(c & mc[j]) ^ par(d & md[j])) << j for j in range(32))


def main():
    mc, md = masks()
    rnd = random.Random(1)
    for _ in range(200):
        n = rnd.randrange(1, 20)
        blob = bytes(rnd.getrandbits(8) for _ in range(16 * n))
        c = 0xFFFFFFFF
        for i in range(n):
            c = apply(mc, md, c, int.from_bytes(blob[16 * i:16 * i + 16], "little"))
        assert (c ^ 0xFFFFFFFF) == zlib.crc32(blob), "zlib と合わない"
    print("    // tools/crc128_masks.py が作った（zlib.crc32 と 200 通り照らした）")
    print("    function [31:0] crc128(input [31:0] c, input [127:0] d);")
    print("        begin")
    for j in range(32):
        print("            crc128[%2d] = ^(c & 32'h%08X) ^ ^(d & 128'h%032X);" % (j, mc[j], md[j]))
    print("        end")
    print("    endfunction")


if __name__ == "__main__":
    main()
