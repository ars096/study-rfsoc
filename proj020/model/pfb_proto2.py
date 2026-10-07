# SPDX-License-Identifier: BSD-3-Clause
"""proj020 下調べ 2（2026-10-07）: 原型を「0.5 ch で −3 dB（隣の ch と −3 dB で交わる）」に寄せたときの ch の応答。numpy だけ。

要件の目安: 0.5 ch 未満はできるだけ 0 dB、0.5 ch で −3 dB、|Δ| ≧ 1 ch で −60 / −50 / −40 dB。
sinc × Kaiser の bw を、0.5 ch で −3 dB になるように β ごとに二分法で合わせ、|Δ| ≧ 1 ch の最大が最も深い β を T ごとに探す。
係数は Σh² = 4096 に規格化し 18 bit（Q16）に丸めたもので評価する（model/pfb4.py と同じ流儀）。

結果（N = 4096、18 bit）:
  T  原型                     0.5 ch  ≧1 ch  ≧1.5 ch  ≧3 ch  0.4 ch  和の波打ち  ENBW
  4  Kaiser β8 bw1.00（rev1）  −5.88  −42.1   −83.6  −101.5  −3.35     2.88    0.776
  4  Kaiser β5 bw1.198（F）    −3.00  −53.7   −58.0   −64.5  −1.20     0.08    1.010
  3  Kaiser β3.25 bw1.215（H） −2.99  −41.9   −48.0   −54.5  −1.28     0.08    1.010
  T = 2 は ≧ 1 ch が −25 dB 止まり。T = 3 は minimax でも −49 dB（−50 dB に届かない）。−60 dB には T ≧ 6 が要る。

使い方: python3 pfb_proto2.py            # 上の 3 つの表
        python3 pfb_proto2.py search T   # T を指定して β を掃く
"""
import sys

import numpy as np

N = 4096
OS = 32          # 1 ch を T·OS 点で見る


def proto(T, beta, bw):
    L = N * T
    n = np.arange(L) - (L - 1) / 2
    h = np.sinc(bw * n / N) * np.kaiser(L, beta)
    h *= np.sqrt(N / np.sum(h * h))
    return np.round(h * 65536) / 65536            # 18 bit・Q16


def stats(h, T):
    L = len(h)
    H = np.abs(np.fft.rfft(h, L * OS)) ** 2
    H /= H[0]
    f = np.arange(len(H)) * N / (L * OS)
    dB = 10 * np.log10(np.maximum(H, 1e-30))
    Mi = T * OS
    S = np.concatenate([H, H[-2:0:-1]]).reshape(-1, Mi).sum(0)
    return dict(h05=np.interp(0.5, f, dB), h04=np.interp(0.4, f, dB),
                sb1=dB[f >= 1].max(), sb15=dB[f >= 1.5].max(), sb3=dB[f >= 3].max(),
                rip=10 * np.log10(S.max() / S.min()), enbw=S.sum() / Mi)


def fit_bw(T, beta, lo=0.9, hi=1.6):
    """0.5 ch で −3.01 dB になる bw（二分法）。"""
    for _ in range(30):
        m = 0.5 * (lo + hi)
        if stats(proto(T, beta, m), T)["h05"] < -3.0103:
            lo = m
        else:
            hi = m
    return 0.5 * (lo + hi)


def show(name, T, beta, bw):
    s = stats(proto(T, beta, bw), T)
    print(f"T={T} {name:26s} 0.5ch {s['h05']:6.2f} | ≥1ch {s['sb1']:6.1f} ≥1.5ch {s['sb15']:6.1f} ≥3ch {s['sb3']:7.1f} | "
          f"0.4ch {s['h04']:6.2f} | 和の波打ち {s['rip']:.2f} dB | ENBW {s['enbw']:.3f}")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "search":
        T = int(sys.argv[2])
        for beta in np.arange(2.0, 10.01, 0.5):
            show(f"Kaiser β{beta:.2f} bw{fit_bw(T, beta):.3f}", T, beta, fit_bw(T, beta))
    else:
        show("Kaiser β8 bw1.00（rev1）", 4, 8.0, 1.0)
        show("Kaiser β5 bw1.198（F）", 4, 5.0, 1.198)
        show("Kaiser β3.25 bw1.215（H）", 3, 3.25, 1.215)
