#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj017 — 時刻・設定番号・健全性の実機の判定（proj016 の T-0〜T-4 を 4 ADC × NW 窓に。README の F-0・F-1・F-2）

proj017 から: 窓は 4 ADC × NW（= 2）の全部（--ns は ADC の順・窓の順に並べた NS、既定 1,2,3,4,5,6,1,6）。
TP は 4 ADC とも同じ予約で TP_ARM する。T-2 は --t2-adc で全帯域（spec_core_0）につなぐ ADC を選ぶ（FULL_SEL）。

    sudo -E $(which python3) timetest.py --clkin 0 --ref 10 --t0                 # T-0: ID・PPS の間隔 256,000,000 ± 1（既定 120 s）
    sudo -E $(which python3) timetest.py --clkin 0 --ref 10 --t1 --seconds 1800  # T-1: 同時開始とダンプの開始のビートの連続
    sudo -E $(which python3) timetest.py --clkin 0 --ref 10 --t2 --t2-adc 0,1,2,3  # T-2（F-2）: 閉ループ（1PPS を 4 ADC にも分けて入れる）
    sudo -E $(which python3) timetest.py --clkin 0 --ref 10 --t3 --seconds 300   # T-3: 健全性のフラグを見ながら、PPS を抜く・基準を替える
    sudo -E $(which python3) timetest.py --clkin 0 --ref 10 --t4                 # T-4: RUN の間に SHIFT・CFG_ID を書いても、ダンプは変わらない

約束（src/time_core.v・src/dstamp.v・src/win_core.v の冒頭）:
  - コアの RUN は T = START_AT + 1 のクロック（RUN_T）。ダンプの DUMP_T = そのダンプの最初のフレームの最初のサンプルがコアに入ったビート
  - 全帯域は DUMP_T(k) − DUMP_T(0) = k·N·512 ちょうど。窓は k·N·L（L = 4096·2^(NS−1)）から z の出方の揺れ（sim で ≦ 数ビート）
  - DUMP_H: [0] PPS 来ていない / [1] 間隔の異常 / [2] グリッチ / [3] 原点なし / [4] ADC の振り切れ / [5] 入力の途切れ /
            [6] 窓の WRST と RUN の CFG_ID が違う / [14] 帳簿が上書きされた / [15] 帳簿が閉じていない
"""
import argparse
import os
import sys
import time

import numpy as np

import spectrometer as S
import window as W
from timebase import BEATS_PER_SEC, TimeCore, Timebase, TimebaseError, beats_to_ns

# 窓（win_core_0 の窓 w = 0x20000·w ＋ 下）
R_CFG, R_RUN_CFG, R_WRST_CFG = 0x94, 0x98, 0x9C
R_DUMP_T, R_DUMP_H, R_DUMP_CFG, R_RUN_T, R_RUN_SHIFT = 0xA0, 0xA8, 0xAC, 0xB0, 0xB8
CTRL_ARM, CTRL_DISARM, CTRL_ARM_WRST = 1 << 2, 1 << 3, 1 << 13
# ADC の共通（0x80000 ＋）
RA_TP_CTRL, RA_ANCH_F, RA_ANCH_T, RA_ANCH_ST, RA_TP_RUN_T, RA_OVR, RA_GAP = 0x10, 0x2C, 0x34, 0x3C, 0x40, 0x48, 0x4C
TP_RUN, TP_ARM, TP_DISARM, TP_ANCH = 1, 4, 8, 16
RA_TP_N, RA_TP_WP, RA_RING = 0x100, 0x108, 0x2000
# 全帯域（spec_core_0）
RS_CFG, RS_RUN_CFG, RS_DUMP_T, RS_DUMP_H, RS_DUMP_CFG, RS_RUN_T, RS_RUN_SHIFT = 0xC0, 0xC4, 0xC8, 0xD0, 0xD4, 0xD8, 0xE0
H_NAMES = {0: "PPS 来ていない", 1: "間隔の異常", 2: "グリッチ", 3: "原点なし", 4: "振り切れ", 5: "入力の途切れ", 6: "CFG 不一致",
           14: "帳簿の上書き", 15: "帳簿が閉じていない"}

log = S.log


def h_text(h):
    s = [n for b, n in H_NAMES.items() if h >> b & 1]
    return "なし" if not s else " / ".join(s)


class Core:
    """RUN と ダンプのメタを持つコア 1 個（窓・全帯域で番地が違うだけ）"""

    def __init__(self, name, mmio, base, regs, frame_beats, adc=None, widx=None):
        self.name, self.m, self.base, self.r, self.L = name, mmio, base, regs, frame_beats
        self.adc, self.widx = adc, widx

    def rd(self, a):
        return int(self.m.read(self.base + a)) & 0xFFFFFFFF

    def wr(self, a, v):
        self.m.write(self.base + a, int(v) & 0xFFFFFFFF)

    def rd64(self, a):
        lo = self.rd(a)
        return (self.rd(a + 4) << 32) | lo

    def meta(self):
        """seqlock（SEQ → 中身 → SEQ）"""
        for _ in range(5):
            s = self.rd(W.R_SEQ)
            m = dict(seq=s, k=self.rd(W.R_DUMP_K), n=self.rd(W.R_DUMP_N), f0=self.rd64(W.R_DUMP_F0_LO),
                     t=self.rd64(self.r["dump_t"]), h=self.rd(self.r["dump_h"]), cfg=self.rd(self.r["dump_cfg"]))
            if self.rd(W.R_SEQ) == s:
                return m
        raise RuntimeError(f"{self.name}: 読む間にダンプが閉じ続けた")


def open_all(ol, ns_list):
    """proj017: wms = ADC ごとの win_core_i の mmio（4 本）、wins = ADC の順・窓の順の全部の窓（4 × NW）"""
    tc = TimeCore(ol.time_core_0.mmio)
    wms = []
    nw = None
    for i in range(len(S.CHANS)):
        wm = getattr(ol, f"win_core_{i}").mmio
        if (int(wm.read(W.A_BASE + W.R_A_ID)) & 0xFFFFFFFF) != W.ID_ADC:
            log(f"ERROR: win_core_{i} の ADC の共通 ID {int(wm.read(W.A_BASE)):08x}（期待 {W.ID_ADC:08x}）"); sys.exit(1)
        n = int(wm.read(W.A_BASE + W.R_A_NW))
        if nw is not None and n != nw:
            log(f"ERROR: win_core_{i} の NW {n} が win_core_0 の {nw} と違う"); sys.exit(1)
        nw = n
        wms.append(wm)
    if len(ns_list) != len(wms) * nw:
        log(f"ERROR: --ns は {len(wms)} ADC × {nw} 窓 = {len(wms) * nw} 個（{len(ns_list)} 個が与えられた）"); sys.exit(1)
    wins = []
    for j, ns in enumerate(ns_list):
        i, w = divmod(j, nw)
        c = Core(f"{S.CHANS[i][0]} 窓 {w}", wms[i], W.WIN_STRIDE * w,
                 dict(cfg=R_CFG, run_cfg=R_RUN_CFG, dump_t=R_DUMP_T, dump_h=R_DUMP_H, dump_cfg=R_DUMP_CFG, run_t=R_RUN_T),
                 4096 << (ns - 1), adc=i, widx=w)
        c.ns = ns
        if c.rd(W.R_ID) != W.ID_WIN:
            log(f"ERROR: {c.name} の ID {c.rd(W.R_ID):08x}（期待 {W.ID_WIN:08x}）"); sys.exit(1)
        if c.rd(0x90) != w:
            log(f"ERROR: {c.name} の WIDX {c.rd(0x90)}"); sys.exit(1)
        wins.append(c)
    sm = ol.spec_core_0.mmio
    full = Core("全帯域", sm, 0, dict(cfg=RS_CFG, run_cfg=RS_RUN_CFG, dump_t=RS_DUMP_T, dump_h=RS_DUMP_H, dump_cfg=RS_DUMP_CFG,
                                     run_t=RS_RUN_T), 512)
    if (full.rd(W.R_ID) & S.ID_MASK) != S.ID_EXPECT:
        log(f"ERROR: spec_core_0 の ID {full.rd(W.R_ID):08x}"); sys.exit(1)
    return tc, wms, wins, full


def select_full(wms, full, adc):
    """全帯域（spec_core_0）を ADC adc につなぎ、SRST で起動し直す（window.open_full と同じ手順）"""
    wms[0].write(W.A_BASE + W.R_A_FULL_SEL, adc)
    if (int(wms[0].read(W.A_BASE + W.R_A_FULL_SEL)) & 3) != adc:
        raise RuntimeError("FULL_SEL が書けない")
    time.sleep(0.01)
    full.wr(S.R_CTRL, S.CTRL_SRST)
    time.sleep(0.1)
    log(f"全帯域: spec_core_0 を FULL_SEL = {adc}（{S.CHANS[adc][0]}）につないで SRST")


def tp_run_t(wm):
    return int(wm.read(W.A_BASE + RA_TP_RUN_T)) | (int(wm.read(W.A_BASE + RA_TP_RUN_T + 4)) << 32)


# proj017: 時刻の格子（BITS.md）。WRST・RUN・TP_ARM の START_AT は G の倍数に置く。窓のフレーム長 L = 2^(11+NS) は G を割り切り、
#   wspec_core が F0 を (⌊fin / M⌋ + 2)·M（M = G / L）に寄せるので、WSTART が揃った窓どうしはダンプの区切りがサンプルの時刻で揃う
G_BEATS = 1 << 19                # 524,288 ビート = 2.048 ms
R_WSTART, R_WCUR = 0x8C, 0x64


def start_at_grid(tb, lead_s=2, offset=0):
    """錨の PPS ＋ (lead_s + 1) 秒より後の、最初の格子の点（＋ offset。offset ≠ 0 は陽性対照用）"""
    p = tb.check()
    t = p["stamp"] + (lead_s + 1) * BEATS_PER_SEC
    return -(-t // G_BEATS) * G_BEATS + offset


def wrst_on_grid(tc, tb, wins, full, wms, ns_list, if_c, cfg, offset=0, only=None):
    """窓の設定を書き、ARM_WRST で格子の START_AT に一斉に WRST する。WSTART（窓の始まりのビート）が ADC の中で全窓同じことを照合。
    only = 窓の添字のリスト（陽性対照: その窓だけを offset のずれた START_AT で WRST し直す）。戻り値: START_AT、窓ごとの WSTART"""
    sel = list(range(len(wins))) if only is None else list(only)
    for j in sel:
        c, ns = wins[j], ns_list[j]
        _, k, dphi, ns_, _ = W.window_params(if_c, 512.0 / (1 << ns))
        c.wr(W.R_WK, k); c.wr(W.R_WDPHI, dphi); c.wr(W.R_WNS, ns_)
        c.wr(R_CFG, cfg)
        c.wr(W.R_CTRL, CTRL_ARM_WRST)
        c.want = (k, dphi, ns_)
    sa = start_at_grid(tb, lead_s=1, offset=offset)
    arm_tc(tc, wins, full, wms, sa)
    t_e = time.time() + 5.0
    while not tc.status()["fired"]:
        if time.time() > t_e:
            raise TimebaseError("ARM_WRST の発火が来ない")
        time.sleep(0.01)
    time.sleep(0.01)
    for j in sel:
        c = wins[j]
        while c.rd(W.R_CTRL) & (1 << 4):
            time.sleep(0.001)
        cur = c.rd(R_WCUR)
        k, dphi, ns_ = c.want
        if (cur & 31) != k or ((cur >> 8) & 15) != ns_ or c.rd(0x68) != dphi:
            raise RuntimeError(f"{c.name}: WRST の後の WCUR {cur:#x} が書いた値（k {k}・NS {ns_}）と違う")
    ws = [wins[j].rd(R_WSTART) for j in range(len(wins))]
    log(f"  WRST: START_AT {sa}（格子 {sa // G_BEATS}·G{f' ＋ {offset}' if offset else ''}）/ WSTART " +
        " / ".join(f"{c.name} {w_}" for c, w_ in zip(wins, ws)))
    for i in range(len(wms)):
        wi = [ws[j] for j in range(len(wins)) if wins[j].adc == i]
        if len(set(wi)) != 1 and only is None:
            raise RuntimeError(f"{S.CHANS[i][0]}: 窓の WSTART が揃っていない {wi}")
    return sa, ws


def setup_windows(wins, ns_list, if_c, cfg):
    """窓 w を IF if_c の中心・幅 512/2^NS で WRST（CFG_ID = cfg）"""
    for c, ns in zip(wins, ns_list):
        w_mhz = 512.0 / (1 << ns)
        _, k, dphi, ns_, _ = W.window_params(if_c, w_mhz)
        c.wr(R_CFG, cfg)
        wn = W.Win(c.m, base=c.base)
        wn.set_window(k, dphi, ns_)


def start_at_next_second(tb, lead_s=2):
    """次の PPS ＋ lead_s 秒のビート（錨の PPS のスタンプから整数秒）"""
    p = tb.check()
    return p["stamp"] + (lead_s + 1) * BEATS_PER_SEC


def disarm_all(wins, full, wms):
    """コアの側の予約を消す。**time_core の取り消し・「遅すぎ」ではコアの ARM は消えない**（次の無関係な発火で走ってしまう）"""
    for c in wins:
        c.wr(W.R_CTRL, CTRL_DISARM)
    full.wr(W.R_CTRL, CTRL_DISARM)
    for wm in wms:
        wm.write(W.A_BASE + RA_TP_CTRL, TP_DISARM)


def arm_tc(tc, wins, full, wms, start_at):
    try:
        tc.arm(start_at)
    except TimebaseError:
        tc.wr(0x08, TimeCore.CTRL_CANCEL)
        disarm_all(wins, full, wms)
        raise


def arm_all(tc, wins, full, wms, start_at, tp=True, with_full=True):
    for c in wins:
        c.wr(W.R_CTRL, W.CTRL_CLR | CTRL_ARM)
    if with_full:
        full.wr(W.R_CTRL, W.CTRL_CLR | CTRL_ARM)
    if tp:
        for wm in wms:
            wm.write(W.A_BASE + RA_TP_CTRL, TP_ARM)
    arm_tc(tc, wins, full, wms, start_at)


# ---------------------------------------------------------------- T-0
def t0(tc, tb, seconds):
    log(f"T-0: PPS の間隔を {seconds} 秒（TRIG・COMP の両系統）")
    c0 = tc.counters()
    log(f"  EPOCH {c0['epoch']} / 状態 {tc.status()}")
    last = {"trig": None, "comp": None}
    bad = 0
    ints = {"trig": [], "comp": []}
    t_end = time.time() + seconds
    while time.time() < t_end:
        time.sleep(0.5)
        for path in ("trig", "comp"):
            p = tc.pps(path)
            if last[path] is not None and p["count"] != last[path]["count"]:
                if p["count"] - last[path]["count"] != 1:
                    log(f"  NG {path}: 数が {p['count'] - last[path]['count']} 進んだ（0.5 s おきに読んで）"); bad += 1
                ints[path].append(p["interval"])
                if abs(p["interval"] - BEATS_PER_SEC) > 1:
                    log(f"  NG {path}: 間隔 {p['interval']}（{p['interval'] - BEATS_PER_SEC:+d} ビート）"); bad += 1
            last[path] = p
    c1 = tc.counters()
    for path in ("trig", "comp"):
        a = np.array(ints[path], dtype=np.int64) - BEATS_PER_SEC
        if len(a):
            log(f"  {path}: {len(a)} 個 / 間隔 − 1 秒: 平均 {a.mean():+.3f} / 最小 {a.min():+d} / 最大 {a.max():+d} ビート"
                f"（1 ビート = 3.906 ns。{len(a)} 秒で {a.sum():+d} ビート = {a.sum() / len(a) / BEATS_PER_SEC * 1e9:+.4f} ppb）")
        else:
            log(f"  NG {path}: PPS が 1 つも来ない"); bad += 1
    log(f"  GLITCH trig {c1['glitch_trig'] - c0['glitch_trig']} / comp {c1['glitch_comp'] - c0['glitch_comp']} / "
        f"BAD {c1['bad'] - c0['bad']} / MISS {c1['miss'] - c0['miss']} / EPOCH {c0['epoch']} → {c1['epoch']}")
    if c1["epoch"] != c0["epoch"]:
        bad += 1
    log(f"T-0: {'通過' if bad == 0 else f'失敗（{bad} 件）'}")
    return bad == 0


# ---------------------------------------------------------------- T-1
def t1(tc, tb, wins, full, wms, ns_list, seconds, tint, out=None):
    log(f"T-1（F-1）: 窓 {len(wins)}・TP {len(wms)}・全帯域を同時に開始し、{seconds} 秒のダンプの開始のビートの連続を見る（積分 {tint} s）")
    n_w = [max(1, int(round(tint * BEATS_PER_SEC / c.L))) for c in wins]
    n_f = max(1, int(round(tint * BEATS_PER_SEC / 512)))
    for c, n in zip(wins, n_w):
        c.wr(W.R_NACC, n); c.wr(W.R_NDUMP, 0); c.wr(W.R_SHIFT, 4)
    full.wr(W.R_NACC, n_f); full.wr(W.R_NDUMP, 0); full.wr(W.R_SHIFT, 4)
    sa = start_at_grid(tb)                        # proj017: 格子の点（窓の WRST も格子で済ませてある: main の wrst_on_grid）
    arm_all(tc, wins, full, wms, sa)
    log(f"  START_AT = {sa}（格子 {sa // G_BEATS}·G、UTC {tb.beat_utc_ns(sa) / 1e9:.6f}）")
    while not tc.status()["fired"]:
        time.sleep(0.05)
    bad = 0
    if tc.fired_at() != sa:
        log(f"  NG FIRED {tc.fired_at()}（START_AT {sa}）"); bad += 1
    runts = [c.rd64(c.r["run_t"]) for c in wins] + [full.rd64(full.r["run_t"])] + [tp_run_t(wm) for wm in wms]
    names = [c.name for c in wins] + ["全帯域"] + [f"TP {S.CHANS[i][0]}" for i in range(len(wms))]
    log("  RUN_T: " + " / ".join(f"{n} {t - sa:+d}" for n, t in zip(names, runts)) + f"（START_AT との差。期待 +1、{len(runts)} コア）")
    if any(t != sa + 1 for t in runts):
        log("  NG: RUN を受けたビートが揃っていない"); bad += 1
    cores = wins + [full]
    ns_of = ns_list + [None]
    nn = n_w + [n_f]
    rec = {c.name: [] for c in cores}
    seq = {c.name: c.rd(W.R_SEQ) for c in cores}
    t_end = time.time() + seconds
    while time.time() < t_end:
        time.sleep(min(0.02, tint / 4))
        for c in cores:
            s = c.rd(W.R_SEQ)
            if s != seq[c.name]:
                if s - seq[c.name] != 1 and seq[c.name] is not None and rec[c.name]:
                    log(f"  NOTE {c.name}: ダンプを {s - seq[c.name] - 1} 個読み落とした")
                m = c.meta()
                seq[c.name] = m["seq"]
                rec[c.name].append((m["k"], m["f0"], m["t"], m["h"], m["cfg"]))
    for c, ns, n in zip(cores, ns_of, nn):
        r = np.array(rec[c.name], dtype=np.int64)
        if len(r) < 2:
            log(f"  NG {c.name}: ダンプが {len(r)} 個"); bad += 1; continue
        k, t, h = r[:, 0], r[:, 2], r[:, 3]
        dev = (t - t[0]) - (k - k[0]) * n * c.L
        hs = np.bitwise_or.reduce(h)
        tol = 0 if ns is None else 16
        ok = np.all(np.abs(dev) <= tol) and not (hs >> 14 & 3)
        log(f"  {c.name}: {len(r)} 個 / N {n} × L {c.L} / DUMP_T の k·N·L からのずれ 最小 {dev.min():+d} 最大 {dev.max():+d} ビート"
            f"（許容 ±{tol}）/ 健全性の OR: {h_text(int(hs))} {'OK' if ok else 'NG'}")
        if not ok:
            bad += 1
    if out:
        np.savez(out, **{f"core{i}": np.array(rec[c.name], dtype=np.int64) for i, c in enumerate(cores)}, start_at=sa,
                 names=np.array([c.name for c in cores]))
        log(f"  記録: {out}")
    for c in cores:
        c.wr(W.R_CTRL, W.CTRL_STOP)
    log(f"T-1: {'通過' if bad == 0 else f'失敗（{bad} 件）'}")
    return bad == 0


# ---------------------------------------------------------------- T-2
def _wait_T(tc, t_target, timeout=5.0):
    t_end = time.time() + timeout
    while tc.t() < t_target:
        if time.time() > t_end:
            raise TimebaseError(f"T が {t_target} に届かない（今 {tc.t()}）")
        time.sleep(0.0005)


def _stamp_of(tc, path, edge_pred):
    """予言した縁 edge_pred の実際のスタンプ（予言 ± 16 ビートの内でなければ例外）"""
    p = tc.pps(path)
    if abs(p["stamp"] - edge_pred) > 16:
        raise TimebaseError(f"PPS のスタンプ {p['stamp']} が予言 {edge_pred} と合わない（{p['stamp'] - edge_pred:+d}）")
    return p["stamp"]


def t2(tc, tb, wins, full, wms, path="trig", n_trial=5, if_c=2200.0, out=None, adc=0):
    """閉ループ: 1PPS を ADC_A にも分けて入れ、PPS の縁が窓 0（NS 1、z = 1 ビート）・TP（50 µs の区切り）に出る位置をスタンプと比べる。

    **縁が見えていることを先に確かめる**（|z| の山 / 中央値 ≧ 10。見えなければ位置を判定しない。argmax は雑音でも何かを返す）。
    縁の z は PFB・DDC の群遅延のぶん遅れて山になる（D(1) = 57.6 ビート、重心）。窓の IF は低いほど縁のエネルギーが大きい（既定 2200 MHz）。
    出す量: 山の位置の T − D(1) − スタンプ ＝（ADC → コアの入口）−（PPS の縁 → スタンプ）＋（2 本のケーブルの長さの差）"""
    from timebase import WIN_DELAY_BEATS
    lbl = S.CHANS[adc][0]
    wm = wms[adc]
    select_full(wms, full, adc)
    log(f"T-2（{lbl}）: 閉ループ（1PPS を {lbl} にも入れておくこと）。{n_trial} 回ずつ: (a) 全帯域の生サンプル (b) 窓 0（NS 1・IF {if_c} MHz）(c) TP")
    # (a) 全帯域（spec_core_0）のスナップショット = 1 フレーム 8192 サンプル（512 ビート = 2 µs）の**生の ADC 値**。フィルタを通らないので
    #     縁のサンプルがそのまま読める（proj008 の閉ループの型）。フレームは 512 ビートで 1 s = 500,000 フレームちょうどなので、
    #     フレームの位相（DUMP_T mod 512）は PPS に対して動かない → 1 回測って、縁（の見当）を含むフレームを狙う
    sp = S.Spec(full.m, idx=adc, label=lbl)
    full.wr(W.R_NACC, 1); full.wr(W.R_NDUMP, 1); full.wr(W.R_SHIFT, 7)
    seq0 = full.rd(W.R_SEQ)
    full.wr(W.R_CTRL, W.CTRL_CLR | W.CTRL_RUN)
    t_e = time.time() + 1.0
    while full.rd(W.R_SEQ) == seq0 and time.time() < t_e:
        time.sleep(0.001)
    phi = full.meta()["t"] % 512
    L0 = 55                                  # 縁 → コアの入口の見当（ビート）。外れていても縁はフレームの中に入る（± 100 ビートまで）
    offs_f, raws = [], []
    for k in range(n_trial):
        p = tb.check()
        edge = p["stamp"] + 2 * BEATS_PER_SEC
        te = edge + L0
        S0 = te - ((te - phi) % 512)         # 縁（の見当）を含むフレームの頭。フレーム内の位置は位相で決まり、選べない
        full.wr(W.R_CTRL, W.CTRL_CLR | CTRL_ARM)
        seq0 = full.rd(W.R_SEQ)
        arm_tc(tc, wins, full, wms, S0 - 769)  # RUN（START_AT + 1）は S0 − 768 = 1.5 フレーム前 → F0 = fin + 2 の頭が S0
        _wait_T(tc, edge + BEATS_PER_SEC // 10)
        if full.rd(W.R_SEQ) == seq0:
            log(f"  NG (a) 試行 {k}: 全帯域のダンプが閉じない"); return False
        st = _stamp_of(tc, path, edge)
        m, _, snap = sp.read_dump(with_snap=True)
        x = (snap.astype(np.int64) >> 2).astype(float)
        x -= np.median(x[:1024])
        sig = 1.4826 * float(np.median(np.abs(x[:1024]))) or 1.0
        snr = float(np.max(np.abs(x))) / sig
        dt = full.rd64(RS_DUMP_T)
        raws.append(dict(x=snap, dump_t=dt, stamp=st))
        if dt != S0:
            log(f"    注意: DUMP_T {dt} が狙った S0 {S0} と違う（{dt - S0:+d}）")
        if not (32 <= (edge + L0 - S0) < 480):
            log(f"    注意: 縁の見当がフレームの端（{edge + L0 - S0} ビート目）。L0 が外れていると縁がフレームの外に出る")
        if snr < 20:
            log(f"  (a) 試行 {k}: **縁が見えない**（最大 / σ = {snr:.1f} < 20）")
            continue
        i_e = int(np.argmax(np.abs(x) > 0.5 * np.max(np.abs(x))))     # 最大の半分を初めて越えたサンプル
        off = (dt + i_e / 16.0) - st
        offs_f.append(off)
        log(f"  (a) 試行 {k}: 縁のサンプル {i_e}（ビート {i_e / 16:.2f}、最大 / σ {snr:.0f}）→ 縁がコアに入った T − スタンプ = {off:+.2f} ビート"
            f"（{off * 3.90625:+.1f} ns）")
    if len(offs_f) >= 2:
        o_ = np.array(offs_f)
        log(f"  (a) 全帯域（{lbl}）: {len(o_)} 回 / 平均 {o_.mean():+.2f}・標準偏差 {o_.std():.2f}・最小 {o_.min():+.2f}・最大 {o_.max():+.2f} ビート"
            f"（平均 {o_.mean() * 3.90625:+.1f} ns・σ {o_.std() * 3.90625:.1f} ns）")
    else:
        log("  (a) 全帯域: 縁が見えた試行が 2 回に満たない")
    c = [w_ for w_ in wins if w_.adc == adc and w_.widx == 0][0]
    setup_windows([c], [1], if_c, 0)
    wm.write(W.A_BASE + W.R_A_SNAP_SEL, 0)
    c.wr(W.R_NACC, 1); c.wr(W.R_NDUMP, 1); c.wr(W.R_SHIFT, 7)
    wn = W.Win(c.m, base=c.base)
    d1 = WIN_DELAY_BEATS[1]
    offs, snaps = [], []
    # 窓のフレーム（4096 ビート）も 1 s = 62,500 フレームちょうどで位相は PPS に対して動かない → (a) と同じく位相を 1 回測って狙う
    #   （2026-10-02 の 3 回目: 縁の 6000 ビート前に RUN、では頭のフレームが縁の 1443 ビート後に来た。RUN から頭までは 1〜2 フレームで揺れる）
    seq0 = c.rd(W.R_SEQ)
    c.wr(W.R_CTRL, W.CTRL_CLR | W.CTRL_RUN)
    t_e = time.time() + 1.0
    while c.rd(W.R_SEQ) == seq0 and time.time() < t_e:
        time.sleep(0.001)
    phw = c.meta()["t"] % 4096
    for k in range(n_trial):
        p = tb.check()
        edge = p["stamp"] + 2 * BEATS_PER_SEC
        te = edge + 31 + int(round(d1))                  # 縁が z に出る見当 = スタンプ ＋ M ＋ D(1)
        S0 = te - ((te - phw) % 4096)
        c.wr(W.R_CTRL, W.CTRL_CLR | CTRL_ARM)
        arm_tc(tc, wins, full, wms, S0 - 6145)            # RUN（START_AT + 1）は S0 − 6144 = 1.5 フレーム前 → F0 の頭が S0
        seq0 = c.rd(W.R_SEQ)
        _wait_T(tc, edge + BEATS_PER_SEC // 10)
        if c.rd(W.R_SEQ) == seq0:
            log(f"  NG 試行 {k}: 窓 0 のダンプが閉じない"); return False
        st = _stamp_of(tc, path, edge)
        m = c.meta()
        z = wn.block(W.SNAP_BASE, 2 * 4096).view(np.int32)
        z = z[0::2] + 1j * z[1::2]
        a = np.abs(z)
        med = float(np.median(a)) or 1.0
        j_pk = int(np.argmax(a))
        snr = float(a[j_pk]) / med
        lead = st - m["t"]
        snaps.append(dict(z=z, dump_t=m["t"], stamp=st))
        if snr < 10:
            log(f"  試行 {k}: **縁が見えない**（山 / 中央値 = {snr:.1f} < 10）。位置は判定しない（DUMP_T は縁の {lead} ビート前）")
            continue
        off = m["t"] + j_pk - d1 - st
        offs.append(off)
        log(f"  試行 {k}: DUMP_T は縁の {lead} ビート前 / |z| の山 j = {j_pk}（山 / 中央値 {snr:.0f}）"
            f" → 山の T − D(1) − スタンプ = {off:+.1f} ビート（{off * 3.90625:+.0f} ns）")
        if not (0 < lead < 4096):
            log("    注意: 縁がダンプの頭のフレームの外")
    ok = len(offs_f) >= 2
    if len(offs) >= 2:
        o_ = np.array(offs)
        log(f"  窓 0: {len(o_)} 回 / 平均 {o_.mean():+.1f} ・ 標準偏差 {o_.std():.1f} ・ 最小 {o_.min():+.1f} ・ 最大 {o_.max():+.1f} ビート"
            f"（平均 {o_.mean() * 3.90625:+.0f} ns）。**揃っていれば本物、散っていれば雑音**")
    else:
        log("  窓 0: 縁が見えた試行が 2 回に満たない（判定は (a) で行う。窓は参考）")
    # (b) TP: TP_N = 25（1 区切り = 25 ADC フレーム = 50 µs）。縁の 5 ms 前から。縁の 2 ms 後に、最新の 128 個（6.4 ms）を読む
    wm.write(W.A_BASE + RA_TP_N, 25)
    p = tb.check()
    edge = p["stamp"] + 2 * BEATS_PER_SEC
    wm.write(W.A_BASE + RA_TP_CTRL, TP_ARM)
    arm_tc(tc, wins, full, wms, edge - 100 * 25 * 512)
    _wait_T(tc, edge + 2 * BEATS_PER_SEC // 1000)
    wp = int(wm.read(W.A_BASE + RA_TP_WP))
    ring = np.array([[int(wm.read(W.A_BASE + RA_RING + 16 * (i % 512) + 4 * j)) for j in range(4)] for i in range(wp - 128, wp)],
                    dtype=np.int64)
    wp2 = int(wm.read(W.A_BASE + RA_TP_WP))
    st = _stamp_of(tc, path, edge)
    wm.write(W.A_BASE + RA_TP_CTRL, TP_ANCH)
    time.sleep(0.01)
    af = int(wm.read(W.A_BASE + RA_ANCH_F)); at = int(wm.read(W.A_BASE + RA_ANCH_T)) | (int(wm.read(W.A_BASE + RA_ANCH_T + 4)) << 32)
    pw = (ring[:, 0] | (ring[:, 1] << 32)) / np.maximum(ring[:, 3] & 0xFFFFFF, 1)
    f = ring[:, 2]
    med = float(np.median(pw)) or 1.0
    i_pk = int(np.argmax(pw))
    d_f = ((int(f[i_pk]) - (af & 0xFFFFFFFF) + 2**31) % 2**32) - 2**31     # リングの語 2 はフレーム番号の下位 32 bit
    t_reg = at + d_f * 512
    log(f"  TP: 読む間に {wp2 - wp} 個進んだ（512 個の輪）/ 1 フレームあたりの和が最大の区切り: 山 / 中央値 {pw[i_pk] / med:.2f}・"
        f"区切りの頭の T − スタンプ = {t_reg - st:+d} ビート（{beats_to_ns(t_reg - st) / 1000:+.1f} µs。区切り 50 µs）")
    if pw[i_pk] / med < 1.05:
        log("  TP: 縁が見えない（和の山が中央値の 1.05 倍未満）")
    for i in range(max(0, i_pk - 4), min(len(pw), i_pk + 4)):
        d_i = ((int(f[i]) - (af & 0xFFFFFFFF) + 2**31) % 2**32) - 2**31
        log(f"    区切りの頭の T − スタンプ {at + d_i * 512 - st:+8d} ビート（{beats_to_ns(at + d_i * 512 - st) / 1000:+7.1f} µs）: 和 / 中央値 {pw[i] / med:8.2f}")
    wm.write(W.A_BASE + RA_TP_N, 512)            # proj017: 既定の 1.024 ms に戻す
    if out:
        np.savez(out + f".t2-{lbl}.npz", raw=np.array([r_["x"] for r_ in raws]), raw_dump_t=np.array([r_["dump_t"] for r_ in raws]),
                 raw_stamp=np.array([r_["stamp"] for r_ in raws]),
                 z=np.array([s_["z"] for s_ in snaps]), dump_t=np.array([s_["dump_t"] for s_ in snaps]),
                 stamp=np.array([s_["stamp"] for s_ in snaps]), tp=ring, tp_anchor=np.array([af, at]), d1=d1, if_c=if_c)
        log(f"  記録: {out}.t2-{lbl}.npz")
    return ok


# ---------------------------------------------------------------- T-3
def t3(tc, tb, wins, full, wms, seconds, tint):
    log(f"T-3: {seconds} 秒、ダンプごとの健全性を出す（その間に PPS を抜く・10 MHz を替える・SG を上げる・Overlay を読み直す、など）")
    c = full
    n = max(1, int(round(tint * BEATS_PER_SEC / 512)))
    c.wr(W.R_NACC, n); c.wr(W.R_NDUMP, 0); c.wr(W.R_SHIFT, 4)
    c.wr(W.R_CTRL, W.CTRL_CLR | W.CTRL_RUN)
    seq = c.rd(W.R_SEQ)
    t0_ = time.time()
    prev = None
    counts = {}
    while time.time() - t0_ < seconds:
        time.sleep(tint / 4)
        s = c.rd(W.R_SEQ)
        if s == seq:
            continue
        seq = s
        m = c.meta()
        for b in H_NAMES:
            if m["h"] >> b & 1:
                counts[b] = counts.get(b, 0) + 1
        if m["h"] != prev:
            log(f"  {time.time() - t0_:8.1f} s  ダンプ {m['k']}: 健全性 {m['h']:04x}（{h_text(m['h'])}）")
            prev = m["h"]
    c.wr(W.R_CTRL, W.CTRL_STOP)
    log("T-3: 立ったダンプの数: " + (" / ".join(f"{H_NAMES[b]} {n}" for b, n in sorted(counts.items())) or "なし")
        + "（" + " / ".join(f"{S.CHANS[i][0]} OVR_CNT {int(wm.read(W.A_BASE + RA_OVR))}・GAP_CNT {int(wm.read(W.A_BASE + RA_GAP))}"
                            for i, wm in enumerate(wms)) + f" / time_core {tc.counters()}）")
    return True


# ---------------------------------------------------------------- T-4
def t4(tc, tb, wins, full, wms, ns_list):
    log("T-4: RUN の間に SHIFT・CFG_ID を書き換えても、その RUN のダンプは RUN の時点の値")
    bad = 0
    for c in (wins[0], full):
        n = max(1, int(round(0.1 * BEATS_PER_SEC / c.L)))
        c.wr(c.r["cfg"], 0x1234)
        c.wr(W.R_NACC, n); c.wr(W.R_NDUMP, 0); c.wr(W.R_SHIFT, 4)
        c.wr(W.R_CTRL, W.CTRL_CLR | W.CTRL_RUN)
        seq = c.rd(W.R_SEQ)
        sums = []
        cfgs = []
        wn = W.Win(c.m, base=c.base) if c is not full else None
        for i in range(8):
            if i == 3:
                c.wr(W.R_SHIFT, 2); c.wr(c.r["cfg"], 0x9999)          # RUN の間に書く
                log(f"  {c.name}: ダンプ 3 の前に SHIFT 4 → 2・CFG_ID 0x1234 → 0x9999 を書いた")
            t_e = time.time() + 1.0
            while c.rd(W.R_SEQ) == seq and time.time() < t_e:
                time.sleep(0.005)
            seq = c.rd(W.R_SEQ)
            m = c.meta()
            if wn is not None:
                w = wn.block(W.SPEC_BASE, 2 * 4096)
                sp = w[0::2].astype(np.uint64) | (w[1::2].astype(np.uint64) << np.uint64(32))
            else:
                sp = None
            sums.append(float(sp.sum()) if sp is not None else float("nan"))
            cfgs.append(m["cfg"])
        rs = c.rd(RS_RUN_SHIFT if c is full else R_RUN_SHIFT)
        ok = all(x == 0x1234 for x in cfgs) and rs == 4
        if sp is not None:
            r = np.array(sums) / np.median(sums)
            ok = ok and np.all(np.abs(r - 1) < 0.05)        # SHIFT が 2 に変われば 16 倍
            log(f"  {c.name}: ダンプの和の比 {np.round(r, 3).tolist()}")
        log(f"  {c.name}: DUMP_CFG {[hex(x) for x in cfgs]} / RUN_SHIFT {rs} → {'OK' if ok else 'NG'}")
        bad += not ok
        c.wr(W.R_CTRL, W.CTRL_STOP)
        c.wr(W.R_SHIFT, 4)
    log(f"T-4: {'通過' if bad == 0 else f'失敗（{bad} 件）'}")
    return bad == 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=S.BITFILE)
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--path", default="trig", choices=("trig", "comp"), help="錨・健全性に使う PPS の系統")
    p.add_argument("--ns", default="1,2,3,4,5,6,1,6",
                   help="窓の NS（幅 512/2^NS MHz）。ADC の順・窓の順に 4 × NW 個（既定は SAM45-Fine の 6 幅を全部と 256・8 MHz をもう 1 つずつ）")
    p.add_argument("--if", dest="if_c", type=float, default=3000.0)
    p.add_argument("--seconds", type=float, default=120.0)
    p.add_argument("--tint", type=float, default=0.04096, help="積分時間 [s]（proj017: 2.048 ms の倍数。40.96 ms）")
    p.add_argument("--out", default=None)
    p.add_argument("--t2-n", type=int, default=5, help="T-2 の試行の回数")
    p.add_argument("--t2-if", type=float, default=2200.0, help="T-2 の窓 0 の IF の中心 [MHz]（低いほど縁が強い）")
    p.add_argument("--t2-adc", default="0", help="T-2 で閉ループを測る ADC（0..3 = ADC_A..D、カンマ区切りで順に）")
    for t in ("t0", "t1", "t2", "t3", "t4"):
        p.add_argument(f"--{t}", action="store_true")
    a = p.parse_args()
    ns_list = [int(x) for x in a.ns.split(",")]
    if a.out:
        # **測る前に書けることを確かめる**（2026-10-02、30 分の T-1 の最後に runs/ が無くて記録を失った）
        d = os.path.dirname(a.out) or "."
        os.makedirs(d, exist_ok=True)
        if not os.access(d, os.W_OK):
            log(f"ERROR: {d} に書けない"); sys.exit(1)

    from pynq import Overlay
    import xrfdc                                   # Overlay() より前に import する（VERSIONS.md）
    S.setup_clocks(a.clkin, a.ref)
    ol = Overlay(a.bitfile)
    log(f"Overlay: {a.bitfile}")
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    S.check_tiles(ol.rfdc, 2)
    if a.settle > 0:
        time.sleep(a.settle)
    tc, wms, wins, full = open_all(ol, ns_list)
    tc.configure(src=a.path, tol=1)
    tb = Timebase(tc, path=a.path)
    ok = True
    if a.t0:
        ok &= t0(tc, tb, a.seconds)
    if a.t1 or a.t2 or a.t3 or a.t4:
        try:
            anc = tb.anchor()
        except TimebaseError as e:
            log(f"ERROR: 錨を打てない: {e}"); sys.exit(1)
        log(f"錨: UTC {anc['utc_sec']} 秒 = スタンプ {anc['stamp']}（PPS {anc['count']} 個目、EPOCH {anc['epoch']}）/ 精度 {tb.accuracy()}")
        wrst_on_grid(tc, tb, wins, full, wms, ns_list, a.if_c, 0x0017_0001)   # proj017: 格子の START_AT で一斉に WRST
    if a.t1:
        ok &= t1(tc, tb, wins, full, wms, ns_list, a.seconds, a.tint, a.out)
    if a.t2:
        for adc in [int(x) for x in a.t2_adc.split(",")]:
            ok &= t2(tc, tb, wins, full, wms, path=a.path, n_trial=a.t2_n, if_c=a.t2_if, out=a.out, adc=adc)
    if a.t3:
        ok &= t3(tc, tb, wins, full, wms, a.seconds, a.tint)
    if a.t4:
        ok &= t4(tc, tb, wins, full, wms, ns_list)
    log(f"総合: {'通過' if ok else '失敗'}")


if __name__ == "__main__":
    main()
