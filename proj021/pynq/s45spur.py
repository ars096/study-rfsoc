#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — 分光計のスプリアスの評価（V-0〜V-2）。どの線が・どれだけの強さで・入力のレベルにどう依るか・時間で揺れるか。

量（窓ごと、ch は abs の LSB²）:
  base   その ch の雑音の床。33 ch の移動中央値（線は 1〜数 ch なので外れる）
  r      線の ch の (S − base) / base。**Ta* への効きはこれ**: 線が一定なら、その ch の Ta* が 1/(1+r) 倍に縮む（尺度の誤差）。
         線が δ（相対）揺れると、ON − OFF に r·δ·Tsys のベースラインが残る
  E      線の超過の電力 Σ(S − base)（山の ±2 ch）。入力のレベルに依らなければ加算的（ADC・クロックの線）、比例すれば
         インターリーブの像、2 乗以上なら非線形
  z      (S − base) / (base · σ_rel)。σ_rel は窓の ch の相対の揺れ（中央値の絶対偏差から）

使い方:

    # V-0・V-1: リニアリティの記録（s45lin.measure の .lin.jsonl と .spec.npz）から、レベル対スプリアス
    python3 s45spur.py lin runs/lin5.lin.jsonl                     # 表・runs/lin5.spur.json・runs/lin5.spur.png
    python3 s45spur.py lin runs/lin5.lin.jsonl --ref-dbfs -15.9 --tsys 139

    # V-0・V-2: specrecv の .s45（入力は固定）から、線の一覧と時間の揺れ
    python3 s45spur.py rec term.s45 --bin 25                       # 25 ダンプ ≒ 1 s ずつ束ねて

lin: 床の段（ATT ≧ --floor-att）は終端に近い。床の段が何回もあれば、線の E の段ごとのばらつき（分単位の安定度）も出す。
     ref の r は E = a + b·P（P は TP の電力、線形）と base = c0 + c1·P を段に合わせて、--ref-dbfs で評価したもの。
rec: 束ねた区間ごとの E の相対の揺れ（rstd）と、同じ幅の線の無い ch の組で測ったラジオメータの揺れとの比（ratio）。
     ratio ≫ 1 なら線そのものが揺れていて、ポジションスイッチで消えきらない。
"""
import argparse
import json
import math
import sys

import numpy as np

KEYS = [f"{a}{w}" for a in "ABCD" for w in "01"]
DBFS0 = 10 * math.log10(8192 ** 2 / 2)
WMED = 33
HALF = 2            # 山の ±2 ch を線の超過に数える
QMIN = 3.0          # rec: 1 フレームの ch の電力がこれ（SHIFT 後の LSB²）未満の窓は線を探さない
EDGE = 0.05         # 窓の両端 5 % は使わない（窓の肩）


def baseline(s, w=WMED, gap=HALF):
    """ch ごとの床: 両側 w//2 ch のうち、自分と ±gap を除いた ch の中央値。
    自分を含めた移動中央値は、雑音が小さく（長い積分）床が単調に傾いていると「自分の値」を返してしまい
    （窓の中が単調なら中央値 = 真ん中）、r が 0 になる（allan2 の 1 時間で σ が 0 に見えた）。両側を対称に取れば、
    傾きの 1 次は打ち消され、線そのもの（±gap）も床に入らない"""
    from numpy.lib.stride_tricks import sliding_window_view
    h = w // 2
    p = np.pad(s, h, mode="edge")
    win = sliding_window_view(p, w)
    keep = np.ones(w, bool); keep[h - gap:h + gap + 1] = False
    return np.median(win[:, keep], axis=-1)


def rel_sigma(r, use):
    x = r[use]
    return float(1.4826 * np.median(np.abs(x - np.median(x))))


def detect(S, zth, use):
    """S: 1 本のスペクトル。戻り値 (山の ch の並び, base, z)"""
    b = baseline(S)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(b > 0, S / b - 1.0, 0.0)
    sig = max(rel_sigma(r, use), 1e-12)
    z = r / sig
    cand = np.flatnonzero(use & (z > zth))
    peaks = []
    for c in cand:                                   # 隣り合う ch は 1 本にまとめ、山（z が最大）を代表に
        if peaks and c - peaks[-1][-1] <= HALF:
            peaks[-1].append(c)
        else:
            peaks.append([c])
    return [int(g[int(np.argmax(z[g]))]) for g in peaks], b, z


def excess(S, b, pk):
    sl = slice(max(pk - HALF, 0), pk + HALF + 1)
    return float(np.sum(S[sl] - b[sl]))


def merge_peaks(lists, tol=HALF):
    allp = sorted(set(p for l in lists for p in l))
    out = []
    for p in allp:
        if out and p - out[-1] <= tol:
            continue
        out.append(p)
    return out


# --------------------------------------------------------------------------- lin
KIND_EN = {"加算的": "additive", "比例": "proportional", "非線形": "nonlinear", "減る": "decreasing", "床だけ": "floor only"}


def spur_e(S, b, sig, pk):
    """線の超過 E（LSB²）と、その 1σ。山の ch と、±HALF のうち z > 3 の ch を足す（雑音だけの ch を足さない）"""
    idx = [pk] + [c for c in range(pk - HALF, pk + HALF + 1) if c != pk and 0 <= c < len(S) and b[c] > 0 and (S[c] / b[c] - 1) / sig > 3]
    e = float(sum(S[c] - b[c] for c in idx))
    se = float(sig * np.sqrt(sum(b[c] ** 2 for c in idx)))
    return e, se


def run_lin(path, floor_att=90.0, zth=8.0, ref_dbfs=-15.9, tsys=139.0, plot=True):
    rows = [json.loads(l) for l in open(path)]
    head, steps = rows[0], [r for r in rows[1:] if r.get("kind") == "step"]
    z = np.load(path.replace(".lin.jsonl", ".spec.npz"))
    tp_unit = 1.0 if head.get("tp_unit") == "x14" else 16.0
    tint = float(head.get("settings", {}).get("tint", 0.04096)); ndump = int(head.get("n", 25))
    att = np.array([s["att"] for s in steps])
    floor = att >= floor_att
    res = {}
    print(f"スプリアス（lin）: {path}・{len(steps)} 段（床 {int(floor.sum())} 段）・判定 z > {zth:g}・ref {ref_dbfs:+.1f} dBFS・Tsys {tsys:g} K")
    for key in KEYS:
        if key not in z.files:
            continue
        S = z[key]; f = z[key + "_if"][0]
        n = S.shape[1]
        use = np.zeros(n, bool); e = int(n * EDGE); use[e:n - e] = True
        dnu = abs(f[1] - f[0]) * 1e6
        th1 = 1.0 / math.sqrt(dnu * tint * ndump)                     # 1 段の ch の相対の揺れ（ラジオメータ）
        adc = key[0]
        tp = np.array([s["tp"][adc]["mean"] * tp_unit for s in steps])
        pdb = 10 * np.log10(tp) - DBFS0
        B, SIG, RAD = [], [], []
        for i in range(len(steps)):
            b = baseline(S[i])
            r = np.where(b > 0, S[i] / b - 1, 0)
            sg = max(rel_sigma(r, use), 1e-12)
            B.append(b); SIG.append(sg); RAD.append(0.67 < sg / th1 < 1.5)
        RAD = np.array(RAD)
        # 線を探す: ラジオメータの式どおりに揺れている段（量子化に埋もれた段は外す）と、床の平均（同じ条件のとき）
        lists = [detect(S[i], zth, use)[0] for i in np.flatnonzero(RAD)]
        if floor.sum() > 1:
            Sf = S[floor].mean(axis=0)
            bf = baseline(Sf); sf = rel_sigma(np.where(bf > 0, Sf / bf - 1, 0), use)
            if 0.67 < sf / (th1 / math.sqrt(floor.sum())) < 1.5:
                lists.append(detect(Sf, zth, use)[0])
        pks = merge_peaks(lists)
        spurs = []
        for pk in pks:
            E = np.zeros(len(steps)); sE = np.zeros(len(steps))
            for i in range(len(steps)):
                E[i], sE[i] = spur_e(S[i], B[i], SIG[i], pk)
            det = RAD & (E > 5 * sE)
            r = np.array([E[i] / B[i][pk] for i in range(len(steps))])
            nf = ~floor
            sel = nf & det & (E > 0)
            slope = float(np.polyfit(pdb[sel] / 10, np.log10(E[sel]), 1)[0]) if sel.sum() >= 3 and np.ptp(pdb[sel]) > 6 else None
            if slope is None:
                cls = "床だけ" if not sel.any() else "加算的"
            else:
                cls = "減る" if slope < -0.4 else "加算的" if slope < 0.4 else "比例" if slope < 1.5 else "非線形"
            # ref での r: その ch の床（base）は P に比例（床の段を除いて当てはめ）。線の E は「検出できた一番高いレベルの値のまま」とみなす
            # （加算的・減るなら安全側）。比例・非線形なら検出できた点の傾きで延ばす
            Pl = 10 ** (pdb / 10)
            bk = np.array([B[i][pk] for i in range(len(steps))])
            A = np.vstack([np.ones(nf.sum()), Pl[nf]]).T
            (c0, c1), *_ = np.linalg.lstsq(A, bk[nf], rcond=None)
            base_ref = c0 + c1 * 10 ** (ref_dbfs / 10)
            r_ref = None
            if sel.any():
                hi = int(np.flatnonzero(sel)[np.argmax(pdb[sel])])
                e_ref = E[hi] if (slope is None or slope < 0.4) else E[hi] * 10 ** (slope * (ref_dbfs - pdb[hi]) / 10)
                r_ref = float(e_ref / base_ref)
            # 検出の限界: ref に一番近い段の 5σ
            near = int(np.argmin(np.where(nf & RAD, np.abs(pdb - ref_dbfs), 1e9)))
            Ef = E[floor]
            spurs.append(dict(ch=pk, if_mhz=float(f[pk]), z_max=float(np.max(np.where(RAD, E / np.maximum(sE, 1e-30), 0))),
                              slope=slope, kind=cls,
                              E_floor_mean=float(Ef.mean()) if len(Ef) else None,
                              E_floor_rstd=float(Ef.std() / abs(Ef.mean())) if len(Ef) > 1 and Ef.mean() else None,
                              E_floor_minmax=[float(Ef.min()), float(Ef.max())] if len(Ef) else None,
                              r_ref=r_ref, T_ref_K=None if r_ref is None else r_ref * tsys,
                              r_limit_near_ref=float(5 * SIG[near]), dbfs_near_ref=float(pdb[near]),
                              steps=dict(dbfs=pdb.tolist(), E=E.tolist(), sE=sE.tolist(), r=r.tolist(), det=det.tolist())))
        spurs.sort(key=lambda d: -d["z_max"])
        res[key] = dict(dnu_khz=dnu / 1e3, sigma_theory=th1, sigma_meas=[float(x) for x in SIG], radiometric=RAD.tolist(), spurs=spurs)
        print(f"  {key}（Δν {dnu / 1e3:.2f} kHz）: 線 {len(spurs)} 本・ラジオメータの式どおりの段 {int(RAD.sum())}/{len(steps)}"
              f"（1 段の ch の揺れ 予言 {th1:.4f}）")
        for d in spurs[:10]:
            ef = "-" if d["E_floor_mean"] is None else f"{d['E_floor_mean']:.3g}（{d['E_floor_minmax'][0]:.2g}〜{d['E_floor_minmax'][1]:.2g}）"
            rr = "検出できず" if d["r_ref"] is None else f"{d['r_ref']:.2e}（{d['T_ref_K']:.3g} K 相当）"
            print(f"      {d['if_mhz']:10.4f} MHz  z {d['z_max']:7.0f}  {d['kind']:4s} 傾き {'-' if d['slope'] is None else '%+.2f' % d['slope']:>5}  "
                  f"床の E {ef} LSB²・ref で r {rr}・{d['dbfs_near_ref']:.0f} dBFS の検出限界 r < {d['r_limit_near_ref']:.1e}")
    out = path.replace(".lin.jsonl", "")
    json.dump(dict(path=path, mode="lin", floor_att=floor_att, zth=zth, ref_dbfs=ref_dbfs, tsys=tsys, res=res),
              open(out + ".spur.json", "w"), ensure_ascii=False, indent=1)
    print(f"まとめ: {out}.spur.json")
    if plot:
        _plot_lin(out + ".spur.png", z, steps, floor, res, ref_dbfs)
    return res


def _plot_lin(png, z, steps, floor, res, ref_dbfs):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(4, 4, figsize=(18, 13))
    top = int(np.argmax([s["tp"]["A"]["mean"] for s in steps]))
    for ia, a in enumerate("ABCD"):
        for w in "01":
            key = a + w
            if key not in res:
                continue
            S = z[key]; f = z[key + "_if"][0]
            ax = axs[ia, 2 * int(w)]
            for lab, spec, c in (("floor", S[floor].mean(axis=0) if floor.any() else None, "C3"), ("top level", S[top], "C0")):
                if spec is None:
                    continue
                b = baseline(spec)
                ax.plot(f, spec / b - 1, lw=0.6, color=c, label=lab)
            ax.set_yscale("symlog", linthresh=0.01)
            ax.set_title(f"{key}: (S - base)/base", fontsize=9); ax.legend(fontsize=7); ax.grid(alpha=0.3)
            ax = axs[ia, 2 * int(w) + 1]
            for j, d in enumerate(res[key]["spurs"][:6]):
                st = d["steps"]
                rr = np.array(st["r"]); x = np.array(st["dbfs"]); dt = np.array(st["det"])
                c = f"C{j}"
                ax.semilogy(x[dt], np.maximum(rr[dt], 1e-6), "o", ms=4, color=c, label=f"{d['if_mhz']:.3f} ({KIND_EN[d['kind']]})")
                ax.semilogy(x[~dt], np.maximum(rr[~dt], 1e-6), "x", ms=3, color=c, alpha=0.4)
            sm = np.array(res[key]["sigma_meas"]); x = np.array(res[key]["spurs"][0]["steps"]["dbfs"]) if res[key]["spurs"] else None
            if x is not None:
                o = np.argsort(x); ax.semilogy(x[o], 5 * sm[o], "k:", lw=0.8, label="5 sigma (1 step)")
            ax.axvline(ref_dbfs, color="k", lw=0.6, ls="--")
            ax.set_xlabel("TP [dBFS]", fontsize=8)
            ax.set_title(f"{key}: r of spur ch (o detected, x not)", fontsize=9); ax.legend(fontsize=6); ax.grid(alpha=0.3, which="both")
    fig.tight_layout(); fig.savefig(png, dpi=100)
    print(f"図: {png}")


# --------------------------------------------------------------------------- rec
def _read_rec(paths, keys):
    import s45proto as P
    w = {k: dict(sum=None, n=0, meta=None) for k in keys}

    def it():
        for path in paths:
            with open(path, "rb") as fh:
                while True:
                    h = fh.read(P.HDR.size)
                    if len(h) < P.HDR.size:
                        break
                    rtype, plen, crc, seq = P.parse_header(h)
                    pl = fh.read(plen)
                    if len(pl) < plen:
                        break
                    yield rtype, pl

    def absval(d):
        sc = 4.0 ** d["shift"] * 4.0 ** (4 - d["g"]) / 2.0 ** 31
        return (d["data"].astype(np.float64) / d["nacc"] - 2.0 / 3.0) * sc
    return it, absval


def run_rec(paths, keys=None, zth=8.0, bin_=25, tsys=139.0, plot=True, edge=EDGE):
    import s45proto as P
    keys = keys or KEYS
    it, absval = _read_rec(paths, keys)
    acc = {k: None for k in keys}; cnt = {k: 0 for k in keys}; meta = {}
    tps = {a: [] for a in "ABCD"}
    for rtype, pl in it():                                     # 1 回目: 平均のスペクトル
        if rtype == P.T_SPEC:
            d = P.decode(rtype, pl)
            k = f"{'ABCD'[d['adc']]}{d['win']}"
            if k not in acc:
                continue
            v = absval(d)
            acc[k] = v if acc[k] is None else acc[k] + v
            cnt[k] += 1
            meta[k] = dict(ns=d["ns"], if_mhz=d["if_mhz"], nacc=d["nacc"], sc=4.0 ** d["shift"] * 4.0 ** (4 - d["g"]) / 2.0 ** 31)
        elif rtype == P.T_TP:
            d = P.decode(rtype, pl)
            e = d["e"]
            tps["ABCD"[d["adc"]]].append(e["sum"].astype(np.float64) / (e["nfr"] * 8192.0))
    res = {}
    plan = {}
    for k in keys:
        if not cnt[k]:
            continue
        S = acc[k] / cnt[k]
        n = len(S); use = np.zeros(n, bool); e = int(n * edge); use[e:n - e] = True
        pks, b, zz = detect(S, zth, use)
        # 量子化: 1 フレームの ch の電力が SHIFT の後の LSB² で何個ぶんか（偏りを引いた後）。QMIN 未満なら（無入力の狭い窓など）
        # 値が LSB に近く、χ² でなく量子化の形が見える → 線を探さない。長い平均では床の細かい形（さざ波）が
        # ラジオメータの予言 1/√(N_ACC·ダンプ数) を越えるので、z はその窓の実測の揺れ（sg）で測る
        th = 1.0 / math.sqrt(meta[k]["nacc"] * cnt[k])
        sg = rel_sigma(np.where(b > 0, S / b - 1, 0), use)
        q = float(np.median(S[use]) / meta[k]["sc"])
        rad = q >= QMIN
        if not rad:
            pks = []
        wmhz = 512.0 / (1 << meta[k]["ns"])
        bb = P.IF_ORDER
        f = meta[k]["if_mhz"] - np.where(bb < n // 2, bb, bb - n) * (wmhz / n)
        # 線の無い ch の組（同じ幅 2·HALF+1）を対照に 32 組
        bad = np.zeros(n, bool)
        for p in pks:
            bad[max(p - 8, 0):p + 9] = True
        free = np.flatnonzero(use & ~bad)
        ctrl = free[np.linspace(0, len(free) - 1, 32).astype(int)] if len(free) > 64 else np.array([], int)
        plan[k] = dict(S=S, b=b, z=zz, pks=pks, f=f, ctrl=ctrl, series=[], cur=None, ncur=0, rad=rad, sg=sg, th=th, q=q)
    for rtype, pl in it():                                     # 2 回目: 束ねた区間ごとの E
        if rtype != P.T_SPEC:
            continue
        d = P.decode(rtype, pl)
        k = f"{'ABCD'[d['adc']]}{d['win']}"
        if k not in plan:
            continue
        p = plan[k]
        v = absval(d)
        p["cur"] = v if p["cur"] is None else p["cur"] + v
        p["ncur"] += 1
        if p["ncur"] == bin_:
            m = p["cur"] / bin_
            row = [excess(m, p["b"], pk) for pk in p["pks"]] + [excess(m, p["b"], c) for c in p["ctrl"]]
            p["series"].append(row)
            p["cur"] = None; p["ncur"] = 0
    print(f"スプリアス（rec）: {', '.join(paths)}・{bin_} ダンプずつ束ねて・判定 z > {zth:g}")
    for a in "ABCD":
        if tps[a]:
            v = np.concatenate(tps[a])
            print(f"  TP {a}: {10 * np.log10(v.mean()) - DBFS0:+.2f} dBFS")
    for k, p in plan.items():
        ser = np.array(p["series"]) if p["series"] else np.zeros((0, len(p["pks"]) + len(p["ctrl"])))
        npk = len(p["pks"])
        noise_sd = float(np.median(ser[:, npk:].std(axis=0))) if ser.shape[0] > 2 and ser.shape[1] > npk else None
        spurs = []
        def rebin_var(x, m):
            k = len(x) // m
            if k < 8:
                return None
            y = x[:k * m].reshape(k, m, *x.shape[1:]).mean(axis=1)
            return 0.5 * np.mean(np.diff(y, axis=0) ** 2, axis=0)            # アラン分散（重ならない）
        MS = [m for m in (1, 10, 100) if ser.shape[0] // m >= 8]
        ctrl_av = {m: float(np.median(rebin_var(ser[:, npk:], m))) for m in MS} if ser.shape[1] > npk else {}
        for j, pk in enumerate(p["pks"]):
            s = ser[:, j] if ser.shape[0] else np.array([])
            stab = {str(m * bin_): (float(rebin_var(s, m)) / ctrl_av[m] if ctrl_av.get(m) else None) for m in MS}
            E = float(p["S"][max(pk - HALF, 0):pk + HALF + 1].sum() - p["b"][max(pk - HALF, 0):pk + HALF + 1].sum())
            r = float(p["S"][pk] / p["b"][pk] - 1)
            sd = float(s.std()) if len(s) > 2 else None
            spurs.append(dict(ch=pk, if_mhz=float(p["f"][pk]), z=float(p["z"][pk]), E=E, r=r, T_K=r * tsys,
                              E_rstd=sd / abs(E) if sd is not None and E else None,
                              ratio=(sd / noise_sd) ** 2 if sd is not None and noise_sd else None, allan_ratio=stab))
        spurs.sort(key=lambda d: -d["r"])
        res[k] = dict(n_bins=int(ser.shape[0]), noise_sd=noise_sd, q_lsb2=p["q"], usable=bool(p["rad"]), sigma_meas=p["sg"], sigma_theory=p["th"], spurs=spurs)
        print(f"  {k}: 線 {len(spurs)} 本（{ser.shape[0]} 区間）・ch の電力 {p['q']:.2g} LSB²/フレーム・ch の相対の揺れ {p['sg']:.2e}（ラジオメータ {p['th']:.2e}）"
              + ("" if p["rad"] else f" → {QMIN:g} LSB² 未満（量子化に埋もれている）ので線を探さない"))
        for d in spurs[:8]:
            print(f"      {d['if_mhz']:10.4f} MHz  z {d['z']:8.1f}  r {d['r']:9.3g}（{d['T_K']:.3g} K 相当、Tsys {tsys:g} K のとき）  "
                  f"E {d['E']:.3g} LSB²  区間ごとの揺れ {'-' if d['E_rstd'] is None else '%.1f %%' % (100 * d['E_rstd'])}"
                  f"（雑音の {'-' if d['ratio'] is None else '%.3g' % d['ratio']} 倍の分散）・アラン分散 / 線の無い ch: "
                  + " ".join(f"{int(k) * 0.04096:.0f}s {v:.3g}" for k, v in d["allan_ratio"].items() if v is not None))
    out = paths[0].rsplit(".s45", 1)[0]
    json.dump(dict(paths=paths, mode="rec", zth=zth, bin=bin_, tsys=tsys, res=res), open(out + ".spur.json", "w"), ensure_ascii=False, indent=1)
    print(f"まとめ: {out}.spur.json")
    if plot:
        _plot_rec(out + ".spur.png", plan, res)
    return res


def _plot_rec(png, plan, res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ks = list(plan)
    fig, axs = plt.subplots(len(ks), 2, figsize=(15, 2.4 * len(ks)), squeeze=False)
    for i, k in enumerate(ks):
        p = plan[k]
        ax = axs[i, 0]
        o = np.argsort(p["f"])
        ax.plot(p["f"][o], (p["S"] / p["b"] - 1)[o], lw=0.5)
        ax.set_yscale("symlog", linthresh=0.01); ax.set_title(f"{k}: (S - base)/base (mean)", fontsize=9); ax.grid(alpha=0.3)
        ax = axs[i, 1]
        ser = np.array(p["series"]) if p["series"] else None
        if ser is not None and ser.size:
            for j, d in enumerate(res[k]["spurs"][:5]):
                jj = p["pks"].index(d["ch"])
                s = ser[:, jj]
                ax.plot(s / s.mean() if s.mean() else s, lw=0.7, label=f"{d['if_mhz']:.3f}")
            ax.legend(fontsize=6)
        ax.set_title(f"{k}: spur excess / mean, per bin", fontsize=9); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(png, dpi=90)
    print(f"図: {png}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="mode", required=True)
    a = sub.add_parser("lin"); a.add_argument("path"); a.add_argument("--floor-att", type=float, default=90.0)
    a.add_argument("--zth", type=float, default=8.0); a.add_argument("--ref-dbfs", type=float, default=-15.9)
    a.add_argument("--tsys", type=float, default=139.0); a.add_argument("--no-plot", action="store_true")
    b = sub.add_parser("rec"); b.add_argument("paths", nargs="+"); b.add_argument("--keys", default=None)
    b.add_argument("--zth", type=float, default=8.0); b.add_argument("--bin", type=int, default=25)
    b.add_argument("--tsys", type=float, default=139.0); b.add_argument("--no-plot", action="store_true")
    b.add_argument("--edge", type=float, default=EDGE, help="窓の両端で見ない割合（既定 0.05）")
    x = p.parse_args()
    if x.mode == "lin":
        run_lin(x.path, x.floor_att, x.zth, x.ref_dbfs, x.tsys, not x.no_plot)
    else:
        run_rec(x.paths, x.keys.split(",") if x.keys else None, x.zth, x.bin, x.tsys, not x.no_plot, x.edge)


if __name__ == "__main__":
    sys.exit(main())
