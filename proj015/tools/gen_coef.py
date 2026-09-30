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
    gen_nco_rom(os.path.join(os.path.dirname(out), "nco_rom.v"))


def gen_nco_rom(path):
    """NCO の 1/4 波の表（model/win_fixed.py の nco_table と同じ値）を ROM のモジュールにする。"""
    import win_fixed as F
    P, A = F.DEFAULT["NCO_P"], (1 << (F.DEFAULT["NCO_A"] - 1)) - 1
    T = F.nco_table(P, A)
    q = len(T)
    aw = (q - 1).bit_length()
    L = ["// SPDX-License-Identifier: BSD-3-Clause",
         "// 生成物（tools/gen_coef.py、make coef）。**手で直さない。**",
         f"// nco_rom — NCO の 1/4 波の表 T[r] = round({A} · sin(2π(r + 1/2) / 2^{P}))、r = 0..{q - 1}（18 bit）。",
         "// 読み出しは 2 口・1 クロック（出力をレジスタで受ける → BRAM に載る）。対応する模型: model/win_fixed.py の nco_table / nco_cs",
         "`timescale 1ns / 1ps",
         "module nco_rom (",
         "    input  wire              clk,",
         f"    input  wire [{aw - 1}:0]       a0, a1,",
         "    output reg  signed [17:0] d0, d1",
         ");",
         f"    (* rom_style = \"block\" *) reg signed [17:0] rom [0:{q - 1}];",
         "    initial begin"]
    for r, v in enumerate(T):
        L.append(f"        rom[{r}] = {'-' if v < 0 else ''}18'sd{abs(int(v))};")
    L += ["    end",
          "    always @(posedge clk) begin",
          "        d0 <= rom[a0];",
          "        d1 <= rom[a1];",
          "    end",
          "endmodule"]
    with open(path, "w") as fp:
        fp.write("\n".join(L) + "\n")
    print("書いた:", path)


if __name__ == "__main__":
    main()
