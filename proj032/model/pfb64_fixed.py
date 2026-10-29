#!/usr/bin/env python3
"""proj032 P-5 — 粗い PFB（pfb64_core）の整数の模型。RTL と bit 単位で同じ値を出す。

  y = pfb64_fixed(x16, ks, cnt)   x16: ADC の 16 bit（整数の 1 次元配列）、ks: 頭ごとの粗い ch k（0..32）
                                  戻り値 (yr, yi): (フレーム, 頭) の整数（Q = YF）。フレーム m = 0 は x の最初の 192 個で作る（p = 16m + 191）

RTL の段（src/spw/pfb64_core.v）をそのまま整数で:
  1. x14 = x16 >>> 2、分岐の和 s_r[m] = Σ_t H[r + 64t]·x14[p − r − 64t]（H = round(h·2^SH)）→ u = sat_UW((s + 2^(SH−UF−1)) >>> (SH − UF))
  2. 偶の z[a] = u[4a] + j·u[4a+1]、奇の z[a] = u[4a+2] + j·u[4a+3] を dft16f（4 × 4 の分解・cmul の丸め）に → E[k]・O[k]
  3. T[k] = W32^k·O[k]（cmul、k = 0・8 は自明）、Z[k] = E[k] + T[k]、Z[k+16] = E[k] − T[k]
  4. 頭ごとに A = Z[k] + conj(Z[32−k])、B = Z[k] − conj(Z[32−k])、X = conj(A + (−j·W64^k)·B)（cmul 1 個）
  5. (−j)^((k·m) mod 4) → y = sat_YW((X + 2^(SH2−1)) >>> SH2)、SH2 = UF + 1 − YF
cmul（src/common/cmul.v）: y = (a·w + 2^15) >>> 16、w は 18 bit（2^16 = 1.0）。
係数は runs/m0_coef.json と式から作り、src/spw/pfb64_coef.vh の値と一致することを load() で確かめる（RTL と模型が同じ表を見ていることの照合）。
途中の語幅（dft16f の U 23・Z 25、回転 25、Z 26、A・B 27、X 28）は RTL では巻き戻る。模型は巻き戻りを数え（cnt["wrap_*"]）、0 であることを求める。
"""
import json
import math
import os
import re

import numpy as np

UF, UW, YF, YW = 10, 21, 8, 24
HERE = os.path.dirname(os.path.abspath(__file__))


def wq(e, n):
    """exp(−j2π e / n) を 18 bit（2^16 = 1.0）に丸めた値。"""
    return int(round(65536 * math.cos(2 * math.pi * e / n))), int(round(-65536 * math.sin(2 * math.pi * e / n)))


def _vh_list(txt, name):
    m = re.search(r"localparam \[[^\]]*\] " + name + r" = \{([^}]*)\}", txt)
    v = [int(s.replace("18'sd", "").replace(" ", "")) for s in m.group(1).split(",")]
    return v[::-1]                       # Verilog の {} は先頭が最上位 = 番号の大きいほう


def load():
    co = json.load(open(os.path.join(HERE, "..", "runs", "m0_coef.json")))["pfb"]
    H = np.array(co["coef"], dtype=np.int64)
    sh = int(co["shift"])
    tw = [wq(k, 32) for k in range(16)]
    post = []
    for k in range(33):
        c, s = wq(k, 64)                 # W64^k = c + j·s（s は −sin）
        post.append((s, -c))             # −j·(c + j s) = s − j c
    vh = open(os.path.join(HERE, "..", "src", "spw", "pfb64_coef.vh")).read()
    assert int(re.search(r"PFB64_SH = (\d+)", vh).group(1)) == sh, "PFB64_SH"
    assert _vh_list(vh, "PFB64_H") == list(H), "PFB64_H"
    assert _vh_list(vh, "TW32_R") == [t[0] for t in tw] and _vh_list(vh, "TW32_I") == [t[1] for t in tw], "TW32"
    assert _vh_list(vh, "POST64_WR") == [p[0] for p in post] and _vh_list(vh, "POST64_WI") == [p[1] for p in post], "POST64"
    return dict(H=H, sh=sh, tw=tw, post=post)


def rsh(a, k):
    return (a + (1 << (k - 1))) >> k


def sat(a, w, cnt, key):
    lo, hi = -(1 << (w - 1)), (1 << (w - 1)) - 1
    n = int(np.count_nonzero((a < lo) | (a > hi)))
    if n:
        cnt[key] = cnt.get(key, 0) + n
    return np.clip(a, lo, hi)


def fits(a, w, cnt, key):
    lo, hi = -(1 << (w - 1)), (1 << (w - 1)) - 1
    n = int(np.count_nonzero((a < lo) | (a > hi)))
    if n:
        cnt["wrap_" + key] = cnt.get("wrap_" + key, 0) + n
    return a


def cmul(ar, ai, wr, wi):
    return (ar * wr - ai * wi + (1 << 15)) >> 16, (ar * wi + ai * wr + (1 << 15)) >> 16


def dft16f(zr, zi, uw, zw, cnt):
    """(F, 16) → (F, 16)。src/common/dft16f.v と同じ: 段 1 の 4 点（加減算）→ W16^(b·c)（cmul、0・4 は自明）→ 段 3 の 4 点。"""
    def dft4(x):
        (r0, i0), (r1, i1), (r2, i2), (r3, i3) = x
        return [(r0 + r1 + r2 + r3, i0 + i1 + i2 + i3), (r0 + i1 - r2 - i3, i0 - r1 - i2 + r3),
                (r0 - r1 + r2 - r3, i0 - i1 + i2 - i3), (r0 - i1 - r2 + i3, i0 + r1 - i2 - r3)]
    T = {}
    for b in range(4):
        U = dft4([(zr[:, 4 * a + b], zi[:, 4 * a + b]) for a in range(4)])
        for c in range(4):
            ur, ui = fits(U[c][0], uw, cnt, "u16"), fits(U[c][1], uw, cnt, "u16")
            e = b * c
            if e == 0:
                tr, ti = ur, ui
            elif e == 4:
                tr, ti = ui, -ur
            else:
                tr, ti = cmul(ur, ui, *wq(e, 16))
            T[(b, c)] = (fits(tr, uw, cnt, "t16"), fits(ti, uw, cnt, "t16"))
    Zr = np.empty(zr.shape, dtype=np.int64)
    Zi = np.empty_like(Zr)
    for c in range(4):
        Y = dft4([T[(b, c)] for b in range(4)])
        for d in range(4):
            Zr[:, c + 4 * d] = fits(Y[d][0], zw, cnt, "z16")
            Zi[:, c + 4 * d] = fits(Y[d][1], zw, cnt, "z16")
    return Zr, Zi


def pfb64_fixed(x16, ks, cnt, co=None):
    co = co or load()
    x = np.asarray(x16, dtype=np.int64) >> 2
    nf = (len(x) - 192) // 16 + 1
    p = np.arange(nf) * 16 + 191
    H, sh = co["H"], co["sh"]
    u = np.zeros((nf, 64), dtype=np.int64)
    for r in range(64):
        s = H[r] * x[p - r] + H[r + 64] * x[p - r - 64] + H[r + 128] * x[p - r - 128]
        u[:, r] = sat(rsh(s, sh - UF), UW, cnt, "u")
    DW = UW + 4
    Er, Ei = dft16f(u[:, 0::4], u[:, 1::4], UW + 2, DW, cnt)
    Or, Oi = dft16f(u[:, 2::4], u[:, 3::4], UW + 2, DW, cnt)
    Zr = np.empty((nf, 32), dtype=np.int64)
    Zi = np.empty_like(Zr)
    for k in range(16):
        if k == 0:
            tr, ti = Or[:, 0], Oi[:, 0]
        elif k == 8:
            tr, ti = Oi[:, 8], -Or[:, 8]
        else:
            tr, ti = cmul(Or[:, k], Oi[:, k], *co["tw"][k])
        tr, ti = fits(tr, DW, cnt, "tw"), fits(ti, DW, cnt, "tw")
        Zr[:, k], Zi[:, k] = Er[:, k] + tr, Ei[:, k] + ti
        Zr[:, k + 16], Zi[:, k + 16] = Er[:, k] - tr, Ei[:, k] - ti
    yr = np.empty((nf, len(ks)), dtype=np.int64)
    yi = np.empty_like(yr)
    m = np.arange(nf)
    for h, k in enumerate(ks):
        k1, k2 = k % 32, (32 - k) % 32
        ar, ai = Zr[:, k1] + Zr[:, k2], Zi[:, k1] - Zi[:, k2]
        br, bi = Zr[:, k1] - Zr[:, k2], Zi[:, k1] + Zi[:, k2]
        cr, ci = cmul(br, bi, *co["post"][k])
        cr, ci = fits(cr, UW + 6, cnt, "post"), fits(ci, UW + 6, cnt, "post")
        xr, xi = ar + cr, -(ai + ci)
        e = ((k % 4) * (m % 4)) % 4
        rr = np.where(e == 0, xr, np.where(e == 1, xi, np.where(e == 2, -xr, -xi)))
        ri = np.where(e == 0, xi, np.where(e == 1, -xr, np.where(e == 2, -xi, xr)))
        yr[:, h] = sat(rsh(rr, UF + 1 - YF), YW, cnt, "y")
        yi[:, h] = sat(rsh(ri, UF + 1 - YF), YW, cnt, "y")
    return yr, yi


if __name__ == "__main__":
    load()
    print("係数: m0_coef.json と式から作った値が pfb64_coef.vh と一致")
