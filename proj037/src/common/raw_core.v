// SPDX-License-Identifier: BSD-3-Clause
//
// raw_core — 生サンプルの流れ（INTERFACE v2 の KIND 4 = RAW）。proj021 手順 2-5 で起こした
//
// 選んだ ADC の生サンプル（axis_sel4 の出口。16 サンプル × 16 bit / ビート、下位が古い）を、ダンプごとに頭の 1 フレーム
// （512 ビート = 8192 サンプル）だけ取り、SNAP のレコード（type 4）で出す。FFT・積分・TP は持たない。
// SAM45-Fine で FULL（spec_core）の代わりに置く（F-2 の 1PPS の縁・specd の SNAP 命令に使う）。
//
// ---- 区切り（spec_core と同じ約束）----
//   フレーム = 受けた有効なビート 512 個（fin = フレームの番号、m_in = フレームの中のビート）。
//   RUN（CTRL[0]、または ARM_RUN と time_core の発火）の時点の fin を f として、ダンプ k の頭のフレームは f + 2 + k·N（N = N_ACC、0 は 1）。
//   N_DUMP（≠ 0）個で止まる。ダンプ k は頭のフレームから N フレームが過ぎたところ（次のフレームの頭のクロック）で閉じる（SEQ + 1）。
//   **DUMP_T = 頭のフレームの最初のビートを口で受けたクロックの t_loc**（spec_core の DUMP_T と同じ点。t_loc は t_in を 1 段受けたもの）
//   DUMP_H = そのダンプの間に ev（[3:0] time_core の健全性・[4] 振り切れ・[5] 入力の途切れ）のどれかが 1 だったか（OR）
//
// ---- 記憶とレコード ----
//   2 面 × 512 ビート × 256 bit（BRAM36 × 8）。ダンプの頭で空いた面に取る。空いた面が無ければ取らない（そのダンプは閉じたときに
//   REC_LATE + 1・rec_drop）。閉じたダンプは REC_CTRL の ALL（毎回）・ONE（1 回だけ。出したら 0 に戻す）で SNAP のレコードにする:
//     頭 w0 {s, core, 4, 1, "S45R"} / w1 {DUMP_K, SEQ} / w2 DUMP_F0 / w3 DUMP_T / w4 {DUMP_H, SRC, 0, 0, 0, 0, 13} / w5 {0, DUMP_N} /
//     w6 {FLAGS, DUMP_CFG} / w7 16,384（中身のバイト数）、中身 2,048 語（語 j = サンプル 4j〜4j+3。spec_core の SNAP と同じ並び）
//   レコードを出さないダンプの面はすぐ空ける。出すレコードは閉じた順に 2 つまで待たせる（面の数）
//
// ---- 番地（流れのブロックの 10 bit。INTERFACE 2.5。s45_core が振る）----
//   0x00 SID {2, 4, s, 0} / 0x04 PARAM [7:0] 13 / 0x08 CTRL / 0x0C N_ACC / 0x10 N_DUMP / 0x14 SHIFT（受けるが効かない）/ 0x18 FLAGS / 0x1C SEQ /
//   0x20 NCH 0 / 0x24 FRAME_BEATS 512 / 0x28 SRC（[3:0] 今効いている入力・[31] 1。書いた値は WRST で効く）/ 0x2C CFG_ID / 0x30 RUN_CFG /
//   0x34 WRST_CFG / 0x38 RUN_SHIFT / 0x3C DUMP_K / 0x40·44 DUMP_F0 / 0x48 DUMP_N / 0x4C DUMP_SAT（0）/ 0x50·54 DUMP_T / 0x58 DUMP_H /
//   0x5C DUMP_CFG / 0x60·64 RUN_T / 0x68·6C RUN_F0 / 0x70·74 FIN（LO を読むと HI を固定）/ 0x78·7C FOUT（= FIN）/ 0x80 NFFT_MIN_MAX 0 /
//   0x84 REC_CTRL / 0x88 REC_LATE。ほかは 0
//   CTRL W: [0] RUN / [1] STOP / [2] ARM_RUN / [3] 予約の取り消し / [8] FLAGS を消す / [12] WRST（SRC・CFG_ID を取り込む）/ [13] ARM_WRST。
//          [9]〜[11]（spec_core の診断を消す・SRST・GRST）は受けるが効かない
//        R: [0] ダンプ中 / [1] 頭のフレーム待ち / [3] 入力が流れ始めた / [5] ARM_RUN 中 / [6] ARM_WRST 中
//   FLAGS（粘着、CTRL[8] で消す）: [4] 入力の途切れ（最初のビートの後に valid = 0 のクロック）

`timescale 1ns / 1ps

module raw_core #(
    parameter integer N_ACC_DEFAULT = 1,
    parameter integer SID_S         = 2,
    parameter integer REC_CORE      = 0
)(
    input  wire         aclk,
    input  wire         aresetn,
    input  wire [255:0] s_axis_tdata,
    input  wire         s_axis_tvalid,
    output wire         s_axis_tready,
    input  wire [15:0]  s_axi_awaddr,
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
    input  wire [15:0]  s_axi_araddr,
    input  wire [2:0]   s_axi_arprot,
    input  wire         s_axi_arvalid,
    output wire         s_axi_arready,
    output reg  [31:0]  s_axi_rdata,
    output wire [1:0]   s_axi_rresp,
    output reg          s_axi_rvalid,
    input  wire         s_axi_rready,
    input  wire [63:0]  t_in,
    input  wire         go_in,
    input  wire [3:0]   tev_in,
    output wire [1:0]   src_sel,
    output wire [63:0]  m_axis_rec_tdata,
    output wire         m_axis_rec_tvalid,
    input  wire         m_axis_rec_tready,
    output wire         m_axis_rec_tlast,
    output wire         m_axis_rec_tuser,
    output reg          rec_drop
);
    localparam integer FW = 48;
    localparam [7:0] SS8 = SID_S;
    localparam [7:0] RC8 = REC_CORE;
    wire rst = ~aresetn;
    assign s_axis_tready = 1'b1;
    assign s_axi_bresp = 2'b00;
    assign s_axi_rresp = 2'b00;
    assign m_axis_rec_tuser = 1'b0;

    // ---- 時刻（1 段受ける。spec_core と同じ）----
    (* max_fanout = 32 *) reg [63:0] t_loc;
    reg go_loc;
    reg [3:0] tev_loc;
    always @(posedge aclk) begin t_loc <= t_in; go_loc <= go_in; tev_loc <= tev_in; end

    // ---- 書き込み ----
    reg [31:0] r_nacc, r_ndump, r_cfg;
    reg [3:0]  r_shift, r_src, c_src;
    reg [2:0]  r_rec;
    reg        arm_run, arm_wrst, cmd_run, cmd_stop, cmd_clr, cmd_wrst;
    reg [31:0] c_cfg;
    reg        one_clr;
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    always @(posedge aclk) begin
        cmd_run <= go_loc && arm_run; cmd_wrst <= go_loc && arm_wrst; cmd_stop <= 1'b0; cmd_clr <= 1'b0;
        if (go_loc) begin arm_run <= 1'b0; arm_wrst <= 1'b0; end
        if (rst) begin
            s_axi_bvalid <= 1'b0; r_nacc <= N_ACC_DEFAULT; r_ndump <= 32'd0; r_shift <= 4'd0; r_cfg <= 32'd0;
            r_src <= 4'd0; r_rec <= 3'd0; arm_run <= 1'b0; arm_wrst <= 1'b0;
        end else begin
            if (one_clr) r_rec[1] <= 1'b0;
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) begin
                s_axi_bvalid <= 1'b1;
                if (s_axi_awaddr[15:10] == 6'd0)
                case (s_axi_awaddr[9:2])
                    8'h02: begin
                        cmd_run  <= s_axi_wdata[0] | (go_loc && arm_run);
                        cmd_wrst <= s_axi_wdata[12] | (go_loc && arm_wrst);
                        if (s_axi_wdata[2])  arm_run  <= 1'b1;
                        if (s_axi_wdata[13]) arm_wrst <= 1'b1;
                        if (s_axi_wdata[3] || s_axi_wdata[1]) begin arm_run <= 1'b0; arm_wrst <= 1'b0; end
                        cmd_stop <= s_axi_wdata[1];
                        cmd_clr  <= s_axi_wdata[8];
                    end
                    8'h03: r_nacc  <= s_axi_wdata;
                    8'h04: r_ndump <= s_axi_wdata;
                    8'h05: r_shift <= s_axi_wdata[3:0];
                    8'h0A: r_src   <= s_axi_wdata[3:0];
                    8'h0B: r_cfg   <= s_axi_wdata;
                    8'h21: r_rec   <= s_axi_wdata[2:0];
                    default: ;
                endcase
            end
        end
    end
    always @(posedge aclk) begin
        if (rst) begin c_src <= 4'd0; c_cfg <= 32'd0; end
        else if (cmd_wrst) begin c_src <= r_src; c_cfg <= r_cfg; end
    end
    assign src_sel = c_src[1:0];

    // ---- 入力と健全性（spec_core と同じく、口の s_axis をそのまま数える。DUMP_T が spec_core の DUMP_T と同じ点になる）----
    wire [255:0] x_d = s_axis_tdata;
    wire         v_d = s_axis_tvalid && !rst;
    wire a_ovr, a_gap;
    adc_ev u_aev (.clk(aclk), .rst(rst), .tdata(s_axis_tdata), .tvalid(s_axis_tvalid), .ovr(a_ovr), .gap(a_gap));
    reg  [5:0] ev;
    always @(posedge aclk) ev <= {a_gap, a_ovr, tev_loc};
    reg        started, f_gap;
    reg  [8:0] m_in;
    reg  [FW-1:0] fin;
    wire       fhead = v_d && (m_in == 9'd0);

    // ---- 区切り ----
    reg  [31:0] run_n, run_nd;
    reg  [FW-1:0] run_f0, f_next;
    reg  [63:0] run_t;
    reg  [31:0] run_cfg;
    reg  [3:0]  run_shift;
    reg         on;            // 次の頭のフレームを待っている（RUN の後、N_DUMP に達するまで）
    reg  [31:0] k_next;        // 次に始めるダンプの番号
    reg         open_;         // 開いているダンプがある
    reg  [31:0] o_k;
    reg  [FW-1:0] o_f0, o_end;
    reg  [63:0] o_t;
    reg  [5:0]  o_h;
    reg         o_has;         // 面を取れた
    reg         o_p;           // 取った面
    reg  [31:0] o_cfg;
    reg  [3:0]  o_src;
    reg         cap;           // 面に書いている（頭のビートの次から）
    reg         cap_p;
    // 面: busy = 1 は使用中（取り中・閉じ待ち・送り待ち・送り中）。空けるのは「送り終えた」「レコードを出さずに閉じた」の 2 か所、
    // 取るのは「ダンプを始めた」の 1 か所（同じクロックに空いた面も取れる。取る方を後に書くので取る方が勝つ）
    reg  [1:0]  busy;
    // 閉じたダンプの頭（出す予定）。2 つまで（面が 2 つで、開いているダンプが 1 面を持つので、実際は 1 つまでしか溜まらない）
    reg  [1:0]  q_v;
    reg  [383:0] q_h [0:1];   // w1..w6
    reg         q_p [0:1];
    reg         q_head;       // 次に出す方
    reg         q_tail;       // 次に入れる方
    // 流れのブロックに出す値
    reg  [31:0] seq, d_k, d_n, d_cfg, rec_late;
    reg  [FW-1:0] d_f0;
    reg  [63:0] d_t;
    reg  [15:0] d_h;
    wire [31:0] nn = (run_n == 32'd0) ? 32'd1 : run_n;
    wire        o_close = open_ && fhead && (fin == o_end);
    wire        n_start = on && fhead && (fin == f_next);
    wire        want_rec = r_rec[0] || r_rec[1];
    wire        rec_ok   = want_rec && o_has && !q_v[q_tail];        // 閉じるダンプをレコードにする
    // 送り側から
    wire        q_take;                             // 送り側が q_head の頭を取った
    wire        rd_done;                            // 送り終えた
    wire        rd_done_p;
    // このクロックに空く面も、始めるダンプに使える（同じクロックの「空ける」と「取る」は、下の always で取る方を後に書く）
    wire        rel_o    = o_close && o_has && !rec_ok;
    wire [1:0]  avail    = ~busy | {rel_o && o_p, rel_o && !o_p} | {rd_done && rd_done_p, rd_done && !rd_done_p};
    wire        has_free = |avail;
    wire        free_p   = !avail[0];               // 空いている面（0 が空いていれば 0）

    // ---- 面の記憶（書き口 1 つ: 頭のビートは n_start のとき空いた面へ、残りは cap の面へ）----
    reg  [255:0] mem [0:1023];
    wire        mem_we = (n_start && has_free) || (cap && v_d && m_in != 9'd0);
    wire [9:0]  mem_wa = (m_in == 9'd0) ? {free_p, 9'd0} : {cap_p, m_in};
    always @(posedge aclk) if (mem_we) mem[mem_wa] <= x_d;

    always @(posedge aclk) begin
        rec_drop <= 1'b0;
        one_clr  <= 1'b0;
        if (rst) begin
            started <= 1'b0; f_gap <= 1'b0; m_in <= 9'd0; fin <= {FW{1'b0}};
            on <= 1'b0; open_ <= 1'b0; cap <= 1'b0; busy <= 2'b00; q_v <= 2'b00; q_tail <= 1'b0; q_head <= 1'b0;
            o_has <= 1'b0; o_p <= 1'b0; cap_p <= 1'b0;
            seq <= 32'd0; d_k <= 32'd0; d_n <= 32'd0; d_cfg <= 32'd0; d_f0 <= {FW{1'b0}}; d_t <= 64'd0; d_h <= 16'd0;
            rec_late <= 32'd0; run_n <= 32'd1; run_nd <= 32'd0; run_f0 <= {FW{1'b0}}; f_next <= {FW{1'b0}}; run_t <= 64'd0;
            run_cfg <= 32'd0; run_shift <= 4'd0; k_next <= 32'd0; o_h <= 6'd0;
        end else begin
            // 入力の数え
            if (v_d) begin
                started <= 1'b1;
                m_in <= m_in + 9'd1;
                if (m_in == 9'd511) begin fin <= fin + 1'b1; cap <= 1'b0; end
            end else if (started) f_gap <= 1'b1;
            if (cmd_clr) f_gap <= 1'b0;
            if (open_) o_h <= o_h | ev;
            // 送り側が取った頭
            if (q_take) begin q_v[q_head] <= 1'b0; q_head <= ~q_head; end
            // 送り終えた面を空ける
            if (rd_done) busy[rd_done_p] <= 1'b0;
            // ダンプを閉じる（頭のクロック。同じクロックに次のダンプが始まることもある）
            if (o_close) begin
                open_ <= 1'b0;
                seq <= seq + 32'd1;
                d_k <= o_k; d_f0 <= o_f0; d_n <= nn; d_t <= o_t; d_h <= {10'd0, o_h}; d_cfg <= o_cfg;
                if (rec_ok) begin
                    q_v[q_tail] <= 1'b1;
                    q_p[q_tail] <= o_p;
                    q_h[q_tail] <= {{27'd0, f_gap, 4'd0}, o_cfg,                        // w6 FLAGS | DUMP_CFG
                                    32'd0, nn,                                          // w5 DUMP_SAT | DUMP_N
                                    {10'd0, o_h}, {4'd0, o_src}, 32'd0, 8'd13,          // w4 DUMP_H | SRC | 0 | log2
                                    o_t,                                                // w3 DUMP_T
                                    {{(64-FW){1'b0}}, o_f0},                            // w2 DUMP_F0
                                    o_k, seq + 32'd1};                                  // w1 DUMP_K | SEQ
                    q_tail <= ~q_tail;
                    if (r_rec[1]) one_clr <= 1'b1;
                end else begin
                    if (o_has) busy[o_p] <= 1'b0;
                    if (want_rec) begin
                        rec_drop <= 1'b1;
                        if (rec_late != 32'hFFFF_FFFF) rec_late <= rec_late + 32'd1;
                    end
                end
            end
            // ダンプを始める（頭のビートは上の書き口が書く）
            if (n_start) begin
                open_ <= 1'b1;
                o_k <= k_next; o_f0 <= fin; o_end <= fin + nn; o_t <= t_loc; o_h <= ev; o_cfg <= run_cfg; o_src <= c_src;
                k_next <= k_next + 32'd1;
                f_next <= f_next + nn;
                if (run_nd != 32'd0 && k_next + 32'd1 == run_nd) on <= 1'b0;
                o_has <= has_free;
                if (has_free) begin
                    o_p <= free_p; cap <= 1'b1; cap_p <= free_p;
                    busy[free_p] <= 1'b1;
                end
            end
            // コマンドは最後に
            if (cmd_run) begin
                on <= 1'b1; f_next <= fin + 2; run_f0 <= fin + 2; k_next <= 32'd0;
                run_n <= r_nacc; run_nd <= r_ndump; run_t <= t_loc; run_cfg <= r_cfg; run_shift <= r_shift;
            end
`ifdef SPEC_POSCTL_SHIFT
            run_shift <= r_shift;                   // sim-tsys-p の陽性対照（spec_core と同じ口）: SHIFT を RUN で取り込まない
`endif
            if (cmd_stop) on <= 1'b0;
        end
    end

    // ---- 送り（ヘッダ 8 語 ＋ 中身 2,048 語）----
    //   3 段: 語の番号（v0・w0）→ 記憶の読み（v1・w1・d1）→ 出口（ov・od・ol）。3 段とも adv（出口が空くか受けられる）でだけ進むので、
    //   tready が落ちても語は落ちず・重ならない。最後の語（2055）を出し終えた（rd_done）ところで面を空け、次の頭を取る
    reg         s_busy;
    reg         s_p;
    reg  [383:0] s_h;
    reg  [11:0] w_iss;          // 次に出す語の番号（0..2055。2056 = 出し終えた）
    reg         v0, v1, ov;
    reg  [11:0] w0, w1;
    reg  [255:0] d1;
    reg  [63:0] od;
    reg         ol;
    wire        adv = !ov || m_axis_rec_tready;
    assign q_take    = !s_busy && q_v[q_head];
    assign rd_done   = ov && ol && m_axis_rec_tready;
    assign rd_done_p = s_p;
    wire [63:0] hw = (w1 == 12'd0) ? {SS8, RC8, 8'd4, 8'd1, 32'h5235_3453} :
                     (w1 == 12'd7) ? 64'd16384 : s_h[64*(w1 - 12'd1) +: 64];
    wire [11:0] wb0 = w0 - 12'd8;
    wire        iss = s_busy && (w_iss <= 12'd2055);
    always @(posedge aclk) begin
        if (adv) d1 <= mem[{s_p, wb0[10:2]}];
        if (rst) begin
            s_busy <= 1'b0; s_p <= 1'b0; v0 <= 1'b0; v1 <= 1'b0; ov <= 1'b0; w_iss <= 12'd0; ol <= 1'b0;
            w0 <= 12'd0; w1 <= 12'd0; od <= 64'd0;
        end else begin
            if (adv) begin
                ov <= v1;
                od <= (w1 < 12'd8) ? hw : d1[64 * w1[1:0] +: 64];
                ol <= v1 && (w1 == 12'd2055);
                v1 <= v0; w1 <= w0;
                v0 <= iss;
                w0 <= w_iss;
                if (iss) w_iss <= w_iss + 12'd1;
            end
            if (rd_done) s_busy <= 1'b0;
            if (q_take) begin
                s_busy <= 1'b1; s_p <= q_p[q_head]; s_h <= q_h[q_head]; w_iss <= 12'd0;
            end
        end
    end
    assign m_axis_rec_tdata  = od;
    assign m_axis_rec_tvalid = ov;
    assign m_axis_rec_tlast  = ol;

    // ---- 読み出し ----
    reg  [9:0]  ar_a;
    reg         ar_busy;
    reg  [1:0]  ar_w;
    reg  [FW-1:0] fin_lat;
    assign s_axi_arready = !ar_busy && !s_axi_rvalid;
    reg [31:0] rr;
    always @* begin
        case (ar_a[9:2])
            8'h00: rr = {8'd2, 8'd4, SS8, 8'd0};
            8'h01: rr = {24'd0, 8'd13};
            8'h02: rr = {25'd0, arm_wrst, arm_run, 1'b0, started, 1'b0, on, open_};
            8'h03: rr = r_nacc;
            8'h04: rr = r_ndump;
            8'h05: rr = {28'd0, r_shift};
            8'h06: rr = {27'd0, f_gap, 4'd0};
            8'h07: rr = seq;
            8'h08: rr = 32'd0;
            8'h09: rr = 32'd512;
            8'h0A: rr = {1'b1, 27'd0, c_src};
            8'h0B: rr = r_cfg;
            8'h0C: rr = run_cfg;
            8'h0D: rr = c_cfg;
            8'h0E: rr = {28'd0, run_shift};
            8'h0F: rr = d_k;
            8'h10: rr = d_f0[31:0];
            8'h11: rr = {{(64-FW){1'b0}}, d_f0[FW-1:32]};
            8'h12: rr = d_n;
            8'h13: rr = 32'd0;
            8'h14: rr = d_t[31:0];
            8'h15: rr = d_t[63:32];
            8'h16: rr = {16'd0, d_h};
            8'h17: rr = d_cfg;
            8'h18: rr = run_t[31:0];
            8'h19: rr = run_t[63:32];
            8'h1A: rr = run_f0[31:0];
            8'h1B: rr = {{(64-FW){1'b0}}, run_f0[FW-1:32]};
            8'h1C, 8'h1E: rr = fin_lat[31:0];
            8'h1D, 8'h1F: rr = {{(64-FW){1'b0}}, fin_lat[FW-1:32]};
            8'h21: rr = {29'd0, r_rec};
            8'h22: rr = rec_late;
            default: rr = 32'd0;
        endcase
    end
    always @(posedge aclk) begin
        if (rst) begin
            ar_busy <= 1'b0; ar_w <= 2'd0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0; ar_a <= 10'd0; fin_lat <= {FW{1'b0}};
        end else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin
                ar_busy <= 1'b1; ar_w <= 2'd0; ar_a <= s_axi_araddr[9:0];
                if (s_axi_araddr[15:2] == 14'h1C || s_axi_araddr[15:2] == 14'h1E) fin_lat <= fin;   // FIN_LO / FOUT_LO
            end else if (ar_busy) begin
                ar_w <= ar_w + 2'd1;
                if (ar_w == 2'd2) begin
                    ar_busy <= 1'b0; s_axi_rvalid <= 1'b1;
                    s_axi_rdata <= (ar_a[9:8] == 2'd0) ? rr : 32'd0;
                end
            end
        end
    end
endmodule
