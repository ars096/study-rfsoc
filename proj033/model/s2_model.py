#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj033 — レーン FFT の 2-for-1 を 2G-1-Fast の鎖（N 262144・M 16384）で確かめる（README の M-1・M-2）。

  python3 s2_model.py        # M-1 a〜c・M-2 a〜b（1 分ほど）。成否は最後の「まとめ」の行で読む

proj030（1a3e733）の model/s2_model.py を 2G-1 の寸法に直したもの。鎖の定義は proj024-m0 の model/g21_fixed.py（写し）。
変えるのはレーン FFT の出口と鎖の入口だけ:
  z_q = y_q + j·y_(q+8)（q = 0..7）→ Z_q = rint(DFT_16384(z_q))（IP の行動模型と同じ rint。Z は 30 bit）
  2·Y_q[k]     = Z_q[k] + conj Z_q[−k]       = (Zr[k] + Zr[−k]) + j(Zi[k] − Zi[−k])
  2·Y_(q+8)[k] = −j(Z_q[k] − conj Z_q[−k])  = (Zi[k] + Zi[−k]) + j(Zr[−k] − Zr[k])
鎖の入口（2Y、31 bit）の形は 2 つを比べる（README の M-1b）:
  (i)  2Y を D 3 bit 丸める → 27 bit（飽和は起きない）→ cmul SH 18
  (ii) 2Y を D 2 bit 丸める → 27 bit に飽和 → cmul SH 19（proj030 の 2G-4 と同じ形）
どちらも V の目盛りは今（Y を 2 bit 丸めて SH 18）と同じ。

(B) の鎖（M-2）: そろった行 r ∈ [0, M/2] だけを流す。入口 → V = cmul(·, w[p][r]) → 16 点 DFT の 16 出口 Z[k2] → q = sat18(Z >>> SHIFT)。
  k2 0..7 は行 r の銀行 k2（ch r + M·k2）。k2 8..15 は共役で行 M − r の銀行 15 − k2（ch N − r − M·k2）。
  r = 0・M/2 は k2 0..7 だけ。1 フレームに 131,072 ch を 1 回ずつ
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from g2_model import core_fft, design, pfb_float  # noqa: E402
import g21_fixed as F  # noqa: E402

NQ = F.LANES // 2         # 8（IP の数）
KB = 14                   # log2 M
YW = 27                   # 鎖の入口（cmul の A 口）
ZW = 30                   # IP の出口（複素の入力、unscaled）
FORMS = {"(i)": (3, 18), "(ii)": (2, 19)}     # 2Y の丸めの bit 数 D・cmul の SH


def neg(k):
    return (-k) % F.M


def lane_ip(yf):
    """1 フレームの y（長さ N）→ IP 8 個の出口 Z（re, im、(8, M)、k の順）。"""
    yp = yf.reshape(F.M, F.LANES).T.astype(np.float64)
    Z = np.fft.fft(yp[:NQ] + 1j * yp[NQ:], axis=1)
    return np.rint(Z.real).astype(np.int64), np.rint(Z.imag).astype(np.int64)


def sep_Z(Zr, Zi, partner=neg):
    """IP 8 個の出口 Z（(8, M)）→ 2Y（re, im、(16, M)）。s2_sep の定義。partner は −k の番地（陽性対照で替える）。"""
    kp = partner(np.arange(F.M))
    Y2r = np.concatenate([Zr + Zr[:, kp], Zi + Zi[:, kp]])
    Y2i = np.concatenate([Zi - Zi[:, kp], Zr[:, kp] - Zr])
    return Y2r, Y2i


def sat(v, w):
    lo, hi = -(1 << (w - 1)), (1 << (w - 1)) - 1
    return np.clip(v, lo, hi), int(np.sum((v < lo) | (v > hi)))


def entry(Y2r, Y2i, form):
    """2Y → cmul の A 口（27 bit）と飽和の数・cmul の SH。"""
    d, sh = FORMS[form]
    ar, n1 = sat(F.rshift_round(Y2r, d), YW)
    ai, n2 = sat(F.rshift_round(Y2i, d), YW)
    return ar, ai, n1 + n2, sh


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


def test_input():
    """proj024 M-8c と同じ入力: CW 1000 LSB @ ch 40000 ＋ 雑音 σ 100、5 フレーム。"""
    N = F.N
    rng = np.random.default_rng(8)
    c0 = 40000
    n = np.arange(5 * N)
    x = np.clip(np.round(1000 * np.cos(2 * np.pi * c0 * n / N) + rng.normal(0, 100, 5 * N)), -8191, 8191).astype(np.int64)
    return x, c0


def m_b(y, ysat, yfl, c0, tw):
    """鎖の全体: 今（16 レーン・Y 2 bit・SH 18）と 2-for-1 の (i)・(ii) を同じ入力で浮動小数点と比べる（proj024 M-8c の判定）。"""
    N = F.N
    pr, pi = tw
    mask = np.abs(np.arange(N // 2) - c0) > 3
    zmax = 0
    out = {}
    cases = [("今（16 レーン）", None, neg)] + [(f"2-for-1 {k}", k, neg) for k in FORMS] + \
            [("陽性対照（相手を −k−1、(i)）", "(i)", lambda k: (-k - 1) % F.M)]
    for name, form, partner in cases:
        en = ed = 0.0
        dcw = []
        st = {}
        nsat = 0
        y2max = 0
        for f in (3, 4):
            if form is None:
                Yr, Yi = F.lane_fft(y[f])
                Zr, Zi = F.chain_Y(Yr, Yi, pr, pi, d1=2, sh=18, stats=st)
            else:
                Zr0, Zi0 = lane_ip(y[f])
                zmax = max(zmax, int(np.abs(Zr0).max()), int(np.abs(Zi0).max()))
                Y2r, Y2i = sep_Z(Zr0, Zi0, partner)
                y2max = max(y2max, int(np.abs(Y2r).max()), int(np.abs(Y2i).max()))
                ar, ai, ns, sh = entry(Y2r, Y2i, form)
                nsat += ns
                Zr, Zi = F.chain_Y(ar, ai, pr, pi, d1=0, sh=sh, stats=st)
            Xf = core_fft(yfl[f])
            Zc = (Zr + 1j * Zi).reshape(-1) * 16.0
            en += np.sum(np.abs(Zc - Xf)[mask] ** 2)
            ed += np.sum(np.abs(Xf)[mask] ** 2)
            dcw.append(10 * np.log10(np.abs(Zc[c0]) ** 2 / np.abs(Xf[c0]) ** 2))
        out[name] = (en / ed, max(dcw, key=abs), st, nsat, y2max)
        extra = "" if form is None else f"・2Y の最大 {y2max:,}・入口の飽和 {nsat}"
        print(f"  b {name}: 雑音の ch の ε {en / ed:.2e}・CW の差 {max(dcw, key=abs):+.4f} dB・"
              f"最大 Y(入口) {st['Y']:,}・V {st['V']:,}・U {st['U']:,}・Z {st['Z']:,}{extra}")
    e0, _, s0, _, _ = out["今（16 レーン）"]
    ok = ysat == 0 and abs(e0 / 8.7e-6 - 1) < 0.05 and zmax < (1 << (ZW - 1))
    for k in FORMS:
        e1, d1, s1, ns, _ = out[f"2-for-1 {k}"]
        zr = s1["Z"] / s0["Z"]
        ok &= 0.95 * e0 <= e1 <= e0 and abs(d1) < 0.01 and abs(zr - 1) < 0.01 and ns == 0
        print(f"     {k}: ε の比（/ 今）{e1 / e0:.4f}・Z の最大の比 {zr:.4f}")
    ep = out["陽性対照（相手を −k−1、(i)）"][0]
    ok &= ep > 1e-2
    ei, eii = out["2-for-1 (i)"][0], out["2-for-1 (ii)"][0]
    diff = (ei - eii) / ei
    choice = "(i)" if diff < 0.02 else "(ii)"
    print(f"     IP の出口 Z の最大 {zmax:,}（{ZW} bit: < 2^{ZW - 1} = {1 << (ZW - 1):,}）・y の飽和 {ysat}・"
          f"(ii) が (i) より良い分 {100 * diff:+.2f} %（2 % 未満なら (i)）→ **{choice}**")
    print(f"  → b {'通過' if ok else '不合格'}（今 ε ≒ 8.7e-6 ±5 %・比 0.95〜1.00・CW < 0.01 dB・Z の比 ±1 %・飽和 0・Z < 2^{ZW - 1}、陽性対照 ε > 1e-2）")
    return ok, choice


def m_c():
    """bit 反転順の出口で、相手（−k）を待つ値の数（溜めの深さ）。"""
    n = np.arange(F.M)
    k = F.bitrev(n, KB)
    wait = set()
    wmax = 0
    ready = 0
    for i in range(F.M):
        kk, kp = int(k[i]), int(neg(k[i]))
        if kp == kk or kp in wait:
            wait.discard(kp)
            ready += 1
        else:
            wait.add(kk)
        wmax = max(wmax, len(wait))
    ok = wmax == F.M // 4
    print(f"  c 待つ値の最大 {wmax}（IP 1 個あたり）・組がそろう拍 {ready} / {F.M}")
    print(f"  → c {'通過' if ok else '不合格'}（待つ値の最大 = M/4 = {F.M // 4}）")
    return ok


def dft16_full(Vr, Vi):
    """V（(16, R)）→ Z（(16, R)、k2 = 0..15）。g21_fixed.chain_Y の dft16 を d = 0..3 に広げたもの（dft16f と同じ値）。"""
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


def chain_s2(Y2r, Y2i, twr, twi, form, rows=None):
    """2Y（(16, M)）の行 rows（既定 0..M/2）→ Z16（(16, R)）・入口の飽和の数。"""
    if rows is None:
        rows = np.arange(F.M // 2 + 1)
    ar, ai, ns, sh = entry(Y2r[:, rows], Y2i[:, rows], form)
    Vr, Vi = F.cmul_q(ar, ai, twr[:, rows], twi[:, rows], sh)
    Zr, Zi = dft16_full(Vr, Vi)
    return Zr, Zi, ns


def power_s2(Zr, Zi, twr, twi, shift, form):
    """IP 8 個の出口 Z（(8, M)）→ 積分器の 1 フレームぶんの電力 pw[b, k1]（ch k1 + M·b、(8, M)）と、書いた q の飽和の数。
    s2_sep → s2_chain → s2_q の定義（行 r の銀行 b = k2 b、行 M − r の銀行 b = k2 15 − b、r = 0・M/2 は 8 個だけ）。RTL の sim の正解に使う。"""
    Y2r, Y2i = sep_Z(Zr, Zi)
    rows = np.arange(F.M // 2 + 1)
    Qr, Qi, _ = chain_s2(Y2r, Y2i, twr, twi, form, rows)
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
    """行 r の Z16 → ch ごとの Z（共役で戻す、長さ N/2）と、ch ごとの書かれた回数。bank_err は陽性対照（k2 − 8）。"""
    N2 = F.N // 2
    Zc = np.zeros(N2, dtype=np.complex128)
    cnt = np.zeros(N2, dtype=np.int64)
    ends = (rows == 0) | (rows == F.M // 2)
    for k2 in range(16):
        if k2 < 8:
            c, z = rows + F.M * k2, Zr[k2] + 1j * Zi[k2]
        else:
            b = (k2 - 8) if bank_err else (15 - k2)
            c, z = (F.M - rows) + F.M * b, Zr[k2] - 1j * Zi[k2]
            c, z = c[~ends], z[~ends]
        np.add.at(Zc, c, z)
        np.add.at(cnt, c, 1)
    return Zc, cnt


def m2_a(y, yfl, c0, tw, form):
    """(B) の鎖の全体: 131,072 ch が 1 回ずつ・浮動小数点と ε・今の鎖の Z との差・power_s2 が to_ch と同じ電力。陽性対照は銀行の取り違え。"""
    N = F.N
    pr, pi = tw
    rows = np.arange(F.M // 2 + 1)
    mask = np.abs(np.arange(N // 2) - c0) > 3
    ok = True
    for name, berr in ((f"(B) の鎖 {form}", False), ("陽性対照（銀行 k2 − 8）", True)):
        en = ed = 0.0
        dcw = []
        cover = True
        nsat = 0
        dp = []
        pw_ok = True
        for f in (3, 4):
            Zr0, Zi0 = lane_ip(y[f])
            Y2r, Y2i = sep_Z(Zr0, Zi0)
            Zr, Zi, ns = chain_s2(Y2r, Y2i, pr, pi, form)
            nsat += ns
            Zq, cnt = to_ch(rows, Zr, Zi, berr)
            cover &= bool(np.all(cnt == 1))
            Zc = Zq * 16.0
            Xf = core_fft(yfl[f])
            en += np.sum(np.abs(Zc - Xf)[mask] ** 2)
            ed += np.sum(np.abs(Xf)[mask] ** 2)
            dcw.append(10 * np.log10(np.abs(Zc[c0]) ** 2 / np.abs(Xf[c0]) ** 2))
            Z0r, Z0i = F.chain_frame(y[f], pr, pi)
            dp.append(np.abs(Zq - (Z0r + 1j * Z0i).reshape(-1)).max())
            if not berr:
                # power_s2（RTL の sim の正解）が ch ごとの Z の電力と同じ並びになっているか（SHIFT 7）
                pw, _ = power_s2(Zr0, Zi0, pr, pi, 7, form)
                # 鏡の側の ch（k1 > M/2）は共役で戻してあるので、RTL と同じく共役する前の値（虚部の符号を戻す）を切り捨てる
                sgn = np.where(np.arange(F.N // 2) % F.M > F.M // 2, -1, 1)
                qr = np.clip(np.round(Zq.real).astype(np.int64) >> 7, -(1 << 17), (1 << 17) - 1)
                qi = np.clip((sgn * np.round(Zq.imag).astype(np.int64)) >> 7, -(1 << 17), (1 << 17) - 1)
                pw_ok &= bool(np.array_equal(pw, (qr * qr + qi * qi).reshape(8, F.M)))
        eps = en / ed
        print(f"  M-2a {name}: ch の書き込み 1 回ずつ {cover}・ε {eps:.2e}・CW の差 {max(dcw, key=abs):+.4f} dB・"
              f"今の鎖の Z との差 最大 {max(dp):.1f} LSB・入口の飽和 {nsat}" + ("" if berr else f"・power_s2 の並び {pw_ok}"))
        if berr:
            ok &= eps > 1e-2
        else:
            ok &= cover and eps <= 2e-5 and abs(max(dcw, key=abs)) < 0.01 and nsat == 0 and pw_ok
    print(f"  → M-2a {'通過' if ok else '不合格'}（1 回ずつ・ε ≦ 2e-5・CW < 0.01 dB・飽和 0・power_s2 の並び、陽性対照 ε > 1e-2）")
    return ok


def ready_rows():
    """1 フレームの拍 n ごとに、そろう行 r（無ければ −1）。"""
    br = F.bitrev(np.arange(F.M), KB)
    out = np.full(F.M, -1, dtype=np.int64)
    for n in range(F.M):
        h = 1 << (n.bit_length() - 1) if n else 0
        if n >= 2 and n < h + h // 2:
            continue
        k = int(br[n])
        out[n] = min(k, F.M - k)
    return out


def m2_b(nf=6):
    """均しの待ち行列: そろった拍に組（行 1 本か 2 本）を 1 項目として積み、1 拍に行を 1 本出す（積分器の RMW）。
    行の単位と組の単位の最大の深さ・遅れ・同じ行の間隔。"""
    rr = ready_rows()
    q = []                    # 項目 = [行の並び, 積んだ拍]
    rmax = imax = imax2 = lat = 0
    last = {}
    dmin = None
    nout = 0
    for t in range(nf * F.M):
        r = rr[t % F.M]
        if r >= 0:
            q.append([[r] if r in (0, F.M // 2) else [r, F.M - r], t])
        rmax = max(rmax, sum(len(it[0]) for it in q))
        imax = max(imax, len(q))
        if q:
            it = q[0]
            row = it[0].pop(0)
            lat = max(lat, t - it[1])
            if not it[0]:
                q.pop(0)
            imax2 = max(imax2, len(q))
            if row in last:
                d = t - last[row]
                dmin = d if dmin is None else min(dmin, d)
            last[row] = t
            nout += 1
    left = sum(len(it[0]) for it in q)
    print(f"  M-2b 待ち行列の最大 行 {rmax} 本・組 {imax} 項目（その拍の取り出しの後 {imax2}）・積んでから出るまでの最大 {lat} 拍・"
          f"同じ行の書き込みの間隔の最小 {dmin} 拍（{nf} フレーム、出た {nout} 本 ＋ 残り {left} 本）")
    ok = rmax <= 4400 and dmin is not None and dmin >= 8 and nout + left == nf * F.M
    print(f"  → M-2b {'通過' if ok else '不合格'}（深さ ≦ 4,400・同じ行の間隔 ≧ 8 拍・出た本数 ＋ 残り = フレーム × M）")
    return ok


def main():
    print(f"M-1 2-for-1（2G-1-Fast の鎖: N {F.N}・M {F.M}・IP {NQ} 個、組は p と p + 8）")
    res = {}
    t0 = time.time()
    res["1a"] = m_a()
    cf = F.coef_interp()
    tw = F.tw_prod()
    x, c0 = test_input()
    y, ysat = F.pfb_int(x, cf)
    yfl = pfb_float(x.astype(np.float64), design(F.N), F.N)
    res["1b"], form = m_b(y, ysat, yfl, c0, tw)
    res["1c"] = m_c()
    res["2a"] = m2_a(y, yfl, c0, tw, form)
    res["2b"] = m2_b()
    print(f"  [{time.time() - t0:.1f} s]")
    print("まとめ: " + "  ".join(f"M-{k} {'通過' if v else '不合格'}" for k, v in res.items()) + f"（鎖の入口 {form}）")
    sys.exit(0 if all(res.values()) else 1)


if __name__ == "__main__":
    main()
