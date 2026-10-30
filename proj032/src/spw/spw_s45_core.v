// SPDX-License-Identifier: BSD-3-Clause
//
// spw_s45_core — BD に module reference で置く SpW のコア（proj032 P-7）。中身は spw_core（レジスタ ＋ 共通部 ＋ 前段 ＋ wsb ＋ dsink ＋ 合流）
//
//   - セルの名前は s45_core_c（PS はセルの名前でコアを見つける。SAM45-Fine と同じ）。ポートの名前も g24_s45_core に揃えた
//     （s_axis = ギアボックスの出口・s_axi = 64 KiB・gb_* ・t_in・go_in・m_axis_rec・rec_drop）
//   - リセットはコアの中で 3 段受けてから配る（g24_s45_core と同じ）
//   - P-7 は PL の DDR（MIG）を載せない: wsb の DDR の口は全部 0 で縛る（AW・W・AR を受けない）。
//     **窓の履歴の枠はチップ内（WSL < S）だけを使う**。DDR の枠を指した窓は WRST の約束では通るが、書き手が進まず機関の FLAGS に出る
//   - m_axis_rec は 128 bit（ring128 の入口）。rec_drop[E−1:0] は受け手で捨てたダンプ、[E] は捨てた TP のレコード（ring128 の ext_drop、NX = E ＋ 1）
`timescale 1ns / 1ps

module spw_s45_core #(
    parameter integer H          = 14,
    parameter integer E          = 3,
    parameter integer S          = 6,
    parameter integer NK         = 8,
    parameter integer G_L2       = 19,
    parameter integer ADC        = 0,           // CORE_PORT（[3:0] ADC・[11:8] タイル・[15:12] スライス）
    parameter integer BUILD_TAG  = 0,
    parameter integer BIT_KIND   = 7,
    parameter integer BIT_REV    = 1,
    parameter integer PROJ       = 3277568,     // 0x0032_0300（10 進で書く）
    parameter integer GB_K_RST   = 2
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis:s_axi:m_axis_rec, ASSOCIATED_RESET aresetn:gb_dn_rstn" *)
    input  wire          aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire          aresetn,
    input  wire [255:0]  s_axis_tdata,
    input  wire          s_axis_tvalid,
    output wire          s_axis_tready,
    input  wire [15:0]   s_axi_awaddr,
    input  wire [2:0]    s_axi_awprot,
    input  wire          s_axi_awvalid,
    output wire          s_axi_awready,
    input  wire [31:0]   s_axi_wdata,
    input  wire [3:0]    s_axi_wstrb,
    input  wire          s_axi_wvalid,
    output wire          s_axi_wready,
    output wire [1:0]    s_axi_bresp,
    output wire          s_axi_bvalid,
    input  wire          s_axi_bready,
    input  wire [15:0]   s_axi_araddr,
    input  wire [2:0]    s_axi_arprot,
    input  wire          s_axi_arvalid,
    output wire          s_axi_arready,
    output wire [31:0]   s_axi_rdata,
    output wire [1:0]    s_axi_rresp,
    output wire          s_axi_rvalid,
    input  wire          s_axi_rready,
    output wire          gb_hold,
    output wire [1:0]    gb_adj,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 gb_dn_rstn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    output wire          gb_dn_rstn,
    output wire [5:0]    gb_k,
    input  wire [31:0]   gb_stat,
    input  wire [31:0]   adc_stat,
    input  wire [63:0]   t_in,
    input  wire          go_in,
    output wire [127:0]  m_axis_rec_tdata,
    output wire          m_axis_rec_tvalid,
    input  wire          m_axis_rec_tready,
    output wire          m_axis_rec_tlast,
    output wire [E:0]    rec_drop
);
    reg rstn_q1 = 1'b0, rstn_q2 = 1'b0;
    (* max_fanout = 50 *) reg rstn_l = 1'b0;
    always @(posedge aclk) begin rstn_q1 <= aresetn; rstn_q2 <= rstn_q1; rstn_l <= rstn_q2; end
    assign s_axis_tready = 1'b1;

    spw_core #(.H(H), .E(E), .S(S), .NK(NK), .G_L2(G_L2), .ADC(ADC), .BUILD_TAG(BUILD_TAG),
               .BIT_KIND(BIT_KIND), .BIT_REV(BIT_REV), .PROJ(PROJ), .GB_K_RST(GB_K_RST)) u_core (
        .clk(aclk), .rst(!rstn_l),
        .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata), .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),
        .s_axi_bvalid(s_axi_bvalid), .s_axi_bresp(s_axi_bresp), .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata), .s_axi_rvalid(s_axi_rvalid), .s_axi_rresp(s_axi_rresp), .s_axi_rready(s_axi_rready),
        .s_tdata(s_axis_tdata), .s_tvalid(s_axis_tvalid),
        .gb_hold(gb_hold), .gb_adj(gb_adj), .gb_dn_rstn(gb_dn_rstn), .gb_k(gb_k), .gb_stat(gb_stat), .adc_stat(adc_stat),
        .t_now(t_in), .fire(go_in),
        // P-7: PL の DDR は無い（全部 0 で縛る）
        .m_awaddr(), .m_awlen(), .m_awvalid(), .m_awready(1'b0), .m_wdata(), .m_wlast(), .m_wvalid(), .m_wready(1'b0), .m_bvalid(1'b0),
        .m_araddr(), .m_arvalid(), .m_arready({E{1'b0}}), .m_rdata({E*128{1'b0}}), .m_rvalid({E{1'b0}}), .m_rlast({E{1'b0}}),
        .m_tdata(m_axis_rec_tdata), .m_tvalid(m_axis_rec_tvalid), .m_tready(m_axis_rec_tready), .m_tlast(m_axis_rec_tlast),
        .drop(rec_drop));
endmodule
