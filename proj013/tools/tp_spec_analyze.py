#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""--tp --tp-save-spec の .tp.npz から、total power の揺れがどの ch から来ているかを分ける（proj013）。

    python3 tools/tp_spec_analyze.py PREFIX.tp.npz [--top 20]

ダンプ d・ch k のスペクトル S[d, k]（SHIFT を戻した |X_k|²）について、パーセバルの重み（DC は 1、ほかは 2）を掛けた
T[d] = Σ_k w_k S[d, k] の揺れを、ch ごとの寄与 c_k = w_k cov(S_k, T) / var(T) に分ける（Σ_k c_k = 1）。
  - c_k の上位の ch と、k·fs/8（ch 0・1024・2048・3072）の ± 1 ch の寄与の合計
  - 残り（広い帯域）の寄与
  - ナイキスト（スナップショットの X_4096）は T に入らない。ダンプの外にあるので、別に q の平均と揺れを出す
**寄与は共分散なので負にもなる**（その ch が全体と逆に動く）。上位は |c_k| で並べる。
"""
import sys
import numpy as np

FS_MHZ, NFFT = 4096.0, 8192


def if_mhz(k, zone=2):
    fa = k * FS_MHZ / NFFT
    return FS_MHZ - fa if zone == 2 else fa


def main():
    path = sys.argv[1]
    top = int(sys.argv[sys.argv.index("--top") + 1]) if "--top" in sys.argv else 20
    z = np.load(path, allow_pickle=True)
    labels = [k[:-5] for k in z.files if k.endswith("_spec")]
    for lb in labels:
        S = z[f"{lb}_spec"]
        nd = S.shape[0]
        print(f"==== {lb}: ダンプ {nd} 個 ====")
        if nd < 10:
            print("  ダンプが 10 個に満たない")
            continue
        w = np.full(S.shape[1], 2.0)
        w[0] = 1.0
        T = (S * w).sum(axis=1)
        vt = T.var()
        c = w * ((S - S.mean(0)) * (T - T.mean())[:, None]).mean(0) / vt
        spur = np.zeros(S.shape[1], bool)
        spur[[0, 1]] = True
        for ch in (1024, 2048, 3072):
            spur[ch - 1:ch + 2] = True
        print(f"  全体の揺れ（ダンプごと）{np.sqrt(vt) / T.mean():.2e} / 理想 {np.sqrt(2.0 / (NFFT * 50000)):.2e}（N_ACC 50000 として）")
        print(f"  寄与: k·fs/8 の ch（DC・1024・2048・3072 ± 1）{c[spur].sum():+.3f} / それ以外 {c[~spur].sum():+.3f}")
        # k·fs/8 の ch を除いた残りの揺れ（寄与は共分散なので、残りの揺れそのものを別に出す）
        R = (S[:, ~spur] * w[~spur]).sum(axis=1)
        print(f"  k·fs/8 の ch を除いた残り: 電力の {R.mean() / T.mean():.3f}・揺れ {R.std() / R.mean():.2e}（理想 {np.sqrt(2.0 / (NFFT * 50000)):.2e}。"
              f"残りの帯域が狭いと理想は大きくなる）")
        order = np.argsort(-np.abs(c))
        cum = np.cumsum(c[order])
        for n in (1, 8, 64, 512):
            print(f"    上位 {n:4d} ch の寄与の合計 {cum[n - 1]:+.3f}")
        print(f"  上位 {top} ch（|c_k| の順）:")
        print("      ch    IF [MHz]   寄与     電力の割合   揺れ（その ch の相対）")
        pm = S.mean(0)
        for k in order[:top]:
            tag = " ← k·fs/8" if spur[k] else ""
            print(f"    {k:5d}  {if_mhz(k):9.2f}  {c[k]:+.4f}   {w[k] * pm[k] / T.mean():.2e}    {S[:, k].std() / max(pm[k], 1e-30):.2e}{tag}")
        if f"{lb}_snap" in z.files:
            x = z[f"{lb}_snap"].astype(np.int64) >> 2
            e = (x * x).sum(axis=1).astype(np.float64)
            xn = (x[:, 0::2].sum(axis=1) - x[:, 1::2].sum(axis=1)).astype(np.float64)
            q = xn ** 2 / (NFFT * e)
            # 比の平均と、平均の比（DC がフレームごとに大きく動くと e と |X_4096|² が一緒に動き、2 つが食い違う）
            print(f"  ナイキスト: 比の平均 {q.mean():.3e} / 平均の比 {np.mean(xn ** 2) / (NFFT * e.mean()):.3e}")
            if f"{lb}_dump_S" in z.files:
                pass
            print(f"  ナイキスト（1 フレームずつ）: q の平均 {q.mean():.2e}・標準偏差 {q.std():.2e}（白色雑音だけなら平均 {1 / NFFT:.1e}、"
                  f"標準偏差も同じ程度）/ X_4096 の符号付きの平均 {np.mean(xn / np.sqrt(NFFT * e)):+.3f}（安定した線なら 0 から離れる）")
        print()

    # ---- ch 間の比（1 ms の total power）----
    # 同じ入力を分配したとき、入力側の揺れ（雑音そのもの・雑音源やアンプの利得）は比で消え、ADC ごとの利得の揺れと
    # ADC 自身の雑音だけが残る。開始のずれ（数十フレーム）は TP_N より短いので個の番号で揃える
    labs = [lb for lb in ("ADC_A", "ADC_B", "ADC_C", "ADC_D") if f"{lb}_sum" in z.files]
    if len(labs) > 1:
        tp_n = int(z["tp_n"])
        p = {lb: z[f"{lb}_sum"] / (NFFT * z[f"{lb}_nfr"]) for lb in labs}
        n = min(len(v) for v in p.values())
        print(f"==== ch 間の比（1 区切り = {tp_n * 2e-3:g} ms、{n} 個）====")
        print("  相関（1 区切り）: " + " / ".join(f"{a}-{b} {np.corrcoef(p[a][:n], p[b][:n])[0, 1]:+.3f}"
                                            for i, a in enumerate(labs) for b in labs[i + 1:]))
        for i, a in enumerate(labs):
            for b in labs[i + 1:]:
                r = p[a][:n] / p[b][:n]
                r = r / r.mean() - 1.0
                xa, xb = p[a][:n] / p[a][:n].mean() - 1.0, p[b][:n] / p[b][:n].mean() - 1.0
                rows = []
                for m in (1, 10, 100, 1000):
                    nb = n // m
                    if nb < 10:
                        break
                    f = lambda v: v[:nb * m].reshape(nb, m).mean(axis=1).std()
                    rows.append(f"{m * tp_n * 2e-3:g} ms 比 {f(r):.2e}（{a} 単独 {f(xa):.2e}・{b} 単独 {f(xb):.2e}）")
                print(f"  {a} / {b}: " + " / ".join(rows))
        print("  読み: 比の揺れが単独の揺れより十分小さければ、揺れの大部分は 4 本に共通（入力側）。同じ程度なら ADC ごと")


if __name__ == "__main__":
    main()
