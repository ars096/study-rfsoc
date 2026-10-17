#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj023 H-3（PL だけ）— SAM45-Wide で INTERFACE 9. の V2-a 相当・V2-e・V2-f を、specd を使わずにボードの道具で

ボードで root。リングの持ち主は 1 つ（specd などを止めてから）。

    python3 wide_v2.py --clkin 0 --ref 10 --v2a                       # V2-a 相当: 10.24 ms × 4 の和 = 40.96 ms（整数で一致）
    python3 wide_v2.py --clkin 0 --ref 10 --v2e                       # V2-e: TP のレコード = AXI4-Lite の TP のリング
    python3 wide_v2.py --clkin 0 --ref 10 --v2f --runs 2 --seconds 10 --posctl   # V2-f: r = DUMP_T − m·BASE が一定（陽性対照つき）
    for i in 1 2 3; do python3 wide_v2.py --clkin 0 --ref 10 --v2f; done          # V2-f: Overlay をまたいで r が同じ（D-2）

V2-a 相当（proj021 の V2-a は specd の 10.24 ms と 40.96 ms の比べ。ここでは PL の積分器そのものを比べる）:
  同じ ADC の SLICE の流れ 0・1 を**同じ B・同じ S0** にし、流れ 0 を N_ACC 1280（10.24 ms）、流れ 1 を N_ACC 5120（40.96 ms）で
  **同じ START_AT（ARM_RUN、tint 40.96 ms の格子）**から走らせる。流れ 1 のダンプ j と、DUMP_F0 が F0_1(j) + q·1280（q = 0..3）の
  流れ 0 の 4 個の和が**全 ch で整数として一致**すること。陽性対照: 1 個ずらした和（q = 1..4）は一致しない。
  B 4 は流れ 1 が空なので入れない（--mode の B 4 は拒む）。
V2-e: plring.py --tpcompare と同じ（core_cmn は win_core の TP を番地・意味を変えずに写した。README 手順 3）。
V2-f: 全部の流れを N_ACC 1280（= BASE）・N_DUMP 0 で、START_AT を tint の格子に置いて RUN。ダンプごとに
  r = DUMP_T mod BASE（m = ⌊DUMP_T / BASE⌋）。**予言（D-2・K_F 0）: r = 2·G = 1,048,576**（RUN は START_AT ＋ 1 で、F0 = (⌊fa / 256⌋ + 2)·256 =
  START_AT / 2048 ＋ 512 フレーム）。見るもの: RUN の中で r が 1 つ・m の飛び 0・SEQ の飛び 0・DUMP_T = K_F ＋ 2048·DUMP_F0・RUN の間で同じ・予言と同じ。
  --posctl: 最後に START_AT を格子 ＋ G にずらした RUN を足す → r = 3·G になり、「RUN の間で同じ」の比べが**違うと言う**こと。
V2-b（specd の 30 分）は s45acq・specd を SLICE に移してから。V2-c は H-3 から外した（README の H-3）。
"""
import argparse
import os
import sys
import time
import traceback

import numpy as np

import s45core as SC
import wide as WD
from timebase import TimeCore, TimebaseError, BEATS_PER_SEC

G = 1 << 19                      # 524,288 ビート = 2.048 ms（256 フレーム）
FRAME = 2048                     # Wide のフレーム（ビート）
BASE = 5 * G                     # 10.24 ms = 1280 フレーム
TINT = 4 * BASE                  # 40.96 ms
K_F = 0                          # build.tcl の wide_kf
CTRL_ARMRUN, CTRL_CANCEL = 1 << 2, 1 << 3
R_PRED = 2 * G                   # V2-f の予言


def log(*a):
    print(*a, flush=True)


def rd64(st, a):
    lo = st.rd(a)
    return st.rd(a + 4) << 32 | lo


# ------------------------------------------------------------------ 純粋な部分（selftest で見る）
def v2a_compare(r0, r1, nacc0):
    """r0: {DUMP_F0: payload}（流れ 0）、r1: [(DUMP_F0, payload)]（流れ 1、N_ACC = 4·nacc0）。
    戻り: dict(n = 比べた組, eq = 全 ch 一致の組, bad_ch = 一致しない ch の延べ, miss = 流れ 0 が欠けた組,
               pos_n = 陽性対照の組, pos_hit = 陽性対照で不一致を見つけた組)"""
    o = dict(n=0, eq=0, bad_ch=0, miss=0, pos_n=0, pos_hit=0)
    for f1, p1 in r1:
        parts = [r0.get(f1 + q * nacc0) for q in range(5)]
        if any(x is None for x in parts[:4]):
            o["miss"] += 1
            continue
        s = parts[0] + parts[1] + parts[2] + parts[3]          # u64 のまま（PL の積分器と同じ幅）
        o["n"] += 1
        nb = int(np.count_nonzero(s != p1))
        o["bad_ch"] += nb
        o["eq"] += nb == 0
        if parts[4] is not None:
            sp = parts[1] + parts[2] + parts[3] + parts[4]
            o["pos_n"] += 1
            o["pos_hit"] += bool(np.any(sp != p1))
    return o


def r_of(dump_t):
    return dump_t % BASE, dump_t // BASE


class RAcc:
    """V2-f: 流れ 1 本ぶんの数え（中身は捨てる）"""

    def __init__(self, nacc):
        self.nacc = nacc
        self.rs, self.ms, self.seqs = set(), [], []
        self.n = self.bad_n = self.bad_t = self.bad_f0 = self.flags = self.sat = self.crc = 0
        self.f0_prev = None

    def add(self, h, ok):
        self.n += 1
        self.crc += not ok
        r, m = r_of(h["dump_t"])
        self.rs.add(r); self.ms.append(m); self.seqs.append(h["seq"])
        self.bad_n += h["dump_n"] != self.nacc
        self.bad_t += h["dump_t"] != K_F + FRAME * h["dump_f0"]
        if self.f0_prev is not None and h["dump_f0"] - self.f0_prev != self.nacc:
            self.bad_f0 += 1
        self.f0_prev = h["dump_f0"]
        self.flags += h["flags"] != 0
        self.sat += h["dump_sat"] != 0

    def summary(self):
        ms, sq = np.array(self.ms, np.int64), np.array(self.seqs, np.int64)
        return dict(n=self.n, r=sorted(self.rs), mgap=int(np.sum(np.diff(ms) != 1)) if len(ms) > 1 else 0,
                    sgap=int(np.sum((np.diff(sq) & 0xFFFFFFFF) != 1)) if len(sq) > 1 else 0,
                    bad_n=self.bad_n, bad_t=self.bad_t, bad_f0=self.bad_f0, flags=self.flags, sat=self.sat, crc=self.crc)


def selftest():
    ng = 0
    rng = np.random.default_rng(1)
    d = [rng.integers(0, 1 << 40, WD.NCH, dtype=np.uint64) for _ in range(13)]
    f0 = 512 * 1000
    r0 = {f0 + k * 1280: d[k] for k in range(13)}
    r1 = [(f0 + j * 5120, d[4 * j] + d[4 * j + 1] + d[4 * j + 2] + d[4 * j + 3]) for j in range(3)]
    o = v2a_compare(r0, r1, 1280)
    if (o["n"], o["eq"], o["bad_ch"], o["miss"], o["pos_n"], o["pos_hit"]) != (3, 3, 0, 0, 3, 3):
        log(f"NG: v2a の一致 {o}"); ng += 1
    r1b = [(f, p.copy()) for f, p in r1]
    r1b[1][1][123] += np.uint64(1)                              # 陽性対照: 1 ch を 1 だけ変える
    o = v2a_compare(r0, r1b, 1280)
    if (o["eq"], o["bad_ch"]) != (2, 1):
        log(f"NG: v2a の陽性対照（1 ch の 1）{o}"); ng += 1
    o = v2a_compare(r0, [(f0 + 256, r1[0][1])], 1280)          # F0 が格子からずれた組は「欠け」
    if o["miss"] != 1:
        log(f"NG: v2a の欠け {o}"); ng += 1
    sa = 12345 * TINT                                           # 予言: RUN = sa + 1 → F0 = ⌊fa/256⌋·256 + 512
    fa = (sa + 2 - K_F) // FRAME
    F0 = ((fa >> 8) + 2) << 8
    if r_of(K_F + FRAME * F0)[0] != R_PRED:
        log(f"NG: r の予言 {r_of(K_F + FRAME * F0)}"); ng += 1
    fa = (sa + G + 2 - K_F) // FRAME
    F0 = ((fa >> 8) + 2) << 8
    if r_of(K_F + FRAME * F0)[0] != R_PRED + G:
        log("NG: 陽性対照の r の予言"); ng += 1
    acc = RAcc(1280)
    for k in range(5):
        f = F0 + k * 1280 + (1280 if k >= 3 else 0)             # 1 個飛ばす
        acc.add(dict(dump_t=K_F + FRAME * f, dump_f0=f, seq=k, dump_n=1280, flags=0, dump_sat=0), True)
    sm = acc.summary()
    if (sm["mgap"], sm["bad_f0"], sm["sgap"], len(sm["r"])) != (1, 1, 0, 1):
        log(f"NG: RAcc {sm}"); ng += 1
    log(f"selftest: {'全部通過' if ng == 0 else f'NG {ng} 件'}")
    return ng


# ------------------------------------------------------------------ ボード
def next_grid(tc, grid, lead_s=0.3, plus=0):
    t = tc.t() + int(lead_s * BEATS_PER_SEC)
    return -(-t // grid) * grid + plus


def arm_run(tc, sts, nacc, ndump, shift, sa):
    """流れごとの N_ACC・N_DUMP（dict: st → 値）で ARM_RUN し、START_AT sa で発火させる。RUN_T（流れごと）を返す"""
    for st in sts:
        st.wr(SC.S_NACC, nacc[st]); st.wr(SC.S_NDUMP, ndump[st]); st.wr(SC.S_SHIFT, shift)
        st.wr(SC.S_REC_CTRL, 1)
    for st in sts:
        st.wr(SC.S_CTRL, WD.CTRL_FCLR | CTRL_ARMRUN)
    try:
        tc.arm(sa)
    except TimebaseError:
        tc.wr(0x08, TimeCore.CTRL_CANCEL)
        for st in sts:
            st.wr(SC.S_CTRL, CTRL_CANCEL)
        raise
    t0 = time.time()
    while not tc.status()["fired"]:
        if time.time() - t0 > 3:
            raise SC.S45Error(f"START_AT {sa} で発火しない（今 {tc.t()}）")
        time.sleep(0.005)
    return {st: rd64(st, SC.S_RUN_T) for st in sts}


def stop_all(sts):
    for st in sts:
        st.wr(SC.S_CTRL, WD.CTRL_STOP)
        st.wr(SC.S_REC_CTRL, 0)


def set_modes(cores, mode, s0, same_s0=False):
    ng, sts = [], []
    for c in cores:
        L = c.adc_name[-1]
        b = mode.get(L, 1)
        ss = {s: s0.get(f"{L}{0 if same_s0 else s}", 0) for s in (0, 1)}
        ng += WD.set_mode(c, b, ss)
        sts += [st for st in WD.slices(c) if WD.nch_of(b, st.s)]
    return ng, sts


def runt_line(runt, sa):
    vals = sorted({v - sa for v in runt.values()})
    return vals, " / ".join(f"{WD.key_of(st)} {v - sa:+d}" for st, v in runt.items())


def do_v2a(cores, ring, tc, a, mode, s0):
    for L, b in mode.items():
        if b == 4:
            log(f"ERROR: V2-a は B 4 を入れない（{L} の流れ 1 が空）"); return 1
    ng, sts = set_modes(cores, mode, s0, same_s0=True)
    n1 = a.v2a_n
    nacc = {st: (1280 if st.s == 0 else 5120) for st in sts}
    ndump = {st: (4 * n1 + 1 if st.s == 0 else n1) for st in sts}    # 流れ 0 は陽性対照の 1 個ぶん多く
    ring.read()
    d0 = ring.regs()["drop"]
    late0 = {st: st.rd(SC.S_REC_LATE) for st in sts}
    sa = next_grid(tc, TINT)
    runt = arm_run(tc, sts, nacc, ndump, a.shift, sa)
    vals, line = runt_line(runt, sa)
    log(f"V2-a: START_AT {sa}（tint の格子 {sa // TINT}）/ RUN_T − START_AT: {line}")
    if len(vals) != 1:
        ng.append(f"RUN_T が流れでそろわない {vals}")
    want = {(st.core.adc, st.s): st for st in sts}
    got = {st: [] for st in sts}
    t0 = time.time()
    while time.time() - t0 < n1 * 0.041 + 3:
        for core, s, seq, hw, pay, crc_ok, tail_ok in ring.read():
            h = WD.parse_hdr(hw)
            st = want.get((core, s))
            if st is not None and h["rtype"] == WD.TYPE_SPEC:
                got[st].append((h, pay, crc_ok and tail_ok))
        if all(len(got[st]) >= ndump[st] for st in sts):
            break
        time.sleep(0.005)
    stop_all(sts)
    tot = 0
    for c in cores:
        L = c.adc_name[-1]
        b = mode.get(L, 1)
        ss = [st for st in sts if st.core is c]
        if len(ss) != 2:
            continue
        s0v = s0.get(f"{L}0", 0)
        for st in ss:
            ng += WD.check_recs(WD.key_of(st), got[st], b, s0v, nacc[st], ndump[st])
            for h, _, _ in got[st]:
                if h["dump_t"] != K_F + FRAME * h["dump_f0"]:
                    ng.append(f"{WD.key_of(st)}: SEQ {h['seq']} の DUMP_T {h['dump_t']} ≠ K_F ＋ 2048·DUMP_F0")
                if h["flags"] or h["dump_sat"]:
                    ng.append(f"{WD.key_of(st)}: SEQ {h['seq']} の FLAGS {h['flags']:#x}・DUMP_SAT {h['dump_sat']}")
            late = st.rd(SC.S_REC_LATE) - late0[st]
            if late:
                ng.append(f"{WD.key_of(st)}: REC_LATE +{late}")
        r0 = {h["dump_f0"]: p for h, p, _ in got[ss[0]]}
        r1 = [(h["dump_f0"], p) for h, p, _ in got[ss[1]]]
        f00 = got[ss[0]][0][0]["dump_f0"] if got[ss[0]] else None
        f01 = got[ss[1]][0][0]["dump_f0"] if got[ss[1]] else None
        o = v2a_compare(r0, r1, 1280)
        good = o["n"] == n1 and o["eq"] == n1 and o["miss"] == 0 and o["pos_n"] == n1 and o["pos_hit"] == n1 and f00 == f01
        mx = max((int(p.max()) for _, p in r1), default=0)
        log(f"  {c.adc_name}（B {b}・S0 {s0v}）: F0 流れ 0 {f00}・流れ 1 {f01} / 40.96 ms の {o['n']} 組のうち全 ch 一致 {o['eq']}"
            f"（一致しない ch の延べ {o['bad_ch']}・欠け {o['miss']}）/ 陽性対照（1 個ずらし）不一致を見つけた {o['pos_hit']}/{o['pos_n']}"
            f" / 40.96 ms の最大 {mx:.4g}（≈ 2^{np.log2(max(mx, 1)):.1f}）: {'OK' if good else 'NG'}")
        if not good:
            ng.append(f"{c.adc_name}: V2-a の一致 {o}・F0 {f00}/{f01}")
        tot += 1
    dd = ring.regs()["drop"] - d0
    if dd:
        ng.append(f"DROP_CNT +{dd}")
    for x in ng:
        log(f"  NG: {x}")
    log(f"結果（V2-a 相当、{tot} ADC）: {'通過' if not ng else f'NG {len(ng)} 件'}")
    return 1 if ng else 0


def v2f_run(cores, ring, tc, a, sts, plus):
    accs = {st: RAcc(1280) for st in sts}
    ring.read()
    d0 = ring.regs()["drop"]
    sa = next_grid(tc, TINT, plus=plus)
    runt = arm_run(tc, sts, {st: 1280 for st in sts}, {st: 0 for st in sts}, a.shift, sa)
    vals, line = runt_line(runt, sa)
    log(f"  START_AT {sa}（tint の格子 ＋ {plus // G}·G）/ RUN_T − START_AT: {line}")
    want = {(st.core.adc, st.s): st for st in sts}
    t0 = time.time()
    nrec = 0
    while time.time() - t0 < a.seconds:
        for core, s, seq, hw, pay, crc_ok, tail_ok in ring.read():
            h = WD.parse_hdr(hw)
            st = want.get((core, s))
            if st is not None and h["rtype"] == WD.TYPE_SPEC:
                accs[st].add(h, crc_ok and tail_ok); nrec += 1
        time.sleep(0.01)
    stop_all(sts)
    time.sleep(0.1)
    for core, s, seq, hw, pay, crc_ok, tail_ok in ring.read():
        h = WD.parse_hdr(hw)
        st = want.get((core, s))
        if st is not None and h["rtype"] == WD.TYPE_SPEC:
            accs[st].add(h, crc_ok and tail_ok)
    dd = ring.regs()["drop"] - d0
    return {WD.key_of(st): accs[st].summary() for st in sts}, len(vals) == 1, dd


def do_v2f(cores, ring, tc, a, mode, s0):
    ng, sts = set_modes(cores, mode, s0)
    log(f"V2-f: 流れ {len(sts)} 本（{', '.join(WD.key_of(st) + ' B ' + str(mode.get(WD.key_of(st)[0], 1)) for st in sts)}）・"
        f"N_ACC 1280（BASE）・{a.seconds} s × {a.runs} 回{' ＋ 陽性対照 1 回' if a.posctl else ''}。予言 r = {R_PRED}（2·G）")
    plan = [0] * a.runs + ([G] if a.posctl else [])
    res = []
    for k, plus in enumerate(plan):
        pos = plus != 0
        log(f"---- RUN {k + 1}{'（陽性対照: START_AT を ＋ G）' if pos else ''} ----")
        rr, runt_ok, dd = v2f_run(cores, ring, tc, a, sts, plus)
        if not runt_ok:
            ng.append(f"RUN {k + 1}: RUN_T が流れでそろわない")
        if dd:
            ng.append(f"RUN {k + 1}: DROP_CNT +{dd}")
        for key, sm in rr.items():
            const = sm["n"] > 0 and len(sm["r"]) == 1
            good = (const and sm["mgap"] == 0 and sm["sgap"] == 0 and sm["bad_n"] == 0 and sm["bad_t"] == 0 and sm["bad_f0"] == 0
                    and sm["flags"] == 0 and sm["sat"] == 0 and sm["crc"] == 0)
            r0 = sm["r"][0] if const else None
            pred = R_PRED + plus
            log(f"    {key}: ダンプ {sm['n']:>5}・r {sm['r'][:3]}{'…' if len(sm['r']) > 3 else ''}"
                f"{'（' + format(r0 / G, '.4f') + '·G）' if const else ''}・m の飛び {sm['mgap']}・SEQ の飛び {sm['sgap']}・"
                f"DUMP_N の違い {sm['bad_n']}・DUMP_T の式の外れ {sm['bad_t']}・F0 の飛び {sm['bad_f0']}・FLAGS {sm['flags']}・SAT {sm['sat']}・"
                f"CRC {sm['crc']}・予言 {pred} と{'同じ' if r0 == pred else '**違う**'}: {'OK' if good and r0 == pred else 'NG'}")
            if not good:
                ng.append(f"RUN {k + 1} {key}: {sm}")
            elif r0 != pred:
                ng.append(f"RUN {k + 1} {key}: r {r0} が予言 {pred} と違う")
        res.append((plus, rr))
    log("---- RUN の間で r が同じか ----")
    keys = [WD.key_of(st) for st in sts]
    main = [rr for plus, rr in res if plus == 0]
    for key in keys:
        vals = [tuple(rr[key]["r"]) for rr in main]
        same = len(set(vals)) == 1
        line = f"    {key}: r = {[list(v) for v in vals]}: {'同じ' if same else '**違う**'}"
        if not same:
            ng.append(f"{key}: RUN の間で r が違う {vals}")
        if a.posctl:
            pv = tuple(res[-1][1][key]["r"])
            hit = pv != vals[0]
            line += f" / 陽性対照の RUN {list(pv)} を比べると{'違うと言った（よい）' if hit else '**同じと言った（比べが効いていない）**'}"
            if not hit:
                ng.append(f"{key}: 陽性対照で r が変わらない")
        log(line)
    if main:
        allr = sorted({v for rr in main for sm in rr.values() for v in sm["r"]})
        log(f"V2-f の r（この Overlay、全部の流れ）: {allr} — Overlay をまたいで同じかは、この行を回ごとに並べて見る（D-2）")
    for x in ng:
        log(f"  NG: {x}")
    log(f"結果（V2-f{'・陽性対照' if a.posctl else ''}）: {'通過' if not ng else f'NG {len(ng)} 件'}")
    return 1 if ng else 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--selftest", action="store_true")
    p.add_argument("--bitfile", default="proj023.bit")
    p.add_argument("--clkin", default="stock")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--size-mib", type=int, default=32)
    p.add_argument("--v2a", action="store_true")
    p.add_argument("--v2e", action="store_true")
    p.add_argument("--v2f", action="store_true")
    p.add_argument("--mode", default="", help="コアの束ね: A=1,B=2,…（既定 V2-a A=1,B=2,C=1,D=2・V2-f A=1,B=2,C=4,D=1）")
    p.add_argument("--s0", default="", help="流れの S0（V2-a は流れ 0 の値を流れ 1 にも使う）")
    p.add_argument("--shift", type=int, default=7)
    p.add_argument("--v2a-n", type=int, default=10, help="V2-a: 40.96 ms のダンプの数")
    p.add_argument("--tp-seconds", type=float, default=3.0, help="V2-e: 集める時間 [s]")
    p.add_argument("--seconds", type=float, default=10.0, help="V2-f: 1 回の RUN の長さ [s]")
    p.add_argument("--runs", type=int, default=2)
    p.add_argument("--posctl", action="store_true", help="V2-f: START_AT を ＋ G にずらした RUN を足す")
    a = p.parse_args()
    if a.selftest:
        sys.exit(1 if selftest() else 0)
    if not (a.v2a or a.v2e or a.v2f):
        log("ERROR: --v2a・--v2e・--v2f のどれか"); sys.exit(1)
    s0 = WD.parse_kv(a.s0, WD.KEYS)
    try:
        ol, cores, tmm = WD.open_board(a)
        tc = TimeCore(tmm)
        import plring
        ring = plring.Ring(ol.s45_ring_0.mmio, a.size_mib * plring.MiB)
    except (SC.S45Error, TimebaseError) as e:
        log(f"ERROR: {e}"); sys.exit(1)
    log(SC.table(cores, tmm))
    WD.diag(cores)
    rc = 0
    allst = [st for c in cores for st in c.streams]
    try:
        ring.enable(True)
        if a.v2a:
            mode = WD.parse_kv(a.mode or "A=1,B=2,C=1,D=2", list("ABCD"))
            rc |= do_v2a(cores, ring, tc, a, mode, s0)
        if a.v2e:
            rc |= plring.do_tpcompare(cores, ring, a)
        if a.v2f:
            mode = WD.parse_kv(a.mode or "A=1,B=2,C=4,D=1", list("ABCD"))
            rc |= do_v2f(cores, ring, tc, a, mode, s0)
    except Exception:
        log("ERROR: 道具が例外で止まった:\n" + traceback.format_exc())
        rc = 2
    finally:
        ring.close(allst)
    sys.exit(rc)


if __name__ == "__main__":
    main()
