#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj008 — `timebase.py` を実機で端から端まで確かめる。

**配線を 4ch 科学用に戻す前に走らせること。**
1PPS が ADC に分配されている今しか、この閉ループは作れない。

## 何を確かめるか

**「PPS のエッジが乗っているサンプル」の時刻を計算すると、整数秒に戻るはずである。**

鎖はこうなっている:

    PPS の到来 → PL のスタンプ → 錨（UTC 整数秒）→ ビート → サンプル番号
                                                              → 較正定数を引く

**どこか 1 つでも壊れていれば、整数秒に戻らない。** しかも壊れ方で場所が分かる:

| ずれ | 疑うところ |
|---|---|
| 〜5 ns | 期待どおり（エポック残差 3.3 ns ＋ 測定 0.2 ns ＋ 丸め 0.5 ns）|
| **〜426 ns** | **較正定数の符号**（2 × 213.16）。proj007 と proj008 で 2 回踏んだ場所 |
| 〜213 ns | 較正定数を適用していない |
| **1 秒ちょうど** | **錨の整数秒**。秒境界の近くで読んだ |
| 数 µs 以上 | ビート ↔ サンプルの換算か、原点の取り違え |

**この試験は符号に敏感である。** それが作った理由である。

## 使い方

    sudo -E $(which python3) timebase_check.py --ch 0 --trials 5 --clkin 0 --atten-db 19
"""

import argparse
import math
import time

import numpy as np

import adc_capture as ac
import pps as pps_mod
import pps_delay as pd
import timebase as tbm

log = ac.log
SAMP_NS = 1e9 / ac.FS_HZ

PASS_NS = 100.0          # これ以内なら通す（符号反転 426 ns は必ず外れる）
SUSPECT_NS = 1000.0


def classify(off_ns):
    a = abs(off_ns)
    if a < 20.0:
        return "OK", "期待どおり（エポック残差の範囲）"
    if a < PASS_NS:
        return "OK", "通るが大きい。較正定数を見直す価値がある"
    if a < SUSPECT_NS:
        cal = tbm.CAL[0x00080001]["l_adc_minus_d_pps_ns"]
        if abs(a - 2 * cal) < 50:
            return "NG", f"**符号を疑う**（2 × {cal} = {2 * cal:.0f} ns に近い）"
        if abs(a - cal) < 50:
            return "NG", f"**較正定数を適用していない**（{cal} ns に近い）"
        return "NG", "換算のどこかが壊れている"
    if a > 0.5e9:
        return "NG", "**錨の整数秒がずれている**（1 秒級）"
    return "NG", "ビート ↔ サンプルの換算か、原点の取り違え"


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=ac.BITFILE)
    p.add_argument("--ch", type=int, default=0, choices=tuple(range(ac.NCH)))
    p.add_argument("--trials", type=int, default=5)
    p.add_argument("--nsamples", type=int, default=ac.MAX_BEATS * ac.SPW)
    p.add_argument("--k", type=int, default=2)
    p.add_argument("--frac", type=float, default=0.5)
    p.add_argument("--win-us", type=float, default=5.0)
    p.add_argument("--atten-db", type=float, default=0.0)
    p.add_argument("--pol", type=int, default=0, choices=(0, 1))
    p.add_argument("--zone", type=int, default=1, choices=(1, 2))
    p.add_argument("--fs", type=float, default=ac.FS_HZ / 1e6)
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--src-tile", type=int, default=2,
                   help="判定 D で止めるタイル（MMCM の源）")
    p.add_argument("--skip-epoch-test", action="store_true",
                   help="判定 D（原点を壊して拒否させる）を飛ばす")
    args = p.parse_args()

    pd.check_chan_map()

    from pynq import Overlay
    import xrfdc                                   # noqa: F401

    ac.setup_clocks(args.clkin, args.ref)
    ol = Overlay(args.bitfile)
    log(f"Overlay: {args.bitfile}")
    ac.start_tiles(ol.rfdc, args.fs * 1e6, args.zone)
    t_tiles = time.time()

    pps = pps_mod.PPS(ol)
    pps.check_magic()
    pps.set_pol(args.pol)
    pps_mod.wait_ready(pps, t_tiles, label="タイル起動")

    results = {}

    # ---------------------------------------------------------- 判定 A
    log("")
    log("==== 判定 A: 較正定数を持っているか ====")
    tb = tbm.Timebase(pps)
    acc = tb.accuracy_ns()
    log(f"  MAGIC 0x{tb.magic:08x} の定数を持っている")
    log(f"  適用する値      : {acc['applied_ns']} ns ± {acc['applied_unc_ns']}")
    log(f"  補正し残す量    : エポック {acc['epoch_residual_ns']} ns "
        f"/ タイル間 {acc['tile_residual_ns']} ns")
    log(f"  合計の時刻確度  : {acc['total_ns']:.1f} ns")
    log(f"  出どころ        : {acc['source']}")
    results["A"] = True

    # ---------------------------------------------------------- 判定 B
    log("")
    log("==== 判定 B: 錨を打てるか ====")
    a = tb.anchor()
    log(f"  UTC 整数秒 {a['utc_sec']} ＝ PPS #{a['count']}（ビート {a['stamp']}）"
        f" / epoch {a['epoch']}")
    log(f"  壁時計       : {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(a['utc_sec']))} UTC")
    results["B"] = True

    # ---------------------------------------------------------- 判定 C
    log("")
    log("==== 判定 C: **閉ループ** —— PPS のエッジが整数秒に戻るか ====")
    log("  **この試験が本題である。** 符号・定数・錨・換算のどれが壊れていても落ちる")
    log("")
    n_beats = args.nsamples // ac.SPW
    offset = -(n_beats // 2)
    half = int(round(args.win_us * 1e-6 * ac.FS_HZ))
    offs = []
    for t in range(args.trials):
        start_at, d = pps.next_start(k=args.k, offset=offset)
        pps_beat = d["stamp"] + args.k * pps_mod.BEATS_PER_SEC
        x = ac.capture(ol, args.nsamples, blocks=None, start_at=start_at, pps=pps)
        snap = pps.snapshot()
        if (snap["t_start"] & 0xFFFFFFFF) != start_at:
            log(f"  [{t}] t_start が start_at と違う。飛ばす")
            continue
        pred = (pps_beat - snap["t_start"]) * ac.SPW
        meas, pk, amp = pd.find_edge(x[args.ch], args.frac, center=pred, half=half)
        i0 = int(math.floor(meas))
        fr = meas - i0
        try:
            t_ns = tb.time_of_ns(snap["t_start"], i0, snap=snap)
        except tbm.TimebaseError as e:
            log(f"  [{t}] **時刻を返さなかった**: {e}")
            continue
        t_exact = t_ns + fr * SAMP_NS
        off = t_exact - round(t_exact / 1e9) * 1e9
        offs.append(off)
        verdict, why = classify(off)
        log(f"  [{t}] エッジ {meas:9.2f} サンプル → UTC "
            f"{t_exact / 1e9:.9f} s   整数秒からのずれ **{off:+9.2f} ns**  [{verdict}] {why}")

    log("")
    if not offs:
        log("  **一度も成立しなかった。** 上のメッセージを見る")
        results["C"] = False
    else:
        arr = np.array(offs)
        m, sd = float(arr.mean()), float(arr.std(ddof=1)) if arr.size >= 2 else 0.0
        log(f"  平均 {m:+.2f} ns / 標準偏差 {sd:.2f} ns（{arr.size} 回）")
        verdict, why = classify(m)
        results["C"] = (verdict == "OK")
        log(f"  → **{verdict}** {why}")
        if verdict == "OK":
            log("    **鎖が端から端まで通っている。**"
                " PPS → PL のスタンプ → 錨 → ビート → サンプル → 較正")

    # ---------------------------------------------------------- 判定 D
    log("")
    log("==== 判定 D: **原点を壊したら拒否するか** ====")
    if args.skip_epoch_test:
        log("  飛ばした（--skip-epoch-test）")
        results["D"] = None
    else:
        log(f"  adc_tiles[{args.src_tile}] を止めて原点を作り直す。"
            "**そのあと時刻を聞いて、例外が出れば合格**")
        tile = ol.rfdc.adc_tiles[args.src_tile]
        tile.ShutDown()
        time.sleep(0.5)
        tile.StartUp()
        t0 = time.time()
        while not (pps.flags() & pps_mod.FLAG_LOCKED):
            if time.time() - t0 > 10.0:
                break
            time.sleep(0.05)
        ac.start_tiles(ol.rfdc, args.fs * 1e6, args.zone)
        time.sleep(3.0)
        try:
            t_ns = tb.time_of_ns(snap["t_start"], 0)
        except tbm.TimebaseError as e:
            log(f"  → **合格。拒否した。**")
            log(f"    {e}")
            results["D"] = True
        else:
            log(f"  → **不合格。答えてしまった**（{t_ns} ns）。")
            log("    **原点が変わったあとに時刻を返すのは、いちばん危ない壊れ方である** ——")
            log("    値は尤もらしいのに、秒単位でずれている")
            results["D"] = False

    # ---------------------------------------------------------- まとめ
    log("")
    log("=" * 56)
    names = {"A": "較正定数を持っている", "B": "錨を打てる",
             "C": "**閉ループ（整数秒に戻る）**", "D": "**原点を壊したら拒否する**"}
    ng = 0
    for k in ("A", "B", "C", "D"):
        v = results.get(k)
        mark = "—" if v is None else ("○" if v else "**×**")
        if v is False:
            ng += 1
        log(f"  判定 {k}  {mark}  {names[k]}")
    log("=" * 56)
    log("")
    if ng:
        log(f"**{ng} 件が通っていない。** 上を見る")
        raise SystemExit(1)
    log("**すべて通った。** `timebase.py` は実機で働いている")
    log("")
    log("**次**: 配線を 4ch 科学用に戻してよい。戻すと閉ループは作れなくなるので、")
    log("  ビットストリームを変えたときは 1PPS を一時的に ADC へ分配して")
    log("  `pps_delay.py --ch all` で定数を測り直し、`timebase.CAL` を更新する")


if __name__ == "__main__":
    main()
