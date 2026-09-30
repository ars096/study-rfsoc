#!/usr/bin/env python3
"""proj014 — 狭帯域の窓（bit ③）の仕様の模型。numpy だけで動く。

仕様（README の「着手の前に決めたこと」）:

  x[p]   実数、fs = 4096 MSPS、ゾーン 2（IF = 4096 − f、f は 0〜2048 MHz の標本化後の周波数）
  粗い PFB: ch 間隔 S = 128 MHz（M = 32）、4 倍のオーバーサンプリング（ホップ D = 8）、各 ch 複素 512 MSPS
      y_k[m] = Σ_n h[n] · x[p − n] · exp(−j2π k (p − n) / M)、 p = m·D + (N − 1)
      （k 番の粗い ch へ周波数を −k·S ずらし、原型の低域通過 h で絞って D で間引く。ポリフェーズ＋FFT はこの式の実装）
  窓: 中心 c（f の側で。IF の中心 C なら c = 4096 − C）、幅 W = 512 / 2^s（s = 1..6 → 256〜8 MHz）
      k = round(c / S)、d = c − k·S（|d| ≦ 64 MHz）
      v[m] = y_k[m] · exp(−j2π d m / 512)             NCO（細かいずらし）
      半帯域 ÷2 を s 段: 軽い段（light）× (s − 1) → 最終段（final）× 1。出力は複素 W MSPS
      4096 点 FFT（矩形窓）→ 電力。出力の ch b（fftshift 後 0..4095）↔ ν = (b − 2048)·W/4096、
      f = c + ν、IF = 4096 − c − ν（ゾーン 2 で反転する）
  要求: 中央 90 %（|ν| ≦ 0.45W）で
      - 平坦さ（主の経路の利得の p-p）≦ RIPPLE_PP dB
      - 主の経路以外（窓の外・折り返し・負の周波数の鏡像）から落ちる利得 ≦ −A dB
      両端 5 % は遷移帯として使わない（折り返しが落ちてよい）

各フィルタの要求はこの要求から導く（守るのは |ν| ≦ 0.45W だけ）:
  final:  レート 2W → W。通過 0.45W、阻止 0.55W（= 2W/2 − 0.45W）
  light:  レート R → R/2（後ろに final があるので W ≦ R/4）。通過 0.45·R/4、阻止 R/2 − 0.45·R/4
  PFB:    通過 |d|max + 0.45·Wmax = 64 + 115.2 = 179.2、阻止 512 − 179.2 = 332.8 MHz（fs = 4096）

検証は 2 層:
  1. 解析: 入力の周波数 f（両側、5 kHz 刻み）ごとに、各段の利得と行き先（間引きの折り返し）を追い、
     出力のどの ν にどの利得で落ちるかを全部数える。窓の置き場所は粗い ch の境目・中央・帯域の端・乱数
  2. 時間領域: 浮動小数点で連鎖をそのまま回し（CW）、1 の予言（ch の位置・利得・鏡像の量・最悪の折り返しの量）と比べる
陽性対照（--posctl）: pfb-short（原型を 1 タップ / 分岐に）/ hb-short（final の長さを半分に）/
  nco-sign（NCO の符号を逆に）/ ppfb（PFB の式の位相 exp(−j2πk p / M) を落とす）。どれも落ちるべきところで落ちれば通過

使い方:
  python3 win_model.py                # 設計・解析・時間領域・資源の見当。最後に「結果: 全部通過」
  python3 win_model.py --posctl all   # 陽性対照 4 通り（それぞれ落ちれば「結果: 全部通過」）
  python3 win_model.py --A 50 70      # 要求の深さを振った設計の比較（情報）
  python3 win_model.py --json coeffs.json   # 設計した係数を書き出す
"""
import argparse
import json
import math
import sys

import numpy as np

FS = 4096.0            # MHz
S = 128.0              # 粗い ch の間隔
M = 32                 # FS / S
O = 4                  # オーバーサンプリング
D = M // O             # 8
R0 = FS / D            # 512 MHz（粗い ch の出力レート、複素）
WIDTHS = [256.0, 128.0, 64.0, 32.0, 16.0, 8.0]
NFFT = 4096
EDGE = 0.05
USE = 0.5 - EDGE       # 0.45
DMAX = S / 2           # |d| の最大
COEF_BITS = 18         # DSP48E2 の B ポート
DF = 0.005             # 解析の刻み（MHz）= 5 kHz
RIPPLE_PP = 0.1        # dB


# ------------------------------------------------------------------ 設計

def kaiser_beta(a):
    if a > 50:
        return 0.1102 * (a - 8.7)
    if a >= 21:
        return 0.5842 * (a - 21) ** 0.4 + 0.07886 * (a - 21)
    return 0.0


METHOD = "minimax"      # minimax（Lawson の反復重み付き最小二乗 = 等リプル）/ kaiser（窓関数法。初版）


def lawson(N, bands, desired, weights, fs, iters=400):
    """対称な FIR（長さ N）の等リプル（最大誤差の最小化）設計。Lawson の反復重み付き最小二乗。numpy だけ。
    scipy.signal.remez と同じ解に収束する（2026-09-29 に PFB 96 タップ・半帯域で突き合わせた）。"""
    even = N % 2 == 0
    M = N // 2 if even else (N - 1) // 2
    k = (np.arange(M) + 0.5) if even else np.arange(M + 1)
    fs_, ds, ws = [], [], []
    for (a, b), d, q in zip(bands, desired, weights):
        n = max(20, int(12 * N * (b - a) / (fs / 2)))
        fs_.append(np.linspace(a, b, n)); ds.append(np.full(n, float(d))); ws.append(np.full(n, float(q)))
    f, D, Wt = np.concatenate(fs_), np.concatenate(ds), np.concatenate(ws)
    C = np.cos(2 * np.pi * np.outer(f, k) / fs)
    if even:
        C *= 2
    else:
        C[:, 1:] *= 2
    v = np.ones(len(f)) / len(f)
    for _ in range(iters):
        sw = np.sqrt(v * Wt)
        a, *_ = np.linalg.lstsq(C * sw[:, None], D * sw, rcond=None)
        v = v * (np.abs(C @ a - D) * Wt)
        v /= v.sum()
    return np.concatenate([a[::-1], a]) if even else np.concatenate([a[:0:-1], a])


def resp(h, f, rate):
    """対称な係数の零位相の応答（実数）。f と rate は同じ単位。"""
    n = np.arange(len(h)) - (len(h) - 1) / 2.0
    f = np.atleast_1d(np.asarray(f, dtype=float))
    out = np.empty(f.shape)
    step = max(1, 4_000_000 // len(h))
    for i in range(0, f.size, step):
        out.flat[i:i + step] = np.cos(2 * np.pi * np.outer(f.flat[i:i + step] / rate, n)) @ h
    return out


def quantize(h, bits=COEF_BITS):
    """符号付き bits ビット。最大の係数が入る 2 のべき乗のスケールで丸める。"""
    full = 2 ** (bits - 1) - 1
    sh = math.floor(math.log2(full / np.max(np.abs(h))))
    q = np.round(h * 2.0 ** sh)
    return q / 2.0 ** sh, q.astype(np.int64), sh


def meets(h, rate, fp, fst, a, ripple_pp):
    fpass = np.linspace(0, fp, 400)
    fstop = np.linspace(fst, rate / 2, 2000)
    hp = np.abs(resp(h, fpass, rate))
    hs = np.abs(resp(h, fstop, rate))
    rip = 20 * np.log10(hp.max() / hp.min())
    att = -20 * np.log10(hs.max() / hp.mean())
    return rip <= ripple_pp and att >= a, rip, att


def design_halfband(fp_n, a, ripple_pp, lmin=1, lmax=80):
    """半帯域（中心 0.5・偶数番目の係数 0）。fp_n = 通過の端 / レート。阻止の端は 0.5 − fp_n。
    長さ 4L − 1（0 でない係数は中心と ±1, ±3, …, ±(2L − 1)）。量子化した後でも要求を満たす最小の L。"""
    for L in range(lmin, lmax + 1):
        N = 4 * L - 1
        n = np.arange(N) - (N - 1) // 2
        cands = []
        if METHOD == "minimax":
            # 半帯域の定石: 長さ 2L の g を通過 [0, 2·fp_n] で 1 に近づけ（型 II なので 0.5 で 0）、奇数番目に g/2、中心に 1/2
            g = lawson(2 * L, [(0.0, 2 * fp_n)], [1.0], [1.0], 1.0)
            h = np.zeros(N); h[0::2] = g / 2; h[(N - 1) // 2] = 0.5
            cands.append((h / h.sum(), 0.0))
        for extra in np.arange(0.0, 25.0, 3.0):    # Kaiser の β を深めに振って、短い長さで通る形を探す（平坦さが律速の段がある）
            h = 0.5 * np.sinc(n / 2.0) * np.kaiser(N, kaiser_beta(a + extra))
            h[(n % 2 == 0) & (n != 0)] = 0.0
            cands.append((h / h.sum(), extra))
        for h, extra in cands:
            hq, _, _ = quantize(h)
            ok, rip, att = meets(hq, 1.0, fp_n, 0.5 - fp_n, a, ripple_pp)
            if ok:
                return {"h": hq, "L": L, "N": N, "ripple_pp": rip, "att": att, "beta_extra": extra,
                        "method": "minimax" if (METHOD == "minimax" and extra == 0.0 and h is cands[0][0]) else "kaiser"}
    raise RuntimeError("halfband: 要求を満たす長さが見つからない")


def design_pfb(fp, fst, a, ripple_pp, tmin=1, tmax=12):
    """原型の低域通過。長さ N = M·T（T = 分岐あたりのタップ数）。量子化の後でも要求を満たす最小の T。"""
    for T in range(tmin, tmax + 1):
        N = M * T
        if METHOD == "minimax":
            for wt in (1.0, 2.0, 3.0, 5.0):        # 阻止の重み（平坦さの予算との釣り合いで選ぶ）
                h = lawson(N, [(0.0, fp), (fst, FS / 2)], [1.0, 0.0], [1.0, wt], FS)
                hq, _, _ = quantize(h / h.sum())
                ok, rip, att = meets(hq, FS, fp, fst, a, ripple_pp)
                if ok:
                    return {"h": hq, "T": T, "N": N, "fc": float("nan"), "ripple_pp": rip, "att": att,
                            "beta_extra": 0.0, "method": f"minimax（阻止の重み {wt:g}）"}
        for extra in np.arange(0.0, 25.0, 3.0):
            for fc in np.linspace(fp, fst, 9)[1:-1]:
                n = np.arange(N) - (N - 1) / 2.0
                h = 2 * fc / FS * np.sinc(2 * fc / FS * n) * np.kaiser(N, kaiser_beta(a + extra))
                h = h / h.sum()
                hq, _, _ = quantize(h)
                ok, rip, att = meets(hq, FS, fp, fst, a, ripple_pp)
                if ok:
                    return {"h": hq, "T": T, "N": N, "fc": fc, "ripple_pp": rip, "att": att, "beta_extra": extra,
                            "method": "kaiser"}
    raise RuntimeError("PFB: 要求を満たす長さが見つからない")


def design(a, ripple_pp, posctl=None):
    # 平坦さの予算: PFB・light・final に分ける（dB の和で効く。light は最大 5 段）
    r_pfb, r_light, r_final = ripple_pp * 0.3, ripple_pp * 0.05, ripple_pp * 0.3
    fp_pfb = DMAX + USE * WIDTHS[0]
    fst_pfb = R0 - fp_pfb
    pfb = design_pfb(fp_pfb, fst_pfb, a, r_pfb)
    light = design_halfband(USE / 4.0, a, r_light)
    final = design_halfband(USE / 2.0, a, r_final)
    if posctl == "pfb-short":
        N = M * 1
        n = np.arange(N) - (N - 1) / 2.0
        fc = (fp_pfb + fst_pfb) / 2
        h = 2 * fc / FS * np.sinc(2 * fc / FS * n) * np.kaiser(N, kaiser_beta(a))
        pfb = dict(pfb, h=quantize(h / h.sum())[0], T=1, N=N)
    if posctl == "hb-short":
        L = max(1, final["L"] // 2)
        N = 4 * L - 1
        n = np.arange(N) - (N - 1) // 2
        h = 0.5 * np.sinc(n / 2.0) * np.kaiser(N, kaiser_beta(a))
        h[(n % 2 == 0) & (n != 0)] = 0.0
        final = dict(final, h=quantize(h / h.sum())[0], L=L, N=N)
    return {"pfb": pfb, "light": light, "final": final, "fp_pfb": fp_pfb, "fst_pfb": fst_pfb}


# ------------------------------------------------------------------ 解析（層 1）

def nstages(W):
    return int(round(math.log2(R0 / W)))


def window_params(c):
    k = int(round(c / S))
    return k, c - k * S


def wrap(f, rate):
    return (f + rate / 2.0) % rate - rate / 2.0


class Lut:
    """フィルタの応答を DF 刻みで一周期ぶん持ち、整数の添字で引く（解析の走査を速くするため）。"""

    def __init__(self, h, rate):
        self.n = int(round(rate / DF))
        grid = np.arange(self.n) * DF
        self.v = np.abs(resp(h, grid, rate))

    def __call__(self, fi):
        return self.v[np.mod(fi, self.n)]


def wrap_i(fi, n):
    return np.mod(fi + n // 2, n) - n // 2


def analyze_window(c, W, luts):
    """入力 f（両側・DF 刻み）ごとに、出力の ν と利得を返す。整数（DF 単位）で折り返しを厳密に追う。"""
    nfs = int(round(FS / DF))
    fi = np.arange(-nfs // 2, nfs // 2, dtype=np.int64)
    k, d = window_params(c)
    ki = int(round(k * S / DF))
    di = int(round(d / DF))
    f1 = fi - ki
    g = luts["pfb"](f1)
    n0 = int(round(R0 / DF))
    f2 = wrap_i(wrap_i(f1, n0) - di, n0)
    ns = nstages(W)
    rate_i = n0
    for j in range(ns):
        lut = luts[("final" if j == ns - 1 else "light", rate_i)]
        g = g * lut(f2)
        rate_i //= 2
        f2 = wrap_i(f2, rate_i)
    ci = int(round(c / DF))
    principal = (fi - ci - f2) == 0
    return fi, f2, g, principal


def build_luts(des):
    luts = {"pfb": Lut(des["pfb"]["h"], FS)}
    rate = R0
    for _ in range(nstages(WIDTHS[-1])):
        for kind in ("light", "final"):
            luts[(kind, int(round(rate / DF)))] = Lut(des[kind]["h"], rate)
        rate /= 2
    return luts


def centers_for(W, rng, nrand=40):
    lo, hi = W / 2, 2048.0 - W / 2
    cs = [lo, hi]
    cs += [S * k for k in range(17) if lo <= S * k <= hi]                   # 粗い ch の中央
    cs += [S * k + S / 2 for k in range(16) if lo <= S * k + S / 2 <= hi]   # 粗い ch の境目（|d| = 64）
    cs += [S * k + S / 2 - DF for k in range(16) if lo <= S * k + S / 2 - DF <= hi]
    grid = W / NFFT                                                          # ch の格子（PS の既定）
    cs += list(np.round(rng.uniform(lo, hi, nrand) / grid) * grid)
    return sorted(set(round(x / DF) * DF for x in cs))


def analyze_all(des, rng, quiet=False):
    luts = build_luts(des)
    res = {}
    ok_all = True
    for W in WIDTHS:
        worst_alias, worst_rip = -1e9, 0.0
        worst = None
        for c in centers_for(W, rng):
            fi, nu, g, pr = analyze_window(c, W, luts)
            use = np.abs(nu) <= int(round(USE * W / DF))
            gp = g[pr & use]
            g0 = gp.mean()
            rip = 20 * np.log10(gp.max() / gp.min())
            ga = g[(~pr) & use]
            ia = int(np.argmax(ga))
            alias_db = 20 * np.log10(ga[ia] / g0)
            if alias_db > worst_alias:
                sel = np.flatnonzero((~pr) & use)[ia]
                worst_alias = alias_db
                worst = {"c": c, "f": fi[sel] * DF, "nu": nu[sel] * DF, "db": alias_db}
            worst_rip = max(worst_rip, rip)
        res[W] = {"alias_db": worst_alias, "ripple_pp": worst_rip, "worst": worst,
                  "ncenters": len(centers_for(W, rng))}
    return res, luts


# ------------------------------------------------------------------ 時間領域（層 2）

def fir_decim(x, h, step, phase0=0):
    """z[q] = Σ_j h_rev[j] · x[q·step + phase0 + j]（窓の頭を q·step に置いた相関）。h が対称なら畳み込みと同じ。"""
    N = len(h)
    nout = (len(x) - N - phase0) // step + 1
    out = np.empty(nout, dtype=complex)
    hr = h[::-1]
    blk = 1 << 16
    for i in range(0, nout, blk):
        j = min(nout, i + blk)
        idx = (np.arange(i, j) * step + phase0)[:, None] + np.arange(N)[None, :]
        out[i:j] = x[idx] @ hr
    return out


def run_chain(x, c, W, des, posctl=None):
    k, d = window_params(c)
    h = des["pfb"]["h"]
    N = len(h)
    n = np.arange(N)
    gk = h * np.exp(2j * np.pi * k * n / M)          # h[n]·exp(+j2πkn/M)
    z = fir_decim(x.astype(complex), gk, D)          # Σ_n gk[n] x[p − n]、p = m·D + N − 1
    p = np.arange(len(z)) * D + (N - 1)
    if posctl != "ppfb":
        z = z * np.exp(-2j * np.pi * k * (p % M) / M)
    m = np.arange(len(z))
    sgn = +1 if posctl == "nco-sign" else -1
    v = z * np.exp(sgn * 2j * np.pi * d * m / R0)
    ns = nstages(W)
    for j in range(ns):
        hb = des["final" if j == ns - 1 else "light"]["h"]
        v = fir_decim(v, hb, 2)
    return v


def spectrum(v, nfr):
    v = v[len(v) - nfr * NFFT:]                      # 頭の過渡を捨てる（後ろから nfr フレーム）
    X = np.fft.fftshift(np.fft.fft(v.reshape(nfr, NFFT), axis=1), axes=1)
    return (np.abs(X) ** 2).mean(axis=0)


def chain_gain(f, c, W, des, posctl=None):
    """1 本の入力の周波数 f（MHz、両側）の行き先 ν と利得（解析の式を任意の f で）。"""
    k, d = window_params(c)
    f1 = f - k * S
    g = abs(resp(des["pfb"]["h"], f1, FS)[0])
    sgn = +1 if posctl == "nco-sign" else -1
    f2 = wrap(wrap(f1, R0) + sgn * d, R0)
    rate = R0
    ns = nstages(W)
    for j in range(ns):
        g *= abs(resp(des["final" if j == ns - 1 else "light"]["h"], f2, rate)[0])
        rate /= 2
        f2 = wrap(f2, rate)
    return f2, g


def tone_test(c, W, f0, des, posctl=None, nfr=2):
    """CW cos(2π f0 t) を入れ、+f0 と −f0 の行き先の予言と比べる。
    返り値: (主の ch の一致, 主の利得の差 dB, その他の ch の電力 / 予言)。"""
    ns = nstages(W)
    dec = D * 2 ** ns
    L = (nfr * NFFT + 64) * dec + 4096
    t = np.arange(L)
    x = np.cos(2 * np.pi * f0 / FS * t)
    v = run_chain(x, c, W, des, posctl)
    P = spectrum(v, nfr) / NFFT ** 2                 # 振幅 a の複素正弦 → a²
    nu_p, g_p = chain_gain(f0, c, W, des)
    nu_m, g_m = chain_gain(-f0, c, W, des)
    b_exp = int(round(nu_p / (W / NFFT))) + NFFT // 2
    b_meas = int(np.argmax(P))
    pk = P[b_exp] / (g_p ** 2 / 4)
    other = P.sum() - P[b_exp]                       # 絶対量（入力の振幅 1）
    pred = g_m ** 2 / 4                              # 鏡像（−f0）の行き先に落ちる量の予言
    return b_meas == b_exp, 10 * np.log10(pk), other, pred, b_meas, b_exp


def alias_tone_test(worst, W, des, posctl=None, nfr=2):
    """解析で最悪だった折り返しの入力を、出力の ch の中心に落ちるよう少しずらして入れ、落ちる量を予言と比べる。"""
    c = worst["c"]
    grid = W / NFFT
    nu_t = round(worst["nu"] / grid) * grid
    f0 = worst["f"] + (nu_t - worst["nu"])
    if f0 < 0:                                        # cos は ±f0 を持つので正の側で与えてよい
        f0 = -f0
    f0 = f0 % FS
    nu_a, g_a = chain_gain(f0, c, W, des)
    nu_b, g_b = chain_gain(-f0, c, W, des)
    ns = nstages(W)
    dec = D * 2 ** ns
    L = (nfr * NFFT + 64) * dec + 4096
    t = np.arange(L)
    x = np.cos(2 * np.pi * f0 / FS * t)
    v = run_chain(x, c, W, des, posctl)
    P = spectrum(v, nfr) / NFFT ** 2
    # どちらか（worst が指す側）が ch の中心に来ている
    cand = [(nu_a, g_a), (nu_b, g_b)]
    nu_x, g_x = min(cand, key=lambda z: abs(z[0] - nu_t))
    b = int(round(nu_x / grid)) + NFFT // 2
    return 10 * np.log10(P[b] / (g_x ** 2 / 4)), 20 * np.log10(g_x), f0


# ------------------------------------------------------------------ 資源の見当（情報）

def resources(des):
    pfb, light, final = des["pfb"], des["light"], des["final"]
    frames_per_clk = (FS / D) / 256.0               # 2 フレーム / クロック（256 MHz）
    # **前置加算は使えない**: 対称の相手 h[N−1−n] は別の分岐（31 − r）の和に入るので、1 つの和の中で組にならない
    pfb_mult = frames_per_clk * pfb["N"]
    fin = 2 * final["L"]                              # 複素・対称（前置加算で L 個 / 成分）・1 出力 / クロック（W = 256）
    lig = 2 * light["L"] * 2                          # 1 + 1/2 + 1/4 + … ≒ 2 倍（時分割）
    nco = 2 * 3                                       # 2 サンプル / クロック × 複素乗算 3 DSP
    dft16 = frames_per_clk * 8 * 4                    # 16 点 複素 DFT: 自明でないひねり係数 8 個 × cmul 4 DSP、2 フレーム / クロック
    post = frames_per_clk * 4                         # 窓 1 つにつき選んだ ch の実数化の後処理 cmul 1 個
    return {"pfb_fir_dsp_per_adc": pfb_mult, "pfb_dft16_dsp_per_adc": dft16, "post_dsp_per_window": post,
            "final_dsp": fin, "light_dsp": lig, "nco_dsp": nco,
            "per_window_dsp_wo_fft": fin + lig + nco + post}


# ------------------------------------------------------------------ 本体

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--A", type=float, nargs="*", default=None, help="要求の深さ（dB）を振って設計を比べる（情報）")
    ap.add_argument("--a", type=float, default=60.0, help="要求の深さ（dB）")
    ap.add_argument("--posctl", default=None, help="pfb-short / hb-short / nco-sign / ppfb / all")
    ap.add_argument("--json", default=None, help="係数を書き出す")
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--no-time", action="store_true", help="時間領域を省く")
    ap.add_argument("--method", default=None, help="minimax（既定）/ kaiser（初版の窓関数法）")
    args = ap.parse_args()
    global METHOD
    if args.method:
        METHOD = args.method

    if args.A:
        print("要求の深さ A と設計（情報。平坦さの要求は", RIPPLE_PP, "dB p-p）")
        print(f"{'A':>4} | {'PFB T (N)':>10} | {'light L (N)':>11} | {'final L (N)':>11} | PFB の DSP/ADC | 窓 1 つの DSP（FFT 除く）")
        for a in args.A:
            des = design(a, RIPPLE_PP)
            r = resources(des)
            print(f"{a:4.0f} | {des['pfb']['T']:>3} ({des['pfb']['N']:>4}) | {des['light']['L']:>4} ({des['light']['N']:>4}) |"
                  f" {des['final']['L']:>4} ({des['final']['N']:>4}) | {r['pfb_fir_dsp_per_adc']:>14.0f} | {r['per_window_dsp_wo_fft']:>6}")
        return 0

    if args.posctl == "all":
        import subprocess
        bad = 0
        for pc in ("pfb-short", "hb-short", "nco-sign", "ppfb"):
            print(f"===== 陽性対照 {pc}")
            rc = subprocess.call([sys.executable, __file__, "--posctl", pc, "--a", str(args.a)])
            bad += rc != 0
        print("結果: 全部通過" if bad == 0 else f"結果: 失敗 {bad} 件")
        return 1 if bad else 0

    rng = np.random.default_rng(args.seed)
    des = design(args.a, RIPPLE_PP, args.posctl)
    pfb, light, final = des["pfb"], des["light"], des["final"]
    print(f"要求: 中央 90 % の平坦さ ≦ {RIPPLE_PP} dB p-p、主の経路以外 ≦ −{args.a:.0f} dB。係数 {COEF_BITS} bit")
    print(f"設計法: {METHOD}")
    print(f"PFB   : 通過 {des['fp_pfb']:.1f} / 阻止 {des['fst_pfb']:.1f} MHz → T = {pfb['T']}（N = {pfb['N']}、{pfb['method']}）、"
          f"fc {pfb.get('fc', float('nan')):.1f} MHz、平坦さ {pfb['ripple_pp']:.4f} dB、阻止 {pfb['att']:.1f} dB")
    print(f"light : 通過 {USE/4:.4f}·R / 阻止 {0.5-USE/4:.4f}·R → L = {light['L']}（N = {light['N']}）、"
          f"平坦さ {light['ripple_pp']:.4f} dB、阻止 {light['att']:.1f} dB")
    print(f"final : 通過 {USE/2:.4f}·R / 阻止 {0.5-USE/2:.4f}·R → L = {final['L']}（N = {final['N']}）、"
          f"平坦さ {final['ripple_pp']:.4f} dB、阻止 {final['att']:.1f} dB")

    fails = []
    # --- 層 1: 解析
    res, _ = analyze_all(des, rng)
    print("\n層 1（解析、入力 ±2048 MHz を 5 kHz 刻み、窓の置き場所は境目・中央・端・乱数）")
    print(f"{'W':>6} | 置き場所 | 平坦さ p-p | 主以外の最悪 | その入力 f → ν（窓の中心 c）")
    for W in WIDTHS:
        r = res[W]
        w = r["worst"]
        print(f"{W:6.0f} | {r['ncenters']:>8} | {r['ripple_pp']:8.4f} dB | {r['alias_db']:8.1f} dB | "
              f"{w['f']:+9.3f} → {w['nu']:+8.3f}（c {w['c']:.3f}）")
        if r["ripple_pp"] > RIPPLE_PP:
            fails.append(f"平坦さ W={W}")
        if r["alias_db"] > -args.a:
            fails.append(f"主以外 W={W}")

    # --- 層 2: 時間領域
    if not args.no_time:
        print("\n層 2（時間領域、浮動小数点、CW）")
        print(f"{'W':>6} | 窓の中心 c | 入力 f0 | ch 予言 / 実測 | 主の利得の差 | 鏡像の電力 / 予言 | 最悪の折り返し 実測 − 予言（予言）")
        for W in WIDTHS:
            lo, hi = W / 2, 2048.0 - W / 2
            grid = W / NFFT
            cs = [S * 5 + S / 2, round(rng.uniform(lo, hi) / grid) * grid]  # 粗い ch の境目と乱数
            for c in cs:
                nu = round(rng.uniform(-USE * W, USE * W) / grid) * grid
                f0 = c + nu
                okb, dpk, oth, pred, bm, be = tone_test(c, W, f0, des, args.posctl)
                ratio = oth / pred if pred > 0 else float("inf")
                line = f"{W:6.0f} | {c:9.4f} | {f0:9.4f} | {be:4d} / {bm:4d} | {dpk:+8.4f} dB | {ratio:8.4f}（{10*np.log10(max(pred,1e-300)/0.25):6.1f} dB）"
                if not okb:
                    fails.append(f"ch の位置 W={W} c={c}")
                if abs(dpk) > 0.01:
                    fails.append(f"主の利得 W={W} c={c}")
                if oth > 1.05 * pred + 1e-14:            # 1e-14 = 主の −134 dB（倍精度の連鎖の床）
                    fails.append(f"主以外の電力 W={W} c={c}")
                if c == cs[0]:
                    da, pred, fa = alias_tone_test(res[W]["worst"], W, des, args.posctl)
                    line += f" | {da:+7.3f} dB（{pred:6.1f} dB、f0 {fa:.3f}）"
                    if abs(da) > 0.1:
                        fails.append(f"折り返しの量 W={W}")
                print(line)

    r = resources(des)
    print("\n資源の見当（情報）: PFB の FIR {:.0f} DSP / ADC（2 フレーム / クロック × N。前置加算は使えない）、"
          "16 点 DFT {:.0f} / ADC、窓 1 つ（FFT 除く）{:.0f} DSP（final {} ＋ light {} ＋ NCO {} ＋ 実数化 {:.0f}）".format(
              r["pfb_fir_dsp_per_adc"], r["pfb_dft16_dsp_per_adc"], r["per_window_dsp_wo_fft"], r["final_dsp"],
              r["light_dsp"], r["nco_dsp"], r["post_dsp_per_window"]))

    if args.json:
        out = {}
        for key in ("pfb", "light", "final"):
            _, qi, sh = quantize(des[key]["h"])
            out[key] = {"N": int(len(qi)), "shift": int(sh), "coef": [int(v) for v in qi]}
        out["params"] = {"FS": FS, "S": S, "M": M, "O": O, "D": D, "R0": R0, "COEF_BITS": COEF_BITS,
                         "A": args.a, "RIPPLE_PP": RIPPLE_PP}
        with open(args.json, "w") as fp:
            json.dump(out, fp, indent=1)
        print("係数:", args.json)

    if args.posctl:
        if fails:
            print(f"陽性対照 {args.posctl}: 落ちた（{len(fails)} 件。例: {fails[0]}）→ 結果: 全部通過")
            return 0
        print(f"陽性対照 {args.posctl}: 落ちなかった → 結果: 失敗（見張りが効いていない）")
        return 1
    if fails:
        print("結果: 失敗", fails)
        return 1
    print("結果: 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
