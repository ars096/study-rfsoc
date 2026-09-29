#!/usr/bin/env python3
"""proj014 — model/win_model.py の設計（18 bit に丸めた係数）から src/win_coef.vh を作る（make coef）。

生成物はリポジトリに入れる（proj013 の tw_rom.v と同じ扱い）。**手で直さない。**
設計を変えたら make coef で作り直し、make model・make fixed・make sim-pfb を回し直す。
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import win_model as WM  # noqa: E402


def packed(name, vals, w):
    items = ", ".join(f"{'-' if v < 0 else ''}{w}'sd{abs(v)}" for v in reversed(vals))
    return f"localparam [{w}*{len(vals)}-1:0] {name} = {{{items}}};"


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "src", "win_coef.vh")
    des = WM.design(60.0, WM.RIPPLE_PP)
    lines = ["// SPDX-License-Identifier: BSD-3-Clause",
             "// 生成物（tools/gen_coef.py、make coef）。**手で直さない。**",
             f"// 設計: model/win_model.py（{WM.METHOD}、要求 60 dB・{WM.RIPPLE_PP} dB p-p、係数 {WM.COEF_BITS} bit）",
             "// 係数は符号付き 18 bit。値 = 係数 / 2^SH。[n*18 +: 18] が n 番目（n = 0 が先頭）", ""]
    for key, nm in (("pfb", "PFB"), ("light", "HBL"), ("final", "HBF")):
        _, q, sh = WM.quantize(des[key]["h"])
        q = [int(v) for v in q]
        lines.append(f"// {key}: N = {len(q)}、SH = {sh}、対称 = {q == q[::-1]}")
        lines.append(f"localparam integer {nm}_N  = {len(q)};")
        lines.append(f"localparam integer {nm}_SH = {sh};")
        lines.append(packed(f"{nm}_H", q, 18))
        lines.append("")
    # 実数化の後処理のひねり係数 −j·W32^k（k = 0..16）。2^16 = 1.0
    wr, wi = [], []
    for k in range(17):
        a = int(round(65536 * math.cos(2 * math.pi * k / 32)))
        b = int(round(-65536 * math.sin(2 * math.pi * k / 32)))
        wr.append(b); wi.append(-a)                   # −j·(a + jb) = b − ja
    lines.append("// 実数化の後処理: −j·W32^k（k = 0..16）、2^16 = 1.0。W32 = exp(−2πi/32)")
    lines.append(packed("POST_WR", wr, 18))
    lines.append(packed("POST_WI", wi, 18))
    with open(out, "w") as fp:
        fp.write("\n".join(lines) + "\n")
    print("書いた:", out)


if __name__ == "__main__":
    main()
