// SPDX-License-Identifier: BSD-3-Clause
//
// s2_strm — 2G-1-Fine の STAGE2 の流れ 1 本（INTERFACE 2.1 の KIND 5、ADR 0027）。proj037 U（S-2・T-2・T-3）
//
// 中身: 荒い段（coarse_pfb → cfft32 → coarse_post）・RUN の印と区切り・チャンクごとの帳簿・細かい側（fine_core）の頭の組み立て・流れのブロック。
// corner turn（ct_wr・ct_rd、MIG への AXI4）はこの外（BD のセル）。荒い段の出口を m_axis_ct で ct_wr へ、ct_rd の出口を s_axis_ct で受ける。
// YATSUGATAKE の g21_core（2G-1-Fast の FULL の流れ）を流れのブロックの手本にした。全部が DSP ドメイン（256 MHz）。
//
// ---- 時刻とブロックの位相（U-3）----
//   入力は axis_sel4 の出口（1 段のレジスタ）なので、s_axis の拍はコアの入口の T − 1 の拍（g21_core と同じ）。1 段受けて、
//   拍のラベル lbl = t_loc − 1 − 1 + LBL_FIX（受けた分）を付けて coarse_pfb に渡す。coarse_pfb は対の頭を lbl ≡ 0 (mod 7) に置く。
//   LBL_FIX は U-e（孤立したサンプル）で D_S = 0 になるように決める定数（既定 0）
//
// ---- RUN（U-3）----
//   CTRL[0] RUN: 次の対の頭（どれでも）から。CTRL[2] ARM_RUN ＋ time_core の発火: 発火の拍の t_loc（= START_AT）を的にし、
//   **o_t0 = START_AT の対の頭のブロック**から始める。的を越えた対の頭が来たら（START_AT が 7 の倍数でない）始めず FLAGS[1]。
//   前の RUN の区切りが出口まで済んでいないとき（act_in・out_arm・act_out）の RUN は受けず FLAGS[14]。
//   RUN_T = 頭のブロックの o_t0。チャンク c の頭のブロックの o_t0 をスタンプし、式 RUN_T ＋ c·BASE_BEATS と違えば FLAGS[2]
//   荒い段の入口で数えたブロックの番号 n_run を、出口で同じに数え、n_run のブロックに tuser の印。以後 N_DUMP チャンク（0 = 止めるまで）だけ
//   m_axis_ct に valid を出す。STOP・WRST は入口と出口の両方をすぐ止める（半端なチャンクは ct_wr で閉じないので細かい側に来ない）
//
// ---- 帳簿（U-4、4 面 = c mod 4）----
//   入口: チャンク c の {スタンプ, DUMP_H（[5:0] ev の OR）, DUMP_CFG, src, SHIFT} を、最後のブロックで閉じて c を付ける
//   出口: 荒い ch k の飽和の数え（coarse_post の m_clip）をチャンクの最後のブロックで写し、32 拍で記憶に書いて c を付ける
//   fine_core が読ませる拍（rdo_go）に {k, c の下位 16 bit, 積んだ数} を受け、c を出口のチャンクの数から 32 bit に戻して帳簿を引く。
//   3 拍で頭（w1..w7）を作って hdr_v。帳簿の c が違えば hdr_bad（そのレコードは tuser = 1）と FLAGS[3]
//   SEQ: rdo_go ごとに +1（REC_CTRL で出さないレコード・fine_rdo が捨てたものも進む = 欠けは SEQ の飛び）
//
// ---- 流れのブロック（INTERFACE 2.5。STAGE2 の読み方）----
//   0x00 SID {2, 5, SID_S, 0} / 0x04 PARAM {0, 64, 0, 17} / 0x08 CTRL / 0x0C N_ACC（書けるが効かない、既定 160）/ 0x10 N_DUMP（チャンク）/
//   0x14 SHIFT（細かい側の電力の前のシフト。RUN で取り込む）/ 0x18 FLAGS / 0x1C SEQ（最後に始めたレコード）/ 0x20 NCH 3,670,016 /
//   0x24 FRAME_BEATS 458,752 / 0x28 SRC / 0x2C CFG_ID / 0x30 RUN_CFG / 0x34 WRST_CFG / 0x38 RUN_SHIFT / 0x3C DUMP_K /
//   0x40·44 DUMP_F0 / 0x48 DUMP_N / 0x4C DUMP_SAT / 0x50·54 DUMP_T / 0x58 DUMP_H / 0x5C DUMP_CFG（最後の捨てなかったレコードの頭と同じ値）/
//   0x60·64 RUN_T / 0x68·6C RUN_F0（0: DUMP_F0 は RUN から数える）/ 0x70·74 FIN（入口のブロックの数。LO で HI を固定）/
//   0x78·7C FOUT（出口のブロックの数）/ 0x80 NFFT_MIN_MAX {0, 0, 17, 17} / 0x84 REC_CTRL / 0x88 REC_LATE
//   0x100〜0x1FF 種類に固有: 0x100 + 4k GAIN[k]（荒い ch の利得、coarse_post）
//   0x200〜0x3FF 診断（約束の外）: 0x200 + 8k POW[k]・0x300 + 4k CLIP[k]・0x380 POW の NACC・0x384 POW の SEQ（coarse_post）/
//     0x3C0 [0] 細かい側の SRST（1 の間リセット）/ 0x3C4 fine_core の FLAGS / 0x3C8 fine_core のレコードの数 / 0x3CC BUILD_TAG /
//     0x3D0 {ph_err, ph_lock}
//   CTRL W: [0] RUN / [1] STOP / [2] ARM_RUN / [3] 予約の取り消し / [8] FLAGS を消す / [12] WRST（SRC・CFG_ID を取り込み、RUN を止める）/ [13] ARM_WRST
//        R: [0] 入口が区切り中 [1] 開始待ち [2] 出口が区切り中 [5] ARM_RUN 中 [6] ARM_WRST 中
//   FLAGS（粘着、CTRL[8] で消す）: [0] ブロックの位相の食い違い / [1] START_AT が対の頭でない（RUN を受けなかった）/ [2] スタンプが式と違う /
//     [3] 帳簿の c が違う（捨てたレコード）/ [12:4] fine_core の FLAGS / [14] 前の RUN が済む前の RUN（受けなかった）
//
// -DS2_MARK_LATE: 印を 1 ブロック遅らせる（陽性対照。U-e で D_S が 3.5 ビート出るべき）
// -DS2_S0_ERR: 語 7 の S0 を (k ＋ 1)·114,688 にする（陽性対照。U-c で落ちるべき）

`timescale 1ns / 1ps

module s2_strm #(
    parameter integer SID_S         = 0,
    parameter integer REC_CORE      = 0,
    parameter integer B_C           = 20971520,    // 1 チャンクの荒いブロックの数（286.72 ms）
    parameter integer BASE_BEATS    = 73400320,    // = 3.5·B_C
    parameter integer N_ACC_DEFAULT = 160,
    parameter integer SHIFT_DEFAULT = 7,
    parameter integer LBL_FIX       = 0,
    parameter integer REC_W         = 114688,      // 本体の語の数（語 7 の P = 8·REC_W だけに効く。sim でスタブに合わせて縮める）
    parameter integer BUILD_TAG     = 0,
    parameter LO_FILE = "fine_coef_lo.hex",
    parameter HI_FILE = "fine_coef_hi.hex",
    parameter TA_FILE = "fine_tw_a.hex",
    parameter TB_FILE = "fine_tw_b.hex"
)(
    input  wire          aclk,
    input  wire          aresetn,
    input  wire [255:0]  s_axis_tdata,
    input  wire          s_axis_tvalid,
    // AXI4-Lite（流れ 1 本のブロック、10 bit）
    input  wire [9:0]    s_axi_awaddr,
    input  wire          s_axi_awvalid,
    output wire          s_axi_awready,
    input  wire [31:0]   s_axi_wdata,
    input  wire          s_axi_wvalid,
    output wire          s_axi_wready,
    output reg           s_axi_bvalid,
    input  wire          s_axi_bready,
    input  wire [9:0]    s_axi_araddr,
    input  wire          s_axi_arvalid,
    output wire          s_axi_arready,
    output reg  [31:0]   s_axi_rdata,
    output reg           s_axi_rvalid,
    input  wire          s_axi_rready,
    output wire [1:0]    src_sel,
    input  wire [63:0]   t_in,
    input  wire          go_in,
    input  wire [3:0]    tev_in,
    // 荒い段の出口 → ct_wr（受け手は止めない。溢れは ct_wr が数える）
    output wire [511:0]  m_axis_ct_tdata,
    output wire          m_axis_ct_tuser,      // RUN の頭のブロック
    output wire          m_axis_ct_tvalid,
    // ct_rd → 細かい側
    input  wire [511:0]  s_axis_ct_tdata,
    input  wire [21:0]   s_axis_ct_tuser,
    input  wire          s_axis_ct_tlast,
    input  wire          s_axis_ct_tvalid,
    output wire          s_axis_ct_tready,
    // レコード → rec_arb
    output wire [63:0]   m_axis_rec_tdata,
    output wire          m_axis_rec_tvalid,
    input  wire          m_axis_rec_tready,
    output wire          m_axis_rec_tlast,
    output wire          m_axis_rec_tuser,
    output reg           rec_drop
);
    wire rst = ~aresetn;
    localparam [31:0] NCH = 32'd3670016, FRB = 32'd458752, CHS = 32'd114688;

    // ---- 時刻・入力（1 段受ける）----
    reg [63:0]  t_loc;
    reg         go_loc;
    reg [3:0]   tev_loc;
    reg [255:0] d_loc;
    reg         v_loc;
    reg [63:0]  lbl;
    always @(posedge aclk) begin
        t_loc <= t_in; go_loc <= go_in; tev_loc <= tev_in;
        d_loc <= s_axis_tdata; v_loc <= s_axis_tvalid;
        lbl <= t_loc - 64'd1 + LBL_FIX;              // s_axis の拍はコアの入口の t_loc − 1（axis_sel4 の 1 段）。受けた 1 段で t_loc も 1 進むので相殺
    end
    wire a_ovr, a_gap;
    adc_ev u_aev (.clk(aclk), .rst(rst), .tdata(s_axis_tdata), .tvalid(s_axis_tvalid), .ovr(a_ovr), .gap(a_gap));
    wire [5:0] ev = {a_gap, a_ovr, tev_loc};

    // ---- AXI4-Lite の書き ----
    reg [31:0] r_nacc, r_ndump, r_cfg;
    reg [3:0]  r_shift, r_src, c_src;
    reg [2:0]  r_rec;
    reg        arm_run, arm_wrst;
    reg        cmd_run, cmd_arm_go, cmd_stop, cmd_wrst, cmd_fclr;
    reg        f_srst;
    reg        one_clr;
    wire       wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    wire [9:0] wa = s_axi_awaddr;
    // coarse_post への写し（0x100〜0x3BF）
    function automatic [11:0] cp_map(input [9:0] a);
        cp_map = (a[9:8] == 2'b01 || a[9:8] == 2'b10) ? {2'b00, a} :
                 (a[9:7] == 3'b110)                   ? {5'b01000, a[6:0]} :
                 (a == 10'h380)                       ? 12'h004 :
                 (a == 10'h384)                       ? 12'h008 : 12'hFFC;
    endfunction
    wire cp_reg_w = (wa[9:8] != 2'd0) && (wa < 10'h3C0);
    always @(posedge aclk) begin
        cmd_run    <= 1'b0;
        cmd_arm_go <= go_loc && arm_run;
        cmd_wrst   <= go_loc && arm_wrst;
        cmd_stop <= 1'b0; cmd_fclr <= 1'b0;
        if (go_loc) begin arm_run <= 1'b0; arm_wrst <= 1'b0; end
        if (rst) begin
            s_axi_bvalid <= 1'b0; arm_run <= 1'b0; arm_wrst <= 1'b0; f_srst <= 1'b0;
            r_nacc <= N_ACC_DEFAULT; r_ndump <= 32'd0; r_cfg <= 32'd0; r_shift <= SHIFT_DEFAULT; r_src <= 4'd0; r_rec <= 3'd0;
        end else begin
            if (one_clr) r_rec[1] <= 1'b0;
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) s_axi_bvalid <= 1'b1;
            if (wr_go && wa[9:8] == 2'd0) begin
                case (wa[7:2])
                    6'h02: begin
                        cmd_run  <= s_axi_wdata[0];
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
                    6'h0A: r_src   <= s_axi_wdata[3:0];
                    6'h0B: r_cfg   <= s_axi_wdata;
                    6'h21: r_rec   <= s_axi_wdata[2:0];
                    default: ;
                endcase
            end
            if (wr_go && wa == 10'h3C0) f_srst <= s_axi_wdata[0];
        end
    end
    reg [31:0] wrst_cfg;
    always @(posedge aclk) begin
        if (rst) begin c_src <= 4'd0; wrst_cfg <= 32'd0; end
        else if (cmd_wrst) begin c_src <= r_src; wrst_cfg <= r_cfg; end
    end
    assign src_sel = c_src[1:0];

    // ---- 荒い段 ----
    wire          zv, fv, cp_v, o_blk, o_blk_b, ph_lock, ph_err;
    wire [63:0]   o_t0;
    wire [64*18-1:0] z;
    wire [32*2*24-1:0] f;
    wire [511:0]  cp_y;
    wire [63:0]   cp_clip;
    reg  [11:0]   cp_awaddr, cp_araddr;
    reg           cp_awv, cp_arv;
    reg  [31:0]   cp_wdata;
    wire [31:0]   cp_rdata;
    wire          cp_rvalid;
    coarse_pfb u_pfb (.clk(aclk), .rst(rst), .s_valid(v_loc), .s_data(d_loc), .s_t(lbl), .ph_clr(cmd_fclr),
        .m_valid(zv), .m_z(z), .o_blk(o_blk), .o_blk_b(o_blk_b), .o_t0(o_t0), .ph_lock(ph_lock), .ph_err(ph_err));
    cfft32 u_fft (.clk(aclk), .s_valid(zv), .s_z(z), .m_valid(fv), .m_f(f));
    coarse_post u_post (.clk(aclk), .aresetn(aresetn), .s_valid(fv), .s_f(f), .m_valid(cp_v), .m_y(cp_y), .m_clip(cp_clip),
        .s_axi_awaddr(cp_awaddr), .s_axi_awvalid(cp_awv), .s_axi_awready(), .s_axi_wdata(cp_wdata), .s_axi_wvalid(cp_awv), .s_axi_wready(),
        .s_axi_bvalid(), .s_axi_bresp(), .s_axi_bready(1'b1),
        .s_axi_araddr(cp_araddr), .s_axi_arvalid(cp_arv), .s_axi_arready(), .s_axi_rdata(cp_rdata), .s_axi_rvalid(cp_rvalid),
        .s_axi_rresp(), .s_axi_rready(1'b1));
    always @(posedge aclk) begin
        cp_awv <= wr_go && cp_reg_w && !rst; cp_awaddr <= cp_map(wa); cp_wdata <= s_axi_wdata;
    end

    // ---- 入口の側: RUN の的・区切り・入口の帳簿 ----
    reg  [47:0] ib, n_run;
    reg         pend, pend_any, act_in, out_arm, act_out;
    reg  [63:0] tgt, run_t, exp_t;
    reg  [31:0] bc_in, c_in, hnd, run_cfg;
    reg  [3:0]  c_shift, run_src;
    reg  [5:0]  dh_acc;
    reg  [7:0]  flg;
    // 帳簿（入口）
    reg  [31:0] li_tag [0:3];
    reg  [3:0]  li_ok;
    reg  [63:0] li_t   [0:3];
    reg  [5:0]  li_dh  [0:3];
    reg  [31:0] li_cfg [0:3];
    reg  [3:0]  li_src [0:3];
    reg  [3:0]  li_sh  [0:3];
    wire busy_run = pend || act_in || out_arm || act_out;
    wire run_req  = (cmd_run || cmd_arm_go) && !cmd_wrst;
    wire hit      = o_blk && o_blk_b && pend && (pend_any || o_t0 == tgt);
    wire miss     = o_blk && o_blk_b && pend && !pend_any && (o_t0 > tgt);
    wire take_in  = o_blk && (act_in || hit);
    wire [31:0] bci = hit ? 32'd0 : bc_in;
    wire [31:0] cci = hit ? 32'd0 : c_in;
    wire [63:0] ext = hit ? o_t0 : exp_t;
    wire        stop = cmd_stop || cmd_wrst;
    integer q;
    always @(posedge aclk) begin
        if (rst) begin
            ib <= 48'd0; n_run <= 48'd0; pend <= 1'b0; pend_any <= 1'b0; act_in <= 1'b0; out_arm <= 1'b0;
            tgt <= 64'd0; run_t <= 64'd0; exp_t <= 64'd0; bc_in <= 32'd0; c_in <= 32'd0; hnd <= 32'd0; run_cfg <= 32'd0;
            c_shift <= SHIFT_DEFAULT; run_src <= 4'd0; dh_acc <= 6'd0; flg <= 8'd0; li_ok <= 4'd0;
            for (q = 0; q < 4; q = q + 1) li_tag[q] <= 32'hFFFF_FFFF;
        end else begin
            if (o_blk) ib <= ib + 48'd1;
            if (run_req) begin
                if (busy_run) flg[6] <= 1'b1;
                else begin
                    pend <= 1'b1; pend_any <= cmd_run; tgt <= t_loc - 64'd1;     // cmd_arm_go は go_loc（t_loc = START_AT）の 1 拍後
                    hnd <= r_ndump; run_cfg <= r_cfg; c_shift <= r_shift; run_src <= c_src;
                end
            end
            if (miss) begin pend <= 1'b0; flg[1] <= 1'b1; end
            if (hit) begin
                pend <= 1'b0; act_in <= 1'b1; out_arm <= 1'b1; run_t <= o_t0;
`ifdef S2_MARK_LATE
                n_run <= ib + 48'd1;
`else
                n_run <= ib;
`endif
            end
            // ev はブロックの拍に依らず毎拍 OR
            if (act_in || hit) dh_acc <= (take_in && bci == 32'd0) ? ev : (dh_acc | ev);
            if (take_in) begin
                if (bci == 32'd0) begin
                    li_t[cci[1:0]] <= o_t0; li_ok[cci[1:0]] <= 1'b0;
                    if (o_t0 != ext) flg[2] <= 1'b1;
                    exp_t <= ext + BASE_BEATS;
                end
                if (bci == B_C - 1) begin
                    li_tag[cci[1:0]] <= cci; li_ok[cci[1:0]] <= 1'b1; li_dh[cci[1:0]] <= dh_acc | ev;
                    li_cfg[cci[1:0]] <= run_cfg; li_src[cci[1:0]] <= run_src; li_sh[cci[1:0]] <= c_shift;
                    bc_in <= 32'd0; c_in <= cci + 32'd1;
                    if (hnd != 32'd0 && cci + 32'd1 == hnd) act_in <= 1'b0;
                end else begin
                    bc_in <= bci + 32'd1; c_in <= cci;
                end
            end
            if (out_arm && act_out) out_arm <= 1'b0;
            if (stop) begin pend <= 1'b0; act_in <= 1'b0; out_arm <= 1'b0; end
            if (ph_err) flg[0] <= 1'b1;
            if (cmd_fclr) flg <= 8'd0;
        end
    end

    // ---- 出口の側: 印・区切り・飽和の帳簿 ----
    reg  [47:0] ob;
    reg  [31:0] bc_out, c_out;
    wire        mark  = cp_v && out_arm && !act_out && (ob == n_run);
    wire        take_o = cp_v && (act_out || mark);
    wire [31:0] bco = mark ? 32'd0 : bc_out;
    wire [31:0] cco = mark ? 32'd0 : c_out;
    reg  [31:0] sat_c [0:31];
    reg  [31:0] sat_s [0:31];
    reg         cp_go;
    reg  [5:0]  cp_k;
    reg  [31:0] cp_c;
    reg  [31:0] lo_tag [0:3];
    (* ram_style = "distributed" *) reg [31:0] sat_ram [0:127];
    integer kk;
    always @(posedge aclk) begin
        if (rst) begin
            ob <= 48'd0; act_out <= 1'b0; bc_out <= 32'd0; c_out <= 32'd0; cp_go <= 1'b0; cp_k <= 6'd0; cp_c <= 32'd0;
            for (q = 0; q < 4; q = q + 1) lo_tag[q] <= 32'hFFFF_FFFF;
        end else begin
            if (cp_v) ob <= ob + 48'd1;
            if (mark) act_out <= 1'b1;
            if (take_o) begin
                for (kk = 0; kk < 32; kk = kk + 1)
                    sat_c[kk] <= ((bco == 32'd0) ? 32'd0 : sat_c[kk]) + cp_clip[2*kk +: 2];
                if (bco == B_C - 1) begin
                    for (kk = 0; kk < 32; kk = kk + 1) sat_s[kk] <= sat_c[kk] + cp_clip[2*kk +: 2];
                    cp_go <= 1'b1; cp_k <= 6'd0; cp_c <= cco;
                    bc_out <= 32'd0; c_out <= cco + 32'd1;
                    if (hnd != 32'd0 && cco + 32'd1 == hnd) act_out <= 1'b0;
                end else begin
                    bc_out <= bco + 32'd1; c_out <= cco;
                end
            end
            // 写し: 32 拍で記憶へ、最後に c を付ける
            if (cp_go) begin
                sat_ram[{cp_c[1:0], cp_k[4:0]}] <= sat_s[cp_k[4:0]];
                if (cp_k == 6'd31) begin cp_go <= 1'b0; lo_tag[cp_c[1:0]] <= cp_c; end
                cp_k <= cp_k + 6'd1;
            end
            if (stop) act_out <= 1'b0;
        end
    end
    assign m_axis_ct_tdata  = cp_y;
    assign m_axis_ct_tvalid = take_o;
    assign m_axis_ct_tuser  = mark;

    // ---- 細かい側 ----
    wire        rdo_go;
    wire [4:0]  rdo_k;
    wire [15:0] rdo_c, rdo_n, rdo_nd;
    wire [8:0]  fflags;
    wire [31:0] f_nrec;
    reg         hdr_v, hdr_bad;
    reg  [447:0] hdr;
    reg         rdo_en;
    reg  [31:0] one_c;
    reg         one_act;
    reg f_rst = 1'b1;
    always @(posedge aclk) f_rst <= rst || f_srst;
    // c の下位 16 bit を出口のチャンクの数（読むチャンク ≦ c_out）から 32 bit に戻す
    wire [15:0] c_back = c_out[15:0] - rdo_c;
    wire [31:0] c_full = c_out - {16'd0, c_back};
    always @* rdo_en = r_rec[0] || (one_act && c_full == one_c) || (r_rec[1] && !one_act && rdo_k == 5'd0);
    fine_core #(.SID_S(SID_S), .REC_CORE(REC_CORE), .LO_FILE(LO_FILE), .HI_FILE(HI_FILE), .TA_FILE(TA_FILE), .TB_FILE(TB_FILE)) u_fine (
        .clk(aclk), .rst(f_rst),
        .s_axis_tdata(s_axis_ct_tdata), .s_axis_tuser(s_axis_ct_tuser), .s_axis_tlast(s_axis_ct_tlast),
        .s_axis_tvalid(s_axis_ct_tvalid), .s_axis_tready(s_axis_ct_tready), .shift(c_shift),
        .m_axis_tdata(m_axis_rec_tdata), .m_axis_tlast(m_axis_rec_tlast), .m_axis_tuser(m_axis_rec_tuser),
        .m_axis_tvalid(m_axis_rec_tvalid), .m_axis_tready(m_axis_rec_tready),
        .rdo_go(rdo_go), .rdo_k(rdo_k), .rdo_c(rdo_c), .rdo_n(rdo_n), .rdo_en(rdo_en),
        .hdr_v(hdr_v), .hdr(hdr), .hdr_bad(hdr_bad), .rdo_ndrop(rdo_nd),
        .flags(fflags), .n_rec(f_nrec), .dbg_ip_tdata(), .dbg_ip_k1(), .dbg_ip_v());

    // 頭の組み立て（3 段）
    reg  [31:0] seq, g_seq, g_c, g_sat;
    reg  [4:0]  g_k;
    reg  [15:0] g_n;
    reg  [2:0]  g_sh;
    reg  [1:0]  g_i;
    reg         g_bad;
    // 最後のレコードの値（流れのブロックで読む）
    reg  [31:0] d_k, d_n, d_sat, d_cfg;
    reg  [63:0] d_t, d_f0;
    reg  [15:0] d_h;
    reg  [3:0]  d_shift, d_src;
    reg  [15:0] nd_prev;
    reg  [31:0] rec_late;
    reg         flg3;
    wire [31:0] flags = {17'd0, flg[6], 1'b0, fflags, flg3, flg[2], flg[1], flg[0]};
`ifdef S2_S0_ERR
    wire [31:0] s0 = ({27'd0, g_k} + 32'd1) * CHS;
`else
    wire [31:0] s0 = {27'd0, g_k} * CHS;
`endif
    always @(posedge aclk) begin
        hdr_v <= 1'b0; one_clr <= 1'b0; rec_drop <= 1'b0;
        if (rst) begin
            seq <= 32'd0; g_sh <= 3'd0; one_act <= 1'b0; one_c <= 32'd0; nd_prev <= 16'd0; rec_late <= 32'd0; flg3 <= 1'b0;
            d_k <= 0; d_n <= 0; d_sat <= 0; d_cfg <= 0; d_t <= 0; d_f0 <= 0; d_h <= 0; d_shift <= 0; d_src <= 0;
        end else begin
            g_sh <= {g_sh[1:0], rdo_go};
            if (rdo_go) begin
                g_seq <= seq; seq <= seq + 32'd1; g_k <= rdo_k; g_c <= c_full; g_n <= rdo_n; g_i <= c_full[1:0];
                if (!r_rec[0] && r_rec[1] && !one_act && rdo_k == 5'd0) begin one_act <= 1'b1; one_c <= c_full; end
                if (one_act && c_full == one_c && rdo_k == 5'd31) begin one_act <= 1'b0; one_clr <= 1'b1; end
            end
            if (g_sh[0]) begin
                g_sat <= sat_ram[{g_i, g_k}];
                g_bad <= !li_ok[g_i] || li_tag[g_i] != g_c || lo_tag[g_i] != g_c;
            end
            if (g_sh[1]) begin
                hdr_v   <= 1'b1;
                hdr_bad <= g_bad;
                hdr[ 63:  0] <= {g_c, g_seq};                                                    // w1 {DUMP_K, SEQ}
                hdr[127: 64] <= {32'd0, g_c} * B_C;                                              // w2 DUMP_F0
                hdr[191:128] <= li_t[g_i];                                                       // w3 DUMP_T
                hdr[255:192] <= {10'd0, li_dh[g_i], 4'd0, li_src[g_i], 8'd0, 8'd0, 4'd0, li_sh[g_i], 8'd6, 8'd17}; // w4
                hdr[319:256] <= {g_sat, 16'd0, g_n};                                             // w5 {DUMP_SAT, DUMP_N}
                hdr[383:320] <= {flags, li_cfg[g_i]};                                            // w6 {FLAGS, DUMP_CFG}
                hdr[447:384] <= {s0, REC_W * 32'd8};                                             // w7 {S0, P = 8·REC_W = 917,504}
                if (g_bad) flg3 <= 1'b1;
                else begin                                                                       // 流れのブロックの DUMP_* は捨てなかったレコードの値
                    d_k <= g_c; d_n <= {16'd0, g_n}; d_sat <= g_sat; d_cfg <= li_cfg[g_i]; d_t <= li_t[g_i];
                    d_f0 <= {32'd0, g_c} * B_C; d_h <= {10'd0, li_dh[g_i]}; d_shift <= li_sh[g_i]; d_src <= li_src[g_i];
                end
            end
            nd_prev <= rdo_nd;
            // rec_drop は読み始めなかったレコード（fine_rdo の n_drop）だけ。帳簿に無いレコードは tuser = 1 で出し、
            // リングが DROP_CNT に数える（両方で数えると 1 本が 2 になる。U-d の 1 回目）。REC_LATE はどちらも数える
            if (rdo_nd != nd_prev) rec_drop <= 1'b1;
            if ((rdo_nd != nd_prev || (g_sh[1] && g_bad)) && rec_late != 32'hFFFF_FFFF) rec_late <= rec_late + 32'd1;
            if (cmd_fclr) flg3 <= 1'b0;
        end
    end

    // ---- AXI4-Lite の読み（受けてから 4 クロック。g21_core と同じ）----
    reg [2:0]  ar_wait;
    reg        ar_busy;
    reg [9:0]  ar_addr;
    reg [47:0] fin_lat, fout_lat;
    reg [31:0] cp_rlat;
    assign s_axi_arready = !ar_busy && !s_axi_rvalid;
    reg [31:0] reg_rd;
    always @* begin
        case (ar_addr[9:2])
            8'h00: reg_rd = {8'd2, 8'd5, SID_S[7:0], 8'd0};
            8'h01: reg_rd = {8'd0, 8'd64, 8'd0, 8'd17};
            8'h02: reg_rd = {25'd0, arm_wrst, arm_run, 2'd0, act_out, pend, act_in};
            8'h03: reg_rd = r_nacc;
            8'h04: reg_rd = r_ndump;
            8'h05: reg_rd = {28'd0, r_shift};
            8'h06: reg_rd = flags;
            8'h07: reg_rd = seq - 32'd1;
            8'h08: reg_rd = NCH;
            8'h09: reg_rd = FRB;
            8'h0A: reg_rd = {1'b1, 27'd0, c_src};
            8'h0B: reg_rd = r_cfg;
            8'h0C: reg_rd = run_cfg;
            8'h0D: reg_rd = wrst_cfg;
            8'h0E: reg_rd = {28'd0, c_shift};
            8'h0F: reg_rd = d_k;
            8'h10: reg_rd = d_f0[31:0];
            8'h11: reg_rd = d_f0[63:32];
            8'h12: reg_rd = d_n;
            8'h13: reg_rd = d_sat;
            8'h14: reg_rd = d_t[31:0];
            8'h15: reg_rd = d_t[63:32];
            8'h16: reg_rd = {16'd0, d_h};
            8'h17: reg_rd = d_cfg;
            8'h18: reg_rd = run_t[31:0];
            8'h19: reg_rd = run_t[63:32];
            8'h1A: reg_rd = 32'd0;
            8'h1B: reg_rd = 32'd0;
            8'h1C: reg_rd = fin_lat[31:0];
            8'h1D: reg_rd = {16'd0, fin_lat[47:32]};
            8'h1E: reg_rd = fout_lat[31:0];
            8'h1F: reg_rd = {16'd0, fout_lat[47:32]};
            8'h20: reg_rd = {16'd0, 8'd17, 8'd17};
            8'h21: reg_rd = {29'd0, r_rec};
            8'h22: reg_rd = rec_late;
            8'hF0: reg_rd = {31'd0, f_srst};
            8'hF1: reg_rd = {23'd0, fflags};
            8'hF2: reg_rd = f_nrec;
            8'hF3: reg_rd = BUILD_TAG;
            8'hF4: reg_rd = {30'd0, ph_err, ph_lock};
            default: reg_rd = 32'd0;
        endcase
    end
    wire ar_cp = (ar_addr[9:8] != 2'd0) && (ar_addr < 10'h3C0);
    always @(posedge aclk) begin
        cp_arv <= 1'b0;
        if (cp_rvalid) cp_rlat <= cp_rdata;
        if (rst) begin
            ar_busy <= 1'b0; ar_wait <= 3'd0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0; ar_addr <= 10'd0;
            fin_lat <= 48'd0; fout_lat <= 48'd0;
        end else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin
                ar_busy <= 1'b1; ar_wait <= 3'd0; ar_addr <= s_axi_araddr;
                cp_arv <= (s_axi_araddr[9:8] != 2'd0) && (s_axi_araddr < 10'h3C0); cp_araddr <= cp_map(s_axi_araddr);
                if (s_axi_araddr[9:2] == 8'h1C) fin_lat  <= ib;
                if (s_axi_araddr[9:2] == 8'h1E) fout_lat <= ob;
            end else if (ar_busy) begin
                ar_wait <= ar_wait + 3'd1;
                if (ar_wait == 3'd3) begin
                    ar_busy <= 1'b0; s_axi_rvalid <= 1'b1;
                    s_axi_rdata <= ar_cp ? cp_rlat : reg_rd;
                end
            end
        end
    end
endmodule
