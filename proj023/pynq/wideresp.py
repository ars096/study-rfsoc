#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj023 H-1 — SAM45-Wide の束ねた ch の応答（半 ch・−3 dB 幅・ENBW）を SG の掃引で。B 1・2・4 を 1 回の掃引で同時に

ボードで root（specd を止めてから）。SG は RFSOC_SG か --sg（リポジトリに書かない）。配線は今のまま（ノイズ ＋ SG → PATT → 4 ADC）でよい:
雑音は SG を切った P_off を引いて消す（点ごとに 2,560 フレームの平均で、雑音の揺れは CW の −40 dB 程度）。

    python3 wideresp.py --clkin 0 --ref 10 --sg $SG --dbm 0 --out h1a        # 掃引（≒ 3 分）→ h1a.h1.npz と判定
    python3 wideresp.py --analyze h1a.h1.npz                                  # 判定だけやり直す

流れ（流れ 0 だけを使う）: A B 1（S0 6720, ch 2048）・B B 2（S0 2336, ch 2048）・C B 4（S0 0, ch 2192）・D B 1（A と同じ。ADC の違いの比べ）。
4 本の的の ch の中心は細かい ch（125 kHz）で 8768・8768.5・8769.5・8768（ADC で 1096 MHz ＝ IF 3000 MHz の近く、BPF の通過域の中）。
SG を細かい ch の 1/8（15.625 kHz）刻みで 8740〜8798 に動かし、点ごとに N_ACC 1280 × 2 ダンプを捕まえ、的の ch の電力 − P_off を記録する。
軸は束ねた ch の単位 u = (f − 的の中心) / (B·125 kHz)。**的の中心は INTERFACE 2.1 の (S0 + i + (B − 1)/(2B))·fs / N**。
判定（README の H-1: model/bin_resp.py の値と）: 半 ch（u = ±0.5）の両側が模型 ±0.02 dB・−3 dB 幅が模型 ±0.005 ch・ENBW（|u| ≦ 5）が模型 ±0.5 %・
中心の繰り返し（掃引の間の 8 回）の揺れ ≦ 0.02 dB。陽性対照: (B − 1)/(2B) を落とした軸では B 2・4 で半 ch の両側が 0.02 dB を越えて食い違う（NG であるべき）
"""
import argparse
import os
import sys
import time

import numpy as np

FINE_KHZ = 125.0
FS_MHZ = 4096.0
STREAMS = {"A0": (1, 6720, 2048), "B0": (2, 2336, 2048), "C0": (4, 0, 2192), "D0": (1, 6720, 2048)}   # KEY: (B, S0, 的の ch i)
# model/bin_resp.py（量子化した 18 bit の係数、2026-10-18）: 半 ch・−3 dB 幅・ENBW（|u| ≦ 5）
MODEL = {1: dict(half=-3.001, w3=1.0008, enbw=1.0103), 2: dict(half=-3.010, w3=1.0000, enbw=1.0081), 4: dict(half=-3.010, w3=1.0000, enbw=1.0081)}
TOL = dict(half=0.02, w3=0.005, enbw=0.005, drift=0.02)
X0, X1, STEP = 8740.0, 8798.0, 0.125         # 細かい ch の単位
REF_X = 8769.0                               # 繰り返して測る点（4 本とも中心の近く）


def log(*a):
    print(*a, flush=True)


def center_fine(b, s0, i, with_off=True):
    return (s0 + i) * b + ((b - 1) / 2 if with_off else 0.0)


def if_of_fine(x):
    return FS_MHZ - x * FINE_KHZ / 1000.0      # ゾーン 2


def db(v):
    return 10 * np.log10(np.maximum(v, 1e-30))


def metrics(u, g):
    """u（昇順）・g（u = 0 で 1 に正規化済み）→ 半 ch の両側・−3 dB 幅・ENBW（|u| ≦ 5）"""
    d = db(g)
    hp, hm = float(np.interp(0.5, u, d)), float(np.interp(-0.5, u, d))
    th = 10 * np.log10(0.5)
    i0 = int(np.argmin(np.abs(u)))
    r = i0 + int(np.argmax(d[i0:] < th)); l = i0 - int(np.argmax(d[i0::-1] < th))
    ur = float(np.interp(th, [d[r], d[r - 1]], [u[r], u[r - 1]]))
    ul = float(np.interp(th, [d[l], d[l + 1]], [u[l], u[l + 1]]))
    k = np.abs(u) <= 5
    return dict(half_p=hp, half_m=hm, w3=ur - ul, enbw=float(np.trapezoid(g[k], u[k])), umin=float(u.min()), umax=float(u.max()))


def analyze(path):
    z = np.load(path, allow_pickle=True)
    xs, keys = z["x"], list(z["keys"])
    ok = True
    for j, key in enumerate(keys):
        b, s0, i = STREAMS[key]
        p = z["p"][:, j] - z["poff"][j]
        for tag, off in (("本番", True), ("陽性対照: (B − 1)/(2B) を落とした軸", False)):
            u = (xs - center_fine(b, s0, i, off)) / b
            g0 = float(np.interp(0.0, u, p))
            g = p / g0
            m = metrics(u, g)
            md = MODEL[b]
            okh = abs(m["half_p"] - md["half"]) <= TOL["half"] and abs(m["half_m"] - md["half"]) <= TOL["half"]
            okw = abs(m["w3"] - md["w3"]) <= TOL["w3"]
            oke = abs(m["enbw"] / md["enbw"] - 1) <= TOL["enbw"]
            good = okh and okw and oke and m["umin"] <= -5 and m["umax"] >= 5
            if off:
                ok &= good
                log(f"  {key}（B {b}）: 半 ch {m['half_p']:+.3f} / {m['half_m']:+.3f} dB（模型 {md['half']:+.3f}、±{TOL['half']}）・"
                    f"−3 dB 幅 {m['w3']:.4f} ch（{md['w3']:.4f}、±{TOL['w3']}）・ENBW {m['enbw']:.4f}（{md['enbw']:.4f}、±{TOL['enbw'] * 100:.1f} %）・"
                    f"u の範囲 {m['umin']:+.1f}〜{m['umax']:+.1f}: {'OK' if good else 'NG'}")
            elif b > 1:
                log(f"      {tag}: 半 ch {m['half_p']:+.3f} / {m['half_m']:+.3f} dB → {'NG（よい）' if not okh else '**OK と出た（陽性対照が効いていない）**'}")
                ok &= not okh
        r = z["pref"][:, j] - z["poff"][j]
        dr = float(db(r.max()) - db(r.min()))
        okd = dr <= TOL["drift"]
        ok &= okd
        log(f"      中心の近く（細かい ch {REF_X}）の繰り返し {len(r)} 回の揺れ {dr:.3f} dB（≦ {TOL['drift']}）: {'OK' if okd else 'NG'}")
    log(f"P_off の最初と最後の差（的の ch）: " + " / ".join(f"{k} {float(db(z['poff_end'][j]) - db(z['poff_beg'][j])):+.3f} dB" for j, k in enumerate(keys)))
    log(f"結果（H-1）: {'通過' if ok else '失敗'}")
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--analyze", default=None)
    p.add_argument("--bitfile", default="proj023.bit")
    p.add_argument("--clkin", default="stock")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--size-mib", type=int, default=32)
    p.add_argument("--sg", default=os.environ.get("RFSOC_SG", ""))
    p.add_argument("--dbm", type=float, default=0.0)
    p.add_argument("--nacc", type=int, default=1280)
    p.add_argument("--ndump", type=int, default=2)
    p.add_argument("--shift", type=int, default=7)
    p.add_argument("--sg-settle", type=float, default=0.05)
    p.add_argument("--out", default="h1")
    a = p.parse_args()
    if a.analyze:
        sys.exit(0 if analyze(a.analyze) else 1)
    if not a.sg:
        log("ERROR: SG の宛先（--sg か RFSOC_SG）"); sys.exit(1)
    import wide as WD
    import plring
    import sg as SGM
    ol, cores, tmm = WD.open_board(a)
    ring = plring.Ring(ol.s45_ring_0.mmio, a.size_mib * plring.MiB)
    allst = [st for c in cores for st in c.streams]
    keys = list(STREAMS)
    mode = {k[0]: STREAMS[k][0] for k in keys}
    s0 = {k: STREAMS[k][1] for k in keys}
    xs = np.arange(X0, X1 + STEP / 2, STEP)
    sg = SGM.SG(a.sg, log=lambda *x: None)
    rc = 0
    try:
        ring.enable(True)
        def grab():
            res, ng = WD.capture(cores, ring, mode, s0, a.nacc, a.ndump, a.shift, 10.0)
            if ng:
                raise RuntimeError("捕まえで NG: " + " / ".join(ng[:3]))
            sat = [x for k in keys for x in res[k]["sat"]]
            if any(sat):
                raise RuntimeError(f"飽和 {sat}（SG を下げるか SHIFT を上げる）")
            return [float(res[k]["spec"][STREAMS[k][2]]) for k in keys]
        sg.set_output(False)
        time.sleep(0.2)
        poff_beg = np.array(grab())
        sg.set_freq_mhz(if_of_fine(xs[0])); sg.set_dbm(a.dbm); sg.set_output(True)
        log(f"H-1: {len(xs)} 点（細かい ch {X0}〜{X1}、刻み {STEP}）・SG {a.dbm:+.1f} dBm・N_ACC {a.nacc} × {a.ndump}")
        P, Pref = [], []
        t0 = time.time()
        for n, x in enumerate(xs):
            if n % 64 == 0:
                sg.set_freq_mhz(if_of_fine(REF_X)); time.sleep(a.sg_settle); Pref.append(grab())
            sg.set_freq_mhz(if_of_fine(x)); time.sleep(a.sg_settle)
            P.append(grab())
            if n % 50 == 0:
                log(f"  {n:>4}/{len(xs)} 細かい ch {x:.3f}（IF {if_of_fine(x):.6f} MHz）: " + " ".join(f"{k} {v:.4g}" for k, v in zip(keys, P[-1]))
                    + f"（{time.time() - t0:.0f} s）")
        sg.set_freq_mhz(if_of_fine(REF_X)); time.sleep(a.sg_settle); Pref.append(grab())
        sg.set_output(False)
        time.sleep(0.2)
        poff_end = np.array(grab())
        np.savez(a.out + ".h1.npz", x=xs, keys=np.array(keys), p=np.array(P), pref=np.array(Pref),
                 poff=(poff_beg + poff_end) / 2, poff_beg=poff_beg, poff_end=poff_end, dbm=a.dbm, sg=sg.state().get("idn", ""))
        log(f"記録: {a.out}.h1.npz（{time.time() - t0:.0f} s）")
        rc = 0 if analyze(a.out + ".h1.npz") else 1
    except Exception:
        import traceback
        log("ERROR: 道具が例外で止まった:\n" + traceback.format_exc())
        rc = 2
    finally:
        try:
            sg.close()
        finally:
            ring.close(allst)
    sys.exit(rc)


if __name__ == "__main__":
    main()
