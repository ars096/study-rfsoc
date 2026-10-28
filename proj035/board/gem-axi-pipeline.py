#!/usr/bin/env python3
"""GEM1（eth0, 0xFF0C0000）の AXI_MAX_PIPELINE を 0x0808 にする（proj035）。

既定の 0x0101（AXI の要求が読み書き 1 本ずつ）だと送り出しが ≒ 200 Mbit/s で止まる。
0x0808 で ≒ 424 Mbit/s。0x2020 は GEM が止まるので、0x0808 より大きくしない。
書いた後に読み返し、違えば 1 で終わる（systemd の状態に failed で出る）。
"""
import mmap
import os
import struct
import sys

GEM1_BASE = 0xFF0C0000
AXI_MAX_PIPELINE = 0x054
WANT = 0x0808

fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
m = mmap.mmap(fd, 0x1000, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=GEM1_BASE)
before = struct.unpack("<I", m[AXI_MAX_PIPELINE:AXI_MAX_PIPELINE + 4])[0]
m[AXI_MAX_PIPELINE:AXI_MAX_PIPELINE + 4] = struct.pack("<I", WANT)
after = struct.unpack("<I", m[AXI_MAX_PIPELINE:AXI_MAX_PIPELINE + 4])[0]
print(f"gem1 AXI_MAX_PIPELINE {before:#06x} -> {after:#06x}")
sys.exit(0 if after == WANT else 1)
