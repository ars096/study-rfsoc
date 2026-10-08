#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj020 — 窓の分光の PFB（T = 4、4096 点）の係数と、RTL と bit 単位で同じ固定小数点の模型。numpy だけ。

原型（README の「決めたこと」。2026-10-07 に β 8・bw 1.00 → β 5・bw 1.198 に決め直した）:
  h[n] = sinc(1.198 · (n − (L − 1)/2) / 4096) · kaiser(L, β = 5)、L = 16384。隣の ch と −3 dB で交わり、ch の間の谷が無い
  （0.5 ch −3.00 dB・隣接 ch の和の波打ち 0.08 dB・≧ 1 ch −53.7 dB・≧ 1.5 ch −58.0 dB・≧ 3 ch −64.5 dB・ENBW 1.010）。**Σh² = 4096 に規格化**（雑音の電力を保つ:
  白色の z に対し PFB の出口の分散の平均 = z の分散。proj019 の abs の式と「窓の和 = TP」がそのまま成り立つ）
  係数 c = round(h · 2^CF)、18 bit 符号付き（CF = 16、最大 78288 ≒ 1.19・最小 −7682。18 bit に入る）。**c は左右対称に作る**（前半を作って鏡に写す）。
  RTL は対称を使い、ROM 2 本（タップ 0・1）の 2 ポート目で タップ 3・2 を読む: c[a + 4096·(3 − t)] = c[(4095 − a) + 4096·t]

フレームと式（wspec_core の冒頭と同じ）:
  入力 z のフレーム f = z[4096f : 4096f + 4096]（WRST の後の最初の z が 0 番）。PFB の出力フレーム r（番号は**最新の入力フレーム**）:
    acc[a] = Σ_{t=0..3} c[a + 4096t] · z_{r − 3 + t}[a]        （r − 3 + t < 0 のフレームは 0。WRST の直後の 3 フレーム）
    y[a]   = sat18(floor((acc[a] + 2^(CF−1)) / 2^CF))         （re・im を別々に。飽和は 18 bit の符号付きの範囲、回数を数える）
  y が FFT の入力。スナップショットは y（FFT の入力）を残す（PS の --golden はそのまま）。

使い方:
  python3 pfb4.py gen      # model/pfb4_coef.txt と src/pfb4_rom.v を作り直す（係数の唯一の正は pfb4_coef.txt）
  python3 pfb4.py resp     # 量子化した係数の ch の応答（半 ch の落ち・|Δ| ≧ 1.5 ch の最大・ENBW）
"""
import os
import sys

import numpy as np

N = 4096
T = 4
L = N * T
BETA = 5.0       # 2026-10-07 決め直し（README「決めたこと」）: rev1 の β 8・bw 1.00 から
BW = 1.198
CF = 16          # 係数の小数部
CW = 18          # 係数の bit 数
ZW = 18          # z・y の bit 数
HERE = os.path.dirname(os.path.abspath(__file__))
COEF_TXT = os.path.join(HERE, "pfb4_coef.txt")
ROM_V = os.path.join(HERE, "..", "src", "pfb4_rom.v")


def design():
    """浮動小数点の原型（Σh² = N）。左右対称を厳密に保つため前半だけ計算して鏡に写す。"""
    n = np.arange(L) - (L - 1) / 2
    h = np.sinc(BW * n / N) * np.kaiser(L, BETA)
    half = h[: L // 2]
    h = np.concatenate([half, half[::-1]])
    return h * np.sqrt(N / np.sum(h * h))


def quantize(h):
    c = np.round(h * (1 << CF)).astype(np.int64)
    assert c.max() < (1 << (CW - 1)) and c.min() >= -(1 << (CW - 1)), "係数が 18 bit に入らない"
    assert np.array_equal(c, c[::-1]), "係数が対称でない"
    return c


def load_coef():
    c = np.loadtxt(COEF_TXT, dtype=np.int64)
    assert len(c) == L and np.array_equal(c, c[::-1])
    return c


def pfb4_fixed(zr, zi, c=None, cnt=None):
    """z（整数の re・im、長さ 4096 の倍数）→ y（同じ長さ）。フレーム r の出力は z のフレーム r − 3 … r。cnt['pfb_sat'] に飽和の回数。"""
    if c is None:
        c = load_coef()
    nf = len(zr) // N
    zr = np.asarray(zr[: nf * N], dtype=np.int64).reshape(nf, N)
    zi = np.asarray(zi[: nf * N], dtype=np.int64).reshape(nf, N)
    ct = c.reshape(T, N)
    ar = np.zeros((nf, N), dtype=np.int64)
    ai = np.zeros((nf, N), dtype=np.int64)
    for t in range(T):
        sh = T - 1 - t                       # タップ t は r − sh のフレーム
        ar[sh:] += ct[t] * zr[: nf - sh]
        ai[sh:] += ct[t] * zi[: nf - sh]
    lo, hi = -(1 << (ZW - 1)), (1 << (ZW - 1)) - 1
    yr = (ar + (1 << (CF - 1))) >> CF
    yi = (ai + (1 << (CF - 1))) >> CF
    s = (yr < lo) | (yr > hi) | (yi < lo) | (yi > hi)
    if cnt is not None and np.any(s):
        cnt["pfb_sat"] = cnt.get("pfb_sat", 0) + int(np.count_nonzero(s))
    return np.clip(yr, lo, hi).reshape(-1), np.clip(yi, lo, hi).reshape(-1)


def gen():
    c = quantize(design())
    np.savetxt(COEF_TXT, c, fmt="%d", header=f"proj020 pfb4: sinc x kaiser(beta={BETA}), bw={BW}, L={L}, sum h^2 = {N}, "
               f"Q{CF} {CW} bit signed. 生成: model/pfb4.py gen。手で直さない")
    ct = c.reshape(T, N)
    m = (1 << CW) - 1
    with open(ROM_V, "w") as fp:
        fp.write(f"""// SPDX-License-Identifier: BSD-3-Clause
//
// pfb4_rom — PFB（T = 4）の係数 ROM。**model/pfb4.py gen の生成物。手で直さない**（係数の正は model/pfb4_coef.txt）
//
// P = 0 がタップ 0、P = 1 がタップ 1 の 4096 語（c[a + 4096·P]、Q{CF}・{CW} bit 符号付き）。2 ポートで読む:
//   ポート A: 番地 a      → タップ P の c[a + 4096·P]
//   ポート B: 番地 4095 − a → 係数の対称で タップ 3 − P の c[a + 4096·(3 − P)]（呼ぶ側が番地を 4095 − a にして渡す）
// 出力は番地から **2 クロック後**（ROM の読み出し + 出力レジスタ）。

`timescale 1ns / 1ps

module pfb4_rom #(
    parameter integer P = 0
)(
    input  wire                  clk,
    input  wire [11:0]           addr_a,
    input  wire [11:0]           addr_b,
    output reg  signed [{CW - 1}:0]   c_a,
    output reg  signed [{CW - 1}:0]   c_b
);
    (* rom_style = "block" *) reg [{CW - 1}:0] rom [0:4095];
    reg [{CW - 1}:0] ra, rb;
    always @(posedge clk) begin
        ra  <= rom[addr_a];
        rb  <= rom[addr_b];
        c_a <= ra;
        c_b <= rb;
    end
    generate
    if (P == 0) begin : g_p0
        initial begin
""")
        for a in range(N):
            fp.write(f"            rom[{a}] = {CW}'h{int(ct[0][a]) & m:05x};\n")
        fp.write("        end\n    end else begin : g_p1\n        initial begin\n")
        for a in range(N):
            fp.write(f"            rom[{a}] = {CW}'h{int(ct[1][a]) & m:05x};\n")
        fp.write("        end\n    end\n    endgenerate\nendmodule\n")
    print(f"係数: 最大 {c.max()}・最小 {c.min()}・Σc²/2^{2 * CF} = {np.sum(c.astype(float) ** 2) / 4.0 ** CF:.3f}（{N} のはず）")
    print(f"→ {COEF_TXT}\n→ {os.path.normpath(ROM_V)}")


def resp(c=None):
    if c is None:
        c = load_coef()
    os_ = 64
    H = np.abs(np.fft.fft(c.astype(float), L * os_)) ** 2
    H /= H[0]
    f = np.fft.fftfreq(L * os_) * N
    o = np.argsort(f)
    sc = 10 * np.log10(np.interp(0.5, f[o], H[o]))
    sl = 10 * np.log10(H[np.abs(f) >= 1.5].max())
    s1 = 10 * np.log10(H[np.abs(f) >= 1.0].max())
    s3 = 10 * np.log10(H[np.abs(f) >= 3.0].max())
    s04 = 10 * np.log10(np.interp(0.4, f[o], H[o]))
    ct = c.reshape(T, N).astype(float)
    gmax = np.abs(ct).sum(0).max() / (1 << CF)
    enbw = H.sum() / (T * os_)
    S = H.reshape(-1, T * os_).sum(0)
    print(f"0.5 ch {sc:.2f} dB・0.4 ch {s04:.2f} dB・隣接 ch の和の波打ち {10 * np.log10(S.max() / S.min()):.2f} dB・"
          f"|Δ| ≧ 1 / 1.5 / 3 ch の最大 {s1:.1f} / {sl:.1f} / {s3:.1f} dB・ENBW {enbw:.3f} ch・CW の山（矩形比）{10 * np.log10(1 / enbw):+.2f} dB・"
          f"ch の中心の CW の振幅の利得 {c.sum() / (1 << CF) / N:.3f}・番地ごとの Σ|c| の最大 {gmax:.3f}")


if __name__ == "__main__":
    {"gen": gen, "resp": resp}[sys.argv[1] if len(sys.argv) > 1 else "resp"]()
