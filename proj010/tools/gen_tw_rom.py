#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""src/tw_rom.v を生成する（レーン p ごとのひねり係数 W8192^(p·k1)、k1 = 0..511）。

    python3 tools/gen_tw_rom.py > src/tw_rom.v

**生成物もコミットする。**ビルドサーバで Python を走らせずに済ませるためと、
係数が変わったことを git の差分で見えるようにするため。

値は round(2^16 · exp(-2πi·p·k1/8192))。18 bit 符号付きで、2^16 = 1.0。
sim/model.py の twiddle() と **同じ式**でなければならない（make sim が突き合わせる）。
"""
import math

N, P, M = 8192, 16, 512
SCALE = 1 << 16


def tw(p, k1):
    a = 2.0 * math.pi * p * k1 / N
    return round(SCALE * math.cos(a)), round(-SCALE * math.sin(a))


out = []
w = out.append
w("// SPDX-License-Identifier: BSD-3-Clause")
w("//")
w("// tw_rom — レーン P のひねり係数 W8192^(P·k1)（k1 = 0..511）。**tools/gen_tw_rom.py の生成物。手で直さない**")
w("//")
w("// 出力はアドレスから **2 クロック後**（ROM の読み出し + 出力レジスタ）。")
w("// 値は round(2^16 · exp(-2πi·P·k1/8192))、18 bit 符号付き。")
w("")
w("`timescale 1ns / 1ps")
w("")
w("module tw_rom #(")
w("    parameter integer P = 0")
w(")(")
w("    input  wire               clk,")
w("    input  wire [8:0]         addr,")
w("    output reg  signed [17:0] w_re,")
w("    output reg  signed [17:0] w_im")
w(");")
w("    // 1 語 36 bit = {im[17:0], re[17:0]}（生成物を小さくするため 16 進 1 語にまとめている）")
w("    reg [35:0] r;")
w("    always @(posedge clk) begin")
w("        w_re <= r[17:0];")
w("        w_im <= r[35:18];")
w("    end")
w("")
w("    generate")
for p in range(P):
    kw = "if" if p == 0 else "else if"
    w("    %s (P == %d) begin : g_p%d" % (kw, p, p))
    w("        always @(posedge clk) begin")
    w("            case (addr)")
    for k1 in range(M):
        re, im = tw(p, k1)
        word = ((im & 0x3FFFF) << 18) | (re & 0x3FFFF)
        w("            %d: r <= 36'h%09x;" % (k1, word))
    w("            default: r <= 36'h0;")
    w("            endcase")
    w("        end")
    w("    end")
w("    endgenerate")
w("endmodule")
print("\n".join(out))
