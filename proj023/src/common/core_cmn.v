// SPDX-License-Identifier: BSD-3-Clause
//
// core_cmn — ADC のコアの共通（INTERFACE 2.4）だけを win_core から抜き出したもの（proj023 手順 3。窓の無い SAM45-Wide のコアのため）
//
// win_core（proj021-m0）の「コアの共通」の部分を、番地・意味・段数を変えずに写した:
//   - 0x0000–0x00FF コアの共通: 0x00 IF_ID / 0x04 PROJ / 0x08 NSTREAM / 0x0C CAPS / 0x10 BASE_BEATS / 0x14 BUILD / 0x18 CORE_PORT /
//     0x20 CTRL（[0] TP_RUN・[2] TP_ARM・[3] 取り消し・[4] TANCH）/ 0x24·28 TFIN / 0x2C GB_K / 0x34 GB_STAT / 0x38 ADC_STAT /
//     0x3C·40 ANCH_F / 0x44·48 ANCH_T / 0x4C ANCH_STAT / 0x50·54 TP_RUN_T / 0x58 OVR_CNT / 0x5C GAP_CNT
//     **＋ 0x80 FFT_N（proj023、INTERFACE 2.4。SLICE の流れを持つコアだけ。書きは fftn_we・fftn_wdata で外へ、読みは fftn_rd を返す）**
//   - 0x0100–0x01FF TP のレジスタ / 0x2000–0x3FFF TP のリング（tp_core、TP のレコード）
//   - ギアボックスの制御（gb_hold・gb_adj・gb_dn_rstn・gb_k）と見張りの読み（gb_stat・adc_stat）
// 窓（pfb_core・ddc_core・wspec_core・rec_fr）は持たない。流れのブロック（0x4000〜）は持ち主（wide_s45_core）が振り分ける。
// win_core の番地の判定（ar_com = 0x0000–0x3FFF）・応答の段数（5 クロック）・候補の 1 段受けはそのまま。

`timescale 1ns / 1ps

module core_cmn #(
    parameter integer BUILD_TAG     = 0,
    parameter integer TP            = 1,
    parameter integer TPN_DEFAULT   = 512,
    parameter integer GB_K_RST      = 2,
    parameter integer BIT_KIND      = 1,
    parameter integer BIT_REV       = 1,
    parameter integer PROJ          = 2294016,   // = 0x0023_0100（10 進で書く。proj021 の注意）
    parameter integer CORE_PORT     = 0,
    parameter integer NSTREAM       = 2,
    parameter integer BASE_BEATS    = 2621440
)(
    input  wire         aclk,
    input  wire         aresetn,
    input  wire [255:0] s_axis_tdata,
    input  wire         s_axis_tvalid,
    input  wire [15:0]  s_axi_awaddr,
    input  wire         s_axi_awvalid,
    output wire         s_axi_awready,
    input  wire [31:0]  s_axi_wdata,
    input  wire         s_axi_wvalid,
    output wire         s_axi_wready,
    output reg          s_axi_bvalid,
    input  wire         s_axi_bready,
    input  wire [15:0]  s_axi_araddr,
    input  wire         s_axi_arvalid,
    output wire         s_axi_arready,
    output reg  [31:0]  s_axi_rdata,
    output reg          s_axi_rvalid,
    input  wire         s_axi_rready,
    output wire         gb_hold,
    output wire [1:0]   gb_adj,
    output reg          gb_dn_rstn,
    output wire [5:0]   gb_k,
    input  wire [31:0]  gb_stat,
    input  wire [31:0]  adc_stat,
    input  wire [63:0]  t_in,
    input  wire         go_in,
    input  wire [3:0]   tev_in,
    // FFT_N（0x80）
    output wire         fftn_we,
    output wire [7:0]   fftn_wdata,
    input  wire [31:0]  fftn_rd,
    // TP のレコード
    output wire [63:0]  m_axis_rec_tdata,
    output wire         m_axis_rec_tvalid,
    input  wire         m_axis_rec_tready,
    output wire         m_axis_rec_tlast,
    output wire         m_axis_rec_tuser,
    output wire         rec_drop
);
    localparam integer FW = 48;
    localparam [7:0]   BK8 = BIT_KIND, BR8 = BIT_REV;
    localparam [15:0]  CP16 = CORE_PORT;
    localparam [31:0]  IF_ID = {8'd2, BK8, BR8, 8'd1};
    wire rst = ~aresetn;

    (* max_fanout = 32 *) reg [63:0] t_loc;
    reg        go_loc;
    reg [3:0]  tev_loc;
    always @(posedge aclk) begin t_loc <= t_in; go_loc <= go_in; tev_loc <= tev_in; end
    wire a_ovr, a_gap;
    adc_ev u_aev (.clk(aclk), .rst(rst), .tdata(s_axis_tdata), .tvalid(s_axis_tvalid), .ovr(a_ovr), .gap(a_gap));

    // ---- 書き込み ----
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    wire wr_com = (s_axi_awaddr[15:8] == 8'h00);
    wire wr_tpr = (s_axi_awaddr[15:8] == 8'h01);
    always @(posedge aclk) begin
        if (rst) s_axi_bvalid <= 1'b0;
        else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) s_axi_bvalid <= 1'b1;
        end
    end
    assign fftn_we    = wr_go && wr_com && s_axi_awaddr[7:2] == 6'h20;          // 0x80 FFT_N
    assign fftn_wdata = s_axi_wdata[7:0];

    // ---- ギアボックス ----
    reg [5:0] r_gbk;
    always @(posedge aclk) begin
        if (rst) r_gbk <= GB_K_RST;
        else if (wr_go && wr_com && s_axi_awaddr[7:2] == 6'h0B) r_gbk <= s_axi_wdata[5:0];   // 0x2C GB_K
    end
    assign gb_hold = 1'b0;
    assign gb_adj  = 2'd0;
    assign gb_k    = r_gbk;
    always @(posedge aclk) gb_dn_rstn <= aresetn;

    // ---- ADC のフレーム・TANCH・TP（win_core のまま）----
    reg  [56:0] a_cnt;
    always @(posedge aclk) begin
        if (rst) a_cnt <= 57'd0;
        else if (s_axis_tvalid) a_cnt <= a_cnt + 57'd1;
    end
    wire [FW-1:0] a_fin = a_cnt[56:9];
    reg  tp_run, tp_arm, anch_req, anch_done;
    reg  [FW-1:0] anch_f;
    reg  [63:0]   anch_t, tp_run_t;
    reg  [31:0]   n_ovr, n_gap;
    wire wr_tpc = wr_go && wr_com && s_axi_awaddr[7:2] == 6'h08;
    always @(posedge aclk) begin
        tp_run <= (wr_tpc && s_axi_wdata[0]) || (tp_arm && go_loc);
        if (rst) begin
            tp_arm <= 1'b0; anch_req <= 1'b0; anch_done <= 1'b0; anch_f <= {FW{1'b0}}; anch_t <= 64'd0; tp_run_t <= 64'd0;
            n_ovr <= 32'd0; n_gap <= 32'd0;
        end else begin
            if (wr_tpc && s_axi_wdata[2]) tp_arm <= 1'b1;
            else if ((wr_tpc && s_axi_wdata[3]) || go_loc) tp_arm <= 1'b0;
            if (wr_tpc && s_axi_wdata[4]) begin anch_req <= 1'b1; anch_done <= 1'b0; end
            else if (anch_req && s_axis_tvalid && a_cnt[8:0] == 9'd0) begin
                anch_req <= 1'b0; anch_done <= 1'b1; anch_f <= a_fin; anch_t <= t_loc;
            end
            if (tp_run) tp_run_t <= t_loc;
            if (a_ovr && n_ovr != 32'hFFFF_FFFF) n_ovr <= n_ovr + 32'd1;
            if (a_gap && n_gap != 32'hFFFF_FFFF) n_gap <= n_gap + 32'd1;
        end
    end
    wire [31:0] tp_ring_rd, tp_reg_rd;
    reg  [15:0] ar_addr;
    generate
        if (TP != 0) begin : g_tp
            tp_core #(.TPN_DEFAULT(TPN_DEFAULT), .FW(FW), .REC(1), .REC_CORE({4'd0, CP16[3:0]})) u_tp (
                .clk(aclk), .rst(rst), .rst_rec(rst), .in_acc(s_axis_tvalid), .m_in(a_cnt[8:0]), .fin(a_fin), .tdata(s_axis_tdata),
                .cmd_run(tp_run),
                .wr_en(wr_go && wr_tpr), .wr_addr(s_axi_awaddr[7:2]), .wr_data(s_axi_wdata),
                .rd_addr(ar_addr), .rd_ring(tp_ring_rd), .rd_reg(tp_reg_rd),
                .t_now(t_loc), .m_tdata(m_axis_rec_tdata), .m_tvalid(m_axis_rec_tvalid), .m_tready(m_axis_rec_tready),
                .m_tlast(m_axis_rec_tlast), .m_tuser(m_axis_rec_tuser), .rec_drop(rec_drop));
        end else begin : g_notp
            assign tp_ring_rd = 32'd0; assign tp_reg_rd = 32'd0;
            assign m_axis_rec_tdata = 64'd0; assign m_axis_rec_tvalid = 1'b0; assign m_axis_rec_tlast = 1'b0;
            assign m_axis_rec_tuser = 1'b0; assign rec_drop = 1'b0;
        end
    endgenerate

    // ---- 読み出し（win_core と同じ: 受けてから 5 クロック、候補を 1 段受ける）----
    reg [2:0] ar_wait;
    reg       ar_busy, ar_go_d;
    assign s_axi_arready = !ar_busy && !s_axi_rvalid;
    wire ar_go = s_axi_arvalid && s_axi_arready;
    always @(posedge aclk) ar_go_d <= rst ? 1'b0 : ar_go;
    reg [FW-1:0] afin_lat;
    always @(posedge aclk) begin
        if (rst) afin_lat <= {FW{1'b0}};
        else if (ar_go_d && ar_addr[15:2] == 14'h0009) afin_lat <= a_fin;
    end
    reg [31:0] reg_a;
    always @* begin
        case (ar_addr[7:2])
            6'h00: reg_a = IF_ID;
            6'h01: reg_a = PROJ;
            6'h02: reg_a = NSTREAM;
            6'h03: reg_a = (TP != 0) ? 32'd3 : 32'd1;     // CAPS: [0] DMA のレコード・[1] TP をレコードで（SNAP は RAW の流れが持つので [2] は持ち主が足す）
            6'h04: reg_a = BASE_BEATS;
            6'h05: reg_a = BUILD_TAG;
            6'h06: reg_a = {16'd0, CP16};
            6'h09: reg_a = afin_lat[31:0];
            6'h0A: reg_a = {{(64-FW){1'b0}}, afin_lat[FW-1:32]};
            6'h0B: reg_a = {26'd0, r_gbk};
            6'h0D: reg_a = gb_stat;
            6'h0E: reg_a = adc_stat;
            6'h0F: reg_a = anch_f[31:0];
            6'h10: reg_a = {{(64-FW){1'b0}}, anch_f[FW-1:32]};
            6'h11: reg_a = anch_t[31:0];
            6'h12: reg_a = anch_t[63:32];
            6'h13: reg_a = {29'd0, tp_arm, anch_done, anch_req};
            6'h14: reg_a = tp_run_t[31:0];
            6'h15: reg_a = tp_run_t[63:32];
            6'h16: reg_a = n_ovr;
            6'h17: reg_a = n_gap;
            6'h20: reg_a = fftn_rd;                        // 0x80 FFT_N（proj023）
            default: reg_a = 32'd0;
        endcase
    end
    reg [31:0] rq_a;
    always @(posedge aclk)
        rq_a <= (ar_addr[13:8] == 6'd0) ? reg_a : (ar_addr[13:8] == 6'h01) ? tp_reg_rd : ar_addr[13] ? tp_ring_rd : 32'd0;
    always @(posedge aclk) begin
        if (rst) begin
            ar_busy <= 1'b0; ar_wait <= 3'd0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0; ar_addr <= 16'd0;
        end else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (ar_go) begin ar_busy <= 1'b1; ar_wait <= 3'd0; ar_addr <= s_axi_araddr; end
            else if (ar_busy) begin
                ar_wait <= ar_wait + 3'd1;
                if (ar_wait == 3'd4) begin ar_busy <= 1'b0; s_axi_rvalid <= 1'b1; s_axi_rdata <= rq_a; end
            end
        end
    end
endmodule
