#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj027 4d-y — 1 つの Overlay の中で、コア 0 とコア 3 の RAW を交互に使って F-2 の値（縁がコアに入った T − スタンプ）を測り、コアの間の差を見る。
widef2.py の open_board・open_raw・measure をそのまま使う（測り方は widef2 の (a) と同じ）。Overlay を載せ直すと ADC ごとに ≒ 1 ビート跳ねるので
（README の 4d-x）、別々の widef2 の回どうしでは比べられない。配線 P・root・specd を止めてから:

    python3 f2pair.py --clkin 0 --ref 10 --adc 0,1,2,3 --rounds 3 --out f2_27pair

1 回の値は 5 試行の中央値。判定: ADC ごとに、同じ巡の (コア 3 − コア 0) の差の中央値が |差| ≦ 0.1 ビート
"""
import argparse
import json
import sys
import time

import numpy as np

import widef2 as F
from timebase import TimeCore, Timebase

log = F.log


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default="proj031.bit")
    p.add_argument("--clkin", default="stock")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--path", default="trig", choices=("trig", "comp"))
    p.add_argument("--adc", default="0,1,2,3")
    p.add_argument("--cores", default="0,3")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--tol", type=float, default=0.1)
    p.add_argument("--out", default=None)
    a = p.parse_args()
    cs = [int(x) for x in a.cores.split(",")]
    ol = F.open_board(a)
    raws = {}
    for c in cs:
        cores, tmm, raws[c] = F.open_raw(ol, c)
    tc = TimeCore(tmm)
    tc.configure(src=a.path, tol=1)
    tb = Timebase(tc, path=a.path)
    anc = tb.anchor()
    log(f"錨: UTC {anc['utc_sec']} 秒 = スタンプ {anc['stamp']}（EPOCH {anc['epoch']}）・RAW のコア {cs}")
    wms = [c.m for c in cores]
    val = {}                                   # (adc, 巡, コア) → (中央値, 試行の値)
    for adc in [int(x) for x in a.adc.split(",")]:
        for r in range(a.rounds):
            for c in (cs if r % 2 == 0 else cs[::-1]):
                res = F.measure(tc, tb, raws[c], wms, a.path, adc, a.n)
                offs = [x["off"] for x in res if x["snr"] >= 20]
                med = float(np.median(offs)) if len(offs) == a.n else None
                val[(adc, r, c)] = (med, offs)
                log(f"  ADC_{'ABCD'[adc]} 巡 {r} コア {c}: 中央値 {med if med is None else f'{med:+.2f}'} ビート（試行 {' '.join(f'{x:+.2f}' for x in offs)}）")
    ng = 0
    out = {}
    log(f"---- 判定: 同じ巡の (コア {cs[1]} − コア {cs[0]}) の差の中央値が |差| ≦ {a.tol} ビート")
    for adc in [int(x) for x in a.adc.split(",")]:
        d = [val[(adc, r, cs[1])][0] - val[(adc, r, cs[0])][0] for r in range(a.rounds)
             if val[(adc, r, cs[0])][0] is not None and val[(adc, r, cs[1])][0] is not None]
        dm = float(np.median(d)) if len(d) == a.rounds else None
        ok = dm is not None and abs(dm) <= a.tol
        ng += not ok
        out[str(adc)] = dict(diff=d, diff_med=dm, ok=ok,
                             vals={f"{r}_{c}": val[(adc, r, c)] for r in range(a.rounds) for c in cs})
        log(f"  ADC_{'ABCD'[adc]}: 巡ごとの差 {' '.join(f'{x:+.2f}' for x in d)} → 中央値 {dm if dm is None else f'{dm:+.2f}'}: {'OK' if ok else 'NG'}")
    if a.out:
        json.dump(dict(adc=out, cores=cs, bitfile=a.bitfile, t=time.time()), open(a.out + ".pair.json", "w"), indent=1)
        log(f"記録: {a.out}.pair.json")
    log("結果: 全部通過" if ng == 0 else f"結果: 不合格（{ng}）")
    sys.exit(1 if ng else 0)


if __name__ == "__main__":
    main()
