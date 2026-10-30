#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 R-1 — 運転の入力（雑音が支配）で、荒い段の丸めが f ± k·fs/56 に作る線の高さ

  python3 model/r1_lines.py --check          速い版（fast_coarse）と ref の bit 単位の照合・陽性対照
  python3 model/r1_lines.py [--nb 131072]    条件ごとの線の高さ（README の R-1）

  e_Y = Y（固定小数点）− Y（同じ式で丸めない）: z の SH と cfft32 の中の丸めの誤差
  e_8 = y（8 bit）− Y_float·g/2^16:            上に 8 bit の再量子化を足した誤差の全部
  線は ch c の長い FFT（Blackman-Harris、±4 bin の和）で、F ± k·FO が落ちる bin（どの ch でも同じ bin）を読む。
  どれも Y（8 bit の利得の前）の目盛りで比べる。dBc は CW（ch 17）に対して、dBN は細かい ch の雑音（中央値の bin × 9、ch 17・18 を除く ch の中央値）に対して
"""
import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
import fast_coarse as fc  # noqa: E402
from coarse_pfb_ref import zblocks as z_ref  # noqa: E402
from cfft32_ref import cfft32 as f_ref  # noqa: E402
from coarse_post_ref import post as p_ref  # noqa: E402

FS = 4.096e9
FO = FS / 56
F = 1151.999442e6
WARM = 32


def check():
    rng = np.random.default_rng(1)
    nb = 300
    x = np.round(rng.normal(0, 1031, 56 * nb + 64)).astype(np.int64)
    x[56 * 100:56 * 130] = np.where(rng.random(56 * 30) < 0.5, -8192, 8191)    # 満杯の区間
    x = np.clip(x, -8192, 8191)
    za, zb = z_ref(x, nb), fc.zblocks(x, nb)
    fra, fia = f_ref(za)
    frb, fib = fc.cfft32(zb)
    g = rng.integers(1, 2 ** 17, 32)
    ya = p_ref(fra, fia, g)
    yr, yi = fc.ymap(frb, fib)
    yb = fc.post(yr, yi, g)
    d = [int(np.sum(za != zb)), int(np.sum(fra != frb) + np.sum(fia != fib)),
         int(np.sum(ya[0] != yb[0]) + np.sum(ya[1] != yb[1]))]
    frc, fic = fc.cfft32(zb, noround=True)
    bad = int(np.sum(fra != frc) + np.sum(fia != fic))
    zf = fc.zblocks(x, nb, float_=True)
    fff, fif = fc.cfft32(zf, float_=True)
    rel = np.max(np.abs(fff - fra)) / np.std(fra[WARM:])
    print(f"照合（{nb} ブロック、満杯の区間を含む）: z の違い {d[0]}・F の違い {d[1]}・y の違い {d[2]}")
    print(f"陽性対照（cfft32 の丸めの加えを抜く）: F の違い {bad}")
    print(f"丸めない版と固定の差の最大 / σ_F: {rel:.2e}")
    ok = d == [0, 0, 0] and bad > 0
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


def spectra(a, n):
    t_ = 2 * np.pi * np.arange(n) / n
    w = 0.35875 - 0.48829 * np.cos(t_) + 0.14128 * np.cos(2 * t_) - 0.01168 * np.cos(3 * t_)
    return np.abs(np.fft.fft(a[-n:] * w[:, None], axis=0)) ** 2


def run(A, sx, seed, nb, label):
    rng = np.random.default_rng(seed)
    ph = rng.uniform(0, 2 * np.pi)
    t = np.arange(56 * (nb + WARM) + 64)
    x = np.clip(np.round(A * np.cos(2 * np.pi * F / FS * t + ph) + rng.normal(0, sx, len(t))), -8192, 8191).astype(np.int64)
    nbt = nb + WARM
    (yr, yi), _ = fc.chain(x, nbt)
    g = fc.gains_for(yr, yi)
    (_, _), (qr, qi) = fc.chain(x, nbt, gains=g)
    (fr, fi), _ = fc.chain(x, nbt, float_=True)
    del x
    y8 = qr + 1j * qi
    Y = yr + 1j * yi
    Yf = fr + 1j * fi
    # 全部を Y（利得の前）の目盛りで比べる。8 bit の利得は ch ごとに違う（CW の ch は小さい）ので、y の目盛りの dBc は ch の間で比べられない
    yY = y8 * (65536.0 / g[None, :])
    eY = Y - Yf
    e8 = yY - Yf
    clip = int(np.sum(np.abs(qr) >= 127) + np.sum(np.abs(qi) >= 127))
    P = {k: spectra(v, nb) for k, v in (("y", yY), ("eY", eY), ("e8", e8))}
    nu = (F - 17 * FO + FO / 2) % FO - FO / 2
    b = int(round(nu / (FO / nb))) % nb
    win = [(b + d) % nb for d in range(-4, 5)]
    lv = lambda k, c: P[k][win, c].sum()
    fl = lambda k, c: np.median(P[k][:, c]) * 9
    pt = lv("y", 17)
    noise = np.median([fl("y", c) for c in range(32) if c not in (17, 18)])
    cnr = 10 * np.log10(pt / fl("y", 17))
    # 線の無いところの「床の上」の分布（同じ ch のほかの 400 か所の ±4 bin の和）の 99 % 点。これを越えたら線が在ると読む
    rs = np.random.default_rng(99)
    null = {}
    for key in ("y", "eY", "e8"):
        v = []
        for c in range(32):
            if c in (17, 18):
                continue
            for b0 in rs.integers(0, nb, 400):
                if min((b0 - b) % nb, (b - b0) % nb) < 64:
                    continue
                v.append(P[key][[(b0 + d) % nb for d in range(-4, 5)], c].sum() / fl(key, c))
        null[key] = 10 * np.log10(np.percentile(v, 99))
    rows = []
    for c in range(32):
        u = (F - 64e6 * c) % FO
        k = int(round((64e6 * c + u - F) / FO))
        if u < 64e6 and c not in (17, 18) and abs(k) <= 8 and k != 0:
            r = {"k": k}
            for key in ("y", "eY", "e8"):
                r[key] = (10 * np.log10(lv(key, c) / pt), 10 * np.log10(lv(key, c) / noise), 10 * np.log10(lv(key, c) / fl(key, c)))
            rows.append(r)
    eYf = 10 * np.log10(np.median([fl("eY", c) for c in range(32)]) / noise)
    e8f = 10 * np.log10(np.median([fl("e8", c) for c in range(32)]) / noise)
    print(f"[{label}] A {A}・σ {sx}・種 {seed}・CNR {cnr:+.1f} dB（ch 17 の細かい bin の雑音に対して）・8 bit の飽和 {clip}・利得 {g.min()}〜{g.max()}")
    print(f"  床（雑音に対して）: e_Y {eYf:+.1f} dB・e_8 {e8f:+.1f} dB。線の無いところの床の上の 99 % 点: y {null['y']:+.1f}・e_Y {null['eY']:+.1f}・e_8 {null['e8']:+.1f} dB")
    print("   k |  y: dBc   dBN  床の上 |  e_Y: dBc   dBN  床の上 |  e_8: dBc   dBN  床の上")
    for r in sorted(rows, key=lambda r: r["k"]):
        s = f"  {r['k']:+d} |"
        for key in ("y", "eY", "e8"):
            s += f" {r[key][0]:+7.1f} {r[key][1]:+6.1f} {r[key][2]:+5.1f} |"
        print(s.rstrip("|"))
    sys.stdout.flush()
    return {"label": label, "cnr": cnr, "rows": rows, "eYf": eYf, "e8f": e8f, "null": null}


def leak(nb, fs_list):
    """係数（量子化した荒い PFB と cfft32 のひねり係数）だけが作る f ± k·FO の像: 雑音なし・丸めなしの実数の CW"""
    for f in fs_list:
        t = np.arange(56 * (nb + WARM) + 64)
        x = 1000.0 * np.cos(2 * np.pi * f / FS * t)
        (fr, fi), _ = fc.chain(x, nb + WARM, float_=True)
        P = spectra(fr + 1j * fi, nb)
        c0 = int(f // 64e6)
        nu = (f - c0 * FO + FO / 2) % FO - FO / 2
        b = int(round(nu / (FO / nb))) % nb
        win = [(b + d) % nb for d in range(-4, 5)]
        pt = max(P[win, c].sum() for c in range(32))
        out = []
        for c in range(32):
            u = (f - 64e6 * c) % FO
            k = int(round((64e6 * c + u - f) / FO))
            if u < 64e6 and k != 0 and abs(k) <= 8:
                out.append((k, c, 10 * np.log10(P[win, c].sum() / pt)))
        print(f"係数の像 f {f / 1e6:.6f} MHz（ch の中の位置 {(f % 64e6) / 64e6:.3f}）: " + " ".join(f"k{k:+d}(ch{c}) {d:+.1f}" for k, c, d in sorted(out)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--nb", type=int, default=131072)
    ap.add_argument("--only", default="")
    ap.add_argument("--leak", action="store_true")
    a = ap.parse_args()
    if a.leak:
        leak(8192, [F, 1120.0e6 + 0.37e6, 1100.0e6 + 0.11e6, 1145.0e6 + 0.23e6, 300.0e6 + 0.29e6])
        return
    if a.check:
        sys.exit(0 if check() else 1)
    sx = 1031.0
    # CW の振幅: 細かい bin（FO/nb）の雑音 σ²·(FO/nb)/(FS/2) に対する比が CNR
    nbin = sx ** 2 * (FO / a.nb) / (FS / 2)
    cases = [("F8a", 47.2, 5.2)] + [(f"cnr{c:+d}", float(np.sqrt(2 * nbin * 10 ** (c / 10))), sx) for c in (0, 20, 40, 58)]
    for label, A, s in cases:
        if a.only and label != a.only:
            continue
        t0 = time.time()
        run(round(A, 1), s, 1, a.nb, label)
        print(f"  （{time.time() - t0:.0f} s）")


if __name__ == "__main__":
    main()
