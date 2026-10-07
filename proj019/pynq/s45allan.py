#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — アラン分散（安定度、A-1〜A-3）。specrecv.py（または s45client の out=）で書いた .s45 の記録から、窓ごと・ADC ごとに出す。
記録は大きい（1 時間で ≒ 22 GB）ので、1 度だけ頭から読んで、ダンプごとの小さな量と、ch ごとの値を --chan-bin ダンプずつ束ねたものだけを持つ。

    # 記録（ダウンロード PC。入力は固定のまま: ノイズソース → BPF → アッテネータ（固定）→ 分配 → ADC）
    python3 specctl.py --host <board> "SEND ON" "START n=87890"            # 1 時間
    python3 specrecv.py --host <board> --out allan1.s45 --seconds 3720
    # 解析（どの PC でも。numpy・matplotlib）
    python3 s45allan.py allan1.s45                 # 表と図（allan1.allan.png）・allan1.allan.json
    python3 s45allan.py allan1.s45 --keys A0,A1 --chan-bin 25

時系列（どれも自分の平均で割った相対値、重なりありのアラン分散 σ²(τ)）:
  (a) 窓の帯域の電力: 中央 90 % の ch（線の ch を除く）の和                     予言 1 / (M·Δν·τ)
  (b) ch ごと: ch ごとのアラン分散の中央値（--chan-bin ダンプ束ねた後）         予言 1 / (Δν·τ)
  (c) ch ごと・共通の利得を除く: 各時刻を「ch の比の中央値」で割ってから (b)     予言 1 / (Δν·τ)
  (d) 分光の安定度: 帯域の下半分 / 上半分 の比                                  予言 1/(M_lo·Δν·τ) + 1/(M_hi·Δν·τ)
  (t) TP（ADC ごと、1.024 ms）                                                  予言 1 / (B·τ)（B = 入力の雑音の帯域、--tp-bw MHz、BPF の幅）
  Δν = ch の幅 = W / 4096（矩形窓、重ならないフレームなので ch は 1 フレームで自由度 2）
アラン時間: 測った σ² が予言の 2 倍を初めて越える τ（越えなければ「測った範囲より長い」）。ポジションスイッチの周期の根拠。
読み落とし・DROP で途切れていたら、最長の連続区間だけを使う（τ の最大はその長さの 1/3）。
線の ch: ch ごとの平均が中央値の 1.5 倍を越える ch と、(b) の 1 番短い τ で予言の 3 倍を越える ch を外す（数を出す）。
"""
import argparse
import json
import sys

import numpy as np

import s45cal
import s45proto as P

KEYS = [f"{a}{w}" for a in "ABCD" for w in "01"]
TAU0 = 0.04096
QMIN = 3.0                           # 1 フレームの ch の電力（SHIFT 後の LSB²）がこれ未満の窓は飛ばす（s45spur と同じ）
TP_TAU0 = 512 * 512 / 256e6          # 1.024 ms


def oavar(x, m):
    """重なりありのアラン分散（列ごと）。x: [N] か [N, C]、m: 束ねる数（proj017 tools/allan.py と同じ）"""
    x = np.asarray(x, np.float64)
    two = x.ndim == 1
    if two:
        x = x[:, None]
    c = np.cumsum(np.vstack([np.zeros((1, x.shape[1])), x]), axis=0)
    y = (c[m:] - c[:-m]) / m
    d = y[m:] - y[:-m]
    v = 0.5 * np.mean(d * d, axis=0)
    return v[0] if two else v


def m_grid(n):
    ms, dec = [], 1
    while dec <= n // 3:
        for f in (1, 2, 5):
            if f * dec <= n // 3:
                ms.append(f * dec)
        dec *= 10
    return ms


def longest_run(k):
    if len(k) < 2:
        return 0, len(k)
    brk = np.flatnonzero(np.diff(k) != 1) + 1
    edges = np.r_[0, brk, len(k)]
    i = int(np.argmax(np.diff(edges)))
    return int(edges[i]), int(edges[i + 1])


def read(paths, keys, chan_bin, frac=0.9):
    """記録を 1 度だけ読む。窓ごと: k・帯域の和・下半分・上半分（ダンプごと）と、ch ごとの chan_bin ダンプの和（float64 で足して float32 で持つ）"""
    w = {k: dict(k=[], band=[], lo=[], hi=[], ch=[], acc=None, nacc_in=0, k_acc=None, meta=None) for k in keys}
    tp = {a: dict(t=[], v=[]) for a in "ABCD"}
    a0 = int(round(P.NCH * (1 - frac) / 2))
    sl = slice(a0, P.NCH - a0)
    half = P.NCH // 2
    nrec = 0
    for path in paths:
        with open(path, "rb") as f:
            while True:
                h = f.read(P.HDR.size)
                if len(h) < P.HDR.size:
                    break
                rtype, plen, crc, seq = P.parse_header(h)
                pl = f.read(plen)
                if len(pl) < plen:
                    break
                nrec += 1
                if rtype == P.T_SPEC:
                    d = P.decode(rtype, pl)
                    key = f"{'ABCD'[d['adc']]}{d['win']}"
                    if key not in w:
                        continue
                    r = w[key]
                    if r["meta"] is None:
                        r["meta"] = dict(ns=d["ns"], nacc=d["nacc"], if_mhz=d["if_mhz"], shift=d["shift"], g=d["g"])
                    elif (d["ns"], d["nacc"], d["shift"]) != (r["meta"]["ns"], r["meta"]["nacc"], r["meta"]["shift"]):
                        raise SystemExit(f"{key}: 記録の途中で設定が変わった（START をまたいだ記録は分けて解析する）")
                    # 切り捨ての偏り（成分ごと +1/3 LSB²、ch で +2/3、N_ACC 回足す）を引く。引かないと、入力が LSB に近い窓
                    # （狭い窓・無入力）で平均が膨らみ、相対の揺らぎが小さく見える（term で (b) が予言の 0.53 倍に見えた）
                    x = d["data"].astype(np.float64) - (2.0 / 3.0) * d["nacc"]
                    r["k"].append(d["k"])
                    r["band"].append(x[sl].sum()); r["lo"].append(x[sl.start:half].sum()); r["hi"].append(x[half:sl.stop].sum())
                    if chan_bin:
                        # 束ねは DUMP_K の連続の上だけ（途切れたら捨てて数え直す）
                        if r["acc"] is None or d["k"] != r["k_acc"] + 1:
                            r["acc"] = np.zeros(P.NCH); r["nacc_in"] = 0; r["k0"] = d["k"]
                        r["acc"] += x; r["nacc_in"] += 1; r["k_acc"] = d["k"]
                        if r["nacc_in"] == chan_bin:
                            r["ch"].append(r["acc"].astype(np.float32)); r.setdefault("ch_k", []).append(r["k0"])
                            r["acc"] = None
                elif rtype == P.T_TP:
                    d = P.decode(rtype, pl)
                    e = d["e"]
                    tp["ABCD"[d["adc"]]]["t"].append(e["t_beat"].astype(np.int64))
                    tp["ABCD"[d["adc"]]]["v"].append(e["sum"].astype(np.float64) / e["nfr"])
    return w, tp, nrec


RHO_LAGS = (1, 2, 4, 8, 16, 64)


def tp_extra(v, pred0):
    """TP の補助の量。v = 区切りごとの Σx²/nfr（1 フレーム 8192 サンプルの和）
    dbfs     平均の電力（σ² = v/8192、DC も含む）
    white_ratio  2 階差分 x[i] − 2x[i+1] + x[i+2] の分散 / 6 を、τ0 の予言で割ったもの。
             白い成分だけなら 1 倍の予言と比べられる（直線の漂いは消え、1/f の漏れも 1 階差分より小さい）
    rho_hp   65 点の移動平均を引いた後の自己相関（RHO_LAGS）。区切りどうしが重なっていれば ρ(1) > 0 に出る"""
    s2 = v / 8192.0
    x = v / v.mean()
    d2 = x[:-2] - 2 * x[1:-1] + x[2:]
    white = float(np.mean(d2 * d2) / 6.0)
    k = 65
    if len(x) > 10 * k:
        c = np.cumsum(np.r_[0.0, x])
        ma = (c[k:] - c[:-k]) / k
        h = x[k // 2: k // 2 + len(ma)] - ma
        h = h - h.mean()
        v0 = np.mean(h * h)
        rho = [float(np.mean(h[:-L] * h[L:]) / v0) for L in RHO_LAGS]
    else:
        rho = []
    return dict(dbfs=float(s45cal.dbfs(s2.mean())), sigma2=float(s2.mean()), white_ratio=white / pred0, rho_lags=list(RHO_LAGS), rho_hp=rho)


def mask_lines(ch):
    m = ch.mean(axis=0)
    med = np.median(m)
    return m <= 1.5 * med


def analyze(paths, keys=None, chan_bin=25, tp_bw=1800.0, plot=True, out=None):
    keys = keys or KEYS
    w, tp, nrec = read(paths, keys, chan_bin)
    out = out or paths[0].rsplit(".s45", 1)[0]
    res = {}
    print(f"アラン分散: {', '.join(paths)}（記録 {nrec}）。τ0 = 40.96 ms、ch は {chan_bin} ダンプ（{chan_bin * TAU0:.3f} s）ずつ束ねて")
    rows_plot = {}
    for key in keys:
        r = w[key]
        if not r["k"]:
            continue
        k = np.array(r["k"], np.int64)
        a, b = longest_run(k)
        n = b - a
        meta = r["meta"]
        W = 512.0 / (1 << meta["ns"])
        dnu = W * 1e6 / P.NCH
        band = np.array(r["band"][a:b]); lo = np.array(r["lo"][a:b]); hi = np.array(r["hi"][a:b])
        # 量子化: 1 フレームの ch の電力（偏りを引いた後、SHIFT 後の LSB²）。QMIN 未満（無入力の狭い窓など）は
        # χ² でなく量子化の形になり、偏りを引くと平均が 0 に近づいて相対の揺れが意味を持たない → 飛ばす
        q = band.mean() / (P.NCH - 2 * int(round(P.NCH * 0.05))) / meta["nacc"]
        if q < QMIN:
            print(f"  {key}（{W:g} MHz）: 1 フレームの ch の電力 {q:.2g} LSB²（{QMIN:g} 未満、量子化に埋もれている）→ 飛ばす")
            res[key] = dict(W=W, n=n, skipped=f"q {q:.3g} LSB2 < {QMIN:g}")
            continue
        # 線の ch（束ねたもので決める）
        ch = np.array(r["ch"]) if r["ch"] else None
        if ch is not None:
            ck = np.array(r["ch_k"])
            # 束ねの頭の k が chan_bin ずつ進む最長の区間
            brk = np.flatnonzero(np.diff(ck) != chan_bin) + 1
            edges = np.r_[0, brk, len(ck)]
            i = int(np.argmax(np.diff(edges))); ca, cb = int(edges[i]), int(edges[i + 1])
            ch = ch[ca:cb].astype(np.float64)
        frac = 0.9
        a0 = int(round(P.NCH * (1 - frac) / 2))
        use = np.zeros(P.NCH, bool); use[a0:P.NCH - a0] = True
        nline = 0
        if ch is not None and len(ch) > 3:
            good = mask_lines(ch)
            rel1 = ch[:, use & good] / ch[:, use & good].mean(axis=0)
            v1 = oavar(rel1, 1)
            pred1 = 1.0 / (dnu * chan_bin * TAU0)
            ok_ch = np.ones(P.NCH, bool); idx = np.flatnonzero(use & good)
            ok_ch[idx[v1 > 3 * pred1]] = False
            good &= ok_ch
            nline = int(np.sum(use & ~good))
        M = int(np.sum(use & good)) if ch is not None else int(np.sum(use))
        M_lo = int(np.sum((use & good)[:P.NCH // 2])) if ch is not None else M // 2
        M_hi = M - M_lo
        if min(M_lo, M_hi) < 1:
            print(f"  {key}: 使える ch が無い（線で外しきった）→ 飛ばす")
            res[key] = dict(W=W, n=n, skipped="no usable channels")
            continue
        out_k = {}
        ms = m_grid(n)
        taus = np.array(ms) * TAU0
        series = dict(band=band / band.mean(), sub=(lo / hi) / np.mean(lo / hi))
        preds = dict(band=1.0 / (M * dnu * taus), sub=(1.0 / M_lo + 1.0 / M_hi) / (dnu * taus))
        for nm, x in series.items():
            out_k[nm] = dict(tau=taus.tolist(), avar=[float(oavar(x, m)) for m in ms], pred=preds[nm].tolist())
        if ch is not None and len(ch) > 6:
            sel = use & good
            rel = ch[:, sel] / ch[:, sel].mean(axis=0)
            g = np.median(rel, axis=1, keepdims=True)
            msc = m_grid(len(rel))
            tc = np.array(msc) * chan_bin * TAU0
            out_k["ch"] = dict(tau=tc.tolist(), avar=[float(np.median(oavar(rel, m))) for m in msc], pred=(1.0 / (dnu * tc)).tolist())
            out_k["ch_cg"] = dict(tau=tc.tolist(), avar=[float(np.median(oavar(rel / g, m))) for m in msc], pred=(1.0 / (dnu * tc)).tolist())
        for nm, d in out_k.items():
            av, pr = np.array(d["avar"]), np.array(d["pred"])
            over = np.flatnonzero(av > 2 * pr)
            d["allan_time"] = float(d["tau"][over[0]]) if len(over) else None
            d["ratio_first"] = float(av[0] / pr[0]) if len(av) else None
        # 水準: ch の平均（切り捨ての偏りを引いた後、14 bit の LSB²。abs と同じ単位）と、偏りがその何割か
        sl_n = P.NCH - 2 * a0
        ch_raw = band.mean() / sl_n
        bias = (2.0 / 3.0) * meta["nacc"]
        scale = 4.0 ** meta["shift"] * 4.0 ** (4 - meta["g"]) / 2.0 ** 31 / meta["nacc"]
        lvl = dict(ch_mean_abs=float(ch_raw * scale), bias_frac=float(bias / ch_raw) if ch_raw > 0 else None)
        res[key] = dict(W=W, dnu_hz=dnu, n=n, dropped_before=int(a), M=M, lines=nline, level=lvl, q=out_k)
        print(f"  {key}（{W:g} MHz、Δν {dnu / 1e3:.2f} kHz）: 連続 {n} ダンプ（{n * TAU0:.0f} s）・使う ch {M}・線で外した ch {nline}・"
              f"ch の平均 {lvl['ch_mean_abs']:.3g} LSB²（切り捨ての偏りはその {lvl['bias_frac'] or 0:.2f} 倍）")
        for nm, lab in (("band", "(a) 帯域"), ("ch", "(b) ch ごと"), ("ch_cg", "(c) 共通利得を除く"), ("sub", "(d) 分光（下/上）")):
            if nm in out_k:
                d = out_k[nm]
                at = d["allan_time"]
                print(f"      {lab:16s}: 最短の τ で 予言の {d['ratio_first']:.2f} 倍・予言の 2 倍を越える τ "
                      f"{'%.2f s' % at if at else '（測った範囲 %.0f s まで越えない）' % d['tau'][-1]}")
        rows_plot[key] = out_k
    for a in "ABCD":
        if not tp[a]["t"]:
            continue
        t = np.concatenate(tp[a]["t"]); v = np.concatenate(tp[a]["v"])
        kk = (t - t[0]) // (512 * 512)
        i0, i1 = longest_run(kk)
        x = v[i0:i1] / v[i0:i1].mean()
        ms = m_grid(len(x))
        taus = np.array(ms) * TP_TAU0
        av = np.array([float(oavar(x, m)) for m in ms]); pr = 1.0 / (tp_bw * 1e6 * taus)
        over = np.flatnonzero(av > 2 * pr)
        d = dict(tau=taus.tolist(), avar=av.tolist(), pred=pr.tolist(), allan_time=float(taus[over[0]]) if len(over) else None,
                 ratio_first=float(av[0] / pr[0]))
        ex = tp_extra(v[i0:i1], pr[0])
        res[f"TP {a}"] = dict(n=len(x), q=dict(tp=d), **ex)
        rows_plot[f"TP {a}"] = dict(tp=d)
        print(f"  TP {a}: 連続 {len(x)} 区切り（{len(x) * TP_TAU0:.0f} s）・{ex['dbfs']:.2f} dBFS・最短の τ で 予言（B = {tp_bw:g} MHz）の {d['ratio_first']:.2f} 倍・"
              f"2 倍を越える τ {'%.3f s' % d['allan_time'] if d['allan_time'] else 'なし'}")
        print(f"        白い部分（2 階差分）: 予言の {ex['white_ratio']:.2f} 倍・高域の自己相関 ρ(1,2,4,8) = "
              + ", ".join(f"{r:+.3f}" for r in ex['rho_hp'][:4]))
    json.dump(dict(paths=paths, chan_bin=chan_bin, tp_bw_mhz=tp_bw, res=res), open(out + ".allan.json", "w"), ensure_ascii=False, indent=1)
    print(f"まとめ: {out}.allan.json")
    if plot and rows_plot:
        _plot(out + ".allan.png", rows_plot)
    return res


def _plot(png, rows):
    import matplotlib.pyplot as plt
    ks = list(rows)
    cols = 4
    nr = -(-len(ks) // cols)
    fig, axs = plt.subplots(nr, cols, figsize=(4.4 * cols, 3.4 * nr), squeeze=False)
    sty = dict(band="C0", ch="C1", ch_cg="C2", sub="C3", tp="C4")
    lab = dict(band="(a) band", ch="(b) per ch", ch_cg="(c) per ch, gain removed", sub="(d) lo/hi", tp="TP")
    for ax, k in zip(axs.ravel(), ks):
        for nm, d in rows[k].items():
            ax.loglog(d["tau"], d["avar"], "o-", ms=3, color=sty[nm], label=lab[nm])
            ax.loglog(d["tau"], d["pred"], "--", lw=0.8, color=sty[nm])
        ax.set_title(k, fontsize=9); ax.grid(alpha=0.3, which="both"); ax.set_xlabel("tau [s]", fontsize=8)
        ax.tick_params(labelsize=7)
    for ax in axs.ravel()[len(ks):]:
        ax.axis("off")
    axs[0, 0].legend(fontsize=7)
    fig.suptitle("Allan variance (relative). dashed = radiometer prediction")
    fig.tight_layout()
    fig.savefig(png, dpi=110)
    print(f"図: {png}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("paths", nargs="+", help="specrecv.py --out の .s45（同じ RUN の記録。分けて書いたなら順に並べる）")
    p.add_argument("--keys", default=None, help="窓（例 A0,A1）。既定 8 窓")
    p.add_argument("--chan-bin", type=int, default=25, help="ch ごとの値を何ダンプ束ねて持つか（25 ≒ 1 s。0 で ch ごとを出さない）")
    p.add_argument("--tp-bw", type=float, default=1800.0, help="TP の予言の雑音の帯域 [MHz]（BPF の幅）")
    p.add_argument("--no-plot", action="store_true")
    a = p.parse_args()
    analyze(a.paths, a.keys.split(",") if a.keys else None, a.chan_bin, a.tp_bw, not a.no_plot)


if __name__ == "__main__":
    sys.exit(main())
