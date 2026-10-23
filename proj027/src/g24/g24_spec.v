// SPDX-License-Identifier: BSD-3-Clause
//
// g24_spec — 2G-4 の分光の本体（コア 1 個ぶん: 1 ADC、FULL の流れ 1 本）。proj027 手順 2c: proj025（proj025-m0）の g22_spec を 4096 ビートのフレームに縮めた。AXI・レコードは持たない（外の g24_core が包む。2d）
//
// proj024（proj024-m0）の g21_spec を 4096 ビートのフレームに縮めたもの。g21_spec は src/common/wide_spec.v（567fda2）を写して直したもの:
//   入力（axis_sel4 で選んだ ADC。D-8）→ 起動の見張り → g24_pfb（PFB T = 4、係数の補間を中に持つ）→ lane_fft_g24 × 16（IP、4096 点・
//   bit 反転順）→ g24_chain（＋ g24_tw、ひねり係数の積）→ g24_acc（全 ch の積分器、URAM）
//   - 係数・ひねり係数はコアの中（Wide の「共有の ROM」と配りの 1 段 coef_q・tw_q は無い）。2G-4 はコアが 4 個で、ROM もコアごとに 1 組（proj027 F-2・F-3）
//   - フレームは 4096 ビート: m = (T − K_F) mod 4096、fa = ⌊(T − K_F) / 4096⌋。F0 の格子は **128 フレーム**（2.048 ms、GF_L2 = 7）
//   - 流れは 1 本（KIND 1 FULL）。帳簿は wide_spec の流れごとの形を NS = 1 で残した。束ね・S0 は無い
//   - **SHIFT は RUN で取り込む**（2d で直した。INTERFACE 2.5 の FULL の約束・spec_core と同じ。2c までは Wide（SLICE）を写して WRST で取り込んでいた。
//     RUN の F0 は 2 格子（≧ 32 フレーム）先なので、鎖の途中のフレームは積まない。WRST は SHIFT を変えない）
//   - 出口は bit 反転順: フレームの最初の k1 は 0、最後は 4095（bitrev(4095) = 4095）。fs = (k1 == 0)、最後の行 = (k1 == 4095)
//   - flags[6]（出口の k1 の飛び）は「次の k1 = bitrev(bitrev(k1) + 1)」で見る。flags[7]（積分器の書き込みの衝突）は起きない形なので 0
// DUMP_T = K_F ＋ 4096·DUMP_F0（コアの入口でのそのダンプの最初のビートの T）。
//
// ---- 異常フラグ（粘着。flags_clr で消す。並びは wide_spec と同じ）----
//   [0] coef_mis / [1] tw_mis / [2] 口を開けた後に入力が途切れた / [3] IP の 16 レーンの valid・k1 が揃わない / [4] IP の TLAST の事象 /
//   [5] IP の手前の待ち行列のあふれか、16 レーンの tready の不揃い / [6] 出口の k1 の飛び / [7] 0（予約）

`timescale 1ns / 1ps

module g24_spec #(
    parameter integer K_F           = 0,       // フレームの頭の位相（T ≡ K_F mod 4096）
    parameter integer ST_N          = 16384,   // 起動の見張り（クロック）。0 = 見張らない
    parameter integer SHIFT_DEFAULT = 7,
    parameter integer FW            = 48,
    parameter integer GF_L2         = 7,       // 格子のフレーム数の log2（128 フレーム = 2.048 ms）。sim では小さくして待ちを縮める
    parameter LO_FILE = "g24_coef_lo.hex",
    parameter HI_FILE = "g24_coef_hi.hex",
    parameter TA_FILE = "g24_tw_a.hex",
    parameter TB_FILE = "g24_tw_b.hex"
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [255:0]      s_tdata,
    input  wire              s_tvalid,
    input  wire [63:0]       t_in,
    // 制御
    input  wire              cmd_wrst,
    input  wire [3:0]        w_shift,
    input  wire              cmd_run,
    input  wire              cmd_stop,
    input  wire [31:0]       r_nacc,
    input  wire [31:0]       r_ndump,
    input  wire              flags_clr,
    // 今効いている値・状態
    output reg  [3:0]        c_shift,
    output reg               go,
    output wire [FW-1:0]     fa_now,
    output reg  [FW-1:0]     fo,
    output reg  [7:0]        flags,
    output reg               st_sched, st_acc,
    // ダンプ（commit で変わる）
    output reg               commit,
    output reg  [31:0]       seq,
    output reg  [31:0]       dk,
    output reg  [FW-1:0]     df0,
    output reg  [31:0]       dn,
    output reg  [31:0]       dsat,
    output reg               rd_plane,
    // 読み出し（凍った面）
    input  wire [14:0]       rd_c,
    output wire [63:0]       rd_d,
    // 診断
    output wire [15:0]       dbg_pfb_sat,
    output wire              dbg_have_first,
    output wire [15:0]       dbg_ipq,          // {待たされたクロック数（8 bit で飽和）, 2'b0, 待ち行列の語数}
    output wire [31:0]       dbg_ip_ph,        // {4'b0, 入口の位相[27:16], 4'b0, 出口の位相[11:0]}
    output wire [15:0]       dbg_ip_st,        // 最初に IP が受けてから初めて待たされるまでのクロック（飽和）
    // sim の記録用（IP の出口）
    output wire [16*64-1:0]  dbg_ip_tdata,
    output wire [11:0]       dbg_ip_k1,
    output wire              dbg_ip_v
);
    localparam integer NL = 16;

    function [11:0] brev12(input [11:0] n);
        integer b;
        begin for (b = 0; b < 12; b = b + 1) brev12[11 - b] = n[b]; end
    endfunction

    // ---- 入力と T を 1 段受ける ----
    reg [255:0] d_loc;
    reg         v_loc;
    reg [63:0]  t_loc;
    always @(posedge clk) begin d_loc <= s_tdata; v_loc <= s_tvalid; t_loc <= t_in; end
    wire [63:0] tk = t_loc - K_F;
    wire [11:0] m_now = tk[11:0];
    assign fa_now = tk[12 +: FW];

    // ---- 起動の見張り（wide_spec と同じ。IP の 16 レーンの tready も見る）----
    wire [NL-1:0] ln_s_tready;
    wire          ip_ready = &ln_s_tready;
    reg [15:0] st_run;
    always @(posedge clk) begin
        if (rst) begin
            go <= (ST_N == 0); st_run <= 16'd0;
        end else if (!go) begin
            if (v_loc && ip_ready) begin
                if (st_run == ST_N - 1) go <= 1'b1; else st_run <= st_run + 16'd1;
            end else st_run <= 16'd0;
        end
    end

    // ---- PFB（係数の補間は g24_pfb の中）----
    wire              p_v = v_loc && go;
    wire [16*15-1:0]  y;
    wire              y_v, y_first, coef_mis;
    wire [11:0]       y_m;
    wire [1:0]        y_fr;
    wire [15:0]       pfb_sat;
    g24_pfb #(.LO_FILE(LO_FILE), .HI_FILE(HI_FILE)) u_pfb (.clk(clk), .rst(rst), .s_tdata(d_loc), .s_tvalid(p_v), .s_m(m_now),
                    .y(y), .y_v(y_v), .y_m(y_m), .y_first(y_first), .y_fr(y_fr), .sat_cnt(pfb_sat), .coef_mis(coef_mis));

    // ---- IP の手前の待ち行列（wide_spec と同じ。proj023 4b）----
    localparam integer QD = 32;
    reg  [15*NL:0] q_sr [0:QD-1];        // {TLAST, y}
    reg  [5:0]     q_n;
    reg  [7:0]     q_stall;
    wire           q_v   = (q_n != 6'd0);
    wire           q_pop = q_v && ip_ready;
    wire [4:0]     q_idx = q_n[4:0] - 5'd1;
`ifdef IPQ_POSCTL
    wire [15*NL:0] q_out = {y_m == 12'd4095, y};
    wire           q_vin = y_v;
`else
    wire [15*NL:0] q_out = q_sr[q_idx];
    wire           q_vin = q_v;
`endif
    wire           q_ovf = (q_n == QD) && y_v && !q_pop;
    integer qi;
    always @(posedge clk) begin
        if (y_v) begin
            q_sr[0] <= {y_m == 12'd4095, y};
            for (qi = 1; qi < QD; qi = qi + 1) q_sr[qi] <= q_sr[qi - 1];
        end
    end
    always @(posedge clk) begin
        if (rst) begin q_n <= 6'd0; q_stall <= 8'd0; end
        else begin
            if (!q_ovf) q_n <= q_n + {5'd0, y_v} - {5'd0, q_pop};
            if (q_v && !ip_ready && q_stall != 8'hFF) q_stall <= q_stall + 8'd1;
        end
    end
    assign dbg_ipq = {q_stall, 2'b00, q_n};

    // ---- IP の位相（wide_spec と同じ診断。出口の位相は k1 = 0 を出したクロックの m）----
    wire [NL-1:0]    ln_m_tvalid, ln_m_tlast, ln_ev_fs, ln_ev_unexp, ln_ev_miss, ln_ev_halt;
    wire [NL*64-1:0] ln_m_tdata;
    wire [NL*16-1:0] ln_m_tuser;
    reg [11:0] ph_in, ph_out;
    reg        ph_in_v, st_seen;
    reg [15:0] st_at;
    always @(posedge clk) begin
        if (rst) begin ph_in <= 12'd0; ph_out <= 12'd0; ph_in_v <= 1'b0; st_seen <= 1'b0; st_at <= 16'd0; end
        else begin
            if (q_pop && !ph_in_v) begin ph_in_v <= 1'b1; ph_in <= m_now; end
            if (!st_seen && q_v && !ip_ready) st_seen <= 1'b1;
            else if (ph_in_v && !st_seen && st_at != 16'hFFFF) st_at <= st_at + 16'd1;
            if (ln_m_tvalid[0] && ln_m_tuser[11:0] == 12'd0) ph_out <= m_now;
        end
    end
    assign dbg_ip_ph = {4'd0, ph_in, 4'd0, ph_out};
    assign dbg_ip_st = st_at;

    // PFB に入った最初のフレームの番号
    reg          have_first;
    reg [FW-1:0] f_first;
    always @(posedge clk) begin
        if (rst) begin have_first <= 1'b0; f_first <= {FW{1'b0}}; end
        else if (p_v && !have_first && m_now == 12'd0) begin have_first <= 1'b1; f_first <= fa_now; end
    end

    // ---- レーン FFT（IP）× 16 ----
    genvar p;
    generate
        for (p = 0; p < NL; p = p + 1) begin : g_lane
            wire signed [14:0] yp = q_out[15*p +: 15];
            (* dont_touch = "true" *) reg ln_rstn = 1'b0;
            always @(posedge clk) ln_rstn <= ~rst;
            lane_fft_g24 u_fft (
                .aclk(clk), .aresetn(ln_rstn),
                .s_axis_config_tdata(8'h01), .s_axis_config_tvalid(!go), .s_axis_config_tready(),
                .s_axis_data_tdata({16'h0000, yp[14], yp}), .s_axis_data_tvalid(q_vin), .s_axis_data_tready(ln_s_tready[p]),
                .s_axis_data_tlast(q_out[15*NL]),
                .m_axis_data_tdata(ln_m_tdata[64*p +: 64]), .m_axis_data_tuser(ln_m_tuser[16*p +: 16]),
                .m_axis_data_tvalid(ln_m_tvalid[p]), .m_axis_data_tlast(ln_m_tlast[p]),
                .event_frame_started(ln_ev_fs[p]), .event_tlast_unexpected(ln_ev_unexp[p]),
                .event_tlast_missing(ln_ev_miss[p]), .event_data_in_channel_halt(ln_ev_halt[p]));
        end
    endgenerate
    assign dbg_ip_tdata   = ln_m_tdata;
    assign dbg_pfb_sat    = pfb_sat;
    assign dbg_have_first = have_first;
    assign dbg_ip_k1      = ln_m_tuser[11:0];
    assign dbg_ip_v       = ln_m_tvalid[0];

    // ---- 鎖（＋ ひねり係数の積）----
    wire [16*27-1:0] yr, yi;
    generate
        for (p = 0; p < NL; p = p + 1) begin : g_y
            assign yr[27*p +: 27] = ln_m_tdata[64*p      +: 27];
            assign yi[27*p +: 27] = ln_m_tdata[64*p + 32 +: 27];
        end
    endgenerate
    wire [11:0]  tw_addr, tw_k1, pk1;
    wire [575:0] tw;
    g24_tw #(.A_FILE(TA_FILE), .B_FILE(TB_FILE)) u_tw (.clk(clk), .addr(tw_addr), .tw(tw), .k1_out(tw_k1));
    wire [8*37-1:0] pw;
    wire            pv, tw_mis;
    wire [3:0]      psat;
    g24_chain u_chain (.clk(clk), .rst(rst), .y_re(yr), .y_im(yi), .y_k1(ln_m_tuser[11:0]), .y_v(ln_m_tvalid[0]),
                       .tw_addr(tw_addr), .tw(tw), .tw_k1(tw_k1), .shift(c_shift),
                       .p(pw), .p_v(pv), .p_k1(pk1), .p_sat(psat), .tw_mis(tw_mis));

    // ---- RUN: SHIFT を取り込む（2d。FULL の約束）----
    always @(posedge clk) begin
        if (rst) c_shift <= SHIFT_DEFAULT;
        else if (cmd_run && !cmd_wrst) c_shift <= w_shift;
    end

    // ---- 出口のフレームの番号（bit 反転順: 最初の k1 = 0、最後の k1 = 4095）----
    wire          fs = pv && (pk1 == 12'd0);
    wire          ls = pv && (pk1 == 12'd4095);
    reg           have_fo;
    wire [FW-1:0] fo_now = have_fo ? fo + 1'b1 : f_first;

    // ---- 帳簿（wide_spec の流れごとの形を、流れ 1 本で）----
    reg [31:0]   run_n, run_nd, cur_k, cur_i;
    reg [FW-1:0] run_f0;
    reg          cur_act, cur_first, cur_last, cur_pl;
    reg          d_act, d_first, d_last, d_pl, d_new, d_stop;
    reg [31:0]   d_k, d_i;
    reg          pre_hit, pre_end, pre_ip1_is0, pre_nxt_last, pre_zero_last;
    reg [31:0]   pre_kp1, pre_ip1;
    always @(posedge clk) begin
        pre_kp1       <= cur_k + 32'd1;
        pre_end       <= (run_nd != 32'd0) && (cur_k + 32'd1 == run_nd);
        pre_ip1       <= cur_i + 32'd1;
        pre_ip1_is0   <= (cur_i == 32'hFFFF_FFFF);
        pre_nxt_last  <= (cur_i + 32'd1 == run_n - 32'd1);
        pre_zero_last <= (run_n == 32'd1);
        if (rst || cmd_run) pre_hit <= 1'b0;
        else                pre_hit <= (fo_now == run_f0);
    end
    always @* begin
        d_act = 1'b0; d_new = 1'b0; d_stop = 1'b0;
        d_k = cur_k; d_i = pre_ip1;
        d_first = pre_ip1_is0; d_last = pre_nxt_last;
        if (st_sched && pre_hit) begin
            d_act = 1'b1; d_new = 1'b1; d_k = 32'd0; d_i = 32'd0; d_first = 1'b1; d_last = pre_zero_last;
        end else if (st_acc) begin
            if (cur_last) begin
                if (pre_end) d_stop = 1'b1;
                else begin d_act = 1'b1; d_k = pre_kp1; d_i = 32'd0; d_first = 1'b1; d_last = pre_zero_last; end
            end else d_act = 1'b1;
        end
        d_last = d_act && d_last;
        d_pl   = d_k[0];
    end
    wire t_act   = fs ? d_act   : cur_act;
    wire t_first = fs ? d_first : cur_first;
    wire t_pl    = fs ? d_pl    : cur_pl;
    wire t_last  = fs ? d_last  : cur_last;

    // ダンプを閉じる: 最後のフレームの最後の行から 5 クロック後（g24_acc の書きが終わった後）
    reg [4:0]    cm;
    reg [31:0]   l_k, l_n, l_sat;
    reg [FW-1:0] l_f0, k_f0;
    reg          l_pl;
    reg [31:0]   sat_run;
    always @(posedge clk) begin
        if (rst) begin
            have_fo <= 1'b0; fo <= {FW{1'b0}};
            st_sched <= 1'b0; st_acc <= 1'b0;
            cur_act <= 1'b0; cur_first <= 1'b0; cur_last <= 1'b0; cur_pl <= 1'b0;
            run_n <= 32'd1; run_nd <= 32'd0; run_f0 <= {FW{1'b0}}; cur_k <= 32'd0; cur_i <= 32'd0; sat_run <= 32'd0;
            cm <= 5'd0;
        end else begin
            if (fs) begin
                have_fo <= 1'b1; fo <= fo_now;
                cur_act <= d_act; cur_first <= d_first; cur_last <= d_last; cur_pl <= d_pl;
                cur_k <= d_k; cur_i <= d_i;
                if (d_new)  begin st_sched <= 1'b0; st_acc <= 1'b1; end
                if (d_stop) st_acc <= 1'b0;
            end
            if (pv && t_act) sat_run <= ((t_first && fs) ? 32'd0 : sat_run) + {28'd0, psat};
            cm <= {cm[3:0], ls && t_act && t_last};
            if (ls && t_act && t_last) begin
                l_k <= fs ? d_k : cur_k; l_pl <= t_pl; l_f0 <= (fs && d_first) ? fo_now : k_f0;
                l_n <= run_n; l_sat <= ((t_first && fs) ? 32'd0 : sat_run) + {28'd0, psat};
            end
            if (cmd_wrst || cmd_stop) begin st_sched <= 1'b0; st_acc <= 1'b0; cur_act <= 1'b0; end
            if (cmd_run && !cmd_wrst) begin
                st_sched <= 1'b1; st_acc <= 1'b0; cur_act <= 1'b0;
                run_n  <= (r_nacc == 32'd0) ? 32'd1 : r_nacc;
                run_nd <= r_ndump;
                run_f0 <= ((fa_now >> GF_L2) + 2) << GF_L2;
            end
        end
    end
    always @(posedge clk) begin
        if (rst) begin
            commit <= 1'b0; seq <= 0; dk <= 0; df0 <= 0; dn <= 0; dsat <= 0; rd_plane <= 1'b0;
        end else begin
            commit <= cm[4];
            if (fs && d_act && d_first) k_f0 <= fo_now;
            if (cm[4]) begin seq <= seq + 1; dk <= l_k; df0 <= l_f0; dn <= l_n; dsat <= l_sat; rd_plane <= l_pl; end
        end
    end

    // ---- 積分器 ----
    g24_acc u_acc (.clk(clk), .rst(rst), .p(pw), .p_v(pv), .p_k1(pk1), .t_act(t_act), .t_first(t_first), .t_plane(t_pl),
                   .rd_c(rd_c), .rd_plane(rd_plane), .rd_d(rd_d));

    // ---- 異常フラグ ----
    reg [11:0] k1_exp;
    reg        k1_seen;
    reg        f_lane;
    integer li;
    always @* begin
        f_lane = (ln_m_tvalid != {NL{1'b0}}) && (ln_m_tvalid != {NL{1'b1}});
        for (li = 1; li < NL; li = li + 1)
            if (ln_m_tvalid[li] && ln_m_tuser[16*li +: 12] != ln_m_tuser[11:0]) f_lane = 1'b1;
    end
    wire [7:0] f_now = {1'b0,
                        k1_seen && ln_m_tvalid[0] && ln_m_tuser[11:0] != k1_exp,
                        q_ovf || (q_vin && ln_s_tready != {NL{1'b0}} && ln_s_tready != {NL{1'b1}})
`ifdef IPQ_POSCTL
                        || (q_vin && !ip_ready)
`endif
                        ,
                        |(ln_ev_unexp | ln_ev_miss),
                        f_lane,
                        go && !v_loc,
                        tw_mis,
                        coef_mis};
    always @(posedge clk) begin
        if (rst) begin k1_seen <= 1'b0; k1_exp <= 12'd0; end
        else if (ln_m_tvalid[0]) begin k1_seen <= 1'b1; k1_exp <= brev12(brev12(ln_m_tuser[11:0]) + 12'd1); end
        if (rst || flags_clr) flags <= 8'd0;
        else flags <= flags | f_now;
    end
endmodule
