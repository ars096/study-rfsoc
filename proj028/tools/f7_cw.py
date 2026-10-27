#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-7 — SG の正弦波（CW）を入れて、細かい段の 558 Hz の bin の位置・線の形・継ぎ目・像・レベルを確かめる（この PC で動かす）

  RFSOC_SG=<SG> RFSOC_ATT=<アッテネータ> python3 tools/f7_cw.py --plan a --out runs/f7a
  python3 tools/f7_cw.py --ana runs/f7a_s2 --f-mhz 1100          # 取ったものを解くだけ

- 段ごとに: アッテネータと SG を設定して読み返す → ボードで f5.py（Overlay・利得の合わせ・3 チャンク）→ spec と meta を runs/ に持ってくる → 解く
- **宛先（SG・アッテネータ・ボード）はリポジトリに書かない**（環境変数 RFSOC_SG・RFSOC_ATT、ボードは ssh の別名 --board）
- 終わったら SG の出力を切り、アッテネータを --att-home に戻す（例外でも）
- 解き方: チャンク 1〜2 の平均を g² で割る（入力に換算）。期待の bin の ±200 bin で最大の bin b を取り、両隣の大きい方との比を
  細かい PFB の模型の応答 R(x)（model/m4_stitch.design）に当てて端数 x を出す → f = (b ± x)·DF → ずれ（ppm）= (f − f_SG) / f_SG
  （proj004 の adc_capture.py と同じ向き: + はボードの刻みが遅い、つまり周波数が高く見える）
- 像: 荒い段の隣の ch に漏れて折り返した分は f ± fs/56（73.142857 MHz）に出る。高さを模型の荒い応答（m3_coarse_fixed）と比べる
"""
import argparse
import json
import os
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
sys.path.insert(0, os.path.join(HERE, "..", "pynq"))

FS = 4.096e9
NF = 131072
NCH = 32
NKEEP = 114688
DF = FS / (56 * NF)
FOUT = FS / 56                         # 荒い ch の出口の速さ（像の間隔）
WIN = 200

RUN = ("bash -lc 'cd /home/xilinx/proj028 && source /etc/profile.d/pynq_venv.sh 2>/dev/null; "
       "source /etc/profile.d/xrt_setup.sh 2>/dev/null; python3 f5.py --chunks 3 --clkin {clkin} --out {name}'")

# 段: (名前, clkin, SG の MHz（None は出力を切る）, SG の dBm, アッテネータ dB)
F1 = 1100.0
DBM = -10.0                           # この E8257D は 1100 MHz で −15 dBm 以下が unleveled（−12 から ok）
DBM_B = 0.0                           # F-7b・c はノイズソースを切って、線を床から 60 dB 以上に
SEAM = 18 * NKEEP * DF / 1e6          # ch 17 | 18 の継ぎ目 1152 MHz
PLANS = {
    "a": [("ref", "stock", None, None, 13), ("s1", "stock", F1, DBM, 13), ("e1", "0", F1, DBM, 13),
          ("s2", "stock", F1, DBM, 13), ("e2", "0", F1, DBM, 13)],
    "b": [("c0", "0", F1, DBM_B, 13), ("h0", "0", F1 + DF / 2e6, DBM_B, 13),
          ("q0", "0", F1 + DF / 4e6, DBM_B, 13),
          ("sl", "0", SEAM - DF / 1e6, DBM_B, 13), ("sr", "0", SEAM, DBM_B, 13),
          ("sl10", "0", SEAM - 10 * DF / 1e6, DBM_B, 13), ("sr10", "0", SEAM + 10 * DF / 1e6, DBM_B, 13)],
    "c": [("a13", "0", F1, DBM_B, 13), ("a23", "0", F1, DBM_B, 23), ("a33", "0", F1, DBM_B, 33), ("a43", "0", F1, DBM_B, 43),
          ("a13b", "0", F1, DBM_B, 13)],
}

_R = None


def fine_resp():
    """細かい PFB の応答の電力（dB）を端数 x = 0..1.5 bin の格子で（0.005 刻み）"""
    global _R
    if _R is None:
        from m4_stitch import design
        h = design(NF)
        q = h.reshape(-1, NF)                         # m = q·N + r
        r = np.arange(NF)
        xs = np.arange(0, 1.5001, 0.005)
        out = []
        for x in xs:
            fold = (q * np.exp(-2j * np.pi * x * np.arange(q.shape[0]))[:, None]).sum(0)
            out.append(abs(np.sum(fold * np.exp(-2j * np.pi * x * r / NF))))
        out = np.array(out)
        _R = (xs, 20 * np.log10(out / out[0]))
    return _R


def coarse_resp_db(f_hz):
    from m3_coarse_fixed import coeffs
    _, hq, _ = coeffs()
    n = np.arange(len(hq))
    H = lambda f: abs(np.sum(hq * np.exp(-2j * np.pi * f / FS * n)))
    return 20 * np.log10(H(f_hz) / H(0.0) + 1e-30)


def subbin(p0, pside):
    """隣との比（dB）から端数 x（0..0.5）。R(1 − x) − R(x) は x について増える"""
    xs, R = fine_resp()
    k = xs <= 0.5
    d = np.interp(1 - xs[k], xs, R) - R[k]
    want = 10 * np.log10(pside / p0)
    return float(np.interp(want, d, xs[k]))


def load(stem):
    spec = np.load(stem + "_spec.npy")
    meta = json.load(open(stem + "_meta.json"))
    g = np.array(meta["gain"], float)
    s = spec[1:].astype(np.float64).mean(0) / np.repeat(g ** 2, NKEEP)
    return s, meta


def ana(stem, f_mhz):
    s, meta = load(stem)
    res = dict(stem=os.path.basename(stem), clkin=meta.get("clkin"), gain=meta["gain"])
    if f_mhz is None:
        res["floor_ch"] = [float(np.median(s[k * NKEEP:(k + 1) * NKEEP])) for k in range(NCH)]
        return res
    f = f_mhz * 1e6
    G0 = f / DF
    lo = max(int(G0) - WIN, 1)
    b = lo + int(np.argmax(s[lo:int(G0) + WIN]))
    k = b // NKEEP
    chs = s[k * NKEEP:(k + 1) * NKEEP].copy()
    j = b - k * NKEEP
    chs[max(j - 2000, 0):j + 2000] = np.nan
    floor = float(np.nanmedian(chs))
    p0 = s[b]
    side = 1 if s[b + 1] > s[b - 1] else -1
    x = subbin(p0, s[b + side])
    fe = (b + side * x) * DF
    ptot = float(s[b - 3:b + 4].sum())
    res.update(f_sg=f, bin=b, ch=k, x=side * x, f_est=fe, ppm=(fe - f) / f * 1e6, off_bins=b + side * x - G0,
               ptot=ptot, snr_db=10 * np.log10(ptot / floor), floor=floor,
               nb_db={d: 10 * np.log10(s[b + d] / p0) for d in (-3, -2, -1, 1, 2, 3)})
    imgs = []
    for sgn in (-1, 1):
        fi = f + sgn * FOUT
        Gi = fi / DF * (1 + res["ppm"] * 1e-6)
        delta = (f - (k + 0.5) * 64e6) - sgn * 64e6     # 隣の ch の中心からの離れ
        if not 0 < Gi < NCH * NKEEP - WIN or abs(delta + sgn * FOUT) >= 32e6:
            continue                                     # 折り返した先が隣の ch の残す 64 MHz の外
        li = int(Gi) - WIN
        bi = li + int(np.argmax(s[li:int(Gi) + WIN]))
        ki = bi // NKEEP
        loc = float(np.median(s[ki * NKEEP:(ki + 1) * NKEEP]))
        imgs.append(dict(f=fi, bin=bi, rel_db=10 * np.log10(s[bi - 3:bi + 4].sum() / ptot),
                         above_floor_db=10 * np.log10(s[bi] / loc), model_db=coarse_resp_db(delta) - coarse_resp_db(f - (k + 0.5) * 64e6)))
    res["images"] = imgs
    # 全体の目立つ山（線の ±10 bin を除く、ch ごとの床から 20 dB 上）
    fl = np.repeat([np.median(s[c * NKEEP:(c + 1) * NKEEP]) for c in range(NCH)], NKEEP)
    z = 10 * np.log10(s / fl)
    z[b - 10:b + 11] = -99
    top = np.argsort(z)[::-1][:12]
    res["peaks"] = [dict(f_mhz=float(t * DF / 1e6), above_floor_db=float(z[t]), rel_db=float(10 * np.log10(s[t] / ptot))) for t in sorted(top) if z[t] > 20]
    return res


def line(r):
    if "ppm" not in r:
        return f"{r['stem']}: SG 切り・clkin {r['clkin']}・g {min(r['gain'])}〜{max(r['gain'])}・床（ch 17）{r['floor_ch'][17]:.4g}"
    nb = " ".join(f"{d:+d}:{v:+.1f}" for d, v in r["nb_db"].items())
    im = " ".join(f"{(i['f'] - r['f_sg']) / 1e6:+.3f} MHz {i['rel_db']:+.1f} dB（床 +{i['above_floor_db']:.1f}・模型 {i['model_db']:+.1f}）" for i in r["images"])
    return (f"{r['stem']}: clkin {r['clkin']}・bin {r['bin']}（ch {r['ch']}）端数 {r['x']:+.3f}・ずれ {r['off_bins']:+.3f} bin = {r['ppm']:+.4f} ppm・"
            f"線 {10 * np.log10(r['ptot']):.2f} dB・床の上 {r['snr_db']:.1f} dB\n    隣（dB）{nb}\n    像 {im}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", choices=sorted(PLANS))
    ap.add_argument("--only", help="段の名前をカンマで（既定は全部）")
    ap.add_argument("--out", default="runs/f7")
    ap.add_argument("--board", default="rfsoc4x2-root")
    ap.add_argument("--att-home", type=float, default=13.0)
    ap.add_argument("--ana")
    ap.add_argument("--f-mhz", type=float)
    a = ap.parse_args()
    if a.ana:
        r = ana(a.ana, a.f_mhz)
        print(line(r))
        return 0
    from sg import SG
    from instr import Atten
    steps = PLANS[a.plan]
    if a.only:
        keep = a.only.split(",")
        steps = [s for s in steps if s[0] in keep]
    results = []
    sg = SG()
    at = Atten()
    try:
        for name, clkin, fmhz, dbm, att in steps:
            at.set(att)
            if fmhz is None:
                sg.set_output(False)
            else:
                sg.set_freq_mhz(fmhz)
                sg.set_dbm(dbm)
                sg.set_output(True)
            st = dict(sg=sg.state(), att=at.get(), t=time.strftime("%H:%M:%S"))
            bname = f"{os.path.basename(a.out)}_{name}"
            print(f"== {name}: clkin {clkin}・SG {'切り' if fmhz is None else f'{fmhz:.6f} MHz {dbm:+.1f} dBm'}・ATT {att} dB（{st['t']}）", flush=True)
            p = subprocess.run(["ssh", a.board, RUN.format(clkin=clkin, name=bname)], capture_output=True, text=True)
            keep = [l for l in p.stdout.splitlines() if any(w in l for w in ("ERROR", "結果", "飽和", "利得", "チャンク 1", "ppm"))]
            print("   " + "\n   ".join(keep[-6:]), flush=True)
            stem = os.path.join(os.path.dirname(a.out) or ".", bname)
            for ext in ("_spec.npy", "_meta.json"):
                subprocess.run(["scp", "-q", f"{a.board}:/home/xilinx/proj028/{bname}{ext}", stem + ext], check=True)
            r = ana(stem, fmhz)
            r.update(step=name, cond=st, rc=p.returncode)
            print("   " + line(r).replace("\n", "\n   "), flush=True)
            results.append(r)
            json.dump(results, open(a.out + ".json", "w"), indent=1, default=float)
    finally:
        sg.set_output(False)
        at.set(a.att_home)
        sg.close()
    print(f"保存: {a.out}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
