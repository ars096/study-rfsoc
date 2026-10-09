#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""floorplan.py — tools/floorplan.tcl が書いた CSV から、配置の図（フロアマップ）を描く（proj021、2026-10-09）

    python3 tools/floorplan.py build/floorplan                       # → build/floorplan/floorplan.png・floorplan_detail.png・blocks.txt
    python3 tools/floorplan.py build/floorplan --title "2-1 既定" --paths 30
    python3 tools/floorplan.py build/floorplan build-1b/floorplan    # 2 つを縦に並べる（compare.png は 1 つ目のディレクトリに）

図の座標は Vivado の RPM_X・RPM_Y（SLICE・DSP・BRAM・URAM が同じ物差し。左下が原点）。点 1 つ = 使っているサイト 1 つ。
  floorplan.png        ブロックの種類で色分け（コアごとの色相: PFB は濃く、窓 0・1・コアの共通は薄く。FULL・ギアボックス・SmartConnect・RFDC）
  floorplan_detail.png 深さ D で束ねたグループごとに色（細かい）
  blocks.txt           ブロックごとのサイト数・プリミティブ数・重心・広がり（5〜95 % の幅）・使ったクロック領域
--paths N で setup の上位 N 本の経路を始点 → 終点の線で重ねる（色は slack。負は赤）。
図の文字は英数字だけ（Vivado サーバに日本語のフォントが無くても読めるように）。
"""
import argparse
import csv
import os
import re
import sys

import numpy as np

ADC = ["ADC_A", "ADC_B", "ADC_C", "ADC_D"]
HUE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]          # コア 0..3


def shade(hexc, f):
    """f > 0 で白へ、f < 0 で黒へ寄せる"""
    c = np.array([int(hexc[i:i + 2], 16) for i in (1, 3, 5)], float) / 255
    c = c + (1 - c) * f if f >= 0 else c * (1 + f)
    return tuple(np.clip(c, 0, 1))


def category(g):
    """深さ D のグループ名 → (図の凡例の名前, 色, 並べる順)"""
    if re.search(r"/spec_core_\d+/", g):                     # proj021 1b まで: 全帯域は spec_core_0 のセル
        return "FULL (s45_core_0)", "#9467bd", 40
    m = re.search(r"(?:s45_core|win_core)_(\d+)/inst/(.*)", g)   # 1b までは win_core_i（u_win の段が無い）
    if m:
        i, rest = int(m.group(1)), m.group(2)
        a, h = ADC[i] if i < 4 else f"core{i}", HUE[i % 4]
        if rest.startswith("g_full"):
            return "FULL (s45_core_0)", "#9467bd", 40
        if "u_pfb" in rest:
            return f"{a} PFB", shade(h, -0.35), 10 * i + 1
        w = re.search(r"g_w\[(\d+)\]", rest)
        if w:
            return f"{a} win{w.group(1)}", shade(h, 0.15 + 0.3 * int(w.group(1))), 10 * i + 2 + int(w.group(1))
        return f"{a} common/TP/AXI", shade(h, 0.55), 10 * i + 6
    m = re.search(r"/(gb_(?:adc|up|fifo|gate|dn|bc))_(\d+)", g)
    if m:
        i = int(m.group(2))
        return f"{ADC[i] if i < 4 else i} gearbox", shade(HUE[i % 4], 0.65), 10 * i + 7
    for pat, lab, col, k in ((r"smc|smartconnect", "SmartConnect", "#8c564b", 50), (r"rfdc", "RFDC", "#222222", 51),
                             (r"full_sel", "full_sel (axis_sel4)", "#e377c2", 41), (r"time_core", "time_core", "#bcbd22", 52),
                             (r"clk_wiz|rst_", "clock/reset", "#17becf", 53), (r"zynq|ps_e", "PS", "#7f7f7f", 54)):
        if re.search(pat, g):
            return lab, col, k
    return "other", "#aaaaaa", 99


def load(d):
    def rd(name):
        p = os.path.join(d, name)
        if not os.path.exists(p):
            return []
        with open(p, newline="") as f:
            return list(csv.DictReader(f))
    cells = rd("cells.csv")
    if not cells:
        sys.exit(f"{d}/cells.csv が無い・空（tools/floorplan.tcl を先に）")
    return dict(cells=cells, sites=rd("sites.csv"), regions=rd("regions.csv"), paths=rd("paths.csv"), dir=d)


def region_of(x, y, regions):
    for r in regions:
        if int(r["x0"]) <= x <= int(r["x1"]) and int(r["y0"]) <= y <= int(r["y1"]):
            return r["name"]
    return "?"


def draw(ax, D, detail=False, npaths=0, title=None):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    BG = {"SLICE": ("#e8e8e8", 1.0), "DSP": ("#d6e4f0", 3.0), "BRAM": ("#f0e0d0", 3.0), "URAM": ("#e0f0d8", 3.0),
          "RFADC": ("#ffcccc", 12.0), "RFDAC": ("#ffe0cc", 12.0), "IO": ("#eeeeaa", 3.0), "PS": ("#dddddd", 20.0)}
    sx = {}
    for s in D["sites"]:
        sx.setdefault(s["kind"], []).append((int(s["x"]), int(s["y"])))
    for k, pts in sx.items():
        c, sz = BG.get(k, ("#eeeeee", 1.0))
        p = np.array(pts)
        ax.scatter(p[:, 0], p[:, 1], s=sz, c=c, marker="s", linewidths=0, zorder=1)
    for r in D["regions"]:
        x0, y0, x1, y1 = (int(r[k]) for k in ("x0", "y0", "x1", "y1"))
        ax.add_patch(Rectangle((x0 - 0.5, y0 - 0.5), x1 - x0 + 1, y1 - y0 + 1, fill=False, lw=0.6, ec="#666666", zorder=2))
        ax.text(x0 + 1, y1 - 1, r["name"].replace("CLOCKREGION_", ""), fontsize=6, color="#666666", va="top", zorder=5)
    groups = {}
    for c in D["cells"]:
        groups.setdefault(c["group"], []).append((int(c["x"]), int(c["y"]), int(c["n"]), c["site_type"]))
    if detail:
        names = sorted(groups)
        cmap = plt.get_cmap("tab20") if len(names) <= 20 else plt.get_cmap("gist_ncar")
        for j, g in enumerate(names):
            p = np.array([q[:3] for q in groups[g]])
            col = cmap(j % 20) if len(names) <= 20 else cmap(0.05 + 0.9 * j / max(len(names) - 1, 1))
            ax.scatter(p[:, 0], p[:, 1], s=2.0, c=[col], marker="s", linewidths=0, zorder=3,
                       label=g.split("/inst/")[-1][:40] if "/inst/" in g else g[-40:])
    else:
        cats = {}
        for g, pts in groups.items():
            lab, col, k = category(g)
            cats.setdefault((k, lab, col), []).extend(pts)
        for (k, lab, col), pts in sorted(cats.items(), key=lambda t: t[0][0]):
            p = np.array([q[:3] for q in pts])
            big = np.array([q[3].startswith(("DSP", "RAMB", "URAM")) for q in pts])
            ax.scatter(p[~big, 0], p[~big, 1], s=4.0, c=[col], marker="s", linewidths=0, zorder=3, label=lab)
            if big.any():
                ax.scatter(p[big, 0], p[big, 1], s=10.0, c=[col], marker="s", edgecolors="k", linewidths=0.2, zorder=4)
    if npaths and D["paths"]:
        ps = D["paths"][:npaths]
        sl = np.array([float(p["slack"]) for p in ps])
        lim = max(abs(sl).max(), 1e-3)
        for p, s in zip(ps, sl):
            col = plt.get_cmap("RdYlGn")((s / lim + 1) / 2)
            ax.annotate("", xy=(int(p["ex"]), int(p["ey"])), xytext=(int(p["sx"]), int(p["sy"])),
                        arrowprops=dict(arrowstyle="->", color=col, lw=0.8), zorder=6)
        ax.text(0.01, 0.005, f"arrows: setup top {len(ps)} paths, slack {sl.min():+.3f} .. {sl.max():+.3f} ns (red = worst)",
                transform=ax.transAxes, fontsize=7)
    # RPM_X は RPM_Y より刻みが細かい（x 0〜3700・y 0〜1000 ほど）ので、等倍にすると潰れる。クロック領域の箱が縦長に見える比にする
    ax.set_aspect("auto")
    ax.set_xlabel("RPM_X"); ax.set_ylabel("RPM_Y")
    ax.set_title(title or os.path.normpath(D["dir"]), fontsize=9)
    return ax


def blocks(D):
    cats = {}
    for c in D["cells"]:
        lab, _, k = category(c["group"])
        cats.setdefault((k, lab), []).append((int(c["x"]), int(c["y"]), int(c["n"])))
    out = [f"{'ブロック':<26} {'サイト':>7} {'プリミティブ':>10} {'重心 x':>7} {'重心 y':>7} {'幅 x (5-95%)':>13} {'幅 y':>7}  クロック領域"]
    for (k, lab), pts in sorted(cats.items()):
        p = np.array(pts, float)
        w = p[:, 2]
        cx, cy = np.average(p[:, 0], weights=w), np.average(p[:, 1], weights=w)
        wx = np.percentile(p[:, 0], 95) - np.percentile(p[:, 0], 5)
        wy = np.percentile(p[:, 1], 95) - np.percentile(p[:, 1], 5)
        regs = {}
        for x, y, n in pts:
            r = region_of(x, y, D["regions"]).replace("CLOCKREGION_", "")
            regs[r] = regs.get(r, 0) + n
        top = " ".join(f"{r}:{100 * n / w.sum():.0f}%" for r, n in sorted(regs.items(), key=lambda t: -t[1])[:4])
        out.append(f"{lab:<26} {len(p):>7} {int(w.sum()):>10} {cx:>7.0f} {cy:>7.0f} {wx:>13.0f} {wy:>7.0f}  {top}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dirs", nargs="+", help="tools/floorplan.tcl の出力ディレクトリ（2 つ目以降は縦に並べて比べる）")
    ap.add_argument("--title", action="append", default=None, help="図の題（ディレクトリの順に。既定はディレクトリ名）")
    ap.add_argument("--paths", type=int, default=20, help="重ねる setup の経路の本数（0 で重ねない）")
    ap.add_argument("--dpi", type=int, default=200)
    a = ap.parse_args()
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    Ds = [load(d) for d in a.dirs]
    titles = (a.title or []) + [None] * len(Ds)
    D = Ds[0]
    for detail, name in ((False, "floorplan.png"), (True, "floorplan_detail.png")):
        fig, ax = plt.subplots(figsize=(16, 12))
        draw(ax, D, detail=detail, npaths=0 if detail else a.paths, title=titles[0])
        ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=6 if detail else 7, markerscale=4, frameon=False,
                  ncol=2 if detail and len({c["group"] for c in D["cells"]}) > 40 else 1)
        fig.savefig(os.path.join(D["dir"], name), dpi=a.dpi, bbox_inches="tight")
        plt.close(fig)
        print(f"書いた: {os.path.join(D['dir'], name)}")
    txt = blocks(D)
    with open(os.path.join(D["dir"], "blocks.txt"), "w") as f:
        f.write(txt + "\n")
    print(txt)
    if len(Ds) > 1:
        fig, axs = plt.subplots(len(Ds), 1, figsize=(16, 11 * len(Ds)), sharex=True, sharey=True)
        for ax, Dk, t in zip(axs, Ds, titles):
            draw(ax, Dk, npaths=a.paths, title=t)
        axs[-1].legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=7, markerscale=4, frameon=False)
        p = os.path.join(D["dir"], "compare.png")
        fig.savefig(p, dpi=a.dpi, bbox_inches="tight")
        print(f"書いた: {p}")


if __name__ == "__main__":
    main()
