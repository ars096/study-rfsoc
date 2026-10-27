#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-5h — Overlay を読み直しながら、荒い段の電力の数え（POW）で入力の全電力を追う（ボードの上で。f5.py と同じ場所に置く）

  sudo -E $(which python3) f5_pow.py --gains-from f5g_on2_meta.json --loads 4 --secs 120 --out f5h_pow

- 利得は --gains-from の meta の gain に固定する（読み直しの間で同じ利得 → POW の比がそのまま入力の電力の比）
- 読み直しごとに: クロック → Overlay → タイル・ID・ギアボックスの照合 → NACC と利得を書く → --secs 秒のあいだ POW を読み続ける
- 陽性対照: 1 回目の読み込みの中ほど --bump-secs 秒だけ利得を (1 + --bump) 倍にする（電力は ≒ (1 + bump)² 倍に見えるはず）
- 保存: <out>.json（読み込みごとに、時刻・ch ごとの POW・CLIP の列）
"""
import argparse
import json
import time

import numpy as np

import f5
from f5 import Regs, log, NCH


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bit", default="proj028.bit")
    ap.add_argument("--gains-from", required=True)
    ap.add_argument("--loads", type=int, default=4)
    ap.add_argument("--secs", type=float, default=120.0)
    ap.add_argument("--nacc", type=int, default=1 << 22, help="POW の区切り（ブロック、2^22 ≒ 57 ms）")
    ap.add_argument("--bump", type=float, default=0.002)
    ap.add_argument("--bump-secs", type=float, default=10.0)
    ap.add_argument("--out", default="f5h_pow")
    a = ap.parse_args()
    g = np.array(json.load(open(a.gains_from))["gain"], dtype=np.int64)
    gb = np.round(g * (1 + a.bump)).astype(np.int64)

    from pynq import Overlay
    import xrfdc                                  # Overlay() より前
    res = dict(bit=a.bit, gains=g.tolist(), nacc=a.nacc, bump=a.bump, loads=[])
    t_start = time.time()
    for L in range(a.loads):
        f5.setup_clocks("stock", 10.0)
        ol = Overlay(a.bit)
        t_load = time.time()
        if not isinstance(ol.rfdc, xrfdc.RFdc):
            log("ERROR: RFDC に xrfdc のドライバが当たっていない")
            return 1
        f5.check_tile(ol.rfdc, 1)
        cs, ft = Regs(ol, "coarse_stage_0"), Regs(ol, "fine_top_0")
        if cs.rd(0) != f5.ID_CS:
            log(f"ERROR: coarse_stage の ID 0x{cs.rd(0):08x}")
            return 1
        txt, gbs, adcs = f5.gb_text(ft)
        log(f"読み込み {L}: " + txt)
        cs.wr(0x004, a.nacc)
        for k in range(NCH):
            cs.wr(0x100 + 4 * k, int(g[k]))
        rows = []
        bumped = False
        t0 = time.time()
        while time.time() - t0 < a.secs:
            te = time.time() - t0
            want = L == 0 and a.secs / 2 <= te < a.secs / 2 + a.bump_secs
            if want != bumped:
                for k in range(NCH):
                    cs.wr(0x100 + 4 * k, int((gb if want else g)[k]))
                bumped = want
            p, c = f5.coarse_pow(cs, a.nacc)
            rows.append((round(time.time() - t_start, 3), int(bumped), p.tolist(), c.tolist()))
        q = np.array([r[2] for r in rows])[:, 2:31].sum(1)
        log(f"読み込み {L}: Overlay から {t_load - t_start:.1f} s・{len(rows)} 区切り・ch 2〜30 の POW の平均 {q.mean():.6g}（最初の 1/4 {q[:len(q) // 4].mean():.6g}・後の 1/4 {q[-len(q) // 4:].mean():.6g}）・飽和 {int(np.array([r[3] for r in rows]).sum())}")
        res["loads"].append(dict(t_load=round(t_load - t_start, 3), gb=gbs, adc=adcs, rows=rows))
        json.dump(res, open(a.out + ".json", "w"))
    log(f"保存: {a.out}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
