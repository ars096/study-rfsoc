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
        # ---- 事象の間隔（周期があるか）----
        if len(ev2) >= 10:
            st = np.array([s_ for s_, _ in ev2])
            iv = np.diff(st) * tp_n * 2e-3                     # ms
            hist, edges = np.histogram(iv, bins=np.arange(0, min(iv.max(), 500) + 2, 1))
            top = np.argsort(-hist)[:5]
            print(f"  事象の間隔: 中央値 {np.median(iv):.1f} ms・最小 {iv.min():.0f} ms・最大 {iv.max():.0f} ms / "
                  f"多い間隔: " + " / ".join(f"{edges[i]:.0f} ms（{hist[i]} 回）" for i in top if hist[i] > 0))
            ln = np.array([l for _, l in ev2]) * tp_n * 2e-3
            print(f"  事象の長さ: " + " / ".join(f"{v:g} ms {np.sum(ln == v)} 回" for v in np.unique(ln)[:8]))
        # ---- スペクトルがあれば: 事象の多いダンプと少ないダンプの平均スペクトルの差（事象がどの ch にあるか）----
        lab0 = labs[0]
        if f"{lab0}_spec" in z.files and len(ev2) > 0:
            f0 = z[f"{lab0}_f0"][:n]
            S = z[f"{lab0}_spec"]
            sf0 = z[f"{lab0}_spec_f0"]
            nacc = int(z["nacc"])
            per = nacc // tp_n
            cnt = []
            for d0 in sf0:
                i0 = np.searchsorted(f0, d0)
                cnt.append(int(np.sum(k[i0:i0 + per] >= 2)) if i0 + per <= n and f0[i0] == d0 else -1)
            cnt = np.array(cnt)
            ok = cnt >= 0
            if ok.sum() >= 10 and np.any(cnt[ok] > 0) and np.any(cnt[ok] == 0):
                hi = S[ok & (cnt >= np.percentile(cnt[ok], 75)) & (cnt > 0)].mean(axis=0)
                lo = S[ok & (cnt == 0)].mean(axis=0)
                dlt = hi - lo
                w = np.full(S.shape[1], 2.0); w[0] = 1.0
                tot = (w * dlt).sum()
                o = np.argsort(-(w * dlt))
                cum = np.cumsum((w * dlt)[o]) / tot
                print(f"  {lab0} のスペクトル: 事象の多いダンプ（{int(np.sum(ok & (cnt >= np.percentile(cnt[ok], 75)) & (cnt > 0)))} 個）− 事象の無いダンプ（{int(np.sum(ok & (cnt == 0)))} 個）"
                      f" = 全電力の {tot / (w * lo).sum() * 100:+.2f} %")
                print(f"    その差の上位 8 ch が {cum[7] * 100:.0f} %・上位 64 ch が {cum[63] * 100:.0f} %・上位 512 ch が {cum[511] * 100:.0f} %"
                      f"（上位の数 ch に集まれば細い混信、512 ch でも小さければ帯域全体）")
                print("    上位: " + " / ".join(f"ch {c}（IF {4096 - c * 0.5:.1f}・ゾーン 1 {c * 0.5:.1f} MHz）{(w * dlt)[c] / tot * 100:.1f} %" for c in o[:6]))
                # 帯域を 8 つに分けた差の比（帯域全体が一様に上がるなら、どの帯も同じ比）
                band = [(w * dlt)[i * 512:(i + 1) * 512].sum() / max((w * lo)[i * 512:(i + 1) * 512].sum(), 1e-30) for i in range(8)]
                print("    帯域ごとの上がり（ch 0〜511, 512〜1023, …）: " + " ".join(f"{b_ * 100:+.2f}%" for b_ in band))
            else:
                print(f"  （スペクトルと事象の突き合わせができない: 照合できたダンプ {int(ok.sum())} 個）")
    print()
    print("==== まとめ（事象の回数 / 1 分あたり / 最大の強さ）====")
    for path in args:
        rr = [r for r in rows if r[0] == path]
        print(f"  {path:40s} " + " / ".join(f"{lb[-1]} {c:4d}（{r:.2f}/分・+{b * 100:.1f} %）" for _, lb, c, r, b in rr))


if __name__ == "__main__":
    main()
