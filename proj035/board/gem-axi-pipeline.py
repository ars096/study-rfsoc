#!/usr/bin/env python3
"""GEM1（eth0, 0xFF0C0000）の AXI_MAX_PIPELINE を 0x0102 にする（proj035）。

下の byte が読み（送信で DDR から読む）、上の byte が書き（受信で DDR に書く）の、出しっぱなしにできる AXI の要求の数。
既定の 0x0101 だと送り出しが ≒ 194 Mbit/s で止まる。読みを 2 本（0x0102）で ≒ 350 Mbit/s。
読みを 4 本以上にすると送り出しは速くなる（4 本 403・8 本 420 Mbit/s）が、CPU の DDR の読みの遅れが増え
（8 本・130 Mbit/s の送り出しで 151 → 190 ns）、2G-4 の取得（ネットワークの tint 30.72 ms）が追いつかなくなる。
0x2020 は GEM が止まる。書いた後に読み返し、違えば 1 で終わる（systemd の状態に failed で出る）。
"""
import mmap
import os
import struct
import sys

GEM1_BASE = 0xFF0C0000
AXI_MAX_PIPELINE = 0x054
WANT = 0x0102

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=GEM1_BASE)
before = struct.unpack("<I", m[AXI_MAX_PIPELINE:AXI_MAX_PIPELINE + 4])[0]
m[AXI_MAX_PIPELINE:AXI_MAX_PIPELINE + 4] = struct.pack("<I", WANT)
after = struct.unpack("<I", m[AXI_MAX_PIPELINE:AXI_MAX_PIPELINE + 4])[0]
print(f"gem1 AXI_MAX_PIPELINE {before:#06x} -> {after:#06x}")
sys.exit(0 if after == WANT else 1)
