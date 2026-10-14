#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj021 手順 2-3c — s45proto v2 の確かめ（specd は --proto 2 で）

    python3 s45v2c.py --host <board> --n 50

1. fmt=both（同じ束を u64 と float32 の 2 つで送らせる）で n 束を取り、受けた記録の照合（specrecv と同じ）で
   組の数 = 8 窓 × n・float32 = u64 を最も近い float32 に丸めたもの（不一致 0）・差 ≦ 0.5 ulp を見る
2. utc_ns（v2 = 実効の区間の始まり、INTERFACE 5.2）:
   - 束の間隔がちょうど tint（±1 ns）
   - 窓ごとに e = utc_ns − dump_t·125/32 ＋ (D(NS) ＋ 1.5·L(NS))·125/32 を出し、同じ ADC の窓 0（NS 1）と窓 1（NS 6）で一致（±2 ns）
     （D(NS) は timebase.WIN_DELAY_BEATS。式どおりに D_eff を引いていれば、e は ADC だけで決まる）
   - 陽性対照: 1.5·L を足さない e' は窓 0 と窓 1 で 1.5·(L6 − L1)·125/32 = 768,000 ns − 24,000 ns ずれる
"""
import argparse
import sys

import numpy as np

import s45proto as P
import timebase as TB
from s45client import S45

NS_PER_BEAT = 125 / 32


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", required=True)
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--tint", type=float, default=0.04096)
    a = p.parse_args()
    s = S45(a.host)
    s.set(f"tint={a.tint} fmt=both " + " ".join(f"{x}0.bw=256 {x}1.bw=8" for x in "ABCD"))
    try:
        d = s.acquire(a.n)
    finally:
        try:
            s.wait_idle(10)
            s.set("fmt=f32")
        except Exception as e:  # noqa: BLE001
            print(f"NOTE: fmt を f32 に戻せなかった（{e}）")
    chk = s.check()
    ok = chk["f32_pairs"] >= 8 * (a.n - 1) and chk["f32_bad"] == 0 and chk["f32_maxulp"] <= 0.5 and chk["crc_bad"] == 0 \
        and chk["unexplained"] == 0 and chk["kgap"] == 0 and chk["tdev"] == 0
    print(f"照合: 組 {chk['f32_pairs']}・不一致 {chk['f32_bad']}・最大 {chk['f32_maxulp']} ulp・版 {chk['ver']}・"
          f"CRC {chk['crc_bad']}・説明のない欠け {chk['unexplained']}・kgap {chk['kgap']}・tdev {chk['tdev']}: {'OK' if ok else 'NG'}")
    tint_ns = round(a.tint * 1e9)
    for x in "ABCD":
        es, es0 = [], []
        base = None
        for w in (0, 1):
            m = d.meta(f"{x}{w}")
            if len(m) < 2 or not m["utc_ns"][0]:
                print(f"ADC_{x}{w}: utc_ns が無い（時刻を答えられない）"); ok = False; es.append(None); es0.append(None); continue
            step = np.diff(m["utc_ns"].astype(np.int64))
            ns = int(m["ns"][0])
            L = 4096 << (ns - 1)
            # 整数で引いてから float に（utc_ns ≒ 1.8e18 は float64 では 256 ns 刻みにしかならない。クラウドの偽物で 1 回目に見えた）
            ei = m["utc_ns"].astype(np.int64) - (m["dump_t"].astype(np.int64) * 125) // 32
            if base is None:
                base = int(ei[0])                       # ≒ 1.8e18 を引いてから float に（そのままでは 256 ns 刻み）
            e = (ei - base).astype(np.float64)
            es0.append(float(np.median(e)))
            e = e + (TB.WIN_DELAY_BEATS[ns] + 1.5 * L) * NS_PER_BEAT
            es.append(float(np.median(e)))
            good = bool(np.all(np.abs(step - tint_ns) <= 1)) and float(np.ptp(e)) <= 2
            ok &= good
            print(f"ADC_{x}{w}（NS {ns}）: 束の間隔 {int(step.min())}〜{int(step.max())} ns・e の幅 {np.ptp(e):.1f} ns: {'OK' if good else 'NG'}")
        if None not in es:
            de, de0 = es[0] - es[1], es0[0] - es0[1]
            good = abs(de) <= 2 and abs(de0) > 1000
            ok &= good
            print(f"ADC_{x}: e(窓 0) − e(窓 1) = {de:+.1f} ns（±2 ns であるべき）/ 1.5·L と D を足さないと {de0:+.0f} ns（陽性対照: ずれるべき）: "
                  f"{'OK' if good else 'NG'}")
    print(f"結果（2-3c の v2 の確かめ）: {'通過' if ok else '失敗'}")
    s.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
