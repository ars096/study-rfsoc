#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — Ta* のヌル試験（V-3）。チョッパーホイール較正と ON − OFF を実験室で真似て、分光計（スプリアス・利得の揺れ・
量子化）が Ta* に何を残すかを、観測と同じ式で見る。

    Ta*(ν) = T_amb · (ON − OFF) / (R − SKY)

  実験室での置き換え: SKY = OFF = ON = ノイズソース（ATT = a）、R（HOT）= 同じ源で ATT = a − hot_db（既定 5 dB、R − SKY ≒ Y 3.2）。
  **ON と OFF は同じ ATT のまま**（アッテネータを動かさない）→ 真の Ta* は 0。残るのは分光計と源の時間の揺らぎだけ。
  R は ATT を動かすので、R − SKY にはアッテネータの段の形（≒ 0.04 dB / 8 MHz、lin5）が乗る。分母なので **ヌルの 0 には効かない**
  （効くのは尺度だけ。線の入った試験ではないので、ここでは尺度を問わない）。

判定（予言）:
  T-1 Ta* の平均（全サイクル）が 0 と矛盾しない: ch の rms / 予言 σ_Ta/√N ≒ 1。σ_Ta = T_sys·√2 / √(N_ACC·n)（1 サイクルの ON − OFF）
  T-2 サイクルを重ねると rms が 1/√N で下がる（ベースラインの残りが無い）: N = 1, 2, 4, … の rms / 予言
  T-3 64 ch 束ねた Ta*（ベースライン）も予言どおり
  T-4 スプリアスの ch（SKY のスペクトルで s45spur.detect）: Ta* の平均は 0（一定の線は分子・分母の差で消える）、
      サイクルごとの揺れは隣の ch の √(1 + 2r) 倍（r = 線 / その ch の雑音、SKY で測る）
  T-5 ADC どうしの差 Ta*(X) − Ta*(Y): 源の揺らぎ（共通）が消え、分光計と分配の後の経路に固有のものだけが残る。予言 ≒ 1 本の σ の 1〜2 %
  入力のレベルを変えて（既定 3 段）同じことを繰り返す。r ∝ 1/P なので、スプリアスの ch の雑音の増えはレベルとともに減るはず

    # 配線は lin / allan と同じ。窓は先に specctl の SET で決めておく（例: spur3768 と同じ。ヘッダに GET を残す）
    python3 s45tastar.py --host <board> --att <ATT の IP> --levels 23,20,17 --cycles 30 --t-state 10 --out ta1
    python3 s45tastar.py --analyze ta1.ta.jsonl                     # 表と図（ta1.ta.png）・ta1.ta.json

  --levels は SKY の ATT [dB]。R は各レベルで ATT − --hot-db。並び: R, (OFF, ON) × r_every, R, … を cycles 回。
  1 状態 = t_state 秒のダンプ（acquire の前後に ≒ 2 s の手間）。既定（3 段 × 30 サイクル × 10 s）で ≒ 45 分。
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np

KEYS = [f"{a}{w}" for a in "ABCD" for w in "01"]
ADCS = "ABCD"
DBFS0 = 10 * math.log10(8192 ** 2 / 2)


# --------------------------------------------------------------------------- 測る
def measure(s, att, levels, cycles=30, t_state=10.0, r_every=5, hot_db=5.0, settle=1.0, out="ta", note=""):
    from s45lin import _abs_spec, _tp_abs
    path = out + ".ta.jsonl"
    if os.path.exists(path):
        raise SystemExit(f"{path} がある（別の out にする）")
    tint = float(s.get()["tint"])
    n = max(1, int(round(t_state / tint)))
    if n > s.keep:
        raise SystemExit(f"1 状態 {n} ダンプが手元に残せる数 keep={s.keep} を越える（t_state を短く）")
    for a in levels:
        if a - hot_db < 0:
            raise SystemExit(f"SKY の ATT {a} dB では R の ATT が負になる（hot_db {hot_db}）")
    head = dict(kind="head", t=time.time(), settings=s.get(), server=s.id(), att=getattr(att, "idn", None), levels=levels,
                cycles=cycles, t_state=t_state, n=n, r_every=r_every, hot_db=hot_db, settle=settle, note=note, tp_unit="x14")
    with open(path, "w") as f:
        f.write(json.dumps(head, ensure_ascii=False) + "\n")
    spec = {}
    seq = []
    for li, a in enumerate(levels):
        for c in range(cycles):
            if c % r_every == 0:
                seq.append((li, a, "R", c))
            seq.append((li, a, "OFF", c))
            seq.append((li, a, "ON", c))
    print(f"Ta* のヌル試験: {len(levels)} 段 × {cycles} サイクル、1 状態 {n} ダンプ（{n * tint:.1f} s）→ {path}")
    t0 = time.time()
    cur = None
    for i, (li, a, kind, c) in enumerate(seq):
        want = a - hot_db if kind == "R" else a
        if cur != want:
            att.set(want)
            cur = want
            time.sleep(settle)
        d = s.acquire(n)
        row = dict(kind="state", i=i, t=time.time(), level=li, att_sky=a, att=want, state=kind, cycle=c, win={}, tp={})
        for k in KEYS:
            m = d.meta(k)
            if not len(m):
                continue
            spec.setdefault(k, []).append(_abs_spec(d, k).astype(np.float32))
            if k + "_if" not in spec:
                spec[k + "_if"] = [d.freq(k)]
            row["win"][k] = dict(n=len(m), nacc=int(m["nacc"][-1]), sat=int(m["sat"].sum()),
                                 health=int(np.bitwise_or.reduce(m["health"])))
        for ad in ADCS:
            v, novr = _tp_abs(d, ad)
            if v is not None:
                row["tp"][ad] = dict(mean=float(v.mean()), ovr=novr)
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
        if i % 10 == 9 or i == len(seq) - 1:
            np.savez(out + ".ta.npz", **{k: np.array(v) for k, v in spec.items()})
        tpa = row["tp"].get("A", {}).get("mean")
        el = time.time() - t0
        print(f"  {i + 1:4d}/{len(seq)}  段 {li} ATT {want:5.1f}  {kind:3s} c{c:02d}  TP_A {10 * math.log10(tpa) - DBFS0 if tpa else float('nan'):+7.2f} dBFS"
              f"  振り切れ {sum(t['ovr'] for t in row['tp'].values())}  残り ≒ {el / (i + 1) * (len(seq) - i - 1) / 60:.0f} 分", flush=True)
    print(f"終わり: {path}（python3 s45tastar.py --analyze {path}）")
    return path


# --------------------------------------------------------------------------- 解析
def _central(n, frac=0.9):
    a0 = int(round(n * (1 - frac) / 2))
    u = np.zeros(n, bool); u[a0:n - a0] = True
    return u


def analyze(path, tamb=290.0, zth=8.0, plot=True):
    from s45spur import detect
    rows = [json.loads(l) for l in open(path)]
    head, st = rows[0], [r for r in rows[1:] if r.get("kind") == "state"]
    z = np.load(path.replace(".ta.jsonl", ".ta.npz"))
    n = head["n"]
    out = path.replace(".ta.jsonl", "")
    res = dict(path=path, tamb=tamb, levels=head["levels"], hot_db=head["hot_db"], n=n, res={})
    print(f"Ta* のヌル試験の解析: {path}・{len(st)} 状態・T_amb {tamb:g} K・1 状態 {n} ダンプ")
    plot_rows = {}
    keep_ta = {}
    for k in KEYS:
        if k not in z.files:
            continue
        S = z[k].astype(np.float64)
        f = z[k + "_if"][0]
        nch = S.shape[1]
        use = _central(nch)
        idx = [i for i, r in enumerate(st) if k in r["win"]]
        if len(idx) != len(S):
            raise SystemExit(f"{k}: 状態の数 {len(idx)} とスペクトルの数 {len(S)} が合わない")
        pos = {i: j for j, i in enumerate(idx)}
        nacc = st[idx[0]]["win"][k]["nacc"]
        res["res"][k] = {}
        plot_rows[k] = {}
        for li, a in enumerate(head["levels"]):
            sl = [i for i in idx if st[i]["level"] == li]
            cal = None; cal_list = []; ta = []; offs = []
            pend_r = None
            for i in sl:
                r = st[i]
                if r["state"] == "R":
                    pend_r = S[pos[i]]
                elif r["state"] == "OFF":
                    if pend_r is not None:                    # R の直後の OFF を SKY に: R − SKY
                        cal = pend_r - S[pos[i]]
                        cal_list.append(cal)
                        pend_r = None
                    off = S[pos[i]]
                elif r["state"] == "ON" and cal is not None:
                    with np.errstate(divide="ignore", invalid="ignore"):
                        ta.append(tamb * (S[pos[i]] - off) / cal)
                    offs.append(off)
            if not ta:
                continue
            ta = np.array(ta); offs = np.array(offs)
            calm = np.mean(cal_list, axis=0)
            with np.errstate(divide="ignore", invalid="ignore"):
                tsys = tamb * offs.mean(axis=0) / calm
            tsys_med = float(np.median(tsys[use]))
            sig1 = tsys * math.sqrt(2.0) / math.sqrt(nacc * n)            # 1 サイクルの ON − OFF の Ta* の σ（ch ごと）
            N = len(ta)
            mean = ta.mean(axis=0)
            # T-1: 平均の rms / 予言
            t1 = float(np.sqrt(np.mean((mean[use] / (sig1[use] / math.sqrt(N))) ** 2)))
            # 1 サイクルごとの揺れ / 予言（ch ごとの標準偏差の中央値）
            sd = ta.std(axis=0, ddof=1)
            t0r = float(np.median(sd[use] / sig1[use]))
            # T-2: N を増やしたときの rms
            t2 = []
            m = 1
            while m <= N:
                mm = ta[:m].mean(axis=0)
                t2.append(dict(N=m, rms_K=float(np.sqrt(np.mean(mm[use] ** 2))),
                               ratio=float(np.sqrt(np.mean((mm[use] / (sig1[use] / math.sqrt(m))) ** 2)))))
                m *= 2
            # T-3: 64 ch 束ねた平均
            nb = 64
            u_idx = np.flatnonzero(use)
            u_idx = u_idx[:len(u_idx) // nb * nb].reshape(-1, nb)
            bm = mean[u_idx].mean(axis=1)
            bs = np.sqrt((sig1[u_idx] ** 2).sum(axis=1)) / nb / math.sqrt(N)
            t3 = float(np.sqrt(np.mean((bm / bs) ** 2)))
            # T-4: スプリアス（SKY = OFF の平均で探す）
            sky = offs.mean(axis=0)
            pks, b, zz = detect(sky, zth, use)
            sp = []
            for pk in pks:
                r_ = float(sky[pk] / b[pk] - 1)
                nb_ = np.r_[max(pk - 20, 0):max(pk - 3, 0), min(pk + 4, nch):min(pk + 21, nch)]
                # 揺れの比は K のまま隣の ch と比べる（sig1 は Tsys ∝ OFF を使うので、線の ch では (1 + r) 倍に膨らむ。
                # それで割ると √(1+2r)/(1+r) に見える。ta1 の初版で 0.6〜0.9 倍に出た）
                ref_sd = float(np.median(sd[nb_])) if len(nb_) else float("nan")
                ref_sig = float(np.median(sig1[nb_])) if len(nb_) else float("nan")
                sp.append(dict(ch=int(pk), if_mhz=float(f[pk]), r=r_, ta_mean_K=float(mean[pk]),
                               ta_mean_z=float(mean[pk] / (ref_sig * math.sqrt(1 + 2 * max(r_, 0)) / math.sqrt(N))),
                               noise_ratio=float(sd[pk] / ref_sd), noise_pred=math.sqrt(1 + 2 * max(r_, 0))))
            sp.sort(key=lambda d: -d["r"])
            tp = [st[i]["tp"] for i in sl]
            ovr = {"R": sum(sum(t[ad]["ovr"] for ad in t) for t, i in zip(tp, sl) if st[i]["state"] == "R"),
                   "SKY": sum(sum(t[ad]["ovr"] for ad in t) for t, i in zip(tp, sl) if st[i]["state"] != "R")}
            adc = k[0]
            sky_db = [10 * math.log10(t[adc]["mean"]) - DBFS0 for t, i in zip(tp, sl) if st[i]["state"] == "OFF" and adc in t]
            r_db = [10 * math.log10(t[adc]["mean"]) - DBFS0 for t, i in zip(tp, sl) if st[i]["state"] == "R" and adc in t]
            d = dict(att_sky=a, sky_dbfs=float(np.mean(sky_db)) if sky_db else None, r_dbfs=float(np.mean(r_db)) if r_db else None,
                     y_db=float(10 * np.log10(np.median((calm + sky)[use] / sky[use]))),
                     tsys_K=tsys_med, cycles=N, sigma1_K=float(np.median(sig1[use])),
                     T1_mean_rms_ratio=t1, T0_cycle_sd_ratio=t0r, T2=t2, T3_bin64_ratio=t3, spurs=sp, ovr=ovr)
            res["res"][k][str(li)] = d
            keep_ta.setdefault((k[1], li), {})[k[0]] = (ta, sig1, use, tsys_med)
            plot_rows[k][li] = dict(f=f, mean=mean, sig=sig1 / math.sqrt(N), t2=t2, sky_dbfs=d["sky_dbfs"])
            print(f"  {k} 段 {li}（SKY {d['sky_dbfs']:+.1f} dBFS・R {d['r_dbfs']:+.1f}・Y {d['y_db']:.2f} dB・Tsys {tsys_med:.0f} K・{N} サイクル）: "
                  f"1 サイクルの揺れ {t0r:.2f}・T-1 平均の rms {t1:.2f}・T-2 N={t2[-1]['N']} で {t2[-1]['ratio']:.2f}・T-3 64 ch {t3:.2f}"
                  f"・振り切れ R {ovr['R']} / SKY {ovr['SKY']}（予言はどれも 1）")
            for q in sp[:4]:
                print(f"      線 {q['if_mhz']:10.4f} MHz  r {q['r']:.3g}  Ta* の平均 {q['ta_mean_K']:+.4f} K（{q['ta_mean_z']:+.1f}σ）"
                      f"  揺れ {q['noise_ratio']:.2f} 倍（予言 √(1+2r) = {q['noise_pred']:.2f}）")
    # T-5: ADC どうしの差。4 ADC は同じノイズソースを分けて見ているので、源の揺らぎ（ラジオメータ雑音も、源・BPF・ATT の形の揺れも）は
    # 4 本に同じく乗る。差 Ta*(X) − Ta*(Y) にはそれが消え、**分光計と分配の後の経路（ケーブル・口・ADC）に固有のもの**だけが残る。
    # 予言: ADC 自身の雑音（無入力で ≒ −60 dBFS）は入力より ≒ 43 dB 下なので、差の雑音は 1 本の σ の ≒ 1〜2 %
    res["cross"] = {}
    print("  T-5 ADC どうしの差（同じ窓・同じ段）: 平均の rms / 1 本の予言 σ/√N、64 ch 束ね、ベースラインの傾き")
    for (w, li), byadc in sorted(keep_ta.items()):
        ads = sorted(byadc)
        for i1 in range(len(ads)):
            for i2 in range(i1 + 1, len(ads)):
                x, y = ads[i1], ads[i2]
                tx, sx, use, tsx = byadc[x]; ty, sy, _, _ = byadc[y]
                Nn = min(len(tx), len(ty))
                dm = (tx[:Nn] - ty[:Nn]).mean(axis=0)
                sg = sx / math.sqrt(Nn)
                r_ch = float(np.sqrt(np.mean((dm[use] / sg[use]) ** 2)))
                ui = np.flatnonzero(use); ui = ui[:len(ui) // 64 * 64].reshape(-1, 64)
                bm = dm[ui].mean(axis=1)
                r_b = float(np.sqrt(np.mean(bm ** 2)))
                xs = np.linspace(-1, 1, len(bm))
                tilt = float(np.polyfit(xs, bm, 1)[0])                    # 窓の端から端で ±tilt K
                key = f"{x}{w}-{y}{w}"
                res["cross"].setdefault(key, {})[str(li)] = dict(rms_ratio_ch=r_ch, rms_bin64_K=r_b, rms_bin64_rel=r_b / tsx,
                                                                tilt_K=tilt, tilt_rel=tilt / tsx)
                print(f"      {key} 段 {li}: ch {r_ch:.3f}・64 ch 束ね rms {r_b * 1e3:.2f} mK（Tsys の {r_b / tsx:.1e}）・傾き {tilt * 1e3:+.2f} mK")
    json.dump(res, open(out + ".ta.json", "w"), ensure_ascii=False, indent=1)
    print(f"まとめ: {out}.ta.json")
    if plot:
        _plot(out + ".ta.png", plot_rows)
    return res


def _plot(png, rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ks = list(rows)
    fig, axs = plt.subplots(len(ks), 2, figsize=(15, 2.6 * len(ks)), squeeze=False, gridspec_kw=dict(width_ratios=[3, 1]))
    for i, k in enumerate(ks):
        ax, ax2 = axs[i]
        for j, (li, d) in enumerate(sorted(rows[k].items())):
            nb = 16
            n = len(d["mean"]) // nb * nb
            fb = d["f"][:n].reshape(-1, nb).mean(axis=1)
            mb = d["mean"][:n].reshape(-1, nb).mean(axis=1)
            off = j * 6 * np.median(d["sig"]) / math.sqrt(nb)
            ax.plot(fb, mb + off, lw=0.6, label=f"SKY {d['sky_dbfs']:+.1f} dBFS (+{off:.3g} K)")
            n2 = [t["N"] for t in d["t2"]]; r2 = [t["rms_K"] for t in d["t2"]]
            ax2.loglog(n2, r2, "o-", ms=3, label=f"{d['sky_dbfs']:+.1f}")
            ax2.loglog(n2, [r2[0] / math.sqrt(x) for x in n2], ":", color="gray", lw=0.8)
        ax.set_title(f"{k}: mean Ta* (16 ch bins, offset per level)", fontsize=9); ax.legend(fontsize=6); ax.grid(alpha=0.3)
        ax2.set_title(f"{k}: rms of mean Ta* vs cycles (dotted 1/sqrt N)", fontsize=9); ax2.grid(alpha=0.3, which="both")
        ax2.set_xlabel("cycles", fontsize=8); ax2.set_ylabel("K", fontsize=8)
    fig.tight_layout(); fig.savefig(png, dpi=90)
    print(f"図: {png}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--att", default=None, help="アッテネータ HOST[:PORT]（環境変数 RFSOC_ATT でも）。manual で手で回す")
    p.add_argument("--levels", default="23,20,17", help="SKY の ATT [dB]（カンマ区切り）")
    p.add_argument("--cycles", type=int, default=30)
    p.add_argument("--t-state", type=float, default=10.0)
    p.add_argument("--r-every", type=int, default=5)
    p.add_argument("--hot-db", type=float, default=5.0)
    p.add_argument("--settle", type=float, default=1.0)
    p.add_argument("--tamb", type=float, default=290.0)
    p.add_argument("--out", default="ta")
    p.add_argument("--note", default="")
    p.add_argument("--analyze", default=None, help="記録（*.ta.jsonl）を解析するだけ")
    a = p.parse_args()
    if a.analyze:
        analyze(a.analyze, tamb=a.tamb)
        return
    from s45client import S45
    from instr import Atten, ManualAtten
    at = ManualAtten() if a.att == "manual" else Atten(a.att)
    s = S45(a.host)
    try:
        path = measure(s, at, [float(x) for x in a.levels.split(",")], cycles=a.cycles, t_state=a.t_state, r_every=a.r_every,
                       hot_db=a.hot_db, settle=a.settle, out=a.out, note=a.note)
    finally:
        s.close(); at.close()
    analyze(path, tamb=a.tamb)


if __name__ == "__main__":
    sys.exit(main())
