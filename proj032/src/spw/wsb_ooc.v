// SPDX-License-Identifier: BSD-3-Clause
// wsb_ooc — wsb（E-4・D-2）を OOC で数えるための包み。設定（窓ごとの NS・機関・枠・シフト・利得）はレジスタから（定数にすると合成が畳む）
`timescale 1ns / 1ps
module wsb_ooc #(
    parameter integer H = 14, E = 3, S = 6, W = 20, D = 1024, LEAD = 960, NK = 8
)(
    input  wire             clk, rst,
    input  wire [E-1:0]     y_v,
    input  wire [E*4-1:0]   y_ch,
    input  wire [E*W-1:0]   y_re, y_im,
    input  wire             cfg_we,
    input  wire [3:0]       cfg_a,
    input  wire [16:0]      cfg_d,
    input  wire [31:0]      ng, ndump, ddr_base,
    input  wire             cmd_run, cmd_stop,
    output wire [E-1:0]     d_v,
    output wire [E*4-1:0]   d_w,
    output wire [E*32-1:0]  d_k,
    output wire [E*12-1:0]  d_ch,
    output wire [E*64-1:0]  d_data,
    output wire [E*16-1:0]  flags,
    output wire [2*E+1:0]   dflags,
    output wire [31:0]      m_awaddr,
    output wire [7:0]       m_awlen,
    output wire             m_awvalid,
    input  wire             m_awready,
    output wire [63:0]      m_wdata,
    output wire             m_wlast,
    output wire             m_wvalid,
    input  wire             m_wready,
    input  wire             m_bvalid,
    output wire [E*32-1:0]  m_araddr,
    output wire [E-1:0]     m_arvalid,
    input  wire [E-1:0]     m_arready,
    input  wire [E*128-1:0] m_rdata,
    input  wire [E-1:0]     m_rvalid,
    input  wire [E-1:0]     m_rlast
);
    reg [H*3-1:0] cns; reg [H*4-1:0] csl, csh, cg; reg [H*2-1:0] cfl;
    always @(posedge clk) if (cfg_we) begin
        cns[cfg_a*3 +: 3] <= cfg_d[2:0]; cfl[cfg_a*2 +: 2] <= cfg_d[4:3];
        csl[cfg_a*4 +: 4] <= cfg_d[8:5]; csh[cfg_a*4 +: 4] <= cfg_d[12:9]; cg[cfg_a*4 +: 4] <= cfg_d[16:13];
    end
    wire go; wire [31:0] g0;
    wsb #(.H(H), .E(E), .S(S), .W(W), .G_L2(19), .D(D), .LEAD(LEAD), .NK(NK)) u (
        .clk(clk), .rst(rst), .y_v(y_v), .y_ch(y_ch), .y_re(y_re), .y_im(y_im),
        .cfg_ns(cns), .cfg_fl(cfl), .cfg_sl(csl), .cfg_sh(csh), .cfg_g(cg), .ddr_base(ddr_base), .ng(ng), .ndump(ndump),
        .cmd_run(cmd_run), .cmd_stop(cmd_stop), .go(go), .g0(g0),
        .d_v(d_v), .d_w(d_w), .d_k(d_k), .d_ch(d_ch), .d_data(d_data), .flags(flags), .dflags(dflags),
        .m_awaddr(m_awaddr), .m_awlen(m_awlen), .m_awvalid(m_awvalid), .m_awready(m_awready), .m_wdata(m_wdata), .m_wlast(m_wlast),
        .m_wvalid(m_wvalid), .m_wready(m_wready), .m_bvalid(m_bvalid),
        .m_araddr(m_araddr), .m_arvalid(m_arvalid), .m_arready(m_arready), .m_rdata(m_rdata), .m_rvalid(m_rvalid), .m_rlast(m_rlast));
endmodule
