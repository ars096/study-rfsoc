#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F — 細かい側（荒い ch 1 本、N_f 131072 点 = 16 レーン × 8192 点、複素の入力）の固定小数点の鎖。bit 単位の定義の唯一の正。

proj024 の model/g21_fixed.py（cbf0674、2G-1: 実数の入力・262144 点）を写して直したもの。違い:
  - N = 131072、M = 8192（レーン FFT の点数 = 1 フレームのビート数）、L = 4N、片側の区間 4096（係数の表は前半・後半 2048 ずつ）
  - 係数の傾き S は 13 bit（N が半分で 1 区間あたりの変化が倍）。G 5 のまま、表の幅 23 ＋ 13 = 36 bit
  - 入力は複素の 8 bit（荒い段の出口、S 12）。PFB は実部・虚部に同じ係数。y = sat15((Σ c·x + 2^11) >> 12)（端数を 4 bit 残す。
    8 bit の LSB のまま丸めると 2 度目の量子化で損失が倍になる）
  - レーン FFT の出口 Y は 28 bit → Yd = (Y + 1) >> 1（d1 = 1、27 bit）
  - ひねり係数 W_N^(p·k1)、k1 = hi·128 + lo（hi 0..63）
  - dft16 は 16 出力（k2 = 0..15、複素の入力なので全部）。bin b = k1 + 8192·k2（N 点の DFT の番号）
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from m4_stitch import design  # noqa: E402

LANES, T = 16, 4
CF = 16
N = 131072
M = N // LANES            # 8192
L = T * N
D = 64
NSEG = L // 2 // D        # 4096（片側）
G = 5
VW, SW = 23, 13
S_TW = 128
XW, SHY, YW = 8, 12, 15


def rshift_round(v, s):
    if s == 0:
        return v
    return (v + (1 << (s - 1))) >> s


def coef_tables(g=G):
    hs = design(N) * (1 << CF)
    node = np.round(hs[np.arange(NSEG + 1) * D] * (1 << g)).astype(np.int64)
    V, S = node[:NSEG], node[1:] - node[:NSEG]
    assert V.max() < (1 << (VW - 1)) and V.min() >= -(1 << (VW - 1))
    assert S.max() < (1 << (SW - 1)) and S.min() >= -(1 << (SW - 1))
    return V, S


def coef_beat(V, S, g=G, frac_err=False):
    """c[t, m, p]（= c[t·N + 16m + p]）。frac_err: 陽性対照（t 2・3 の端数を折り返さない）"""
    m = np.arange(M, dtype=np.int64)[:, None]
    p = np.arange(LANES, dtype=np.int64)[None, :]
    out = np.zeros((T, M, LANES), dtype=np.int64)
    for t in range(T):
        if t < 2:
            s = t * N // 64 + (m >> 2)
            f = 16 * (m & 3) + p
        else:
            s = (L - t * N) // 64 - (m >> 2) - 1
            f = (16 * (m & 3) + p) if frac_err else (63 - 16 * (m & 3) - p)
        s = np.broadcast_to(s, f.shape)
        out[t] = (V[s] * 64 + S[s] * f + (1 << (g + 5))) >> (g + 6)
    return out


def pfb_frames(xr, xi, c):
    """xr・xi（int、1 本の ch の流れ、長さ N の倍数、先頭から履歴 0）→ yr・yi（(nf, N)、YW bit）・飽和の数。
    c は coef_beat の形 (T, M, 16) → (T, N)（n = 16m + p）"""
    ct = c.reshape(T, N)
    out = []
    nsat = 0
    lo, hi = -(1 << (YW - 1)), (1 << (YW - 1)) - 1
    for x in (xr, xi):
        nf = len(x) // N
        xf = np.asarray(x[: nf * N], dtype=np.int64).reshape(nf, N)
        acc = np.zeros((nf, N), dtype=np.int64)
        for t in range(T):
            sh = T - 1 - t
            acc[sh:] += ct[t] * xf[: nf - sh]
        y = rshift_round(acc, SHY)
        nsat += int(np.sum((y < lo) | (y > hi)))
        out.append(np.clip(y, lo, hi))
    return out[0], out[1], nsat


def _q16(z):
    return np.round(z.real * 65536).astype(np.int64), np.round(z.imag * 65536).astype(np.int64)


def tw_tables(s_tw=S_TW):
    p = np.arange(LANES)[:, None]
    hi = np.arange(M // s_tw)[None, :]
    lo = np.arange(s_tw)[None, :]
    Ar, Ai = _q16(np.exp(-2j * np.pi * p * hi * s_tw / N))
    Br, Bi = _q16(np.exp(-2j * np.pi * p * lo / N))
    return Ar, Ai, Br, Bi


def cmul_q(ar, ai, wr, wi, s):
    return rshift_round(ar * wr - ai * wi, s), rshift_round(ar * wi + ai * wr, s)


def tw_prod(s_tw=S_TW):
    Ar, Ai, Br, Bi = tw_tables(s_tw)
    k1 = np.arange(M)
    hi, lo = k1 // s_tw, k1 % s_tw
    return cmul_q(Ar[:, hi], Ai[:, hi], Br[:, lo], Bi[:, lo], 16)


J4 = [(1, 0), (0, -1), (-1, 0), (0, 1)]


def w16_q():
    return _q16(np.exp(-2j * np.pi * np.arange(16) / 16))


def lane_fft(yr, yi):
    """1 フレームの y（長さ N、複素）→ Y（re, im、(16, M)、[p, k1]）。IP（unscaled）は rint"""
    yp = (yr.astype(np.float64) + 1j * yi.astype(np.float64)).reshape(M, LANES).T
    Yc = np.fft.fft(yp, axis=1)
    return np.rint(Yc.real).astype(np.int64), np.rint(Yc.imag).astype(np.int64)


def chain_Y(Yr, Yi, twr, twi, d1=1, sh=18):
    """Y（(16, M)）→ Z（re, im、(16, M)、bin b = k1 + M·k2）"""
    Ydr, Ydi = rshift_round(Yr, d1), rshift_round(Yi, d1)
    Vr, Vi = cmul_q(Ydr, Ydi, twr, twi, sh)
    Vr4, Vi4 = Vr.reshape(4, 4, M), Vi.reshape(4, 4, M)          # [a, b]: p = 4a + b
    Ur = np.zeros((4, 4, M), dtype=np.int64)
    Ui = np.zeros((4, 4, M), dtype=np.int64)
    for cc in range(4):
        for a in range(4):
            er, ei = J4[(a * cc) % 4]
            Ur[:, cc] += er * Vr4[a] - ei * Vi4[a]
            Ui[:, cc] += er * Vi4[a] + ei * Vr4[a]
    wr16, wi16 = w16_q()
    Tr, Ti = np.zeros_like(Ur), np.zeros_like(Ui)
    for b in range(4):
        for cc in range(4):
            Tr[b, cc], Ti[b, cc] = cmul_q(Ur[b, cc], Ui[b, cc], wr16[b * cc], wi16[b * cc], 16)
    Zr = np.zeros((16, M), dtype=np.int64)
    Zi = np.zeros((16, M), dtype=np.int64)
    for cc in range(4):
        for d in range(4):
            for b in range(4):
                er, ei = J4[(b * d) % 4]
                Zr[cc + 4 * d] += er * Tr[b, cc] - ei * Ti[b, cc]
                Zi[cc + 4 * d] += er * Ti[b, cc] + ei * Tr[b, cc]
    return Zr, Zi


def power(Zr, Zi, shift):
    lo, hi = -(1 << 17), (1 << 17) - 1
    qr, qi = Zr >> shift, Zi >> shift
    nsat = int(np.sum((qr < lo) | (qr > hi) | (qi < lo) | (qi > hi)))
    qr, qi = np.clip(qr, lo, hi), np.clip(qi, lo, hi)
    return qr * qr + qi * qi, nsat


def bitrev(n, bits):
    r = np.zeros_like(n)
    for b in range(bits):
        r |= ((n >> b) & 1) << (bits - 1 - b)
    return r
