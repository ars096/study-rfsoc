#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-4 — pon（proj037.bit・全部動く）・pa（同じ .bit・A だけ）・a1（proj037_a1.bit）の RAW の形を比べる（ボードの上で、runs/ のある所で）

  python3 y4_cmp.py [巡の数 6]

形の測り方と床は y5_cmp.py と同じ。Y-5 の結果（runs/y5_grid.npz）と proj028 の生の標本（runs/y2_snap.npz）とも比べる。
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


def show(name, a, b, fa, fb):
    r = res(a, b)
    f = np.hypot(fa, fb)
    print(f"{name:30s}: {r:.4f}（床 {f:.4f}、床を引いて {np.sqrt(max(r * r - f * f, 0)):.4f}）")


P, fl = {}, {}
for s in ("pon", "pa", "a1"):
    ev, _ = spec([f"runs/y4_{s}_{i}_raw.npy" for i in range(2, N + 1, 2)])
    od, _ = spec([f"runs/y4_{s}_{i}_raw.npy" for i in range(1, N + 1, 2)])
    P[s] = (ev.sum(0) + od.sum(0)) / (len(ev) + len(od))
    fl[s] = res(ev.mean(0), od.mean(0)) / 2
    print(f"{s:3s}: SNAP {len(ev) + len(od)} 本（2048 点の区切り）・床 {fl[s]:.4f}・偶数巡 / 奇数巡 {2 * fl[s]:.4f}")

y5 = np.load("runs/y5_grid.npz")
z = np.load("runs/y2_snap.npz")
key = [k for k in z.files if "idle" in k and z[k].ndim == 1 and z[k].size > 60000][0]
S = z[key].astype(np.float64)
gi = np.round(np.arange(S.size) * (4096.0 / 131072) / 2.0).astype(int)
m = gi < L // 2 + 1
snap = np.bincount(gi[m], S[m], minlength=L // 2 + 1) / np.maximum(np.bincount(gi[m], minlength=L // 2 + 1), 1)

print()
show("pa / pon", P["pa"], P["pon"], fl["pa"], fl["pon"])
show("a1 / pon", P["a1"], P["pon"], fl["a1"], fl["pon"])
show("a1 / pa", P["a1"], P["pa"], fl["a1"], fl["pa"])
print()
show("pon / Y-5 の on", P["pon"], y5["P_on"], fl["pon"], float(y5["fl_on"]))
show("pa / Y-5 の a", P["pa"], y5["P_a"], fl["pa"], float(y5["fl_a"]))
print()
for s in ("pon", "pa", "a1"):
    show(f"{s} / proj028 の生の標本", P[s], snap, fl[s], 0.0)


def dv(x, y):
    out = []
    for k in range(NCH):
        s = slice(k * PER + 2, (k + 1) * PER - 2)
        r = np.log(x[s] / y[s])
        out.append(r - r.mean())
    return np.concatenate(out)


d28 = dv(snap, P["pon"])
for s in ("pa", "a1"):
    d = dv(P[s], P["pon"])
    print(f"{s} − pon と proj028 − pon: 相関 {np.corrcoef(d, d28)[0, 1]:.3f}・射影 {d @ d28 / (d28 @ d28):.3f}")
rev = np.concatenate([P["a1"][k * PER:(k + 1) * PER][::-1] for k in range(NCH)] + [P["a1"][NCH * PER:]])
print(f"\n陽性対照: a1 を荒い ch の中で反転 / a1: {res(rev, P['a1']):.4f}（0.5 を越えるはず）")
np.savez("runs/y4_grid.npz", **{f"P_{s}": P[s] for s in P}, **{f"fl_{s}": fl[s] for s in fl})
