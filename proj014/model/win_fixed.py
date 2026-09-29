#!/usr/bin/env python3
"""proj014 — 狭帯域の窓（bit ③）の固定小数点の模型。語長・丸め・NCO の bit を決めるための道具。numpy だけ。

win_model.py（仕様の模型）が正。ここでは同じ連鎖を「段の境目で丸める形」で回し、同じ入力の浮動小数点と比べる。
RTL の bit 単位の照合は、後でこのファイルの式（段の境目の丸め）に RTL の内部（32 点 FFT の中など）を足したものに対して行う。

段と語の形式（Q = 小数部の bit 数。単位は ADC の LSB = 14 bit の 1）:

  x      14 bit 整数（ADC の有効 14 bit、proj010 以来の >>> 2）
  u_r    PFB の分岐の和  u_r[m] = Σ_t h[r + 32t] · x[p − r − 32t]、p = 8m + N − 1         U_W bit、Q = U_F
  y      粗い ch         y[m] = (−j)^(k·m) · Σ_r u_r[m] · exp(+j2πkr/32)                 Y_W bit、Q = Y_F（複素）
         （仕様の式 exp(−j2πkp/M) のうち定数 exp(−j2πk(N−1)/M) を落とした形。電力には効かない。
          残る (−j)^(km) は符号と実虚の入れ替えだけ。32 点の実 DFT は RTL の形そのまま（下の rfft32_ch）:
          16 点 複素 DFT（proj013 の dft16 と同じ分解・同じ cmul の丸め）＋ 選んだ ch だけ実数化の後処理）
  NCO    位相 32 bit、θ[m] = m·Δ mod 2³²、Δ = round(d / 512 · 2³²)。表の番地 = θ の上位 P bit、
         値 = round(A · cos / sin)、A = 2^(NCO_A − 1) − 1
  v      y · (cos − j sin)                                                                 V_W bit、Q = V_F
  半帯域 各段の出力                                                                         V_W bit、Q = V_F
  z      FFT の入力      z = v · 2^(G − V_F) を丸め                                          Z_W bit、Q = G
既定の語長の根拠（2026-09-29、--sweep で振った結果）:
  G = 4      N1 の誤差は 1/W で増え、W = 8 で G 3: 2.1e-3（NG）/ 4: 5.3e-4 / 5: 1.4e-4 / 6: 4.1e-5。G 6 は −1 dBFS の CW が
             FFT の入力で飽和する（18 bit）。G 4 は CW に 7 dB の余裕を残して N1 を 2 倍の余裕で通す。G はレジスタで変えられる形にする
  NCO_P = 14 格子に乗らない中心で、位相の切り捨ての線が P 12: −62.3 / 13: −68.3 / 14: −74.3 / 15: −80.3 / 16: −86.3 dBc（≒ −6.0·P + 10）。
             ch の格子の上でも W ≦ 64 では切り捨てが起きる（Δ の下位 bit が残る）。表は 1/4 波で 4096 語 × 18 bit
  U・Y・V    24 bit（DSP48E2 の A ポート 27 bit に前置加算ごと入る）。整数部は最悪の利得（Σ|h|: PFB 1.65・light 1.32・final 1.80）から
丸め: 床(x + 1/2)（1 << (k − 1) を足して k bit 右へ）。飽和: その段の bit 数の符号付きの範囲で止め、回数を数える

判定（既定の語長で）:
  N1  雑音 −47 dBFS（proj013 の熱雑音の入力、σ ≒ 26 LSB）: FFT の入力での誤差の電力 / 信号の電力 ≦ 1e-3（感度の損 0.1 %）
  N2  雑音 −10 dBFS（強い入力）: どの段も飽和 0、誤差 ≦ 1e-3
  C1  CW −1 dBFS（窓の中、乱数の位置・ch の格子の外の細かい NCO も含む）: 飽和 0、
      固定小数点が作る線（誤差のスペクトルの最大）≦ −70 dBc（ADC 自身のイメージ −53〜−66 dBc より 4 dB 以上下）
  すべての幅（256〜8 MHz）× 窓の置き場所 2 か所（粗い ch の境目・乱数）

使い方:
  python3 win_fixed.py                   # 既定の語長で N1・N2・C1。最後に「結果: 全部通過」
  python3 win_fixed.py --sweep G 2 3 4 5 6       # 1 つの語長を振って誤差と飽和を見る（情報）
  python3 win_fixed.py --sweep NCO_P 10 11 12 13 14
  python3 win_fixed.py --posctl          # 陽性対照: G = 0（FFT の入力を整数に丸める）で N1 が落ちること
"""
import argparse
import math
import sys

import numpy as np

import win_model as WM

DEFAULT = {
    "U_W": 22, "U_F": 10,
    "Y_W": 24, "Y_F": 8,
    "V_W": 24, "V_F": 8,
    "NCO_P": 14, "NCO_A": 18,
    "Z_W": 18, "G": 4,
}
FS_SINE_RMS = 8192 / math.sqrt(2)     # 0 dBFS = 14 bit の満杯の正弦波の電力


def rnd_shift(a, k):
    """整数の配列を k bit 右へ（床(x/2^k + 1/2)）。k ≦ 0 なら左へ。"""
    if k <= 0:
        return a << (-k)
    return (a + (1 << (k - 1))) >> k


def sat(a, w, cnt, key):
    lo, hi = -(1 << (w - 1)), (1 << (w - 1)) - 1
    n = int(np.count_nonzero((a < lo) | (a > hi)))
    if n:
        cnt[key] = cnt.get(key, 0) + n
    return np.clip(a, lo, hi)


def fir_decim_int(x, h, step):
    """win_model.fir_decim と同じ添字で、整数のまま（int64）。"""
    N = len(h)
    nout = (len(x) - N) // step + 1
    out = np.empty(nout, dtype=np.int64)
    hr = h[::-1].astype(np.int64)
    blk = 1 << 15
    for i in range(0, nout, blk):
        j = min(nout, i + blk)
        idx = (np.arange(i, j) * step)[:, None] + np.arange(N)[None, :]
        out[i:j] = x[idx] @ hr
    return out


def pfb_branches(x, h):
    """u_r[m] = Σ_t h[r + 32t] · x[p − r − 32t]、p = 8m + N − 1。戻り値 (nframes, 32)。x・h が整数なら整数で。"""
    N = len(h)
    T = N // WM.M
    nout = (len(x) - N) // WM.D + 1
    p = np.arange(nout) * WM.D + (N - 1)
    dt = np.int64 if np.issubdtype(np.asarray(h).dtype, np.integer) else float
    u = np.zeros((nout, WM.M), dtype=dt)
    for t in range(T):
        for r in range(WM.M):
            u[:, r] += h[r + WM.M * t] * x[p - r - WM.M * t]
    return u, p


ROT = np.array([1, -1j, -1, 1j])     # (−j)^n


def nco_step(d):
    """NCO の 1 サンプルあたりの位相の増分（32 bit）と、それが表す周波数（MHz、符号付き）。"""
    dphi = int(round(d / WM.R0 * 2 ** 32)) % (1 << 32)
    signed = dphi - (1 << 32) if dphi >= (1 << 31) else dphi
    return dphi, signed / 2 ** 32 * WM.R0


# ---- PFB の 32 点 実 DFT（RTL の形そのもの）--------------------------------------------------
# z[n] = u[2n] + j·u[2n+1]（n = 0..15）→ 16 点 複素 DFT（proj013 の dft16 と同じ 4 × 4 の分解・同じ cmul の丸め、
# ただし出力 16 本とも）→ 選んだ ch k だけ実数化の後処理:
#   A = Z[k] + conj(Z[16−k])、B = Z[k] − conj(Z[16−k])、X_f[k] · 2 = A + (−j·W32^k) · B（cmul 1 個）
# 仕様の exp(+j2πkr/32) は順変換の複素共役なので、最後に虚部の符号を返す。
# 語幅（整数部の上限は Σ|h|·8192 = 1.65·8192 から）: u 22 bit → U 24 → Z 26 → A・B 27（cmul の入口 = DSP の A ポート 27 bit）

def cmul_int(ar, ai, wr, wi):
    """proj013 の cmul.v: y = floor((a·w + 2^15) / 2^16)、w は 18 bit・2^16 = 1.0。"""
    return (ar * wr - ai * wi + (1 << 15)) >> 16, (ar * wi + ai * wr + (1 << 15)) >> 16


def wq(e, n):
    """exp(−j2π e / n) を 18 bit（2^16 = 1.0）に丸めた値。"""
    return int(round(65536 * math.cos(2 * math.pi * e / n))), int(round(-65536 * math.sin(2 * math.pi * e / n)))


def dft16_int(zr, zi):
    """(nframes, 16) の整数 → 16 点 DFT（順変換、W16 = exp(−2πi/16)）。段 1: 4 点（加減算）/ 段 2: cmul W16^(b·c) / 段 3: 4 点。"""
    ur = np.zeros(zr.shape[:1] + (4, 4), dtype=np.int64)
    ui = np.zeros_like(ur)
    for b in range(4):
        x = [(zr[:, 4 * a + b], zi[:, 4 * a + b]) for a in range(4)]
        # X_c = Σ_a W4^(a·c) x_a、W4 = −j
        ur[:, b, 0] = x[0][0] + x[1][0] + x[2][0] + x[3][0]; ui[:, b, 0] = x[0][1] + x[1][1] + x[2][1] + x[3][1]
        ur[:, b, 1] = x[0][0] + x[1][1] - x[2][0] - x[3][1]; ui[:, b, 1] = x[0][1] - x[1][0] - x[2][1] + x[3][0]
        ur[:, b, 2] = x[0][0] - x[1][0] + x[2][0] - x[3][0]; ui[:, b, 2] = x[0][1] - x[1][1] + x[2][1] - x[3][1]
        ur[:, b, 3] = x[0][0] - x[1][1] - x[2][0] + x[3][1]; ui[:, b, 3] = x[0][1] + x[1][0] - x[2][1] - x[3][0]
    tr = np.empty_like(ur); ti = np.empty_like(ui)
    for b in range(4):
        for c in range(4):
            wr, wi = wq(b * c, 16)
            tr[:, b, c], ti[:, b, c] = cmul_int(ur[:, b, c], ui[:, b, c], wr, wi)
    Zr = np.empty(zr.shape, dtype=np.int64); Zi = np.empty_like(Zr)
    for c in range(4):
        y = [(tr[:, b, c], ti[:, b, c]) for b in range(4)]
        Zr[:, c + 0] = y[0][0] + y[1][0] + y[2][0] + y[3][0]; Zi[:, c + 0] = y[0][1] + y[1][1] + y[2][1] + y[3][1]
        Zr[:, c + 4] = y[0][0] + y[1][1] - y[2][0] - y[3][1]; Zi[:, c + 4] = y[0][1] - y[1][0] - y[2][1] + y[3][0]
        Zr[:, c + 8] = y[0][0] - y[1][0] + y[2][0] - y[3][0]; Zi[:, c + 8] = y[0][1] - y[1][1] + y[2][1] - y[3][1]
        Zr[:, c + 12] = y[0][0] - y[1][1] - y[2][0] + y[3][1]; Zi[:, c + 12] = y[0][1] + y[1][0] - y[2][1] - y[3][0]
    return Zr, Zi


def rfft32_ch(u, k, cnt):
    """u: (nframes, 32) 整数 → 2·Σ_r u_r exp(+j2πkr/32)（整数）。"""
    Zr, Zi = dft16_int(u[:, 0::2], u[:, 1::2])
    Zr = sat(Zr, 26, cnt, "z16"); Zi = sat(Zi, 26, cnt, "z16")
    k1, k2 = k % 16, (16 - k) % 16
    ar, ai = Zr[:, k1] + Zr[:, k2], Zi[:, k1] - Zi[:, k2]         # Z[k] + conj(Z[16−k])
    br, bi = Zr[:, k1] - Zr[:, k2], Zi[:, k1] + Zi[:, k2]         # Z[k] − conj(Z[16−k])
    wr, wi = wq(k, 32)
    wr, wi = wi, -wr                                              # −j·W32^k
    br, bi = sat(br, 27, cnt, "b27"), sat(bi, 27, cnt, "b27")
    cr, ci = cmul_int(br, bi, wr, wi)
    return ar + cr, -(ai + ci)                                    # 共役 → exp(+j…)


def rot_mj(r, i, n):
    """(r + j i)·(−j)^n、n は配列（0..3）。"""
    out_r = np.where(n == 0, r, np.where(n == 1, i, np.where(n == 2, -r, -i)))
    out_i = np.where(n == 0, i, np.where(n == 1, -r, np.where(n == 2, -i, r)))
    return out_r, out_i


def run(x, c, W, des, cfg, fixed, cnt=None):
    """連鎖を回して FFT の入力（複素、ADC の LSB を単位にした値）を返す。fixed=True なら段の境目で丸める。
    NCO の周波数は両方とも 32 bit に丸めた値（浮動小数点の側も同じ周波数で回し、位相の丸めだけを比べる）。"""
    k, _ = WM.window_params(c)
    dphi, d = nco_step(c - k * WM.S)
    M = WM.M
    tw = np.exp(2j * np.pi * k * np.arange(M) / M)
    m_idx = None
    if fixed:
        hq_p = np.round(des["pfb"]["h"] * 2.0 ** des["sh_pfb"]).astype(np.int64)
        u, p = pfb_branches(x.astype(np.int64), hq_p)
        u = sat(rnd_shift(u, des["sh_pfb"] - cfg["U_F"]), cfg["U_W"], cnt, "u")
        xr, xi = rfft32_ch(u, k, cnt)                             # 2·Σ_r u_r exp(+j2πkr/32)（整数、Q = U_F）
        m_idx = np.arange(len(xr))
        xr, xi = rot_mj(xr, xi, (k * m_idx) % 4)                  # (−j)^(k·m)
        yr = sat(rnd_shift(xr, cfg["U_F"] + 1 - cfg["Y_F"]), cfg["Y_W"], cnt, "y")
        yi = sat(rnd_shift(xi, cfg["U_F"] + 1 - cfg["Y_F"]), cfg["Y_W"], cnt, "y")
        # NCO
        P, A = cfg["NCO_P"], (1 << (cfg["NCO_A"] - 1)) - 1
        theta = (m_idx.astype(np.uint64) * np.uint64(dphi)) & np.uint64(0xFFFFFFFF)
        addr = (theta >> np.uint64(32 - P)).astype(np.int64)
        ang = 2 * np.pi * addr / 2 ** P
        cq = np.round(A * np.cos(ang)).astype(np.int64)
        sq = np.round(A * np.sin(ang)).astype(np.int64)
        sh = (cfg["NCO_A"] - 1) + cfg["Y_F"] - cfg["V_F"]
        vr = sat(rnd_shift(yr * cq + yi * sq, sh), cfg["V_W"], cnt, "v")   # (yr + j yi)(c − j s)
        vi = sat(rnd_shift(yi * cq - yr * sq, sh), cfg["V_W"], cnt, "v")
        ns = WM.nstages(W)
        for j in range(ns):
            key = "final" if j == ns - 1 else "light"
            hq = np.round(des[key]["h"] * 2.0 ** des["sh_" + key]).astype(np.int64)
            vr = sat(rnd_shift(fir_decim_int(vr, hq, 2), des["sh_" + key]), cfg["V_W"], cnt, f"hb{j}")
            vi = sat(rnd_shift(fir_decim_int(vi, hq, 2), des["sh_" + key]), cfg["V_W"], cnt, f"hb{j}")
        zr = sat(rnd_shift(vr, cfg["V_F"] - cfg["G"]), cfg["Z_W"], cnt, "z")
        zi = sat(rnd_shift(vi, cfg["V_F"] - cfg["G"]), cfg["Z_W"], cnt, "z")
        return (zr + 1j * zi) / 2.0 ** cfg["G"]
    # 浮動小数点（同じ式・同じ添字、丸めなし、NCO は厳密な exp）
    u, p = pfb_branches(x.astype(float), des["pfb"]["h"])
    yc = u @ tw
    m_idx = np.arange(len(yc))
    yc = yc * ROT[(k * m_idx) % 4]
    v = yc * np.exp(-2j * np.pi * d * m_idx / WM.R0)
    ns = WM.nstages(W)
    for j in range(ns):
        v = WM.fir_decim(v, des["final" if j == ns - 1 else "light"]["h"], 2)
    return v


def prepare(des):
    for key in ("pfb", "light", "final"):
        _, _, sh = WM.quantize(des[key]["h"])
        des["sh_" + key] = sh
    return des


def make_input(kind, level_dbfs, L, rng, f0=None):
    if kind == "noise":
        sigma = FS_SINE_RMS * 10 ** (level_dbfs / 20)
        x = rng.normal(0, sigma, L)
    else:
        a = 8192 * 10 ** (level_dbfs / 20)
        x = a * np.cos(2 * np.pi * f0 / WM.FS * np.arange(L) + rng.uniform(0, 2 * np.pi))
    return np.clip(np.round(x), -8192, 8191)


def trial(kind, level, c, W, des, cfg, rng, nout=8192, f0=None):
    dec = WM.D * 2 ** WM.nstages(W)
    L = (nout + 200) * dec + 256
    x = make_input(kind, level, L, rng, f0)
    cnt = {}
    zf = run(x, c, W, des, cfg, True, cnt)
    zr = run(x, c, W, des, cfg, False)
    zf, zr = zf[-nout:], zr[-nout:]                     # 頭の過渡を捨てる（同じ添字なので揃っている）
    e = zf - zr
    rel = np.mean(np.abs(e) ** 2) / np.mean(np.abs(zr) ** 2)
    spur = None
    if kind == "cw":
        nfr = nout // WM.NFFT
        E = (np.abs(np.fft.fft(e[-nfr * WM.NFFT:].reshape(nfr, WM.NFFT), axis=1)) ** 2).mean(0)
        Y = (np.abs(np.fft.fft(zr[-nfr * WM.NFFT:].reshape(nfr, WM.NFFT), axis=1)) ** 2).mean(0)
        spur = 10 * np.log10(E.max() / Y.max())
    return rel, cnt, spur


def run_checks(des, cfg, rng, quiet=False):
    fails = []
    rows = []
    for W in WM.WIDTHS:
        grid = W / WM.NFFT
        lo, hi = W / 2, 2048.0 - W / 2
        # 粗い ch の境目 / ch の格子の上の乱数（PS の既定）/ 格子に乗らない乱数（NCO の位相の下位 bit まで使う）
        cs = [WM.S * 5 + WM.S / 2, round(float(rng.uniform(lo, hi)) / grid) * grid, float(rng.uniform(lo, hi))]
        for c in cs:
            r1, n1, _ = trial("noise", -47, c, W, des, cfg, rng)
            r2, n2, _ = trial("noise", -10, c, W, des, cfg, rng)
            nu = round(rng.uniform(-WM.USE * W, WM.USE * W) / grid) * grid
            r3, n3, sp = trial("cw", -1, c, W, des, cfg, rng, f0=c + nu)
            rows.append((W, c, r1, r2, sum(n2.values()), sum(n3.values()), sp, n1, n2, n3))
            if r1 > 1e-3:
                fails.append(f"N1 W={W} c={c:.3f} {r1:.2e}")
            if n2 or r2 > 1e-3:
                fails.append(f"N2 W={W} c={c:.3f} {r2:.2e} 飽和 {n2}")
            if n3 or sp > -70:
                fails.append(f"C1 W={W} c={c:.3f} {sp:.1f} dBc 飽和 {n3}")
    if not quiet:
        print(f"{'W':>5} | {'窓の中心 c':>10} | N1 誤差 −47 dBFS | N2 誤差 −10 dBFS | N2 飽和 | C1 飽和 | C1 固定小数点の線")
        for W, c, r1, r2, s2, s3, sp, *_ in rows:
            print(f"{W:5.0f} | {c:10.4f} | {r1:14.2e} | {r2:14.2e} | {s2:7d} | {s3:7d} | {sp:8.1f} dBc")
    return fails, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", nargs="+", default=None, help="語長の名前と値の並び（例: G 2 3 4 5）")
    ap.add_argument("--posctl", action="store_true")
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--a", type=float, default=60.0)
    args = ap.parse_args()

    des = prepare(WM.design(args.a, WM.RIPPLE_PP))
    cfg = dict(DEFAULT)
    print("語長:", " ".join(f"{k}={v}" for k, v in cfg.items()))

    if args.sweep:
        name, vals = args.sweep[0], [int(v) for v in args.sweep[1:]]
        print(f"{name} を振る（情報。各行は 6 通りの幅 × 2 か所の最悪）")
        print(f"{name:>6} | N1 誤差（最悪） | N2 誤差（最悪） | 飽和（N2 + C1） | C1 の線（最悪）")
        for v in vals:
            c2 = dict(cfg, **{name: v})
            _, rows = run_checks(des, c2, np.random.default_rng(args.seed), quiet=True)
            print(f"{v:6d} | {max(r[2] for r in rows):14.2e} | {max(r[3] for r in rows):14.2e} | "
                  f"{sum(r[4] + r[5] for r in rows):14d} | {max(r[6] for r in rows):8.1f} dBc")
        return 0

    if args.posctl:
        cfg["G"] = 0
        print("陽性対照: G = 0（FFT の入力を整数に丸める）→ N1 が落ちるはず")
    fails, _ = run_checks(des, cfg, np.random.default_rng(args.seed))
    if args.posctl:
        if any(f.startswith("N1") for f in fails):
            print(f"陽性対照: N1 が落ちた（{sum(f.startswith('N1') for f in fails)} 件）→ 結果: 全部通過")
            return 0
        print("陽性対照: N1 が落ちなかった → 結果: 失敗（判定が効いていない）")
        return 1
    if fails:
        print("結果: 失敗", fails)
        return 1
    print("結果: 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
