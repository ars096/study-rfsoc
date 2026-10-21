#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj018 — 取得のプロセス。PL（proj017 の bit）を持ち、8 窓のダンプと 4 ADC の TP を読み落としなく読み、記録にして溜まりに置く。

通信のプロセス（specd.py）とは、溜まり（s45ring）と命令のパイプ（辞書を送って辞書を受ける）だけでつながる。
読み出しの環は proj017 `fine.py` の F-4 と同じ（SEQ を見て閉じたダンプを seqlock で読む・TP のリングを TP_WP まで読む）。
違うのは、**記録を Python のリストに溜めない**こと（GC と伸びるリストが 1 周の最大を延ばす疑い。README）。

遅れの対策（README の方針）: GC を止める（gc.freeze の後 gc.disable）・CPU 1 つに固定・可能なら SCHED_FIFO。

裏（backend）は 2 つ: HwBackend（PYNQ・proj017 の bit）と FakeBackend（PL なしで同じ間隔・同じ形の記録を作る。通信の試験用）。

proj021 手順 2-3a: HwBackend の読み口を **PL が書くリング**（s45_ring_0。plring.Ring）に替えた（`--read ring`、既定）。
  SPEC・TP・SNAP をレコードで受け、記録の形（s45proto v1）は今のまま。2-3a〜2-3d にあった `--read axi`（仮の読み窓を seqlock で）は
  2-2d で外した（bit に仮の読み窓が無い）

proj023 手順 4d: **SAM45-Wide（BIT_KIND 1）の裏 WideBackend**（`--wide`。bits.json の項目なら "kind": "wide"）。窓の代わりに
  8 本の SLICE の流れ（A0〜D1、コアごとに束ね B と流れごとの S0）。PL のダンプは BASE（10.24 ms = 1280 フレーム × 2048 ビート）で、
  specd が tint / BASE 個を束ねる（Bundler はそのまま。r = 2·G は H-3 の V2-f で見た式の定数）。SPEC は s45proto v2 の kind 2（SLICE）:
  ns の欄 = log2 B、中身は IF の昇順（流れの ch の逆順）、if_mhz = 送る 2047 番目の ch の IF（DDC と同じく IF = if_mhz ＋ (i − 2047)·df）。
  utc_ns = beat_utc(dump_t) − adc_to_core − (D_S ＋ 1.5·L)、L = 2048。**D_S = 0**（手順 4e の sim-wds: SLICE と RAW は同じサンプルに同じ T を付ける）。
  SNAP は RAW の流れ（コア 0 の s 2）で、SAM45-Fine と同じ HwBackend._snap_ring（proj023 4g）
"""
import collections
import gc
import os
import time
import traceback

import numpy as np

import s45cal
import s45proto as P
from tpjump import TpJump

BEATS_PER_SEC = 256_000_000
G_BEATS = 1 << 19                          # 時刻の格子 2.048 ms（BITS.md）
BASE_BEATS = 5 * G_BEATS                   # proj021 2-3b: 基本の単位 10.24 ms（INTERFACE 4.4・5.1。コアの BASE_BEATS と照らす）
TP_N = 512                                 # 1.024 ms
TP_BEATS = TP_N * 512
TP_FLUSH = 40                              # TP をまとめて 1 記録にする区切りの数（40 × 1.024 ms = 40.96 ms）
TPF_RUN, TPF_OVR = 2, 16
ADC_NAMES = ("ADC_A", "ADC_B", "ADC_C", "ADC_D")
NW = 2
NS_OF_BW = {256: 1, 128: 2, 64: 3, 32: 4, 16: 5, 8: 6}
FLAGS_OK_MASK = 0x7EF                      # 窓の FLAGS で異常に数えるもの（[4] FFT IP に待たされた は正常。fine.py と同じ）
VERSION = "proj023-0.1"                 # proj023: SAM45-Wide（SLICE の流れ、--wide）。proj019-0.2: SNAP・LMX の出力の強さ


def default_settings():
    wins = []
    for i in range(4):
        wins.append(dict(if_mhz=3000.0, ns=1, shift=9, bundle=1))     # 窓 0: 256 MHz
        wins.append(dict(if_mhz=3000.0, ns=6, shift=9, bundle=1))     # 窓 1: 8 MHz
    return dict(tint=0.04096, cfg=0, fmt="f32", wins=wins)


# ---- proj023: SAM45-Wide（SLICE の流れ）
W_FS_MHZ, W_NPHYS, W_FRAME = 4096.0, 32768, 2048
W_PL_NACC = BASE_BEATS // W_FRAME          # 1280
W_DS_BEATS = 0                             # D_S（RTL の遅れ）。proj023 4e の sim-wds で 0（SLICE の T = RAW の T。adc_to_core は RAW で測る）
W_LB = {1: 0, 2: 1, 4: 2}
W_SID_CTRL_ARMRUN, W_CTRL_ARMWRST, W_CTRL_DISARM = 1 << 2, 1 << 13, 1 << 3
W_FFT_N = 0x80


def w_s0_max(b):
    return W_NPHYS // b // 2 - P.NCH


def w_if_mhz(s0, i, b):
    """流れの ch i の IF（INTERFACE 2.1、ナイキストゾーン 2）"""
    n = W_NPHYS // b
    return W_FS_MHZ - (s0 + i + (b - 1) / (2 * b)) * W_FS_MHZ / n


def default_settings_wide():
    wins = []
    for i in range(4):
        for s in range(NW):
            wins.append(dict(b=1, s0=0 if s == 0 else 4096, shift=7))
    return dict(kind="wide", tint=0.04096, cfg=0, fmt="f32", wins=wins)


def check_wide(st):
    """SET の後の照合（Wide）。b・shift はコアで 1 つ（流れ 0・1 にそろえて持つ）"""
    for i in range(4):
        a, b_ = st["wins"][NW * i], st["wins"][NW * i + 1]
        if a["b"] != b_["b"] or a["shift"] != b_["shift"]:
            raise ValueError(f"{'ABCD'[i]}: b・shift はコアで 1 つ")
        if a["b"] not in W_LB:
            raise ValueError(f"{'ABCD'[i]}.b は 1・2・4")
        for s, ws in enumerate((a, b_)):
            if a["b"] == 4 and s == 1:
                continue                         # B 4 の流れ 1 は空
            if not 0 <= ws["s0"] <= w_s0_max(a["b"]):
                raise ValueError(f"{'ABCD'[i]}{s}.s0 {ws['s0']}（B {a['b']} では 0〜{w_s0_max(a['b'])}）")


def wide_cfgs(st):
    """START の設定（流れごと）。B 4 の流れ 1 は active False（レコードが来ない）"""
    n_sum = check_tint(st["tint"])
    out = []
    for j, ws in enumerate(st["wins"]):
        b = ws["b"]
        act = not (b == 4 and j % NW == 1)
        out.append(dict(kind="slice", b=b, lb=W_LB[b], s0=ws["s0"], shift=ws["shift"], active=act,
                        nacc=n_sum * W_PL_NACC, n_sum=n_sum, pl_nacc=W_PL_NACC, bundle=1, g=0, ns=W_LB[b],
                        if_mhz=float(w_if_mhz(ws["s0"], 2048, b)), df_hz=W_FS_MHZ * 1e6 * b / W_NPHYS))
    return out


def win_key(j):
    i, w = divmod(j, NW)
    return f"{'ABCD'[i]}{w}"


def frame_beats(ns):
    return 4096 << (ns - 1)


def nacc_of(tint, ns):
    L = frame_beats(ns)
    n = int(round(tint * BEATS_PER_SEC / L))
    if n < 1 or (n * L) % G_BEATS or abs(n * L - tint * BEATS_PER_SEC) > 0.5:
        raise ValueError(f"tint {tint} s は 2.048 ms の倍数でない（NS {ns} の L = {L} ビート）")
    return n


def check_tint(tint):
    """proj021 2-3b: tint は BASE（10.24 ms）の倍数（INTERFACE 5.1）。戻り値 n_sum"""
    b = tint * BEATS_PER_SEC
    n = int(round(b / BASE_BEATS))
    if n < 1 or abs(n * BASE_BEATS - b) > 0.5:
        raise ValueError(f"tint {tint} s は 10.24 ms の倍数でない（INTERFACE 5.1）")
    return n


class Bundler:
    """proj021 2-3b: 1 窓の束ね（INTERFACE 5.1）。PL のダンプ（BASE ごと）を n_sum 個ずつ u64 で足す。
    m = round(DUMP_T / BASE)・r = DUMP_T − m·BASE（1 回の RUN で一定 ±1 のはず）・束 jb = m // n_sum。
    束が揃う条件: n_sum 個の m が jb·n_sum から続いている・DUMP_N がどれも pl_nacc・DUMP_CFG が同じ。欠けた束は丸ごと捨てる"""

    def __init__(self, n_sum, pl_nacc):
        self.n_sum, self.pl_nacc = n_sum, pl_nacc
        self.r0 = None
        self.r_bad = 0
        self.dead = False             # r が動いた（以後この RUN では束ねない）
        self.jb0 = None
        self.drop = 0                 # 捨てた束
        self.drop_why = {}
        self.cur = None

    def _close(self, why):
        if self.cur is not None:
            self.drop += 1
            self.drop_why[why] = self.drop_why.get(why, 0) + 1
            out = (self.cur["jb"], why, len(self.cur["ms"]))
            self.cur = None
            return out
        return None

    def add(self, m, spec):
        """戻り値 (できた束 (meta, u64 の和) または None, 捨てた束 (jb, 理由, 持っていた数) または None)"""
        t = int(m["t"])
        mi = (t + BASE_BEATS // 2) // BASE_BEATS
        r = t - mi * BASE_BEATS
        if self.dead:
            return None, None
        if self.r0 is None:
            self.r0 = r
        elif abs(r - self.r0) > 1:
            self.r_bad += 1
            self.dead = True
            return None, self._close("r") or (mi // self.n_sum, "r", 0)     # 束の途中でなくても ERROR の EVENT を出す
        jb = mi // self.n_sum
        if self.jb0 is None:
            self.jb0 = jb
        dropped = None
        if self.cur is not None and self.cur["jb"] != jb:
            dropped = self._close("欠け")
        bad = int(m["n"]) != self.pl_nacc
        if self.cur is None:
            self.cur = dict(jb=jb, ms=[mi], acc=np.array(spec, dtype=np.uint64), m=dict(m), sat=int(m["sat"]),
                            flags=int(m["flags"]), h=int(m["h"]), n=int(m["n"]), bad="N" if bad else None)
        else:
            c = self.cur
            if mi != c["ms"][-1] + 1:
                c["bad"] = c["bad"] or "順"
            if int(m["cfg"]) != int(c["m"]["cfg"]):
                c["bad"] = c["bad"] or "CFG"
            if bad:
                c["bad"] = c["bad"] or "N"
            c["ms"].append(mi)
            c["acc"] += spec
            c["sat"] += int(m["sat"]); c["flags"] |= int(m["flags"]); c["h"] |= int(m["h"]); c["n"] += int(m["n"])
        c = self.cur
        if len(c["ms"]) < self.n_sum:
            return None, dropped
        if c["bad"] or c["ms"][0] != jb * self.n_sum:
            d2 = self._close(c["bad"] or "頭")
            return None, dropped or d2
        mm = dict(c["m"])
        mm.update(k=jb - self.jb0, n=c["n"], sat=c["sat"], flags=c["flags"], h=c["h"])
        self.cur = None
        return (mm, c["acc"]), dropped

    def stop(self):
        return self._close("STOP")


def g_of(ns):
    return 5 if ns >= 7 else 4


# ================================================================ 時刻（timebase の式を、確かめは 1 秒に 1 回に分けて）
def _b2ns(d):
    """timebase.beats_to_ns と同じ（最近接に丸める。負は対称）。numpy の配列も可"""
    d = np.asarray(d, np.int64)
    return np.where(d >= 0, (d * 125 + 16) // 32, -((-d * 125 + 16) // 32))


class Clock:
    """timebase.Timebase.sample_utc_ns と同じ式。check()（PPS の照合、MMIO を数語読む）は poll で 1 秒に 1 回だけ打ち、
    落ちたら ok = False（記録に H_NOTIME、utc_ns = 0）。錨を打ち直すまで戻らない"""

    def __init__(self, tb, win_delay):
        self.tb, self.wd = tb, win_delay
        self.ok = tb is not None and tb._anchor is not None
        self.err = None
        self.t_next = 0.0

    def poll(self):
        if self.tb is None or not self.ok or time.time() < self.t_next:
            return
        self.t_next = time.time() + 1.0
        try:
            self.tb.check()
        except Exception as e:                  # TimebaseError
            self.ok, self.err = False, str(e)

    def utc_ns(self, beat, ns=None, adc=0):
        if not self.ok:
            return 0
        a, c = self.tb._anchor, self.tb.cal
        t = a["utc_sec"] * 10**9 + int(_b2ns(int(beat) - a["stamp"])) + int(round(c["pps_det_ns"] or 0))   # pps_det は足す（2026-10-21、test_cal_b.py）
        v = c["adc_to_core_ns"]
        t -= int(round((v.get(adc) if isinstance(v, dict) else v) or 0))
        if ns is not None and ns in self.wd:
            t -= int(round(self.wd[ns] * 125 / 32))
        return t

    def utc_ns_arr(self, beats, adc=0):
        """utc_ns(beat, None, adc) を配列で（TP の区切り）"""
        a, c = self.tb._anchor, self.tb.cal
        v = c["adc_to_core_ns"]
        off = a["utc_sec"] * 10**9 + int(round(c["pps_det_ns"] or 0)) - int(round((v.get(adc) if isinstance(v, dict) else v) or 0))
        return off + _b2ns(np.asarray(beats, np.int64) - a["stamp"])

    def beat_of_utc_ns(self, utc_ns):
        a = self.tb._anchor
        p = int(round(self.tb.cal["pps_det_ns"] or 0))      # beat_utc_ns の逆
        return a["stamp"] + ((int(utc_ns) - a["utc_sec"] * 10**9 - p) * 32) // 125


# ================================================================ TP のリングの読み手（記録を溜めず、TP_FLUSH ごとに渡す）
def make_tp_reader(S):
    class TpStream(S.TpReader):
        def __init__(self, sp, tp_n, run_f0):
            super().__init__(sp, tp_n, run_f0)
            self.buf = np.zeros(4 * S.TP_DEPTH, P.TP_E)
            self.n = 0
            self.n_ovr = 0
            self.total = 0
            self.overflow = 0         # 手元の箱（4 × 512 個）が溢れて捨てた区切り（flush が 2 秒来ない。0 のはず）
            self.rec_lost = 0         # proj021 2-3a: 落ちた TP のレコードの数（個の番号の飛びを K で割って切り上げた見積り）

        def feed(self, seq, n, pay, k):
            """proj021 2-3a: TP のレコード（type 2）の個を受ける。seq = 最初の個の番号（TP_WP の数え）、pay = u64 × 2·n…
            個 = {和 u64, [31:0] F0 の下位・[55:32] フレーム数・[63:56] FLAGS}（AXI4-Lite の TP のリングと同じ 16 バイト）"""
            if self.wp is not None:
                g = (seq - self.wp) & 0xFFFFFFFF
                if g >= 1 << 31:
                    return                    # 古い（前の RUN の残り）
                if g and self.started:
                    self.lost += g
                    self.rec_lost += -(-g // k)
            self.wp = (seq + n) & 0xFFFFFFFF
            v = pay[:2 * n].tolist()                  # numpy の要素を 1 個ずつ int にするより速い
            for i in range(n):
                x = v[2 * i + 1]
                self._take(v[2 * i], x & 0xFFFFFFFF, x >> 56, (x >> 32) & 0xFFFFFF)

        def _take(self, tsum, f0lo, fl, nfr):
            if not self.started:
                if (fl & TPF_RUN) and f0lo == (self.run_f0 & 0xFFFFFFFF):
                    self.started = True
                    f0 = self.run_f0
                else:
                    self.pre += 1
                    return
            else:
                exp = self.last_f0 + self.last_nfr
                f0 = exp + ((f0lo - (exp & 0xFFFFFFFF) + (1 << 31)) % (1 << 32)) - (1 << 31)
                if f0 != exp:
                    self.bad_seq += 1
                if fl & ~TPF_OVR:
                    self.bad_flag += 1
            if fl & TPF_OVR:
                self.n_ovr += 1
            if nfr != self.tp_n:
                self.bad_nfr += 1
            self.last_f0, self.last_nfr = f0, nfr
            if self.n < len(self.buf):
                e = self.buf[self.n]
                e["t_beat"] = f0            # フレームの番号。flush でビートに直す
                e["sum"] = tsum; e["nfr"] = nfr; e["flags"] = fl
                self.n += 1
            else:
                self.overflow += 1
            self.total += 1
    return TpStream


# ================================================================ 実機
REC_ALL, REC_SNAP = 1, 4
TP_REC_CTRL, TP_REC_K = 0x11C, 10           # proj021 2-2b: TP のレコード（[0] EN・[12:8] K）。TP_FLUSH（40 個）は手元で束ねる
TYPE_SPEC, TYPE_TP, TYPE_SNAP = 1, 2, 4


def rec_meta(hw):
    """レコードの頭 w1..w6（INTERFACE 4.4）→ 今の meta と同じ鍵"""
    w = [int(x) for x in hw]
    return dict(seq=w[1] & 0xFFFFFFFF, k=w[1] >> 32, f0=w[2] & ((1 << 48) - 1), t=w[3], h=(w[4] >> 48) & 0xFFFF,
                n=w[5] & 0xFFFFFFFF, sat=w[5] >> 32, cfg=w[6] & 0xFFFFFFFF, flags=w[6] >> 32)


class HwBackend:
    def __init__(self, opts, log):
        self.o, self.log = opts, log
        self.running = False
        if getattr(opts, "read", "ring") != "ring":
            raise RuntimeError("proj021 2-2d: 読み口はリングだけ（--read axi の道は外した。仮の読み窓の無い bit）")
        self.use_ring = True
        self.ring = None
        self.ring_crc = 0
        self.stall_at = getattr(opts, "posctl_ring_stall", 0.0)
        self.n_pump = 0

    def open(self):
        import spectrometer as S
        import timetest as T
        import window as W
        import timebase as TB
        self.S, self.T, self.W, self.TB = S, T, W, TB
        from pynq import Overlay
        import xrfdc                               # Overlay() より前に import する（VERSIONS.md）
        S.setup_clocks(self.o.clkin, self.o.ref)
        self.lmx = None
        chdiv = getattr(self.o, "lmx_chdiv", 16)
        pwr = getattr(self.o, "lmx_pwr", None)
        if chdiv != 16 or pwr is not None:         # proj019: LMX の VCO・出力の強さを動かす（櫛の出どころの試験）。出力 491.52 は同じ
            import extref
            self.lmx = extref.rewrite_lmx(chdiv, pwr)
        self.ol = Overlay(self.o.bitfile)
        if not isinstance(self.ol.rfdc, xrfdc.RFdc):
            raise RuntimeError("RFDC に xrfdc のドライバが当たっていない")
        S.check_tiles(self.ol.rfdc, 2)
        time.sleep(self.o.settle)
        ns_list = [1] * (4 * NW)
        self.tc, self.wms, self.wins, self.full = T.open_all(self.ol, ns_list)   # 照合は自己記述（s45core.discover。open_all の中）
        import s45core as SC
        self.cores, _ = SC.discover(self.ol)
        for wm in self.wms:
            prm = int(wm.read(W.A_BASE + S.R_TP_PARAM)) & 0xFFFFFFFF
            if prm != S.TP_PARAM_EXPECT:
                raise RuntimeError(f"TP_PARAM {prm:08x}（期待 {S.TP_PARAM_EXPECT:08x}）")
        self.tc.configure(src=self.o.path, tol=1)
        self.tb = TB.Timebase(self.tc, path=self.o.path)
        self.TpStream = make_tp_reader(S)
        c0 = self.cores[0]
        self.ids = dict(win=f"{self.wins[0].rd(W.R_ID):08x}", adc=f"{c0.if_id:08x}", time=f"{self.tc.rd(0x00):08x}",   # proj021 2-2d: 載っている time_core の IF_ID（BIT_REV 1 / 2）
                        proj=f"{c0.proj:08x}",
                        lmx_vco=f"{self.lmx['vco_mhz']:.2f}" if self.lmx else "7864.32",
                        lmx_pwr=str(self.lmx.get("outa_pwr", 31)) if self.lmx else "31")
        self.clock = Clock(None, TB.WIN_DELAY_BEATS)
        if self.use_ring:
            self._open_ring()
        self.ids["read"] = "ring" if self.use_ring else "axi"
        self.bit_kind = (self.cores[0].if_id >> 16) & 0xFF        # proj021 2-3c: v2 の SPEC の bit_kind
        self.anchor()

    # ---- proj021 2-3a: リング ----
    def _open_ring(self):
        import plring as PR
        import s45core as SC
        self.SC = SC
        bad = [c.name for c in self.cores if (c.caps & 7) != 7]
        if bad:
            raise RuntimeError(f"CAPS の [0]〜[2]（SPEC・TP・SNAP のレコード）が無いコア {bad}。2-2c 以降の .bit を")
        rip = getattr(self.ol, "s45_ring_0", None)
        if rip is None:
            raise RuntimeError("ol.s45_ring_0 が無い（2-2a 以降の .bit ではない）")
        self.ring = PR.Ring(rip.mmio, getattr(self.o, "ring_mib", 32) << 20)
        self.ring.enable(True)
        self.jmap = {(self.cores[c.adc].adc, c.widx): j for j, c in enumerate(self.wins)}   # レコードの core = CORE_PORT の ADC
        self.amap = {c.adc: i for i, c in enumerate(self.cores)}
        self.q = [collections.deque() for _ in self.wins]
        fs = SC.snap_stream(self.cores)            # proj021 2-5: SNAP は RAW の流れ（2-4 までは FULL）
        self.fkey = (fs.core.adc, fs.s)
        self.log(f"リング: BASE {self.ring.base:#x} / SIZE {self.ring.size}（範囲の invalidate {'あり' if self.ring.bo_sync else 'なし'}）")

    def _rec_off(self):
        """REC_CTRL・TP_REC_CTRL を 0（窓・FULL・4 ADC）"""
        SC = self.SC
        for c in self.wins:
            c.wr(SC.S_REC_CTRL, 0)
        self.full.wr(SC.S_REC_CTRL, 0)
        for wm in self.wms:
            wm.write(TP_REC_CTRL, TP_REC_K << 8)

    def _drain(self):
        self.ring.read()
        for d in self.q:
            d.clear()

    def pump(self):
        """1 周の頭に 1 回: リングを [R, W) まで読み、SPEC は窓ごとの列へ、TP は TpStream へ"""
        if not self.use_ring:
            return 0
        self.n_pump += 1
        if self.stall_at and self.n_pump == 100:
            self.log(f"陽性対照: リングを {self.stall_at} 秒読まない")
            time.sleep(self.stall_at)
        t0 = time.perf_counter()
        recs = self.ring.read()
        t1 = time.perf_counter()
        for core, s, seq, hw, pay, crc_ok, tail_ok in recs:
            if not (crc_ok and tail_ok):
                self.ring_crc += 1
                continue
            ty = int(hw[0]) >> 40 & 0xFF
            if ty == TYPE_SPEC:
                j = self.jmap.get((core, s))
                if j is not None:
                    self.q[j].append((seq, hw, pay))
            elif ty == TYPE_TP and s == 0xFF and core in self.amap and self.running:   # 2-2d: FULL の TP（s = FULL の流れ）は使わない
                self.tps[self.amap[core]].feed(seq, int(hw[5]) & 0xFFFFFFFF, pay, TP_REC_K)
        self.last_pump = (t1 - t0, time.perf_counter() - t1)      # 遅い周の内訳（リングの読み・振り分け）
        return len(recs)

    def ring_stat(self):
        if self.ring is None:
            return None
        r = self.ring.regs()
        return dict(w=r["w"], r=r["r"], drop=r["drop"], rec=r["rec"], peak=r["peak"], err=r["err"], crc=self.ring_crc,
                    tp_rec_lost=sum(t.rec_lost for t in getattr(self, "tps", [])))

    def close(self):
        if self.ring is None:
            return
        try:
            self._rec_off()
        finally:
            self.ring.close(())
            self.ring = None

    def anchor(self):
        try:
            a = self.tb.anchor()
            self.clock = Clock(self.tb, self.TB.WIN_DELAY_BEATS)
            self.log(f"錨: UTC {a['utc_sec']} 秒 = スタンプ {a['stamp']}（EPOCH {a['epoch']}）")
            return True, None
        except Exception as e:
            self.clock = Clock(None, self.TB.WIN_DELAY_BEATS)
            self.log(f"錨を打てない: {e}")
            return False, str(e)

    def now_beat(self):
        return self.tc.t()

    def grid_after(self, beat):
        """proj021 2-3b: START_AT（WRST・RUN・TP_ARM）は T の tint の倍数（INTERFACE 5.1。tint は BASE = 5G の倍数なので G の格子にも乗る）"""
        q = getattr(self, "tint_beats", G_BEATS)
        return -(-int(beat) // q) * q

    def start(self, st, at_beat, force):
        """WRST（格子の点で一斉）→ N_ACC・SHIFT・TP_N → 窓と TP 4 本を格子の START_AT で同時に ARM。戻り値 START_AT"""
        T, W = self.T, self.W
        if self.clock.ok:
            try:
                self.tb.check()
            except Exception as e:                 # IDLE の間は Clock.poll が回らないので、ここで初めて分かることがある
                self.clock.ok, self.clock.err = False, str(e)
        if not self.clock.ok and not force:
            raise RuntimeError("時刻を答えられない（錨が無い・PPS が来ていない）。ANCHOR か force=1")
        self.disarm()
        self.tint_beats = check_tint(st["tint"]) * BASE_BEATS
        bb = {c.base_beats for c in self.cores}
        if bb != {BASE_BEATS}:
            raise RuntimeError(f"コアの BASE_BEATS {bb}（{BASE_BEATS} を期待）")
        self.cfgs = []
        for j, c in enumerate(self.wins):
            ws = st["wins"][j]
            ns = ws["ns"]
            _, k, dphi, ns_, if_act = W.window_params(ws["if_mhz"], 512.0 / (1 << ns))
            c.ns, c.L = ns, frame_beats(ns)
            c.wr(W.R_WK, k); c.wr(W.R_WDPHI, dphi); c.wr(W.R_WNS, ns_)
            c.wr(T.R_CFG, st["cfg"])
            c.wr(W.R_CTRL, T.CTRL_ARM_WRST)
            c.want = (k, dphi, ns_)
            bund = int(ws.get("bundle", 1))
            self.cfgs.append(dict(if_mhz=if_act, ns=ns, shift=ws["shift"], nacc=nacc_of(st["tint"], ns), g=g_of(ns),
                                  bundle=bund, n_sum=check_tint(st["tint"]) if bund else 1,
                                  pl_nacc=BASE_BEATS // c.L if bund else nacc_of(st["tint"], ns)))
        sa_w = self.grid_after(self.now_beat() + BEATS_PER_SEC // 2)
        T.arm_tc(self.tc, self.wins, self.full, self.wms, sa_w)
        self._wait_fired(5.0)
        time.sleep(0.01)
        ws_ = []
        for c in self.wins:
            while c.rd(W.R_CTRL) & (1 << 4):
                time.sleep(0.001)
            cur = c.rd(T.R_WCUR)
            k, dphi, ns_ = c.want
            if (cur & 31) != k or ((cur >> 8) & 15) != ns_ or c.rd(W.R_WCUR_DPHI) != dphi:
                raise RuntimeError(f"{c.name}: WRST の後の WCUR {cur:#x} が書いた値と違う")
            ws_.append(c.rd(T.R_WSTART))
        for i in range(4):
            wi = [ws_[j] for j in range(len(self.wins)) if self.wins[j].adc == i]
            if len(set(wi)) != 1:
                raise RuntimeError(f"{ADC_NAMES[i]}: 窓の WSTART が揃っていない {wi}")
        for c, cf in zip(self.wins, self.cfgs):
            c.wr(W.R_NACC, cf["pl_nacc"]); c.wr(W.R_NDUMP, 0); c.wr(W.R_SHIFT, cf["shift"])   # proj021 2-3b: 束ねる窓は BASE
        for wm in self.wms:
            wm.write(W.A_BASE + T.RA_TP_N, TP_N)
        if self.use_ring:                          # proj021 2-3a: 窓は ALL・TP は K 個 / レコード。前の残りは読み捨てる
            for c in self.wins:
                c.wr(self.SC.S_REC_CTRL, REC_ALL)
            for wm in self.wms:
                wm.write(TP_REC_CTRL, (TP_REC_K << 8) | 1)
            self._drain()
        sa = self.grid_after(max(at_beat or 0, self.now_beat() + BEATS_PER_SEC // 2))
        T.arm_all(self.tc, self.wins, self.full, self.wms, sa, tp=True, with_full=False)
        self.sa = sa
        self.armed = True
        return sa

    def _wait_fired(self, timeout):
        t_e = time.time() + timeout
        while not self.tc.status()["fired"]:
            if time.time() > t_e:
                raise RuntimeError("予約の発火が来ない")
            time.sleep(0.01)

    def fired(self):
        return bool(self.tc.status()["fired"])

    def begin(self):
        """発火の後: RUN_T の照合・SEQ と TP の読み手の起点・錨の組（TANCH）"""
        S, T, W = self.S, self.T, self.W
        runts = [c.rd64(c.r["run_t"]) for c in self.wins] + [T.tp_run_t(wm) for wm in self.wms]
        bad = [i for i, t in enumerate(runts) if t != self.sa + 1]
        for c, cf in zip(self.wins, self.cfgs):
            rs = c.rd(T.R_RUN_SHIFT)
            if rs != cf["shift"]:
                raise RuntimeError(f"{c.name}: RUN_SHIFT {rs}（書いた値 {cf['shift']}）")
        self.seq = [c.rd(W.R_SEQ) for c in self.wins]
        self.tps = []
        self.anch = []
        for wm in self.wms:
            tp = _WinTp(wm, W.A_BASE)
            tf0 = tp.rd(S.R_TP_F0_LO) | (tp.rd(S.R_TP_F0_HI) << 32)
            self.tps.append(self.TpStream(tp, TP_N, tf0))
            self.anch.append(self._tanch(wm))
        self.gap0 = [int(wm.read(W.A_BASE + T.RA_GAP)) for wm in self.wms]
        self.running = True
        return dict(run_t_bad=bad)

    def _tanch(self, wm, timeout=0.5):
        W, T = self.W, self.T
        wm.write(W.A_BASE + T.RA_TP_CTRL, T.TP_ANCH)
        t_e = time.time() + timeout
        while not (int(wm.read(W.A_BASE + T.RA_ANCH_ST)) & 2):
            if time.time() > t_e:
                raise RuntimeError("TANCH が残らない")
            time.sleep(0.001)
        af = int(wm.read(W.A_BASE + T.RA_ANCH_F)) | (int(wm.read(W.A_BASE + T.RA_ANCH_F + 4)) << 32)
        at = int(wm.read(W.A_BASE + T.RA_ANCH_T)) | (int(wm.read(W.A_BASE + T.RA_ANCH_T + 4)) << 32)
        return af, at

    def poll_win(self, j):
        """窓 j に閉じたダンプがあれば (メタ, uint64 の 4096 個の FFT の順, 読み落とした数) を返す。無ければ None"""
        W = self.W
        if self.use_ring:
            q = self.q[j]
            while q:
                seq, hw, pay = q.popleft()
                d = (seq - self.seq[j]) & 0xFFFFFFFF
                if d == 0 or d >= 1 << 31:
                    continue                       # 前の RUN の残り・同じ SEQ
                self.seq[j] = seq
                return rec_meta(hw), pay, d - 1
            return None
        raise RuntimeError("proj021 2-2d: 仮の読み窓の道は外した")

    def poll_tp(self, i):
        if not self.use_ring:
            self.tps[i].poll()                     # ring: pump が個を渡している
        return self.tps[i]

    def tp_time(self, i, f):
        af, at = self.anch[i]
        return at + (f - af) * 512

    def snap(self, adc, n, nacc, timeout=5.0):
        """全帯域コア（spec_core_0）を ADC adc につないで N_ACC = nacc・N_DUMP = n で走らせ、ダンプごとの最初のフレームの
        生サンプル 8192 個を読む（IDLE のときだけ。窓・TP の RUN には触らない: specd は全帯域コアを RUN に入れていない）。
        戻り値 [(meta, int16 の 8192 個)]。SNAP_F ≠ DUMP_F0（別のフレームを読んだ）・読む間に閉じたものは読み直す"""
        return self._snap_ring(adc, n, nacc, timeout)     # proj021 2-2d: 仮の読み窓の道は外した

    def _snap_ring(self, adc, n, nacc, timeout):
        """proj021 2-3a: FULL の流れを REC_CTRL = ALL | SNAP・N_DUMP = n で走らせ、SNAP のレコード（type 4）を n 個集める。
        2-5: RAW の流れ（SNAP のレコードだけを出す。SNAP の bit は意味が無いが害も無い）でも同じ手順。
        上書きの見張りは PL（2-2c の snap_ok）。ここは SEQ の飛び・DUMP_K・CRC を見る"""
        S, T, SC = self.S, self.T, self.SC
        full = self.full
        T.select_full(self.wms, full, adc)
        full.wr(SC.S_REC_CTRL, 0)
        self._drain()
        full.wr(S.R_NACC, nacc)
        full.wr(S.R_NDUMP, n)
        full.wr(SC.S_REC_CTRL, REC_ALL | REC_SNAP)
        full.wr(S.R_CTRL, S.CTRL_CLR | S.CTRL_RUN)
        out = []
        last = None
        t_end = time.time() + timeout + n * nacc * 2e-6
        try:
            while len(out) < n:
                if time.time() > t_end:
                    raise RuntimeError(f"SNAP: {len(out)}/{n} 個で時間切れ（REC_LATE {full.rd(SC.S_REC_LATE)}・リングの DROP {self.ring.regs()['drop']}）")
                for core, s, seq, hw, pay, crc_ok, tail_ok in self.ring.read():
                    if (core, s) != self.fkey or (int(hw[0]) >> 40 & 0xFF) != TYPE_SNAP:
                        continue
                    if not (crc_ok and tail_ok):
                        raise RuntimeError(f"SNAP: CRC・尾の不一致（SEQ {seq}）")
                    m = rec_meta(hw)
                    if last is not None and seq != (last + 1) & 0xFFFFFFFF:
                        raise RuntimeError(f"SNAP: ダンプを読み落とした（SEQ {last} → {seq}。every を長く）")
                    if m["k"] != len(out):
                        raise RuntimeError(f"SNAP: DUMP_K {m['k']}（{len(out)} であるべき）")
                    last = seq
                    out.append((m, pay.view(np.int16).copy()))
                time.sleep(0.0005)
        finally:
            full.wr(S.R_CTRL, S.CTRL_STOP)
            full.wr(SC.S_REC_CTRL, 0)
        return out

    def disarm(self):
        T = self.T
        T.disarm_all(self.wins, self.full, self.wms)

    def stop(self):
        W = self.W
        if not self.running:
            # ARMED のまま止める: コアの予約は time_core の取り消しでは消えない（timetest.disarm_all の注意）。両方消し、TANCH は比べない
            self.disarm()
            self.tc.wr(0x08, self.TB.TimeCore.CTRL_CANCEL)
            if self.use_ring:
                self._rec_off()
            return []
        for c in self.wins:
            c.wr(W.R_CTRL, W.CTRL_STOP)
        if self.use_ring:
            self.pump()                            # 止める前に閉じたぶんを TP に渡す（SPEC の残りは次の START で捨てる）
            self._rec_off()
        self.running = False
        out = []
        for i, wm in enumerate(self.wms):
            try:
                af1, at1 = self._tanch(wm)
                af, at = self.anch[i]
                gap1 = int(wm.read(self.W.A_BASE + self.T.RA_GAP))
                out.append(dict(adc=i, anch_dev=(at1 - at) - (af1 - af) * 512, gap=gap1 - self.gap0[i]))
            except Exception as e:
                out.append(dict(adc=i, err=str(e)))
        return out


class _WinTp:
    def __init__(self, mmio, base):
        self.m, self.b = mmio, base

    def rd(self, a):
        return int(self.m.read(self.b + a)) & 0xFFFFFFFF

    def block(self, base, nwords):
        i0 = (self.b + base) // 4
        return np.array(self.m.array[i0:i0 + nwords], dtype=np.uint32)


# ================================================================ 偽物（PL なし。同じ間隔・同じ形）
class FakeBackend:
    """T = (time.time() − t0)·256e6 のビート。ダンプは tint ごとに 8 窓、TP は 1.024 ms ごと。中身は乱数（k で変わる）"""

    def __init__(self, opts, log):
        self.o, self.log = opts, log
        self.running = False

    def open(self):
        import types
        self.t0 = time.time() - 100.0                # 偽の時刻: T = (time − t0)·256e6、UTC = t0 + T / 256e6
        self.ids = dict(win="fake", adc="fake", time="fake")
        rng = np.random.default_rng(1)
        self.base = rng.integers(1 << 40, 1 << 41, (4 * NW, P.NCH), dtype=np.uint64)
        tb = types.SimpleNamespace(cal=dict(pps_det_ns=0, adc_to_core_ns=0), check=lambda: None,
                                   _anchor=dict(utc_sec=int(self.t0), stamp=-int(round((self.t0 - int(self.t0)) * BEATS_PER_SEC))))
        self.clock = Clock(tb, {})
        if self.o.fake_notime:                       # 1PPS が無い（錨が打てない）実機の振る舞いを真似る
            self.clock = Clock(None, {})
            self.clock.err = "偽物: 1PPS なし（--fake-notime）"

    def anchor(self):
        return True, None

    def now_beat(self):
        return int((time.time() - self.t0) * BEATS_PER_SEC)

    def grid_after(self, beat):
        return -(-int(beat) // G_BEATS) * G_BEATS

    def start(self, st, at_beat, force):
        if not self.clock.ok and not force:
            raise RuntimeError("時刻を答えられない（錨が無い・PPS が来ていない）。ANCHOR か force=1")
        self.cfgs = [dict(if_mhz=ws["if_mhz"], ns=ws["ns"], shift=ws["shift"], nacc=nacc_of(st["tint"], ws["ns"]), g=g_of(ws["ns"]),
                          bundle=0, n_sum=1, pl_nacc=nacc_of(st["tint"], ws["ns"]))      # 偽物は束ねない（ダンプ = tint）
                     for ws in st["wins"]]
        self.cfg = st["cfg"]
        self.tint_beats = int(round(st["tint"] * BEATS_PER_SEC))
        self.sa = self.grid_after(max(at_beat or 0, self.now_beat() + BEATS_PER_SEC // 2))
        return self.sa

    def fired(self):
        return self.now_beat() > self.sa

    def begin(self):
        self.k_next = [0] * (4 * NW)
        self.tp_next = [0] * 4
        self.tps = []
        for _ in range(4):
            t = type("T", (), {})()
            t.buf = np.zeros(4 * 512, P.TP_E); t.n = 0; t.lost = 0; t.bad_seq = 0; t.bad_flag = 0; t.bad_nfr = 0
            t.n_ovr = 0; t.total = 0; t.started = True; t.overflow = 0
            self.tps.append(t)
        self.running = True
        return dict(run_t_bad=[])

    def poll_win(self, j):
        k = self.k_next[j]
        t_end = self.sa + 1 + (k + 1) * self.tint_beats
        if self.now_beat() < t_end + 20000:        # 閉じてから読めるまで ≒ 80 µs
            return None
        if self.o.fake_stall and k and k % self.o.fake_stall == 0 and j == 0:
            time.sleep(0.05)                       # 陽性対照: 読み出しを 50 ms 止める → 次の面で読み落とす
        self.k_next[j] = k + 1
        cf = self.cfgs[j]
        m = dict(seq=k + 1, k=k, n=cf["nacc"], t=self.sa + 1 + k * self.tint_beats, h=0, cfg=self.cfg, sat=0, flags=0)
        spec = self.base[j] + np.uint64(k)
        # 実機は面が 2 つで、1 周が tint を越えると次のダンプを上書きする。偽物も同じに数える
        lag = (self.now_beat() - t_end) // self.tint_beats
        miss = 0
        if lag >= 1:
            miss = int(lag)
            self.k_next[j] = k + 1 + miss
        return m, spec, miss

    def poll_tp(self, i):
        t = self.tps[i]
        f_now = (self.now_beat() - self.sa - 1) // 512
        while (self.tp_next[i] + 1) * TP_N <= f_now and t.n < len(t.buf):
            e = t.buf[t.n]
            e["t_beat"] = self.tp_next[i] * TP_N
            e["sum"] = 3_000_000_000 + self.tp_next[i]; e["nfr"] = TP_N; e["flags"] = TPF_RUN if self.tp_next[i] == 0 else 0
            pj = getattr(self.o, "posctl_tp_jump", 0)
            if pj and self.tp_next[i] and self.tp_next[i] % pj == 0:
                e["sum"] = int(e["sum"]) * 105 // 100            # 陽性対照（B2）: この個だけ +0.21 dB
            t.n += 1; t.total += 1
            self.tp_next[i] += 1
        return t

    def tp_time(self, i, f):
        return self.sa + 1 + f * 512

    def pump(self):
        return 0

    def snap(self, adc, n, nacc, timeout=5.0):
        """偽物: 3000.25 MHz（第 2 ナイキストで 1095.75 MHz に見える）の正弦波 ＋ ガウス雑音、16 bit の上位 14 bit"""
        rng = np.random.default_rng(adc)
        out = []
        t0 = self.now_beat()
        for k in range(n):
            t = t0 + k * nacc * 512
            i = np.arange(P.SNAP_N) + (t * 16)
            x = 1000 * np.sin(2 * np.pi * (1095.75 / 4096.0) * i) + 800 * rng.standard_normal(P.SNAP_N)
            out.append((dict(seq=k + 1, k=k, n=nacc, f0=t // 512, t=t, h=0, cfg=0),
                        (np.clip(np.round(x), -8191, 8191).astype(np.int16) * 4)))
            time.sleep(nacc * 2e-6)
        return out

    def disarm(self):
        pass

    def stop(self):
        was, self.running = self.running, False
        return [dict(adc=i, anch_dev=0, gap=0) for i in range(4)] if was else []


# ================================================================ proj023: SAM45-Wide
class WideBackend(HwBackend):
    """SAM45-Wide（BIT_KIND 1）の裏。8 本の SLICE の流れを窓 j = 2·ADC + s の位置に。TP・リング・束ね・時刻は HwBackend と同じ"""

    def open(self):
        import spectrometer as S
        import timetest as T
        import window as W
        import timebase as TB
        import s45core as SC
        self.S, self.T, self.W, self.TB, self.SC = S, T, W, TB, SC
        from pynq import Overlay
        import xrfdc                               # Overlay() より前に import する（VERSIONS.md）
        S.setup_clocks(self.o.clkin, self.o.ref)
        self.lmx = None
        self.ol = Overlay(self.o.bitfile)
        if not isinstance(self.ol.rfdc, xrfdc.RFdc):
            raise RuntimeError("RFDC に xrfdc のドライバが当たっていない")
        S.check_tiles(self.ol.rfdc, 2)
        time.sleep(self.o.settle)
        self.cores, tmm = SC.discover(self.ol, bit_kind=1, bit_rev_min=1)
        self.tc = TB.TimeCore(tmm)
        self.wms = [c.m for c in self.cores]
        self.wins = []
        for c in self.cores:
            ss = c.slices()
            if [x.s for x in ss] != [0, 1]:
                raise RuntimeError(f"{c.name} の SLICE の流れが s = 0・1 でない")
            self.wins += ss
        for wm in self.wms:
            prm = int(wm.read(W.A_BASE + S.R_TP_PARAM)) & 0xFFFFFFFF
            if prm != S.TP_PARAM_EXPECT:
                raise RuntimeError(f"TP_PARAM {prm:08x}（期待 {S.TP_PARAM_EXPECT:08x}）")
        self.tc.configure(src=self.o.path, tol=1)
        self.tb = TB.Timebase(self.tc, path=self.o.path)
        self.TpStream = make_tp_reader(S)
        c0 = self.cores[0]
        self.ids = dict(win=f"{self.wins[0].rd(SC.S_SID):08x}", adc=f"{c0.if_id:08x}", time=f"{self.tc.rd(0x00):08x}",
                        proj=f"{c0.proj:08x}", kind="wide", lmx_vco="7864.32", lmx_pwr="31")
        self.clock = Clock(None, {})
        self._open_ring()
        self.ids["read"] = "ring"
        self.bit_kind = c0.bit_kind
        self.anchor()

    def _open_ring(self):
        import plring as PR
        SC = self.SC
        bad = [c.name for c in self.cores if (c.caps & 3) != 3]
        if bad:
            raise RuntimeError(f"CAPS の [0]〜[1]（レコード・TP）が無いコア {bad}")
        rip = getattr(self.ol, "s45_ring_0", None)
        if rip is None:
            raise RuntimeError("ol.s45_ring_0 が無い")
        self.ring = PR.Ring(rip.mmio, getattr(self.o, "ring_mib", 32) << 20)
        self.ring.enable(True)
        self.jmap = {(st.core.adc, st.s): j for j, st in enumerate(self.wins)}
        self.amap = {c.adc: i for i, c in enumerate(self.cores)}
        self.q = [collections.deque() for _ in self.wins]
        self.raws = [st for c in self.cores for st in c.raw()]
        # proj023 4g: SNAP は RAW の流れ（コア 0 の s 2、入口は axis_sel4 で 4 ADC から選ぶ）。HwBackend._snap_ring をそのまま使う
        #   （SRC → WRST・N_ACC・N_DUMP・REC_CTRL = ALL | SNAP・RUN、SNAP のレコードを集める。番地と意味は SAM45-Fine の RAW と同じ）
        self.full = SC.snap_stream(self.cores)
        if self.full.kind != SC.KIND_RAW:
            raise RuntimeError("RAW の流れが無い（SNAP を取れない）")
        self.fkey = (self.full.core.adc, self.full.s)
        self.log(f"リング: BASE {self.ring.base:#x} / SIZE {self.ring.size}（Wide: SLICE {len(self.wins)} 本）")

    def _rec_off(self):
        SC = self.SC
        for st in self.wins + self.raws:
            st.wr(SC.S_REC_CTRL, 0)
        for wm in self.wms:
            wm.write(TP_REC_CTRL, TP_REC_K << 8)

    def disarm(self):
        SC, T, W = self.SC, self.T, self.W
        for st in self.wins:
            st.wr(SC.S_CTRL, W_CTRL_DISARM)
        for wm in self.wms:
            wm.write(W.A_BASE + T.RA_TP_CTRL, T.TP_DISARM)

    def _arm_tc(self, sa):
        try:
            self.tc.arm(sa)
        except Exception:
            self.tc.wr(0x08, self.TB.TimeCore.CTRL_CANCEL)
            self.disarm()
            raise

    def start(self, st, at_beat, force):
        """FFT_N・S0・SHIFT・CFG → ARM_WRST（tint の格子で 4 コア一斉）→ 読み返し → N_ACC 1280・REC ALL・TP → ARM_RUN と TP_ARM を tint の格子で"""
        SC, T, W = self.SC, self.T, self.W
        if self.clock.ok:
            try:
                self.tb.check()
            except Exception as e:
                self.clock.ok, self.clock.err = False, str(e)
        if not self.clock.ok and not force:
            raise RuntimeError("時刻を答えられない（錨が無い・PPS が来ていない）。ANCHOR か force=1")
        self.disarm()
        check_wide(st)
        self.tint_beats = check_tint(st["tint"]) * BASE_BEATS
        bb = {c.base_beats for c in self.cores}
        if bb != {BASE_BEATS}:
            raise RuntimeError(f"コアの BASE_BEATS {bb}（{BASE_BEATS} を期待）")
        self.cfgs = wide_cfgs(st)
        for st_ in self.wins:
            st_.wr(SC.S_CTRL, 1 << 1)              # STOP
            st_.wr(SC.S_REC_CTRL, 0)
        for i, c in enumerate(self.cores):
            cf0 = self.cfgs[NW * i]
            c.wr(W_FFT_N, 15 - cf0["lb"])
            for s in range(NW):
                cf, st_ = self.cfgs[NW * i + s], self.wins[NW * i + s]
                st_.wr(SC.S_S0, cf["s0"]); st_.wr(SC.S_SHIFT, cf["shift"]); st_.wr(SC.S_CFG, st["cfg"])
            self.wins[NW * i].wr(SC.S_CTRL, W_CTRL_ARMWRST)     # どちらの流れでもコアの WRST
        sa_w = self.grid_after(self.now_beat() + BEATS_PER_SEC // 2)
        self._arm_tc(sa_w)
        self._wait_fired(5.0)
        time.sleep(0.01)
        for i, c in enumerate(self.cores):
            lb = self.cfgs[NW * i]["lb"]
            fr = c.rd(W_FFT_N)
            if (fr & 0xFF, fr >> 8 & 0xFF) != (15 - lb, 15 - lb):
                raise RuntimeError(f"{c.adc_name}: WRST の後の FFT_N {fr:#x}（書いた {15 - lb}）")
            for s in range(NW):
                cf, st_ = self.cfgs[NW * i + s], self.wins[NW * i + s]
                if cf["active"] and st_.rd(SC.S_S0_CUR) != cf["s0"]:
                    raise RuntimeError(f"{win_key(NW * i + s)}: S0_CUR {st_.rd(SC.S_S0_CUR)}（書いた {cf['s0']}）")
                if st_.rd(SC.S_NCH) != (P.NCH if cf["active"] else 0):
                    raise RuntimeError(f"{win_key(NW * i + s)}: NCH {st_.rd(SC.S_NCH)}")
        for cf, st_ in zip(self.cfgs, self.wins):
            if cf["active"]:
                st_.wr(SC.S_NACC, cf["pl_nacc"]); st_.wr(SC.S_NDUMP, 0)
                st_.wr(SC.S_REC_CTRL, REC_ALL)
        for wm in self.wms:
            wm.write(W.A_BASE + T.RA_TP_N, TP_N)
            wm.write(TP_REC_CTRL, (TP_REC_K << 8) | 1)
        self._drain()
        sa = self.grid_after(max(at_beat or 0, self.now_beat() + BEATS_PER_SEC // 2))
        for cf, st_ in zip(self.cfgs, self.wins):
            if cf["active"]:
                st_.wr(SC.S_CTRL, (1 << 8) | W_SID_CTRL_ARMRUN)
        for wm in self.wms:
            wm.write(W.A_BASE + T.RA_TP_CTRL, T.TP_ARM)
        self._arm_tc(sa)
        self.sa = sa
        self.armed = True
        return sa

    def begin(self):
        S, T, W, SC = self.S, self.T, self.W, self.SC
        act = [st for st, cf in zip(self.wins, self.cfgs) if cf["active"]]
        rd64 = lambda st, a: st.rd(a) | (st.rd(a + 4) << 32)
        runts = [rd64(st, SC.S_RUN_T) for st in act] + [T.tp_run_t(wm) for wm in self.wms]
        bad = [i for i, t in enumerate(runts) if t != self.sa + 1]
        for st, cf in zip(self.wins, self.cfgs):
            if cf["active"] and st.rd(SC.S_RUN_SHIFT) != cf["shift"]:
                raise RuntimeError(f"{st.name}: RUN_SHIFT {st.rd(SC.S_RUN_SHIFT)}（書いた値 {cf['shift']}）")
        self.seq = [st.rd(SC.S_SEQ) for st in self.wins]
        self.tps, self.anch = [], []
        for wm in self.wms:
            tp = _WinTp(wm, W.A_BASE)
            tf0 = tp.rd(S.R_TP_F0_LO) | (tp.rd(S.R_TP_F0_HI) << 32)
            self.tps.append(self.TpStream(tp, TP_N, tf0))
            self.anch.append(self._tanch(wm))
        self.gap0 = [int(wm.read(W.A_BASE + T.RA_GAP)) for wm in self.wms]
        self.running = True
        return dict(run_t_bad=bad)

    def snap(self, adc, n, nacc, timeout=5.0):
        """proj023 4g: RAW の流れで（IDLE のときだけ。Acq._snap が見る）"""
        return self._snap_ring(adc, n, nacc, timeout)

    def stop(self):
        SC = self.SC
        if not self.running:
            self.disarm()
            self.tc.wr(0x08, self.TB.TimeCore.CTRL_CANCEL)
            self._rec_off()
            return []
        for st in self.wins:
            st.wr(SC.S_CTRL, 1 << 1)
        self.pump()
        self._rec_off()
        self.running = False
        out = []
        for i, wm in enumerate(self.wms):
            try:
                af1, at1 = self._tanch(wm)
                af, at = self.anch[i]
                gap1 = int(wm.read(self.W.A_BASE + self.T.RA_GAP))
                out.append(dict(adc=i, anch_dev=(at1 - at) - (af1 - af) * 512, gap=gap1 - self.gap0[i]))
            except Exception as e:
                out.append(dict(adc=i, err=str(e)))
        return out


class FakeWideBackend(FakeBackend):
    """PL なしの Wide（偽物は束ねない: ダンプ = tint。中身の形・鍵・IF の軸・DUMP_T の進み 2048·nacc を受け側で確かめる）"""

    def start(self, st, at_beat, force):
        if not self.clock.ok and not force:
            raise RuntimeError("時刻を答えられない（錨が無い・PPS が来ていない）。ANCHOR か force=1")
        check_wide(st)
        self.cfgs = wide_cfgs(st)
        for cf in self.cfgs:
            cf.update(bundle=0, n_sum=1, pl_nacc=cf["nacc"])
        self.cfg = st["cfg"]
        self.tint_beats = int(round(st["tint"] * BEATS_PER_SEC))
        self.sa = self.grid_after(max(at_beat or 0, self.now_beat() + BEATS_PER_SEC // 2))
        return self.sa

    def poll_win(self, j):
        if not self.cfgs[j]["active"]:
            return None
        return super().poll_win(j)


# ================================================================ 取得の本体
class Acq:
    IDLE, ARMED, RUN, ERROR = "IDLE", "ARMED", "RUN", "ERROR"

    def __init__(self, conn, ring, opts):
        self.conn, self.ring, self.o = conn, ring, opts
        self.wide = bool(getattr(opts, "wide", False))               # proj023: SAM45-Wide（SLICE の流れ）
        self.st = default_settings_wide() if self.wide else default_settings()
        self.state = self.IDLE
        self.seq = 0
        self.drop = dict(n=0, first=None, last=None, pending=None)
        self.err = None
        self.forced = False
        self.posctl = dict(corrupt=opts.posctl_corrupt, gap=opts.posctl_gap)
        self.proto = int(getattr(opts, "proto", P.VERSION))          # proj021 2-3c: 送る版（1 = 今までの v1）
        self.f32_trunc = bool(getattr(opts, "posctl_f32_trunc", False))
        self.hist = np.zeros(1001, np.int64)      # 1 周の時間（0.1 ms 刻み、100 ms で頭打ち）
        self.cal = getattr(opts, "tp_cal", None)    # TP の dBm の較正（s45cal、specd が起動時に読む）。bit の ID は open の後で照らす
        self.cal_msg = "較正ファイルが無い" if self.cal is None else "未確認"
        self.tp_last = [None] * 4                  # ADC ごとの直近の TP（σ_x²、最後に書き出した記録の平均）
        self.tpj = [TpJump(phase=250 * i) for i in range(4)]    # proj021 B2: TP の跳ねの見張り（tpjump.py。START で初めから。B2b: σ の計算し直しを ADC ごとにずらす）
        self.tpj_on = not getattr(opts, "no_tp_jump", False)   # --no-tp-jump: 見張りを止める（1 周の重さの比べ）
        self._reset_counters()

    def log(self, *a):
        print("[acq]", *a, flush=True)

    def _reset_counters(self):
        self.n_dump = [0] * (4 * NW)
        self.active = [True] * (4 * NW)            # proj023: B 4 の流れ 1 は空（数えない）
        self.n_miss = [0] * (4 * NW)
        self.kgap = [0] * (4 * NW)
        self.last_k = [None] * (4 * NW)
        self.h_or = 0
        self.fl_or = 0
        self.sat = 0
        self.loop_max = 0.0
        self.loop_max_at = 0                       # proj021 2-3a: 最大だった周の番号（RUN から）
        self.bund = [None] * (4 * NW)              # proj021 2-3b: 窓ごとの Bundler（START で作る）
        self.pl_dumps = [0] * (4 * NW)
        self.loop_slow = 0                         # 1 周が tint を越えた回数
        self.hist[:] = 0
        self.n_loop = 0
        self.ndump_target = 0
        self.start_at = None
        self.stop_info = None

    # ---- 溜まりへ
    def _next_seq(self):
        self.seq += 1
        return self.seq

    def _put(self, rtype, payload_parts, crc):
        """記録を溜まりに置く。入らなければ捨てて数える。**一度溢れたら、空きが溜まりの 1/4 に戻るまで捨て続ける**
        （空きの縁で 1 個おきに入る・捨てるを繰り返し、DROP の EVENT が細切れになるのを避ける）。DROP の EVENT は再開の直前に置く"""
        d = self.drop
        if d["pending"] is not None:
            if rtype == P.T_EVENT or self.ring.cap - self.ring.used() >= self.ring.cap // 4:
                self._flush_drop()                    # EVENT（小さく、START・STOP を落としたくない）は空きがあれば割り込む
        seq = self._next_seq()
        if self.posctl["gap"] and seq % self.posctl["gap"] == 0:
            return                                    # 陽性対照: 番号だけ進めて黙って捨てる（受け側の「説明のない欠け」が数えるはず）
        plen = sum(memoryview(p).nbytes for p in payload_parts)
        if self.posctl["corrupt"] and seq % self.posctl["corrupt"] == 0:
            payload_parts = list(payload_parts)
            b = bytearray(payload_parts[-1]); b[len(b) // 2] ^= 0x01
            payload_parts[-1] = bytes(b)              # 陽性対照: CRC を計算した後に 1 bit 反転（受け側の CRC の不一致が数えるはず）
        ok = (d["pending"] is None or rtype == P.T_EVENT) and self.ring.put([P.header(rtype, plen, crc, seq, self.proto)] + list(payload_parts))
        if not ok:
            d["n"] += 1
            if d["pending"] is None:
                d["pending"] = [seq, seq, 1]
            else:
                d["pending"][1] = seq; d["pending"][2] += 1

    def _flush_drop(self):
        a, b, n = self.drop["pending"]
        p = P.event_payload(dict(ev="DROP", **{"from": a, "to": b, "n": n}))
        seq = self.seq + 1
        if self.ring.put([P.header(P.T_EVENT, len(p), P.crc32(p), seq, self.proto), p]):
            self.seq = seq
            self.drop["pending"] = None
            self.log(f"溜まりが溢れて捨てた: seq {a}〜{b}（{n} 個）")

    def event(self, d):
        p = P.event_payload(d)
        self._put(P.T_EVENT, [p], P.crc32(p))

    # ---- 命令
    def handle(self, cmd):
        op = cmd.get("op")
        try:
            if op == "status":
                return dict(ok=True, **self.status())
            if op == "id":
                return dict(ok=True, ids=self.be.ids, version=VERSION, adcs=4, nw=NW, fake=bool(self.o.fake))
            if op == "get":
                return dict(ok=True, settings=self.st)
            if op == "cal":
                return dict(ok=True, cal=self._cal_pub(), msg=self.cal_msg)
            if op == "set":
                if self.state not in (self.IDLE, self.ERROR):
                    return dict(ok=False, code="STATE", msg=f"{self.state} の間は SET できない（STOP の後に）")
                st = self.st
                new = dict(tint=st["tint"], cfg=st["cfg"], fmt=st.get("fmt", "f32"), wins=[dict(w) for w in st["wins"]])
                if self.wide:
                    new["kind"] = "wide"
                    for k, v in cmd["kv"].items():
                        self._set1_wide(new, k, v)
                    check_tint(new["tint"])
                    check_wide(new)
                    self.st = new
                    return dict(ok=True)
                for k, v in cmd["kv"].items():
                    self._set1(new, k, v)
                check_tint(new["tint"])
                for ws in new["wins"]:
                    nacc_of(new["tint"], ws["ns"])
                    import window as W
                    W.window_params(ws["if_mhz"], 512.0 / (1 << ws["ns"]))
                self.st = new
                return dict(ok=True)
            if op == "anchor":
                if self.state in (self.ARMED, self.RUN):
                    return dict(ok=False, code="STATE", msg="RUN の間は錨を打ち直さない")
                ok, e = self.be.anchor()
                return dict(ok=ok, code="TIME", msg=e) if not ok else dict(ok=True)
            if op == "start":
                return self._start(cmd)
            if op == "snap":
                return self._snap(cmd)
            if op == "stop":
                if self.state not in (self.ARMED, self.RUN):
                    return dict(ok=False, code="STATE", msg=f"{self.state} なので止めるものが無い")
                self._stop("命令")
                return dict(ok=True)
            if op == "quit":
                if self.state in (self.ARMED, self.RUN):
                    self._stop("終了")
                return dict(ok=True, quit=True)
            return dict(ok=False, code="CMD", msg=f"知らない命令 {op}")
        except (ValueError, KeyError, SystemExit) as e:
            return dict(ok=False, code="ARG", msg=str(e))
        except Exception as e:
            self.log(traceback.format_exc())
            return dict(ok=False, code="FAIL", msg=f"{type(e).__name__}: {e}")

    def _set1_wide(self, new, k, v):
        """proj023: tint・fmt・cfg と、A.b / A0.b（束ね B、コアで 1 つ）・A.shift / A0.shift（コアで 1 つ）・A0.s0 / A0.ch0（流れの最初の ch）。all.b・all.shift も"""
        if k in ("tint", "fmt", "cfg"):
            return self._set1(new, k, v)
        name, _, field = k.partition(".")
        nu = name.upper()
        if nu == "ALL":
            js = list(range(4 * NW))
        elif len(nu) == 1 and nu in "ABCD":
            js = [NW * "ABCD".index(nu) + s for s in range(NW)]
        elif len(nu) == 2 and nu[0] in "ABCD" and nu[1] in "01":
            js = [NW * "ABCD".index(nu[0]) + int(nu[1])]
        else:
            raise ValueError(f"知らない設定 {k}（tint・fmt・cfg・A.b・A.shift・A0.s0・all.b・all.shift …）")
        if field in ("b", "shift"):
            js = sorted({NW * (j // NW) + s for j in js for s in range(NW)})     # コアで 1 つ
            x = int(v)
            if field == "b" and x not in W_LB:
                raise ValueError(f"{k}: B は 1・2・4")
            if field == "shift" and x not in range(16):
                raise ValueError(f"{k}: SHIFT は 0..15")
            for j in js:
                new["wins"][j][field] = x
        elif field in ("s0", "ch0"):
            if len(nu) != 2:
                raise ValueError(f"{k}: s0 は流れごと（A0.s0 のように）")
            new["wins"][js[0]]["s0"] = int(v)
        else:
            raise ValueError(f"知らない流れの設定 {k}（b・shift・s0）")

    def _set1(self, new, k, v):
        if k == "tint":
            new["tint"] = float(v)
        elif k == "fmt":                           # proj021 2-3c: v2 の SPEC の形（f32 = 運転 / u64 = 試験 / both = 同じ束を両方。照合用）
            if v not in ("f32", "u64", "both"):
                raise ValueError("fmt は f32・u64・both")
            new["fmt"] = v
        elif k == "cfg":
            new["cfg"] = int(v, 0) & 0xFFFFFFFF
        else:
            name, _, field = k.partition(".")
            if name.lower() == "all":
                js = range(4 * NW)
            elif len(name) == 2 and name[0].upper() in "ABCD" and name[1] in "01":
                js = [("ABCD".index(name[0].upper())) * NW + int(name[1])]
            else:
                raise ValueError(f"知らない設定 {k}（tint・cfg・A0.if・A0.ns・A0.bw・A0.shift・all.shift …）")
            for j in js:
                ws = new["wins"][j]
                if field == "if":
                    ws["if_mhz"] = float(v)
                elif field == "ns":
                    n = int(v)
                    if n not in range(1, 7):
                        raise ValueError(f"{k}: NS は 1..6（SAM45-Fine）")
                    ws["ns"] = n
                elif field == "bw":
                    b = int(float(v))
                    if b not in NS_OF_BW:
                        raise ValueError(f"{k}: 幅は 256 / 128 / 64 / 32 / 16 / 8 MHz")
                    ws["ns"] = NS_OF_BW[b]
                elif field == "shift":
                    s = int(v)
                    if s not in range(16):
                        raise ValueError(f"{k}: SHIFT は 0..15")
                    ws["shift"] = s
                elif field == "bundle":
                    b = int(v)
                    if b not in (0, 1):
                        raise ValueError(f"{k}: bundle は 1（PL は 10.24 ms・specd が束ねる。既定）/ 0（PL が tint を 1 個で。V2-a の比べ用）")
                    ws["bundle"] = b
                else:
                    raise ValueError(f"知らない窓の設定 {k}（if・ns・bw・shift・bundle）")

    def _start(self, cmd):
        if self.state in (self.ARMED, self.RUN):
            return dict(ok=False, code="STATE", msg=f"{self.state} の間は START できない")
        force = bool(cmd.get("force"))
        at_beat = None
        if cmd.get("at_utc_ns") is not None:
            if not self.be.clock.ok:
                return dict(ok=False, code="TIME", msg="時刻を答えられないので at= は使えない")
            at_beat = self.be.clock.beat_of_utc_ns(cmd["at_utc_ns"])
            if at_beat < self.be.now_beat() + BEATS_PER_SEC:
                return dict(ok=False, code="ARG", msg="at= は今から 1 秒以上後に")
        self._reset_counters()
        for t in self.tpj:
            t.reset()                              # B2: スキャンの状態（CFG_ID）は RUN ごとなので、R の段差は RUN の境で除ける
        self.state = self.ARMED
        try:
            sa = self.be.start(self.st, at_beat, force)
        except Exception:
            self.state = self.IDLE
            raise
        self.forced = force and not self.be.clock.ok
        self.start_at = sa
        self.active = [bool(cf.get("active", True)) for cf in self.be.cfgs]
        self.bund = [Bundler(cf["n_sum"], cf["pl_nacc"]) if cf.get("bundle") else None for cf in self.be.cfgs]
        self.ndump_target = int(cmd.get("n") or 0)
        utc = self.be.clock.utc_ns(sa)
        self.event(dict(ev="START", start_at=sa, utc_ns=utc, n=self.ndump_target, forced=self.forced, version=VERSION,
                        proto=self.proto, fmt=self.st.get("fmt", "f32") if self.proto == 2 else "u64",
                        ids=self.be.ids, tint=self.st["tint"], cfg=self.st["cfg"], tp_cal=self._cal_pub(),
                        wins=[dict(key=win_key(j), adc=j // NW, win=j % NW, **cf) for j, cf in enumerate(self.be.cfgs)]))
        self.log(f"START: START_AT {sa}（格子 {sa // G_BEATS}·G、UTC {utc / 1e9:.6f}）n = {self.ndump_target}")
        return dict(ok=True, start_at=sa, utc_ns=utc)

    SNAP_MAX = 256

    def _snap(self, cmd):
        """ADC の生サンプル（全帯域コアのスナップショット 8192 個 = 2 µs）を n 個、every_ms おきに取り、T_SNAP の記録で溜まりへ。
        IDLE のときだけ（RUN の窓・TP には触らない）。記録の前後に EVENT（SNAP / SNAP_END）"""
        if self.state not in (self.IDLE, self.ERROR):
            return dict(ok=False, code="STATE", msg=f"{self.state} の間は SNAP できない（STOP の後に）")
        adc, n, every = int(cmd["adc"]), int(cmd.get("n", 1)), float(cmd.get("every_ms", 20.0))
        if not 0 <= adc < 4:
            raise ValueError("adc は A〜D（0〜3）")
        if not 1 <= n <= self.SNAP_MAX:
            raise ValueError(f"n は 1〜{self.SNAP_MAX}")
        if not 5.0 <= every <= 10000.0:
            raise ValueError("every は 5〜10000 ms（読み出しに数 ms かかる）")
        nacc = int(round(every * 1e-3 / 2.0e-6))           # 1 フレーム = 8192 サンプル = 512 ビート = 2.000 µs
        self.event(dict(ev="SNAP", adc=adc, n=n, every_ms=every, nacc=nacc))
        got = self.be.snap(adc, n, nacc)
        for k, (m, x) in enumerate(got):
            h = int(m["h"]) | (0 if self.be.clock.ok else P.H_NOTIME)
            utc = self.be.clock.utc_ns(m["t"], None, adc)
            hd = P.SNAP_H.pack(adc, 0, 0, len(x), int(m["t"]), int(utc), int(m["f0"]), h, k)
            data = np.ascontiguousarray(x, "<i2")
            self._put(P.T_SNAP, [hd, data], P.crc32(hd, data))
        self.event(dict(ev="SNAP_END", adc=adc, n=len(got)))
        return dict(ok=True, n=len(got), nacc=nacc, every_ms=every)

    def _stop(self, why):
        info = []
        try:
            info = self.be.stop()
        except Exception as e:
            info = [dict(err=str(e))]
        if self.state == self.RUN:
            for b in self.bund:
                if b is not None:
                    b.stop()                       # 半端な束は捨てる（INTERFACE 5.1 の 4）
            for i in range(4):
                try:
                    self._flush_tp(i, final=True)
                except Exception as e:             # 止める理由が TP・時刻の誤りのとき、ここでもう一度落ちないように
                    self.log(f"STOP の TP の書き出しで: {type(e).__name__}: {e}")
        self.state = self.IDLE if why != "ERROR" else self.ERROR
        self.stop_info = info
        self.event(dict(ev="STOP", why=why, dumps=self.n_dump, miss=self.n_miss, tp=[t.total for t in self.be.tps] if hasattr(self.be, "tps") else [],
                        tp_info=info, err=self.err))
        self.log(f"STOP（{why}）: ダンプ {sum(self.n_dump)}・読み落とし {sum(self.n_miss)}・TP の錨の組 {info}")

    def status(self):
        tl = self.hist
        tot = int(tl.sum())
        p99 = float(np.searchsorted(np.cumsum(tl), 0.99 * tot) * 0.1) if tot else 0.0
        tps = getattr(self.be, "tps", [])
        w, r = self.ring.positions()
        return dict(state=self.state, time_ok=self.be.clock.ok, time_err=self.be.clock.err, start_at=self.start_at,
                    dumps=self._dumps_min(), dumps_each=self.n_dump, miss=sum(self.n_miss), kgap=sum(self.kgap),
                    tp=[t.total for t in tps], tp_lost=sum(t.lost + t.overflow for t in tps), tp_bad=sum(t.bad_seq + t.bad_flag + t.bad_nfr for t in tps),
                    tp_ovr=sum(t.n_ovr for t in tps), tp_jump=[t.count for t in self.tpj], health=self.h_or, flags=self.fl_or, sat=self.sat,
                    loop_max_ms=round(self.loop_max * 1e3, 2), loop_p99_ms=p99, loops=self.n_loop,
                    loop_max_at=self.loop_max_at, loop_slow=self.loop_slow,
                    pl_dumps=sum(self.pl_dumps), bdrop=sum(b.drop for b in self.bund if b is not None),
                    r_bad=sum(b.r_bad for b in self.bund if b is not None),
                    bund_r=[None if b is None else b.r0 for b in self.bund],
                    seq=self.seq, drop=self.drop["n"], ring_used=w - r, ring_cap=self.ring.cap, err=self.err, forced=self.forced,
                    tp_dbfs=[None if v is None else round(float(s45cal.dbfs(v)), 2) for v in self.tp_last],
                    tp_dbm=[None if v is None or self.cal is None else round(float(s45cal.dbm(v, self.cal, "ABCD"[i])), 2)
                            for i, v in enumerate(self.tp_last)],
                    ring=self.be.ring_stat() if hasattr(self.be, "ring_stat") else None)

    def _dumps_min(self):
        v = [n for n, a in zip(self.n_dump, self.active) if a]
        return min(v) if v else 0

    # ---- 読み出しの 1 周
    def _cal_pub(self):
        """START の EVENT・GET CAL に出す較正（使えないときは None）"""
        if self.cal is None:
            return None
        return {k: v for k, v in self.cal.items() if not k.startswith("_")} | {"file": self.cal.get("_file")}

    def _spec_record(self, j, m, spec):
        cf = self.be.cfgs[j]
        h = int(m["h"]) | (0 if self.be.clock.ok else P.H_NOTIME) | (P.H_FORCED if self.forced else 0)
        if cf.get("kind") == "slice":
            self._spec_record_slice(j, m, spec, cf, h)
            return
        utc = self.be.clock.utc_ns(m["t"], cf["ns"], j // NW)
        if self.proto == 2:
            self._spec_record2(j, m, spec, cf, h, utc)
            return
        hd = P.SPEC_H.pack(j // NW, j % NW, cf["ns"], cf["shift"], P.FMT_RAW, cf["g"], 0, m["cfg"], m["k"], cf["nacc"],
                           m["sat"], m["flags"], h, m["t"], utc, cf["if_mhz"])
        data = np.ascontiguousarray(spec[P.IF_ORDER])
        self._put(P.T_SPEC, [hd, data], P.crc32(hd, data))
        self.h_or |= int(m["h"]); self.fl_or |= int(m["flags"]) & FLAGS_OK_MASK; self.sat += int(m["sat"])

    def _spec_record2(self, j, m, spec, cf, h, utc):
        """proj021 2-3c: s45proto v2 の SPEC（INTERFACE 6.）。utc_ns は実効の区間の始まり（5.2）: v1 の utc（D(NS) を引いたもの）から、
        さらに PFB の重心のずれ 1.5·L(NS) を引く。fmt = f32（既定）/ u64 / both（同じ束を u64 と f32 の 2 つで。受け側の照合）"""
        ns = cf["ns"]
        L = 4096 << (ns - 1)
        if utc:
            utc -= (3 * L * 125) // 64                 # 1.5·L ビート → ns（1 ビート = 125/32 ns）
        df = 512e6 / (1 << ns) / P.NCH
        raw = np.ascontiguousarray(spec[P.IF_ORDER])
        fm = self.st.get("fmt", "f32")
        for f in (("u64", "f32") if fm == "both" else (fm,)):
            if f == "u64":
                data, code = raw, P.FMT_RAW
            else:
                data, code = P.f32_round(raw), P.FMT_F32
                if self.f32_trunc:                     # 陽性対照: 0 へ切り捨て（最も近い値でない）→ 受け側の照合が落ちる
                    up = data.astype(np.float64) > raw.astype(np.float64)
                    data[up] = np.nextafter(data[up], np.float32(0))
            hd = P.SPEC2_H.pack(j // NW, j % NW, j // NW, 3, ns, cf["shift"], code, int(getattr(self.be, "bit_kind", 0)),
                                P.NCH, int(cf.get("n_sum", 1)), m["cfg"], m["k"], cf["nacc"], m["sat"], m["flags"], h, cf["g"], 0,
                                m["t"], utc, P.BASE_NS, cf["if_mhz"], df)
            self._put(P.T_SPEC, [hd, data], P.crc32(hd, data))
        self.h_or |= int(m["h"]); self.fl_or |= int(m["flags"]) & FLAGS_OK_MASK; self.sat += int(m["sat"])

    def _spec_record_slice(self, j, m, spec, cf, h):
        """proj023: SLICE の SPEC（s45proto v2、kind 2）。ns の欄 = log2 B。中身は IF の昇順（流れの ch i の逆順）。
        utc_ns = beat_utc(dump_t) − adc_to_core − (D_S ＋ 1.5·L)、L = 2048 ビート（D_S = 0、sim-wds）"""
        adc, s = j // NW, j % NW
        utc = self.be.clock.utc_ns(m["t"], None, adc)
        if utc:
            utc -= ((W_DS_BEATS + 3 * W_FRAME // 2) * 125) // 32
        raw = np.ascontiguousarray(np.asarray(spec, np.uint64)[::-1])
        fm = self.st.get("fmt", "f32")
        for f in (("u64", "f32") if fm == "both" else (fm,)):
            if f == "u64":
                data, code = raw, P.FMT_RAW
            else:
                data, code = P.f32_round(raw), P.FMT_F32
                if self.f32_trunc:
                    up = data.astype(np.float64) > raw.astype(np.float64)
                    data[up] = np.nextafter(data[up], np.float32(0))
            hd = P.SPEC2_H.pack(adc, s, adc, 2, cf["lb"], cf["shift"], code, int(getattr(self.be, "bit_kind", 1)),
                                P.NCH, int(cf["n_sum"]), m["cfg"], m["k"], cf["nacc"], m["sat"], m["flags"], h, 0, 0,
                                m["t"], utc, P.BASE_NS, cf["if_mhz"], cf["df_hz"])
            self._put(P.T_SPEC, [hd, data], P.crc32(hd, data))
        self.h_or |= int(m["h"]); self.fl_or |= int(m["flags"]); self.sat += int(m["sat"])   # Wide の FLAGS は全部が異常

    def _bdrop(self, j, d):
        """束を捨てた（INTERFACE 5.1 の 4）。EVENT は最初の 20 回まで（止まりの後に窓ごとに続くので）"""
        jb, why, have = d
        tot = sum(b.drop for b in self.bund if b is not None)
        if tot <= 20 and why != "STOP":
            self.event(dict(ev="BDROP", key=win_key(j), bundle=int(jb), why=why, have=int(have), n_sum=self.bund[j].n_sum))
        if why == "r":
            self.event(dict(ev="ERROR", msg=f"{win_key(j)}: DUMP_T − m·BASE が RUN の中で動いた（r0 {self.bund[j].r0}）。この窓は束ねない"))

    def _flush_tp(self, i, final=False):
        t = self.be.tps[i]
        n = t.n
        if n == 0 or (n < TP_FLUSH and not final):
            if final and n == 0 and self.tpj_on:
                self._tp_jump(i, self.tpj[i].finish())     # B2: 最後の区切りで開いたままの跳ねも閉じる（溜まりが空でも）
            return
        e = t.buf[:n].copy()
        self.tp_last[i] = float(np.mean(e["sum"].astype(np.float64) / (e["nfr"].astype(np.float64) * 8192.0)))
        e["t_beat"] = self.be.tp_time(i, e["t_beat"].astype(np.int64))      # フレームの番号 → ビート
        if self.tpj_on:
            evs = self.tpj[i].feed(e["t_beat"], e["sum"].astype(np.float64) / (e["nfr"].astype(np.float64) * 8192.0), e["flags"])
            if final:
                evs += self.tpj[i].finish()
            self._tp_jump(i, evs)
        if self.be.clock.ok:
            e["utc_ns"] = self.be.clock.utc_ns_arr(e["t_beat"], i)
        else:
            e["utc_ns"] = 0
            e["flags"] |= P.TPF_NOTIME
        t.n = 0
        hd = P.TP_H.pack(i, 0, 0, n)
        b = e.tobytes()
        pad = b"\0" * (P.pad8(len(hd) + len(b)) - len(hd) - len(b))
        self._put(P.T_TP, [hd, b + pad], P.crc32(hd, b + pad))

    TP_JUMP_EV_MAX = 100                           # B2: EVENT は ADC ごとに RUN あたりこれまで（STATUS の tp_jump は全部数える）

    def _tp_jump(self, i, evs):
        for ev in evs:
            t = self.tpj[i]
            if t.count > self.TP_JUMP_EV_MAX:
                continue
            utc = self.be.clock.utc_ns(ev["t_beat"], None, i)
            self.event(dict(ev="TP_JUMP", adc=i, t_beat=ev["t_beat"], utc_ns=int(utc), n=ev["n"], db=ev["db"], step_db=ev["step_db"], sigma_db=ev["sigma_db"],
                            ovr=ev["ovr"], **({"last": True} if t.count == self.TP_JUMP_EV_MAX else {})))

    def _loop_once(self):
        ts = time.perf_counter()
        be = self.be
        nrec = be.pump()                           # proj021 2-3a: リングを 1 回読んで振り分ける（axi・偽物では何もしない）
        t_p = time.perf_counter()
        for j in range(4 * NW):
            for _ in range(64):                    # 溜まったぶんを全部（リングでは止まりの後に何個も来る）
                r = be.poll_win(j)
                if r is None:
                    break
                m, spec, miss = r
                self.n_miss[j] += miss
                self.pl_dumps[j] += 1
                bu = self.bund[j]
                if bu is not None:                 # proj021 2-3b: 束ねる（INTERFACE 5.1）
                    got, dropped = bu.add(m, spec)
                    if dropped is not None:
                        self._bdrop(j, dropped)
                    if got is None:
                        continue
                    m, spec = got
                if self.last_k[j] is not None and m["k"] != self.last_k[j] + 1:
                    self.kgap[j] += 1
                self.last_k[j] = m["k"]
                self.n_dump[j] += 1
                self._spec_record(j, m, spec)
        t_w = time.perf_counter()
        for i in range(4):
            be.poll_tp(i)
            self._flush_tp(i)
        t_t = time.perf_counter()
        be.clock.poll()
        t_c = time.perf_counter()
        dt = t_c - ts
        self.hist[min(1000, int(dt * 1e4))] += 1
        if dt > self.loop_max:
            self.loop_max, self.loop_max_at = dt, self.n_loop
        if dt > self.st["tint"]:
            self.loop_slow += 1
            if self.loop_slow <= 20:               # どの周が遅いかを残す（2-3a の 1 回目: 最大 115 ms・p99 14.5 ms）
                lp = getattr(be, "last_pump", (0.0, 0.0))
                self.log(f"1 周が {dt * 1e3:.1f} ms（周 {self.n_loop}・リングのレコード {nrec}）: リングの読み {lp[0] * 1e3:.1f}・振り分け {lp[1] * 1e3:.1f}・"
                         f"窓の記録 {(t_w - t_p) * 1e3:.1f}・TP {(t_t - t_w) * 1e3:.1f}・時刻の確かめ {(t_c - t_t) * 1e3:.1f} ms")
        self.n_loop += 1
        if self.ndump_target and self._dumps_min() >= self.ndump_target:
            self._stop("n に達した")

    # ---- 本体
    def run(self):
        self._rt()
        if self.wide:
            self.be = (FakeWideBackend if self.o.fake else WideBackend)(self.o, self.log)
        else:
            self.be = (FakeBackend if self.o.fake else HwBackend)(self.o, self.log)
        try:
            self.be.open()
        except BaseException as e:
            self.conn.send(dict(ok=False, msg=f"起動できない: {type(e).__name__}: {e}"))
            raise
        if self.cal is not None:
            ok, self.cal_msg = s45cal.check(self.cal, self.be.ids)
            if not ok:
                self.log(f"TP の較正を使わない: {self.cal_msg}（{self.cal.get('_file')}）")
                self.cal = None
            else:
                self.log(f"TP の較正: {self.cal.get('_file')}（" + "・".join(
                    f"{a} K {c['k_db']:+.2f}{' 暫定' if c.get('provisional') else ''}" for a, c in sorted(self.cal["adc"].items())) + "）")
        gc.collect(); gc.freeze(); gc.disable()
        self.conn.send(dict(ok=True, ids=self.be.ids, version=VERSION))
        self.log(f"準備完了（{'偽物' if self.o.fake else '実機'}、ID {self.be.ids}）")
        quit_ = False
        while not quit_:
            if self.state == self.RUN:
                try:
                    self._loop_once()
                except Exception as e:
                    self.err = f"{type(e).__name__}: {e}"
                    self.log(traceback.format_exc())
                    self.event(dict(ev="ERROR", msg=self.err))
                    self._stop("ERROR")
                wait = 0.0 if self.state == self.RUN else 0.05
            elif self.state == self.ARMED:
                try:
                    if self.be.fired():
                        info = self.be.begin()
                        if info["run_t_bad"]:
                            self.event(dict(ev="WARN", msg=f"RUN_T が START_AT + 1 でないコア {info['run_t_bad']}"))
                        self.state = self.RUN
                        self.log("RUN")
                except Exception as e:
                    self.err = f"{type(e).__name__}: {e}"
                    self.log(traceback.format_exc())
                    self.event(dict(ev="ERROR", msg=self.err))
                    self._stop("ERROR")
                wait = 0.005
            else:
                wait = 0.1
                if self.drop["pending"] is not None:
                    self._flush_drop()                # 止まった後に残った DROP を、空きができたら置く
            if self.conn.poll(wait if self.state != self.RUN else 0):
                cmd = self.conn.recv()
                rep = self.handle(cmd)
                self.conn.send(rep)
                quit_ = bool(rep.get("quit"))
            if self.state == self.RUN:
                time.sleep(self.o.loop_sleep)
        gc.enable()
        if hasattr(self.be, "close"):
            self.be.close()                        # proj021 2-3a: PL が書き終えてからリングのバッファを返す

    def _rt(self):
        if self.o.cpu is not None:
            try:
                os.sched_setaffinity(0, {self.o.cpu})
            except OSError as e:
                self.log(f"CPU の固定ができない: {e}")
        if self.o.rt:
            try:
                os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(self.o.rt))
            except (OSError, AttributeError) as e:
                self.log(f"SCHED_FIFO にできない（{e}）。普通の優先度で続ける")


def main(conn, ring, opts):
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)   # 端末の Ctrl-C は親だけが受け、親が quit で止める（README）
    try:
        Acq(conn, ring, opts).run()
    except BaseException:
        traceback.print_exc()
