#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-5 — 状態（on・cd・b・a）ごとの RAW の SNAP から、荒い ch の中の形を比べる（ボードの上で、runs/ のある所で）

  python3 y5_cmp.py [巡の数 6]

形は W-1d と同じ: 2048 点のハニング窓の FFT（2 MHz の格子）、荒い ch k の 32 bin のうち端 2 本ずつを除き、比を中央値で割った std の二乗平均。
床は各状態の偶数巡 / 奇数巡の比の std ÷ 2（= その状態の全部の平均の揺れ）。2 つの平均の差の床は √(床a² ＋ 床b²)。
"""
import sys
import numpy as np

L, NCH, PER = 2048, 32, 32
N = int(sys.argv[1]) if len(sys.argv) > 1 else 6


def spec(files):
    raw = np.concatenate([np.load(f) for f in files]).astype(np.float64)
    seg = raw.reshape(-1, L)
    seg = seg - seg.mean(1, keepdims=True)
    return np.abs(np.fft.rfft(seg * np.hanning(L), axis=1)) ** 2, raw.shape[0]


def res(a, b):
    e = []
    for k in range(NCH):
        s = slice(k * PER + 2, (k + 1) * PER - 2)
        r = a[s] / b[s]
        e.append(np.std(r / np.median(r)))
    return float(np.sqrt(np.mean(np.square(e))))


P, fl, nsnap = {}, {}, {}
for s in ("on", "cd", "b", "a"):
    ev, n0 = spec([f"runs/y5_{s}_{i}_raw.npy" for i in range(2, N + 1, 2)])
    od, n1 = spec([f"runs/y5_{s}_{i}_raw.npy" for i in range(1, N + 1, 2)])
    P[s] = (ev.sum(0) + od.sum(0)) / (len(ev) + len(od))
    fl[s] = res(ev.mean(0), od.mean(0)) / 2
    nsnap[s] = n0 + n1
    print(f"{s:3s}: SNAP {nsnap[s]} 本・床 {fl[s]:.4f}・偶数巡 / 奇数巡 {2 * fl[s]:.4f}")


def show(name, a, b, fa, fb):
    r = res(a, b)
    f = np.hypot(fa, fb)
    print(f"{name:34s}: {r:.4f}（床 {f:.4f}、床を引いて {np.sqrt(max(r * r - f * f, 0)):.4f}）")


print()
for s in ("cd", "b", "a"):
    show(f"{s} / on", P[s], P["on"], fl[s], fl["on"])
show("a / cd", P["a"], P["cd"], fl["a"], fl["cd"])
show("a / b", P["a"], P["b"], fl["a"], fl["b"])

# proj037（W-1d、別の日の ON）と proj028 の生の標本（Y-2）
d = np.load("runs/w1d_grid2.npz")
w = d["P"]
z = np.load("runs/y2_snap.npz")
key = [k for k in z.files if "idle" in k and z[k].ndim == 1 and z[k].size > 60000][0]
S = z[key].astype(np.float64)
fs = np.arange(S.size) * (4096.0 / 131072)
nb = L // 2 + 1
gi = np.round(fs / 2.0).astype(int)
m = gi < nb
snap = np.bincount(gi[m], S[m], minlength=nb) / np.maximum(np.bincount(gi[m], minlength=nb), 1)
print()
for s in ("on", "cd", "b", "a"):
    show(f"{s} / proj037 W-1d の RAW", P[s], w, fl[s], 0.042)
for s in ("on", "cd", "b", "a"):
    show(f"{s} / proj028 の生の標本", P[s], snap, fl[s], 0.0)
rev = np.concatenate([P["on"][k * PER:(k + 1) * PER][::-1] for k in range(NCH)] + [P["on"][NCH * PER:]])
print(f"\n陽性対照: on を荒い ch の中で反転 / on: {res(rev, P['on']):.4f}（0.5 を越えるはず）")
np.savez("runs/y5_grid.npz", **{f"P_{s}": P[s] for s in P}, **{f"fl_{s}": fl[s] for s in fl})
