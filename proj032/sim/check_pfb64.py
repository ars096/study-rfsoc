#!/usr/bin/env python3
"""check_pfb64 — tb_pfb64 の出力を仕様の式 y_k[m] = Σ h[n]·x[p−n]·exp(−j2πk(p−n)/64)（p = 16m + 191）と比べる。
RTL は定数の位相 exp(−j2πk·191/64) を落とし、2^YF 倍で出す: y_rtl = y_spec · exp(+j2πk·191/64) · 2^YF。
判定: 頭ごとに相対誤差 rms ≦ 1e-4（丸め: u の 2^-10 と出口の 2^-8 で決まる見当）・ch の取り違えなし（別の k の予言とは合わない）。
  python3 check_pfb64.py gen  x_in.hex      # 入力を作る（雑音 ＋ CW 2 本、16 bit）
  python3 check_pfb64.py check x_in.hex y_out.txt   # PSPLIT=1 の環境変数で偶奇の 2 組の並び"""
import json, sys
import numpy as np
K = [0, 1, 2, 3, 5, 8, 13, 16, 17, 21, 29, 31, 32, 7, 24, 30]
K_PS = [0, 2, 8, 16, 24, 30, 32, 4, 1, 3, 5, 13, 17, 21, 29, 31]   # PSPLIT（頭 0..7 は偶、8..15 は奇）
import os
if os.environ.get('PSPLIT') == '1':
    K = K_PS
NBEAT, YF = 400, 8
here = __file__.rsplit('/', 1)[0]
co = json.load(open(here + '/../runs/m0_coef.json'))['pfb']
h = np.array(co['coef'], float) / 2.0 ** co['shift']
if sys.argv[1] == 'gen':
    rng = np.random.default_rng(32)
    n = np.arange(NBEAT * 16)
    x = rng.normal(0, 3000, n.size) + 9000 * np.cos(2 * np.pi * 300.3 / 4096 * n) + 4000 * np.cos(2 * np.pi * 1730.7 / 4096 * n)
    x = np.clip(np.round(x), -32768, 32767).astype(np.int64)
    with open(sys.argv[2], 'w') as f:
        for q in range(NBEAT):
            f.write(''.join(f'{int(v) & 0xFFFF:04x}' for v in x[16 * q:16 * q + 16][::-1]) + '\n')
    sys.exit(0)
rows = [l.split() for l in open(sys.argv[3])]
y = np.array([[int(a) + 1j * int(b) for a, b in zip(r[0::2], r[1::2])] for r in rows])
xs = []
for l in open(sys.argv[2]):
    l = l.strip()
    xs += [int(l[4 * (15 - j):4 * (16 - j)], 16) for j in range(16)]
xs = np.array([v - 65536 if v >= 32768 else v for v in xs]) >> 2
nm = y.shape[0]
print(f'フレーム {nm}（入力 {NBEAT} ビート → 予言 {NBEAT - 11}）')
ok = nm == NBEAT - 11
nn = np.arange(192)
for i, k in enumerate(K):
    ref = np.array([np.sum(h * xs[16 * m + 191 - nn] * np.exp(-2j * np.pi * k * (16 * m + 191 - nn) / 64)) for m in range(nm)])
    ref = ref * np.exp(2j * np.pi * k * 191 / 64) * 2 ** YF
    err = np.sqrt(np.mean(np.abs(y[:, i] - ref) ** 2)) / np.sqrt(np.mean(np.abs(ref) ** 2))
    # 取り違えの見張り: 隣の k の予言と比べると大きく外れること
    k2 = (k + 1) % 33
    ref2 = np.array([np.sum(h * xs[16 * m + 191 - nn] * np.exp(-2j * np.pi * k2 * (16 * m + 191 - nn) / 64)) for m in range(nm)]) * np.exp(2j * np.pi * k2 * 191 / 64) * 2 ** YF
    err2 = np.sqrt(np.mean(np.abs(y[:, i] - ref2) ** 2)) / np.sqrt(np.mean(np.abs(ref2) ** 2))
    good = err <= 1e-4 and err2 > 0.5
    ok &= good
    print(f'k {k:2d}: 相対誤差 rms {err:.2e}（隣の k {k2} と {err2:.2f}）{"" if good else " ← NG"}')
print('結果: 全部通過' if ok else '結果: 失敗')
sys.exit(0 if ok else 1)
