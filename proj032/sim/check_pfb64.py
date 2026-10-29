#!/usr/bin/env python3
"""check_pfb64 — tb_pfb64 の出力を仕様の式 y_k[m] = Σ h[n]·x[p−n]·exp(−j2πk(p−n)/64)（p = 16m + 191）と比べる。
RTL は定数の位相 exp(−j2πk·191/64) を落とし、2^YF 倍で出す: y_rtl = y_spec · exp(+j2πk·191/64) · 2^YF。
判定: 頭ごとに相対誤差 rms ≦ 1e-4（丸め: u の 2^-10 と出口の 2^-8 で決まる見当）・ch の取り違えなし（別の k の予言とは合わない）。
  python3 check_pfb64.py gen  x_in.hex      # 入力を作る（雑音 ＋ CW 2 本、16 bit）
  python3 check_pfb64.py check x_in.hex y_out.txt   # PSPLIT=1 の環境変数で偶奇の 2 組の並び
P-5: 加えて整数の模型（model/pfb64_fixed.py）と全部の頭・全部のフレームを bit 単位で照らす（PFB64_POSCTL_MODEL=1 で照合の陽性対照）"""
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
    if os.environ.get('LOUD') == '1':     # P-5: 満杯（ADC の端で切れる）の方形に近い波 ＋ 雑音。出口の飽和の道を通す
        x = 40000 * np.sign(np.cos(2 * np.pi * 512.0 / 4096 * n + 0.3)) + rng.normal(0, 2000, n.size)
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
    good = (err <= 1e-4 or os.environ.get('LOUD') == '1') and err2 > 0.5   # LOUD: 弱い ch の電力が小さく相対誤差が膨らむので、判定は bit 単位の照合だけ
    ok &= good
    print(f'k {k:2d}: 相対誤差 rms {err:.2e}（隣の k {k2} と {err2:.2f}）{"" if good else " ← NG"}')
# P-5: 整数の模型（model/pfb64_fixed.py）と bit 単位で
sys.path.insert(0, here + '/../model')
import pfb64_fixed as PF  # noqa: E402
xs16 = np.array([v - 65536 if v >= 32768 else v for v in (int(l.strip()[4 * (15 - j):4 * (16 - j)], 16) for l in open(sys.argv[2]) for j in range(16))])
cnt = {}
mr, mi = PF.pfb64_fixed(xs16, K, cnt)
if os.environ.get('PFB64_POSCTL_MODEL') == '1':   # 照合の陽性対照: 模型の頭 3 の k を 1 ずらす
    mr2, mi2 = PF.pfb64_fixed(xs16, [k + (i == 3) for i, k in enumerate(K)], {})
    mr[:, 3], mi[:, 3] = mr2[:, 3], mi2[:, 3]
nb = min(nm, mr.shape[0])
yr_, yi_ = y.real.astype(np.int64)[:nb], y.imag.astype(np.int64)[:nb]
for i, k in enumerate(K):
    bad = int(np.count_nonzero((yr_[:, i] != mr[:nb, i]) | (yi_[:, i] != mi[:nb, i])))
    if bad:
        ok = False
        print(f'k {k:2d}: 整数の模型と不一致 {bad} / {nb} フレーム ← NG')
wr = {kk: v for kk, v in cnt.items() if kk.startswith('wrap_')}
print(f'整数の模型と bit 単位: フレーム {nb}・頭 {len(K)}・不一致 {"なし" if all(np.array_equal(yr_[:, i], mr[:nb, i]) and np.array_equal(yi_[:, i], mi[:nb, i]) for i in range(len(K))) else "あり"}・模型の飽和 {cnt}・巻き戻り {wr}')
if wr or nm != mr.shape[0]:
    ok = False
print('結果: 全部通過' if ok else '結果: 失敗')
sys.exit(0 if ok else 1)
