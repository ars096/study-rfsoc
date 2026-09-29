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
        # 128 帯の電力: {ch}_dump_band（proj013 の 2026-09-29 以降）か、無ければ --tp-save-spec のスペクトル {ch}_spec から作る
        bands = {}
        for lb in ("ADC_A", "ADC_B", "ADC_C", "ADC_D"):
            if only is not None and lb != only:
                continue
            if f"{lb}_dump_band" in z.files:
                bands[lb] = z[f"{lb}_dump_band"]
            elif f"{lb}_spec" in z.files:
                S = z[f"{lb}_spec"]
                bands[lb] = S.reshape(S.shape[0], NB, CPB).sum(axis=2)
        labs = list(bands)
        if not labs:
            print(f"{path}: 帯の電力もスペクトルも無い（--tp-save-spec なしの、帯を残す前の記録）")
            continue
        src = "dump_band" if f"{labs[0]}_dump_band" in z.files else "スペクトルから作った"
        nd = min(len(bands[lb]) for lb in labs)
        minutes = nd * 0.1 / 60
        print(f"==== {path}: ダンプ {nd} 個（{minutes:.1f} 分）・+{nsig:g} σ・帯は {src} ====")
        hit = {}
        for lb in labs:
            B = np.asarray(bands[lb][:nd], dtype=np.float64)
            # **利得の漂いを除く**（2026-09-29、10 分の記録で全部の帯が「混信あり」になった誤りを直した）:
            #   1. ダンプごとに、帯の中央値で割る（帯域全体が一緒に動く分 = 利得が消え、一部の帯だけの上がり = 混信が残る）
            #   2. 帯ごとに、50 ダンプ（5 s）ずつの中央値で割る（帯の形のゆっくりした変化を除く）
            R = B / np.median(B, axis=1, keepdims=True)
            w = 50
            nb_ = nd // w
            base = np.empty_like(R)
            for j in range(nb_ + (1 if nd % w else 0)):
                sl = slice(j * w, min(nd, (j + 1) * w))
                base[sl] = np.median(R[sl], axis=0)
            X = R / base - 1.0
            sig = 1.4826 * np.median(np.abs(X - np.median(X, axis=0)), axis=0)
            hit[lb] = X > nsig * np.maximum(sig, 1e-12)
            wide = np.mean(hit[lb].sum(axis=1) > NB // 10) * 100
            print(f"  {lb}: 帯ごとの σ（中央値）{np.median(sig):.1e} / 1 割以上の帯が同時に越えたダンプ {wide:.2f} %（多ければ利得の漂いが残っている）")
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
        lev = []
        for name, a_, b_ in TAGS:
            bs = sorted(set(range(a_ // CPB, (b_ - 1) // CPB + 1)))
            n = int(np.any(H[:, bs], axis=1).sum())
            row.append(n)
            # **強さそのもの**: 名前の帯の電力を、両隣 2 帯ずつ（名前の帯を除く）の平均と比べた超過。
            # 続いて出る混信（通話中の携帯電話など）は 5 s の中央値に吸収されて上の数えに出ないので、こちらで見る
            nb_ = [c for c in (bs[0] - 2, bs[0] - 1, bs[-1] + 1, bs[-1] + 2) if 0 <= c < NB]
            ex = []
            for lb in labs:
                B = np.asarray(bands[lb][:nd], dtype=np.float64)
                ex.append(B[:, bs].sum(axis=1) / (B[:, nb_].mean(axis=1) * len(bs)) - 1.0)
            ex = np.mean(ex, axis=0)
            lev.append((float(np.median(ex)), float(np.percentile(ex, 99))))
            print(f"  {name}（帯 {bs[0]}〜{bs[-1]}）: {n} 個（{n / nd * 100:.2f} %・{n / minutes:.1f} 個/分）/ "
                  f"両隣に対する超過 中央値 {lev[-1][0] * 100:+.2f} %・99 % 点 {lev[-1][1] * 100:+.2f} %")
        row.append(lev)
        summary.append(row)
    print()
    print("==== まとめ（混信ありのダンプの数・1 分あたり）====")
    print("  " + " " * 34 + " ".join(f"{t[0][:10]:>12s}" for t in TAGS))
    for r in summary:
        print(f"  {r[0]:34s}" + " ".join(f"{n:5d}（{n / r[1]:4.1f}/分）" for n in r[2:-1]))
    print()
    print("==== まとめ（両隣の帯に対する超過: 中央値 / 99 % 点。帯の形は BPF で決まるので、同じ入力の記録どうしで比べる）====")
    print("  " + " " * 34 + " ".join(f"{t[0][:10]:>16s}" for t in TAGS))
    for r in summary:
        print(f"  {r[0]:34s}" + " ".join(f"{m * 100:+6.2f}/{q * 100:+6.2f} %" for m, q in r[-1]))


if __name__ == "__main__":
    main()
