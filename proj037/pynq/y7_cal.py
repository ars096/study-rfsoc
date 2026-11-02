#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-7 — 載っている .bit のまま、ADC_A の背景の較正を止める / 戻す / 係数を読む（ボードの上で、README Y-7）

  python3 y7_cal.py --bit proj037.bit freeze|unfreeze
  python3 y7_cal.py --bit proj037.bit coef <名>      # runs/y7_coef_<名>.json（1 s おいて 2 回読む）

止める・戻すは CalFreeze（DisableFreezePin = 1、PL のピンでなく道具が決める）。書いたら CalFrozen を読み返し、違えば exit 1。
係数は OCB1・OCB2・GCB・TSCB（0〜3）の Coeff0〜7。xrfdc の GetCalCoefficients の包みは引数が足りず呼べないので、
下の C の関数 XRFdc_GetCalCoefficients(inst, tile, block, cb, coeff*) を直接呼ぶ。ADC_A = タイル 2・ブロック 1。
"""
import argparse
import json
import sys
import time

TILE, BLOCK = 2, 1


def coef(xrfdc, r):
    out = []
    for cb in range(4):
        c = xrfdc._ffi.new("XRFdc_Calibration_Coefficients *")
        rc = xrfdc._lib.XRFdc_GetCalCoefficients(r._instance, TILE, BLOCK, cb, c)
        if rc != 0:
            raise RuntimeError(f"XRFdc_GetCalCoefficients(cb {cb}) が {rc}")
        out.append([int(getattr(c, f"Coeff{i}")) for i in range(8)])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bit", required=True)
    ap.add_argument("cmd", choices=("freeze", "unfreeze", "coef"))
    ap.add_argument("name", nargs="?")
    a = ap.parse_args()
    import xrfdc                                  # **Overlay() より前に import する**（VERSIONS.md）
    from pynq import Overlay
    r = Overlay(a.bit, download=False).rfdc
    blk = r.adc_tiles[TILE].blocks[BLOCK]
    if a.cmd == "coef":
        if not a.name:
            raise SystemExit("coef には名が要る")
        c0 = coef(xrfdc, r)
        time.sleep(1.0)
        c1 = coef(xrfdc, r)
        d = dict(name=a.name, freeze=blk.CalFreeze, mode=blk.CalibrationMode, c0=c0, c1=c1, same=c0 == c1)
        json.dump(d, open(f"runs/y7_coef_{a.name}.json", "w"), indent=1)
        print(f"{a.name}: CalFrozen {d['freeze']['CalFrozen']}・1 s で係数が{'動かない' if d['same'] else '動く'}"
              f"（{[cb for cb in range(4) if c0[cb] != c1[cb]]} が動く）")
        return
    want = 1 if a.cmd == "freeze" else 0
    blk.CalFreeze = {"CalFrozen": 0, "DisableFreezePin": 1, "FreezeCalibration": want}
    time.sleep(0.2)
    st = blk.CalFreeze
    print(f"{a.cmd}: {st}")
    if st["CalFrozen"] != want:
        print(f"ERROR: CalFrozen が {st['CalFrozen']}（{want} を求めた）")
        sys.exit(1)


if __name__ == "__main__":
    main()
