#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj024 — 2G の模型（全帯域 2048 MHz を 1 × 262144 / 2 × 131072 / 4 × 65536 点の FFT で）。numpy だけ。

README の判定 M-1〜M-6 を数える。RTL を書く前の、式と語長と記憶の量の唯一の正。
原型・係数・ch の応答の物差しは proj022 の wide_model.py から写した（proj は自己完結にする。中身は同じ）。

2G の仕様（BITS.md の 3 行目）:
  ADC 1 / 2 / 4 本、各 ADC の出力 131072 / 65536 / 32768 ch（FFT 262144 / 131072 / 65536 点、実数の入力の半分）、
  df 15.625 / 31.25 / 62.5 kHz、dt 10.24 ms。1 フレーム = N / 16 ビート（64 / 32 / 16 µs）

式は SAM45-Wide（proj022・proj023）と同じ: PFB（T = 4）→ 16 レーン（a = 16m + p）→ レーン FFT（M = N / 16 点）
→ ひねり係数 W_N^(p·k1) → 16 点 DFT の k2 = 0..7 → ch c = k1 + M·k2。

案 R（1 本の bit で 1 / 2 / 4 をレジスタで切り替える）の「前段」（M-1b）:
  65536 点のコア（16 レーン × 4096 点）を 4 個持ち、N = r·Nc（r = 1, 2, 4、Nc = 65536）のとき r 個のコアで 1 本の FFT を作る。
    a_m[n] = W_N^(n·m) · Σ_{q=0..r−1} y[n + q·Nc] · W_r^(q·m)      n = 0..Nc−1、m = 0..r−1（周波数間引きの最初の段）
    コア m: a_m の Nc 点 FFT（複素の入力。16 レーンの分解の k2 = 0..7 だけ）→ X[r·k + m]（k < Nc/2）
  r·k + m < N/2 ⇔ k < Nc/2 なので、**各コアは今と同じく k2 = 0..7 だけを出せば全帯域の半分（実数の入力の全部）が揃う**。

使い方:
  python3 g2_model.py all        # M-1〜M-8（1〜2 分）
  python3 g2_model.py m1 | m2 | m3 | m4 | m5 | m6 | m7 | m8
"""
import sys
import time

import numpy as np

LANES = 16
T = 4
BETA = 5.0
BW = 1.198
CF = 16          # 係数の小数部
CW = 18          # 係数の bit 数
XW = 14          # 入力（ADC の 14 bit）
NC = 65536       # 案 R のコア 1 個の FFT の点数（16 レーン × 4096 点）
MODES = {1: 262144, 2: 131072, 4: 65536}         # ADC の本数 → 1 本の FFT の点数
FS = 4096e6
BEAT = 256e6
G = 524288       # 時刻の格子（2.048 ms）
BASE = 2621440   # 基本の単位（10.24 ms）
FINE_REF = dict(half=-3.00, ge1=-53.7, ge15=-58.0, ge3=-64.5, p04=-1.20, ripple=0.08, enbw=1.010)  # proj020 README

np.set_printoptions(linewidth=140)


# ---------------------------------------------------------------- 原型と係数（proj022 の wide_model.py と同じ）

def design(N, taps=T):
    """浮動小数点の原型（Σh² = N）。n₀ = (L−1)/2、左右対称（proj020・022 と同じ作り）。taps = 1 は矩形（h = 1）"""
    L = taps * N
    if taps == 1:
        return np.ones(N)
    n = np.arange(L, dtype=np.float64)
    n0 = (L - 1) / 2
    h = np.sinc(BW * (n - n0) / N) * np.kaiser(L, BETA)
    half = h[: L // 2]
    h = np.concatenate([half, half[::-1]])
    return h * np.sqrt(N / np.sum(h * h))


def quantize(h):
    c = np.round(h * (1 << CF)).astype(np.int64)
    assert c.max() < (1 << (CW - 1)) and c.min() >= -(1 << (CW - 1)), "係数が 18 bit に入らない"
    return c


def response_metrics(h, N, pad=4, span=24, fine=True):
    """h（L タップ）の ch の応答（δ は ch の単位、0 ch で 0 dB）と ENBW。proj022 と同じ測り方。
    fine = False は −3 dB 幅と ±0.4・0.5 ch を DTFT で直に測らず、FFT の格子で済ませる（長い h の時間を縮める）"""
    h = np.asarray(h, dtype=np.float64)
    L = len(h)
    nfft = L * pad
    H = np.fft.rfft(h, nfft)
    P = np.abs(H) ** 2
    P /= P[0]
    step = N / nfft
    d = np.arange(len(P)) * step
    keep = d <= span
    d, P = d[keep], P[keep]
    db = 10 * np.log10(np.maximum(P, 1e-300))
    s0 = np.sum(h) ** 2
    n = np.arange(L)

    def at(delta):
        return 10 * np.log10(np.abs(np.sum(h * np.exp(-2j * np.pi * delta * n / N))) ** 2 / s0)

    if fine:
        dd = np.linspace(0.45, 0.55, 101)
        pv = np.array([at(x) for x in dd])
        i = int(np.argmax(pv < -3.0103))
        w3 = 2 * (dd[i - 1] + (dd[i] - dd[i - 1]) * (pv[i - 1] + 3.0103) / (pv[i - 1] - pv[i]))
        half, p04 = at(0.5), at(0.4)
    else:
        half = np.interp(0.5, d, db)
        p04 = np.interp(0.4, d, db)
        i = int(np.argmax(db < -3.0103))
        w3 = 2 * (d[i - 1] + (d[i] - d[i - 1]) * (db[i - 1] + 3.0103) / (db[i - 1] - db[i]))
    # 1 ch より外の最大は、主ローブの裾（≧ 1 ch で単調に下がる区間）も含む
    grid = np.arange(0, 1, step)
    tot = np.zeros_like(grid)
    lin = 10 ** (db / 10)
    for k in range(-6, 7):
        tot += np.interp(np.abs(grid - k), d, lin, right=0.0)
    ripple = 10 * np.log10(tot.max() / tot.min())
    return dict(half=half, p04=p04, w3=w3,
                ge1=db[d >= 1.0].max(), ge15=db[d >= 1.5].max(), ge3=db[d >= 3.0].max(),
                ripple=ripple, enbw=N * np.sum(h * h) / np.sum(h) ** 2)


def fmt_resp(name, r):
    return (f"  {name:<30s} 0.5ch {r['half']:6.2f}  0.4ch {r['p04']:6.2f}  −3dB 幅 {r['w3']:.3f}  "
            f"≧1 {r['ge1']:6.1f}  ≧1.5 {r['ge15']:6.1f}  ≧3 {r['ge3']:6.1f}  和の波打ち {r['ripple']:.2f}  ENBW {r['enbw']:.3f}")


# ---------------------------------------------------------------- 分解（浮動小数点）

def pfb_float(x, h, N):
    """x（長さ N の倍数）→ 出力フレーム (nf, N)（r − 3 + t < 0 のタップは 0）。"""
    nf = len(x) // N
    xf = np.asarray(x[: nf * N], dtype=np.float64).reshape(nf, N)
    ht = np.asarray(h, dtype=np.float64).reshape(T, N)
    y = np.zeros((nf, N), dtype=np.result_type(xf, np.float64))
    for t in range(T):
        sh = T - 1 - t
        y[sh:] += ht[t] * xf[: nf - sh]
    return y


def core_fft(a, sign_err=False):
    """コア 1 個（16 レーン × M 点、複素の入力でよい）→ X[0 .. N/2 − 1]（k2 = 0..7 だけ）。"""
    N = len(a)
    M = N // LANES
    ap = a.reshape(M, LANES).T                        # ap[p, m] = a[16m + p]
    Y = np.fft.fft(ap, axis=1)                        # レーン FFT
    k1 = np.arange(M)
    p = np.arange(LANES)[:, None]
    s = +1 if sign_err else -1
    V = Y * np.exp(s * 2j * np.pi * p * k1 / N)       # ひねり係数
    k2 = np.arange(8)[:, None]
    W16 = np.exp(-2j * np.pi * k2 * np.arange(LANES) / LANES)
    return (W16 @ V).reshape(-1)                      # c = k1 + M·k2


def front(y, r, nc=NC, sign_err=False):
    """案 R の前段: 1 フレームの y（長さ N = r·nc）→ a_m（m = 0..r−1、各 nc 点）。"""
    N = r * nc
    yq = y.reshape(r, nc)                             # yq[q, n] = y[n + q·nc]
    q = np.arange(r)
    n = np.arange(nc)
    out = []
    for m in range(r):
        b = np.sum(yq * np.exp(-2j * np.pi * q * m / r)[:, None], axis=0)
        s = +1 if sign_err else -1
        out.append(b * np.exp(s * 2j * np.pi * n * m / N))
    return out


def front_fft(y, r, nc=NC, sign_err=False):
    """前段 ＋ r 個のコア → X[0 .. N/2 − 1]（X[r·k + m] = コア m の k 番目）。"""
    N = r * nc
    X = np.zeros(N // 2, dtype=complex)
    for m, a in enumerate(front(y, r, nc, sign_err)):
        X[m::r] = core_fft(a)
    return X


# ---------------------------------------------------------------- 判定

def m1():
    print("M-1 分解と numpy.fft.rfft の一致（浮動小数点、PFB の出口 y の 1 フレーム）")
    rng = np.random.default_rng(1)
    ok = True
    print(" (a) 1 本の FFT を 16 レーンで（案 O の各 bit・案 R の 4 ADC のモード）")
    for nadc, N in MODES.items():
        y = rng.normal(0, 1000, N)
        ref = np.fft.rfft(y)[: N // 2]
        e = np.max(np.abs(core_fft(y) - ref)) / np.max(np.abs(ref))
        ok &= e < 1e-9
        print(f"   N {N:6d}（レーン FFT {N // LANES:5d} 点）: 相対誤差 {e:.1e}")
    print(" (b) 案 R の前段: r 個のコア（各 65536 点、k2 = 0..7）で N = r·65536")
    for r in (1, 2, 4):
        N = r * NC
        y = rng.normal(0, 1000, N)
        ref = np.fft.rfft(y)[: N // 2]
        e = np.max(np.abs(front_fft(y, r) - ref)) / np.max(np.abs(ref))
        ok &= e < 1e-9
        line = f"   r {r}（N {N:6d}）: 相対誤差 {e:.1e}"
        if r > 1:
            ep = np.max(np.abs(front_fft(y, r, sign_err=True) - ref)) / np.max(np.abs(ref))
            line += f"   陽性対照（前段のひねり係数の符号を逆に）: {ep:.2f}"
            ok &= ep > 0.1
        print(line)
    # 前段の値の大きさ（語長）: |a_m| ≦ r·max|y|。雑音なら rms が √r 倍
    y = rng.normal(0, 1000, 4 * NC)
    a = front(y, 4)
    print(f"   前段の出口の rms / y の rms（r 4、雑音）: {np.mean([np.std(v) for v in a]) / np.std(y):.2f}（√r = 2）")
    print(f"  → M-1 {'通過' if ok else '不合格'}")
    return ok


def m2():
    print("M-2 ch の応答（18 bit に量子化した係数、T = 4）。物差しは proj020 の窓")
    ok = True
    for nadc, N in sorted(MODES.items(), key=lambda kv: kv[1]):
        t0 = time.time()
        c = quantize(design(N))
        r = response_metrics(c.astype(np.float64), N, pad=4)
        print(fmt_resp(f"N {N}（{nadc} ADC）", r) + f"  [{time.time() - t0:.0f} s]")
        ok &= abs(r["half"] - FINE_REF["half"]) <= 0.02 and abs(r["ge15"] - FINE_REF["ge15"]) <= 0.3 \
            and abs(r["enbw"] - FINE_REF["enbw"]) <= 0.002
    print(" 参考（PFB を入れない場合。2G の ch の応答を軽くする案の物差し、N 65536）")
    N = 65536
    print(fmt_resp("矩形（T = 1、h = 1）", response_metrics(np.ones(N), N, pad=16)))
    print(fmt_resp("Hann（T = 1）", response_metrics(np.hanning(N + 2)[1:-1], N, pad=16)))
    print(f"  → M-2 {'通過' if ok else '不合格'}（3 つの N とも proj020 の値と ±0.02 dB・ENBW ±0.002）")
    return ok


def m3():
    print("M-3 PFB の係数を粗い表の線形補間で作る（N 262144 = 1 ADC、4N = 1,048,576 タップ）")
    N = MODES[1]
    h = design(N)
    c = quantize(h)
    L = len(h)
    hs = h * (1 << CF)
    full_mbit = L * CW / 1e6
    print(f"  全部の表: {L} タップ × 18 bit = {full_mbit:.1f} Mbit（左右対称で半分 {full_mbit / 2:.1f} Mbit）")
    ok = True
    res = {}
    for D in (16, 64, 256, 1024):
        idx = np.arange(0, L + 1, D)
        idx = np.minimum(idx, L - 1)
        tab = hs[idx]
        ci = np.round(np.interp(np.arange(L), idx, tab)).astype(np.int64)
        d = np.abs(ci - c)
        res[D] = ci
        tbl_kbit = (L // D // 2 + 1) * 2 * 24 / 1e3       # 対称で半分、値と傾き × 24 bit
        print(f"  D {D:5d}: 表 {L // D:6d} 点（対称で半分・値と傾き 24 bit で {tbl_kbit:7.1f} kbit）、"
              f"量子化した表との差 最大 {d.max()} LSB・違う係数 {np.mean(d > 0) * 100:5.2f} %")
    ci = res[64]
    r0 = response_metrics(c.astype(np.float64), N, pad=4)
    r1 = response_metrics(ci.astype(np.float64), N, pad=4)
    print(fmt_resp("全部の表", r0))
    print(fmt_resp("D 64 の線形補間", r1))
    dmax = max(abs(r1[k] - r0[k]) for k in ("half", "p04", "ge1", "ge15", "ge3"))
    ok &= dmax <= 0.05 and np.max(np.abs(ci - c)) <= 1
    print(f"  応答の差の最大 {dmax:.3f} dB")
    print(f"  → M-3 {'通過' if ok else '不合格'}（D 64 で係数の差 ≦ 1 LSB・応答の差 ≦ 0.05 dB）")
    return ok


def tw_err(M, S, wbits=18):
    """ひねり係数 W_N^(p·k1)（N = 16M）を直の表と 2 つの表の積（k1 = hi·S + lo）で作り、誤差の rms を比べる。"""
    N = LANES * M
    sc = 1 << (wbits - 2)
    p = np.arange(1, LANES)[:, None]
    k1 = np.arange(M)[None, :]
    w = np.exp(-2j * np.pi * p * k1 / N)
    q = lambda z: (np.round(z.real * sc) + 1j * np.round(z.imag * sc)) / sc
    direct = q(w)
    hi, lo = k1 // S, k1 % S
    A = q(np.exp(-2j * np.pi * p * hi * S / N))
    B = q(np.exp(-2j * np.pi * p * lo / N))
    prod = q(A * B)                                     # 積を 18 bit に丸めて使う
    e_d = np.sqrt(np.mean(np.abs(direct - w) ** 2))
    e_p = np.sqrt(np.mean(np.abs(prod - w) ** 2))
    return e_d, e_p


def m4():
    print("M-4 語長と、ひねり係数を 2 つの小さな表の積で作る案")
    ok = True
    # PFB の出口 y の上限（proj022 の M-4: max Σ_t |c_t| = 1.405 → 15 bit）は N に依らない。レーン FFT の出口 Y は × M
    ymax = 11507
    print("  レーン FFT の出口 |Y| ≦ max|y| · M（同相の最悪）と、cmul の A ポート（27 bit）")
    for nadc, N in sorted(MODES.items(), key=lambda kv: kv[1]):
        M = N // LANES
        yb = ymax * M
        bits = int(np.ceil(np.log2(yb + 1))) + 1
        fits = bits <= 27
        print(f"   N {N:6d}・M {M:5d}: |Y| ≦ {yb:,}（{bits} bit）"
              + ("  → A ポートに入る" if fits else f"  → 入らない（{bits - 27} bit 落とす段が要る）"))
    print("   案 R の前段（r 4）: |a| ≦ 4·max|y| → 17 bit。レーン FFT の入力が 15 → 17 bit、|Y| ≦ 4·11507·4096（29 bit）")
    print("   → 前段の後で 2 bit 落とす（雑音の rms は √4 = 2 倍なので、実質 1 bit 分の丸めの雑音が増える）か、入力 17 bit の IP")
    print("  ひねり係数（18 bit、2^16 = 1.0）: 直の表と、k1 = hi·S + lo の 2 つの表の積（積を 18 bit に丸める）")
    for M, S in ((4096, 64), (8192, 128), (16384, 128)):
        e_d, e_p = tw_err(M, S)
        tab_direct = 15 * M * 36 / 1e6
        tab_fact = 15 * (M // S + S) * 36 / 1e3
        print(f"   M {M:5d}: 直 {tab_direct:5.2f} Mbit・誤差 rms {e_d:.2e} / 積（S {S}）{tab_fact:6.1f} kbit・誤差 rms {e_p:.2e}"
              f"（比 {e_p / e_d:.2f}）")
        ok &= e_p / e_d < 2.0
    print(f"  → M-4 {'通過' if ok else '不合格'}（積の誤差 < 直の 2 倍。どちらも 18 bit の量子化の大きさ ≒ 1e-5）")
    return ok


def m5():
    print("M-5 積分器の幅（Z は 18 bit で飽和 → 電力 P ≦ 2·(2^17)² = 2^35）")
    pmax = 2 * (2 ** 17) ** 2
    ok = True
    for nadc, N in sorted(MODES.items(), key=lambda kv: kv[1]):
        L = N // LANES
        nacc = BASE // L
        s = pmax * nacc
        print(f"   N {N:6d}: N_ACC = BASE / L = {nacc:4d} フレーム → 和 ≦ 2^{np.log2(s):.2f}"
              f"（48 bit に入る N_ACC の上限 {2 ** 48 // pmax - 1}）")
        ok &= s < 2 ** 48
    print("  → 48 bit で足りる（運転の N_ACC は BASE に固定。試験の N_ACC = 1 も入る）。リングのレコードは u64 のまま（PL が 0 で埋める）")
    print(f"  → M-5 {'通過' if ok else '不合格'}")
    return ok


def m6():
    print("M-6 時刻（フレーム・格子・PFB の重心）")
    ok = True
    for nadc, N in sorted(MODES.items(), key=lambda kv: kv[1]):
        L = N // LANES
        ok &= BASE % L == 0 and G % L == 0
        print(f"   N {N:6d}: L = {L:5d} ビート = {L / BEAT * 1e6:4.0f} µs、BASE / L = {BASE // L}、G / L = {G // L}"
              f"（F0 の格子 M）、PFB の立ち上がり 3 フレーム = {3 * L / BEAT * 1e6:.0f} µs・重心のずれ 1.5·L = {1.5 * L / BEAT * 1e6:.0f} µs、"
              f"df = {FS / N / 1e3:.3f} kHz")
    print("   案 R（r 個のコアで 1 本）: コア m のフレームは入力のフレームの最後の 1/r に詰めて流す（4096 ビート）。")
    print("   残りの (r − 1)/r はコアの IP に流さない（フレームの間の空き。窓の bit が 2 面の溜めで既にしている形）")
    print(f"  → M-6 {'通過' if ok else '不合格'}（どの N でも BASE・G がフレームの整数倍）")
    return ok


def _cround(z):
    return np.round(z.real) + 1j * np.round(z.imag)


def chain_lsb(Y, d1, sh, exact=False):
    """レーン FFT の出口 Y（16 × M、整数）→ Y の d1 bit を丸め → cmul（係数 18 bit、2^16 = 1.0、右シフト sh）
    → dft16（4 × 4、段 2 の cmul も 18 bit・SH 16 で丸め）→ Z[k2]（k2 = 0..7、8 × M）。
    戻り値は Y の単位に戻した Z と、V・Z の成分の最大値（V・Z の整数の単位）。exact = True は丸めなしの浮動小数点の鎖。"""
    M = Y.shape[1]
    N = LANES * M
    p = np.arange(LANES)[:, None]
    k1 = np.arange(M)[None, :]
    w = np.exp(-2j * np.pi * p * k1 / N)
    if exact:
        V = Y * w
        Z = np.exp(-2j * np.pi * np.arange(8)[:, None] * np.arange(LANES)[None, :] / LANES) @ V
        return Z, 0, 0
    Yd = _cround(Y / 2 ** d1)
    wq = _cround(w * 2 ** 16)
    V = _cround(Yd * wq / 2 ** sh)
    unit = 2.0 ** (d1 + sh - 16)
    Vr = V.reshape(4, 4, M)                             # Vr[a, b] = V[4a + b]
    W4 = np.exp(-2j * np.pi * np.outer(np.arange(4), np.arange(4)) / 4).round()
    U = np.einsum("ca,abm->bcm", W4, Vr)               # U[b, c]（±1・±j だけ = 整数のまま）
    W16 = _cround(np.exp(-2j * np.pi * np.outer(np.arange(4), np.arange(4)) / 16) * 2 ** 16)
    Tt = _cround(U * W16[:, :, None] / 2 ** 16)         # 段 2
    Zc = np.einsum("db,bcm->dcm", W4[:2], Tt)           # Z[c + 4d]、d = 0, 1
    Z = Zc.reshape(8, M)
    vmax = max(np.abs(V.real).max(), np.abs(V.imag).max())
    zmax = max(np.abs(Z.real).max(), np.abs(Z.imag).max())
    return Z * unit, vmax, zmax


def m7():
    print("M-7 2G-1 の語長（D-7）: Y → V で落とす bit（dft16 を変えずに V 25 bit）の雑音")
    rng = np.random.default_rng(7)
    ymax = 11507
    ok = True
    cases = [("2G-1", 16384, 2, 18, True), ("2G-2", 8192, 1, 18, True), ("Wide（参考）", 2048, 0, 17, False),
             ("陽性対照 2G-1 ＋10 bit", 16384, 12, 18, False)]
    for name, M, d1, sh, judged in cases:
        line = []
        for sy in (2, 8, 64):
            y = np.clip(np.round(rng.normal(0, sy, (2, LANES, M))), -ymax, ymax)
            num = den = 0.0
            for f in range(2):
                Yf = np.fft.fft(y[f], axis=1)
                Y = _cround(Yf)                          # IP の出口は整数
                Zi, _, _ = chain_lsb(Y, d1, sh)
                Zf, _, _ = chain_lsb(Yf, 0, 0, exact=True)
                num += np.sum(np.abs(Zi - Zf) ** 2)
                den += np.sum(np.abs(Zf) ** 2)
            eps = num / den
            ddb = 10 * np.log10(1 + eps)
            line.append(f"σ_y {sy:2d}: ε {eps:.2e}（ε·σ² {eps * sy * sy:.1e}）劣化 {ddb:.4f} dB")
            if judged and sy >= 2:
                ok &= ddb < 0.01
            if name.startswith("陽性") and sy == 2:
                ok &= ddb > 1.0
        # 最悪（y が全部 +ymax で同相）: V・Z が語幅に入るか
        Yw = _cround(np.fft.fft(np.full((LANES, M), float(ymax)), axis=1))
        _, vmax, zmax = chain_lsb(Yw, d1, sh)
        vbits = int(np.ceil(np.log2(vmax + 1))) + 1
        zbits = int(np.ceil(np.log2(zmax + 1))) + 1
        yb = int(np.ceil(np.log2(ymax * M + 1))) + 1
        fit = vbits <= 25 and zbits <= 29
        print(f"  {name}: M {M}・Y {yb} bit → {d1} bit 丸め → {yb - d1} bit（A ポート ≦ 27）→ cmul SH {sh} → V"
              f"。最悪の同相で V {vbits} bit・Z {zbits} bit" + ("（V 25・Z 29 に入る）" if fit else "（入らない）"))
        for l in line:
            print("     " + l)
        if judged:
            ok &= fit and (yb - d1) <= 27
    print(f"  → M-7 {'通過' if ok else '不合格'}（2G-1・2G-2 は σ_y ≧ 2 で劣化 < 0.01 dB・最悪でも V 25・Z 29 に入る、陽性対照は σ_y 2 で > 1 dB）")
    return ok


def m8():
    import g21_fixed as F
    print("M-8 2G-1 の新しい部品を bit 単位で（model/g21_fixed.py）")
    ok = True
    N = F.N
    c = quantize(design(N))
    # ---- 8-a 係数の補間 ----
    print("  8-a 係数の補間（D 64、左右の折り返し、節の追加の小数 G bit）: 全部の表 c = round(h·2^16) との差")
    sigbits = lambda v: int(np.ceil(np.log2(np.abs(v).max() + 1))) + 1
    hs = design(N) * (1 << CF)
    e_c = np.sqrt(np.mean((c - hs) ** 2))
    print(f"   （物差し: 全部の表 c の h に対する rms {e_c:.4f} LSB）")
    for g in range(0, 9):
        V, S = F.coef_tables(g)
        cg = F.coef_fold(V, S, g)
        d = np.abs(cg - c)
        w_ = sigbits(V) + sigbits(S)
        print(f"   G {g}: c との差 最大 {d.max()} LSB・違う係数 {np.mean(d > 0) * 100:6.3f} %・h に対する rms {np.sqrt(np.mean((cg - hs) ** 2)):.4f} LSB"
              f"・V {sigbits(V)}・S {sigbits(S)} bit（計 {w_}、RAMB36 {2 * int(np.ceil(w_ / 9))}）" + ("  ← 使う" if g == F.G else ""))
    V, S = F.coef_tables()
    cf = F.coef_fold(V, S)
    d = np.abs(cf - c)
    e_i = np.sqrt(np.mean((cf - hs) ** 2))
    ok &= d.max() <= 1 and e_i <= 1.01 * e_c
    cb = F.coef_beat(V, S)
    same = np.array_equal(cb.reshape(-1), cf)               # [t, m, p] → t·N + 16m + p
    bad = F.coef_fold(V, S, fold_err=True)
    pc = int(np.sum(bad != cf))
    print(f"   ビートの式と折り返しの式: {'全部の i で一致' if same else '不一致'}。陽性対照（i' = L − i）: 違う係数 {pc:,}")
    ok &= same and pc > 0
    vw, sw = sigbits(V), sigbits(S)
    w = vw + sw
    # t = 0・3 は前半の 4096 個、t = 1・2 は後半を引く → 半分ずつの 2 ポートの ROM（4K × 9 の RAMB36）
    nb = 2 * int(np.ceil(w / 9))
    print(f"   表: 8192 × {w} bit（V {vw}・S {sw}）= {8192 * w / 1e3:.0f} kbit。1 ビートの 4 読みは t 0・3 が前半、t 1・2 が後半"
          f" → 前半・後半を 2 ポートの ROM（4K × 9）に: RAMB36 {nb} 個")
    r0 = response_metrics(c.astype(np.float64), N, pad=4)
    r1 = response_metrics(cf.astype(np.float64), N, pad=4)
    dmax = max(abs(r1[k] - r0[k]) for k in ("half", "p04", "ge1", "ge15", "ge3"))
    print(f"   応答の差の最大 {dmax:.3f} dB")
    ok &= dmax <= 0.05
    # ---- 8-b ひねり係数の積 ----
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
    print(f"  8-b ひねり係数の積（S {F.S_TW}）: 直の表との差 最大 {dlsb} LSB・誤差 rms {e_p:.3f} LSB（直の表 {e_d:.3f}、比 {e_p / e_d:.2f}）"
          f"・成分の最大 {cmax}（18 bit ≦ 131071）。陽性対照（hi·127 + lo）: 差 最大 {pcd} LSB")
    ok &= dlsb <= 2 and e_p / e_d < 2.0 and cmax <= 131071 and pcd > 100
    # ---- 8-c 鎖の全体 ----
    rng = np.random.default_rng(8)
    c0 = 40000
    nf = 5
    n = np.arange(nf * N)
    x = np.clip(np.round(1000 * np.cos(2 * np.pi * c0 * n / N) + rng.normal(0, 100, nf * N)), -8191, 8191).astype(np.int64)
    y, ysat = F.pfb_int(x, cf)
    yfl = pfb_float(x.astype(np.float64), design(N), N)
    st = {}
    res = {}
    for name, tw in (("鎖", (pr, pi)), ("陽性対照（k1 を 1 ずらす）", (np.roll(pr, -1, axis=1), np.roll(pi, -1, axis=1)))):
        en = ed = 0.0
        dcw = []
        for f in (3, 4):
            Zr, Zi = F.chain_frame(y[f], *tw, stats=st if name == "鎖" else None)
            Zc = (Zr + 1j * Zi).reshape(-1) * 16.0
            Xf = core_fft(yfl[f])
            mask = np.abs(np.arange(N // 2) - c0) > 3
            en += np.sum(np.abs(Zc - Xf)[mask] ** 2)
            ed += np.sum(np.abs(Xf)[mask] ** 2)
            dcw.append(10 * np.log10(np.abs(Zc[c0]) ** 2 / np.abs(Xf[c0]) ** 2))
            if name == "鎖" and f == 4:
                pw, psat = F.power(Zr, Zi, 7)
                zrms = np.sqrt(np.mean((np.abs(Zr + 1j * Zi).reshape(-1)[mask]) ** 2))
        res[name] = en / ed
        print(f"  8-c {name}: 雑音の ch の ε {en / ed:.2e}・CW の ch の電力の差 {max(dcw, key=abs):+.4f} dB")
        if name == "鎖":
            ok &= en / ed <= 2e-5 and max(abs(v) for v in dcw) < 0.01
        else:
            ok &= en / ed > 2e-5
    print(f"     y の飽和 {ysat}・各段の最大 Y {st['Y']:,}・Yd {st['Yd']:,}・V {st['V']:,}・U {st['U']:,}・Z {st['Z']:,}"
          f"（参考: 雑音の Z の rms {zrms:.0f}、SHIFT 7 で q の飽和 {psat}）")
    # ---- 8-d 積分器の番地 ----
    k = F.bitrev(np.arange(F.M), 14)
    perm = np.array_equal(np.sort(k), np.arange(F.M))
    seq = np.concatenate([k, k])
    last = {}
    dist = F.M
    for i, a in enumerate(seq):
        if a in last:
            dist = min(dist, i - last[a])
        last[a] = i
    print(f"  8-d 積分器の番地（bit 反転順の k1）: {'1 フレームで全部の番地を 1 回ずつ' if perm else '並べ替えでない'}・"
          f"同じ番地に戻るまで最小 {dist} ビート")
    ok &= perm and dist == F.M
    print(f"  → M-8 {'通過' if ok else '不合格'}（8-a: 差 ≦ 1 LSB・h に対する rms ≦ 全部の表の 1.01 倍・ビートの式が一致・応答の差 ≦ 0.05 dB。"
          "8-b: 差 ≦ 2 LSB・rms 比 < 2。8-c: ε ≦ 2e-5・CW < 0.01 dB、陽性対照は ε > 2e-5。8-d: 並べ替え・距離 16384）")
    return ok


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    fns = dict(m1=m1, m2=m2, m3=m3, m4=m4, m5=m5, m6=m6, m7=m7, m8=m8)
    names = list(fns) if which == "all" else [which]
    res = {}
    for k in names:
        t0 = time.time()
        res[k] = fns[k]()
        print(f"  [{k}: {time.time() - t0:.1f} s]\n")
    print("まとめ: " + "  ".join(f"{k.upper()} {'通過' if v else '不合格'}" for k, v in res.items()))
    sys.exit(0 if all(res.values()) else 1)


if __name__ == "__main__":
    main()
