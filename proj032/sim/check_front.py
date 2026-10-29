#!/usr/bin/env python3
"""proj032 P-1 — spw_front の照合。頭の入口（front_c.log、粗い PFB の出口 24 bit・Q 8）から、M-3 の整数の模型
（model/win64_fixed.py の nco_table・nco_cs・fir_decim_int・rnd_shift・sat と runs/m0_coef.json の light・final）で ddcb の出口を作り、
front_y.log の窓ごとの列と bit 単位で照らす。

  python3 sim/check_front.py DIR
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import win64_fixed as WF  # noqa: E402

BS = {1: 0, 2: 0, 3: 1, 4: 1, 5: 2}


def model(yr, yi, dphi, ns, co, cnt):
    P, A = 14, (1 << 17) - 1
    m = np.arange(len(yr), dtype=np.uint64)
    th = (m * np.uint64(dphi)) & np.uint64(0xFFFFFFFF)
    addr = (th >> np.uint64(32 - P)).astype(np.int64)
    cq, sq = WF.nco_cs(addr, P, WF.nco_table(P, A))
    vr = WF.sat(WF.rnd_shift(yr * cq + yi * sq, 17), 24, cnt, "v")
    vi = WF.sat(WF.rnd_shift(yi * cq - yr * sq, 17), 24, cnt, "v")
    hl, hf, shl, shf = co["light"], co["final"], co["sh_light"], co["sh_final"]

    def hb(ar, ai, h, s, w, key):
        ne = 2 * (len(ar) // 2)
        return (WF.sat(WF.rnd_shift(WF.fir_decim_int(ar[:ne], h, 2), s), w, cnt, key),
                WF.sat(WF.rnd_shift(WF.fir_decim_int(ai[:ne], h, 2), s), w, cnt, key))

    if ns >= 2:
        vr, vi = hb(vr, vi, hl, shl, 24, "l1")
    sh = 4 - BS[ns]
    br, bi = WF.sat(WF.rnd_shift(vr, sh), 20, cnt, "b"), WF.sat(WF.rnd_shift(vi, sh), 20, cnt, "b")
    for j in range(1, ns):
        last = j == ns - 1
        br, bi = hb(br, bi, hf if last else hl, shf if last else shl, 20, "f" if last else "l%d" % (j + 1))
    if ns == 1:
        br, bi = hb(br, bi, hf, shf, 20, "f")
    return br, bi


def main(d):
    cfg = {}
    for l in open(os.path.join(d, "front_cfg.log")):
        w, ns, fl, wk, dp = map(int, l.split())
        cfg[w] = (ns, fl, wk, dp)
    H = len(cfg)
    c = np.loadtxt(os.path.join(d, "front_c.log"), dtype=np.int64)
    out = {w: [] for w in range(H)}
    for l in open(os.path.join(d, "front_y.log")):
        e, w, r, i = map(int, l.split())
        if cfg[w][1] != e and cfg[w][1] != 3:
            print("窓 %d が lane %d に出た（期待 %d）" % (w, e, cfg[w][1]))
        out[w].append((r, i))
    co = WF.load_coef()
    bad = 0
    for w in range(H):
        ns, fl, wk, dp = cfg[w]
        if fl == 3:                                  # 止める窓: 何も出ない
            print("窓 %2d（止める窓）: 出口 %d 個" % (w, len(out[w])))
            if out[w]:
                bad += 1
            continue
        cnt = {}
        er, ei = model(c[:, 2 * w], c[:, 2 * w + 1], dp, ns, co, cnt)
        got = np.array(out[w], dtype=np.int64).reshape(-1, 2)
        n = min(len(got), len(er))
        nb = int(np.count_nonzero((got[:n, 0] != er[:n]) | (got[:n, 1] != ei[:n])))
        rms = float(np.sqrt(np.mean(got[:n].astype(float) ** 2))) if n else 0.0
        print("窓 %2d（NS %d・lane %d・粗い ch %2d）: 照らした %5d 個（RTL %5d・模型 %5d）・不一致 %d・rms %.0f・模型の飽和 %s"
              % (w, ns, fl, wk, n, len(got), len(er), nb, rms, cnt or "0"))
        # RTL は管の中の遅れ（入口で 64 ビートほど）の分だけ少ない
        if nb or n < 200 or not 0 <= len(er) - len(got) <= 16:
            bad += 1
    print("結果: " + ("全部通過" if bad == 0 else "不合格 %d 窓" % bad))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
