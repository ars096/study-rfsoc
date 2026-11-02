#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""ADR 0025 の TP の dBm の較正ファイル（ボードごと）の試験。PL なし（s45cal の照らし・adopt）。

    python3 test_tpcal.py            # 結果: 全部通過 / 不合格
陽性対照: 別のボード・ボードの印の無い前の形・ADC の道の違う bit・印の読めないボードでは使わないこと。道の決まらない前の形は adopt しないこと。
"""
import json
import os
import sys
import tempfile

import s45cal
import timebase as TB

BOARD = dict(id="mac:" + ":".join(["0a"] * 6), src="試験")
OTHER = "mac:" + ":".join(["02"] * 6)
ADC = {a: dict(k_db=-69.3, provisional=False, valid_dbfs=[-47.0, -7.0], date="2026-10-06") for a in "ABCD"}
IDS_WIDE = dict(win="02020000", adc="02010101", time="02010102", board=BOARD["id"])
IDS_FINE = dict(IDS_WIDE, adc="02020301")


def main():
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"{'OK' if cond else 'NG'}: {name}{'（' + detail + '）' if detail else ''}")

    with tempfile.TemporaryDirectory() as td:
        legacy = os.path.join(td, "old.json")
        json.dump(dict(version=1, bits=[[2, 3], [1, 1]], unit="dBm at ADC input (SMA)", adc=ADC), open(legacy, "w"))
        r, why = s45cal.check(s45cal.load(legacy), IDS_WIDE)
        check("陽性対照: ボードの印の無い前の形は使わない", not r, why)

        dst = os.path.join(td, "etc", "tp_cal.json")
        s45cal.adopt(legacy, dst, BOARD)
        cal = s45cal.load(dst)
        check("adopt: ボードの印・ADC の道 1・測った bit を残す", cal["board"]["id"] == BOARD["id"] and cal["adc_path"] == 1
              and cal["measured_on_bits"] == [[2, 3], [1, 1]] and "bits" not in cal)
        check("adopt: K は変えない", all(cal["adc"][a]["k_db"] == ADC[a]["k_db"] for a in "ABCD"))
        s45cal.adopt(legacy, dst, BOARD)
        check("adopt: 前のファイルを残す", len([x for x in os.listdir(os.path.dirname(dst)) if x.startswith("tp_cal.json.")]) == 1)

        check("このボード・Wide → 使う", s45cal.check(cal, IDS_WIDE)[0])
        check("このボード・Fine → 使う", s45cal.check(cal, IDS_FINE)[0])
        check("このボード・CAL に無い開発中の bit → 使う（道は共通）", s45cal.check(cal, dict(IDS_WIDE, adc="03070101"))[0])
        check("偽物 → 照らさない", s45cal.check(cal, dict(win="fake", adc="fake", board="fake"))[0])
        r, why = s45cal.check(cal, dict(IDS_WIDE, board=OTHER))
        check("陽性対照: 別のボード → 使わない", not r, why)
        r, why = s45cal.check(cal, dict(IDS_WIDE, board="-"))
        check("陽性対照: ボードの印が読めない → 使わない", not r, why)
        TB.ADC_PATH[(7, 1)] = 2
        try:
            r, why = s45cal.check(cal, dict(IDS_WIDE, adc="02070101"))
            check("陽性対照: ADC の道が違う bit → 使わない", not r, why)
            mixed = os.path.join(td, "mixed.json")
            json.dump(dict(version=1, bits=[[2, 3], [7, 1]], adc=ADC), open(mixed, "w"))
            try:
                s45cal.adopt(mixed, os.path.join(td, "x.json"), BOARD)
                check("陽性対照: 道が 1 つに決まらない前の形は adopt しない", False)
            except ValueError as e:
                check("陽性対照: 道が 1 つに決まらない前の形は adopt しない", True, str(e))
        finally:
            del TB.ADC_PATH[(7, 1)]

        os.environ["YATSUGATAKE_TP_CAL"] = dst
        check("置き場所は環境変数で替えられる", s45cal.tp_cal_path() == dst)
        del os.environ["YATSUGATAKE_TP_CAL"]
        check("既定の置き場所はボードの /etc/yatsugatake", s45cal.tp_cal_path() == "/etc/yatsugatake/tp_cal.json")

    print(f"結果: {'全部通過' if ok else '不合格'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
