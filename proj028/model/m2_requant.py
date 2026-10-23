#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 M-2 — 荒い段の後の再量子化（b bit、各成分の雑音の σ = S LSB、丸め・飽和）。numpy だけ。

荒い ch の複素の時系列を、白い複素ガウス雑音（各成分 σ）＋ CW（振幅 A、細かい ch の中心）で置く。
荒い PFB の通過域は M-1 で 0.016 dB 以内に平らなので、ここでは荒い PFB を通さない（ch の中の白い雑音として扱う）。

判定（README の M-2）:
  (a) 量子化の損失 var(q(x) − x) / var(x)。模型の判定は 1/12/S² と 5 % 以内（目標 ≦ 0.1 % は S を選ぶ物差しで、判定ではない）
  (b) 細かい FFT（N_f 16384、Hann、K 本平均）で、CW の ±3 bin の外の最大が床 + 3 dB を超える CW の強さ
使い方:
  python3 model/m2_requant.py all
"""
import sys

import numpy as np

NF = 16384
KEEP = 14336                 # N_f / os（os 8/7）
K = 64
THR_DB = 3.0


def quant(x, b):
    lim = 2 ** (b - 1) - 1
    return np.clip(np.round(x.real), -lim, lim) + 1j * np.clip(np.round(x.imag), -lim, lim)


def loss(b, S, n=1 << 22, rng=None):
    x = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) * S
    e = quant(x, b) - x
    return np.var(e) / np.var(x)


def spur_excess(b, S, cw_db_coarse, rng):
    """cw_db_coarse: CW の電力 A² を荒い ch の雑音 2S² に対して dB で。戻り: 床に対する最大の超え（dB）。"""
    A = np.sqrt(2 * S * S * 10 ** (cw_db_coarse / 10))
    kc = 1234                                     # CW の bin（ch の中心）
    n = np.arange(NF)
    w = np.hanning(NF)
    acc = np.zeros(NF)
    for _ in range(K):
        ph = rng.uniform(0, 2 * np.pi)
        x = (rng.standard_normal(NF) + 1j * rng.standard_normal(NF)) * S + A * np.exp(1j * (2 * np.pi * kc * n / NF + ph))
        acc += np.abs(np.fft.fft(quant(x, b) * w)) ** 2
    mask = np.ones(NF, bool)
    mask[kc - 3: kc + 4] = False
    # 残す範囲（|y| ≦ Δ/2）だけを見る: bin の番号 j を −NF/2..NF/2 で
    j = (np.arange(NF) + NF // 2) % NF - NF // 2
    mask &= np.abs(j) < KEEP // 2
    floor = np.median(acc[mask])
    return 10 * np.log10(acc[mask].max() / floor)


def onset(b, S, rng, levels):
    for lv in levels:
        ex = spur_excess(b, S, lv, rng)
        if ex > THR_DB:
            return lv, ex
    return None, None


def main():
    rng = np.random.default_rng(2)
    fine_db = 10 * np.log10(KEEP)                 # 荒い ch の雑音 / 細かい ch の雑音
    ok = True
    print("== M-2: 再量子化（細かい ch の雑音 = 荒い ch の雑音 − %.1f dB）" % fine_db)
    print("   b   S    (a) 損失     1/12/S²     (b) 歪みが見え始める CW（荒い ch / 細かい ch）")
    for b, S, ctrl in ((8, 16, False), (8, 12, False), (8, 11, False), (8, 8, False), (4, 2, True)):
        a = loss(b, S, rng=rng)
        lv, ex = onset(b, S, rng, np.arange(-6.0, 30.01, 0.5))
        lvs = "見えない（≦ +30 dB）" if lv is None else "%+5.1f dB / %+5.1f dB（超え %.1f dB）" % (lv, lv + fine_db, ex)
        tgt = "" if ctrl else ("  目標 ≦ 0.1 %: " + ("○" if a <= 1e-3 else "×"))
        print("  %2d  %3d   %.2e    %.2e    %s%s%s" % (b, S, a, 1 / 12 / S ** 2, lvs, "  ← 陽性対照" if ctrl else "", tgt))
        # 模型の判定: 損失が 1/12/S² と 5 % 以内（飽和の無い丸め）。陽性対照は損失が大きく、低い強さで歪みが見える
        ok &= abs(a * 12 * S * S - 1) < 0.05
        if ctrl:
            ok &= a > 1e-2 and lv is not None and lv < 8
    print("  結果: %s" % ("全部通過" if ok else "不合格"))


if __name__ == "__main__":
    main()
