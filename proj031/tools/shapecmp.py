#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj030 R-4 — 2 つの 2G-4 の記録（.s45）の平均スペクトルの形を ch ごとに比べ、ch の並びが同じかを見る（SG なし、雑音の帯域の形と ADC の山で）

  python3 shapecmp.py runs/r1a.s45 ../proj027/runs/g24_lvl.s45                 # 窓ごと（同じ src の組）に比 r[ch] = A[ch] / B[ch] / 中央値
  python3 shapecmp.py runs/r1a.s45 ../proj027/runs/g24_lvl.s45 --posctl mirror  # 陽性対照: A の 8 ch の組（行）の中を逆順に
  python3 shapecmp.py runs/r1a.s45 ../proj027/runs/g24_lvl.s45 --posctl shift   # 陽性対照: A を 1 ch ずらす

ch の並びが同じなら、比は帯域の形が消えて平ら（ch ごとの散らばりは雑音の √(1/N) の程度）。並びが違うと帯域の形と山が残り、散らばりが桁で増える。
判定（128 ch ごとの中央値で割って遅い形を除いた後）: 比の ch ごとの散らばり（中央値からの MAD を σ に直したもの）≦ 雑音の見込み × 3、かつ 比の 1 % 〜 99 % が中央値の ±--tol
--spur 0.05: 判定を細い山の位置に替える（R-4 の 1 回目で、散らばりの判定は陽性対照が落ちず比べる力が無かった）。B（相手の記録）で両隣 ±4 ch の中央値から 5 % 以上抜けた ch を山とし、
A の同じ ch で山の高さが半分以上残った割合 ≧ 0.9 で通過
numpy だけ。g24cw.py の read を使う（PYTHONPATH=pynq）
"""
import argparse
import sys

import numpy as np

import g24cw as G


def mean_spec(fn):
    recs, _, bad = G.read(fn)
    out = {}
    for c in range(G.NC):
        rs = recs.get(c, {}).get(G.P.FMT_F32, [])
        if rs:
            out[c] = (np.mean([np.asarray(d["data"], dtype=np.float64) for d in rs], axis=0), "ABCD"[rs[0]["src"]], len(rs), rs[0]["nacc"])
    return out, bad


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--posctl", choices=("mirror", "shift"), default=None)
    p.add_argument("--tol", type=float, default=0.1, help="比の 1 %〜99 % の許す幅（中央値に対する割合）")
    p.add_argument("--spur", type=float, default=0.0, help="> 0: 判定を山の位置の一致に替える（B の床から抜けた割合の閾値、例 0.05）")
    p.add_argument("--edge", type=int, default=512, help="両端で見ない ch（帯域の外で床が小さく、量子化が効く）")
    o = p.parse_args()
    A, ba = mean_spec(o.a)
    B, bb = mean_spec(o.b)
    ng = 0
    print(f"CRC の不一致 {ba}・{bb}")
    for c in range(G.NC):
        if c not in A or c not in B:
            continue
        sa, srca, na, ka = A[c]
        sb, srcb, nb, kb = B[c]
        if srca != srcb:
            print(f"    {G.KEYS[c]}: src が違う（{srca}・{srcb}）。比べない")
            continue
        if o.posctl == "mirror":
            sa = sa.reshape(-1, 8)[:, ::-1].ravel()
        elif o.posctl == "shift":
            sa = np.roll(sa, 1)
        sl = slice(o.edge, G.NCH - o.edge)
        r = sa[sl] / sb[sl]
        r = r / np.median(r)
        # 遅い形の違い（日による帯域の傾き・ADC の利得）は ch の並びと関係ないので、128 ch ごとの中央値で割って除く
        nb_ = len(r) // 128
        med = np.repeat(np.median(r[: nb_ * 128].reshape(nb_, 128), axis=1), 128)
        r = r[: nb_ * 128] / med
        sig = 1.4826 * np.median(np.abs(r - 1))
        exp = np.sqrt(1.0 / (na * ka) + 1.0 / (nb * kb))        # 雑音の見込み（χ² の自由度 2·N で相対 σ = 1/√N）
        lo, hi = np.percentile(r, [1, 99])
        # 帯域の形がどれだけ消えたか: A の形の散らばりに対する比
        shp = 1.4826 * np.median(np.abs(sa[sl] / np.median(sa[sl]) - 1))
        ok = sig <= 3 * exp and lo >= 1 - o.tol and hi <= 1 + o.tol
        if o.spur:
            # 細い山（B の床から --spur 以上抜けた ch）が A の同じ ch にもあるか。山の高さの比（A の抜け / B の抜け）の中央値と、半分以上残った山の割合
            def excess(x):
                # 両隣 ±4 ch（自分を除く 8 ch）の中央値からの抜け。8 ch より細い山だけが残る
                w = np.lib.stride_tricks.sliding_window_view(np.pad(x, 4, mode="edge"), 9)
                m = np.median(np.delete(w, 4, axis=1), axis=1)
                return x / m - 1
            ea, eb = excess(sa[sl]), excess(sb[sl])
            idx = np.nonzero(eb > o.spur)[0]
            if len(idx):
                q = ea[idx] / eb[idx]
                keep = np.mean(q > 0.5)
                ok = keep >= 0.9
                print(f"    {G.KEYS[c]}: B の山 {len(idx)} 個（床 +{o.spur:.0%} 以上、ch {', '.join(str(o.edge + int(i)) for i in idx[:8])}{' …' if len(idx) > 8 else ''}）・"
                      f"A に半分以上残った割合 {keep:.2f}・高さの比の中央値 {np.median(q):.2f}")
            else:
                ok = False
                print(f"    {G.KEYS[c]}: B に山が無い（比べられない）")
        ng += not ok
        print(f"{'OK ' if ok else 'NG '} {G.KEYS[c]}（src {srca}、{na} × {nb} ダンプ）: 比の σ {sig:.4f}（雑音の見込み {exp:.4f}）・1 % {lo:.4f}・99 % {hi:.4f}・"
              f"最小 {r.min():.4f}（ch {o.edge + int(np.argmin(r))}）・最大 {r.max():.4f}（ch {o.edge + int(np.argmax(r))}）・形の σ {shp:.4f}")
    print("結果: " + ("全部通過" if ng == 0 else f"不合格（{ng}）"))
    sys.exit(1 if ng else 0)


if __name__ == "__main__":
    main()
