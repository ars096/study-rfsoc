#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""連続したダンプの記録から、アラン分散とラジオメータ式の曲線を出す。

    python3 tools/allan.py noise1h                      # spectrometer.py --record の出力（接頭辞）
    python3 tools/allan.py tick_term.npz                # --tick --save / --ndump --save の .npz も読める
    python3 tools/allan.py noise1h --prebin 10 --plot noise1h_allan.png

**ダンプは隙間なく並ぶ**（二面で交互に積む。DUMP_F0 の間隔 = N_ACC）ので、連続した m 個を足したものは
m × τ0 で積分したものと同じ。N_ACC を変えて測り直さずに、1 本の記録から τ を振れる。

出す 4 種（どれも電力を ch ごとの平均で割った相対値、重なりありのアラン分散）:
  全電力        静かな ch の和。雑音源・増幅器・ADC の利得の揺れがそのまま入る。期待 1/(n·Δν·τ)
  ch ごと       ch ごとのアラン分散の中央値。期待 1/(Δν·τ)（ラジオメータ式）
  共通利得除く  各ダンプを「ch ごとの比の中央値」で割ってから ch ごと。期待 1/(Δν·τ)
  2 ch の差     P ch 離れた 2 ch の比の差（分光のアラン分散）。期待 2/(Δν·τ)
アラン分散は τ とともに 1/τ で下がり、揺れ（利得・ちらつき・ドリフト）が勝つと上がり始める。
**最小になる τ がアラン時間**（ポジションスイッチの周期を決める根拠）。

2026-09-24 の 50 Ω 終端（ADC 自身の雑音だけ）では、共通利得を除いても ch ごとに約 1.2e-3 のちらつき型の揺れが残り、
1/√(Δν·τ) と並ぶのが τ ≒ 1.4 s だった（README の判定 3）。増幅した雑音で、これが縮むかを見る。
"""
import argparse
import json
import sys

import numpy as np

T_FRAME = 8192 / 4096e6          # 2.000 µs
DF = 0.5e6                       # ch 幅 = 矩形窓の等価雑音帯域 [Hz]


def load(path):
    """(spec[N, 4096], k[N] or None, nacc, 出どころの説明) を返す"""
    if path.endswith(".npz"):
        d = np.load(path)
        spec = d["spec"]
        k = None
        if "k" in d.files:
            k = d["k"]
        elif "meta" in d.files:
            k = d["meta"][:, 1]
        if "nacc" in d.files:
            nacc = int(d["nacc"])
        elif "meta" in d.files:
            nacc = int(d["meta"][0, 2])
        else:
            sys.exit("ERROR: nacc が分からない（npz に nacc も meta も無い）")
        return spec, k, nacc, path
    info = json.load(open(path + ".info.json"))
    n = int(info["ndump_written"])
    spec = np.load(path + ".spec.npy", mmap_mode="r")[:n]
    meta = np.load(path + ".meta.npy")[:n]
    return spec, meta[:, 1], int(info["nacc"]), f"{path}（{info.get('stopped', '')}）"


def longest_run(k):
    """DUMP_K が 1 ずつ続く最長の区間 [a, b)。読み落としをまたいで束ねない"""
    if k is None or len(k) < 2:
        return 0, (len(k) if k is not None else None)
    brk = np.flatnonzero(np.diff(k) != 1) + 1
    edges = np.r_[0, brk, len(k)]
    i = int(np.argmax(np.diff(edges)))
    return int(edges[i]), int(edges[i + 1])


def oavar(x, m):
    """重なりありのアラン分散（列ごと）。x: [N, C]、m: 束ねる数"""
    c = np.cumsum(np.vstack([np.zeros((1, x.shape[1]), x.dtype), x]), axis=0, dtype=np.float64)
    y = (c[m:] - c[:-m]) / m                          # 長さ m の窓の平均（窓は 1 ずつずらす）
    d = y[m:] - y[:-m]
    return 0.5 * np.mean(d * d, axis=0)


def m_grid(n):
    ms, dec = [], 1
    while dec <= n // 3:
        for f in (1, 2, 5):
            if f * dec <= n // 3:
                ms.append(f * dec)
        dec *= 10
    return ms


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("path", help="--record の接頭辞、または .npz")
    p.add_argument("--edge", type=int, default=50, help="両端から外す ch 数")
    p.add_argument("--pair", type=int, default=1000, help="2 ch の差で組む ch の間隔")
    p.add_argument("--prebin", type=int, default=1, help="先に m 個ずつ足して τ0 を伸ばす（長い 100 ms 記録のメモリ節約）")
    p.add_argument("--chunk", type=int, default=512, help="一度に計算する ch 数（メモリ）")
    p.add_argument("--plot", default=None, help="図を PNG で書く（matplotlib があれば）")
    a = p.parse_args()

    spec, k, nacc, src = load(a.path)
    lo, hi = longest_run(k)
    if hi is None:
        hi = spec.shape[0]
    n_all = spec.shape[0]
    spec = spec[lo:hi]
    tau0 = nacc * T_FRAME
    nb = spec.shape[0] // a.prebin
    print(f"{src}: {n_all} ダンプ × τ {tau0 * 1e3:.1f} ms")
    if (hi - lo) != n_all:
        print(f"  **読み落としがある**: 連続した最長の区間 [{lo}, {hi})（{hi - lo} ダンプ）だけを使う")
    if a.prebin > 1:
        print(f"  先に {a.prebin} 個ずつ足す → τ0 = {tau0 * a.prebin:.3f} s × {nb} 個")
    tau0 *= a.prebin
    if nb < 12:
        sys.exit("ERROR: ダンプが少なすぎる（束ねた後で 12 個以上要る）")

    # ---- ch の選び方: 両端と線（周りの中央値の 1.5 倍超）を外し、τ0 で揺れすぎる ch（混信）を外す ----
    nch = spec.shape[1]
    mu = np.zeros(nch)
    for c0 in range(0, nch, a.chunk):
        mu[c0:c0 + a.chunk] = np.asarray(spec[:nb * a.prebin, c0:c0 + a.chunk], dtype=np.float64).mean(axis=0)
    half = 16
    pad = np.pad(mu, half, mode="edge")
    base = np.array([np.median(pad[i:i + 2 * half + 1]) for i in range(nch)])
    sel = np.zeros(nch, bool)
    sel[a.edge:nch - a.edge] = True
    line = sel & (mu > 1.5 * base)
    sel &= ~line
    idx = np.flatnonzero(sel)

    def block(cols):
        x = np.asarray(spec[:nb * a.prebin, cols], dtype=np.float64)
        if a.prebin > 1:
            x = x.reshape(nb, a.prebin, -1).sum(axis=1)
        return x / x.mean(axis=0)

    want0 = 1 / (DF * tau0)
    r0 = np.empty(len(idx))
    for c0 in range(0, len(idx), a.chunk):
        cols = idx[c0:c0 + a.chunk]
        r0[c0:c0 + a.chunk] = oavar(block(cols), 1) / want0
    noisy = r0 > 4.0                                  # σ で 2 倍超
    q = idx[~noisy]
    print(f"  使う ch: {len(q)}（両端 {2 * a.edge}・線 {int(line.sum())}・τ0 で揺れすぎ {int(noisy.sum())} を除く）")
    if noisy.any():
        worst = idx[noisy][np.argsort(r0[noisy])[::-1][:8]]
        print("    揺れすぎで除いた ch（上位）: " + ", ".join(str(int(c)) for c in worst))

    # ---- 全 ch を読んで、必要な量をまとめて作る ----
    X = np.empty((nb, len(q)), dtype=np.float32)
    for c0 in range(0, len(q), a.chunk):
        X[:, c0:c0 + a.chunk] = block(q[c0:c0 + a.chunk])
    g = np.median(X, axis=1)                          # 共通の利得（ch ごとの比の中央値）
    tot = X.mean(axis=1, dtype=np.float64)            # 全電力（静かな ch、平均で割った値の平均）
    pos = {int(c): i for i, c in enumerate(q)}
    pairs = [(pos[int(c)], pos[int(c) + a.pair]) for c in q if int(c) + a.pair in pos]

    ms = m_grid(nb)
    rows = []
    for m in ms:
        tau = m * tau0
        av_tot = float(oavar(tot[:, None], m)[0])
        av_ch, av_cg = [], []
        for c0 in range(0, X.shape[1], a.chunk):
            x = X[:, c0:c0 + a.chunk].astype(np.float64)
            av_ch.append(oavar(x, m))
            av_cg.append(oavar(x / g[:, None], m))
        av_ch = float(np.median(np.concatenate(av_ch)))
        av_cg = float(np.median(np.concatenate(av_cg)))
        if pairs:
            ia = np.array([p_[0] for p_ in pairs])
            ib = np.array([p_[1] for p_ in pairs])
            av_pr = []
            for c0 in range(0, len(ia), a.chunk):
                d = X[:, ia[c0:c0 + a.chunk]].astype(np.float64) - X[:, ib[c0:c0 + a.chunk]]
                av_pr.append(oavar(d, m))
            av_pr = float(np.median(np.concatenate(av_pr)))
        else:
            av_pr = np.nan
        w = 1 / (DF * tau)
        rows.append((tau, nb / m, av_tot, w / len(q), av_ch, w, av_cg, w, av_pr, 2 * w))

    print("\n  アラン分散（相対値の 2 乗）と、ラジオメータ式に対する比 √(実測/期待)")
    print("    τ[s]    独立数   全電力               ch ごと              共通利得を除く        2 ch の差")
    for tau, nind, a1, w1, a2, w2, a3, w3, a4, w4 in rows:
        cells = [f"{av:9.2e}（{np.sqrt(av / ww):5.2f}）" for av, ww in ((a1, w1), (a2, w2), (a3, w3), (a4, w4))]
        print(f"  {tau:7.2f}  {nind:7.1f}   " + "  ".join(cells))
    print("  （独立数 = 記録の長さ / τ。10 を切ると 1 点の誤差が 30 % を越える。重なりありの推定）")

    print("\n  アラン時間（アラン分散が最小になる τ）:")
    names = ["全電力", "ch ごと", "共通利得を除く", "2 ch の差"]
    for j, name in enumerate(names):
        av = np.array([r[2 + 2 * j] for r in rows])
        if np.all(np.isnan(av)):
            continue
        i = int(np.nanargmin(av))
        tau = rows[i][0]
        txt = f"> {tau:.2f} s（最後まで下がり続けた）" if i == len(rows) - 1 else f"{tau:.2f} s"
        print(f"    {name:<10} {txt}")

    if a.plot:
        plot(rows, len(q), a.plot, src)


def plot(rows, nq, out, title):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  （matplotlib が無いので図は書かない）")
        return
    from matplotlib import font_manager
    # 日本語のフォントがあれば日本語で、無ければ英語で書く（ボードには無いことが多い）
    have = {f.name for f in font_manager.fontManager.ttflist}
    jp = next((f for f in ("Hiragino Sans", "Hiragino Maru Gothic Pro", "Noto Sans CJK JP", "IPAexGothic",
                           "IPAGothic", "TakaoGothic", "Yu Gothic") if f in have), None)
    if jp:
        matplotlib.rcParams["font.family"] = jp
        L = dict(names=["全電力", "ch ごと", "共通利得を除く", "2 ch の差"], y1="アラン分散（相対）",
                 t1="アラン分散（破線 = ラジオメータ式）", y2="√(実測 / ラジオメータ式)",
                 t2="ラジオメータ式に対する比（1 = 理想）", ch="静かな ch")
    else:
        L = dict(names=["total power", "per channel", "common gain removed", "2-channel difference"],
                 y1="Allan variance (relative)", t1="Allan variance (dashed = radiometer equation)",
                 y2="sqrt(measured / radiometer)", t2="Ratio to radiometer equation (1 = ideal)", ch="quiet ch")
    # 系列の色は固定の順（dataviz の既定パレットの 1〜4 番）。期待は同じ色の破線
    colors = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
    names = L["names"]
    tau = np.array([r[0] for r in rows])
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.2), constrained_layout=True)
    for j, (c, nm) in enumerate(zip(colors, names)):
        av = np.array([r[2 + 2 * j] for r in rows])
        w = np.array([r[3 + 2 * j] for r in rows])
        if np.all(np.isnan(av)):
            continue
        ax1.loglog(tau, av, "-o", color=c, lw=2, ms=4, label=nm)
        ax1.loglog(tau, w, "--", color=c, lw=1, alpha=0.7)
        ax2.loglog(tau, np.sqrt(av / w), "-o", color=c, lw=2, ms=4, label=nm)
    ax2.axhline(1.0, color="#888888", lw=1)
    ax1.set_xlabel("τ [s]")
    ax1.set_ylabel(L["y1"])
    ax1.set_title(L["t1"], fontsize=10)
    ax2.set_xlabel("τ [s]")
    ax2.set_ylabel(L["y2"])
    ax2.set_title(L["t2"], fontsize=10)
    for ax in (ax1, ax2):
        ax.grid(True, which="both", color="#dddddd", lw=0.5)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    ax1.legend(frameon=False, fontsize=9)
    fig.suptitle(f"{title} ({L['ch']} {nq})", fontsize=10)
    try:
        fig.savefig(out, dpi=130)
        print(f"  図: {out}")
    except Exception as e:                            # 日本語フォントが無い環境でも落とさない
        print(f"  図を書けなかった: {e}")


if __name__ == "__main__":
    main()
