#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj024 — 2G-1（1 ADC、FFT 262144 点 = 16 レーン × 16384 点）の固定小数点の鎖。bit 単位の定義の唯一の正。

RTL の proj の sim の正解の元にする（Wide の model/wide_model.py の fixed_chain と同じ役。写して使う）。
丸めは Wide と同じ rshift_round(v, s) = (v + 2^(s−1)) >> s（cmul の丸め）。README の M-8 と D-5・D-6・D-7。

  1. PFB の係数（D-6、線形補間）: 番地 i = t·N + n を左右で折り返し（i ≧ L/2 → i' = L − 1 − i）、s = i' >> 6・f = i' & 63、
       c[i] = (V[s]·64 + S[s]·f + 2^(G+5)) >> (G+6)、V[s] = round(h[64s]·2^(16+G))、S[s] = V[s+1] − V[s]（s = 0..8191）
     1 ビート m の 16 レーン p は同じ s（coef_beat）。
  2. PFB: y = sat15((Σ_t c[t·N + n]·x[(r − 3 + t)·N + n] + 2^15) >> 16)（Wide の wide_pfb と同じ。係数の出どころだけが違う）
  3. レーン FFT（IP、unscaled）: Y = rint(DFT(y))（29 bit に入る）
  4. Y の丸め（D-7）: Yd = (Y + 2) >> 2（27 bit、cmul の A ポート）
  5. ひねり係数（D-5、2 つの表の積）: k1 = hi·128 + lo、w = cmul(A[p][hi], B[p][lo], SH 16)、
       A[p][hi] = round(2^16·W_N^(p·128·hi))、B[p][lo] = round(2^16·W_N^(p·lo))
  6. V = cmul(Yd, w, SH 18)（25 bit）→ dft16（Wide と同じ、U 27・Z 29、k2 = 0..7）→ ch c = k1 + 16384·k2
  7. q = sat18(Z >>> SHIFT)（切り捨て、Wide の wide_chain と同じ）、p = q_re² + q_im²
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from g2_model import CF, LANES, T, design, quantize  # noqa: E402

N = 262144
M = N // LANES            # 16384（レーン FFT の点数 = 1 フレームのビート数）
L = T * N                 # 1,048,576 タップ
D = 64                    # 補間の区間
NSEG = L // 2 // D        # 8192（片側）
G = 5                     # 節の小数部の追加の bit（M-8a で決めた: 表の幅 35 bit ≦ 36 で RAMB36 8 個のまま、h に対する rms は最良に近い）
S_TW = 128                # ひねり係数の積の分け方 k1 = hi·S_TW + lo


def rshift_round(v, s):
    if s == 0:
        return v
    return (v + (1 << (s - 1))) >> s


# ---------------------------------------------------------------- 1. 係数の補間

def coef_tables(g=G):
    """節 V（8192）と傾き S（8192）。戻り値 (V, S) は int64。"""
    hs = design(N) * (1 << CF)
    node = np.round(hs[np.arange(NSEG + 1) * D] * (1 << g)).astype(np.int64)
    return node[:NSEG], node[1:] - node[:NSEG]


def coef_fold(V, S, g=G, i=None, fold_err=False):
    """番地 i（既定は全部）の係数。折り返しの式。fold_err = True は陽性対照（i' = L − i）。"""
    if i is None:
        i = np.arange(L, dtype=np.int64)
    ip = np.where(i >= L // 2, (L - i) if fold_err else (L - 1 - i), i)
    ip = np.clip(ip, 0, L // 2 - 1)
    s, f = ip >> 6, ip & 63
    return (V[s] * 64 + S[s] * f + (1 << (g + 5))) >> (g + 6)


def coef_beat(V, S, g=G):
    """RTL の形: ビート m・タップ t ごとに 1 つの s、16 レーンの f。戻り値 c[t, m, p]（= c[t·N + 16m + p]）。"""
    m = np.arange(M, dtype=np.int64)[:, None]
    p = np.arange(LANES, dtype=np.int64)[None, :]
    out = np.zeros((T, M, LANES), dtype=np.int64)
    for t in range(T):
        if t < 2:
            s = t * N // 64 + (m >> 2)
            f = 16 * (m & 3) + p
        else:
            s = (L - t * N) // 64 - (m >> 2) - 1
            f = 63 - 16 * (m & 3) - p
        s = np.broadcast_to(s, f.shape)
        out[t] = (V[s] * 64 + S[s] * f + (1 << (g + 5))) >> (g + 6)
    return out


def coef_interp(g=G):
    V, S = coef_tables(g)
    return coef_fold(V, S, g)


# ---------------------------------------------------------------- 5. ひねり係数の積

def _q16(z):
    return np.round(z.real * 65536).astype(np.int64), np.round(z.imag * 65536).astype(np.int64)


def tw_tables(s_tw=S_TW):
    """A[p, hi]・B[p, lo]（re, im）。p = 0..15（p = 0 は 1.0）。"""
    p = np.arange(LANES)[:, None]
    hi = np.arange(M // s_tw)[None, :]
    lo = np.arange(s_tw)[None, :]
    Ar, Ai = _q16(np.exp(-2j * np.pi * p * hi * s_tw / N))
    Br, Bi = _q16(np.exp(-2j * np.pi * p * lo / N))
    return Ar, Ai, Br, Bi


def cmul_q(ar, ai, wr, wi, s):
    return rshift_round(ar * wr - ai * wi, s), rshift_round(ar * wi + ai * wr, s)


def tw_prod(s_tw=S_TW, map_err=False):
    """w[p, k1]（re, im）。map_err = True は陽性対照（k1 = hi·(S−1) + lo として引く）。"""
    Ar, Ai, Br, Bi = tw_tables(s_tw)
    k1 = np.arange(M)
    if map_err:
        hi, lo = k1 // (s_tw - 1), k1 % (s_tw - 1)
        hi = np.minimum(hi, M // s_tw - 1)
    else:
        hi, lo = k1 // s_tw, k1 % s_tw
    return cmul_q(Ar[:, hi], Ai[:, hi], Br[:, lo], Bi[:, lo], 16)


def tw_direct():
    p = np.arange(LANES)[:, None]
    k1 = np.arange(M)[None, :]
    return _q16(np.exp(-2j * np.pi * p * k1 / N))


# ---------------------------------------------------------------- 2〜7. 鎖

J4 = [(1, 0), (0, -1), (-1, 0), (0, 1)]     # W4^e


def w16_q():
    return _q16(np.exp(-2j * np.pi * np.arange(16) / 16))


def pfb_int(x, c, YW=15):
    """x（int、長さ N の倍数）→ y（(nf, N)、YW bit で飽和）と飽和の数。"""
    nf = len(x) // N
    xf = np.asarray(x[: nf * N], dtype=np.int64).reshape(nf, N)
    ct = c.reshape(T, N)
    acc = np.zeros((nf, N), dtype=np.int64)
    for t in range(T):
        sh = T - 1 - t
        acc[sh:] += ct[t] * xf[: nf - sh]
    y = rshift_round(acc, CF)
    lo, hi = -(1 << (YW - 1)), (1 << (YW - 1)) - 1
    nsat = int(np.sum((y < lo) | (y > hi)))
    return np.clip(y, lo, hi), nsat


def chain_frame(yf, twr, twi, d1=2, sh=18, stats=None):
    """1 フレームの y（長さ N）→ Z（re, im、(8, M)、ch c = k1 + M·k2）。"""
    yp = yf.reshape(M, LANES).T
    Yc = np.fft.fft(yp.astype(np.float64), axis=1)
    Yr, Yi = np.rint(Yc.real).astype(np.int64), np.rint(Yc.imag).astype(np.int64)
    Ydr, Ydi = rshift_round(Yr, d1), rshift_round(Yi, d1)
    Vr, Vi = cmul_q(Ydr, Ydi, twr, twi, sh)
    Vr4, Vi4 = Vr.reshape(4, 4, M), Vi.reshape(4, 4, M)
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
    Zr = np.zeros((8, M), dtype=np.int64)
    Zi = np.zeros((8, M), dtype=np.int64)
    for cc in range(4):
        for d in range(2):
            for b in range(4):
                er, ei = J4[(b * d) % 4]
                Zr[cc + 4 * d] += er * Tr[b, cc] - ei * Ti[b, cc]
                Zi[cc + 4 * d] += er * Ti[b, cc] + ei * Tr[b, cc]
    if stats is not None:
        for k, v in (("Y", (Yr, Yi)), ("Yd", (Ydr, Ydi)), ("V", (Vr, Vi)), ("U", (Ur, Ui)), ("Z", (Zr, Zi))):
            stats[k] = max(stats.get(k, 0), int(np.abs(v[0]).max()), int(np.abs(v[1]).max()))
    return Zr, Zi


def power(Zr, Zi, shift):
    """q = sat18(Z >>> SHIFT)、p = q_re² + q_im²。戻り値 (p, 飽和の数)。"""
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
