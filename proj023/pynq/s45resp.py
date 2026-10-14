#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — 今のビットストリーム（proj017.bit・specd）の窓の周波数応答。SG の CW を動かし、8 窓（幅の違う 6 種）を同時に測る。

配線: ノイズソースを外し、SG を BPF の入口へ（BPF → ATT → 分配 → 4 ADC）。ボードと SG は同じ 10 MHz（--clkin 0 --ref 10 の specd）。
窓（既定 --layout）: A0 256・A1 8・B0 128・B1 16・C0 64・C1 32・D0 256・D1 8 MHz、IF はすべて --if（既定 3000）。

    python3 s45resp.py --host <board> --sg <SG> --dbm -20 --out resp1            # 測る（≒ 11 分）→ resp1.resp.npz と図
    python3 s45resp.py --plot resp1.resp.npz                                      # 図と数字だけ作り直す
    python3 s45resp.py --dry-run                                                  # 点の数と時間の見積もりだけ

掃引は 2 種類（どちらも全 8 窓で同時に記録する。点は幅ごとに作り、合わせて周波数順に回る）:
  band  窓の形: IF ± --span/2·W（既定 ±0.75 W）を W/--nb（既定 64）刻み。点は ch の中心（窓の側の目減りなし）
        → 通過域の平らさ（中央 90 %）、−3 dB の端、窓の外の CW の折り返し（行き先 = IF + ((ν − IF + W/2) mod W) − W/2 の ch）
  chan  ch の形: 窓の中（IF + W/8 の ch）の周りを ±--kch ch（既定 4）、1 ch を --nsub（既定 8）分割で
        → ch の中心に対する半 ch ずれの目減り（scalloping）、隣の ch への漏れ、−3 dB 幅、サイドローブ（前後の ch も重ねて ±12 ch まで）
量: 利得 G = (P_ch,on − P_ch,off) / (TP_on − TP_off)。P_ch は窓の ch の abs（LSB²）、TP は同じ ADC の全帯域の電力（σ²、LSB²）。
  TP で割るので SG のレベルとアナログの傾き（BPF・増幅器）は消え、窓（DDC・PFB/FFT）だけの応答が残る。図は窓ごとに通過域の中央で 0 dB に。
  P_off（SG を切る）は最初と最後に測って平均し、ch ごとに引く（雑音の平均と SG に依らない線が消える）。最初と最後の差も出す。
記録（<out>.resp.npz）: 点ごとに SG の周波数・TP・掃引の種類、窓ごとに Σ ch・最大の ch と番号・行き先 ±8 ch の利得、各窓の ch の IF、P_off。
  --keep-spec で全 ch（float32）も残す（1000 点で ≒ 130 MB）。
"""
import argparse
import json
import math
import sys
import time

import numpy as np

KEYS = [f"{a}{w}" for a in "ABCD" for w in "01"]
LAYOUT = "A0=256,A1=8,B0=128,B1=16,C0=64,C1=32,D0=256,D1=8"
NCH = 4096
HALF = 8                                   # 行き先の ±8 ch を残す


def parse_layout(s):
    out = {}
    for it in s.split(","):
        k, v = it.split("=")
        out[k.strip().upper()] = int(v)
    assert sorted(out) == KEYS, f"--layout は 8 窓すべて（{KEYS}）"
    return out


def center(f, w):
    """窓の中心の IF（= 記録の if_mhz。ch の IF は if − k·Δν、k = −2048..2047）"""
    return float(f.min() + (NCH // 2 - 1) * (w / NCH))


def fold(nu, ifc, w):
    """窓（中心 ifc・幅 w）の出力に CW nu が出る IF（窓の中ならそのまま、外なら出力のレート w で折り返す）。
    ch の IF は ifc − 2047Δν 〜 ifc + 2048Δν なので、(−w/2, +w/2] に畳む"""
    off = nu - ifc
    return ifc + off - w * np.ceil((off - w / 2) / w)


def plan(fch, layout, span, nb, kch, nsub):
    """点の一覧 [(ν MHz, 種類 0=band/1=chan, 幅)]。fch: 窓ごとの ch の IF（実の IF から）。
    同じ周波数が幅違いで重なっても両方回る（band の点はどの窓でも ch の中心に乗るので、解析は band を幅によらず全部使う）"""
    pts = []
    for w in sorted(set(layout.values()), reverse=True):
        k = [k for k in KEYS if layout[k] == w][0]
        ifc = center(fch[k], w)
        dnu = w / NCH
        for u in np.arange(-span / 2 * nb, span / 2 * nb + 0.5):
            pts.append((ifc + u * w / nb, 0, w))
        c0 = ifc + round(w / 8 / dnu) * dnu
        for j in range(-kch * nsub, kch * nsub + 1):
            pts.append((c0 + j * dnu / nsub, 1, w))
    return sorted(pts)


class FakeSG:
    def __init__(self):
        self.f, self.on, self.dbm = 3000.0, False, -20.0
    def set_freq_mhz(self, m): self.f = m
    def set_dbm(self, d): self.dbm = d
    def set_output(self, on): self.on = on
    def state(self): return dict(idn="fake", freq_hz=self.f * 1e6, dbm=self.dbm, on=self.on)
    def close(self): pass


def grab(s, n, settle):
    """n ダンプ → 窓ごとの ch の abs（平均）・飽和の数、ADC ごとの TP（σ²）"""
    from s45lin import _abs_spec, _tp_abs
    d = s.acquire(n, settle=settle)
    P = {k: _abs_spec(d, k) for k in KEYS}
    sat = {k: int(d.meta(k)["sat"].max()) for k in KEYS}
    tp = {}
    for a in "ABCD":
        v, _ = _tp_abs(d, a)
        tp[a] = float(v.mean()) if v is not None and len(v) else float("nan")
    return d, P, sat, tp


def measure(a):
    from s45client import S45
    layout = parse_layout(a.layout)
    if a.sg == "fake":
        sg = FakeSG()
    else:
        from sg import SG
        sg = SG(a.sg, log=lambda *x: None)
    s = S45(a.host, a.ctrl_port, a.data_port)
    t0 = time.time()
    try:
        kw = {"tint": a.tint}
        for k in KEYS:
            kw.update({f"{k}_if": a.if_mhz, f"{k}_bw": layout[k], f"{k}_shift": a.shift})
        s.set(**kw)
        ident = s.id()
        if a.dbm is not None:
            sg.set_dbm(a.dbm)
        sg.set_output(False)
        time.sleep(a.settle)
        d, Poff0, _, tpoff0 = grab(s, a.n_off, 0.1)
        fch = {k: d.freq(k) for k in KEYS}
        pts = plan(fch, layout, a.span, a.nb, a.kch, a.nsub)
        print(f"ID {ident}\n点 {len(pts)}（band {sum(t == 0 for _, t, _ in pts)}・chan {sum(t == 1 for _, t, _ in pts)}）")
        nu_a = np.array([p[0] for p in pts]); typ = np.array([p[1] for p in pts], np.int8); wsw = np.array([p[2] for p in pts], np.int16)
        M = len(pts)
        tp = np.full((M, 4), np.nan); sat = np.zeros((M, 8), np.int64)
        on = {k: dict(sum=np.zeros(M), imax=np.zeros(M, np.int32), vmax=np.zeros(M), dest=np.zeros(M, np.int32),
                      near=np.zeros((M, 2 * HALF + 1))) for k in KEYS}
        raw = {k: np.zeros((M, NCH), np.float32) for k in KEYS} if a.keep_spec else None
        sg.set_freq_mhz(float(nu_a[0])); sg.set_output(True)
        ton = []
        for i, nu in enumerate(nu_a):
            sg.set_freq_mhz(float(nu))
            time.sleep(a.settle)
            _, P, st, tpo = grab(s, a.n, 0.05)
            ton.append(P)
            tp[i] = [tpo[c] for c in "ABCD"]
            sat[i] = [st[k] for k in KEYS]
            if raw is not None:
                for k in KEYS:
                    raw[k][i] = P[k]
            if i % 25 == 0 or i == M - 1:
                el = time.time() - t0
                print(f"  {i + 1}/{M}  {nu:.6f} MHz  TP_A {10 * math.log10(max(tp[i, 0], 1e-30)) - 10 * math.log10(8192 ** 2 / 2):+.1f} dBFS"
                      f"  飽和 {int(sat[i].max())}  経過 {el / 60:.1f} 分（残り ≒ {el / (i + 1) * (M - i - 1) / 60:.1f} 分）", flush=True)
        sg.set_output(False)
        time.sleep(a.settle)
        _, Poff1, _, tpoff1 = grab(s, a.n_off, 0.1)
        sgst = sg.state()
    finally:
        try:
            sg.set_output(False)
        except Exception:                       # noqa: BLE001
            pass
        s.close(); sg.close()
    Poff = {k: 0.5 * (Poff0[k] + Poff1[k]) for k in KEYS}
    tpoff = np.array([0.5 * (tpoff0[c] + tpoff1[c]) for c in "ABCD"])
    for i, nu in enumerate(nu_a):
        for j, k in enumerate(KEYS):
            x = ton[i][k] - Poff[k]
            f = fch[k]; w = layout[k]
            ifc = center(f, w)
            on[k]["sum"][i] = x.sum()
            on[k]["imax"][i] = int(np.argmax(x)); on[k]["vmax"][i] = x.max()
            dd = int(np.argmin(np.abs(f - fold(nu, ifc, w))))
            on[k]["dest"][i] = dd
            idx = np.clip(np.arange(dd - HALF, dd + HALF + 1), 0, NCH - 1)
            on[k]["near"][i] = x[idx]
    save = dict(nu=nu_a, typ=typ, wsweep=wsw, tp=tp, tpoff=tpoff, sat=sat, if_mhz=a.if_mhz,
                layout=json.dumps(layout), meta=json.dumps(dict(id=ident, sg=sgst, dbm=a.dbm, n=a.n, tint=a.tint, shift=a.shift,
                                                                 t0=t0, t1=time.time())))
    for k in KEYS:
        save[k + "_f"] = fch[k]; save[k + "_off"] = Poff[k]; save[k + "_off_drift"] = Poff1[k] - Poff0[k]
        for q, v in on[k].items():
            save[f"{k}_{q}"] = v
        if raw is not None:
            save[k + "_raw"] = raw[k]
    path = a.out + ".resp.npz"
    np.savez(path, **save)
    print(f"→ {path}（{(time.time() - t0) / 60:.1f} 分）")
    return path


# ---------------------------------------------------------------- 解析と図
def load(path):
    z = np.load(path)
    layout = json.loads(str(z["layout"]))
    return z, layout


def gains(z, k):
    """点ごとの利得（TP で割る）: dest（行き先の ch）・sum（窓の Σ）・near（±8 ch）"""
    p = z["tp"][:, "ABCD".index(k[0])] - z["tpoff"]["ABCD".index(k[0])]
    p = np.where(p > 0, p, np.nan)
    near = z[k + "_near"] / p[:, None]
    return near[:, HALF], z[k + "_sum"] / p, near


def db(x):
    return 10 * np.log10(np.maximum(x, 1e-30))


def analyze(z, layout, k):
    f = z[k + "_f"]; w = layout[k]; dnu = w / NCH
    ifc = center(f, w)
    nu = z["nu"]; typ = z["typ"]
    gd, gs, near = gains(z, k)
    r = dict(key=k, w=w)
    u = (nu - ifc) / w
    band = (typ == 0) & (np.abs(u) <= 0.75)
    inn = band & (np.abs(u) <= 0.45)
    ref = np.nanmedian(gd[band & (np.abs(u) <= 0.25)]) if np.any(band & (np.abs(u) <= 0.25)) else np.nan
    r["ref"] = float(ref)
    if np.any(inn):
        g = db(gd[inn] / ref)
        r["ripple_pp_db"] = float(np.nanmax(g) - np.nanmin(g))
        r["ripple_min_db"] = float(np.nanmin(g))
    for side, sel in (("lo", band & (u < 0)), ("hi", band & (u > 0))):
        uu = u[sel]; g = db(gd[sel] / ref)
        o = np.argsort(np.abs(uu)); uu, g = uu[o], g[o]
        j = np.flatnonzero(g < -3)
        if len(j) and j[0] > 0:                 # 前の点（≧ −3 dB）との間を直線で
            u0, u1, g0, g1 = uu[j[0] - 1], uu[j[0]], g[j[0] - 1], g[j[0]]
            r[f"edge3_{side}"] = float(u0 + (u1 - u0) * (-3 - g0) / (g1 - g0))
        else:
            r[f"edge3_{side}"] = None
    out = band & (np.abs(u) > 0.5)
    if np.any(out):
        dest_u = (fold(nu[out], ifc, w) - ifc) / w
        g = db(gd[out] / ref)
        c90 = np.abs(dest_u) <= 0.45
        if np.any(c90):
            j = int(np.nanargmax(np.where(c90, g, -np.inf)))
            r["alias_max_db"] = float(g[j]); r["alias_max_nu"] = float(nu[out][j])
    ch = (typ == 1) & (z["wsweep"] == w)
    if np.any(ch):
        xs, ys = [], []
        for i, n_ in zip(np.flatnonzero(ch), nu[ch]):
            idx = np.clip(np.arange(z[k + "_dest"][i] - HALF, z[k + "_dest"][i] + HALF + 1), 0, NCH - 1)
            xs.append((n_ - f[idx]) / dnu); ys.append(near[i])
        x = np.concatenate(xs); y = np.concatenate(ys)
        c0 = np.nanmax(y[np.abs(x) < 0.01]) if np.any(np.abs(x) < 0.01) else np.nanmax(y)
        yd = db(y / c0)
        r["chan_x"], r["chan_db"] = x, yd
        def at(v, tol=0.01):
            m = np.abs(np.abs(x) - v) < tol
            return float(np.nanmax(yd[m])) if np.any(m) else None
        r["scallop_db"] = at(0.5)
        r["adj_db"] = at(1.0)
        o = np.argsort(x); xo, yo = x[o], yd[o]
        def cross(side):                        # 中心から外へ、最初に −3 dB を切る所（直線で）
            m = (xo * side >= 0) & (np.abs(xo) <= 1.5)
            xx, yy = np.abs(xo[m]), yo[m]
            o2 = np.argsort(xx); xx, yy = xx[o2], yy[o2]
            j = np.flatnonzero(yy < -3)
            if not len(j) or j[0] == 0:
                return None
            return float(xx[j[0] - 1] + (xx[j[0]] - xx[j[0] - 1]) * (-3 - yy[j[0] - 1]) / (yy[j[0]] - yy[j[0] - 1]))
        a_, b_ = cross(-1), cross(+1)
        r["bw3_ch"] = a_ + b_ if a_ is not None and b_ is not None else None
        far = np.abs(x) >= 1.5
        r["sidelobe_db"] = float(np.nanmax(yd[far])) if np.any(far) else None
        r["chan_ref_gain_vs_band"] = float(db(c0 / ref)) if np.isfinite(ref) else None
    return r


def report(z, layout):
    rows = []
    print(f"{'窓':4s} {'幅':>5s}  {'通過 p-p':>8s} {'−3 dB 端 (×W)':>16s} {'折返し最大':>10s}  {'半ch目減り':>9s} {'隣 ch':>7s} {'−3dB 幅':>7s} {'サイドローブ':>9s}")
    for k in KEYS:
        r = analyze(z, layout, k)
        rows.append(r)
        fmt = lambda v, s="{:+.2f}": (s.format(v) if v is not None and np.isfinite(v) else "-")   # noqa: E731
        print(f"{k:4s} {r['w']:5d}  {fmt(r.get('ripple_pp_db'), '{:.3f}'):>8s} {fmt(r.get('edge3_lo'), '{:+.3f}') + ' / ' + fmt(r.get('edge3_hi'), '{:+.3f}'):>16s}"
              f" {fmt(r.get('alias_max_db'), '{:+.1f}'):>10s}  {fmt(r.get('scallop_db')):>9s} {fmt(r.get('adj_db'), '{:+.1f}'):>7s}"
              f" {fmt(r.get('bw3_ch'), '{:.3f}'):>7s} {fmt(r.get('sidelobe_db'), '{:+.1f}'):>9s}")
    s = z["sat"]
    if s.max() > 0:
        print(f"**飽和あり**（最大 {int(s.max())}、点 {int((s.max(1) > 0).sum())}）→ --shift を上げるか --dbm を下げる")
    print("通過 p-p: 中央 90 % の行き先 ch の利得の幅 / −3 dB 端: 中央から外へ見て最初に −3 dB を切る位置（窓の幅 W 単位、理想 ±0.5）")
    print("折返し最大: 窓の外の CW が中央 90 % の ch に折り返る量（dB、通過域の中央が 0）/ 半 ch 目減り・隣 ch・−3 dB 幅・サイドローブ（±1.5 ch より外）は ch の形")
    return rows


def plot(path, rows=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    z, layout = load(path)
    rows = rows or [analyze(z, layout, k) for k in KEYS]
    base = path[:-4] if path.endswith(".npz") else path
    nu = z["nu"]; typ = z["typ"]
    # 1 窓の形
    fig, axs = plt.subplots(4, 4, figsize=(20, 14))
    for j, (k, r) in enumerate(zip(KEYS, rows)):
        w = layout[k]; f = z[k + "_f"]; ifc = center(f, w)
        gd, gs, _ = gains(z, k)
        u_all = (nu - ifc) / w
        sel = (typ == 0) & (np.abs(u_all) <= 0.75)
        u = u_all[sel]
        o = np.argsort(u)
        ref = r["ref"]
        ax = axs[(j // 4) * 2, j % 4]
        inw = np.abs(u[o]) <= 0.5
        ax.plot(u[o], db(gs[sel][o] / ref), "-", color="0.6", lw=0.8, label="sum over window")
        ax.plot(u[o][inw], db(gd[sel][o][inw] / ref), ".-", ms=3, lw=0.8, label="CW channel")
        ax.plot(u[o][~inw], db(gd[sel][o][~inw] / ref), "o", ms=3, mfc="none", color="C3", label="aliased channel")
        for v in (-0.5, 0.5):
            ax.axvline(v, color="k", lw=0.6, ls="--")
        for v in (-0.45, 0.45):
            ax.axvline(v, color="k", lw=0.4, ls=":")
        ax.set_ylim(-110, 5); ax.grid(alpha=0.3)
        ax.set_title(f"{k}  {w} MHz  IF {ifc:.3f}", fontsize=9)
        ax.set_xlabel("(SG − IF) / W"); ax.set_ylabel("dB"); ax.legend(fontsize=6, loc="lower center")
        ax = axs[(j // 4) * 2 + 1, j % 4]
        m = np.abs(u[o]) <= 0.55
        ax.plot(u[o][m], db(gd[sel][o][m] / ref), ".-", ms=3, lw=0.8)
        for v in (-0.5, 0.5):
            ax.axvline(v, color="k", lw=0.6, ls="--")
        for v in (-0.45, 0.45):
            ax.axvline(v, color="k", lw=0.4, ls=":")
        pp = r.get("ripple_pp_db")
        ax.set_ylim(-4, 1); ax.grid(alpha=0.3)
        ax.set_title(f"{k} passband  p-p(90%) {pp:.3f} dB" if pp is not None else f"{k} passband", fontsize=9)
        ax.set_xlabel("(SG − IF) / W"); ax.set_ylabel("dB")
    fig.suptitle(f"{path}  window response (TP-normalized, 0 dB = passband center)", fontsize=10)
    fig.tight_layout(); fig.savefig(base + ".band.png", dpi=90)
    # 2 ch の形
    fig, axs = plt.subplots(2, 4, figsize=(20, 8))
    for ax, k, r in zip(axs.ravel(), KEYS, rows):
        if "chan_x" not in r:
            ax.set_visible(False); continue
        x, y = r["chan_x"], r["chan_db"]
        ax.plot(x, y, ".", ms=2)
        ax.set_xlim(-12, 12); ax.set_ylim(-120, 5); ax.grid(alpha=0.3)
        ax.set_xlabel("(SG − channel center) / Δν"); ax.set_ylabel("dB")
        ax.set_title(f"{k} {r['w']} MHz  Δν {r['w'] / NCH * 1e3:.3f} kHz  half-ch {r.get('scallop_db') or float('nan'):+.2f} dB"
                     f"  adj {r.get('adj_db') or float('nan'):+.1f} dB", fontsize=8)
        ins = ax.inset_axes([0.05, 0.3, 0.3, 0.3])
        m = np.abs(x) <= 1.5
        ins.plot(x[m], y[m], ".", ms=2); ins.set_ylim(-6, 0.5); ins.grid(alpha=0.3); ins.tick_params(labelsize=6)
    fig.suptitle(f"{path}  channel response (composite of ±8 neighbouring channels)", fontsize=10)
    fig.tight_layout(); fig.savefig(base + ".chan.png", dpi=90)
    print(f"図: {base}.band.png・{base}.chan.png")
    js = [{kk: (v if not isinstance(v, np.ndarray) else None) for kk, v in r.items() if kk not in ("chan_x", "chan_db")} for r in rows]
    json.dump(js, open(base + ".json", "w"), ensure_ascii=False, indent=1)
    print(f"数字: {base}.json")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--ctrl-port", type=int, default=51000)
    p.add_argument("--data-port", type=int, default=51001)
    p.add_argument("--sg", default=None, help="SG HOST[:PORT]（環境変数 RFSOC_SG でも）。'fake' で SG なし（通しの試験）")
    p.add_argument("--dbm", type=float, default=None, help="SG の出力 [dBm]（ADC で ≒ −20 dBFS）")
    p.add_argument("--if", dest="if_mhz", type=float, default=3000.0)
    p.add_argument("--layout", default=LAYOUT, help="窓の幅（MHz、256/128/64/32/16/8）")
    p.add_argument("--shift", type=int, default=9)
    p.add_argument("--tint", type=float, default=0.02048, help="1 ダンプ [s]（2.048 ms の倍数）")
    p.add_argument("--n", type=int, default=3, help="点ごとのダンプ数")
    p.add_argument("--n-off", type=int, default=25, help="SG を切った基準のダンプ数（最初と最後）")
    p.add_argument("--settle", type=float, default=0.05, help="SG を動かしてから待つ [s]")
    p.add_argument("--span", type=float, default=1.5, help="band の幅（W 単位、既定 ±0.75 W）")
    p.add_argument("--nb", type=int, default=64, help="band の刻み = W / nb（ch の中心に乗る値に）")
    p.add_argument("--kch", type=int, default=4, help="chan の幅 ±kch ch")
    p.add_argument("--nsub", type=int, default=8, help="chan の刻み = Δν / nsub")
    p.add_argument("--keep-spec", action="store_true")
    p.add_argument("--out", default="resp")
    p.add_argument("--plot", default=None, help="<out>.resp.npz から図と数字だけ")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    if a.plot:
        z, layout = load(a.plot)
        plot(a.plot, report(z, layout))
        return 0
    if a.nb % 64 or NCH % a.nb:
        p.error("--nb は 64 の倍数で 4096 の約数（刻みを ch の中心に乗せる）")
    if a.dry_run:
        layout = parse_layout(a.layout)
        fch = {}
        for k in KEYS:
            w = layout[k]
            fch[k] = a.if_mhz - (np.arange(NCH) - NCH // 2) * (w / NCH)
        pts = plan(fch, layout, a.span, a.nb, a.kch, a.nsub)
        nb = sum(t == 0 for _, t, _ in pts)
        per = a.n * a.tint + a.settle + 0.6        # fake の通しで 1 点 ≒ 0.7 s
        print(f"点 {len(pts)}（band {nb}・chan {len(pts) - nb}）。1 点 ≒ {per:.2f} s として ≒ {len(pts) * per / 60:.0f} 分")
        print(f"範囲 {pts[0][0]:.3f} 〜 {pts[-1][0]:.3f} MHz")
        return 0
    if a.sg is None:
        import os
        a.sg = os.environ.get("RFSOC_SG")
        if not a.sg:
            p.error("--sg か RFSOC_SG が要る（'fake' で SG なし）")
    path = measure(a)
    z, layout = load(path)
    plot(path, report(z, layout))
    return 0


if __name__ == "__main__":
    sys.exit(main())
