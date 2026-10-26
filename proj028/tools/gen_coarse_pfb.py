#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 C-1 — 荒い PFB の RTL を作る（src/coarse_pfb.v）。係数は model/coarse_pfb_ref.py の gtable() と同じ。

使い方: python3 tools/gen_coarse_pfb.py [--bad] [--out PATH]   （--bad: 陽性対照。係数 g[100] の符号を逆に）
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "model"))
from coarse_pfb_ref import gtable, M, TC, SH, ZW, L  # noqa: E402

XW, CW = 14, 18
NH = L + 8                    # 履歴（位相 B は 8 ずれる）
KD = 9                        # 1 本の r あたりの積の数（27 タップ / 3 拍）


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bad", action="store_true")
    ap.add_argument("--out", default="src/coarse_pfb.v")
    a = ap.parse_args()
    g = gtable()
    if a.bad:
        g = g.copy()
        g[100] = -g[100]
    lim = (1 << (CW - 1)) - 1
    assert g.max() <= lim and g.min() >= -lim
    # 係数の定数のベクトル: n 番を [CW*n +: CW]
    hexw = (CW * L + 3) // 4
    v = 0
    for n in range(L):
        v |= (int(g[n]) & ((1 << CW) - 1)) << (CW * n)
    gl = "%d'h%0*x" % (CW * L, hexw, v)
    o = []
    w = o.append
    w("// SPDX-License-Identifier: BSD-3-Clause")
    w("// proj028 C-1 — 荒い PFB（tools/gen_coarse_pfb.py が作る。手で直さない）%s" % ("  **陽性対照（--bad: g[100] の符号が逆）**" if a.bad else ""))
    w("// 入力 1 拍 16 サンプル（[16p+2 +: 14]、p = 拍の中の時間の順）。ブロック m の最も新しいサンプルは 56m + 55（拍の数え 7 拍に 2 回）")
    w("// z_r = sat18((Σ_t g[r + 64t]·x[t0 − r − 64t] + 2^17) >>> 18)、g は (−1)^t を含む 18 bit。model/coarse_pfb_ref.py と bit 単位で同じ")
    w("`default_nettype none")
    w("module coarse_pfb (")
    w("    input  wire          clk,")
    w("    input  wire          rst,              // 拍の数え（ブロックの位相）だけを戻す。履歴はリセットしない")
    w("    input  wire          s_valid,")
    w("    input  wire [255:0]  s_data,")
    w("    output reg           m_valid,")
    w("    output wire [%d:0] m_z               // z_r（r = 0..63）、各 %d bit" % (M * ZW - 1, ZW))
    w(");")
    w("    localparam integer L = %d, NH = %d, XW = %d, CW = %d;" % (L, NH, XW, CW))
    w("    localparam [CW*L-1:0] G = %s;" % gl)
    w("    // ---- 履歴（新しいほど小さい番号: H[0] = 今の拍の 15 番）----")
    w("    reg [XW*NH-1:0] H;")
    w("    integer p;")
    w("    reg [XW*16-1:0] nb;")
    w("    always @* for (p = 0; p < 16; p = p + 1) nb[XW*(15-p) +: XW] = s_data[16*p + 2 +: XW];")
    w("    always @(posedge clk) if (s_valid) H <= {H[XW*(NH-16)-1:0], nb};")
    w("    // ---- 拍の数え（7 拍に 2 ブロック）: 拍 3 → 位相 B（H[n + 8]）、拍 6 → 位相 A（H[n]）。数えは履歴に入った拍の番号 ----")
    w("    reg [2:0] b7;")
    w("    reg       v1;")
    w("    always @(posedge clk) begin")
    w("        v1 <= s_valid;")
    w("        if (rst) b7 <= 3'd0;")
    w("        else if (v1) b7 <= (b7 == 3'd6) ? 3'd0 : b7 + 3'd1;")
    w("    end")
    w("    // v1 の拍で H は拍 b7 を最新に持つ")
    w("    wire blk_a = v1 && !rst && (b7 == 3'd6);")
    w("    wire blk_b = v1 && !rst && (b7 == 3'd3);")
    w("    // ---- 窓の写し S[n] = x[t0 − n] ----")
    w("    reg [XW*L-1:0] S;")
    w("    always @(posedge clk) begin")
    w("        if (blk_a) S <= H[XW*L-1:0];")
    w("        else if (blk_b) S <= H[XW*(L+8)-1:XW*8];")
    w("    end")
    w("    // ---- 3 拍の計算: 拍 c（0..2）に DSP (r, k) が n = r + 64(3k + c) ----")
    w("    reg [1:0] c;          // 0..2 計算中、3 休み")
    w("    always @(posedge clk) begin")
    w("        if (rst) c <= 2'd3;")
    w("        else if (blk_a || blk_b) c <= 2'd0;")
    w("        else if (c != 2'd3) c <= c + 2'd1;")
    w("    end")
    w("    reg [1:0] c1, c2, c3, c4, c5;")
    w("    reg       c6;")
    w("    always @(posedge clk) begin c1 <= c; c2 <= c1; c3 <= c2; c4 <= c3; c5 <= c4; end")
    w("    genvar r, k;")
    w("    generate for (r = 0; r < %d; r = r + 1) begin : g_r" % M)
    w("        wire signed [%d:0] pr [0:%d];" % (XW + CW - 1, KD - 1))
    w("        for (k = 0; k < %d; k = k + 1) begin : g_k" % KD)
    w("            reg signed [XW-1:0] xs;")
    w("            reg signed [CW-1:0] gs;")
    w("            (* use_dsp = \"yes\" *) reg signed [XW+CW-1:0] m1, m2;")
    w("            always @(posedge clk) begin")
    w("                case (c)")
    for cc in range(3):
        w("                    2'd%d: begin xs <= S[XW*(r + 64*(3*k + %d)) +: XW]; gs <= G[CW*(r + 64*(3*k + %d)) +: CW]; end" % (cc, cc, cc))
    w("                    default: begin xs <= {XW{1'b0}}; gs <= {CW{1'b0}}; end")
    w("                endcase")
    w("                m1 <= xs * gs;")
    w("                m2 <= m1;")
    w("            end")
    w("            assign pr[k] = m2;")
    w("        end")
    w("        // 9 個の和（2 段）→ 3 拍ぶん積む")
    w("        reg signed [%d:0] s0, s1, s2, sa;" % (XW + CW + 4))
    w("        always @(posedge clk) begin")
    w("            s0 <= pr[0] + pr[1] + pr[2];")
    w("            s1 <= pr[3] + pr[4] + pr[5];")
    w("            s2 <= pr[6] + pr[7] + pr[8];")
    w("            sa <= s0 + s1 + s2;")
    w("        end")
    # F-5b: 最後の和（fsum）をレジスタで受けてから丸め・飽和（全体のビルドで acc + sa → 丸め → 飽和 → zr が WNS −0.335 ns だった）
    w("        reg signed [%d:0] acc, fsum;" % (XW + CW + 5))
    w("        reg signed [%d:0] zr;" % (ZW - 1))
    w("        wire signed [%d:0] accn = (c5 == 2'd0) ? sa : acc + sa;" % (XW + CW + 5))
    w("        wire signed [%d:0] rnd = (fsum + (1 <<< %d)) >>> %d;" % (XW + CW + 5, SH - 1, SH))
    w("        always @(posedge clk) begin")
    w("            acc <= accn;")
    w("            if (c5 == 2'd2) fsum <= accn;")
    w("            if (c6) zr <= (rnd > %d) ? %d : (rnd < -%d) ? -%d : rnd[%d:0];" % ((1 << (ZW - 1)) - 1, (1 << (ZW - 1)) - 1, (1 << (ZW - 1)) - 1, (1 << (ZW - 1)) - 1, ZW - 1))
    w("        end")
    w("        assign m_z[%d*r +: %d] = zr;" % (ZW, ZW))
    w("    end endgenerate")
    w("    // 遅れ: c = 0 の拍 → xs（+1）→ m1（+2）→ m2（+3）→ s（+4）→ sa（+5）→ acc（c5 = c の 5 拍後に積む）。c5 == 2 で fsum、その次の拍（c6）で zr、さらに次の拍に valid")
    w("    always @(posedge clk) begin c6 <= !rst && (c5 == 2'd2); m_valid <= !rst && c6; end")
    w("endmodule")
    w("`default_nettype wire")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    open(a.out, "w").write("\n".join(o) + "\n")
    print("wrote %s（係数 %d 個、積 %d 個%s）" % (a.out, L, M * KD, "、陽性対照" if a.bad else ""))


if __name__ == "__main__":
    main()
