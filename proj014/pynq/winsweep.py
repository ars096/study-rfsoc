#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj014 — 窓の掃引（判定 W-2・W-3）。SG の周波数を動かしながら、窓（win_core_0）と全帯域（spec_core_1）を同時に測る。

  W-2  窓の中の利得の形: 窓の中（|ν| < 0.5W）に CW を置き、ch の利得を ν ごとに測って模型（src/win_coef.vh の係数）と比べる
       W-2a 中央 90 %（|ν| ≦ 0.45W）の平らさ（p-p）/ W-2b 中央 90 % の模型との差 / W-2c 両端 5 % の落ち方の模型との差
  W-3  窓の外からの折り返し: 窓の外に CW を置き、窓の出力のレート W で折り返る先（中央 90 % の中）に出る量を測る（要求 −60 dB）

測り方の約束:
  - **SG を切った基準（P_off）を最初と最後に測り、CW を入れたスペクトルから ch ごとに引く**。雑音の平均と、SG に依らない線（k·fs/8 など）が消える
  - アナログの特性（増幅器・BPF・分配器の傾き）は、**同じ ADC の全帯域（spec_core_1）で測った CW の電力で割って消す**（W-6 と同じ）。
    全帯域の ch の端数による目減りは sinc²(δ_f) で戻す（δ_f は SG の周波数から決まる。窓関数を掛けない 8192 点 FFT）
    利得 G = (P_win − P_win,off) / ((P_full − P_full,off) / sinc²(δ_f)) / (64·4^(SHIFT_full − SHIFT))
  - CW は窓の ch の中心に置く（窓の側の目減りなし）。W ≧ 64 MHz では全帯域の ch の中心（0.5 MHz 格子）にも揃える
  - W-3 の検出限界: 引き算の後の ch の揺れ σ（中央 90 % の ch の MAD から）の 5 倍。限界が要求に届かないときは「判定できない」（NG）。
    **窓に出た量と同じ IF に全帯域でも線があれば ADC 側の線**（窓の折り返しではない）として判定から除き、そう書く
  - W-3 の検出限界は CW と ch あたりの雑音の比で決まる（−20 dBm・0.5 s で −55 dB 前後の見当で、−60 dB に届かない）。
    **W-3 は SG を上げる（--w3-dbm 0）**。CW は窓の外なので窓の SHIFT はそのまま（雑音が量子化で消えないように）、
    全帯域だけ飽和しないよう --w3-shift-full を上げる。窓の雑音の床が 4 LSB² を切ると量子化で折り返しが見えなくなるので「判定できない」にする
  - ボードと SG は同じ 10 MHz に載せる（--clkin 0 --ref 10。載せないと ch の中心に置けない）

  python3 winsweep.py --if 3000 --w 256 --clkin 0 --ref 10 --w3-dbm 0 --w3-shift-full 12    W-2 と W-3
  python3 winsweep.py --if 3010 --w 8 --clkin 0 --ref 10 --only w2        W-2 だけ
  python3 winsweep.py --if 3000 --w 256 --dry-run                         ボードに触らず、置く CW と模型の予言だけを出す
"""
import argparse
import atexit
import os
import re
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FS = 4096.0
S_CH = 128.0
R0 = 512.0
NFFT_W = 4096
DF_FULL = 0.5          # 全帯域の ch 幅 [MHz]


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- 模型（係数から）
def load_coef(path):
    """src/win_coef.vh（make coef の生成物）から PFB・light・final の係数（実数）を読む。"""
    txt = open(path, encoding="utf-8").read()
    out = {}
    for name, key in (("PFB", "pfb"), ("HBL", "light"), ("HBF", "final")):
        sh = int(re.search(rf"localparam integer {name}_SH\s*=\s*(\d+);", txt).group(1))
        body = re.search(rf"localparam \[[^\]]+\] {name}_H\s*=\s*\{{([^}}]*)\}};", txt).group(1)
        vals = [int(v.replace("18'sd", "")) for v in re.findall(r"-?18'sd\d+", body)]
        out[key] = np.array(vals, dtype=float) / 2.0 ** sh
    return out


def resp(h, f, rate):
    """対称な係数の零位相の応答（model/win_model.py の resp と同じ）。"""
    n = np.arange(len(h)) - (len(h) - 1) / 2.0
    f = np.atleast_1d(np.asarray(f, dtype=float))
    return np.cos(2 * np.pi * np.outer(f / rate, n)) @ h


def wrap(f, rate):
    return (f + rate / 2.0) % rate - rate / 2.0


def chain(coef, f, c, w):
    """入力の周波数 f（f の側、MHz、両側）→ 窓の出力の ν と振幅の利得（model/win_model.py の chain_gain と同じ流れ）。"""
    k = int(round(c / S_CH)); d = c - S_CH * k
    ns = int(round(np.log2(R0 / w)))
    f = np.atleast_1d(np.asarray(f, dtype=float))
    f1 = f - k * S_CH
    g = np.abs(resp(coef["pfb"], f1, FS))
    f2 = wrap(wrap(f1, R0) - d, R0)
    rate = R0
    for j in range(ns):
        g = g * np.abs(resp(coef["final" if j == ns - 1 else "light"], f2, rate))
        rate /= 2
        f2 = wrap(f2, rate)
    return f2, g


def model_db(coef, f, c, w):
    """CW 1 本（実数なので ±f の両方）の、窓の出力での (ν, 電力の利得 dB)。+f の側と −f の側。"""
    nu_p, g_p = chain(coef, f, c, w)
    nu_m, g_m = chain(coef, -np.asarray(f), c, w)
    _, g0 = chain(coef, [c], c, w)
    return nu_p, 20 * np.log10(np.maximum(g_p / g0[0], 1e-12)), nu_m, 20 * np.log10(np.maximum(g_m / g0[0], 1e-12))


# ---------------------------------------------------------------- CW の置き方
def plan_w2(c, w, n_mid, edge_step, f_grid):
    dw = w / NFFT_W
    nus = list(np.linspace(-0.45, 0.45, n_mid) * w)
    e = np.arange(0.45, 0.5, edge_step) * w
    nus += list(e) + list(-e)
    out = set()
    for nu in nus:
        f = c + nu
        if f_grid:
            f = round(f / DF_FULL) * DF_FULL
        else:
            f = c + round(nu / dw) * dw
        nu2 = f - c
        if abs(nu2) < 0.5 * w - 1e-9:
            out.add(round(nu2 / dw))
    return [b * dw for b in sorted(out)]


def plan_w3(c, w, ms, max_off, pfb_js):
    """窓の外の ν_out = a + s·m·W（折り返し先 a は中央 90 % の中）と、PFB の折り返し ν_out = a + s·512·j。"""
    dw = w / NFFT_W
    alist = [round(x * w / dw) * dw for x in (-0.35, -0.1, 0.15, 0.4)]
    offs = sorted(set([m * w for m in ms if m * w <= max_off] + [512.0 * j for j in pfb_js]))
    out = []
    for off in offs:
        for s in (+1, -1):
            for a in alist:
                nu = a + s * off
                f = c + nu
                if 5.0 <= f <= 2043.0 and abs(nu) >= 0.5 * w:
                    out.append((nu, a))
    return out


# ---------------------------------------------------------------- 判定の足回り
def robust_sigma(x):
    med = np.median(x)
    return 1.4826 * np.median(np.abs(x - med))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--if", dest="if_c", type=float, default=3000.0, help="窓の IF の中心 [MHz]")
    p.add_argument("--w", type=float, default=256.0, help="窓の幅 [MHz]")
    p.add_argument("--no-grid", action="store_true")
    p.add_argument("--only", choices=("w2", "w3"), default=None)
    p.add_argument("--bitfile", default=None)
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--sg", default=None, help="SG の HOST[:PORT]（環境変数 RFSOC_SG でも可）")
    p.add_argument("--sg-dbm", type=float, default=-20.0)
    p.add_argument("--sg-settle", type=float, default=0.05, help="SG の周波数を変えてから測り始めるまで [s]")
    p.add_argument("--shift", type=int, default=11)
    p.add_argument("--shift-full", type=int, default=8)
    p.add_argument("--tint", type=float, default=0.05, help="W-2 の 1 点の積分 [s]")
    p.add_argument("--w3-tint", type=float, default=0.5, help="W-3 の 1 点の積分と、SG を切った基準の積分 [s]")
    p.add_argument("--w3-dbm", type=float, default=None, help="W-3 の SG のレベル [dBm]（既定 --sg-dbm）")
    p.add_argument("--w3-shift-full", type=int, default=None, help="W-3 の全帯域の SHIFT（既定 --shift-full）")
    p.add_argument("--w3-shift", type=int, default=None, help="W-3 の窓の SHIFT（既定 --shift）。狭い窓は雑音が小さいので下げる")
    p.add_argument("--w2-n", type=int, default=37, help="W-2 の中央 90 % の点の数")
    p.add_argument("--w2-edge", type=float, default=0.005, help="W-2 の両端 5 % の刻み（W に対する比）")
    p.add_argument("--w3-m", default="1,2,3,4,8,16,32,64", help="W-3 の窓の外の離れ（W の倍数）")
    p.add_argument("--w3-max", type=float, default=640.0, help="W-3 の離れの上限 [MHz]")
    p.add_argument("--w3-pfb", default="1,2", help="W-3 の PFB の折り返し（512 MHz の倍数）")
    p.add_argument("--tol-pp", type=float, default=0.15, help="W-2a 中央 90 % の p-p [dB]")
    p.add_argument("--tol-mid", type=float, default=0.05, help="W-2b 中央 90 % の模型との差 [dB]")
    p.add_argument("--tol-edge", type=float, default=0.3, help="W-2c 両端 5 % の模型との差 [dB]")
    p.add_argument("--alias-req", type=float, default=60.0, help="W-3 の要求 [dB]")
    p.add_argument("--coef", default=None, help="win_coef.vh（既定: このスクリプトの隣か ../src/）")
    p.add_argument("--allow-nopreset", action="store_true")
    p.add_argument("--out", default=None, help="結果を PREFIX.sweep.npz（と matplotlib があれば PREFIX.sweep.png）に")
    p.add_argument("--dry-run", action="store_true", help="ボードと SG に触らず、置く CW と模型の予言だけ")
    a = p.parse_args()

    import window as WN
    c, k, dphi, ns, if_c = WN.window_params(a.if_c, a.w, grid=not a.no_grid)
    w = a.w
    dw = w / NFFT_W
    log(f"窓: IF {if_c:.6f} MHz ± {w / 2}（c = {c:.6f}）/ WK {k} / WDPHI {dphi:#010x} / WNS {ns}")

    coef_path = a.coef or next((q for q in (os.path.join(HERE, "win_coef.vh"), os.path.join(HERE, "..", "src", "win_coef.vh"))
                                if os.path.exists(q)), None)
    if coef_path is None:
        log("ERROR: win_coef.vh が無い（--coef で与えるか、src/win_coef.vh をこのスクリプトの隣に置く）"); sys.exit(1)
    coef = load_coef(coef_path)
    log(f"模型の係数: {coef_path}（PFB {len(coef['pfb'])}・light {len(coef['light'])}・final {len(coef['final'])} タップ）")

    do2 = a.only in (None, "w2")
    do3 = a.only in (None, "w3")
    f_grid = w >= 64
    nus2 = plan_w2(c, w, a.w2_n, a.w2_edge, f_grid) if do2 else []
    w3 = plan_w3(c, w, [int(x) for x in a.w3_m.split(",") if x], a.w3_max,
                 [int(x) for x in a.w3_pfb.split(",") if x]) if do3 else []
    if do2:
        _, m2, _, _ = model_db(coef, c + np.array(nus2), c, w)
        mid = np.abs(nus2) <= 0.45 * w
        log(f"W-2: CW {len(nus2)} 点（{'全帯域の 0.5 MHz 格子にも揃える' if f_grid else '窓の ch の中心・全帯域は sinc² で戻す'}）。"
            f"模型の中央 90 % の p-p {np.ptp(m2[mid]):.3f} dB / 0.5W の手前 {m2[np.argmax(np.abs(nus2))]:+.2f} dB")
    if do3:
        f3 = c + np.array([x[0] for x in w3])
        nup, gp, num, gm = model_db(coef, f3, c, w)
        log(f"W-3: CW {len(w3)} 点。模型の折り返しの最大 {gp.max():+.1f} dB（+f の側）/ {gm.max():+.1f} dB（−f の側）")
    if a.dry_run:
        if do2:
            for nu, g in zip(nus2, m2):
                log(f"  W-2 ν {nu:+10.5f} MHz（{nu / w:+.4f} W）IF {4096 - c - nu:.6f} → 模型 {g:+.3f} dB")
        if do3:
            for (nu, al), g, nq in zip(w3, gp, nup):
                log(f"  W-3 ν {nu:+10.4f} MHz → 折り返し先 {nq:+.5f}（予定 {al:+.5f}）IF {4096 - c - nu:.4f} → 模型 {g:+.1f} dB")
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
    sg.set_dbm(a.sg_dbm)
    sg.set_output(False)
    wn.set_window(k, dphi, ns)
    spf = S.Spec(ol.spec_core_1.mmio, idx=1, label="ADC_B")
    shf3 = a.w3_shift_full if a.w3_shift_full is not None else a.shift_full
    dbm3 = a.w3_dbm if a.w3_dbm is not None else a.sg_dbm
    pred = 64.0 * 4.0 ** (a.shift_full - a.shift)
    sh3 = a.w3_shift if a.w3_shift is not None else a.shift
    pred3 = 64.0 * 4.0 ** (shf3 - sh3)
    quiet = lambda *x: None

    nsat = [0]

    def measure(tint, shf, shw=None):
        nw = WN.nacc_for(w, tint)
        nf = max(1, int(round(tint / S.T_FRAME)))
        sf = spf.run(nf, 1, shf)
        s = wn.run(nw, 1, a.shift if shw is None else shw)
        to = tint * 3 + 2
        if wn.wait_dump(s, to) is None or spf.wait_dump(sf, to) is None:
            raise RuntimeError("ダンプが閉じない")
        m, pw, _ = wn.read_dump()
        mf, pf, _ = spf.read_dump()
        if m["sat"] or mf.get("sat", 0):
            nsat[0] += 1
        return pw.astype(float) / m["n"], pf.astype(float) / mf["n"], m, mf

    def full_ref(pf, pf0, f):
        kf = int(round(f / DF_FULL)); df = f / DF_FULL - kf
        return (pf[kf] - pf0[kf]) / (np.sinc(df) ** 2), kf, df

    t0 = time.time()
    log(f"基準（SG を切る、{a.w3_tint} s）…")
    pw0, pf0, m0, _ = measure(a.w3_tint, a.shift_full)
    if do3 and (shf3 != a.shift_full or sh3 != a.shift):
        pw03, pf03, _, _ = measure(a.w3_tint, shf3, sh3)
    else:
        pw03, pf03 = pw0, pf0
    nb = np.where(np.arange(NFFT_W) < NFFT_W // 2, np.arange(NFFT_W), np.arange(NFFT_W) - NFFT_W) * dw
    floor_w = float(np.median(pw0[np.abs(nb) <= 0.45 * w]))
    floor_w3 = float(np.median(pw03[np.abs(nb) <= 0.45 * w]))
    log(f"  窓の雑音の床（中央 90 % の ch の中央値）{floor_w:.1f} LSB² / フレーム（SHIFT {a.shift}）"
        + (f"・W-3 の SHIFT {sh3} で {floor_w3:.1f}" if do3 else ""))
    sg.set_output(True)
    sg.log = quiet
    ok = True
    res = dict(c=c, w=w, k=k, dphi=dphi, ns=ns, shift=a.shift, shift_full=a.shift_full, sg_dbm=a.sg_dbm, sg=str(sg.state()))

    def judge(cond, msg):
        nonlocal ok
        log(("  OK  " if cond else "  NG  ") + msg)
        ok &= bool(cond)

    if do2:
        g2 = []
        for i, nu in enumerate(nus2):
            f = c + nu
            sg.set_freq_mhz(4096.0 - f)
            time.sleep(a.sg_settle)
            pw, pf, m, mf = measure(a.tint, a.shift_full)
            b = int(round(nu / dw)) % NFFT_W
            ref, kf, df = full_ref(pf, pf0, f)
            g = (pw[b] - pw0[b]) / ref / pred
            g2.append(10 * np.log10(max(g, 1e-12)))
            if i % 10 == 0 or abs(nu) > 0.45 * w:
                log(f"  W-2 [{i + 1}/{len(nus2)}] ν {nu:+.5f} MHz（{nu / w:+.4f} W）: 窓 / 全帯域 {g2[-1]:+.3f} dB（模型 {m2[i]:+.3f}）")
        g2 = np.array(g2); nus2a = np.array(nus2)
        mid = np.abs(nus2a) <= 0.45 * w
        edge = ~mid
        ctr = np.abs(nus2a) <= 0.1 * w
        rel = g2 - np.median(g2[ctr]); mrel = m2 - np.median(m2[ctr])
        dmid = np.max(np.abs(rel[mid] - mrel[mid]))
        judge(np.ptp(g2[mid]) <= a.tol_pp, f"W-2a: 中央 90 % の平らさ p-p {np.ptp(g2[mid]):.3f} dB（模型 {np.ptp(m2[mid]):.3f}、許容 {a.tol_pp}）"
                                          f"・絶対値の中央値 {np.median(g2[mid]):+.3f} dB")
        judge(dmid <= a.tol_mid, f"W-2b: 中央 90 % の模型との差の最大 {dmid:.3f} dB（許容 {a.tol_mid}。|ν| ≦ 0.1W の中央値で揃える）")
        if edge.any():
            de = np.abs(rel[edge] - mrel[edge]); j = int(np.argmax(de))
            judge(de.max() <= a.tol_edge, f"W-2c: 両端 5 % の模型との差の最大 {de.max():.3f} dB（ν {nus2a[edge][j] / w:+.4f} W: "
                                          f"実測 {rel[edge][j]:+.2f}・模型 {mrel[edge][j]:+.2f} dB、許容 {a.tol_edge}）")
        res.update(w2_nu=nus2a, w2_db=g2, w2_model=m2)

    if do3:
        if dbm3 != a.sg_dbm:
            sg.set_dbm(dbm3)
        log(f"W-3: SG {dbm3:+.1f} dBm・窓の SHIFT {sh3}・全帯域の SHIFT {shf3}・{a.w3_tint} s / 点")
        rows = []
        for i, ((nu, al), gmod, nq) in enumerate(zip(w3, gp, nup)):
            f = c + nu
            sg.set_freq_mhz(4096.0 - f)
            time.sleep(a.sg_settle)
            pw, pf, m, mf = measure(a.w3_tint, shf3, sh3)
            ref, kf, df = full_ref(pf, pf03, f)
            ba = int(round(nq / dw)) % NFFT_W
            diff = pw - pw03
            nub = np.where(np.arange(NFFT_W) < NFFT_W // 2, np.arange(NFFT_W), np.arange(NFFT_W) - NFFT_W) * dw
            use = (np.abs(nub) <= 0.45 * w) & (np.abs(np.arange(NFFT_W) - ba) > 3)
            sig = robust_sigma(diff[use])
            ex = diff[ba]
            if floor_w3 < 4.0:
                sig = np.inf                               # 雑音が量子化で消えている: 小さな折り返しも消えうる
            lim = 10 * np.log10(max(5 * sig, 1e-30) / (ref * pred3)) if np.isfinite(sig) else np.inf
            lev = 10 * np.log10(max(ex, 1e-30) / (ref * pred3)) if ex > 5 * sig else None
            # 同じ IF に全帯域でも線があるか（ADC 側の線）
            fa = c + nq
            ka = int(round(fa / DF_FULL))
            dfa = pf[ka] - pf03[ka]
            sigf = robust_sigma((pf - pf03)[max(0, ka - 40):ka + 40])
            lev_full = 10 * np.log10(max(dfa, 1e-30) / ref) if dfa > 5 * sigf else None
            adc = lev is not None and lev_full is not None and lev_full >= lev - 3.0
            rows.append((nu, nq, gmod, lev, lim, lev_full, adc))
            tag = ("ADC 側の線（全帯域でも同じ IF に " + f"{lev_full:+.1f} dB）" if adc else "")
            log(f"  W-3 [{i + 1}/{len(w3)}] ν {nu:+10.4f} MHz → {nq:+.4f}: "
                + (f"{lev:+.1f} dB" if lev is not None else
                   (f"< {lim:+.1f} dB（検出限界）" if np.isfinite(lim) else "判定できない（窓の雑音の床 < 4 LSB²）"))
                + f"（模型 {gmod:+.1f}）{tag}")
        worst = None; undec = 0; nadc = 0
        for nu, nq, gmod, lev, lim, lev_full, adc in rows:
            if adc:
                nadc += 1; continue
            v = lev if lev is not None else lim
            if lev is None and lim > -a.alias_req:
                undec += 1
            if lev is not None and (worst is None or v > worst[0]):
                worst = (v, nu)
        ntot = len(rows)
        wv = worst[0] if worst else None
        judge((wv is None or wv <= -a.alias_req) and undec == 0,
              f"W-3: 折り返しの最大 {('%+.1f dB（ν %+.3f MHz）' % worst) if worst else '検出限界より下'} / 要求 −{a.alias_req:.0f} dB"
              f"（{ntot} 点、ADC 側の線として除いた {nadc}、検出限界が要求に届かず判定できない {undec}）")
        if undec:
            if floor_w3 < 4.0:
                log(f"    → 窓の雑音の床 {floor_w3:.1f} LSB² が 4 を切っている: --w3-shift を下げる（1 下げると床は 4 倍）")
            else:
                log("    → --w3-dbm を上げる（全帯域が飽和しないよう --w3-shift-full も）か --w3-tint を延ばす。雑音源を外すとさらに下がる")
        res.update(w3=np.array([(r[0], r[1], r[2], np.nan if r[3] is None else r[3], r[4],
                                 np.nan if r[5] is None else r[5], r[6]) for r in rows], dtype=float))

    sg.set_output(False)
    pw1, pf1, _, _ = measure(a.w3_tint, a.shift_full)
    drift = np.median(pw1[pw0 > 0] / pw0[pw0 > 0])
    flags = wn.rd(WN.R_FLAGS)
    judge((flags & 0x3EF) == 0 and nsat[0] == 0,
          f"W-0: FLAGS {flags:#x}（{WN.flag_text(flags)}）・飽和した点 {nsat[0]}・基準の雑音の前後の比 {drift:.4f}")
    log(f"かかった時間 {time.time() - t0:.0f} s")
    if a.out:
        np.savez(a.out + ".sweep.npz", pw0=pw0, pf0=pf0, pw1=pw1, pf1=pf1, **res)
        log(f"書いた: {a.out}.sweep.npz")
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            n = int(do2) + int(do3)
            fig, ax = plt.subplots(n, 1, figsize=(8, 3.6 * n), squeeze=False)
            i = 0
            if do2:
                ax[i][0].plot(nus2a / w, rel, "o", ms=3, label="measured"); ax[i][0].plot(nus2a / w, mrel, "-", label="model")
                ax[i][0].set_xlabel("ν / W"); ax[i][0].set_ylabel("gain [dB]"); ax[i][0].legend(); ax[i][0].grid(alpha=.3)
                i += 1
            if do3:
                r = res["w3"]
                ax[i][0].plot(np.abs(r[:, 0]) / w, r[:, 3], "o", ms=4, label="measured")
                ax[i][0].plot(np.abs(r[:, 0]) / w, r[:, 4], "v", ms=3, alpha=.5, label="detection limit")
                ax[i][0].plot(np.abs(r[:, 0]) / w, r[:, 2], "x", ms=4, label="model")
                ax[i][0].axhline(-a.alias_req, color="k", lw=.8); ax[i][0].set_xscale("log")
                ax[i][0].set_xlabel("|ν_out| / W"); ax[i][0].set_ylabel("alias [dB]"); ax[i][0].legend(); ax[i][0].grid(alpha=.3)
            fig.suptitle(f"window IF {if_c:.3f} MHz +/- {w / 2} MHz")
            fig.tight_layout(); fig.savefig(a.out + ".sweep.png", dpi=120)
            log(f"書いた: {a.out}.sweep.png")
        except ImportError:
            pass
    log("RESULT " + ("OK" if ok else "NG"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
