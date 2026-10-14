#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj023 D-7 — 32768 点の PFB（T = 4）の ch を B 個ずつ束ねた（ビニングした）ときの ch の応答。

    python3 model/bin_resp.py            # 量子化した 18 bit の係数（wide_model と同じ原型）で

束ねた ch j = 細かい ch B·j 〜 B·j + B − 1 の電力の和。中心は細かい ch (B − 1)/2 だけずれる（f = (B·j + (B−1)/2)·fs / 32768）。
物差しは束ねた ch の幅（= B 個の細かい ch）。比べる相手は proj020 の窓の値（wide_model.FINE_REF）と、
その長さの PFB を直に使う案（proj022 の M-2、B = 1 の行と同じ形）。
"""
import numpy as np
from wide_model import design, quantize, CF, FINE_REF

N = 32768
P = 8                                   # 細かい ch あたりの周波数の点（ゼロ埋め）
c = quantize(design(N)).astype(np.float64) / (1 << CF)
L = c.size
H2 = np.abs(np.fft.fft(c, L * P)) ** 2
H2 /= H2[0]
H2 = np.fft.fftshift(H2)
x = (np.arange(L * P) - L * P // 2) * (N / (L * P))     # 細かい ch の単位
keep = np.abs(x) <= 40
x, H2 = x[keep], H2[keep]
resp = lambda f: np.interp(f, x, H2, left=0.0, right=0.0)
db = lambda v: 10 * np.log10(np.maximum(v, 1e-30))

print("物差し proj020: 半 ch %.2f dB・≧1 ch %.1f・≧1.5 ch %.1f・≧3 ch %.1f dB・ENBW %.3f" %
      (FINE_REF["half"], FINE_REF["ge1"], FINE_REF["ge15"], FINE_REF["ge3"], FINE_REF["enbw"]))
for B in (1, 2, 4):
    u = np.linspace(-8, 8, 32001)                         # 束ねた ch の単位、中心からの距離
    f = u * B
    cen = (B - 1) / 2
    G = sum(resp(f + cen - m) for m in range(B))
    G /= np.interp(0.0, u, G)
    half = db(np.interp(0.5, u, G))
    inb = np.abs(u) <= 0.25
    rip = db(G[inb].max()) - db(G[inb].min())
    ge = lambda a: db(G[np.abs(u) >= a].max())
    enbw = np.trapezoid(G, u)
    print("B = %d（%s）: 中心のずれ %.1f 細かい ch・半 ch %.2f dB・|u|≦0.25 の凹凸 %.2f dB・≧1 ch %.1f・≧1.5 ch %.1f・≧3 ch %.1f dB・ENBW %.3f" %
          (B, {1: "512 MHz", 2: "1 GHz", 4: "全帯域"}[B], cen, half, rip, ge(1.0), ge(1.5), ge(3.0), enbw))
