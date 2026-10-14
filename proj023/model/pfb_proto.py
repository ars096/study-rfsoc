# SPDX-License-Identifier: BSD-3-Clause
# proj020 下調べ: PFB（T = 4、4096 点）の原型の ch の応答（半 ch の落ち・隣接 ch の和の波打ち・|Δ| ≧ 1.5 ch の最大・ENBW）
import numpy as np
from scipy.signal import windows
N=4096;T=4;L=N*T;OS=64
n=np.arange(L)-(L-1)/2
for nm,w in [("Hann",windows.hann(L)),("Hamming",windows.hamming(L)),("Kaiser8",windows.kaiser(L,8))]:
  for bw in (1.0,1.05,1.1):
    h=np.sinc(bw*n/N)*w
    H=np.abs(np.fft.fft(h,L*OS))**2; H/=H[0]
    # 1 ch = T*OS bins. Sum of shifted responses over all ch at sub-ch offset
    M=T*OS; S=H.reshape(-1,M).sum(0)  # aliasing sum over channels
    rip=10*np.log10(S.max()/S.min())
    f=np.fft.fftfreq(L*OS)*N; sc=10*np.log10(np.interp(0.5,np.sort(f),H[np.argsort(f)]))
    sl=10*np.log10(H[(np.abs(f)>=1.5)].max())
    print(f"{nm:8s} bw={bw:4.2f} scallop {sc:6.2f} dB  ΣP の波打ち {rip:5.2f} dB  |f|≥1.5 の最大 {sl:6.1f} dB  ENBW {H.sum()/M:5.3f}")
