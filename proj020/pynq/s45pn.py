#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — 試験音（CW）の裾（位相雑音）と、ほかの線（SFDR）。LMX の出力の強さ（PWR）を下げて櫛を下げたときの副作用を見る。

タイルの基準（LMX の出力 491.52 MHz）を弱めると、タイル PLL の位相雑音（基準の受けの雑音）が増えるかもしれない。
増えれば強い線の両脇の裾が持ち上がる。SG（10 MHz を共有）の CW を入れ、裾を dBc/Hz で測って PWR ごとに比べる。
SG 自身の位相雑音も裾に入るが、**PWR だけを変えた比較**なので差は分光計の側のもの。

配線: ノイズソースを外し、SG を BPF の入口へ（BPF → ATT → 分配 → 4 ADC は同じ）。ADC で ≒ −20 dBFS（TP で見る）。
窓: 4 ADC とも 0 = 256 MHz・IF 3000、1 = 8 MHz・IF 3000（このツールが SET する）。
試験音 3000.25 MHz = 256 MHz の窓（Δν 62.5 kHz）でも 8 MHz の窓（1.953125 kHz）でも **ch の中心**（矩形の窓の漏れが無い）。

    # PWR ごとに specd を起動し直して（sudo -E … specd.py --clkin 0 --ref 10 --lmx-pwr 10）から
    python3 s45pn.py --host <board> --sg <SG の IP> --dbm -20 --n 250 --label p10       # → p10.pn.json
    python3 s45pn.py --compare p31.pn.json p10.pn.json p0.pn.json                       # 表と図（pn_compare.png）

量（窓ごと）:
  tone      試験音の ch の電力（abs、LSB²）
  skirt     両脇の帯ごとの、ch の電力の中央値 / 試験音 / Δν → dBc/Hz（試験音の ±3 ch は除く）
            8 MHz:  5–20 kHz・20–100 kHz・100 k–1 MHz・1–3.5 MHz / 256 MHz: 0.2–1 MHz・1–10 MHz・10–100 MHz
  floor     試験音から遠い所（帯の外側）の ch の中央値（dBc/Hz）。ADC と経路の雑音
  sfdr      試験音と ±3 ch を除いた最大の ch / 試験音（dBc、ch の中で）とその IF
"""
import argparse
import json
import math
import sys
import time

import numpy as np

KEYS = [f"{a}{w}" for a in "ABCD" for w in "01"]
F_TONE = 3000.25
BANDS = {8: [(5e3, 20e3), (20e3, 100e3), (100e3, 1e6), (1e6, 3.5e6)],
         256: [(0.2e6, 1e6), (1e6, 10e6), (10e6, 100e6)]}


def measure(s, n=250, sg=None, dbm=None, label="pn", settle=1.0):
    from s45lin import _abs_spec, _tp_abs
    kw = {}
    for a in "ABCD":
        kw.update({f"{a}0_if": 3000, f"{a}0_bw": 256, f"{a}0_shift": 9, f"{a}1_if": 3000, f"{a}1_bw": 8, f"{a}1_shift": 9})
    s.set(**kw)
    st = None
    if sg is not None:
        sg.set_freq_mhz(F_TONE)
        if dbm is not None:
            sg.set_dbm(dbm)
        sg.set_output(True)
        time.sleep(settle)
        st = sg.state()
    d = s.acquire(n)
    ident = s.id()
    out = dict(label=label, n=n, id=ident, sg=st, t=time.time(), win={}, tp={})
    for a in "ABCD":
        v, novr = _tp_abs(d, a)
        if v is not None:
            out["tp"][a] = dict(dbfs=float(10 * np.log10(v.mean()) - 10 * math.log10(8192 ** 2 / 2)), ovr=novr)
    for k in KEYS:
        S = _abs_spec(d, k)
        f = d.freq(k)
        out["win"][k] = analyze_one(S, f)
    path = label + ".pn.json"
    json.dump(out, open(path, "w"), ensure_ascii=False, indent=1)
    np.savez(label + ".pn.npz", **{k: _abs_spec(d, k) for k in KEYS}, **{k + "_if": d.freq(k) for k in KEYS})
    report(out)
    print(f"→ {path}（スペクトルは {label}.pn.npz）")
    return out


def analyze_one(S, f):
    dnu = abs(f[1] - f[0]) * 1e6
    w = int(round(dnu * len(S) / 1e6))                      # 窓の幅 [MHz]
    i0 = int(np.argmin(np.abs(f - F_TONE)))
    tone = float(S[i0])
    off = np.abs(f - f[i0]) * 1e6
    near = off <= 3 * dnu
    edge = np.zeros(len(S), bool); e = int(len(S) * 0.03); edge[:e] = True; edge[-e:] = True
    res = dict(w_mhz=w, dnu_hz=dnu, tone_ch=i0, tone_if=float(f[i0]), tone=tone, tone_off_hz=float((f[i0] - F_TONE) * 1e6), skirt={})
    for lo, hi in BANDS.get(w, []):
        m = (off >= lo) & (off < hi) & ~near & ~edge
        if m.sum() >= 3:
            res["skirt"][f"{lo / 1e3:g}-{hi / 1e3:g}k"] = float(10 * np.log10(np.median(S[m]) / tone / dnu))
    hi_b = BANDS.get(w, [(0, 0)])[-1][1]
    fm = (off >= hi_b) & ~edge
    if fm.sum() >= 16:
        res["floor_dbc_hz"] = float(10 * np.log10(np.median(S[fm]) / tone / dnu))
    m = ~near & ~edge
    j = int(np.flatnonzero(m)[np.argmax(S[m])])
    res["sfdr_dbc"] = float(10 * np.log10(S[j] / tone)); res["sfdr_if"] = float(f[j])
    return res


def report(out):
    print(f"[{out['label']}] lmx_pwr={out['id'].get('lmx_pwr', '-')}・TP " + " ".join(f"{a} {t['dbfs']:+.1f}" for a, t in out["tp"].items()) + " dBFS")
    for k, r in out["win"].items():
        sk = "  ".join(f"{b} {v:6.1f}" for b, v in r["skirt"].items())
        print(f"  {k}（{r['w_mhz']} MHz）試験音 {r['tone_if']:.4f} MHz  裾 [dBc/Hz] {sk}  床 {r.get('floor_dbc_hz', float('nan')):6.1f}"
              f"  最大の他の線 {r['sfdr_dbc']:6.1f} dBc @ {r['sfdr_if']:.4f}")


def compare(paths):
    rows = [json.load(open(p)) for p in paths]
    print("比較（同じ窓・同じ帯の裾 [dBc/Hz]。左が基準）")
    for k in KEYS:
        bands = list(rows[0]["win"][k]["skirt"])
        for b in bands + ["floor", "sfdr"]:
            vals = []
            for r in rows:
                w = r["win"][k]
                v = w["skirt"].get(b) if b not in ("floor", "sfdr") else (w.get("floor_dbc_hz") if b == "floor" else w["sfdr_dbc"])
                vals.append(v)
            print(f"  {k} {b:>12s}: " + "  ".join(f"{r['label']} {v:7.1f}" for r, v in zip(rows, vals))
                  + f"   差 {vals[-1] - vals[0]:+.1f} dB")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axs = plt.subplots(2, 4, figsize=(18, 7))
        for ax, k in zip(axs.T.ravel(), KEYS):
            for r, p in zip(rows, paths):
                z = np.load(p.replace(".pn.json", ".pn.npz"))
                S = z[k]; f = z[k + "_if"]; o = np.argsort(f)
                t = r["win"][k]["tone"]; dnu = r["win"][k]["dnu_hz"]
                ax.plot((f[o] - F_TONE) * 1e3, 10 * np.log10(np.maximum(S[o], 1e-30) / t / dnu), lw=0.5, label=r["label"])
            ax.set_title(f"{k}: dBc/Hz vs offset [kHz]", fontsize=9); ax.grid(alpha=0.3); ax.legend(fontsize=7)
        fig.tight_layout(); fig.savefig("pn_compare.png", dpi=90)
        print("図: pn_compare.png")
    except Exception as e:                       # noqa: BLE001
        print(f"（図は作れなかった: {e}）")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--sg", default=None, help="SG HOST[:PORT]（環境変数 RFSOC_SG でも）。無ければ SG は手で 3000.25 MHz・ON に")
    p.add_argument("--dbm", type=float, default=None, help="SG の出力 [dBm]（ADC で ≒ −20 dBFS になる値）")
    p.add_argument("--n", type=int, default=250, help="ダンプ数（250 ≒ 10 s）")
    p.add_argument("--label", default="pn")
    p.add_argument("--compare", nargs="+", default=None, help="*.pn.json を並べて比べる（左が基準）")
    a = p.parse_args()
    if a.compare:
        compare(a.compare)
        return
    from s45client import S45
    sg = None
    if a.sg is not None:
        from sg import SG
        sg = SG(a.sg)
    s = S45(a.host)
    try:
        measure(s, n=a.n, sg=sg, dbm=a.dbm, label=a.label)
    finally:
        s.close()
        if sg is not None:
            sg.close()


if __name__ == "__main__":
    sys.exit(main())
