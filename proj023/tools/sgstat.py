#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj023 H-2: SG のレベルを段階的に変え、各段で出力が設定どおりに出ているか（ALC・unleveled）を SCPI で読む。出力は最後に OFF
ボードで: python3 sgstat.py --sg HOST 3941.75 10 0 -5 -10 -20
:STAT:QUES:POW:COND? の bit 1 が unleveled（E8257D）。0 以外なら、その段のレベルは設定どおりに出ていない"""
import sys
import time
import argparse
import sg as SGM

p = argparse.ArgumentParser()
p.add_argument("--sg", default=None)
p.add_argument("freq", type=float)
p.add_argument("levels", type=float, nargs="+")
a = p.parse_args()
s = SGM.SG(a.sg)
try:
    s.set_freq_mhz(a.freq)
    s.set_output(True)
    for L in a.levels:
        s.set_dbm(L)
        time.sleep(0.5)
        out = []
        for q in (":POW:ALC?", ":STAT:QUES:POW:COND?", ":STAT:QUES:COND?", ":POW:ATT:AUTO?"):
            try:
                out.append(f"{q} {s.query(q).strip()}")
            except Exception as e:
                out.append(f"{q} （読めない: {e}）")
        errs = s.read_errors()
        print(f"{L:+6.1f} dBm: " + " / ".join(out) + (f" / エラー {errs}" if errs else ""))
finally:
    s.set_output(False)
    s.close()
