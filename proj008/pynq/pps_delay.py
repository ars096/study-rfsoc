#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj008 — 1PPS を ADC に常時入れ、較正定数を **4ch 同時に**測る。

proj007 で `L_adc − D_pps` は装置の定数ではなく**エポックごとの定数**だと決着した。
だとすれば較正値を持ち回る設計は成立しない。**1PPS を ADC のチャネルに常時入れておけば、
1 回のキャプチャ（53 µs）が N も k も δ もまとめて与える。**

proj007 からの差は 1 つだけ: **512 bit 語には 4ch すべてが入っているので、
1 キャプチャが 4 つの独立な測定になる。** 追加のキャプチャは要らない。

    1PPS ─┬─(2分配 −3 dB)────────────────▶ PPS Clk
          └─(2分配 −3 dB)─ 4分配(−6 dB) ─┬─(減衰)─▶ ADC_A  ch3
                                          ├─(減衰)─▶ ADC_B  ch2
                                          ├─(減衰)─▶ ADC_C  ch1
                                          └─(減衰)─▶ ADC_D  ch0

**段を分けるのは `PPS Clk` 側を proj007 で受かった実績（−3 dB）のレベルに保つため。**
コンパレータの閾値は RefMan に記載が無い。5 分配を 1 段で作ると −7 dB まで落ちる。

使い方（ボード上）:

    sudo -E $(which python3) pps_delay.py --ch all --trials 10 --clkin 0 --atten-db 20
    sudo -E $(which python3) pps_delay.py --ch all --epochs 5 --trials 5 --clkin 0

**この測定が決めること。**

| 問い | 見る所 |
|---|---|
| 同じタイルの ch は 1 本の PPS で較正できるか | タイル内の差（proj006 の予言: 0.02 サンプル以内）|
| タイルをまたいでも 1 本で足りるか | **タイル間の差がエポックをまたいで一定か** |

**後者が proj008 ① の本題である。** 一定なら PPS 1 本（科学 3ch）、
エポックごとに変わるならタイルごとに 1 本（科学 2ch）になる。
**`--epochs` を 2 以上にしないとこの問いには答えられない。**

**注意が 3 つある。**

1. **バラン（MABA-011118）は 10 MHz〜10 GHz で DC 結合ではない。**
   パルスの平坦部は垂れる。だがエッジは高周波成分なので通り、微分されて
   鋭いスパイクになる — タイミング測定にはかえって好都合である。
   「方形波が方形に見えない」で慌てないこと。
2. **減衰器は入れすぎない。まず 0 dB から始める。**
   「0 dBFS ≒ +5.8 dBm なので TTL は飽和する」は**平坦部の話で、ここには効かない**。
   バランが低周波を落とすため ADC に届くのはエッジの微分だけで、その高さは
   立ち上がりの速さで決まる。**SNR を見ながら減らす。**
   **減衰量は必ず申告する**（proj005 で決めた規約）。
3. **Tile 224 と Tile 226 は入力極性が反転している**（proj006 で確定・厳密な 180°）。
   エッジ探索は `find_edge` が絶対値を取るので**壊れない**。むしろ
   **ピークの符号が無料の対照になる** — ch0/ch1 と ch2/ch3 で符号が逆に出なければ、
   配線か ch の対応表を疑う。

分解能について正直に書いておく。PL のタイムスタンプは 1 ビート = **6.51 ns 粒度**で、
ADC 側は 0.814 ns である。すべてが同じ 10 MHz にロックしていると PPS のエッジは
ビート境界に対して毎回同じ位置に落ちるので、**この 6.51 ns の量子化誤差は
回数を増やしても平均で消えない**。分光計にとっては 9 桁小さい量なので問題にならない。
**ただし ch 間の差には効かない** — 同じキャプチャの同じスタンプを共有するので、
量子化バイアスは共通項として引き算で消える。**ch 間の比較のほうが絶対値より精度が高い。**
"""

import argparse
import time

import numpy as np

import adc_capture as ac
import pps as pps_mod

log = ac.log
SAMP_NS = 1e9 / ac.FS_HZ            # = 0.8138 ns

# **proj006 で実測して確定した対応**（2026-09-17・`slice_map.py`）。
# ラベルから推測した値ではない。SMA を 1 本ずつ挿し替えて 4 本とも測り、
# 2 番目の ch との差は 59〜61 dB で取り違えようがなかった。
# 512 bit 語の並び（ch0 が最下位）は **SMA ラベルの逆順**になる。
SMA_OF_CH = {0: "ADC_D", 1: "ADC_C", 2: "ADC_B", 3: "ADC_A"}
TILE_NO = {0: 224, 2: 226}          # ac.CHANS のタイル添字 → RFDC のタイル番号

# proj006 の実測値。**予言として使い、外れたら測定系を疑う。**
#
# **量の種類を取り違えないこと（2026-09-18 に取り違えた）。**
# proj006 がタイル間について測ったのは **CW の位相を巻き戻した「起動ごとのばらつき」**
# であって、**あるエポックでの平均オフセットではない**。
#
#   | | 10.0125 MHz | 13.0125 MHz |
#   |---|---|---|
#   | タイル間の幅（巻き戻し後）| 2.64 サンプル | 5.30 サンプル |
#   | 同 標準偏差               | 0.93         | 1.50         |
#
# したがって **1 エポックの平均オフセットを 1.5 と比べても意味が無い。**
# 比べてよいのは **エポックをまたいだ平均の σ** である（--epochs で出る）。
PRED_WITHIN_TILE_SIGMA = 0.02       # 同一タイル内: σ 0.018 →「0.02 サンプル以内」
PRED_WITHIN_TILE_SPAN = 0.054       # 同 幅
PRED_CROSS_TILE_RMS = (0.93, 1.50)  # タイル間: **起動ごとの σ**（平均オフセットではない）
PRED_CROSS_TILE_SPAN = (2.64, 5.30) # 同 幅


def check_chan_map():
    """**ch → SMA の対応表がビットストリームの並びと合っているか。**

    `SMA_OF_CH` は `build.tcl` の `chans` の並びに依存する。並びを変えると
    **ラベルだけが黙って嘘になる**（測定は成立し、値も出る）。
    proj007 で踏んだ穴はすべてこの形だったので、機械に照合させる。
    """
    expect = [(0, 0), (0, 2), (2, 0), (2, 2)]
    if list(ac.CHANS) != expect:
        raise SystemExit(
            f"**ac.CHANS が {list(ac.CHANS)} で、SMA_OF_CH が前提とする {expect} と違う。**\n"
            "  build.tcl の chans を変えたなら SMA_OF_CH も直すこと。\n"
            "  直さないと ch のラベルだけが嘘になり、測定は成立したまま結論が壊れる。")


def tile_of(c):
    return TILE_NO[ac.CHANS[c][0]]


def label(c):
    return f"ch{c} {SMA_OF_CH[c]}(T{tile_of(c)})"


def beat_summary(a):
    """**±1 ビートのディザを潰さずに要約する。**

    PPS のエッジがビート境界の上に乗ったエポックでは、PL のスタンプが
    ±1 ビート（8 サンプル）でばたつく。すると測定値は **2 つの山**になる。

    **ここに算術平均を使うと、平均は山と山の間に落ちてどちらの山にも
    対応しない値を返し、標準偏差は膨らんで「精度が悪い」ように見える。**
    実際の精度は 0.2 サンプル級である。
    proj006 で「位相の巻き戻る量に算術平均を使って誤判定を出しかけた」のと
    **まったく同じ形**で、**壊れた統計が壊れたこと自体を隠す。**

    中央値からのビート単位のずれで分類し、**多数派の山だけを返す。**
    戻り値は (平均, 標準偏差, 多数派の数, ディザの内訳 dict)。

    **ch ごとに掛けること。** 4ch をまとめてから要約すると、
    ch 間の実差が「ばらつき」に見えて同じ罠に落ちる。
    """
    a = np.asarray(a, dtype=np.float64)
    med = float(np.median(a))
    key = np.round((a - med) / ac.SPW).astype(int)   # ビート単位のずれ
    counts = {}
    for k in key:
        counts[int(k)] = counts.get(int(k), 0) + 1
    main = max(counts, key=lambda k: counts[k])
    sel = a[key == main]
    return float(sel.mean()), float(sel.std()), int(sel.size), counts


def find_edge(x, frac=0.5, center=None, half=None):
    """微分されたパルスの立ち上がり位置を返す（サンプル単位・小数）。

    **argmax をそのまま使わない。** ピークの位置は波形の形で動く。
    ピークまで遡って **振幅が frac を横切る点**を線形内挿で取る方が、
    信号源やケーブルを替えても意味が変わらない。

    **絶対値を取るので、タイル間の 180° 反転では壊れない**（proj006）。

    **探索は予測位置の周りに限る（center / half）。**
    2026-09-17、窓全体の argmax を取っていたため、**ADC 入力に何も繋がって
    いない状態でも「測定結果」が出た。** 実測位置は 65536 サンプルの窓じゅうに
    散らばり、平均 +4716 ns / 標準偏差 13324 ns という数字まで計算された。
    **「値が出た」ことを測定が成立した証拠にしない。**
    雑音のピークは必ずどこかに在り、argmax は必ず何かを返す。
    期待する遅延は 45 ns 級なので、±5 µs も見れば 100 倍以上の余裕がある。
    **窓を絞ることで結果は偏らない。偏るとすれば窓が狭すぎるときだけで、
    それは「窓の端に張り付く」という分かる形で出る。**
    """
    a = np.abs(x.astype(np.float64))
    n = a.size
    if center is None or half is None:
        lo, hi = 0, n
    else:
        lo = max(0, int(center) - int(half))
        hi = min(n, int(center) + int(half) + 1)
    pk = lo + int(np.argmax(a[lo:hi]))
    th = a[pk] * frac
    i = pk
    while i > lo and a[i] > th:
        i -= 1
    if i == pk:
        return float(pk), pk, a[pk]
    # a[i] <= th < a[i+1]
    d = a[i + 1] - a[i]
    off = 0.0 if d == 0 else (th - a[i]) / d
    return i + off, pk, a[pk]


def measure_channel(wave, pred, half, frac):
    """1ch ぶんのエッジ測定。戻り値は dict。"""
    meas, pk, amp = find_edge(wave, frac, center=pred, half=half)
    signed = float(wave[pk])
    dbfs = 20 * np.log10(max(amp, 1e-9) / 32768.0)
    # **雑音は窓の外から取る。** 信号の在る所を混ぜない。
    # MAD からガウス相当の σ に直す（外れ値に強い）
    outside = np.abs(np.concatenate([wave[:max(0, pred - half)],
                                     wave[pred + half:]]).astype(np.float64))
    noise = float(np.median(outside)) * 1.4826 if outside.size else 0.0
    snr = 20 * np.log10(max(amp, 1e-9) / max(noise, 1e-9))
    flag = ""
    if amp >= 32700:
        flag = "  **飽和。減衰器を足す**"
    elif snr < 12.0:
        flag = "  **SNR 不足。減衰器を減らす**"
    elif abs(meas - pred) > 0.9 * half:
        flag = "  **窓の端に張り付いた。--win-us を広げる**"
    return dict(meas=meas, delay=meas - pred, amp=amp, signed=signed,
                dbfs=dbfs, snr=snr, flag=flag)


def split_beat(m):
    """サンプル単位の平均を「整数ビート + 小数部」に分ける。"""
    frac = m % ac.SPW
    nb = int(round((m - frac) / ac.SPW))
    return nb, frac


def group_mean(arrs, cs):
    """複数 ch の per-trial 平均。試行の並びは保たれる。"""
    return np.mean(np.stack([np.asarray(arrs[c], dtype=np.float64) for c in cs]), axis=0)


def paired_diff(arrs, ca, cb):
    """**ch 間の差は試行ごとに対にする。**

    4ch は同じキャプチャの同じ PL スタンプから出ている。したがって

    - ビート量子化の固定バイアス（0〜6.51 ns）
    - ±1 ビートのディザ
    - PPS そのもののジッタ

    はすべて**共通項として引き算で消える**。個々の ch の σ で差の誤差を
    見積もると、実際より 1 桁悪く見える。**対にしてから統計を取ること。**
    """
    return np.asarray(arrs[cb], dtype=np.float64) - np.asarray(arrs[ca], dtype=np.float64)


def tile_diff_series(arrs, tiles):
    """per-trial のタイル間差。戻り値 (系列, 低いタイル番号, 高いタイル番号)。"""
    ts = sorted(tiles)
    if len(ts) < 2:
        return None, None, None
    a = group_mean(arrs, tiles[ts[0]])
    b = group_mean(arrs, tiles[ts[1]])
    return b - a, ts[0], ts[1]


def epoch_verdict(means, sds, ns):
    """エポック間で一定か。戻り値 (変わる: bool, エポック間 σ, 幅, 標準誤差)。

    **判定は「エポック間のばらつき」対「実行内から予想される標準誤差」。**
    3 倍を超えたら本物の変化と読む（proj007 で較正定数がエポックごとだと
    決着させたときと同じ基準）。
    """
    means = np.asarray(means, dtype=np.float64)
    if means.size < 2:
        return False, 0.0, 0.0, float("inf")
    spread = float(means.std(ddof=1))
    span = float(means.max() - means.min())
    sem = float(np.mean(sds)) / np.sqrt(max(1.0, float(np.mean(ns))))
    # **bool() で包む。** numpy の bool_ を返すと `is True` に一致せず、
    # 呼ぶ側の判定が黙って落ちる（テストで露見した）。
    return bool(spread > 3 * sem), spread, span, sem


def parse_chans(s):
    if s.strip().lower() == "all":
        return list(range(ac.NCH))
    out = []
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        c = int(tok)
        if not 0 <= c < ac.NCH:
            raise SystemExit(f"ch は 0〜{ac.NCH - 1} の範囲。{c} は範囲外")
        if c not in out:
            out.append(c)
    if not out:
        raise SystemExit("--ch が空")
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=ac.BITFILE)
    p.add_argument("--ch", default="all",
                   help="1PPS を入れた ch。'all' か '0,2' のような並び。"
                        "512bit 語の並びで、**SMA ラベルの逆順**（ch0 = ADC_D）")
    p.add_argument("--trials", type=int, default=10)
    p.add_argument("--nsamples", type=int, default=ac.MAX_BEATS * ac.SPW)
    p.add_argument("--k", type=int, default=2, help="何秒先の PPS を狙うか")
    p.add_argument("--frac", type=float, default=0.5, help="エッジ判定の振幅比")
    p.add_argument("--win-us", type=float, default=5.0,
                   help="予測位置の周り ±この時間だけを探す [us]。"
                        "期待する遅延は 45 ns 級なので既定で 100 倍以上の余裕がある")
    p.add_argument("--atten-db", type=float, default=0.0,
                   help="ADC 入力までの減衰量 [dB]。**記録のために必ず申告する**")
    p.add_argument("--pol", type=int, default=0, choices=(0, 1))
    p.add_argument("--zone", type=int, default=1, choices=(1, 2))
    p.add_argument("--fs", type=float, default=ac.FS_HZ / 1e6)
    p.add_argument("--no-clk", action="store_true",
                   help="**xrfclk を触らない。** LMK/LMX の設定は PL と独立なので、"
                        "一度 --clkin 0 で書けば以後は残る。"
                        "「クロックの位相はそのまま、Overlay だけ焼き直し」を作るため")
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--epochs", type=int, default=1,
                   help="**エポックを N 回張り直して、そのたびに測る。**"
                        "タイル間の差がエポックごとに変わるかはここでしか分からない")
    p.add_argument("--src-tile", type=int, default=2,
                   help="MMCM の源のタイル（build.tcl の wiz_src_tile）。"
                        "--epoch-mode src のとき、これを止めて新しいエポックを作る")
    p.add_argument("--epoch-mode", default="overlay", choices=("src", "both", "overlay"),
                   help="**エポックの作り方。測っている量がこれで変わる。** "
                        "overlay = Overlay を焼き直す（**既定**）。ShutDown() を使わず、"
                        "全タイルを同時に立ち上げ直す。**実運用のエポック変化に最も近い**。 "
                        "src = 源のタイルだけ止める（proj007 の --epoch-test と同じ）。"
                        "**止めなかったタイルだけが動く非対称な操作**なので、"
                        "タイル間差を測る用途には使えない（2026-09-18 に踏んだ）。 "
                        "both = 両タイルを止めて起動し直す。**このボード / ドライバでは成立しない**"
                        "（同上。下のコメントを見る）")
    p.add_argument("--tol-ns", type=float, default=None,
                   help="**較正せずに許せるタイル間のずれ [ns]。**"
                        "これを渡さないと構成 B の判定（PPS 1 本か 2 本か）を出さない。"
                        "**「一定ではない」と「較正が要る」は別の問いだから** —— "
                        "実行内の誤差が 0.01 サンプル級なので、有意差はほぼ必ず出る。"
                        "**有意であることは、設計上効くことを意味しない**（2026-09-18）")
    p.add_argument("--save", default=None, help="1 回目の波形を .npy で残す")
    args = p.parse_args()

    check_chan_map()
    chans = parse_chans(args.ch)

    from pynq import Overlay
    import xrfdc                                   # noqa: F401

    if args.no_clk:
        # **小数部が「起動ごと」に引き直される原因の切り分けに使う。**
        log("**xrfclk を触らない（--no-clk）。** 直前の --clkin 0 の設定が残っている前提")
        log("  残っていなければ基準は出荷時（内部 Si5395）のままになる。")
        log("  **判定は ppm で行う** — pps.py --watch で確かめられる")
    else:
        ac.setup_clocks(args.clkin, args.ref)
    ol = Overlay(args.bitfile)
    log(f"Overlay: {args.bitfile}")
    blocks = ac.start_tiles(ol.rfdc, args.fs * 1e6, args.zone)
    t_tiles = time.time()

    pps = pps_mod.PPS(ol)
    pps.check_magic()
    pps.set_pol(args.pol)

    # **Overlay とタイル起動を終えても、まだ PPS は 1 回も来ていない。**
    # リセット解除は Overlay の直後で、そこから start_tiles() の 177 ms しか
    # 経っていない。1 Hz なので `alive` は 0 のままである。
    # **当初これを「start_tiles() がリセットを起こす」と診断したが誤りだった。**
    # **対策が動くことは、診断が正しいことの証拠にならない。**
    d_ready = pps_mod.wait_ready(pps, t_tiles, label="タイル起動")
    epoch0 = d_ready["epoch"]

    n_beats = args.nsamples // ac.SPW
    offset = -(n_beats // 2)        # PPS が取得窓の真ん中に来るようにする
    log("")
    log(f"取得長 {args.nsamples} サンプル/ch = {n_beats} ビート "
        f"({args.nsamples / ac.FS_HZ * 1e6:.1f} us)")
    log(f"PPS は窓の中央（先頭から {-offset * pps_mod.BEAT_NS / 1e3:.1f} us）に来る予定")
    log(f"減衰量 {args.atten_db:.1f} dB / pol={args.pol}")
    log(f"測る ch: {', '.join(label(c) for c in chans)}")
    log("")

    def run_trials(epoch0, tag):
        """1 エポックぶんの試行。戻り値は {ch: [サンプル単位の遅延, ...]}。"""
        results = {c: [] for c in chans}
        signs = {c: [] for c in chans}
        for t in range(args.trials):
            start_at, d = pps.next_start(k=args.k, offset=offset)
            # **予測する PPS のビートは 64 bit で持つ。**start_at は下位 32 bit だけ
            pps_beat = d["stamp"] + args.k * pps_mod.BEATS_PER_SEC
            x = ac.capture(ol, args.nsamples, blocks=None, start_at=start_at, pps=pps)
            snap = pps.snapshot()
            # **試行をまたいで原点が変わっていないこと。**
            # 変わっていれば pps_beat の予測が別の原点の値になり、
            # **遅延ではなく原点の差を測ってしまう**（しかも値は出る）
            if snap["epoch"] != epoch0:
                log(f"  [{t}] **時刻の原点が変わった（epoch {epoch0} → {snap['epoch']}）。**")
                log("       この試行以降は無効。RFDC のタイルか MMCM を疑う")
                break
            if (snap["t_start"] & 0xFFFFFFFF) != start_at:
                log(f"  [{t}] **t_start が start_at と違う** "
                    f"({snap['t_start'] & 0xFFFFFFFF} != {start_at})。発火の設計が壊れている")
                continue
            if snap["flags"] & pps_mod.FLAG_LATE:
                log(f"  [{t}] late。--k を増やす")
                continue

            # PL が言う PPS の位置（取得窓の先頭からのサンプル数）
            pred = (pps_beat - snap["t_start"]) * ac.SPW
            half = int(round(args.win_us * 1e-6 * ac.FS_HZ))
            for c in chans:
                m = measure_channel(x[c], pred, half, args.frac)
                results[c].append(m["delay"])
                signs[c].append(1 if m["signed"] >= 0 else -1)
                pm = "+" if m["signed"] >= 0 else "-"
                log(f"  [{t:2d}] {label(c):<18} 差 {m['delay']:+9.2f} サンプル "
                    f"= {m['delay'] * SAMP_NS:+9.2f} ns   "
                    f"ピーク {m['dbfs']:6.1f} dBFS({pm}) / SNR {m['snr']:5.1f} dB{m['flag']}")
            if t == 0 and tag == 0 and args.save:
                np.save(args.save, x)
                log(f"       {args.save} に保存")
        return results, signs

    # ---- エポックごとに測る ----
    per_epoch = []      # [(epoch, {ch: np.array})]
    all_signs = {c: [] for c in chans}
    for e in range(args.epochs):
        if args.epochs > 1:
            log(f"==== epoch {epoch0}（{e + 1} / {args.epochs}）====")
        r, sg = run_trials(epoch0, e)
        for c in chans:
            all_signs[c].extend(sg[c])
        if min(len(v) for v in r.values()) >= 2:
            per_epoch.append((epoch0, {c: np.array(r[c]) for c in chans}))
        else:
            log(f"  **epoch {epoch0} は試行が足りなかった**")
        if e == args.epochs - 1:
            break

        # ---- 次のエポックを作る ----
        #
        # **どう作るかで、測っている量が変わる。**
        # 2026-09-18、`src`（源のタイルだけ止める）で測ったところ、
        # **止めなかった Tile 224 が 4 ビート動き、止めた Tile 226 は 1 ビート未満**
        # だった。エポックの作り方が非対称なので、タイル間差の変動がそのまま
        # 「片方だけ触った」ことの反映になる。**タイル間差を測る用途には使えない。**
        log("")
        if args.epoch_mode == "overlay":
            log("---- Overlay を焼き直して新しいエポックを作る ----")
            ol = Overlay(args.bitfile)
            blocks = ac.start_tiles(ol.rfdc, args.fs * 1e6, args.zone)
            pps = pps_mod.PPS(ol)
            pps.check_magic()
            pps.set_pol(args.pol)
            d_ready = pps_mod.wait_ready(pps, time.time(), label="Overlay 焼き直し")
        else:
            targets = ([args.src_tile] if args.epoch_mode == "src"
                       else sorted(set(t for t, _ in ac.CHANS)))
            others = [t for t in targets if t != args.src_tile]
            has_src = args.src_tile in targets
            log(f"---- adc_tiles{targets} を止めて新しいエポックを作る "
                f"（--epoch-mode {args.epoch_mode}）----")

            # **`both` はこのボード / ドライバでは成立しない。**（2026-09-18）
            #
            # 複数タイルに `ShutDown()` を掛けると、そのあとどの順で `StartUp()` しても
            # タイルの状態機械が進まない。**順序の問題ではない。**
            #
            #   起動順 0 → 2 : ADC 0 timed out at **state 14**（AXIS クロックが無い）
            #   起動順 2 → 0 : ADC 2 timed out at **state 3**（クロック検出で止まる）
            #
            # 源を単独で止めて起動する `src` は 5 エポック通るので、**「もう片方も
            # 止めた」こと自体**が効いている。深追いはしない —— **`overlay` は
            # `ShutDown()` を使わずに同じ目的を果たし、しかも実運用に近い。**
            #
            # 以下の順序（止めるときは源を最後、起動するときは源を最初）は
            # `state 14` の側だけは説明できるので残してある。
            # **順序に依存がある**のは事実である（VERSIONS.md）。
            # build.tcl は **両タイルの `m*_axis_aclk` を MMCM の出力**に繋いでおり、
            # その MMCM の源は `--src-tile` のタイルの `clk_adc<n>` である。
            # したがって **源のタイルが止まっていると、他のタイルは AXIS クロックを
            # 失う。** その状態で `StartUp()` を呼ぶとタイルの状態機械が進めず、
            #   RuntimeError: ADC 0 timed out at state 14 in XRFdc_WaitForRestartClr
            # で落ちる。**止めるときは源を最後に、起動するときは源を最初に。**
            for t in others:
                ol.rfdc.adc_tiles[t].ShutDown()
            if has_src:
                ol.rfdc.adc_tiles[args.src_tile].ShutDown()
            time.sleep(0.5)
            if pps.flags() & pps_mod.FLAG_LOCKED:
                log("  **停止中も locked が立っている。** --src-tile が違う")
                break

            def _startup(t, why):
                try:
                    ol.rfdc.adc_tiles[t].StartUp()
                except RuntimeError as e:
                    log(f"  **adc_tiles[{t}] の StartUp が失敗した（{why}）。**")
                    log(f"    {e}")
                    log("    **AXIS クロックが来ていない可能性が高い。**")
                    log(f"    build.tcl は全タイルの m*_axis_aclk を MMCM に繋いでおり、")
                    log(f"    その源は adc_tiles[{args.src_tile}] である。")
                    log("")
                    log("  **`--epoch-mode both` はこのボード / ドライバでは成立しない。**")
                    log("    複数タイルに ShutDown() を掛けると、どの順で StartUp() しても")
                    log("    状態機械が進まない（state 14 / state 3）。**順序の問題ではない。**")
                    log("    **`--epoch-mode overlay` を使うこと** — ShutDown() を使わず、")
                    log("    実運用のエポック変化にも近い")
                    raise SystemExit(1)

            if has_src:
                _startup(args.src_tile, "MMCM の源")
                t0 = time.time()
                while not (pps.flags() & pps_mod.FLAG_LOCKED):
                    if time.time() - t0 > 10.0:
                        log("  **locked が戻らない。** ここで止める")
                        break
                    time.sleep(0.05)
                log(f"  adc_tiles[{args.src_tile}]（源）が起動し MMCM がロックした")
            for t in others:
                _startup(t, "源の起動と MMCM ロックの後")
            t0 = time.time()
            while not (pps.flags() & pps_mod.FLAG_LOCKED):
                if time.time() - t0 > 10.0:
                    log("  **locked が戻らない。** ここで止める")
                    break
                time.sleep(0.05)
            blocks = ac.start_tiles(ol.rfdc, args.fs * 1e6, args.zone)
            d_ready = pps_mod.wait_ready(pps, time.time(), label="タイル再起動")
        epoch0 = d_ready["epoch"]
        log("")

    log("")
    if not per_epoch:
        log("**測定が成立していない。** 上のメッセージを見る")
        return

    # ---- 極性の対照（無料で手に入る）----
    log("---- 極性の対照 ----")
    log("  proj006 で Tile 224 と Tile 226 の入力極性は反転していると確定している。")
    log("  **ピークの符号がタイルで分かれなければ、配線か ch の対応表を疑う。**")
    by_tile_sign = {}
    for c in chans:
        s = all_signs[c]
        if not s:
            continue
        pos = sum(1 for v in s if v > 0)
        dom = "+" if pos * 2 >= len(s) else "-"
        mixed = "" if pos in (0, len(s)) else f"  （+{pos} / -{len(s) - pos} で混在）"
        by_tile_sign.setdefault(tile_of(c), set()).add(dom)
        log(f"  {label(c):<18} 符号 {dom}{mixed}")
    if len(by_tile_sign) >= 2 and all(len(v) == 1 for v in by_tile_sign.values()):
        doms = {t: next(iter(v)) for t, v in by_tile_sign.items()}
        if len(set(doms.values())) == 2:
            log("  → **タイルで符号が分かれた。proj006 の 180° と整合。**")
        else:
            log("  → **タイルで符号が分かれていない。** proj006 の 180° と食い違う。")
            log("    分配器の出力を入れ替えて対照を取る（proj006 と同じ手）")
    log("")

    # ---- ch ごとの較正定数（最初のエポック）----
    ep0, ch0_arrays = per_epoch[0]
    stat = {}
    for c in chans:
        m, sd, n, counts = beat_summary(ch0_arrays[c])
        nb, frac = split_beat(m)
        stat[c] = dict(mean=m, sd=sd, n=n, counts=counts, nb=nb, frac=frac)

    log(f"---- ch ごとの較正定数（epoch {ep0}）----")
    log("  ch  SMA     Tile  多数派  平均 [ns]   σ [ns]  整数ビート  小数 [sample]  ディザ")
    log("  " + "-" * 82)
    for c in chans:
        s = stat[c]
        dith = "なし" if len(s["counts"]) == 1 else f"あり {s['counts']}"
        log(f"  {c:<3} {SMA_OF_CH[c]:<7} {tile_of(c):<5} {s['n']:>5}  "
            f"{s['mean'] * SAMP_NS:>9.2f}  {s['sd'] * SAMP_NS:>7.2f}  "
            f"{s['nb']:>9}  {s['frac']:>12.2f}  {dith}")
    log("")
    log("  **整数ビートと小数部を分けて読む。** エポック間で動くのは整数ビートだけで、")
    log("  小数部は物理的な位相である（proj007 の実測: N は 33/34/35/37、小数部は 0.2 ns 以内）。")
    log("  **未知数が整数なので、エポックあたり 1 回の測定で厳密に決まる。**")
    log("")

    # ---- 判定 3 / 4 — どちらも「対にした差」で見る ----
    tiles = {}
    for c in chans:
        tiles.setdefault(tile_of(c), []).append(c)

    log("---- 判定 3: タイル内の差 ----")
    log(f"  **予言（proj006）: 同一タイル内は {PRED_WITHIN_TILE_SIGMA} サンプル以内で不変。**")
    log("  proj006 は CW トーンの位相で測った。ここは PPS のエッジで測る。")
    log("  **まったく違う方法で同じ量を測るので、一致すれば両方信用できる。**")
    within_ok = []
    for t, cs in sorted(tiles.items()):
        if len(cs) < 2:
            log(f"  Tile {t}: ch が 1 本しかないので判定できない")
            continue
        a, b = cs[0], cs[1]
        d = paired_diff(ch0_arrays, a, b)
        mu = float(d.mean())
        sd = float(d.std(ddof=1)) if d.size >= 2 else 0.0
        sem = sd / np.sqrt(max(1, d.size))
        good = abs(mu) <= PRED_WITHIN_TILE_SIGMA
        verdict = "予言と整合" if good else (
            "予言より大きいが測定の誤差の範囲内" if abs(mu) <= 3 * sem
            else "**予言と食い違う**")
        within_ok.append(good)
        log(f"  Tile {t}: {SMA_OF_CH[b]} − {SMA_OF_CH[a]} = {mu:+.3f} ± {sem:.3f} サンプル "
            f"({mu * SAMP_NS:+.3f} ns)  [実行内 σ {sd * SAMP_NS:.3f} ns]  → {verdict}")
    if within_ok and all(within_ok):
        log("  → **同じタイルの ch は 1 本の PPS で較正できる。**")
    elif within_ok:
        log("  → タイル内でも差がある。**構成 B の割り当ては ch ごとの PPS まで要る**")
    log("")

    log("---- 判定 4: タイル間の差 ----")
    log("  **proj006 に直接比べられる数字は無い。ここで当たり外れを言わない。**")
    log(f"  proj006 が測ったのは CW の位相を巻き戻した**起動ごとのばらつき**"
        f"（σ {PRED_CROSS_TILE_RMS[0]}〜{PRED_CROSS_TILE_RMS[1]} サンプル / "
        f"幅 {PRED_CROSS_TILE_SPAN[0]}〜{PRED_CROSS_TILE_SPAN[1]} サンプル）であって、")
    log("  **あるエポックでの平均オフセットではない。** ここで出るのは後者である。")
    log("  **平均と RMS を比べない**（2026-09-18 に取り違えた）。")
    d, t_lo, t_hi = tile_diff_series(ch0_arrays, tiles)
    if d is None:
        log("  タイルが 1 つしか測れていないので判定できない")
    else:
        mu = float(d.mean())
        sd = float(d.std(ddof=1)) if d.size >= 2 else 0.0
        sem = sd / np.sqrt(max(1, d.size))
        log("")
        log(f"  Tile {t_hi} − Tile {t_lo} = {mu:+.3f} ± {sem:.3f} サンプル "
            f"({mu * SAMP_NS:+.3f} ns)  [実行内 σ {sd * SAMP_NS:.3f} ns]")
        log(f"  （8 サンプル = 1 ビート = {pps_mod.BEAT_NS:.2f} ns。"
            f"この差は {abs(mu) / ac.SPW:.2f} ビート）")
        lo, hi = PRED_CROSS_TILE_SPAN
        if lo <= abs(mu) <= hi:
            log(f"  参考: proj006 が起動ごとに見た幅 {lo}〜{hi} サンプルの**中に入っている**。")
            log("        同じ現象を見ている見込みは高いが、**これは整合の確認であって判定ではない。**")
        else:
            log(f"  参考: proj006 が起動ごとに見た幅 {lo}〜{hi} サンプルの**外にある**。")
    log("")
    log("  **この差は「その瞬間の値」でしかない。**")
    log("  較正の設計を決めるのも、proj006 と比べられる量になるのも、")
    log("  **エポックをまたいだときのばらつき**である（下）。")
    log("")

    # ---- 判定 5 の材料: エポックをまたいだ比較 ----
    log("---- エポックをまたいだ比較 ----")
    if len(per_epoch) < 2:
        log("  **エポックが 1 つしかないので、タイル間の差が一定かは判定できない。**")
        log("  これは proj008 ① の本題なので、**--epochs 5 で測り直すこと。**")
        log("  1 エポックの測定は「その瞬間の差」であって、較正の設計を決める材料にならない。")
        log("")
    else:
        log("  **ここが proj008 ① の本題である。**")
        log("  タイル間の差がエポックをまたいで一定なら、**PPS 1 本（科学 3ch）で足りる**。")
        log("  エポックごとに変わるなら、**タイルごとに 1 本（科学 2ch）が要る**。")
        log("")
        head = "  epoch " + "".join(f"{label(c):>22}" for c in chans) + "        タイル間差"
        log(head)
        log("  " + "-" * (len(head) - 2))
        cx_means, cx_sds, cx_ns = [], [], []
        for ep, arrs in per_epoch:
            cells = []
            for c in chans:
                m, sd_c, n_c, counts = beat_summary(arrs[c])
                nb, frac = split_beat(m)
                cells.append(f"{m * SAMP_NS:>13.2f} (N{nb:>3})")
            dd, _, _ = tile_diff_series(arrs, tiles)
            if dd is None:
                cx_s = "            —"
            else:
                mu = float(dd.mean())
                sd = float(dd.std(ddof=1)) if dd.size >= 2 else 0.0
                cx_means.append(mu)
                cx_sds.append(sd)
                cx_ns.append(dd.size)
                cx_s = f"{mu:+9.3f} sa"
            log(f"  {ep:>5} " + "".join(f"{x:>22}" for x in cells) + f"  {cx_s}")
        log("")
        log("  **N は整数ビート。** エポック間で動くのはここだけのはず（proj007 の実測）。")
        log("")
        # **タイルごとの変動を別々に出す。**
        # タイル間差だけを見ていると「片方のタイルだけが動いている」ことに気づけない。
        # 2026-09-18、`--epoch-mode src` で止めなかったタイルだけが 4 ビート動いた。
        log("  ---- タイルごとのエポック間変動（**非対称なら測定方法を疑う**）----")
        per_tile_means = {}
        for t, cs in sorted(tiles.items()):
            ms = [float(np.mean([beat_summary(arrs[c])[0] for c in cs]))
                  for ep, arrs in per_epoch]
            per_tile_means[t] = ms
            a = np.asarray(ms)
            sd_t = float(a.std(ddof=1)) if a.size >= 2 else 0.0
            span_t = float(a.max() - a.min()) if a.size else 0.0
            log(f"    Tile {t}: σ {sd_t:7.3f} サンプル / 幅 {span_t:7.3f} サンプル "
                f"({span_t / ac.SPW:.2f} ビート)")
        if len(per_tile_means) >= 2:
            spans = {t: (max(m) - min(m)) for t, m in per_tile_means.items()}
            big = max(spans, key=lambda k: spans[k])
            small = min(spans, key=lambda k: spans[k])
            if spans[big] > 3.0 * max(spans[small], 1e-9):
                log("")
                log(f"    → **Tile {big} だけが Tile {small} の "
                    f"{spans[big] / max(spans[small], 1e-9):.1f} 倍動いている。**")
                log("      タイルが対称に扱われていない。**エポックの作り方を疑う。**")
                if args.epoch_mode == "src":
                    log(f"      `--epoch-mode src` は adc_tiles[{args.src_tile}] しか止めない。")
                    log("      **`--epoch-mode both` か `overlay` で測り直すこと。**")
                    log("      この状態のタイル間差は、装置の性質ではなく")
                    log("      **操作の非対称性**を測っている")
        log("  **タイル間差は対にして取っている**ので、ビート量子化とディザは消えている。")
        log("")
        if len(cx_means) >= 2:
            varies, spread, span, sem = epoch_verdict(cx_means, cx_sds, cx_ns)
            log(f"  タイル間差のエポック間 σ    : {spread:.3f} サンプル "
                f"({spread * SAMP_NS:.3f} ns)")
            log(f"  同 幅                       : {span:.3f} サンプル "
                f"({span * SAMP_NS:.3f} ns)")
            log(f"  実行内から予想される標準誤差 : {sem:.3f} サンプル "
                f"({sem * SAMP_NS:.3f} ns)")
            log("")
            lo, hi = PRED_CROSS_TILE_RMS
            log(f"  （proj006 の起動ごとの σ は {lo}〜{hi} サンプル。"
                "**ここで初めて同じ量どうしを比べられる**）")
            log("")
            # ---- (a) 統計の問い: 一定か、変わるか ----
            if varies:
                log(f"  [統計] **一定ではない。** エポック間の σ が実行内から予想される")
                log(f"         標準誤差の {spread / max(sem, 1e-12):.0f} 倍ある")
            else:
                log("  [統計] **一定と区別がつかない**（この試行数の範囲で）。")
                log("         **「有意差なし」は「差がない」ではない。**")
            log("")
            # ---- (b) 設計の問い: 較正が要るか ----
            #
            # **(a) と (b) は別の問いである。**（2026-09-18 に取り違えた）
            # 実行内の誤差が 0.01 サンプル級なので、**有意差はほぼ必ず出る。**
            # 「有意である」ことは「設計上効く」ことを意味しない。
            # 判定には**要求値**が要る。要求値が無いなら**答えを返さない。**
            if args.tol_ns is None:
                log("  [設計] **判定しない。** `--tol-ns`（較正せずに許せるずれ）が無い。")
                log("         **実行内の誤差が 0.01 サンプル級なので、有意差はほぼ必ず出る。**")
                log("         有意であることは、設計上効くことを意味しない。")
                log(f"         決めるべきはこの幅 **{span * SAMP_NS:.3f} ns** を許せるかどうかで、")
                log("         それは分光計の要求であってこの測定では決まらない。")
                log("         **要求値を決めて `--tol-ns` で渡すこと。**")
            else:
                tol_sa = args.tol_ns / SAMP_NS
                log(f"  [設計] 要求 {args.tol_ns:.3f} ns（= {tol_sa:.3f} サンプル）に対し、")
                log(f"         エポック間の幅 {span * SAMP_NS:.3f} ns / σ {spread * SAMP_NS:.3f} ns")
                if span * SAMP_NS <= args.tol_ns:
                    log("")
                    log("         → **要求の中に収まっている。較正なしで足りる。**")
                    log("           **PPS 1 本（科学 3ch）で足りる。**")
                    log("           タイル間差は一定ではないが、**効かない大きさである。**")
                else:
                    log("")
                    log("         → **要求を超えている。タイルごとに較正が要る。**")
                    log("           **構成 B は「タイルごとに PPS 1 本」= 科学 2ch になる。**")
            log("")
            # ---- (c) 共通成分と独立成分に分ける ----
            # **タイルが一緒に動いているのか、別々に動いているのか。**
            # 別々なら独立予測 sqrt(σ1²+σ2²) に一致するはず。
            # それより小さければ、**大半は共通（= AXIS クロックの位相）**で、
            # 残差だけが PPS 1 本では拾えない量になる。
            if len(per_tile_means) >= 2:
                sds_t = []
                for t, ms in per_tile_means.items():
                    a = np.asarray(ms)
                    sds_t.append(float(a.std(ddof=1)) if a.size >= 2 else 0.0)
                indep = float(np.sqrt(sum(x * x for x in sds_t)))
                log("  ---- 共通成分と独立成分 ----")
                log(f"    タイルが独立に動くなら σ(差) = {indep:.3f} サンプル のはず")
                log(f"    実測は {spread:.3f} サンプル")
                if indep > 0 and spread < 0.8 * indep:
                    log("    → **大半は共通の動き**（AXIS クロックの位相）で、")
                    log(f"      **PPS 1 本で拾えない残差は {spread * SAMP_NS:.3f} ns 分だけ**である")
                elif indep > 0:
                    log("    → タイルはほぼ独立に動いている")
                log("")
        else:
            log("  **タイル間差が 2 エポックぶん揃わなかった。** 判定できない")
        log("")

    # ---- 符号と式の読み方（proj007 から持ち越し）----
    log("**符号の読み方。** delay = meas − pred。")
    log("  正 = **ADC のバッファ上でエッジが PL のスタンプより後ろに現れる**。")
    log("  バッファの添字は RFDC のデータパスを通ったあとの beat に揃っているので、")
    log("  **ADC のレイテンシが効く**:")
    log("")
    log("      delay = L_adc − D_pps + (τ_ADCケーブル − τ_PPSケーブル)")
    log("")
    log("      L_adc : RFDC のデータパスのレイテンシ")
    log("      D_pps : コンパレータ＋シュミットトリガ＋同期器（2 ビート）")
    log("")
    log("  **2026-09-17、ここを逆に立てて「コンパレータ単独の遅延」だと思い込んだ。**")
    log("  ケーブルを入れ替える対照実験で符号が予想と逆に動いて発覚した。")
    log("  **外れた予言のほうが、当たった測定より多くを教えた。**")
    log("")
    log(f"**量子化の下限は 1 ビート = {pps_mod.BEAT_NS:.2f} ns。**")
    log("  すべてが同じ 10 MHz にロックしていると、この誤差は回数を増やしても消えない。")
    log("  **ただし ch 間の差には効かない** — 同じキャプチャの同じスタンプを共有するので、")
    log("  量子化バイアスは共通項として引き算で消える。")
    log("  **判定 3 / 4 の差のほうが、ch ごとの絶対値より精度が高い。**")
    log("")
    log("**ケーブル長差の除き方。** 4 本を巡回させてもう一度測る。")
    log("  ケーブル項だけが ch について入れ替わるので、2 回の平均が ch の真の差になる。")
    log("  proj007 の実測: **1 ns ≒ 25 cm ≒ "
        f"{1.0 / SAMP_NS:.2f} サンプル**（短縮率 0.85。VF 0.66 の 20 cm ではない）。")
    log(f"  **同じ長さのケーブルを使っているなら、ch 間の差にケーブルは効かない。**")
    log(f"  減衰量 {args.atten_db:.1f} dB と経路の構成を README に残す（proj005 の規約）")


if __name__ == "__main__":
    main()
