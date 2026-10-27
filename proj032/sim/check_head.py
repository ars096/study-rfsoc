#!/usr/bin/env python3
"""check_head — tb_head の出口: 周波数 3.4375 MHz（128 MS/s）の CW、振幅は入力 × 2^(VF−8) × light の利得（≒ 1）。
判定: 出口の数 ≒ 4096、FFT の山の bin が予言どおり、振幅の比 1 ± 0.001、山以外の最大 ≦ −60 dB。"""
import sys
import numpy as np
z = np.array([[int(a) for a in l.split()] for l in open(sys.argv[1])])
z = z[:, 0] + 1j * z[:, 1]
z = z[100:100 + 2048]
n = len(z)
X = np.fft.fft(z * np.hanning(n))
k = int(np.argmax(np.abs(X)))
kp = round(3.4375 / 128 * n)
amp = np.median(np.abs(z)) / 1e6
P = np.abs(X) ** 2
Pn = P.copy(); Pn[max(0, k - 4):k + 5] = 0
spur = 10 * np.log10(Pn.max() / P[k])
ok = k == kp and abs(amp - 1) < 1e-3 and spur < -60
print(f"出口 {len(z)} 個・山 bin {k}（予言 {kp}）・振幅比 {amp:.6f}・山以外 {spur:.1f} dB")
print("結果: 全部通過" if ok else "結果: 失敗")
