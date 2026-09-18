#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""`spectrometer.py --tick ... --save X.npz` の記録を読み、全 ch の和の揺れの出どころを切り分ける。

    python3 tools/tick_analyze.py tick_pps.npz      # numpy だけ。ボードでも Mac でも走る

見るもの（2026-09-19 の初回: 揺れが期待の 110 倍で、PPS の縁が埋もれた）:
  1. 畳み込み（エポック畳み込み）: 1 秒周期で畳んで平均する。60 周期なら雑音は 1/√60 になり、
     縁が 1 ダンプに乗っていればそこだけ飛び出す。**外れの判定より約 8 倍感度が高い**
  2. 揺れの周波数: ダンプの並び（10 Hz 標本）の電力スペクトル。1 Hz とその倍数なら PPS 由来
  3. ch 間の相関: var(全 ch の和) / Σ var(各 ch)。1 なら ch ごとに独立（雑音）、ch 数に近ければ
     全 ch が一緒に動いている（利得・較正・広帯域の干渉）
  4. どの ch が揺れているか: 隣との差で見た σ/μ を ch ごとに出し、期待 1/√(Δν·τ) との比が大きい順
  5. 帯域ごと: 8 分割した帯域の和の揺れ
"""
import sys
import numpy as np

FS, NFFT = 4096e6, 8192
DF = FS / NFFT
T_FRAME = NFFT / FS


def main(path):
    d = np.load(path)
    spec = d["spec"].astype(np.float64)          # [dump, ch]
    nacc = int(d["nacc"])
    tau = nacc * T_FRAME
    nd, nch = spec.shape
    sel = slice(50, nch - 50)
    s = spec[:, sel]
    tot = s.sum(axis=1)
    per = int(round(1 / tau))
    print(f"{path}: {nd} ダンプ × τ {tau * 1e3:.1f} ms（{nd * tau:.0f} s）/ 1 秒 = {per} ダンプ")

    # ---- 1. 畳み込み ----
    ncyc = nd // per
    fold = tot[:ncyc * per].reshape(ncyc, per)
    fold = fold / np.median(fold)
    prof = fold.mean(axis=0) - 1
    err = fold.std(axis=0).mean() / np.sqrt(ncyc)
    print(f"\n1. 1 秒で畳んだ平均（{ncyc} 周期、1 点の誤差 {err:.1e}）")
    for i, v in enumerate(prof):
        bar = "#" * int(min(60, max(0, v / err * 2)))
        print(f"   位相 {i:>2}: {v:+.2e}（{v / err:+5.1f} σ）{bar}")

    # ---- 2. 揺れの周波数 ----
    x = tot / tot.mean() - 1
    x = x - np.polyval(np.polyfit(np.arange(nd), x, 1), np.arange(nd))
    ps = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(nd, tau)
    top = np.argsort(ps[1:])[::-1][:8] + 1
    print("\n2. 全 ch の和の揺れの周波数（直線の傾きを除いた後、強い順）")
    for i in top:
        print(f"   {f[i]:6.3f} Hz  相対 {ps[i] / ps[1:].mean():6.1f} 倍")

    # ---- 3. ch 間の相関 ----
    dd = np.diff(s, axis=0)
    r = dd.sum(axis=1).var() / dd.var(axis=0).sum()
    print(f"\n3. var(和の差) / Σ var(各 ch の差) = {r:.1f}（1 = ch ごとに独立 / {s.shape[1]} = 全 ch が一緒に動く）")

    # ---- 4. どの ch が揺れているか ----
    mu = s.mean(axis=0)
    rel = dd.std(axis=0) / mu / np.sqrt(2)
    want = 1 / np.sqrt(DF * tau)
    ratio = rel / want
    print(f"\n4. ch ごとの揺れ（隣との差）/ 期待 {want:.2e}: 中央値 {np.median(ratio):.2f} 倍、"
          f"上位 1 % {np.percentile(ratio, 99):.2f} 倍")
    idx = np.argsort(ratio)[::-1][:10]
    for i in idx:
        k = i + 50
        print(f"   ch {k:>4}（IF {FS / 1e6 - k * DF / 1e6:8.2f} MHz）{ratio[i]:7.2f} 倍 / "
              f"平均の電力 {mu[i] / np.median(mu):.2f} × 中央値")

    # ---- 5. 帯域ごと ----
    print("\n5. 帯域を 8 分割した和の揺れ（隣との差、期待比）")
    edges = np.linspace(0, s.shape[1], 9).astype(int)
    for a, b in zip(edges[:-1], edges[1:]):
        t = s[:, a:b].sum(axis=1)
        w = 1 / np.sqrt(DF * (b - a) * tau)
        v = np.diff(t).std() / t.mean() / np.sqrt(2)
        print(f"   ch {a + 50:>4}–{b + 49:>4}: {v:.2e}（期待 {w:.2e}、{v / w:6.1f} 倍）")


if __name__ == "__main__":
    main(sys.argv[1])
