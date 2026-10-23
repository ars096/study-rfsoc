#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 C-2 — cfft32 の整数の模型（tools/gen_cfft32.py が作る RTL と bit 単位で同じ）。

  前掛け: w_n = cmul(z_n + j·z_{n+32}, e^{jπn/64})（n = 0 は掛けない）、語長 ZW + 1
  32 点 DIF: 段 st（span = 16 >> st）で a' = a + b、b' = cmul(a − b, e^{+j2π·j/(2·span)})（j = 0 は掛けない、1/4 周は ×(+j)）
  cmul: (xr·CR − xi·CI + 2^16) >> 17、(xr·CI + xi·CR + 2^16) >> 17（>> は床の算術シフト）。係数は round(cos·(2^17 − 1)) など
  出口: F_m（m の自然順）
"""
import math

import numpy as np

CW = 18
N = 32


def tw(e_num, e_den, cw=CW):
    a = 2 * math.pi * e_num / e_den
    s = (1 << (cw - 1)) - 1
    return int(round(math.cos(a) * s)), int(round(math.sin(a) * s))


def cmul(xr, xi, cr, ci):
    h = 1 << (CW - 2)
    return (xr * cr - xi * ci + h) >> (CW - 1), (xr * ci + xi * cr + h) >> (CW - 1)


def cfft32(z):
    """z: 整数 (ブロック, 64)。戻り: F の実部・虚部 (ブロック, 32)（RTL の m_f と同じ値）"""
    z = np.asarray(z, dtype=object)
    nb = z.shape[0]
    out_r = np.empty((nb, N), dtype=np.int64)
    out_i = np.empty((nb, N), dtype=np.int64)
    pre = [tw(n, 128) for n in range(N)]
    for b in range(nb):
        vr = [0] * N
        vi = [0] * N
        for n in range(N):
            zr, zi = int(z[b, n]), int(z[b, n + 32])
            if n == 0:
                vr[n], vi[n] = zr, zi
            else:
                vr[n], vi[n] = cmul(zr, zi, *pre[n])
        for st in range(5):
            span = 16 >> st
            nr, ni = vr[:], vi[:]
            for blk in range(0, N, 2 * span):
                for j in range(span):
                    i0, i1 = blk + j, blk + j + span
                    ar, ai, br, bi = vr[i0], vi[i0], vr[i1], vi[i1]
                    nr[i0], ni[i0] = ar + br, ai + bi
                    dr, di = ar - br, ai - bi
                    e = j / (2 * span)
                    if j == 0:
                        nr[i1], ni[i1] = dr, di
                    elif abs(e - 0.25) < 1e-12:
                        nr[i1], ni[i1] = -di, dr
                    else:
                        nr[i1], ni[i1] = cmul(dr, di, *tw(j, 2 * span))
            vr, vi = nr, ni
        for m in range(N):
            bpos = int("{:05b}".format(m)[::-1], 2)
            out_r[b, m] = vr[bpos]
            out_i[b, m] = vi[bpos]
    return out_r, out_i
