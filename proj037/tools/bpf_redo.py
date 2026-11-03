#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 BPF の内で出し直す — Y-4・Y-8・W-1e の数を、荒い ch 全部（0〜31）と BPF の通過域の内（ch 4〜30）で並べる（ボードの上で、runs/ のある所で、README「BPF の内で出し直す」）

  python3 bpf_redo.py

ノイズは BPF 2100〜3900 MHz を通り、4096 MS/s の第 2 ナイキストで IF = 4096 − RF（196〜1996 MHz）に折り返す。
ch 4〜30（IF 256〜1984 MHz）は全部が通過域の内。ch 0〜3・31 は BPF の外か端を含む。
尺・床・相関の作りは y4_cmp.py と同じ（2,048 点・Hann、ch ごとに比を中央値で割った std の rms、端 2 格子を除く）。反射の当てはめは y8_ripple.fit。
"""
import numpy as np

import y8_ripple as y8

L, NCH, PER = 2048, 32, 32
ALL, IN = list(range(NCH)), list(range(4, 31))
F = np.arange(L // 2 + 1) * 2.0


def spec(files):
    raw = np.concatenate([np.load(f) for f in files]).astype(np.float64)
    seg = raw.reshape(-1, L)
    seg = seg - seg.mean(1, keepdims=True)
    return np.abs(np.fft.rfft(seg * np.hanning(L), axis=1)) ** 2


def res(a, b, chs):
    e = []
    for k in chs:
        s = slice(k * PER + 2, (k + 1) * PER - 2)
        r = a[s] / b[s]
        e.append(np.std(r / np.median(r)))
    return float(np.sqrt(np.mean(np.square(e))))


def dv(x, y, chs):
    out = []
    for k in chs:
        s = slice(k * PER + 2, (k + 1) * PER - 2)
        r = np.log(x[s] / y[s])
        out.append(r - r.mean())
    return np.concatenate(out)


def sub(r, *f):
    return np.sqrt(max(r * r - sum(x * x for x in f), 0))


def main():
    P, fl = {}, {}
    for s in ("pon", "pa", "a1"):
        ev = spec([f"runs/y4_{s}_{i}_raw.npy" for i in range(2, 7, 2)])
        od = spec([f"runs/y4_{s}_{i}_raw.npy" for i in range(1, 7, 2)])
        P[s] = (ev.sum(0) + od.sum(0)) / (len(ev) + len(od))
        fl[s] = {n: res(ev.mean(0), od.mean(0), c) / 2 for n, c in (("all", ALL), ("in", IN))}
    z = np.load("runs/y2_snap.npz")
    key = [k for k in z.files if "idle" in k and z[k].ndim == 1 and z[k].size > 60000][0]
    S = z[key].astype(np.float64)
    gi = np.round(np.arange(S.size) * (4096.0 / 131072) / 2.0).astype(int)
    m = gi < L // 2 + 1
    snap = np.bincount(gi[m], S[m], minlength=L // 2 + 1) / np.maximum(np.bincount(gi[m], minlength=L // 2 + 1), 1)

    print("Y-4（床を引いた値、ch 0〜31 → ch 4〜30）")
    for s in ("pon", "pa", "a1"):
        print(f"  床 {s:3s}: {fl[s]['all']:.4f} → {fl[s]['in']:.4f}")
    for name, a, b in (("pa / pon", "pa", "pon"), ("a1 / pon", "a1", "pon"), ("a1 / pa", "a1", "pa")):
        v = [sub(res(P[a], P[b], c), fl[a][n], fl[b][n]) for n, c in (("all", ALL), ("in", IN))]
        print(f"  {name:22s}: {v[0]:.4f} → {v[1]:.4f}")
    for s in ("pon", "pa", "a1"):
        v = [sub(res(P[s], snap, c), fl[s][n]) for n, c in (("all", ALL), ("in", IN))]
        print(f"  {s + ' / proj028 の生の標本':22s}: {v[0]:.4f} → {v[1]:.4f}")
    for s in ("pa", "a1"):
        v = []
        for c in (ALL, IN):
            d, d28 = dv(P[s], P["pon"], c), dv(snap, P["pon"], c)
            v.append((np.corrcoef(d, d28)[0, 1], d @ d28 / (d28 @ d28)))
        print(f"  {s} − pon と proj028 − pon の相関・射影: {v[0][0]:.3f}・{v[0][1]:.3f} → {v[1][0]:.3f}・{v[1][1]:.3f}")

    print("Y-8（反射の当てはめ: IF 50〜2000 → 200〜1990 MHz、尺は床を引いて ch 0〜31 → ch 4〜30）")
    for s in ("a1", "pa"):
        out = []
        for (lo, hi), chs, n in (((50, 2000), ALL, "all"), ((200, 1990), IN, "in")):
            mm = (F >= lo) & (F <= hi)
            tau, expl, a5, a15, x = y8.fit(F[mm], 10 * np.log10(P[s][mm] / P["pon"][mm]))
            wave = y8.basis(F, tau)[:, 2:] @ x[2:]
            flat = P[s] / 10 ** (wave / 10)
            out.append((tau, expl, a5, a15, sub(res(flat, P["pon"], chs), fl[s][n], fl["pon"][n])))
        print(f"  {s} / pon: " + " → ".join(f"τ {t:.3f} ns・説明 {e * 100:.0f} %・振れ {a:.2f} / {b:.2f} dB・残り {r:.4f}" for t, e, a, b, r in out))

    print("W-1e（細かい / RAW、床を引いて ch 0〜31 → ch 4〜30）")
    raw = np.concatenate([np.load(f"runs/w1e_{i}_raw.npy") for i in range(1, 12)]).astype(np.float64)
    seg = raw.reshape(-1, L)
    seg = seg - seg.mean(1, keepdims=True)
    Sr = np.abs(np.fft.rfft(seg * np.hanning(L), axis=1)) ** 2
    Pr = Sr.mean(0)
    NK = 114688
    idx = np.round(np.arange(NCH * NK) * (4096.0 / 56 / 131072) / 2.0).astype(int)
    cnt = np.maximum(np.bincount(idx, minlength=Pr.size), 1)
    x = np.mean([np.load(f"runs/w1e_{i}_spec.npy").astype(np.float64).mean(0) for i in range(1, 12)], 0)
    g = np.bincount(idx, x, minlength=Pr.size) / cnt
    for n, c in (("all", ALL), ("in", IN)):
        f = res(Sr[0::2].mean(0), Sr[1::2].mean(0), c) / 2
        r = res(g, Pr, c)
        print(f"  {n:3s}: 残り {r:.4f}・床 {f:.4f}・床を引いて {sub(r, f):.4f}")


if __name__ == "__main__":
    main()
