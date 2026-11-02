#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""時刻の較正の形 (b)（2026-10-21、study-rfsoc proj026）の試験。PL なし、numpy だけ。

T-2（F-2）で測れるのは M = adc_to_core − pps_det だけ。CAL を
  (a) pps_det_ns = 0、adc_to_core_ns = M
  (b) pps_det_ns = P（1PPS の入口の LPF の遅れ）、adc_to_core_ns = M + P
のどちらで書いても、**サンプルの時刻は同じ**でなければならない（引く量は M）。ビートの時刻（コアに入った時刻）は
(b) のほうが P だけ遅い（スタンプは本当の縁より pps_det 後に打たれる）。

    python3 test_cal_b.py            # 結果: 全部通過 / 不合格
陽性対照: 2026-10-21 より前の式（pps_det を引いていた）では (b) のサンプルの時刻が 2P ずれて落ちる（直す前に回して確かめた）。
"""
import sys
import types

import numpy as np

import s45acq as A
import timebase as TB

M = {0: 70.0, 1: 70.1, 2: 69.7, 3: 69.7}
P = 71.5
CAL_A = dict(pps_det_ns=0.0, adc_to_core_ns=dict(M), bound_ns=50, source="試験 (a)")
CAL_B = dict(pps_det_ns=P, adc_to_core_ns={k: v + P for k, v in M.items()}, bound_ns=50, source="試験 (b)")
ANCHOR = dict(utc_sec=1_792_557_829, stamp=1_488_900_165, epoch=1, count=0)


def make_tb(cal):
    tb = TB.Timebase.__new__(TB.Timebase)
    tb.cal = cal
    tb._anchor = dict(ANCHOR)
    tb.path = "trig"
    tb.check = lambda: None
    return tb


def main():
    ok = True

    def chk(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"{'OK' if cond else 'NG'}  {name}{('  ' + detail) if detail else ''}")

    ta, tb_ = make_tb(CAL_A), make_tb(CAL_B)
    beats = [ANCHOR["stamp"] + d for d in (0, 1, 255, 256_000_000, 1_000_000_007, -12345)]
    # 1. サンプルの時刻は (a) と (b) で同じ（丸めの 1 ns まで）
    for adc in range(4):
        d = [tb_.sample_utc_ns(b, adc=adc) - ta.sample_utc_ns(b, adc=adc) for b in beats]
        chk(f"timebase.sample_utc_ns: (b) − (a) = 0（ADC {adc}）", max(abs(x) for x in d) <= 1, f"差 {d}")
        dw = [tb_.sample_utc_ns(b, ns=3, adc=adc) - ta.sample_utc_ns(b, ns=3, adc=adc) for b in beats]
        chk(f"timebase.sample_utc_ns（窓 NS 3）: (b) − (a) = 0（ADC {adc}）", max(abs(x) for x in dw) <= 1, f"差 {dw}")
    # 2. ビートの時刻は (b) が P だけ遅い
    d = [tb_.beat_utc_ns(b) - ta.beat_utc_ns(b) for b in beats]
    chk(f"timebase.beat_utc_ns: (b) − (a) = +P（{P} ns）", all(abs(x - P) <= 1 for x in d), f"差 {d}")
    # 3. 取得の Clock（s45acq）も同じ式
    wd = dict(TB.WIN_DELAY_BEATS)
    ca, cb = A.Clock(ta, wd), A.Clock(tb_, wd)
    for adc in range(4):
        d = [cb.utc_ns(b, adc=adc) - ca.utc_ns(b, adc=adc) for b in beats]
        chk(f"s45acq.Clock.utc_ns: (b) − (a) = 0（ADC {adc}）", max(abs(x) for x in d) <= 1, f"差 {d}")
        e = [cb.utc_ns(b, adc=adc) - tb_.sample_utc_ns(b, adc=adc) for b in beats]
        chk(f"s45acq.Clock.utc_ns = timebase.sample_utc_ns（(b)、ADC {adc}）", max(abs(x) for x in e) <= 1, f"差 {e}")
        arr = cb.utc_ns_arr(np.array(beats, np.int64), adc=adc)
        f = [int(x) - cb.utc_ns(b, adc=adc) for x, b in zip(arr, beats)]
        chk(f"s45acq.Clock.utc_ns_arr = utc_ns（(b)、ADC {adc}）", max(abs(x) for x in f) <= 1, f"差 {f}")
    # 4. 逆の式: beat_of_utc_ns(beat_utc_ns(B)) = B（(a)・(b) とも）
    for name, t, c in (("(a)", ta, ca), ("(b)", tb_, cb)):
        r = [c.beat_of_utc_ns(t.beat_utc_ns(b)) - b for b in beats]
        chk(f"s45acq.Clock.beat_of_utc_ns は beat_utc_ns の逆 {name}", max(abs(x) for x in r) <= 1, f"差 {r}")
    print(f"結果: {'全部通過' if ok else '不合格'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
