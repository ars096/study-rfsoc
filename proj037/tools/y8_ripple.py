#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-8 — ノイズの比（dB）に 1 つの反射の波（遅れ τ、振れは f の 1 次）を当てはめる（runs/ のある所で、README Y-8）

  python3 y8_ripple.py

r(f) = a + b·f + (c0 + c1·f)·cos 2πfτ + (s0 + s1·f)·sin 2πfτ。τ を 0.5〜10 ns で掃き、残りの二乗和が最小のもの。
波を割り落とした後の W-1d の尺（荒い ch の中の形、y4_cmp.py と同じ）も出す。
"""
import numpy as np

NCH, PER = 32, 32
TAUS = np.arange(0.5, 10.0, 0.005)


def basis(f, tau):
    w = 2 * np.pi * f * 1e6 * tau * 1e-9
    g = f / 1000.0
    return np.stack([np.ones_like(f), g, np.cos(w), g * np.cos(w), np.sin(w), g * np.sin(w)], 1)


def fit(f, r):
    best = None
    for tau in TAUS:
        A = basis(f, tau)
        x, res, *_ = np.linalg.lstsq(A, r, rcond=None)
        e = float(np.sum((r - A @ x) ** 2))
        if best is None or e < best[1]:
            best = (tau, e, x)
    tau, e, x = best
    lin = basis(f, tau)[:, :2] @ x[:2]
    expl = 1 - e / float(np.sum((r - lin) ** 2))          # 1 次の傾きを除いた分散のうち、波が説明する割合
    amp = lambda g: float(np.hypot(x[2] + x[3] * g, x[4] + x[5] * g))
    return tau, expl, amp(0.5), amp(1.5), x


def shape(a, b):
    e = []
    for k in range(NCH):
        s = slice(k * PER + 2, (k + 1) * PER - 2)
        q = a[s] / b[s]
        e.append(np.std(q / np.median(q)))
    return float(np.sqrt(np.mean(np.square(e))))


def show(name, f, r):
    tau, expl, a5, a15, _ = fit(f, r)
    print(f"{name:22s}: τ {tau:.3f} ns（周期 {1e3 / tau:.0f} MHz）・説明 {expl * 100:.0f} %・振れ 500 MHz {a5:.2f}・1500 MHz {a15:.2f} dB")
    return tau


def main():
    z4, z5 = np.load("runs/y4_grid.npz"), np.load("runs/y5_grid.npz")
    F = np.arange(z4["P_pon"].size) * 2.0
    m = (F >= 50) & (F <= 2000)
    f = F[m]
    db = lambda x: 10 * np.log10(x)

    rng = np.random.default_rng(1)
    syn = (0.5 + 1.0 * f / 1000) * np.cos(2 * np.pi * f * 1e6 * 3.2e-9 + 0.7) + 0.3 + rng.normal(0, 0.25, f.size)
    show("陽性対照（τ 3.200）", f, syn)
    show("陰性対照 Y-5 on / P-on", f, db(z5["P_on"][m] / z4["P_pon"][m]))
    t_a1 = show("A1 / P-on", f, db(z4["P_a1"][m] / z4["P_pon"][m]))
    t_pa = show("P-a / P-on", f, db(z4["P_pa"][m] / z4["P_pon"][m]))
    print(f"τ の違い: {abs(t_a1 - t_pa) / t_a1 * 100:.1f} %")

    for s in ("a1", "pa"):
        r = db(z4[f"P_{s}"] / z4["P_pon"])
        tau, _, _, _, x = fit(f, r[m])
        wave = basis(F, tau)[:, 2:] @ x[2:]
        flat = z4[f"P_{s}"] / 10 ** (wave / 10)
        print(f"W-1d の尺 {s} / pon: {shape(z4[f'P_{s}'], z4['P_pon']):.4f} → 波を割り落として {shape(flat, z4['P_pon']):.4f}")


if __name__ == "__main__":
    main()
