#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 M-3 — 荒い段の語長（固定小数点）。numpy だけ。bit 単位の模型ではなく、語長と捨てる bit を決めるための模型。

  x（14 bit）→ 荒い PFB（係数 18 bit、z を SH bit 落として 18 bit）→ 32 点の FFT（出口 24 bit。S-1 の cfft32 の語長）
  → Y_k（共役の詰め替え）→ 利得 g_k（18 bit、Y·g >> 16）→ 各成分 σ = S LSB → 8 bit
判定（README の M-3）:
  (a) 量子化の損失: 浮動小数点の Y と比べた雑音の床の持ち上がり（z の丸め・FFT の丸め・8 bit）
  (b) CW を強くして、z の 18 bit が ADC より先に飽和しないか（荒い ch の雑音に対する強さで）
  (c) IF の傾き（ch の間 ±10 dB）を利得で吸収して、全部の ch で σ ≒ S になるか
使い方: python3 model/m3_coarse_fixed.py
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from m1_coarse import proto  # noqa: E402

M, P_OS, Q_OS, TC = 64, 8, 7, 27
D = M * Q_OS // P_OS
XW, CW, ZW, FW, GW, BW = 14, 18, 18, 24, 18, 8
S = 12.0
DBFS = -18.0                                     # 運転のレベル（−16〜−21 dBFS の真ん中）


def coeffs():
    h = proto(M, TC, P_OS / Q_OS)
    hq = np.round(h / np.max(np.abs(h)) * (2 ** (CW - 1) - 1)).astype(np.int64)
    hr = (hq.reshape(TC, M) * ((-1) ** np.arange(TC))[:, None]).astype(np.int64)   # (−1)^t を含む
    return h, hq, hr


def blocks(x, hr, nblk):
    """z_r（整数、丸める前）をブロックごとに"""
    r = np.arange(M)
    m0 = int(np.ceil((TC * M - 1) / D))
    z = np.empty((nblk, M), np.int64)
    for i in range(nblk):
        t0 = (m0 + i) * D
        z[i] = np.sum(hr * x[t0 - r[None, :] - (np.arange(TC) * M)[:, None]], axis=0)
    return z


def sat(v, w):
    lim = 2 ** (w - 1) - 1
    return np.clip(v, -lim, lim)


def fft32_y(z):
    """z（実数、ブロック × 64）→ Y（ブロック × 32、出口の回転の前）。M-1d の形"""
    n = np.arange(M // 2)
    w = (z[:, :M // 2] + 1j * z[:, M // 2:]) * np.exp(1j * np.pi * n / M)
    F = (M // 2) * np.fft.ifft(w, axis=1)
    Y = np.empty((z.shape[0], M // 2), complex)
    Y[:, 0::2] = F[:, :M // 4]
    Y[:, 1::2] = np.conj(F[:, ::-1][:, :M // 4])
    return Y


def chain(x, hr, nblk, SH, gains=None, cw_only=False):
    zi = blocks(x, hr, nblk)
    zf = zi / 2.0 ** SH                                          # 浮動小数点の基準（同じ SH の縮尺）
    zq = sat(np.round(zf), ZW)
    nsat = np.sum(np.abs(np.round(zf)) > 2 ** (ZW - 1) - 1)
    Yf = fft32_y(zf)
    Yq = fft32_y(zq.astype(float))
    Yq = np.round(Yq.real) + 1j * np.round(Yq.imag)               # cfft32 の出口の丸め（中の丸めは S-1 の sim で 7.5e-6）
    Yq = sat(Yq.real, FW) + 1j * sat(Yq.imag, FW)
    if gains is None:
        sig = np.sqrt(np.mean(np.abs(Yq) ** 2, axis=0) / 2)
        gains = np.round(S / sig * 2 ** 16).astype(np.int64)
        gains = np.clip(gains, 1, 2 ** (GW - 1) - 1)
    y8 = sat(np.round(Yq.real * gains / 2 ** 16), BW) + 1j * sat(np.round(Yq.imag * gains / 2 ** 16), BW)
    return zf, zq, nsat, Yf, Yq, y8, gains


def main():
    rng = np.random.default_rng(7)
    h, hq, hr = coeffs()
    sig_x = 2 ** (XW - 1) * 10 ** (DBFS / 20)
    nrm = np.sqrt(np.sum(hq.astype(float) ** 2))
    sig_z_int = sig_x * nrm
    SH = int(np.round(np.log2(sig_z_int / 2 ** 12)))
    print("== M-3: 荒い段の語長（x %d bit・%.0f dBFS → σ_x %.0f LSB、係数 %d bit・‖h‖ %.0f）" % (XW, DBFS, sig_x, CW, nrm))
    print("  z の σ（落とす前）%.3g → SH %d で σ_z ≒ %.0f LSB（18 bit の最大まで %.1f dB）"
          % (sig_z_int, SH, sig_z_int / 2 ** SH, 20 * np.log10((2 ** 17 - 1) / (sig_z_int / 2 ** SH))))
    ok = True
    # (a) 雑音での損失（IF の傾き ±10 dB を入れる: 白い雑音を周波数で傾ける）
    nblk = 3000
    n = TC * M + (nblk + 4) * D
    X = np.fft.rfft(rng.standard_normal(n))
    tilt = 10 ** (np.linspace(-10, 10, X.size) / 20)
    x = np.fft.irfft(X * tilt, n)
    x = np.round(x / np.std(x) * sig_x).astype(np.int64)
    x = sat(x, XW)
    zf, zq, nsat, Yf, Yq, y8, g = chain(x, hr, nblk, SH)
    # 損失: 各段の誤差の電力 / 信号の電力（ch ごと、Y の縮尺で）
    e_z = np.mean(np.abs(Yq - Yf) ** 2, axis=0) / np.mean(np.abs(Yf) ** 2, axis=0)
    y8s = y8 * 2 ** 16 / g                                         # 8 bit を Y の縮尺に戻す
    e_all = np.mean(np.abs(y8s - Yf) ** 2, axis=0) / np.mean(np.abs(Yf) ** 2, axis=0)
    sig8 = np.sqrt(np.mean(np.abs(y8) ** 2, axis=0) / 2)
    print("(a) 損失（ch の中央値 / 最大）: z と FFT の丸め %.2e / %.2e・8 bit まで全部 %.2e / %.2e（M-2 の 1/12/S² = %.2e）"
          % (np.median(e_z), e_z.max(), np.median(e_all), e_all.max(), 1 / 12 / S ** 2))
    print("    z の飽和 %d 個・Y の σ の幅（ch の間）%.1f dB・8 bit の σ %.2f〜%.2f LSB（目標 %.0f）・利得 %d〜%d（%d bit の中）"
          % (nsat, 20 * np.log10(np.sqrt(np.mean(np.abs(Yq) ** 2, axis=0)).max() / np.sqrt(np.mean(np.abs(Yq) ** 2, axis=0)).min()),
             sig8.min(), sig8.max(), S, g.min(), g.max(), GW))
    ok &= np.median(e_z) < 1e-5 and e_all.max() < 1e-3 and nsat == 0 and sig8.min() > 0.9 * S and sig8.max() < 1.1 * S
    # (b) z の飽和が始まる CW（ch 10 の中心、雑音は傾きなし）
    nblk2 = 400
    n2 = TC * M + (nblk2 + 4) * D
    nn = np.arange(n2)
    xn = rng.standard_normal(n2) * sig_x
    onset = None
    for lv in np.arange(0, 70.1, 2.0):
        # CW の電力を「荒い ch の雑音」に対して lv dB: 荒い ch の帯域は fs/M、全帯域 fs/2 の雑音 σ_x² の 2/M
        A = np.sqrt(2 * sig_x ** 2 * (2 / M) * 10 ** (lv / 10))
        x2 = np.round(xn + A * np.cos(2 * np.pi * (10.5 / M) * nn)).astype(np.int64)
        if np.max(np.abs(x2)) > 2 ** (XW - 1) - 1:
            onset = ("ADC", lv)
            break
        zi = blocks(x2, hr, nblk2)
        if np.max(np.abs(np.round(zi / 2.0 ** SH))) > 2 ** (ZW - 1) - 1:
            onset = ("z", lv)
            break
    print("(b) 飽和が始まる CW（荒い ch の雑音に対して）: %s が +%.0f dB（M-2 の 8 bit は S 12 で +16.5 dB）" % onset)
    # 判定: z が ADC より先に飽和しない（z の語長が律速にならない）。1 回目は「+40 dB 以上」と置いて、ADC が +26 dB で先に飽和して落ちた
    ok &= onset is not None and onset[0] == "ADC"
    print("結果: %s" % ("全部通過" if ok else "不合格"))
    print("    → RTL に渡す値: 係数 %d bit・SH %d・z %d bit・Y %d bit・利得 %d bit（>> 16）・出口 %d bit" % (CW, SH, ZW, FW, GW, BW))


if __name__ == "__main__":
    main()
