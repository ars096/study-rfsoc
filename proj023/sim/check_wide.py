#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj023 — SAM45-Wide の sim の模型と判定（wide_pfb・wide_core）。check.py（spec_core）の流儀を 32768 点・束ね B に広げたもの。

    python3 sim/check_wide.py selftest            # 模型どうしの突き合わせと陽性対照（RTL なし。数十秒）
    python3 sim/check_wide.py gen OUT [NF]        # OUT/stim.hex（1 行 = 1 ビート、256 bit）・OUT/stim14.npy を作る
    python3 sim/check_wide.py pfb OUT [posctl]    # A1: OUT/pfbout.txt（wide_pfb の出口）を PFB の整数模型と bit 単位で（手順 2b）
    python3 sim/check_wide.py genchain OUT [NF]   # OUT/lanes_in.txt（IP の出口を模型で）・stim14.npy（手順 2c-1）
    python3 sim/check_wide.py chain OUT LB SHIFT [posctl]   # A2 の後半: OUT/chain_out.txt（wide_chain の束ねの出口）を模型と bit 単位で
    python3 sim/check_wide.py spec OUT [posctl]    # 手順 2c-2: wide_spec の A1'・A2・B・C（OUT/meta.txt・lanes.txt・dumps.txt）

---- 鎖（README の D-1・D-3、proj022 の M-4）----
  x 14 bit（ADC の 16 bit の上位 14）
  → PFB（T = 4）: acc = Σ_t c[t·N + n]·x[(r − 3 + t)·N + n]、y = round(acc / 2^16)、15 bit に飽和（YF = 0）
  → 16 レーン（y[16m + p] がレーン p の m 番目）× レーン FFT 2048 点（IP、unscaled）: Y 26 bit
  → ひねり係数 W_32768^(p·k1)（18 bit、2^16 = 1）× cmul、(… + 2^16) >> 17（D = 1）: V 25 bit
  → dft16（今の RTL のまま。4 点 → W16 の cmul（>> 16）→ 4 点）: U 27・Z 29 bit、k2 = 0..7
  → Z >> SHIFT（切り捨て）→ 18 bit に飽和 → 電力 re² + im²（37 bit）。細かい ch c = k1 + 2048·k2（0 .. 16383）
  → 束ね: 束ねた ch j = Σ_{b<B} p[B·j + b]（B = 1・2・4）。続く B 個は同じ銀行 k2 の続く B クロック（2048 は B で割り切れる）
  → 切り出し: 流れ s の ch i = 束ねた ch S0_s + i（i < 4096）→ 64 bit で N_ACC フレーム積む
  Z = X·2^(−D)（X は 32768 点の rfft、y の目盛り）。

---- 判定の層（D-3）----
  A1  PFB の出口（IP の入口）を整数模型と bit 単位
  A2  IP の出口（lanes.txt）から先を整数模型と bit 単位（ひねり係数・dft16・丸め・飽和・電力・束ね・積分・切り出し）
  B   刺激（stim14）から浮動小数点（PFB ＋ rfft ＋ 束ね）と振幅の許容。**分解の式そのもの**を、整数模型を介さずに
  C   帳簿
  **IP（レーン FFT）は sim では行動模型**（lane_fft_model.v、倍精度の DFT を丸めたもの）。IP 自身との一致は実機で見る。
"""
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import wide_model as WM                                    # noqa: E402  原型と係数（設計の唯一の正）

N = 32768            # 実際の FFT（N_PHYS）
P = 16               # レーン
M = N // P           # 2048 = レーン FFT の点数 = 1 フレームのビート数
T = 4                # PFB のタップ
CF = 16              # 係数の小数部
XW, YW = 14, 15      # 入力・PFB の出口
D = 1                # ひねり係数の cmul の余分な右シフト（>> 16 + D）
VW, UW, ZW, QW = 25, 27, 29, 18
QMAX, QMIN = (1 << (QW - 1)) - 1, -(1 << (QW - 1))
NCH = N // 2         # 細かい ch 16384
SLICE = 4096
BS = (1, 2, 4)       # 束ね（512 MHz・1 GHz・全帯域）


# ---------------------------------------------------------------- 係数（wide_model と同じ）
def coef():
    """PFB の係数 c[t·N + n]（int64、18 bit）。wide_model.design(N)（対称・proj020 の作り）を量子化したもの"""
    return WM.quantize(WM.design(N))


def coef_words(c=None):
    """ROM の語: レーン p・番地 m に 4 タップ {c[3N + 16m + p], c[2N + …], c[N + …], c[16m + p]}（各 18 bit、t = 0 が下位）。
    戻り値 [p][m] の int（72 bit）。RTL の係数 ROM の中身（手順 2b で URAM の初期値にする）"""
    c = coef() if c is None else c
    ct = c.reshape(T, M, P)                                   # [t, m, p]
    w = np.zeros((P, M), dtype=object)
    for t in range(T):
        w += (ct[t].T.astype(object) & 0x3FFFF) << (18 * t)
    return w


# ---------------------------------------------------------------- 入力
def stim(nf, seed=23):
    """試験の刺激（14 bit）。線の置き場所は束ねと切り出しの境を突くように選ぶ"""
    rng = np.random.default_rng(seed)
    n = np.arange(nf * N)
    x = rng.normal(0.0, 150.0, nf * N)
    x += 1500.0 * np.cos(2 * np.pi * 5000.37 * n / N + 0.4)    # 細かい ch の間の強い線
    x += 400.0 * np.cos(2 * np.pi * 8191.0 * n / N)            # 銀行 k2 = 3 の最後（k1 = 2047）
    x += 400.0 * np.cos(2 * np.pi * 8192.0 * n / N + 0.7)      # 銀行 k2 = 4 の最初（k1 = 0）
    x += 600.0 * np.cos(2 * np.pi * 12287.5 * n / N + 1.1)     # 束ね B 4 の区切り（12287 | 12288）の上
    x += 2000.0 * np.cos(2 * np.pi * 16383.0 * n / N + 1.0)    # 最後の ch
    return np.clip(np.round(x), -(1 << (XW - 1)), (1 << (XW - 1)) - 1).astype(np.int64)


def gen(out, nf=8):
    os.makedirs(out, exist_ok=True)
    x14 = stim(nf)
    x16 = (x14 * 4) & 0xFFFF
    with open(os.path.join(out, "stim.hex"), "w") as f:
        for m in range(nf * M):
            w = 0
            for p in range(P):
                w |= int(x16[P * m + p]) << (16 * p)
            f.write("%064x\n" % w)
    np.save(os.path.join(out, "stim14.npy"), x14)
    print("wrote %s/stim.hex（%d フレーム × %d ビート）" % (out, nf, M))


# ---------------------------------------------------------------- 整数模型
def rs_round(v, s):
    return (v + (1 << (s - 1))) >> s


def pfb_int(x14, c=None, hist0=None):
    """A1 の模型。x14（長さ N の倍数）→ y[r, n]（int64、15 bit に飽和）・飽和の数。
    起動の直後は履歴 0（r − 3 + t < 0 のタップは 0。hist0 で前の 3 フレームを与えられる）"""
    c = coef() if c is None else c
    nf = len(x14) // N
    xf = np.asarray(x14[: nf * N], dtype=np.int64).reshape(nf, N)
    if hist0 is not None:
        xf = np.vstack([np.asarray(hist0, dtype=np.int64).reshape(T - 1, N), xf])
    ct = c.reshape(T, N)
    acc = np.zeros_like(xf)
    for t in range(T):
        sh = T - 1 - t
        acc[sh:] += ct[t] * xf[: len(xf) - sh]
    if hist0 is not None:
        acc = acc[T - 1:]
    y = rs_round(acc, CF)
    lo, hi = -(1 << (YW - 1)), (1 << (YW - 1)) - 1
    nsat = int(np.sum((y < lo) | (y > hi)))
    return np.clip(y, lo, hi), nsat


def lanes_ip(y_frame):
    """IP の行動模型（lane_fft_model.v と同じ: 倍精度の DFT を最も近い整数に）。y[N] → Y[p, k1]（re, im の int64）"""
    yp = np.asarray(y_frame, dtype=np.float64).reshape(M, P).T
    Y = np.fft.fft(yp, axis=1)
    return np.rint(Y.real).astype(np.int64), np.rint(Y.imag).astype(np.int64)


def _tw(p, k1):  # tools/gen_tw_rom.py の式を 32768 点に（手順 2c で生成器を直すときもこの式）
    a = 2.0 * math.pi * p * k1 / N
    return round(65536 * math.cos(a)), round(-65536 * math.sin(a))


TWR = np.array([[_tw(p, k1)[0] for k1 in range(M)] for p in range(P)], dtype=np.int64)
TWI = np.array([[_tw(p, k1)[1] for k1 in range(M)] for p in range(P)], dtype=np.int64)
W16 = {0: (65536, 0), 1: (60547, -25080), 2: (46341, -46341), 3: (25080, -60547),
       4: (0, -65536), 6: (-46341, -46341), 9: (-60547, 25080)}       # check.py と同じ（dft16 の定数）


def _cmul(ar, ai, wr, wi, s, ow):
    yr = rs_round(ar * wr - ai * wi, s)
    yi = rs_round(ar * wi + ai * wr, s)
    lim = 1 << (ow - 1)
    assert yr.min() >= -lim and yr.max() < lim and yi.min() >= -lim and yi.max() < lim, "cmul の出力が %d bit に収まらない" % ow
    return yr, yi


def chain_int(Yr, Yi, shift, tw_skew=0):
    """A2 の模型（1 フレーム）。Y[p, k1] → 細かい ch の電力 pw[16384]（int64）・飽和の数・Z（re, im、[k2, k1]）。
    check.py の model_frame と同じ式（dft16 の段 1〜3）を、k1 について numpy で並べたもの。tw_skew は陽性対照（番地をずらす）"""
    k1 = (np.arange(M) + tw_skew) % M
    Vr, Vi = _cmul(Yr, Yi, TWR[:, k1], TWI[:, k1], 16 + D, VW)
    x = [(Vr[4 * a:4 * a + 4], Vi[4 * a:4 * a + 4]) for a in range(4)]     # x[a][re|im][b, k1]
    U = {}
    for b in range(4):
        x0r, x0i = x[0][0][b], x[0][1][b]
        x1r, x1i = x[1][0][b], x[1][1][b]
        x2r, x2i = x[2][0][b], x[2][1][b]
        x3r, x3i = x[3][0][b], x[3][1][b]
        U[b, 0] = (x0r + x1r + x2r + x3r, x0i + x1i + x2i + x3i)
        U[b, 1] = (x0r + x1i - x2r - x3i, x0i - x1r - x2i + x3r)
        U[b, 2] = (x0r - x1r + x2r - x3r, x0i - x1i + x2i - x3i)
        U[b, 3] = (x0r - x1i - x2r + x3i, x0i + x1r - x2i - x3r)
    Tm = {}
    for b in range(4):
        for cc in range(4):
            wr, wi = W16[b * cc]
            Tm[b, cc] = _cmul(U[b, cc][0], U[b, cc][1], wr, wi, 16, UW)
    Zr = np.zeros((8, M), dtype=np.int64)
    Zi = np.zeros((8, M), dtype=np.int64)
    for cc in range(4):
        y = [Tm[b, cc] for b in range(4)]
        Zr[cc] = y[0][0] + y[1][0] + y[2][0] + y[3][0]
        Zi[cc] = y[0][1] + y[1][1] + y[2][1] + y[3][1]
        Zr[cc + 4] = y[0][0] + y[1][1] - y[2][0] - y[3][1]
        Zi[cc + 4] = y[0][1] - y[1][0] - y[2][1] + y[3][0]
    qr, qi = Zr >> shift, Zi >> shift
    sat = (qr > QMAX) | (qr < QMIN) | (qi > QMAX) | (qi < QMIN)
    qr, qi = np.clip(qr, QMIN, QMAX), np.clip(qi, QMIN, QMAX)
    pw = (qr * qr + qi * qi).reshape(-1)                       # c = k1 + 2048·k2
    return pw, int(sat.sum()), (Zr, Zi)


def bin_power(pw, B, skew=0):
    """束ね。pw[16384] → 束ねた ch[16384 / B]。skew は陽性対照（区切りをずらす）"""
    if B == 1:
        return pw.copy()
    return np.roll(pw, -skew).reshape(-1, B).sum(axis=1)


def slice_acc(pw_frames, B, s0, nacc):
    """切り出しと積分。pw_frames（細かい ch の電力、フレームの並び）→ 流れの ch i = 束ねた ch s0 + i を nacc フレームずつ積んだダンプの並び"""
    assert 0 <= s0 <= NCH // B - SLICE
    dumps = []
    for k in range(len(pw_frames) // nacc):
        acc = np.zeros(SLICE, dtype=object)
        for f in range(k * nacc, (k + 1) * nacc):
            acc += bin_power(pw_frames[f], B)[s0:s0 + SLICE].astype(object)
        dumps.append(acc)
    return dumps


def ch_center(B, s0, i):
    """流れの ch i の中心周波数（fs の単位）。INTERFACE 2.1: (S0 + i + (B − 1)/(2B))·fs / (N / B)"""
    return (s0 + i + (B - 1) / (2 * B)) * B / N


# ---------------------------------------------------------------- 浮動小数点の参照（B 層）
def float_power(x14, r, shift):
    """フレーム r（≧ 3）の電力を浮動小数点で: PFB（係数は量子化した c / 2^16）→ 32768 点の FFT。整数の pw と同じ目盛り"""
    c = coef().astype(np.float64) / (1 << CF)
    xs = np.asarray(x14, dtype=np.float64)
    y = sum(c[t * N:(t + 1) * N] * xs[(r - 3 + t) * N:(r - 2 + t) * N] for t in range(T))
    X = np.fft.fft(y)[:NCH] * 2.0 ** (-D - shift)
    return np.abs(X) ** 2


# ---------------------------------------------------------------- 判定の道具
class Judge:
    def __init__(self):
        self.ng = 0

    def __call__(self, ok, msg):
        print("  [%s] %s" % ("OK  " if ok else "NG  ", msg))
        if not ok:
            self.ng += 1
        return ok


def amp_compare(pw_int, pw_float, tol_lsb=4.0, rel=2e-3):
    """振幅で比べる（check.py の B と同じ考え）。差 / 許容 の最大を返す。許容 = tol_lsb ＋ rel·振幅"""
    a = np.sqrt(pw_int.astype(np.float64))
    b = np.sqrt(pw_float)
    return float(np.max(np.abs(a - b) / (tol_lsb + rel * b)))


# ---------------------------------------------------------------- selftest（RTL なし）
def selftest():
    J = Judge()
    print("selftest: 模型どうしの突き合わせ（RTL なし）")
    nf, shift = 5, 7                                       # SHIFT 7: 最大 |Z| ≒ 2^23.8 → 2^16.8（18 bit に飽和しない）
    x = stim(nf)
    c = coef()

    # 0. 係数・語幅
    J(c.size == T * N and int(np.abs(c).max()) < (1 << 17), "係数 %d 個・最大 |c| = %d（18 bit に入る）" % (c.size, int(np.abs(c).max())))
    w = coef_words(c)
    p, m = 5, 1234
    taps = [(int(w[p, m]) >> (18 * t)) & 0x3FFFF for t in range(T)]
    taps = [v - (1 << 18) if v >= (1 << 17) else v for v in taps]
    J(taps == [int(c[t * N + P * m + p]) for t in range(T)], "coef_words: レーン 5・番地 1234 の 4 タップが c[t·N + 16m + p]")

    # 1. PFB の整数模型 = wide_model.fixed_chain の PFB（同じ式の別の実装）
    y, ysat = pfb_int(x, c)
    acc = np.zeros((nf, N), dtype=np.int64)
    xf = x.reshape(nf, N)
    for t in range(T):
        sh = T - 1 - t
        acc[sh:] += c.reshape(T, N)[t] * xf[: nf - sh]
    y2 = np.clip(WM.rshift_round(acc, CF), -(1 << 14), (1 << 14) - 1)
    J(np.array_equal(y, y2) and ysat == 0, "PFB: wide_model の式と bit 単位で一致（飽和 %d）" % ysat)
    yh, _ = pfb_int(x[3 * N:], c, hist0=x[:3 * N])
    J(np.array_equal(yh, y[3:]), "PFB: 履歴を与えた起動（hist0）= 続けて流した模型のフレーム 3 以降")

    # 2. 鎖の整数模型 = wide_model.fixed_chain（dft16 を別の書き方で。D = 1・YW 15・YF 0）
    Zr_w, Zi_w = WM.fixed_chain(x, c, N, D=D, YW=YW, YF=0)
    same, zmax = True, 0
    for r in range(nf):
        Yr, Yi = lanes_ip(y[r])
        _, _, (Zr, Zi) = chain_int(Yr, Yi, shift)
        same &= np.array_equal(Zr.reshape(-1), Zr_w[r]) and np.array_equal(Zi.reshape(-1), Zi_w[r])
        zmax = max(zmax, int(np.abs(Zr).max()), int(np.abs(Zi).max()))
    J(same, "鎖: Z が wide_model.fixed_chain と bit 単位で一致（%d フレーム、最大 |Z| = %d < 2^%d）" % (nf, zmax, ZW - 1))

    # 3. B 層: 整数の電力 ≒ 浮動小数点の PFB ＋ 32768 点の FFT（フレーム 3・4 = 履歴が埋まった後）
    worst, nsat = 0.0, 0
    pws = []
    for r in range(nf):
        Yr, Yi = lanes_ip(y[r])
        pw, ns, _ = chain_int(Yr, Yi, shift)
        pws.append(pw)
        nsat += ns
        if r >= 3:
            worst = max(worst, amp_compare(pw, float_power(x, r, shift)))
    J(worst <= 1.0 and nsat == 0, "B: 浮動小数点と振幅で一致（差 / 許容 の最大 %.2f、飽和 %d）" % (worst, nsat))
    Yr, Yi = lanes_ip(y[4])
    pw4, ns4, (Zr4, Zi4) = chain_int(Yr, Yi, 4)
    J(ns4 > 0 and ns4 == int(((Zr4 >> 4 > QMAX) | (Zr4 >> 4 < QMIN) | (Zi4 >> 4 > QMAX) | (Zi4 >> 4 < QMIN)).sum()),
      "飽和: SHIFT 4 で %d 個（強い線の ch）。数えは re・im のどちらかが 18 bit を越えた ch の数" % ns4)
    pk = int(np.argmax(pws[4]))
    J(pk == 16383, "B: いちばん強い ch = %d（期待 16383、最後の ch の線）" % pk)

    # 4. 束ね: 浮動小数点の束ねと一致・区切りの位置
    for B in BS:
        bi = bin_power(pws[4], B)
        bf = bin_power(float_power(x, 4, shift), B)
        J(bi.size == NCH // B and amp_compare(bi, bf) <= 1.0, "束ね B %d: %d ch・浮動小数点と一致（%.2f）" % (B, bi.size, amp_compare(bi, bf)))
    b4 = bin_power(pws[4], 4)
    r = b4[3071] / b4[3072]
    J(0.5 < r < 2.0 and min(b4[3071], b4[3072]) > 100 * np.median(b4),
      "束ね B 4: 12287.5 の線は区切りの両側（束ねた ch 3071 = 12284〜12287 と 3072 = 12288〜12291）に半分ずつ（比 %.2f）" % r)

    # 5. 切り出しと積分（2 本、端と途中）
    for B, s0 in ((4, 0), (2, 0), (2, 8192 - SLICE), (1, 3000), (1, NCH - SLICE)):
        d = slice_acc(pws[3:5], B, s0, 2)[0]
        ref = (bin_power(pws[3], B) + bin_power(pws[4], B))[s0:s0 + SLICE]
        J(np.array_equal(d.astype(np.int64), ref), "切り出し B %d・S0 %d: 4096 ch・2 フレームの積分 = 束ねた ch の部分" % (B, s0))
    J(abs(ch_center(4, 0, 0) - 1.5 / N) < 1e-15 and abs(ch_center(1, 3000, 5) - 3005 / N) < 1e-15,
      "ch → IF: B 4 の ch 0 の中心は細かい ch 1.5、B 1 はずれなし（INTERFACE 2.1）")

    # 6. 陽性対照（落ちるべき）
    print("陽性対照（落ちるべきところで落ちること）:")
    Yr, Yi = lanes_ip(y[4])
    pw_sk, _, _ = chain_int(Yr, Yi, shift, tw_skew=1)
    bad = amp_compare(pw_sk, float_power(x, 4, shift))
    J(bad > 1.0, "ひねり係数の番地を 1 ずらす → B が落ちる（差 / 許容 %.1f）" % bad)
    bad = amp_compare(bin_power(pws[4], 4, skew=1), bin_power(float_power(x, 4, shift), 4))
    J(bad > 1.0, "束ねの区切りを 1 ずらす → 束ねが落ちる（差 / 許容 %.1f）" % bad)
    y_bad = y[4].reshape(M, P).copy()
    y_bad[:, [1, 2]] = y_bad[:, [2, 1]]                      # レーン 1 と 2 の取り違え
    Yr, Yi = lanes_ip(y_bad.reshape(-1))
    pw_b, _, _ = chain_int(Yr, Yi, shift)
    bad = amp_compare(pw_b, float_power(x, 4, shift))
    J(bad > 1.0, "レーン 1 と 2 を取り違える → B が落ちる（差 / 許容 %.1f）" % bad)

    # 7. B 層の盲点（落ちないことを確かめて、A1・C が要る理由として残す）
    print("B 層の盲点（落ちないこと。A1 の bit 単位と C のフレームの頭で見る）:")
    Yr, Yi = lanes_ip(np.roll(y[4], P))
    pw_r, _, _ = chain_int(Yr, Yi, shift)
    blind = amp_compare(pw_r, float_power(x, 4, shift))
    J(blind <= 1.0, "PFB の出口を 1 ビート巡回させても電力は同じ（差 / 許容 %.2f）。フレームの区切りの 1 ビートのずれは振幅では見えない" % blind)
    xs = np.roll(x, -P)                                      # フレームの区切りを 1 ビート後ろに（巡回でない）
    ys, _ = pfb_int(xs, c)
    Yr, Yi = lanes_ip(ys[4])
    pw_s, _, _ = chain_int(Yr, Yi, shift)
    blind = amp_compare(pw_s, float_power(x, 4, shift))
    J(blind <= 1.0, "区切りを 1 ビートずらした入力でも、定常な刺激では振幅がほぼ同じ（差 / 許容 %.2f）" % blind)

    print("結果: 全部通過" if J.ng == 0 else "結果: NG %d 件" % J.ng)
    return J.ng


# ---------------------------------------------------------------- A1（手順 2b）: wide_pfb の出口
def load_pfbout(out):
    """pfbout.txt: 1 行 = 1 ビート「frame m y0 … y15」（tb が書く）。戻り値 {frame: y[N]}（揃ったフレームだけ）"""
    fr = {}
    with open(os.path.join(out, "pfbout.txt")) as f:
        for line in f:
            v = [int(t) for t in line.split()]
            r, m = v[0], v[1]
            y = fr.setdefault(r, np.full(N, np.iinfo(np.int64).min, dtype=np.int64))
            y[P * m:P * m + P] = v[2:2 + P]
    return {r: y for r, y in fr.items() if (y != np.iinfo(np.int64).min).all()}


def check_pfb(out, posctl=False):
    J = Judge()
    x = np.load(os.path.join(out, "stim14.npy"))
    got = load_pfbout(out)
    ymod, ysat = pfb_int(x)
    nf = len(x) // N
    J(len(got) >= 4, "揃ったフレーム %d 個（4 個以上）" % len(got))
    reg = {}
    rp = os.path.join(out, "pfbreg.txt")
    if os.path.exists(rp):
        with open(rp) as f:
            reg = {k: int(v) for k, v in (line.split() for line in f if line.strip())}
        J(reg.get("coef_mis") == 0, "coef_mis = %s（係数の番地が自分の m と食い違わなかった）" % reg.get("coef_mis"))
        J(reg.get("sat_cnt") == ysat, "sat_cnt = %s（模型の飽和 %d）" % (reg.get("sat_cnt"), ysat))
    mis = {r: int(np.sum(got[r] != ymod[r % nf])) for r in sorted(got) if r < nf}
    J(len(mis) > 0 and all(v == 0 for v in mis.values()),
      "A1: PFB の出口が模型と bit 単位で一致（不一致 %s）" % mis)
    if posctl:
        ok = J.ng > 0
        print("結果: 全部通過（陽性対照が落ちるべきところで落ちた）" if ok else "結果: NG（陽性対照が落ちなかった）")
        return 0 if ok else 1
    print("結果: 全部通過" if J.ng == 0 else "結果: NG %d 件" % J.ng)
    return J.ng


# ---------------------------------------------------------------- A2 の後半（手順 2c-1）: wide_chain（ひねり係数〜束ね）
def gen_chain(out, nf=4):
    """lanes_in.txt: PFB の整数模型 → IP の行動模型（lanes_ip）の出口を 1 行 = 1 クロック「k1 re0 im0 … re15 im15」で"""
    os.makedirs(out, exist_ok=True)
    x = stim(nf)
    y, _ = pfb_int(x)
    with open(os.path.join(out, "lanes_in.txt"), "w") as f:
        for r in range(nf):
            Yr, Yi = lanes_ip(y[r])
            for k1 in range(M):
                f.write("%d %s\n" % (k1, " ".join("%d %d" % (Yr[p, k1], Yi[p, k1]) for p in range(P))))
    np.save(os.path.join(out, "stim14.npy"), x)
    print("wrote %s/lanes_in.txt（%d フレーム）" % (out, nf))


def check_chain(out, lb, shift, posctl=False):
    J = Judge()
    B = 1 << lb
    x = np.load(os.path.join(out, "stim14.npy"))
    nf = len(x) // N
    y, _ = pfb_int(x)
    got = {}
    with open(os.path.join(out, "chain_out.txt")) as f:
        for line in f:
            v = [int(t) for t in line.split()]
            got.setdefault(v[0], {})[v[1]] = (v[2], v[3:11])
    reg = {}
    with open(os.path.join(out, "chainreg.txt")) as f:
        reg = {k: int(v) for k, v in (line.split() for line in f if line.strip())}
    J(sorted(got) == list(range(nf)) and all(len(got[r]) == M // B for r in got),
      "束ね B %d: %d フレーム × %d 個の束（1 束 = 8 銀行）" % (B, len(got), M // B))
    J(reg.get("tw_mis") == 0, "tw_mis = %s（ひねり係数の番地が自分の k1 と食い違わなかった）" % reg.get("tw_mis"))
    nbad, nsat_bad, tot_sat = 0, 0, 0
    for r in range(nf):
        Yr, Yi = lanes_ip(y[r])
        pw, _, (Zr, Zi) = chain_int(Yr, Yi, shift)
        qs = ((Zr >> shift) > QMAX) | ((Zr >> shift) < QMIN) | ((Zi >> shift) > QMAX) | ((Zi >> shift) < QMIN)   # [k2, k1]
        pb = bin_power(pw, B)
        for jb, (st, vals) in got.get(r, {}).items():
            for k2 in range(8):
                if vals[k2] != int(pb[jb + (M // B) * k2]):
                    nbad += 1
            es = int(qs[:, jb * B:(jb + 1) * B].sum())
            tot_sat += es
            nsat_bad += (st != es)
    J(nbad == 0, "A2: 束ねた電力が模型と bit 単位で一致（不一致 %d / %d）" % (nbad, nf * NCH // B))
    J(nsat_bad == 0, "飽和の数が束ごとに模型と一致（不一致 %d 束、飽和の総数 %d）" % (nsat_bad, tot_sat))
    if posctl:
        ok = J.ng > 0
        print("結果: 全部通過（陽性対照が落ちるべきところで落ちた）" if ok else "結果: NG（陽性対照が落ちなかった）")
        return 0 if ok else 1
    print("結果: 全部通過" if J.ng == 0 else "結果: NG %d 件" % J.ng)
    return J.ng


# ---------------------------------------------------------------- 手順 2c-2: wide_spec（PFB → IP → 鎖 → 積分 → 帳簿）
def check_spec(out, posctl=False):
    """meta.txt・lanes.txt・dumps.txt を読み、A1'（IP の出口の区切り）・A2・B・C を判定する"""
    J = Judge()
    meta = {}
    with open(os.path.join(out, "meta.txt")) as f:
        for line in f:
            k, v = line.split()
            meta[k] = int(v)
    T0, KF, lb, sh, nacc, ndump, gf = (meta[k] for k in ("T0", "KF", "LB", "SHIFT", "NACC", "NDUMP", "GF"))
    B, ff, fa_run = 1 << lb, meta["f_first"], meta["fa_run"]
    s0 = [meta["c_s0_0"], meta["c_s0_1"]]
    en = [True, lb != 2]
    stim14 = np.load(os.path.join(out, "stim14.npy"))
    L = len(stim14)

    def frame_x(fa):                                     # フレーム fa（T = KF + 2048·fa から）の 32768 サンプル
        n0 = KF + M * fa - T0
        idx = (P * n0 + np.arange(N)) % L
        return stim14[idx]

    # IP の出口（出口の通し番号 r = フレーム ff + r）
    lanes = {}
    with open(os.path.join(out, "lanes.txt")) as f:
        for line in f:
            v = line.split()
            r, k1 = int(v[0]), int(v[1])
            a = lanes.setdefault(r, (np.zeros((P, M), np.int64), np.zeros((P, M), np.int64), np.zeros(M, bool)))
            vals = np.array(v[2:], dtype=np.int64)
            a[0][:, k1] = vals[0::2]
            a[1][:, k1] = vals[1::2]
            a[2][k1] = True
    lanes = {r: a for r, a in lanes.items() if a[2].all()}

    # ダンプ
    dumps = []
    with open(os.path.join(out, "dumps.txt")) as f:
        cur = None
        for line in f:
            t = line.split()
            if t[0] == "dump":
                cur = dict(zip(("s", "seq", "k", "f0", "n", "sat", "plane"), (int(x) for x in t[1:])), v=[])
                dumps.append(cur)
            else:
                cur["v"].append(int(t[1]))

    J(meta["flags"] == 0, "flags = %02x（係数・ひねり係数の見張り・途切れ・IP の事象・k1 の飛び・書き込みの衝突が無い）" % meta["flags"])
    nexp = ndump * (2 if en[1] else 1)
    J(len(dumps) == nexp and all(len(d["v"]) == SLICE for d in dumps), "ダンプ %d 個（期待 %d）× 4096 ch" % (len(dumps), nexp))

    # C: 帳簿
    F0 = ((fa_run >> gf) + 2) << gf
    okc = True
    for d in dumps:
        okc &= d["f0"] == F0 + d["k"] * nacc and d["n"] == nacc and d["seq"] == d["k"] + 1 and d["plane"] == d["k"] % 2
    J(okc, "C: DUMP_F0 = F0 ＋ k·N_ACC（F0 = %d = (⌊fa_run / 2^%d⌋ + 2)·2^%d、格子に乗る）・DUMP_N・SEQ・面" % (F0, gf, gf))
    J(F0 % (1 << gf) == 0 and (KF + M * F0 - KF) % (M << gf) == 0,
      "C: ダンプの区切りの T = K_F ＋ 2048·F0 は T ≡ K_F（mod 2048·2^%d）に乗る" % gf)

    # 模型の PFB（ff から 0 の履歴）
    nfr = max(d["f0"] + d["n"] for d in dumps) - ff + 1 if dumps else 0
    xs = np.concatenate([frame_x(ff + r) for r in range(nfr)])
    ymod, _ = pfb_int(xs)

    # A1': 記録した IP の出口 = 模型の区切りで作った PFB → DFT（丸めの差 ±1 まで）。D-2 の区切り（T ≡ K_F）を IP の手前で確かめる
    worst = 0
    for r in sorted(lanes):
        if r >= nfr:
            continue
        Yr, Yi = lanes_ip(ymod[r])
        worst = max(worst, int(np.abs(lanes[r][0] - Yr).max()), int(np.abs(lanes[r][1] - Yi).max()))
    J(len(lanes) > 0 and worst <= 1, "A1': IP の出口が、T ≡ K_F で区切った模型の PFB → DFT と ±1 で一致（最大の差 %d、%d フレーム）" % (worst, len(lanes)))

    # A2・B・飽和
    bad_a, worst_b, bad_sat, nsatch = 0, 0.0, 0, 0
    for d in dumps:
        s, f0, n = d["s"], d["f0"], d["n"]
        acc = np.zeros(SLICE, dtype=object)
        accf = np.zeros(SLICE)
        smask = np.zeros(SLICE, bool)                    # 飽和した細かい ch を含む束ねた ch（B では比べない。値が浮動小数点と違って当たり前）
        sat = 0
        for f in range(f0, f0 + n):
            r = f - ff
            if r not in lanes:
                bad_a += SLICE
                continue
            pw, ns, (Zr, Zi) = chain_int(lanes[r][0], lanes[r][1], sh)
            sat += ns
            qs = (((Zr >> sh) > QMAX) | ((Zr >> sh) < QMIN) | ((Zi >> sh) > QMAX) | ((Zi >> sh) < QMIN)).reshape(-1)
            smask |= qs.reshape(-1, B).any(axis=1)[s0[s]:s0[s] + SLICE]
            acc += bin_power(pw, B)[s0[s]:s0[s] + SLICE].astype(object)
            accf += bin_power(float_power(xs, r, sh), B)[s0[s]:s0[s] + SLICE]
        got = np.array(d["v"], dtype=object)
        bad_a += int(np.sum(got != acc))
        keep = ~smask
        worst_b = max(worst_b, amp_compare(np.array(d["v"], dtype=np.float64)[keep], accf[keep], tol_lsb=4.0 * n, rel=2e-3))
        nsatch += int(smask.sum())
        bad_sat += (d["sat"] != sat)
    J(bad_a == 0, "A2: ダンプが、記録した IP の出口から作った模型（鎖・束ね・切り出し・積分）と bit 単位で一致（不一致 %d）" % bad_a)
    J(worst_b <= 1.0, "B: ダンプが刺激からの浮動小数点（PFB ＋ 32768 点 ＋ 束ね）と振幅で一致（差 / 許容 の最大 %.2f。飽和を含む ch %d 個は除いた）" % (worst_b, nsatch))
    J(bad_sat == 0, "飽和の数（DUMP_SAT）が模型と一致（不一致 %d ダンプ）" % bad_sat)
    if posctl:
        ok = J.ng > 0
        print("結果: 全部通過（陽性対照が落ちるべきところで落ちた）" if ok else "結果: NG（陽性対照が落ちなかった）")
        return 0 if ok else 1
    print("結果: 全部通過" if J.ng == 0 else "結果: NG %d 件" % J.ng)
    return J.ng


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "selftest"
    if cmd == "selftest":
        sys.exit(1 if selftest() else 0)
    elif cmd == "gen":
        gen(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 8)
    elif cmd == "genchain":
        gen_chain(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 4)
    elif cmd == "chain":
        sys.exit(1 if check_chain(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), len(sys.argv) > 5 and sys.argv[5] == "posctl") else 0)
    elif cmd == "spec":
        sys.exit(1 if check_spec(sys.argv[2], len(sys.argv) > 3 and sys.argv[3] == "posctl") else 0)
    elif cmd == "pfb":
        sys.exit(1 if check_pfb(sys.argv[2], len(sys.argv) > 3 and sys.argv[3] == "posctl") else 0)
    else:
        print(__doc__)
        sys.exit(2)
