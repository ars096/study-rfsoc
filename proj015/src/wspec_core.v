// SPDX-License-Identifier: BSD-3-Clause
//
// wspec_core — 窓 1 つの分光: z（FFT の入力、複素 18 bit・Q4）→ フレームの溜め → 複素 4096 点 FFT → 電力 → 積分（4096 ch）
//
// **溜めを置く理由**: realtime の FFT IP は入力の途切れを待たずに進む（proj011）。窓の出力は W MSPS（W = 8 なら 32 クロックに 1 個）で
// 必ず途切れるので、4096 語を 2 面の溜めに書き、溜まった面を 4096 クロック途切れなく IP へ流す。次のフレームが溜まるには
// 4096 クロック以上かかる（入力は 1 / クロック以下）ので、読み出しは必ず間に合う（間に合わなければ FLAGS[1]）。
//
// **rev2: IP の s_axis_data_tready を守る**。rev1 は tready を見ずに流し、実機 1 回目で WRST の直後に tready = 0 の間の
// サンプルを IP が受けず、IP の中のフレームの枠が溜めの枠からずれたまま回った（FLAGS[2] が立ち続け、--golden が NG）。
// rev2 は出口のレジスタ（fd・f_v・f_last）を「空いている か IP が受けた」ときだけ進める（AXI の握手）。待たされても
// 1 語も落とさないので、IP の枠 = 溜めの枠がいつも保たれる。待たされたぶん読み出しが遅れても、次の面の開始は pend で
// 予約して遅れて始める（書き込みが未読の番地に追いついたときだけ FLAGS[1]）。
//
// ---- フレームと ch ----
// フレーム f = z の 4096f … 4096f + 4095 番目（rst の後の最初の z を 0 番とする）。fin = 溜め終えたフレームの数。
// FFT は順変換・unscaled（出力 31 bit = 18 + 12 + 1）・自然順。ch b（0..4095）は ν = b·W/4096（b < 2048）/ (b − 4096)·W/4096（b ≧ 2048）。
// **並べ替え（fftshift）とゾーン 2 の反転（IF = 4096 − c − ν）は PS 側**。
//
// ---- 電力と積分（spec_core と同じ約束）----
//   q = sat18(Y >>> SHIFT)、p = q_re² + q_im²（37 bit）、64 bit で N_ACC フレーム積む。二面（ダンプごとに交互）。
//   RUN: F0 = fin + 2（確実に未来）。フレーム F0 + k·N … F0 + k·N + N − 1 をダンプ k に積む。N_DUMP = 0 なら止めるまで。
//   ダンプが閉じるたびに SEQ が 1 増え、rd_* と読み出しの面がその面に切り替わる（seqlock。PS は SEQ → 中身 → SEQ）。
//   スナップショット: ダンプ k の最初のフレーム（F0 + k·N）の z を 4096 語、面 k mod 2 に残す（snap_f* がその番号）。
//   **N_ACC = 1 ならスナップショットの FFT とダンプが 1 対 1**（PS 側の --golden の型）
//
// FLAGS（粘着、cmd_clr で消す）: [0] XK_INDEX が 1 ずつ進まなかった / [1] 溜めの読み出しが間に合わなかった /
//   [2] IP の TLAST 事象 / [3] IP の data_in_channel_halt / [4] IP に待たされた（f_v = 1 で tready = 0。rev2 はデータを保って待つ）
// 見張り（rst から）: stall_cnt = 待たされたクロック数（飽和）/ rdy0 = rst の解除から tready が最初に 1 になるまでのクロック数
//
// 段（FFT の出力を受けたクロックを S0）: S1 丸めと飽和 → S2 二乗の入口・積分の読み出し番地 → S3 二乗 → S4 電力・読み値
// → S5 書き込み（初回は p、以降は 読み値 + p）。同じ ch は 4096 クロックおきにしか来ないので、読み書きの追い越しは起きない

`timescale 1ns / 1ps

module wspec_core #(
    parameter integer FW = 48,
    parameter integer ZW = 18,
    parameter integer SNAP = 1     // 1: スナップショットの記憶を中に持つ / 0: 持たず、書き込みを sn_w* に出す（ADC ごとに 1 つを共有する。proj015）
)(
    input  wire                 clk,
    input  wire                 rst,
    input  wire                 z_valid,
    input  wire signed [ZW-1:0] z_re, z_im,
    // 制御（1 クロックのパルス）と設定
    input  wire                 cmd_run, cmd_stop, cmd_clr,
    input  wire [31:0]          r_nacc, r_ndump,
    input  wire [3:0]           r_shift,
    // 状態
    output reg  [FW-1:0]        fin,
    output reg  [FW-1:0]        fout,
    output reg  [FW-1:0]        run_f0,
    output reg                  sched, acc_on,
    output reg  [31:0]          seq, rd_k, rd_n, rd_sat,
    output reg  [FW-1:0]        rd_f0,
    output reg                  rd_bank,
    output reg  [FW-1:0]        snap_f0, snap_f1,
    output reg  [7:0]           flags,
    output reg  [31:0]          stall_cnt,
    output reg  [31:0]          rdy0,
    // 読み出し（2 クロック）: スペクトル（面 rd_bk の ch rd_ch）/ スナップショット（面 sn_bk の語 sn_a、{im, re}）
    input  wire                 rd_bk,
    input  wire [11:0]          rd_ch,
    output wire [63:0]          rd_data,
    input  wire                 sn_bk,
    input  wire [11:0]          sn_a,
    output wire [2*ZW-1:0]      sn_data,
    // スナップショットの書き込み（SNAP = 0 のとき外の記憶が使う。SNAP = 1 でも出る）: 面・番地 {sn_wbank, sn_waddr}、{im, re}
    output wire                 sn_wen,
    output wire [12:0]          sn_waddr,
    output wire [2*ZW-1:0]      sn_wdata
);
    localparam integer NF = 4096;
    localparam integer YW = ZW + 13;       // 31
    localparam integer QW = 18;
    localparam integer PW = 2 * QW + 1;    // 37

    // =====================================================================
    // 溜め（2 面 × 4096 × {im, re}）と、IP への流し込み
    // =====================================================================
    reg [2*ZW-1:0] fbuf [0:2*NF-1];
    reg [11:0]     wa;
    reg            wb;
    reg            rd_go;                 // 読み出し中（ra = 次に出す番地）
    reg            rbk;
    reg [11:0]     ra;
    reg            pend, pbk;             // 溜まったがまだ読み始めていない面
    reg            ovr;                   // 書き込みが未読の番地に追いついた
    reg            f_v, f_last;           // 出口（IP の入力）
    wire           s_tready;
`ifdef WSPEC_NOREADY
    wire           adv = 1'b1;            // 陽性対照: rev1 と同じく tready を見ない
`else
    wire           adv = !f_v || s_tready;   // 出口が空いている / IP が今の語を受けた → 次の語を出してよい
`endif
    wire           issue  = rd_go && adv;
    wire           rd_end = issue && (ra == 12'd4095);
    wire           fdone  = z_valid && (wa == 12'd4095);
    wire           can_st = !rd_go || rd_end;
    // スナップショットの予約（ダンプ k の最初のフレーム）
    reg            sn_on;                 // RUN から N_DUMP 回ぶん
    reg  [FW-1:0]  sn_next;
    reg  [31:0]    sn_k;
    reg            sn_act, sn_buf;
    reg  [31:0]    run_n, run_ndump;
    wire [31:0]    n_eff = (run_n == 0) ? 32'd1 : run_n;
    wire           sn_hit = sn_on && (fin == sn_next);        // wa == 0 のときだけ意味を持つ
    wire           sn_we  = z_valid && ((wa == 12'd0) ? sn_hit : sn_act);
    wire           sn_wb  = (wa == 12'd0) ? sn_k[0] : sn_buf;

    always @(posedge clk) begin
        if (z_valid) fbuf[{wb, wa}] <= {z_im, z_re};
    end
    assign sn_wen   = sn_we;
    assign sn_waddr = {sn_wb, wa};
    assign sn_wdata = {z_im, z_re};

    always @(posedge clk) begin
        ovr <= 1'b0;
        if (rst) begin
            wa <= 12'd0; wb <= 1'b0; fin <= {FW{1'b0}};
            rd_go <= 1'b0; rbk <= 1'b0; ra <= 12'd0; pend <= 1'b0; pbk <= 1'b0;
            sn_on <= 1'b0; sn_next <= {FW{1'b0}}; sn_k <= 32'd0; sn_act <= 1'b0; sn_buf <= 1'b0;
            snap_f0 <= {FW{1'b1}}; snap_f1 <= {FW{1'b1}};
        end else begin
            if (issue) begin
                ra <= ra + 12'd1;
                if (ra == 12'd4095) rd_go <= 1'b0;
            end
            // 面の読み始め: 予約（pend）が先、無ければ今溜まった面。読み中なら予約する
            if (can_st && (pend || fdone)) begin
                rd_go <= 1'b1; ra <= 12'd0; rbk <= pend ? pbk : wb;
                pend  <= pend && fdone;
            end else if (fdone) begin
                pend <= 1'b1;
            end
            if (fdone) pbk <= wb;
            // 書き込みが未読のところを潰す: 読み中の面の未読の番地（≧ ra）/ 予約中の面
            if (z_valid && ((rd_go && wb == rbk && wa >= ra) || (pend && wb == pbk))) ovr <= 1'b1;
            if (z_valid) begin
                wa <= wa + 12'd1;
                if (wa == 12'd0) begin
                    sn_act <= sn_hit;
                    sn_buf <= sn_k[0];
                    if (sn_hit) begin
                        if (sn_k[0]) snap_f1 <= fin; else snap_f0 <= fin;
                        sn_k    <= sn_k + 32'd1;
                        sn_next <= sn_next + n_eff;
                        if (run_ndump != 32'd0 && sn_k + 32'd1 == run_ndump) sn_on <= 1'b0;
                    end
                end
                if (wa == 12'd4095) begin
                    sn_act <= 1'b0;
                    wb  <= ~wb;
                    fin <= fin + 1'b1;
                end
            end
            if (cmd_run) begin
                sn_on <= 1'b1; sn_next <= fin + 2; sn_k <= 32'd0;
            end
            if (cmd_stop) sn_on <= 1'b0;
        end
    end

    reg [2*ZW-1:0] fd;
    always @(posedge clk) if (adv) fd <= fbuf[{rbk, ra}];
    always @(posedge clk) begin
        if (rst) begin
            f_v <= 1'b0; f_last <= 1'b0;
        end else if (adv) begin
            f_v    <= rd_go;
            f_last <= rd_go && (ra == 12'd4095);
        end
    end
    // 見張り
    reg rdy_seen;
    always @(posedge clk) begin
        if (rst) begin
            stall_cnt <= 32'd0; rdy0 <= 32'd0; rdy_seen <= 1'b0;
        end else begin
            if (f_v && !s_tready && stall_cnt != 32'hFFFF_FFFF) stall_cnt <= stall_cnt + 32'd1;
            if (s_tready) rdy_seen <= 1'b1;
            else if (!rdy_seen && rdy0 != 32'hFFFF_FFFF) rdy0 <= rdy0 + 32'd1;
        end
    end

    // =====================================================================
    // FFT（build では Xilinx FFT IP、sim では sim/win_fft_model.v。同じポート）
    // =====================================================================
    wire [47:0] s_td = {{(24-ZW){fd[2*ZW-1]}}, fd[2*ZW-1:ZW], {(24-ZW){fd[ZW-1]}}, fd[ZW-1:0]};
    wire [63:0] m_td;
    wire [15:0] m_tu;
    wire        m_tv, m_tl;
    wire        ev_tu, ev_tm, ev_halt, ev_fs;
    win_fft u_fft (
        .aclk                        (clk),
        .aresetn                     (~rst),
        .s_axis_config_tdata         (8'h01),
        .s_axis_config_tvalid        (1'b1),
        .s_axis_config_tready        (),
        .s_axis_data_tdata           (s_td),
        .s_axis_data_tvalid          (f_v),
        .s_axis_data_tready          (s_tready),
        .s_axis_data_tlast           (f_last),
        .m_axis_data_tdata           (m_td),
        .m_axis_data_tuser           (m_tu),
        .m_axis_data_tvalid          (m_tv),
        .m_axis_data_tlast           (m_tl),
        .event_frame_started         (ev_fs),
        .event_tlast_unexpected      (ev_tu),
        .event_tlast_missing         (ev_tm),
        .event_data_in_channel_halt  (ev_halt)
    );

    // =====================================================================
    // 出力側: フレームの判定（spec_core と同じ。fs = ch 0 のクロック）
    // =====================================================================
    wire        o_valid = m_tv;
    wire [11:0] o_k     = m_tu[11:0];
    reg  [11:0] k_exp;
    reg  [31:0] cur_k, cur_idx;
    reg         cur_act, cur_first, cur_last, cur_bank;
    reg  [FW-1:0] pend_f0_0, pend_f0_1;
    reg  [31:0] pend_k_0, pend_k_1;

    reg [31:0] pre_kp1, pre_idxp1;
    reg        pre_end, pre_idxp1_is0, pre_nxt_last, pre_zero_last, pre_f0hit;
    always @(posedge clk) begin
        pre_kp1       <= cur_k + 32'd1;
        pre_end       <= (run_ndump != 32'd0) && (cur_k + 32'd1 == run_ndump);
        pre_idxp1     <= cur_idx + 32'd1;
        pre_idxp1_is0 <= (cur_idx == 32'hFFFF_FFFF);
        pre_nxt_last  <= (cur_idx + 32'd1 == n_eff - 32'd1);
        pre_zero_last <= (n_eff == 32'd1);
        if (rst || cmd_run)                     pre_f0hit <= 1'b0;
        else if (o_valid && o_k == 12'd4095)    pre_f0hit <= (fout + 1'b1 == run_f0);
    end

    reg        d_act, d_newrun, d_stop, d_zero;
    reg [31:0] d_k, d_idx;
    reg        d_idx_is0, d_idx_last;
    always @* begin
        d_act = 1'b0; d_newrun = 1'b0; d_stop = 1'b0; d_k = cur_k; d_zero = 1'b0;
        if (sched && pre_f0hit) begin
            d_act = 1'b1; d_newrun = 1'b1; d_k = 32'd0; d_zero = 1'b1;
        end else if (acc_on) begin
            if (cur_last) begin
                if (pre_end) d_stop = 1'b1;
                else begin d_act = 1'b1; d_k = pre_kp1; d_zero = 1'b1; end
            end else d_act = 1'b1;
        end
        d_idx      = d_zero ? 32'd0 : pre_idxp1;
        d_idx_is0  = d_zero ? 1'b1  : pre_idxp1_is0;
        d_idx_last = d_zero ? pre_zero_last : pre_nxt_last;
    end
    wire fs      = o_valid && (o_k == 12'd0);
    wire t_act   = fs ? d_act : cur_act;
    wire t_first = fs ? d_idx_is0 : cur_first;
    wire t_last  = fs ? d_idx_last : cur_last;
    wire t_bank  = fs ? d_k[0] : cur_bank;

    always @(posedge clk) begin
        if (rst) begin
            fout <= {FW{1'b0}}; k_exp <= 12'd0;
            sched <= 1'b0; acc_on <= 1'b0;
            cur_k <= 0; cur_idx <= 0;
            cur_act <= 1'b0; cur_first <= 1'b0; cur_last <= 1'b0; cur_bank <= 1'b0;
            pend_f0_0 <= 0; pend_f0_1 <= 0; pend_k_0 <= 0; pend_k_1 <= 0;
            run_n <= 32'd1; run_ndump <= 32'd0; run_f0 <= {FW{1'b0}};
        end else begin
            if (o_valid) begin
                k_exp <= o_k + 12'd1;
                if (o_k == 12'd4095) fout <= fout + 1'b1;
            end
            if (fs) begin
                cur_act   <= d_act;
                cur_first <= d_idx_is0;
                cur_last  <= d_act && d_idx_last;
                cur_bank  <= d_k[0];
                cur_k     <= d_k;
                cur_idx   <= d_idx;
                if (d_newrun) begin sched <= 1'b0; acc_on <= 1'b1; end
                if (d_stop)   acc_on <= 1'b0;
                if (d_act && d_idx_is0) begin
                    if (d_k[0]) begin pend_f0_1 <= fout; pend_k_1 <= d_k; end
                    else        begin pend_f0_0 <= fout; pend_k_0 <= d_k; end
                end
            end
            if (cmd_run) begin
                sched <= 1'b1; acc_on <= 1'b0; cur_act <= 1'b0;
                run_n <= r_nacc; run_ndump <= r_ndump; run_f0 <= fin + 2;
            end
            if (cmd_stop) begin sched <= 1'b0; acc_on <= 1'b0; cur_act <= 1'b0; end
        end
    end

    // =====================================================================
    // データ経路: タグ {valid, act, first, last, bank, k[11:0]}
    // =====================================================================
    localparam integer TW = 17;
    localparam integer S_RD = 2, S_SUM = 5;
    reg [TW-1:0] tag [0:S_SUM];
    integer ti;
    always @(posedge clk) begin
        if (rst) for (ti = 0; ti <= S_SUM; ti = ti + 1) tag[ti] <= {TW{1'b0}};
        else begin
            tag[0] <= {o_valid, o_valid && t_act, t_first, t_last, t_bank, o_k};
            for (ti = 1; ti <= S_SUM; ti = ti + 1) tag[ti] <= tag[ti-1];
        end
    end
    `define WV(t)  tag[t][16]
    `define WA(t)  tag[t][15]
    `define WF(t)  tag[t][14]
    `define WL(t)  tag[t][13]
    `define WB(t)  tag[t][12]
    `define WK(t)  tag[t][11:0]

    reg signed [YW-1:0] y_re, y_im;          // S0
    always @(posedge clk) begin
        y_re <= m_td[YW-1:0];
        y_im <= m_td[32 +: YW];
    end
    localparam signed [YW-1:0] QMAX =  (1 <<< (QW-1)) - 1;
    localparam signed [YW-1:0] QMIN = -(1 <<< (QW-1));
    function [QW:0] sat;
        input signed [YW-1:0] z;
        input [3:0]           sh;
        reg   signed [YW-1:0] t;
        begin
            t = z >>> sh;
            if (t > QMAX)      sat = {1'b1, QMAX[QW-1:0]};
            else if (t < QMIN) sat = {1'b1, QMIN[QW-1:0]};
            else               sat = {1'b0, t[QW-1:0]};
        end
    endfunction
    reg signed [QW-1:0] q_re, q_im;           // S1
    reg                 q_sat;
    reg [QW:0] sr, si;
    always @(posedge clk) begin
        sr = sat(y_re, r_shift);
        si = sat(y_im, r_shift);
        q_re <= sr[QW-1:0]; q_im <= si[QW-1:0]; q_sat <= sr[QW] | si[QW];
    end
    reg signed [QW-1:0]   a_re, a_im;         // S2
    reg                   a_sat;
    reg signed [2*QW-1:0] m_re, m_im;         // S3
    reg                   m_sat;
    reg [PW-1:0]          pwr;                // S4
    reg                   p_sat;
    always @(posedge clk) begin
        a_re <= q_re; a_im <= q_im; a_sat <= q_sat;
        m_re <= a_re * a_re; m_im <= a_im * a_im; m_sat <= a_sat;
        pwr  <= m_re + m_im; p_sat <= m_sat;
    end

    // 二面の積分メモリ（面ごとに 4096 × 64 bit）
    wire [63:0] acc_rd [0:1];
    genvar bk;
    generate
        for (bk = 0; bk < 2; bk = bk + 1) begin : g_bank
            reg [63:0] mem [0:NF-1];
            integer mi;
            initial for (mi = 0; mi < NF; mi = mi + 1) mem[mi] = 64'd0;   // 初期値 0（BRAM の初期化。sim で X を出さないため）
            reg [63:0] rd1, rd2;
            reg [11:0] wa_;
            reg [63:0] wd;
            reg        we;
            wire rmw = `WV(S_RD) && `WA(S_RD) && !`WF(S_RD) && (`WB(S_RD) == bk);
            always @(posedge clk) begin
                rd1 <= mem[rmw ? `WK(S_RD) : rd_ch];
                rd2 <= rd1;
                if (we) mem[wa_] <= wd;
            end
            assign acc_rd[bk] = rd2;
            always @(posedge clk) begin
                we  <= `WV(S_SUM-1) && `WA(S_SUM-1) && (`WB(S_SUM-1) == bk);
                wa_ <= `WK(S_SUM-1);
`ifdef WSPEC_POSCTL
                // 陽性対照: 初回のフレームでも読み値に足す（前のダンプの残りが混ざる）
                wd  <= rd2 + {27'd0, pwr};
`else
                wd  <= `WF(S_SUM-1) ? {27'd0, pwr} : rd2 + {27'd0, pwr};
`endif
            end
        end
    endgenerate
    assign rd_data = acc_rd[rd_bk];

    // ---- ダンプの閉じ（S5 の最後の ch）----
    reg [31:0] sat_run;
    reg        s5_sat;
    always @(posedge clk) s5_sat <= p_sat;     // S5 に揃える
    wire commit = `WV(S_SUM) && `WA(S_SUM) && `WL(S_SUM) && (`WK(S_SUM) == 12'd4095);
    always @(posedge clk) begin
        if (rst) begin
            seq <= 0; rd_k <= 0; rd_n <= 0; rd_sat <= 0; sat_run <= 0;
            rd_f0 <= {FW{1'b1}}; rd_bank <= 1'b0;
        end else begin
            if (`WV(S_SUM) && `WA(S_SUM)) begin
                if (`WF(S_SUM) && `WK(S_SUM) == 12'd0) sat_run <= {31'd0, s5_sat};
                else                                   sat_run <= sat_run + {31'd0, s5_sat};
            end
            if (commit) begin
                seq     <= seq + 1;
                rd_bank <= `WB(S_SUM);
                rd_sat  <= sat_run + {31'd0, s5_sat};
                rd_n    <= n_eff;
                rd_f0   <= `WB(S_SUM) ? pend_f0_1 : pend_f0_0;
                rd_k    <= `WB(S_SUM) ? pend_k_1  : pend_k_0;
            end
        end
    end

    // ---- スナップショットの読み出し ----
    generate
        if (SNAP != 0) begin : g_snap
            reg [2*ZW-1:0] snap_mem [0:2*NF-1];
            reg [2*ZW-1:0] sn1, sn2;
            always @(posedge clk) begin
                if (sn_we) snap_mem[{sn_wb, wa}] <= {z_im, z_re};
                sn1 <= snap_mem[{sn_bk, sn_a}];
                sn2 <= sn1;
            end
            assign sn_data = sn2;
        end else begin : g_nosnap
            assign sn_data = {2*ZW{1'b0}};
        end
    endgenerate

    // ---- FLAGS ----
    wire [7:0] f_now = {3'd0, f_v && !s_tready, ev_halt, ev_tu | ev_tm, ovr, o_valid && (o_k != k_exp)};
    always @(posedge clk) begin
        if (rst || cmd_clr) flags <= 8'd0;
        else                flags <= flags | f_now;
    end
endmodule
