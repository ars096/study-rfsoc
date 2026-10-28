// SPDX-License-Identifier: BSD-3-Clause
// ksink_ooc — 受け手（dsink）＋ リング（ring128）を OOC で数えるための包み（proj032 K-2）。窓ごとの設定はレジスタから
`timescale 1ns / 1ps
module ksink_ooc #(
    parameter integer H = 14, E = 3, NU = 2
)(
    input  wire             clk, aresetn,
    input  wire [E-1:0]     d_v,
    input  wire [E*4-1:0]   d_w,
    input  wire [E*32-1:0]  d_k,
    input  wire [E*12-1:0]  d_ch,
    input  wire [E*64-1:0]  d_data,
    input  wire             cfg_we,
    input  wire [3:0]       cfg_a,
    input  wire [10:0]      cfg_d,
    input  wire [31:0]      ng, g0,
    input  wire [H*64-1:0]  t0,
    output wire [3:0]       sflags,
    input  wire [11:0]      s_axi_awaddr,
    input  wire             s_axi_awvalid,
    output wire             s_axi_awready,
    input  wire [31:0]      s_axi_wdata,
    input  wire             s_axi_wvalid,
    output wire             s_axi_wready,
    output wire [1:0]       s_axi_bresp,
    output wire             s_axi_bvalid,
    input  wire             s_axi_bready,
    input  wire [11:0]      s_axi_araddr,
    input  wire             s_axi_arvalid,
    output wire             s_axi_arready,
    output wire [31:0]      s_axi_rdata,
    output wire [1:0]       s_axi_rresp,
    output wire             s_axi_rvalid,
    input  wire             s_axi_rready,
    output wire [48:0]      m_axi_awaddr,
    output wire [7:0]       m_axi_awlen,
    output wire             m_axi_awvalid,
    input  wire             m_axi_awready,
    output wire [127:0]     m_axi_wdata,
    output wire             m_axi_wlast,
    output wire             m_axi_wvalid,
    input  wire             m_axi_wready,
    input  wire [1:0]       m_axi_bresp,
    input  wire             m_axi_bvalid
);
    reg [2:0] ns [0:H-1]; reg [3:0] sh [0:H-1]; reg [3:0] gg [0:H-1];
    wire [H*3-1:0] cfg_ns; wire [H*4-1:0] cfg_sh, cfg_g;
    integer i;
    always @(posedge clk) if (cfg_we) begin ns[cfg_a] <= cfg_d[2:0]; sh[cfg_a] <= cfg_d[6:3]; gg[cfg_a] <= cfg_d[10:7]; end
    genvar g;
    generate for (g = 0; g < H; g = g + 1) begin : c
        assign cfg_ns[g*3 +: 3] = ns[g]; assign cfg_sh[g*4 +: 4] = sh[g]; assign cfg_g[g*4 +: 4] = gg[g];
    end endgenerate
    reg r1 = 1'b1, rst = 1'b1;
    always @(posedge clk) begin r1 <= ~aresetn; rst <= r1; end
    wire [127:0] t_d; wire t_v, t_r, t_l; wire [E-1:0] drop;
    dsink #(.E(E), .H(H), .NU(NU)) u_sink (.clk(clk), .rst(rst), .d_v(d_v), .d_w(d_w), .d_k(d_k), .d_ch(d_ch), .d_data(d_data),
        .cfg_ns(cfg_ns), .cfg_sh(cfg_sh), .cfg_g(cfg_g), .ng(ng), .g0(g0), .t0(t0), .m_tdata(t_d), .m_tvalid(t_v), .m_tready(t_r), .m_tlast(t_l),
        .drop(drop), .flags(sflags));
    wire [2:0] aws, awp; wire [1:0] awb; wire awl; wire [3:0] awc, awq; wire [15:0] ws; wire bready;
    ring128 #(.NX(E)) u_ring (.aclk(clk), .aresetn(aresetn), .s_axis_tdata(t_d), .s_axis_tvalid(t_v), .s_axis_tready(t_r), .s_axis_tlast(t_l),
        .ext_drop(drop),
        .s_axi_awaddr(s_axi_awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp), .s_axi_bvalid(s_axi_bvalid), .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata), .s_axi_rresp(s_axi_rresp), .s_axi_rvalid(s_axi_rvalid), .s_axi_rready(s_axi_rready),
        .m_axi_awaddr(m_axi_awaddr), .m_axi_awlen(m_axi_awlen), .m_axi_awsize(aws), .m_axi_awburst(awb), .m_axi_awlock(awl),
        .m_axi_awcache(awc), .m_axi_awprot(awp), .m_axi_awqos(awq), .m_axi_awvalid(m_axi_awvalid), .m_axi_awready(m_axi_awready),
        .m_axi_wdata(m_axi_wdata), .m_axi_wstrb(ws), .m_axi_wlast(m_axi_wlast), .m_axi_wvalid(m_axi_wvalid), .m_axi_wready(m_axi_wready),
        .m_axi_bresp(m_axi_bresp), .m_axi_bvalid(m_axi_bvalid), .m_axi_bready(bready));
endmodule
