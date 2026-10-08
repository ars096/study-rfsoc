// SPDX-License-Identifier: BSD-3-Clause
//
// s45_core — ADC 1 本ぶんのコア（INTERFACE.md v2 の 2.2）。proj021 手順 2-1 で起こした
//
// 中身:
//   - win_core（src/common/win_core.v）: コアの共通（2.4。ギアボックスの制御・TP・時刻の錨）＋ DDC の流れ s = 0..NW−1
//   - FULL = 1 のときだけ spec_core（src/common/spec_core.v）: FULL の流れ s = NW。入力は s_axis_full（外の axis_sel4 が
//     4 ADC から選んだもの）。選ぶのはこの流れの SRC（src_sel → full_sel の出口 → axis_sel4）
//   - AXI4-Lite の 1 → 2 の振り分け（下）
//
// ブロックデザインには module reference で `s45_core_i`（i = 0..3 = ADC_A..D）として置く。**PS はこの名前でコアを見つける**（2.3）。
// 全部が DSP ドメイン（256 MHz）。
//
// ---- 番地（コアの 1 MiB。手順 2-1。2-2 で 64 KiB に縮める）----
//   0x04000 + 0x400·NW（FULL の流れのブロック）     → spec_core の 0x0000–0x03FF
//   0xC0000–0xCFFFF（FULL の仮の読み窓、約束の外）  → spec_core の 0x0000–0xFFFF
//   ほか                                            → win_core（番地はそのまま。win_core.v の冒頭）
//   FULL = 0 のコアでは全部 win_core へ（FULL の範囲は win_core が 0 / 0xDEADBEEF を返す）
//   **FULL = 1 は NW ≦ 2 のときだけ**（0xC0000 は窓 2 の仮の読み窓と重なる。仮の読み窓は 2-2 で無くなる）
//
// ---- 振り分け ----
// 取り引きを 1 つずつ（書きと読みのどちらか 1 つ、応答を返し終えるまで次を受けない）。上流の口・下流の口とも全部レジスタで
// 受け渡すので、番地の比べは 1 クロックの中で SmartConnect の口に戻らない（`-1` の壁を足さない）。
// 1 回の取り引きは 1b より 3〜4 クロック長い（AXI4-Lite の読み 1 回 ≒ 20 クロックのうち）

`timescale 1ns / 1ps

module s45_core #(
    // ---- win_core（コアの共通・DDC の流れ）----
    parameter integer NW            = 2,
    parameter integer N_ACC_DEFAULT = 6250,
    parameter integer SHIFT_DEFAULT = 4,
    parameter integer BUILD_TAG     = 0,
    parameter integer TP            = 1,
    parameter integer TPN_DEFAULT   = 512,
    parameter integer GB_K_RST      = 2,
    parameter integer G_L2          = 19,
    parameter integer BIT_KIND      = 2,
    parameter integer BIT_REV       = 1,
    parameter integer PROJ          = 32'h0021_0200,
    parameter integer CORE_PORT     = 0,
    parameter integer BASE_BEATS    = 2621440,
    // ---- FULL の流れ（spec_core）----
    parameter integer FULL               = 0,
    parameter integer FULL_FFT_CFG       = 0,
    parameter integer FULL_BUILD_TAG     = 0,
    parameter integer FULL_N_ACC_DEFAULT = 50000,
    parameter integer FULL_SHIFT_DEFAULT = 4,
    parameter integer FULL_STABLE_N      = 16384
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis:s_axis_full:s_axi, ASSOCIATED_RESET aresetn:gb_dn_rstn" *)
    input  wire         aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire         aresetn,
    // このコアの ADC（ギアボックスの出口）
    input  wire [255:0] s_axis_tdata,
    input  wire         s_axis_tvalid,
    output wire         s_axis_tready,
    // FULL の流れの入力（axis_sel4 の出口。FULL = 0 なら繋がない）
    input  wire [255:0] s_axis_full_tdata,
    input  wire         s_axis_full_tvalid,
    output wire         s_axis_full_tready,
    input  wire [31:0]  full_gb_stat,
    input  wire [31:0]  full_adc_stat,
    output wire [1:0]   full_sel,
    // AXI4-Lite
    input  wire [19:0]  s_axi_awaddr,
    input  wire [2:0]   s_axi_awprot,
    input  wire         s_axi_awvalid,
    output wire         s_axi_awready,
    input  wire [31:0]  s_axi_wdata,
    input  wire [3:0]   s_axi_wstrb,
    input  wire         s_axi_wvalid,
    output wire         s_axi_wready,
    output wire [1:0]   s_axi_bresp,
    output reg          s_axi_bvalid,
    input  wire         s_axi_bready,
    input  wire [19:0]  s_axi_araddr,
    input  wire [2:0]   s_axi_arprot,
    input  wire         s_axi_arvalid,
    output wire         s_axi_arready,
    output reg  [31:0]  s_axi_rdata,
    output wire [1:0]   s_axi_rresp,
    output reg          s_axi_rvalid,
    input  wire         s_axi_rready,
    // ギアボックスの制御と見張り（win_core のまま）
    output wire         gb_hold,
    output wire [1:0]   gb_adj,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 gb_dn_rstn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    output wire         gb_dn_rstn,
    output wire [5:0]   gb_k,
    input  wire [31:0]  gb_stat,
    input  wire [31:0]  adc_stat,
    // 時刻（time_core から）
    input  wire [63:0]  t_in,
    input  wire         go_in,
    input  wire [3:0]   tev_in
);
    wire rst = ~aresetn;
    initial if (FULL != 0 && NW > 2) begin $display("s45_core: FULL = 1 は NW ≦ 2 のときだけ（NW %0d）", NW); $finish; end
    localparam [19:0] FBLK = 20'h04000 + 20'h00400 * NW;     // FULL の流れのブロック

    function automatic is_full(input [19:0] a);
        is_full = (FULL != 0) && ((a[19:10] == FBLK[19:10]) || (a[19:16] == 4'hC));
    endfunction

    // ---- 上流の口 ----
    localparam [2:0] S_IDLE = 3'd0, S_WREQ = 3'd1, S_WRSP = 3'd2, S_RREQ = 3'd3, S_RRSP = 3'd4, S_DONE = 3'd5;
    reg  [2:0]  st;
    reg  [19:0] q_addr;
    reg  [31:0] q_wdata;
    reg  [3:0]  q_wstrb;
    reg         q_full;
    wire        take_w = (st == S_IDLE) && s_axi_awvalid && s_axi_wvalid;
    wire        take_r = (st == S_IDLE) && s_axi_arvalid && !take_w;
    assign s_axi_awready = take_w;
    assign s_axi_wready  = take_w;
    assign s_axi_arready = take_r;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_rresp   = 2'b00;

    // ---- 下流の口（win_core = 0、spec_core = 1）----
    wire        d_awvalid = (st == S_WREQ);
    wire        d_arvalid = (st == S_RREQ);
    wire        w_awready, w_wready, w_bvalid, w_arready, w_rvalid;
    wire [31:0] w_rdata;
    wire        f_awready, f_wready, f_bvalid, f_arready, f_rvalid;
    wire [31:0] f_rdata;
    wire        dn_awready = q_full ? (f_awready & f_wready) : (w_awready & w_wready);
    wire        dn_arready = q_full ? f_arready : w_arready;
    wire        dn_bvalid  = q_full ? f_bvalid  : w_bvalid;
    wire        dn_rvalid  = q_full ? f_rvalid  : w_rvalid;
    wire [31:0] dn_rdata   = q_full ? f_rdata   : w_rdata;
    wire        d_bready   = (st == S_WRSP);
    wire        d_rready   = (st == S_RRSP);
    // spec_core の番地（16 bit）: 流れのブロックは 0x0000–0x03FF、仮の読み窓はそのまま
    wire [15:0] f_addr = (q_addr[19:16] == 4'hC) ? q_addr[15:0] : {6'd0, q_addr[9:0]};

    always @(posedge aclk) begin
        if (rst) begin
            st <= S_IDLE; q_addr <= 20'd0; q_wdata <= 32'd0; q_wstrb <= 4'd0; q_full <= 1'b0;
            s_axi_bvalid <= 1'b0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0;
        end else begin
            case (st)
                S_IDLE: begin
                    if (take_w) begin
                        st <= S_WREQ; q_addr <= s_axi_awaddr; q_wdata <= s_axi_wdata; q_wstrb <= s_axi_wstrb; q_full <= is_full(s_axi_awaddr);
                    end else if (take_r) begin
                        st <= S_RREQ; q_addr <= s_axi_araddr; q_full <= is_full(s_axi_araddr);
                    end
                end
                S_WREQ: if (dn_awready) st <= S_WRSP;
                S_WRSP: if (dn_bvalid) begin s_axi_bvalid <= 1'b1; st <= S_DONE; end
                S_RREQ: if (dn_arready) st <= S_RRSP;
                S_RRSP: if (dn_rvalid) begin s_axi_rvalid <= 1'b1; s_axi_rdata <= dn_rdata; st <= S_DONE; end
                S_DONE: begin
                    if (s_axi_bvalid && s_axi_bready) begin s_axi_bvalid <= 1'b0; st <= S_IDLE; end
                    if (s_axi_rvalid && s_axi_rready) begin s_axi_rvalid <= 1'b0; st <= S_IDLE; end
                end
                default: st <= S_IDLE;
            endcase
        end
    end

    // ---- win_core（コアの共通・DDC の流れ）----
    win_core #(.NW(NW), .N_ACC_DEFAULT(N_ACC_DEFAULT), .SHIFT_DEFAULT(SHIFT_DEFAULT), .BUILD_TAG(BUILD_TAG), .TP(TP),
               .TPN_DEFAULT(TPN_DEFAULT), .GB_K_RST(GB_K_RST), .G_L2(G_L2), .BIT_KIND(BIT_KIND), .BIT_REV(BIT_REV),
               .PROJ(PROJ), .CORE_PORT(CORE_PORT), .NFULL(FULL != 0 ? 1 : 0), .BASE_BEATS(BASE_BEATS)) u_win (
        .aclk(aclk), .aresetn(aresetn),
        .s_axis_tdata(s_axis_tdata), .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(s_axis_tready),
        .s_axi_awaddr(q_addr), .s_axi_awprot(3'd0), .s_axi_awvalid(d_awvalid && !q_full), .s_axi_awready(w_awready),
        .s_axi_wdata(q_wdata), .s_axi_wstrb(q_wstrb), .s_axi_wvalid(d_awvalid && !q_full), .s_axi_wready(w_wready),
        .s_axi_bresp(), .s_axi_bvalid(w_bvalid), .s_axi_bready(d_bready && !q_full),
        .s_axi_araddr(q_addr), .s_axi_arprot(3'd0), .s_axi_arvalid(d_arvalid && !q_full), .s_axi_arready(w_arready),
        .s_axi_rdata(w_rdata), .s_axi_rresp(), .s_axi_rvalid(w_rvalid), .s_axi_rready(d_rready && !q_full),
        .gb_hold(gb_hold), .gb_adj(gb_adj), .gb_dn_rstn(gb_dn_rstn), .gb_k(gb_k), .gb_stat(gb_stat), .adc_stat(adc_stat),
        .t_in(t_in), .go_in(go_in), .tev_in(tev_in));

    // ---- spec_core（FULL の流れ）----
    generate
        if (FULL != 0) begin : g_full
            spec_core #(.N_ACC_DEFAULT(FULL_N_ACC_DEFAULT), .SHIFT_DEFAULT(FULL_SHIFT_DEFAULT), .FFT_CFG(FULL_FFT_CFG),
                        .BUILD_TAG(FULL_BUILD_TAG), .STABLE_N(FULL_STABLE_N), .GB_K_RST(GB_K_RST), .SID_S(NW),
                        .TPN_DEFAULT(TPN_DEFAULT)) u_full (
                .aclk(aclk), .aresetn(aresetn),
                .s_axis_tdata(s_axis_full_tdata), .s_axis_tvalid(s_axis_full_tvalid), .s_axis_tready(s_axis_full_tready),
                .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(full_gb_stat), .adc_stat(full_adc_stat),
                .s_axi_awaddr(f_addr), .s_axi_awprot(3'd0), .s_axi_awvalid(d_awvalid && q_full), .s_axi_awready(f_awready),
                .s_axi_wdata(q_wdata), .s_axi_wstrb(q_wstrb), .s_axi_wvalid(d_awvalid && q_full), .s_axi_wready(f_wready),
                .s_axi_bresp(), .s_axi_bvalid(f_bvalid), .s_axi_bready(d_bready && q_full),
                .s_axi_araddr(f_addr), .s_axi_arprot(3'd0), .s_axi_arvalid(d_arvalid && q_full), .s_axi_arready(f_arready),
                .s_axi_rdata(f_rdata), .s_axi_rresp(), .s_axi_rvalid(f_rvalid), .s_axi_rready(d_rready && q_full),
                .t_in(t_in), .go_in(go_in), .tev_in(tev_in), .src_sel(full_sel));
        end else begin : g_nofull
            assign s_axis_full_tready = 1'b1;
            assign full_sel = 2'd0;
            assign f_awready = 1'b0; assign f_wready = 1'b0; assign f_bvalid = 1'b0;
            assign f_arready = 1'b0; assign f_rvalid = 1'b0; assign f_rdata = 32'd0;
        end
    endgenerate
endmodule
