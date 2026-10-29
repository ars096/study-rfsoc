// SPDX-License-Identifier: BSD-3-Clause
//
// spw_core — SpW のコア 1 ADC ぶん（proj032 P-2）: レジスタ（spw_regs、64 KiB）＋ 前段（spw_front）＋ 窓の分光の後段（wsb）＋ ダンプの受け手（dsink）
//
// 外にあるもの（BD）: ギアボックス（s_tdata）・time_core（t_now・fire）・PL の DDR（wsb の履歴の枠、m_*）・リング（ring128。m_tdata と drop を渡す）
// リセット: rst = ハード（レジスタ・粗い PFB）。WRST（spw_regs の wrst）は頭・ddcb・wsb・dsink を最初から（窓の t0 も取り直す）
// 設定は spw_regs の効いている値だけを使う（WRST・RUN で取り込んだもの）
// WRST は水抜きの後（spw_regs の drain → dsink が開いたレコードを送り終えて idle → 設定を取り込みリセット）。リングに切れたレコードを渡さない
`timescale 1ns / 1ps

module spw_core #(
    parameter integer H          = 14,
    parameter integer E          = 3,
    parameter integer S          = 6,
    parameter integer NK         = 8,
    parameter integer W          = 20,
    parameter integer G_L2       = 19,
    parameter integer D          = 1024,
    parameter integer NU         = 2,
    parameter integer ADC        = 0,
    parameter integer PSPLIT     = 1,
    parameter integer DDR_BASE   = 0,
    parameter integer BUILD_TAG  = 0,
    parameter integer BASE_BEATS = 2621440
)(
    input  wire                 clk,
    input  wire                 rst,
    // AXI4-Lite（コアの 64 KiB）
    input  wire [15:0]          s_axi_awaddr,
    input  wire                 s_axi_awvalid,
    output wire                 s_axi_awready,
    input  wire [31:0]          s_axi_wdata,
    input  wire                 s_axi_wvalid,
    output wire                 s_axi_wready,
    output wire                 s_axi_bvalid,
    output wire [1:0]           s_axi_bresp,
    input  wire                 s_axi_bready,
    input  wire [15:0]          s_axi_araddr,
    input  wire                 s_axi_arvalid,
    output wire                 s_axi_arready,
    output wire [31:0]          s_axi_rdata,
    output wire                 s_axi_rvalid,
    output wire [1:0]           s_axi_rresp,
    input  wire                 s_axi_rready,
    // ギアボックスの出口
    input  wire [255:0]         s_tdata,
    input  wire                 s_tvalid,
    // 時刻
    input  wire [63:0]          t_now,
    input  wire                 fire,
    // PL の DDR（履歴の枠 S..S+NK−1）
    output wire [31:0]          m_awaddr,
    output wire [7:0]           m_awlen,
    output wire                 m_awvalid,
    input  wire                 m_awready,
    output wire [63:0]          m_wdata,
    output wire                 m_wlast,
    output wire                 m_wvalid,
    input  wire                 m_wready,
    input  wire                 m_bvalid,
    output wire [E*32-1:0]      m_araddr,
    output wire [E-1:0]         m_arvalid,
    input  wire [E-1:0]         m_arready,
    input  wire [E*128-1:0]     m_rdata,
    input  wire [E-1:0]         m_rvalid,
    input  wire [E-1:0]         m_rlast,
    // リングへ（ring128 の s_axis・ext_drop）
    output wire [127:0]         m_tdata,
    output wire                 m_tvalid,
    input  wire                 m_tready,
    output wire                 m_tlast,
    output wire [E-1:0]         drop
);
    wire          wrst, drain, dp_idle, cmd_run, cmd_stop;
    wire [H*6-1:0]  cfg_wk;
    wire [H*32-1:0] cfg_dphi;
    wire [H*3-1:0]  cfg_ns;
    wire [H*2-1:0]  cfg_fl;
    wire [H*4-1:0]  cfg_sl, cfg_g, cfg_sh;
    wire [31:0]   ng, ndump, g0, g0a;
    wire [H*64-1:0] t0;
    wire [E*16-1:0] eng_flags;
    wire [2*E+1:0]  dflags;
    wire [3:0]    sflags;
    wire [5:0]    fflags;
    // WRST の間とその直後は前段の出口を受けない（rst を 1 段そろえる）
    // 最初の WRST が通るまでは前段・wsb・dsink をリセットに留める（既定の設定は全窓が止める窓で、データの道はまだ扱えない。
    //   動かすと ddcb の印が粘着の CORE_FLAGS[4] に残る。P-2 の sim で見つけた）
    reg           cfg_ok, rst_d;
    wire          dp_rst = rst || wrst || !cfg_ok;
    always @(posedge clk) begin
        if (rst) cfg_ok <= 1'b0; else if (wrst) cfg_ok <= 1'b1;
        rst_d <= dp_rst;
    end

    spw_regs #(.H(H), .E(E), .S(S), .NK(NK), .G_L2(G_L2), .BUILD_TAG(BUILD_TAG), .CORE_PORT(ADC), .PSPLIT(PSPLIT), .BASE_BEATS(BASE_BEATS)) u_regs (
        .clk(clk), .rst(rst),
        .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata), .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),
        .s_axi_bvalid(s_axi_bvalid), .s_axi_bresp(s_axi_bresp), .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata), .s_axi_rvalid(s_axi_rvalid), .s_axi_rresp(s_axi_rresp), .s_axi_rready(s_axi_rready),
        .t_now(t_now), .fire(fire), .wrst(wrst), .drain(drain), .dp_idle(dp_idle),
        .cfg_wk(cfg_wk), .cfg_dphi(cfg_dphi), .cfg_ns(cfg_ns), .cfg_fl(cfg_fl), .cfg_sl(cfg_sl), .cfg_g(cfg_g), .cfg_sh(cfg_sh),
        .ng(ng), .ndump(ndump), .cmd_run(cmd_run), .cmd_stop(cmd_stop),
        .g0(g0a), .t0(t0), .eng_flags(eng_flags), .ddr_flag(|dflags), .sink_flag(|sflags), .front_flag(|fflags));

    wire [E-1:0]   y_v;
    wire [E*4-1:0] y_ch;
    wire [E*W-1:0] y_re, y_im;
    spw_front #(.H(H), .E(E), .PSPLIT(PSPLIT), .BW(W)) u_front (
        .clk(clk), .rst_pfb(rst), .rst(dp_rst),
        .s_tdata(s_tdata), .s_tvalid(s_tvalid),
        .cfg_wk(cfg_wk), .cfg_dphi(cfg_dphi), .cfg_ns(cfg_ns), .cfg_fl(cfg_fl),
        .y_v(y_v), .y_ch(y_ch), .y_re(y_re), .y_im(y_im), .c_re(), .c_im(), .c_v(), .flags(fflags));

    wire [E-1:0]    d_v;
    wire [E*4-1:0]  d_w;
    wire [E*32-1:0] d_k;
    wire [E*12-1:0] d_ch;
    wire [E*64-1:0] d_data;
    wsb #(.H(H), .E(E), .S(S), .W(W), .G_L2(G_L2), .D(D), .NK(NK)) u_wsb (
        .clk(clk), .rst(rst_d), .y_v(y_v & {E{!rst_d}}), .y_ch(y_ch), .y_re(y_re), .y_im(y_im),
        .cfg_ns(cfg_ns), .cfg_fl(cfg_fl), .cfg_sl(cfg_sl), .cfg_sh(cfg_sh), .cfg_g(cfg_g), .ddr_base(DDR_BASE),
        .ng(ng), .ndump(ndump), .cmd_run(cmd_run), .cmd_stop(cmd_stop),
        .go(), .g0(g0), .g0a(g0a), .d_v(d_v), .d_w(d_w), .d_k(d_k), .d_ch(d_ch), .d_data(d_data), .flags(eng_flags), .dflags(dflags),
        .t_now(t_now), .t0(t0),
        .m_awaddr(m_awaddr), .m_awlen(m_awlen), .m_awvalid(m_awvalid), .m_awready(m_awready), .m_wdata(m_wdata), .m_wlast(m_wlast),
        .m_wvalid(m_wvalid), .m_wready(m_wready), .m_bvalid(m_bvalid),
        .m_araddr(m_araddr), .m_arvalid(m_arvalid), .m_arready(m_arready), .m_rdata(m_rdata), .m_rvalid(m_rvalid), .m_rlast(m_rlast));

    dsink #(.E(E), .H(H), .NU(NU), .G_L2(G_L2), .ADC(ADC)) u_sink (
        .clk(clk), .rst(rst_d), .d_v(d_v), .d_w(d_w), .d_k(d_k), .d_ch(d_ch), .d_data(d_data),
        .cfg_ns(cfg_ns), .cfg_sh(cfg_sh), .cfg_g(cfg_g), .ng(ng), .g0(g0), .g0a(g0a), .t0(t0),
        .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast), .drop(drop), .flags(sflags), .drain(drain), .idle(dp_idle));
endmodule
