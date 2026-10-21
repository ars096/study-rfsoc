#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj026 — 携帯電話の 800 MHz 帯の上り（ゾーン 1 の 815〜845 MHz = IF 3251〜3281 MHz）が分光に入る量を、
specrecv の記録（.s45、SAM45-Fine の窓）から測る。proj013 の「名前の帯の、両隣 2 帯ずつに対する超過」と同じ量。

    python3 tools/phone_rfi.py --label C1 --off runs/c1_off1.s45 runs/c1_off2.s45 --on runs/c1_on1.s45 runs/c1_on2.s45
    python3 tools/phone_rfi.py --level runs/lvl.s45          # 床の高さ（SHIFT の選び）と飽和だけ見る
    python3 tools/phone_rfi.py --selftest                     # 合成の記録で（陽性対照つき）
    python3 tools/phone_rfi.py --label C1 --off … --on … --plot runs/c1   # レポートの材料: .spec.npz・.spec.png・.ts.png

窓: 4 ADC とも窓 0 を IF 3200 MHz・幅 256 MHz（3072〜3328 MHz）に置く。窓の中心（DDC の DC）は帯の外。
量: ダンプごと・ADC ごとに excess = mean(S[帯]) / mean(S[両隣]) − 1。帯と両隣は下の BANDS。対照の帯（ctl）は通話で動かないはず。
線を除く: 窓の両端 5 %・窓の中心 ±3 ch・k·163.84 MHz（fs/25 の櫛。**3276.8 MHz は 800 MHz 帯の中にある**）±3 ch と、
         通話なしの記録の平均スペクトルで 33 ch の移動中央値から ZTH σ を越えた ch ±3 ch。線は一定なので on − off では消えるが、
         帯の中の強い線は比の分母・分子を揺らすので除く。通話の信号（LTE、数 MHz 幅）は 33 ch（2 MHz）の中央値では線に見えない。
s45proto.py は YATSUGATAKE の sw/pynq/s45proto.py（5fc4dbc）の写し（proj を自己完結にするため）。
"""
import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s45proto as P  # noqa: E402

COMB = 163.84               # fs/25
BANDS = {
    "800": ((3251.0, 3281.0), [(3219.0, 3251.0), (3281.0, 3313.0)]),
    "ctl": ((3150.0, 3180.0), [(3118.0, 3150.0), (3180.0, 3212.0)]),
}
EDGE = 0.05
HALF = 3
ZTH = 6.0
WMED = 33
WIN = 0


def freq_axis(if_mhz, ns, nch):
    """s45client.freq と同じ式（IF の昇順）"""
    w = 512.0 / (1 << ns)
    b = (nch // 2 - 1 - np.arange(nch)) % nch
    return if_mhz - np.where(b < nch // 2, b, b - nch) * (w / nch)


def read(paths, win=WIN):
    """{adc: dict(S=[ダンプ × ch], f=, sc=, sat=, flags=, health=, shift=, nsum=)}"""
    out = {}
    for path in paths:
        with open(path, "rb") as fh:
            while True:
                h = fh.read(P.HDR.size)
                if len(h) < P.HDR.size:
                    break
                rtype, plen, crc, seq = P.parse_header(h)
                ver = P.header_ver(h)
                pl = fh.read(plen)
                if len(pl) < plen:
                    break
                if rtype == P.T_EVENT and b"\"START\"" in pl[:40]:
                    nstart = locals().get("nstart", 0) + 1
                if rtype != P.T_SPEC:
                    continue
                d = P.decode(rtype, pl, ver)
                if d["win"] != win:
                    continue
                sc = 4.0 ** d["shift"] * 4.0 ** (4 - d["g"]) / 2.0 ** 31
                v = (d["data"].astype(np.float64) / d["nacc"] - 2.0 / 3.0) * sc
                o = out.setdefault(d["adc"], dict(S=[], f=freq_axis(d["if_mhz"], d["ns"], len(v)), sc=sc, sat=0, flags=0,
                                                 health=0, shift=d["shift"], if_mhz=d["if_mhz"], ns=d["ns"]))
                o["S"].append(v)
                o.setdefault("t", []).append(int(d["utc_ns"]))
                o["sat"] += int(d["sat"])
                o["flags"] |= int(d["flags"])
                o["health"] |= int(d["health"])
        if locals().get("nstart", 0) > 1:
            print(f"**注意**: {path} に START が {nstart} 回ある（同じ名前で受けを 2 回回した）。区間ごとに分けて見ること（tools/segscan.py）")
        nstart = 0
    for o in out.values():
        o["S"] = np.array(o["S"])
        o["t"] = np.array(o["t"], np.int64)
    return out


def running_median(s, w=WMED):
    from numpy.lib.stride_tricks import sliding_window_view
    p = w // 2
    return np.median(sliding_window_view(np.pad(s, p, mode="edge"), w), axis=1)


def make_mask(f, Sref, if_mhz, detect=True):
    """使ってよい ch（True）。Sref = 通話なしの平均スペクトル"""
    n = len(f)
    ok = np.ones(n, bool)
    e = int(n * EDGE)
    ok[:e] = False
    ok[n - e:] = False
    df = abs(f[1] - f[0])
    bad = np.zeros(n, bool)
    for k in range(int(f.min() // COMB), int(f.max() // COMB) + 2):
        bad |= np.abs(f - k * COMB) <= (HALF + 0.5) * df
    bad |= np.abs(f - if_mhz) <= (HALF + 0.5) * df
    nline = 0
    if detect and Sref is not None:
        b = running_median(Sref)
        rel = np.where(b > 0, Sref / b - 1.0, 0.0)
        use = ok & ~bad
        sig = 1.4826 * np.median(np.abs(rel[use] - np.median(rel[use])))
        pk = np.where(use & (rel > ZTH * sig))[0]
        nline = len(pk)
        for p in pk:
            bad[max(p - HALF, 0):p + HALF + 1] = True
    return ok & ~bad, nline


def sel(f, lo, hi):
    return (f >= lo) & (f < hi)


def excess(S, f, ok, band):
    (lo, hi), nbs = band
    m_b = sel(f, lo, hi) & ok
    m_n = np.zeros(len(f), bool)
    for a, b in nbs:
        m_n |= sel(f, a, b)
    m_n &= ok
    return S[:, m_b].mean(axis=1) / S[:, m_n].mean(axis=1) - 1.0, int(m_b.sum()), int(m_n.sum())


def stats(x):
    return dict(n=int(len(x)), med=float(np.median(x)), p99=float(np.percentile(x, 99)), mean=float(np.mean(x)))


def analyze(off, on, label="", detect=True, quiet=False):
    """off / on: read() の結果のリスト（ファイルごと）。返り値: ADC → 量"""
    res = {}
    adcs = sorted(set().union(*[set(r) for r in off + on]))
    for a in adcs:
        offs = [r[a] for r in off if a in r]
        ons = [r[a] for r in on if a in r]
        f = (offs or ons)[0]["f"]
        ifm = (offs or ons)[0]["if_mhz"]
        # 線の検出は通話なしのダンプの**中央値**で（2026-10-21: 平均では、通話を切った直後の電話の送信が off に混じり、
        # 混信そのものを線として除いて「増えた分」を小さく出した）
        Sref = np.median(np.concatenate([o["S"] for o in offs]), axis=0) if offs else None
        ok, nline = make_mask(f, Sref, ifm, detect)
        r = dict(nline=nline, files=[])
        for kind, lst in (("off", offs), ("on", ons)):
            for o in lst:
                row = dict(kind=kind, sat=o["sat"], flags=o["flags"], health=o["health"], shift=o["shift"],
                           q=float(np.median(o["S"].mean(axis=0)[ok]) / o["sc"]))
                for name, band in BANDS.items():
                    x, nb, nn = excess(o["S"], f, ok, band)
                    row[name] = stats(x)
                    row[name + "_nch"] = (nb, nn)
                r["files"].append(row)
        for name in BANDS:
            moff = [row[name]["med"] for row in r["files"] if row["kind"] == "off"]
            mon = [row[name]["med"] for row in r["files"] if row["kind"] == "on"]
            r[name] = dict(off=float(np.mean(moff)) if moff else None, on=float(np.mean(mon)) if mon else None)
            if moff and mon:
                r[name]["delta"] = r[name]["on"] - r[name]["off"]
                # 揺れの目安: 同じ種類のファイルの間のばらつき（2 本以上あれば）
                sp = [np.std(v, ddof=1) for v in (moff, mon) if len(v) > 1]
                r[name]["spread"] = float(max(sp)) if sp else None
        res["ABCD"[a]] = r
    if not quiet:
        print(f"== {label}  （帯 800 = IF 3251〜3281 MHz、ctl = 3150〜3180 MHz。excess は両隣に対する超過の中央値、%）")
        print("ADC | 線 | 800: off → on（増えた分）| ctl: off → on（増えた分）| 飽和 | flags | q（床, LSB²）")
        for k, r in res.items():
            def fm(name):
                x = r[name]
                s = f"{100 * x['off']:+.2f} → {100 * x['on']:+.2f}" if x["off"] is not None and x["on"] is not None else \
                    "  ".join(f"{100 * row[name]['med']:+.2f}" for row in r["files"])
                if "delta" in x:
                    s += f"（{100 * x['delta']:+.2f}" + (f" ± {100 * x['spread']:.2f}" if x.get("spread") else "") + "）"
                return s
            sat = sum(row["sat"] for row in r["files"])
            fl = 0
            for row in r["files"]:
                fl |= row["flags"]
            q = min(row["q"] for row in r["files"])
            print(f"{k} | {r['nline']} | {fm('800')} | {fm('ctl')} | {sat} | {fl:#x} | {q:.1f}")
        # 4 ADC の平均（電話の向き・場所で ADC ごとの入り方は入れ替わるが、和は揃う。2026-10-21 の C1 で on1・on2 の ADC ごとの比 0.4〜2.4 倍、4 ADC の平均は ±9 %）
        for name in BANDS:
            per = {}
            for kind in ("off", "on"):
                rows = [[row[name]["med"] for row in r["files"] if row["kind"] == kind] for r in res.values()]
                if all(rows) and rows:
                    per[kind] = np.mean(np.array(rows), axis=0)            # ファイルごとの 4 ADC の平均
            if "off" in per and "on" in per:
                d = per["on"].mean() - per["off"].mean()
                sp = np.std(per["on"], ddof=1) if len(per["on"]) > 1 else float("nan")
                print(f"4 ADC の平均 {name}: off {100 * per['off'].mean():+.2f} → on {100 * per['on'].mean():+.2f}（増えた分 {100 * d:+.2f}、"
                      f"on のファイルごと " + "・".join(f"{100 * x:+.1f}" for x in per["on"]) + f"、ばらつき {100 * sp:.1f}）")
                for r in res.values():
                    r.setdefault("mean4", {})[name] = dict(off=float(per["off"].mean()), on=float(per["on"].mean()), delta=float(d),
                                                         on_files=[float(x) for x in per["on"]])
        print("ファイルごと（800 の med / p99、ctl の med）:")
        for k, r in res.items():
            print(f"  {k}: " + "  ".join(f"{row['kind']} {100 * row['800']['med']:+.2f}/{100 * row['800']['p99']:+.1f}"
                                       f" ctl {100 * row['ctl']['med']:+.2f}（n {row['800']['n']}）" for row in r["files"]))
    return res


# ---------------- レポートの材料（--plot） ----------------
def _font():
    import matplotlib
    from matplotlib import font_manager
    for name in ("Noto Sans CJK JP", "IPAexGothic", "IPAGothic", "TakaoGothic", "Noto Sans Mono CJK JP", "Noto Serif CJK JP"):
        if any(f.name == name for f in font_manager.fontManager.ttflist):
            matplotlib.rcParams["font.family"] = name
            return name
    return None


def report(prefix, label, off_paths, on_paths, off, on, detect=True):
    """prefix.spec.npz（スペクトル・印・時系列）と prefix.spec.png（平均スペクトル）・prefix.ts.png（超過の時系列）"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _font()
    files = [("off", p, r) for p, r in zip(off_paths, off)] + [("on", p, r) for p, r in zip(on_paths, on)]
    adcs = sorted(set().union(*[set(r) for _, _, r in files]))
    files.sort(key=lambda x: min(int(o["t"][0]) for o in x[2].values()))          # 時刻の順
    t0 = min(int(o["t"][0]) for _, _, r in files for o in r.values())
    npz = dict(label=label, files=np.array([os.path.basename(p) for _, p, _ in files]),
               kinds=np.array([k for k, _, _ in files]), adcs=np.array(["ABCD"[a] for a in adcs]),
               bands=json.dumps(BANDS), t0_utc_ns=t0)
    fig, axs = plt.subplots(len(adcs), 1, figsize=(11, 2.6 * len(adcs)), sharex=True, squeeze=False)
    fig2, axs2 = plt.subplots(len(adcs), 1, figsize=(11, 2.2 * len(adcs)), sharex=True, squeeze=False)
    for i, a in enumerate(adcs):
        L = "ABCD"[a]
        rs = [(k, p, r[a]) for k, p, r in files if a in r]
        f = rs[0][2]["f"]
        sc = rs[0][2]["sc"]
        offS = [o["S"] for k, _, o in rs if k == "off"]
        onS = [o["S"] for k, _, o in rs if k == "on"]
        Sref = np.median(np.concatenate(offS), axis=0) if offS else None
        ok, _ = make_mask(f, Sref, rs[0][2]["if_mhz"], detect)
        floor = np.median((Sref if Sref is not None else np.concatenate(onS).mean(axis=0))[ok])
        npz[f"{L}_f_mhz"] = f
        npz[f"{L}_ok"] = ok
        npz[f"{L}_sc"] = sc
        npz[f"{L}_floor"] = floor
        ax = axs[i, 0]
        for kind, lst, col in (("off", offS, "#4c78a8"), ("on", onS, "#e45756")):
            if not lst:
                continue
            m = np.concatenate(lst).mean(axis=0)
            npz[f"{L}_mean_{kind}"] = m
            ax.plot(f, 10 * np.log10(np.maximum(m / floor, 1e-6)), lw=0.6, color=col,
                    label=f"通話{'あり' if kind == 'on' else 'なし'}（{sum(len(x) for x in lst)} ダンプの平均）")
        for j, (k, p, o) in enumerate(rs):
            npz[f"{L}_file{j}_mean"] = o["S"].mean(axis=0)
        (lo, hi), nbs = BANDS["800"]
        ax.axvspan(lo, hi, color="#e45756", alpha=0.12, lw=0)
        for x0, x1 in nbs:
            ax.axvspan(x0, x1, color="0.5", alpha=0.12, lw=0)
        (lo, hi), nbs = BANDS["ctl"]
        ax.axvspan(lo, hi, color="#54a24b", alpha=0.12, lw=0)
        bad = ~ok
        e = int(len(f) * EDGE)
        bad[:e] = False
        bad[len(f) - e:] = False
        ax.plot(f[bad], np.full(bad.sum(), -1.5), "|", color="0.3", ms=4, label="除いた ch（線）")
        ax.set_ylabel(f"ADC_{L}\n[dB, 床に対して]")
        ax.set_ylim(-2, None)
        ax.grid(alpha=0.3)
        if i == 0:
            ax.legend(fontsize=7, loc="upper left", ncol=3)
        # 時系列
        ax2 = axs2[i, 0]
        for k, p, o in rs:
            x, _, _ = excess(o["S"], f, ok, BANDS["800"])
            xc, _, _ = excess(o["S"], f, ok, BANDS["ctl"])
            tt = (o["t"] - t0) / 1e9
            npz[f"{L}_{os.path.basename(p)}_t_s"] = tt
            npz[f"{L}_{os.path.basename(p)}_x800"] = x
            npz[f"{L}_{os.path.basename(p)}_xctl"] = xc
            ax2.plot(tt, 100 * x, lw=0.6, color="#e45756" if k == "on" else "#4c78a8")
            ax2.plot(tt, 100 * xc, lw=0.5, color="0.6")
        ax2.set_ylabel(f"ADC_{L}\n超過 [%]")
        ax2.grid(alpha=0.3)
    axs[-1, 0].set_xlabel("IF [MHz]（帯 800 = 赤、両隣 = 灰、対照 = 緑）")
    axs[-1, 0].set_xlim(f.min(), f.max())
    fig.suptitle(f"{label}: 窓 0（IF 3200 MHz・256 MHz）の平均スペクトル")
    fig.tight_layout()
    fig.savefig(prefix + ".spec.png", dpi=150)
    axs2[-1, 0].set_xlabel("最初の区間の頭からの時間 [s]（赤 = 通話あり・青 = なしの 800 MHz 帯、灰 = 対照の帯）")
    fig2.suptitle(f"{label}: ダンプ（40.96 ms）ごとの超過")
    fig2.tight_layout()
    fig2.savefig(prefix + ".ts.png", dpi=150)
    np.savez_compressed(prefix + ".spec.npz", **npz)
    print(f"書いた: {prefix}.spec.npz・{prefix}.spec.png・{prefix}.ts.png")


# ---------------- 合成の記録（selftest） ----------------
def synth_file(path, n_dump, band_gain=0.0, line_gain=20.0, seed=0, shift=5, nacc=80, if_mhz=3200.0, ns=1, sat=0):
    """4 ADC × 窓 0 の SPEC v2（f32）を n_dump 個。床 1、χ² の揺れは nacc で。800 MHz 帯に band_gain、
    3276.8 MHz に 1 ch の強い線（line_gain）、窓の中心にも線"""
    rng = np.random.default_rng(seed)
    nch = P.NCH
    f = freq_axis(if_mhz, ns, nch)
    base = np.ones(nch)
    base[np.argmin(np.abs(f - 3276.8))] += line_gain
    base[np.argmin(np.abs(f - if_mhz))] += 5.0
    base[np.argmin(np.abs(f - 3301.3))] += 3.0           # 名の無い線（検出で除く）
    g = 4
    sc = 4.0 ** shift * 4.0 ** (4 - g) / 2.0 ** 31
    with open(path, "wb") as fh:
        seq = 0
        for i in range(n_dump):
            for adc in range(4):
                S = base.copy()
                S[sel(f, 3251, 3281)] *= 1.0 + band_gain
                S = S * rng.chisquare(2 * nacc, nch) / (2 * nacc)
                raw = ((S / sc) + 2.0 / 3.0) * nacc
                data = raw.astype("<f4").tobytes()
                hdr = P.SPEC2_H.pack(adc, 0, adc, 1, ns, shift, P.FMT_F32, 2, nch, 4, 0, i, nacc, sat, 0, 0, g, 0,
                                     i * 10485760, 0, P.BASE_NS * 4, if_mhz, 0.0)
                pl = hdr + data
                pl += b"\0" * (P.pad8(len(pl)) - len(pl))
                fh.write(P.header(P.T_SPEC, len(pl), P.crc32(pl), seq, ver=2) + pl)
                seq += 1


def selftest(tmp):
    os.makedirs(tmp, exist_ok=True)
    fs = {}
    for name, bg, seed in (("off1", 0.0, 1), ("on1", 0.20, 2), ("off2", 0.0, 3), ("on2", 0.20, 4)):
        p = os.path.join(tmp, f"st_{name}.s45")
        synth_file(p, 200, band_gain=bg, seed=seed)
        fs[name] = read([p])
    ok = True
    r = analyze([fs["off1"], fs["off2"]], [fs["on1"], fs["on2"]], label="selftest（通話で 800 の帯だけ +20 %）")
    for k, x in r.items():
        c1 = abs(x["800"]["delta"] - 0.20) < 0.01
        c2 = abs(x["ctl"]["delta"]) < 0.005
        c3 = abs(x["800"]["off"]) < 0.005            # 3276.8 MHz の線を除けている
        c4 = x["nline"] >= 1                          # 名の無い線を検出した
        if not (c1 and c2 and c3 and c4):
            ok = False
            print(f"  {k}: NG（delta {c1}・ctl {c2}・off ≒ 0 {c3}・線の検出 {c4}）")
    report(os.path.join(tmp, "st"), "selftest", [os.path.join(tmp, "st_off1.s45"), os.path.join(tmp, "st_off2.s45")],
           [os.path.join(tmp, "st_on1.s45"), os.path.join(tmp, "st_on2.s45")], [fs["off1"], fs["off2"]], [fs["on1"], fs["on2"]])
    print(f"selftest: {'通過' if ok else '不合格'}")
    # 陽性対照: 線を除かないと 3276.8 MHz の線が 800 の帯の off を持ち上げる（除きが効いている証拠）
    global HALF
    h0 = HALF
    HALF = -1      # 櫛・中心も除かない
    rp = analyze([fs["off1"]], [fs["on1"]], label="陽性対照（線を除かない）", detect=False, quiet=True)
    HALF = h0
    lifted = all(x["800"]["off"] > 0.02 for x in rp.values())
    print(f"陽性対照（線を除かない → off が持ち上がる）: {'不合格（落ちるべきところで落ちた）' if lifted else '通ってしまった — 道具を疑う'}"
          f"  off = " + ", ".join(f"{k} {100 * x['800']['off']:+.2f} %" for k, x in rp.items()))
    return ok and lifted


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--off", nargs="*", default=[])
    ap.add_argument("--on", nargs="*", default=[])
    ap.add_argument("--level", nargs="*", default=None)
    ap.add_argument("--label", default="")
    ap.add_argument("--json", default=None)
    ap.add_argument("--plot", default=None, help="レポートの材料の接頭辞（例: runs/c1 → c1.spec.npz・c1.spec.png・c1.ts.png）")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tmp", default="/tmp/phone_rfi_st")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest(a.tmp) else 1)
    if a.level is not None:
        for p in a.level:
            r = read([p])
            for adc, o in sorted(r.items()):
                S = o["S"]
                ok, _ = make_mask(o["f"], S.mean(axis=0), o["if_mhz"], detect=False)
                q = np.median(S.mean(axis=0)[ok]) / o["sc"]
                print(f"{p} {'ABCD'[adc]}: ダンプ {len(S)}・SHIFT {o['shift']}・床 q {q:.1f} LSB²（≧ 16 が目安）・"
                      f"飽和 {o['sat']}・flags {o['flags']:#x}・health {o['health']:#x}・IF {o['if_mhz']}・NS {o['ns']}")
        return
    off = [read([p]) for p in a.off]
    on = [read([p]) for p in a.on]
    res = analyze(off, on, label=a.label)
    if a.plot:
        report(a.plot, a.label, a.off, a.on, off, on)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(dict(label=a.label, off=a.off, on=a.on, res=res), fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
