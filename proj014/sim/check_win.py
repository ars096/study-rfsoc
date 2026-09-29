#!/usr/bin/env python3
"""proj014 — pfb_core → ddc_core の sim の照合（make sim-win）。

  python3 check_win.py gen DIR      x（雑音 + CW 2 本 + 満杯の区間、低位 2 bit は乱数）を DIR/x.hex に
  python3 check_win.py cases        照合する組（K NS DPHI）
  python3 check_win.py check DIR    DIR/z_*.txt を pfb_fixed → ddc_fixed と bit 単位で照合
つなぎ目の試験なので、組は少なめ（6 通りの幅 × 1、入力の途切れあり）。各段の中身の網羅は sim-pfb・sim-ddc が持つ。
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import win_fixed as F  # noqa: E402
import win_model as WM  # noqa: E402

NSAMP = 16 * 4096
CASES = [(5, ns, -37.81234567) for ns in range(1, 7)]


def gen(d):
    rng = np.random.default_rng(16)
    t = np.arange(NSAMP)
    x = rng.normal(0, 1200, NSAMP)
    x += 2500 * np.cos(2 * np.pi * (5 * 128 - 37.81 + 1.3) / 4096 * t) + 600 * np.cos(2 * np.pi * 1700.1 / 4096 * t)
    x[30000:30200] = 8191 * np.sign(rng.normal(size=200))
    x = np.clip(np.round(x), -8192, 8191).astype(np.int64)
    w16 = ((x << 2) | rng.integers(0, 4, NSAMP)) & 0xFFFF
    np.save(os.path.join(d, "x14.npy"), x)
    with open(os.path.join(d, "x.hex"), "w") as fp:
        fp.write("\n".join(f"{v:04x}" for v in w16) + "\n")
    print(f"入力: {NSAMP} サンプル → {d}/x.hex")


def cases():
    for k, ns, dd in CASES:
        print(k, ns, F.nco_step(dd)[0])


def check(d):
    x = np.load(os.path.join(d, "x14.npy"))
    des = F.prepare(WM.design(60.0, WM.RIPPLE_PP))
    cfg = dict(F.DEFAULT)
    bad = 0
    for k, ns, dd in CASES:
        dp = F.nco_step(dd)[0]
        cnt = {}
        yr, yi = F.pfb_fixed(x, k, des, cfg, cnt)
        ne = 2 * (len(yr) // 2)
        zr, zi = F.ddc_fixed(yr[:ne], yi[:ne], dp, ns, des, cfg, cnt)
        got = np.loadtxt(os.path.join(d, f"z_k{k}_ns{ns}.txt"), dtype=np.int64, ndmin=2)
        n = min(len(zr), len(got))
        neq = int(np.count_nonzero((got[:n, 0] != zr[:n]) | (got[:n, 1] != zi[:n])))
        st = "OK" if (neq == 0 and len(got) == len(zr) and not cnt) else "NG"
        print(f"  k {k} NS {ns}（{WM.R0 / 2 ** ns:4.0f} MHz）: 出力 RTL {len(got)} / 模型 {len(zr)}、不一致 {neq}、模型の飽和 {cnt or 0} → {st}")
        bad += st == "NG"
    print("結果: 全部通過" if bad == 0 else f"結果: 失敗 {bad} 件")
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        gen(sys.argv[2])
    elif sys.argv[1] == "cases":
        cases()
    else:
        sys.exit(check(sys.argv[2]))
