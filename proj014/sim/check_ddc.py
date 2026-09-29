#!/usr/bin/env python3
"""proj014 — ddc_core の単体の sim の照合（make sim-ddc）。

  python3 check_ddc.py gen DIR       入力を作る: x（雑音 + CW + 満杯の区間）→ pfb_fixed（k = 5）→ y を pfb_core の出力の並びで DIR/y.txt に
  python3 check_ddc.py cases         照合する組（NS DPHI）を 1 行ずつ出す（Makefile が回す）
  python3 check_ddc.py check DIR     DIR/z_*.txt を ddc_fixed と bit 単位で照合

判定: 全出力の実部・虚部が一致・出力の数が模型と同じ・飽和 0。陽性対照（SIM_DDC_POSCTL=1）: RTL の NCO の位相を 1 番地ずらす → 一致しないこと
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import win_fixed as F  # noqa: E402
import win_model as WM  # noqa: E402

NSAMP = 16 * 16384
K = 5
# (NS, d [MHz])。d = 64 は粗い ch の境目（Δ = 2^29、番地の下位が 0）、−37.8123… は格子の外（位相の下位 bit まで使う）
CASES = [(ns, d) for ns in range(1, 7) for d in (64.0, -37.81234567)]


def dphi_of(d):
    return F.nco_step(d)[0]


def gen(dd):
    rng = np.random.default_rng(15)
    t = np.arange(NSAMP)
    x = rng.normal(0, 1500, NSAMP)
    x += 2500 * np.cos(2 * np.pi * (K * 128 + 20.37) / 4096 * t) + 800 * np.cos(2 * np.pi * (K * 128 - 50.1) / 4096 * t)
    x[100000:100400] = 8191 * np.sign(np.cos(2 * np.pi * K * 128 / 4096 * t[100000:100400]))
    x = np.clip(np.round(x), -8192, 8191).astype(np.int64)
    des = F.prepare(WM.design(60.0, WM.RIPPLE_PP))
    yr, yi = F.pfb_fixed(x, K, des, dict(F.DEFAULT), {})
    np.save(os.path.join(dd, "y.npy"), np.stack([yr, yi]))
    nb = (len(yr) - 1) // 2 + 1
    with open(os.path.join(dd, "y.txt"), "w") as fp:
        fp.write(f"0 0 0 1 {yr[0]} {yi[0]}\n")                       # 最初のビート: y0 は m = −1（ok でない）
        for b in range(1, nb):
            fp.write(f"1 {yr[2*b-1]} {yi[2*b-1]} 1 {yr[2*b]} {yi[2*b]}\n")
    print(f"入力: y {len(yr)} 個 → {nb} ビート（{dd}/y.txt）")


def cases():
    for ns, d in CASES:
        print(ns, dphi_of(d))


def check(dd, posctl):
    y = np.load(os.path.join(dd, "y.npy"))
    nb = (y.shape[1] - 1) // 2 + 1
    # RTL に届くのは y[0 .. 2nb − 2]。組にまとめ直すので最後の偶数番目（相手のいない 1 個）は NCO に入らない → 偶数個で切る
    ne = 2 * ((2 * nb - 1) // 2)
    yr, yi = y[0][:ne], y[1][:ne]
    des = F.prepare(WM.design(60.0, WM.RIPPLE_PP))
    cfg = dict(F.DEFAULT)
    bad = 0
    for ns, d in CASES:
        dp = dphi_of(d)
        cnt = {}
        zr, zi = F.ddc_fixed(yr, yi, dp, ns, des, cfg, cnt)
        for gap in (0, 1):
            got = np.loadtxt(os.path.join(dd, f"z_ns{ns}_d{dp}_g{gap}.txt"), dtype=np.int64, ndmin=2)
            n = min(len(zr), len(got))
            neq = int(np.count_nonzero((got[:n, 0] != zr[:n]) | (got[:n, 1] != zi[:n])))
            ok_len = len(got) == len(zr)
            st = "OK" if (neq == 0 and ok_len and not cnt) else "NG"
            extra = ""
            if neq:
                f0 = int(np.flatnonzero((got[:n, 0] != zr[:n]) | (got[:n, 1] != zi[:n]))[0])
                extra = f"（最初 {f0}: RTL {tuple(int(v) for v in got[f0])} / 模型 {(int(zr[f0]), int(zi[f0]))}）"
            print(f"  NS {ns}（{WM.R0 / 2 ** ns:5.0f} MHz）d {d:+10.5f} GAP {gap}: 出力 RTL {len(got)} / 模型 {len(zr)}、"
                  f"不一致 {neq}{extra}、模型の飽和 {cnt or 0} → {st}")
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
    cmd = sys.argv[1]
    if cmd == "gen":
        gen(sys.argv[2])
    elif cmd == "cases":
        cases()
    else:
        sys.exit(check(sys.argv[2], os.environ.get("SIM_DDC_POSCTL", "0") == "1"))
