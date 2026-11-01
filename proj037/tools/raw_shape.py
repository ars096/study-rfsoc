#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 W-1c の診断 — 細かいスペクトル（<out>_spec.npy）の荒い ch の中の形を、荒い段を通らない RAW の SNAP（<out>_raw.npy）と比べる（numpy だけ）

  python3 tools/raw_shape.py --raw runs/w1d_r1 runs/w1d_r2 ... --spec A=runs/w1c_a1,runs/w1c_a2 B=runs/w1c_b1,runs/w1c_b2

  RAW: SNAP（int16 × 8,192）を 2,048 点ずつ Hann 窓で FFT して平均（2 MHz の格子）
  細かいスペクトル: 全体の bin j = k·114,688 ＋ i が IF = j·fs / (56·2^17)（INTERFACE、S0 = k·114,688）。2 MHz の格子に平均
  荒い ch ごとに（両端 2 格子を除く）比 spec / RAW を中央値で割り、その rms を「残り」とする
  陽性対照（--posctl）: 細かいスペクトルの荒い ch の中を反転する → 残りが床より大きく上がる（形を見ている印）
  床: RAW の SNAP の区切りを偶数番・奇数番に分けた比の rms / 2（全部の平均の揺れの見積もり）
"""
import argparse

import numpy as np

NCH, NK, FS, L = 32, 114688, 4096.0, 2048
DFR = FS / L
PER = int(64 / DFR)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--raw", nargs="+", required=True)
    p.add_argument("--spec", nargs="+", required=True, help="名前=接頭辞,接頭辞,…")
    p.add_argument("--posctl", action="store_true")
    a = p.parse_args()
    raw = np.concatenate([np.load(n + "_raw.npy") for n in a.raw]).astype(np.float64)
    seg = raw.reshape(-1, L)
    seg = seg - seg.mean(1, keepdims=True)
    S = np.abs(np.fft.rfft(seg * np.hanning(L), axis=1)) ** 2
    P, P1, P2 = S.mean(0), S[0::2].mean(0), S[1::2].mean(0)
    sl = [slice(k * PER + 2, (k + 1) * PER - 2) for k in range(NCH)]
    fl = np.array([np.std((P1[s] / P2[s]) / np.median(P1[s] / P2[s])) / 2 for s in sl])
    print(f"RAW: SNAP {raw.shape[0]} 本・床 {np.sqrt(np.mean(fl ** 2)):.4f}")
    idx = np.round(np.arange(NCH * NK) * (FS / 56 / 131072) / DFR).astype(int)
    cnt = np.maximum(np.bincount(idx, minlength=P.size), 1)
    res = {}
    for item in a.spec:
        name, pre = item.split("=", 1)
        x = np.mean([np.load(n + "_spec.npy").astype(np.float64).mean(0) for n in pre.split(",")], 0)
        if a.posctl:
            x = x.reshape(NCH, NK)[:, ::-1].ravel()
        g = np.bincount(idx, x, minlength=P.size) / cnt
        e = np.array([np.std((g[s] / P[s]) / np.median(g[s] / P[s])) for s in sl])
        res[name] = e
        tot = np.mean(e ** 2)
        print(f"{name}: 残り {np.sqrt(tot):.4f}・床を引いて {np.sqrt(max(tot - np.mean(fl ** 2), 0)):.4f}")
    print("ch: " + "  ".join(res) + "  床")
    for k in range(NCH):
        print(f"{k:2d}: " + "  ".join(f"{res[n][k]:.3f}" for n in res) + f"  {fl[k]:.3f}")


if __name__ == "__main__":
    main()
