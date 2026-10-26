#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-5c の手元の解析: f5.py の <out>_spec.npy（チャンク × 3670016、継いだ順 G、f = G·fs/(56·131072)）を読む
  python3 tools/f5_ana.py runs/f5_run1_spec.npy [--png out.png]
見るもの:
  1. スプリアス: 移動中央値の上 --thr dB を超える bin（DC と fs/2^k の近くは名前をつける）
  2. 荒い ch の継ぎ目: 継ぎ目の両側 W bin の平均の比（dB）。床が平らなら 0 に近い
  3. 荒い ch の中の形: 32 本を（各 ch の平均で割って）重ねた平均を 64 区間で
  4. チャンク間: 隣の 2 チャンクの比の相対 σ（160 フレームの積算の雑音なら √2/√160 ≒ 0.112）
"""
import argparse
import numpy as np

FS = 4.096e9
NF = 131072
NCH = 32
NKEEP = 114688
DF = FS / (56 * NF)


def name_of(f):
    for k in range(1, 9):
        for m in range(0, 2 ** k + 1):
            fr = FS * m / 2 ** k
            if abs(f - fr) < 3 * DF and fr <= FS / 2:
                return f"{m}·fs/{2 ** k}" if m else "DC"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--thr", type=float, default=10.0)
    ap.add_argument("--w", type=int, default=2048)
    ap.add_argument("--png")
    a = ap.parse_args()
    s = np.load(a.spec).astype(np.float64)
    nck, n = s.shape
    assert n == NCH * NKEEP
    m = s[1:].mean(0) if nck > 1 else s[0]           # チャンク 0（157 フレーム）は除いて平均
    print(f"{a.spec}: {nck} チャンク × {n}・df {DF:.3f} Hz・全体の中央値 {np.median(m):.1f}")

    # 1. スプリアス（局所の床 = 4096 bin ごとの中央値）
    blk = 4096
    floor = np.repeat(np.median(m.reshape(-1, blk), axis=1), blk)
    r = 10 * np.log10(m / floor)
    idx = np.where(r > a.thr)[0]
    print(f"\n1. スプリアス（局所の床の +{a.thr} dB 超）: {len(idx)} bin")
    # 隣り合う bin をまとめて、山ごとに最大を出す
    groups = np.split(idx, np.where(np.diff(idx) > 2)[0] + 1) if len(idx) else []
    groups.sort(key=lambda g: -r[g].max())
    for g in groups[:30]:
        b = g[np.argmax(r[g])]
        f = b * DF
        print(f"  bin {b:8d}  {f / 1e6:14.6f} MHz  +{r[b]:5.1f} dB  幅 {len(g)} bin  荒い ch {b // NKEEP:2d}  {name_of(f)}")

    # 2. 継ぎ目
    w = a.w
    lv = m.reshape(NCH, NKEEP)
    print(f"\n2. 荒い ch の平均（dB、全体の中央値に対して）と継ぎ目の段（両側 {w} bin、スプリアスの bin は除く）")
    ok = r < 3.0
    mm = np.where(ok, m, np.nan).reshape(NCH, NKEEP)
    med = np.median(m)
    print("  ch の平均: " + " ".join(f"{10 * np.log10(np.nanmean(mm[k]) / med):+.2f}" for k in range(NCH)))
    steps = []
    for k in range(NCH - 1):
        lo = np.nanmean(mm[k, -w:])
        hi = np.nanmean(mm[k + 1, :w])
        steps.append(10 * np.log10(hi / lo))
    steps = np.array(steps)
    print("  継ぎ目の段（dB）: " + " ".join(f"{x:+.3f}" for x in steps))
    e = 10 * np.log10(1 + 1 / np.sqrt(w * (nck - 1) * 160))
    print(f"  |段| の最大 {np.abs(steps).max():.3f} dB・RMS {np.sqrt((steps ** 2).mean()):.3f} dB（雑音だけなら 1σ ≒ {e * np.sqrt(2):.3f} dB）")

    # 3. 荒い ch の中の形
    nseg = 64
    prof = (mm / np.nanmean(mm, axis=1, keepdims=True)).reshape(NCH, nseg, -1)
    pr = 10 * np.log10(np.nanmean(np.nanmean(prof, axis=2), axis=0))
    print(f"\n3. 荒い ch の中の形（{nseg} 区間、ch 1〜30 も含む 32 本の平均、dB）: 幅 {pr.max() - pr.min():.3f} dB")
    print("  " + " ".join(f"{x:+.2f}" for x in pr))

    # 4. チャンク間
    if nck >= 3:
        q = s[2] / s[1]
        ok2 = ok
        rs = np.std(q[ok2]) / np.mean(q[ok2])
        print(f"\n4. チャンク 2 / 1 の比: 平均 {np.mean(q[ok2]):.4f}・相対 σ {rs:.4f}（160 フレームの雑音なら {np.sqrt(2 / 160):.4f}）")
        q0 = s[0] / s[1]
        print(f"   チャンク 0 / 1 の比: 平均 {np.mean(q0[ok2]):.4f}（157/160 = {157 / 160:.4f} なら和、1 なら平均）")

    if a.png:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(3, 1, figsize=(12, 10))
        x = np.arange(n) * DF / 1e6
        d = 64
        ax[0].plot(x[::d], 10 * np.log10(m.reshape(-1, d).mean(1)), lw=0.5)
        ax[0].set_xlabel("MHz"); ax[0].set_ylabel("dB"); ax[0].set_title(f"{a.spec}（{d} bin 平均）")
        for k in range(1, NCH):
            ax[0].axvline(k * NKEEP * DF / 1e6, color="r", lw=0.2)
        ax[1].plot(np.arange(nseg), pr, "o-"); ax[1].set_xlabel("荒い ch の中の区間"); ax[1].set_ylabel("dB")
        ax[2].plot(np.arange(1, NCH), steps, "o-"); ax[2].set_xlabel("継ぎ目（ch k−1 | k）"); ax[2].set_ylabel("段 dB")
        fig.tight_layout(); fig.savefig(a.png, dpi=110)
        print(f"\n図: {a.png}")


if __name__ == "__main__":
    main()
