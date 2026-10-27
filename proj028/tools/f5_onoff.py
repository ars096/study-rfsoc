#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-5f: 荒い段の利得 g_k で割った（入力に換算した）スペクトルで、継ぎ目・ON / OFF の比・チャンクごとの電力を見る
  python3 tools/f5_onoff.py runs/f5f_on40 runs/f5e_run40     # <out>_spec.npy と <out>_meta.json の組（ON・OFF の順）
spec は y = Y·g/2^16 の電力なので、入力の換算は spec / g_k²（定数は落とす）
"""
import argparse
import json
import numpy as np

FS = 4.096e9
NF = 131072
NCH = 32
NKEEP = 114688
DF = FS / (56 * NF)


def load(stem):
    s = np.load(stem + "_spec.npy").astype(np.float64)
    meta = json.load(open(stem + "_meta.json"))
    g = np.array(meta["gain"], float)
    return s / np.repeat(g ** 2, NKEEP)[None, :], meta


def spur_mask(m, thr=3.0, blk=4096):
    floor = np.repeat(np.median(m.reshape(-1, blk), axis=1), blk)
    return 10 * np.log10(m / floor) < thr


def seams(m, ok, w=2048):
    mm = np.where(ok, m, np.nan).reshape(NCH, NKEEP)
    return np.array([10 * np.log10(np.nanmean(mm[k + 1, :w]) / np.nanmean(mm[k, -w:])) for k in range(NCH - 1)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("on")
    ap.add_argument("off")
    a = ap.parse_args()
    son, _ = load(a.on)
    soff, _ = load(a.off)
    mon, moff = son[1:].mean(0), soff[1:].mean(0)       # チャンク 0（157 フレーム）は除く
    ok = spur_mask(mon) & spur_mask(moff)

    print("1. 継ぎ目の段（g² で割った後、両側 2048 bin、dB）")
    for name, m in (("ON ", mon), ("OFF", moff)):
        st = seams(m, ok)
        print(f"  {name}: " + " ".join(f"{x:+.3f}" for x in st))
        print(f"       |段| の最大 {np.abs(st).max():.3f}（継ぎ目 {np.argmax(np.abs(st))}|{np.argmax(np.abs(st)) + 1}）・"
              f"ch 2〜30 の間の最大 {np.abs(st[1:30]).max():.3f}・RMS {np.sqrt((st[1:30] ** 2).mean()):.3f} dB")

    print("\n2. ON / OFF の比（g² で割った後、スプリアスの bin は除く）")
    y = np.where(ok, mon / moff, np.nan).reshape(NCH, NKEEP)
    yc = np.nanmean(y, axis=1)
    print("  荒い ch ごと（dB）: " + " ".join(f"{k}:{10 * np.log10(yc[k]):+.1f}" for k in range(NCH)))
    nseg = 64
    prof = (y / yc[:, None]).reshape(NCH, nseg, -1)
    pr = 10 * np.log10(np.nanmean(np.nanmean(prof[2:31], axis=2), axis=0))
    print(f"  荒い ch の中の形（ch 2〜30 の平均、{nseg} 区間）: 幅 {pr.max() - pr.min():.3f} dB")
    print("   " + " ".join(f"{x:+.2f}" for x in pr))
    d = 256                                             # 143 kHz ごとの比
    yb = 10 * np.log10(np.nanmean(y.reshape(-1, d), axis=1))
    print(f"  {d} bin（{d * DF / 1e3:.0f} kHz）ごとの比: 最小 {np.nanmin(yb):+.1f}・最大 {np.nanmax(yb):+.1f} dB")

    print("\n3. スプリアスの高さ（局所の床に対して、dB）: OFF → ON")
    blk = 4096
    for b in (917504, 1835008, 2752512):               # fs/8・fs/4・3fs/8
        for nm, m in (("OFF", moff), ("ON", mon)):
            fl = np.median(m[(b // blk) * blk:(b // blk + 1) * blk])
            print(f"  {b * DF / 1e6:9.3f} MHz {nm:3s}: {10 * np.log10(m[b] / fl):+.1f}", end="")
        print()

    print("\n4. チャンクごとの電力（ch 2〜30 の全電力、チャンク 1〜の平均に対して、%）")
    for nm, s in (("ON ", son), ("OFF", soff)):
        p = np.nanmean(np.where(ok, s, np.nan).reshape(s.shape[0], NCH, NKEEP)[:, 2:31], axis=(1, 2))
        q = 100 * (p[1:] / p[1:].mean() - 1)
        print(f"  {nm}: σ {q.std():.2f} %・幅 {q.min():+.2f}〜{q.max():+.2f} %・隣の差の σ {np.diff(q).std() / np.sqrt(2):.2f} %")
        print("       " + " ".join(f"{x:+.1f}" for x in q))


if __name__ == "__main__":
    main()
