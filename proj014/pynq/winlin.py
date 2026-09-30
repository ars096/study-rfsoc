#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj014 — 判定 W-7: 線形性と頭打ち。窓の中の CW の強さ（SG のレベル）を振り、窓と全帯域の比が一定か、どこで何が飽和し始めるかを見る。

  python3 winlin.py --if 3000 --w 256 --tone 3010.5 --from -20 --to 10 --step 1 --clkin 0 --ref 10 --out lin256

1 点ごとに（SG を切った基準を引いて）:
  - P_win: 窓の CW の ch の電力 / P_full: 全帯域の CW の ch の電力（ch の端数は sinc² で戻す）
  - 比 G = P_win / P_full / (64·4^(SHIFT_full − SHIFT))。**線形なら SG のレベルによらず一定**（W-6 と同じ量）
  - 傾き: P_full の SG のレベルに対する傾き（ADC と SG を含めて 1 dB / dB のはず）
  - 余裕（頭打ちまでの dB）:
      q（電力の前の 18 bit）: 20·log10(2^17 / √P_win)   ← 窓の CW の ch の振幅
      z（FFT の入力の 18 bit、スナップショット）: 20·log10(2^17 / max(|re|, |im|))
  - 飽和の数え: pfb（PFB_SAT）・ddc（DDC_SAT）・窓のダンプ（q の飽和）・全帯域のダンプ（q の飽和）。その点で増えた分
判定 W-7: 飽和がどこにも無い点で、比 G の最大と最小の差 ≦ --tol（既定 0.05 dB）。どの段が最初に飽和したか（SG のレベル）を出す
"""
import argparse
import atexit
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
NFFT_W = 4096
DF_FULL = 0.5


def log(*a):
    print(*a, flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--if", dest="if_c", type=float, default=3000.0)
    p.add_argument("--w", type=float, default=256.0)
    p.add_argument("--no-grid", action="store_true")
    p.add_argument("--tone", type=float, default=None, help="CW の IF [MHz]（既定: 窓の中心から 0.04W の辺りで、窓と全帯域の両方の ch の中心）")
    p.add_argument("--from", dest="l_from", type=float, default=-20.0, help="SG のレベルの始め [dBm]")
    p.add_argument("--to", dest="l_to", type=float, default=10.0, help="SG のレベルの終わり [dBm]")
    p.add_argument("--step", type=float, default=1.0)
    p.add_argument("--shift", type=int, default=None, help="窓の SHIFT（既定: 終わりのレベルで q が飽和しない見当 = 11 + (終わり + 20) / 6）")
    p.add_argument("--shift-full", type=int, default=None, help="全帯域の SHIFT（既定: 8 + (終わり + 20) / 6）")
    p.add_argument("--tint", type=float, default=0.1)
    p.add_argument("--tol", type=float, default=0.05, help="W-7 の比の最大と最小の差の許容 [dB]")
    p.add_argument("--sg", default=None)
    p.add_argument("--sg-settle", type=float, default=0.1)
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--bitfile", default=None)
    p.add_argument("--allow-nopreset", action="store_true")
    p.add_argument("--out", default=None, help="PREFIX.lin.npz と PREFIX.lin.png")
    a = p.parse_args()

    import window as WN
    import spectrometer as S
    import sg as SGMOD
    from pynq import Overlay
    import xrfdc                                   # Overlay() より前に import する（VERSIONS.md）
    c, k, dphi, ns, if_c = WN.window_params(a.if_c, a.w, grid=not a.no_grid)
    w = a.w
    dw = w / NFFT_W
    if a.tone is None:
        nu = round((c + 0.04 * w) / DF_FULL) * DF_FULL - c       # 全帯域の ch の中心にも揃える（端数の目減りなし）
        if abs(nu) > 0.45 * w:
            nu = round(0.04 * w / dw) * dw
    else:
        nu = round(((4096.0 - a.tone) - c) / dw) * dw
    tone = 4096.0 - (c + nu)
    if abs(nu) > 0.45 * w:
        log("ERROR: CW が窓の中央 90 % の外"); sys.exit(1)
    b = int(round(nu / dw)) % NFFT_W
    f = c + nu
    kf = int(round(f / DF_FULL)); df = f / DF_FULL - kf
    levels = np.arange(a.l_from, a.l_to + a.step / 2, a.step)
    sh = a.shift if a.shift is not None else int(min(15, 11 + np.ceil((a.l_to + 20.0) / 6.02)))
    shf = a.shift_full if a.shift_full is not None else int(min(15, 8 + np.ceil((a.l_to + 20.0) / 6.02)))
    pred = 64.0 * 4.0 ** (shf - sh)
    log(f"窓: IF {if_c:.6f} MHz ± {w / 2} / WK {k} / WNS {ns}・CW IF {tone:.6f} MHz（ν {nu:+.5f}、窓の ch {b}・全帯域の ch {kf}、端数 {df:+.3f}）")
    log(f"SG: {levels[0]:+.1f}〜{levels[-1]:+.1f} dBm を {a.step} dB 刻み（{len(levels)} 点）・SHIFT 窓 {sh} / 全帯域 {shf}・{a.tint} s / 点")

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
    if levels.min() < sg.pmin - 1e-6 or levels.max() > sg.pmax + 1e-6:
        log(f"ERROR: SG のレベルの範囲 {sg.pmin:+.1f}〜{sg.pmax:+.1f} dBm の外を含む"); sys.exit(1)
    sg.set_output(False)
    sg.set_freq_mhz(tone)
    wn.set_window(k, dphi, ns)
    spf = S.Spec(ol.spec_core_1.mmio, idx=1, label="ADC_B")

    def measure():
        nw = WN.nacc_for(w, a.tint)
        nf = max(1, int(round(a.tint / S.T_FRAME)))
        sf = spf.run(nf, 1, shf)
        s = wn.run(nw, 1, sh)
        to = a.tint * 3 + 2
        if wn.wait_dump(s, to) is None or spf.wait_dump(sf, to) is None:
            raise RuntimeError("ダンプが閉じない")
        m, pw, snap = wn.read_dump(with_snap=True)
        mf, pf, _ = spf.read_dump()
        return pw.astype(float) / m["n"], pf.astype(float) / mf["n"], snap, m["sat"], mf.get("sat", 0)

    t0 = time.time()
    pw0, pf0, _, _, _ = measure()
    sg.set_output(True)
    sg.log = lambda *x: None
    rows = []
    first = {}
    for lv in levels:
        sg.set_dbm(lv)
        time.sleep(a.sg_settle)
        s_p0, s_d0 = wn.rd(WN.R_PFB_SAT), wn.rd(WN.R_DDC_SAT)
        pw, pf, snap, sat_w, sat_f = measure()
        d_p, d_d = wn.rd(WN.R_PFB_SAT) - s_p0, wn.rd(WN.R_DDC_SAT) - s_d0
        pwin = pw[b] - pw0[b]
        pfull = (pf[kf] - pf0[kf]) / np.sinc(df) ** 2
        G = 10 * np.log10(max(pwin, 1e-30) / max(pfull, 1e-30) / pred)
        hq = 20 * np.log10(2 ** 17 / np.sqrt(max(pw[b], 1e-30)))
        zmax = float(np.max(np.abs(np.concatenate([snap.real, snap.imag])))) if snap is not None else np.nan
        hz = 20 * np.log10(2 ** 17 / max(zmax, 1.0))
        sat = dict(pfb=d_p, ddc=d_d, win=int(sat_w), full=int(sat_f))
        for kk, v in sat.items():
            if v and kk not in first:
                first[kk] = lv
        rows.append((lv, 10 * np.log10(max(pwin, 1e-30)), 10 * np.log10(max(pfull, 1e-30)), G, hq, hz, d_p, d_d, int(sat_w), int(sat_f)))
        log(f"  SG {lv:+6.1f} dBm: 窓 {rows[-1][1]:7.2f}・全帯域 {rows[-1][2]:7.2f} dB → 比 {G:+.3f} dB・余裕 q {hq:5.1f} / z {hz:5.1f} dB"
            + ("・飽和 " + " ".join(f"{kk} {v}" for kk, v in sat.items() if v) if any(sat.values()) else ""))
    sg.set_output(False)
    r = np.array(rows)
    clean = (r[:, 6] == 0) & (r[:, 7] == 0) & (r[:, 8] == 0) & (r[:, 9] == 0)
    ok = True
    if clean.sum() >= 2:
        ptp = float(np.ptp(r[clean, 3]))
        slope = float(np.polyfit(r[clean, 0], r[clean, 2], 1)[0])
        ok = ptp <= a.tol
        log(("  OK  " if ok else "  NG  ") + f"W-7: 飽和の無い {clean.sum()} 点（{r[clean, 0].min():+.0f}〜{r[clean, 0].max():+.0f} dBm）で、"
            f"窓 / 全帯域の比の最大 − 最小 {ptp:.3f} dB（許容 {a.tol}）・平均 {np.mean(r[clean, 3]):+.3f} dB・全帯域の傾き {slope:.4f} dB / dB")
    else:
        ok = False
        log("  NG  W-7: 飽和の無い点が 2 点に満たない（--shift・--shift-full を上げる）")
    log("最初に飽和した段（SG のレベル）: " + (" / ".join(f"{kk} {v:+.1f} dBm" for kk, v in sorted(first.items(), key=lambda x: x[1])) if first else "なし"))
    log(f"かかった時間 {time.time() - t0:.0f} s")
    if a.out:
        np.savez(a.out + ".lin.npz", rows=r, cols="dBm, win_dB, full_dB, ratio_dB, headroom_q_dB, headroom_z_dB, sat_pfb, sat_ddc, sat_win, sat_full",
                 c=c, w=w, k=k, ns=ns, tone_if=tone, shift=sh, shift_full=shf)
        log(f"書いた: {a.out}.lin.npz")
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(3, 1, figsize=(8, 9), sharex=True)
            ax[0].plot(r[:, 0], r[:, 1] - r[0, 1], "o-", ms=3, label="window")
            ax[0].plot(r[:, 0], r[:, 2] - r[0, 2], "s-", ms=3, label="full band")
            ax[0].plot(r[:, 0], r[:, 0] - r[0, 0], "k:", lw=.8, label="1 dB/dB")
            ax[0].set_ylabel("power (rel.) [dB]"); ax[0].legend(); ax[0].grid(alpha=.3)
            ax[1].plot(r[:, 0], r[:, 3], "o-", ms=3); ax[1].set_ylabel("window / full [dB]"); ax[1].grid(alpha=.3)
            ax[2].plot(r[:, 0], r[:, 4], "o-", ms=3, label="q (FFT out, 18 bit)")
            ax[2].plot(r[:, 0], r[:, 5], "s-", ms=3, label="z (FFT in, 18 bit)")
            ax[2].axhline(0, color="r", lw=.8); ax[2].set_ylabel("headroom [dB]"); ax[2].set_xlabel("SG level [dBm]")
            ax[2].legend(); ax[2].grid(alpha=.3)
            for i in np.where(~clean)[0]:
                for axi in ax:
                    axi.axvspan(r[i, 0] - a.step / 2, r[i, 0] + a.step / 2, color="r", alpha=.08)
            fig.suptitle(f"linearity: window IF {if_c:.1f} MHz, W = {w:g} MHz, CW {tone:.3f} MHz, SHIFT {sh} / {shf}")
            fig.tight_layout(); fig.savefig(a.out + ".lin.png", dpi=120)
            log(f"書いた: {a.out}.lin.png")
        except ImportError:
            pass
    log("RESULT " + ("OK" if ok else "NG"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
