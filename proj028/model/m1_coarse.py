#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 M-1 — 荒い PFB（オーバーサンプリング、半 ch ずらし）の原型とタップ数。numpy だけ。

組み方（README の M-1）:
  実数の入力 x[n]（fs）→ ch k = 0..M/2−1（中心 f_k = (k + 1/2)·Δ、Δ = fs/M）→ 間引き D = M / os
    y_k[m] = Σ_n h[n] · x[mD − n] · exp(−j2π (k + 1/2)(mD − n) / M)          … 直の定義（DDC → 低域 → 間引き）
  残すのは |f − f_k| ≦ Δ/2。出口の速さは os·Δ なので、入力の f − f_k = y + j·os·Δ（j ≠ 0）が y に折り返す。

判定:
  A  原型 h の応答 H から、残す範囲 |y| ≦ Δ/2 に落ちる折り返しの和 Σ_{j≠0} |H(y + j·osΔ)|² / |H(y)|² の最悪 ≦ −60 dB を満たす最小の T_c
  B  直の定義で y_k を作り、ポリフェーズ＋FFT の形（下の pfb()）と一致するか（実装の形の式の確かめ）
  C  トーンを入れて、残す範囲に落ちた折り返しの大きさが A の |H| の値と合うか（陽性対照: os = 1 は −6 dB 前後で落ちる）

使い方:
  python3 model/m1_coarse.py all | a | b | c
"""
import sys

import numpy as np

ATT = 60.0                      # 折り返しの目標（dB）
BETA = 0.1102 * (ATT - 8.7)     # Kaiser の β（A ≧ 50 dB の式）
YC = 0.48                       # C で見る残す範囲の点（端の近く。真ん中寄りでは os = 1 でも折り返しが小さい）
OS_LIST = [(4, 3), (5, 4), (8, 7), (9, 8), (21, 20)]


def proto(M, Tc, os):
    """Kaiser 窓の sinc。長さ L = Tc·M、切れ目 os·Δ/2（遷移帯の真ん中）、DC で利得 1。"""
    L = Tc * M
    n = np.arange(L) - (L - 1) / 2
    fc = os / (2 * M)                                   # 周期 / サンプル
    h = 2 * fc * np.sinc(2 * fc * n) * np.kaiser(L, BETA)
    return h / h.sum()


def response(h, M, nfft_per_delta=512):
    """H を Δ の単位の周波数の格子で返す（u = f/Δ、−M/2..M/2）。"""
    nfft = M * nfft_per_delta
    H = np.fft.fftshift(np.fft.fft(h, nfft))
    u = (np.arange(nfft) - nfft // 2) / nfft_per_delta
    return u, np.abs(H)


def alias_metrics(h, M, os, npd=512):
    u, A = response(h, M, npd)
    P = A ** 2
    keep = np.abs(u) <= 0.5
    yk = u[keep]
    worst_sum, worst_one = 0.0, 0.0
    jmax = int(np.ceil(M / os))
    for y in yk[:: max(1, len(yk) // 400)]:
        p0 = np.interp(y, u, P)
        s = 0.0
        for j in range(-jmax, jmax + 1):
            if j == 0:
                continue
            x = y + j * os
            if abs(x) > M / 2:
                continue
            pj = np.interp(x, u, P)
            s += pj
            worst_one = max(worst_one, pj / p0)
        worst_sum = max(worst_sum, s / p0)
    edge = 20 * np.log10(np.interp(0.5, u, A) / np.interp(0.0, u, A))
    rip = 20 * np.log10(A[keep].max() / A[keep].min())
    return 10 * np.log10(worst_sum), 10 * np.log10(worst_one), edge, rip


def m1a():
    print("== M-1 A: 折り返し ≦ −%.0f dB を満たす最小の T_c（Kaiser β %.3f）" % (ATT, BETA))
    print("  os      遷移帯   M    T_c  折り返し（和）  （最大の 1 本）  端 ±Δ/2   範囲内の波打ち  DSP(16×T_c)")
    res = {}
    for p, q in OS_LIST:
        os = p / q
        for M in (64, 256):
            for Tc in range(4, 200):
                h = proto(M, Tc, os)
                a_sum, a_one, edge, rip = alias_metrics(h, M, os)
                if a_sum <= -ATT:
                    break
            res[(p, q, M)] = Tc
            print("  %2d/%-3d  %.3fΔ  %4d  %3d   %7.1f dB     %7.1f dB     %6.3f dB  %6.3f dB      %4d（%.1f %%）"
                  % (p, q, os - 1, M, Tc, a_sum, a_one, edge, rip, 16 * Tc, 100 * 16 * Tc / 4272))
    return res


def direct(x, h, M, D, k, nout):
    """直の定義 y_k[m]（m = 0..nout−1）。m·D ≧ L−1 から（履歴が満ちてから）。"""
    L = len(h)
    m0 = int(np.ceil((L - 1) / D))
    y = np.empty(nout, complex)
    nn = np.arange(L)
    for i in range(nout):
        t = (m0 + i) * D
        seg = x[t - nn]
        y[i] = np.sum(h * seg * np.exp(-2j * np.pi * (k + 0.5) * (t - nn) / M))
    return y, m0


def pfb(x, h, M, D, nout, m0):
    """ポリフェーズ＋FFT の形。z[r] = Σ_t (−1)^t·h[r + tM]·x[mD − r − tM]（半 ch ずらしで e^{j2π(k+½)t} = (−1)^t）、
    Y_k = e^{−j2π(k+½)mD/M} · Σ_r (z[r]·e^{jπr/M}) · e^{j2πkr/M}（= M·ifft）。k = 0..M/2−1 を返す。"""
    L = len(h)
    Tc = L // M
    hr = h.reshape(Tc, M) * ((-1.0) ** np.arange(Tc))[:, None]   # hr[t, r] = (−1)^t·h[r + tM]
    r = np.arange(M)
    pre = np.exp(1j * np.pi * r / M)
    k = np.arange(M // 2)
    out = np.empty((nout, M // 2), complex)
    for i in range(nout):
        t0 = (m0 + i) * D
        idx = t0 - r[None, :] - (np.arange(Tc) * M)[:, None]
        z = np.sum(hr * x[idx], axis=0)
        Y = M * np.fft.ifft(z * pre)
        out[i] = np.exp(-2j * np.pi * (k + 0.5) * t0 / M) * Y[: M // 2]
    return out


def m1b():
    print("== M-1 B: 直の定義とポリフェーズ＋FFT の形の一致（M 64、os 8/7、D 56、T_c 26）")
    M, p, q, Tc = 64, 8, 7, 26
    D = M * q // p
    h = proto(M, Tc, p / q)
    rng = np.random.default_rng(1)
    x = rng.standard_normal(Tc * M + 200 * D)
    nout = 150
    Yp = None
    worst = 0.0
    for k in (0, 1, 17, 31):
        yd, m0 = direct(x, h, M, D, k, nout)
        if Yp is None:
            Yp = pfb(x, h, M, D, nout, m0)
        e = np.max(np.abs(yd - Yp[:, k])) / np.max(np.abs(yd))
        worst = max(worst, e)
        print("  ch %2d: 相対の差 %.2e" % (k, e))
    # 陽性対照: 半 ch ずらしの前掛けを抜く
    hr = h.reshape(Tc, M) * ((-1.0) ** np.arange(Tc))[:, None]
    r = np.arange(M)
    t0 = (m0 + 3) * D
    z = np.sum(hr * x[t0 - r[None, :] - (np.arange(Tc) * M)[:, None]], axis=0)
    bad = np.exp(-2j * np.pi * (5 + 0.5) * t0 / M) * (M * np.fft.ifft(z))[5]
    yd5, _ = direct(x, h, M, D, 5, 4)
    ebad = abs(bad - yd5[3]) / abs(yd5[3])
    print("  陽性対照（前掛け e^{jπr/M} を抜く）: 相対の差 %.2f" % ebad)
    ok = worst < 1e-10 and ebad > 0.1
    print("  結果: %s" % ("全部通過" if ok else "不合格"))
    return ok


def tone_alias(M, p, q, Tc, k, off_delta):
    """ch k の中心から off_delta·Δ の位置にトーンを入れ、出口の y の周波数ごとの大きさを測る。"""
    os = p / q
    D = M * q // p
    h = proto(M, Tc, os)
    nout = 2048
    n = np.arange(Tc * M + (nout + 4) * D)
    f = (k + 0.5 + off_delta) / M                         # 周期 / サンプル
    x = np.cos(2 * np.pi * f * n)
    m0 = int(np.ceil((Tc * M - 1) / D))
    Y = pfb(x, h, M, D, nout, m0)[:, k]
    w = np.hanning(nout)
    S = np.abs(np.fft.fftshift(np.fft.fft(Y * w))) / (w.sum() / 2)
    yf = (np.arange(nout) - nout // 2) / nout * os       # Δ の単位
    i = np.argmax(S)
    return yf[i], 20 * np.log10(S[i])


def m1c(res):
    print("== M-1 C: トーンで折り返しを測る（ch 10、M 64、残す範囲の端の近く y = +%.2fΔ に折り返す入力）" % YC)
    ok = True
    cases = [(8, 7, res.get((8, 7, 64), 27)), (4, 3, res.get((4, 3, 64), 11)), (1, 1, 12)]
    for p, q, Tc in cases:
        os = p / q
        off = YC - os                                    # j = −1 の折り返しが y = YC に落ちる入力
        yf, lev = tone_alias(64, p, q, Tc, 10, off)
        u, A = response(proto(64, Tc, os), 64)
        pred = 20 * np.log10(np.interp(off, u, A) / np.interp(0, u, A))
        inkeep = abs(yf) <= 0.5
        print("  os %d/%d T_c %d: 入力 %+.3fΔ → 出口 %+.3fΔ（残す範囲の中: %s）  %.1f dB（|H| の予言 %.1f dB）"
              % (p, q, Tc, off, yf, "はい" if inkeep else "いいえ", lev, pred))
        if abs(lev - pred) > 1.0 or not inkeep or abs(yf - YC) > 0.01:
            ok = False
        if (p, q) == (1, 1):
            if lev < -30:                                # 陽性対照: 臨界の間引きは端で大きく折り返す
                ok = False
        elif lev > -ATT:
            ok = False
    print("  結果: %s" % ("全部通過" if ok else "不合格"))
    return ok


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    res = {}
    if what in ("all", "a"):
        res = m1a()
    if what in ("all", "b"):
        m1b()
    if what in ("all", "c"):
        m1c(res)
