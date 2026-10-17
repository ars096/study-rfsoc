// SPDX-License-Identifier: BSD-3-Clause
//
// wide_s45_core — SAM45-Wide の ADC 1 本ぶんのコア（INTERFACE 2.2）。proj023 手順 3。s45_core（proj021）の Wide 版
//
// 中身:
//   - core_cmn（コアの共通 2.4: IF_ID・NSTREAM・ギアボックスの制御・TP・TANCH・FFT_N 0x80）。win_core から窓を除いたもの
//   - wide_core（SLICE の流れ s = 0, 1）
//   - RAW = 1 のときだけ raw_core（RAW の流れ s = 2。入力は s_axis_full = 外の axis_sel4 が 4 ADC から選んだもの。proj021 2-5 と同じ）
//   - AXI4-Lite の 1 → 3 の振り分け（s45_core と同じ取り引き 1 つずつ・全部レジスタで受け渡す形）
//   - レコードの束ね（rec_arb: TP・SPEC × 2・SNAP（RAW））
// ブロックデザインには module reference で `s45_core_i`（i = 0..3）として置く（**PS はセルの名前でコアを見つける**。モジュール名は違ってよい）。
// 全部が DSP ドメイン（256 MHz）。係数 ROM・ひねり係数 ROM はコアの外（4 コアで 1 つずつ、build.tcl がコア 0 の番地で引いて全コアに配る）。
//
// ---- 番地（コアの 64 KiB）----
//   0x0000–0x3FFF → core_cmn（0x0000–0x00FF 共通・0x0100– TP のレジスタ・0x2000– TP のリング）
//   0x4000–0x47FF → wide_core（流れ 0・1 のブロック。wide_core の 11 bit）
//   0x4800–0x4BFF → raw_core（RAW = 1 のコアだけ。流れ 2 のブロック）。他は 0 を返す

`timescale 1ns / 1ps

module wide_s45_core #(
    parameter integer BUILD_TAG          = 0,
    parameter integer TP                 = 1,
    parameter integer TPN_DEFAULT        = 512,
    parameter integer GB_K_RST           = 2,
    parameter integer BIT_KIND           = 1,
    parameter integer BIT_REV            = 1,
    parameter integer PROJ               = 2294016,   // = 0x0023_0100（10 進で書く）
    parameter integer CORE_PORT          = 0,
    parameter integer BASE_BEATS         = 2621440,
    parameter integer K_F                = 0,
    parameter integer ST_N               = 16384,
    parameter integer GF_L2              = 8,
    parameter integer N_ACC_DEFAULT      = 1280,
    parameter integer SHIFT_DEFAULT      = 7,
    parameter integer RAW                = 0,
    parameter integer RAW_N_ACC_DEFAULT  = 5120       // 10.24 ms（RAW のフレーム 512 ビート）
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis:s_axis_full:s_axi:m_axis_rec, ASSOCIATED_RESET aresetn:gb_dn_rstn" *)
    input  wire          aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire          aresetn,
    input  wire [255:0]  s_axis_tdata,
    input  wire          s_axis_tvalid,
    output wire          s_axis_tready,
    input  wire [255:0]  s_axis_full_tdata,
    input  wire          s_axis_full_tvalid,
    output wire          s_axis_full_tready,
    output wire [1:0]    full_sel,
    input  wire [15:0]   s_axi_awaddr,
    input  wire [2:0]    s_axi_awprot,
    input  wire          s_axi_awvalid,
    output wire          s_axi_awready,
    input  wire [31:0]   s_axi_wdata,
    input  wire [3:0]    s_axi_wstrb,
    input  wire          s_axi_wvalid,
    output wire          s_axi_wready,
    output wire [1:0]    s_axi_bresp,
    output reg           s_axi_bvalid,
    input  wire          s_axi_bready,
    input  wire [15:0]   s_axi_araddr,
    input  wire [2:0]    s_axi_arprot,
    input  wire          s_axi_arvalid,
    output wire          s_axi_arready,
    output reg  [31:0]   s_axi_rdata,
    output wire [1:0]    s_axi_rresp,
    output reg           s_axi_rvalid,
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
    input  wire [3:0]    tev_in,
    // 共有の ROM（コア 0 の番地で引いたものを全コアへ）
    output wire [10:0]   coef_addr,
    output wire          coef_addr_v,
    input  wire [1151:0] coef_in,
    input  wire [10:0]   coef_m,
    output wire [10:0]   tw_addr,
    input  wire [575:0]  tw_in,
    input  wire [10:0]   tw_k1,
    output wire [63:0]   m_axis_rec_tdata,
    output wire          m_axis_rec_tvalid,
    input  wire          m_axis_rec_tready,
    output wire          m_axis_rec_tlast,
    output wire          m_axis_rec_tuser,
    output wire [1:0]    rec_drop
);
    // リセットはコアの中で 3 段受けてから配る（s45_core と同じ。proj021 2-2a のビルド 4 回目）
    reg rstn_q1 = 1'b0, rstn_q2 = 1'b0;
    (* max_fanout = 50 *) reg rstn_l = 1'b0;
    always @(posedge aclk) begin rstn_q1 <= aresetn; rstn_q2 <= rstn_q1; rstn_l <= rstn_q2; end
    wire rst = ~rstn_l;
    assign s_axis_tready = 1'b1;

    // ---- 上流の口（s45_core と同じ）----
    localparam [2:0] S_IDLE = 3'd0, S_WREQ = 3'd1, S_WRSP = 3'd2, S_RREQ = 3'd3, S_RRSP = 3'd4, S_DONE = 3'd5;
    reg  [2:0]  st;
    reg  [15:0] q_addr;
    reg  [31:0] q_wdata;
    reg  [1:0]  q_dst;                 // 0 = 共通・1 = wide・2 = RAW・3 = 無し
    function automatic [1:0] dst(input [15:0] a);
        dst = (a[15:14] == 2'd0) ? 2'd0 :
              (a[15:11] == 5'b01000) ? 2'd1 :
              (RAW != 0 && a[15:10] == 6'b010010) ? 2'd2 : 2'd3;
    endfunction
    wire take_w = (st == S_IDLE) && s_axi_awvalid && s_axi_wvalid;
    wire take_r = (st == S_IDLE) && s_axi_arvalid && !take_w;
    assign s_axi_awready = take_w;
    // **ビルド 5 回目の .bit に無かった**（実機で NSTREAM が IF_ID の値に読めた。2026-10-15）。iverilog の tb は arready の z を
    //   「準備よし」と読んで通っていた。Vivado は Synth 8-3848（ドライバの無いネット）を警告していた → build.tcl で止める
    assign s_axi_arready = take_r;
    assign s_axi_wready  = take_w;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_rresp   = 2'b00;

    wire d_aw = (st == S_WREQ), d_ar = (st == S_RREQ), d_b = (st == S_WRSP), d_r = (st == S_RRSP);
    wire [3:0]  awr, wr_, bv, arr, rv;
    wire [31:0] rd [0:3];
    assign awr[3] = 1'b1; assign wr_[3] = 1'b1; assign bv[3] = 1'b1; assign arr[3] = 1'b1; assign rv[3] = 1'b1; assign rd[3] = 32'd0;
    always @(posedge aclk) begin
        if (rst) begin
            st <= S_IDLE; q_addr <= 16'd0; q_wdata <= 32'd0; q_dst <= 2'd0;
            s_axi_bvalid <= 1'b0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0;
        end else begin
            case (st)
                S_IDLE: if (take_w) begin st <= S_WREQ; q_addr <= s_axi_awaddr; q_wdata <= s_axi_wdata; q_dst <= dst(s_axi_awaddr); end
                        else if (take_r) begin st <= S_RREQ; q_addr <= s_axi_araddr; q_dst <= dst(s_axi_araddr); end
                S_WREQ: if (awr[q_dst] & wr_[q_dst]) st <= S_WRSP;
                S_WRSP: if (bv[q_dst]) begin s_axi_bvalid <= 1'b1; st <= S_DONE; end
                S_RREQ: if (arr[q_dst]) st <= S_RRSP;
                S_RRSP: if (rv[q_dst]) begin s_axi_rvalid <= 1'b1; s_axi_rdata <= rd[q_dst]; st <= S_DONE; end
                S_DONE: begin
                    if (s_axi_bvalid && s_axi_bready) begin s_axi_bvalid <= 1'b0; st <= S_IDLE; end
                    if (s_axi_rvalid && s_axi_rready) begin s_axi_rvalid <= 1'b0; st <= S_IDLE; end
                end
                default: st <= S_IDLE;
            endcase
        end
    end

    // ---- コアの共通 ----
    wire        fftn_we;
    wire [7:0]  fftn_wd;
    wire [31:0] fftn_rd;
    wire [63:0] c_d, w_d, r_d;
    wire        c_v, c_r, c_l, c_u, w_v, w_r, w_l, w_u, r_v, r_r, r_l, r_u;
    wire        c_drop, r_drop;
    wire [1:0]  w_drop;
    core_cmn #(.BUILD_TAG(BUILD_TAG), .TP(TP), .TPN_DEFAULT(TPN_DEFAULT), .GB_K_RST(GB_K_RST), .BIT_KIND(BIT_KIND),
               .BIT_REV(BIT_REV), .PROJ(PROJ), .CORE_PORT(CORE_PORT), .NSTREAM(RAW != 0 ? 3 : 2), .BASE_BEATS(BASE_BEATS)) u_cmn (
        .aclk(aclk), .aresetn(rstn_l), .s_axis_tdata(s_axis_tdata), .s_axis_tvalid(s_axis_tvalid),
        .s_axi_awaddr(q_addr), .s_axi_awvalid(d_aw && q_dst == 2'd0), .s_axi_awready(awr[0]),
        .s_axi_wdata(q_wdata), .s_axi_wvalid(d_aw && q_dst == 2'd0), .s_axi_wready(wr_[0]),
        .s_axi_bvalid(bv[0]), .s_axi_bready(d_b && q_dst == 2'd0),
        .s_axi_araddr(q_addr), .s_axi_arvalid(d_ar && q_dst == 2'd0), .s_axi_arready(arr[0]),
        .s_axi_rdata(rd[0]), .s_axi_rvalid(rv[0]), .s_axi_rready(d_r && q_dst == 2'd0),
        .gb_hold(gb_hold), .gb_adj(gb_adj), .gb_dn_rstn(gb_dn_rstn), .gb_k(gb_k), .gb_stat(gb_stat), .adc_stat(adc_stat),
        .t_in(t_in), .go_in(go_in), .tev_in(tev_in), .fftn_we(fftn_we), .fftn_wdata(fftn_wd), .fftn_rd(fftn_rd),
        .m_axis_rec_tdata(c_d), .m_axis_rec_tvalid(c_v), .m_axis_rec_tready(c_r), .m_axis_rec_tlast(c_l), .m_axis_rec_tuser(c_u),
        .rec_drop(c_drop));

    // ---- SLICE の流れ 0・1 ----
    wide_core #(.SID_S(0), .REC_CORE(CORE_PORT % 16), .K_F(K_F), .ST_N(ST_N), .GF_L2(GF_L2), .N_ACC_DEFAULT(N_ACC_DEFAULT),
                .SHIFT_DEFAULT(SHIFT_DEFAULT), .BUILD_TAG(BUILD_TAG)) u_wide (
        .aclk(aclk), .aresetn(rstn_l), .s_axis_tdata(s_axis_tdata), .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(),
        .s_axi_awaddr(q_addr[10:0]), .s_axi_awvalid(d_aw && q_dst == 2'd1), .s_axi_awready(awr[1]),
        .s_axi_wdata(q_wdata), .s_axi_wvalid(d_aw && q_dst == 2'd1), .s_axi_wready(wr_[1]), .s_axi_bresp(),
        .s_axi_bvalid(bv[1]), .s_axi_bready(d_b && q_dst == 2'd1),
        .s_axi_araddr(q_addr[10:0]), .s_axi_arvalid(d_ar && q_dst == 2'd1), .s_axi_arready(arr[1]),
        .s_axi_rdata(rd[1]), .s_axi_rresp(), .s_axi_rvalid(rv[1]), .s_axi_rready(d_r && q_dst == 2'd1),
`ifdef FFTN_POSCTL
        .fftn_we(1'b0),                                  // 陽性対照: コアの FFT_N の書きを wide_core に渡さない
`else
        .fftn_we(fftn_we),
`endif
        .fftn_wdata(fftn_wd), .fftn_rd(fftn_rd),
        .t_in(t_in), .go_in(go_in), .tev_in(tev_in),
        .coef_addr(coef_addr), .coef_addr_v(coef_addr_v), .coef_in(coef_in), .coef_m(coef_m),
        .tw_addr(tw_addr), .tw_in(tw_in), .tw_k1(tw_k1),
        .m_axis_rec_tdata(w_d), .m_axis_rec_tvalid(w_v), .m_axis_rec_tready(w_r), .m_axis_rec_tlast(w_l), .m_axis_rec_tuser(w_u),
        .rec_drop(w_drop), .dbg_ip_tdata(), .dbg_ip_k1(), .dbg_ip_v());

    // ---- RAW の流れ 2（コア 0 だけ）----
    generate
        if (RAW != 0) begin : g_raw
            raw_core #(.N_ACC_DEFAULT(RAW_N_ACC_DEFAULT), .SID_S(2), .REC_CORE(CORE_PORT % 16)) u_raw (
                .aclk(aclk), .aresetn(rstn_l),
                .s_axis_tdata(s_axis_full_tdata), .s_axis_tvalid(s_axis_full_tvalid), .s_axis_tready(s_axis_full_tready),
                .s_axi_awaddr({6'd0, q_addr[9:0]}), .s_axi_awprot(3'd0), .s_axi_awvalid(d_aw && q_dst == 2'd2), .s_axi_awready(awr[2]),
                .s_axi_wdata(q_wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(d_aw && q_dst == 2'd2), .s_axi_wready(wr_[2]),
                .s_axi_bresp(), .s_axi_bvalid(bv[2]), .s_axi_bready(d_b && q_dst == 2'd2),
                .s_axi_araddr({6'd0, q_addr[9:0]}), .s_axi_arprot(3'd0), .s_axi_arvalid(d_ar && q_dst == 2'd2), .s_axi_arready(arr[2]),
                .s_axi_rdata(rd[2]), .s_axi_rresp(), .s_axi_rvalid(rv[2]), .s_axi_rready(d_r && q_dst == 2'd2),
                .t_in(t_in), .go_in(go_in), .tev_in(tev_in), .src_sel(full_sel),
                .m_axis_rec_tdata(r_d), .m_axis_rec_tvalid(r_v), .m_axis_rec_tready(r_r), .m_axis_rec_tlast(r_l),
                .m_axis_rec_tuser(r_u), .rec_drop(r_drop));
        end else begin : g_noraw
            assign awr[2] = 1'b1; assign wr_[2] = 1'b1; assign bv[2] = 1'b1; assign arr[2] = 1'b1; assign rv[2] = 1'b1; assign rd[2] = 32'd0;
            assign s_axis_full_tready = 1'b1; assign full_sel = 2'd0;
            assign r_d = 64'd0; assign r_v = 1'b0; assign r_l = 1'b0; assign r_u = 1'b0; assign r_drop = 1'b0;
        end
    endgenerate

    // ---- レコードの束ね（TP・SPEC・SNAP）→ s45_ring ----
    rec_arb #(.N(3)) u_arb (.clk(aclk), .rst(rst),
        .s_tdata({r_d, w_d, c_d}), .s_tvalid({r_v, w_v, c_v}), .s_tready({r_r, w_r, c_r}), .s_tlast({r_l, w_l, c_l}), .s_tuser({r_u, w_u, c_u}),
        .m_tdata(m_axis_rec_tdata), .m_tvalid(m_axis_rec_tvalid), .m_tready(m_axis_rec_tready),
        .m_tlast(m_axis_rec_tlast), .m_tuser(m_axis_rec_tuser));

    // ---- 読み始めなかったダンプの数（1 クロックに最大 4 → 溜めて 3 までずつ。s45_core と同じ）----
    wire [2:0] drop_sum = {2'd0, c_drop} + {2'd0, w_drop[0]} + {2'd0, w_drop[1]} + {2'd0, r_drop};
    reg  [7:0] drop_pend;
    reg  [1:0] drop_q;
    wire [7:0] drop_tot = drop_pend + {5'd0, drop_sum};
    always @(posedge aclk) begin
        if (rst) begin drop_pend <= 8'd0; drop_q <= 2'd0; end
        else begin
            drop_q    <= (drop_tot > 8'd3) ? 2'd3 : drop_tot[1:0];
            drop_pend <= (drop_tot > 8'd3) ? drop_tot - 8'd3 : 8'd0;
        end
    end
    assign rec_drop = drop_q;
endmodule
