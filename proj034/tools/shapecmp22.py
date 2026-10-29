#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj034 R-2 — 2 つの 2G-2 の記録（.s45、g22cw.py の read）の平均スペクトルを窓ごとに ch で比べ、床の差と ch の並びが同じかを見る（SG なし）
proj033 の tools/shapecmp21.py（2G-1、1 窓・131,072 ch・M 16384）を 2G-2（2 窓・65,536 ch・M 8192）に直したもの

  python3 shapecmp22.py runs/r1_034a.s45 runs/r1_025a.s45 --win A0 --spur 0.05                 # 床の差（dB）・比の散らばり・細い山の位置
  python3 shapecmp22.py runs/r1_034a.s45 runs/r1_025a.s45 --win A0 --spur 0.05 --posctl conj   # 陽性対照: A の銀行の中で行 r と M − r を入れ替える
  python3 shapecmp22.py ... --posctl bank    # 陽性対照: A の行 > M/2（共役の側）を銀行 7 − b から取る
  python3 shapecmp22.py ... --posctl shift   # 陽性対照: A を 1 ch ずらす
  python3 shapecmp22.py ... --skip-self      # 山の判定から自己共役の行を外す（R-2b の判定はこれで）

ch c = 65535 − i（i は送る番号）、行 r = c mod 8192、銀行 b = c div 8192。r > 4096 が s2_q の 2 行目（共役の側、鎖の行 M − r・銀行 15 − b）、r = 0・4096 は自己共役の行
判定は shapecmp21.py と同じ: 128 ch ごとの中央値で割った比の σ ≦ 雑音の見込み × 3 かつ 1 %〜99 % が ±--tol、--spur > 0 なら細い山が A に半分以上残った割合 ≧ 0.9
numpy だけ（PYTHONPATH=pynq）
"""
import argparse
import sys

import numpy as np

import g22cw as G
import s45proto as P

M = 8192


def mean_spec(fn, core):
    recs, _, _ = G.read(fn)
    rs = recs[core][P.FMT_F32]
    sp = np.mean([d["data"].astype(np.float64) for d in rs], axis=0) / rs[0]["nacc"]
    return sp[::-1], "ABCD"[rs[0]["src"]], len(rs), rs[0]["nacc"]      # ch c の順に


def side(c):
    r = c % M
    return "自己共役" if r in (0, M // 2) else ("共役" if r > M // 2 else "直接")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--win", choices=G.KEYS, default="A0")
    p.add_argument("--posctl", choices=("conj", "bank", "shift"), default=None)
    p.add_argument("--tol", type=float, default=0.1)
    p.add_argument("--spur", type=float, default=0.0)
    p.add_argument("--edge", type=int, default=512)
    p.add_argument("--skip-self", action="store_true", help="山の判定から自己共役の行（r = 0・4096、ADC のインターリーブの山が載せ直しで揺れる。proj033 R-2b）を外す")
    o = p.parse_args()
    core = G.KEYS.index(o.win)
    sa, srca, na, ka = mean_spec(o.a, core)
    sb, srcb, nb, kb = mean_spec(o.b, core)
    if srca != srcb:
        print(f"src が違う（{srca}・{srcb}）。比べない"); sys.exit(1)
    nbk = len(sa) // M
    if o.posctl == "conj":
        sa = sa.reshape(nbk, M)[:, (M - np.arange(M)) % M].ravel()
    elif o.posctl == "bank":
        x = sa.reshape(nbk, M).copy()
        x[:, M // 2 + 1:] = x[::-1, M // 2 + 1:]
        sa = x.ravel()
    elif o.posctl == "shift":
        sa = np.roll(sa, 1)
    sl = slice(o.edge, len(sa) - o.edge)
    r0 = sa[sl] / sb[sl]
    print(f"{o.win}: 床（1 フレームあたりの中央値）A {np.median(sa):.4g}・B {np.median(sb):.4g}・比の中央値 {10 * np.log10(np.median(r0)):+.3f} dB（A / B）")
    r = r0 / np.median(r0)
    n128 = len(r) // 128
    med = np.repeat(np.median(r[: n128 * 128].reshape(n128, 128), axis=1), 128)
    r = r[: n128 * 128] / med
    sig = 1.4826 * np.median(np.abs(r - 1))
    exp = np.sqrt(1.0 / (na * ka) + 1.0 / (nb * kb))
    lo, hi = np.percentile(r, [1, 99])
    ok = sig <= 3 * exp and lo >= 1 - o.tol and hi <= 1 + o.tol
    print(f"{'OK ' if ok else 'NG '} 比の σ {sig:.4f}（雑音の見込み {exp:.4f}）・1 % {lo:.4f}・99 % {hi:.4f}（src {srca}、{na} × {nb} ダンプ）")
    if o.spur:
        def excess(x):
            w = np.lib.stride_tricks.sliding_window_view(np.pad(x, 4, mode="edge"), 9)
            return x / np.median(np.delete(w, 4, axis=1), axis=1) - 1
        ea, eb = excess(sa[sl]), excess(sb[sl])
        idx = np.nonzero(eb > o.spur)[0]
        if o.skip_self:
            idx = np.array([i for i in idx if side(o.edge + int(i)) != "自己共役"], dtype=int)
        if len(idx):
            q = ea[idx] / eb[idx]
            keep = np.mean(q > 0.5)
            ok = keep >= 0.9
            cs = o.edge + idx
            cnt = {k: sum(side(int(c)) == k for c in cs) for k in ("直接", "共役", "自己共役")}
            print(f"{'OK ' if ok else 'NG '} B の山 {len(idx)} 個（{cnt}）・A に半分以上残った割合 {keep:.2f}・高さの比の中央値 {np.median(q):.2f}")
            for c, qa, qb in sorted(zip(cs, ea[idx], eb[idx]), key=lambda t: -t[2])[:12]:
                print(f"    ch {int(c)}（行 {int(c) % M}・銀行 {int(c) // M}・{side(int(c))}）: B +{qb:.1%}・A {qa:+.1%}")
        else:
            ok = False
            print("NG  B に山が無い（比べられない）")
    print("結果: " + ("全部通過" if ok else "不合格"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
