#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 W-1c — 2 つの .bit の細かいスペクトル（<out>_spec.npy: チャンク × 3,670,016）の形を比べる（PC でもボードでも、numpy だけ）

  python3 tools/cmp_spec.py --a runs/w1c_a1 runs/w1c_a2 --b runs/w1c_b1 runs/w1c_b2

  各組（A・B）の全部のチャンクを平均し、1024 bin ごとの中央値（3,584 点、荒い ch あたり 112 点）にしてから比 B / A を取る。
  判定（README W-1 の予言）:
    水準: 荒い ch ごとの比の中央値が 1 ± --tol-level（0.03。利得はどちらも σ 12 に合わせるので、合わせの差だけが出る）
    形  : 比を荒い ch ごとの中央値で割った残りの 1 % 点〜99 % 点が 1 ± --tol-shape（0.01）
  同じ組の 2 回（A2 / A1）の同じ数えも並べて出す（.bit の違いが Overlay の読み直しの揺れより大きいか）
  陽性対照（--posctl）: B の荒い ch の並びを 1 つずらして比べる → 荒い ch ごとに違うアナログの帯域の傾きが残り、形で落ちる
"""
import argparse
import sys

import numpy as np

NCH, NKEEP, BLK = 32, 114688, 1024


def load(names):
    xs = [np.load(n + "_spec.npy").astype(np.float64) for n in names]
    return [x.mean(axis=0) for x in xs]


def coarse(sp):
    m = np.median(sp.reshape(-1, BLK), axis=1)                 # 3,584 点
    return m


def per_ch(r):
    return np.array([np.median(r[k * (NKEEP // BLK):(k + 1) * (NKEEP // BLK)]) for k in range(NCH)])


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--a", nargs="+", required=True)
    p.add_argument("--b", nargs="+", required=True)
    p.add_argument("--tol-level", type=float, default=0.03)
    p.add_argument("--tol-shape", type=float, default=0.01)
    p.add_argument("--posctl", action="store_true")
    a = p.parse_args()
    A, B = load(a.a), load(a.b)
    if a.posctl:
        B = [np.roll(x, NKEEP) for x in B]

    def judge_pair(ca, cb):
        r = cb / ca
        rk = per_ch(r)
        sh = r / np.repeat(rk, NKEEP // BLK)
        return r, rk, sh, np.percentile(sh, [1, 99])

    ca = np.mean([coarse(x) for x in A], axis=0)
    cb = np.mean([coarse(x) for x in B], axis=0)
    r, rk, sh, (s1, s99) = judge_pair(ca, cb)
    print(f"B / A（{len(B)} 回 / {len(A)} 回の平均）: 比の中央値 {np.median(r):.4f}")
    print("  水準: 荒い ch ごとの比の中央値: " + " ".join(f"{x:.3f}" for x in rk) + f"（最小 {rk.min():.4f}・最大 {rk.max():.4f}）")
    print(f"  形  : 荒い ch ごとに割った残りの 1 % 点 {s1:.4f}・99 % 点 {s99:.4f}（最悪の荒い ch {int(np.argmax(np.abs(sh - 1)) // (NKEEP // BLK))}）")
    for nm, grp in (("A", A), ("B", B)):
        if len(grp) >= 2:
            _, rkk, _, (t1, t99) = judge_pair(coarse(grp[0]), coarse(grp[1]))
            print(f"  同じ組の 2 回（{nm}2 / {nm}1）: 水準 {rkk.min():.4f}〜{rkk.max():.4f}・形 {t1:.4f}〜{t99:.4f}")
    ok_level = bool(np.all(np.abs(rk - 1) <= a.tol_level))
    ok_shape = bool(abs(s1 - 1) <= a.tol_shape and abs(s99 - 1) <= a.tol_shape)
    print(f"  水準 {'○' if ok_level else '×'}（±{a.tol_level}）・形 {'○' if ok_shape else '×'}（±{a.tol_shape}）")
    ok = ok_level and ok_shape
    if a.posctl:
        print("結果: " + ("不合格（陽性対照として正しく落ちた）" if not ok_shape else "陽性対照が通ってしまった（形の比べが荒い ch の並びを見ていない）"))
        return 0 if not ok_shape else 1
    print("結果: " + ("全部通過" if ok else "不合格"))
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
