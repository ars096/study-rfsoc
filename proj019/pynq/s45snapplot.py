#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — s45snap.py が残した <out>.snap.npz（ADC の生サンプル 8192 個 × n 塊）を図にする。

    python3 s45snapplot.py snap_noise.snap.npz                          # → snap_noise.snap.png
    python3 s45snapplot.py snap_sg.snap.npz --sg 3000.25 --marks        # SG の線と櫛・インターリーブの位置に印
    python3 s45snapplot.py snap_sg.snap.npz --adc A --block 3 --zoom 1080 1110

ADC ごとに 1 行・4 枚:
  1 時系列（--block の塊、14 bit。先頭 --nt 個 = 0.25 ns/点）
  2 ヒストグラム（全塊）と同じ分散のガウス。凡例に dBFS・尖度（ガウスで 3）・DC・振り切れ
  3 スペクトル（Hann、全塊の平均）。dBFS/bin（全 bin の和 = 全電力）。横軸は入力の周波数
    （第 2 ナイキスト: 入力 f は 4096 − f に出る。--nyq 1 なら f のまま）、上の軸はベースバンド
  4 塊ごとの電力（dBFS）と時刻（dump_t から。every ms 間隔）
正弦波の山は Hann の等価雑音帯域（1.5 bin）のぶん 1.76 dB 低く読める。bin は 0.5 MHz なので、3000.25 MHz は
bin の間（3000.0 と 3000.5 に分かれ、さらに約 1.4 dB 低い）。
"""
import argparse
import math
import sys

import numpy as np

DBFS0 = 10 * math.log10(8192 ** 2 / 2)
FS = 4096.0
COMB = 163.84          # fs/25（LMX の出力の経路から出る櫛）
ILV = 512.0            # fs/8（インターリーブの線）


def to_in(fbb, nyq):
    """ベースバンド [MHz] → 入力の周波数 [MHz]"""
    return FS - fbb if nyq == 2 else fbb


def spectrum(x14):
    """x14: (n, N) → (fbb [MHz], dBFS/bin)。Hann、塊の平均。全 bin の和が平均電力になる正規化"""
    n, N = x14.shape
    w = np.hanning(N)
    X = np.fft.rfft((x14 - x14.mean(axis=1, keepdims=True)) * w, axis=1)
    P = np.mean(np.abs(X) ** 2, axis=0) / (N * np.sum(w ** 2))
    P[1:-1] *= 2
    return np.fft.rfftfreq(N, 1 / FS), 10 * np.log10(np.maximum(P, 1e-30)) - DBFS0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", help="<out>.snap.npz")
    p.add_argument("--out", default=None, help="図のファイル（既定: <path の .npz を .png に>）")
    p.add_argument("--adc", default="ABCD", help="描く ADC（npz に無いものは飛ばす）")
    p.add_argument("--block", type=int, default=0, help="時系列に描く塊の番号")
    p.add_argument("--nt", type=int, default=256, help="時系列に描く点数（8192 で全部 = 2 µs）")
    p.add_argument("--nyq", type=int, default=2, choices=(1, 2), help="ナイキスト帯（既定 2: 入力 f → 4096 − f）")
    p.add_argument("--sg", type=float, default=None, help="SG の周波数 [MHz]（スペクトルに印）")
    p.add_argument("--marks", action="store_true", help="櫛 n×163.84 MHz とインターリーブ k×512 MHz に印")
    p.add_argument("--zoom", type=float, nargs=2, default=None, metavar=("F0", "F1"), help="スペクトルの横軸 [MHz]（入力の周波数）")
    p.add_argument("--show", action="store_true", help="画面に出す（既定はファイルだけ）")
    a = p.parse_args()

    import matplotlib
    if not a.show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    z = np.load(a.path)
    every = float(z["every_ms"]) if "every_ms" in z else float("nan")
    adcs = [c for c in a.adc.upper() if c in z.files]
    if not adcs:
        print(f"{a.path} に ADC がない（中身: {z.files}）")
        return 1
    fig, axs = plt.subplots(len(adcs), 4, figsize=(20, 3.6 * len(adcs)), squeeze=False,
                            gridspec_kw=dict(width_ratios=[1.2, 0.8, 2.0, 0.9]))
    for row, c in zip(axs, adcs):
        x14 = (z[c].astype(np.int16) >> 2).astype(np.float64)      # 16 bit → 14 bit
        n, N = x14.shape
        b = min(max(a.block, 0), n - 1)
        pw = np.mean(x14 ** 2, axis=1)
        dbfs = 10 * math.log10(max(pw.mean(), 1e-30)) - DBFS0
        cc = x14 - x14.mean()
        var = float(np.mean(cc ** 2))
        kurt = float(np.mean(cc ** 4) / var ** 2) if var > 0 else float("nan")
        clip = int(np.sum(np.abs(x14) >= 8191))

        # 1 時系列
        ax = row[0]
        nt = min(a.nt, N)
        ax.plot(np.arange(nt) * 1e3 / FS, x14[b, :nt], lw=0.6, marker="." if nt <= 512 else None, ms=2)
        ax.set_xlabel("time [ns]"); ax.set_ylabel("ADC [14-bit LSB]")
        ax.set_title(f"ADC_{c}  block {b}/{n}  (first {nt} samples)", fontsize=10)
        ax.grid(alpha=0.3)

        # 2 ヒストグラム
        ax = row[1]
        lo, hi = int(x14.min()), int(x14.max())
        step = max(1, (hi - lo + 1) // 200)
        edges = np.arange(lo - 0.5, hi + step + 0.5, step)
        ax.hist(x14.ravel(), bins=edges, density=True, alpha=0.6, label="data")
        if var > 0:
            u = np.linspace(lo, hi, 400)
            ax.plot(u, np.exp(-(u - x14.mean()) ** 2 / (2 * var)) / math.sqrt(2 * math.pi * var), "r", lw=1, label="Gauss")
        ax.set_yscale("log"); ax.set_xlabel("ADC [14-bit LSB]")
        ax.set_title(f"{dbfs:+.2f} dBFS  kurt {kurt:.3f}  DC {x14.mean():+.2f}  clip {clip}", fontsize=9)
        ax.legend(fontsize=7); ax.grid(alpha=0.3)

        # 3 スペクトル
        ax = row[2]
        fbb, S = spectrum(x14)
        fin = to_in(fbb, a.nyq)
        ax.plot(fin, S, lw=0.5)
        if a.marks:
            for k in range(1, int(FS / COMB) + 1):
                f = k * COMB
                if FS / 2 * (a.nyq - 1) <= f <= FS / 2 * a.nyq:
                    ax.axvline(f, color="orange", lw=0.6, ls=":", alpha=0.8)
            for k in range(0, 9):
                f = k * ILV
                if FS / 2 * (a.nyq - 1) <= f <= FS / 2 * a.nyq:
                    ax.axvline(f, color="purple", lw=0.6, ls="--", alpha=0.6)
        if a.sg is not None:
            ax.axvline(a.sg, color="red", lw=0.8, ls="--", alpha=0.7)
            i = int(np.argmin(np.abs(fin - a.sg)))
            j0, j1 = max(i - 3, 0), min(i + 4, len(S))
            k = j0 + int(np.argmax(S[j0:j1]))
            if S[k] > np.median(S) + 10:                            # 線が見えている ADC だけ書く
                ax.annotate(f"{fin[k]:.2f} MHz  {S[k]:.1f} dBFS", (fin[k], S[k]), fontsize=8, color="red",
                            xytext=(5, -12), textcoords="offset points")
        if a.zoom:
            ax.set_xlim(*a.zoom)
            m = (fin >= min(a.zoom)) & (fin <= max(a.zoom))
            if m.any():
                ax.set_ylim(S[m].min() - 5, S[m].max() + 5)
        else:
            ax.set_xlim(fin.min(), fin.max())
        ax.set_xlabel(f"input freq [MHz]  (Nyquist zone {a.nyq})")
        ax.set_ylabel(f"dBFS / bin ({FS / N * 1e3:.0f} kHz)")
        ax.set_title(f"ADC_{c}  Hann, mean of {n} blocks" + ("   orange: n*163.84  purple: k*512" if a.marks else ""), fontsize=9)
        ax.grid(alpha=0.3)
        sec = ax.secondary_xaxis("top", functions=((lambda f: FS - f), (lambda f: FS - f)) if a.nyq == 2 else (lambda f: f, lambda f: f))
        sec.set_xlabel("baseband [MHz]", fontsize=8); sec.tick_params(labelsize=7)

        # 4 塊ごとの電力
        ax = row[3]
        key = c + "_dump_t"
        if key in z.files and len(z[key]) == n:
            t = (z[key] - z[key][0]) * 125 / 32 * 1e-6           # ビート（256 MHz = 3.90625 ns）→ ms
            xl = "time from first block [ms]"
        else:
            t = np.arange(n) * every
            xl = "block × every [ms]"
        ax.plot(t, 10 * np.log10(np.maximum(pw, 1e-30)) - DBFS0, "o-", ms=3, lw=0.8)
        ax.set_xlabel(xl); ax.set_ylabel("block power [dBFS]")
        ax.set_title(f"every {every:g} ms  σ {np.std(10 * np.log10(np.maximum(pw, 1e-30))):.3f} dB", fontsize=9)
        ax.grid(alpha=0.3)

        print(f"ADC_{c}: {n} 塊  {dbfs:+.2f} dBFS  尖度 {kurt:.3f}  DC {x14.mean():+.2f}  振り切れ {clip}"
              f"  最大の bin {fin[1 + np.argmax(S[1:])]:.2f} MHz（{S[1:].max():.1f} dBFS/bin）")

    fig.suptitle(a.path, fontsize=10)
    fig.tight_layout()
    out = a.out or (a.path[:-4] if a.path.endswith(".npz") else a.path) + ".png"
    fig.savefig(out, dpi=100)
    print(f"→ {out}")
    if a.show:
        plt.show()
    return 0


if __name__ == "__main__":
    sys.exit(main())
