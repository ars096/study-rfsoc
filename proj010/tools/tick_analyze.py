#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""`spectrometer.py --tick ... --save X.npz` の記録を読み、全 ch の和の揺れの出どころを切り分ける。

    python3 tools/tick_analyze.py tick_pps.npz      # numpy だけ。ボードでも Mac でも走る

見るもの（2026-09-19 の初回: 揺れが期待の 110 倍で、PPS の縁が埋もれた）:
  1. 畳み込み（エポック畳み込み）: 1 秒周期で畳んで平均する。60 周期なら雑音は 1/√60 になり、
     縁が 1 ダンプに乗っていればそこだけ飛び出す。**外れの判定より約 8 倍感度が高い**
  2. 揺れの周波数: ダンプの並び（10 Hz 標本）の電力スペクトル。1 Hz とその倍数なら PPS 由来
  3. ch 間の相関: var(全 ch の和) / Σ var(各 ch)。1 なら ch ごとに独立（雑音）、ch 数に近ければ
     全 ch が一緒に動いている（利得・較正・広帯域の干渉）
  4. どの ch が揺れているか: 隣との差で見た σ/μ を ch ごとに出し、期待 1/√(Δν·τ) との比が大きい順
  5. 帯域ごと: 8 分割した帯域の和の揺れ
  6. 静かな ch だけで 1〜3 をやり直す: 揺れの大きい ch（期待比 > 1.5）と電力の高い ch（中央値の 2 倍超）を外す。
     初回（2026-09-19）は ch 間の相関が 2.1 しかなく、**和の揺れは少数の ch（fs/8 の倍数と 45〜100 MHz の折り返し）が
     作っていた**ので、それを外せば PPS の縁が見えるはず、という予言を確かめる
  7. 共通の利得の揺れ: 静かな ch の和の揺れ c が全 ch 共通なら、ch ごとの揺れは √(期待² + c²)。
     各ダンプを静かな ch の和で割ると ch ごとの揺れが期待（1.0 倍）に戻るかを見る
  8. 外れたダンプの中身: 全 ch の和が跳ねたダンプで、超過が全 ch に薄く広がるか（利得・較正）、
     特定の帯域に固まるか（電波の混入）。帯域はゾーン 2 の IF とゾーン 1 に置いたときの周波数の両方で出す
"""
import sys
import numpy as np

FS, NFFT = 4096e6, 8192
DF = FS / NFFT
T_FRAME = NFFT / FS


def main(path):
    d = np.load(path)
    spec = d["spec"].astype(np.float64)          # [dump, ch]
    nacc = int(d["nacc"])
    tau = nacc * T_FRAME
    nd, nch = spec.shape
    sel = slice(50, nch - 50)
    s = spec[:, sel]
    tot = s.sum(axis=1)
    per = int(round(1 / tau))
    print(f"{path}: {nd} ダンプ × τ {tau * 1e3:.1f} ms（{nd * tau:.0f} s）/ 1 秒 = {per} ダンプ")

    # ---- 1. 畳み込み ----
    ncyc = nd // per
    fold = tot[:ncyc * per].reshape(ncyc, per)
    fold = fold / np.median(fold)
    prof = fold.mean(axis=0) - 1
    err = fold.std(axis=0).mean() / np.sqrt(ncyc)
    print(f"\n1. 1 秒で畳んだ平均（{ncyc} 周期、1 点の誤差 {err:.1e}）")
    for i, v in enumerate(prof):
        bar = "#" * int(min(60, max(0, v / err * 2)))
        print(f"   位相 {i:>2}: {v:+.2e}（{v / err:+5.1f} σ）{bar}")

    # ---- 2. 揺れの周波数 ----
    x = tot / tot.mean() - 1
    x = x - np.polyval(np.polyfit(np.arange(nd), x, 1), np.arange(nd))
    ps = np.abs(np.fft.rfft(x)) ** 2
    f = np.fft.rfftfreq(nd, tau)
    top = np.argsort(ps[1:])[::-1][:8] + 1
    print("\n2. 全 ch の和の揺れの周波数（直線の傾きを除いた後、強い順）")
    for i in top:
        print(f"   {f[i]:6.3f} Hz  相対 {ps[i] / ps[1:].mean():6.1f} 倍")

    # ---- 3. ch 間の相関 ----
    dd = np.diff(s, axis=0)
    r = dd.sum(axis=1).var() / dd.var(axis=0).sum()
    print(f"\n3. var(和の差) / Σ var(各 ch の差) = {r:.1f}（1 = ch ごとに独立 / {s.shape[1]} = 全 ch が一緒に動く）")

    # ---- 4. どの ch が揺れているか ----
    mu = s.mean(axis=0)
    rel = dd.std(axis=0) / mu / np.sqrt(2)
    want = 1 / np.sqrt(DF * tau)
    ratio = rel / want
    print(f"\n4. ch ごとの揺れ（隣との差）/ 期待 {want:.2e}: 中央値 {np.median(ratio):.2f} 倍、"
          f"上位 1 % {np.percentile(ratio, 99):.2f} 倍")
    idx = np.argsort(ratio)[::-1][:10]
    for i in idx:
        k = i + 50
        print(f"   ch {k:>4}（IF {FS / 1e6 - k * DF / 1e6:8.2f} MHz）{ratio[i]:7.2f} 倍 / "
              f"平均の電力 {mu[i] / np.median(mu):.2f} × 中央値")

    # ---- 5. 帯域ごと ----
    print("\n5. 帯域を 8 分割した和の揺れ（隣との差、期待比）")
    edges = np.linspace(0, s.shape[1], 9).astype(int)
    for a, b in zip(edges[:-1], edges[1:]):
        t = s[:, a:b].sum(axis=1)
        w = 1 / np.sqrt(DF * (b - a) * tau)
        v = np.diff(t).std() / t.mean() / np.sqrt(2)
        print(f"   ch {a + 50:>4}–{b + 49:>4}: {v:.2e}（期待 {w:.2e}、{v / w:6.1f} 倍）")

    # ---- 6. 静かな ch だけで ----
    quiet = (ratio < 1.5) & (mu < 2 * np.median(mu))
    q = s[:, quiet]
    qt = q.sum(axis=1)
    w = 1 / np.sqrt(DF * quiet.sum() * tau)
    v = np.diff(qt).std() / qt.mean() / np.sqrt(2)
    print(f"\n6. 静かな ch だけ（{quiet.sum()} / {len(quiet)} ch）: 和の揺れ（隣との差）{v:.2e}（期待 {w:.2e}、{v / w:.1f} 倍）")
    print(f"   ch ごとの揺れの分布（期待比）: 10 % {np.percentile(ratio[quiet], 10):.2f} / 50 % "
          f"{np.median(ratio[quiet]):.2f} / 90 % {np.percentile(ratio[quiet], 90):.2f}")
    fq = qt[:ncyc * per].reshape(ncyc, per)
    fq = fq / np.median(fq)
    pq = fq.mean(axis=0) - 1
    eq = fq.std(axis=0).mean() / np.sqrt(ncyc)
    print(f"   1 秒で畳んだ平均（1 点の誤差 {eq:.1e}）")
    for i, val in enumerate(pq):
        bar = "#" * int(min(60, max(0, val / eq * 2)))
        print(f"   位相 {i:>2}: {val:+.2e}（{val / eq:+5.1f} σ）{bar}")
    # 各ダンプを前後の中央値で割った残りの外れ（PPS の縁は 1 ダンプだけ持ち上げる）
    base = np.array([np.median(qt[max(0, i - 5):i + 6]) for i in range(nd)])
    res = qt / base - 1
    sig = 1.4826 * np.median(np.abs(res - np.median(res)))
    big = np.argsort(res)[::-1][:12]
    print(f"   前後の中央値からの超過が大きいダンプ（σ {sig:.1e}）: " +
          ", ".join(f"{i}({i % per}) {res[i] / sig:+.0f}σ" for i in sorted(big)))
    print("   （括弧は 1 秒の中の位相。PPS の縁なら位相がそろい、10 ダンプおきに並ぶ）")

    # ---- 7. 共通の利得の揺れを除く ----
    # 2026-09-19 の 2 回目: 静かな ch の和が期待の 36.6 倍揺れ、ch ごとは一様に 1.20 倍だった。
    # 和の揺れ c（相対）が全 ch 共通の利得の揺れなら、ch ごとの揺れは √(want² + c²) になり、
    # 各ダンプを静かな ch の和で割れば ch ごとの揺れは期待どおり（1.0 倍）に戻るはず
    c = v
    print(f"\n7. 共通の利得の揺れ c = {c:.2e}（静かな ch の和の隣との差）")
    print(f"   c から予言する ch ごとの揺れ: √(1 + (c/期待)²) = {np.sqrt(1 + (c / want) ** 2):.3f} 倍"
          f"（実測の中央値 {np.median(ratio[quiet]):.3f} 倍）")
    g = qt / qt.mean()
    n = q / g[:, None]
    dn = np.diff(n, axis=0)
    rn = dn.std(axis=0) / n.mean(axis=0) / np.sqrt(2) / want
    print(f"   各ダンプを静かな ch の和で割った後の ch ごとの揺れ（期待比）: 10 % {np.percentile(rn, 10):.3f} / "
          f"50 % {np.median(rn):.3f} / 90 % {np.percentile(rn, 90):.3f}")
    xq = g - 1
    xq = xq - np.polyval(np.polyfit(np.arange(nd), xq, 1), np.arange(nd))
    pq2 = np.abs(np.fft.rfft(xq)) ** 2
    topq = np.argsort(pq2[1:])[::-1][:6] + 1
    print("   共通の利得の揺れの周波数（強い順）: " +
          ", ".join(f"{f[i]:.3f} Hz ×{pq2[i] / pq2[1:].mean():.1f}" for i in topq))
    print(f"   共通の利得の揺れの幅: 全体の σ {g.std():.2e} / 最大−最小 {g.max() - g.min():.2e}")

    # ---- 8. 外れたダンプはどの ch が持ち上げたか ----
    # 2026-09-24、ADC_B を 50 Ω 終端にしたら全 ch の和が 1 ダンプで +4〜13 % 跳ねる事象が 4 秒に固まって出た。
    # 広帯域（利得・較正）なら超過は全 ch に薄く広がり、電波の混入なら特定の帯域に固まる
    base_t = np.array([np.median(tot[max(0, i - 5):i + 6]) for i in range(nd)])
    rt = tot / base_t - 1
    st = 1.4826 * np.median(np.abs(rt - np.median(rt)))
    ev = [i for i in np.argsort(rt)[::-1][:8] if rt[i] > 5 * st]
    print(f"\n8. 外れたダンプの超過の中身（全 ch の和で 5 σ 超、大きい順に最大 8 個。σ {st:.1e}）")
    if not ev:
        print("   なし")
    if "sat" in d.files:
        sat = d["sat"]
        ns = int((sat > 0).sum())
        print(f"   SAT（18 bit に飽和した ch × フレーム）> 0 のダンプ: {ns} / {nd} 個、合計 {int(sat.sum())}。"
              f"うち上の事象: {int(sum(sat[i] > 0 for i in ev))} / {len(ev)} 個")
    exs = []
    for i in ev:
        lo, hi = max(0, i - 5), min(nd, i + 6)
        ref = np.median(s[lo:hi], axis=0)
        ex = s[i] - ref                               # 超過の電力 [ch]
        exs.append(ex)
        tot_ex = ex.sum()
        o = np.argsort(ex)[::-1]
        c90 = np.searchsorted(np.cumsum(ex[o]) / tot_ex, 0.9) + 1
        band = [ex[a:b].sum() / tot_ex for a, b in zip(edges[:-1], edges[1:])]
        sat_i = f" / SAT {int(d['sat'][i])}" if "sat" in d.files else ""
        print(f"   ダンプ {i}（{rt[i] / st:+.0f} σ, +{rt[i] * 100:.1f} %{sat_i}）: 超過の 90 % が {c90} ch に集中 / "
              "8 帯域の割合 " + " ".join(f"{b * 100:3.0f}" for b in band))
    if exs:
        m = np.mean(exs, axis=0)
        mu_ref = np.median(s, axis=0)
        o = np.argsort(m)[::-1][:12]
        print("   事象を平均した超過の上位 ch（ゾーン 2 の IF / ゾーン 1 に置いたときの周波数 / 超過÷平時の電力）:")
        for j in sorted(o):
            k = j + 50
            print(f"     ch {k:>4}  IF {FS / 1e6 - k * DF / 1e6:8.2f} MHz / {k * DF / 1e6:7.2f} MHz  {m[j] / mu_ref[j]:7.3f}")
        # 超過が連続した ch の塊（上位 12 ch が 1 本の線か、帯域を持つか）
        hot = m > 0.2 * m.max()
        runs, a = [], None
        for j, h in enumerate(np.append(hot, False)):
            if h and a is None:
                a = j
            elif not h and a is not None:
                runs.append((a, j - 1)); a = None
        runs.sort(key=lambda r: -m[r[0]:r[1] + 1].sum())
        print("   超過の塊（最大値の 20 % 超が続く範囲、超過の多い順に 6 個）:")
        for a, b in runs[:6]:
            ka, kb = a + 50, b + 50
            print(f"     ch {ka:>4}–{kb:>4}（{kb - ka + 1:>3} ch）IF {FS / 1e6 - kb * DF / 1e6:8.2f}–{FS / 1e6 - ka * DF / 1e6:8.2f} MHz"
                  f" / {ka * DF / 1e6:7.2f}–{kb * DF / 1e6:7.2f} MHz  超過の {m[a:b + 1].sum() / m.sum() * 100:4.1f} %")


if __name__ == "__main__":
    main(sys.argv[1])
