#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — SG の CW を入れたまま長く記録した .s45 から、試験音の強さの時間の揺れを ADC・窓ごとに、ADC どうしの比で見る。

目的: B/D の枝の利得の揺れ（ta1・spur3768p3 で見えた）を、ノイズソースより高い S/N で追う。同じ CW が分配で 4 ADC に入るので、
SG の出力の揺れは ADC どうしの比で消え、残るのは分配の後（ケーブル・ADC・クロック）の揺れ。同じ ADC の 2 窓の比はデジタルだけ（≒ 一定のはず）。

    # 記録（入力は SG の CW を固定。ch の中心に: 3000.25 MHz は 256 MHz・8 MHz の窓（IF 3000）とも ch の中心）
    python3 specctl.py --host <board> "SEND ON" "START n=703125"         # 8 時間（40.96 ms）
    python3 specrecv.py --host <board> --out cwnight1.s45 --seconds 29100
    # 解析（どの PC でも）
    python3 s45cwlong.py cwnight1.s45                   # 表・cwnight1.cw.png・cwnight1.cw.json
    python3 s45cwlong.py cwnight1.s45 --sg 3000.25      # 試験音の ch を周波数で決める（既定は最初のダンプの最大の ch）

量（窓ごと、ダンプごと。値は PL の積分値から切り捨ての偏り 2/3·N_ACC を引いたもの）:
  tone   試験音の ch と両隣の和（SG と ch の中心のわずかなずれに強く）
  floor  試験音から 8〜64 ch 離れた ch の中央値（雑音の床 1 ch あたり）
  熱雑音だけの予言（相対の分散、1 ダンプ）: 2·(floor / (tone − 3·floor)) / N_ACC（CW と雑音の交差項）。m ダンプ束ねると 1/m
比: 同じ窓の番号で X/A（X = B・C・D）、同じ ADC で 窓1/窓0。TP も ADC ごとに 40 区切り（≒ 41.9 ms）に束ねて X/A。
出すもの: 全体の傾き（%/h、直線）・10 分平均の p-p（%）・アラン偏差（τ = 1 s・10 s・100 s・1000 s・1 h）と予言の比。
読み落とし・DROP で途切れていたら最長の連続区間だけを使う。
"""
import argparse
import json
import math
import sys

import numpy as np

import s45proto as P

KEYS = [f"{a}{w}" for a in "ABCD" for w in "01"]
BEAT = 1 / 256e6
TP_SEC = 512 * 512                 # 1 区切り（ビート）
TP_BIN = 40                        # TP を束ねる区切りの数
TAUS = (1.0, 10.0, 100.0, 1000.0, 3600.0)


def ch_if(if_mhz, ns):
    w = 512.0 / (1 << ns)
    b = P.IF_ORDER
    nu = np.where(b < P.NCH // 2, b, b - P.NCH) * (w / P.NCH)
    return if_mhz - nu


def oavar(x, m):
    c = np.cumsum(np.r_[0.0, np.asarray(x, np.float64)])
    y = (c[m:] - c[:-m]) / m
    d = y[m:] - y[:-m]
    return 0.5 * float(np.mean(d * d)) if len(d) else float("nan")


def read(paths, sg=None):
    w = {k: dict(k=[], t=[], tone=[], floor=[], sat=0, ch=None, meta=None) for k in KEYS}
    tpb = {a: {} for a in "ABCD"}
    t0tp = None
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
                    r = w[key]
                    x = d["data"].astype(np.float64) - (2.0 / 3.0) * d["nacc"]
                    if r["ch"] is None:
                        r["meta"] = dict(ns=d["ns"], nacc=d["nacc"], if_mhz=d["if_mhz"], shift=d["shift"])
                        if sg is not None:
                            r["ch"] = int(np.argmin(np.abs(ch_if(d["if_mhz"], d["ns"]) - sg)))
                        else:
                            e = int(P.NCH * 0.05)
                            r["ch"] = e + int(np.argmax(x[e:P.NCH - e]))
                        c = r["ch"]
                        off = np.r_[np.arange(c - 64, c - 7), np.arange(c + 8, c + 65)]
                        r["off"] = off[(off >= 0) & (off < P.NCH)]
                    elif (d["ns"], d["nacc"], d["shift"]) != (r["meta"]["ns"], r["meta"]["nacc"], r["meta"]["shift"]):
                        raise SystemExit(f"{key}: 記録の途中で設定が変わった（START をまたいだ記録は分けて解析する）")
                    c = r["ch"]
                    r["k"].append(d["k"]); r["t"].append(d["dump_t"])
                    r["tone"].append(x[c - 1:c + 2].sum()); r["floor"].append(float(np.median(x[r["off"]])))
                    r["sat"] += d["sat"] > 0
                elif rtype == P.T_TP:
                    d = P.decode(rtype, pl)
                    e = d["e"]
                    if t0tp is None:
                        t0tp = int(e["t_beat"][0])
                    b = (e["t_beat"].astype(np.int64) - t0tp) // (TP_SEC * TP_BIN)
                    acc = tpb["ABCD"[d["adc"]]]
                    for bi, s, n in zip(b.tolist(), e["sum"].tolist(), e["nfr"].tolist()):
                        v = acc.get(bi)
                        if v is None:
                            acc[bi] = [s, n, 1]
                        else:
                            v[0] += s; v[1] += n; v[2] += 1
    return w, tpb, nrec


def longest_run(k):
    if len(k) < 2:
        return 0, len(k)
    brk = np.flatnonzero(np.diff(k) != 1) + 1
    edges = np.r_[0, brk, len(k)]
    i = int(np.argmax(np.diff(edges)))
    return int(edges[i]), int(edges[i + 1])


def stats(t_s, y, tau0, pred0=None):
    """y: 相対値（平均 1）。傾き・10 分平均の p-p・アラン偏差"""
    r = {}
    if len(y) < 10:
        return r
    a, b = np.polyfit(t_s / 3600.0, y, 1)
    r["slope_pct_h"] = 100 * a
    nb = int(round(600 / tau0))
    if len(y) >= 2 * nb:
        yb = y[:len(y) // nb * nb].reshape(-1, nb).mean(1)
        r["pp10min_pct"] = 100 * float(yb.max() - yb.min())
    r["adev"] = {}
    for tau in TAUS:
        m = int(round(tau / tau0))
        if m >= 1 and 3 * m <= len(y):
            v = oavar(y, m)
            r["adev"][f"{tau:g}"] = math.sqrt(v)
            if pred0:
                r["adev"][f"{tau:g}_ratio"] = math.sqrt(v / (pred0 / m))
    return r


def analyze(paths, sg=None, out=None, plot=True):
    w, tpb, nrec = read(paths, sg)
    out = out or paths[0].rsplit(".s45", 1)[0]
    res = dict(files=paths, nrec=nrec, win={}, ratio={}, tp={})
    ser = {}
    print(f"記録 {nrec}")
    for key in KEYS:
        r = w[key]
        if not r["k"]:
            continue
        k = np.array(r["k"]); i0, i1 = longest_run(k)
        tone = np.array(r["tone"])[i0:i1]; fl = np.array(r["floor"])[i0:i1]
        t = (np.array(r["t"], np.int64)[i0:i1] - r["t"][i0]) * BEAT
        nacc = r["meta"]["nacc"]; tau0 = float(np.median(np.diff(t))) if len(t) > 1 else 0.04096
        ps = tone.mean() - 3 * fl.mean(); pn = fl.mean()
        pred0 = 2 * (pn / ps) / nacc if ps > 0 else None
        y = tone / tone.mean()
        st = stats(t, y, tau0, pred0)
        st.update(ch=r["ch"], n=int(i1 - i0), n_all=len(k), hours=float(t[-1] / 3600) if len(t) else 0, tau0=tau0,
                  snr_db=10 * math.log10(ps / pn) if ps > 0 and pn > 0 else None, pred0=pred0, sat_dumps=int(r["sat"]))
        res["win"][key] = st
        ser[key] = dict(k=k[i0:i1], t=t, y=y, tau0=tau0, pred0=pred0, tone=tone)
    # 比（k で揃える）
    def ratio(a, b):
        if a not in ser or b not in ser:
            return None
        ka, kb = ser[a]["k"], ser[b]["k"]
        common, ia, ib = np.intersect1d(ka, kb, return_indices=True)
        if len(common) < 10:
            return None
        q = ser[a]["tone"][ia] / ser[b]["tone"][ib]
        y = q / q.mean()
        p0 = (ser[a]["pred0"] or 0) + (ser[b]["pred0"] or 0)
        st = stats(ser[a]["t"][ia], y, ser[a]["tau0"], p0 or None)
        st["mean_db"] = 10 * math.log10(q.mean())
        st["tau0"] = ser[a]["tau0"]; st["pred0"] = p0 or None
        return st, ser[a]["t"][ia], y
    rser = {}
    for wn in "01":
        for x in "BCD":
            rr = ratio(f"{x}{wn}", f"A{wn}")
            if rr:
                res["ratio"][f"{x}{wn}/A{wn}"] = rr[0]; rser[f"{x}{wn}/A{wn}"] = rr[1:]
    for x in "ABCD":
        rr = ratio(f"{x}1", f"{x}0")
        if rr:
            res["ratio"][f"{x}1/{x}0"] = rr[0]; rser[f"{x}1/{x}0"] = rr[1:]
    # TP
    tser = {}
    for a in "ABCD":
        acc = tpb[a]
        if not acc:
            continue
        bi = np.array(sorted(acc)); v = np.array([acc[i][0] / acc[i][1] for i in bi]); full = np.array([acc[i][2] for i in bi]) == TP_BIN
        bi, v = bi[full], v[full]
        i0, i1 = longest_run(bi)
        tser[a] = (bi[i0:i1], v[i0:i1])
        tau0 = TP_SEC * TP_BIN * BEAT
        res["tp"][a] = stats((bi[i0:i1] - bi[i0]) * tau0, v[i0:i1] / v[i0:i1].mean(), tau0)
    for x in "BCD":
        if x in tser and "A" in tser:
            c, ia, ib = np.intersect1d(tser[x][0], tser["A"][0], return_indices=True)
            q = tser[x][1][ia] / tser["A"][1][ib]
            tau0 = TP_SEC * TP_BIN * BEAT
            st = stats((c - c[0]) * tau0, q / q.mean(), tau0)
            st["mean_db"] = 10 * math.log10(q.mean())
            res["tp"][f"{x}/A"] = st
            rser[f"TP {x}/A"] = ((c - c[0]) * tau0, q / q.mean())
    report(res)
    json.dump(res, open(out + ".cw.json", "w"), ensure_ascii=False, indent=1, default=float)
    print(f"数字: {out}.cw.json")
    if plot:
        _plot(out + ".cw.png", ser, rser, res)
    return res


def _fmt(st):
    ad = st.get("adev", {})
    a = "  ".join(f"{t}s {ad[t] * 100:.4f}%" + (f"（{ad[t + '_ratio']:.1f}×）" if t + "_ratio" in ad else "")
                  for t in [f"{x:g}" for x in TAUS] if t in ad)
    pp = f"・10 分 p-p {st['pp10min_pct']:.4f} %" if "pp10min_pct" in st else ""
    return f"傾き {st.get('slope_pct_h', float('nan')):+.4f} %/h{pp}  アラン偏差 {a}"


def report(res):
    print("\n== 試験音（窓ごと、自分の平均に対する相対。（）は熱雑音だけの予言との比）")
    for k, st in res["win"].items():
        print(f"{k}: ch {st['ch']}・{st['n']}/{st['n_all']} ダンプ（{st['hours']:.2f} h）・CW/床 {st['snr_db']:.1f} dB・飽和 {st['sat_dumps']}\n    {_fmt(st)}")
    print("\n== 比（X/A は分配の後の枝の差、X1/X0 は同じ ADC の 2 窓 = デジタルだけ）")
    for k, st in res["ratio"].items():
        print(f"{k}: 平均 {st['mean_db']:+.3f} dB  {_fmt(st)}")
    print("\n== TP（40 区切り ≒ 41.9 ms ずつ）")
    for k, st in res["tp"].items():
        print(f"{k}: " + (f"平均 {st['mean_db']:+.3f} dB  " if "mean_db" in st else "") + _fmt(st))


def _plot(png, ser, rser, res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(2, 3, figsize=(20, 10))

    span = max((s["t"][-1] for s in ser.values() if len(s["t"])), default=60.0)
    sec0 = max(60.0, span / 2000) if span > 3600 else max(span / 300, 0.04096)

    def binned(t, y, sec=None):
        sec = sec or sec0
        if len(t) < 2:
            return t, y
        b = ((t - t[0]) // sec).astype(np.int64)
        n = np.bincount(b); s = np.bincount(b, y)
        m = n > 0
        return (np.arange(len(n))[m] * sec + sec / 2) / 3600, s[m] / n[m]

    def dbs(y):
        return 10 * np.log10(np.maximum(y, 1e-30))

    ax = axs[0, 0]
    for k, s in ser.items():
        tt, yy = binned(s["t"], s["y"]); ax.plot(tt, dbs(yy), lw=0.8, label=k)
    ax.set_title(f"tone power per window ({sec0:g}-s mean, rel. to own mean)", fontsize=9)
    ax.set_xlabel("hours"); ax.set_ylabel("dB"); ax.grid(alpha=0.3); ax.legend(fontsize=7, ncol=2)
    for ax, sel, ttl in ((axs[0, 1], lambda k: not k.startswith("TP") and k[3] == "A" and k[0] != "A", "X/A (same window index)"),
                         (axs[0, 2], lambda k: k[0] in "ABCD" and k[1] == "1" and "/" in k and k[3] == k[0], "window1/window0 (same ADC, digital only)"),
                         (axs[1, 0], lambda k: k.startswith("TP"), "TP X/A (41.9 ms bins)")):
        for k, (t, y) in rser.items():
            if sel(k):
                tt, yy = binned(t, y); ax.plot(tt, dbs(yy), lw=0.8, label=k)
        ax.set_title(ttl + f"  ({sec0:g}-s mean)", fontsize=9); ax.set_xlabel("hours"); ax.set_ylabel("dB")
        ax.grid(alpha=0.3); ax.legend(fontsize=7, ncol=2)
    for ax, src, ttl in ((axs[1, 1], {k: (s["y"], s["tau0"], s["pred0"]) for k, s in ser.items()}, "Allan deviation: tone per window (dashed = thermal)"),
                         (axs[1, 2], None, "Allan deviation: ratios (dashed = thermal)")):
        items = src.items() if src is not None else [(k, (y, None, None)) for k, (t, y) in rser.items()]
        for j, (k, (y, tau0, p0)) in enumerate(items):
            if src is None:
                st = res["ratio"].get(k) or {}
                tau0 = TP_SEC * TP_BIN * BEAT if k.startswith("TP") else st.get("tau0", 0.04096)
                p0 = st.get("pred0")
            ms = np.unique(np.round(np.logspace(0, np.log10(max(len(y) // 3, 1)), 30)).astype(int))
            ad = [math.sqrt(oavar(y, m)) for m in ms]
            l, = ax.loglog(ms * tau0, ad, lw=0.8, label=k)
            if p0:
                ax.loglog(ms * tau0, np.sqrt(p0 / ms), "--", lw=0.5, color=l.get_color())
        ax.set_title(ttl, fontsize=9); ax.set_xlabel("tau [s]"); ax.set_ylabel("Allan deviation (relative)")
        ax.grid(alpha=0.3, which="both"); ax.legend(fontsize=6, ncol=2)
    fig.suptitle(png, fontsize=10)
    fig.tight_layout(); fig.savefig(png, dpi=90)
    print(f"図: {png}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+", help=".s45（続きのファイルは順に）")
    p.add_argument("--sg", type=float, default=None, help="試験音の周波数 [MHz]（既定: 最初のダンプの最大の ch）")
    p.add_argument("--out", default=None)
    p.add_argument("--no-plot", action="store_true")
    a = p.parse_args()
    analyze(a.files, a.sg, a.out, not a.no_plot)
    return 0


if __name__ == "__main__":
    sys.exit(main())
