// SPDX-License-Identifier: BSD-3-Clause
//
// spw_front — SpW の前段 1 ADC ぶん（proj032 P-1）: ギアボックスの出口 → 粗い PFB（pfb64_core）→ 窓の頭 H 本（head_core）→ ddcb の入口の語長 → ddcb → final の lane E 本
//
// 窓 w の設定（spw_regs の効いている値。WRST の間に変わり、rst = WRST で頭・ddcb を最初から）:
//   粗い ch cfg_wk[w]（PSPLIT: 頭 0..H/2−1 は偶の k、残りは奇の k）・NCO の増分 cfg_dphi[w]・NS cfg_ns[w]・final の lane cfg_fl[w]
// 語長（M-3）: 頭の出口 v（24 bit・Q 8）→ ddcb の入口 b = sat20(round(v / 2^(4 − bs)))、bs = 0, 0, 1, 1, 2（NS 1..5。Q = 4 + bs）。
//   wsb の入口で z = sat18(round(y / 2^bs)) と戻す（eng）
// NS 1 の窓は light 1 段目を通さない（head_core の byp）
// 粗い PFB は rst（WRST）で止めない（窓の始まりは頭の rst の後の最初の y。SAM45-Fine の pfb_core と同じ考え）
// flags: [0] 頭の飽和（どれか）[1] 頭の追い越し [2] ddcb の入口の飽和 [3..5] ddcb の flags（粘着、rst で消す）
`timescale 1ns / 1ps

module spw_front #(
    parameter integer H      = 14,
    parameter integer E      = 3,
    parameter integer PSPLIT = 1,
    parameter integer BW     = 20
)(
    input  wire                 clk,
    input  wire                 rst_pfb,        // ハードのリセット（粗い PFB）
    input  wire                 rst,            // WRST（頭・ddcb）
    input  wire [255:0]         s_tdata,
    input  wire                 s_tvalid,
    input  wire [H*6-1:0]       cfg_wk,
    input  wire [H*32-1:0]      cfg_dphi,
    input  wire [H*3-1:0]       cfg_ns,
    input  wire [H*2-1:0]       cfg_fl,
    output wire [E-1:0]         y_v,
    output wire [E*4-1:0]       y_ch,
    output wire [E*BW-1:0]      y_re, y_im,
    // 照合用（sim）: 粗い PFB の出口
    output wire [24*H-1:0]      c_re, c_im,
    output wire                 c_v,
    output reg  [5:0]           flags
);
    pfb64_core #(.NH(H), .PSPLIT(PSPLIT)) u_pfb (.clk(clk), .rst(rst_pfb), .s_tdata(s_tdata), .s_tvalid(s_tvalid), .k(cfg_wk),
        .y_re(c_re), .y_im(c_im), .y_valid(c_v));
    wire [H-1:0]    hv, hs, ho;
    wire [24*H-1:0] hr, hi;
    reg  [H-1:0]    bv;
    reg  [BW*H-1:0] br, bi;
    reg  [H-1:0]    bsat;
    genvar g;
    generate for (g = 0; g < H; g = g + 1) begin : hd
        wire [2:0] ns = cfg_ns[g*3 +: 3];
        head_core u_h (.clk(clk), .rst(rst), .y_valid(c_v), .y_re(c_re[g*24 +: 24]), .y_im(c_im[g*24 +: 24]), .dphi(cfg_dphi[g*32 +: 32]),
            .byp(ns == 3'd1), .z_valid(hv[g]), .z_re(hr[g*24 +: 24]), .z_im(hi[g*24 +: 24]), .sat(hs[g]), .ovr(ho[g]));
        // ddcb の入口: >>> (4 − bs) の丸め・BW bit の飽和
        wire [2:0] sh = (ns <= 3'd2) ? 3'd4 : (ns <= 3'd4) ? 3'd3 : 3'd2;
        wire signed [24:0] tr = ($signed(hr[g*24 +: 24]) + $signed(25'sd1 <<< (sh - 1))) >>> sh;
        wire signed [24:0] ti = ($signed(hi[g*24 +: 24]) + $signed(25'sd1 <<< (sh - 1))) >>> sh;
        localparam signed [24:0] MX = (1 <<< (BW - 1)) - 1, MN = -(1 <<< (BW - 1));
        always @(posedge clk) begin
            bv[g] <= hv[g] && !rst;
            br[g*BW +: BW] <= (tr > MX) ? MX[BW-1:0] : (tr < MN) ? MN[BW-1:0] : tr[BW-1:0];
            bi[g*BW +: BW] <= (ti > MX) ? MX[BW-1:0] : (ti < MN) ? MN[BW-1:0] : ti[BW-1:0];
            bsat[g] <= hv[g] && (tr > MX || tr < MN || ti > MX || ti < MN);
        end
    end endgenerate
    wire [2:0] dfl;
    ddcb #(.H(H), .NF(E), .W(BW)) u_ddcb (.clk(clk), .rst(rst), .x_v(bv), .x_re(br), .x_im(bi), .cfg_ns(cfg_ns), .cfg_fl(cfg_fl),
        .y_v(y_v), .y_ch(y_ch), .y_re(y_re), .y_im(y_im), .flags(dfl));
    always @(posedge clk) begin
        if (rst) flags <= 6'd0;
        else flags <= flags | {dfl, |bsat, |ho, |hs};
    end
endmodule
