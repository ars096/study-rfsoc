#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj005 — 内部基準と外部 10 MHz 基準を切り替えて ppm を比べる。

使い方（ボード上で sudo が要る）:

    sudo python3 extref_test.py --tone 100.0125            # 既定の 3 条件
    sudo python3 extref_test.py --tone 100.0125 --order stock,0,1,stock
    sudo python3 extref_test.py --tone 100.0125 --save-prefix run1

**これが proj005 の判定そのもの。** 出てくる表の 1 列（ppm）だけを見る。


なぜ 1 つのプロセスで回すのか
=============================

条件を変えるたびに人間がコマンドを打ち直すと、**打ち間違いと順序の記憶違いが入る**。
ppm は条件間の差でしか意味を持たないので、取り違えるとそのまま誤った結論になる。
同じプロセスで順に回し、同じ書式で並べて出す。

各条件でやることは毎回同じ。

    クロックを書く → **ビットストリームを読み直す** → タイルを確かめる → 取得 → 解析

**ビットストリームを毎回読み直すのが要点。** RFDC のタイルはロード時に起動して
LMX の 491.52 MHz を掴む（proj003 で確認）。クロック源を変えた後もタイルをそのままに
すると、古い基準で起動したタイルの上で測ることになり、**何を測っているのか言えなくなる**。


判定の読み方
============

| 条件 | 期待 |
|---|---|
| `stock`（基板の Si5395） | proj003 と同じ **+14.9 ppm 付近** |
| 外部基準が効いた CLKin | **SG とボードが同じ 10 MHz を見る**ので 0 付近（±0.1 ppm 級） |
| 外部基準が来ていない CLKin | PLL1 がロックしない。ppm は不定、または取得が壊れる |

**SG（APSYN420）も同じ 10 MHz に同期させること。** ボードだけを外部基準にすると、
ppm は 0 にならず「SG 自身の確度」に置き換わるだけで、**減るとは限らない**。
proj005 の判定条件はここに依存する。

**0 に潰れたことは「両者が同じ基準を見ている」ことしか言わない。** 基準そのものの
確度は、この測定では分からない（共通のずれは打ち消える）。観測所の基準信号を使う
以上それで十分だが、**言えることと言えないことを混ぜない**。
"""

import argparse
import sys
import time

import adc_capture as ac
import extref


def log(*a):
    print(*a, flush=True)


def run_one(clkin, args):
    """1 条件ぶん。戻り値は analyse() の dict（失敗したら None）。"""
    log("")
    log("=" * 72)
    log(f"=== 条件: clkin = {clkin} ===")
    log("=" * 72)

    ac.setup_clocks(clkin, args.ref)

    from pynq import Overlay
    ol = Overlay(args.bitfile)
    log(f"Overlay を読み直した: {args.bitfile}")

    fs_hz = args.fs * 1e6
    try:
        _, block = ac.start_tile(ol.rfdc, fs_hz, args.zone)
    except SystemExit:
        # start_tile は PLL がロックしていなければ exit する。
        # **ここで止めない。** 「ロックしなかった」こと自体が結果である。
        log(f"→ clkin = {clkin} ではタイル PLL がロックしなかった。")
        log("  外部基準が来ていないか、その CLKin に何も繋がっていない。")
        return None

    x = ac.capture(ol, args.nsamples, block)
    if args.save_prefix:
        import numpy as np
        path = f"{args.save_prefix}_clkin{clkin}.npy"
        np.save(path, x)
        log(f"saved: {path}")

    return ac.analyse(x, fs_hz, args.tone * 1e6 if args.tone else None, args.window)


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=ac.BITFILE)
    p.add_argument("--tone", type=float, required=True,
                   help="入力している CW の周波数 [MHz]。**SG も同じ 10 MHz に同期させること**")
    p.add_argument("--order", default="stock,0,1",
                   help="試す順番。カンマ区切り（stock / 0 / 1 / 2）。同じ条件を 2 回"
                        "並べれば再現性も見られる")
    p.add_argument("--zone", type=int, default=1, choices=(1, 2))
    p.add_argument("--fs", type=float, default=ac.FS_HZ / 1e6)
    p.add_argument("--nsamples", type=int, default=ac.N_DEFAULT)
    p.add_argument("--window", default="hann", choices=("hann", "none"))
    p.add_argument("--ref", type=float, default=10.0, help="外部基準の周波数 [MHz]")
    p.add_argument("--save-prefix", default=None, help="各条件の生サンプルを .npy で残す")
    p.add_argument("--settle", type=float, default=2.0,
                   help="条件を変えてから取得までの追加の待ち [s]")
    args = p.parse_args()

    order = [s.strip() for s in args.order.split(",") if s.strip()]
    for s in order:
        if s not in ("stock", "0", "1", "2"):
            log(f"ERROR: 条件 '{s}' は stock / 0 / 1 / 2 のどれかにすること")
            sys.exit(2)

    import xrfdc                 # **Overlay() より前に import する**（proj003）
    _ = xrfdc

    rows = []
    for s in order:
        r = run_one(s, args)
        time.sleep(args.settle)
        rows.append((s, r))

    log("")
    log("=" * 72)
    log(f"=== まとめ  入力 {args.tone} MHz / fs {args.fs} MSPS / N = {args.nsamples} ===")
    log("=" * 72)
    log(f"{'clkin':>8}  {'推定周波数 [MHz]':>18}  {'ずれ [Hz]':>12}  {'ppm':>10}  {'dBFS':>8}")
    for s, r in rows:
        if r is None or r.get("ppm") is None:
            log(f"{s:>8}  {'—（ロックせず / 解析できず）':>18}")
            continue
        log(f"{s:>8}  {r['f_est_hz'] / 1e6:>18.6f}  {r['d_hz']:>12.1f}  "
            f"{r['ppm']:>+10.3f}  {r['peak_dbfs']:>8.2f}")

    ok = [(s, r["ppm"]) for s, r in rows if r and r.get("ppm") is not None]
    log("")
    if not ok:
        log("**どの条件でも ppm が出ていない。** まず `--clkin stock` 単独で "
            "adc_capture.py が proj003 と同じ結果を出すか確かめること。")
        return

    base = dict(ok).get("stock")
    best = min(ok, key=lambda t: abs(t[1]))
    log(f"内部基準（stock）: {base:+.3f} ppm" if base is not None else
        "内部基準（stock）は測っていない")
    log(f"0 に最も近い条件 : clkin = {best[0]}  ({best[1]:+.3f} ppm)")
    if base is not None and best[0] != "stock" and abs(best[1]) < abs(base) / 10:
        log("")
        log(f"→ **clkin = {best[0]} が CLK_IN の SMA。外部 10 MHz が効いている。**")
        log("   ずれが 1 桁以上小さくなった。SG とボードが同じ基準を見ている。")
    elif base is not None:
        log("")
        log("→ **どの条件でも ppm が桁で減っていない。** 疑う順に:")
        log("   1. SG を同じ 10 MHz に同期させたか（していなければ 0 にはならない）")
        log("   2. CLK_IN にケーブルが挿さっているか、レベルは足りているか")
        log("   3. ボードの PLL1 ロック LED は点いているか")
        log("   4. CLKin の取り違え（--order に 2 を足してみる）")
        log("   5. 正弦波で PLL1 がロックしない場合がある（TI は方形波と MOS 入力を推奨）。"
            "レベルを上げるか方形波にしてみる")


if __name__ == "__main__":
    main()
