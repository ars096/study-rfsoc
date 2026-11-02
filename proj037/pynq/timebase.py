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

## 較正（ADR 0023）

ボードの較正ファイル（`timecal.py` が作る。鍵はボードの印）があればそれを、無ければ `CAL`（開発の値）を**暫定**として当てる。
どちらを当てたかは `cal_state`（"board" / "provisional"）と `accuracy()` の state に出す。
"""

import json
import math
import os
import time

BEATS_PER_SEC = 256_000_000
NS_NUM, NS_DEN = 125, 32          # 1 ビート = 125/32 ns（厳密）

# ---- 較正定数（ビットストリームの ID と対）----
#   pps_det_ns   : PPS の縁 → スタンプ（同期器 3 段 ＋ 入力の遅れ）。proj007 の COMP − TRIG = 58.6 ns（RC）は系統の差
#   adc_to_core_ns: ADC のサンプル → ギアボックスの出口（コアの入口）。proj007/008 の L_adc − D_pps = 213 ns は fs が違うので使えない
#   **ADR 0023（2026-10-29）: この表は開発の値（開発のボードの F-2）で、どの bit にも「暫定」として当てる。**
#   本番のボードは、設置の後に timecal.py で測ってボードに置く較正ファイル（TIME_CAL_PATH、リポジトリに戻さない）を使う
#   **どちらも T-2（1PPS を ADC にも入れる閉ループ）で測るまで未較正。** 上限の見当（bound_ns）だけ持つ
#   **T-2（閉ループ）で測れるのは差 M = adc_to_core − pps_det（＋ 2 本のケーブルの差）の 1 つだけ**なので、M を adc_to_core_ns に入れ、
#   pps_det_ns = 0 とする（式の上では引く量は M で同じ: サンプルの時刻 = 錨 ＋ (B − スタンプ) ＋ pps_det − adc_to_core）。
#   2026-10-21（study-rfsoc proj026）: 1PPS の入口に LPF を常設。**形 (b)**: LPF の遅れ（設置の性質）を pps_det_ns に、adc_to_core_ns は bit の値。
#   このとき式の符号が効く（pps_det を引いていた誤りを直した。test_cal_b.py が (a)・(b) で同じサンプルの時刻になることを見る）
CAL = {
    # YATSUGATAKE M5a（INTERFACE v2 の 5.2）: 鍵は (BIT_KIND, BIT_REV)。PROJ（0x5C）は記録だけで、較正には使わない。
    #   値は study-rfsoc の proj021 2-5（BIT_KIND 2・BIT_REV 3、PROJ 0x0021_0200）の F-2。
    #   IF_ID の無い過去の proj の bit（0x0021_7101・0x0020_7101・0x0017_7101・0x0016_7101 の鍵）の値は study-rfsoc に残る
    #   **RTL を変えて BIT_REV を上げたら、F-2 で測り直して新しい鍵で足す**（古い値は新しい REV に当たらない = 黙って使われない）
    (2, 3): dict(pps_det_ns=71.6, adc_to_core_ns={0: 141.6, 1: 141.7, 2: 141.3, 3: 141.3}, bound_ns=5,
                      source="形 (b)（2026-10-21、YATSUGATAKE M6 の塊 P・study-rfsoc proj026）: 1PPS・10 MHz の入口に LPF（Mini-Circuits BLP-10.7+）を常設。"
                             "配線 P（LPF は分配器の後の PPS Clk の枝）で F-2 を LPF ありで 2 回（ケーブルをまっすぐ / A↔D・B↔C、Overlay も 2 回）: "
                             "M = A 17.54・18.32 / B 17.49・18.39 / C 17.40・18.27 / D 17.41・18.29 ビート、平均 70.04・70.08・69.67・69.73 ns。"
                             "同じ日に LPF なしで 1 回: 36.26・36.23・36.16・36.21 ビート（141.3〜141.7 ns）→ LPF の遅れ 71.4〜71.7 ns、平均 71.6 ns を pps_det_ns に。"
                             "adc_to_core_ns = M（LPF あり）＋ 71.6。前の値（10-14、LPF なし、146.0〜147.5 ns）より 4.3〜6.1 ns 小さい（Overlay か配線 P の違いか分けられない）。"
                             "F-2 の 2 回の差（≒ 0.8 ビート）は PPS のスタンプの 1 ビートの量子化と見ている（未確認）ので bound_ns は 5 ns（±0.5 ビート ＋ LPF の分の ±2 ns）。"
                             "LPF を外す・替えるときは pps_det_ns だけを測り直す"),
    # YATSUGATAKE（SAM45-Wide の M5）: (1, 1) は study-rfsoc の proj023（BIT_KIND 1・BIT_REV 1、PROJ 0x0023_0100）の F-2。
    (1, 1): dict(pps_det_ns=71.5, adc_to_core_ns={0: 143.0, 1: 142.9, 2: 141.5, 3: 141.4}, bound_ns=5,
                 source="形 (b)（2026-10-21、study-rfsoc proj023 の F-2・proj026）: 1PPS・10 MHz の入口に LPF（BLP-10.7+）。"
                        "配線 P（LPF は分配器の後の PPS Clk の枝）で RAW の流れ（コア 0 の s 2）の生サンプルの 1PPS の縁を LPF ありで 2 回"
                        "（ケーブルをまっすぐ / A↔D・B↔C、Overlay も 2 回）: M = A 18.54・18.09 / B 18.48・18.09 / C 17.93・17.90 / D 17.94・17.86 ビート、"
                        "平均 71.5・71.4・70.0・69.9 ns。pps_det_ns は LPF の遅れ（proj026 で同じ日の LPF なしとの差 ≒ 71.5 ns）、"
                        "adc_to_core_ns = M（LPF あり）＋ 71.5。bound_ns は (2, 3) と同じ 5 ns（±0.5 ビート ＋ LPF の分の ±2 ns）"),
    # YATSUGATAKE（2G-4 の M5）: (3, 1) は study-rfsoc の proj031 rev 2（BIT_KIND 3・BIT_REV 1、PROJ 0x0031_0200）の R-5 の F-2。
    #   2G-1（BIT_KIND 11）・2G-2（BIT_KIND 10）は移植のときに、その bit の F-2 で足す（proj024・proj025 の値は別の配置なので持ち込まない）。
#   ADR 0023 の後は CAL に足さない（2G-1-Fast は proj033 の CAL[0x0033_0100]、2G-2 は proj034 の CAL[0x0034_0100] を持ち込まず、下の ADC_PATH で共通の道とした）
    (3, 1): dict(pps_det_ns=71.5, adc_to_core_ns={0: 140.9, 1: 141.1, 2: 141.6, 3: 141.9}, bound_ns=50,
                 source="proj031 rev 2 R-5 の F-2（2026-10-28、配線 P・1PPS の入口に LPF BLP-10.7+）: RAW の流れ（コア 0 の s 1、SRC で ADC を選ぶ）の生サンプルで "
                        "1PPS の縁がコアに入った T − スタンプを 4 ADC、ケーブルを A↔D・B↔C に入れ替えて 2 回（f2_31a・f2_31b）。M = A 69.4・B 69.6・C 70.1・D 70.4 ns。"
                        "(b): pps_det_ns = LPF の分 71.5、adc_to_core_ns = M ＋ 71.5（LPF を外したら pps_det_ns を 0 に）。bound_ns は移植元の 50 のまま"),
}
# ---- ADR 0023: ボードの時刻の較正ファイル（timecal.py が作る。リポジトリには戻さない）----
#   鍵は bit ではなくボード（board_id()）。1 本の bit（SAM45-Wide）で測った M を、ADC → コアの道が同じ bit すべてに当てる
#   （SAM45-Fine と Wide の差 ≦ 1.6 ns は Overlay ごとの共通のずれ ≒ 1 ビートより小さい）。
#   **ADC → コアの道（RFDC の設定・ギアボックス）を変えた bit は ADC_PATH に新しい番号で足す**（その bit には較正ファイルが当たらず、暫定になる）
TIME_CAL_PATH = "/etc/yatsugatake/time_cal.json"      # 環境変数 YATSUGATAKE_TIME_CAL で替えられる
ADC_PATH = {}                                           # (BIT_KIND, BIT_REV) → ADC → コアの道の版。無い bit は ADC_PATH_COMMON
ADC_PATH_COMMON = 1                                     # 共通コアの道（SAM45-Fine (2, 3)・SAM45-Wide (1, 1)）
#   2G-4 (3, 1) も共通の道（M5 で確かめた: gb_adc・gb_gate・raw_core・dstamp・adc_ev・time_core・axis_sel4 は hw/common の同じファイル、
#   RFDC のセルの組み立てと fs・spw_adc 12 → spw 16 が Wide と同じ、PWR 3 の F-2 の M は Wide M6 と ≦ 1.0 ns）
#   2G-1-Fast (11, 1) も共通の道（M5 で確かめた: 上の RTL は hw/common の同じファイル、RFDC のセルの組み立てと fs・spw_adc 12 → spw 16 が
#   Wide と同じで、ビルドの rfdc_params.rpt（869 行）が Wide の build-PE と同じ。proj033 の F-2 の M 68.5〜70.2 ns は Wide と ±1.4 ns）
#   2G-2 (10, 1) も共通の道（M5 で確かめた: 上の RTL は hw/common の同じファイル、RFDC のセルの組み立てと fs・spw_adc 12 → spw 16 が
#   Wide と同じで、ビルドの rfdc_params.rpt が Fine・Wide・2G-4・2G-1-Fast のビルドと 1 行も違わない。F-2 は回していない（ADR 0023））
CAL_PROVISIONAL_KEY = (1, 1)                            # CAL に無い bit（開発中）に暫定で当てる値
TIME_CAL_VERSION = 1


def time_cal_path():
    return os.environ.get("YATSUGATAKE_TIME_CAL") or TIME_CAL_PATH


def adc_path_of(key):
    return ADC_PATH.get(tuple(key), ADC_PATH_COMMON)


def board_id():
    """このボードの印（dict(id, src)）。時刻・TP の較正ファイルを別のボードで使わないため。
    eth0 の MAC（ボードの EEPROM の固定のアドレス、root でなくても読める）。読めなければ None。
    eFuse の DNA は PYNQ v3.1.1 では読めない（nvmem は EOPNOTSUPP、/dev/mem は Bus error）ので使わない（ADR 0026）"""
    try:
        with open("/sys/class/net/eth0/address") as f:
            mac = f.read().strip().lower()
        if set(mac) - set("0:"):                           # 全部 0 は印にならない
            return dict(id="mac:" + mac, src="eth0")
    except OSError:
        pass
    return None


def load_time_cal(path):
    """較正ファイルを読んで形を確かめる。戻り値は CAL の 1 項目と同じ形の dict（adc_to_core_ns の鍵は int）＋ board・adc_path・_file"""
    with open(path) as f:
        d = json.load(f)
    if d.get("version") != TIME_CAL_VERSION or d.get("kind") != "yatsugatake-time-cal":
        raise ValueError(f"{path}: 形が違う（version {TIME_CAL_VERSION}・kind yatsugatake-time-cal が要る）")
    a2c = {int(k): float(v) for k, v in d.get("adc_to_core_ns", {}).items()}
    if sorted(a2c) != [0, 1, 2, 3]:
        raise ValueError(f"{path}: adc_to_core_ns に ADC 0〜3 がそろっていない")
    if not (d.get("board") or {}).get("id"):
        raise ValueError(f"{path}: board.id が無い")
    return dict(pps_det_ns=float(d.get("pps_det_ns", 0.0)), adc_to_core_ns=a2c, bound_ns=float(d["bound_ns"]),
                adc_path=int(d["adc_path"]), board=d["board"], date=d.get("date"),
                source=f"ボードの較正ファイル {path}（{d.get('date')}、{d.get('note', '')}）", _file=path)


def select_cal(key, board_cal=None, this_board=None, cal=None):
    """bit の鍵とボードの較正から、当てる定数を選ぶ。戻り値 (定数, 状態, 説明)。状態は "board"（ボードの較正）か "provisional"（暫定）"""
    cal = CAL if cal is None else cal
    why = "ボードの較正ファイルが無い"
    if board_cal is not None:
        want = (board_cal.get("board") or {}).get("id")
        if this_board is None:
            why = "このボードの印が読めない（較正ファイルを照らせない）"
        elif want != this_board.get("id"):
            why = f"較正ファイルは別のボード（{want}）のもの。このボードは {this_board.get('id')}"
        elif board_cal["adc_path"] != adc_path_of(key):
            why = f"較正ファイルは ADC → コアの道 {board_cal['adc_path']} で測った。この bit {key} は道 {adc_path_of(key)}"
        else:
            return dict(board_cal), "board", "ok"
    base = cal[key] if key in cal else cal[CAL_PROVISIONAL_KEY]
    src = "" if key in cal else f"（bit {key} の値は無いので {CAL_PROVISIONAL_KEY} の値）"
    return dict(base, source="暫定: 開発の値" + src + "。" + base.get("source", "")), "provisional", why


# 窓の PFB・DDC の遅れ（win_core の入口のビート → そのインパルスの |z|² の重心が wspec に入るまで、ビート）。NS → 値。
#   make sim-wdelay（2026-10-02、iverilog・k = 5・Δφ = 0）。線形位相なので重心 = 群遅延 ＋ 経路の遅れ。**RTL を変えたら出し直す**
#   窓の PFB（T = 4）は wspec の中（z の後）なので入らない（ずれ 1.5·L は D_eff で足す）。PFB 入りの RTL でも NS 1〜8 とも同じ値
#   （proj021 2026-10-14、hw/bits/sam45-fine の RTL で 2026-10-23）
WIN_DELAY_BEATS = {1: 57.56, 2: 87.21, 3: 136.06, 4: 229.02, 5: 408.09, 6: 748.27, 7: 1427.80, 8: 2781.10}
# proj017: 窓の最初の z の遅れ F(NS)（WSTART = 窓の始まりのビートから、窓のフレーム 0 の最初の z が wspec に入るまで、ビート）と、
#   **幅の違う窓の区切りに残る一定の差 X(NS) = F(NS) − D(NS)**。窓の区切りの実効のサンプルの時刻は DUMP_T − D(NS) = WSTART ＋ F0·L ＋ X(NS)。
#   WSTART と F0·L を時刻の格子で揃えても、X(NS) の差（NS 1 と 6 で 625 ビート = 2.4 µs、NS 1 と 8 で 2548 ビート = 10 µs）は残る
#   （フレーム 0 は WSTART の後の最初の z で、最初の z は群遅延ぶん遅れて出るため）。2026-10-03 の F-4 で実測と 1 ビート以内で一致し、受け入れた。
#   **時刻の換算（sample_utc_ns）はもともと DUMP_T − D(NS) なので、この差は換算に含まれている**（区切りが µs だけ違う、という事実の記録）。
#   make sim-wdelay（2026-10-03、iverilog・k = 5・Δφ = 0）。**RTL を変えたら出し直す**
WIN_FIRST_Z_BEATS = {1: 72, 2: 122, 3: 211, 4: 384, 5: 722, 6: 1388, 7: 2710, 8: 5344}
WIN_BOUNDARY_BEATS = {1: 14.44, 2: 34.79, 3: 74.94, 4: 154.98, 5: 313.91, 6: 639.73, 7: 1282.20, 8: 2562.90}


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
    """time_core_0 のレジスタ（src/common/time_core.v の冒頭の表）。mmio は pynq.MMIO か、read(off) / write(off, v) を持つもの。"""
    ID = 0x0202_0302              # proj021 2-5: IF_ID（IF_VER 2・BIT_KIND 2 = SAM45-Fine・BIT_REV 3・CORE_KIND 2）。2-2d〜2-4 は 0x0202_0202、2-1〜2-2c は 0x0202_0102、旧 0x0021_7101
    IDS = (0x0202_0102, 0x0202_0202, 0x0202_0302,   # BIT_REV 1（2-1〜2-2c）・2（2-2d〜2-4）・3（2-5〜）。time_core の中身は同じ
           0x0201_0102,                              # SAM45-Wide（BIT_KIND 1・BIT_REV 1、study-rfsoc proj023）
           0x020B_0102,                              # 2G-1（BIT_KIND 11・BIT_REV 1、study-rfsoc proj024）
           0x020A_0102,                              # 2G-2（BIT_KIND 10・BIT_REV 1、study-rfsoc proj025）
           0x0203_0102,                              # 2G-4（BIT_KIND 3・BIT_REV 1、study-rfsoc proj027〜031）
           0x020C_0102)                              # 2G-1-Fine（BIT_KIND 12・BIT_REV 1、study-rfsoc proj037。CAL は未較正: 1PPS は開発中 ADC に入れない）
    PROJ = 0x0021_0200            # 0x5C。記録だけ（M5a から CAL の鍵は IF_ID の (BIT_KIND, BIT_REV)）
    CTRL_ARM, CTRL_CANCEL, CTRL_ASET, CTRL_ACLR, CTRL_NCLR = 1, 2, 8, 16, 256

    def __init__(self, mmio):
        self.m = mmio
        idv = self.rd(0x00)
        if idv >> 24 != 2 or idv & 0xFF != 2:
            raise TimebaseError(f"time_core の IF_ID 0x{idv:08x}（IF_VER 2・CORE_KIND 2 でない）。載っている .bit が違う")
        if idv not in self.IDS:
            raise TimebaseError(f"time_core の IF_ID 0x{idv:08x}（期待 0x{self.ID:08x}: BIT_KIND・BIT_REV が違う）")
        self.proj = self.rd(0x5C)
        self.bit_kind, self.bit_rev = (idv >> 16) & 0xFF, (idv >> 8) & 0xFF   # M5a: CAL の鍵
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

    def __init__(self, tc, path="trig", cal=None, time_cal="auto", log=None):
        """time_cal: "auto" = time_cal_path() にあれば読む・None = 読まない（暫定）・dict = 読んだもの（試験）"""
        self.tc = tc
        key = (tc.bit_kind, tc.bit_rev)                                 # M5a: (BIT_KIND, BIT_REV)
        if time_cal == "auto":
            time_cal, p = None, time_cal_path()
            if os.path.exists(p):
                try:
                    time_cal = load_time_cal(p)
                except (ValueError, KeyError, OSError) as e:
                    (log or print)(f"時刻の較正ファイルを読めない（暫定の値を使う）: {e}")
        self.board = board_id()                                         # ADR 0023・0025: 時刻と TP の較正ファイルの鍵
        self.cal, self.cal_state, self.cal_why = select_cal(key, time_cal, self.board, cal)   # ADR 0023
        if self.cal_state != "board":
            (log or print)(f"時刻の較正は暫定（開発の値）: {self.cal_why}")
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
        # スタンプは本当の縁より pps_det 後に打たれる → ビートの時刻は pps_det を**足す**（2026-10-21 まで引いていた。pps_det 0 の間は表に出なかった。test_cal_b.py）
        return a["utc_sec"] * 10**9 + beats_to_ns(int(beat) - a["stamp"]) + int(round(self.cal["pps_det_ns"] or 0))

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
        return dict(uncalibrated=unc, bound_ns=c["bound_ns"], source=c["source"], state=self.cal_state)
