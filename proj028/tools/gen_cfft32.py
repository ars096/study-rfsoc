#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 S-1 — 荒い FFT（M-1d の形）の RTL を作る。src/cfft32.v を書く。

  入力: z_r（r = 0..63、実数、ZW bit）を 1 拍に 1 ブロック（s_valid）
  前掛け: w_n = (z_n + j·z_{n+32})·e^{jπn/64}（n = 0 は掛けない）
  32 点 DIF（自然順の入力、bit 反転順の出口）: F_m = Σ_n w_n e^{+j2πmn/32}
  出口: F_m を m の自然順に並べ直して出す（並べ直しは配線）。Y への詰め替え（共役）は後段（細かい側の入口）でする

  回しの係数 CW bit（小数 CW−1）、積は丸めて元の小数に戻す。語長は大きさで数える: 前掛けの出口 ZW+1（成分が √2 倍になる）、
  DIF の各段で +1（和・差。回しは大きさを変えない）→ 出口 ZW+6。
  前掛けは LAT_CM 拍、DIF の各段は 加算 1 ＋ LAT_CM 拍に揃える（自明な道は同じ拍だけ遅らせる）。

使い方: python3 tools/gen_cfft32.py [--bad]   （--bad は陽性対照: 段 0 の回し 1 個の符号を逆に）
"""
import argparse
import math

ZW = 18
CW = 18
LAT_CM = 4
N = 32


def tw(e_num, e_den, cw=CW):
    """e^{+j2π·e_num/e_den} を CW bit の整数に"""
    a = 2 * math.pi * e_num / e_den
    s = (1 << (cw - 1)) - 1
    return int(round(math.cos(a) * s)), int(round(math.sin(a) * s))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bad", action="store_true")
    ap.add_argument("--out", default="src/cfft32.v")
    a = ap.parse_args()
    L = []
    w = L.append
    w("// SPDX-License-Identifier: BSD-3-Clause")
    w("// proj028 S-1 — 荒い FFT（tools/gen_cfft32.py が作る。手で直さない）%s" % ("  **陽性対照（--bad）**" if a.bad else ""))
    w("// 前掛け e^{jπn/64} → 32 点 DIF の全並列。遅れ %d 拍（前掛け %d ＋ 5 段 × %d）" % (LAT_CM + 5 * (LAT_CM + 1), LAT_CM, LAT_CM + 1))
    w("`default_nettype none")
    w("module cfft32_cmul #(parameter W = 18, parameter WO = 18, parameter signed [%d:0] CR = 0, parameter signed [%d:0] CI = 0) (" % (CW - 1, CW - 1))
    w("    input  wire clk,")
    w("    input  wire signed [W-1:0] xr, xi,")
    w("    output reg  signed [WO-1:0] yr, yi);")
    w("    // (xr + j xi)(CR + j CI)、4 乗算・%d 拍。積は小数 %d bit を丸めて落とす" % (LAT_CM, CW - 1))
    w("    (* use_dsp = \"yes\" *) reg signed [W+%d:0] p_rr, p_ii, p_ri, p_ir;" % CW)
    w("    reg signed [W-1:0] ar, ai;")
    w("    reg signed [W+%d:0] sr, si;" % (CW + 1))
    w("    always @(posedge clk) begin")
    w("        ar <= xr; ai <= xi;")
    w("        p_rr <= ar * CR; p_ii <= ai * CI; p_ri <= ar * CI; p_ir <= ai * CR;")
    w("        sr <= p_rr - p_ii + (1 <<< %d);" % (CW - 2))
    w("        si <= p_ri + p_ir + (1 <<< %d);" % (CW - 2))
    w("        yr <= sr >>> %d; yi <= si >>> %d;" % (CW - 1, CW - 1))
    w("    end")
    w("endmodule")
    w("")
    w("module cfft32_dly #(parameter W = 18, parameter D = %d) (input wire clk, input wire [W-1:0] x, output wire [W-1:0] y);" % LAT_CM)
    w("    reg [W-1:0] r [0:D-1];")
    w("    integer i;")
    w("    always @(posedge clk) begin r[0] <= x; for (i = 1; i < D; i = i + 1) r[i] <= r[i-1]; end")
    w("    assign y = r[D-1];")
    w("endmodule")
    w("")
    w("module cfft32 (")
    w("    input  wire clk,")
    w("    input  wire s_valid,")
    w("    input  wire [%d:0] s_z,            // z_r（r = 0..63）、各 %d bit" % (64 * ZW - 1, ZW))
    w("    output wire m_valid,")
    w("    output wire [%d:0] m_f           // F_m（m = 0..31、自然順）、各 実部 %d bit ＋ 虚部 %d bit（実部が下）" % (N * 2 * (ZW + 6) - 1, ZW + 6, ZW + 6))
    w(");")
    # 前掛け
    w("    // ---- 前掛け: w_n = (z_n + j z_{n+32})·e^{jπn/64}")
    for n in range(N):
        w("    wire signed [%d:0] w0r_%d, w0i_%d;" % (ZW, n, n))
        zr = "s_z[%d*%d +: %d]" % (n, ZW, ZW)
        zi = "s_z[%d*%d +: %d]" % (n + 32, ZW, ZW)
        if n == 0:
            w("    cfft32_dly #(.W(%d)) u_pd%d_r (.clk(clk), .x({s_z[%d], %s}), .y(w0r_%d));" % (ZW + 1, n, n * ZW + ZW - 1, zr, n))
            w("    cfft32_dly #(.W(%d)) u_pd%d_i (.clk(clk), .x({s_z[%d], %s}), .y(w0i_%d));" % (ZW + 1, n, (n + 32) * ZW + ZW - 1, zi, n))
        else:
            cr, ci = tw(n, 128)                          # e^{jπn/64} = e^{j2π n/128}
            w("    cfft32_cmul #(.W(%d), .WO(%d), .CR(%d), .CI(%d)) u_pm%d (.clk(clk), .xr(%s), .xi(%s), .yr(w0r_%d), .yi(w0i_%d));"
              % (ZW, ZW + 1, cr, ci, n, zr, zi, n, n))
    # DIF の段
    cur = ["w0r_%d" % n for n in range(N)], ["w0i_%d" % n for n in range(N)]
    width = ZW + 1                                       # 前掛けで成分が最大 √2 倍（大きさは変わらない）→ 1 bit 足す
    ncm = N - 1
    for st in range(5):
        span = 16 >> st
        nw = width + 1
        w("    // ---- 段 %d（span %d、出口 %d bit）" % (st, span, nw))
        nr, ni = [None] * N, [None] * N
        for blk in range(0, N, 2 * span):
            for j in range(span):
                i0, i1 = blk + j, blk + j + span
                ar, ai = cur[0][i0], cur[1][i0]
                br, bi = cur[0][i1], cur[1][i1]
                s0r, s0i = "s%d_%dr" % (st, i0), "s%d_%di" % (st, i0)
                d0r, d0i = "d%d_%dr" % (st, i1), "d%d_%di" % (st, i1)
                w("    reg signed [%d:0] %s, %s, %s, %s;" % (nw - 1, s0r, s0i, d0r, d0i))
                w("    always @(posedge clk) begin %s <= %s + %s; %s <= %s + %s; %s <= %s - %s; %s <= %s - %s; end"
                  % (s0r, ar, br, s0i, ai, bi, d0r, ar, br, d0i, ai, bi))
                o0r, o0i, o1r, o1i = "o%d_%dr" % (st, i0), "o%d_%di" % (st, i0), "o%d_%dr" % (st, i1), "o%d_%di" % (st, i1)
                w("    wire signed [%d:0] %s, %s, %s, %s;" % (nw - 1, o0r, o0i, o1r, o1i))
                # 段の遅れは 加算 1 ＋ LAT_CM（cmul の道に揃える）
                w("    cfft32_dly #(.W(%d), .D(%d)) u_s%d_%d_r (.clk(clk), .x(%s), .y(%s));" % (nw, LAT_CM, st, i0, s0r, o0r))
                w("    cfft32_dly #(.W(%d), .D(%d)) u_s%d_%d_i (.clk(clk), .x(%s), .y(%s));" % (nw, LAT_CM, st, i0, s0i, o0i))
                e = j / (2 * span)                       # 回し e^{+j2π·j/(2·span)}
                if j == 0:
                    w("    cfft32_dly #(.W(%d), .D(%d)) u_d%d_%d_r (.clk(clk), .x(%s), .y(%s));" % (nw, LAT_CM, st, i1, d0r, o1r))
                    w("    cfft32_dly #(.W(%d), .D(%d)) u_d%d_%d_i (.clk(clk), .x(%s), .y(%s));" % (nw, LAT_CM, st, i1, d0i, o1i))
                elif abs(e - 0.25) < 1e-12:                # ×(+j): (x + jy)·j = −y + jx
                    w("    wire signed [%d:0] nj%d_%d = -%s;" % (nw - 1, st, i1, d0i))
                    w("    cfft32_dly #(.W(%d), .D(%d)) u_d%d_%d_r (.clk(clk), .x(nj%d_%d), .y(%s));" % (nw, LAT_CM, st, i1, st, i1, o1r))
                    w("    cfft32_dly #(.W(%d), .D(%d)) u_d%d_%d_i (.clk(clk), .x(%s), .y(%s));" % (nw, LAT_CM, st, i1, d0r, o1i))
                else:
                    cr, ci = tw(j, 2 * span)
                    if a.bad and st == 0 and j == 1:
                        ci = -ci
                    w("    cfft32_cmul #(.W(%d), .WO(%d), .CR(%d), .CI(%d)) u_cm%d_%d (.clk(clk), .xr(%s), .xi(%s), .yr(%s), .yi(%s));"
                      % (nw, nw, cr, ci, st, i1, d0r, d0i, o1r, o1i))
                    ncm += 1
                nr[i0], ni[i0], nr[i1], ni[i1] = o0r, o0i, o1r, o1i
        cur = nr, ni
        width = nw
    w("    // cmul の数: %d" % ncm)
    # 出口: DIF は bit 反転順 → F_m（m 自然順）は位置 bitrev(m)
    w("    // ---- 出口（bit 反転順 → 自然順は配線）")
    for m in range(N):
        b = int("{:05b}".format(m)[::-1], 2)
        base = m * 2 * width
        w("    assign m_f[%d +: %d] = %s;" % (base, width, cur[0][b]))
        w("    assign m_f[%d +: %d] = %s;" % (base + width, width, cur[1][b]))
    lat = LAT_CM + 5 * (LAT_CM + 1)
    w("    reg [%d:0] vsh = 0;" % (lat - 1))
    w("    always @(posedge clk) vsh <= {vsh[%d:0], s_valid};" % (lat - 2))
    w("    assign m_valid = vsh[%d];" % (lat - 1))
    w("endmodule")
    w("`default_nettype wire")
    open(a.out, "w").write("\n".join(L) + "\n")
    print("wrote %s（cmul %d 個、出口 %d bit%s）" % (a.out, ncm, width, "、陽性対照" if a.bad else ""))


if __name__ == "__main__":
    main()
