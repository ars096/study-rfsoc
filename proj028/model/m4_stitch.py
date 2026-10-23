#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 M-4 — つなぎの模型。ADC → 荒い段（浮動小数点、bit 単位の一致は C-1・C-2 で確かめた）→ 8 bit
→ 細かい PFB（T 4、proj024 の原型）・FFT（N_f）→ 電力 → bin の巡回 sh_k・7/8 の切り出し → 32 ch をつなぐ。numpy だけ。

  T_k[b] = P_k[(b + sh_k) mod N_f]、sh_k = ((k + ½)·7/8 mod 1)·N_f
  残す b ∈ [−7N_f/16, 7N_f/16)、G = k·7N_f/8 ＋ b ＋ 7N_f/16、f = G·fs / (56·N_f)
判定（README の M-4）: (a) CW のピークの位置 (b) 継ぎ目の雑音の床。陽性対照: sh を 1 ずらす・sh を掛けない
使い方: python3 model/m4_stitch.py [--nf 512] [--frames 300]
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from m3_coarse_fixed import coeffs, fft32_y  # noqa: E402

FS = 4096e6
M, D, TC = 64, 56, 27
L = M * TC
S = 12.0
T, BETA, BW = 4, 5.0, 1.198


def design(N, taps=T):
    """proj024 model/g2_model.py の design() と同じ原型（Σh² = N）"""
    Lf = taps * N
    n = np.arange(Lf, dtype=np.float64)
    n0 = (Lf - 1) / 2
    h = np.sinc(BW * (n - n0) / N) * np.kaiser(Lf, BETA)
    half = h[: Lf // 2]
    h = np.concatenate([half, half[::-1]])
    return h * np.sqrt(N / np.sum(h * h))


def coarse_float(x, nblk):
    """荒い PFB（浮動小数点、係数は 18 bit の hq と同じ形）→ z (nblk, 64)"""
    _, hq, _ = coeffs()
    g = hq.astype(np.float64) * ((-1.0) ** (np.arange(L) // M))
    xp = np.concatenate([np.zeros(L), x.astype(np.float64)])
    z = np.empty((nblk, M))
    CH = 20000
    for b0 in range(0, nblk, CH):
        b1 = min(nblk, b0 + CH)
        t0 = 56 * np.arange(b0, b1) + 55 + L                 # xp の番号
        idx = t0[:, None] - np.arange(L)[None, :]
        w = xp[idx] * g[None, :]
        z[b0:b1] = w.reshape(b1 - b0, TC, M).sum(axis=1)
    return z


def fine_power(s, N, h):
    """複素の列 s → PFB（T 4）→ FFT（前向き）→ フレームの平均の電力 P[b]（最初の T − 1 フレームは捨てる）"""
    nf = len(s) // N
    xf = s[: nf * N].reshape(nf, N)
    ht = h.reshape(T, N)
    y = np.zeros((nf, N), complex)
    for t in range(T):
        sh = T - 1 - t
        y[sh:] += ht[t] * xf[: nf - sh]
    Y = np.fft.fft(y[T - 1:], axis=1)
    return np.mean(np.abs(Y) ** 2, axis=0)


def stitch(P, N, shift_err=0, no_shift=False):
    """P: (32, N) → つないだスペクトル（32·7N/8）"""
    keep = 7 * N // 16
    out = np.empty(32 * 2 * keep)
    for k in range(32):
        nu = ((k + 0.5) * D / M) % 1.0
        sh = int(round(nu * N))
        assert abs(nu * N - sh) < 1e-9
        if no_shift:
            sh = 0
        sh += shift_err
        Tk = np.roll(P[k], -sh)                              # Tk[b] = P[(b + sh) mod N]
        bs = np.arange(-keep, keep)
        out[k * 2 * keep:(k + 1) * 2 * keep] = Tk[bs % N]
    return out


def run(x, N, frames):
    nblk = N * frames
    z = coarse_float(x, nblk)
    Y = fft32_y(z)
    sg = np.sqrt(np.mean(np.abs(Y[30:]) ** 2, axis=0) / 2)
    g = S / sg
    y8 = np.clip(np.round(Y.real * g), -127, 127) + 1j * np.clip(np.round(Y.imag * g), -127, 127)
    h = design(N)
    P = np.array([fine_power(y8[:, k], N, h) for k in range(32)])
    return P, g


def main():
    N = int(sys.argv[sys.argv.index("--nf") + 1]) if "--nf" in sys.argv else 512
    frames = int(sys.argv[sys.argv.index("--frames") + 1]) if "--frames" in sys.argv else 300
    df = FS / (56 * N)
    keep2 = 7 * N // 8
    rng = np.random.default_rng(29)
    nx = 56 * N * frames + L
    sig = 2 ** 13 * 10 ** (-18 / 20)
    print("== M-4: つなぎ（N_f %d・%d フレーム・df %.3f kHz・つないだ bin %d）" % (N, frames, df / 1e3, 32 * keep2))
    ok = True
    # (a) CW の位置（雑音は弱く）: 継ぎ目の近くを含む 6 点（bin の中心）
    G0s = [5 * keep2 + 3, 5 * keep2 - 2, 11 * keep2 + keep2 // 2, 17 * keep2 + 1, 23 * keep2 - 1, 30 * keep2 + 100]
    n = np.arange(nx)
    res = {}
    for name, kw in (("ふつう", {}), ("陽性対照: sh を 1 ずらす", {"shift_err": 1}), ("陽性対照: sh を掛けない", {"no_shift": True})):
        offs = []
        for G0 in G0s:
            f0 = G0 * df
            x = rng.standard_normal(nx) * sig * 0.1 + 0.5 * sig * np.cos(2 * np.pi * f0 / FS * n)
            x = np.clip(np.round(x), -(2 ** 13 - 1), 2 ** 13 - 1)
            P, _ = run(x, N, frames)
            sp = stitch(P, N, **kw)
            offs.append(int(np.argmax(sp)) - G0)
        res[name] = offs
        print("(a) %s: ピークのずれ（bin）%s" % (name, offs))
    ok &= all(o == 0 for o in res["ふつう"])
    ok &= all(o != 0 for o in res["陽性対照: sh を 1 ずらす"]) and any(abs(o) > 1 for o in res["陽性対照: sh を掛けない"])
    # (b) 継ぎ目の雑音の床
    x = np.clip(np.round(rng.standard_normal(nx) * sig), -(2 ** 13 - 1), 2 ** 13 - 1)
    P, g = run(x, N, frames)
    sp = stitch(P, N)
    # ch ごとの利得の違いは ch の内側（真ん中の半分、224 bin）の平均で揃える（較正の代わり）。
    # 継ぎ目の窓（両側 8 bin = 16 bin）と、内側の同じ幅の窓（対照）の比を比べる。
    # 1 回目は真ん中の 16 bin で揃え、窓 1 個の統計の揺れ（≒ 0.06 dB）を継ぎ目の効果と取り違えて不合格にした
    seam, ctrl = [], []
    for k in range(32):
        seg = sp[k * keep2:(k + 1) * keep2]
        seg = seg / np.mean(seg[keep2 // 4: 3 * keep2 // 4])
        seam.append(np.mean(np.r_[seg[:8], seg[-8:]]))
        for c0 in range(keep2 // 4, 3 * keep2 // 4 - 16, 32):
            ctrl.append(np.mean(seg[c0:c0 + 16]))
    seam_db = 10 * np.log10(np.array(seam))
    ctrl_db = 10 * np.log10(np.array(ctrl))
    sd_ratio = np.std(seam_db) / np.std(ctrl_db)
    print("(b) 継ぎ目の 16 bin / ch の内側: 32 ch の平均 %+.4f dB（系統）・揺れ %.3f dB、内側の同じ幅の窓の揺れ %.3f dB（比 %.2f）"
          % (seam_db.mean(), np.std(seam_db), np.std(ctrl_db), sd_ratio))
    ok &= abs(seam_db.mean()) < 0.03 and sd_ratio < 1.5
    # 陽性対照: sh を N_f/16 ずらすと残す範囲が荒い ch の遷移帯にかかり、継ぎ目の片側の床が下がるはず
    spb = stitch(P, N, shift_err=N // 16)
    sb = []
    for k in range(32):
        seg = spb[k * keep2:(k + 1) * keep2]
        seg = seg / np.mean(seg[keep2 // 4: 3 * keep2 // 4])
        sb.append(np.mean(np.r_[seg[:8], seg[-8:]]))
    sb_db = 10 * np.log10(np.array(sb))
    print("(b) 陽性対照（sh を N_f/16 ずらす）: 継ぎ目の 32 ch の平均 %+.3f dB" % sb_db.mean())
    ok &= sb_db.mean() < -0.3
    print("結果: %s" % ("全部通過" if ok else "不合格"))


if __name__ == "__main__":
    main()
