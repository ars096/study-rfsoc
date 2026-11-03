#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj032 P-12 — tb_spwdelay の記録から窓の遅れ D(NS) を出す（numpy）

  python3 check_spwdelay.py DIR [--gap 3072]

インパルス i（クロック t_i、標本の位置 ln_i）ごとに、窓 w の y（wsb の入口）の |y|² の重心のクロック c_iw を [t_i, 次のインパルス) で出し、
D_iw = c_iw − t_i − ln_i / 16（ビート。ビートの頭 = 標本 0 から測る、Fine の D と同じ基準）。窓ごとに D の平均・最小・最大を出す。
gap の終わり 1/4 に残るエネルギーの割合も出す（応答が gap に収まっているか。1e-6 を越えれば不合格）
"""
import argparse
import os
import sys

import numpy as np

NS = {0: 2, 1: 5, 2: 1, 3: 3, 4: 1, 5: 2, 6: 4, 7: 1}     # tb_spwdelay の窓


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--gap", type=int, default=3072)
    a = ap.parse_args()
    imp = np.loadtxt(os.path.join(a.dir, "dly_imp.log"), dtype=np.int64, ndmin=2)
    y = np.loadtxt(os.path.join(a.dir, "dly_y.log"), dtype=np.int64, ndmin=2)
    t, w, p = y[:, 0], y[:, 1], y[:, 2].astype(float) ** 2 + y[:, 3].astype(float) ** 2
    bad = []
    res = {}
    for wi in sorted(NS):
        ds, tails = [], []
        for n, (ti, ln) in enumerate(imp):
            te = imp[n + 1][0] if n + 1 < len(imp) else ti + a.gap     # 次のインパルスまで（位相が戻ると間隔は gap − NPH ＋ 1 まで縮む）
            m = (w == wi) & (t >= ti) & (t < te)
            e = p[m].sum()
            if e == 0:
                bad.append(f"窓 {wi} インパルス {ti}: 出力が 0"); continue
            ds.append((p[m] * t[m]).sum() / e - ti - ln / 16.0)
            tails.append(p[m & (t >= ti + 3 * (te - ti) // 4)].sum() / e)
        ds = np.array(ds)
        res[wi] = ds
        tail = max(tails) if tails else 1
        print(f"窓 {wi}（NS {NS[wi]}）: D = {ds.mean():9.2f} ビート（{len(ds)} 個、最小 {ds.min():.2f}・最大 {ds.max():.2f}・幅 {ds.max() - ds.min():.2f}）・終わり 1/4 のエネルギー {tail:.1e}")
        if tail > 1e-6:
            bad.append(f"窓 {wi}: 応答が gap に収まらない（{tail:.1e}）")
    print("NS ごと: " + "・".join(f"NS {n}: " + ", ".join(f"{res[wi].mean():.2f}" for wi in sorted(NS) if NS[wi] == n) for n in sorted(set(NS.values()))))
    print("結果: " + ("全部通過" if not bad else "不合格: " + "・".join(bad)))
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
