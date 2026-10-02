#!/usr/bin/env python3
"""proj014 — pfb_core の単体の sim の照合（make sim-pfb）。

  python3 check_pfb.py gen DIR          入力を作る（雑音 + CW 2 本 + 満杯に近い振幅を少し。低位の 2 bit は乱数）
  python3 check_pfb.py check DIR K...   DIR/y_K*.txt を model/win_fixed.py の pfb_fixed と bit 単位で照合

判定: 全フレーム・全 k で実部・虚部とも一致（1 LSB の違いも NG）。出力のフレーム数が模型と同じ。飽和 0。
陽性対照（make sim-pfb SIM_PFB_POSCTL=1）: RTL の分岐の和の丸めを切り捨てに替える → 一致しないこと。
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import win_fixed as F  # noqa: E402
import win_model as WM  # noqa: E402

NSAMP = 16 * 1024


def gen(d):
    rng = np.random.default_rng(14)
    t = np.arange(NSAMP)
    x = rng.normal(0, 600, NSAMP)
    x += 3000 * np.cos(2 * np.pi * 700.3 / 4096 * t) + 1500 * np.cos(2 * np.pi * 1333.7 / 4096 * t + 1)
    x[5000:5100] = 8191 * np.sign(rng.normal(size=100))          # 満杯の区間（語幅の上限の近く）
    x = np.clip(np.round(x), -8192, 8191).astype(np.int64)
    w16 = (x << 2) | rng.integers(0, 4, NSAMP)                    # ADC の 16 bit 語（低位 2 bit は >>> 2 で捨てる）
    w16 &= 0xFFFF
    np.save(os.path.join(d, "x14.npy"), x)
    with open(os.path.join(d, "x.hex"), "w") as fp:
        fp.write("\n".join(f"{v:04x}" for v in w16) + "\n")
    print(f"入力: {NSAMP} サンプル → {d}/x.hex")


def check(d, ks, posctl):
    x = np.load(os.path.join(d, "x14.npy"))
    des = F.prepare(WM.design(60.0, WM.RIPPLE_PP))
    cfg = dict(F.DEFAULT)
    bad = 0
    for k in ks:
        for gap in (0, 1):
            fn = os.path.join(d, f"y_k{k}_g{gap}.txt")
            got = np.loadtxt(fn, dtype=np.int64, ndmin=2)
            cnt = {}
            yr, yi = F.pfb_fixed(x, k, des, cfg, cnt)
            n = min(len(yr), len(got))
            ok_len = len(got) == len(yr)
            neq = int(np.count_nonzero((got[:n, 0] != yr[:n]) | (got[:n, 1] != yi[:n])))
            first = int(np.flatnonzero((got[:n, 0] != yr[:n]) | (got[:n, 1] != yi[:n]))[0]) if neq else -1
            st = "OK" if (neq == 0 and ok_len and not cnt) else "NG"
            print(f"  k {k:2d} GAP {gap}: フレーム RTL {len(got)} / 模型 {len(yr)}、不一致 {neq}"
                  f"{'（最初 m = %d: RTL %s / 模型 %s）' % (first, tuple(got[first]), (yr[first], yi[first])) if neq else ''}"
                  f"、模型の飽和 {cnt or 0} → {st}")
            bad += st == "NG"
    if posctl:
        if bad:
            print(f"陽性対照: {bad} 件が一致しなかった → 結果: 全部通過")
            return 0
        print("陽性対照: 一致してしまった → 結果: 失敗（照合が効いていない）")
        return 1
    print("結果: 全部通過" if bad == 0 else f"結果: 失敗 {bad} 件")
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        gen(sys.argv[2])
    else:
        posctl = os.environ.get("SIM_PFB_POSCTL", "0") == "1"
        sys.exit(check(sys.argv[2], [int(v) for v in sys.argv[3:]], posctl))
