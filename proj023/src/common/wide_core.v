// SPDX-License-Identifier: BSD-3-Clause
//
// wide_core — SAM45-Wide の SLICE の流れ 2 本（1 ADC）。proj023 手順 2c-3
//
// wide_spec（分光の本体）を、INTERFACE.md v2 の流れのブロック（2.5、KIND 2 = SLICE）× 2・SPEC のレコード（rec_fr）・
// 時刻の予約（ARM_RUN・ARM_WRST）・ダンプの健全性（DUMP_H）で包む。s45_core の中に置き、s45_core が番地を振る（手順 3）:
//   コアの 0x4000 + 0x400·(SID_S + s) → ここの 0x400·s + 0x000–0x3FF（s = 0, 1）
//   コアの 0x80 FFT_N（2.4）→ fftn_* の口（s45_core が番地を見て渡す）
// TP はコアの共通（win_core）に任せる（流れごとの TP は持たない）。SNAP は持たない（生のサンプルは RAW の流れ）。
// 全部が DSP ドメイン（256 MHz）。
//
// ---- 流れのブロック（INTERFACE 2.5。SLICE の読み方）----
//   0x00 SID {2, 2, SID_S + s, 0} / 0x04 PARAM {0, 64, 0, log2 N}（N = 32768 / B、実効の点数）/ 0x08 CTRL /
//   0x0C N_ACC / 0x10 N_DUMP / 0x14 SHIFT（書いた値。**効くのは WRST で取り込んだ流れ 0 の値**、D-8）/ 0x18 FLAGS（コアに 1 つ、wide_spec の flags）/
//   0x1C SEQ / 0x20 NCH（4096、空の流れは 0）/ 0x24 FRAME_BEATS 2048 / 0x28 SRC {0, ADC}（書き換えられない）/ 0x2C CFG_ID /
//   0x30 RUN_CFG / 0x34 WRST_CFG / 0x38 RUN_SHIFT（今効いている SHIFT）/ 0x3C DUMP_K / 0x40·44 DUMP_F0 / 0x48 DUMP_N / 0x4C DUMP_SAT /
//   0x50·54 DUMP_T（= K_F ＋ 2048·DUMP_F0）/ 0x58 DUMP_H / 0x5C DUMP_CFG / 0x60·64 RUN_T / 0x68·6C RUN_F0 / 0x70·74 FIN / 0x78·7C FOUT /
//   0x80 NFFT_MIN_MAX {0, 0, 15, 13} / 0x84 REC_CTRL / 0x88 REC_LATE /
//   0x100 S0（書いた値、次の WRST で効く）/ 0x104 S0_CUR / 0x108 S0_STEP 1 /
//   0x200 診断: {pfb の飽和の数}・0x204 {go, have_first}・0x208 BUILD_TAG
//   CTRL の書き: [0] RUN / [1] STOP / [2] ARM_RUN / [3] 予約の取り消し / [8] FLAGS を消す / [12] WRST / [13] ARM_WRST。
//   **WRST はどちらの流れに書いてもコアの WRST**（両方の流れの RUN を止め、束ね・S0・SHIFT を取り込む。INTERFACE 2.5）。
//   CTRL の読み: [0] 積分中 / [1] 開始待ち / [3] 口が開いた（go）/ [5] ARM_RUN 中 / [6] ARM_WRST 中
//
// ---- FFT_N（コアの 0x80、2.4）----
//   W: [7:0] log2 N（13・14・15。外は効かせない）→ 次の WRST で B = 2^(15 − log2 N)。R: [7:0] 今効いている log2 N・[15:8] 書いた値・[23:16] 15（N_PHYS）
//
// ---- DUMP_H（ダンプの間の入力の健全性。spec_core の dstamp と同じ意味）----
//   [3:0] time_core の時刻の健全性（tev）・[4] ADC の振り切れ・[5] 入力の途切れ を、ダンプの入力の区間（T の [DUMP_T, DUMP_T + 2048·N_ACC)）の間 OR。
//   [15] H_OPEN（commit の時点で入力の区間がまだ閉じていない）。入力の側でダンプの区間を数え、8 個の輪に置いて commit で読む
//
// ---- レコード ----
//   rec_fr（NS = 2、S_BASE = SID_S、W7HI = 1）。語 4 = {DUMP_H, src, 0, 0, SHIFT, log2 B, log2 N}（INTERFACE 4.4、SLICE の NS 欄は log2 B）、
//   語 7 = {S0_CUR, 32768}。空の流れ（B 4 の流れ 1）は REC_CTRL を書いてもレコードを出さない（SEQ が進まない）

`timescale 1ns / 1ps

module wide_core #(
    parameter integer SID_S         = 0,
    parameter integer REC_CORE      = 0,       // レコードの core・SRC（ADC の番号）
    parameter integer K_F           = 0,
    parameter integer ST_N          = 16384,
    parameter integer GF_L2         = 8,
    parameter integer N_ACC_DEFAULT = 1280,    // 10.24 ms（2048 ビート × 1280 = 2^21·1.25 ＝ BASE）
    parameter integer SHIFT_DEFAULT = 7,
    parameter integer BUILD_TAG     = 0
)(
    input  wire          aclk,
    input  wire          aresetn,
    input  wire [255:0]  s_axis_tdata,
    input  wire          s_axis_tvalid,
    output wire          s_axis_tready,
    // AXI4-Lite（ここの番地 11 bit = 流れ 2 本のブロック）
    input  wire [10:0]   s_axi_awaddr,
    input  wire          s_axi_awvalid,
    output wire          s_axi_awready,
    input  wire [31:0]   s_axi_wdata,
    input  wire          s_axi_wvalid,
    output wire          s_axi_wready,
    output wire [1:0]    s_axi_bresp,
    output reg           s_axi_bvalid,
    input  wire          s_axi_bready,
    input  wire [10:0]   s_axi_araddr,
    input  wire          s_axi_arvalid,
    output wire          s_axi_arready,
    output reg  [31:0]   s_axi_rdata,
    output wire [1:0]    s_axi_rresp,
    output reg           s_axi_rvalid,
    input  wire          s_axi_rready,
    // コアの FFT_N（s45_core が番地を見て渡す）
    input  wire          fftn_we,
    input  wire [7:0]    fftn_wdata,
    output wire [31:0]   fftn_rd,
    // 時刻（time_core から）
    input  wire [63:0]   t_in,
    input  wire          go_in,
    input  wire [3:0]    tev_in,
    // 共有の ROM
    output wire [10:0]   coef_addr,
    output wire          coef_addr_v,
    input  wire [1151:0] coef_in,
    input  wire [10:0]   coef_m,
    output wire [10:0]   tw_addr,
    input  wire [575:0]  tw_in,
    input  wire [10:0]   tw_k1,
    // SPEC のレコード → s45_core の rec_arb → s45_ring
    output wire [63:0]   m_axis_rec_tdata,
    output wire          m_axis_rec_tvalid,
    input  wire          m_axis_rec_tready,
    output wire          m_axis_rec_tlast,
    output wire          m_axis_rec_tuser,
    output wire          rec_drop,
    // sim の記録用
    output wire [16*64-1:0] dbg_ip_tdata,
    output wire [10:0]      dbg_ip_k1,
    output wire             dbg_ip_v
);
    localparam integer FW = 48;
    wire rst = ~aresetn;
    assign s_axis_tready = 1'b1;

    // ---- 時刻（1 段受ける）----
    reg [63:0] t_loc;
    reg        go_loc;
    reg [3:0]  tev_loc;
    always @(posedge aclk) begin t_loc <= t_in; go_loc <= go_in; tev_loc <= tev_in; end

    // ---- AXI4-Lite の書き ----
    reg [31:0] r_nacc [0:1], r_ndump [0:1], r_cfg [0:1];
    reg [3:0]  r_shift [0:1];
    reg [13:0] r_s0 [0:1];
    reg [2:0]  r_rec [0:1];
    reg [1:0]  arm_run;
    reg        arm_wrst;
    reg [1:0]  cmd_run, cmd_stop;
    reg        cmd_wrst, cmd_fclr;
    reg [7:0]  r_fftn;
    wire [1:0] fr_one_clr;
    wire       wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
    wire       ws    = s_axi_awaddr[10];
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    integer s;
    always @(posedge aclk) begin
        cmd_run  <= {2{go_loc}} & arm_run;
        cmd_wrst <= go_loc && arm_wrst;
        cmd_stop <= 2'b00; cmd_fclr <= 1'b0;
        if (go_loc) begin arm_run <= 2'b00; arm_wrst <= 1'b0; end
        if (rst) begin
            s_axi_bvalid <= 1'b0; arm_run <= 2'b00; arm_wrst <= 1'b0; r_fftn <= 8'd13;
            for (s = 0; s < 2; s = s + 1) begin
                r_nacc[s] <= N_ACC_DEFAULT; r_ndump[s] <= 32'd0; r_cfg[s] <= 32'd0; r_shift[s] <= SHIFT_DEFAULT;
                r_s0[s] <= (s == 0) ? 14'd0 : 14'd4096; r_rec[s] <= 3'd0;
            end
        end else begin
            for (s = 0; s < 2; s = s + 1) if (fr_one_clr[s]) r_rec[s][1] <= 1'b0;
            if (fftn_we && fftn_wdata >= 8'd13 && fftn_wdata <= 8'd15) r_fftn <= fftn_wdata;
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) begin
                s_axi_bvalid <= 1'b1;
                case (s_axi_awaddr[9:2])
                    8'h02: begin
                        cmd_run[ws] <= s_axi_wdata[0] | (go_loc && arm_run[ws]);
                        cmd_wrst    <= s_axi_wdata[12] | (go_loc && arm_wrst);
                        if (s_axi_wdata[2])  arm_run[ws] <= 1'b1;
                        if (s_axi_wdata[13]) arm_wrst <= 1'b1;
                        if (s_axi_wdata[3] || s_axi_wdata[1]) begin arm_run[ws] <= 1'b0; arm_wrst <= 1'b0; end
                        cmd_stop[ws] <= s_axi_wdata[1];
                        cmd_fclr     <= s_axi_wdata[8];
                    end
                    8'h03: r_nacc[ws]  <= s_axi_wdata;
                    8'h04: r_ndump[ws] <= s_axi_wdata;
                    8'h05: r_shift[ws] <= s_axi_wdata[3:0];
                    8'h0B: r_cfg[ws]   <= s_axi_wdata;
                    8'h21: r_rec[ws]   <= s_axi_wdata[2:0];
                    8'h40: r_s0[ws]    <= s_axi_wdata[13:0];      // 0x100 S0
                    default: ;
                endcase
            end
        end
    end

    // ---- 本体 ----
    wire [1:0]    c_lb, c_en, st_sched, st_acc, commit, rd_plane;
    wire [13:0]   c_s0_0, c_s0_1;
    wire [3:0]    c_shift;
    wire          go;
    wire [FW-1:0] fa_now, fo, df0_0, df0_1;
    wire [7:0]    flags;
    wire [31:0]   seq0, seq1, dk0, dk1, dn0, dn1, dsat0, dsat1;
    wire [1:0]    fr_rs2;
    wire [11:0]   fr_ch;
    wire [63:0]   rd_d;
    wire [15:0]   pfb_sat;
    wire          have_first;
    wire [1:0]    rec_drop_s;
    wire [1:0]    w_lb = 2'd3 - r_fftn[1:0];             // log2 N 13・14・15 → LB 2・1・0（r_fftn は 13..15 だけ）
    wide_spec #(.K_F(K_F), .ST_N(ST_N), .SHIFT_DEFAULT(SHIFT_DEFAULT), .FW(FW), .GF_L2(GF_L2)) u_spec (
        .clk(aclk), .rst(rst), .s_tdata(s_axis_tdata), .s_tvalid(s_axis_tvalid), .t_in(t_in),
        .coef_addr(coef_addr), .coef_addr_v(coef_addr_v), .coef_in(coef_in), .coef_m(coef_m),
        .tw_addr(tw_addr), .tw_in(tw_in), .tw_k1(tw_k1),
        .cmd_wrst(cmd_wrst), .w_lb(w_lb), .w_s0_0(r_s0[0]), .w_s0_1(r_s0[1]), .w_shift(r_shift[0]),
        .cmd_run(cmd_run), .cmd_stop(cmd_stop), .r_nacc0(r_nacc[0]), .r_nacc1(r_nacc[1]), .r_ndump0(r_ndump[0]), .r_ndump1(r_ndump[1]),
        .flags_clr(cmd_fclr),
        .c_lb(c_lb), .c_s0_0(c_s0_0), .c_s0_1(c_s0_1), .c_shift(c_shift), .c_en(c_en), .go(go), .fa_now(fa_now), .fo(fo),
        .flags(flags), .st_sched(st_sched), .st_acc(st_acc),
        .commit(commit), .seq0(seq0), .seq1(seq1), .dk0(dk0), .dk1(dk1), .df0_0(df0_0), .df0_1(df0_1),
        .dn0(dn0), .dn1(dn1), .dsat0(dsat0), .dsat1(dsat1), .rd_plane(rd_plane),
        .rd_s(fr_rs2[0]), .rd_i(fr_ch), .rd_d(rd_d),
        .dbg_pfb_sat(pfb_sat), .dbg_have_first(have_first),
        .dbg_ip_tdata(dbg_ip_tdata), .dbg_ip_k1(dbg_ip_k1), .dbg_ip_v(dbg_ip_v));
    assign fftn_rd = {8'd0, 8'd15, r_fftn, 8'd15 - {6'd0, c_lb}};

    // ---- RUN・WRST の帳簿（AXI4-Lite で読む値）----
    reg [63:0]   run_t [0:1];
    reg [FW-1:0] run_f0 [0:1];
    reg [31:0]   run_cfg [0:1], dcfg [0:1], wrst_cfg;
    always @(posedge aclk) begin
        if (rst) begin
            wrst_cfg <= 32'd0;
            for (s = 0; s < 2; s = s + 1) begin run_t[s] <= 64'd0; run_f0[s] <= {FW{1'b0}}; run_cfg[s] <= 32'd0; dcfg[s] <= 32'd0; end
        end else begin
            if (cmd_wrst) wrst_cfg <= r_cfg[0];
            for (s = 0; s < 2; s = s + 1) begin
                if (cmd_run[s] && !cmd_wrst) begin
                    run_t[s] <= t_loc; run_cfg[s] <= r_cfg[s];
                    run_f0[s] <= ((fa_now >> GF_L2) + 2) << GF_L2;      // wide_spec と同じ式（同じクロックの fa_now）
                end
                if (commit[s]) dcfg[s] <= run_cfg[s];
            end
        end
    end

    // ---- DUMP_H: 入力の側でダンプの区間を数える（流れごと、8 個の輪）----
    wire       a_ovr, a_gap;
    adc_ev u_aev (.clk(aclk), .rst(rst), .tdata(s_axis_tdata), .tvalid(s_axis_tvalid), .ovr(a_ovr), .gap(a_gap));
    wire [5:0] ev = {a_gap, a_ovr, tev_loc};
    reg  [FW-1:0] hb_next [0:1];           // 次のダンプの最初のフレーム
    reg  [31:0]   hk [0:1], hn [0:1], hnd [0:1];
    reg  [1:0]    h_arm, h_on;
    reg  [5:0]    hring [0:15];            // [8s + k mod 8]
    reg  [31:0]   h_done [0:1];            // 入力の区間が閉じたダンプの数
    wire [63:0]   tk = t_loc - K_F;
    wire          fstart = go && (tk[10:0] == 11'd0);
    wire [FW-1:0] fa_loc = tk[11 +: FW];
    integer q;
    always @(posedge aclk) begin
        if (rst) begin
            h_arm <= 2'b00; h_on <= 2'b00;
            for (s = 0; s < 2; s = s + 1) begin hb_next[s] <= 0; hk[s] <= 0; hn[s] <= 1; hnd[s] <= 0; h_done[s] <= 0; end
            for (q = 0; q < 16; q = q + 1) hring[q] <= 6'd0;
        end else begin
            for (s = 0; s < 2; s = s + 1) begin
                if (h_on[s]) hring[8*s + hk[s][2:0]] <= hring[8*s + hk[s][2:0]] | ev;
                if (fstart && (h_arm[s] || h_on[s]) && fa_loc == hb_next[s]) begin
                    if (h_on[s]) h_done[s] <= h_done[s] + 32'd1;
                    if (h_arm[s]) begin hk[s] <= 32'd0; end else hk[s] <= hk[s] + 32'd1;
                    if (!h_arm[s] && hnd[s] != 32'd0 && hk[s] + 32'd1 == hnd[s]) begin
                        h_on[s] <= 1'b0;                                  // N_DUMP 個目の区間が閉じた
                    end else begin
                        h_on[s] <= 1'b1;
                        hring[8*s + (h_arm[s] ? 3'd0 : hk[s][2:0] + 3'd1)] <= ev;
                    end
                    h_arm[s] <= 1'b0;
                    hb_next[s] <= hb_next[s] + hn[s];
                end
                if (cmd_wrst || cmd_stop[s]) begin h_arm[s] <= 1'b0; h_on[s] <= 1'b0; end
                if (cmd_run[s] && !cmd_wrst) begin
                    h_arm[s] <= 1'b1; h_on[s] <= 1'b0; h_done[s] <= 32'd0;
                    hn[s] <= (r_nacc[s] == 32'd0) ? 32'd1 : r_nacc[s]; hnd[s] <= r_ndump[s];
                    hb_next[s] <= ((fa_now >> GF_L2) + 2) << GF_L2;
                end
            end
        end
    end
    reg [15:0] dh [0:1];
    always @(posedge aclk) begin
        if (rst) begin dh[0] <= 16'd0; dh[1] <= 16'd0; end
        else begin
            if (commit[0]) dh[0] <= {(h_done[0] <= dk0), 9'd0, hring[{1'b0, dk0[2:0]}]};
            if (commit[1]) dh[1] <= {(h_done[1] <= dk1), 9'd0, hring[{1'b1, dk1[2:0]}]};
        end
    end
    // commit のクロックには dk* がもう新しい値（wide_spec が同じエッジで替える）。dh はその次のクロックに揃い、rec_fr は HOLD クロック待つので間に合う

    // ---- SPEC のレコード ----
    wire [63:0]   dt0 = K_F + {df0_0, 11'd0};
    wire [63:0]   dt1 = K_F + {df0_1, 11'd0};
    wire [7:0]    ln  = 8'd15 - {6'd0, c_lb};
    localparam [7:0] RC8 = REC_CORE;
    wire [383:0] hdr0 = {{24'd0, flags}, dcfg[0], dsat0, dn0,
                         dh[0], {4'd0, RC8[3:0]}, 8'd0, 8'd0, {4'd0, c_shift}, {6'd0, c_lb}, ln,
                         dt0, {{(64-FW){1'b0}}, df0_0}, dk0, seq0};
    wire [383:0] hdr1 = {{24'd0, flags}, dcfg[1], dsat1, dn1,
                         dh[1], {4'd0, RC8[3:0]}, 8'd0, 8'd0, {4'd0, c_shift}, {6'd0, c_lb}, ln,
                         dt1, {{(64-FW){1'b0}}, df0_1}, dk1, seq1};
    wire       fr_req;
    reg        fr_gnt;
    wire [1:0] fr_late;
    always @(posedge aclk) fr_gnt <= rst ? 1'b0 : fr_req;
`ifdef W7_POSCTL
    localparam integer W7 = 0;                 // 陽性対照: 語 7 の S0_CUR を入れない
`else
    localparam integer W7 = 1;
`endif
    rec_fr #(.NS(2), .S_BASE(SID_S), .CORE(RC8), .LAT(5), .SNAP(0), .W7HI(W7)) u_rec (.clk(aclk), .rst(rst),
        .seq({seq1, seq0}), .hdr({hdr1, hdr0}),
        .rec_all({r_rec[1][0] & c_en[1], r_rec[0][0]}), .rec_one({r_rec[1][1] & c_en[1], r_rec[0][1]}), .rec_snap(2'b00), .snap_ok(2'b00),
        .rd_snap(), .one_clr(fr_one_clr), .late(fr_late), .drop(rec_drop_s),
        .req(fr_req), .gnt(fr_gnt), .rd_s(fr_rs2), .rd_ch(fr_ch), .rd_data(rd_d),
        .m_tdata(m_axis_rec_tdata), .m_tvalid(m_axis_rec_tvalid), .m_tready(m_axis_rec_tready),
        .m_tlast(m_axis_rec_tlast), .m_tuser(m_axis_rec_tuser),
        .w7hi({18'd0, c_s0_1, 18'd0, c_s0_0}));
    assign rec_drop = |rec_drop_s;
    reg [31:0] rec_late [0:1];
    always @(posedge aclk) begin
        if (rst) begin rec_late[0] <= 0; rec_late[1] <= 0; end
        else for (s = 0; s < 2; s = s + 1) if (fr_late[s] && rec_late[s] != 32'hFFFF_FFFF) rec_late[s] <= rec_late[s] + 32'd1;
    end

    // ---- AXI4-Lite の読み ----
    reg [10:0]   ar_addr;
    reg [2:0]    ar_wait;
    reg          ar_busy;
    reg [FW-1:0] fin_lat, fout_lat;
    assign s_axi_arready = !ar_busy && !s_axi_rvalid;
    assign s_axi_rresp   = 2'b00;
    wire          rs = ar_addr[10];
    wire [31:0]   seq_s  = rs ? seq1 : seq0;
    wire [31:0]   dk_s   = rs ? dk1 : dk0;
    wire [FW-1:0] df0_s  = rs ? df0_1 : df0_0;
    wire [63:0]   dt_s   = rs ? dt1 : dt0;
    wire [13:0]   s0c_s  = rs ? c_s0_1 : c_s0_0;
    reg  [31:0]   reg_rd;
    always @* begin
        case (ar_addr[9:2])
            8'h00: reg_rd = {8'd2, 8'd2, SID_S[7:0] + {7'd0, rs}, 8'd0};
            8'h01: reg_rd = {8'd0, 8'd64, 8'd0, ln};
            8'h02: reg_rd = {25'd0, arm_wrst, arm_run[rs], 1'b0, go, 1'b0, st_sched[rs], st_acc[rs]};
            8'h03: reg_rd = r_nacc[rs];
            8'h04: reg_rd = r_ndump[rs];
            8'h05: reg_rd = {28'd0, r_shift[rs]};
            8'h06: reg_rd = {24'd0, flags};
            8'h07: reg_rd = seq_s;
            8'h08: reg_rd = c_en[rs] ? 32'd4096 : 32'd0;
            8'h09: reg_rd = 32'd2048;
            8'h0A: reg_rd = {28'd0, RC8[3:0]};
            8'h0B: reg_rd = r_cfg[rs];
            8'h0C: reg_rd = run_cfg[rs];
            8'h0D: reg_rd = wrst_cfg;
            8'h0E: reg_rd = {28'd0, c_shift};
            8'h0F: reg_rd = dk_s;
            8'h10: reg_rd = df0_s[31:0];
            8'h11: reg_rd = {{(64-FW){1'b0}}, df0_s[FW-1:32]};
            8'h12: reg_rd = rs ? dn1 : dn0;
            8'h13: reg_rd = rs ? dsat1 : dsat0;
            8'h14: reg_rd = dt_s[31:0];
            8'h15: reg_rd = dt_s[63:32];
            8'h16: reg_rd = {16'd0, dh[rs]};
            8'h17: reg_rd = dcfg[rs];
            8'h18: reg_rd = run_t[rs][31:0];
            8'h19: reg_rd = run_t[rs][63:32];
            8'h1A: reg_rd = run_f0[rs][31:0];
            8'h1B: reg_rd = {{(64-FW){1'b0}}, run_f0[rs][FW-1:32]};
            8'h1C: reg_rd = fin_lat[31:0];
            8'h1D: reg_rd = {{(64-FW){1'b0}}, fin_lat[FW-1:32]};
            8'h1E: reg_rd = fout_lat[31:0];
            8'h1F: reg_rd = {{(64-FW){1'b0}}, fout_lat[FW-1:32]};
            8'h20: reg_rd = {16'd0, 8'd15, 8'd13};
            8'h21: reg_rd = {29'd0, r_rec[rs]};
            8'h22: reg_rd = rec_late[rs];
            8'h40: reg_rd = {18'd0, r_s0[rs]};
            8'h41: reg_rd = {18'd0, s0c_s};
            8'h42: reg_rd = 32'd1;
            8'h80: reg_rd = {16'd0, pfb_sat};
            8'h81: reg_rd = {30'd0, go, have_first};
            8'h82: reg_rd = BUILD_TAG;
            default: reg_rd = 32'd0;
        endcase
    end
    always @(posedge aclk) begin
        if (rst) begin
            ar_busy <= 1'b0; ar_wait <= 3'd0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0; ar_addr <= 11'd0;
            fin_lat <= {FW{1'b0}}; fout_lat <= {FW{1'b0}};
        end else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin
                ar_busy <= 1'b1; ar_wait <= 3'd0; ar_addr <= s_axi_araddr;
                if (s_axi_araddr[9:2] == 8'h1C) fin_lat  <= fa_now;     // LO を読むと HI を固定
                if (s_axi_araddr[9:2] == 8'h1E) fout_lat <= fo;
            end else if (ar_busy) begin
                ar_wait <= ar_wait + 3'd1;
                if (ar_wait == 3'd3) begin ar_busy <= 1'b0; s_axi_rvalid <= 1'b1; s_axi_rdata <= reg_rd; end
            end
        end
    end
endmodule
