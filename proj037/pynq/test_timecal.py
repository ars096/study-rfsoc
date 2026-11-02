#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""ADR 0023 のボードの時刻の較正ファイルの試験。PL なし（timecal の合成・書き読み・timebase の選び方）。

    python3 test_timecal.py            # 結果: 全部通過 / 不合格
陽性対照: 別のボードの印・ADC → コアの道の違う bit・1 回の線を通らない記録・ばらつきの大きい記録は、それぞれ落ちるか暫定になること。
"""
import json
import os
import sys
import tempfile

import timebase as TB
import timecal as TC

IF_WIDE = "02010102"                      # BIT_KIND 1・BIT_REV 1
BOARD = dict(id="mac:" + ":".join(["0a"] * 6), src="試験")


def rec(dirn, name, means, std=0.05, p_seen=0, n=5, if_id=IF_WIDE):
    adc = {str(i): dict(mean=m, std=std, n=n, n_trial=5, p_seen=p_seen) for i, m in enumerate(means)}
    p = os.path.join(dirn, name + ".f2.json")
    json.dump(dict(adc=adc, bitfile="proj023.bit", if_id=if_id, t=0), open(p, "w"))
    return p


def main():
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"{'OK' if cond else 'NG'}: {name}{'（' + detail + '）' if detail else ''}")

    with tempfile.TemporaryDirectory() as td:
        # 合成: 5 回、Overlay ごとに 4 ADC そろって動く（M6 の形）
        shifts = [0.0, 1.18, 0.4, -0.3, 0.9]
        base = [17.9, 17.95, 17.85, 17.87]
        ps = [rec(td, f"load{k}", [b + s for b in base]) for k, s in enumerate(shifts)]
        d, good = TC.combine(ps)
        check("合成が通る", good and d is not None)
        m0 = sum(base[0] + s for s in shifts) / len(shifts)
        check("M = 回の平均（ns）", abs(d["adc_to_core_ns"]["0"] - m0 * TC.NS_PER_BEAT) < 0.01, f"{d['adc_to_core_ns']['0']}")
        check("bound_ns = max(5, ばらつき ½ ＋ 2 の切り上げ)", d["bound_ns"] == max(5.0, float(-(-(1.48 / 2 * 3.90625 + 2.0) // 1))), f"{d['bound_ns']}")
        check("形 (a)・道 1・測った bit (1, 1)", d["pps_det_ns"] == 0.0 and d["adc_path"] == 1
              and (d["measured_on"]["bit_kind"], d["measured_on"]["bit_rev"]) == (1, 1))

        # 陽性対照: 1 回の線・ばらつき・bit の混在
        bad1 = ps[:4] + [rec(td, "bad_p", base, p_seen=1)]
        check("陽性対照: (p) で縁が見えた回があれば落ちる", not TC.combine(bad1)[1])
        bad2 = ps[:4] + [rec(td, "bad_s", [b + 2.5 for b in base])]
        check("陽性対照: ばらつき > 2 ビートなら落ちる", not TC.combine(bad2)[1])
        bad3 = ps[:4] + [rec(td, "bad_id", base, if_id="02020302")]
        check("陽性対照: 回によって bit が違えば落ちる", not TC.combine(bad3)[1])

        # 書き読み
        path = os.path.join(td, "etc", "time_cal.json")
        TC.write_cal(d, path, BOARD)
        TC.write_cal(d, path, BOARD)                      # 2 回目は前のを残す
        check("前の較正ファイルを残す", len([x for x in os.listdir(os.path.dirname(path)) if x.startswith("time_cal.json.")]) == 1)
        c = TB.load_time_cal(path)
        check("読める・ADC の鍵は int", sorted(c["adc_to_core_ns"]) == [0, 1, 2, 3])

        # 選び方
        cal, st, _ = TB.select_cal((1, 1), c, BOARD)
        check("このボード → board", st == "board" and cal["adc_to_core_ns"][0] == c["adc_to_core_ns"][0])
        cal, st, _ = TB.select_cal((2, 3), c, BOARD)
        check("道の同じ別の bit（Fine）にも board", st == "board")
        cal, st, _ = TB.select_cal((7, 1), c, BOARD)
        check("CAL に無い開発中の bit にも board（道は共通とみなす）", st == "board")
        cal, st, why = TB.select_cal((1, 1), c, dict(id="mac:" + ":".join(["02"] * 6)))
        check("陽性対照: 別のボード → 暫定", st == "provisional" and cal["adc_to_core_ns"] == TB.CAL[(1, 1)]["adc_to_core_ns"], why)
        cal, st, why = TB.select_cal((1, 1), c, None)
        check("陽性対照: ボードの印が読めない → 暫定", st == "provisional", why)
        TB.ADC_PATH[(7, 1)] = 2
        try:
            cal, st, why = TB.select_cal((7, 1), c, BOARD)
            check("陽性対照: ADC → コアの道が違う bit → 暫定（(1, 1) の値）", st == "provisional"
                  and cal["adc_to_core_ns"] == TB.CAL[(1, 1)]["adc_to_core_ns"], why)
        finally:
            del TB.ADC_PATH[(7, 1)]
        cal, st, _ = TB.select_cal((2, 3), None, BOARD)
        check("較正ファイルが無い → 暫定（その bit の開発の値）", st == "provisional" and cal["adc_to_core_ns"] == TB.CAL[(2, 3)]["adc_to_core_ns"])
        check("暫定は source に「暫定」", cal["source"].startswith("暫定"))

        # 形の誤り
        json.dump(dict(version=1, kind="yatsugatake-time-cal", adc_to_core_ns={"0": 1}, bound_ns=5, adc_path=1, board=BOARD),
                  open(path, "w"))
        try:
            TB.load_time_cal(path)
            check("陽性対照: ADC がそろわないファイルは読まない", False)
        except ValueError as e:
            check("陽性対照: ADC がそろわないファイルは読まない", True, str(e))

    print(f"結果: {'全部通過' if ok else '不合格'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
