#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-7 — 較正を止めた CW の利得と像を状態（pon・pa・a1、2 巡）ごとに比べる（ボードの上で、runs/ のある所で）

  python3 y7_cmp.py

CW の読みは y6_cmp.py と同じ（名の頭が y7）。足したもの: 止まったかの照合（係数 c0・f0・f1）、止めた状態のノイズ n1 / n0 の形（W-1d の尺）、
f0 の係数の状態ごとの違い。

8192 点の Hann（0.5 MHz）。CW の電力 = 山（f の ±2 bin で最大の bin）の ±4 bin の和。
像 = CW と、SG OFF の目録（頭と尾の 2 回のどちらかで床の中央値 ＋ 15 dB を越える bin ±2）を除いた bin の最大（dBc）と、その周波数。
W-1c の読みの位置 128k ＋ 64 − f（±1 MHz）の dBc も別に出す。H2（2f）の dBc は陽性対照。
"""
import json
import numpy as np

L, FS = 8192, 4096.0
DF = FS / L
TAGS = ("pon1", "pon2", "pa1", "pa2", "a11", "a12")
W = np.hanning(L)


def spec(o):
    x = np.load(o + "_raw.npy").astype(np.float64).reshape(-1, L)
    x -= x.mean(1, keepdims=True)
    return (np.abs(np.fft.rfft(x * W, axis=1)) ** 2).mean(0)


def band(S, f, hw=4, search=2):
    k0 = int(round(f / DF))
    lo = max(k0 - search, 0)
    k = lo + int(np.argmax(S[lo:k0 + search + 1]))
    return float(S[max(k - hw, 0):k + hw + 1].sum()), k


R = {}
for t in TAGS:
    meta = json.load(open(f"runs/y7_{t}.json"))
    rows = meta["rows"]
    off = [spec(f"runs/y7_{t}_{r['i']}") for r in rows if r["f"] is None]
    mask = np.zeros(L // 2 + 1, bool)
    for S in off:
        hot = np.where(S > np.median(S) * 10 ** 1.5)[0]
        for k in hot:
            mask[max(k - 2, 0):k + 3] = True
    mask[:8] = True
    out = []
    for r in rows:
        if r["f"] is None:
            continue
        f = r["f"]
        S = spec(f"runs/y7_{t}_{r['i']}")
        p, kc = band(S, f)
        m = mask.copy()
        m[max(kc - 6, 0):kc + 7] = True
        f2 = 2 * f
        h2 = band(S, f2)[0] / p if f2 < FS / 2 - 4 else np.nan
        if f2 < FS / 2 - 4:
            k2 = int(round(f2 / DF)); m[max(k2 - 6, 0):k2 + 7] = True
        ch = int(f // 64)
        fm = 128 * ch + 64 - f
        km = int(round(fm / DF))
        mir = S[km - 2:km + 3].max() * 9 / p          # ±1 MHz の最大の bin を、山の和（9 bin）と同じ尺に
        Sx = np.where(m, 0, S)
        ks = int(np.argmax(Sx))
        out.append(dict(f=f, p=p, h2=h2, mir=mir, spur=Sx[ks] * 9 / p, fspur=ks * DF))
    R[t] = out

f = np.array([o["f"] for o in R["pon1"]])
P = {t: np.array([o["p"] for o in R[t]]) for t in TAGS}
db = lambda x: 10 * np.log10(x)
print("再現（同じ状態の 2 巡の CW の利得の比）: " + "・".join(
    f"{s} {np.ptp(P[s + '1'] / P[s + '2'] / np.median(P[s + '1'] / P[s + '2'])) * 50:.2f} %（±、中央値で割る）" for s in ("pon", "pa", "a1")))
for t in TAGS:
    h2 = np.array([o["h2"] for o in R[t]])
    print(f"{t:4s}: CW の利得 {db(np.median(P[t] / P['pon1'])):+.2f} dB（pon1 に対して、中央値）・H2 {np.nanmedian(db(h2)):.1f} dBc"
          f"・鏡の位置の最大 {db(max(o['mir'] for o in R[t])):.1f} dBc・ほかの線の最大 {db(max(o['spur'] for o in R[t])):.1f} dBc")

pon = (P["pon1"] + P["pon2"]) / 2
for s in ("pa", "a1"):
    g = (P[s + "1"] + P[s + "2"]) / 2 / pon
    print(f"\n{s} / pon の CW の利得の比（荒い ch ごとに中央値で割る、%）:")
    for k in sorted(set((f // 64).astype(int))):
        sel = (f // 64).astype(int) == k
        r = g[sel] / np.median(g[sel])
        print(f"  ch {k:2d}: " + " ".join(f"{(v - 1) * 100:+.1f}" for v in r) + f"   （rms {np.std(r) * 100:.2f} %）")

z = np.load("runs/y4_grid.npz")
gi = np.clip(np.round(f / 2.0).astype(int), 0, 1024)
for s, key in (("pa", "P_pa"), ("a1", "P_a1")):
    g = (P[s + "1"] + P[s + "2"]) / 2 / pon
    nr = z[key][gi] / z["P_pon"][gi]
    a, b = [], []
    for k in sorted(set((f // 64).astype(int))):
        sel = (f // 64).astype(int) == k
        a.append(np.log(g[sel] / np.median(g[sel])))
        b.append(np.log(nr[sel] / np.median(nr[sel])))
    a, b = np.concatenate(a), np.concatenate(b)
    print(f"{s} / pon: CW の利得の比とノイズの比（Y-4）の相関 {np.corrcoef(a, b)[0, 1]:.3f}・CW の rms {np.std(a) * 100:.2f} %・ノイズの rms {np.std(b) * 100:.2f} %")

print("\n鏡の位置（128k ＋ 64 − f）と、ほかの線の最大（dBc、2 巡の平均の電力で）:")
for t in ("pon", "pa", "a1"):
    mir = (np.array([o["mir"] for o in R[t + "1"]]) + np.array([o["mir"] for o in R[t + "2"]])) / 2
    sp = [(o["spur"], o["fspur"], o["f"]) for o in R[t + "1"]]
    top = sorted(sp, reverse=True)[:5]
    print(f"  {t:3s}: 鏡 中央値 {np.median(db(mir)):.1f}・最大 {db(mir.max()):.1f} dBc（f {f[np.argmax(mir)]:.1f}）"
          f" / ほかの線の上位: " + "・".join(f"{db(v):.1f} dBc @ {fs:.1f}（f {ff:.1f}）" for v, fs, ff in top))
json.dump({t: R[t] for t in TAGS}, open("runs/y7_cmp.json", "w"), indent=1)


# 止まったか（陽性対照）と係数
print("\n係数（OCB1・OCB2・GCB・TSCB）:")
C = {}
for t in TAGS:
    c0, f0, f1 = (json.load(open(f"runs/y7_coef_{t}_{k}.json")) for k in ("c0", "f0", "f1"))
    C[t] = f0["c0"]
    mv = [cb for cb in range(4) if c0["c0"][cb] != c0["c1"][cb]]
    print(f"  {t:4s}: 止める前に 1 s で動く {mv}・f0 CalFrozen {f0['freeze']['CalFrozen']}（1 s で{'動かず' if f0['same'] else '動く'}）"
          f"・f1 CalFrozen {f1['freeze']['CalFrozen']}（{'動かず' if f1['same'] else '動く'}）・f1 = f0（GCB・OCB2・TSCB）: {all(f1['c0'][cb] == f0['c0'][cb] for cb in (1, 2, 3))}・f1 = f0（OCB1）: {f1['c0'][0] == f0['c0'][0]}")
s32 = lambda v: v - (1 << 32) if v >= 1 << 31 else v
for cb, nm in ((2, "GCB"), (3, "TSCB")):
    print(f"  f0 の {nm}: " + " / ".join(f"{t} {[s32(v) for v in C[t][cb][:4]]}" for t in TAGS))

# 止めた状態のノイズの形 n1 / n0（W-1d の尺。床は各 RAW の前半 / 後半）
L2, NCH, PER = 2048, 32, 32


def pw(o):
    x = np.load(o + "_raw.npy").astype(np.float64).reshape(-1, L2)
    x -= x.mean(1, keepdims=True)
    p = np.abs(np.fft.rfft(x * np.hanning(L2), axis=1)) ** 2
    h = len(p) // 2
    return p.mean(0), p[:h].mean(0), p[h:].mean(0)


def res(a, b):
    e = []
    for k in range(NCH):
        s_ = slice(k * PER + 2, (k + 1) * PER - 2)
        r = a[s_] / b[s_]
        e.append(np.std(r / np.median(r)))
    return float(np.sqrt(np.mean(np.square(e))))


print("\n止めた状態のノイズの形 n1 / n0（床を引いて）:")
N0 = {}
for t in TAGS:
    a, a1, a2 = pw(f"runs/y7_{t}_n0")
    b, b1, b2 = pw(f"runs/y7_{t}_n1")
    N0[t] = a
    r, fa, fb = res(b, a), res(a1, a2) / 2, res(b1, b2) / 2
    print(f"  {t:4s}: {r:.4f}（床 {np.hypot(fa, fb):.4f}、床を引いて {np.sqrt(max(r * r - fa * fa - fb * fb, 0)):.4f}）")
z4 = np.load("runs/y4_grid.npz")
for s_, key in (("pa", "P_pa"), ("a1", "P_a1")):
    n = (N0[s_ + "1"] + N0[s_ + "2"]) / 2 / ((N0["pon1"] + N0["pon2"]) / 2)
    print(f"  n0 の {s_} / pon の形と Y-4 の {s_} / pon: 違い {res(n, z4[key] / z4['P_pon']):.4f}（Y-4 の比そのものの大きさ {res(z4[key], z4['P_pon']):.4f}）")
