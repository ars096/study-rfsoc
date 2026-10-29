// SPDX-License-Identifier: BSD-3-Clause
//
// spw_regs — SpW のコアのレジスタ（proj032 R-1b）。INTERFACE v2 の 2.4（コアの共通）・2.5（流れのブロック、KIND 3 = DDC）の形に SpW の窓を載せる
//
// **RUN・WRST はコアで 1 つ**（R-1 の決め、2026-10-28）: どの流れの CTRL に打っても、コアの全部の窓に効く。
//   WRST: 書いておいた窓の設定（WK・WDPHI・WNS・WFL・WSL・WG）を全部の窓で取り込み、データの道（wsb・dsink・頭）を WRST_T クロックだけリセットする（wrst）。
//         取り込む前に約束を数える（下の「約束」）。破れていれば **WRST を断り**、効いている設定もデータの道もそのまま（CORE_FLAGS[0]・0x8C WRST_BAD）
//   RUN:  SHIFT（窓ごと）・NG・NDUMP・CFG_ID を取り込み、cmd_run を 1 クロック。WRST のリセット中に来た RUN はその明けまで待つ。
//         RUN の中の RUN は断り、STOP の直後の RUN は静まるまで待つ（下の「RUN の約束」）。NDUMP で止まった後も RUN の中のまま（STOP してから打つ）
//   ARM_RUN・ARM_WRST: time_core の発火（fire = go_out）で RUN・WRST。同じ発火で両方なら WRST → 明けて RUN（SAM45-Fine の win_core と同じ）。
//   予約は発火・STOP・取り消し（CTRL[3]）でしか消えない
// 約束（WRST の前に H クロックで数える。fl ≧ E の窓は止める窓: 数えない）:
//   [1] lane（機関）ごとに幅の和 ≦ 256 MHz（8 MHz を 1 として NS 1..5 = 16・8・4・2・1、和 ≦ 32）
//   [2] DDR の窓（WSL ≧ S）の幅の和 ≦ 256 MHz（D-1）
//   [3] チップ内の履歴の枠（WSL < S）が重ならない・[4] DDR の枠（WSL − S）が NK 未満で重ならない
//   [5] WNS が 1..5 の外
//   [6] 粗い ch WK が 32 を越える、または PSPLIT のとき頭の組と偶奇が合わない（頭 0..H/2−1 は偶、残りは奇。pfb64_core は k の最下位 bit を
//       頭の組で決めるので、取り違えると黙って隣の ch を出す）
//   断った WRST を待っていた RUN も捨てる（run_wait を消す）
// 水抜き（P-2）: 約束が通ったら drain を立て、データの道が開いたレコードを送り終える（dp_idle）のを待ってから設定を取り込みリセットする。
//   送っている途中のレコードを WRST で切ると、リング（ring128）が次のレコードの頭を本体として受け、CRC の合ったまま中身が壊れる。
//   新しい設定が送っている途中のレコードの頭に入るのも防ぐ。DRN_MAX クロック待っても空かなければ構わずリセットし CORE_FLAGS[5] を立てる
// 格子（P-4）: WRST の明け（データの道のリセットを解くクロック）を T ≡ 0 mod 2^AL_L2 に揃える。窓のフレームの頭は T ≡ K_F mod L（K_F は鎖の遅れ）になり、
//   DUMP_F0 は T の原点から数えたフレーム番号、DUMP_T = K_F ＋ L·DUMP_F0（proj023 の形）。待ちは最長 2^AL_L2 クロック（G_L2 19 で 2 ms）
// RUN の約束（P-4）: RUN の中に来た RUN は断る（CORE_FLAGS[6]、STOP してから打つ）。STOP の後 QUIET クロックかつ受け手が空く（dp_idle）までは RUN を待たせる。
//   理由: レコードの頭の NG・g0 は今の値を読むので、送りかけのダンプの頭に新しい RUN の値が入り、DUMP_F0・DUMP_T・DUMP_N が黙って狂う
// N_ACC・N_DUMP: SpW はコアで 1 つ（区切りの格子は全窓で同じ）。**0x84 NG（格子 G の数）・0x88 NDUMP に書く**（変更案）。
//   流れのブロックの N_ACC は読むだけ = NG·2^(G_L2 − 12 − NS)（その窓のフレーム）、N_DUMP は NDUMP
// 帳簿（SEQ・DUMP_*）はレコード（dsink）に入るので、流れのブロックの 0x1C・0x3C〜0x5C は 0 を返す（変更案）
//
// ---- 番地（コアの 64 KiB、AXI4-Lite 32 bit）----
//   0x0000 IF_ID {2, BIT_KIND, BIT_REV, 1} / 0x04 PROJ / 0x08 NSTREAM = H / 0x0C CAPS [0] レコード / 0x10 BASE_BEATS / 0x14 BUILD / 0x18 CORE_PORT
//   0x0080 CORE_FLAGS R（粘着、どの流れの CTRL[8] でも消える）: [0] WRST を断った [1] 機関の FLAGS の OR [2] DDR の道の FLAGS の OR [3] 受け手の FLAGS の OR [4] 前段（頭・ddcb）の FLAGS の OR [5] WRST の水抜きが時間切れ [6] RUN の中の RUN を断った
//   0x0084 NG RW（RUN で取り込む、0 は 1）/ 0x88 NDUMP RW（0 = 止めるまで）/ 0x8C WRST_BAD R（最後に断った WRST の約束の印 [6:1]）/ 0x90 WRST_CNT R
//   0x4000 + 0x400·s（s < H）流れ s のブロック:
//     0x00 SID {2, 3, s, 0} / 0x04 PARAM {1（f32）, 64, 0, 12} / 0x08 CTRL / 0x0C N_ACC R / 0x10 N_DUMP R / 0x14 SHIFT RW / 0x18 FLAGS R（その窓の機関の FLAGS）/
//     0x1C SEQ 0 / 0x20 NCH 4096 / 0x24 FRAME_BEATS = 2^(12 + NS) / 0x28 SRC = CORE_PORT[3:0] / 0x2C CFG_ID RW（コアで 1 つ）/ 0x30 RUN_CFG / 0x34 WRST_CFG /
//     0x38 RUN_SHIFT / 0x60·64 RUN_T / 0x68·6C RUN_F0 = g0·2^(G_L2 − 12 − NS) / 0x80 NFFT_MIN_MAX {12, 12}
//     0x100 WK [5:0] / 0x104 WDPHI / 0x108 WNS [2:0] / 0x10C WCUR {WNS, WK} / 0x110 WCUR_DPHI / 0x114·118 WSTART = t0[w]（フレーム 0 の z 0 の T）/
//     0x11C WRST_T（コアで 1 つ、[15:0]、0 は 1、既定 64）/ 0x120 WFL [1:0] / 0x124 WSL [3:0] / 0x128 WG [3:0] / 0x12C WCUR2 {WG, WSL, WFL}
//   CTRL の書き: [0] RUN [1] STOP [2] ARM_RUN [3] 予約の取り消し [8] FLAGS を消す [12] WRST [13] ARM_WRST（全部コアに効く）
//   CTRL の読み: [0] RUN の中 [4] WRST の中 [5] ARM_RUN 中 [6] ARM_WRST 中 [7] WRST の明けを待つ RUN
// 空きは 0

`timescale 1ns / 1ps

module spw_regs #(
    parameter integer H          = 14,
    parameter integer E          = 3,
    parameter integer S          = 6,
    parameter integer NK         = 8,
    parameter integer G_L2       = 19,
    parameter integer BIT_KIND   = 7,
    parameter integer BIT_REV    = 1,
    parameter integer PROJ       = 3277312,     // 0x0032_0200（10 進で書く）
    parameter integer BUILD_TAG  = 0,
    parameter integer CORE_PORT  = 0,
    parameter integer BASE_BEATS = 2621440,
    parameter integer PSPLIT     = 1,
    parameter integer DRN_MAX    = 4194304,     // 水抜きの待ちの上限（16 ms）
    parameter integer AL_L2      = G_L2,        // WRST の明けを揃える T の格子（sim で縮めるため別の名前）
    parameter integer QUIET      = 12288        // STOP の後、送りかけのダンプが受け手に入りきるまでの待ち（枠 3 つ）
)(
    input  wire                 clk,
    input  wire                 rst,
    // AXI4-Lite（64 KiB）
    input  wire [15:0]          s_axi_awaddr,
    input  wire                 s_axi_awvalid,
    output wire                 s_axi_awready,
    input  wire [31:0]          s_axi_wdata,
    input  wire                 s_axi_wvalid,
    output wire                 s_axi_wready,
    output reg                  s_axi_bvalid,
    output wire [1:0]           s_axi_bresp,
    input  wire                 s_axi_bready,
    input  wire [15:0]          s_axi_araddr,
    input  wire                 s_axi_arvalid,
    output wire                 s_axi_arready,
    output reg  [31:0]          s_axi_rdata,
    output reg                  s_axi_rvalid,
    output wire [1:0]           s_axi_rresp,
    input  wire                 s_axi_rready,
    // 時刻
    input  wire [63:0]          t_now,
    input  wire                 fire,
    // データの道へ（効いている値）
    output reg                  wrst,
    output reg                  drain,          // 新しいレコードを始めない（水抜き）
    input  wire                 dp_idle,        // 開いたレコードが無い
    output wire [H*6-1:0]       cfg_wk,
    output wire [H*32-1:0]      cfg_dphi,
    output wire [H*3-1:0]       cfg_ns,
    output wire [H*2-1:0]       cfg_fl,
    output wire [H*4-1:0]       cfg_sl,
    output wire [H*4-1:0]       cfg_g,
    output wire [H*4-1:0]       cfg_sh,
    output reg  [31:0]          ng,
    output reg  [31:0]          ndump,
    output reg                  cmd_run,
    output reg                  cmd_stop,
    // データの道から
    input  wire [31:0]          g0,
    input  wire [H*64-1:0]      t0,
    input  wire [E*16-1:0]      eng_flags,
    input  wire                 ddr_flag,
    input  wire                 sink_flag,
    input  wire                 front_flag
);
    localparam [7:0] BK8 = BIT_KIND, BR8 = BIT_REV;
    integer i;

    // ---- 書いた値（窓ごと）と効いている値 ----
    reg  [5:0]   w_wk  [0:H-1], c_wk  [0:H-1];
    reg  [31:0]  w_dp  [0:H-1], c_dp  [0:H-1];
    reg  [2:0]   w_ns  [0:H-1], c_ns  [0:H-1];
    reg  [1:0]   w_fl  [0:H-1], c_fl  [0:H-1];
    reg  [3:0]   w_sl  [0:H-1], c_sl  [0:H-1];
    reg  [3:0]   w_g   [0:H-1], c_g   [0:H-1];
    reg  [3:0]   w_sh  [0:H-1], c_sh  [0:H-1];
    genvar g;
    generate for (g = 0; g < H; g = g + 1) begin : co
        assign cfg_wk[g*6 +: 6]    = c_wk[g];
        assign cfg_dphi[g*32 +: 32] = c_dp[g];
        assign cfg_ns[g*3 +: 3]    = c_ns[g];
        assign cfg_fl[g*2 +: 2]    = c_fl[g];
        assign cfg_sl[g*4 +: 4]    = c_sl[g];
        assign cfg_g[g*4 +: 4]     = c_g[g];
        assign cfg_sh[g*4 +: 4]    = c_sh[g];
    end endgenerate
    reg  [31:0]  w_ng, w_ndump, w_cfg, run_cfg, wrst_cfg;
    reg  [15:0]  wrst_t;
    reg  [63:0]  run_t;
    reg  [31:0]  wrst_cnt;
    reg  [6:1]   wrst_bad;
    reg  [6:0]   cflags;

    // ---- AXI4-Lite の書き ----
    wire        wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !rst;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    wire [15:0] wa  = s_axi_awaddr;
    wire [5:0]  ws  = wa[15:10] - 6'd16;            // 流れ s
    wire        wst = wa >= 16'h4000 && ws < H;
    wire [9:0]  wo  = wa[9:0];
    wire [31:0] wd  = s_axi_wdata;
    // CTRL（どの流れでも）
    wire        c_wr   = wr_go && wst && wo == 10'h008;
    wire        q_run  = c_wr && wd[0], q_stop = c_wr && wd[1], q_arun = c_wr && wd[2], q_cancel = c_wr && wd[3];
    wire        q_clr  = c_wr && wd[8], q_wrst = c_wr && wd[12], q_awrst = c_wr && wd[13];

    // ---- 制御: 予約・WRST（約束を数える → リセット）・RUN ----
    reg          arm_run, arm_wrst, run_wait, running;
    localparam [1:0] W_IDLE = 2'd0, W_CHK = 2'd1, W_RST = 2'd2, W_DRN = 2'd3;
    reg  [1:0]   wsm;
    reg  [4:0]   ci;                                 // 数えている窓
    reg  [5:0]   lsum [0:E-1];                       // lane ごとの幅（8 MHz 単位）
    reg  [5:0]   dsum;
    reg  [15:0]  sl_used;                            // 枠の使い（チップ内 0..S−1・DDR S..S+NK−1）
    reg  [6:1]   bad;
    reg  [15:0]  rcnt;
    reg  [22:0]  dcnt;
    reg  [15:0]  qcnt;                               // STOP からの時間（QUIET で止まる）
    wire         quiet = (qcnt >= QUIET) && dp_idle;
    wire [2:0]   cns = w_ns[ci];
    wire [5:0]   unit = (cns >= 3'd1 && cns <= 3'd5) ? (6'd32 >> cns) : 6'd0;
    wire         con = w_fl[ci] < E;                 // 止める窓は数えない
    wire         do_wrst = q_wrst || (fire && arm_wrst);
    wire         do_run  = q_run  || (fire && arm_run);
    always @(posedge clk) begin
        cmd_run <= 1'b0; cmd_stop <= 1'b0;
        if (rst) begin
            wsm <= W_IDLE; wrst <= 1'b0; drain <= 1'b0; arm_run <= 1'b0; arm_wrst <= 1'b0; run_wait <= 1'b0; running <= 1'b0;
            wrst_cnt <= 32'd0; wrst_bad <= 6'd0; cflags <= 7'd0; qcnt <= QUIET; run_cfg <= 32'd0; wrst_cfg <= 32'd0; run_t <= 64'd0;
            ng <= 32'd5; ndump <= 32'd0;
            for (i = 0; i < H; i = i + 1) begin
                c_wk[i] <= 6'd0; c_dp[i] <= 32'd0; c_ns[i] <= 3'd1; c_fl[i] <= 2'd3; c_sl[i] <= 4'd0; c_g[i] <= 4'd0; c_sh[i] <= 4'd4;
            end
        end else begin
            // 予約
            if (q_arun) arm_run <= 1'b1;
            if (q_awrst) arm_wrst <= 1'b1;
            if (q_cancel || q_stop) begin arm_run <= 1'b0; arm_wrst <= 1'b0; end
            if (fire) begin arm_run <= 1'b0; arm_wrst <= 1'b0; end
            // WRST: 約束を数えてからリセット
            case (wsm)
                W_IDLE: if (do_wrst) begin
                    wsm <= W_CHK; ci <= 5'd0; dsum <= 6'd0; sl_used <= 16'd0; bad <= 6'd0;
                    for (i = 0; i < E; i = i + 1) lsum[i] <= 6'd0;
                end
                W_CHK: begin
                    if (con) begin
                        if (unit == 6'd0) bad[5] <= 1'b1;
                        if (w_wk[ci] > 6'd32 || (PSPLIT != 0 && w_wk[ci][0] != (ci >= H / 2))) bad[6] <= 1'b1;
                        lsum[w_fl[ci]] <= lsum[w_fl[ci]] + unit;
`ifndef REGS_POSCTL
                        if (lsum[w_fl[ci]] + unit > 6'd32) bad[1] <= 1'b1;     // 陽性対照 REGS_POSCTL: lane の和を数えない
`endif
                        if (w_sl[ci] >= S) begin
                            dsum <= dsum + unit;
                            if (dsum + unit > 6'd32) bad[2] <= 1'b1;
                            if (w_sl[ci] >= S + NK || sl_used[w_sl[ci]]) bad[4] <= 1'b1;
                        end else if (sl_used[w_sl[ci]]) bad[3] <= 1'b1;
                        sl_used[w_sl[ci]] <= 1'b1;
                    end
                    ci <= ci + 5'd1;
                    if (ci == H - 1) wsm <= W_RST;   // 次のクロックで bad が揃う
                    rcnt <= 16'd0;
                end
                W_RST: begin
                    if (rcnt == 16'd0) begin
                        if (bad != 6'd0) begin                       // 断る: 何も変えない
                            wrst_bad <= bad; cflags[0] <= 1'b1; wsm <= W_IDLE; run_wait <= 1'b0;
                        end else begin
                            drain <= 1'b1; dcnt <= 23'd0; wsm <= W_DRN;
                        end
                    end else if (rcnt >= ((wrst_t == 16'd0) ? 16'd1 : wrst_t)) begin
                        if (&t_now[AL_L2-1:0]) begin wrst <= 1'b0; wsm <= W_IDLE; end   // 次のクロック（T ≡ 0）でデータの道が明ける
                    end else rcnt <= rcnt + 16'd1;
                end
                W_DRN: begin                                     // 水抜き: 開いたレコードを送り終えるまで待つ（drain は次のクロックから効くので 1 クロック置く）
                    dcnt <= dcnt + 23'd1;
                    if ((dp_idle && dcnt >= 23'd2) || dcnt >= DRN_MAX) begin
                        if (!dp_idle) cflags[5] <= 1'b1;
                        for (i = 0; i < H; i = i + 1) begin
                            c_wk[i] <= w_wk[i]; c_dp[i] <= w_dp[i]; c_ns[i] <= w_ns[i]; c_fl[i] <= w_fl[i]; c_sl[i] <= w_sl[i]; c_g[i] <= w_g[i];
                        end
                        wrst_cfg <= w_cfg; wrst_cnt <= wrst_cnt + 32'd1; running <= 1'b0;
                        wrst <= 1'b1; drain <= 1'b0; rcnt <= 16'd1; wsm <= W_RST;
                    end
                end
            endcase
            // RUN（WRST の最中・同じ発火なら明けを待つ）
            if (wrst) qcnt <= QUIET;
            else if (qcnt < QUIET) qcnt <= qcnt + 16'd1;
            if (do_run && running && wsm == W_IDLE && !do_wrst) cflags[6] <= 1'b1;               // RUN の中の RUN は断る
            else if (do_run && (wsm != W_IDLE || do_wrst || !quiet)) run_wait <= 1'b1;
            if ((do_run && !running && wsm == W_IDLE && !do_wrst && quiet) || (run_wait && wsm == W_IDLE && !do_wrst && quiet)) begin
                run_wait <= 1'b0;
                for (i = 0; i < H; i = i + 1) c_sh[i] <= w_sh[i];
                ng <= (w_ng == 32'd0) ? 32'd1 : w_ng; ndump <= w_ndump; run_cfg <= w_cfg; run_t <= t_now;
                cmd_run <= 1'b1; running <= 1'b1;
            end
            if (q_stop) begin cmd_stop <= 1'b1; running <= 1'b0; run_wait <= 1'b0; if (running) qcnt <= 16'd0; end
            // 見張り
            if (q_clr) cflags <= 7'd0;
            else cflags[4:1] <= cflags[4:1] | {front_flag, sink_flag, ddr_flag, |eng_flags};
        end
    end

    // ---- 書いた値の受け ----
    always @(posedge clk) begin
        if (rst) begin
            s_axi_bvalid <= 1'b0; w_ng <= 32'd5; w_ndump <= 32'd0; w_cfg <= 32'd0; wrst_t <= 16'd64;
            for (i = 0; i < H; i = i + 1) begin
                w_wk[i] <= 6'd0; w_dp[i] <= 32'd0; w_ns[i] <= 3'd1; w_fl[i] <= 2'd3; w_sl[i] <= 4'd0; w_g[i] <= 4'd0; w_sh[i] <= 4'd4;
            end
        end else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) begin
                s_axi_bvalid <= 1'b1;
                if (wa == 16'h0084) w_ng <= wd;
                if (wa == 16'h0088) w_ndump <= wd;
                if (wst) case (wo)
                    10'h014: w_sh[ws] <= wd[3:0];
                    10'h02C: w_cfg <= wd;
                    10'h100: w_wk[ws] <= wd[5:0];
                    10'h104: w_dp[ws] <= wd;
                    10'h108: w_ns[ws] <= wd[2:0];
                    10'h11C: wrst_t <= wd[15:0];
                    10'h120: w_fl[ws] <= wd[1:0];
                    10'h124: w_sl[ws] <= wd[3:0];
                    10'h128: w_g[ws] <= wd[3:0];
                    default: ;
                endcase
            end
        end
    end

    // ---- 読み（番地を 1 段受け、値を 1 段で）----
    reg  [15:0] ra;
    reg         ar_busy;
    assign s_axi_arready = !ar_busy && !s_axi_rvalid && !rst;
    assign s_axi_rresp   = 2'b00;
    wire [5:0]  rs  = ra[15:10] - 6'd16;
    wire        rst_ = ra >= 16'h4000 && rs < H;
    wire [9:0]  ro  = ra[9:0];
    wire [4:0]  ri  = rs[4:0];
    wire [2:0]  ens = c_ns[ri];
    wire [5:0]  fe  = G_L2 - 12 - ens;
    wire [63:0] rf0 = {32'd0, g0} << fe;
    wire [63:0] t0s = t0[ri*64 +: 64];
    always @(posedge clk) begin
        if (rst) begin ar_busy <= 1'b0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0; ra <= 16'd0; end
        else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin ar_busy <= 1'b1; ra <= s_axi_araddr; end
            else if (ar_busy) begin
                ar_busy <= 1'b0; s_axi_rvalid <= 1'b1; s_axi_rdata <= 32'd0;
                if (!rst_) case (ra)
                    16'h0000: s_axi_rdata <= {8'd2, BK8, BR8, 8'd1};
                    16'h0004: s_axi_rdata <= PROJ;
                    16'h0008: s_axi_rdata <= H;
                    16'h000C: s_axi_rdata <= 32'd1;
                    16'h0010: s_axi_rdata <= BASE_BEATS;
                    16'h0014: s_axi_rdata <= BUILD_TAG;
                    16'h0018: s_axi_rdata <= CORE_PORT;
                    16'h0080: s_axi_rdata <= {25'd0, cflags};
                    16'h0084: s_axi_rdata <= w_ng;
                    16'h0088: s_axi_rdata <= w_ndump;
                    16'h008C: s_axi_rdata <= {25'd0, wrst_bad, 1'b0};
                    16'h0090: s_axi_rdata <= wrst_cnt;
                    default: ;
                endcase
                else case (ro)
                    10'h000: s_axi_rdata <= {8'd2, 8'd3, 2'd0, rs, 8'd0};
                    10'h004: s_axi_rdata <= {8'd1, 8'd64, 8'd0, 8'd12};
                    10'h008: s_axi_rdata <= {24'd0, run_wait, arm_wrst, arm_run, wsm != W_IDLE, 3'd0, running};
                    10'h00C: s_axi_rdata <= ng << fe;
                    10'h010: s_axi_rdata <= ndump;
                    10'h014: s_axi_rdata <= {28'd0, w_sh[ri]};
                    10'h018: s_axi_rdata <= (c_fl[ri] < E) ? {16'd0, eng_flags[c_fl[ri]*16 +: 16]} : 32'd0;
                    10'h020: s_axi_rdata <= 32'd4096;
                    10'h024: s_axi_rdata <= 32'd1 << (12 + ens);
                    10'h028: s_axi_rdata <= CORE_PORT & 15;
                    10'h02C: s_axi_rdata <= w_cfg;
                    10'h030: s_axi_rdata <= run_cfg;
                    10'h034: s_axi_rdata <= wrst_cfg;
                    10'h038: s_axi_rdata <= {28'd0, c_sh[ri]};
                    10'h060: s_axi_rdata <= run_t[31:0];
                    10'h064: s_axi_rdata <= run_t[63:32];
                    10'h068: s_axi_rdata <= rf0[31:0];
                    10'h06C: s_axi_rdata <= rf0[63:32];
                    10'h080: s_axi_rdata <= {16'd0, 8'd12, 8'd12};
                    10'h100: s_axi_rdata <= {26'd0, w_wk[ri]};
                    10'h104: s_axi_rdata <= w_dp[ri];
                    10'h108: s_axi_rdata <= {29'd0, w_ns[ri]};
                    10'h10C: s_axi_rdata <= {21'd0, ens, 2'd0, c_wk[ri]};
                    10'h110: s_axi_rdata <= c_dp[ri];
                    10'h114: s_axi_rdata <= t0s[31:0];
                    10'h118: s_axi_rdata <= t0s[63:32];
                    10'h11C: s_axi_rdata <= {16'd0, wrst_t};
                    10'h120: s_axi_rdata <= {30'd0, w_fl[ri]};
                    10'h124: s_axi_rdata <= {28'd0, w_sl[ri]};
                    10'h128: s_axi_rdata <= {28'd0, w_g[ri]};
                    10'h12C: s_axi_rdata <= {20'd0, c_g[ri], c_sl[ri], 2'd0, c_fl[ri]};
                    default: ;
                endcase
            end
        end
    end
endmodule
