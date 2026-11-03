#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-10 — 1 つの反射の波を割り落とした後の残りを、床・2 つ目の反射・荒い ch の格子の型に分ける（runs/ のある所で、README Y-10）

  python3 y10_resid.py
"""
import numpy as np

import y8_ripple as y8

NCH, PER = 32, 32
db = lambda x: 10 * np.log10(x)


def fold(r, per):
    """r（dB、全 bin）を per bin の周期で畳んだ型を、もとの長さに並べ直して返す（ch の端 2 bin は y8.shape と同じく使わない）"""
    j = np.arange(r.size) % per
    use = (j >= 2) & (j < per - 2) & (np.arange(r.size) < NCH * PER)
    t = np.array([r[use & (j == q)].mean() if np.any(use & (j == q)) else 0.0 for q in range(per)])
    return t[j], use


def explained(r, per):
    """各 ch の平均を引いた残りの分散のうち、畳んだ型が説明する割合"""
    rc = r.copy()
    for k in range(NCH):
        s = slice(k * PER, (k + 1) * PER)
        rc[s] -= rc[s][2:PER - 2].mean()
    t, use = fold(rc, per)
    return 1 - np.var((rc - t)[use]) / np.var(rc[use]), t


def floorsub(r, fa, fb):
    return float(np.sqrt(max(r * r - fa * fa - fb * fb, 0)))


def main():
    z = np.load("runs/y4_grid.npz")
    F = np.arange(z["P_pon"].size) * 2.0
    m = (F >= 50) & (F <= 2000)
    fpon = float(z["fl_pon"])
    for s in ("a1", "pa"):
        P, fs = z[f"P_{s}"], float(z[f"fl_{s}"])
        r0 = db(P / z["P_pon"])
        tau, _, _, _, x = y8.fit(F[m], r0[m])
        P1 = P / 10 ** ((y8.basis(F, tau)[:, 2:] @ x[2:]) / 10)
        w0, w1 = y8.shape(P, z["P_pon"]), y8.shape(P1, z["P_pon"])
        print(f"\n== {s} / pon（床 {s} {fs:.4f}・pon {fpon:.4f}）")
        print(f"(i)  尺: もと {w0:.4f}（床を引いて {floorsub(w0, fs, fpon):.4f}）→ 1 つ目の反射を割って {w1:.4f}（床を引いて {floorsub(w1, fs, fpon):.4f}）")
        r1 = db(P1 / z["P_pon"])
        y8.TAUS = np.arange(0.5, 20.0, 0.005)
        tau2, expl2, a5, a15, x2 = y8.fit(F[m], r1[m])
        P2 = P1 / 10 ** ((y8.basis(F, tau2)[:, 2:] @ x2[2:]) / 10)
        w2 = y8.shape(P2, z["P_pon"])
        y8.TAUS = np.arange(0.5, 10.0, 0.005)
        print(f"(ii) 2 つ目の反射: τ {tau2:.3f} ns・残りの説明 {expl2 * 100:.0f} %・振れ {a5:.2f} / {a15:.2f} dB → 尺 {w2:.4f}（床を引いて {floorsub(w2, fs, fpon):.4f}）")
        e32, t32 = explained(r1, 32)
        e31, _ = explained(r1, 31)
        e33, _ = explained(r1, 33)
        print(f"(iii) 格子の型（32 bin）の説明 {e32 * 100:.1f} %・偽の周期 31 bin {e31 * 100:.1f} %・33 bin {e33 * 100:.1f} %")
        print("     型（dB、ch の中の位置 2〜29）: " + " ".join(f"{v:+.3f}" for v in t32[2:30]))
        Pg = P1 / 10 ** (fold(np.zeros_like(r1), 32)[0] / 10)
        flat = Pg / 10 ** (np.resize(np.r_[t32[:32]], P1.size) / 10)
        print(f"     格子の型も割り落とした尺 {y8.shape(flat, z['P_pon']):.4f}（床を引いて {floorsub(y8.shape(flat, z['P_pon']), fs, fpon):.4f}）")
        rng = np.random.default_rng(2)
        pat = 0.0864 * np.sin(np.linspace(0, 2 * np.pi, 32, endpoint=False) * 1.5 + 0.3)   # ≒ 2 %（dB で 0.086）
        syn = r1 + np.resize(pat, r1.size)
        _, ts = explained(syn, 32)
        q = np.arange(2, 30)
        print(f"     陽性対照: 2 % の型を足して取り戻した型と、(足した型 ＋ もとの型) の相関 {np.corrcoef(ts[q], (pat + t32[:32])[q])[0, 1]:.3f}"
              f"・足した分だけの相関 {np.corrcoef(ts[q] - t32[q], pat[q])[0, 1]:.3f}")


if __name__ == "__main__":
    main()
