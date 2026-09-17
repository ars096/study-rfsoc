#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj006 — SMA のラベル（ADC_A/B/C/D）と (tile, slice) の対応を **実測で** 埋める。

RefMan は「ADC_A / ADC_B が Tile 226」としか書いておらず、スライス番号の割り当ては
書かれていない。しかも proj003 で **「SMA のラベルとスライス番号の並びが逆」** を
踏んでいる（ADC_B が slice 0 だった）。**推定で表を書かないこと。**

やることは単純で、SMA を 1 本ずつ挿し替えて、どの ch にトーンが乗るかを見るだけ。
1 回の取得で 4ch 全部が見えるので、**挿し替えるたびに 4ch の表が 1 行できる**。

使い方（ボード上で sudo が要る）:

    sudo python3 slice_map.py --tone 100.0125 --clkin 0

    # ケーブルを挿し替えずに、今どこに入っているかだけ見る
    sudo python3 slice_map.py --tone 100.0125 --clkin 0 --once

**判定は「一番強い ch」ではなく「2 番目との差」で行う。**
差が小さいときは、分配器が複数 ch に配っているか、ケーブルが挿さっていない。
そのまま表にすると、proj003 と同じ間違いを別の形で繰り返すことになる。

出力の最後に VERSIONS.md へ貼れる表が出る。
"""

import argparse
import sys

import numpy as np

import adc_capture as ac

log = ac.log

# クロストークでもこれだけ離れていれば、取り違えようがない。
# 実測値が近ければ警告を出して表には入れない。
MARGIN_DB = 20.0


def tone_dbfs(x, fs_hz, tone_hz):
    """与えたトーンの周波数における振幅を dBFS で返す。

    ピーク探索ではなく **周波数を決め打ちで測る**。信号が乗っていない ch では
    ピーク探索が雑音の山を拾ってしまい、比較の意味がなくなる。
    """
    n = len(x)
    w = np.hanning(n)
    cg = np.sum(w) / n
    # 折返しを考慮した期待周波数
    f = tone_hz % fs_hz
    if f > fs_hz / 2:
        f = fs_hz - f
    k = f / (fs_hz / n)
    lo, hi = int(max(1, np.floor(k) - 2)), int(min(n // 2, np.ceil(k) + 3))
    spec = np.fft.rfft(x.astype(np.float64) * w) / (n / 2 * cg)
    mag = np.abs(spec[lo:hi])
    return 20 * np.log10(max(mag.max(), 1e-12) / 32768.0)


def measure(ol, blocks, args):
    xs = ac.capture(ol, args.nsamples, blocks)
    rows = []
    for i, (ti, si) in enumerate(ac.CHANS):
        rows.append({
            "ch": i, "tile": 224 + ti, "slice": si,
            "dbfs": tone_dbfs(xs[i], args.fs * 1e6, args.tone * 1e6),
            "max": int(np.max(np.abs(xs[i]))),
            "std": float(np.std(xs[i])),
        })
    order = sorted(rows, key=lambda r: -r["dbfs"])
    best, second = order[0], order[1]
    margin = best["dbfs"] - second["dbfs"]

    log("")
    log("  ch  tile/slice   トーン [dBFS]   max|x|      std")
    for r in rows:
        mark = "  ← 最大" if r is best else ""
        log(f"  {r['ch']}   {r['tile']}/{r['slice']}      "
            f"{r['dbfs']:>10.2f}  {r['max']:>7}  {r['std']:>8.1f}{mark}")
    log(f"  2 番目との差 = {margin:.1f} dB")
    return best, margin


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=ac.BITFILE)
    p.add_argument("--tone", type=float, required=True, help="入れる CW の周波数 [MHz]")
    p.add_argument("--fs", type=float, default=ac.FS_HZ / 1e6)
    p.add_argument("--nsamples", type=int, default=ac.N_DEFAULT)
    p.add_argument("--zone", type=int, default=1, choices=(1, 2))
    p.add_argument("--clkin", default="0", choices=("stock", "0", "1", "2"),
                   help="LMK04828 の PLL1 基準入力。**外部 10 MHz（0）を既定にしてある**")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--sma", default="ADC_A,ADC_B,ADC_C,ADC_D",
                   help="挿し替える順番。カンマ区切り")
    p.add_argument("--once", action="store_true",
                   help="挿し替えず、今の状態を 1 回だけ見る")
    args = p.parse_args()

    from pynq import Overlay
    import xrfdc                                   # noqa: F401  Overlay より前に import

    ac.setup_clocks(args.clkin, args.ref)
    ol = Overlay(args.bitfile)
    log(f"Overlay: {args.bitfile}")
    blocks = ac.start_tiles(ol.rfdc, args.fs * 1e6, args.zone)

    if args.once:
        measure(ol, blocks, args)
        return

    log("")
    log("=" * 72)
    log("SMA を 1 本ずつ挿し替える。**ほかの SMA には何も挿さないこと。**")
    log("分配器を付けたままだと複数 ch に乗り、対応が決まらない。")
    log("=" * 72)

    table = {}
    for sma in [s.strip() for s in args.sma.split(",") if s.strip()]:
        log("")
        log("-" * 72)
        try:
            input(f"**{sma}** にだけ {args.tone} MHz を入れて Enter（skip で飛ばす）: ")
        except EOFError:
            log("入力が読めない。--once で 1 回ずつ走らせること")
            sys.exit(1)
        best, margin = measure(ol, blocks, args)
        if margin < MARGIN_DB:
            log(f"  **判定しない。**2 番目との差が {margin:.1f} dB しかない "
                f"（{MARGIN_DB:.0f} dB 未満）。")
            log("  ケーブルが挿さっていないか、分配器が複数 ch に配っている。")
            log("  挿し直して同じ SMA をもう一度測ること")
            continue
        table[sma] = best
        log(f"  → **{sma} = Tile {best['tile']} / slice {best['slice']} "
            f"(ch{best['ch']})**")

    log("")
    log("=" * 72)
    log("=== 確定した対応 ===")
    log("")
    log("| SMA | tile | slice | ch（512bit 語の並び）|")
    log("|---|---|---|---|")
    for sma, b in table.items():
        log(f"| {sma} | {b['tile']} | {b['slice']} | {b['ch']} |")
    log("")
    chs = [b["ch"] for b in table.values()]
    if len(set(chs)) != len(chs):
        log("**同じ ch が 2 回出ている。どこかで挿し替えを飛ばしている。**")
    if len(table) < 4:
        log(f"**{4 - len(table)} 本ぶん未確定。**VERSIONS.md に書くのは全部埋まってから")
    else:
        log("VERSIONS.md の「ADC_A ... 推定」「ADC_C / ADC_D ... 未確認」を")
        log("この表で置き換える。**日付と proj 番号を添えること。**")


if __name__ == "__main__":
    main()
