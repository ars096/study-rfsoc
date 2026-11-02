#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj021 手順 2-4 — V2-f: INTERFACE 5.1 の見張り（r = DUMP_T − m·BASE が 1 回の RUN の中で一定 ±1）を、FULL と DDC の全部の流れで

ボードで root。**specd を止めてから**（リングの持ち主は 1 つ）。

    sudo -E $(which python3) s45v2f.py --clkin 0 --ref 10                       # 60 s × 2 RUN
    sudo -E $(which python3) s45v2f.py --clkin 0 --ref 10 --posctl              # 陽性対照: 途中で A0 を tint の格子 ＋ G で RUN し直す

手順: 8 窓を NS 1〜8（--ns）で G の格子に一斉に WRST、FULL は ADC_A。9 流れとも N_ACC = BASE / L・REC_CTRL = ALL、RUN の START_AT は T の tint の倍数（specd と同じ）。
リングの SPEC のレコードを流れごとに **s45acq.Bundler（specd と同じ見張りのコード）** に入れ、道具の側でも r の最小・最大・m の飛びを数える。

proj021 2-5: FULL の位置が RAW（KIND 4、SNAP のレコードだけ）の bit では、RAW は 5.1 の見張り（束ね）に入れず、
**DUMP_T の間隔 = N_ACC·512（= BASE）ちょうど**・SEQ の飛び 0 だけを見る（RAW の SNAP のレコードで）。
"""
import argparse
import sys
import time

import numpy as np

import s45core as SC
import spectrometer as S
import timetest as T
import window as W
from timebase import BEATS_PER_SEC, Timebase, TimebaseError

G = T.G_BEATS
TYPE_SPEC = 1


def log(*a):
    print(*a, flush=True)


TYPE_SNAP = 4


class Stream:
    def __init__(self, name, c, key, L, ns, raw=False):
        import s45acq as A
        self.name, self.c, self.key, self.L, self.ns = name, c, key, L, ns
        self.raw = raw                     # proj021 2-5: RAW（SNAP のレコードだけ。束ねない、DUMP_T の間隔だけ）
        self.nacc = A.BASE_BEATS // L
        self.A = A

    def reset(self, n_sum):
        self.b = self.A.Bundler(n_sum, self.nacc)
        self.rs, self.ms = [], []
        self.nbund = 0
        self.nbad_n = 0
        self.drops = []
        self.ts, self.seqs = [], []

    def add(self, hw, pay):
        m = self.A.rec_meta(hw)
        t = int(m["t"])
        if self.raw:
            self.ts.append(t); self.seqs.append(int(hw[1]) & 0xFFFFFFFF)
            if int(m["n"]) != self.nacc:
                self.nbad_n += 1
            return
        mi = (t + self.A.BASE_BEATS // 2) // self.A.BASE_BEATS
        self.rs.append(t - mi * self.A.BASE_BEATS)
        self.ms.append(mi)
        if int(m["n"]) != self.nacc:
            self.nbad_n += 1
        out, dropped = self.b.add(m, pay)
        if out is not None:
            self.nbund += 1
        if dropped is not None:
            self.drops.append(dropped)

    def summary_raw(self):
        ts = np.array(self.ts, np.int64)
        sq = np.array(self.seqs, np.int64)
        d = np.diff(ts) - self.nacc * 512 if len(ts) > 1 else np.zeros(0, np.int64)
        return dict(n=len(ts), dev=int(np.abs(d).max()) if len(d) else None, gaps=int(np.sum(np.diff(sq) != 1)) if len(sq) > 1 else 0,
                    bad_n=self.nbad_n, rmin=None)

    def summary(self):
        if self.raw:
            return self.summary_raw()
        rs = np.array(self.rs, np.int64)
        ms = np.array(self.ms, np.int64)
        gaps = int(np.sum(np.diff(ms) != 1)) if len(ms) > 1 else 0
        return dict(n=len(rs), rmin=int(rs.min()) if len(rs) else None, rmax=int(rs.max()) if len(rs) else None,
                    gaps=gaps, r_bad=self.b.r_bad, bund=self.nbund, drop=len([d for d in self.drops if d[1] != "STOP"]),
                    drop_why=sorted({d[1] for d in self.drops}), bad_n=self.nbad_n, dead=self.b.dead)


def next_tint(tc, tint_beats, lead_s=1.0, plus=0):
    t = tc.t() + int(lead_s * BEATS_PER_SEC)
    return -(-t // tint_beats) * tint_beats + plus


def run_once(tc, wins, full, wms, streams, ring, tint_beats, n_sum, seconds, posctl):
    for st in streams:
        st.reset(n_sum)
        st.c.wr(SC.S_NACC, st.nacc); st.c.wr(SC.S_NDUMP, 0); st.c.wr(SC.S_SHIFT, 4)
        st.c.wr(SC.S_REC_CTRL, 1)                                  # ALL
    ring.read()
    sa = next_tint(tc, tint_beats)
    T.arm_all(tc, wins, full, wms, sa, tp=False, with_full=True)
    log(f"  START_AT = {sa}（tint の格子 {sa // tint_beats}·tint）")
    while not tc.status()["fired"]:
        time.sleep(0.01)
    runts = [st.c.rd64(SC.S_RUN_T) for st in streams]
    if any(x != sa + 1 for x in runts):
        log("  NG RUN_T: " + " / ".join(f"{st.name} {x - sa:+d}" for st, x in zip(streams, runts)))
    by = {st.key: st for st in streams}
    t0 = time.time()
    pos_done = False
    pos_at = None
    nrec = 0
    while time.time() - t0 < seconds:
        for core, s, seq, hw, pay, crc_ok, tail_ok in ring.read():
            if not (crc_ok and tail_ok):
                log(f"  NG CRC・尾（{core}, {s}）"); continue
            ty = int(hw[0]) >> 40 & 0xFF
            st = by.get((core, s))
            if st is not None and ty == (TYPE_SNAP if st.raw else TYPE_SPEC):
                st.add(hw, pay); nrec += 1
        if posctl and not pos_done and time.time() - t0 > seconds / 2:
            c = streams[0].c                                         # A0
            c.wr(SC.S_CTRL, 1 << 1)                                  # STOP
            pos_at = next_tint(tc, tint_beats, lead_s=0.3, plus=G)
            c.wr(SC.S_CTRL, (1 << 8) | T.CTRL_ARM)
            T.arm_tc(tc, wins, full, wms, pos_at)
            log(f"  陽性対照: {streams[0].name} を STOP し、START_AT {pos_at}（tint の格子 ＋ G）で RUN し直す")
            pos_done = True
        time.sleep(0.02)
    for st in streams:
        st.c.wr(SC.S_CTRL, 1 << 1)
    time.sleep(0.2)
    for core, s, seq, hw, pay, crc_ok, tail_ok in ring.read():
        st = by.get((core, s))
        if crc_ok and tail_ok and st is not None and (int(hw[0]) >> 40 & 0xFF) == (TYPE_SNAP if st.raw else TYPE_SPEC):
            st.add(hw, pay)
    for st in streams:
        st.c.wr(SC.S_REC_CTRL, 0)
        if not st.raw:
            st.b.stop()
    return sa


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=S.BITFILE)
    p.add_argument("--clkin", default="stock")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--path", default="trig", choices=("trig", "comp"))
    p.add_argument("--ns", default="1,2,3,4,5,6,7,8", help="8 窓の NS（ADC の順・窓の順）")
    p.add_argument("--if", dest="if_c", type=float, default=3000.0)
    p.add_argument("--tint", type=float, default=0.04096, help="tint [s]（BASE 10.24 ms の倍数）")
    p.add_argument("--seconds", type=float, default=60.0, help="1 回の RUN の長さ [s]")
    p.add_argument("--runs", type=int, default=2)
    p.add_argument("--full-adc", type=int, default=0)
    p.add_argument("--posctl", action="store_true", help="陽性対照: 1 回目の RUN の途中で A0 を tint の格子 ＋ G で RUN し直す")
    p.add_argument("--size-mib", type=int, default=32)
    a = p.parse_args()
    import s45acq as A
    tint_beats = int(round(a.tint * BEATS_PER_SEC))
    if tint_beats % A.BASE_BEATS:
        log(f"ERROR: tint {a.tint} は BASE（10.24 ms）の倍数でない"); sys.exit(1)
    n_sum = tint_beats // A.BASE_BEATS
    ns_list = [int(x) for x in a.ns.split(",")]

    from pynq import Overlay
    import xrfdc  # noqa: F401
    import plring as PR
    S.setup_clocks(a.clkin, a.ref)
    ol = Overlay(a.bitfile)
    log(f"Overlay: {a.bitfile}")
    S.check_tiles(ol.rfdc, 2)
    time.sleep(a.settle)
    tc, wms, wins, full = T.open_all(ol, ns_list)
    tc.configure(src=a.path, tol=1)
    tb = Timebase(tc, path=a.path)
    try:
        anc = tb.anchor()
    except TimebaseError as e:
        log(f"ERROR: 錨を打てない: {e}"); sys.exit(1)
    log(f"錨: UTC {anc['utc_sec']} 秒 = スタンプ {anc['stamp']}")
    ring = PR.Ring(ol.s45_ring_0.mmio, a.size_mib << 20)
    ring.enable(True)
    T.select_full(wms, full, a.full_adc)
    T.wrst_on_grid(tc, tb, wins, full, wms, ns_list, a.if_c, 0x0024_0001)
    streams = [Stream(c.name, c, (c.adc, c.widx), c.L, ns) for c, ns in zip(wins, ns_list)]
    is_raw = getattr(full, "kind", SC.KIND_FULL) == SC.KIND_RAW
    streams.append(Stream("RAW" if is_raw else "全帯域", full, full.rec_key, 512, None, raw=is_raw))
    log(f"流れ: " + " / ".join(f"{st.name}（{'NS ' + str(st.ns) if st.ns else 'FULL'}・L {st.L}・N_ACC {st.nacc}）" for st in streams))
    log(f"tint {a.tint} s = n_sum {n_sum} × BASE {A.BASE_BEATS}・1 回 {a.seconds} s × {a.runs} 回")
    res = []
    ok = True
    try:
        for k in range(a.runs):
            log(f"---- RUN {k + 1} ----")
            run_once(tc, wins, full, wms, streams, ring, tint_beats, n_sum, a.seconds, a.posctl and k == 0)
            rr = {}
            for j, st in enumerate(streams):
                sm = st.summary()
                rr[st.name] = sm
                if st.raw:
                    good = sm["n"] > 1 and sm["dev"] == 0 and sm["gaps"] == 0 and sm["bad_n"] == 0
                    ok &= bool(good)
                    log(f"  {st.name:<12} RAW   SNAP {sm['n']:>5}・DUMP_T の間隔の N_ACC·512 からのずれ 最大 {sm['dev']}・SEQ の飛び {sm['gaps']}・"
                        f"DUMP_N の違い {sm['bad_n']}（5.1 の見張りには入れない）: {'OK' if good else 'NG'}")
                    continue
                const = sm["n"] > 0 and sm["rmax"] - sm["rmin"] <= 1
                pos = a.posctl and k == 0 and j == 0
                if pos:
                    good = sm["r_bad"] == 1 and sm["dead"]
                else:
                    good = const and sm["gaps"] == 0 and sm["r_bad"] == 0 and sm["drop"] == 0 and sm["bad_n"] == 0
                ok &= bool(good)
                extra = (f"r − G {sm['rmin'] - G:+d}" if st.ns else f"r mod 512 = {sm['rmin'] % 512}") if sm["n"] else ""
                log(f"  {st.name:<12} {'NS ' + str(st.ns) if st.ns else 'FULL':<5} ダンプ {sm['n']:>5}・r {sm['rmin']}〜{sm['rmax']}（{extra}）・m の飛び {sm['gaps']}・"
                    f"束 {sm['bund']}・捨てた束 {sm['drop']}{sm['drop_why'] if sm['drop'] else ''}・DUMP_N の違い {sm['bad_n']}・r_bad {sm['r_bad']}"
                    f"{'（陽性対照: r_bad 1・束ねを止めた であるべき）' if pos else ''}: {'OK' if good else 'NG'}")
            res.append(rr)
        if len(res) > 1:
            log("---- RUN の間で r が同じか（陽性対照で動かした A0 の 1 回目は除く）----")
            for j, st in enumerate(streams):
                if st.raw:
                    continue
                vals = [rr[st.name]["rmin"] for i, rr in enumerate(res) if not (a.posctl and i == 0 and j == 0)]
                same = len(set(vals)) == 1
                ok &= same
                log(f"  {st.name:<12} r = {vals}: {'同じ' if same else '**違う**'}")
        r = ring.regs()
        log(f"リング: REC_CNT {r['rec']} / DROP_CNT {r['drop']} / ERR {r['err']}")
        ok &= r["drop"] == 0 and not r["err"]
        tab = {st.ns: res[-1][st.name]["rmin"] - G for st in streams if st.ns}
        log("DDC の r − G（NS: 値）: " + " / ".join(f"{k_}: {v}" for k_, v in sorted(tab.items())))
        if not is_raw:
            fr = res[-1]["全帯域"]["rmin"]
            log(f"FULL の r = {fr}（START_AT から {fr / 512:.3f} フレーム、r mod 512 = {fr % 512}）")
    finally:
        ring.close([st.c for st in streams])
    log(f"結果（V2-f{'・陽性対照' if a.posctl else ''}）: {'通過' if ok else '失敗'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
