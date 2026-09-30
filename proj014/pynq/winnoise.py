#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj014 — 判定 W-5: 雑音を入れた窓の積分の揺れがラジオメータの式どおりか。

  雑音（SG は切る）を窓に入れ、N_ACC = N のダンプを M 回とり、ch ごとに 分散 / 平均² を出す。
  窓の FFT は窓関数を掛けない 4096 点で、フレームは途切れずに隣り合う（重ならない）ので、1 フレームの電力は自由度 2 の χ²
  （分散 / 平均² = 1）。N フレーム積むと 1 / N。**ラジオメータの式 ΔT / T = 1 / √(B τ)** は、ch 幅 B = W / 4096・τ = N × 4096 / W で B τ = N。
  判定: 中央 90 % の ch（線を除く）で平均した R = N · 分散 / 平均² が、理想のラジオメータの R₀ に近い（R / R₀ の許容 --tol、既定 5 %）。
  R₀ は 1 だが、M 回の標本の平均で割るので小さな偏りがある（N = 1・M = 40 で約 +5 %）。**同じ N・M の χ²（ガンマ分布）を乱数で作って R₀ を出し、それと比べる**

  - ch ごとの平均は線（k·fs/8 など）も含むが、線は揺れが小さく R を下げるので、平均が中央値の 3 倍を超える ch は除く
  - **量子化で雑音が消えないように SHIFT を自分で選ぶ**: SHIFT 11 で床を測り、量子化（約 0.67 LSB²）を除いた真の雑音から、
    床が --floor（既定 2000 LSB² / フレーム）前後になる SHIFT を出す（--shift で固定もできる）。雑音が 1 LSB 程度だと量子化の分だけ R が 1 からずれる
  - N が大きいと利得の揺らぎ（増幅器・温度）が出て R が 1 を超えうる。そこは判定に入れず、目安として出す（--judge-max の τ まで判定）
  - **共通の揺らぎを分ける**（実機の帯域の端で τ 30〜70 ms から R/R₀ ≒ 1.08 が出たのを受けて）: ダンプごとに窓の中央 90 % の ch の平均で割った
    g_i（帯域の電力の相対値）を出し、その揺れ g_rms（ラジオメータの分 1/√(N·ch) を引いたもの）を「共通の利得の揺らぎ」として出す。
    **判定は g_i で割った後の R_cm / R₀**（分光計の ch ごとの性質。帯域全体が一緒に揺れるのはアナログか ADC の較正の揺らぎ）。割る前の R / R₀ も出す
    ch ごとの R（割る前・後）を npz に残す（どの ch が揺れているかを IF に対して描ける）
  - 各ダンプは RUN を打ち直して独立にとる（N = 1 でもダンプの読み出しに追いつく）

  python3 winnoise.py --if 3000 --w 256 --clkin 0 --ref 10
  python3 winnoise.py --if 3010 --w 8 --clkin 0 --ref 10
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


def log(*a):
    print(*a, flush=True)


def stats(dumps, nb, w):
    """dumps: (M, 4096) の 1 フレームあたりの電力。→ 中央 90 % の線を除いた ch で、分散 / 平均² の平均と使った ch の数。"""
    mu = dumps.mean(axis=0)
    var = dumps.var(axis=0, ddof=1)
    use = np.abs(nb) <= 0.45 * w
    med = np.median(mu[use])
    use &= (mu < 3 * med) & (mu > 0)
    r = var[use] / mu[use] ** 2
    return float(np.mean(r)), int(use.sum()), float(med), r


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--if", dest="if_c", type=float, default=3000.0)
    p.add_argument("--w", type=float, default=256.0)
    p.add_argument("--no-grid", action="store_true")
    p.add_argument("--bitfile", default=None)
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--sg", default=None, help="SG の HOST[:PORT]（環境変数 RFSOC_SG でも可）。あれば出力を切って確かめる")
    p.add_argument("--shift", type=int, default=None, help="窓の SHIFT（既定: 床が --floor 前後になるよう選ぶ）")
    p.add_argument("--floor", type=float, default=2000.0, help="選ぶ SHIFT で狙う雑音の床 [LSB² / フレーム]")
    p.add_argument("--n", default="1,4,16,64,256,1024,4096,16384", help="N_ACC の並び")
    p.add_argument("--m", type=int, default=40, help="N ごとのダンプの数（上限）")
    p.add_argument("--m-min", type=int, default=12)
    p.add_argument("--time", type=float, default=20.0, help="N ごとの時間の上限 [s]（M を減らす）")
    p.add_argument("--judge-max", type=float, default=0.1, help="判定に入れる τ（1 ダンプ）の上限 [s]")
    p.add_argument("--tau-max", type=float, default=1.0, help="測る τ の上限 [s]（これより長い N は飛ばす）")
    p.add_argument("--tol", type=float, default=0.05, help="R の 1 からのずれの許容")
    p.add_argument("--allow-nopreset", action="store_true")
    p.add_argument("--out", default=None, help="PREFIX.noise.npz に")
    a = p.parse_args()

    import window as WN
    import spectrometer as S
    from pynq import Overlay
    import xrfdc                                   # Overlay() より前に import する（VERSIONS.md）
    c, k, dphi, ns, if_c = WN.window_params(a.if_c, a.w, grid=not a.no_grid)
    w = a.w
    tf = NFFT_W / w * 1e-6                          # 1 フレーム [s]
    log(f"窓: IF {if_c:.6f} MHz ± {w / 2} / WK {k} / WDPHI {dphi:#010x} / WNS {ns} / 1 フレーム {tf * 1e6:.0f} µs")
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
        log("注意: SG の宛先が無い。**SG の出力が切れていること**を確かめてから（雑音だけを入れる）")
    wn.set_window(k, dphi, ns)
    nb = np.where(np.arange(NFFT_W) < NFFT_W // 2, np.arange(NFFT_W), np.arange(NFFT_W) - NFFT_W) * (w / NFFT_W)

    def dump(n, shift):
        s = wn.run(n, 1, shift)
        if wn.wait_dump(s, n * tf * 3 + 2) is None:
            raise RuntimeError("ダンプが閉じない")
        m, spec, _ = wn.read_dump()
        return spec.astype(float) / m["n"], m["sat"]

    if a.shift is None:
        p11, _ = dump(max(1, int(round(0.05 / tf))), 11)
        fl = float(np.median(p11[np.abs(nb) <= 0.45 * w]))
        true = max(fl - 0.67, 0.02)
        shift = int(np.clip(11 - round(np.log(a.floor / true) / np.log(4.0)), 0, 15))
        log(f"SHIFT 11 の床 {fl:.2f} LSB²（量子化を除いて {true:.2f}）→ SHIFT {shift}（床の見当 {true * 4 ** (11 - shift):.0f} LSB²）")
    else:
        shift = a.shift
    ok = True

    def judge(cond, msg):
        nonlocal ok
        log(("  OK  " if cond else "  NG  ") + msg)
        ok &= bool(cond)

    rows = []
    nsat = 0
    t0 = time.time()
    rng = np.random.default_rng(1)
    per_ch = {}
    for n in [int(x) for x in a.n.split(",") if x]:
        tau = n * tf
        if tau > a.tau_max:
            log(f"  --  N {n}（τ {tau:.2f} s）は --tau-max {a.tau_max} s を超えるので飛ばす")
            continue
        m = int(min(a.m, max(a.m_min, a.time / max(tau, 1e-6))))
        d = np.empty((m, NFFT_W))
        for i in range(m):
            d[i], sat = dump(n, shift)
            nsat += bool(sat)
        R1, nuse, med, r = stats(d, nb, w)
        R = n * R1
        use = (np.abs(nb) <= 0.45 * w)
        mu = d.mean(axis=0); use &= (mu < 3 * np.median(mu[use])) & (mu > 0)
        g = (d[:, use] / mu[use]).mean(axis=1)                   # ダンプごとの帯域の電力（相対）
        g_rms = float(np.sqrt(max(np.var(g, ddof=1) - 1.0 / (n * use.sum()), 0.0)))
        R1c, _, _, rc = stats(d / g[:, None], nb, w)
        Rc = n * R1c
        err = n * np.std(r) / np.sqrt(nuse)               # ch の平均の揺れ（ch どうしは独立とみなす）
        sim = rng.gamma(shape=n, scale=1.0 / n, size=(m, 4000))   # 理想のラジオメータ: 1 ダンプ = 自由度 2N の χ²
        R0 = n * float(np.mean(sim.var(axis=0, ddof=1) / sim.mean(axis=0) ** 2))
        inj = tau <= a.judge_max
        rows.append((n, tau, m, R, err, nuse, med, R0, Rc, g_rms))
        def full_r(x):                                   # 4096 ch ぶん（使わない ch は NaN）
            out = np.full(NFFT_W, np.nan)
            out[use] = n * x[:, use].var(axis=0, ddof=1) / x[:, use].mean(axis=0) ** 2
            return out
        per_ch[n] = (full_r(d), full_r(d / g[:, None]), g)
        msg = (f"N {n:6d}（τ {tau * 1e3:9.3f} ms）× M {m:3d}: 共通の揺らぎを除いて R_cm/R₀ {Rc / R0:.4f}"
               f"・除く前 R/R₀ {R / R0:.4f}（R₀ {R0:.4f}、±{err / R0:.4f}）・共通の利得の揺らぎ {g_rms * 100:.3f} %（ch {nuse}、床 {med:.0f} LSB²）")
        if inj:
            judge(abs(Rc / R0 - 1) <= a.tol, "W-5: " + msg + f"（許容 ±{a.tol}）")
        else:
            log("  --  " + msg + f"（τ > {a.judge_max} s は判定に入れない。R > 1 は利得の揺らぎの目安）")
    judge(nsat == 0, f"W-5: 飽和したダンプ {nsat}")
    flags = wn.rd(WN.R_FLAGS)
    judge((flags & 0x3EF) == 0, f"W-0: FLAGS {flags:#x}（{WN.flag_text(flags)}）")
    log(f"かかった時間 {time.time() - t0:.0f} s")
    if a.out:
        extra = {}
        for n_, (rr, rrc, gg) in per_ch.items():
            extra[f"r_N{n_}"] = rr; extra[f"rcm_N{n_}"] = rrc; extra[f"g_N{n_}"] = gg
        # r_N* / rcm_N* は ch ごとの R（中央 90 % で線を除いた ch だけ値、他は NaN）。横軸は if_win
        np.savez(a.out + ".noise.npz", rows=np.array(rows), c=c, w=w, k=k, dphi=dphi, ns=ns, shift=shift,
                 if_win=WN.ch_if(c, w),
                 rows_cols="N, tau, M, R, err, nch, floor, R0, R_cm, g_rms", **extra)
        log(f"書いた: {a.out}.noise.npz")
    log("RESULT " + ("OK" if ok else "NG"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
