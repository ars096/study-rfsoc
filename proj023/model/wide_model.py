#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj022 — SAM45-Wide の模型（PFB T = 4 ＋ 16 レーンの全帯域 FFT、8192 / 16384 / 32768 点）。numpy だけ。

README の判定 M-1〜M-6 を数える。RTL はまだ無い（proj021 の後に書く）ので、ここが式と語長の唯一の正になる。

式（proj011 の spec_core に、proj020 の PFB を前に足したもの）:
  入力 x（実数・14 bit、ADC の 16 bit を >>> 2）。フレーム f = x[N·f : N·f + N]、WRST の後の最初のサンプルが 0 番
  PFB（出力フレーム r の番号は最新の入力フレーム。r − 3 + t < 0 のタップは 0。proj020 の決定 6）:
    acc[a] = Σ_{t=0..3} c[a + N·t] · x_{r−3+t}[a]
    y[a]   = sat(YW, (acc[a] + 2^(CF−1)) >> CF)
  16 レーン（a = 16·m + p、m = 0..M−1、p = 0..15、M = N / 16）:
    Y_p[k1] = Σ_m y[16m + p] · W_M^(m·k1)                       レーン FFT（FFT IP、unscaled・自然順）
    V_p[k1] = (W_N^(p·k1) · Y_p[k1] + 2^(15+D)) >> (16 + D)     ひねり係数（cmul、D bit 落とす）
    Z[k2]   = Σ_p W_16^(p·k2) · V_p[k1]、k2 = 0..7              16 点 DFT（dft16 の 4 × 4）
    X[k1 + M·k2] = 2^D · Z[k2]                                   ch c = k1 + M·k2（c = 0..N/2 − 1）
  電力 P = re² + im²（SHIFT・18 bit の飽和の後）→ 積分（64 bit）

原型（proj020 と同じ考え方を N 点・実数に）:
  h[n] = sinc(BW·(n − n₀)/N) · kaiser(L, β)、L = 4N、Σh² = N（雑音の電力を保つ）。係数 c = round(h·2^CF)、18 bit
  n₀ = (L − 1)/2（proj020 と同じ・左右対称）か n₀ = L/2（M-3 の案 c）

使い方:
  python3 wide_model.py all          # M-1〜M-6 を全部（数分）
  python3 wide_model.py m1 | m2 | m3 | m4 | m5 | m6
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
MODES = (8192, 16384, 32768)      # 全帯域 / 1 GHz / 512 MHz
FINE_REF = dict(half=-3.00, ge1=-53.7, ge15=-58.0, ge3=-64.5, p04=-1.20, ripple=0.08, enbw=1.010)  # proj020 README
SLICE = 4096                       # 1 本の流れの ch

np.set_printoptions(linewidth=140)


# ---------------------------------------------------------------- 原型と係数

def kaiser_cont(n, L, beta, n0):
    """Kaiser の窓を中心 n₀・全幅 L の連続関数として n で評価する（n₀ = (L−1)/2 なら np.kaiser(L) と同じ）。"""
    half = (L - 1) / 2 if n0 == (L - 1) / 2 else L / 2
    r = (n - n0) / half
    r = np.clip(r, -1.0, 1.0)
    return np.i0(beta * np.sqrt(1.0 - r * r)) / np.i0(beta)


def design(N, center="sym"):
    """浮動小数点の原型（Σh² = N）。center = "sym"（n₀ = (L−1)/2、proj020）/ "int"（n₀ = L/2、案 c）"""
    L = T * N
    n = np.arange(L, dtype=np.float64)
    if center == "sym":
        n0 = (L - 1) / 2
        h = np.sinc(BW * (n - n0) / N) * np.kaiser(L, BETA)
        half = h[: L // 2]
        h = np.concatenate([half, half[::-1]])       # 対称を厳密に（proj020 と同じ作り方）
    else:
        n0 = L / 2
        h = np.sinc(BW * (n - n0) / N) * kaiser_cont(n, L, BETA, n0)
    return h * np.sqrt(N / np.sum(h * h))


def quantize(h):
    c = np.round(h * (1 << CF)).astype(np.int64)
    assert c.max() < (1 << (CW - 1)) and c.min() >= -(1 << (CW - 1)), "係数が 18 bit に入らない"
    return c


# ---------------------------------------------------------------- ch の応答

def response_metrics(h, N, pad=16, span=48):
    """h（L = 4N タップ）の ch の応答。δ は ch の単位。戻り値は dB（0 ch で 0 dB）と ENBW。"""
    h = np.asarray(h, dtype=np.float64)
    L = len(h)
    nfft = L * pad                               # δ の刻み = N / nfft = 1 / (4·pad) ch
    H = np.fft.rfft(h, nfft)
    P = np.abs(H) ** 2
    P /= P[0]
    step = N / nfft
    d = np.arange(len(P)) * step
    keep = d <= span
    d, P = d[keep], P[keep]
    db = 10 * np.log10(np.maximum(P, 1e-300))

    def at(delta):                                # DTFT を直に（刻みに乗らない点のため）
        n = np.arange(L)
        v = np.abs(np.sum(h * np.exp(-2j * np.pi * delta * n / N))) ** 2
        return 10 * np.log10(v / np.sum(h) ** 2)

    # −3 dB の幅（主ローブの片側を細かく）
    dd = np.linspace(0.3, 0.7, 401)
    n = np.arange(L)
    s0 = np.sum(h) ** 2
    pv = np.array([np.abs(np.sum(h * np.exp(-2j * np.pi * x * n / N))) ** 2 / s0 for x in dd])
    i = np.argmax(10 * np.log10(pv) < -3.0103)
    w3 = 2 * (dd[i - 1] + (dd[i] - dd[i - 1]) * ((10 * np.log10(pv[i - 1]) + 3.0103)
                                                   / (10 * np.log10(pv[i - 1]) - 10 * np.log10(pv[i]))))
    # 隣り合う ch の和の波打ち（δ ∈ [0, 1)）
    grid = np.arange(0, 1, step)
    tot = np.zeros_like(grid)
    lin = 10 ** (db / 10)
    for k in range(-6, 7):
        tot += np.interp(np.abs(grid - k), d, lin, right=0.0)
    ripple = 10 * np.log10(tot.max() / tot.min())
    return dict(
        half=at(0.5), p04=at(0.4), w3=w3,
        ge1=db[d >= 1.0].max(), ge15=db[d >= 1.5].max(), ge3=db[d >= 3.0].max(),
        ripple=ripple, enbw=N * np.sum(h * h) / np.sum(h) ** 2,
    )


def fmt_resp(name, r):
    return (f"  {name:<34s} 0.5ch {r['half']:6.2f}  0.4ch {r['p04']:6.2f}  −3dB 幅 {r['w3']:.3f}  "
            f"≧1 {r['ge1']:6.1f}  ≧1.5 {r['ge15']:6.1f}  ≧3 {r['ge3']:6.1f}  和の波打ち {r['ripple']:.2f}  ENBW {r['enbw']:.3f}")


# ---------------------------------------------------------------- 分解（浮動小数点）

def pfb_float(x, h, N):
    """x（長さ N の倍数）→ 出力フレーム r = 0 .. nf−1（r − 3 + t < 0 のタップは 0）。戻り値 (nf, N)。"""
    nf = len(x) // N
    xf = np.asarray(x[: nf * N], dtype=np.float64).reshape(nf, N)
    ht = np.asarray(h, dtype=np.float64).reshape(T, N)
    y = np.zeros((nf, N))
    for t in range(T):
        sh = T - 1 - t
        y[sh:] += ht[t] * xf[: nf - sh]
    return y


def lanes_fft_float(y, N):
    """1 フレームの y（長さ N）→ X[0 .. N/2 − 1]（16 レーンの分解）。"""
    M = N // LANES
    yp = y.reshape(M, LANES).T                       # yp[p, m] = y[16m + p]
    Y = np.fft.fft(yp, axis=1)                        # Y[p, k1]
    k1 = np.arange(M)
    p = np.arange(LANES)[:, None]
    V = Y * np.exp(-2j * np.pi * p * k1 / N)
    k2 = np.arange(8)[:, None]
    W16 = np.exp(-2j * np.pi * k2 * np.arange(LANES) / LANES)   # [k2, p]
    Z = W16 @ V                                       # Z[k2, k1]
    return Z.reshape(-1)                              # 並びは k2 が外側 → c = k1 + M·k2


# ---------------------------------------------------------------- 固定小数点

def rshift_round(v, s):
    """(v + 2^(s−1)) >> s（算術右シフト。cmul の丸めと同じ）。"""
    if s == 0:
        return v
    return (v + (1 << (s - 1))) >> s


def tw_q(N):
    """ひねり係数 W_N^(p·k1)、18 bit・2^16 = 1.0（tw_rom と同じ作り）。[p, k1]"""
    M = N // LANES
    p = np.arange(LANES)[:, None]
    k1 = np.arange(M)[None, :]
    w = np.exp(-2j * np.pi * p * k1 / N)
    return np.round(w.real * 65536).astype(np.int64), np.round(w.imag * 65536).astype(np.int64)


def w16_q():
    e = np.arange(16)
    w = np.exp(-2j * np.pi * e / 16)
    return np.round(w.real * 65536).astype(np.int64), np.round(w.imag * 65536).astype(np.int64)


def cmul_q(ar, ai, wr, wi, s):
    return rshift_round(ar * wr - ai * wi, s), rshift_round(ar * wi + ai * wr, s)


def fixed_chain(x, c, N, D=1, YW=16, YF=0, stats=None):
    """固定小数点の鎖。x（int）→ Z（int、re・im、(nf, N/2)）= X·2^(YF − D)。stats に各段の最大の絶対値を入れる。
    YF = PFB の出口 y に残す小数の bit 数（0 = 入力と同じ目盛りの整数）"""
    nf = len(x) // N
    M = N // LANES
    xf = np.asarray(x[: nf * N], dtype=np.int64).reshape(nf, N)
    ct = c.reshape(T, N)
    acc = np.zeros((nf, N), dtype=np.int64)
    for t in range(T):
        sh = T - 1 - t
        acc[sh:] += ct[t] * xf[: nf - sh]
    y = rshift_round(acc, CF - YF)
    lo, hi = -(1 << (YW - 1)), (1 << (YW - 1)) - 1
    ysat = int(np.sum((y < lo) | (y > hi)))
    y = np.clip(y, lo, hi)
    twr, twi = tw_q(N)
    wr16, wi16 = w16_q()
    Zr = np.zeros((nf, N // 2), dtype=np.int64)
    Zi = np.zeros((nf, N // 2), dtype=np.int64)
    mx = dict(y=0, Y=0, V=0, U=0, Z=0, ysat=ysat)
    for f in range(nf):
        yp = y[f].reshape(M, LANES).T                         # [p, m]
        Yc = np.fft.fft(yp.astype(np.float64), axis=1)        # IP（unscaled）: 整数の入力の DFT。出口は整数に丸める
        Yr = np.rint(Yc.real).astype(np.int64)
        Yi = np.rint(Yc.imag).astype(np.int64)
        Vr, Vi = cmul_q(Yr, Yi, twr, twi, 16 + D)             # [p, k1]
        # dft16（4 × 4）: p = 4a + b、k2 = cc + 4d
        Vr4 = Vr.reshape(4, 4, M)                             # [a, b, k1]
        Vi4 = Vi.reshape(4, 4, M)
        Ur = np.zeros((4, 4, M), dtype=np.int64)              # [b, cc, k1]
        Ui = np.zeros((4, 4, M), dtype=np.int64)
        j4 = [(1, 0), (0, -1), (-1, 0), (0, 1)]               # W4^e = 1, −j, −1, +j
        for cc in range(4):
            for a in range(4):
                er, ei = j4[(a * cc) % 4]
                Ur[:, cc] += er * Vr4[a] - ei * Vi4[a]
                Ui[:, cc] += er * Vi4[a] + ei * Vr4[a]
        Tr = np.zeros_like(Ur)
        Ti = np.zeros_like(Ui)
        for b in range(4):
            for cc in range(4):
                e = b * cc
                Tr[b, cc], Ti[b, cc] = cmul_q(Ur[b, cc], Ui[b, cc], wr16[e], wi16[e], 16)
        Zf_r = np.zeros((8, M), dtype=np.int64)
        Zf_i = np.zeros((8, M), dtype=np.int64)
        for cc in range(4):
            for d in range(2):
                k2 = cc + 4 * d
                for b in range(4):
                    er, ei = j4[(b * d) % 4]
                    Zf_r[k2] += er * Tr[b, cc] - ei * Ti[b, cc]
                    Zf_i[k2] += er * Ti[b, cc] + ei * Tr[b, cc]
        Zr[f] = Zf_r.reshape(-1)
        Zi[f] = Zf_i.reshape(-1)
        mx["Y"] = max(mx["Y"], int(np.abs(Yr).max()), int(np.abs(Yi).max()))
        mx["V"] = max(mx["V"], int(np.abs(Vr).max()), int(np.abs(Vi).max()))
        mx["U"] = max(mx["U"], int(np.abs(Ur).max()), int(np.abs(Ui).max()))
        mx["Z"] = max(mx["Z"], int(np.abs(Zf_r).max()), int(np.abs(Zf_i).max()))
    mx["y"] = int(np.abs(y).max())
    if stats is not None:
        stats.update(mx)
    return Zr, Zi


def bits_signed(v):
    """|v| ≦ v を入れる符号付きの bit 数。"""
    return int(np.ceil(np.log2(v + 1))) + 1


# ---------------------------------------------------------------- 判定

def m1():
    print("M-1 分解（PFB → 16 レーン → レーン FFT → ひねり係数 → 16 点 DFT）と numpy.fft.rfft の一致（浮動小数点）")
    rng = np.random.default_rng(1)
    ok = True
    for N in MODES:
        h = design(N)
        x = rng.normal(0, 1000, N * 6)
        y = pfb_float(x, h, N)
        worst = 0.0
        for r in range(3, 6):
            Xd = lanes_fft_float(y[r], N)
            Xr = np.fft.rfft(y[r])[: N // 2]
            worst = max(worst, np.max(np.abs(Xd - Xr)) / np.max(np.abs(Xr)))
        # PFB の定義そのもの: y の FFT = 長さ 4N の窓を掛けた区間の FFT の 4 本おき
        seg = x[2 * N: 6 * N] * h
        Xw = np.fft.rfft(seg)[: 2 * N: 4]
        pf = np.max(np.abs(np.fft.rfft(y[5])[: N // 2] - Xw)) / np.max(np.abs(Xw))
        good = worst <= 1e-9 and pf <= 1e-9
        ok &= good
        print(f"  N = {N:5d}: 分解の相対誤差 {worst:.2e}  /  PFB = 窓付き 4N 点 FFT の 4 本おき {pf:.2e}  → {'通過' if good else 'NG'}")
    # 陽性対照: ひねり係数の符号を逆にした分解は一致しない
    N = 8192
    h = design(N)
    x = rng.normal(0, 1000, N * 4)
    y = pfb_float(x, h, N)[3]
    M = N // LANES
    yp = y.reshape(M, LANES).T
    Y = np.fft.fft(yp, axis=1)
    V = Y * np.exp(+2j * np.pi * np.arange(LANES)[:, None] * np.arange(M) / N)
    W16 = np.exp(-2j * np.pi * np.arange(8)[:, None] * np.arange(LANES) / LANES)
    bad = np.max(np.abs((W16 @ V).reshape(-1) - np.fft.rfft(y)[: N // 2])) / np.max(np.abs(np.fft.rfft(y)))
    print(f"  陽性対照（ひねり係数の符号を逆に）: 相対誤差 {bad:.2e} → {'落ちる（正しい）' if bad > 1e-3 else '落ちない（判定が効いていない）'}")
    return ok


def m2():
    print("M-2 ch の応答（18 bit の係数・n₀ = (L−1)/2）。proj020 の窓（N = 4096 複素）の値と比べる")
    rows = {}
    for N in (4096,) + MODES:
        c = quantize(design(N)).astype(np.float64)
        rows[N] = response_metrics(c, N)
        print(fmt_resp(f"N = {N}" + ("（proj020 の再現）" if N == 4096 else ""), rows[N]))
    ref = rows[4096]
    tol = 0.02
    ok = True
    for N in MODES:
        dmax = max(abs(rows[N][k] - ref[k]) for k in ("half", "p04", "ripple"))
        dfar = max(abs(rows[N][k] - ref[k]) for k in ("ge1", "ge15", "ge3"))
        good = dmax <= tol
        ok &= good
        print(f"  N = {N}: 主ローブ・和の差の最大 {dmax:.3f} dB（≦ {tol}）、サイドローブの差の最大 {dfar:.2f} dB → {'通過' if good else 'NG'}")
    d = {k: rows[4096][k] - FINE_REF[k] for k in ("half", "ge1", "ge15", "ge3", "p04")}
    print("  proj020 の README の値との差（N = 4096、測り方の陽性対照）: " + "  ".join(f"{k} {v:+.2f}" for k, v in d.items()))
    return ok


def m3():
    print("M-3 係数の持ち方。(a) 長さごとの表 / (b) 32768 の表（n₀ = (L−1)/2）を s 個おき / (c) 32768 の表（n₀ = L/2）を s 個おき")
    big = {"b": quantize(design(32768, "sym")), "c": quantize(design(32768, "int"))}
    print("  応答:")
    for N in MODES:
        s = 32768 // N
        ra = response_metrics(quantize(design(N)).astype(float), N)
        print(fmt_resp(f"N = {N} (a) 長さごとの表", ra))
        for k in ("b", "c"):
            cs = big[k][::s].astype(np.float64)
            g = 10 * np.log10(np.sum(cs * cs) / 2 ** (2 * CF) / N)
            r = response_metrics(cs, N)
            print(fmt_resp(f"N = {N} ({k}) {s} 個おき", r) + f"  雑音の利得 {g:+.4f} dB")
        if N != 32768:
            ex = np.max(np.abs(design(32768, "int")[::s] / np.sqrt(np.sum(design(32768, 'int')[::s] ** 2) / N)
                               - design(N, "int")))
            print(f"    (c) の厳密さ: 32768 の原型の {s} 個おき（規格化し直し）と N = {N} の原型の差の最大 {ex:.2e}")
    # ポートの数: 1 本の表を s 個おきに読むと、レーン p は表のレーン (p·s mod 16) の行 (m·s + ⌊p·s/16⌋) を読む
    print("  1 本の表を 16 レーン × 4 タップの ROM（レーン q・タップ t ごとに 1 個、深さ 2048）に分けたとき、1 クロックの読みの数:")
    for N in MODES:
        s = 32768 // N
        cnt = {}
        for p in range(LANES):
            q = (p * s) % LANES
            cnt[q] = cnt.get(q, 0) + 1
        print(f"    N = {N}: ROM 1 個あたりの読み 最大 {max(cnt.values())}（2 ポートで足りるのは 2 以下。対称でポートを 1 つ使うなら 1 以下）")
    return True


def m4():
    print("M-4 語長と量子化の雑音（固定小数点の鎖 vs 浮動小数点）。D = ひねり係数の後に落とす bit 数")
    ok = True
    rng = np.random.default_rng(4)
    fs_sine = (2 ** (XW - 1)) ** 2 / 2                 # フルスケールの正弦の電力（LSB²）
    for N in MODES:
        M = N // LANES
        c = quantize(design(N))
        ct = c.reshape(T, N)
        ymax = int(np.max(np.sum(np.abs(ct), axis=0)) * (2 ** (XW - 1)) / 2 ** CF) + 1
        Ymax = ymax * M
        print(f"  N = {N}: 上限 |y| ≦ {ymax}（{bits_signed(ymax)} bit）、|Y| ≦ {Ymax}（{bits_signed(Ymax)} bit、IP の宣言は "
              f"{bits_signed(ymax) + int(np.log2(M)) + 1}）、D = 1 で |V| ≦ {Ymax // 2}（{bits_signed(Ymax // 2)}）・"
              f"|U| ≦ {4 * Ymax // 2}（{bits_signed(4 * Ymax // 2)}）・|Z| ≦ {16 * Ymax // 2}（{bits_signed(16 * Ymax // 2)}）")
    print("  雑音の入力（ガウス、14 bit に丸めて飽和）で、Z の誤差の電力 / 信号の電力（ch の平均）:")
    for N in MODES:
        c = quantize(design(N))
        h = c.astype(np.float64) / 2 ** CF
        for dbfs in (-30.0, -17.0):
            sig = np.sqrt(fs_sine * 10 ** (dbfs / 10))
            x = np.clip(np.rint(rng.normal(0, sig, N * 7)), -(2 ** (XW - 1)), 2 ** (XW - 1) - 1).astype(np.int64)
            for D in (0, 1, 2):
                st = {}
                Zr, Zi = fixed_chain(x, c, N, D=D, stats=st)
                yref = pfb_float(x.astype(np.float64), h, N)
                err = 0.0
                pw = 0.0
                for r in range(3, 7):
                    Xr = np.fft.rfft(yref[r])[: N // 2] / 2 ** D
                    e = (Zr[r] + 1j * Zi[r]) - Xr
                    err += np.mean(np.abs(e) ** 2)
                    pw += np.mean(np.abs(Xr) ** 2)
                ratio = err / pw
                adcq = (1 / 12) / sig ** 2
                print(f"    N = {N:5d}  {dbfs:5.0f} dBFS  D = {D}: 誤差 / 信号 {ratio:.2e}（ADC の量子化雑音 / 信号 {adcq:.1e}）"
                      f"  最大 |y| {st['y']}・|Y| {st['Y']}（{bits_signed(st['Y'])} bit）・|V| {st['V']}・|U| {st['U']}・|Z| {st['Z']}"
                      f"（{bits_signed(st['Z'])} bit）、y の飽和 {st['ysat']}")
                if D == 1 and dbfs == -30.0:
                    ok &= ratio <= 1e-4                       # 判定（書き直した後）: 信号に対して ≦ 1e-4（README の M-4）
    print("  PFB の出口に小数を残すと（YF bit）、y の丸めの雑音がどれだけ減り、幅がどれだけ増えるか（N = 32768・−30 dBFS・D = 1 + YF で Z の目盛りを保つ）:")
    N = 32768
    c = quantize(design(N))
    h = c.astype(np.float64) / 2 ** CF
    sig = np.sqrt(fs_sine * 10 ** (-30 / 10))
    x = np.clip(np.rint(rng.normal(0, sig, N * 7)), -(2 ** (XW - 1)), 2 ** (XW - 1) - 1).astype(np.int64)
    yref = pfb_float(x.astype(np.float64), h, N)
    ymax = int(np.max(np.sum(np.abs(c.reshape(T, N)), axis=0)) * (2 ** (XW - 1)) / 2 ** CF) + 1
    for YF in (0, 1, 2):
        Zr, Zi = fixed_chain(x, c, N, D=1 + YF, YW=16 + YF, YF=YF)
        err = pw = 0.0
        for r in range(3, 7):
            Xr = np.fft.rfft(yref[r])[: N // 2] / 2
            err += np.mean(np.abs((Zr[r] + 1j * Zi[r]) - Xr) ** 2)
            pw += np.mean(np.abs(Xr) ** 2)
        print(f"    YF = {YF}: 誤差 / 信号 {err / pw:.2e}（ADC の量子化雑音の {err / pw / ((1 / 12) / sig ** 2):.2f} 倍）、"
              f"y {bits_signed(ymax << YF)} bit・Y の上限 {bits_signed((ymax << YF) * (N // LANES))} bit（cmul の A ポート 27 bit）")
    print("  強い CW（−1 dBFS）を ch の中心と ch の間に。D = 1 の各段の最大:")
    for N in MODES:
        c = quantize(design(N))
        amp = (2 ** (XW - 1)) * 10 ** (-1 / 20)
        for off in (0.0, 0.5):
            k = N // 4 + off
            n = np.arange(N * 7)
            x = np.clip(np.rint(amp * np.cos(2 * np.pi * k * n / N + 0.3)), -(2 ** 13), 2 ** 13 - 1).astype(np.int64)
            st = {}
            fixed_chain(x, c, N, D=1, stats=st)
            print(f"    N = {N:5d}  ch {k:9.1f}: |y| {st['y']}・|Y| {st['Y']}（{bits_signed(st['Y'])}）・|V| {st['V']}（{bits_signed(st['V'])}）"
                  f"・|U| {st['U']}（{bits_signed(st['U'])}）・|Z| {st['Z']}（{bits_signed(st['Z'])}）・y の飽和 {st['ysat']}")
    print("  運転のレベル（−17 dBFS の雑音）での Z の rms と、18 bit に飽和させる前の SHIFT の目安（rms の 2^3 倍の余裕で飽和しない最小）:")
    for N in MODES:
        sig = np.sqrt(fs_sine * 10 ** (-17 / 10))
        zrms = sig * np.sqrt(N) / 2                        # D = 1、|Z|² の平均 = N·σ²（Σh² = N）、成分ごとに 1/√2 だが余裕で見る
        sh = max(0, int(np.ceil(np.log2(zrms * 8 / (2 ** 17 - 1)))))
        print(f"    N = {N:5d}: Z の rms ≒ {zrms:.3g}（2^{np.log2(zrms):.1f}）→ SHIFT ≧ {sh}")
    print(f"  → {'通過' if ok else 'NG'}（D = 1・−30 dBFS で誤差 / 信号 ≦ 1e-4）")
    return ok


def slice_map(N, starts, wrong=False):
    """切り出しだけを積む積分器（8 銀行 × 深さ 1024 × 2 面）の番地。戻り値: [(k1, bin c, slice j, i, bank, addr)]
    wrong = True は陽性対照: M = 2048 で番地の上の bit を銀行に使わず捨てる（4 銀行 × 1024 に詰めた誤り）"""
    M = N // LANES
    R = SLICE // M if M <= SLICE else 1            # 1 本の流れが 1 クロックに受ける bin の数
    out = []
    for j, s in enumerate(starts):
        for i in range(SLICE):
            cch = s + i
            k1 = cch % M
            b = i // M
            a = i % M
            if M <= 1024:
                bank = R * j + b
                addr = a
            elif wrong:
                bank = 2 * j + b
                addr = a & 1023
            else:                                        # M = 2048: 流れ (j, b) を番地の上の bit で 2 銀行に
                bank = 2 * (2 * j + b) + (a >> 10)
                addr = a & 1023
            out.append((k1, cch, j, i, bank, addr))
    return out


def check_map(N, trials, nst, wrong=False):
    """(1 クロック 1 銀行の書き込みの最大, 番地が重なる・はみ出す組の数)"""
    worst_w = 0
    bad = 0
    for st in trials:
        mp = slice_map(N, st[:nst], wrong=wrong)
        per = {}
        for k1, cch, j, i, bank, addr in mp:                 # 1 クロック（k1）に 1 銀行 1 書き込みか
            per.setdefault((k1, bank), set()).add((j, i))
        worst_w = max(worst_w, max(len(v) for v in per.values()))
        keys = {(bank, addr) for *_, bank, addr in mp}       # (銀行, 番地) が流れの ch と 1 対 1 か・銀行 ≦ 7・番地 ≦ 1023
        if len(keys) != len(mp) or max(m[4] for m in mp) > 7 or max(m[5] for m in mp) > 1023:
            bad += 1
    return worst_w, bad


def m5():
    print("M-5 SLICE。ch c = k1 + M·k2。切り出しだけを積む積分器（8 銀行 × 1024 × 64 bit × 2 面）の番地の衝突と一致")
    rng = np.random.default_rng(5)
    ok = True
    for N in MODES:
        M = N // LANES
        nst = 1 if N == 8192 else 2
        trials = [[0]] if N == 8192 else [[0, 4096], [0, N // 2 - SLICE], [M - 1, M + 1]] + \
            [list(rng.integers(0, N // 2 - SLICE + 1, 2)) for _ in range(200)]
        worst_w, bad = check_map(N, trials, nst)
        # 積分の一致: 全 ch を積んだものの部分 = 切り出しの銀行から読み戻したもの
        x = rng.normal(0, 1000, N * 8)
        y = pfb_float(x, design(N), N)
        Pfull = sum(np.abs(np.fft.rfft(y[r])[: N // 2]) ** 2 for r in range(3, 8))
        st = trials[-1][:nst]
        mem = np.zeros((8, 1024))
        for r in range(3, 8):
            X = lanes_fft_float(y[r], N)
            P = np.abs(X) ** 2
            for k1, cch, j, i, bank, addr in slice_map(N, st):
                mem[bank, addr] += P[cch]
        diff = 0.0
        for k1, cch, j, i, bank, addr in slice_map(N, st):
            diff = max(diff, abs(mem[bank, addr] - Pfull[cch]) / Pfull[cch])
        good = worst_w <= 1 and bad == 0 and diff < 1e-9
        ok &= good
        print(f"  N = {N:5d}（M = {M}、1 本が 1 クロックに受ける bin {max(1, SLICE // M) if M <= SLICE else 1}）: 試した開始 ch {len(trials)} 組、"
              f"1 銀行 1 クロックの書き込みの最大 {worst_w}・番地の重なり/はみ出し {bad} 組・読み戻しの相対差 {diff:.1e} → {'通過' if good else 'NG'}")
    # 陽性対照: 同じ判定に、M = 2048 で番地の上の bit を捨てた誤りの番地を通す
    ww, wb = check_map(32768, [[0, 4096], [100, 9000]], 2, wrong=True)
    print(f"  陽性対照（512 MHz で番地の上の bit を捨てる誤り）: 書き込みの最大 {ww}・重なり {wb} 組 → "
          f"{'落ちる（正しい）' if (ww > 1 or wb) else '落ちない（判定が効いていない）'}")
    mem_full = {N: 2 * 8 * (N // LANES) * 64 for N in MODES}
    mem_slice = 2 * 8 * 1024 * 64
    print("  積分器の記憶 / ADC: 全 ch を積む " + "・".join(f"{N}: {v / 2**20:.2f} Mbit" for N, v in mem_full.items())
          + f" ／ 切り出しだけ（3 モード共通）{mem_slice / 2**20:.2f} Mbit")
    return ok


def m6():
    print("M-6 時刻。フレームの長さ・格子・PFB の重心")
    beat_ns = 1e3 / 256                                  # 256 MHz の 1 ビート
    ok = True
    for N in MODES:
        M = N // LANES
        fr_us = N / 4096.0
        dt = 40.96e3 / fr_us
        g = 2.048e3 / fr_us
        good = dt == int(dt) and g == int(g)
        ok &= good
        print(f"  N = {N:5d}: フレーム {fr_us:.0f} µs = {M} ビート、40.96 ms = {dt:.0f} フレーム、2.048 ms の格子 = {g:.0f} フレーム、"
              f"PFB の重心は矩形（最新のフレームの中央）より 1.5 フレーム前 = {1.5 * fr_us:.0f} µs（{1.5 * M:.0f} ビート）"
              f"、立ち上がり 3 フレーム = {3 * fr_us:.0f} µs → {'整数' if good else 'NG'}")
    # 重心を数で確かめる: インパルスを入れたとき、出力フレーム r の |h| の重みの重心がどこに来るか
    N = 8192
    h = design(N)
    w = h ** 2
    n = np.arange(T * N)
    cen = np.sum(w * n) / np.sum(w)
    print(f"  原型の重みの重心（h² で）: 区間 4N の頭から {cen / N:.4f} フレーム = 最新のフレームの頭から {(3 * N - cen) / N:.4f} フレーム前"
          f"（矩形の重心 = 最新のフレームの中央 より {(3.5 * N - cen) / N:.4f} フレーム前）")
    return ok


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    fns = dict(m1=m1, m2=m2, m3=m3, m4=m4, m5=m5, m6=m6)
    todo = list(fns) if what == "all" else [what]
    res = {}
    for k in todo:
        t0 = time.time()
        res[k] = fns[k]()
        print(f"  （{time.time() - t0:.1f} s）\n")
    print("まとめ: " + "  ".join(f"{k.upper()} {'通過' if v else 'NG'}" for k, v in res.items()))
    return 0 if all(res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
