#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj014 — 窓の掃引（判定 W-2・W-3）。SG の周波数を動かしながら、窓（win_core_0）と全帯域（spec_core_1）を同時に測る。

  W-2  窓の中の利得の形: 窓の中（|ν| < 0.5W）に CW を置き、ch の利得を ν ごとに測って模型（src/common/win_coef.vh の係数）と比べる
       W-2a 中央 90 %（|ν| ≦ 0.45W）の平らさ（p-p）/ W-2b 中央 90 % の模型との差 / W-2c 両端 5 % の落ち方の模型との差
  W-3  窓の外からの折り返し: 窓の外に CW を置き、窓の出力のレート W で折り返る先（中央 90 % の中）に出る量を測る（要求 −60 dB）
  W-4  粗い ch の境目（c = 128k + 64）に窓を置く（--w4）。同じ窓を粗い ch k（d = +64）と k + 1（d = −64）の両方で作り、
       それぞれ W-2 を測って模型と比べ（W-4a）、2 つの利得の差が中央 90 % で小さいこと（W-4b）を見る。PFB の通過域の縁を使う置き方

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
  python3 winsweep.py --if 3008 --w 256 --clkin 0 --ref 10 --w4          W-4（IF 3008 = c 1088 = 128·8 + 64）
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
    """src/common/win_coef.vh（make coef の生成物）から PFB・light・final の係数（実数）を読む。"""
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


def chain(coef, f, c, w, k=None):
    """入力の周波数 f（f の側、MHz、両側）→ 窓の出力の ν と振幅の利得（model/win_model.py の chain_gain と同じ流れ）。
    k を与えると粗い ch をそれに固定する（W-4。d = c − 128k）。"""
    if k is None:
        k = int(round(c / S_CH))
    d = c - S_CH * k
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


def model_db(coef, f, c, w, k=None):
    """CW 1 本（実数なので ±f の両方）の、窓の出力での (ν, 電力の利得 dB)。+f の側と −f の側。"""
    nu_p, g_p = chain(coef, f, c, w, k)
    nu_m, g_m = chain(coef, -np.asarray(f), c, w, k)
    _, g0 = chain(coef, [c], c, w, round(c / S_CH) if k is None else k)
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
        # proj015 実機（2026-10-02、2 MHz・IF 2050）: 全帯域の ch のちょうど境目（端数 0.5）に置いた 4 点だけが模型から +0.52〜−0.69 dB 外れた
        #   （2 回とも同じ点・同じ大きさ）。境目では全帯域の山が sinc²(0.5) = −3.9 dB に落ち、fs/2 の近くでは実数の入力の像（2·(fs/2) − f、
        #   数 ch 先）の漏れが同じ ch に重なって、基準の補正 1/sinc² が狂う。窓の側の誤りではない。**端数 |df| > 0.4 の点は置かない**
        dfr = f / DF_FULL - round(f / DF_FULL)
        if abs(dfr) > 0.4:
            continue
        # 全帯域の DC と fs/2 の近く（1 MHz = 2 ch）は基準にならない（実数の FFT の端の ch、±f の像が同じ ch に重なる）ので置かない
        if abs(nu2) < 0.5 * w - 1e-9 and 2 * DF_FULL <= f <= FS / 2 - 2 * DF_FULL:
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
    p.add_argument("--w4", action="store_true", help="W-4: 粗い ch の境目の窓を k と k + 1 の両方で作って W-2 を比べる（W-2・W-3 の代わり）")
    p.add_argument("--tol-w4", type=float, default=0.05, help="W-4b 2 つの k の利得の差（中央 90 %）[dB]")
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
    p.add_argument("--w3-shift", type=int, default=None, help="W-3 の窓の SHIFT（既定: SG を切った床から、量子化を除いた真の雑音で床 ≧ 16 LSB² になるよう自動で選ぶ）")
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
    p.add_argument("--save-spectra", action="store_true",
                   help="CW ごとの生スペクトル（窓 4096 ch・全帯域 4096 ch、1 フレームあたり）も npz に（W-2 55 点で約 2 MB / float32）")
    p.add_argument("--adc", type=int, default=1, choices=(0, 1, 2, 3), help="窓の ADC（0..3 = ADC_A..D。proj015）")
    p.add_argument("--win", type=int, default=0, choices=(0, 1, 2, 3), help="その ADC の窓の番号（proj015）")
    a = p.parse_args()

    import window as WN
    WN.set_sel(a)
    c, k, dphi, ns, if_c = WN.window_params(a.if_c, a.w, grid=not a.no_grid)
    w = a.w
    dw = w / NFFT_W
    log(f"窓: IF {if_c:.6f} MHz ± {w / 2}（c = {c:.6f}）/ WK {k} / WDPHI {dphi:#010x} / WNS {ns}")

    coef_path = a.coef or next((q for q in (os.path.join(HERE, "win_coef.vh"), os.path.join(HERE, "..", "src", "common", "win_coef.vh"))
                                if os.path.exists(q)), None)
    if coef_path is None:
        log("ERROR: win_coef.vh が無い（--coef で与えるか、src/common/win_coef.vh をこのスクリプトの隣に置く）"); sys.exit(1)
    coef = load_coef(coef_path)
    log(f"模型の係数: {coef_path}（PFB {len(coef['pfb'])}・light {len(coef['light'])}・final {len(coef['final'])} タップ）")

    do2 = a.only in (None, "w2")
    do3 = a.only in (None, "w3") and not a.w4
    ks = [k]
    if a.w4:
        kb = int(np.floor(c / S_CH))
        if abs(c - S_CH * kb - 64.0) > 1e-9:
            log(f"ERROR: --w4 は窓の中心が粗い ch の境目（c = 128k + 64）のとき。今は c = {c:.4f}（d = {c - 128 * k:+.4f}）。"
                f"例: --if {4096 - (128 * kb + 64):.0f} か --if {4096 - (128 * kb + 192):.0f}"); sys.exit(1)
        ks = [kb, kb + 1]
        do2 = True
        log(f"W-4: 境目 c = {c:.1f} = 128·{kb} + 64。粗い ch {kb}（d = +64）と {kb + 1}（d = −64）で同じ窓を作る")
    f_grid = w >= 64
    nus2 = plan_w2(c, w, a.w2_n, a.w2_edge, f_grid) if do2 else []
    w3 = plan_w3(c, w, [int(x) for x in a.w3_m.split(",") if x], a.w3_max,
                 [int(x) for x in a.w3_pfb.split(",") if x]) if do3 else []
    if do2:
        m2s = {kk: model_db(coef, c + np.array(nus2), c, w, kk)[1] for kk in ks}
        m2 = m2s[ks[0]]
        mid = np.abs(nus2) <= 0.45 * w
        if a.w4:
            log(f"W-4: 模型の 2 つの k の差（中央 90 %）の最大 {np.max(np.abs(m2s[ks[0]] - m2s[ks[1]])[mid]):.4f} dB / "
                f"中央 90 % の p-p k {ks[0]}: {np.ptp(m2s[ks[0]][mid]):.3f}・k {ks[1]}: {np.ptp(m2s[ks[1]][mid]):.3f} dB")
        if c - 0.5 * w < 2 * DF_FULL or c + 0.5 * w > FS / 2 - 2 * DF_FULL:
            log("W-2: 窓が DC か fs/2 から 1 MHz 以内に掛かる。そこには CW を置かない（全帯域の基準にならない）。"
                "**実数の入力の像（−f）が窓の両端 5 % に落ちる**（中央 90 % には落ちない。模型の予言を下の W-2' に出す）")
            _, _, nu_i, g_i = model_db(coef, c + np.array(nus2), c, w)
            inw = np.abs(nu_i) <= 0.45 * w
            log(f"W-2': 窓の中の CW の −f の像: 中央 90 % に落ちる最大 {g_i[inw].max() if inw.any() else -999:+.1f} dB・両端 5 % を含めた最大 {g_i[np.abs(nu_i) < 0.5 * w].max() if (np.abs(nu_i) < 0.5 * w).any() else -999:+.1f} dB")
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
    def dphi_of(kk):
        return int(round((c - S_CH * kk) / 512.0 * 2 ** 32)) % (1 << 32)
    wn.set_window(ks[0], dphi_of(ks[0]), ns)
    spf = WN.open_full(ol)
    shf3 = a.w3_shift_full if a.w3_shift_full is not None else a.shift_full
    dbm3 = a.w3_dbm if a.w3_dbm is not None else a.sg_dbm
    pred = WN.pred_ratio(ns, a.shift_full, a.shift)
    sh3 = a.w3_shift if a.w3_shift is not None else a.shift      # 自動のときは基準を測ってから決め直す
    pred3 = WN.pred_ratio(ns, shf3, sh3)
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
    nb = np.where(np.arange(NFFT_W) < NFFT_W // 2, np.arange(NFFT_W), np.arange(NFFT_W) - NFFT_W) * dw
    if do3 and a.w3_shift is None:
        # 床 = 真の雑音 ＋ 量子化（約 0.67 LSB²）。真の雑音は SHIFT を 1 下げると 4 倍。床 ≧ 16 を狙う（W-3 の CW は窓の外なので窓は飽和しない）
        fl = float(np.median(pw0[np.abs(nb) <= 0.45 * w]))
        true = max(fl - 0.67, 0.02)
        n_dn = max(0, int(np.ceil(np.log(16.0 / true) / np.log(4.0))))
        sh3 = max(0, a.shift - n_dn)
        pred3 = WN.pred_ratio(ns, shf3, sh3)
        log(f"  W-3 の窓の SHIFT を自動で {sh3}（SHIFT {a.shift} の床 {fl:.2f}、量子化を除いて {true:.2f} LSB²）")
    if do3 and (shf3 != a.shift_full or sh3 != a.shift):
        pw03, pf03, _, _ = measure(a.w3_tint, shf3, sh3)
    else:
        pw03, pf03 = pw0, pf0
    # 自動のときは、測った床が 16 に届くまで SHIFT をさらに下げて測り直す（真の雑音の見積もりは床が量子化に近いと粗い。
    # 実機の 8 MHz・IF 4000 で、見積もりどおりに下げても床が 4 に届かず W-3 が全点「判定できない」になった）
    while do3 and a.w3_shift is None and sh3 > 0 and float(np.median(pw03[np.abs(nb) <= 0.45 * w])) < 16.0:
        sh3 -= 1
        pred3 = WN.pred_ratio(ns, shf3, sh3)
        pw03, pf03, _, _ = measure(a.w3_tint, shf3, sh3)
        log(f"  床が 16 に届かないので W-3 の窓の SHIFT を {sh3} に下げた（床 {float(np.median(pw03[np.abs(nb) <= 0.45 * w])):.1f} LSB²）")
    floor_w = float(np.median(pw0[np.abs(nb) <= 0.45 * w]))
    floor_w3 = float(np.median(pw03[np.abs(nb) <= 0.45 * w]))
    log(f"  窓の雑音の床（中央 90 % の ch の中央値）{floor_w:.1f} LSB² / フレーム（SHIFT {a.shift}）"
        + (f"・W-3 の SHIFT {sh3} で {floor_w3:.1f}" if do3 else ""))
    sg.set_output(True)
    sg.log = quiet
    ok = True
    res = dict(c=c, w=w, k=k, dphi=dphi, ns=ns, shift=a.shift, shift_full=a.shift_full, sg_dbm=a.sg_dbm, sg=str(sg.state()),
               if_win=WN.ch_if(c, w), if_full=4096.0 - np.arange(NFFT_W) * DF_FULL)
    raw = {}                       # --save-spectra: 名前 → [(SG の IF, 窓, 全帯域), ...]

    def keep(name, if_sg, pw, pf):
        if a.save_spectra:
            raw.setdefault(name, []).append((if_sg, pw.astype(np.float32), pf.astype(np.float32)))

    def judge(cond, msg):
        nonlocal ok
        log(("  OK  " if cond else "  NG  ") + msg)
        ok &= bool(cond)

    def run_w2(kk, m2, pw0, pf0, tag):
        g2 = []
        for i, nu in enumerate(nus2):
            f = c + nu
            sg.set_freq_mhz(4096.0 - f)
            time.sleep(a.sg_settle)
            pw, pf, m, mf = measure(a.tint, a.shift_full)
            keep(f"w2_k{kk}" if a.w4 else "w2", 4096.0 - f, pw, pf)
            b = int(round(nu / dw)) % NFFT_W
            ref, kf, df = full_ref(pf, pf0, f)
            g = (pw[b] - pw0[b]) / ref / pred
            g2.append(10 * np.log10(max(g, 1e-12)))
            if i % 10 == 0 or abs(nu) > 0.45 * w:
                log(f"  W-2{tag} [{i + 1}/{len(nus2)}] ν {nu:+.5f} MHz（{nu / w:+.4f} W）: 窓 / 全帯域 {g2[-1]:+.3f} dB（模型 {m2[i]:+.3f}）")
        g2 = np.array(g2); nus2a = np.array(nus2)
        mid = np.abs(nus2a) <= 0.45 * w
        edge = ~mid
        ctr = np.abs(nus2a) <= 0.1 * w
        rel = g2 - np.median(g2[ctr]); mrel = m2 - np.median(m2[ctr])
        dmid = np.max(np.abs(rel[mid] - mrel[mid]))
        judge(np.ptp(g2[mid]) <= a.tol_pp, f"W-2a{tag}: 中央 90 % の平らさ p-p {np.ptp(g2[mid]):.3f} dB（模型 {np.ptp(m2[mid]):.3f}、許容 {a.tol_pp}）"
                                          f"・絶対値の中央値 {np.median(g2[mid]):+.3f} dB")
        judge(dmid <= a.tol_mid, f"W-2b{tag}: 中央 90 % の模型との差の最大 {dmid:.3f} dB（許容 {a.tol_mid}。|ν| ≦ 0.1W の中央値で揃える）")
        if edge.any():
            de = np.abs(rel[edge] - mrel[edge]); j = int(np.argmax(de))
            judge(de.max() <= a.tol_edge, f"W-2c{tag}: 両端 5 % の模型との差の最大 {de.max():.3f} dB（ν {nus2a[edge][j] / w:+.4f} W: "
                                          f"実測 {rel[edge][j]:+.2f}・模型 {mrel[edge][j]:+.2f} dB、許容 {a.tol_edge}）")
        return nus2a, g2, rel, mrel

    if do2 and not a.w4:
        nus2a, g2, rel, mrel = run_w2(ks[0], m2, pw0, pf0, "")
        res.update(w2_nu=nus2a, w2_db=g2, w2_model=m2)
    if a.w4:
        out4 = {}
        for n_k, kk in enumerate(ks):
            if n_k > 0:
                sg.set_output(False)
                wn.set_window(kk, dphi_of(kk), ns)
                pw0k, pf0k, _, _ = measure(a.w3_tint, a.shift_full)
                sg.set_output(True)
            else:
                pw0k, pf0k = pw0, pf0
            log(f"W-4: 粗い ch {kk}（d = {c - S_CH * kk:+.0f} MHz、WDPHI {dphi_of(kk):#010x}）")
            out4[kk] = run_w2(kk, m2s[kk], pw0k, pf0k, f"（k {kk}）")
        nus2a = out4[ks[0]][0]
        mid = np.abs(nus2a) <= 0.45 * w
        dd = out4[ks[0]][1] - out4[ks[1]][1]
        dm = m2s[ks[0]] - m2s[ks[1]]
        worst = int(np.argmax(np.abs(dd - dm)[mid]))
        judge(np.max(np.abs(dd - dm)[mid]) <= a.tol_w4,
              f"W-4b: 2 つの k の利得の差（中央 90 %、模型の差を除く）の最大 {np.max(np.abs(dd - dm)[mid]):.3f} dB"
              f"（ν {nus2a[mid][worst] / w:+.4f} W、許容 {a.tol_w4}）・差の平均 {np.mean(dd[mid]):+.3f} dB")
        res.update(w4_k=np.array(ks), w2_nu=nus2a, w4_db0=out4[ks[0]][1], w4_db1=out4[ks[1]][1],
                   w4_model0=m2s[ks[0]], w4_model1=m2s[ks[1]])
        do2 = False                                      # 下の図は W-2 の 1 本ぶんを描くので、W-4 のときは描かない

    if do3:
        if dbm3 != a.sg_dbm:
            sg.set_dbm(dbm3)
        log(f"W-3: SG {dbm3:+.1f} dBm・窓の SHIFT {sh3}・全帯域の SHIFT {shf3}・{a.w3_tint} s / 点")
        res.update(w3_shift=sh3, w3_shift_full=shf3, w3_dbm=dbm3)
        rows = []
        for i, ((nu, al), gmod, nq) in enumerate(zip(w3, gp, nup)):
            f = c + nu
            sg.set_freq_mhz(4096.0 - f)
            time.sleep(a.sg_settle)
            pw, pf, m, mf = measure(a.w3_tint, shf3, sh3)
            keep("w3", 4096.0 - f, pw, pf)
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
            ka = int(round(fa / DF_FULL)); dka = fa / DF_FULL - ka
            dfa = pf[ka] - pf03[ka]
            sigf = robust_sigma((pf - pf03)[max(0, ka - 40):ka + 40])
            # 全帯域の ch の端数の目減りを戻す（窓の ch の中心は全帯域の ch の中心と限らない。実機 7 回目の 32 MHz で −2.5 dB の目減りを戻さず見分けそこねた）
            lev_full = 10 * np.log10(max(dfa, 1e-30) / ref / np.sinc(dka) ** 2) if dfa > 5 * sigf else None
            # ADC のインターリーブの線の位置: CW の ±f に j·fs/8 を足したもの（折り返して 0..2048）。PFB の折り返し（512 の倍数）と同じ離れに出る
            sp = np.array([(sgn * f + j * FS / 8) % FS for sgn in (1, -1) for j in range(8)])
            sp = np.minimum(sp, FS - sp)
            il = bool(np.any(np.abs(sp - fa) < 2 * dw)) and abs(f - fa) > 2 * dw
            # ADC 側の線なら窓でも利得 ≒ 1 で同じ量に見える。全帯域の ch（0.5 MHz）は窓の ch より 256 倍広く、別の線が同じ ch に入りうるので、
            # 量が 3 dB 以内で揃うときだけ ADC 側と見る（全帯域のほうが大きいだけなら、窓の ch とは別の周波数の線）
            adc = lev is not None and lev_full is not None and abs(lev_full - lev) <= 3.0
            rows.append((nu, nq, gmod, lev, lim, lev_full, adc))
            tag = ("ADC 側の線（全帯域でも同じ IF に " + f"{lev_full:+.1f} dB）" if adc else "")
            if il and lev is not None and not adc:
                tag += ("・ADC のインターリーブの線（f ± j·fs/8）の位置" +
                        (f"（全帯域 {lev_full:+.1f} dB）" if lev_full is not None else "（全帯域では雑音より下）"))
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
                # 床 = 真の雑音 ＋ 量子化（>>> は切り捨て: 偏り 0.25 × 2 ＋ 分散 1/12 × 2 ≒ 0.67 LSB²）。真の雑音は SHIFT を 1 下げると 4 倍
                true = max(floor_w3 - 0.67, 0.05)
                n_dn = int(np.ceil(np.log(8.0 / true) / np.log(4.0)))
                log(f"    → 窓の雑音の床 {floor_w3:.1f} LSB²（量子化 0.67 を除くと {true:.2f}）が 4 を切っている:"
                    f" --w3-shift {sh3 - n_dn}（{n_dn} 下げると床は約 {true * 4 ** n_dn + 0.67:.0f} LSB²）")
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
        for name, lst in raw.items():
            res[f"raw_{name}_if"] = np.array([x[0] for x in lst])
            res[f"raw_{name}_win"] = np.stack([x[1] for x in lst])
            res[f"raw_{name}_full"] = np.stack([x[2] for x in lst])
        if do3 and (shf3 != a.shift_full or sh3 != a.shift):
            res.update(pw03=pw03, pf03=pf03)
        np.savez(a.out + ".sweep.npz", pw0=pw0, pf0=pf0, pw1=pw1, pf1=pf1, **res)
        log(f"書いた: {a.out}.sweep.npz")
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            n = int(do2) + int(do3) + int(a.w4)
            fig, ax = plt.subplots(n, 1, figsize=(8, 3.6 * n), squeeze=False)
            i = 0
            if do2:
                ax[i][0].plot(nus2a / w, rel, "o", ms=3, label="measured"); ax[i][0].plot(nus2a / w, mrel, "-", label="model")
                ax[i][0].set_xlabel("ν / W"); ax[i][0].set_ylabel("gain [dB]"); ax[i][0].legend(); ax[i][0].grid(alpha=.3)
                i += 1
            if a.w4:
                for kk, key, mk in ((ks[0], "w4_db0", "w4_model0"), (ks[1], "w4_db1", "w4_model1")):
                    ax[i][0].plot(nus2a / w, res[key], "o", ms=3, label=f"measured k={kk}")
                    ax[i][0].plot(nus2a / w, res[mk], "-", lw=.8, label=f"model k={kk}")
                ax[i][0].set_xlabel("nu / W"); ax[i][0].set_ylabel("gain [dB]"); ax[i][0].legend(); ax[i][0].grid(alpha=.3)
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
