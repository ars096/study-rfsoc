#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — ADC の生サンプルの統計（TP のアラン分散が予言の 0.31 倍に見える件の切り分け）。

TP の 1 区切り（N = 512 フレーム × 8192 = 4,194,304 サンプル）の相対分散は、
    var(mean x²) / E[x²]² ≈ F / N、  F = (κ − 3)·(…) + 2·Σ_k ρ(k)²
ガウス雑音なら F = 2·Σρ² ≧ 2（ρ(0) = 1 だけでも 2）。s45allan の --tp-bw 2048 の予言はちょうど 2/N なので、
**TP の τ0 の「予言の何倍」は F/2 と比べられる**。F は生サンプルから直に測れる:
    F(L) = L · var(長さ L の塊ごとの mean x²) / mean(x²)²       （L が相関の長さより十分長ければ L によらない）
  - F/2 ≒ 0.3 なら、入力そのものが「ガウスより揺らがない」（尖度 κ が小さい: 圧縮・振り切れた雑音など）。TP は正しい
  - F/2 ≒ 1 以上なら、入力はふつうで、TP の積み方か解析の側に原因がある

取得（ボード。proj009 の 4ch のビットストリームを載せる → 終わったら specd 用の bit に戻す）:

    cd proj009/pynq
    for k in $(seq -w 1 20); do sudo python3 adc_capture.py --bitfile proj009_4ch.bit --nsamples 131072 --save cap$k.npy; done

解析（どの PC でも。numpy だけ）:

    python3 adcstat.py cap*.npy                 # ch の並びは 4ch 版: ch0=ADC_D / ch1=ADC_C / ch2=ADC_B / ch3=ADC_A
    python3 adcstat.py cap*.npy --json noise.adcstat.json

取得の 1 回は 32 µs しかないので、塊の分散は全ファイルの塊を寄せて出す（20 回 × 131072 = 2.6 M サンプル → L = 8192 で 320 塊、
F の統計誤差 ≒ √(2/320) ≒ 8 %）。
"""
import argparse
import json
import math
import sys

import numpy as np

DBFS0 = 10 * math.log10(8192 ** 2 / 2)
CH_NAMES_4 = ("ADC_D", "ADC_C", "ADC_B", "ADC_A")
LS = (256, 1024, 4096, 8192)
NLAG = 256


def load(paths):
    xs = []
    for p in paths:
        a = np.load(p)
        if a.ndim == 1:
            a = a[None, :]
        xs.append(a)
    nch = {a.shape[0] for a in xs}
    if len(nch) != 1:
        raise SystemExit(f"ファイルごとに ch の数が違う: {sorted(nch)}")
    return xs


def stat(blocks):
    """blocks: 1 ch の取得ごとの配列（int16、14 bit 上位寄せ）の並び"""
    x = [b.astype(np.float64) / 4.0 for b in blocks]          # 14 bit の LSB
    allx = np.concatenate(x)
    mu = allx.mean()
    p2 = np.mean(allx * allx)
    c = allx - mu
    s2 = np.mean(c * c)
    kurt = float(np.mean(c ** 4) / s2 ** 2)
    # 自己相関（取得ごとに FFT で出して平均。取得の継ぎ目はまたがない）
    acc = np.zeros(NLAG + 1); cnt = 0
    for b in x:
        d = b - mu
        n = len(d)
        f = np.fft.rfft(d, 2 * n)
        r = np.fft.irfft(f * np.conj(f))[:NLAG + 1] / np.arange(n, n - NLAG - 1, -1)
        acc += r; cnt += 1
    rho = acc / cnt / (acc[0] / cnt)
    sum_rho2 = float(1 + 2 * np.sum(rho[1:] ** 2))
    # F は取得の中だけで出す（各塊を自分の取得の平均で割る）。取得ごとの電力の違い（Overlay の読み直し・較正の
    # 動き）は別に cap_rstd として出す（入れると F が L に比例して膨らむ: 2026-10-07 の無入力の取得で見えた）
    pw = np.array([np.mean(b * b) for b in x])
    dc = np.array([b.mean() for b in x])
    F = {}
    for L in LS:
        m = []
        for b, pb in zip(x, pw):
            k = len(b) // L
            if k >= 2:
                mb = (b[:k * L] ** 2).reshape(k, L).mean(axis=1) / pb
                m.append(mb - mb.mean())
        m = np.concatenate(m) if m else np.array([])
        if len(m) >= 8:
            dof = len(m) - len([1 for b in x if len(b) // L >= 2])
            F[L] = dict(F=float(L * np.sum(m * m) / max(dof, 1)), nblk=int(len(m)), err=float(math.sqrt(2.0 / max(dof, 1))))
    clip = float(np.mean(np.abs(allx) >= 8191))
    return dict(n=int(len(allx)), mean=float(mu), sigma=float(math.sqrt(s2)), dbfs=float(10 * math.log10(p2) - DBFS0),
                cap_rstd=float(pw.std() / pw.mean()) if len(pw) > 1 else None, cap_dc=[float(v) for v in dc],
                kurtosis=kurt, rho=[float(r) for r in rho[1:9]], sum_rho2=sum_rho2, F_gauss=2 * sum_rho2, F=F, clip_frac=clip)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("paths", nargs="+", help="adc_capture.py --save の .npy（同じ条件で取ったもの）")
    p.add_argument("--json", default=None)
    a = p.parse_args()
    xs = load(a.paths)
    nch = xs[0].shape[0]
    names = CH_NAMES_4 if nch == 4 else tuple(f"ch{i}" for i in range(nch))
    out = {}
    print(f"{len(xs)} 取得 × {xs[0].shape[1]} サンプル")
    for i in range(nch):
        r = stat([b[i] for b in xs])
        out[names[i]] = r
        print(f"{names[i]}: {r['dbfs']:+.2f} dBFS（σ {r['sigma']:.1f} LSB・DC {r['mean']:+.2f}）・尖度 κ {r['kurtosis']:.3f}（ガウス 3）・"
              f"振り切れ {r['clip_frac']:.1e}・取得ごとの電力のばらつき {'-' if r['cap_rstd'] is None else '%.2f %%' % (100 * r['cap_rstd'])}"
              f"・DC {min(r['cap_dc']):+.2f}〜{max(r['cap_dc']):+.2f}")
        if r["dbfs"] < -45:
            print("      **入力がほぼ無い（−45 dBFS 未満）**: ノイズソースが切れている・ATT が 100 dB のまま、では？ TP の切り分けにはノイズを入れて取る")
        print(f"      ρ(1..4) = " + ", ".join(f"{v:+.3f}" for v in r["rho"][:4]) +
              f"・ガウスなら F = 2Σρ² = {r['F_gauss']:.3f}（予言の {r['F_gauss'] / 2:.2f} 倍）")
        for L, d in r["F"].items():
            print(f"      L {L:5d}: F = {d['F']:.3f} ± {d['F'] * d['err']:.3f}（{d['nblk']} 塊）→ TP の τ0 は予言（2048 MHz）の {d['F'] / 2:.2f} 倍のはず")
    if a.json:
        json.dump(dict(paths=a.paths, res=out), open(a.json, "w"), ensure_ascii=False, indent=1)
        print(f"まとめ: {a.json}")


if __name__ == "__main__":
    sys.exit(main())
