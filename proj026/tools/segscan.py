#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj026 — .s45 を START ごとの区間に分け、区間ごとに 800 MHz 帯の超過（窓 0）と、窓 1（IF 2304〜2560 MHz）の帯ごとの超過を並べる。
1 つのファイルに START が 2 回あるとき（受けを同じ名前で 2 回回した）や、通話が 800 MHz 帯以外で送っていたかを見るため。
    python3 tools/segscan.py --ref runs/c1_off1.s45 runs/c2b_on1.s45 ...
線を除く印は --ref（通話なしの記録）の中央値で作る（区間の自分の中央値で作ると、半分以上のダンプに出た混信を線として除いてしまう）。
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import s45proto as P  # noqa: E402
import phone_rfi as R  # noqa: E402


def segments(path):
    segs, cur = [], None
    with open(path, "rb") as fh:
        while True:
            h = fh.read(P.HDR.size)
            if len(h) < P.HDR.size:
                break
            rt, pl, crc, seq = P.parse_header(h)
            ver = P.header_ver(h)
            b = fh.read(pl)
            if rt == P.T_EVENT and b"\"START\"" in b[:40]:
                cur = {}
                segs.append(cur)
            elif rt == P.T_SPEC and cur is not None:
                d = P.decode(rt, b, ver)
                sc = 4.0 ** d["shift"] * 4.0 ** (4 - d["g"]) / 2.0 ** 31
                v = (d["data"].astype(np.float64) / d["nacc"] - 2.0 / 3.0) * sc
                o = cur.setdefault((d["adc"], d["win"]), dict(S=[], t=[], if_mhz=d["if_mhz"], ns=d["ns"]))
                o["S"].append(v)
                o["t"].append(d["utc_ns"])
    return segs


def ref_masks(path):
    seg = segments(path)[0]
    out = {}
    for a in range(4):
        o = seg[(a, 0)]
        S = np.array(o["S"])
        f = R.freq_axis(o["if_mhz"], o["ns"], S.shape[1])
        out[a] = R.make_mask(f, np.median(S, axis=0), o["if_mhz"], detect=True)[0]
    return out


def main():
    argv = sys.argv[1:]
    ref = argv[argv.index("--ref") + 1]
    argv = [a for i, a in enumerate(argv) if a != "--ref" and (i == 0 or argv[i - 1] != "--ref")]
    masks = ref_masks(ref)
    for path in argv:
        for i, seg in enumerate(segments(path)):
            out = []
            t = np.array(seg[(0, 0)]["t"])
            t = t[t > 0]
            import datetime
            ts = datetime.datetime.utcfromtimestamp(t[0] / 1e9).strftime("%H:%M:%S") if len(t) else "-"
            x4, w1 = [], []
            for a in range(4):
                o = seg.get((a, 0))
                if not o:
                    continue
                S = np.array(o["S"])
                f = R.freq_axis(o["if_mhz"], o["ns"], S.shape[1])
                ok = masks[a]
                x, _, _ = R.excess(S, f, ok, R.BANDS["800"])
                x4.append(x)
                o1 = seg.get((a, 1))
                if o1:
                    S1 = np.array(o1["S"])
                    f1 = R.freq_axis(o1["if_mhz"], o1["ns"], S1.shape[1])
                    m = S1.mean(axis=0)
                    # 16 MHz ごとの帯の平均を、窓の中央値で割る（窓 1 の中のどこに出たか）
                    edges = np.arange(2304 + 16, 2560 - 16 + 1, 16)
                    bands = [m[(f1 >= lo) & (f1 < lo + 16)].mean() for lo in edges[:-1]]
                    w1.append(np.array(bands) / np.median(bands) - 1)
            x4 = np.mean(x4, axis=0)
            line = (f"{os.path.basename(path)} 区間 {i}（{ts}〜、{len(x4)} ダンプ）: 800 の超過（4 ADC の平均）中央値 {100 * np.median(x4):+.2f} %・"
                    f"99 % 点 {100 * np.percentile(x4, 99):+.1f} %・> 5 % のダンプ {int((x4 > 0.05).sum())}")
            if w1:
                w = np.mean(w1, axis=0)
                k = int(np.argmax(w))
                line += f" ｜ 窓 1 の最大の帯 IF {2320 + 16 * k}〜{2336 + 16 * k} MHz {100 * w[k]:+.2f} %"
            print(line)


if __name__ == "__main__":
    main()
