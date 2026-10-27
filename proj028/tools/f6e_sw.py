#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-6e — アッテネータの切り替え（f5_cont.py --switch）の結果を解く（この PC で）

  python3 tools/f6e_sw.py runs/f6e_t1 [--ref runs/f5g_on2 runs/f5g_off]

- 状態ごとのスペクトル <stem>_s<k>_spec.npy を、その状態の利得 gains[k] の 2 乗で割る（入力に換算）
- 荒い ch ごとの ON / OFF（状態 0 / 状態 1、スプリアスの bin を除く）。--ref があれば F-5g（雑音源の入り切り）と比べる
- 区間ごと（ON・OFF の繰り返し）の入力換算の電力（ch 2〜30）と、隣り合う ON・OFF の組の比 Y の時間の列
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from f5_onoff import load, spur_mask, NCH, NKEEP  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stem")
    ap.add_argument("--ref", nargs=2)
    a = ap.parse_args()
    meta = json.load(open(a.stem + "_meta.json"))
    G = [np.array(g, float) for g in meta["gains"]]
    sp = [np.load(f"{a.stem}_s{k}_spec.npy").astype(np.float64) / np.repeat(G[k] ** 2, NKEEP) for k in range(len(G))]
    runs = meta["runs"]
    print(f"状態 {meta['switch']} dB・dwell {meta['dwell']}・切り替え {len(meta['switches'])} 回・区間 {len(runs)}・"
          f"捨てた {len(meta['dropped'])}（混ざり {sum(1 for d in meta['dropped'] if d[1] == '混ざり')}）・欠け {len(meta['lost'])}")
    for k, g in enumerate(G):
        print(f"  状態 {k} の利得: g {g.min():.0f}〜{g.max():.0f}")
    W = [s[1] - s[0] for s in meta["switches"]]
    print(f"  切り替えの窓（W1 − W0）: {sorted(set(W))}・切り替えで捨てたチャンク / 回 ≒ {sum(1 for d in meta['dropped'] if d[1] == '切り替え') / max(len(W), 1):.2f}")

    on, off = sp[0], sp[1]
    ok = spur_mask(on) & spur_mask(off)
    y = np.where(ok, on / off, np.nan).reshape(NCH, NKEEP)
    yc = 10 * np.log10(np.nanmean(y, axis=1))
    print("\n1. ON / OFF（荒い ch ごと、dB）: " + " ".join(f"{k}:{v:+.2f}" for k, v in enumerate(yc)))
    if a.ref:
        ron, _ = load(a.ref[0])
        roff, _ = load(a.ref[1])
        ron, roff = ron[1:].mean(0), roff[1:].mean(0)
        ok2 = ok & spur_mask(ron) & spur_mask(roff)
        yr = 10 * np.log10(np.nanmean(np.where(ok2, ron / roff, np.nan).reshape(NCH, NKEEP), axis=1))
        d = yc - yr
        print(f"   F-5g（{os.path.basename(a.ref[0])} / {os.path.basename(a.ref[1])}）との差: " + " ".join(f"{k}:{v:+.2f}" for k, v in enumerate(d)))
        print(f"   ch 2〜30 の差: 平均 {d[2:31].mean():+.3f}・σ {d[2:31].std():.3f}・最大 |差| {np.abs(d[2:31]).max():.3f} dB")

    print("\n2. 区間ごとの入力換算の電力（ch 2〜30 の平均、÷ g² の和）と Y")
    t0 = None
    rows = []
    for r in runs:
        ts = np.array(r["ts"])                         # チャンク × ch の生の電力
        g2 = G[r["state"]] ** 2
        pin = (ts[:, 2:31] / g2[2:31]).mean(1)
        rows.append((r["first"], r["state"], r["n"], pin.mean(), pin.std() / pin.mean() if len(pin) > 1 else np.nan))
    ys = []
    for i in range(len(rows) - 1):
        a_, b_ = rows[i], rows[i + 1]
        if a_[1] == 0 and b_[1] == 1:
            ys.append((a_[0], 10 * np.log10(a_[3] / b_[3]), a_[3], b_[3]))
    for f_, st, n, m, cv in rows[:6]:
        print(f"   チャンク {f_:5d}〜・状態 {st}・{n} チャンク・電力 {m:.5g}・チャンクの σ {100 * cv:.3f} %")
    if len(rows) > 6:
        print(f"   …（全 {len(rows)} 区間）")
    if ys:
        Y = np.array([v[1] for v in ys])
        pon = np.array([v[2] for v in ys])
        poff = np.array([v[3] for v in ys])
        print(f"   Y（ON 区間 / 次の OFF 区間、dB）: {len(Y)} 組・平均 {Y.mean():+.4f}・σ {Y.std():.4f} dB（{100 * (10 ** (Y.std() / 10) - 1):.3f} %）")
        print("   組ごと: " + " ".join(f"{v:+.3f}" for v in Y[:40]) + (" …" if len(Y) > 40 else ""))
        k = len(Y) // 2
        if k >= 2:
            print(f"   前半 / 後半: Y {Y[:k].mean():+.4f} / {Y[k:].mean():+.4f} dB・ON {100 * (pon[k:].mean() / pon[:k].mean() - 1):+.3f} %・"
                  f"OFF {100 * (poff[k:].mean() / poff[:k].mean() - 1):+.3f} %")
    return 0


if __name__ == "__main__":
    sys.exit(main())
