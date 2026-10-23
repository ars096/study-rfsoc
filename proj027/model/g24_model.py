#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj025 — 2G-2 の部品を bit 単位で確かめる（README の M。proj024 の g2_model.py の m8 を 2G-2 の長さで写した）。

  python3 g24_model.py        # a〜d（1 分ほど）。成否は最後の「まとめ」の行で読む
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from g2_model import CF, LANES, core_fft, design, pfb_float, quantize, response_metrics  # noqa: E402
import g24_fixed as F  # noqa: E402


def sigbits(v):
    return int(np.ceil(np.log2(np.abs(v).max() + 1))) + 1


def ramb36(depth, width):
    """深さ depth・幅 width の 2 ポートの ROM 1 個の RAMB36 の数（512×72 / 1K×36 / 2K×18 / 4K×9 の最小）。"""
    best = None
    for d, w in ((512, 72), (1024, 36), (2048, 18), (4096, 9)):
        n = -(-depth // d) * -(-width // w)
        best = n if best is None else min(best, n)
    return best


def m_a():
    N = F.N
    c = quantize(design(N))
    hs = design(N) * (1 << CF)
    e_c = np.sqrt(np.mean((c - hs) ** 2))
    print(f"  a 係数の補間（D {F.D}、左右の折り返し、片側 {F.NSEG} 区間）。物差し: 全部の表 c の h に対する rms {e_c:.4f} LSB")
    for g in range(0, 9):
        V, S = F.coef_tables(g)
        cg = F.coef_fold(V, S, g)
        d = np.abs(cg - c)
        w_ = sigbits(V) + sigbits(S)
        print(f"   G {g}: c との差 最大 {d.max()} LSB・違う係数 {np.mean(d > 0) * 100:6.3f} %・h に対する rms {np.sqrt(np.mean((cg - hs) ** 2)):.4f} LSB"
              f"（比 {np.sqrt(np.mean((cg - hs) ** 2)) / e_c:.4f}）・V {sigbits(V)}・S {sigbits(S)} bit（計 {w_}）" + ("  ← 使う" if g == F.G else ""))
    V, S = F.coef_tables()
    cf = F.coef_fold(V, S)
    d = np.abs(cf - c)
    e_i = np.sqrt(np.mean((cf - hs) ** 2))
    vw, sw = sigbits(V), sigbits(S)
    w = vw + sw
    ok = d.max() <= 1 and e_i <= 1.01 * e_c and w <= 36
    cb = F.coef_beat(V, S)
    same = np.array_equal(cb.reshape(-1), cf)
    bad = F.coef_fold(V, S, fold_err=True)
    pc = int(np.sum(bad != cf))
    print(f"   ビートの式と折り返しの式: {'全部の i で一致' if same else '不一致'}。陽性対照（i' = L − i）: 違う係数 {pc:,}")
    ok &= same and pc > 0
    half = F.NSEG // 2
    nb = 2 * ramb36(half, w)
    print(f"   表: {F.NSEG} × {w} bit（V {vw}・S {sw}）= {F.NSEG * w / 1e3:.0f} kbit。前半・後半を {half} 行の 2 ポートの ROM に: RAMB36 {nb} 個")
    r0 = response_metrics(c.astype(np.float64), N, pad=4)
    r1 = response_metrics(cf.astype(np.float64), N, pad=4)
    dmax = max(abs(r1[k] - r0[k]) for k in ("half", "p04", "ge1", "ge15", "ge3"))
    print(f"   応答の差の最大 {dmax:.3f} dB")
    ok &= dmax <= 0.05
    print(f"  → a {'通過' if ok else '不合格'}（差 ≦ 1 LSB・rms ≦ 1.01 倍・V ＋ S ≦ 36 bit・ビートの式が一致・陽性対照は違う・応答の差 ≦ 0.05 dB）")
    return ok, cf


def m_b():
    N = F.N
    pr, pi = F.tw_prod()
    dr, di = F.tw_direct()
    p_ = np.arange(LANES)[:, None]
    k1 = np.arange(F.M)[None, :]
    wx = np.exp(-2j * np.pi * p_ * k1 / N) * 65536
    dlsb = max(np.abs(pr - dr).max(), np.abs(pi - di).max())
    e_p = np.sqrt(np.mean(np.abs(pr + 1j * pi - wx) ** 2))
    e_d = np.sqrt(np.mean(np.abs(dr + 1j * di - wx) ** 2))
    cmax = max(np.abs(pr).max(), np.abs(pi).max())
    br, bi = F.tw_prod(map_err=True)
    pcd = max(np.abs(br - dr).max(), np.abs(bi - di).max())
    Ar, Ai, Br, Bi = F.tw_tables()
    print(f"  b ひねり係数の積（S {F.S_TW}: hi {Ar.shape[1]} 行・lo {Br.shape[1]} 行）: 直の表との差 最大 {dlsb} LSB・誤差 rms {e_p:.3f} LSB"
          f"（直の表 {e_d:.3f}、比 {e_p / e_d:.2f}）・成分の最大 {cmax}（18 bit ≦ 131071）。陽性対照（hi·127 + lo）: 差 最大 {pcd} LSB")
    ok = dlsb <= 2 and e_p / e_d < 2.0 and cmax <= 131071 and pcd > 100
    print(f"  → b {'通過' if ok else '不合格'}（差 ≦ 2 LSB・rms 比 < 2・18 bit・陽性対照 > 100 LSB）")
    return ok, (pr, pi)


def m_c(cf, tw):
    N = F.N
    pr, pi = tw
    rng = np.random.default_rng(8)
    c0 = 20000
    nf = 5
    n = np.arange(nf * N)
    x = np.clip(np.round(1000 * np.cos(2 * np.pi * c0 * n / N) + rng.normal(0, 100, nf * N)), -8191, 8191).astype(np.int64)
    y, ysat = F.pfb_int(x, cf)
    yfl = pfb_float(x.astype(np.float64), design(N), N)
    st = {}
    ok = ysat == 0
    for name, t in (("鎖", (pr, pi)), ("陽性対照（k1 を 1 ずらす）", (np.roll(pr, -1, axis=1), np.roll(pi, -1, axis=1)))):
        en = ed = 0.0
        dcw = []
        for f in (3, 4):
            Zr, Zi = F.chain_frame(y[f], *t, stats=st if name == "鎖" else None)
            Xf = core_fft(yfl[f])
            # Z の目盛り: Yd = Y / 2^D1、V = Yd·w / 2^18（w = 2^16）→ Z = X / 2^(D1 + 2)
            Zc = (Zr + 1j * Zi).reshape(-1) * 2.0 ** (F.D1 + 2)
            mask = np.abs(np.arange(N // 2) - c0) > 3
            en += np.sum(np.abs(Zc - Xf)[mask] ** 2)
            ed += np.sum(np.abs(Xf)[mask] ** 2)
            dcw.append(10 * np.log10(np.abs(Zc[c0]) ** 2 / np.abs(Xf[c0]) ** 2))
        eps = en / ed
        print(f"  c {name}: 雑音の ch の ε {eps:.2e}・CW の ch の電力の差 {max(dcw, key=abs):+.4f} dB")
        if name == "鎖":
            ok &= eps <= 2e-5 and max(abs(v) for v in dcw) < 0.01
        else:
            ok &= eps > 2e-5
    print(f"     y の飽和 {ysat}・各段の最大 Y {st['Y']:,}（2^27 = {1 << 27:,}）・Yd {st['Yd']:,}・V {st['V']:,}・U {st['U']:,}・Z {st['Z']:,}")
    ok &= st["Y"] < (1 << 27)
    print(f"  → c {'通過' if ok else '不合格'}（ε ≦ 2e-5・CW < 0.01 dB・y の飽和 0・Y < 2^27、陽性対照は ε > 2e-5）")
    return ok


def m_d():
    k = F.bitrev(np.arange(F.M), F.KB)
    perm = np.array_equal(np.sort(k), np.arange(F.M))
    seq = np.concatenate([k, k])
    last = {}
    dist = F.M
    for i, a in enumerate(seq):
        if a in last:
            dist = min(dist, i - last[a])
        last[a] = i
    ok = perm and dist == F.M
    print(f"  d 積分器の番地（bit 反転順の k1、{F.KB} bit）: {'1 フレームで全部の番地を 1 回ずつ' if perm else '並べ替えでない'}・同じ番地に戻るまで最小 {dist} ビート")
    print(f"  → d {'通過' if ok else '不合格'}")
    return ok


def main():
    print(f"M 2G-2 の部品を bit 単位で（model/g24_fixed.py: N {F.N}・M {F.M}・L {F.L}・G {F.G}・D1 {F.D1}・S_TW {F.S_TW}）")
    res = {}
    t0 = time.time()
    res["a"], cf = m_a()
    res["b"], tw = m_b()
    res["c"] = m_c(cf, tw)
    res["d"] = m_d()
    print(f"  [{time.time() - t0:.1f} s]")
    print("まとめ: " + "  ".join(f"M-{k} {'通過' if v else '不合格'}" for k, v in res.items()))
    sys.exit(0 if all(res.values()) else 1)


if __name__ == "__main__":
    main()
