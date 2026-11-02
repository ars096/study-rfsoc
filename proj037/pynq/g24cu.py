#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj031 — 2G-4 の共有の係数 URAM（g24_cu）に書く中身を作る（PS の側。numpy だけ）。

係数の値は proj030 の g24_coef（線形補間）と bit 単位で同じ。補間の表（src/g24/g24_coef_lo.hex・hi.hex、{S 13 bit, V 22 bit}）から
model/g24_fixed.py の coef_beat と同じ式で作る（窓の設計 design() は使わない）。model/cu_model.py が coef_beat と照らす。

行 m（0..4095）= 16 レーン × {t 0, t 1} × 18 bit = 576 bit。係数 j = 2p + t が [18j +: 18]。
t 3・t 2 は 行 4095 − m・レーン 15 − p の t 0・t 1（対称性。g24_cu の 2 ポート目が読む）。
1 行は 18 語 × 32 bit（bit k が語 k div 32 の bit k mod 32）。CRC は 4096 行を 72 バイト（bit k がバイト k div 8 の bit k mod 8）ずつ並べた zlib.crc32。
"""
import zlib

import numpy as np

M = 4096
LANES = 16
VW, SW, G = 22, 13, 4
CW = 18
NWORD = 18          # 576 / 32


def _sext(v, w):
    v = v & ((1 << w) - 1)
    return np.where(v >= (1 << (w - 1)), v - (1 << w), v)


def read_table(path):
    """補間の表の hex（1024 行）→ (V, S)（int64）。"""
    with open(path) as f:
        w = np.array([int(s, 16) for s in f.read().split()], dtype=np.int64)
    if w.size != 1024:
        raise ValueError(f"{path}: {w.size} 行（1024 のはず）")
    return _sext(w, VW), _sext(w >> VW, SW)


def rows(lo_path, hi_path):
    """係数の行（4096 × 16 × 2、int64）。[m, p, t] は c[t·N + 16m + p]（t 0・1）。"""
    Vl, Sl = read_table(lo_path)
    Vh, Sh = read_table(hi_path)
    m = np.arange(M, dtype=np.int64)[:, None]
    p = np.arange(LANES, dtype=np.int64)[None, :]
    a = m >> 2
    f = 16 * (m & 3) + p
    out = np.empty((M, LANES, 2), dtype=np.int64)
    for t, (V, S) in enumerate(((Vl, Sl), (Vh, Sh))):
        out[:, :, t] = (V[a] * 64 + S[a] * f + (1 << (G + 5))) >> (G + 6)
    return out


def read2(r, m):
    """g24_cu の 2 ポートの読みの組み立て（模型）。戻り値 [p, t]（t 0..3）。"""
    A, B = r[m], r[M - 1 - m][::-1]
    return np.stack([A[:, 0], A[:, 1], B[:, 1], B[:, 0]], axis=1)


def row_bytes(r):
    """行 → 72 バイト（4096 × 72、uint8）。"""
    c = (r.reshape(M, 2 * LANES) & ((1 << CW) - 1)).astype(np.uint64)
    bits = ((c[:, :, None] >> np.arange(CW, dtype=np.uint64)) & 1).astype(np.uint8).reshape(M, 2 * LANES * CW)
    return np.packbits(bits, axis=1, bitorder="little")


def words(r):
    """行 → 18 語（4096 × 18、uint32）。g24_cu の DATA[0..17] に書く値。"""
    return np.ascontiguousarray(row_bytes(r)).view("<u4")


def unwords(w):
    """18 語 → 行（words の逆。往復の確かめ用）。"""
    bits = np.unpackbits(np.ascontiguousarray(w, dtype="<u4").view(np.uint8), axis=1, bitorder="little")
    c = (bits.reshape(M, 2 * LANES, CW).astype(np.int64) << np.arange(CW)).sum(axis=2)
    return _sext(c, CW).reshape(M, LANES, 2)


def crc(r):
    return zlib.crc32(row_bytes(r).tobytes()) & 0xFFFFFFFF


# ---------------------------------------------------------------- PL へ書く（g24_cu_0、src/g24/g24_cu.v のレジスタ）

CU_ID = 0x6375_0001
R_ID, R_PROJ, R_CTRL, R_ROW, R_COEF_CRC, R_CRC, R_NROW, R_DATA = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x40
ST_OK, ST_VBUSY, ST_VDONE, ST_VMIS, ST_WROTE = 1, 2, 4, 8, 16


class CuError(RuntimeError):
    pass


def status(mm):
    return dict(stat=int(mm.read(R_CTRL)) & 0x1F, crc=int(mm.read(R_CRC)) & 0xFFFFFFFF,
                coef_crc=int(mm.read(R_COEF_CRC)) & 0xFFFFFFFF, nrow=int(mm.read(R_NROW)) & 0xFFFF)


def load(mm, lo_path, hi_path, proj_expect, timeout=0.5, log=print):
    """係数を書いて VERIFY し、OK を確かめる。戻り値は status() に時間を足したもの。合わなければ CuError。

    PS が作った係数の CRC と、bit に焼き込まれた COEF_CRC を**書く前に**照らす（違えば、この bit が想定する係数ではない）。
    書いた後は PL が URAM を読み直して CRC を取り、COEF_CRC と一致したら OK を立てる（g24_cu）。PS は STAT と CRC を読んで照らすだけ。"""
    import time
    cid, proj = int(mm.read(R_ID)) & 0xFFFFFFFF, int(mm.read(R_PROJ)) & 0xFFFFFFFF
    if cid != CU_ID:
        raise CuError(f"g24_cu_0 の ID {cid:#010x}（期待 {CU_ID:#010x}）")
    if proj != proj_expect:
        raise CuError(f"g24_cu_0 の PROJ {proj:#010x}（期待 {proj_expect:#010x}）")
    r = rows(lo_path, hi_path)
    w = words(r)
    want = crc(r)
    coef_crc = int(mm.read(R_COEF_CRC)) & 0xFFFFFFFF
    if coef_crc != want:
        raise CuError(f"bit の COEF_CRC {coef_crc:#010x} が PS の係数の CRC {want:#010x} と違う（hex の版が bit と食い違っている）")
    t0 = time.time()
    mm.write(R_CTRL, 2)                                 # CLR
    for m in range(M):
        row = w[m]
        for k in range(NWORD):
            mm.write(R_DATA + 4 * k, int(row[k]))
        mm.write(R_ROW, m)
    t1 = time.time()
    st = status(mm)
    if st["nrow"] != M:
        raise CuError(f"NROW {st['nrow']}（期待 {M}）")
    mm.write(R_CTRL, 1)                                 # VERIFY（4096 × 21 拍 ≒ 336 µs）
    while int(mm.read(R_CTRL)) & ST_VBUSY:
        if time.time() - t1 > timeout:
            raise CuError("VERIFY が終わらない")
    st = status(mm)
    st.update(t_write=t1 - t0, t_verify=time.time() - t1)
    if (st["stat"] & 0xF) != (ST_OK | ST_VDONE) or st["crc"] != want:
        raise CuError(f"VERIFY の後 STAT {st['stat']:#04x}・CRC {st['crc']:#010x}（期待 OK・終えた・CRC {want:#010x}）")
    log(f"係数 URAM: 4096 行を {st['t_write']:.2f} s で書き、VERIFY 通過（CRC {st['crc']:#010x}、STAT {st['stat']:#04x}）")
    return st


def check_ok(mm):
    """START の前に読み直す（OK が立ったままか。書きや VERIFY が挟まると落ちる）"""
    st = status(mm)
    if not st["stat"] & ST_OK:
        raise CuError(f"係数 URAM の OK が 0（STAT {st['stat']:#04x}）。書き直して VERIFY する")
    return st
