#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""--tp --out の .tp.npz（ダンプごとの 128 帯の電力 {ch}_dump_band）から、帯ごとに混信の出たダンプを数える（proj013）。

    python3 tools/tp_rfi.py A.tp.npz B.tp.npz ... [--nsig 8] [--ch ADC_A]

1 帯 = 32 ch = 16 MHz、1 ダンプ = 100 ms。帯ごとに、ダンプの電力を頑健な中央値と σ（中央絶対偏差 × 1.4826）で測り、
+nsig σ を越えたダンプを「混信あり」と数える。**--tp-save-spec が要らない**ので、10 分・1 時間の記録を比べられる。
名前を付けた帯（下の TAGS）は別に並べる。IF はゾーン 2（IF = 4096 − ch × 0.5 MHz）、ゾーン 1 の周波数も出す。
"""
import sys
import numpy as np

NB, CPB = 128, 32
# 名前を付けた混信（ch の範囲）。2026-09-29 の実機で見つけたもの
TAGS = [("800 MHz 帯（ゾーン 1 の 815〜845 MHz）", 1630, 1690),
        ("BLE 広告 2480 MHz", 3228, 3236), ("BLE 広告 2426 MHz", 3336, 3344), ("BLE 広告 2402 MHz", 3384, 3392),
        ("Wi-Fi 1 ch 2412 MHz", 3350, 3385)]


def main():
    argv = sys.argv[1:]
    nsig = float(argv[argv.index("--nsig") + 1]) if "--nsig" in argv else 8.0
    only = argv[argv.index("--ch") + 1] if "--ch" in argv else None
    skip = {i + 1 for i, a in enumerate(argv) if a in ("--nsig", "--ch")}
    files = [a for i, a in enumerate(argv) if not a.startswith("--") and i not in skip]
    summary = []
    for path in files:
        z = np.load(path, allow_pickle=True)
        labs = [lb for lb in ("ADC_A", "ADC_B", "ADC_C", "ADC_D") if f"{lb}_dump_band" in z.files and (only is None or lb == only)]
        if not labs:
            print(f"{path}: {'{ch}'}_dump_band が無い（この版より前の spectrometer.py で取った記録）")
            continue
        nd = min(len(z[f"{lb}_dump_band"]) for lb in labs)
        minutes = nd * 0.1 / 60
        print(f"==== {path}: ダンプ {nd} 個（{minutes:.1f} 分）・+{nsig:g} σ ====")
        hit = {}
        for lb in labs:
            B = z[f"{lb}_dump_band"][:nd].astype(np.float64)
            B = B / B.sum(axis=1, keepdims=True).mean()          # 全電力の平均で割る（帯の割合）
            med = np.median(B, axis=0)
            sig = 1.4826 * np.median(np.abs(B - med), axis=0)
            hit[lb] = B > med + nsig * np.maximum(sig, 1e-12)
        H = np.sum([hit[lb] for lb in labs], axis=0) >= max(1, len(labs) // 2)   # 半分以上の ch で越えたダンプ
        cnt = H.sum(axis=0)
        order = np.argsort(-cnt)
        print("  帯ごとの「混信あり」のダンプ（半分以上の ch で越えた）上位:")
        for b in order[:8]:
            if cnt[b] == 0:
                break
            c0 = b * CPB
            print(f"    帯 {b:3d}（ch {c0}〜{c0 + CPB - 1}・IF {4096 - (c0 + CPB) * 0.5:.0f}〜{4096 - c0 * 0.5:.0f} MHz・"
                  f"ゾーン 1 {c0 * 0.5:.0f}〜{(c0 + CPB) * 0.5:.0f} MHz）: {cnt[b]} 個（{cnt[b] / nd * 100:.2f} %）")
        row = [path, minutes]
        for name, a_, b_ in TAGS:
            bs = sorted(set(range(a_ // CPB, (b_ - 1) // CPB + 1)))
            n = int(np.any(H[:, bs], axis=1).sum())
            row.append(n)
            print(f"  {name}（帯 {bs[0]}〜{bs[-1]}）: {n} 個（{n / nd * 100:.2f} %・{n / minutes:.1f} 個/分）")
        summary.append(row)
    print()
    print("==== まとめ（混信ありのダンプの数・1 分あたり）====")
    print("  " + " " * 34 + " ".join(f"{t[0][:10]:>12s}" for t in TAGS))
    for r in summary:
        print(f"  {r[0]:34s}" + " ".join(f"{n:5d}（{n / r[1]:4.1f}/分）" for n in r[2:]))


if __name__ == "__main__":
    main()
