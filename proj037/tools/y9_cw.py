#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-9 — 全帯域の CW の比 A1 / P-on に、Y-8 と同じ 1 つの反射の波を当てはめる（ボードの上で、runs/ のある所で、README Y-9）

  python3 y9_cw.py

CW の電力は y6_cmp.py と同じ（8192 点の Hann、山の ±4 bin の和）。当てはめは y8_ripple.py と同じ形。
"""
import json
import numpy as np

import y8_ripple as y8

L = 8192
W = np.hanning(L)
TAGS = ("pon1", "a11", "pon2", "a12")


def power(o, f):
    x = np.load(o + "_raw.npy").astype(np.float64).reshape(-1, L)
    x -= x.mean(1, keepdims=True)
    S = (np.abs(np.fft.rfft(x * W, axis=1)) ** 2).mean(0)
    k0 = int(round(f / (4096.0 / L)))
    k = k0 - 2 + int(np.argmax(S[k0 - 2:k0 + 3]))
    return float(S[k - 4:k + 5].sum())


P = {}
for t in TAGS:
    rows = [r for r in json.load(open(f"runs/y9_{t}.json"))["rows"] if r["f"] is not None]
    f = np.array([r["f"] for r in rows])
    P[t] = np.array([power(f"runs/y9_{t}_{r['i']}", r["f"]) for r in rows])
db = lambda x: 10 * np.log10(x)
r1, r2 = db(P["a11"] / P["pon1"]), db(P["a12"] / P["pon2"])
print(f"再現: 2 巡の A1 / P-on の差 rms {np.std(r1 - r2):.3f} dB（平均の差 {np.mean(r1 - r2):+.3f} dB）")
r = (r1 + r2) / 2

y7 = json.load(open("runs/y7_cmp.json"))
f7 = np.array([o["f"] for o in y7["pon1"]])
g7 = db((np.array([o["p"] for o in y7["a11"]]) + np.array([o["p"] for o in y7["a12"]]))
        / (np.array([o["p"] for o in y7["pon1"]]) + np.array([o["p"] for o in y7["pon2"]])))
d = np.interp(f7, f, r) - g7
print(f"陽性対照（Y-7 の 80 点との差、内挿）: 中央値 {np.median(d):+.2f}・最大 |差| {np.max(np.abs(d)):.2f} dB")

tau, expl, a5, a15, x = y8.fit(f, r)
print(f"CW の A1 / P-on: τ {tau:.3f} ns（周期 {1e3 / tau:.0f} MHz）・説明 {expl * 100:.0f} %・振れ 500 MHz {a5:.2f}・1500 MHz {a15:.2f} dB"
      f"・ノイズの τ 3.285 ns との違い {abs(tau - 3.285) / 3.285 * 100:.1f} %")
z = np.load("runs/y4_grid.npz")
F = np.arange(z["P_pon"].size) * 2.0
rn = np.interp(f, F, db(z["P_a1"] / z["P_pon"]))
print(f"CW の比とノイズの比（dB、同じ f）の相関 {np.corrcoef(r, rn)[0, 1]:.3f}")
print("f（MHz）と比（dB）: " + " ".join(f"{fi:.0f}:{ri:+.2f}" for fi, ri in zip(f[::5], r[::5])))
np.savez("runs/y9_cw.npz", f=f, **{f"P_{t}": P[t] for t in TAGS})
