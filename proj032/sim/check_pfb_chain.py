#!/usr/bin/env python3
"""proj032 P-5 — 鎖の中の粗い PFB（pfb64_core）を整数の模型（model/pfb64_fixed.py）と bit 単位で照らす。

  python3 sim/check_pfb_chain.py DIR      DIR に tb_front / tb_core の front_x.log・front_m.log・front_c.log・front_cfg.log

front_x.log: 粗い PFB の入口（rst の明けた後の valid なビート、16 × 16 bit、lane 0 が下位）
front_m.log: front_c.log の行ごとの粗い PFB のフレーム番号 m（rst の明けから数える）
front_c.log: 頭の入口 = 粗い PFB の出口（窓 w の re im、24 bit・Q 8）。front_cfg.log の WK が窓 w の粗い ch
判定: 全部の行・全部の窓で模型と一致、行の数 > 0、模型の巻き戻り 0。
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import pfb64_fixed as PF  # noqa: E402


def main(d):
    wk = [int(l.split()[3]) for l in open(os.path.join(d, "front_cfg.log")) if l.strip()]
    xs = []
    for l in open(os.path.join(d, "front_x.log")):
        l = l.strip()
        if len(l) == 64:                   # 止められた sim の最後の行は書きかけのことがある
            xs += [int(l[4 * (15 - j):4 * (16 - j)], 16) for j in range(16)]
    x = np.array(xs, dtype=np.int64)
    x = np.where(x >= 32768, x - 65536, x)
    m = np.loadtxt(os.path.join(d, "front_m.log"), dtype=np.int64, ndmin=1)
    c = np.loadtxt(os.path.join(d, "front_c.log"), dtype=np.int64, ndmin=2)
    n = min(len(m), c.shape[0])            # 記録の最後の行は書きかけのことがある
    m, c = m[:n], c[:n]
    cnt = {}
    yr, yi = PF.pfb64_fixed(x, wk, cnt)
    ok = n > 0
    use = m < yr.shape[0]
    nu = int(np.count_nonzero(~use))
    m, c = m[use], c[use]
    print(f"入口 {len(x) // 16} ビート → 模型のフレーム {yr.shape[0]}・照らす行 {len(m)}（m {m.min() if len(m) else '-'}..{m.max() if len(m) else '-'}、入口の記録の外 {nu}）")
    for w, k in enumerate(wk):
        bad = int(np.count_nonzero((c[:, 2 * w] != yr[m, w]) | (c[:, 2 * w + 1] != yi[m, w])))
        print(f"窓 {w:2d}（k {k:2d}）: 不一致 {bad}")
        ok &= bad == 0
    wr = {k: v for k, v in cnt.items() if k.startswith("wrap_")}
    print(f"模型の飽和 {cnt}・巻き戻り {wr}")
    ok &= not wr and len(m) > 0
    print("結果: " + ("全部通過" if ok else "不合格"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
