#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — 雑音を入れたときのリニアリティ（L-1〜L-3）。プログラムアッテネータで入力を振り、パワーメーターと分光計（8 窓）・TP（4 ADC）を同時に読む。

配線（README）: ノイズソース → BPF 2100〜3900 MHz → プログラムアッテネータ → 分配器 A ─┬→ パワーメーター（N1913A ＋ E9300A）
                                                                                  └→ 3 dB → 分配器 B → C・D → ADC_A〜D
パワーメーターは分光計と同じ分配器の出口を見る。**ノイズソース・BPF の揺らぎは両方に同じく乗る**ので、基準はパワーメーター。
パワーメーターが読めない低い所（< −45 dBm 前後）はアッテネータの設定値を基準にする（2 つの基準が重なる所で互いを確かめる）。

    # Jupyter（ボードの上で可。specd は動かしたまま）
    from s45client import S45; from instr import PowerMeter, Atten; import s45lin as L
    s = S45("<board>"); pm = PowerMeter("<PM の IP>", freq_mhz=3000); at = Atten("<ATT の IP>")
    pm.zero()                                   # ノイズソースの電源を切ってから。終わったら入れる
    path = L.measure(s, pm, at, out="lin1")     # 既定の段: 100（切）・60→0（2 dB）・1→59・100。≒ 6 分
    L.analyze(path)                             # 表と図（lin1.lin.png）

    # コマンドラインで
    python3 s45lin.py --host <board> --pm <IP> --att <IP> --out lin1
    python3 s45lin.py --analyze lin1.lin.jsonl

量（どれも ADC 14 bit の LSB² = proj019 の単位）:
  TP: Σx² / (フレーム数 · 8192) = 入力の分散 σ_x²（全帯域。tp_core は 14 bit の x = ADC の 16 bit >>> 2 の二乗を足す）
  窓: 中央 90 % の ch の abs の和 = その帯域が σ_x² に寄与する量。abs = (Σp/N_ACC − 2/3)·4^SHIFT·4^(4−G)/2³¹
判定（README の予言）:
  L-1 TP・窓とも、雑音の床を引いた値がパワーメーターに比例（残差 ±0.05 dB、パワーメーターの読める範囲・飽和なし）
  L-2 窓 / TP（同じ ADC）が入力のレベルによらず一定（±0.02 dB）: パワーメーターを使わない内部の照合
  L-3 アッテネータの設定値を基準にしても L-1 と同じ（低い所まで）
"""
import argparse
import json
import os
import sys
import time

import numpy as np

KEYS = [f"{a}{w}" for a in "ABCD" for w in "01"]
ADCS = "ABCD"


def default_steps(lo=0, hi=60, step=2, off=100.0, every=8):
    """床 → hi から lo へ → 床 → lo から hi へ（**同じ設定を往復で 2 回**）→ 床。
    同じ設定の 2 回の差 = 時間の揺らぎ、2 回に共通の残差 = 設定ごとの（アッテネータの段の・周波数特性の）ずれ、と分けられる
    （初版は往きが偶数・帰りが奇数で、この 2 つを分けられなかった。2026-10-06 実機）
    床は every 段ごとにも測る（床が時間で数 % 動き、低い所の残差を決めていた。lin3 で TP_C の床が 1 往復で +6.8 %）"""
    down = [float(x) for x in range(hi, lo - 1, -step)]
    seq = down + list(reversed(down))
    out = [off]
    for i, a in enumerate(seq):
        out.append(a)
        if (i + 1) % every == 0:
            out.append(off)
    if out[-1] != off:
        out.append(off)
    return out


def _abs_band(d, key, frac=0.9):
    """窓 key のダンプごとの、中央 frac の ch の abs の和（LSB²）。偏り 2/3 を引く"""
    m = d.meta(key)
    if not len(m):
        return None
    raw = d.spec(key)                                   # (ダンプ, 4096) float64、IF の昇順
    nacc = m["nacc"][:, None].astype(np.float64)
    sc = (4.0 ** m["shift"].astype(np.float64) * 4.0 ** (4 - m["g"].astype(np.float64)) / 2.0 ** 31)[:, None]
    v = (raw / nacc - 2.0 / 3.0) * sc
    n = v.shape[1]
    a = int(round(n * (1 - frac) / 2))
    return v[:, a:n - a].sum(axis=1)


def _abs_spec(d, key):
    """窓 key の ch ごとの abs の、取ったダンプの平均（LSB²、IF の昇順）"""
    m = d.meta(key)
    raw = d.spec(key)
    sc = 4.0 ** float(m["shift"][-1]) * 4.0 ** (4 - float(m["g"][-1])) / 2.0 ** 31
    return ((raw / m["nacc"][:, None].astype(np.float64) - 2.0 / 3.0) * sc).mean(axis=0)


def _tp_abs(d, adc):
    e = d.tp(adc)
    if not len(e):
        return None, 0
    v = e["sum"].astype(np.float64) / (e["nfr"].astype(np.float64) * 8192.0)      # tp_core は 14 bit の x の二乗（/16 は誤り。2026-10-06 実機）
    return v, int(np.sum((e["flags"] & 16) != 0))


def measure(s, pm, att, steps=None, n=25, settle=1.0, out="lin", note="", resume=False):
    """段ごとに: アッテネータ → settle 秒 → パワーメーター → 分光計 n ダンプ → パワーメーター。1 段ごとに out.lin.jsonl に 1 行足す。
    resume=True: 途中で止まった記録の続きから（頭の段の並びを使い、済んだ段は飛ばす）"""
    path = out + ".lin.jsonl"
    done = 0
    if os.path.exists(path):
        if not resume:
            raise SystemExit(f"{path} がもうある（別の out に。途中で止まった続きなら resume=True）")
        head, rows = load(path)
        steps = head["steps"]
        done = len(rows)
        print(f"続きから: {path} の {done} 段は済み（残り {len(steps) - done} 段）。設定は前と同じか確かめる")
        if s.get() != head["settings"]:
            raise SystemExit("サーバーの設定（GET）が前と違う。同じ設定に戻すか、別の out で取り直す")
    else:
        steps = steps or default_steps()
        g = s.get()
        head = dict(kind="head", t=time.time(), settings=g, server=s.id(), pm=getattr(pm, "idn", None), att=getattr(att, "idn", None),
                    pm_freq_mhz=getattr(pm, "freq_mhz", None), pm_avg=getattr(pm, "avg", None), n=n, settle=settle, note=note, steps=steps,
                    tp_unit="x14")
        with open(path, "w") as f:
            f.write(json.dumps(head, ensure_ascii=False) + "\n")
    print(f"リニアリティ: {len(steps)} 段 × {n} ダンプ → {path}（ch ごとの平均のスペクトルは {out}.spec.npz）")
    spec_path = out + ".spec.npz"
    spec = {}
    if done and os.path.exists(spec_path):
        z = np.load(spec_path)
        spec = {k: list(z[k]) for k in z.files}
    for i, a in enumerate(steps):
        if i < done:
            continue
        ag = att.set(a)
        time.sleep(settle)
        p1 = pm.read()
        d = s.acquire(n)
        p2 = pm.read()
        row = dict(kind="step", i=i, t=time.time(), att=a, att_get=ag, pm1=p1, pm2=p2, win={}, tp={})
        for k in KEYS:
            b = _abs_band(d, k)
            if b is None:
                continue
            sp = _abs_spec(d, k)
            spec.setdefault(k, []).append(sp)
            spec.setdefault(k + "_if", []).append(d.freq(k))
            m = d.meta(k)
            row["win"][k] = dict(mean=float(b.mean()), rstd=float(b.std() / abs(b.mean())) if b.mean() else None, n=len(b),
                                 sat=int(m["sat"].sum()), health=int(np.bitwise_or.reduce(m["health"])),
                                 shift=int(m["shift"][-1]), ns=int(m["ns"][-1]), if_mhz=float(m["if_mhz"][-1]))
        for a_ in ADCS:
            v, novr = _tp_abs(d, a_)
            if v is None:
                continue
            row["tp"][a_] = dict(mean=float(v.mean()), rstd=float(v.std() / v.mean()), n=len(v), ovr=novr)
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
        np.savez(spec_path, **{k: np.array(v) for k, v in spec.items()})          # 段ごとに上書き（止まっても残る）
        tpa = row["tp"].get("A", {}).get("mean")
        print(f"  {i + 1:3d}/{len(steps)}  ATT {a:6.1f} dB  PM {p1:+8.3f} / {p2:+8.3f} dBm  "
              f"TP_A {10 * np.log10(tpa / (8192 ** 2 / 2)) if tpa else float('nan'):+7.2f} dBFS  "
              f"A0 {row['win'].get('A0', {}).get('mean', float('nan')):.4g}  "
              f"飽和 {sum(w['sat'] for w in row['win'].values())}・振り切れ {sum(t['ovr'] for t in row['tp'].values())}")
    print(f"終わり: {path}（L.analyze(\"{path}\")）")
    return path


def load(path):
    head, rows = None, []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            if r["kind"] == "head":
                head = r
            else:
                rows.append(r)
    return head, rows


def analyze(path, pm_min=-45.0, snr_min=100.0, off_db=100.0, plot=True, tol_lin=0.05, tol_ratio=0.02, pm_skip=(-13.0, -7.0), snr_hi=100.0):
    """pm_skip: パワーメーターの値でこの範囲は L-1 の当てはめ・判定から外す（E9300A の 2 つの経路の切り替え −10 dBm 前後で
    ±0.1 dB の段差。lin3 で全部の量に同じ形で出た）。snr_hi: L-2 は床の snr_hi 倍以上の点だけ（床の時間の揺らぎを避ける）。
    床は時刻で内挿する（床の段が 2 つ以上あれば）"""
    head, rows = load(path)
    on = [r for r in rows if r["att"] < off_db - 1e-6]
    off = [r for r in rows if r["att"] >= off_db - 1e-6]
    if not off:
        raise SystemExit("雑音の床（ATT ≧ off_db の段）が無い")
    if head.get("tp_unit") != "x14":
        print("注意: この記録の TP は誤った単位（/16）で書かれている（tp_unit が無い）。16 倍して読む")
        for r in rows:
            for v in r["tp"].values():
                v["mean"] *= 16.0
    t_on = np.array([r["t"] for r in on]); t_off = np.array([r["t"] for r in off])
    pm = np.array([(r["pm1"] + r["pm2"]) / 2 for r in on])
    dpm = np.array([r["pm2"] - r["pm1"] for r in on])
    att = np.array([r["att"] for r in on])
    x_pm = 10 ** (pm / 10)
    x_at = 10 ** (-att / 10)
    names = [f"TP {a}" for a in ADCS] + KEYS

    def series(rs, nm):
        if nm.startswith("TP "):
            return np.array([r["tp"].get(nm[3:], {}).get("mean", np.nan) for r in rs])
        return np.array([r["win"].get(nm, {}).get("mean", np.nan) for r in rs])

    def bad(rs, nm):
        if nm.startswith("TP "):
            return np.array([r["tp"].get(nm[3:], {}).get("ovr", 0) > 0 for r in rs])
        return np.array([r["win"].get(nm, {}).get("sat", 0) > 0 for r in rs])

    res = {}
    print(f"リニアリティの解析: {path}（段 {len(on)}・床 {len(off)}、パワーメーターの変化（段の前後）最大 {np.abs(dpm).max():.3f} dB）")
    print(f"{'量':>6} | {'床（LSB²）':>11} | {'利得 [dB, LSB²/mW]':>18} | {'PM 基準の残差 rms / 最大':>24} | {'ATT 基準 rms / 最大':>20} | 点 | 判定 L-1")
    for nm in names:
        y0 = series(off, nm)
        y = series(on, nm)
        if np.all(np.isnan(y)):
            continue
        fl_t = np.interp(t_on, t_off, y0) if len(off) >= 2 else np.full(len(on), np.nanmean(y0))
        fl = np.nanmean(y0)
        yy = y - fl_t
        b = bad(on, nm)
        skip = (pm > pm_skip[0]) & (pm < pm_skip[1]) if pm_skip else np.zeros(len(on), bool)
        ok_pt = (pm >= pm_min) & (yy > snr_min * abs(fl)) & ~b & np.isfinite(yy) & ~skip
        g = np.exp(np.median(np.log(yy[ok_pt] / x_pm[ok_pt]))) if ok_pt.sum() >= 3 else np.nan
        r_pm = 10 * np.log10(np.where(yy > 0, yy, np.nan) / (g * x_pm))
        ok_at = (yy > snr_min * abs(fl)) & ~b & np.isfinite(yy)
        ga = np.exp(np.median(np.log(yy[ok_at] / x_at[ok_at]))) if ok_at.sum() >= 3 else np.nan
        r_at = 10 * np.log10(np.where(yy > 0, yy, np.nan) / (ga * x_at))
        rp = r_pm[ok_pt]; ra = r_at[ok_at]
        good = len(rp) >= 3 and np.nanmax(np.abs(rp)) <= tol_lin
        res[nm] = dict(floor=fl, floor_drift=float(y0.max() / y0.min() - 1) if len(y0) > 1 else 0.0, gain_db=10 * np.log10(g) if g == g else None, rms_pm=float(np.sqrt(np.nanmean(rp ** 2))) if len(rp) else None,
                       max_pm=float(np.nanmax(np.abs(rp))) if len(rp) else None, rms_att=float(np.sqrt(np.nanmean(ra ** 2))) if len(ra) else None,
                       max_att=float(np.nanmax(np.abs(ra))) if len(ra) else None, n=int(ok_pt.sum()), ok=bool(good),
                       r_pm=r_pm.tolist(), r_att=r_at.tolist(), y=yy.tolist())
        print(f"{nm:>6} | {fl:11.4g} | {res[nm]['gain_db'] if res[nm]['gain_db'] is not None else float('nan'):18.3f} | "
              f"{res[nm]['rms_pm'] or float('nan'):10.4f} / {res[nm]['max_pm'] or float('nan'):8.4f} dB | "
              f"{res[nm]['rms_att'] or float('nan'):8.4f} / {res[nm]['max_att'] or float('nan'):7.4f} dB | {ok_pt.sum():2d} | "
              f"{'OK' if good else 'NG'}（±{tol_lin} dB）・床の動き {100 * res[nm]['floor_drift']:.1f} %")
    if pm_skip:
        print(f"  （PM {pm_skip[0]}〜{pm_skip[1]} dBm は当てはめ・判定から外した: E9300A の経路の切り替え。ATT 基準は参考: アッテネータの段の誤差 ±0.3 dB 級が乗る）")
    # 同じ設定を 2 回測った段があれば、残差を「時間の揺らぎ」（2 回の差）と「設定ごと」（2 回の平均）に分ける
    uniq, cnt = np.unique(att, return_counts=True)
    rep_ = uniq[cnt >= 2]
    if len(rep_) >= 3:
        print(f"同じ設定を 2 回以上測った段 {len(rep_)} 個: 残差（PM 基準）の 2 回の差の rms = 時間の揺らぎ・平均の rms = 設定ごとのずれ")
        for nm in names:
            if nm not in res:
                continue
            r = np.array(res[nm]["r_pm"])
            dif, avg = [], []
            for a_ in rep_:
                ii = np.flatnonzero(att == a_)
                v = r[ii]
                if np.all(np.isfinite(v)) and pm[ii].min() >= pm_min:
                    dif.append(v[-1] - v[0]); avg.append(v.mean())
            if dif:
                res[nm]["rep_diff_rms"] = float(np.sqrt(np.mean(np.square(dif)))); res[nm]["rep_avg_rms"] = float(np.sqrt(np.mean(np.square(avg))))
                print(f"  {nm:>6}: 2 回の差 rms {res[nm]['rep_diff_rms']:.4f} dB・2 回の平均 rms {res[nm]['rep_avg_rms']:.4f} dB（{len(dif)} 段）")
    # L-2 窓 / TP
    print(f"L-2 窓 / TP（同じ ADC）の一定さ（パワーメーターを使わない。床を引いた値どうし、点は TP・窓とも床の {snr_hi:g} 倍以上）:")
    for k in KEYS:
        if k not in res or f"TP {k[0]}" not in res:
            continue
        yw = np.array(res[k]["y"]); yt = np.array(res[f"TP {k[0]}"]["y"])
        okp = (yw > snr_hi * abs(res[k]["floor"])) & (yt > snr_hi * abs(res[f"TP {k[0]}"]["floor"])) & ~bad(on, k) & ~bad(on, f"TP {k[0]}")
        if okp.sum() < 3:
            continue
        r = yw[okp] / yt[okp]
        rr = 10 * np.log10(r / np.median(r))
        res[k]["ratio_median"] = float(np.median(r)); res[k]["ratio_max_db"] = float(np.abs(rr).max())
        res[k]["_rr"] = np.where(okp, 10 * np.log10(yw / yt / np.median(r)), np.nan)
        print(f"  {k}: 窓 / TP = {np.median(r):.5f}（帯域が全帯域の電力に占める割合）・ずれ 最大 {np.abs(rr).max():.4f} dB "
              f"{'OK' if np.abs(rr).max() <= tol_ratio else 'NG'}（±{tol_ratio} dB）")
    # L-2 のずれが 4 ADC で同じか（同じなら入力の側: 帯域の中の形がアッテネータの段で変わる。違えば ADC・窓の側）
    for w in "01":
        ks = [a + w for a in ADCS if a + w in res and "_rr" in res[a + w]]
        if len(ks) >= 2:
            M = np.array([res[k]["_rr"] for k in ks])
            com = np.nanmean(M, axis=0)
            dev = M - com
            print(f"  窓 {w} の 4 ADC: L-2 のずれのうち 4 ADC に共通な分 最大 {np.nanmax(np.abs(com)):.4f} dB・ADC ごとの分 rms {np.sqrt(np.nanmean(dev ** 2)):.4f} dB"
                  "（共通な分は入力のスペクトルの形の変化で、分光計のせいではない）")
    for k in KEYS:
        res.get(k, {}).pop("_rr", None)
    _l2b(path, res, on, off, snr_hi)
    # TP と dBm の対応（パワーメーターの位置の dBm）
    print("TP と入力の対応（パワーメーターの dBm → ADC の dBFS。0 dBFS = 14 bit の満杯の正弦波の電力 8192²/2）:")
    for a in ADCS:
        r = res.get(f"TP {a}")
        if r and r["gain_db"] is not None:
            c = r["gain_db"] - 10 * np.log10(8192 ** 2 / 2)
            res[f"TP {a}"]["dbfs_minus_pm_db"] = c
            print(f"  ADC_{a}: dBFS = PM [dBm] {c:+.2f} dB（床 {10 * np.log10(r['floor'] / (8192 ** 2 / 2)):+.2f} dBFS）")
    out = path.replace(".lin.jsonl", "") + ".lin.json"
    json.dump(dict(path=path, head=head, res={k: {kk: vv for kk, vv in v.items() if kk not in ("r_pm", "r_att", "y")} for k, v in res.items()}),
              open(out, "w"), ensure_ascii=False, indent=1, default=float)
    print(f"まとめ: {out}")
    if plot:
        _plot(path.replace(".lin.jsonl", "") + ".lin.png", pm, att, res, names, pm_min)
    return res


def _l2b(path, res, on, off, snr_hi):
    """L-2b: 狭い窓（8 MHz）の帯域の電力 / 広い窓（256 MHz）の同じ IF の範囲の ch の和。同じ ADC・同じ周波数の入力を見るので、
    入力のスペクトルの形の変化が消え、分光計の窓の経路どうしの線形だけが残る（.spec.npz があるとき）"""
    sp = path.replace(".lin.jsonl", ".spec.npz")
    if not os.path.exists(sp):
        return
    z = np.load(sp)
    rows_all = sorted(on + off, key=lambda r: r["i"])
    is_on = np.array([r["att"] < 99 for r in rows_all])
    print("L-2b 狭い窓 / 広い窓の同じ IF の範囲（分光計の中だけの照合、入力の形の変化は消える）:")
    for a in ADCS:
        n_, w_ = a + "1", a + "0"
        if n_ not in z.files or w_ not in z.files:
            continue
        Sn, Sw, fn, fw = z[n_], z[w_], z[n_ + "_if"], z[w_ + "_if"]
        m = len(Sn)
        lo, hi = fn[0, int(0.05 * 4096)], fn[0, int(0.95 * 4096)]
        sel = (fw[0] >= lo) & (fw[0] <= hi)
        pn = Sn[:, int(0.05 * 4096):int(0.95 * 4096)].sum(axis=1)
        pw = Sw[:, sel].sum(axis=1)
        flo_n, flo_w = pn[~is_on[:m]].mean(), pw[~is_on[:m]].mean()
        yn, yw = pn[is_on[:m]] - flo_n, pw[is_on[:m]] - flo_w
        ok = (yn > snr_hi * abs(flo_n)) & (yw > snr_hi * abs(flo_w))
        if ok.sum() < 3:
            continue
        r = yn[ok] / yw[ok]
        rr = 10 * np.log10(r / np.median(r))
        res[n_]["l2b_max_db"] = float(np.abs(rr).max())
        print(f"  {n_} / {w_} の {lo:.2f}〜{hi:.2f} MHz（広い窓の ch {sel.sum()} 個）: 比 {np.median(r):.4f}（1 なら単位が窓幅によらない）・"
              f"ずれ 最大 {np.abs(rr).max():.4f} dB（{ok.sum()} 点）")


def make_cal(path, out="tp_cal.json", fs_dbm=5.9, note=""):
    """リニアリティの記録から、暫定の tp_cal.json を作る（ADC の入口の dBm、全 ADC で同じ K）。
    K = fs_dbm − 10·log10(8192²/2): 0 dBFS（14 bit の満杯の正弦波）= fs_dbm [dBm]（3 GHz、proj010 の実測 +5.9）を使う見積もり。
    PM を ADC の口に付け替えて adc_port_cal() で測ったら、その ADC を置き換える（provisional false）"""
    import s45cal
    head, _ = load(path)
    res = analyze(path, plot=False)
    k = fs_dbm - s45cal.DBFS0
    adc = {}
    for a in ADCS:
        r = res.get(f"TP {a}", {})
        c = r.get("dbfs_minus_pm_db")
        adc[a] = dict(k_db=round(k, 3), provisional=True, valid_dbfs=[-47.0, -7.0], date=time.strftime("%Y-%m-%d"),
                      source=f"{os.path.basename(path)}: 0 dBFS = {fs_dbm:+.1f} dBm（3 GHz の正弦波、proj010）の見積もり",
                      lin_dbfs_minus_pm_db=None if c is None else round(c, 3))
    cal = dict(version=1, bit_id_win=str(head.get("server", {}).get("win_id", "")).zfill(8), unit="dBm at ADC input (SMA)",
               adc=adc, note=note or f"暫定: {os.path.basename(path)} から。PM を ADC の口で測って置き換える")
    if os.path.exists(out):
        raise SystemExit(f"{out} がもうある（上書きしない。消すか別の名前に）")
    json.dump(cal, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"{out} を書いた: K = {k:+.3f} dB（全 ADC、暫定）。ボードの specd の起動の場所に置いて specd を起動し直す")
    return cal


def adc_port_cal(s, pm, adc, cal_path="tp_cal.json", n=50, pad_db=0.0, repeat=1):
    """ADC 1 本の K を PM で直に決める（対話）。ノイズの入力を一定にしたまま、repeat 回くり返して平均する:
      1) PM を分配器 A の口（いつもの場所）に → PM と、**4 ADC の TP** を同時に読む
      2) PM を外して、その ADC につながるケーブルの先に付ける（ADC は外れる）→ PM を読む
      3) PM を分配器 A の口に戻し、ケーブルを ADC に戻す → PM と 4 ADC の TP をもう一度
    K = P(ADC の口) − 10·log10(σ_x²(2) の時刻の見積もり)。
    **入力の揺らぎは、触っていない 3 本の ADC の TP の変化で見る**（PM の監視の値は、PM を付け替えるので口のつなぎ直しの揺らぎも入る。
    2026-10-06 の 1 回目: ADC_B で監視 +0.001 dB なのに TP −0.30 dB、ADC_D で監視 −0.21 dB）。
    その ADC の TP の変化 − 他の 3 本の変化 = ADC の口のつなぎ直しの揺らぎ（SMA の再現性）。K の不確かさはその半分と見る。
    pad_db: 2) で PM の前に入れた減衰"""
    import s45cal
    a = adc.upper()
    others = [x for x in ADCS if x != a]

    def tp_all():
        d = s.acquire(n)
        return {x: float(np.mean(s45cal.sigma2(d.tp(x)))) for x in ADCS}
    ks, uncs = [], []
    for rep_ in range(repeat):
        tag = f"（{rep_ + 1}/{repeat}）" if repeat > 1 else ""
        input(f"1){tag} PM を分配器 A の口（いつもの場所）に。ADC_{a} はケーブルにつないだまま。Enter: ")
        m1 = pm.read(); t1 = tp_all()
        input(f"2){tag} PM を外し、ADC_{a} につながるケーブルの先（ADC を外して）に PM をつなぐ"
              f"{'（PM の前に ' + str(pad_db) + ' dB）' if pad_db else ''}。Enter: ")
        p_port = pm.read() + pad_db
        input(f"3){tag} ケーブルを ADC_{a} に戻し、PM を分配器 A の口に戻す。Enter: ")
        m3 = pm.read(); t3 = tp_all()
        d_in = float(np.median([10 * np.log10(t3[x] / t1[x]) for x in others]))      # 入力の揺らぎ（他の 3 本）
        d_own = 10 * np.log10(t3[a] / t1[a])
        recon = d_own - d_in                                                          # 口のつなぎ直し
        s2_mid = np.sqrt(t1[a] * t3[a])                                              # 2) の時刻（真ん中）の見積もり
        k = p_port - 10 * np.log10(s2_mid)
        unc = abs(recon) / 2 + abs(d_in) / 2
        ks.append(k); uncs.append(unc)
        print(f"ADC_{a}{tag}: 口の電力 {p_port:+.3f} dBm・σ_x² {s2_mid:.4g}（{float(s45cal.dbfs(s2_mid)):+.2f} dBFS）→ K = {k:+.3f} dB。"
              f"入力の揺らぎ（他の 3 本の TP）{d_in:+.3f} dB・ADC_{a} の口のつなぎ直し {recon:+.3f} dB・PM の監視 {m3 - m1:+.3f} dB → 不確かさ ±{unc:.3f} dB")
    k = float(np.mean(ks)); unc = float(np.sqrt(np.mean(np.square(uncs))) / np.sqrt(len(ks)))
    if repeat > 1:
        print(f"ADC_{a}: K = {k:+.3f} dB（{repeat} 回の平均、ばらつき {np.std(ks):.3f} dB）・不確かさ ±{unc:.3f} dB")
    if os.path.exists(cal_path):
        cal = json.load(open(cal_path))
        old = cal["adc"].get(a, {}).get("k_db")
        cal["adc"][a] = dict(k_db=round(k, 3), k_unc_db=round(unc, 3), provisional=False,
                             valid_dbfs=cal["adc"].get(a, {}).get("valid_dbfs", [-47.0, -7.0]), date=time.strftime("%Y-%m-%d"),
                             source=f"adc_port_cal: PM を ADC の口で、{repeat} 回（K {', '.join('%+.3f' % x for x in ks)}）", previous_k_db=old)
        os.replace(cal_path, cal_path + ".bak")
        json.dump(cal, open(cal_path, "w"), ensure_ascii=False, indent=1)
        print(f"{cal_path} の ADC_{a} を置き換えた（前の K {old}、前のファイルは {cal_path}.bak）。specd を起動し直すと効く")
    return k


def _plot(png, pm, att, res, names, pm_min):
    import matplotlib
    matplotlib.use(matplotlib.get_backend())
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 3, figsize=(17, 5))
    for nm in names:
        if nm not in res:
            continue
        r = res[nm]
        st = "-" if nm.startswith("TP") else ":"
        y = np.array(r["y"])
        ax[0].plot(pm, 10 * np.log10(np.where(y > 0, y, np.nan)), "o" + st, ms=3, lw=0.8, label=nm)
        ax[1].plot(pm, r["r_pm"], "o" + st, ms=3, lw=0.8, label=nm)
        ax[2].plot(-att, r["r_att"], "o" + st, ms=3, lw=0.8, label=nm)
    ax[0].set_xlabel("power meter [dBm]"); ax[0].set_ylabel("value - floor [dB, LSB^2]"); ax[0].set_title("response")
    ax[1].set_xlabel("power meter [dBm]"); ax[1].set_ylabel("residual [dB]"); ax[1].set_title("vs power meter")
    ax[1].axvline(pm_min, color="k", lw=0.5, ls="--"); ax[1].set_ylim(-0.3, 0.3)
    ax[2].set_xlabel("-ATT [dB]"); ax[2].set_ylabel("residual [dB]"); ax[2].set_title("vs attenuator setting"); ax[2].set_ylim(-0.3, 0.3)
    for a in ax:
        a.grid(alpha=0.3)
    ax[0].legend(fontsize=7, ncol=2)
    fig.tight_layout()
    fig.savefig(png, dpi=110)
    print(f"図: {png}")
    return fig


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--pm", default=None, help="パワーメーター HOST[:PORT]（環境変数 RFSOC_PM でも）")
    p.add_argument("--att", default=None, help="アッテネータ HOST[:PORT]（環境変数 RFSOC_ATT でも）。manual で手で回す")
    p.add_argument("--freq", type=float, default=3000.0, help="パワーメーターの較正係数の周波数 [MHz]（BPF の中心）")
    p.add_argument("--avg", type=int, default=64)
    p.add_argument("--lo", type=int, default=0); p.add_argument("--hi", type=int, default=60); p.add_argument("--step", type=int, default=2)
    p.add_argument("--n", type=int, default=25, help="段ごとのダンプ数（25 ≒ 1 秒）")
    p.add_argument("--settle", type=float, default=1.0)
    p.add_argument("--zero", action="store_true", help="始める前にパワーメーターの零点（ノイズソースを切っておく）")
    p.add_argument("--out", default="lin")
    p.add_argument("--note", default="")
    p.add_argument("--analyze", default=None, help="記録（*.lin.jsonl）を解析するだけ")
    p.add_argument("--pm-min", type=float, default=-45.0)
    a = p.parse_args()
    if a.analyze:
        analyze(a.analyze, pm_min=a.pm_min)
        return
    from s45client import S45
    from instr import Atten, ManualAtten, PowerMeter
    pm = PowerMeter(a.pm, freq_mhz=a.freq, avg=a.avg)
    at = ManualAtten() if a.att == "manual" else Atten(a.att)
    if a.zero:
        input("ノイズソースを切って Enter（零点を取る）: ")
        pm.zero()
        input("ノイズソースを入れて Enter: ")
    s = S45(a.host)
    try:
        path = measure(s, pm, at, default_steps(a.lo, a.hi, a.step), n=a.n, settle=a.settle, out=a.out, note=a.note)
    finally:
        s.close(); pm.close(); at.close()
    analyze(path, pm_min=a.pm_min)


if __name__ == "__main__":
    sys.exit(main())
