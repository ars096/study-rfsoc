#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj023 手順 4f — F-2（ADC → コアの遅れ adc_to_core、timebase.CAL）を SAM45-Wide の .bit で
（proj024 4d: 2G-1（BIT_KIND 11、コア 1 個）に直した。RAW は コア 0 の s 1（0x4400）、入口は raw_sel（axis_sel4）で 4 ADC から選ぶ（D-14）。
 開き方は s45acq の G21Backend と同じ（discover(bit_kind=11, ncore=1)）。CAL の鍵は 0x0024_0100。測り方・合格の線は proj023 と同じ）

timetest.py --t2 の (a)（RAW の流れの生サンプルで 1PPS の縁を見る）を Wide に移したもの。Wide には DDC の窓が無いので、
窓の (b) の代わりに**陽性対照 (p)**: 同じ手順で RAW のフレームを縁の 2 フレーム（1,024 ビート）前に置き、縁が写らない（最大 / σ < 20）ことを見る。
RAW は コア 0 の s 2、入口は axis_sel4（full_sel）で 4 ADC から選ぶ。SLICE は同じサンプルに同じ T を付ける（手順 4e の sim-wds、D_S = 0）ので、
ここで測った値がそのまま SLICE の utc_ns の adc_to_core になる。

**配線 P**: 1PPS を PPS Clk と ADC_A〜D に分配（proj021 の F-2 と同じ）。ボード直、root、specd を止めてから:

    python3 widef2.py --clkin 0 --ref 10 --adc 0,1,2,3 --out f2_24a
    # ADC のケーブルを A↔C・B↔D に入れ替えて
    python3 widef2.py --clkin 0 --ref 10 --adc 0,1,2,3 --out f2_24b
    python3 widef2.py --combine f2_24a.f2.json f2_24b.f2.json      # 2 回の平均 M と判定（CAL に入れる値）

合格（test/acceptance/F-2.md と同じ線）: (a) 4 ADC × 5 試行とも縁が見える（最大 / σ ≧ 20）・1 回の中の σ ≦ 0.4 ビート・2 回の差 ≦ 1 ビート。
(p) 5 試行とも縁が見えない。M = 2 回の平均（ns）を timebase.CAL[0x0024_0100] に（proj026 の (b) の形で）入れる。
予言（proj023）: proj021 2-5 と同じギアボックス・RAW の道なので M ≒ 146〜148 ns（配置が違うので ±5 ns）。タイルの向きは予言しない（proj021 で外れた）
予言（proj024 4d、LPF あり）: proj023 と同じギアボックス・axis_sel4・RAW の RTL（567fda2）なので M ≒ 70 ns（proj023 の 69.9〜71.5 ns に配置の差 ±5 ns）。予言の全文は README の 4d
2G-1 の SPEC の D_S（FULL と RAW の T の差）はここでは測れない（1 ビート = 3.9 ns はパワースペクトルに出ない）。sim で出す（README の 4d）
"""
import argparse
import json
import os
import sys
import time

import numpy as np

import s45core as SC
import timetest as T
import rectap as RT
import window as W
from timebase import BEATS_PER_SEC, TimeCore, Timebase, TimebaseError

log = T.log
NS_PER_BEAT = 3.90625


def open_board(a):
    """wide.open_board と同じ手順で、2G-1 の .bit を開く（wide.open_board は BIT_KIND 1 と SLICE の流れを要求するので使わない）"""
    import spectrometer as S
    S.setup_clocks(a.clkin, a.ref)
    from pynq import Overlay
    import xrfdc                                         # Overlay() より前に import する（VERSIONS.md）
    ol = Overlay(a.bitfile)
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    S.check_tiles(ol.rfdc, 2)
    time.sleep(a.settle)                                 # DSP のクロックが明けてから読む（s45core.py の注）
    return ol


def open_raw(ol):
    cores, tmm = SC.discover(ol, bit_kind=SC.BIT_KIND_G21, ncore=1, bit_rev_min=1)
    fs = SC.snap_stream(cores)
    if fs.kind != SC.KIND_RAW or fs.s != 1:
        raise SC.S45Error(f"RAW の流れが s 1 に無い（{fs.name}・kind {fs.kind}）")
    regs = dict(cfg=T.R_CFG, run_cfg=T.R_RUN_CFG, dump_t=T.R_DUMP_T, dump_h=T.R_DUMP_H, dump_cfg=T.R_DUMP_CFG, run_t=T.R_RUN_T)
    full = T.Core("RAW", fs.m, fs.base, regs, 512)
    full.rec_key = (fs.core.adc, fs.s)
    full.kind = fs.kind
    return cores, tmm, full


def edge_of(snap):
    """生サンプル（int16 × 8192）→ (縁のサンプルの添字, 最大 / σ)。σ は頭の 1024 サンプルの MAD"""
    x = (snap.astype(np.int64) >> 2).astype(float)
    x -= np.median(x[:1024])
    sig = 1.4826 * float(np.median(np.abs(x[:1024]))) or 1.0
    snr = float(np.max(np.abs(x))) / sig
    i_e = int(np.argmax(np.abs(x) > 0.5 * np.max(np.abs(x))))
    return i_e, snr


def measure(tc, tb, full, wms, path, adc, n_trial, lead_frames=0):
    """lead_frames = 0: 縁（の見当）を含む RAW のフレームを狙う（(a)）。2: その 2 フレーム前（(p)、縁は写らないはず）"""
    T.select_full(wms, full, adc)
    full.wr(W.R_NACC, 1); full.wr(W.R_NDUMP, 1); full.wr(W.R_SHIFT, 7)
    RT.tap().arm(full.m, full.base, False)
    def read_raw():
        _m, pay = RT.tap().latest_snap(full.rec_key, lambda: full.rd(W.R_SEQ))
        return RT.snap_full(pay)
    seq0 = full.rd(W.R_SEQ)
    full.wr(W.R_CTRL, W.CTRL_CLR | W.CTRL_RUN)
    t_e = time.time() + 1.0
    while full.rd(W.R_SEQ) == seq0 and time.time() < t_e:
        time.sleep(0.001)
    phi = full.meta()["t"] % 512                 # RAW のフレームの位相（1 s = 500,000 フレームちょうどなので PPS に対して動かない）
    L0 = 37                                      # 縁 → コアの入口の見当（ビート。proj021 2-5 の実測 37.4）
    res = []
    for k in range(n_trial):
        p = tb.check()
        edge = p["stamp"] + 2 * BEATS_PER_SEC
        te = edge + L0
        S0 = te - ((te - phi) % 512) - 512 * lead_frames
        full.wr(W.R_CTRL, W.CTRL_CLR | T.CTRL_ARM)
        seq0 = full.rd(W.R_SEQ)
        T.arm_tc(tc, [], full, wms, S0 - 769)    # RUN（START_AT + 1）は S0 − 768 → F0 = fin + 2 の頭が S0（timetest の t2 と同じ）
        T._wait_T(tc, edge + BEATS_PER_SEC // 10)
        if full.rd(W.R_SEQ) == seq0:
            raise RuntimeError(f"試行 {k}: RAW のダンプが閉じない")
        st = T._stamp_of(tc, path, edge)
        snap = read_raw()
        dt = full.rd64(T.RS_DUMP_T)
        i_e, snr = edge_of(snap)
        off = (dt + i_e / 16.0) - st
        r = dict(k=k, dump_t=int(dt), stamp=int(st), s0=int(S0), i_e=i_e, snr=snr, off=off, x=snap)
        res.append(r)
        if dt != S0:
            log(f"    注意: DUMP_T {dt} が狙った S0 {S0} と違う（{dt - S0:+d}）")
        tag = "(p)" if lead_frames else "(a)"
        if snr >= 20:
            log(f"  {tag} 試行 {k}: 縁のサンプル {i_e}（ビート {i_e / 16:.2f}、最大 / σ {snr:.0f}）→ 縁がコアに入った T − スタンプ = {off:+.2f} ビート（{off * NS_PER_BEAT:+.1f} ns）")
        else:
            log(f"  {tag} 試行 {k}: 縁が見えない（最大 / σ {snr:.1f} < 20。フレームは縁の見当の {te - S0} ビート前から）")
    full.wr(W.R_CTRL, W.CTRL_STOP)
    return res


def combine(paths):
    runs = [json.load(open(p)) for p in paths]
    ok = True
    log(f"2 回の平均（{', '.join(paths)}）")
    cal = {}
    for adc in sorted({int(a) for r in runs for a in r["adc"]}):
        v = [r["adc"][str(adc)] for r in runs if str(adc) in r["adc"]]
        ms = [x["mean"] for x in v if x["mean"] is not None]
        if len(ms) != len(runs):
            log(f"  {'ABCD'[adc]}: 縁の見えた回が {len(ms)}/{len(runs)}"); ok = False; continue
        d = max(ms) - min(ms)
        m = float(np.mean(ms))
        good = d <= 1.0 and all(x["std"] <= 0.4 and x["n"] == x["n_trial"] and x["p_seen"] == 0 for x in v)
        ok &= good
        cal["ABCD"[adc]] = round(m * NS_PER_BEAT, 1)
        log(f"  {'ABCD'[adc]}: " + " / ".join(f"{x['mean']:+.2f}（σ {x['std']:.2f}・{x['n']}/{x['n_trial']}・(p) で見えた {x['p_seen']}）" for x in v)
            + f" → M = {m:.2f} ビート = **{m * NS_PER_BEAT:.1f} ns**・2 回の差 {d:.2f}（≦ 1）: {'OK' if good else 'NG'}")
    log(f"timebase.CAL[{SC.PROJ_G21:#011_x}] の M（LPF ありなら (b): adc_to_core_ns = M ＋ LPF の分、pps_det_ns = LPF の分）: {cal}")
    log(f"結果（F-2）: {'通過' if ok else '失敗'}")
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default="proj024.bit")
    p.add_argument("--clkin", default="stock")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--path", default="trig", choices=("trig", "comp"))
    p.add_argument("--adc", default="0,1,2,3")
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--out", default=None)
    p.add_argument("--combine", nargs="+", default=None, help="2 回の .f2.json から M と判定")
    a = p.parse_args()
    if a.combine:
        sys.exit(0 if combine(a.combine) else 1)
    if a.out:
        d = os.path.dirname(a.out) or "."
        if not os.access(d, os.W_OK):
            log(f"ERROR: {d} に書けない"); sys.exit(1)
    try:
        ol = open_board(a)
        cores, tmm, full = open_raw(ol)
        tc = TimeCore(tmm)
        tc.configure(src=a.path, tol=1)
        tb = Timebase(tc, path=a.path)
        anc = tb.anchor()
    except (SC.S45Error, TimebaseError) as e:
        log(f"ERROR: {e}"); sys.exit(1)
    log(f"錨: UTC {anc['utc_sec']} 秒 = スタンプ {anc['stamp']}（EPOCH {anc['epoch']}）")
    wms = [c.m for c in cores]
    summ, raw = {}, {}
    ok = True
    try:
        for adc in [int(x) for x in a.adc.split(",")]:
            lbl = "ABCD"[adc]
            log(f"---- ADC_{lbl}（1PPS を ADC_{lbl} にも入れておくこと）----")
            ra = measure(tc, tb, full, wms, a.path, adc, a.n)
            rp = measure(tc, tb, full, wms, a.path, adc, a.n, lead_frames=2)
            offs = np.array([r["off"] for r in ra if r["snr"] >= 20])
            seen_p = sum(r["snr"] >= 20 for r in rp)
            mean = float(offs.mean()) if len(offs) else None
            std = float(offs.std()) if len(offs) else None
            good = len(offs) == a.n and std <= 0.4 and seen_p == 0
            ok &= good
            summ[str(adc)] = dict(mean=mean, std=std, n=int(len(offs)), n_trial=a.n, p_seen=int(seen_p),
                                  snr_a=[round(r["snr"], 1) for r in ra], snr_p=[round(r["snr"], 1) for r in rp])
            raw[lbl] = (ra, rp)
            log(f"  ADC_{lbl}: (a) {len(offs)}/{a.n} 回で縁・平均 {mean if mean is None else f'{mean:+.2f}'} ビート"
                f"（{'-' if mean is None else f'{mean * NS_PER_BEAT:.1f}'} ns）・σ {std if std is None else f'{std:.2f}'}（≦ 0.4）/ "
                f"(p) 縁が見えた {seen_p}/{a.n}（0 のはず、最大 / σ {[round(r['snr'], 1) for r in rp]}）: {'OK' if good else 'NG'}")
    except Exception as e:
        import traceback
        log("ERROR: 道具が例外で止まった:\n" + traceback.format_exc())
        ok = False
    # リングは rectap が終わりに閉じる（atexit）
    if a.out and summ:
        json.dump(dict(adc=summ, bitfile=a.bitfile, t=time.time()), open(a.out + ".f2.json", "w"), indent=1)
        np.savez_compressed(a.out + ".f2.npz", **{f"{k}_{tag}_x": np.array([r["x"] for r in v[i]]) for k, v in raw.items()
                                                 for i, tag in enumerate(("a", "p"))},
                            **{f"{k}_{tag}_meta": np.array([[r["dump_t"], r["stamp"], r["s0"], r["i_e"]] for r in v[i]]) for k, v in raw.items()
                               for i, tag in enumerate(("a", "p"))})
        log(f"記録: {a.out}.f2.json・{a.out}.f2.npz")
    log(f"この回（1 回目か 2 回目）: {'通過' if ok else '失敗'}。2 回そろったら --combine")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
