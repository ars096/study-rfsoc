#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 W-1e — 配線の指紋: W-1e の RAW の 2 MHz の格子を Y-4 の P-on と比べる（runs/ のある所で、README W-1e）

  python3 w1e_cmp.py [n]      # runs/w1e_1〜n_raw.npy（既定 11）

RAW の格子は raw_shape.py と同じ（2,048 点・Hann・平均、床は偶数 / 奇数の比の rms / 2）。runs/w1e_grid.npz に P_e・fl_e を残す。
W-1d の尺（y8_ripple.shape）を床を引いて、比（dB）に 1 つの反射の波（y8_ripple.fit）を当てた振れを出す。陽性対照は A1 / P-on。
"""
import sys

import numpy as np

import y8_ripple as y8

L = 2048


def grid(names):
    raw = np.concatenate([np.load(n + "_raw.npy") for n in names]).astype(np.float64)
    seg = raw.reshape(-1, L)
    seg = seg - seg.mean(1, keepdims=True)
    S = np.abs(np.fft.rfft(seg * np.hanning(L), axis=1)) ** 2
    fl = y8.shape(S[0::2].mean(0), S[1::2].mean(0)) / 2
    return S.mean(0), fl, raw.shape[0]


def show(name, a, b, fa, fb, f, m):
    r = y8.shape(a, b)
    tau, expl, a5, a15, _ = y8.fit(f, 10 * np.log10(a[m] / b[m]))
    print(f"{name:18s}: 尺 {r:.4f}・床を引いて {np.sqrt(max(r ** 2 - fa ** 2 - fb ** 2, 0)):.4f}・"
          f"波 τ {tau:.3f} ns・振れ 500 MHz {a5:.2f}・1500 MHz {a15:.2f} dB（説明 {expl * 100:.0f} %）")


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 11
    P, fl, ns = grid([f"runs/w1e_{i}" for i in range(1, n + 1)])
    np.savez("runs/w1e_grid.npz", P_e=P, fl_e=fl)
    z = np.load("runs/y4_grid.npz")
    F = np.arange(P.size) * 2.0
    m = (F >= 50) & (F <= 2000)
    print(f"W-1e の RAW: SNAP {ns} 本・床 {fl:.4f}（Y-4 の P-on {float(z['fl_pon']):.4f}）")
    show("W-1e / Y-4 P-on", P, z["P_pon"], fl, float(z["fl_pon"]), F[m], m)
    show("陽性対照 A1 / P-on", z["P_a1"], z["P_pon"], float(z["fl_a1"]), float(z["fl_pon"]), F[m], m)


if __name__ == "__main__":
    main()
