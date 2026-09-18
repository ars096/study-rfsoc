#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj008 — pps_delay.py の解析側を実機なしで検証する。

**なぜ要るか。** proj008 の結論（「PPS 1 本で足りる」か「タイルごとに 1 本要る」か）を
出すのは `epoch_verdict` の分岐である。この分岐は実機でしか通らないので、
**一度も走ったことのないコードが結論を印字する**状態になりうる。
proj007 で踏んだ穴はすべて「動いているように見える」形だったので、機械に通させる。

ここで検証するのは数値の扱いだけで、ハードウェアには触らない。
`make sim` から呼ばれる。numpy 以外の依存は無い。
"""

import os
import sys

try:
    import numpy as np
except ImportError:
    # **skip して成功を返さない。** 通らなかったものを成功として報告する形は、
    # このリポジトリで踏んだ穴そのもの（make build の空振り）。
    sys.exit("**numpy が無いのでこのテストは走らない。**\n"
             "  Vivado サーバはビルド専用の機械なので、それで正しい。\n"
             "  編集した機械（Mac）かボード上で `make sim-analysis` を走らせること。")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pynq"))

import adc_capture as ac              # noqa: E402
import pps_delay as pd                # noqa: E402

FAILED = []


def check(cond, name, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}   {detail}")
        FAILED.append(name)


def close(a, b, tol=1e-9):
    return abs(float(a) - float(b)) <= tol


# ---- ch の対応表 ----
print("ch の対応表")
try:
    pd.check_chan_map()
    check(True, "check_chan_map が通る")
except SystemExit as e:
    check(False, "check_chan_map が通る", str(e))
check(pd.tile_of(0) == 224 and pd.tile_of(3) == 226,
      "ch0 は Tile 224 / ch3 は Tile 226",
      f"{pd.tile_of(0)} / {pd.tile_of(3)}")
check(pd.SMA_OF_CH[0] == "ADC_D" and pd.SMA_OF_CH[3] == "ADC_A",
      "512bit 語の並びは SMA ラベルの逆順")

# **対応表が ac.CHANS と食い違ったら止まること**を確かめる。
# ここが働かないと、build.tcl の chans を変えたときラベルだけが黙って嘘になる。
_saved = ac.CHANS
ac.CHANS = [(2, 2), (2, 0), (0, 2), (0, 0)]
try:
    pd.check_chan_map()
    check(False, "chans を入れ替えたら check_chan_map が止まる", "止まらなかった")
except SystemExit:
    check(True, "chans を入れ替えたら check_chan_map が止まる")
finally:
    ac.CHANS = _saved

# ---- parse_chans ----
print("parse_chans")
check(pd.parse_chans("all") == [0, 1, 2, 3], "all が 4ch に展開される")
check(pd.parse_chans("0,2") == [0, 2], "並びの指定")
check(pd.parse_chans(" 2 , 0 ,2") == [2, 0], "空白と重複を落とす")
try:
    pd.parse_chans("9")
    check(False, "範囲外の ch で止まる", "止まらなかった")
except SystemExit:
    check(True, "範囲外の ch で止まる")

# ---- find_edge ----
print("find_edge")
x = np.zeros(4096)
for i in range(11):
    x[2038 + i] = i * 100.0          # 2038→0, 2048→1000 の直線
x[2049:2060] = np.linspace(900, 0, 11)
pos, pk, amp = pd.find_edge(x, 0.5, center=2048, half=50)
check(close(pos, 2043.0, 1e-6), "立ち上がりの 50% 点を内挿で返す", f"{pos}")
neg, _, _ = pd.find_edge(-x, 0.5, center=2048, half=50)
check(close(neg, pos, 1e-9),
      "**極性を反転しても同じ位置**（タイル間の 180° で壊れない）", f"{neg} vs {pos}")
y = x.copy()
y[100] = 50000.0                      # 窓の外にもっと大きいピーク
win, _, _ = pd.find_edge(y, 0.5, center=2048, half=50)
check(close(win, 2043.0, 1e-6),
      "**窓の外のピークに引きずられない**（無入力で結果が出た件の対策）", f"{win}")

# ---- beat_summary ----
print("beat_summary")
a = [100.0] * 7 + [108.0] * 3         # ±1 ビート（8 サンプル）のディザ
m, sd, n, counts = pd.beat_summary(a)
check(close(m, 100.0) and n == 7,
      "**多数派の山だけを返す**（素朴な平均 102.4 を返さない）", f"平均 {m} / n {n}")
check(counts == {0: 7, 1: 3}, "ディザの内訳を残す", f"{counts}")
m2, sd2, n2, c2 = pd.beat_summary([5.0, 5.0, 5.0])
check(close(m2, 5.0) and n2 == 3 and c2 == {0: 3}, "ディザ無しのとき全数が残る")

# ---- paired_diff — 共通項が消えること ----
print("paired_diff")
rng = np.random.default_rng(0)
common = 270.0 + rng.normal(0, 0.4, 32) + 8.0 * rng.integers(0, 2, 32)  # 実行内 σ ＋ ディザ
arrs = {0: common + 0.00, 1: common + 0.01, 2: common + 1.25, 3: common + 1.26}
d = pd.paired_diff(arrs, 0, 2)
check(close(float(d.mean()), 1.25, 1e-9), "差の平均は真の差", f"{d.mean()}")
check(float(d.std(ddof=1)) < 1e-9,
      "**ビート量子化もディザも共通項として消える**", f"σ {d.std(ddof=1)}")
check(float(np.std(arrs[0], ddof=1)) > 1.0,
      "（個々の ch の σ は大きいまま — 対にしないと 1 桁悪く見える）",
      f"σ {np.std(arrs[0], ddof=1)}")

# ---- tile_diff_series ----
print("tile_diff_series")
tiles = {224: [0, 1], 226: [2, 3]}
ser, lo, hi = pd.tile_diff_series(arrs, tiles)
check(lo == 224 and hi == 226, "タイル番号の並びは昇順", f"{lo} / {hi}")
check(close(float(ser.mean()), 1.250, 1e-9),
      "タイル間差は各タイルの ch 平均の差", f"{ser.mean()}")
ser1, lo1, hi1 = pd.tile_diff_series(arrs, {224: [0, 1]})
check(ser1 is None, "タイルが 1 つなら None を返す")

# ---- epoch_verdict — **両方の分岐を通す** ----
print("epoch_verdict")
varies, spread, span, sem = pd.epoch_verdict(
    [1.00, 1.02, 0.98, 1.01, 0.99], [0.5] * 5, [10] * 5)
check(varies is False, "実行内の誤差に埋もれる変動は『一定』と読む",
      f"varies={varies} spread={spread:.4f} sem={sem:.4f}")
varies2, spread2, span2, sem2 = pd.epoch_verdict(
    [1.0, 3.0, 5.0, 2.0, 7.0], [0.05] * 5, [10] * 5)
check(varies2 is True, "実行内の誤差より十分大きい変動は『変わる』と読む",
      f"varies={varies2} spread={spread2:.4f} sem={sem2:.4f}")
check(close(span2, 6.0), "幅は最大 − 最小", f"{span2}")
v3, sp3, sn3, se3 = pd.epoch_verdict([1.0], [0.1], [10])
check(v3 is False and se3 == float("inf"),
      "エポックが 1 つなら判定しない（無限大の誤差を返す）")

# ---- split_beat ----
print("split_beat")
nb, frac = pd.split_beat(33 * 8 + 6.83)
check(nb == 33 and close(frac, 6.83, 1e-9), "整数ビートと小数部に分ける", f"{nb} / {frac}")
nb2, frac2 = pd.split_beat(-1.0)
check(nb2 * ac.SPW + frac2 == -1.0, "負の値でも復元できる", f"{nb2} / {frac2}")

print("")
if FAILED:
    print(f"**{len(FAILED)} 件 FAIL**: {', '.join(FAILED)}")
    sys.exit(1)
print("ALL PASS（解析側）")
