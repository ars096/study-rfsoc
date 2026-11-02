#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — specd の SNAP（ADC の生サンプル 8192 個 = 2 µs）を取り、中身を確かめて .npz に残す。

    python3 s45snap.py --host <board> --adc ABCD --n 16 --every 20 --out snap1        # → snap1.snap.npz
    python3 s45snap.py --host <board> --adc A --n 4 --sg 3000.25                     # SG の線が 4096 − f に見えるか

確かめること（ADC ごと）:
  S-1 記録の間隔: dump_t の差がちょうど N_ACC × 512 ビート（every ms）、frame の差が N_ACC、k が 0, 1, …
  S-2 中身: 下位 2 bit が 0（16 bit のまま来ている）・振り切れ（|x14| ≧ 8191）の数・電力（dBFS）・尖度
  S-3 （--sg があれば）FFT の山が 4096 − f_sg MHz（第 2 ナイキスト）の ±0.5 MHz（1 ch）にあるか
  S-4 時刻: utc_ns が dump_t と同じ間隔で進むか（時刻を答えられないときは 0）
"""
import argparse
import math
import sys

import numpy as np

DBFS0 = 10 * math.log10(8192 ** 2 / 2)
FS = 4096.0


def check(x16, meta, every, sg=None):
    x14 = (x16 >> 2).astype(np.int16)
    out = {}
    dt = np.diff([m["dump_t"] for m in meta])
    nacc = int(round(every * 1e-3 / 2.0e-6))            # 1 フレーム = 2.000 µs
    out["S1_dt_ok"] = bool(np.all(dt == nacc * 512)) if len(dt) else None
    out["S1_frame_ok"] = bool(np.all(np.diff([m["frame"] for m in meta]) == nacc)) if len(dt) else None
    out["S1_k_ok"] = [m["k"] for m in meta] == list(range(len(meta)))
    out["S2_low2bits_zero"] = bool(np.all((x16 & 3) == 0))
    out["S2_clip"] = int(np.sum(np.abs(x14) >= 8191))
    xf = x14.astype(np.float64)
    p = float(np.mean(xf ** 2))
    out["S2_dbfs"] = 10 * math.log10(max(p, 1e-30)) - DBFS0
    c = xf - xf.mean()
    out["S2_kurtosis"] = float(np.mean(c ** 4) / np.mean(c ** 2) ** 2) if np.mean(c ** 2) > 0 else None
    out["S2_dc"] = float(xf.mean())
    utc = np.array([m["utc_ns"] for m in meta], np.int64)
    if len(utc) > 1 and np.all(utc > 0):
        out["S4_utc_step_ns"] = float(np.mean(np.diff(utc)))
        out["S4_ok"] = bool(abs(out["S4_utc_step_ns"] - nacc * 512 * 125 / 32) < 2)
    if sg is not None:
        X = np.mean(np.abs(np.fft.rfft(xf * np.hanning(xf.shape[1]), axis=1)) ** 2, axis=0)
        f = np.fft.rfftfreq(xf.shape[1], 1 / FS)
        pk = float(f[1 + np.argmax(X[1:])])
        want = FS - sg if sg > FS / 2 else sg
        out["S3_peak_mhz"] = pk
        out["S3_want_mhz"] = want
        out["S3_ok"] = abs(pk - want) <= FS / xf.shape[1]
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--ctrl-port", type=int, default=51000)
    p.add_argument("--data-port", type=int, default=51001)
    p.add_argument("--adc", default="ABCD")
    p.add_argument("--n", type=int, default=16)
    p.add_argument("--every", type=float, default=20.0, help="塊の間隔 [ms]")
    p.add_argument("--sg", type=float, default=None, help="SG の周波数 [MHz]（S-3 を見る）")
    p.add_argument("--out", default=None, help="<out>.snap.npz に 16 bit のまま残す")
    a = p.parse_args()
    from s45client import S45
    s = S45(a.host, a.ctrl_port, a.data_port)
    save = {}
    bad = 0
    try:
        print(s.cmd("ID"))
        for adc in a.adc.upper():
            x16, meta = s.snap(adc, n=a.n, every=a.every, x14=False)
            r = check(x16, meta, a.every, a.sg)
            ok = [v for k, v in r.items() if k.endswith("_ok") and v is not None]
            ok = all(ok) and r["S2_low2bits_zero"] and r["S1_k_ok"]
            bad += 0 if ok else 1
            print(f"ADC_{adc}: {'OK' if ok else 'NG'}  {a.n} 塊・{r['S2_dbfs']:+.2f} dBFS・尖度 {r['S2_kurtosis']:.3f}・DC {r['S2_dc']:+.2f}・"
                  f"振り切れ {r['S2_clip']}・間隔 {r['S1_dt_ok']}/{r['S1_frame_ok']}"
                  + (f"・UTC の刻み {r['S4_utc_step_ns']:.0f} ns" if "S4_utc_step_ns" in r else "・UTC なし")
                  + (f"・山 {r['S3_peak_mhz']:.2f} MHz（期待 {r['S3_want_mhz']:.2f}）" if "S3_peak_mhz" in r else ""))
            save[adc] = x16
            save[adc + "_dump_t"] = np.array([m["dump_t"] for m in meta], np.int64)
            save[adc + "_utc_ns"] = np.array([m["utc_ns"] for m in meta], np.int64)
            save[adc + "_frame"] = np.array([m["frame"] for m in meta], np.uint64)
        print("照合（specrecv と同じ）:", s.check())
    finally:
        s.close()
    if a.out:
        np.savez(a.out + ".snap.npz", every_ms=a.every, **save)
        print(f"→ {a.out}.snap.npz（16 bit のまま。14 bit は >> 2）")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
