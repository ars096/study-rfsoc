#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj030 — レーン FFT の 2-for-1（実のレーン 2 本を複素の IP 1 個に）を 2G-4 の鎖で確かめる（README の M-1）。

  python3 s2_model.py        # a〜c（1 分ほど）。成否は最後の「まとめ」の行で読む

鎖の定義は proj027 の model/g24_fixed.py（写し）。変えるのはレーン FFT の出口だけ:
  z_q = y_q + j·y_(q+8)（q = 0..7）→ Z_q = rint(DFT_4096(z_q))（IP の行動模型と同じ rint）
  2·Y_q[k]     = Z_q[k] + conj Z_q[−k]       = (Zr[k] + Zr[−k]) + j(Zi[k] − Zi[−k])
  2·Y_(q+8)[k] = −j(Z_q[k] − conj Z_q[−k])  = (Zi[k] + Zi[−k]) + j(Zr[−k] − Zr[k])
  （加減算だけ。½ は捨てず、2Y を鎖に入れて cmul の SH を 18 → 19 にする。Z の目盛りは今と同じ）
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from g2_model import core_fft, design, pfb_float  # noqa: E402
import g24_fixed as F  # noqa: E402

NQ = F.LANES // 2         # 8（IP の数）


def neg(k):
    return (-k) % F.M


def lane_fft_s2(yf, partner=neg):
    """1 フレームの y（長さ N）→ 2Y（re, im、(16, M)）。partner は −k の番地（陽性対照で替える）。"""
    yp = yf.reshape(F.M, F.LANES).T.astype(np.float64)
    Z = np.fft.fft(yp[:NQ] + 1j * yp[NQ:], axis=1)
    Zr, Zi = np.rint(Z.real).astype(np.int64), np.rint(Z.imag).astype(np.int64)
    kp = partner(np.arange(F.M))
    Y2r = np.concatenate([Zr + Zr[:, kp], Zi + Zi[:, kp]])
    Y2i = np.concatenate([Zi - Zi[:, kp], Zr[:, kp] - Zr])
    return Y2r, Y2i


def m_a():
    """式: 分けた Y が 16 レーンそれぞれの DFT と浮動小数点の丸めの大きさで一致する。陽性対照は共役なし。"""
    rng = np.random.default_rng(1)
    y = rng.normal(0, 1000, (F.LANES, F.M))
    Yref = np.fft.fft(y, axis=1)
    Z = np.fft.fft(y[:NQ] + 1j * y[NQ:], axis=1)
    Zm = Z[:, neg(np.arange(F.M))]
    res = {}
    for name, Zc in (("分け", np.conj(Zm)), ("陽性対照（共役なし）", Zm)):
        Y = np.concatenate([(Z + Zc) / 2, (Z - Zc) / 2j])
        res[name] = np.abs(Y - Yref).max() / np.abs(Yref).max()
        print(f"  a {name}: 相対の最大差 {res[name]:.2e}")
    ok = res["分け"] < 1e-12 and res["陽性対照（共役なし）"] > 1e-2
    print(f"  → a {'通過' if ok else '不合格'}（< 1e-12、陽性対照 > 1e-2）")
    return ok


def m_b(cf, tw):
    """鎖の全体: 今（16 レーンをそれぞれ rint）と 2-for-1（2Y・SH 19）を同じ入力で浮動小数点と比べる（proj027 M-c と同じ入力・判定）。"""
    N = F.N
    pr, pi = tw
    rng = np.random.default_rng(8)
    c0 = 20000
    nf = 5
    n = np.arange(nf * N)
    x = np.clip(np.round(1000 * np.cos(2 * np.pi * c0 * n / N) + rng.normal(0, 100, nf * N)), -8191, 8191).astype(np.int64)
    y, ysat = F.pfb_int(x, cf)
    yfl = pfb_float(x.astype(np.float64), design(N), N)
    cases = (
        ("今（16 レーン）", lambda yf: F.lane_fft(yf), 18),
        ("2-for-1（2Y・SH 19）", lambda yf: lane_fft_s2(yf), 19),
        ("陽性対照（相手を −k−1）", lambda yf: lane_fft_s2(yf, lambda k: (-k - 1) % F.M), 19),
    )
    out = {}
    for name, fn, sh in cases:
        en = ed = 0.0
        dcw = []
        st = {}
        for f in (3, 4):
            Yr, Yi = fn(y[f])
            Zr, Zi = F.chain_Y(Yr, Yi, pr, pi, d1=0, sh=sh, stats=st)
            Xf = core_fft(yfl[f])
            Zc = (Zr + 1j * Zi).reshape(-1) * 4.0
            mask = np.abs(np.arange(N // 2) - c0) > 3
            en += np.sum(np.abs(Zc - Xf)[mask] ** 2)
            ed += np.sum(np.abs(Xf)[mask] ** 2)
            dcw.append(10 * np.log10(np.abs(Zc[c0]) ** 2 / np.abs(Xf[c0]) ** 2))
        out[name] = (en / ed, max(dcw, key=abs), st)
        print(f"  b {name}: 雑音の ch の ε {en / ed:.2e}・CW の差 {max(dcw, key=abs):+.4f} dB・"
              f"最大 Y {st['Y']:,}・V {st['V']:,}・U {st['U']:,}・Z {st['Z']:,}")
    e0, _, s0 = out["今（16 レーン）"]
    e1, d1, s1 = out["2-for-1（2Y・SH 19）"]
    ep = out["陽性対照（相手を −k−1）"][0]
    zr = s1["Z"] / s0["Z"]
    ok = (ysat == 0 and 0.85 * e0 <= e1 <= e0 and abs(d1) < 0.01 and s1["Y"] < (1 << 26)
          and abs(zr - 1) < 0.01 and ep > 1e-2)
    print(f"     ε の比（2-for-1 / 今）{e1 / e0:.3f}・Z の最大の比 {zr:.4f}・2Y の最大 {s1['Y']:,}（cmul の A 27 bit: < 2^26 = {1 << 26:,}）・y の飽和 {ysat}")
    print(f"  → b {'通過' if ok else '不合格'}（ε の比 0.85〜1.00・CW < 0.01 dB・2Y < 2^26・Z の比 ±1 %・陽性対照 ε > 1e-2）")
    return ok


def m_c():
    """bit 反転順の出口で、相手（−k）を待つ値の数と、組がそろう拍の並び（鎖へ渡す形を決める材料。判定は待ちの最大だけ）。"""
    n = np.arange(F.M)
    k = F.bitrev(n, F.KB)
    pos = np.empty(F.M, dtype=np.int64)
    pos[k] = n
    wait = set()
    wmax = 0
    ready = np.zeros(F.M, dtype=np.int64)     # その拍でそろう行の数（k と −k で 1 組。自己共役は 1 拍で 1 組）
    for i in range(F.M):
        kk, kp = int(k[i]), int(neg(k[i]))
        if kp == kk:
            ready[i] = 1
        elif kp in wait:
            wait.remove(kp)
            ready[i] = 1
        else:
            wait.add(kk)
        wmax = max(wmax, len(wait))
    dist = np.abs(pos - pos[neg(np.arange(F.M))]).max()
    # 組がそろう拍の最長の連続と、「行を 1 拍に 1 本」で 2 行（k と −k）ずつ出すときの待ち行列の最大（定常、2 フレーム回す）
    run = best = 0
    for r in ready:
        run = run + 1 if r else 0
        best = max(best, run)
    q = qmax = 0
    for r in np.concatenate([ready, ready, ready]):
        q += 2 * r - (1 if q + 2 * r > 0 else 0)
        qmax = max(qmax, q)
    print(f"  c 相手との距離の最大 {dist} 拍・待つ値の最大 {wmax}（IP 1 個あたり）・組がそろう拍 {int(ready.sum())} / {F.M}（最長の連続 {best} 拍）")
    print(f"     「2 行ずつ・1 拍に 1 行」で鎖へ出すときの行の待ち行列の最大 {qmax} 行")
    ok = wmax == F.M // 4
    print(f"  → c {'通過' if ok else '不合格'}（待つ値の最大 = M/4 = {F.M // 4}）")
    return ok


def main():
    print(f"M-1 2-for-1（2G-4 の鎖: N {F.N}・M {F.M}・IP {NQ} 個、組は p と p + 8）")
    res = {}
    t0 = time.time()
    res["a"] = m_a()
    cf = F.coef_interp()
    res["b"] = m_b(cf, F.tw_prod())
    res["c"] = m_c()
    print(f"  [{time.time() - t0:.1f} s]")
    print("まとめ: " + "  ".join(f"M-1{k} {'通過' if v else '不合格'}" for k, v in res.items()))
    sys.exit(0 if all(res.values()) else 1)


if __name__ == "__main__":
    main()
