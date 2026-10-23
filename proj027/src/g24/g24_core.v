// SPDX-License-Identifier: BSD-3-Clause
//
// g24_core — 2G-4 の FULL の流れ 1 本（1 ADC、32768 ch。コア 1 個ぶん）。proj027 手順 2d: proj025（proj025-m0）の g22_core を 4096 ビートのフレームに縮めた
//
// src/common/wide_core.v（567fda2）を写し、流れのブロックを KIND 1 FULL の 1 本にした。g24_spec（分光の本体）を、
// INTERFACE.md v2 の流れのブロック（2.5）・SPEC のレコード（rec_fr、NCH 32768 = 256 KiB）・FULL の TP（tp_core、D-12）・
// 時刻の予約（ARM_RUN・ARM_WRST）・ダンプの健全性（DUMP_H）で包む。g24_s45_core（2e）の中に置き、番地を振ってもらう:
//   コアの 0x4000 + 0x400·SID_S → ここの 0x000–0x3FF
// 入力は g24_s45_core の axis_sel4 が 4 本から選んだ ADC（D-8）。選ぶのはこの流れの SRC（今効いている値を src_sel で外へ）。
// 係数・ひねり係数はコアの中（g24_spec）。SNAP は持たない（生のサンプルは RAW の流れ、D-13）。全部が DSP ドメイン（256 MHz）。
//
// ---- 流れのブロック（INTERFACE 2.5。FULL の読み方）----
//   0x00 SID {2, 1, SID_S, 0} / 0x04 PARAM {0, 64, 0, 16}（[7:0] log2 N、2G-4 は N = 65536） / 0x08 CTRL / 0x0C N_ACC / 0x10 N_DUMP /
//   0x14 SHIFT（書いた値。**RUN で取り込む**、FULL の約束）/ 0x18 FLAGS（g24_spec の flags）/ 0x1C SEQ / 0x20 NCH 32768 /
//   0x24 FRAME_BEATS 4096 / 0x28 SRC {1, 0, 今効いている ADC}（W: [3:0]、次の WRST で効く）/ 0x2C CFG_ID / 0x30 RUN_CFG / 0x34 WRST_CFG /
//   0x38 RUN_SHIFT（今効いている SHIFT）/ 0x3C DUMP_K / 0x40·44 DUMP_F0 / 0x48 DUMP_N / 0x4C DUMP_SAT / 0x50·54 DUMP_T（= K_F ＋ 4096·DUMP_F0）/
//   0x58 DUMP_H / 0x5C DUMP_CFG / 0x60·64 RUN_T / 0x68·6C RUN_F0 / 0x70·74 FIN / 0x78·7C FOUT / 0x80 NFFT_MIN_MAX {0, 0, 16, 16} /
//   0x84 REC_CTRL（[0] ALL・[1] ONE。[2] SNAP は受けるが意味は無い）/ 0x88 REC_LATE /
//   0x100〜0x1FF FULL の TP のレジスタ（tp_core。コアの 0x100〜 と同じ並び。D-12: SRC で選んだ ADC の入力で測る）/
//   0x200 診断: {pfb の飽和の数}・0x204 {IP に待たされたクロック数[31:24], 待ち行列の語数[21:16], go, have_first}・0x208 BUILD_TAG・
//   0x20C {IP の入口の位相[27:16], 出口の位相[11:0]}・0x210 最初に IP が受けてから待たされるまで（wide_core と同じ並び。位相は 12 bit）
//   CTRL の書き: [0] RUN / [1] STOP / [2] ARM_RUN / [3] 予約の取り消し / [8] FLAGS を消す / [12] WRST / [13] ARM_WRST。
//   **WRST は SRC と CFG_ID を取り込み、RUN を止める**（spec_core の FULL と同じ。SHIFT は変えない）。
//   CTRL の読み: [0] 積分中 / [1] 開始待ち / [3] 口が開いた（go）/ [5] ARM_RUN 中 / [6] ARM_WRST 中
//
// ---- FULL の TP（D-12）----
//   tp_core に、入力のビートを T の格子の 512 ビートの小フレーム（m = (T − K_F) mod 512、番号 = ⌊(T − K_F) / 512⌋）で渡す。
//   RUN の F0 は FULL の RUN_F0 × 32（F0_EXT）。TP_N 512 = 1.024 ms、10 個で 1 レコード = 10.24 ms で、SPEC のダンプと同じ T から始まる。
//   レコード（type 2）の s は SID_S。SPEC のレコードとはレコード単位で rec_arb で束ねる（spec_core と同じ形）
//
// ---- DUMP_H（wide_core と同じ意味）----
//   [3:0] 時刻の健全性（tev）・[4] ADC の振り切れ・[5] 入力の途切れ を、ダンプの入力の区間（T の [DUMP_T, DUMP_T + 4096·N_ACC)）の間 OR。
//   [15] H_OPEN（commit の時点で入力の区間がまだ閉じていない）
//
// ---- レコード ----
//   rec_fr（NS 1・NCH 32768・W7HI 0）。語 4 = {DUMP_H, src, 0, 0, SHIFT, 0, 16}（src・SHIFT はそのダンプを閉じたときの値）、
//   語 7 = {0, 262144}（FULL の KIND に固有は 0）
//
// -DG24C_POSCTL: 積分器の読みの口に 1 段足す（陽性対照。rec_fr の LAT 5 と合わなくなり、レコードの中身が 1 ch ずれて落ちるべき）
// -DG24C_TP_POSCTL: TP の F0 を FULL の RUN_F0 のまま渡す（× 8 を忘れる。陽性対照。TP の区切りが SPEC のダンプと同じ T から始まらず落ちるべき）

`timescale 1ns / 1ps

module g24_core #(
    parameter integer SID_S         = 0,
    parameter integer REC_CORE      = 0,       // レコードの core
    parameter integer K_F           = 0,
    parameter integer ST_N          = 16384,
    parameter integer GF_L2         = 7,       // F0 の格子（128 フレーム = 2.048 ms）
    parameter integer N_ACC_DEFAULT = 640,     // 10.24 ms（4096 ビート × 640 = BASE 2,621,440）
    parameter integer SHIFT_DEFAULT = 7,
    parameter integer TPN_DEFAULT   = 512,     // 1.024 ms（512 ビート × 512）
    parameter integer BUILD_TAG     = 0,
    parameter LO_FILE = "g24_coef_lo.hex",
    parameter HI_FILE = "g24_coef_hi.hex",
    parameter TA_FILE = "g24_tw_a.hex",
    parameter TB_FILE = "g24_tw_b.hex"
)(
    input  wire          aclk,
    input  wire          aresetn,
    input  wire [255:0]  s_axis_tdata,
    input  wire          s_axis_tvalid,
    output wire          s_axis_tready,
    // AXI4-Lite（ここの番地 10 bit = 流れ 1 本のブロック）
    input  wire [9:0]    s_axi_awaddr,
    input  wire          s_axi_awvalid,
    output wire          s_axi_awready,
    input  wire [31:0]   s_axi_wdata,
    input  wire          s_axi_wvalid,
    output wire          s_axi_wready,
    output wire [1:0]    s_axi_bresp,
    output reg           s_axi_bvalid,
    input  wire          s_axi_bready,
    input  wire [9:0]    s_axi_araddr,
    input  wire          s_axi_arvalid,
    output wire          s_axi_arready,
    output reg  [31:0]   s_axi_rdata,
    output wire [1:0]    s_axi_rresp,
    output reg           s_axi_rvalid,
    input  wire          s_axi_rready,
    // 入力の選び（今効いている SRC。g24_s45_core の axis_sel4 へ）
    output wire [1:0]    src_sel,
    // 時刻（time_core から）
    input  wire [63:0]   t_in,
    input  wire          go_in,
    input  wire [3:0]    tev_in,
    // SPEC・TP のレコード → g24_s45_core の rec_arb → s45_ring
    output wire [63:0]   m_axis_rec_tdata,
    output wire          m_axis_rec_tvalid,
    input  wire          m_axis_rec_tready,
    output wire          m_axis_rec_tlast,
    output wire          m_axis_rec_tuser,
    output wire [1:0]    rec_drop,           // [0] SPEC（読み始めなかったダンプ）/ [1] TP
    // sim の記録用
    output wire [16*64-1:0] dbg_ip_tdata,
    output wire [11:0]      dbg_ip_k1,
    output wire             dbg_ip_v
);
    localparam integer FW = 48;
    wire rst = ~aresetn;
    assign s_axis_tready = 1'b1;

    // ---- 時刻・入力（1 段受ける）----
    reg [63:0]  t_loc;
    reg         go_loc;
    reg [3:0]   tev_loc;
    reg [255:0] d_loc;
    reg         v_loc;
    always @(posedge aclk) begin t_loc <= t_in; go_loc <= go_in; tev_loc <= tev_in; d_loc <= s_axis_tdata; v_loc <= s_axis_tvalid; end

    // ---- AXI4-Lite の書き ----
    reg [31:0] r_nacc, r_ndump, r_cfg;
    reg [3:0]  r_shift, r_src, c_src;
    reg [2:0]  r_rec;
    reg        arm_run, arm_wrst;
    reg        cmd_run, cmd_stop, cmd_wrst, cmd_fclr;
    wire       fr_one_clr;
    wire       wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    always @(posedge aclk) begin
        cmd_run  <= go_loc && arm_run;
        cmd_wrst <= go_loc && arm_wrst;
        cmd_stop <= 1'b0; cmd_fclr <= 1'b0;
        if (go_loc) begin arm_run <= 1'b0; arm_wrst <= 1'b0; end
        if (rst) begin
            s_axi_bvalid <= 1'b0; arm_run <= 1'b0; arm_wrst <= 1'b0;
            r_nacc <= N_ACC_DEFAULT; r_ndump <= 32'd0; r_cfg <= 32'd0; r_shift <= SHIFT_DEFAULT; r_src <= 4'd0; r_rec <= 3'd0;
        end else begin
            if (fr_one_clr) r_rec[1] <= 1'b0;
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go && s_axi_awaddr[9:8] == 2'd0) begin
                s_axi_bvalid <= 1'b1;
                case (s_axi_awaddr[7:2])
                    6'h02: begin
                        cmd_run  <= s_axi_wdata[0]  | (go_loc && arm_run);
                        cmd_wrst <= s_axi_wdata[12] | (go_loc && arm_wrst);
                        if (s_axi_wdata[2])  arm_run  <= 1'b1;
                        if (s_axi_wdata[13]) arm_wrst <= 1'b1;
                        if (s_axi_wdata[3] || s_axi_wdata[1]) begin arm_run <= 1'b0; arm_wrst <= 1'b0; end
                        cmd_stop <= s_axi_wdata[1];
                        cmd_fclr <= s_axi_wdata[8];
                    end
                    6'h03: r_nacc  <= s_axi_wdata;
                    6'h04: r_ndump <= s_axi_wdata;
                    6'h05: r_shift <= s_axi_wdata[3:0];
                    6'h0A: r_src   <= s_axi_wdata[3:0];      // 0x28 SRC（次の WRST で効く）
                    6'h0B: r_cfg   <= s_axi_wdata;
                    6'h21: r_rec   <= s_axi_wdata[2:0];      // 0x84 REC_CTRL
                    default: ;
                endcase
            end else if (wr_go) s_axi_bvalid <= 1'b1;        // 0x100〜（TP）・0x200〜（診断）は応答だけ（TP は tp_core が受ける）
        end
    end
    wire run_go = cmd_run && !cmd_wrst;
    always @(posedge aclk) begin
        if (rst) c_src <= 4'd0;
        else if (cmd_wrst) c_src <= r_src;
    end
    assign src_sel = c_src[1:0];

    // ---- 本体 ----
    wire          st_sched, st_acc, commit, rd_plane, go;
    wire [3:0]    c_shift;
    wire [FW-1:0] fa_now, fo, df0;
    wire [7:0]    flags;
    wire [31:0]   seq, dk, dn, dsat;
    wire [14:0]   fr_ch;
    wire [63:0]   rd_d;
    wire [15:0]   pfb_sat, ipq, ip_st;
    wire [31:0]   ip_ph;
    wire          have_first;
    // rd_ch（rec_fr のレジスタ）→ g24_acc の 4 段（番地 → 記憶 → 出力 → 銀行の選択）→ rd_d = rec_fr の LAT 5（wide_core と同じく直に繋ぐ）
`ifdef G24C_POSCTL
    reg  [14:0]   rd_c_pc;
    always @(posedge aclk) rd_c_pc <= fr_ch;
    wire [14:0]   rd_c_use = rd_c_pc;                    // 陽性対照: 1 段多い（中身が 1 ch ずれる）
`else
    wire [14:0]   rd_c_use = fr_ch;
`endif
    g24_spec #(.K_F(K_F), .ST_N(ST_N), .SHIFT_DEFAULT(SHIFT_DEFAULT), .FW(FW), .GF_L2(GF_L2),
               .LO_FILE(LO_FILE), .HI_FILE(HI_FILE), .TA_FILE(TA_FILE), .TB_FILE(TB_FILE)) u_spec (
        .clk(aclk), .rst(rst), .s_tdata(s_axis_tdata), .s_tvalid(s_axis_tvalid), .t_in(t_in),
        .cmd_wrst(cmd_wrst), .w_shift(r_shift), .cmd_run(cmd_run), .cmd_stop(cmd_stop),
        .r_nacc(r_nacc), .r_ndump(r_ndump), .flags_clr(cmd_fclr),
        .c_shift(c_shift), .go(go), .fa_now(fa_now), .fo(fo), .flags(flags), .st_sched(st_sched), .st_acc(st_acc),
        .commit(commit), .seq(seq), .dk(dk), .df0(df0), .dn(dn), .dsat(dsat), .rd_plane(rd_plane),
        .rd_c(rd_c_use), .rd_d(rd_d),
        .dbg_pfb_sat(pfb_sat), .dbg_have_first(have_first), .dbg_ipq(ipq), .dbg_ip_ph(ip_ph), .dbg_ip_st(ip_st),
        .dbg_ip_tdata(dbg_ip_tdata), .dbg_ip_k1(dbg_ip_k1), .dbg_ip_v(dbg_ip_v));

    // ---- RUN・WRST の帳簿（AXI4-Lite で読む値）----
    wire [FW-1:0] f0_now = ((fa_now >> GF_L2) + 2) << GF_L2;     // g24_spec と同じ式（同じクロックの fa_now）
    reg  [63:0]   run_t;
    reg  [FW-1:0] run_f0;
    reg  [31:0]   run_cfg, dcfg, wrst_cfg;
    reg  [3:0]    d_src, d_shift;
    always @(posedge aclk) begin
        if (rst) begin
            wrst_cfg <= 32'd0; run_t <= 64'd0; run_f0 <= {FW{1'b0}}; run_cfg <= 32'd0; dcfg <= 32'd0;
            d_src <= 4'd0; d_shift <= 4'd0;
        end else begin
            if (cmd_wrst) wrst_cfg <= r_cfg;
            if (run_go) begin run_t <= t_loc; run_cfg <= r_cfg; run_f0 <= f0_now; end
            if (commit) begin dcfg <= run_cfg; d_src <= c_src; d_shift <= c_shift; end
        end
    end

    // ---- DUMP_H: 入力の側でダンプの区間を数える（8 個の輪。wide_core の流れ 1 本ぶん）----
    wire       a_ovr, a_gap;
    adc_ev u_aev (.clk(aclk), .rst(rst), .tdata(s_axis_tdata), .tvalid(s_axis_tvalid), .ovr(a_ovr), .gap(a_gap));
    wire [5:0]    ev = {a_gap, a_ovr, tev_loc};
    reg  [FW-1:0] hb_next;
    reg  [31:0]   hk, hn, hnd, h_done;
    reg           h_arm, h_on;
    reg  [5:0]    hring [0:7];
    wire [63:0]   tk = t_loc - K_F;
    wire          fstart = go && (tk[11:0] == 12'd0);
    wire [FW-1:0] fa_loc = tk[12 +: FW];
    integer q;
    always @(posedge aclk) begin
        if (rst) begin
            h_arm <= 1'b0; h_on <= 1'b0; hb_next <= 0; hk <= 0; hn <= 1; hnd <= 0; h_done <= 0;
            for (q = 0; q < 8; q = q + 1) hring[q] <= 6'd0;
        end else begin
            if (h_on) hring[hk[2:0]] <= hring[hk[2:0]] | ev;
            if (fstart && (h_arm || h_on) && fa_loc == hb_next) begin
                if (h_on) h_done <= h_done + 32'd1;
                if (h_arm) hk <= 32'd0; else hk <= hk + 32'd1;
                if (!h_arm && hnd != 32'd0 && hk + 32'd1 == hnd) begin
                    h_on <= 1'b0;                                  // N_DUMP 個目の区間が閉じた
                end else begin
                    h_on <= 1'b1;
                    hring[h_arm ? 3'd0 : hk[2:0] + 3'd1] <= ev;
                end
                h_arm   <= 1'b0;
                hb_next <= hb_next + hn;
            end
            if (cmd_wrst || cmd_stop) begin h_arm <= 1'b0; h_on <= 1'b0; end
            if (run_go) begin
                h_arm <= 1'b1; h_on <= 1'b0; h_done <= 32'd0;
                hn <= (r_nacc == 32'd0) ? 32'd1 : r_nacc; hnd <= r_ndump;
                hb_next <= f0_now;
            end
        end
    end
    reg [15:0] dh;
    always @(posedge aclk) begin
        if (rst) dh <= 16'd0;
        else if (commit) dh <= {(h_done <= dk), 9'd0, hring[dk[2:0]]};
    end
    // commit のクロックには dk がもう新しい値（g24_spec が同じエッジで替える）。dh・d_src・d_shift はその次のクロックに揃い、rec_fr は HOLD クロック待つ

    // ---- FULL の TP（D-12）----
    wire [31:0] tp_reg_rd;
    wire [63:0] tp_d;
    wire        tp_v, tp_r, tp_l, tp_u, tp_drop;
    reg  [9:0]  ar_addr;
    tp_core #(.TPN_DEFAULT(TPN_DEFAULT), .FW(FW), .REC(1), .REC_CORE(REC_CORE % 256), .REC_S(SID_S % 256), .F0_EXT(1)) u_tp (
        .clk(aclk), .rst(rst), .rst_rec(rst),
        .in_acc(v_loc), .m_in(tk[8:0]), .fin(tk[9 +: FW]), .tdata(d_loc),
`ifdef G24C_TP_POSCTL
        .cmd_run(run_go), .f0_ext(f0_now),
`else
        .cmd_run(run_go), .f0_ext({f0_now[FW-4:0], 3'd0}),                  // FULL の F0 × 8（小フレーム 512 ビート、4096 / 512）
`endif
        .wr_en(wr_go && s_axi_awaddr[9:8] == 2'd1), .wr_addr(s_axi_awaddr[7:2]), .wr_data(s_axi_wdata),
        .rd_addr({6'd0, ar_addr}), .rd_ring(), .rd_reg(tp_reg_rd),
        .t_now(t_loc), .m_tdata(tp_d), .m_tvalid(tp_v), .m_tready(tp_r), .m_tlast(tp_l), .m_tuser(tp_u), .rec_drop(tp_drop));

    // ---- SPEC のレコード ----
    wire [63:0]   dt = K_F + {df0, 12'd0};
    localparam [7:0] RC8 = REC_CORE;
    wire [383:0] hdr = {{24'd0, flags}, dcfg, dsat, dn,
                        dh, {4'd0, d_src}, 8'd0, 8'd0, {4'd0, d_shift}, 8'd0, 8'd16,
                        dt, {{(64-FW){1'b0}}, df0}, dk, seq};
    wire       fr_req;
    reg        fr_gnt;
    wire       fr_late;
    wire [63:0] sr_d;
    wire        sr_v, sr_r, sr_l, sr_u;
    always @(posedge aclk) fr_gnt <= rst ? 1'b0 : fr_req;
    rec_fr #(.NS(1), .S_BASE(SID_S), .CORE(RC8), .LAT(5), .SNAP(0), .W7HI(0), .NCH(32768)) u_rec (.clk(aclk), .rst(rst),
        .seq(seq), .hdr(hdr), .rec_all(r_rec[0]), .rec_one(r_rec[1]), .rec_snap(1'b0), .snap_ok(1'b0),
        .rd_snap(), .one_clr(fr_one_clr), .late(fr_late), .drop(rec_drop[0]),
        .req(fr_req), .gnt(fr_gnt), .rd_s(), .rd_ch(fr_ch), .rd_data(rd_d),
        .m_tdata(sr_d), .m_tvalid(sr_v), .m_tready(sr_r), .m_tlast(sr_l), .m_tuser(sr_u), .w7hi(32'd0));
    assign rec_drop[1] = tp_drop;
    rec_arb #(.N(2)) u_sarb (.clk(aclk), .rst(rst),
        .s_tdata({tp_d, sr_d}), .s_tvalid({tp_v, sr_v}), .s_tready({tp_r, sr_r}), .s_tlast({tp_l, sr_l}), .s_tuser({tp_u, sr_u}),
        .m_tdata(m_axis_rec_tdata), .m_tvalid(m_axis_rec_tvalid), .m_tready(m_axis_rec_tready),
        .m_tlast(m_axis_rec_tlast), .m_tuser(m_axis_rec_tuser));
    reg [31:0] rec_late;
    always @(posedge aclk) begin
        if (rst) rec_late <= 32'd0;
        else if (fr_late && rec_late != 32'hFFFF_FFFF) rec_late <= rec_late + 32'd1;
    end

    // ---- AXI4-Lite の読み（wide_core と同じ: 受けてから 4 クロック）----
    reg [2:0]    ar_wait;
    reg          ar_busy;
    reg [FW-1:0] fin_lat, fout_lat;
    assign s_axi_arready = !ar_busy && !s_axi_rvalid;
    assign s_axi_rresp   = 2'b00;
    reg  [31:0]   reg_rd;
    always @* begin
        case (ar_addr[9:2])
            8'h00: reg_rd = {8'd2, 8'd1, SID_S[7:0], 8'd0};
            8'h01: reg_rd = {8'd0, 8'd64, 8'd0, 8'd16};
            8'h02: reg_rd = {25'd0, arm_wrst, arm_run, 1'b0, go, 1'b0, st_sched, st_acc};
            8'h03: reg_rd = r_nacc;
            8'h04: reg_rd = r_ndump;
            8'h05: reg_rd = {28'd0, r_shift};
            8'h06: reg_rd = {24'd0, flags};
            8'h07: reg_rd = seq;
            8'h08: reg_rd = 32'd32768;
            8'h09: reg_rd = 32'd4096;
            8'h0A: reg_rd = {1'b1, 27'd0, c_src};
            8'h0B: reg_rd = r_cfg;
            8'h0C: reg_rd = run_cfg;
            8'h0D: reg_rd = wrst_cfg;
            8'h0E: reg_rd = {28'd0, c_shift};
            8'h0F: reg_rd = dk;
            8'h10: reg_rd = df0[31:0];
            8'h11: reg_rd = {{(64-FW){1'b0}}, df0[FW-1:32]};
            8'h12: reg_rd = dn;
            8'h13: reg_rd = dsat;
            8'h14: reg_rd = dt[31:0];
            8'h15: reg_rd = dt[63:32];
            8'h16: reg_rd = {16'd0, dh};
            8'h17: reg_rd = dcfg;
            8'h18: reg_rd = run_t[31:0];
            8'h19: reg_rd = run_t[63:32];
            8'h1A: reg_rd = run_f0[31:0];
            8'h1B: reg_rd = {{(64-FW){1'b0}}, run_f0[FW-1:32]};
            8'h1C: reg_rd = fin_lat[31:0];
            8'h1D: reg_rd = {{(64-FW){1'b0}}, fin_lat[FW-1:32]};
            8'h1E: reg_rd = fout_lat[31:0];
            8'h1F: reg_rd = {{(64-FW){1'b0}}, fout_lat[FW-1:32]};
            8'h20: reg_rd = {16'd0, 8'd16, 8'd16};
            8'h21: reg_rd = {29'd0, r_rec};
            8'h22: reg_rd = rec_late;
            8'h80: reg_rd = {16'd0, pfb_sat};
            8'h81: reg_rd = {ipq, 14'd0, go, have_first};
            8'h82: reg_rd = BUILD_TAG;
            8'h83: reg_rd = ip_ph;
            8'h84: reg_rd = {16'd0, ip_st};
            default: reg_rd = 32'd0;
        endcase
    end
    always @(posedge aclk) begin
        if (rst) begin
            ar_busy <= 1'b0; ar_wait <= 3'd0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0; ar_addr <= 10'd0;
            fin_lat <= {FW{1'b0}}; fout_lat <= {FW{1'b0}};
        end else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin
                ar_busy <= 1'b1; ar_wait <= 3'd0; ar_addr <= s_axi_araddr;
                if (s_axi_araddr[9:2] == 8'h1C) fin_lat  <= fa_now;     // LO を読むと HI を固定
                if (s_axi_araddr[9:2] == 8'h1E) fout_lat <= fo;
            end else if (ar_busy) begin
                ar_wait <= ar_wait + 3'd1;
                if (ar_wait == 3'd3) begin
                    ar_busy <= 1'b0; s_axi_rvalid <= 1'b1;
                    s_axi_rdata <= (ar_addr[9:8] == 2'd1) ? tp_reg_rd : reg_rd;
                end
            end
        end
    end
endmodule
