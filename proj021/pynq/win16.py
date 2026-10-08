#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj015 — 4 ADC × 4 窓（16 窓）を同時に動かす判定。

  sudo python3 win16.py --clkin 0 --ref 10            （SG の宛先は --sg か環境変数 RFSOC_SG）

判定:
  W-10 窓どうしの独立: 16 窓を同時に回し、CW（既定 IF 3010.5 MHz）を窓 0 にだけ入れる。ほかの 3 窓（同じ粗い ch に置いた窓・
       別の粗い ch の窓・遠い狭い窓）に、SG を切ったときより有意に（> 6σ）大きい ch が無いか、あってもその電力が
       窓 0 の CW の山より 60 dB 以上低いこと。電力は 1 フレームあたり・G と SHIFT をそろえた単位で比べる（W-6 の式: 窓の幅によらない）
  W-11 読み出しの時間: 16 窓を 0.1 s ずつ積分して N 回、届いたダンプを全部読む。1 回分（16 窓）の読み出しの時間が 100 ms に
       収まること・ダンプの番号が飛ばないこと・FLAGS[1]（溜めの読み出しが間に合わない）が立たないこと
  （ADC 間の漏れは、SG がすべての ADC に分けて入っている今の配線では測れない。1 本だけに入れる配線で別に測る）

窓の置き方（4 ADC で同じ。--layout で変える）: 窓 0 = IF 3010・8 MHz（CW が入る）/ 窓 1 = IF 2985・16 MHz（同じ粗い ch、CW は窓の端から
  17.5 MHz 外）/ 窓 2 = IF 3300・64 MHz（別の粗い ch）/ 窓 3 = IF 2600・2 MHz（遠い狭い窓、G = 5）。k·fs/8 の線は避けた
"""
import argparse
import atexit
import os
import sys
import time

import numpy as np

import spectrometer as S
import window as WN

try:
    import sg as SGMOD
except ImportError:
    SGMOD = None

LAYOUT = [(3010.0, 8.0), (2985.0, 16.0), (3300.0, 64.0), (2600.0, 2.0)]
FLOOR_LO, FLOOR_HI = 16.0, 4096.0      # SG を切った床（1 フレームあたりの中央値）をこの範囲に（量子化 ≈ 0.67 LSB² に埋もれず、飽和から遠い）


def log(*a):
    print(*a, flush=True)


def open_all(ol):
    wins = []
    for a in range(4):
        ip = getattr(ol, f"win_core_{a}", None)
        if ip is None:
            log(f"ERROR: ol.win_core_{a} が無い（proj015 の 4 ADC × 4 窓の .bit が載っていない）"); sys.exit(1)
        w0 = WN.Win(ip.mmio, base=0, adc=a, win=0)
        ia, nw = w0.ard(WN.R_A_ID), w0.ard(WN.R_A_NW)
        if ia not in (WN.ID_ADC,) + WN.ID_ADC_R1 or nw != 4:
            log(f"ERROR: win_core_{a} の ADC の共通 ID {ia:08x}・NW {nw}"); sys.exit(1)
        for w in range(4):
            wn = WN.Win(ip.mmio, base=WN.WIN_STRIDE * w, adc=a, win=w)
            ident = wn.rd(WN.R_ID)
            if ident not in (WN.ID_WIN,) + WN.ID_WIN_R2:
                log(f"ERROR: win_core_{a} の窓 {w} の ID {ident:08x}"); sys.exit(1)
            if wn.rd(0x90) != w:
                log(f"ERROR: win_core_{a} の窓 {w} の WIDX {wn.rd(0x90)}"); sys.exit(1)
            wins.append(wn)
    return wins


def start(wins, cfg, shifts, tint):
    seq = {}
    for wn in wins:
        c, k, dphi, ns, ifc, w = cfg[wn.win]
        seq[(wn.adc, wn.win)] = wn.run(WN.nacc_for(w, tint), 0, shifts[wn.win])     # NDUMP 0 = 止めるまで
    return seq


def stop(wins):
    for wn in wins:
        wn.wr(WN.R_CTRL, WN.CTRL_STOP)


def collect(wins, seq, ndump, tint, timing=None):
    """各窓のダンプを ndump 個ずつ集めて平均する（1 フレームあたり）。timing があれば 1 回の読み出しの時間を足していく"""
    acc = {key: [] for key in seq}
    ks = {key: [] for key in seq}
    t_end = time.time() + tint * (ndump + 3) + 2
    while time.time() < t_end and min(len(v) for v in acc.values()) < ndump:
        for wn in wins:
            key = (wn.adc, wn.win)
            if len(acc[key]) >= ndump:
                continue
            s = wn.rd(WN.R_SEQ)
            if s != seq[key]:
                t0 = time.perf_counter()
                m, spec, _ = wn.read_dump()
                if timing is not None:
                    timing.append((key, time.perf_counter() - t0))
                seq[key] = m["seq"]
                acc[key].append(spec.astype(float) / max(m["n"], 1))
                ks[key].append((m["k"], m["n"], m["sat"], m["flags"]))
        time.sleep(0.0005)
    return {k: np.array(v) for k, v in acc.items()}, ks


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=S.BITFILE)
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--tone", type=float, default=3010.5, help="CW の IF [MHz]（窓 0 の中に置く）")
    p.add_argument("--sg", default=None)
    p.add_argument("--sg-dbm", type=float, default=-20.0)
    p.add_argument("--shift-tone", type=int, default=11, help="CW の入る窓 0 の SHIFT（W-1・W-6 と同じ）")
    p.add_argument("--tint", type=float, default=0.1)
    p.add_argument("--ndump", type=int, default=10, help="W-10 の 1 状態あたりのダンプの数")
    p.add_argument("--nread", type=int, default=50, help="W-11 で読むダンプの数（窓ごと）")
    p.add_argument("--sigma", type=float, default=6.0)
    p.add_argument("--req", type=float, default=60.0, help="W-10 の要求 [dB]")
    p.add_argument("--read-max", type=float, default=0.100, help="W-11: 16 窓の 1 回分の読み出しの上限 [s]")
    p.add_argument("--out", default=None)
    a = p.parse_args()

    cfg = {}
    for w, (ifc, wd) in enumerate(LAYOUT):
        c, k, dphi, ns, ifc2 = WN.window_params(ifc, wd)
        cfg[w] = (c, k, dphi, ns, ifc2, wd)
        log(f"窓 {w}: IF {ifc2:.6f} ± {wd / 2} MHz / WK {k} / WNS {ns}（G {WN.g_of(ns)}）")
    c0, _, _, ns0, _, w0 = cfg[0]
    if abs(4096.0 - a.tone - c0) >= 0.45 * w0:
        log("ERROR: CW が窓 0 の中央 90 % に無い"); sys.exit(1)

    from pynq import Overlay
    import xrfdc
    S.setup_clocks(a.clkin, a.ref)
    ol = Overlay(a.bitfile)
    log(f"Overlay: {a.bitfile}")
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    S.check_tiles(ol.rfdc, 2)
    if a.settle > 0:
        time.sleep(a.settle)
    wins = open_all(ol)
    if SGMOD is None or not (a.sg or os.environ.get("RFSOC_SG")):
        log("ERROR: SG の宛先が無い（--sg か 環境変数 RFSOC_SG）"); sys.exit(1)
    sg = SGMOD.SG(a.sg, log=log)
    atexit.register(sg.close)
    sg.set_freq_mhz(a.tone)
    sg.set_dbm(a.sg_dbm)
    sg.set_output(False)

    for wn in wins:
        c, k, dphi, ns, ifc, w = cfg[wn.win]
        wn.set_window(k, dphi, ns)
    time.sleep(0.05)
    for wn in wins:
        wn.wr(WN.R_CTRL, WN.CTRL_CLR)

    ok = True

    def judge(cond, msg):
        nonlocal ok
        log(("  OK  " if cond else "  NG  ") + msg)
        ok &= bool(cond)

    # ---- SHIFT を決める（SG を切った床の中央値を FLOOR_LO..HI に）----
    shifts = {0: a.shift_tone, 1: 9, 2: 10, 3: 8}
    for it in range(4):
        seq = start(wins, cfg, shifts, a.tint)
        off, _ = collect(wins, seq, 2, a.tint)
        stop(wins)
        moved = False
        for w in (1, 2, 3):
            fl = min(float(np.median(off[(adc, w)][-1])) for adc in range(4))
            if fl < FLOOR_LO and shifts[w] > 0:
                shifts[w] -= 1; moved = True
            elif fl > FLOOR_HI:
                shifts[w] += 1; moved = True
        if not moved:
            break
    log(f"SHIFT: {shifts}")

    # ---- W-10 ----
    st = {}
    for name, on in (("off1", False), ("on", True), ("off2", False)):
        sg.set_output(on)
        time.sleep(0.2)
        seq = start(wins, cfg, shifts, a.tint)
        st[name], meta = collect(wins, seq, a.ndump, a.tint)
        stop(wins)
        nsat = sum(m[2] for v in meta.values() for m in v)
        log(f"{name}: SG {'ON' if on else 'OFF'}・ダンプ {min(len(v) for v in st[name].values())} 個 / 窓・飽和 {nsat}")
    sg.set_output(False)

    def unit(w):           # 1 フレームあたりの電力を「窓 0 と同じ G・SHIFT」の単位へ（W-6: CW の 1 フレームの電力は幅によらない）
        ns = cfg[w][3]
        return (4.0 ** (WN.g_of(ns0) - WN.g_of(ns))) * (4.0 ** (shifts[w] - shifts[0]))

    res = {}
    for adc in range(4):
        on0 = st["on"][(adc, 0)].mean(0); of0 = st["off1"][(adc, 0)].mean(0)
        ifs = WN.ch_if(c0, w0)
        b_pred = int(np.argmin(np.abs(ifs - a.tone)))
        b_meas = int(np.argmax(on0 - of0))
        peak = (on0 - of0)[b_meas]
        judge(b_meas == b_pred and peak > 0, f"W-10 ADC {adc} 窓 0: CW が予言の ch {b_pred} に出る（実測 {b_meas}・山 {peak:.4g} / フレーム）")
        for w in (1, 2, 3):
            key = (adc, w)
            on = st["on"][key]; of = np.concatenate([st["off1"][key], st["off2"][key]])
            m_on, m_of = on.mean(0), of.mean(0)
            sd = np.sqrt(of.var(0, ddof=1) / len(on) + of.var(0, ddof=1) / len(of))
            ex = m_on - m_of
            sig = ex / np.maximum(sd, 1e-12)
            hot = np.where(sig > a.sigma)[0]
            worst = int(np.argmax(sig))
            lvl = 10 * np.log10(max(ex[worst] * unit(w), 1e-30) / peak) if ex[worst] > 0 else -999.0
            if len(hot):
                lvl_hot = 10 * np.log10(max(ex[hot].max() * unit(w), 1e-30) / peak)
            else:
                lvl_hot = -999.0
            ifs_w = WN.ch_if(cfg[w][0], cfg[w][5])
            judge(lvl_hot <= -a.req,
                  f"W-10 ADC {adc} 窓 {w}（IF {cfg[w][4]:.0f} ± {cfg[w][5] / 2:g}）: > {a.sigma:g}σ の ch {len(hot)} 個"
                  + (f"・その最大 {lvl_hot:+.1f} dB（CW の山に対して）" if len(hot) else "")
                  + f"・最大の σ {sig[worst]:+.1f}（ch {worst}・IF {ifs_w[worst]:.4f}・{lvl:+.1f} dB）（要求 ≦ −{a.req:g} dB）")
            res[f"sig_{adc}_{w}"] = sig

    # ---- W-11 ----
    timing = []
    seq = start(wins, cfg, shifts, a.tint)
    t0 = time.time()
    got, meta = collect(wins, seq, a.nread, a.tint, timing=timing)
    stop(wins)
    el = time.time() - t0
    nmin = min(len(v) for v in got.values())
    skip = 0; f1 = 0
    for key, v in meta.items():
        kk = [m[0] for m in v]
        skip += sum(1 for x, y in zip(kk, kk[1:]) if y != x + 1)
        f1 += sum(1 for m in v if m[3] & 0x2)
    tt = np.array([t for _, t in timing])
    per_cycle = tt.sum() / max(nmin, 1)
    log(f"W-11: {el:.1f} s で窓ごと {nmin} 個以上・読んだダンプ {len(tt)} 個・1 個の読み出し 平均 {tt.mean() * 1e3:.2f} ms / 最大 {tt.max() * 1e3:.2f} ms")
    judge(nmin >= a.nread, f"W-11: 16 窓ともダンプ {a.nread} 個を読めた（最少 {nmin}）")
    judge(per_cycle <= a.read_max, f"W-11: 16 窓の 1 回分の読み出しの時間 {per_cycle * 1e3:.1f} ms（上限 {a.read_max * 1e3:.0f} ms・積分 {a.tint * 1e3:.0f} ms）")
    judge(skip == 0, f"W-11: ダンプの番号の飛び {skip}")
    judge(f1 == 0, f"W-11: FLAGS[1]（溜めの読み出しが間に合わない）の立ったダンプ {f1}")

    if a.out:
        np.savez(a.out + ".win16.npz", shifts=np.array([shifts[w] for w in range(4)]), read_t=tt, **res,
                 **{f"{n}_{k[0]}_{k[1]}": v for n, d in st.items() for k, v in d.items()})
        log(f"書いた: {a.out}.win16.npz")
    log("RESULT " + ("OK" if ok else "NG"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
