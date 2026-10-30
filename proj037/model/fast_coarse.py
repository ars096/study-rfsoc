#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 R-1 — 荒い段（coarse_pfb → cfft32 → coarse_post）の bit 単位の模型を、ブロックの軸でベクトルにしたもの。

  式は coarse_pfb_ref・cfft32_ref・coarse_post_ref と同じ（照合は r1_lines.py --check）。
  float=True で、同じ係数・同じ詰め替えのまま丸め（>> と飽和）だけを抜いた浮動小数点の値を返す（丸めの誤差 e を取るため）。
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from coarse_pfb_ref import gtable, M, TC, SH, ZW  # noqa: E402
from cfft32_ref import tw, CW  # noqa: E402

L = M * TC
N = 32


def zblocks(x, nblk, g=None, float_=False):
    """z（ブロック × 64）。float_ なら丸め・飽和の前の値 / 2^SH"""
    if g is None:
        g = gtable()
    dt = np.float64 if (float_ and np.asarray(x).dtype.kind == "f") else np.int64     # 丸めない版は x も実数のまま受ける
    x = np.asarray(x, dt)
    xp = np.concatenate([np.zeros(L, dt), x])
    m = np.arange(nblk)[:, None]
    r = np.arange(M)[None, :]
    s = np.zeros((nblk, M), dt)
    for t in range(TC):
        s += g[M * t:M * t + M][None, :] * xp[L + 56 * m + 55 - r - M * t]
    if float_:
        return s / float(1 << SH)
    lim = 2 ** (ZW - 1) - 1
    return np.clip((s + (1 << (SH - 1))) >> SH, -lim, lim)


def _cmul(xr, xi, cr, ci, float_, noround=False):
    if float_:
        d = float(1 << (CW - 1))
        return (xr * cr - xi * ci) / d, (xr * ci + xi * cr) / d
    h = 0 if noround else 1 << (CW - 2)
    return (xr * cr - xi * ci + h) >> (CW - 1), (xr * ci + xi * cr + h) >> (CW - 1)


def cfft32(z, float_=False, noround=False):
    """z（ブロック × 64）→ F の実部・虚部（ブロック × 32、m の自然順）。cfft32_ref と同じ段"""
    vr = [None] * N
    vi = [None] * N
    for n in range(N):
        zr, zi = z[:, n], z[:, n + 32]
        if n == 0:
            vr[n], vi[n] = zr, zi
        else:
            vr[n], vi[n] = _cmul(zr, zi, *tw(n, 128), float_, noround)
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
                    nr[i1], ni[i1] = _cmul(dr, di, *tw(j, 2 * span), float_, noround)
        vr, vi = nr, ni
    perm = [int("{:05b}".format(m)[::-1], 2) for m in range(N)]
    return np.stack([vr[p] for p in perm], axis=1), np.stack([vi[p] for p in perm], axis=1)


def ymap(fr, fi):
    """Y_{2m} = F_m、Y_{2m+1} = conj(F_{31−m})（coarse_post_ref と同じ）"""
    idx = np.array([k // 2 if k % 2 == 0 else 31 - (k - 1) // 2 for k in range(N)])
    sgn = np.array([1 if k % 2 == 0 else -1 for k in range(N)])
    return fr[:, idx], fi[:, idx] * sgn[None, :]


def post(yr, yi, gains, float_=False):
    g = np.asarray(gains, np.int64)[None, :]
    if float_:
        return yr * g / 65536.0, yi * g / 65536.0
    rr = (yr * g + (1 << 15)) >> 16
    ri = (yi * g + (1 << 15)) >> 16
    return np.clip(rr, -127, 127), np.clip(ri, -127, 127)


def chain(x, nblk, gains=None, float_=False, noround=False):
    """x → (Y 24 bit の前の値, y 8 bit)。Y は実部・虚部の組"""
    z = zblocks(x, nblk, float_=float_)
    fr, fi = cfft32(z, float_=float_, noround=noround)
    yr, yi = ymap(fr, fi)
    if gains is None:
        return (yr, yi), None
    return (yr, yi), post(yr, yi, gains, float_=float_)


def gains_for(yr, yi, S=12.0, skip=32):
    """ch ごとに 8 bit の各成分の σ が S になる利得（M-3 と同じ決め方）"""
    sig = np.sqrt(np.mean(yr[skip:].astype(float) ** 2 + yi[skip:].astype(float) ** 2, axis=0) / 2)
    return np.clip(np.round(S / sig * 65536).astype(np.int64), 1, 2 ** 17 - 1)


