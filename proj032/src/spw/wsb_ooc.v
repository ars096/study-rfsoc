// SPDX-License-Identifier: BSD-3-Clause
// wsb_ooc — wsb（E-4）を OOC で数えるための包み。設定（窓ごとの NS・機関・枠・シフト）はレジスタから（定数にすると合成が畳む）
`timescale 1ns / 1ps
module wsb_ooc #(
    parameter integer H = 14, E = 3, S = 6, W = 20, D = 64
)(
    input  wire             clk, rst,
    input  wire [E-1:0]     y_v,
    input  wire [E*4-1:0]   y_ch,
    input  wire [E*W-1:0]   y_re, y_im,
    input  wire             cfg_we,
    input  wire [3:0]       cfg_a,
    input  wire [12:0]      cfg_d,
    input  wire [31:0]      ng, ndump,
    input  wire             cmd_run, cmd_stop,
    output wire [E-1:0]     d_v,
    output wire [E*4-1:0]   d_w,
    output wire [E*32-1:0]  d_k,
    output wire [E*12-1:0]  d_ch,
    output wire [E*64-1:0]  d_data,
    output wire [E*8-1:0]   flags
);
    reg [H*3-1:0] cns; reg [H*4-1:0] csl; reg [H*2-1:0] cfl; reg [H*4-1:0] csh;
    always @(posedge clk) if (cfg_we) begin
        cns[cfg_a*3 +: 3] <= cfg_d[2:0]; cfl[cfg_a*2 +: 2] <= cfg_d[4:3];
        csl[cfg_a*4 +: 4] <= cfg_d[8:5]; csh[cfg_a*4 +: 4] <= cfg_d[12:9];
    end
    wire go; wire [31:0] g0;
    wsb #(.H(H), .E(E), .S(S), .W(W), .G_L2(19), .D(D)) u (
        .clk(clk), .rst(rst), .y_v(y_v), .y_ch(y_ch), .y_re(y_re), .y_im(y_im),
        .cfg_ns(cns), .cfg_fl(cfl), .cfg_sl(csl), .cfg_sh(csh), .ng(ng), .ndump(ndump),
        .cmd_run(cmd_run), .cmd_stop(cmd_stop), .go(go), .g0(g0),
        .d_v(d_v), .d_w(d_w), .d_k(d_k), .d_ch(d_ch), .d_data(d_data), .flags(flags));
endmodule
