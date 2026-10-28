#!/usr/bin/env python3
"""proj032 M-2 — DDR に置く窓の PFB の履歴を 8 bit にしたときの精度（proj028 M-2 の形を、窓の z に）。numpy だけ。

DDR の窓は、z（18 bit・Q4、M-3 の連鎖の出口）を窓ごとの利得で 8 bit に詰めて DDR に書き、読み戻して PFB に入れる:
    h = sat8(round(z_int / 2^s))、PFB には h·2^s
s は PS が窓ごとに決める（z の rms を目標 T [LSB] に寄せる: s = max(0, ⌊log2(σ_z / T)⌋)、8 bit の rms は T 以上 2T 未満。σ_z は実部・虚部それぞれの rms）。
z の手前（粗い PFB・頭・ddcb）は model/win64_fixed.py の chain（M-3 で決めた語長: ddcb 20 bit・Q4・持ち上げ 0,0,1,1,2）。

判定:
  N1  雑音の入力で、8 bit にした z の誤差（M-3 の固定小数点の誤差を含む、浮動小数点の連鎖に対して）/ 信号 ≦ 1e-3（感度の損 0.1 %）
      入力の水準 −47・−30・−20 dBFS、幅 5 つ
  L1  強い線の余裕: 雑音（−30 dBFS）＋ CW。s は雑音だけのときの値（PS は線を知らずに利得を決める）。
      8 bit で飽和しない CW の上限を、ch あたりの雑音に対する線の強さ [dB] で表す。飽和の後に固定小数点が作る線も数える
  陽性対照: T = 2（8 bit の段の丸めが大きい）で N1 が落ちること

  python3 model/m2_hist8.py                   # T = 8, 12, 16, 24, 32 の表
"""
import argparse
import sys

import numpy as np

import win64_model as WM
import win64_fixed as WF

M3 = dict(WF.DEFAULT)
M3["B_W"], M3["B_F"] = 20, 4
M3["B_S"] = {1: 0, 2: 0, 3: 1, 4: 1, 5: 2}


def z_of(kind, level, c, W, co, rng, nout=8192, f0=None, noise_level=None):
    dec = WM.D * 2 ** WM.nstages(W)
    L = (nout + 300) * dec + 512
    x = WF.make_input(kind, level, L, rng, f0).astype(np.float64)
    if noise_level is not None:
        x = x + rng.normal(0, WF.FS_SINE_RMS * 10 ** (noise_level / 20), L)
        x = np.clip(np.round(x), -8192, 8191)
    cnt = {}
    zf, zr = WF.chain(x, c, W, co, M3, cnt)
    n = min(len(zf), len(zr))
    zc = np.round(zf[:n][-nout:] * 2 ** M3["G"])                   # 18 bit の整数（実部・虚部）
    return zc.real.astype(np.int64), zc.imag.astype(np.int64), zr[:n][-nout:] * 2 ** M3["G"], cnt


def gain_shift(zr, zi, T):
    sig = np.sqrt(0.5 * (np.mean(zr.astype(float) ** 2) + np.mean(zi.astype(float) ** 2)))
    return max(0, int(np.floor(np.log2(max(sig, 1e-9) / T))))       # 切り捨て: 8 bit の rms は T 以上・2T 未満


def to8(a, s):
    q = WF.rnd_shift(a, s) if s > 0 else a
    n = int(np.count_nonzero((q < -128) | (q > 127)))
    return np.clip(q, -128, 127) << s, n


def run(T, rng, co, quiet=False):
    fails, rows = [], []
    for W in WM.WIDTHS:
        grid = W / WM.NFFT
        c = round(float(rng.uniform(W / 2, 2048.0 - W / 2)) / grid) * grid
        for lev in (-47, -30, -20):
            zr, zi, ref, _ = z_of("noise", lev, c, W, co, rng)
            s = gain_shift(zr, zi, T)
            hr, n1 = to8(zr, s); hi, n2 = to8(zi, s)
            e18 = np.mean(np.abs(zr + 1j * zi - ref) ** 2) / np.mean(np.abs(ref) ** 2)
            e8 = np.mean(np.abs(hr + 1j * hi - ref) ** 2) / np.mean(np.abs(ref) ** 2)
            rows.append(("N1", W, lev, s, e18, e8, n1 + n2))
            if e8 > 1e-3:
                fails.append(f"N1 W={W} {lev} dBFS: {e8:.2e}（18 bit で {e18:.2e}）")
        # L1: 雑音 −30 dBFS で s を決め、CW の強さを上げていく（線は窓の中の ch の格子の上）
        zr, zi, _, _ = z_of("noise", -30, c, W, co, rng)
        s = gain_shift(zr, zi, T)
        sig2 = 2 * np.mean(zr.astype(float) ** 2)                   # 複素の雑音の電力（z の LSB²）
        nu = round(rng.uniform(-0.3 * W, 0.3 * W) / grid) * grid
        best = None
        for lc in np.arange(-64, 1, 2.0):                           # CW の水準（dBFS、ADC の上での）
            zr2, zi2, _, cnt = z_of("cw", lc, c, W, co, rng, f0=c + nu, noise_level=-30)
            if cnt:                                                   # 8 bit の前の連鎖が飽和する所までは見ない
                break
            hr, n1 = to8(zr2, s); hi, n2 = to8(zi2, s)
            nfr = len(zr2) // WM.NFFT
            Z = np.fft.fft((zr2 + 1j * zi2)[-nfr * WM.NFFT:].reshape(nfr, WM.NFFT), axis=1)
            E = np.fft.fft(((hr - zr2) + 1j * (hi - zi2))[-nfr * WM.NFFT:].reshape(nfr, WM.NFFT), axis=1)
            P = (np.abs(Z) ** 2).mean(0); Pe = (np.abs(E) ** 2).mean(0)
            bt = int(np.argmax(P))
            noise_ch = sig2 * WM.NFFT                                 # ch あたりの雑音（FFT の電力の単位、窓なし）
            line_db = 10 * np.log10(P[bt] / noise_ch)
            Pe[bt] = 0
            spur_db = 10 * np.log10(max(Pe.max(), 1e-30) / noise_ch)  # 8 bit の段が作る線（ch の雑音に対して）
            if n1 + n2 == 0:
                best = (lc, line_db)
            else:
                rows.append(("L1", W, lc, s, line_db, spur_db, n1 + n2))
                break
        rows.append(("L1max", W, best[0] if best else None, s, best[1] if best else None, None, 0))
    if not quiet:
        for r in rows:
            if r[0] == "N1":
                print(f"  N1 W {r[1]:5.0f} {r[2]:4d} dBFS: s {r[3]:2d}・誤差 18 bit {r[4]:.2e} → 8 bit {r[5]:.2e}・飽和 {r[6]}")
            elif r[0] == "L1":
                print(f"  L1 W {r[1]:5.0f}: CW {r[2]:+.0f} dBFS で 8 bit が飽和（線は ch の雑音の +{r[4]:.1f} dB、作られた線は ch の雑音の {r[5]:+.1f} dB）")
            elif r[2] is not None:
                print(f"  L1 W {r[1]:5.0f}: 飽和しない最大 CW {r[2]:+.0f} dBFS・線は ch の雑音の +{r[4]:.1f} dB（s {r[3]}）")
    return fails, rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--T", type=str, default="8,12,16,24,32")
    ap.add_argument("--posctl", action="store_true")
    ap.add_argument("--seed", type=int, default=32002)
    a = ap.parse_args()
    co = WF.load_coef()
    if a.posctl:
        fails, _ = run(2, np.random.default_rng(a.seed), co, quiet=True)
        ok = any(f.startswith("N1") for f in fails)
        print("陽性対照（T 2）: N1 が " + ("落ちた（期待どおり）" if ok else "落ちなかった"))
        sys.exit(0 if ok else 1)
    for T in [int(v) for v in a.T.split(",")]:
        print(f"T = {T} LSB（8 bit の rms の目標）", flush=True)
        fails, rows = run(T, np.random.default_rng(a.seed), co)
        n1 = max(r[5] for r in rows if r[0] == "N1")
        hs = [r[4] for r in rows if r[0] == "L1max" and r[4] is not None]
        hm = min(hs) if len(hs) == len(WM.WIDTHS) else float("nan")      # どこかの幅で最初の水準から飽和したら nan
        print(f"  → N1 の最悪 {n1:.2e}・強い線の余裕（幅の最悪）ch の雑音の +{hm:.1f} dB・判定 {'通過' if not fails else '×'}", flush=True)


if __name__ == "__main__":
    main()
