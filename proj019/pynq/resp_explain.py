#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj014 — winresp.py の結果（PREFIX.resp.npz）で、模型より大きく出た点の「行き先の ch」が、ADC 側の線の周波数に当たるかを調べる。

  python3 resp_explain.py resp256.resp.npz [--margin 10] [--floor -60]

窓の外の CW で、実測が模型より --margin dB 以上大きく、かつ --floor dB より大きい点について、行き先の ch（f の側）に次の線が来るかを見る:
  - CW の n 次の高調波（n = 2〜5、ADC の非線形・SG の高調波）: n·f を fs で折り返したもの
  - ADC のインターリーブの線: ±n·f + j·fs/8（j = 1〜7）を折り返したもの（n = 1 は W-3 で見たもの）
  - 一致の幅は窓の ch 幅の 2 倍（CW を ch の中心に置いているので、線も ch の中心に来るはず）
どれにも当たらない点は「説明なし」として出す（窓のフィルタそのものを疑う点）
"""
import argparse
import sys

import numpy as np

FS = 4096.0


def fold(x):
    x = np.mod(x, FS)
    return np.minimum(x, FS - x)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("npz")
    p.add_argument("--margin", type=float, default=10.0)
    p.add_argument("--floor", type=float, default=-60.0)
    a = p.parse_args()
    d = np.load(a.npz)
    c, w = float(d["c"]), float(d["w"])
    dw = w / 4096
    sg_if = d["sg_if"]; f = 4096.0 - sg_if
    lev, det, mod, nu = d["lev_db"], d["detected"], d["model_db"], d["model_nu"]
    outside = np.abs(f - c) > 0.5 * w
    sel = outside & det & (lev > mod + a.margin) & (lev > a.floor)
    print(f"窓 c = {c}（IF {4096 - c}）・W = {w}。模型より {a.margin} dB 以上大きく {a.floor} dB を超えた点: {sel.sum()} / 窓の外 {outside.sum()}")
    nexp = 0
    for i in np.where(sel)[0]:
        fd = c + nu[i]                                   # 行き先の ch（f の側）
        hits = []
        for n in range(1, 6):
            if n >= 2 and abs(fold(n * f[i]) - fd) < 2 * dw:
                hits.append(f"{n} 次の高調波")
            for j in range(1, 8):
                for sgn in (1, -1):
                    if abs(fold(sgn * n * f[i] + j * FS / 8) - fd) < 2 * dw:
                        hits.append(f"インターリーブ {'+' if sgn > 0 else '−'}{n}f + {j}·fs/8")
        hits = sorted(set(hits))
        nexp += bool(hits)
        print(f"  SG IF {sg_if[i]:9.3f} → 行き先 IF {4096 - fd:9.3f}: 実測 {lev[i]:+6.1f} / 模型 {mod[i]:+6.1f} dB → "
              + (" / ".join(hits) if hits else "**説明なし**"))
    print(f"ADC 側の線で説明がつく点 {nexp} / {sel.sum()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
