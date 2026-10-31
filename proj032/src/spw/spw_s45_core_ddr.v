// SPDX-License-Identifier: BSD-3-Clause
//
// spw_s45_core_ddr — BD に module reference で置く SpW のコア（proj032 P-8、b2）。spw_s45_core（P-7、b1）に PL の DDR の口を足したもの
//
//   - 中身・ポートの名前・リセットの受け方は spw_s45_core と同じ（セルの名前 s45_core_c・s_axis・s_axi・gb_*・t_in・go_in・m_axis_rec・rec_drop）
//   - P-8: spw_core の DDR の口を AXI4 の master 4 本に出す（BD で smc_ddr を通して MIG へ）
//       m_ddrw : 書き手（ddrw、1 ADC に 1 つ）。64 bit・256 拍（2 KiB）。書きだけ
//       m_ddrr0..2: 読み手（ddrr、機関 e ごと）。128 bit・128 拍（2 KiB）。読みだけ
//     AxSIZE・AxBURST・WSTRB・BREADY・RREADY は ddrw・ddrr の中の定数と同じ値をここで出す（spw_core はこれらを外に出さない）。
//     **RREADY・BREADY は常に 1**（ddrr・ddrw は R・B を止めずに受ける作り）。BRESP・RRESP は見ない
//   - E は 3 に固定（読みの口を 3 本の名前で出すため）
`timescale 1ns / 1ps

module spw_s45_core_ddr #(
    parameter integer H          = 14,
    parameter integer E          = 3,
    parameter integer S          = 6,
    parameter integer NK         = 8,
    parameter integer G_L2       = 19,
    parameter integer ADC        = 0,           // CORE_PORT（[3:0] ADC・[11:8] タイル・[15:12] スライス）
    parameter integer BUILD_TAG  = 0,
    parameter integer BIT_KIND   = 7,
    parameter integer BIT_REV    = 3,
    parameter integer PROJ       = 3277568,     // 0x0032_0300（10 進で書く）
    parameter integer GB_K_RST   = 2
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis:s_axi:m_axis_rec:m_ddrw:m_ddrr0:m_ddrr1:m_ddrr2, ASSOCIATED_RESET aresetn:gb_dn_rstn" *)
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
    output wire [E:0]    rec_drop,
    // PL の DDR: 書き手
    output wire [31:0]   m_ddrw_awaddr,
    output wire [7:0]    m_ddrw_awlen,
    output wire [2:0]    m_ddrw_awsize,
    output wire [1:0]    m_ddrw_awburst,
    output wire          m_ddrw_awvalid,
    input  wire          m_ddrw_awready,
    output wire [63:0]   m_ddrw_wdata,
    output wire [7:0]    m_ddrw_wstrb,
    output wire          m_ddrw_wlast,
    output wire          m_ddrw_wvalid,
    input  wire          m_ddrw_wready,
    input  wire [1:0]    m_ddrw_bresp,
    input  wire          m_ddrw_bvalid,
    output wire          m_ddrw_bready,
    // PL の DDR: 読み手（機関 0..2）
    output wire [31:0]   m_ddrr0_araddr,
    output wire [7:0]    m_ddrr0_arlen,
    output wire [2:0]    m_ddrr0_arsize,
    output wire [1:0]    m_ddrr0_arburst,
    output wire          m_ddrr0_arvalid,
    input  wire          m_ddrr0_arready,
    input  wire [127:0]  m_ddrr0_rdata,
    input  wire [1:0]    m_ddrr0_rresp,
    input  wire          m_ddrr0_rlast,
    input  wire          m_ddrr0_rvalid,
    output wire          m_ddrr0_rready,
    output wire [31:0]   m_ddrr1_araddr,
    output wire [7:0]    m_ddrr1_arlen,
    output wire [2:0]    m_ddrr1_arsize,
    output wire [1:0]    m_ddrr1_arburst,
    output wire          m_ddrr1_arvalid,
    input  wire          m_ddrr1_arready,
    input  wire [127:0]  m_ddrr1_rdata,
    input  wire [1:0]    m_ddrr1_rresp,
    input  wire          m_ddrr1_rlast,
    input  wire          m_ddrr1_rvalid,
    output wire          m_ddrr1_rready,
    output wire [31:0]   m_ddrr2_araddr,
    output wire [7:0]    m_ddrr2_arlen,
    output wire [2:0]    m_ddrr2_arsize,
    output wire [1:0]    m_ddrr2_arburst,
    output wire          m_ddrr2_arvalid,
    input  wire          m_ddrr2_arready,
    input  wire [127:0]  m_ddrr2_rdata,
    input  wire [1:0]    m_ddrr2_rresp,
    input  wire          m_ddrr2_rlast,
    input  wire          m_ddrr2_rvalid,
    output wire          m_ddrr2_rready
);
    generate if (E != 3) begin : g_bad_e
        initial begin $display("ERROR: spw_s45_core_ddr は E = 3 だけ（E = %0d）", E); $finish; end
    end endgenerate

    reg rstn_q1 = 1'b0, rstn_q2 = 1'b0;
    (* max_fanout = 50 *) reg rstn_l = 1'b0;
    always @(posedge aclk) begin rstn_q1 <= aresetn; rstn_q2 <= rstn_q1; rstn_l <= rstn_q2; end
    assign s_axis_tready = 1'b1;

    // ddrw・ddrr の中の定数と同じ（ddrw: awlen 255・awsize 3・INCR・wstrb FF・bready 1 / ddrr: arlen 127・arsize 4・INCR・rready 1）
    assign m_ddrw_awsize = 3'd3, m_ddrw_awburst = 2'b01, m_ddrw_wstrb = 8'hFF, m_ddrw_bready = 1'b1;
    assign m_ddrr0_arlen = 8'd127, m_ddrr0_arsize = 3'd4, m_ddrr0_arburst = 2'b01, m_ddrr0_rready = 1'b1;
    assign m_ddrr1_arlen = 8'd127, m_ddrr1_arsize = 3'd4, m_ddrr1_arburst = 2'b01, m_ddrr1_rready = 1'b1;
    assign m_ddrr2_arlen = 8'd127, m_ddrr2_arsize = 3'd4, m_ddrr2_arburst = 2'b01, m_ddrr2_rready = 1'b1;

    wire [E*32-1:0]  araddr;
    wire [E-1:0]     arvalid;
    assign m_ddrr0_araddr = araddr[0*32 +: 32], m_ddrr0_arvalid = arvalid[0];
    assign m_ddrr1_araddr = araddr[1*32 +: 32], m_ddrr1_arvalid = arvalid[1];
    assign m_ddrr2_araddr = araddr[2*32 +: 32], m_ddrr2_arvalid = arvalid[2];

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
        .m_awaddr(m_ddrw_awaddr), .m_awlen(m_ddrw_awlen), .m_awvalid(m_ddrw_awvalid), .m_awready(m_ddrw_awready),
        .m_wdata(m_ddrw_wdata), .m_wlast(m_ddrw_wlast), .m_wvalid(m_ddrw_wvalid), .m_wready(m_ddrw_wready), .m_bvalid(m_ddrw_bvalid),
        .m_araddr(araddr), .m_arvalid(arvalid), .m_arready({m_ddrr2_arready, m_ddrr1_arready, m_ddrr0_arready}),
        .m_rdata({m_ddrr2_rdata, m_ddrr1_rdata, m_ddrr0_rdata}), .m_rvalid({m_ddrr2_rvalid, m_ddrr1_rvalid, m_ddrr0_rvalid}),
        .m_rlast({m_ddrr2_rlast, m_ddrr1_rlast, m_ddrr0_rlast}),
        .m_tdata(m_axis_rec_tdata), .m_tvalid(m_axis_rec_tvalid), .m_tready(m_axis_rec_tready), .m_tlast(m_axis_rec_tlast),
        .drop(rec_drop));
endmodule
