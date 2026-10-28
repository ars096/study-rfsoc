#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj029 1: libs45fast.so（s45fast.c）の ctypes の包み。正解は s45acq.Acq._spec_record_full の中身と CRC（README の 1.）

- spec_f32(spec, hd) → (f32 の配列（IF の昇順 = spec の逆順）, crc)。2^53 以上なら P.f32_round と同じ ValueError
- spec_u64(spec, hd) → (u64 の配列（逆順）, crc)
- out を渡すとそこに書く（周ごとの確保を避ける）。posctl は陽性対照（1 = 0 への切り捨て、2 = 逆順にしない）
- ring_acc(rec, acc, first) → crc_pl（proj036: 束ねの 1 本をリングの上から器へ写す・足す）
"""
import ctypes
import os

import numpy as np

PC_TRUNC, PC_NOREV = 1, 2
PC_NOACC = 1                     # proj036: ring_acc の陽性対照（足さずに写す）

_L = ctypes.CDLL(os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs45fast.so"))
_vp, _sz, _u32p = ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint32)
for _f in (_L.s45_spec_f32, _L.s45_spec_u64):
    _f.argtypes = [_vp, _sz, ctypes.c_char_p, _sz, _vp, _u32p, ctypes.c_int]
    _f.restype = ctypes.c_int
_L.s45_ring_spec.argtypes = [_vp, _sz, ctypes.c_char_p, _sz, _vp, ctypes.c_int, _u32p, _u32p, ctypes.c_int]
_L.s45_ring_spec.restype = ctypes.c_int
_L.s45_ring_acc.argtypes = [_vp, _sz, _vp, ctypes.c_int, _u32p, ctypes.c_int]
_L.s45_ring_acc.restype = None
_L.s45_crc32.argtypes = [ctypes.c_uint32, _vp, _sz]
_L.s45_crc32.restype = ctypes.c_uint32
_L.s45_hw_crc.restype = ctypes.c_int
_L.s45_nop.restype = None

HW_CRC = bool(_L.s45_hw_crc())


def _in(spec):
    a = np.asarray(spec)
    if a.dtype != np.uint64 or not a.flags.c_contiguous:
        a = np.ascontiguousarray(a, np.uint64)
    return a


def spec_f32(spec, hd, out=None, posctl=0):
    a = _in(spec)
    if out is None:
        out = np.empty(a.size, np.float32)
    c = ctypes.c_uint32()
    if _L.s45_spec_f32(a.ctypes.data, a.size, hd, len(hd), out.ctypes.data, ctypes.byref(c), posctl):
        raise ValueError("u64 が 2^53 以上（float64 で厳密でない）")
    return out, c.value


def spec_u64(spec, hd, out=None, posctl=0):
    a = _in(spec)
    if out is None:
        out = np.empty(a.size, np.uint64)
    c = ctypes.c_uint32()
    _L.s45_spec_u64(a.ctypes.data, a.size, hd, len(hd), out.ctypes.data, ctypes.byref(c), posctl)
    return out, c.value


def ring_spec(rec, hd, fmt, out=None, posctl=0):
    """proj029 2: PL のリングの上のレコード（plring.LazyRec）から記録を作る。fmt "f32" / "u64"。
    → (data（逆順）, crc（頭 hd ＋ data）, crc_pl（PL の頭 ＋ 中身。尾の CRC と照らすのは呼び手）)"""
    f = 1 if fmt == "f32" else 0
    if out is None:
        out = np.empty(rec.n, np.float32 if f else np.uint64)
    c, cp = ctypes.c_uint32(), ctypes.c_uint32()
    if _L.s45_ring_spec(rec.addr, rec.n, hd, len(hd), out.ctypes.data, f, ctypes.byref(c), ctypes.byref(cp), posctl):
        raise ValueError("u64 が 2^53 以上（float64 で厳密でない）")
    return out, c.value, cp.value


def ring_acc(rec, acc, first, posctl=0):
    """proj036: PL のリングの上のレコード（plring.LazyRec）を器 acc（np.uint64 × rec.n、C の連続）へ。first なら写す、でなければ足す。
    → crc_pl（PL の頭 ＋ 中身の CRC。尾の CRC と照らすのは呼び手）"""
    if acc.dtype != np.uint64 or acc.size != rec.n or not acc.flags.c_contiguous:
        raise ValueError(f"器は np.uint64 × {rec.n} の連続な配列")
    cp = ctypes.c_uint32()
    _L.s45_ring_acc(rec.addr, rec.n, acc.ctypes.data, 1 if first else 0, ctypes.byref(cp), posctl)
    return cp.value


def crc32(buf, init=0):
    """zlib.crc32(buf, init) と同じ（buf は C の連続な bytes-like）"""
    b = np.frombuffer(memoryview(buf).cast("B"), np.uint8)
    return int(_L.s45_crc32(init, b.ctypes.data, b.size))


def nop():
    _L.s45_nop()
