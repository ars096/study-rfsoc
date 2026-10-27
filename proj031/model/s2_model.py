#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj030 — レーン FFT の 2-for-1（実のレーン 2 本を複素の IP 1 個に）を 2G-4 の鎖で確かめる（README の M-1）。

  python3 s2_model.py        # M-1 a〜c・M-2 a〜b（数秒）。成否は最後の「まとめ」の行で読む

鎖の定義は proj027 の model/g24_fixed.py（写し）。変えるのはレーン FFT の出口だけ:
  z_q = y_q + j·y_(q+8)（q = 0..7）→ Z_q = rint(DFT_4096(z_q))（IP の行動模型と同じ rint）
  2·Y_q[k]     = Z_q[k] + conj Z_q[−k]       = (Zr[k] + Zr[−k]) + j(Zi[k] − Zi[−k])
  2·Y_(q+8)[k] = −j(Z_q[k] − conj Z_q[−k])  = (Zi[k] + Zi[−k]) + j(Zr[−k] − Zr[k])
  （加減算だけ。½ は捨てず、2Y を鎖に入れて cmul の SH を 18 → 19 にする。Z の目盛りは今と同じ）

(B) の鎖（M-2、README の P-2・P-3）: そろった行 r ∈ [0, 2048] だけを流す。
  2Y を 27 bit に飽和（cmul の A 口）→ V = cmul(2Y, w[p][r], SH 19) → 16 点 DFT の 16 出口 Z[k2]（k2 = 0..15）→ q = sat18(Z >>> SHIFT)
  k2 0..7 は行 r の銀行 k2（ch r + 4096·k2）。k2 8..15 は共役で行 4096 − r の銀行 15 − k2（ch 65536 − r − 4096·k2）。
  r = 0・2048 は k2 0..7 だけ（8..15 は同じ ch の重複）。1 フレームに 32,768 ch を 1 回ずつ
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
    return sep_Z(np.rint(Z.real).astype(np.int64), np.rint(Z.imag).astype(np.int64), partner)


def sep_Z(Zr, Zi, partner=neg):
    """IP 8 個の出口 Z（re, im、(8, M)、k の順）→ 2Y（re, im、(16, M)）。s2_sep の定義。"""
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


YW = 27                   # 鎖の入口（cmul の A 口）


def sat(v, w):
    lo, hi = -(1 << (w - 1)), (1 << (w - 1)) - 1
    return np.clip(v, lo, hi), int(np.sum((v < lo) | (v > hi)))


def dft16_full(Vr, Vi):
    """V（(16, R)）→ Z（(16, R)、k2 = 0..15）。g24_fixed.chain_Y の dft16 を d = 0..3 に広げたもの（dft16f と同じ値）。"""
    R = Vr.shape[1]
    Vr4, Vi4 = Vr.reshape(4, 4, R), Vi.reshape(4, 4, R)
    Ur = np.zeros((4, 4, R), dtype=np.int64)
    Ui = np.zeros((4, 4, R), dtype=np.int64)
    for cc in range(4):
        for a in range(4):
            er, ei = F.J4[(a * cc) % 4]
            Ur[:, cc] += er * Vr4[a] - ei * Vi4[a]
            Ui[:, cc] += er * Vi4[a] + ei * Vr4[a]
    wr16, wi16 = F.w16_q()
    Tr, Ti = np.zeros_like(Ur), np.zeros_like(Ui)
    for b in range(4):
        for cc in range(4):
            Tr[b, cc], Ti[b, cc] = F.cmul_q(Ur[b, cc], Ui[b, cc], wr16[b * cc], wi16[b * cc], 16)
    Zr = np.zeros((16, R), dtype=np.int64)
    Zi = np.zeros((16, R), dtype=np.int64)
    for cc in range(4):
        for d in range(4):
            for b in range(4):
                er, ei = F.J4[(b * d) % 4]
                Zr[cc + 4 * d] += er * Tr[b, cc] - ei * Ti[b, cc]
                Zi[cc + 4 * d] += er * Ti[b, cc] + ei * Tr[b, cc]
    return Zr, Zi


def chain_s2(Y2r, Y2i, twr, twi, rows=None):
    """2Y（(16, M)）の行 rows（既定 0..2048）→ Z16（(16, R)）・2Y の飽和の数。"""
    if rows is None:
        rows = np.arange(F.M // 2 + 1)
    ar, n1 = sat(Y2r[:, rows], YW)
    ai, n2 = sat(Y2i[:, rows], YW)
    Vr, Vi = F.cmul_q(ar, ai, twr[:, rows], twi[:, rows], 19)
    Zr, Zi = dft16_full(Vr, Vi)
    return Zr, Zi, n1 + n2


def power_s2(Zr, Zi, twr, twi, shift):
    """IP 8 個の出口 Z（(8, M)）→ 積分器の 1 フレームぶんの電力 pw[b, k1]（ch k1 + 4096·b、(8, M)）と、書いた q の飽和の数。
    s2_sep → s2_chain → s2_q の定義（行 r の銀行 b = k2 b、行 4096 − r の銀行 b = k2 15 − b、r = 0・2048 は 8 個だけ）。"""
    Y2r, Y2i = sep_Z(Zr, Zi)
    rows = np.arange(F.M // 2 + 1)
    Qr, Qi, _ = chain_s2(Y2r, Y2i, twr, twi, rows)
    lo, hi = -(1 << 17), (1 << 17) - 1
    qr, qi = Qr >> shift, Qi >> shift
    st = (qr < lo) | (qr > hi) | (qi < lo) | (qi > hi)
    qr, qi = np.clip(qr, lo, hi), np.clip(qi, lo, hi)
    p16 = qr * qr + qi * qi
    pw = np.zeros((8, F.M), dtype=np.int64)
    pw[:, rows] = p16[:8]
    mid = rows[1:-1]
    pw[:, F.M - mid] = p16[15 - np.arange(8)][:, 1:-1]
    nsat = int(st[:8].sum() + st[8:, 1:-1].sum())
    return pw, nsat


def to_ch(rows, Zr, Zi, bank_err=False):
    """行 r の Z16 → ch ごとの Z（共役で戻す、長さ 32768）と、ch ごとの書かれた回数。bank_err は陽性対照（k2 − 8）。"""
    N2 = F.N // 2
    Zc = np.zeros(N2, dtype=np.complex128)
    cnt = np.zeros(N2, dtype=np.int64)
    for j, r in enumerate(rows):
        for k2 in range(16):
            if k2 < 8:
                c, z = r + F.M * k2, Zr[k2, j] + 1j * Zi[k2, j]
            else:
                if r in (0, F.M // 2):
                    continue
                b = (k2 - 8) if bank_err else (15 - k2)
                c, z = (F.M - r) + F.M * b, Zr[k2, j] - 1j * Zi[k2, j]
            Zc[c] += z
            cnt[c] += 1
    return Zc, cnt


def m2_a(cf, tw):
    """(B) の鎖の全体: 32,768 ch が 1 回ずつ・浮動小数点と ε（M-1b の線）・今の鎖の電力との差。陽性対照は銀行の取り違え。"""
    N = F.N
    pr, pi = tw
    rng = np.random.default_rng(8)
    c0 = 20000
    n = np.arange(5 * N)
    x = np.clip(np.round(1000 * np.cos(2 * np.pi * c0 * n / N) + rng.normal(0, 100, 5 * N)), -8191, 8191).astype(np.int64)
    y, _ = F.pfb_int(x, cf)
    yfl = pfb_float(x.astype(np.float64), design(N), N)
    rows = np.arange(F.M // 2 + 1)
    ok = True
    for name, berr in (("(B) の鎖", False), ("陽性対照（銀行 k2 − 8）", True)):
        en = ed = 0.0
        dcw = []
        cover = True
        nsat = 0
        dp = []
        for f in (3, 4):
            Y2r, Y2i = lane_fft_s2(y[f])
            Zr, Zi, ns = chain_s2(Y2r, Y2i, pr, pi)
            nsat += ns
            Zc, cnt = to_ch(rows, Zr, Zi, berr)
            cover &= bool(np.all(cnt == 1))
            Zc = Zc * 4.0
            Xf = core_fft(yfl[f])
            mask = np.abs(np.arange(N // 2) - c0) > 3
            en += np.sum(np.abs(Zc - Xf)[mask] ** 2)
            ed += np.sum(np.abs(Xf)[mask] ** 2)
            dcw.append(10 * np.log10(np.abs(Zc[c0]) ** 2 / np.abs(Xf[c0]) ** 2))
            # 今の鎖（16 レーン・SH 18・8 出口）の Z との差（SHIFT の前、LSB）
            Z0r, Z0i = F.chain_frame(y[f], pr, pi)
            Z0 = (Z0r + 1j * Z0i).reshape(-1)
            dp.append(np.abs(Zc / 4.0 - Z0).max())
        eps = en / ed
        print(f"  M-2a {name}: ch の書き込み 1 回ずつ {cover}・ε {eps:.2e}・CW の差 {max(dcw, key=abs):+.4f} dB・"
              f"今の鎖の Z との差 最大 {max(dp):.1f} LSB・2Y の飽和 {nsat}")
        if berr:
            ok &= eps > 1e-2
        else:
            ok &= cover and eps <= 2e-5 and abs(max(dcw, key=abs)) < 0.01 and nsat == 0
    print(f"  → M-2a {'通過' if ok else '不合格'}（1 回ずつ・ε ≦ 2e-5・CW < 0.01 dB・飽和 0、陽性対照 ε > 1e-2）")
    return ok


def ready_rows():
    """1 フレームの拍 n ごとに、そろう行 r（無ければ −1）。"""
    br = F.bitrev(np.arange(F.M), F.KB)
    out = np.full(F.M, -1, dtype=np.int64)
    for n in range(F.M):
        h = 1 << (n.bit_length() - 1) if n else 0
        if n >= 2 and n < h + h // 2:
            continue
        k = int(br[n])
        out[n] = min(k, F.M - k)
    return out


def m2_b(nf=6):
    """均しの待ち行列: そろった拍に行の書き込みを 1 本か 2 本積み、1 拍に 1 本出す（積分器の RMW）。最大の深さ・遅れ・同じ行の間隔。"""
    rr = ready_rows()
    q = []
    depth = lat = 0
    last = {}
    dmin = None
    t_out = 0
    for t in range(nf * F.M):
        r = rr[t % F.M]
        if r >= 0:
            q.append((r, t))
            if r not in (0, F.M // 2):
                q.append((F.M - r, t))
        depth = max(depth, len(q))
        if q:
            row, t0 = q.pop(0)
            lat = max(lat, t - t0)
            if row in last:
                d = t - last[row]
                dmin = d if dmin is None else min(dmin, d)
            last[row] = t
            t_out += 1
    print(f"  M-2b 待ち行列の最大 {depth} 本・積んでから出るまでの最大 {lat} 拍・同じ行の書き込みの間隔の最小 {dmin} 拍（{nf} フレーム、出た {t_out} 本）")
    ok = depth <= 1100 and dmin is not None and dmin >= 8
    print(f"  → M-2b {'通過' if ok else '不合格'}（深さ ≦ 1,100・同じ行の間隔 ≧ 8 拍 = 積分器の RMW の段より長い）")
    return ok


def main():
    print(f"M-1 2-for-1（2G-4 の鎖: N {F.N}・M {F.M}・IP {NQ} 個、組は p と p + 8）")
    res = {}
    t0 = time.time()
    res["a"] = m_a()
    cf = F.coef_interp()
    res["b"] = m_b(cf, F.tw_prod())
    res["c"] = m_c()
    res["2a"] = m2_a(cf, F.tw_prod())
    res["2b"] = m2_b()
    print(f"  [{time.time() - t0:.1f} s]")
    print("まとめ: " + "  ".join(f"M-{k if k[0] == '2' else '1' + k} {'通過' if v else '不合格'}" for k, v in res.items()))
    sys.exit(0 if all(res.values()) else 1)


if __name__ == "__main__":
    main()
