#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj007（proj006 からそのまま）— タイル間のサンプルずれと、**それが起動ごとに変わるかどうか**。

## 何を測っているのか

ADC_A / B は Tile 226、ADC_C / D は Tile 224 に載る。この 4 本は **1 個の LMX2594**
から 491.52 MHz をもらうので、サンプリングクロックは同一で位相も固定である。
それでもタイル間でサンプルの番号が揃う保証はない。

RFDC はコンバータのクロック領域と AXI4-Stream の領域の間に内部 FIFO を持つ。
この FIFO の読み出しが始まる位相はタイルの起動シーケンスで決まり、
**タイルごとに、そして起動ごとに変わりうる**。MTS が揃えているのは、
突き詰めればこの FIFO のポインタである。

分光計としては、

- ずれが **毎回同じ** なら → 定数として引けばよい。**MTS は要らない**
- ずれが **毎回違う** なら → MTS か、起動ごとの較正が要る

**どちらなのかを言い切ることが proj006 の成果物**であり、
このスクリプトはそのための唯一の道具である。

## 測り方

同じ CW を 4 分配して 4ch に入れ、**タイルの起動をやり直しながら**位相差を測る。

    sudo python3 tile_offset.py --tone 10.0125 --clkin 0 --trials 10

`--mode overlay`（既定）は **Overlay を読み直す**。proj003 で確かめたとおり、
RFDC のタイルはビットストリームをロードした時点で起動するので、
これがいちばん実運用に近い「起動のやり直し」になる。
`--mode restart` は `ShutDown()` → `StartUp()` を使う。

## 読むときの注意

**測れるのは「FIFO の位相」と「ケーブル長の差」の和である。**
ケーブル長の差は毎回同じなので、**試行ごとのばらつきだけが FIFO 由来**になる。
絶対値を較正定数として使いたいなら、ケーブル長を揃えるか実測して引くこと
（1 ns ≒ 20 cm ≒ 1.2 サンプル）。

**位相には 1 周期の曖昧性がある。** トーンの周期 fs/f [サンプル] より大きなずれは
測れない。10.0125 MHz なら 122.7 サンプル周期で ±61 サンプルまで一意。
このスクリプトは周期と、ずれが周期の端に寄っていないかを毎回出す。
**別の周波数でもう一度測って同じ値が出れば、曖昧性は潰れている。**
"""

import argparse
import sys
import time

import numpy as np

import adc_capture as ac

log = ac.log

MIN_DBFS = -60.0        # これより弱い ch は「信号が来ていない」とみなす


def cplx_at(x, fs_hz, f_hz):
    """周波数 f における複素振幅。ピーク探索ではなく決め打ちで測る。

    4ch は同じ信号源を見ているので、**全 ch で同じ周波数を使わなければ
    位相差に意味が出ない**。ch ごとにピークを探すと、雑音で 1 ビン動いた瞬間に
    位相が飛ぶ。
    """
    n = len(x)
    w = np.hanning(n)
    t = np.arange(n, dtype=np.float64)
    return np.sum(x.astype(np.float64) * w * np.exp(-2j * np.pi * f_hz * t / fs_hz))


def circ_summary(d, period):
    """**巻き戻し（wrap）に強い要約。**

    位相差は period ごとに巻き戻るので、**そのまま平均や標準偏差を取ると壊れる。**
    2026-09-17 に実際に踏んだ: -61.27 と +61.33 は物理的に同じずれ
    （差が 122.60 = ちょうど 1 周期）なのに、
    算術平均が -11.9、標準偏差が 59.5、幅が 122.6 に化けた。
    **「起動ごとに変わる」という誤った判定を出しかけた。**

    複素平面に乗せてから平均し、各試行をその平均のいちばん近くへ巻き戻す。

    戻り値: (平均 [サンプル], 巻き戻した各試行, 集中度 R)
      R は 0〜1。1 に近いほど揃っている。**R が高いのに幅が広ければ、
      それは巻き戻しを疑う合図**（この関数を通していれば起きないが）。
    """
    d = np.asarray(d, dtype=float)
    z = np.exp(2j * np.pi * d / period)
    m = z.mean()
    mean = np.angle(m) / (2 * np.pi) * period
    unwrapped = mean + ((d - mean + period / 2) % period) - period / 2
    return mean, unwrapped, float(np.abs(m))


def estimate_tone(x, fs_hz, tone_hz):
    """サブビンでトーンの周波数を決める（基準 ch で 1 回だけ）。"""
    n = len(x)
    w = np.hanning(n)
    cg = np.sum(w) / n
    rbw = fs_hz / n
    spec = np.abs(np.fft.rfft(x.astype(np.float64) * w) / (n / 2 * cg))
    f_fold = tone_hz % fs_hz
    if f_fold > fs_hz / 2:
        f_fold = fs_hz - f_fold
    k0 = int(round(f_fold / rbw))
    lo, hi = max(1, k0 - 4), min(len(spec) - 1, k0 + 5)
    k = int(np.argmax(spec[lo:hi]) + lo)
    d = 0.0
    if 0 < k < len(spec) - 1:
        a, b, c = spec[k - 1], spec[k], spec[k + 1]
        den = a + 2 * b + c
        if den > 0:
            d = 2.0 * (c - a) / den
    return (k + d) * rbw


def one_trial(ol, args, ref_ch):
    """1 回ぶん。戻り値は {ch: ずれ [サンプル]} と dBFS の一覧。"""
    fs_hz = args.fs * 1e6
    blocks = ac.start_tiles(ol.rfdc, fs_hz, args.zone)
    xs = ac.capture(ol, args.nsamples, blocks)

    f_est = estimate_tone(xs[ref_ch], fs_hz, args.tone * 1e6)
    period = fs_hz / f_est                       # 1 周期あたりのサンプル数

    z = [cplx_at(xs[i], fs_hz, f_est) for i in range(ac.NCH)]
    amp = [20 * np.log10(max(abs(v), 1e-12) / (len(xs[0]) / 2 * 0.5 * 32768.0))
           for v in z]

    off = {}
    for i in range(ac.NCH):
        dphi = np.angle(z[i] / z[ref_ch])
        d = -dphi / (2 * np.pi) * period          # 正 = ref より遅れている
        off[i] = d
    return {"f_est": f_est, "period": period, "off": off, "dbfs": amp}


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=ac.BITFILE)
    p.add_argument("--tone", type=float, required=True,
                   help="4 分配して入れている CW の周波数 [MHz]。"
                        "**周期 fs/f がずれの範囲より長いものを選ぶ**")
    p.add_argument("--fs", type=float, default=ac.FS_HZ / 1e6)
    p.add_argument("--nsamples", type=int, default=ac.N_DEFAULT)
    p.add_argument("--zone", type=int, default=1, choices=(1, 2))
    p.add_argument("--trials", type=int, default=10, help="起動をやり直す回数")
    p.add_argument("--mode", default="overlay", choices=("overlay", "restart"),
                   help="overlay = Overlay を読み直す（実運用に近い）/ "
                        "restart = ShutDown → StartUp")
    p.add_argument("--ref-ch", type=int, default=0, choices=tuple(range(ac.NCH)),
                   help="位相の基準にする ch")
    p.add_argument("--clkin", default="0", choices=("stock", "0", "1", "2"),
                   help="**外部 10 MHz（0）を既定にしてある。**"
                        "fs がずれていると位相が時間とともに回る")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--tol", type=float, default=1.0,
                   help="「一定」とみなす幅 [サンプル]。既定 1.0。"
                        "**AXIS の 1 語 = 8 サンプルなので、FIFO 由来なら幅は 8 の倍数で出る**")
    p.add_argument("--save", default=None, help="試行ごとのずれを .npy で残す")
    args = p.parse_args()

    from pynq import Overlay
    import xrfdc                                   # noqa: F401  Overlay より前に import

    # **クロックは最初に 1 回だけ確定させる。**条件を変えないので、
    # proj004 の「条件ごとに クロック → Overlay」を繰り返す必要はない。
    ac.setup_clocks(args.clkin, args.ref)
    ol = Overlay(args.bitfile)
    log(f"Overlay: {args.bitfile}")

    rows = []
    for t in range(args.trials):
        log("")
        log("=" * 72)
        log(f"=== 試行 {t + 1} / {args.trials}  (mode = {args.mode}) ===")
        log("=" * 72)
        if t > 0:
            if args.mode == "overlay":
                ol = Overlay(args.bitfile)
                log("Overlay を読み直した → タイルが起動し直す")
            else:
                for ti in sorted({c[0] for c in ac.CHANS}):
                    tile = ol.rfdc.adc_tiles[ti]
                    tile.ShutDown()
                    tile.StartUp()
                log("ShutDown → StartUp した")
                time.sleep(0.2)

        r = one_trial(ol, args, args.ref_ch)
        rows.append(r)

        weak = [i for i, d in enumerate(r["dbfs"]) if d < MIN_DBFS]
        log("")
        log(f"  トーン = {r['f_est'] / 1e6:.6f} MHz / 周期 = {r['period']:.2f} サンプル")
        log("  ch  tile/slice   振幅[dBFS]   ずれ[サンプル]    位相[度]")
        for i, (ti, si) in enumerate(ac.CHANS):
            mark = "  ← 基準" if i == args.ref_ch else ""
            warn = "  **弱すぎる**" if i in weak else ""
            deg = r["off"][i] / r["period"] * 360.0
            log(f"  {i}   {224 + ti}/{si}      {r['dbfs'][i]:>9.2f}  "
                f"{r['off'][i]:>+14.3f}  {deg:>+9.2f}{mark}{warn}")
        if weak:
            log("  **信号が来ていない ch がある。**4 分配器とケーブルを確認すること。")
            log("  位相差は測れない（この試行は判定に使えない）")

    # ------------------------------------------------------------ まとめ
    log("")
    log("=" * 72)
    log("=== まとめ ===")
    log("=" * 72)
    period = float(np.mean([r["period"] for r in rows]))
    log(f"トーンの周期 = {period:.2f} サンプル → **±{period / 2:.1f} サンプルまで一意**")
    log("")
    # **位相の列を必ず出す。**「反転か遅延か」は度で見るといちばん早い。
    # 遅延ならサンプル数が周波数によらず一定、反転なら位相が周波数によらず 180 度。
    log("  ch  tile/slice   巻き戻し後の平均  位相[度]  標準偏差     幅    集中度R")
    verdict_stable = True
    edge = []
    data = {}
    for i, (ti, si) in enumerate(ac.CHANS):
        d = np.array([r["off"][i] for r in rows])
        mean, unw, R = circ_summary(d, period)
        data[i] = unw
        span = float(unw.max() - unw.min())
        log(f"  {i}   {224 + ti}/{si}      {mean:>+11.3f}  "
            f"{mean / period * 360.0:>+8.2f}  {unw.std():>9.3f}  "
            f"{span:>7.3f}  {R:>7.3f}")
        if i != args.ref_ch and span > args.tol:
            verdict_stable = False
        # **周期の半分の近くは曖昧性の縁。**ここに乗ると符号が試行ごとに飛ぶ。
        if i != args.ref_ch and abs(abs(mean) - period / 2) < period * 0.05:
            edge.append(i)

    if edge:
        log("")
        log("**測定が曖昧性の縁に乗っている（ch "
            + ", ".join(str(i) for i in edge) + "）。**")
        log(f"  ずれが周期の半分（{period / 2:.2f} サンプル = 位相 180 度）のすぐ近くにある。")
        log("  この位置では、わずかな揺らぎで符号が ± に飛ぶ。巻き戻しは上で処理したが、")
        log("  **「反転」と「遅延」の区別がこの 1 周波数では付かない。**")
        log("")
        # **位相の列で見るのがいちばん早い。**
        log("  - **極性の反転**なら、**位相が周波数によらず 180 度**のまま")
        log("    （サンプル数の方が fs/(2f) に追随して変わる）")
        log("  - **本物の遅延**なら、**サンプル数が周波数によらず一定**")
        log("    （位相の方が周波数に比例する）")
        log("")
        log("  **周波数を変えてもう一度測ること。基本波の整数倍は避ける** — ")
        log("  整数倍だと遅延の側も同じ縁に落ちて、やはり区別が付かない。")
        log(f"    例: --tone 13.0125  → 反転なら約 {1228.8 / 2 / 13.0125:+.1f}、")
        log(f"       遅延 {abs(mean):.1f} サンプルなら別の値になる")
        log("")
        log("  **RFSoC 4x2 では Tile 224 と Tile 226 の入力極性が反転している**")
        log("  （2026-09-17 に proj006 で確定。VERSIONS.md 参照）。")
        log("  それを既知として 180 度を引いた残差:")
        for i in edge:
            m, _, _ = circ_summary(np.array([r["off"][i] for r in rows]), period)
            resid = ((m + period / 2 + period / 2) % period) - period / 2
            log(f"    ch{i}: {resid:+.3f} サンプル "
                f"（{resid / period * 360.0:+.2f} 度）← これがケーブル長差などの実体")

    if args.save:
        np.save(args.save, np.array([[r["off"][i] for i in range(ac.NCH)] for r in rows]))
        log(f"saved: {args.save}")

    log("")
    if edge:
        log("**判定: 保留。** 測定が曖昧性の縁にあり、反転と遅延の区別が付いていない。")
        log("  **上の「巻き戻し後の幅」だけは読んでよい**（巻き戻しは処理済み）。")
        log("  幅が小さければ「起動ごとには変わらない」とは言える。")
        log("  言えないのは**ずれの絶対値が何サンプルか**の方である")
    elif verdict_stable:
        log(f"**判定: タイル間のずれは起動によらず一定**（幅 < {args.tol} サンプル / "
            f"{args.trials} 回）。")
        log("  → 定数として引ける。**MTS は要らない。**")
        log("  ただしこの値には**ケーブル長の差が含まれている**。較正定数として")
        log("  使うなら、ケーブル長を揃えるか実測して引くこと（1 ns ≒ 1.2 サンプル）。")
        log("  **別の周波数でもう一度測ること。**同じ値が出れば曖昧性も潰れている")
    else:
        log(f"**判定: タイル間のずれが起動ごとに変わる**（幅 > {args.tol} サンプル）。")
        log("  → 定数では引けない。次のどちらかが要る:")
        log("     (a) 起動ごとの較正（分配した基準トーンを常時入れて測り続ける）")
        log("     (b) MTS。ただし 4x2 では LMK/LMX を 500 MHz 系に張り替える必要があり、")
        log("         fs = 1228.8 MSPS と proj004 の外部基準を捨てることになる")
        log("         （README の「決めたこと」を参照）")
        log("  **とりうる値が離散なら、その集合を記録しておくこと。**")
        log("  FIFO のポインタ由来なら、AXIS の 1 語 = 8 サンプルの整数倍に乗るはず")
        for i in range(ac.NCH):
            if i == args.ref_ch:
                continue
            u = np.round(data[i], 1)
            log(f"    ch{i}: {sorted(set(u.tolist()))}")


if __name__ == "__main__":
    main()
