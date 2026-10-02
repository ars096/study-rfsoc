#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj016 — 「このビートは UTC の何時か」に答える層（proj008 の timebase.py を fs = 4096 MSPS・DSP 256 MHz に置き直したもの）。

**この層の仕事は 2 つだけである。**

1. time_core のビート T と UTC を対応づける（PPS 1 発のスタンプと `time.time()` を結ぶ）
2. **答えられないときに答えない**（例外 `TimebaseError`。壊れた時刻は正常な時刻に見える）

## ビート

DSP のクロック 1 個 = 1 ビート = 16 サンプル = **3.90625 ns = 125/32 ns ちょうど**。**1 秒 = 256,000,000 ビートちょうど**
（fs = 4,096,000,000 が整数で、10 MHz の基準に乗っている限り）。ns への換算は整数で行う（`beats_to_ns`）。
**秒を float で持たない**（UTC の ns は 1.8e18 で、float64 の刻みは 256 ns。proj008 で踏んだ）。

## 錨（anchor）

PPS のスタンプは「同期器を抜けて縁を見たクロックの T」で、本当の縁より数ビート後（定数。`CAL` の pps_det_ns）。
錨を打つと time_core の ANCHORED を 1 にする。**time_core がリセットされると ANCHORED は 0 に戻り**、ダンプの健全性の [3] に出る。

## ダンプの時刻

ダンプの DUMP_T は「最初のフレームの最初のサンプルがコアに入ったビート」。ADC のサンプルの時刻に直すには、
ADC からコアの入口までの遅れ（RFDC ＋ ギアボックス、`CAL` の adc_to_core_ns）と、窓ではさらに PFB・DDC の遅れ
（`WIN_DELAY_BEATS[NS]`、sim で出した値）を**引く**。どちらも要求 100 µs に対して小さいが、黙って 0 にしない:
未較正のものは `accuracy()` に「未較正」と出す。
"""

import math
import time

BEATS_PER_SEC = 256_000_000
NS_NUM, NS_DEN = 125, 32          # 1 ビート = 125/32 ns（厳密）

# ---- 較正定数（ビットストリームの ID と対）----
#   pps_det_ns   : PPS の縁 → スタンプ（同期器 3 段 ＋ 入力の遅れ）。proj007 の COMP − TRIG = 58.6 ns（RC）は系統の差
#   adc_to_core_ns: ADC のサンプル → ギアボックスの出口（コアの入口）。proj007/008 の L_adc − D_pps = 213 ns は fs が違うので使えない
#   **どちらも T-2（1PPS を ADC にも入れる閉ループ）で測るまで未較正。** 上限の見当（bound_ns）だけ持つ
#   **T-2（閉ループ）で測れるのは差 M = adc_to_core − pps_det（＋ 2 本のケーブルの差）の 1 つだけ**なので、M を adc_to_core_ns に入れ、
#   pps_det_ns = 0 とする（式の上では引く量は M で同じ）。
CAL = {
    # proj017: adc_to_core_ns は ADC ごと（chans の添字 0..3 = ADC_A..D）。F-2 で 4 本とも測るまで None（未較正）。
    #   proj016 の ADC_A の 121.2 ns は別の Overlay・別の配置なので持ち込まない
    0x0017_7101: dict(pps_det_ns=0.0, adc_to_core_ns={0: None, 1: None, 2: None, 3: None}, bound_ns=50,
                      source="proj017: 未較正（F-2 で ADC ごとに測る）"),
    0x0016_7101: dict(pps_det_ns=0.0, adc_to_core_ns=121.2, bound_ns=50,
                      source="proj016 T-2（2026-10-02）: 全帯域の生サンプルで 1PPS の縁がコアに入った T − スタンプ = +31.04 ビート"
                             "（+121.2 ns、5 回で σ 0.2 ns、TRIG 系統）。1 エポック（Overlay 1 回）だけ。"
                             "上限 50 ns の内訳の見当: エポックごとのギアボックスの整数ビート（proj007 では Overlay ごとに数ビート動いた。未測）"
                             "＋ T-2 の配線の PPS と ADC のケーブルの長さの差（未測）"),
}
# 窓の PFB・DDC の遅れ（win_core の入口のビート → そのインパルスの |z|² の重心が wspec に入るまで、ビート）。NS → 値。
#   make sim-wdelay（2026-10-02、iverilog・k = 5・Δφ = 0）。線形位相なので重心 = 群遅延 ＋ 経路の遅れ。**RTL を変えたら出し直す**
WIN_DELAY_BEATS = {1: 57.56, 2: 87.21, 3: 136.06, 4: 229.02, 5: 408.09, 6: 748.27, 7: 1427.80, 8: 2781.10}


class TimebaseError(RuntimeError):
    """時刻を答えられない。**黙って古い値を返さないための例外。**"""


def beats_to_ns(n):
    """ビート数を ns へ（整数、最近接に丸める）。"""
    n = int(n)
    return (n * NS_NUM + NS_DEN // 2) // NS_DEN if n >= 0 else -((-n * NS_NUM + NS_DEN // 2) // NS_DEN)


def require_mid_second(t_host, lo=0.25, hi=0.75):
    """**秒の真ん中で読んだか。** 整数秒は floor(t) で決めるので、秒の境目の近くで読むと 1 秒ずれる。"""
    frac = float(t_host) % 1.0
    if not (lo < frac < hi):
        raise TimebaseError(f"秒の真ん中で読めなかった（frac = {frac:.3f}、要求 {lo}〜{hi}）。やり直す")
    return frac


def pps_is_consistent(d_count, d_stamp, tol=2):
    """錨からの PPS の数とスタンプの差が整合しているか。スタンプは 1 個ごとに ±1 ビートの量子化（溜まらない）なので ±2。"""
    return abs(int(d_stamp) - int(d_count) * BEATS_PER_SEC) <= tol


class TimeCore:
    """time_core_0 のレジスタ（src/time_core.v の冒頭の表）。mmio は pynq.MMIO か、read(off) / write(off, v) を持つもの。"""
    ID = 0x0017_7101
    CTRL_ARM, CTRL_CANCEL, CTRL_ASET, CTRL_ACLR, CTRL_NCLR = 1, 2, 8, 16, 256

    def __init__(self, mmio):
        self.m = mmio
        idv = self.rd(0x00)
        if idv != self.ID:
            raise TimebaseError(f"time_core の ID 0x{idv:08x}（期待 0x{self.ID:08x}）。載っている .bit が違う")
        if self.rd(0x04) != BEATS_PER_SEC:
            raise TimebaseError(f"time_core の 1 秒のビート数 {self.rd(0x04)}（期待 {BEATS_PER_SEC}）")

    def rd(self, off):
        return int(self.m.read(off)) & 0xFFFFFFFF

    def wr(self, off, v):
        self.m.write(off, int(v) & 0xFFFFFFFF)

    def t(self):
        lo = self.rd(0x18)
        return (self.rd(0x1C) << 32) | lo           # LO を読むと HI が固定される

    def status(self):
        s = self.rd(0x08)
        return dict(pending=bool(s & 1), late=bool(s & 2), far=bool(s & 4), fired=bool(s & 8), anchored=bool(s & 16),
                    trig_alive=bool(s & 32), comp_alive=bool(s & 64), pol=(s >> 7) & 1, src=(s >> 8) & 1)

    def pps(self, path="trig"):
        """最後のスタンプ・間隔・数（LO の読みで組を固定してから）。"""
        b = 0x20 if path == "trig" else 0x30
        lo = self.rd(b)
        return dict(stamp=(self.rd(b + 4) << 32) | lo, interval=self.rd(b + 8), count=self.rd(b + 12))

    def counters(self):
        g = self.rd(0x40)
        return dict(glitch_trig=g & 0xFFFF, glitch_comp=g >> 16, bad=self.rd(0x44), miss=self.rd(0x48), epoch=self.rd(0x4C))

    def configure(self, pol=0, src="trig", tol=1):
        self.wr(0x0C, (pol & 1) | ((1 if src == "comp" else 0) << 1) | ((tol & 0xFF) << 8))

    def arm(self, start_at):
        """START_AT でコアに RUN（・WRST）を配る。**コアの側を先に ARM しておく。**"""
        self.wr(0x10, start_at & 0xFFFFFFFF)
        self.wr(0x14, start_at >> 32)
        self.wr(0x08, self.CTRL_ARM)
        st = self.status()
        if st["late"]:
            raise TimebaseError(f"START_AT {start_at} が近すぎる（今 {self.t()}）")
        if st["far"]:
            raise TimebaseError(f"START_AT {start_at} が遠すぎる（≧ 2^40 ビート ≒ 72 分）")
        if not st["pending"] and not st["fired"]:
            raise TimebaseError("ARM が効いていない")

    def fired_at(self):
        lo = self.rd(0x50)
        return (self.rd(0x54) << 32) | lo


class Timebase:
    """時刻を返す層。**答えられないときは例外を投げる。**"""

    def __init__(self, tc, path="trig", cal=None):
        self.tc = tc
        cal = CAL if cal is None else cal
        if TimeCore.ID not in cal:
            raise TimebaseError(f"ID 0x{TimeCore.ID:08x} の較正定数を持っていない")
        self.cal = dict(cal[TimeCore.ID])
        self.path = path
        self._anchor = None

    def anchor(self, settle=0.05):
        """直近の PPS のスタンプと UTC の整数秒を結び、time_core の ANCHORED を 1 にする。**秒の真ん中で読む。**"""
        now = time.time()
        time.sleep(((0.5 - (now % 1.0)) % 1.0) + settle)
        st = self.tc.status()
        if not st[f"{self.path}_alive"]:
            raise TimebaseError("1.5 秒以内に PPS が来ていない。錨を打てない")
        ep0 = self.tc.counters()["epoch"]
        p = self.tc.pps(self.path)
        tnow = self.tc.t()
        t_host = time.time()
        require_mid_second(t_host)
        if not (0 < tnow - p["stamp"] < BEATS_PER_SEC):
            raise TimebaseError(f"最後の PPS が 1 秒より前（T − stamp = {tnow - p['stamp']}）")
        self.tc.wr(0x08, TimeCore.CTRL_ASET)
        if self.tc.counters()["epoch"] != ep0:
            raise TimebaseError("錨を打つ間に原点が変わった")
        self._anchor = dict(epoch=ep0, count=p["count"], stamp=p["stamp"], utc_sec=math.floor(t_host))
        return dict(self._anchor)

    def check(self):
        """今も錨が効いているか。効いていなければ例外。"""
        a = self._anchor
        if a is None:
            raise TimebaseError("錨が無い。先に anchor()")
        st = self.tc.status()
        c = self.tc.counters()
        if c["epoch"] != a["epoch"] or not st["anchored"]:
            raise TimebaseError(f"時刻の原点が変わった（epoch {a['epoch']} → {c['epoch']}、ANCHORED {st['anchored']}）。anchor() を打ち直す")
        if not st[f"{self.path}_alive"]:
            raise TimebaseError("PPS が来ていない（ホールドオーバは基準の質で決まる。黙って外挿しない）")
        p = self.tc.pps(self.path)
        if not pps_is_consistent(p["count"] - a["count"], p["stamp"] - a["stamp"]):
            raise TimebaseError(f"PPS の数とスタンプの差が合わない（{p['count'] - a['count']} 発 / {p['stamp'] - a['stamp']} ビート）。"
                                "PPS を取りこぼしたか、10 MHz の基準がずれている")
        return p

    def beat_utc_ns(self, beat):
        """ビート `beat`（time_core の T）がコアに入った時刻の UTC（整数 ns）。遅れの補正はしない（`sample_utc_ns`）。"""
        self.check()
        a = self._anchor
        return a["utc_sec"] * 10**9 + beats_to_ns(int(beat) - a["stamp"]) - int(round(self.cal["pps_det_ns"] or 0))

    def _a2c(self, adc):
        v = self.cal["adc_to_core_ns"]
        return v.get(adc) if isinstance(v, dict) else v

    def sample_utc_ns(self, beat, ns=None, adc=0):
        """コアに `beat` で入ったデータの、ADC のサンプルとしての UTC（整数 ns）。ns = 窓の NS（全帯域・TP は None）。
        adc = chans の添字（proj017 から adc_to_core_ns は ADC ごと）。"""
        t = self.beat_utc_ns(beat) - int(round(self._a2c(adc) or 0))
        if ns is not None and ns in WIN_DELAY_BEATS:
            t -= int(round(WIN_DELAY_BEATS[ns] * NS_NUM / NS_DEN))
        return t

    def accuracy(self, ns=None, adc=0):
        """補正し残した量。データ製品のメタデータに入れる。"""
        c = self.cal
        unc = []
        if c["pps_det_ns"] is None:
            unc.append("pps_det_ns")
        if self._a2c(adc) is None:
            unc.append(f"adc_to_core_ns[{adc}]")
        if ns is not None and ns not in WIN_DELAY_BEATS:
            unc.append(f"WIN_DELAY_BEATS[{ns}]")
        return dict(uncalibrated=unc, bound_ns=c["bound_ns"], source=c["source"])
