#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj014 — 窓の通過特性（フィルタのカーブ）: SG の周波数を刻みで動かし、窓に出た CW の強さを SG の周波数に対して描く。

  python3 winresp.py --if 3000 --w 256 --from 2500 --to 3500 --step 1 --clkin 0 --ref 10 --out resp256

測り方（winsweep.py の W-2・W-3 と同じ約束）:
  - SG を切った基準を SHIFT ごとに測り、ch ごとに引く
  - 窓の値は、同じ ADC の全帯域（spec_core_1）で測った CW の電力で割る（アナログの傾きを消す。全帯域の ch の端数は sinc² で戻す）
      強さ [dB] = (P_win[b] − P_win,off[b]) / ((P_full − P_full,off) / sinc²(δ_f)) / (64·4^(SHIFT_full − SHIFT))
    b は模型が言う行き先の ch（窓の中なら CW そのもの、窓の外なら出力のレート W で折り返った先）
  - SHIFT は点ごとに 2 通りから選ぶ: 模型の利得が --hi-db（既定 −30 dB）より大きい点は SHIFT_hi（強い CW で飽和しない）、
    それ以外は SHIFT_lo（窓の雑音の床 ≧ 16 LSB² で量子化に埋もれない。SG を切った床から自動）
  - 検出限界は引き算の後の揺れ（中央 90 % の ch の MAD）の 5 倍。それより下は限界の値を「▽」で描く
  - 窓の中の最も強い ch（行き先の ch 以外）も記録する（ADC の線・像などの目安）
  - 図: 上 = 全体（dB、模型の線・検出限界・窓の端 ±0.5W と中央 90 % の印）、下 = 通過域の拡大。
    **窓の外の CW は、行き先（折り返った先）が中央 90 % なら塗りつぶし、両端 5 % なら白抜き**で描く。
    両端 5 % は使わない約束なので、そこに落ちる折り返し（模型でも −56 dB 前後の点がある）は要求（−60 dB）の外
"""
import argparse
import atexit
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import winsweep as SW  # noqa: E402

NFFT_W = 4096
FS = 4096.0
DF_FULL = 0.5


def log(*a):
    print(*a, flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--if", dest="if_c", type=float, default=3000.0, help="窓の IF の中心 [MHz]")
    p.add_argument("--w", type=float, default=256.0)
    p.add_argument("--no-grid", action="store_true")
    p.add_argument("--from", dest="f_from", type=float, default=None, help="SG の IF の始め [MHz]（既定: 中心 − 2W）")
    p.add_argument("--to", dest="f_to", type=float, default=None, help="SG の IF の終わり [MHz]（既定: 中心 + 2W）")
    p.add_argument("--step", type=float, default=1.0, help="刻み [MHz]")
    p.add_argument("--sg", default=None)
    p.add_argument("--sg-dbm", type=float, default=0.0, help="SG のレベル [dBm]（既定 0。ADC で −14 dBm 前後の見当）")
    p.add_argument("--sg-settle", type=float, default=0.05)
    p.add_argument("--shift-hi", type=int, default=None, help="強い点の窓の SHIFT（既定: −20 dBm で 11 を基準に 6 dB ごとに 1）")
    p.add_argument("--shift-lo", type=int, default=None, help="弱い点の窓の SHIFT（既定: 雑音の床から自動）")
    p.add_argument("--shift-full", type=int, default=None, help="全帯域の SHIFT（既定: −20 dBm で 8 を基準に 6 dB ごとに 1）")
    p.add_argument("--hi-db", type=float, default=-30.0, help="模型の利得がこれより大きい点は SHIFT_hi で測る [dB]")
    p.add_argument("--tint", type=float, default=0.05, help="強い点の積分 [s]")
    p.add_argument("--tint-lo", type=float, default=0.2, help="弱い点の積分 [s]")
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--bitfile", default=None)
    p.add_argument("--coef", default=None)
    p.add_argument("--allow-nopreset", action="store_true")
    p.add_argument("--out", default=None, help="PREFIX.resp.npz と PREFIX.resp.png")
    p.add_argument("--dry-run", action="store_true", help="ボードに触らず、模型のカーブだけを描く")
    a = p.parse_args()

    import window as WN
    c, k, dphi, ns, if_c = WN.window_params(a.if_c, a.w, grid=not a.no_grid)
    w = a.w
    dw = w / NFFT_W
    f_from = a.f_from if a.f_from is not None else if_c - 2 * w
    f_to = a.f_to if a.f_to is not None else if_c + 2 * w
    ifs = np.arange(f_from, f_to + a.step / 2, a.step)
    ifs = ifs[(ifs > 2048.0 + 1.0) & (ifs < 4096.0 - 1.0)]          # ゾーン 2 の中（全帯域の端 1 MHz は基準にならない）
    f = 4096.0 - ifs
    coef_path = a.coef or next((q for q in (os.path.join(HERE, "win_coef.vh"), os.path.join(HERE, "..", "src", "win_coef.vh"))
                                if os.path.exists(q)), None)
    if coef_path is None:
        log("ERROR: win_coef.vh が無い"); sys.exit(1)
    coef = SW.load_coef(coef_path)
    nu_p, g_p, nu_m, g_m = SW.model_db(coef, f, c, w)
    hi = g_p > a.hi_db
    dbm = a.sg_dbm
    sh_hi = a.shift_hi if a.shift_hi is not None else int(min(15, 11 + np.ceil((dbm + 20.0) / 6.02)))
    sh_full = a.shift_full if a.shift_full is not None else int(min(15, 8 + np.ceil((dbm + 20.0) / 6.02)))
    t_est = hi.sum() * (a.tint + 0.1) + (~hi).sum() * (a.tint_lo + 0.1)
    log(f"窓: IF {if_c:.6f} MHz ± {w / 2}（c = {c:.6f}）/ WK {k} / WDPHI {dphi:#010x} / WNS {ns}")
    log(f"SG: IF {ifs[0]:.3f}〜{ifs[-1]:.3f} MHz を {a.step} MHz 刻み（{len(ifs)} 点、強い点 {hi.sum()}・弱い点 {(~hi).sum()}）・{dbm:+.1f} dBm・"
        f"SHIFT 強い点 {sh_hi} / 全帯域 {sh_full}・見込み {t_est / 60:.1f} 分")

    def plot(meas=None):
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            return
        fig, ax = plt.subplots(2, 1, figsize=(10, 7.5))
        edge_lo, edge_hi = 4096 - c - 0.5 * w, 4096 - c + 0.5 * w
        for axi, zoom in ((ax[0], False), (ax[1], True)):
            axi.plot(ifs, g_p, "-", color="0.35", lw=1, label="model (+f)")
            if meas is not None:
                lev, lim, det = meas
                cen = np.abs(nu_p) <= 0.45 * w
                axi.plot(ifs[det & cen], lev[det & cen], ".", ms=3, color="C0", label="measured (lands in central 90%)")
                axi.plot(ifs[det & ~cen], lev[det & ~cen], "o", ms=3, mfc="none", color="C2", label="measured (lands in 5% edges)")
                axi.plot(ifs[~det], lim[~det], "v", ms=2.5, color="C1", alpha=.6, label="below detection limit")
            for x in (edge_lo, edge_hi):
                axi.axvline(x, color="k", lw=.6)
            for x in (4096 - c - 0.45 * w, 4096 - c + 0.45 * w):
                axi.axvline(x, color="k", lw=.5, ls=":")
            axi.set_xlabel("SG IF [MHz]"); axi.set_ylabel("window / full-band [dB]"); axi.grid(alpha=.3)
            if zoom:
                axi.set_xlim(edge_lo - 0.1 * w, edge_hi + 0.1 * w); axi.set_ylim(-8, 1)
            else:
                axi.set_ylim(-120, 5); axi.axhline(-60, color="r", lw=.6, ls="--"); axi.legend(loc="lower left", fontsize=8)
        fig.suptitle(f"window IF {if_c:.3f} MHz, W = {w:g} MHz (k = {k}, d = {c - 128 * k:+g} MHz), SG {dbm:+.1f} dBm")
        fig.tight_layout(); fig.savefig(a.out + ".resp.png", dpi=120)
        log(f"書いた: {a.out}.resp.png")

    if a.dry_run:
        for x, g in zip(ifs[:: max(1, len(ifs) // 20)], g_p[:: max(1, len(ifs) // 20)]):
            log(f"  IF {x:9.3f} MHz → 模型 {g:+8.2f} dB")
        if a.out:
            plot()
        return 0

    import spectrometer as S
    import sg as SGMOD
    from pynq import Overlay
    import xrfdc                                   # Overlay() より前に import する（VERSIONS.md）
    S.setup_clocks(a.clkin, a.ref)
    ol = Overlay(a.bitfile or S.BITFILE)
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    S.check_tiles(ol.rfdc, 2)
    if a.settle > 0:
        time.sleep(a.settle)
    wn = WN.open_win(ol, a.allow_nopreset)
    if not (a.sg or os.environ.get("RFSOC_SG")):
        log("ERROR: SG の宛先が無い（--sg か 環境変数 RFSOC_SG）"); sys.exit(1)
    sg = SGMOD.SG(a.sg, log=log)
    atexit.register(sg.close)
    sg.set_output(False)
    sg.set_dbm(dbm)
    wn.set_window(k, dphi, ns)
    spf = S.Spec(ol.spec_core_1.mmio, idx=1, label="ADC_B")
    nb = np.where(np.arange(NFFT_W) < NFFT_W // 2, np.arange(NFFT_W), np.arange(NFFT_W) - NFFT_W) * dw
    mid = np.abs(nb) <= 0.45 * w
    nsat = [0]

    def measure(tint, shw, shf):
        nw = WN.nacc_for(w, tint)
        nf = max(1, int(round(tint / S.T_FRAME)))
        sf = spf.run(nf, 1, shf)
        s = wn.run(nw, 1, shw)
        to = tint * 3 + 2
        if wn.wait_dump(s, to) is None or spf.wait_dump(sf, to) is None:
            raise RuntimeError("ダンプが閉じない")
        m, pw, _ = wn.read_dump()
        mf, pf, _ = spf.read_dump()
        sat = bool(m["sat"] or mf.get("sat", 0))
        nsat[0] += sat
        return pw.astype(float) / m["n"], pf.astype(float) / mf["n"], sat

    t0 = time.time()
    log("基準（SG を切る）…")
    pw_hi0, pf0, _ = measure(0.5, sh_hi, sh_full)
    fl = float(np.median(measure(0.5, 11, sh_full)[0][mid]))
    true = max(fl - 0.67, 0.02)
    sh_lo = a.shift_lo if a.shift_lo is not None else max(0, 11 - max(0, int(np.ceil(np.log(16.0 / true) / np.log(4.0)))))
    pw_lo0, _, _ = measure(0.5, sh_lo, sh_full)
    fl_lo = float(np.median(pw_lo0[mid]))
    log(f"  窓の床: SHIFT 11 で {fl:.2f} LSB²（量子化を除いて {true:.2f}）→ 弱い点は SHIFT {sh_lo}（床 {fl_lo:.1f}）")
    sg.set_output(True)
    sg.log = lambda *x: None

    lev = np.full(len(ifs), np.nan); lim = np.full(len(ifs), np.nan); det = np.zeros(len(ifs), bool)
    other = np.full(len(ifs), np.nan); other_if = np.full(len(ifs), np.nan); used_hi = hi.copy(); sat_pt = np.zeros(len(ifs), bool)
    for i, (x, fi) in enumerate(zip(ifs, f)):
        sg.set_freq_mhz(x)
        time.sleep(a.sg_settle)
        shw = sh_hi if hi[i] else sh_lo
        pw, pf, sat = measure(a.tint if hi[i] else a.tint_lo, shw, sh_full)
        sat_pt[i] = sat
        pw0 = pw_hi0 if hi[i] else pw_lo0
        pred = WN.pred_ratio(ns, sh_full, shw)
        kf = int(round(fi / DF_FULL)); df = fi / DF_FULL - kf
        ref = (pf[kf] - pf0[kf]) / (np.sinc(df) ** 2)
        diff = pw - pw0
        b = int(round(nu_p[i] / dw)) % NFFT_W
        use = mid & (np.abs(np.arange(NFFT_W) - b) > 3)
        sig = SW.robust_sigma(diff[use])
        ex = diff[b]
        lim[i] = 10 * np.log10(max(5 * sig, 1e-30) / (ref * pred))
        if ex > 5 * sig:
            lev[i] = 10 * np.log10(ex / (ref * pred)); det[i] = True
        j = int(np.argmax(np.where(use, diff, -np.inf)))
        other[i] = 10 * np.log10(max(diff[j], 1e-30) / (ref * pred)); other_if[i] = 4096 - c - nb[j]
        if i % 25 == 0 or (hi[i] and abs(nu_p[i]) > 0.44 * w and abs(nu_p[i]) < 0.56 * w):
            log(f"  [{i + 1}/{len(ifs)}] SG IF {x:9.3f} MHz → ν {nu_p[i]:+9.4f}: "
                + (f"{lev[i]:+8.2f} dB" if det[i] else f"< {lim[i]:+.1f} dB") + f"（模型 {g_p[i]:+.2f}）" + ("・飽和" if sat else ""))
    sg.set_output(False)
    inb = hi & det & (np.abs(nu_p) <= 0.45 * w)
    if inb.any():
        d = lev[inb] - g_p[inb]
        log(f"通過域（中央 90 %）: 模型との差 平均 {np.mean(d):+.3f}・最大 {np.max(np.abs(d)):.3f} dB（{inb.sum()} 点）")
    cen = np.abs(nu_p) <= 0.45 * w
    out = np.abs(f - c) > 0.5 * w
    for nm, sel in (("窓の外の CW で、中央 90 % に落ちる", out & cen), ("窓の外の CW で、両端 5 % に落ちる", out & ~cen)):
        if sel.any():
            v = np.where(sel & det, lev, np.where(sel, lim, -np.inf)); jj = int(np.argmax(v))
            log(f"{nm}最大: {'%+.1f dB' % lev[jj] if det[jj] else '< %+.1f dB（検出限界）' % lim[jj]}（SG IF {ifs[jj]:.3f} MHz、模型 {g_p[jj]:+.1f}）"
                f"・模型の最大 {g_p[sel].max():+.1f} dB（{sel.sum()} 点）")
    st = (~hi) & det
    if st.any():
        jj = int(np.argmax(np.where(st, lev, -np.inf)))
        log(f"模型の利得が {a.hi_db:.0f} dB 以下の点で見えた最大: {lev[jj]:+.1f} dB（SG IF {ifs[jj]:.3f} MHz、模型 {g_p[jj]:+.1f}）/ 見えなかった点 {(~hi & ~det).sum()}")
    log(f"飽和した点 {nsat[0]}・FLAGS {wn.rd(WN.R_FLAGS):#x}・かかった時間 {time.time() - t0:.0f} s")
    if a.out:
        np.savez(a.out + ".resp.npz", sg_if=ifs, model_db=g_p, model_nu=nu_p, model_img_db=g_m, model_img_nu=nu_m,
                 lev_db=lev, lim_db=lim, detected=det, hi=used_hi, sat=sat_pt, other_db=other, other_if=other_if,
                 c=c, w=w, k=k, dphi=dphi, ns=ns, sg_dbm=dbm, shift_hi=sh_hi, shift_lo=sh_lo, shift_full=sh_full,
                 pw_hi0=pw_hi0, pw_lo0=pw_lo0, pf0=pf0, if_win=WN.ch_if(c, w))
        log(f"書いた: {a.out}.resp.npz")
        plot((lev, lim, det))
    return 0


if __name__ == "__main__":
    sys.exit(main())
