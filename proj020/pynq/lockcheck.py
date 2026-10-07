#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — LMX2594 の出力の強さ（OUTA・OUTB の PWR）を下げたときの、タイル PLL のロックの余裕。

櫛（n × 163.84 MHz）は LMX の出力 491.52 MHz の経路から出ていて、PWR 31 → 10 で 2〜7 dB 下がった（README）。
どこまで下げてよいかを決めるため、PWR ごとに「クロックを設定 → LMX を書き直す → ビットストリームを読む → タイル PLL の
ロックを n 秒見張る」を繰り返す。**specd を止めてから**ボードで実行する（同じ PL を使う）。

    sudo -E $(which python3) lockcheck.py --clkin 0 --ref 10 --pwr 31,20,10,5,3,1,0 --watch 20 --out lock1

判定（PWR ごと）:
  - 起動直後に 2 つのタイル（224: ADC_C・D / 226: ADC_A・B）とも PLLLockStatus = 2（ロック）か
  - 見張りの間（--watch 秒、1 秒ごと）に一度でも 2 以外になったか（落ちたら、その PWR は使えない）
  - 4 本のブロックの SamplingFreq が 4.096 GHz か
ロックが外れた（2 以外）PWR より下は試さずに止める（--keep-going で続ける）。
結果は 1 行 1 PWR で <out>.lock.jsonl に。**運転に使う PWR は、ロックが外れた一番高い値から十分（数段以上）上に取る**。
"""
import argparse
import json
import sys
import time

import extref
import spectrometer as S


def check(ol, tiles, watch):
    rf = ol.rfdc
    first = {t: int(rf.adc_tiles[t].PLLLockStatus) for t in tiles}
    fs = {}
    for lbl, t, b in S.CHANS:
        st = rf.adc_tiles[t].blocks[b].BlockStatus
        fs[lbl] = st.get("SamplingFreq")
    bad = {t: 0 for t in tiles}
    for _ in range(int(watch)):
        time.sleep(1.0)
        for t in tiles:
            if int(rf.adc_tiles[t].PLLLockStatus) != 2:
                bad[t] += 1
    return first, bad, fs


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default="proj020.bit")
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--pwr", default="31,20,10,5,3,1,0", help="試す PWR（0〜63、上から順に）")
    p.add_argument("--watch", type=float, default=20.0, help="ロックを見張る秒数（PWR ごと）")
    p.add_argument("--keep-going", action="store_true", help="ロックが外れても下の PWR を続ける")
    p.add_argument("--out", default="lock")
    a = p.parse_args()
    import xrfdc  # noqa: F401  Overlay() より前に import する（VERSIONS.md）
    from pynq import Overlay
    tiles = sorted({t for _, t, _ in S.CHANS})
    path = a.out + ".lock.jsonl"
    rows = []
    for pwr in [int(x) for x in a.pwr.split(",")]:
        S.setup_clocks(a.clkin, a.ref)
        info = extref.rewrite_lmx(16, pwr)
        t0 = time.time()
        try:
            ol = Overlay(a.bitfile)
            first, bad, fs = check(ol, tiles, a.watch)
            err = None
        except Exception as e:                      # noqa: BLE001
            first, bad, fs, err = {}, {}, {}, f"{type(e).__name__}: {e}"
        ok = err is None and all(v == 2 for v in first.values()) and not any(bad.values()) and \
            all(f is not None and abs(f - 4.096) < 1e-6 for f in fs.values())
        row = dict(pwr=pwr, ok=ok, lock_first={f"{224 + t}": v for t, v in first.items()},
                   lock_lost_s={f"{224 + t}": v for t, v in bad.items()}, fs_ghz=fs, watch_s=a.watch, err=err,
                   vco_mhz=info["vco_mhz"], t=t0)
        rows.append(row)
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
        S.log(f"PWR {pwr:2d}: {'ロック' if ok else '**だめ**'}  起動直後 {row['lock_first']}  見張り {a.watch:.0f} s で外れた秒数 {row['lock_lost_s']}"
              f"  fs {fs}" + (f"  {err}" if err else ""))
        if not ok and not a.keep_going:
            S.log("ロックが外れたので、ここより下は試さない（--keep-going で続ける）")
            break
    good = [r["pwr"] for r in rows if r["ok"]]
    S.log(f"ロックした PWR: {good}  → {path}")
    S.log("**最後に specd をいつもの設定（--lmx-pwr なし = 31）で起動し直すこと**")


if __name__ == "__main__":
    sys.exit(main())
