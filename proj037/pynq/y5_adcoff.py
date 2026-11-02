#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-5 — 載っている proj037.bit のまま、ADC_A 以外の ADC を実行時に止める / 戻す（ボードの上で、.bit は載せ直さない）

  python3 y5_adcoff.py read            # 読むだけ
  python3 y5_adcoff.py on|cd|b|a       # ON（全部）・cd（タイル 224 を止める）・b（ADC_B を落とす）・a（両方 = ADC_A だけ）

タイル 224（ADC_C・D）は adc_tiles[0].ShutDown() / StartUp()、ADC_B（タイル 226 / slice 0 = adc_tiles[2].blocks[0]）は PwrMode。
書いたら読み返し、求めた状態と違えば exit 1。ADC_A（adc_tiles[2].blocks[1]）には触らない。
"""
import json
import sys

WANT = {"on": (True, True), "cd": (False, True), "b": (True, False), "a": (False, False)}   # (タイル 224 が動く, ADC_B が動く)


def state(r):
    st = r.IPStatus["ADCTileStatus"]
    b = r.adc_tiles[2].blocks[0].PwrMode
    a = r.adc_tiles[2].blocks[1].PwrMode
    return dict(t224=st[0]["TileState"], t226=st[2]["TileState"], b_pwr=b["PwrMode"], a_pwr=a["PwrMode"])


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "read"
    if cmd != "read" and cmd not in WANT:
        raise SystemExit(__doc__)
    import xrfdc                                  # **Overlay() より前に import する**（VERSIONS.md）
    from pynq import Overlay
    ol = Overlay("proj037.bit", download=False)
    r = ol.rfdc
    s0 = state(r)
    if cmd != "read":
        cd_on, b_on = WANT[cmd]
        if cd_on != (s0["t224"] == 15):
            if cd_on:
                r.adc_tiles[0].StartUp()
            else:
                r.adc_tiles[0].ShutDown()
        if b_on != (s0["b_pwr"] == 1):
            r.adc_tiles[2].blocks[0].PwrMode = {"DisableIPControl": 0, "PwrMode": 1 if b_on else 0}
    s1 = state(r)
    print(json.dumps(dict(cmd=cmd, before=s0, after=s1)))
    if cmd != "read":
        ok = ((s1["t224"] == 15) == cd_on and (s1["b_pwr"] == 1) == b_on and s1["t226"] == 15 and s1["a_pwr"] == 1)
        if not ok:
            print(f"ERROR: 求めた状態（タイル 224 {'動' if cd_on else '止'}・ADC_B {'動' if b_on else '落'}）にならない")
            sys.exit(1)


if __name__ == "__main__":
    main()
