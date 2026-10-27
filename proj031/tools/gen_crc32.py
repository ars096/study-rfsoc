#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj031 — 反射 CRC-32（zlib.crc32 と同じ多項式・向き）を 1 拍 32 bit ずつ取る式を、展開した XOR として書く。

c' = F(c, d)。d の bit 0 から順に 1 bit ずつ: c = (c >> 1) ^ (0xEDB88320 if (c ^ bit) & 1 else 0)。
F は線形なので、c と d の単位ベクトルごとの応答から XOR の行列を作る（LESSONS: CRC は for 文でなく展開した XOR の式で、proj021）。
出力: src/g24/crc32_d32.vh（Verilog の function crc32_d32）。初期値・終わりの XOR（0xFFFFFFFF）は使う側（g24_cu）が持つ。

  python3 tools/gen_crc32.py [出力]       （既定 src/g24/crc32_d32.vh）
"""
import os
import sys

POLY = 0xEDB88320


def step_bits(c, d, n=32):
    for k in range(n):
        b = (d >> k) & 1
        c = (c >> 1) ^ (POLY if (c ^ b) & 1 else 0)
    return c


def matrix():
    """out[i] = (c の bit の集合, d の bit の集合)。"""
    out = [(set(), set()) for _ in range(32)]
    for j in range(32):
        rc, rd = step_bits(1 << j, 0), step_bits(0, 1 << j)
        for i in range(32):
            if (rc >> i) & 1:
                out[i][0].add(j)
            if (rd >> i) & 1:
                out[i][1].add(j)
    return out


def step_matrix(c, d, mx=None):
    mx = mx or matrix()
    r = 0
    for i, (cs, ds) in enumerate(mx):
        v = 0
        for j in cs:
            v ^= (c >> j) & 1
        for j in ds:
            v ^= (d >> j) & 1
        r |= v << i
    return r


def verilog(mx=None):
    mx = mx or matrix()
    lines = [
        "// SPDX-License-Identifier: BSD-3-Clause",
        "// 生成物（proj031 tools/gen_crc32.py）。手で直さない。反射 CRC-32（zlib.crc32 と同じ）を d の bit 0 から 32 bit ぶん進める",
        "function [31:0] crc32_d32(input [31:0] c, input [31:0] d);",
        "    begin",
    ]
    for i, (cs, ds) in enumerate(mx):
        terms = [f"c[{j}]" for j in sorted(cs)] + [f"d[{j}]" for j in sorted(ds)]
        lines.append(f"        crc32_d32[{i}] = {' ^ '.join(terms)};")
    lines += ["    end", "endfunction", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "src", "g24", "crc32_d32.vh")
    with open(out, "w") as f:
        f.write(verilog())
    print(f"書いた: {out}")
