#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj014 — 判定 W-9: 長時間の安定度（アラン分散）。雑音だけを窓（win_core_0）と全帯域（spec_core_1）で同時に積み続け、
τ0（既定 0.1 s）ごとのダンプの時系列からアラン分散を τ に対して出す。

  python3 winallan.py --if 3000 --w 256 --duration 3600 --clkin 0 --ref 10 --out allan256

時系列（どれも自分の平均で割った相対値）:
  (a) 窓の帯域の電力: 中央 90 % の使える ch の和
  (b) 全帯域の同じ IF の範囲の電力: 同じ周波数の範囲の全帯域の ch の和（アナログの利得の揺らぎは (a) と同じように乗る）
  (c) 窓 / 全帯域: (a) / (b)。**同じ入力を 2 つの分光計で測るので、アナログの揺らぎも雑音の多くも消え、分光計どうしの安定度が残る**
  (d) 分光の安定度（spectroscopic）: 窓の中の 2 つの小帯域（窓の中心 c より下と上。(e) と同じ全帯域の ch に入る窓の ch だけ）の比。帯域全体の利得の揺らぎが消え、
      ラジオメータの雑音と、帯域の形の揺らぎ（ベースライン）が残る。**観測でいちばん効く量**
ラジオメータの予言（白色雑音）: 相対のアラン分散 σ²(τ) = 1 / (M·N_τ)（M = 和をとる ch の数、N_τ = τ のあいだのフレーム数）。
(d) は 1/(M_A·N_τ) + 1/(M_B·N_τ)。窓関数なし・重ならないフレームなので 1 フレームの ch は自由度 2 の χ²
使える ch: 最初の --probe 個のダンプで ch ごとの分散 / 平均² を出し、理想の 99.9 % 点を超える ch（時間で変わる線。ゾーン 1 の混入など）を外す（W-5 と同じ）
  (e) 全帯域の同じ 2 つの小帯域の比（全帯域の ch で）: (d) と同じ入力・同じ周波数の範囲。**入力（アナログ・混入）の帯域の形の揺らぎは (d) と (e) に同じく乗る**
  (f) (d) / (e): 入力の揺らぎが消え、**窓の分光計そのものの帯域の形の安定度**が残る（同じサンプルを見るので雑音の多くも消える）
全帯域の ch は、窓の使える ch（線を外した後）が入る ch だけを使う（実機 1 回目の 10 分で、(b) に線の ch が入って (c) が τ とともに上がった）
判定 W-9: **(f) のアラン分散が、τ ≦ --judge-max（既定 60 s）でラジオメータの予言（(d) + (e)、雑音が独立とした上限）の --tol 倍（既定 2 倍）以内**
（窓の分光計が、入力より悪くしない）。(d)・(e) は同じサンプルを見るので雑音の一部が消え、(f) は予言より小さく出てよい。
(d) の予言との比と、(d) のアラン時間（(d) が予言の 2 倍になる τ）も出す（入力を含めた値）
SHIFT: 窓・全帯域とも、雑音の床が --floor（既定 2000 LSB² / フレーム）前後になるよう、最初のダンプの床から選ぶ
読み出しが間に合わずダンプを飛ばしたら数える（飛ばした所は時系列を切らずに詰める。数が多ければ τ0 を延ばす）
"""
import argparse
import atexit
import os
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
NFFT_W = 4096
DF_FULL = 0.5


def log(*a):
    print(*a, flush=True)


def allan(y, ns):
    """重ねて取るアラン分散（y は相対値の時系列）。ns: 束ねる個数の並び。"""
    out = []
    c = np.concatenate([[0.0], np.cumsum(y)])
    for n in ns:
        if 2 * n > len(y):
            out.append(np.nan); continue
        m = (c[n:] - c[:-n]) / n                        # 長さ n の移動平均
        d = m[n:] - m[:-n]
        out.append(0.5 * np.mean(d ** 2))
    return np.array(out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--if", dest="if_c", type=float, default=3000.0)
    p.add_argument("--w", type=float, default=256.0)
    p.add_argument("--no-grid", action="store_true")
    p.add_argument("--duration", type=float, default=3600.0, help="積む時間 [s]")
    p.add_argument("--tau0", type=float, default=0.1, help="1 ダンプの積分 [s]")
    p.add_argument("--floor", type=float, default=2000.0)
    p.add_argument("--probe", type=int, default=100, help="使える ch を決めるダンプの数")
    p.add_argument("--judge-max", type=float, default=60.0)
    p.add_argument("--tol", type=float, default=2.0)
    p.add_argument("--sg", default=None, help="あれば SG の出力を切って確かめる")
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--bitfile", default=None)
    p.add_argument("--allow-nopreset", action="store_true")
    p.add_argument("--out", default=None, help="PREFIX.allan.npz と PREFIX.allan.png（途中でも 10 分ごとに npz を書き直す）")
    a = p.parse_args()

    import window as WN
    import spectrometer as S
    from pynq import Overlay
    import xrfdc                                   # Overlay() より前に import する（VERSIONS.md）
    c, k, dphi, ns, if_c = WN.window_params(a.if_c, a.w, grid=not a.no_grid)
    w = a.w
    dw = w / NFFT_W
    tf_w = NFFT_W / w * 1e-6
    nacc_w = WN.nacc_for(w, a.tau0)
    nacc_f = max(1, int(round(a.tau0 / S.T_FRAME)))
    nb = np.where(np.arange(NFFT_W) < NFFT_W // 2, np.arange(NFFT_W), np.arange(NFFT_W) - NFFT_W) * dw
    cen = np.abs(nb) <= 0.45 * w
    # 全帯域の同じ範囲（f の側 c ± 0.45W）の ch
    kf_lo, kf_hi = int(np.ceil((c - 0.45 * w) / DF_FULL)), int(np.floor((c + 0.45 * w) / DF_FULL))
    log(f"窓: IF {if_c:.6f} MHz ± {w / 2} / WK {k} / WNS {ns}・τ0 {a.tau0} s（窓 {nacc_w}・全帯域 {nacc_f} フレーム）・{a.duration:.0f} s")
    log(f"全帯域の同じ範囲: ch {kf_lo}〜{kf_hi}（{kf_hi - kf_lo + 1} ch、IF {4096 - kf_hi * DF_FULL:.1f}〜{4096 - kf_lo * DF_FULL:.1f} MHz）")

    S.setup_clocks(a.clkin, a.ref)
    ol = Overlay(a.bitfile or S.BITFILE)
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    S.check_tiles(ol.rfdc, 2)
    if a.settle > 0:
        time.sleep(a.settle)
    wn = WN.open_win(ol, a.allow_nopreset)
    if a.sg or os.environ.get("RFSOC_SG"):
        import sg as SGMOD
        sg = SGMOD.SG(a.sg, log=log)
        atexit.register(sg.close)
        sg.set_output(False)
    else:
        log("注意: SG の宛先が無い。**SG の出力が切れていること**を確かめてから")
    wn.set_window(k, dphi, ns)
    spf = S.Spec(ol.spec_core_1.mmio, idx=1, label="ADC_B")

    def one(shw, shf):
        sf = spf.run(nacc_f, 1, shf); s = wn.run(nacc_w, 1, shw)
        if wn.wait_dump(s, a.tau0 * 3 + 2) is None or spf.wait_dump(sf, a.tau0 * 3 + 2) is None:
            raise RuntimeError("ダンプが閉じない")
        m, pw, _ = wn.read_dump(); mf, pf, _ = spf.read_dump()
        return pw.astype(float) / m["n"], pf.astype(float) / mf["n"]

    pw, pf = one(11, 8)
    fl_w = float(np.median(pw[cen])); fl_f = float(np.median(pf[kf_lo:kf_hi + 1]))

    def choose(fl, s0):
        true = max(fl - 0.67, 0.02)
        return int(np.clip(s0 - round(np.log(a.floor / true) / np.log(4.0)), 0, 15))
    sh_w, sh_f = choose(fl_w, 11), choose(fl_f, 8)
    log(f"SHIFT: 窓 {sh_w}（SHIFT 11 の床 {fl_w:.2f}）/ 全帯域 {sh_f}（SHIFT 8 の床 {fl_f:.2f}）→ 床 {a.floor:.0f} LSB² の見当")

    # 連続で回す（N_DUMP = 0）。両方をほぼ同時に RUN
    seq_f = spf.run(nacc_f, 0, sh_f)
    seq_w = wn.run(nacc_w, 0, sh_w)
    t0 = time.time()
    ts, ya, yb, ysa, ysb, yfa, yfb = [], [], [], [], [], [], []
    fmask = fa_idx = fb_idx = None
    probe_w = []
    mask = None
    lost_w = lost_f = 0
    minute_w = np.zeros(NFFT_W); minute_f = np.zeros(kf_hi - kf_lo + 1); n_min = 0
    spectra_w, spectra_f = [], []
    last_save = t0
    lost_at = []                                   # 窓のダンプを飛ばした時刻 [s]（原因の切り分け用）
    saver = None                                   # 途中の npz は別のスレッドで書く（1 回目の 1 時間で、書く時刻に合わせてダンプを飛ばした）
    half = None
    while time.time() - t0 < a.duration:
        s = wn.wait_dump(seq_w, a.tau0 * 5 + 2)
        if s is None:
            log("ERROR: 窓のダンプが閉じない"); break
        dl = max(0, (s - seq_w) % (1 << 32) - 1); lost_w += dl; seq_w = s
        if dl:
            lost_at.append(time.time() - t0)
        m, pw_raw, _ = wn.read_dump()
        sfv = spf.wait_dump(seq_f, a.tau0 * 5 + 2)
        if sfv is None:
            log("ERROR: 全帯域のダンプが閉じない"); break
        lost_f += max(0, (sfv - seq_f) % (1 << 32) - 1); seq_f = sfv
        mf, pf_raw, _ = spf.read_dump()
        pw = pw_raw.astype(float) / m["n"]
        pf = pf_raw.astype(float)[kf_lo:kf_hi + 1] / mf["n"]
        if mask is None:
            probe_w.append(pw)
            if len(probe_w) >= a.probe:
                d = np.array(probe_w)
                r = nacc_w * d.var(axis=0, ddof=1) / d.mean(axis=0) ** 2
                sim = np.random.default_rng(1).gamma(nacc_w, 1.0 / nacc_w, size=(len(probe_w), 4000))
                thr = float(np.quantile(nacc_w * sim.var(axis=0, ddof=1) / sim.mean(axis=0) ** 2, 0.999))
                mask = cen & (r <= thr) & (d.mean(axis=0) < 3 * np.median(d.mean(axis=0)[cen]))
                # 全帯域の ch: 窓の中央 90 % の ch が入る全帯域の ch のうち、外した ch を含まないもの
                kfw = np.round((c + nb) / DF_FULL).astype(int) - kf_lo
                okf = np.zeros(kf_hi - kf_lo + 1, bool); badf = np.zeros_like(okf)
                inr = (kfw >= 0) & (kfw < len(okf))
                okf[kfw[cen & mask & inr]] = True; badf[kfw[cen & ~mask & inr]] = True
                fmask = okf & ~badf
                fch = np.arange(len(fmask))
                fa_idx = fch[fmask & ((kf_lo + fch) * DF_FULL < c)]; fb_idx = fch[fmask & ((kf_lo + fch) * DF_FULL >= c)]
                log(f"全帯域の使える ch: {fmask.sum()} / {len(fmask)}（小帯域 A {len(fa_idx)} / B {len(fb_idx)}）")
                # 窓の小帯域 A / B = 全帯域の小帯域 A / B の ch に入る窓の ch（(d) と (e) が同じ周波数を見る）
                kfc = np.clip(kfw, 0, len(fmask) - 1)
                wsel = mask & inr & fmask[kfc]
                half = (np.where(wsel & np.isin(kfc, fa_idx))[0], np.where(wsel & np.isin(kfc, fb_idx))[0])
                if min(len(fa_idx), len(fb_idx)) < 5 or min(len(half[0]), len(half[1])) < 20:
                    log("ERROR: 小帯域の ch が少なすぎる（外した ch が多い。--probe・RFI を確かめる）"); log("RESULT NG"); return 1
                log(f"使える ch: {mask.sum()} / {cen.sum()}（時間で変わる線として外した {int((cen & (r > thr)).sum())}）・"
                    f"小帯域 A {len(half[0])} ch / B {len(half[1])} ch")
            continue
        ts.append(time.time() - t0)
        ya.append(pw[mask].sum()); yb.append(pf[fmask].sum())
        yfa.append(pf[fa_idx].sum()); yfb.append(pf[fb_idx].sum())
        ysa.append(pw[half[0]].sum()); ysb.append(pw[half[1]].sum())
        minute_w += pw; minute_f += pf; n_min += 1
        if n_min * a.tau0 >= 60.0:
            spectra_w.append(minute_w / n_min); spectra_f.append(minute_f / n_min)
            minute_w[:] = 0; minute_f[:] = 0; n_min = 0
            yy = np.array(ysa) / np.array(ysb)
            log(f"  {ts[-1]:7.0f} s: ダンプ {len(ts)}・飛ばした 窓 {lost_w} / 全帯域 {lost_f}・小帯域の比 {yy[-1] / yy.mean():.5f}・"
                f"窓 / 全帯域 {(ya[-1] / yb[-1]) / (np.mean(ya) / np.mean(yb)):.5f}")
        if a.out and time.time() - last_save > 600 and (saver is None or not saver.is_alive()):
            snap = dict(t=np.array(ts), win=np.array(ya), full=np.array(yb), sa=np.array(ysa), sb=np.array(ysb),
                        fa=np.array(yfa), fb=np.array(yfb), fmask=fmask, mask=mask, spectra_win=np.array(spectra_w),
                        spectra_full=np.array(spectra_f), tau0=a.tau0, c=c, w=w, lost_at=np.array(lost_at))
            saver = threading.Thread(target=np.savez, args=(a.out + ".allan.npz",), kwargs=snap, daemon=True)
            saver.start()
            last_save = time.time()
    wn.wr(WN.R_CTRL, WN.CTRL_STOP); spf.stop()
    if saver is not None:
        saver.join()
    if lost_at:
        log("窓のダンプを飛ばした時刻 [s]: " + ", ".join(f"{v:.0f}" for v in lost_at))
    flags = wn.rd(WN.R_FLAGS)
    t = np.array(ts); A = np.array(ya); B = np.array(yb); SA = np.array(ysa); SB = np.array(ysb); FA = np.array(yfa); FB = np.array(yfb)
    ok = len(t) > 20
    if not ok:
        log("ERROR: 時系列が短すぎる"); log("RESULT NG"); return 1
    series = {"(a) 窓": A / A.mean(), "(b) 全帯域": B / B.mean(), "(c) 窓 / 全帯域": (A / B) / (A / B).mean(),
              "(d) 小帯域の比": (SA / SB) / (SA / SB).mean(), "(e) 全帯域の小帯域の比": (FA / FB) / (FA / FB).mean()}
    series["(f) (d) / (e)"] = series["(d) 小帯域の比"] / series["(e) 全帯域の小帯域の比"]
    nmax = len(t) // 4
    nlist = np.unique(np.round(np.logspace(0, np.log10(max(nmax, 1)), 30)).astype(int))
    taus = nlist * a.tau0
    av = {kname: allan(y, nlist) for kname, y in series.items()}
    Nf = taus / tf_w
    theory = {"(a) 窓": 1 / (mask.sum() * Nf), "(b) 全帯域": 1 / (fmask.sum() * taus / S.T_FRAME),
              "(e) 全帯域の小帯域の比": 1 / (len(fa_idx) * taus / S.T_FRAME) + 1 / (len(fb_idx) * taus / S.T_FRAME),
              "(d) 小帯域の比": 1 / (len(half[0]) * Nf) + 1 / (len(half[1]) * Nf)}
    log(f"ダンプ {len(t)}（{t[-1]:.0f} s）・飛ばした 窓 {lost_w} / 全帯域 {lost_f}・FLAGS {flags:#x}")
    log("τ [s]      " + "  ".join(f"{kname:>14s}" for kname in series) + "   予言 (d)")
    for i in range(0, len(taus), max(1, len(taus) // 12)):
        log(f"{taus[i]:8.1f}  " + "  ".join(f"{np.sqrt(av[kname][i]):14.3e}" for kname in series) + f"   {np.sqrt(theory['(d) 小帯域の比'][i]):.3e}")
    rd = av["(d) 小帯域の比"] / theory["(d) 小帯域の比"]
    theory["(f) (d) / (e)"] = theory["(d) 小帯域の比"] + theory["(e) 全帯域の小帯域の比"]   # 雑音が独立とした上限（同じサンプルなので実際は小さい）
    rf = av["(f) (d) / (e)"] / theory["(f) (d) / (e)"]
    sel = taus <= a.judge_max
    over = np.where(rd > a.tol)[0]
    t_allan = taus[over[0]] if len(over) else None
    ok = bool(np.all(np.isfinite(rf[sel])) and np.all(rf[sel] <= a.tol)) and (flags & 0x3EF) == 0
    log(("  OK  " if ok else "  NG  ") + f"W-9: (f) 窓の分光計そのもの（(d) / (e)）のアラン分散 / ラジオメータの予言（(d) + (e)、雑音が独立とした上限）≦ {a.tol}（τ ≦ {a.judge_max:.0f} s）: "
        f"最大 {np.nanmax(rf[sel]):.2f}")
    log("  --  " + f"入力を含めた (d) 小帯域の比のアラン分散 / ラジオメータの予言（τ ≦ {a.judge_max:.0f} s）: "
        f"最大 {np.nanmax(rd[sel]):.2f}・アラン時間 {'> %.0f s（測った範囲で %g 倍を超えない）' % (taus[-1], a.tol) if t_allan is None else '%.1f s' % t_allan}"
        f"・FLAGS {flags:#x}・(e) 全帯域の小帯域の比 / その予言 最大 {np.nanmax((av['(e) 全帯域の小帯域の比'] / theory['(e) 全帯域の小帯域の比'])[sel]):.2f}")
    if a.out:
        np.savez(a.out + ".allan.npz", t=t, win=A, full=B, sa=SA, sb=SB, fa=FA, fb=FB, fmask=fmask, mask=mask, spectra_win=np.array(spectra_w),
                 spectra_full=np.array(spectra_f), tau0=a.tau0, c=c, w=w, taus=taus, lost_at=np.array(lost_at),
                 **{f"av_{i}": av[kname] for i, kname in enumerate(series)}, theory_d=theory["(d) 小帯域の比"],
                 theory_a=theory["(a) 窓"], theory_b=theory["(b) 全帯域"], theory_e=theory["(e) 全帯域の小帯域の比"], theory_f=theory["(f) (d) / (e)"], shift_w=sh_w, shift_f=sh_f, lost_w=lost_w, lost_f=lost_f)
        log(f"書いた: {a.out}.allan.npz")
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(1, 2, figsize=(12, 4.8))
            names = {"(a) 窓": "(a) window", "(b) 全帯域": "(b) full band (same range)", "(c) 窓 / 全帯域": "(c) window / full",
                     "(d) 小帯域の比": "(d) sub-band ratio (spectroscopic)", "(e) 全帯域の小帯域の比": "(e) same, full band",
                     "(f) (d) / (e)": "(f) (d) / (e)"}
            for i, kname in enumerate(series):
                ax[0].loglog(taus, np.sqrt(av[kname]), "o-", ms=3, color=f"C{i}", label=names[kname])
                if kname in theory:
                    ax[0].loglog(taus, np.sqrt(theory[kname]), ":", color=f"C{i}", lw=1)
            ax[0].set_xlabel("tau [s]"); ax[0].set_ylabel("Allan deviation (relative)"); ax[0].grid(alpha=.3, which="both")
            ax[0].legend(fontsize=8); ax[0].set_title("dotted: radiometer equation")
            for i, kname in enumerate(series):
                ax[1].plot(t / 60, series[kname] - 1 + 0.0 * i, lw=.5, color=f"C{i}", label=names[kname])
            ax[1].set_xlabel("time [min]"); ax[1].set_ylabel("relative - 1"); ax[1].grid(alpha=.3); ax[1].legend(fontsize=8)
            fig.suptitle(f"window IF {if_c:.1f} MHz, W = {w:g} MHz, tau0 {a.tau0} s, {t[-1] / 60:.0f} min")
            fig.tight_layout(); fig.savefig(a.out + ".allan.png", dpi=120)
            log(f"書いた: {a.out}.allan.png")
        except ImportError:
            pass
    log("RESULT " + ("OK" if ok else "NG"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
