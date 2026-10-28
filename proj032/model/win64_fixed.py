#!/usr/bin/env python3
"""proj032 M-3 — 窓の頭の後ろ（ddcb: light 2〜4 段目 ＋ final）の語長を詰めたときの精度（proj021 の win_fixed.py の判定を、64 MHz 間隔の連鎖に）。numpy だけ。

目的: ddcb の値の幅（今は 24 bit・小数 8）を詰めると LUT（LUTRAM の履歴・FIFO・和の木）が比例して減る（E-3）。
      詰めたときの感度の損と、強い入力の余裕がどうなるかを、窓の幅ごとに数える。

連鎖（単位は ADC の LSB = 14 bit の 1。Q = 小数の bit 数）:
  x      14 bit 整数
  y      粗い ch（PFB は係数を 18 bit に丸めた値で浮動小数点に計算し、Q = Y_F に丸めて Y_W bit で飽和。PFB の中の丸めはここでは作らない）
  v      窓の頭: NCO（表 P bit・振幅 18 bit、proj021 の nco_cs と同じ）→ Q = V_F・V_W bit。NS ≧ 2 は light 1 段目も頭で（V_F・V_W）
  b      ddcb の入口: v を Q = B_F に丸めて B_W bit で飽和。light × (NS − 2) → final を B_F・B_W で（各段の出口で丸め・飽和）
         **B_S**: NS ごとの左シフト（狭い窓ほど値を持ち上げる。ddcb の入口で 2^B_S[NS] 倍、z を作るときに戻す）
  z      FFT の入力: Q = G・Z_W bit（今の RTL と同じ）
  浮動小数点の側は同じ係数・同じ NCO の周波数（32 bit の Δ）で丸めなし。誤差 = z − 浮動小数点

判定（proj021 と同じ）:
  N1  雑音 −47 dBFS（σ ≒ 26 LSB、熱雑音の入力）: 誤差の電力 / 信号の電力 ≦ 1e-3（感度の損 0.1 %）
  N2  雑音 −10 dBFS: どの段も飽和 0、誤差 ≦ 1e-3
  C1  CW −1 dBFS（窓の中の乱数の位置）: 飽和 0、固定小数点が作る線（CW の ch を除く最大）≦ −70 dBc
  すべての幅（128〜8 MHz）× 窓の置き場所 3 か所

使い方:
  python3 win64_fixed.py                            # 今の語長（B_W 24・B_F 8）で N1・N2・C1
  python3 win64_fixed.py --bw 20 --bf 4             # ddcb を 20 bit・小数 4 に
  python3 win64_fixed.py --sweep                    # (B_W, B_F) の組を並べて表に（M-3 の本体）
  python3 win64_fixed.py --posctl                   # 陽性対照: B_F = 0（ddcb を整数に丸める）で N1 が落ちること
"""
import argparse
import json
import math
import os
import sys

import numpy as np

import win64_model as WM

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = {
    "Y_W": 24, "Y_F": 8,
    "V_W": 24, "V_F": 8,
    "NCO_P": 14, "NCO_A": 18,
    "B_W": 24, "B_F": 8, "B_S": {1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
    "Z_W": 18, "G": 4,
}
FS_SINE_RMS = 8192 / math.sqrt(2)


def load_coef():
    d = json.load(open(os.path.join(HERE, "..", "runs", "m0_coef.json")))
    out = {}
    for key in ("pfb", "light", "final"):
        out[key] = np.array(d[key]["coef"], dtype=np.int64)
        out["sh_" + key] = d[key]["shift"]
    return out


def rnd_shift(a, k):
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


def nco_step(d):
    dphi = int(round(d / WM.R0 * 2 ** 32)) % (1 << 32)
    signed = dphi - (1 << 32) if dphi >= (1 << 31) else dphi
    return dphi, signed / 2 ** 32 * WM.R0


def nco_table(P, A):
    n = np.arange(1 << (P - 2))
    return np.round(A * np.sin(2 * np.pi * (n + 0.5) / (1 << P))).astype(np.int64)


def nco_cs(addr, P, T):
    """head_core と同じ: 1/4 波の表、象限で符号と番地の反転"""
    qa = P - 2
    ra = addr & ((1 << qa) - 1)
    q = addr >> qa
    ta = T[ra]
    tb = T[((1 << qa) - 1) - ra]
    s = np.where(q == 0, ta, np.where(q == 1, tb, np.where(q == 2, -ta, -tb)))
    c = np.where(q == 0, tb, np.where(q == 1, -ta, np.where(q == 2, -tb, ta)))
    return c, s


def coarse(x, k, co):
    """粗い ch k（浮動小数点、係数は 18 bit の整数 / 2^sh）。win64_model.run_chain と同じ式"""
    h = co["pfb"] / 2.0 ** co["sh_pfb"]
    N = len(h)
    n = np.arange(N)
    gk = h * np.exp(2j * np.pi * k * n / WM.M)
    z = WM.fir_decim(x.astype(complex), gk, WM.D)
    p = np.arange(len(z)) * WM.D + (N - 1)
    return z * np.exp(-2j * np.pi * k * (p % WM.M) / WM.M)


def chain(x, c, W, co, cfg, cnt):
    """戻り値: (固定小数点の z（ADC の LSB 単位の複素）, 浮動小数点の同じ連鎖)"""
    k, _ = WM.window_params(c, W)
    dphi, d = nco_step(c - k * WM.S)
    ns = WM.nstages(W)
    y = coarse(x, k, co)
    m = np.arange(len(y))
    hl, hf = co["light"], co["final"]
    shl, shf = co["sh_light"], co["sh_final"]
    # ---- 浮動小数点 ----
    vf = y * np.exp(-2j * np.pi * d * m / WM.R0)
    for j in range(ns):
        h = (hf / 2.0 ** shf) if j == ns - 1 else (hl / 2.0 ** shl)
        vf = WM.fir_decim(vf, h, 2)
    # ---- 固定小数点 ----
    yr = sat(np.round(y.real * 2 ** cfg["Y_F"]).astype(np.int64), cfg["Y_W"], cnt, "y")
    yi = sat(np.round(y.imag * 2 ** cfg["Y_F"]).astype(np.int64), cfg["Y_W"], cnt, "y")
    P, A = cfg["NCO_P"], (1 << (cfg["NCO_A"] - 1)) - 1
    th = (m.astype(np.uint64) * np.uint64(dphi)) & np.uint64(0xFFFFFFFF)
    addr = (th >> np.uint64(32 - P)).astype(np.int64)
    cq, sq = nco_cs(addr, P, nco_table(P, A))
    sh = (cfg["NCO_A"] - 1) + cfg["Y_F"] - cfg["V_F"]
    vr = sat(rnd_shift(yr * cq + yi * sq, sh), cfg["V_W"], cnt, "v")
    vi = sat(rnd_shift(yi * cq - yr * sq, sh), cfg["V_W"], cnt, "v")

    def hb(ar, ai, h, s, w, key):
        ne = 2 * (len(ar) // 2)
        ar, ai = ar[:ne], ai[:ne]
        return (sat(rnd_shift(fir_decim_int(ar, h, 2), s), w, cnt, key),
                sat(rnd_shift(fir_decim_int(ai, h, 2), s), w, cnt, key))

    if ns >= 2:                                           # light 1 段目は窓の頭（V_W・V_F）
        vr, vi = hb(vr, vi, hl, shl, cfg["V_W"], "head_l1")
    # ddcb の入口: Q = V_F → B_F + B_S[ns]
    bs = cfg["B_S"][ns]
    bf = cfg["B_F"] + bs
    br = sat(rnd_shift(vr, cfg["V_F"] - bf), cfg["B_W"], cnt, "b_in")
    bi = sat(rnd_shift(vi, cfg["V_F"] - bf), cfg["B_W"], cnt, "b_in")
    for j in range(1, ns):                                # light 2.. と final（ns = 1 は final だけ）
        last = (j == ns - 1)
        br, bi = hb(br, bi, hf if last else hl, shf if last else shl, cfg["B_W"], "final" if last else f"l{j + 1}")
    if ns == 1:
        br, bi = hb(br, bi, hf, shf, cfg["B_W"], "final")
    zr = sat(rnd_shift(br, bf - cfg["G"]), cfg["Z_W"], cnt, "z")
    zi = sat(rnd_shift(bi, bf - cfg["G"]), cfg["Z_W"], cnt, "z")
    return (zr + 1j * zi) / 2.0 ** cfg["G"], vf


def make_input(kind, level_dbfs, L, rng, f0=None):
    if kind == "noise":
        x = rng.normal(0, FS_SINE_RMS * 10 ** (level_dbfs / 20), L)
    else:
        a = 8192 * 10 ** (level_dbfs / 20)
        x = a * np.cos(2 * np.pi * f0 / WM.FS * np.arange(L) + rng.uniform(0, 2 * np.pi))
    return np.clip(np.round(x), -8192, 8191)


def trial(kind, level, c, W, co, cfg, rng, nout=8192, f0=None):
    dec = WM.D * 2 ** WM.nstages(W)
    L = (nout + 300) * dec + 512
    x = make_input(kind, level, L, rng, f0)
    cnt = {}
    zf, zr = chain(x, c, W, co, cfg, cnt)
    n = min(len(zf), len(zr))
    zf, zr = zf[:n][-nout:], zr[:n][-nout:]
    e = zf - zr
    rel = np.mean(np.abs(e) ** 2) / np.mean(np.abs(zr) ** 2)
    spur = None
    if kind == "cw":
        nfr = nout // WM.NFFT
        E = (np.abs(np.fft.fft(e[-nfr * WM.NFFT:].reshape(nfr, WM.NFFT), axis=1)) ** 2).mean(0)
        Y = (np.abs(np.fft.fft(zr[-nfr * WM.NFFT:].reshape(nfr, WM.NFFT), axis=1)) ** 2).mean(0)
        bt = int(np.argmax(Y))
        Eo = E.copy(); Eo[bt] = 0.0
        spur = 10 * np.log10(Eo.max() / Y[bt])
    return rel, cnt, spur


def run_checks(co, cfg, rng, quiet=False):
    fails, rows = [], []
    for W in WM.WIDTHS:
        grid = W / WM.NFFT
        lo, hi = W / 2, 2048.0 - W / 2
        cs = [WM.S * 9 + WM.S / 2, round(float(rng.uniform(lo, hi)) / grid) * grid, float(rng.uniform(lo, hi))]
        for c in cs:
            r1, n1, _ = trial("noise", -47, c, W, co, cfg, rng)
            r2, n2, _ = trial("noise", -10, c, W, co, cfg, rng)
            nu = round(rng.uniform(-WM.USE * W, WM.USE * W) / grid) * grid
            r3, n3, sp = trial("cw", -1, c, W, co, cfg, rng, f0=c + nu)
            rows.append((W, c, r1, r2, n2, n3, sp))
            if r1 > 1e-3 or n1:
                fails.append(f"N1 W={W} c={c:.3f} {r1:.2e} 飽和 {n1}")
            if n2 or r2 > 1e-3:
                fails.append(f"N2 W={W} c={c:.3f} {r2:.2e} 飽和 {n2}")
            if n3 or sp > -70:
                fails.append(f"C1 W={W} c={c:.3f} {sp:.1f} dBc 飽和 {n3}")
    if not quiet:
        print(f"{'W':>5} | {'c':>9} | N1 誤差 −47 dBFS | N2 誤差 −10 dBFS | N2 飽和 | C1 飽和 | C1 線")
        for W, c, r1, r2, n2, n3, sp in rows:
            print(f"{W:5.0f} | {c:9.4f} | {r1:14.2e} | {r2:14.2e} | {sum(n2.values()):7d} | {sum(n3.values()):7d} | {sp:6.1f} dBc")
    return fails, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bw", type=int, default=DEFAULT["B_W"])
    ap.add_argument("--bf", type=int, default=DEFAULT["B_F"])
    ap.add_argument("--bs", type=str, default="0,0,0,0,0", help="NS 1..5 の持ち上げ（bit）")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--posctl", action="store_true")
    ap.add_argument("--seed", type=int, default=32003)
    a = ap.parse_args()
    co = load_coef()

    def cfg_of(bw, bf, bs):
        c = dict(DEFAULT); c["B_W"], c["B_F"] = bw, bf
        c["B_S"] = {i + 1: v for i, v in enumerate(bs)}
        return c

    if a.sweep:
        combos = [(24, 8, (0,) * 5), (22, 6, (0,) * 5), (21, 5, (0,) * 5), (20, 4, (0,) * 5), (20, 5, (0,) * 5),
                  (19, 4, (0,) * 5), (18, 3, (0,) * 5), (20, 4, (0, 0, 1, 1, 2)), (18, 3, (0, 0, 1, 1, 2)), (18, 2, (0, 1, 1, 2, 2))]
        print("B_W | B_F | 持ち上げ NS1..5 | N1 の最悪（幅ごと 128・64・32・16・8）               | N2 飽和 | C1 飽和 | C1 線の最悪 | 判定")
        for bw, bf, bs in combos:
            fails, rows = run_checks(co, cfg_of(bw, bf, bs), np.random.default_rng(a.seed), quiet=True)
            n1 = [max(r[2] for r in rows if r[0] == W) for W in WM.WIDTHS]
            s2 = sum(sum(r[4].values()) for r in rows)
            s3 = sum(sum(r[5].values()) for r in rows)
            sp = max(r[6] for r in rows)
            print(f"{bw:3d} | {bf:3d} | {','.join(map(str, bs)):>15} | " + " ".join(f"{v:.1e}" for v in n1)
                  + f" | {s2:7d} | {s3:7d} | {sp:8.1f} dBc | {'通過' if not fails else '×'}", flush=True)
        return
    if a.posctl:
        cfg = cfg_of(24, 0, (0,) * 5)
        fails, _ = run_checks(co, cfg, np.random.default_rng(a.seed))
        ok = any(f.startswith("N1") for f in fails)
        print("陽性対照（B_F 0）: N1 が " + ("落ちた（期待どおり）" if ok else "落ちなかった（判定が効いていない）"))
        print("結果: " + ("全部通過" if ok else "不合格"))
        sys.exit(0 if ok else 1)
    cfg = cfg_of(a.bw, a.bf, [int(v) for v in a.bs.split(",")])
    fails, _ = run_checks(co, cfg, np.random.default_rng(a.seed))
    for f in fails:
        print("NG:", f)
    print("結果: " + ("全部通過" if not fails else "不合格"))
    sys.exit(0 if not fails else 1)


if __name__ == "__main__":
    main()
