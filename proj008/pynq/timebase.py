#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj008 — 「バッファの添字 i のサンプルは何時のものか」に答える層。

**この層の仕事は 2 つだけである。**

1. PL のビートカウンタと UTC を対応づける（PPS 1 発と `clock_gettime` を結ぶ）
2. **答えられないときに答えない**

2 の方が重要である。proj007 / proj008 で踏んだ穴はすべて
「**動いているように見える**」形だった。較正が失効したまま尤もらしい時刻を返す層は、
まったく同じ形の失敗になる。**壊れた時刻は正常な時刻に見える。**

## 較正定数の扱い

`L_adc − D_pps` は **RFDC のデータパスのレイテンシ − コンパレータ経路の遅延**で、
**ビットストリームの性質**である（ボードの性質でも観測の性質でもない）。
RFDC の設定を変えれば変わる。

**運用形では ADC に 1PPS を入れないので、実行時にこの定数を測り直せない。**
検証できない定数は黙って古くなる —— このリポジトリで繰り返し踏んだ形そのものである。

そこで **`MAGIC` と対にして持ち、一致しなければ適用を拒否する。**
`MAGIC` はビットストリームの同一性を 1 回の読み出しで言える印なので、
RFDC の設定を変えて定数を直し忘れれば **その場で例外になる。**

**再測定はビットストリームを変えたときだけ。** 1PPS を一時的に ADC 入力へ繋いで
`pps_delay.py --ch all` を 1 回走らせ、下の表を更新する。手順は README にある。

## 符号

```
t(i) = t_anchor + (beat − stamp_anchor) / BEATS_PER_SEC + i / FS  −  (L_adc − D_pps)
                                                                  ^^^ **引く**
```

`delay = meas − pred` が**正**とは「**ADC のバッファ上でエッジが PL のスタンプより
後ろに現れる**」ことである。素直な対応づけは時刻を **213 ns 過大に**見積もるので、**引く。**

**2026-09-18、ここを `+` で書いていた。** proj007 が「符号を逆に立てた誤りは、
当たった 10 回の測定では出ず、予言を外した対照実験で初めて出た」と書いた、
まさに同じ場所である。**この向きは、式を読んでも間違いに気づけない。**
"""

import math
import time

FS_HZ = 1228800000            # 整数。ここが整数であることに全面的に依存している
SPW = 8                       # 1 ビート = 8 サンプル
BEATS_PER_SEC = FS_HZ // SPW  # = 153,600,000 ちょうど

# ns への換算は **整数のまま**やる。
#   10^9 / 1,228,800,000 = 625 / 768   （約分して厳密）
# float64 は UTC 秒（~1.7e9）のところで分解能が 200 ns 級しかなく、
# **較正定数 213 ns と同じ桁**になる。秒を float で返さないこと。
NS_NUM, NS_DEN = 625, 768


class TimebaseError(RuntimeError):
    """時刻を答えられない。**黙って古い値を返さないための例外。**"""


# ---- 較正定数（ビットストリームごと）----
#
# **MAGIC と対にする。** 一致しなければ適用しない。
# 再測定の手順: 1PPS を一時的に ADC 入力へ分配し、
#   sudo -E $(which python3) pps_delay.py --ch all --epochs 5 --trials 5
# を走らせて、判定 4 の「ケーブル入れ替えの対照」で分離した値を入れる。
CAL = {
    0x00080001: dict(
        l_adc_minus_d_pps_ns=213.16,
        unc_ns=0.09,
        # **未較正で残る量。**運用形では ADC 側に PPS を入れないので補正しない。
        epoch_residual_ns=3.3,      # Overlay ごとに 1 ビート幅（6.5 ns）で動く
        tile_residual_ns=1.8,       # Tile 226 側。proj008 判定 5
        source=("proj007 判定 4（ケーブル入れ替えの対照で分離）"
                " / proj008 判定 5（overlay 5 エポック）"),
    ),
}


# ------------------------------------------------------------------ 純関数
def samples_to_ns(n_samples):
    """サンプル数を ns へ。**整数演算だけで、最近接に丸める。**

    1 ビート = 8 サンプル = 5000/768 ns = 6.5104166... ns
    1 秒 = 1,228,800,000 サンプル = **10^9 ns ちょうど**（ここは厳密）

    **正直に: ns へ丸めるので ±0.5 ns の量子化が乗る。**
    未較正で残る量（エポック残差 3.3 ns / タイル残差 1.8 ns）より 1 桁小さいので
    実害は無いが、「厳密」ではない。要求がここまで下りてきたら ps に変える。
    """
    n = int(n_samples)
    # round-half-up を整数で
    return (n * NS_NUM + NS_DEN // 2) // NS_DEN


def utc_second_of_last_pps(t_host):
    """**秒の真ん中で読んだ**ホスト時計から、直近の PPS の UTC 整数秒を決める。

    PL が知っているのは「リセットからの PPS 数」だけで、**整数秒は PS が与える。**

    x.5 s で読めば、ホスト時計の誤差が ±0.5 s 以内である限り
    `floor` が一意に正しい答えを返す（t = x.5 + δ ∈ (x, x+1) なので）。
    **秒境界の近くで読むと 1 秒ずれる。** 呼ぶ側が位相を守ること。
    """
    return math.floor(t_host)


def offset_from_second_ns(t_ns, frac_samples=0.0):
    """整数秒からのずれを ns で返す。**整数のまま modulo を取る。**

    **float64 に落とすと死ぬ。**（2026-09-18 に踏んだ）
    UTC の ns は 1.79×10^18 で、float64 の刻みは **256 ns** である。
    `float(t_ns) - round(float(t_ns)/1e9)*1e9` と書くと、**引き算より前に
    値が 256 ns 単位へ丸められる。** 結果は「きれいに 0.00 ns」になり、
    **測定が完璧に見える。** 実際は何も測れていない。

    このファイルの冒頭に「秒を float で返さないこと」と書いておきながら、
    検査スクリプトの側で破った。**警告を書いた本人が、別のファイルで踏む。**
    だから計算はここに置き、`sim/test_timebase.py` で固定する。

    `frac_samples` はサンプル未満の端数（エッジ位置の小数部）。
    **こちらは小さい数なので float のままでよい。**
    """
    sec, rem = divmod(int(t_ns), 10**9)
    if rem >= 5 * 10**8:                 # 負側へ折り返す
        rem -= 10**9
    return rem + float(frac_samples) * (10**9 / FS_HZ)


def require_mid_second(t_host, lo=0.25, hi=0.75):
    """**秒の真ん中で読んだか。** 違えば例外。

    整数秒は `floor(t)` で決めるので、**秒境界の近くで読むと 1 秒ずれる。**
    1 秒のずれは「小さな誤差」ではなく、**要求 100 µs の 1 万倍**である。
    黙って通さない。
    """
    frac = float(t_host) % 1.0
    if not (lo < frac < hi):
        raise TimebaseError(
            f"秒の真ん中で読めなかった（frac = {frac:.3f}、要求 {lo}〜{hi}）。"
            "**秒境界の近くで読むと整数秒が 1 秒ずれる。** やり直す")
    return frac


def sample_time_ns(anchor_utc_sec, anchor_stamp_beat, beat, i, cal_ns):
    """バッファの添字 i のサンプルの UTC を **整数 ns** で返す。

    - `anchor_utc_sec`      : 錨にした PPS の UTC 整数秒
    - `anchor_stamp_beat`   : その PPS が PL でスタンプされたビート（64 bit）
    - `beat`                : 取得の開始ビート（`t_start`）
    - `i`                   : 取得の中のサンプル番号
    - `cal_ns`              : `L_adc − D_pps`。**引く**

    **float の秒を返さない。** UTC 秒のところで float64 の分解能は 200 ns 級で、
    較正定数と同じ桁になる。整数 ns なら厳密。
    """
    d_beats = int(beat) - int(anchor_stamp_beat)
    n_samples = d_beats * SPW + int(i)
    return (int(anchor_utc_sec) * 10**9
            + samples_to_ns(n_samples)
            - int(round(cal_ns)))


def pps_is_consistent(d_count, d_stamp_beats):
    """錨からの PPS 数とビート差が整合しているか。

    同じ 10 MHz にロックしていれば **1 秒 = 153,600,000 ビートちょうど**なので、
    ここは**厳密に**一致する。ずれていれば PPS の取りこぼしか、原点の移動。
    **「だいたい合っている」を許さない** —— 許すと、欠落が誤差に見える。
    """
    return int(d_stamp_beats) == int(d_count) * BEATS_PER_SEC


# ------------------------------------------------------------------ 本体
class Timebase:
    """時刻を返す層。**答えられないときは例外を投げる。**"""

    def __init__(self, pps, cal=None):
        cal = CAL if cal is None else cal
        magic = pps.check_magic()          # 違えばここで落ちる
        if magic not in cal:
            raise TimebaseError(
                f"MAGIC 0x{magic:08x} の較正定数を持っていない。\n"
                "  **この層は知らないビットストリームに時刻を貼らない。**\n"
                "  L_adc はビットストリームの性質なので、RFDC の設定を変えたら\n"
                "  測り直して timebase.CAL に足すこと（手順は README）。")
        self.pps = pps
        self.magic = magic
        self.cal = dict(cal[magic])
        self._anchor = None

    # ---- 錨を打つ ----
    def anchor(self, settle=0.05):
        """PPS 1 発と UTC の整数秒を結ぶ。**秒の真ん中で読む。**"""
        now = time.time()
        time.sleep(((0.5 - (now % 1.0)) % 1.0) + settle)
        d = self.pps.snapshot()
        t = time.time()
        require_mid_second(t)
        self._require_healthy(d)
        self._anchor = dict(epoch=d["epoch"], count=d["count"],
                            stamp=d["stamp"], utc_sec=utc_second_of_last_pps(t))
        return dict(self._anchor)

    # ---- 時刻を返す ----
    def time_of_ns(self, beat, i, snap=None):
        """取得開始ビート `beat` の中の添字 `i` のサンプルの UTC（整数 ns）。

        **健全性を確かめてから答える。** 確かめられなければ例外。
        """
        if self._anchor is None:
            raise TimebaseError("錨が無い。先に anchor() を呼ぶ")
        if snap is None:
            # **例外の型でも契約を守る。**`pps.snapshot()` は EpochChanged
            # （このモジュールが知らない型）を投げうる。そのまま漏らすと、
            # 呼ぶ側の `except TimebaseError` をすり抜けて**別の扱いになる**。
            # 確かめられなかったのだから、答えない —— それが唯一の契約である。
            try:
                d = self.pps.snapshot()
            except TimebaseError:
                raise
            except Exception as e:                       # noqa: BLE001
                raise TimebaseError(
                    "スナップショットが取れないので時刻を答えられない: "
                    f"{type(e).__name__}: {e}") from e
        else:
            d = snap
        self._require_healthy(d)
        a = self._anchor
        if d["epoch"] != a["epoch"]:
            raise TimebaseError(
                f"時刻の原点が変わった（epoch {a['epoch']} → {d['epoch']}）。"
                "**錨より前のビート値は別の原点のもの。** anchor() を打ち直す")
        if not pps_is_consistent(d["count"] - a["count"], d["stamp"] - a["stamp"]):
            raise TimebaseError(
                "PPS 数とビート差が合わない"
                f"（{d['count'] - a['count']} 発 / {d['stamp'] - a['stamp']} ビート）。"
                "**PPS を取りこぼしたか、基準がずれている。**"
                " pps.py --watch で残差を見る")
        return sample_time_ns(a["utc_sec"], a["stamp"], beat, i,
                              self.cal["l_adc_minus_d_pps_ns"])

    def accuracy_ns(self):
        """**補正し残した量の合計。** データ製品のメタデータに入れる。"""
        c = self.cal
        return dict(
            applied_ns=c["l_adc_minus_d_pps_ns"],
            applied_unc_ns=c["unc_ns"],
            epoch_residual_ns=c["epoch_residual_ns"],
            tile_residual_ns=c["tile_residual_ns"],
            total_ns=(c["unc_ns"] + c["epoch_residual_ns"] + c["tile_residual_ns"]),
            source=c["source"],
        )

    # ---- 内部 ----
    def _require_healthy(self, d):
        f = d["flags"]
        if not (f & 0x40):          # FLAG_LOCKED
            raise TimebaseError("clk_wiz_adc がロックしていない。**時刻は無効。**")
        if not (f & 0x20):          # FLAG_ADCRSTN
            raise TimebaseError("ADC ドメインのリセットが解除されていない")
        if not (f & 0x01):          # FLAG_ALIVE
            raise TimebaseError(
                "1.5 秒以内に PPS が来ていない（alive = 0）。"
                "**ホールドオーバは基準の質で決まる。** 黙って外挿しない")
