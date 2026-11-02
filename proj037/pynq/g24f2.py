#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""2G-4 の F-2（YATSUGATAKE の 2G-4 の M5 で、study-rfsoc proj036-m0 の pynq/widef2.py を名前を替えて入れた。SAM45-Wide の F-2 は widef2.py）。
M5 で足したのは --lmx-pwr（既定 3、specd と同じ）と CAL の鍵の表示 (BIT_KIND, BIT_REV) = (3, 1) だけ。以下は移植元の注:

proj023 手順 4f — F-2（ADC → コアの遅れ adc_to_core、timebase.CAL）を SAM45-Wide の .bit で
（proj024 4d: 2G-1（BIT_KIND 11、コア 1 個）に直した。RAW は コア 0 の s 1（0x4400）、入口は raw_sel（axis_sel4）で 4 ADC から選ぶ（D-14）。
 開き方は s45acq の G21Backend と同じ（discover(bit_kind=11, ncore=1)）。CAL の鍵は 0x0024_0100。測り方・合格の線は proj023 と同じ）
（proj025 4d: 2G-2（BIT_KIND 10、コア 2 個）に直した。RAW はコア 0 だけが持つ（s 1、コア 1 は RAW なし・NSTREAM 1）ので snap_stream はそのまま 1 本。
 開き方は G22Backend と同じ（discover(bit_kind=10, ncore=2)）。CAL の鍵は 0x0025_0100。直したのは開き方・鍵・既定の .bit だけ）
（proj027 4d: 2G-4（BIT_KIND 3、コア 4 個）に直した。**4 コアとも RAW を持つ**（s 1、NSTREAM 2。F-5）ので snap_stream（1 本の前提）は使わず、
 `--raw-core`（既定 0）のコアの RAW を直に取る。開き方は G24Backend と同じ（discover(bit_kind=3, ncore=4)）。CAL の鍵は 0x0027_0100。既定の .bit は proj027.bit）

timetest.py --t2 の (a)（RAW の流れの生サンプルで 1PPS の縁を見る）を Wide に移したもの。Wide には DDC の窓が無いので、
窓の (b) の代わりに**陽性対照 (p)**: 同じ手順で RAW のフレームを縁の 2 フレーム（1,024 ビート）前に置き、縁が写らない（最大 / σ < 20）ことを見る。
RAW は コア 0 の s 2、入口は axis_sel4（full_sel）で 4 ADC から選ぶ。SLICE は同じサンプルに同じ T を付ける（手順 4e の sim-wds、D_S = 0）ので、
ここで測った値がそのまま SLICE の utc_ns の adc_to_core になる。

**配線 P**: 1PPS を PPS Clk と ADC_A〜D に分配（proj021 の F-2 と同じ）。ボード直、root、specd を止めてから:

    python3 g24f2.py --clkin 0 --ref 10 --adc 0,1,2,3 --out f2_24a
    # ADC のケーブルを A↔C・B↔D に入れ替えて
    python3 g24f2.py --clkin 0 --ref 10 --adc 0,1,2,3 --out f2_24b
    python3 g24f2.py --combine f2_24a.f2.json f2_24b.f2.json      # 2 回の平均 M と判定（CAL に入れる値）

合格（test/acceptance/2g-4/F-2.md と同じ線）: (a) 4 ADC × 5 試行とも縁が見える（最大 / σ ≧ 20）・1 回の値は最多の山（peaks、2026-10-29 から）・2 回の差 ≦ 1 ビート。
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
    """wide.open_board と同じ手順で、2G-4 の .bit を開く（proj025 は 2G-2、proj024 は 2G-1）（wide.open_board は BIT_KIND 1 と SLICE の流れを要求するので使わない）"""
    import spectrometer as S
    S.setup_clocks(a.clkin, a.ref)
    if a.lmx_pwr is not None:                            # YATSUGATAKE（2G-4 の M5）: LMX の出力の強さ（wide.open_board・specd と同じ既定 3）。Overlay() の前
        import extref
        lmx = extref.rewrite_lmx(16, a.lmx_pwr)
        log(f"LMX: 出力の強さ {lmx.get('outa_pwr', a.lmx_pwr) if isinstance(lmx, dict) else a.lmx_pwr}（--lmx-pwr {a.lmx_pwr}）")
    from pynq import Overlay
    import xrfdc                                         # Overlay() より前に import する（VERSIONS.md）
    ol = Overlay(a.bitfile)
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    S.check_tiles(ol.rfdc, 2)
    time.sleep(a.settle)                                 # DSP のクロックが明けてから読む（s45core.py の注）
    return ol


def open_raw(ol, raw_core=0):
    cores, tmm = SC.discover(ol, bit_kind=SC.BIT_KIND_G24, ncore=4, bit_rev_min=1)      # proj027: 2G-4（proj025 は G22・ncore 2、proj024 は G21・ncore 1）
    nraw = [len(c.raw()) for c in cores]
    if nraw != [1, 1, 1, 1]:
        raise SC.S45Error(f"RAW の流れの本数がコアごとに {nraw}（期待 [1, 1, 1, 1]）")
    fs = cores[raw_core].raw()[0]                        # proj027: 4 コアとも RAW があるので、使うコアを選ぶ（SRC で ADC を選ぶのは同じ）
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


def peaks(offs, gap=0.5, sd_max=0.4, jump=(0.5, 1.5)):
    """1 回の T − スタンプ（ビート）を最多の山で読む（test/acceptance/2g-4/F-2.md、2026-10-29 から）。
    隣との隙間が gap を越える所で山に分け、最多の山が過半・その中の σ ≦ sd_max・ほかの山は最多の山から jump の範囲
    （1PPS のスタンプがビートの境目に乗って 1 ビート跳ぶ回）なら OK。平均と σ では読まない（2 つの山の間を返し σ が膨らむ）"""
    x = np.sort(np.asarray(offs, dtype=float))
    if not len(x):
        return dict(value=None, std=None, n_major=0, n_out=0, ok=False, why="縁の見えた試行が無い")
    cut = np.nonzero(np.diff(x) > gap)[0] + 1
    groups = np.split(x, cut)
    major = max(groups, key=len)
    v, sd = float(major.mean()), float(major.std())
    others = [g for g in groups if g is not major]
    why = []
    if 2 * len(major) <= len(x):
        why.append(f"最多の山 {len(major)}/{len(x)} が過半に届かない")
    if sd > sd_max:
        why.append(f"山の中の σ {sd:.2f} > {sd_max}")
    for g in others:
        d = abs(float(g.mean()) - v)
        if not jump[0] <= d <= jump[1]:
            why.append(f"ほかの山が {d:.2f} ビート離れている（1 ビートの跳ねではない）")
    return dict(value=v, std=sd, n_major=len(major), n_out=len(x) - len(major), ok=not why, why="・".join(why))


def _offs_of(path, adc, x):
    """.f2.json の 1 ADC の試行ごとの T − スタンプ。2026-10-29 より前の json には無いので、隣の .f2.npz の meta から戻す"""
    if "offs" in x:
        return x["offs"]
    z = np.load(path.replace(".f2.json", ".f2.npz"))
    m = z[f"{'ABCD'[adc]}_a_meta"]                    # [dump_t, stamp, s0, i_e]
    return [float(r[0] + r[3] / 16.0 - r[1]) for r, snr in zip(m, x["snr_a"]) if snr >= 20]


def selftest():
    """最多の山の読みの照合と陽性対照（PC で。ボード不要）"""
    cases = [("M5 の f2_b の A（3 対 2、1 ビートの跳ね）", [18.12, 17.25, 18.12, 17.25, 18.19], True),
             ("跳ねなし", [17.94, 17.88, 18.06, 17.81, 17.94], True),
             ("陽性対照: 山が過半に届かない（2・2・1）", [17.0, 17.1, 18.0, 18.1, 19.0], False),
             ("陽性対照: 山の間が 2 ビート", [18.0, 18.1, 18.0, 16.0, 16.1], False),
             ("陽性対照: 山の中が広い（0.45 ビートおき）", [17.0, 17.45, 17.9, 18.35, 18.8], False)]
    ok = True
    for name, offs, want in cases:
        r = peaks(offs)
        good = r["ok"] == want
        ok &= good
        print(f"  {name}: {'OK' if r['ok'] else 'NG'}（期待 {'OK' if want else 'NG'}）値 {r['value']:+.2f}・σ {r['std']:.2f}・"
              f"山の外 {r['n_out']}{'・' + r['why'] if r['why'] else ''} → {'通過' if good else '外れ'}")
    print(f"selftest: {'全部通過' if ok else 'NG'}")
    return ok


def combine(paths):
    runs = [json.load(open(p)) for p in paths]
    ok = True
    log(f"2 回の平均（{', '.join(paths)}）。1 回の値は最多の山")
    cal = {}
    for adc in sorted({int(a) for r in runs for a in r["adc"]}):
        v = [(p, r["adc"][str(adc)]) for p, r in zip(paths, runs) if str(adc) in r["adc"]]
        pk = [dict(peaks(_offs_of(p, adc, x)), n=x["n"], n_trial=x["n_trial"], p_seen=x["p_seen"]) for p, x in v]
        ms = [x["value"] for x in pk if x["value"] is not None]
        if len(ms) != len(runs):
            log(f"  {'ABCD'[adc]}: 縁の見えた回が {len(ms)}/{len(runs)}"); ok = False; continue
        d = max(ms) - min(ms)
        m = float(np.mean(ms))
        good = d <= 1.0 and all(x["ok"] and x["n"] == x["n_trial"] and x["p_seen"] == 0 for x in pk)
        ok &= good
        cal["ABCD"[adc]] = round(m * NS_PER_BEAT, 1)
        log(f"  {'ABCD'[adc]}: " + " / ".join(f"{x['value']:+.2f}（山 {x['n_major']}・σ {x['std']:.2f}・境目 {x['n_out']}・{x['n']}/{x['n_trial']}・"
                                              f"(p) で見えた {x['p_seen']}{'・' + x['why'] if x['why'] else ''}）" for x in pk)
            + f" → M = {m:.2f} ビート = **{m * NS_PER_BEAT:.1f} ns**・2 回の差 {d:.2f}（≦ 1）: {'OK' if good else 'NG'}")
    log(f"timebase.CAL[(3, 1)]（2G-4、PROJ {SC.PROJ_G24:#011_x}）の M（LPF ありなら (b): adc_to_core_ns = M ＋ LPF の分、pps_det_ns = LPF の分）: {cal}")
    log(f"結果（F-2）: {'通過' if ok else '失敗'}")
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default="proj031.bit")
    p.add_argument("--raw-core", type=int, default=0, choices=range(4), help="proj027: RAW を取るコア（既定 0。4 コアとも RAW を持つ）")
    p.add_argument("--lmx-pwr", type=int, default=3, help="LMX2594 の出力の強さ（specd と同じ既定 3。出荷時は 31、proj031 R-5 の CAL は 31 で測った）")
    p.add_argument("--clkin", default="stock")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--path", default="trig", choices=("trig", "comp"))
    p.add_argument("--adc", default="0,1,2,3")
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--out", default=None)
    p.add_argument("--combine", nargs="+", default=None, help="2 回の .f2.json から M と判定")
    p.add_argument("--selftest", action="store_true", help="最多の山の読みの照合と陽性対照（PC で）")
    a = p.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    if a.combine:
        sys.exit(0 if combine(a.combine) else 1)
    if a.out:
        d = os.path.dirname(a.out) or "."
        if not os.access(d, os.W_OK):
            log(f"ERROR: {d} に書けない"); sys.exit(1)
    try:
        ol = open_board(a)
        cores, tmm, full = open_raw(ol, a.raw_core)
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
            pk = peaks(offs)
            good = len(offs) == a.n and pk["ok"] and seen_p == 0
            ok &= good
            summ[str(adc)] = dict(mean=mean, std=std, mode=pk["value"], std_mode=pk["std"], n_out=pk["n_out"], offs=offs.tolist(),
                                  n=int(len(offs)), n_trial=a.n, p_seen=int(seen_p),
                                  snr_a=[round(r["snr"], 1) for r in ra], snr_p=[round(r["snr"], 1) for r in rp])
            raw[lbl] = (ra, rp)
            v, sdm = pk["value"], pk["std"]
            log(f"  ADC_{lbl}: (a) {len(offs)}/{a.n} 回で縁・最多の山 {'-' if v is None else f'{v:+.2f}'} ビート"
                f"（{'-' if v is None else f'{v * NS_PER_BEAT:.1f}'} ns）・山の中の σ {'-' if v is None else f'{sdm:.2f}'}（≦ 0.4）・"
                f"境目に乗った試行 {pk['n_out']}{'・' + pk['why'] if pk['why'] else ''}（平均 {mean if mean is None else f'{mean:+.2f}'}・"
                f"σ {std if std is None else f'{std:.2f}'} は記録だけ）/ "
                f"(p) 縁が見えた {seen_p}/{a.n}（0 のはず、最大 / σ {[round(r['snr'], 1) for r in rp]}）: {'OK' if good else 'NG'}")
    except Exception as e:
        import traceback
        log("ERROR: 道具が例外で止まった:\n" + traceback.format_exc())
        ok = False
    # リングは rectap が終わりに閉じる（atexit）
    if a.out and summ:
        json.dump(dict(adc=summ, bitfile=a.bitfile, raw_core=a.raw_core, t=time.time()), open(a.out + ".f2.json", "w"), indent=1)
        np.savez_compressed(a.out + ".f2.npz", **{f"{k}_{tag}_x": np.array([r["x"] for r in v[i]]) for k, v in raw.items()
                                                 for i, tag in enumerate(("a", "p"))},
                            **{f"{k}_{tag}_meta": np.array([[r["dump_t"], r["stamp"], r["s0"], r["i_e"]] for r in v[i]]) for k, v in raw.items()
                               for i, tag in enumerate(("a", "p"))})
        log(f"記録: {a.out}.f2.json・{a.out}.f2.npz")
    log(f"この回（1 回目か 2 回目）: {'通過' if ok else '失敗'}。2 回そろったら --combine")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
