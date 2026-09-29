#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""--tp --out の .tp.npz から、1 ms の total power だけで間欠的な混信の瞬間を数える（proj013）。

    python3 tools/tp_burst.py A.tp.npz B.tp.npz ...  [--nsig 8]

スペクトルを残さなくてよいので（--tp-save-spec は 60 秒まで）、10 分・1 時間の記録で混信の起きる率を比べられる。
  1. ch ごとに、1 区切り（1 ms）の電力を 500 区切り（0.5 s）ごとの中央値で割って、ゆっくりした漂いを除く
  2. 揺れの大きさを頑健に（中央絶対偏差 × 1.4826）見積もり、+nsig σ を越えた区切りを数える（上にだけ。混信は電力を足す）
  3. 続けて越えた区切りを 1 回の事象にまとめる。同じ区切りで 2 本以上が越えたものも数える（4 本に共通の入口か）
**混信の強さ（全電力の 0.3 〜 30 %）は 1 ms の揺れ（≒ 7e-4〜3e-3）の数倍〜数百倍**なので、total power だけで拾える。
nsig 8 のとき、ガウス雑音だけで越える区切りは 1 時間・4 本で 1e-8 程度（誤検出はほぼ無い）。
"""
import sys
import numpy as np

NFFT = 8192


def events(mask):
    """True が続く区間を (始まり, 長さ) で返す"""
    if not mask.any():
        return []
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    st = np.where(d == 1)[0]
    en = np.where(d == -1)[0]
    return list(zip(st, en - st))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    nsig = float(sys.argv[sys.argv.index("--nsig") + 1]) if "--nsig" in sys.argv else 8.0
    if "--nsig" in sys.argv:
        args = [a for a in args if a != sys.argv[sys.argv.index("--nsig") + 1]]
    rows = []
    for path in args:
        z = np.load(path, allow_pickle=True)
        tp_n = int(z["tp_n"])
        labs = [lb for lb in ("ADC_A", "ADC_B", "ADC_C", "ADC_D") if f"{lb}_sum" in z.files]
        n = min(len(z[f"{lb}_sum"]) for lb in labs)
        blk = 500
        nb = n // blk
        n = nb * blk
        minutes = n * tp_n * 2e-6 / 60.0
        over = {}
        print(f"==== {path}: {n} 区切り（{minutes:.2f} 分）・しきい値 +{nsig:g} σ ====")
        for lb in labs:
            p = (z[f"{lb}_sum"][:n] / (NFFT * z[f"{lb}_nfr"][:n])).astype(np.float64)
            base = np.median(p.reshape(nb, blk), axis=1).repeat(blk)
            x = p / base - 1.0
            sig = 1.4826 * np.median(np.abs(x - np.median(x)))
            m = x > nsig * sig
            ev = events(m)
            over[lb] = m
            big = max((x[s:s + l].max() for s, l in ev), default=0.0)
            print(f"  {lb}: σ {sig:.2e} / 越えた区切り {m.sum()} / 事象 {len(ev)} 回（{len(ev) / minutes:.2f} 回/分）/ "
                  f"最大 +{big * 100:.2f} %・最長 {max((l for _, l in ev), default=0) * tp_n * 2e-3:g} ms")
            rows.append((path, lb, len(ev), len(ev) / minutes, big))
        k = np.sum([over[lb] for lb in labs], axis=0)
        ev2 = events(k >= 2)
        print(f"  2 本以上が同じ区切りで越えた事象: {len(ev2)} 回（{len(ev2) / minutes:.2f} 回/分）/ 4 本とも: {len(events(k >= 4))} 回")
    print()
    print("==== まとめ（事象の回数 / 1 分あたり / 最大の強さ）====")
    for path in args:
        rr = [r for r in rows if r[0] == path]
        print(f"  {path:40s} " + " / ".join(f"{lb[-1]} {c:4d}（{r:.2f}/分・+{b * 100:.1f} %）" for _, lb, c, r, b in rr))


if __name__ == "__main__":
    main()
