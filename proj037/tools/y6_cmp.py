#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-6 — CW の利得と像を状態（pon・pa・a1、2 巡）ごとに比べる（ボードの上で、runs/ のある所で）

  python3 y6_cmp.py

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
    meta = json.load(open(f"runs/y6_{t}.json"))
    rows = meta["rows"]
    off = [spec(f"runs/y6_{t}_{r['i']}") for r in rows if r["f"] is None]
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
        S = spec(f"runs/y6_{t}_{r['i']}")
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
json.dump({t: R[t] for t in TAGS}, open("runs/y6_cmp.json", "w"), indent=1)
