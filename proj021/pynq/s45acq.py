#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj018 — 取得のプロセス。PL（proj017 の bit）を持ち、8 窓のダンプと 4 ADC の TP を読み落としなく読み、記録にして溜まりに置く。

通信のプロセス（specd.py）とは、溜まり（s45ring）と命令のパイプ（辞書を送って辞書を受ける）だけでつながる。
読み出しの環は proj017 `fine.py` の F-4 と同じ（SEQ を見て閉じたダンプを seqlock で読む・TP のリングを TP_WP まで読む）。
違うのは、**記録を Python のリストに溜めない**こと（GC と伸びるリストが 1 周の最大を延ばす疑い。README）。

遅れの対策（README の方針）: GC を止める（gc.freeze の後 gc.disable）・CPU 1 つに固定・可能なら SCHED_FIFO。

裏（backend）は 2 つ: HwBackend（PYNQ・proj017 の bit）と FakeBackend（PL なしで同じ間隔・同じ形の記録を作る。通信の試験用）。
"""
import gc
import os
import time
import traceback

import numpy as np

import s45cal
import s45proto as P

BEATS_PER_SEC = 256_000_000
G_BEATS = 1 << 19                          # 時刻の格子 2.048 ms（BITS.md）
TP_N = 512                                 # 1.024 ms
TP_BEATS = TP_N * 512
TP_FLUSH = 40                              # TP をまとめて 1 記録にする区切りの数（40 × 1.024 ms = 40.96 ms）
TPF_RUN, TPF_OVR = 2, 16
ADC_NAMES = ("ADC_A", "ADC_B", "ADC_C", "ADC_D")
NW = 2
NS_OF_BW = {256: 1, 128: 2, 64: 3, 32: 4, 16: 5, 8: 6}
FLAGS_OK_MASK = 0x7EF                      # 窓の FLAGS で異常に数えるもの（[4] FFT IP に待たされた は正常。fine.py と同じ）
VERSION = "proj019-0.2"                 # proj019: SNAP（ADC の生サンプル）・LMX の出力の強さ


def default_settings():
    wins = []
    for i in range(4):
        wins.append(dict(if_mhz=3000.0, ns=1, shift=9))     # 窓 0: 256 MHz
        wins.append(dict(if_mhz=3000.0, ns=6, shift=9))     # 窓 1: 8 MHz
    return dict(tint=0.04096, cfg=0, wins=wins)


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
        t = a["utc_sec"] * 10**9 + int(_b2ns(int(beat) - a["stamp"])) - int(round(c["pps_det_ns"] or 0))
        v = c["adc_to_core_ns"]
        t -= int(round((v.get(adc) if isinstance(v, dict) else v) or 0))
        if ns is not None and ns in self.wd:
            t -= int(round(self.wd[ns] * 125 / 32))
        return t

    def utc_ns_arr(self, beats, adc=0):
        """utc_ns(beat, None, adc) を配列で（TP の区切り）"""
        a, c = self.tb._anchor, self.tb.cal
        v = c["adc_to_core_ns"]
        off = a["utc_sec"] * 10**9 - int(round(c["pps_det_ns"] or 0)) - int(round((v.get(adc) if isinstance(v, dict) else v) or 0))
        return off + _b2ns(np.asarray(beats, np.int64) - a["stamp"])

    def beat_of_utc_ns(self, utc_ns):
        a = self.tb._anchor
        return a["stamp"] + ((int(utc_ns) - a["utc_sec"] * 10**9) * 32) // 125


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
class HwBackend:
    def __init__(self, opts, log):
        self.o, self.log = opts, log
        self.running = False

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
        self.tc, self.wms, self.wins, self.full = T.open_all(self.ol, ns_list)   # ID の照合（窓・ADC の共通・全帯域）は open_all の中
        for wm in self.wms:
            prm = int(wm.read(W.A_BASE + S.R_TP_PARAM)) & 0xFFFFFFFF
            if prm != S.TP_PARAM_EXPECT:
                raise RuntimeError(f"TP_PARAM {prm:08x}（期待 {S.TP_PARAM_EXPECT:08x}）")
        self.tc.configure(src=self.o.path, tol=1)
        self.tb = TB.Timebase(self.tc, path=self.o.path)
        self.TpStream = make_tp_reader(S)
        self.ids = dict(win=f"{W.ID_WIN:08x}", adc=f"{W.ID_ADC:08x}", time=f"{TB.TimeCore.ID:08x}",
                        lmx_vco=f"{self.lmx['vco_mhz']:.2f}" if self.lmx else "7864.32",
                        lmx_pwr=str(self.lmx.get("outa_pwr", 31)) if self.lmx else "31")
        self.clock = Clock(None, TB.WIN_DELAY_BEATS)
        self.anchor()

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
        return -(-int(beat) // G_BEATS) * G_BEATS

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
            self.cfgs.append(dict(if_mhz=if_act, ns=ns, shift=ws["shift"], nacc=nacc_of(st["tint"], ns), g=g_of(ns)))
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
            if (cur & 31) != k or ((cur >> 8) & 15) != ns_ or c.rd(0x68) != dphi:
                raise RuntimeError(f"{c.name}: WRST の後の WCUR {cur:#x} が書いた値と違う")
            ws_.append(c.rd(T.R_WSTART))
        for i in range(4):
            wi = [ws_[j] for j in range(len(self.wins)) if self.wins[j].adc == i]
            if len(set(wi)) != 1:
                raise RuntimeError(f"{ADC_NAMES[i]}: 窓の WSTART が揃っていない {wi}")
        for c, cf in zip(self.wins, self.cfgs):
            c.wr(W.R_NACC, cf["nacc"]); c.wr(W.R_NDUMP, 0); c.wr(W.R_SHIFT, cf["shift"])
        for wm in self.wms:
            wm.write(W.A_BASE + T.RA_TP_N, TP_N)
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
        c = self.wins[j]
        s = c.rd(W.R_SEQ)
        if s == self.seq[j]:
            return None
        i0 = (c.base + W.SPEC_BASE) // 4
        for _ in range(5):
            m = c.meta()
            m["sat"] = c.rd(W.R_DUMP_SAT)
            m["flags"] = c.rd(W.R_FLAGS)
            w = np.array(c.m.array[i0:i0 + 2 * P.NCH], dtype=np.uint32)
            if c.rd(W.R_SEQ) == m["seq"]:
                miss = ((m["seq"] - self.seq[j]) & 0xFFFFFFFF) - 1
                self.seq[j] = m["seq"]
                return m, w.view("<u8"), miss
        raise RuntimeError(f"{c.name}: 読む間に毎回ダンプが閉じた（読み出しが積分に間に合わない）")

    def poll_tp(self, i):
        self.tps[i].poll()
        return self.tps[i]

    def tp_time(self, i, f):
        af, at = self.anch[i]
        return at + (f - af) * 512

    def snap(self, adc, n, nacc, timeout=5.0):
        """全帯域コア（spec_core_0）を ADC adc につないで N_ACC = nacc・N_DUMP = n で走らせ、ダンプごとの最初のフレームの
        生サンプル 8192 個を読む（IDLE のときだけ。窓・TP の RUN には触らない: specd は全帯域コアを RUN に入れていない）。
        戻り値 [(meta, int16 の 8192 個)]。SNAP_F ≠ DUMP_F0（別のフレームを読んだ）・読む間に閉じたものは読み直す"""
        S, T, W = self.S, self.T, self.W
        full = self.full
        T.select_full(self.wms, full, adc)
        full.wr(S.R_NACC, nacc)
        full.wr(S.R_NDUMP, n)
        seq = full.rd(W.R_SEQ)
        full.wr(S.R_CTRL, S.CTRL_CLR | S.CTRL_RUN)
        out = []
        t_end = time.time() + timeout + n * nacc * 2e-6
        i0 = S.SNAP_BASE // 4
        while len(out) < n:
            if time.time() > t_end:
                raise RuntimeError(f"SNAP: {len(out)}/{n} 個で時間切れ（全帯域コアのダンプが閉じない）")
            s = full.rd(W.R_SEQ)
            if s == seq:
                time.sleep(0.0005)
                continue
            for _ in range(5):
                m = full.meta()
                sf = full.rd(S.R_SNAP_F_LO) | (full.rd(S.R_SNAP_F_HI) << 32)
                w = np.array(full.m.array[i0:i0 + S.NFFT // 2], dtype=np.uint32)
                if full.rd(W.R_SEQ) == m["seq"]:
                    break
            else:
                raise RuntimeError("SNAP: 読む間に毎回ダンプが閉じた（every を長く）")
            if ((m["seq"] - seq) & 0xFFFFFFFF) != 1:
                raise RuntimeError(f"SNAP: ダンプを読み落とした（seq {seq} → {m['seq']}。every を長く）")
            if sf != m["f0"]:
                raise RuntimeError(f"SNAP: スナップショットのフレーム {sf} ≠ ダンプの最初 {m['f0']}")
            seq = m["seq"]
            x = np.empty(S.NFFT, np.int16)
            x[0::2] = (w & 0xFFFF).astype(np.uint16).view(np.int16)
            x[1::2] = (w >> 16).astype(np.uint16).view(np.int16)
            out.append((m, x))
        full.wr(S.R_CTRL, S.CTRL_STOP)
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
            return []
        for c in self.wins:
            c.wr(W.R_CTRL, W.CTRL_STOP)
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
        self.cfgs = [dict(if_mhz=ws["if_mhz"], ns=ws["ns"], shift=ws["shift"], nacc=nacc_of(st["tint"], ws["ns"]), g=g_of(ws["ns"]))
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
            t.n += 1; t.total += 1
            self.tp_next[i] += 1
        return t

    def tp_time(self, i, f):
        return self.sa + 1 + f * 512

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


# ================================================================ 取得の本体
class Acq:
    IDLE, ARMED, RUN, ERROR = "IDLE", "ARMED", "RUN", "ERROR"

    def __init__(self, conn, ring, opts):
        self.conn, self.ring, self.o = conn, ring, opts
        self.st = default_settings()
        self.state = self.IDLE
        self.seq = 0
        self.drop = dict(n=0, first=None, last=None, pending=None)
        self.err = None
        self.forced = False
        self.posctl = dict(corrupt=opts.posctl_corrupt, gap=opts.posctl_gap)
        self.hist = np.zeros(1001, np.int64)      # 1 周の時間（0.1 ms 刻み、100 ms で頭打ち）
        self.cal = getattr(opts, "tp_cal", None)    # TP の dBm の較正（s45cal、specd が起動時に読む）。bit の ID は open の後で照らす
        self.cal_msg = "較正ファイルが無い" if self.cal is None else "未確認"
        self.tp_last = [None] * 4                  # ADC ごとの直近の TP（σ_x²、最後に書き出した記録の平均）
        self._reset_counters()

    def log(self, *a):
        print("[acq]", *a, flush=True)

    def _reset_counters(self):
        self.n_dump = [0] * (4 * NW)
        self.n_miss = [0] * (4 * NW)
        self.kgap = [0] * (4 * NW)
        self.last_k = [None] * (4 * NW)
        self.h_or = 0
        self.fl_or = 0
        self.sat = 0
        self.loop_max = 0.0
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
        ok = (d["pending"] is None or rtype == P.T_EVENT) and self.ring.put([P.header(rtype, plen, crc, seq)] + list(payload_parts))
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
        if self.ring.put([P.header(P.T_EVENT, len(p), P.crc32(p), seq), p]):
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
                new = dict(tint=st["tint"], cfg=st["cfg"], wins=[dict(w) for w in st["wins"]])
                for k, v in cmd["kv"].items():
                    self._set1(new, k, v)
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

    def _set1(self, new, k, v):
        if k == "tint":
            new["tint"] = float(v)
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
                else:
                    raise ValueError(f"知らない窓の設定 {k}（if・ns・bw・shift）")

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
        self.state = self.ARMED
        try:
            sa = self.be.start(self.st, at_beat, force)
        except Exception:
            self.state = self.IDLE
            raise
        self.forced = force and not self.be.clock.ok
        self.start_at = sa
        self.ndump_target = int(cmd.get("n") or 0)
        utc = self.be.clock.utc_ns(sa)
        self.event(dict(ev="START", start_at=sa, utc_ns=utc, n=self.ndump_target, forced=self.forced, version=VERSION,
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
                    dumps=min(self.n_dump) if self.n_dump else 0, dumps_each=self.n_dump, miss=sum(self.n_miss), kgap=sum(self.kgap),
                    tp=[t.total for t in tps], tp_lost=sum(t.lost + t.overflow for t in tps), tp_bad=sum(t.bad_seq + t.bad_flag + t.bad_nfr for t in tps),
                    tp_ovr=sum(t.n_ovr for t in tps), health=self.h_or, flags=self.fl_or, sat=self.sat,
                    loop_max_ms=round(self.loop_max * 1e3, 2), loop_p99_ms=p99, loops=self.n_loop,
                    seq=self.seq, drop=self.drop["n"], ring_used=w - r, ring_cap=self.ring.cap, err=self.err, forced=self.forced,
                    tp_dbfs=[None if v is None else round(float(s45cal.dbfs(v)), 2) for v in self.tp_last],
                    tp_dbm=[None if v is None or self.cal is None else round(float(s45cal.dbm(v, self.cal, "ABCD"[i])), 2)
                            for i, v in enumerate(self.tp_last)])

    # ---- 読み出しの 1 周
    def _cal_pub(self):
        """START の EVENT・GET CAL に出す較正（使えないときは None）"""
        if self.cal is None:
            return None
        return {k: v for k, v in self.cal.items() if not k.startswith("_")} | {"file": self.cal.get("_file")}

    def _spec_record(self, j, m, spec):
        cf = self.be.cfgs[j]
        h = int(m["h"]) | (0 if self.be.clock.ok else P.H_NOTIME) | (P.H_FORCED if self.forced else 0)
        utc = self.be.clock.utc_ns(m["t"], cf["ns"], j // NW)
        hd = P.SPEC_H.pack(j // NW, j % NW, cf["ns"], cf["shift"], P.FMT_RAW, cf["g"], 0, m["cfg"], m["k"], cf["nacc"],
                           m["sat"], m["flags"], h, m["t"], utc, cf["if_mhz"])
        data = np.ascontiguousarray(spec[P.IF_ORDER])
        self._put(P.T_SPEC, [hd, data], P.crc32(hd, data))
        self.h_or |= int(m["h"]); self.fl_or |= int(m["flags"]) & FLAGS_OK_MASK; self.sat += int(m["sat"])

    def _flush_tp(self, i, final=False):
        t = self.be.tps[i]
        n = t.n
        if n == 0 or (n < TP_FLUSH and not final):
            return
        e = t.buf[:n].copy()
        self.tp_last[i] = float(np.mean(e["sum"].astype(np.float64) / (e["nfr"].astype(np.float64) * 8192.0)))
        e["t_beat"] = self.be.tp_time(i, e["t_beat"].astype(np.int64))      # フレームの番号 → ビート
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

    def _loop_once(self):
        ts = time.perf_counter()
        be = self.be
        for j in range(4 * NW):
            r = be.poll_win(j)
            if r is None:
                continue
            m, spec, miss = r
            self.n_miss[j] += miss
            if self.last_k[j] is not None and m["k"] != self.last_k[j] + 1:
                self.kgap[j] += 1
            self.last_k[j] = m["k"]
            self.n_dump[j] += 1
            self._spec_record(j, m, spec)
        for i in range(4):
            be.poll_tp(i)
            self._flush_tp(i)
        be.clock.poll()
        dt = time.perf_counter() - ts
        self.hist[min(1000, int(dt * 1e4))] += 1
        self.loop_max = max(self.loop_max, dt)
        self.n_loop += 1
        if self.ndump_target and min(self.n_dump) >= self.ndump_target:
            self._stop("n に達した")

    # ---- 本体
    def run(self):
        self._rt()
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
