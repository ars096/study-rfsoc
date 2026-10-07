#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — ADC の線の地図。SG の CW を帯域（既定 2100〜3900 MHz）で動かし、各点で SNAP（全帯域 8192 点 = 2 µs × n 塊）を取って、
入力に依る線（インターリーブの像・高調波）がどこに・どれだけ出るかを 4 ADC について表にする。**specd が IDLE のときだけ**（SNAP の約束）。

    python3 s45spurmap.py --host <board> --sg <SG> --dbm <ADC で ≒ −15 dBFS> --out map1     # 181 点・≒ 5 分 → map1.map.npz・図・表
    python3 s45spurmap.py --plot map1.map.npz                                              # 図と表だけ作り直す
    python3 s45spurmap.py --host <board> --sg fake --from 2990 --to 3010 --step 10           # 通しの試験（specd --fake）

測り方:
  - 最初に SG を切って SNAP（固定の線 = 櫛 n × 163.84 MHz・k·fs/8 など、入力に依らないもの）。最後にもう一度切って比べる
  - 点ごとに SG → 待つ → 4 ADC を SNAP（n 塊、every ms おき）→ Hann・塊の平均のスペクトル（dBFS/bin、0.5 MHz、s45snapplot と同じ）
  - 試験音はベースバンド fold(f)（第 2 ナイキストで 4096 − f）。その bin の山を 0 dBc に
  - 線: 試験音の ±6 bin・DC と端の 4 bin を除き、65 bin の移動中央値（床）より --thr dB（既定 10）上の極大
  - 名前（ベースバンドで ±--tol MHz、既定 0.75 で一致。上から優先）:
      fixed   SG を切った基準にも同じ bin に線がある（櫛など。入力に依らない）
      IL k    インターリーブの像 fold(±f + k·fs/8)、k = 1..7（k = 4 は fs/2）
      H n     n 次の高調波 fold(n·f)、n = 2..5
      HnIL k  高調波の像 fold(±n·f + k·fs/8)、n = 2・3
      ?       どれでもない
  fold(x) = |x − round(x / fs)·fs|（実数のサンプリングの折り返し、0..fs/2）。fs = 4096 MHz
出すもの: ADC ごと・名前ごとに、見えた点の数・最大の dBc（とそのときの f）・中央値。図は ADC ごとの地図（縦 SG の周波数・横 入力に直した周波数、色 dBc）と、
名前ごとの最大 dBc を SG の周波数に対して。
"""
import argparse
import json
import sys
import time

import numpy as np

FS = 4096.0
NB = 4097
DF = FS / 8192
CLASSES = ["fixed"] + [f"IL{k}" for k in range(1, 8)] + [f"H{n}" for n in range(2, 6)] + [f"H{n}IL{k}" for n in (2, 3) for k in range(1, 8)] + ["?"]


def fold(x):
    x = np.asarray(x, float)
    return np.abs(x - np.round(x / FS) * FS)


def spectrum(x14):
    from s45snapplot import spectrum as sp
    return sp(x14.astype(np.float64))[1]


def candidates(f):
    c = []
    for k in range(1, 8):
        for sgn in (1, -1):
            c.append((f"IL{k}", float(fold(sgn * f + k * FS / 8))))
    for n in range(2, 6):
        c.append((f"H{n}", float(fold(n * f))))
    for n in (2, 3):
        for k in range(1, 8):
            for sgn in (1, -1):
                c.append((f"H{n}IL{k}", float(fold(sgn * n * f + k * FS / 8))))
    return c


def runmed(S, w=65):
    from numpy.lib.stride_tricks import sliding_window_view
    p = np.pad(S, w // 2, mode="edge")
    return np.median(sliding_window_view(p, w), axis=1)


def find_lines(S, thr, excl):
    fl = runmed(S)
    m = (S > fl + thr)
    m[1:-1] &= (S[1:-1] >= S[:-2]) & (S[1:-1] >= S[2:])
    m[:5] = False; m[-4:] = False
    for i in excl:
        m[max(i - 6, 0):i + 7] = False
    return np.flatnonzero(m), fl


def classify(fsg, S, Soff, thr=10.0, tol=0.75):
    """1 点・1 ADC: 試験音の dBFS・線の一覧 [(bin, dBc, 名前)]"""
    fb = np.arange(NB) * DF
    it = int(round(float(fold(fsg)) / DF))
    lo, hi = max(it - 2, 0), min(it + 3, NB)
    it = lo + int(np.argmax(S[lo:hi]))
    tone = float(S[it])
    idx, fl = find_lines(S, thr, [it])
    offidx, _ = find_lines(Soff, thr, [])
    offset = set()
    for j in offidx:
        offset.update(range(j - 1, j + 2))
    cand = candidates(fsg)
    out = []
    for i in idx:
        if i in offset:
            name = "fixed"
        else:
            name = "?"
            for nm, fc in cand:
                if abs(fb[i] - fc) <= tol:
                    name = nm
                    break
        out.append((int(i), float(S[i] - tone), name))
    return tone, out, float(np.median(fl) - tone)


class FakeSG:
    def set_freq_mhz(self, m): pass
    def set_dbm(self, d): pass
    def set_output(self, on): pass
    def state(self): return dict(idn="fake")
    def close(self): pass


def measure(a):
    from s45client import S45
    if a.sg == "fake":
        sg = FakeSG()
    else:
        from sg import SG
        sg = SG(a.sg, log=lambda *x: None)
    s = S45(a.host, a.ctrl_port, a.data_port)
    fsg = np.arange(a.f0, a.f1 + 1e-9, a.step)
    adcs = a.adc.upper()
    S = np.full((len(fsg), 4, NB), np.nan, np.float32)
    clip = np.zeros((len(fsg), 4), np.int64)
    t0 = time.time()

    def grab():
        sp = np.full((4, NB), np.nan); cl = np.zeros(4, np.int64)
        for c in adcs:
            x, _ = s.snap(c, n=a.n, every=a.every)
            j = "ABCD".index(c)
            sp[j] = spectrum(x); cl[j] = int(np.sum(np.abs(x) >= 8191))
        return sp, cl
    try:
        ident = s.id()
        if a.dbm is not None:
            sg.set_dbm(a.dbm)
        sg.set_output(False); time.sleep(a.settle)
        off0, _ = grab()
        sg.set_freq_mhz(float(fsg[0])); sg.set_output(True)
        for i, f in enumerate(fsg):
            sg.set_freq_mhz(float(f)); time.sleep(a.settle)
            S[i], clip[i] = grab()
            if i % 20 == 0 or i == len(fsg) - 1:
                el = time.time() - t0
                tone = S[i, "ABCD".index(adcs[0]), int(round(float(fold(f)) / DF))]
                print(f"  {i + 1}/{len(fsg)}  {f:.2f} MHz  試験音 {tone:.1f} dBFS/bin  振り切れ {int(clip[i].max())}"
                      f"  経過 {el / 60:.1f} 分（残り ≒ {el / (i + 1) * (len(fsg) - i - 1) / 60:.1f} 分）", flush=True)
        sg.set_output(False); time.sleep(a.settle)
        off1, _ = grab()
        sgst = sg.state()
    finally:
        try:
            sg.set_output(False)
        except Exception:                       # noqa: BLE001
            pass
        s.close(); sg.close()
    path = a.out + ".map.npz"
    np.savez(path, fsg=fsg, S=S, off0=off0.astype(np.float32), off1=off1.astype(np.float32), clip=clip, adcs=adcs,
             meta=json.dumps(dict(id=ident, sg=sgst, dbm=a.dbm, n=a.n, every=a.every, t0=t0, t1=time.time())))
    print(f"→ {path}（{(time.time() - t0) / 60:.1f} 分）")
    return path


def analyze(path, thr, tol, plot=True):
    z = np.load(path)
    fsg, S, adcs = z["fsg"], z["S"], str(z["adcs"])
    off = np.fmax(z["off0"], z["off1"])
    res = dict(file=path, thr=thr, tol=tol, adc={})
    allpts = {}
    if z["clip"].max() > 0:
        print(f"**振り切れあり**（最大 {int(z['clip'].max())} サンプル、{int((z['clip'].max(1) > 0).sum())} 点）→ --dbm を下げる")
    d = np.abs(z["off0"] - z["off1"])
    print(f"SG を切った基準の最初と最後の差（中央値）: {float(np.nanmedian(d)):.2f} dB")
    for c in adcs:
        j = "ABCD".index(c)
        pts = []
        tones = []
        floors = []
        for i, f in enumerate(fsg):
            tone, lines, flr = classify(float(f), S[i, j].astype(float), off[j].astype(float), thr, tol)
            tones.append(tone); floors.append(flr)
            pts += [(float(f), b, v, nm) for b, v, nm in lines]
        allpts[c] = pts
        bad = int(np.sum(np.array(floors) > -30))
        if bad:
            print(f"**ADC_{c}: 試験音が床から 30 dB 上に見えない点が {bad} 個**（SG の出力・配線・周波数を確かめる）")
        r = dict(tone_dbfs_min=float(np.min(tones)), tone_dbfs_max=float(np.max(tones)), floor_dbc_bin=float(np.median(floors)), cls={})
        for nm in CLASSES:
            v = [(p[2], p[0], p[1]) for p in pts if p[3] == nm]
            if v:
                mx = max(v)
                r["cls"][nm] = dict(n=len(v), max_dbc=mx[0], at_sg=mx[1], at_in=FS - mx[2] * DF, median_dbc=float(np.median([x[0] for x in v])))
        res["adc"][c] = r
    print(f"\n線（床 + {thr:g} dB 以上、試験音を 0 dBc、bin 0.5 MHz）。点は SG の周波数 {len(fsg)} 個のうち見えた数")
    for c, r in res["adc"].items():
        print(f"ADC_{c}: 試験音 {r['tone_dbfs_min']:.1f}〜{r['tone_dbfs_max']:.1f} dBFS/bin・床 {r['floor_dbc_bin']:.1f} dBc/bin")
        for nm, q in sorted(r["cls"].items(), key=lambda kv: -kv[1]["max_dbc"]):
            print(f"   {nm:7s} {q['n']:4d} 点  最大 {q['max_dbc']:6.1f} dBc（SG {q['at_sg']:.1f} → 入力換算 {q['at_in']:.1f} MHz）  中央値 {q['median_dbc']:6.1f}")
    out = path[:-8] if path.endswith(".map.npz") else path
    json.dump(res, open(out + ".map.json", "w"), ensure_ascii=False, indent=1)
    print(f"数字: {out}.map.json")
    if plot:
        _plot(out, fsg, S, adcs, allpts)
    return res


def _plot(out, fsg, S, adcs, allpts):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    n = len(adcs)
    fig, axs = plt.subplots(2, n, figsize=(5.5 * n, 11), squeeze=False)
    fin = FS - np.arange(NB) * DF
    for col, c in enumerate(adcs):
        j = "ABCD".index(c)
        ax = axs[0, col]
        tone = np.array([S[i, j, int(round(float(fold(f)) / DF))] for i, f in enumerate(fsg)])
        rel = S[:, j, :] - tone[:, None]
        if len(fsg) > 1:
            im = ax.pcolormesh(fin, fsg, rel, vmin=-100, vmax=-40, cmap="viridis", shading="nearest")
            fig.colorbar(im, ax=ax, label="dBc / bin")
        ax.set_xlim(FS / 2, FS); ax.set_xlabel("output, as input freq [MHz] (4096 − baseband)"); ax.set_ylabel("SG [MHz]")
        ax.set_title(f"ADC_{c}  spur map (tone = diagonal)", fontsize=9)
        ax = axs[1, col]
        pts = allpts[c]
        names = sorted({p[3] for p in pts}, key=lambda nm: CLASSES.index(nm))
        for nm in names:
            q = [p for p in pts if p[3] == nm]
            ax.plot([p[0] for p in q], [p[2] for p in q], "o" if nm != "?" else "x", ms=3, label=nm)
        ax.set_xlabel("SG [MHz]"); ax.set_ylabel("dBc"); ax.grid(alpha=0.3); ax.set_ylim(-110, -20)
        ax.legend(fontsize=6, ncol=3); ax.set_title(f"ADC_{c}  lines by class", fontsize=9)
    fig.tight_layout(); fig.savefig(out + ".map.png", dpi=90)
    print(f"図: {out}.map.png")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--ctrl-port", type=int, default=51000)
    p.add_argument("--data-port", type=int, default=51001)
    p.add_argument("--sg", default=None, help="SG HOST[:PORT]（環境変数 RFSOC_SG でも）。'fake' で SG なし")
    p.add_argument("--dbm", type=float, default=None, help="SG の出力 [dBm]（ADC で ≒ −15 dBFS。振り切れたら下げる）")
    p.add_argument("--from", dest="f0", type=float, default=2100.0)
    p.add_argument("--to", dest="f1", type=float, default=3900.0)
    p.add_argument("--step", type=float, default=10.0, help="[MHz]（0.5 の倍数で bin の中心に）")
    p.add_argument("--adc", default="ABCD")
    p.add_argument("--n", type=int, default=16, help="点・ADC ごとの SNAP の塊の数（1..256）")
    p.add_argument("--every", type=float, default=5.0, help="塊の間隔 [ms]（5..10000）")
    p.add_argument("--settle", type=float, default=0.1)
    p.add_argument("--thr", type=float, default=10.0, help="線と見なす、床からの高さ [dB]")
    p.add_argument("--tol", type=float, default=0.75, help="名前を付ける一致の幅 [MHz]")
    p.add_argument("--out", default="map")
    p.add_argument("--plot", default=None, help="<out>.map.npz から図と表だけ")
    a = p.parse_args()
    if a.plot:
        analyze(a.plot, a.thr, a.tol)
        return 0
    if abs(a.step / 0.5 - round(a.step / 0.5)) > 1e-9 or abs(a.f0 / 0.5 - round(a.f0 / 0.5)) > 1e-9:
        p.error("--from・--step は 0.5 MHz の倍数（試験音を bin の中心に）")
    if a.sg is None:
        import os
        a.sg = os.environ.get("RFSOC_SG")
        if not a.sg:
            p.error("--sg か RFSOC_SG が要る（'fake' で SG なし）")
    path = measure(a)
    analyze(path, a.thr, a.tol)
    return 0


if __name__ == "__main__":
    sys.exit(main())
