// SPDX-License-Identifier: BSD-3-Clause
//
// fine_core — 細かい側の全体（proj028 F-4）。ct_rd の出口（荒い ch ごとの流れ）→ 細かいスペクトルのレコード
//
//   入口: AXI4-Stream 512 bit（32 サンプル、i 番が [16i +: 16] = {im 8, re 8}）、tuser = {c[15:0], k[4:0], 末尾 1 / 本体 0}、tlast = ch の最後
//   → 256 bit（16 サンプル）に分ける → **2 フレーム（16384 拍）の溜め**（DDR からの途切れを吸い、フレームがそろってから流す。
//     realtime の IP には途切れなく流す、LESSONS）→ fine_pfb（ch の頭で履歴を空に）→ IP の手前の待ち行列（g21_spec と同じ、LESSONS）
//   → レーン FFT × 16（lane_fft_f、8192 点・bit 反転順）→ fine_chain（＋ fine_tw）→ fine_acc → fine_rdo → 出口: レコード（AXI4-Stream 64 bit）
//
//   フレームの帳簿（フレームが PFB に入り終えたときに積み、鎖の出口のフレームの頭で取り出す。IP は 1 フレーム溜めて出すので間に合う）:
//     act = 本体 かつ ch の中で 3 フレーム目以降（PFB の履歴が埋まった）、first = その ch で最初の act、last = ch の最後のフレーム（tlast）、
//     plane = ch ごとに替える面、k・c、積んだ数（last のフレームに載せる）。チャンク 0（末尾なし）は最初の 3 フレームを積まない（157 フレーム）
//   ch の最後のフレームを積み終えたら fine_rdo に読ませる
//
// 異常フラグ（粘着、rst で消す）: [0] 待ち行列のあふれ [1] IP の TLAST の事象 [2] IP の halt [3] tw_mis [4] coef_mis
//   [5] 読み出しが間に合わず捨てた [6] 帳簿の空読み・あふれ [7] PFB の飽和 [8] 空のフレームと本物が重なった

`timescale 1ns / 1ps

module fine_core #(
    parameter LO_FILE = "fine_coef_lo.hex",
    parameter HI_FILE = "fine_coef_hi.hex",
    parameter TA_FILE = "fine_tw_a.hex",
    parameter TB_FILE = "fine_tw_b.hex",
    parameter integer ST_N = 64,           // 起動の見張り: IP の 16 レーンの tready がそろって続いたクロック
    parameter integer FB_LOG = 14          // 溜めの深さ 2^FB_LOG 拍。14 = 2 フレーム（F-5c-0）。13 = 1 フレーム（直す前、sim の陽性対照）
)(
    input  wire          clk,
    input  wire          rst,
    input  wire [511:0]  s_axis_tdata,
    input  wire [21:0]   s_axis_tuser,
    input  wire          s_axis_tlast,
    input  wire          s_axis_tvalid,
    output wire          s_axis_tready,
    input  wire [3:0]    shift,
    output wire [63:0]   m_axis_tdata,
    output wire          m_axis_tlast,
    output wire          m_axis_tvalid,
    input  wire          m_axis_tready,
    output reg  [8:0]    flags,
    output reg  [31:0]   n_rec,               // 読み出しを始めたレコードの数
    // sim の記録用（IP の出口）
    output wire [16*64-1:0] dbg_ip_tdata,
    output wire [12:0]   dbg_ip_k1,
    output wire          dbg_ip_v
);
    localparam integer NL = 16;
    localparam integer FW_ = 256 + 1 + 1 + 1 + 5 + 16;   // {c, k, 末尾, last, first, data}

    // ---- 入口: 512 → 256（2 拍）----
    reg         half;                // 上半分を出す番
    reg [255:0] hi_d;
    reg [21:0]  hi_u;
    reg         hi_l;
    reg         new_ch;              // 次の拍は ch の頭
    wire [FB_LOG:0] f_cnt;
    wire        f_room2 = (f_cnt <= (1 << FB_LOG) - 2);
    assign s_axis_tready = !rst && !half && f_room2;
    wire        in_fire = s_axis_tvalid && s_axis_tready;
    wire        f_we    = in_fire || half;
    wire [FW_-1:0] f_wd = in_fire ? {s_axis_tuser[21:6], s_axis_tuser[5:1], s_axis_tuser[0], 1'b0, new_ch, s_axis_tdata[255:0]}
                                  : {hi_u[21:6], hi_u[5:1], hi_u[0], hi_l, 1'b0, hi_d};
    always @(posedge clk) begin
        if (rst) begin half <= 1'b0; new_ch <= 1'b1; end
        else begin
            if (in_fire) begin
                half <= 1'b1; hi_d <= s_axis_tdata[511:256]; hi_u <= s_axis_tuser; hi_l <= s_axis_tlast;
                new_ch <= s_axis_tlast;
            end else if (half) half <= 1'b0;
        end
    end

    // ---- 溜め（2^FB_LOG × FW_、既定 2 フレーム）----
    //   F-5c-0（実機）: 1 フレームの溜めでは、満ちている間は入口を止めるので、本物の枠の 8192 クロックで次の 1 フレームを埋め切れず、
    //   本物と空の枠が交互になった（1 チャンク 333 ms > 286.72 ms、7 チャンクに 1 つ ct_rd が捨てた）。2 フレームにして、空の枠で溜めた分を次の枠に回す
    (* ram_style = "block" *) reg [FW_-1:0] fmem [0:(1 << FB_LOG) - 1];
    reg [FB_LOG-1:0] f_wa, f_ra;
    reg [FB_LOG:0]   f_n;
    // ---- 枠: 8192 拍ずつ途切れなく回す。枠の頭で 1 フレームそろっていれば本物、そろっていなければ空のフレーム ----
    //   realtime の IP はフレームの間の途切れも halt として進む（IP のモデル・LESSONS）。細かい側の忙しさは 58 % なので、空きを空のフレームで埋める
    reg        s_run;                // 枠の途中
    reg        s_dum;                // 今の枠は空のフレーム
    reg [12:0] f_m;                  // 枠の中の拍
    reg        go;
    wire       s_start = go && !s_run;
    wire       f_full = (f_n >= 8192);                   // 1 フレームそろった
    wire       f_re   = (s_run && !s_dum) || (s_start && f_full);
    wire       d_beat = (s_run && s_dum)  || (s_start && !f_full);
    reg        f_v1, d_v1;
    reg [12:0] d_m1;
    reg [FW_-1:0] f_rd0, f_rdb;
    (* shreg_extract = "no" *) reg [FW_-1:0] f_rd;
    reg        f_v0, d_v0, f_vb, d_vb;
    reg [12:0] d_m0, d_mb;
    assign f_cnt = f_n;
    always @(posedge clk) begin
        if (f_we) fmem[f_wa] <= f_wd;
        // F-5b: 溜めの読みは 2 段（BRAM の出口レジスタ）。全体のビルドで溜めの出口 → 帳簿の加算 → inf_q が WNS −0.186 ns だった。
        //   空のフレームの道（d_*）も同じだけ遅らせる（本物と空の合流の関係は変わらない）
        //   F-5d: 溜めを 2 フレーム（縦につないだ BRAM）にしたら、出口 → fine_pfb の遅延線（SRL）が WNS −0.076 ns（PE）。
        //   3 段にし、最後の段は SRL に吸わせない
        if (f_re) f_rd0 <= fmem[f_ra];
        f_rdb <= f_rd0;
        f_rd  <= f_rdb;
        f_v0 <= f_re && !rst;   f_vb <= f_v0 && !rst;  f_v1 <= f_vb && !rst;
        d_v0 <= d_beat && !rst; d_vb <= d_v0 && !rst;  d_v1 <= d_vb && !rst;
        d_m0 <= s_start ? 13'd0 : f_m; d_mb <= d_m0; d_m1 <= d_mb;
        if (rst) begin f_wa <= 0; f_ra <= 0; f_n <= 0; s_run <= 1'b0; s_dum <= 1'b0; f_m <= 13'd0; end
        else begin
            if (f_we) f_wa <= f_wa + 1'b1;
            if (f_re) f_ra <= f_ra + 1'b1;
            if (s_start) begin s_run <= 1'b1; s_dum <= !f_full; f_m <= 13'd1; end
            else if (s_run) begin f_m <= f_m + 13'd1; if (f_m == 13'd8191) s_run <= 1'b0; end
            f_n <= f_n + (f_we ? 1'b1 : 1'b0) - (f_re ? 1'b1 : 1'b0);
        end
    end
    wire [255:0] x_d    = f_rd[255:0];
    wire         x_first = f_rd[256];
    wire         x_last  = f_rd[257];
    wire         x_tail  = f_rd[258];
    wire [4:0]   x_k     = f_rd[263:259];
    wire [15:0]  x_c     = f_rd[279:264];

    // ---- 帳簿を積む（PFB に入り終えたフレーム）----
    reg [12:0] xm;                   // 入口のフレームの中の拍（ch の頭で 0）
    reg [15:0] xf;                   // ch の中のフレーム
    reg        xpl, xhas_act, xlast;
    reg [15:0] xnact;
    reg [44:0] inf_q [0:7];          // {4'd0, nact 16, last, first, act, plane, k 5, c 16}（45 bit）
    reg [2:0]  inf_w, inf_r;
    reg [3:0]  inf_n;
    reg        inf_push, inf_pop;
    wire       x_frame_end = f_v1 && (x_first ? 1'b0 : (xm == 13'd8191));
    always @(posedge clk) begin
        inf_push <= 1'b0;
        // 空のフレームの帳簿（積まない）。本物のフレームの帳簿とは同じクロックにならない（枠が別）
        if (!rst && d_v1 && d_m1 == 13'd8191) begin
            inf_q[inf_w] <= 45'd0; inf_w <= inf_w + 3'd1; inf_push <= 1'b1;
        end
        if (rst) begin xm <= 13'd0; xf <= 16'd0; xpl <= 1'b1; xhas_act <= 1'b0; xnact <= 16'd0; xlast <= 1'b0; inf_w <= 3'd0; end
        else if (f_v1) begin
            if (x_first) begin xm <= 13'd1; xf <= 16'd0; xpl <= ~xpl; xhas_act <= 1'b0; xnact <= 16'd0; xlast <= x_last; end
            else begin
                xm <= xm + 13'd1;
                if (x_last) xlast <= 1'b1;
            end
            // フレームの最後の拍: 帳簿を積む
            if ((x_first ? 13'd0 : xm) == 13'd8191) begin
                inf_q[inf_w] <= {4'd0, (xnact + (((!x_tail) && xf >= 16'd3) ? 16'd1 : 16'd0)),
                                 (xlast || x_last), ((!x_tail) && xf >= 16'd3 && !xhas_act), ((!x_tail) && xf >= 16'd3),
                                 (x_first ? ~xpl : xpl), x_k, x_c};
                inf_w <= inf_w + 3'd1; inf_push <= 1'b1;
                if ((!x_tail) && xf >= 16'd3) begin xhas_act <= 1'b1; xnact <= xnact + 16'd1; end
                xf <= xf + 16'd1;
                xlast <= 1'b0;
            end
        end
    end

    // ---- 起動の見張り（IP の 16 レーンの tready がそろって ST_N クロック続いたら流し始める）----
    wire [NL-1:0] ln_s_tready;
    wire          ip_ready = &ln_s_tready;
    reg [15:0]    st_run;
    always @(posedge clk) begin
        if (rst) begin go <= 1'b0; st_run <= 16'd0; end
        else if (!go) begin
            if (ip_ready) begin if (st_run == ST_N - 1) go <= 1'b1; else st_run <= st_run + 16'd1; end
            else st_run <= 16'd0;
        end
    end

    // ---- PFB ----
    wire [16*15-1:0] yr, yi;
    wire             y_v, y_first, coef_mis;
    wire [12:0]      y_m;
    wire [1:0]       y_fr;
    wire [15:0]      pfb_sat;
    fine_pfb #(.LO_FILE(LO_FILE), .HI_FILE(HI_FILE)) u_pfb (.clk(clk), .rst(rst), .s_tdata(x_d), .s_tvalid(f_v1), .s_first(f_v1 && x_first),
        .y_re(yr), .y_im(yi), .y_v(y_v), .y_m(y_m), .y_first(y_first), .y_fr(y_fr), .sat_cnt(pfb_sat), .coef_mis(coef_mis));

    // ---- IP の手前の待ち行列（g21_spec と同じ）----
    localparam integer QD = 32;
    reg  [30*NL:0] q_sr [0:QD-1];        // {TLAST, {yi, yr} × 16}
    reg  [5:0]     q_n;
    wire           q_v   = (q_n != 6'd0);
    wire           q_pop = q_v && ip_ready;
    wire [4:0]     q_idx = q_n[4:0] - 5'd1;
    wire [30*NL:0] q_out = q_sr[q_idx];
    wire [30*NL-1:0] yy;
    genvar p;
    generate for (p = 0; p < NL; p = p + 1) begin : g_yy
        assign yy[30*p +: 30] = {yi[15*p +: 15], yr[15*p +: 15]};
    end endgenerate
    // 空のフレームは PFB の遅れ（PFB_LAT 拍、f_v1 → y_v）だけ遅らせて、待ち行列の入口で合流させる
    localparam integer PFB_LAT = 11;   // F-5b: fine_pfb の係数の段を 1 つ足して 10 → 11
    reg [PFB_LAT-1:0] dv_sh;
    reg [12:0]        dm_sh [0:PFB_LAT-1];
    integer di;
    always @(posedge clk) begin
        dv_sh <= {dv_sh[PFB_LAT-2:0], d_v1 && !rst};
        dm_sh[0] <= d_m1;
        for (di = 1; di < PFB_LAT; di = di + 1) dm_sh[di] <= dm_sh[di-1];
        if (rst) dv_sh <= {PFB_LAT{1'b0}};
    end
    wire        d_vo = dv_sh[PFB_LAT-1];
    wire [12:0] d_mo = dm_sh[PFB_LAT-1];
    wire        qi_v = y_v || d_vo;
    wire [30*NL:0] qi_d = y_v ? {y_m == 13'd8191, yy} : {d_mo == 13'd8191, {(30*NL){1'b0}}};
    wire        q_ovl = y_v && d_vo;          // 本物と空が重なった（PFB_LAT の誤り）
    wire        q_ovf = (q_n == QD) && qi_v && !q_pop;
    integer qi;
    always @(posedge clk) begin
        if (qi_v) begin
            q_sr[0] <= qi_d;
            for (qi = 1; qi < QD; qi = qi + 1) q_sr[qi] <= q_sr[qi - 1];
        end
        if (rst) q_n <= 6'd0;
        else if (!q_ovf) q_n <= q_n + {5'd0, qi_v} - {5'd0, q_pop};
    end

    // ---- レーン FFT × 16 ----
    wire [NL-1:0]    ln_m_tvalid, ln_m_tlast, ln_ev_fs, ln_ev_unexp, ln_ev_miss, ln_ev_halt;
    wire [NL*64-1:0] ln_m_tdata;
    wire [NL*16-1:0] ln_m_tuser;
    generate for (p = 0; p < NL; p = p + 1) begin : g_lane
        wire signed [14:0] pr = q_out[30*p +: 15];
        wire signed [14:0] pi = q_out[30*p + 15 +: 15];
        (* dont_touch = "true" *) reg ln_rstn = 1'b0;
        always @(posedge clk) ln_rstn <= ~rst;
        lane_fft_f u_fft (
            .aclk(clk), .aresetn(ln_rstn),
            .s_axis_config_tdata(8'h01), .s_axis_config_tvalid(!go), .s_axis_config_tready(),
            .s_axis_data_tdata({pi[14], pi, pr[14], pr}), .s_axis_data_tvalid(q_v), .s_axis_data_tready(ln_s_tready[p]),
            .s_axis_data_tlast(q_out[30*NL]),
            .m_axis_data_tdata(ln_m_tdata[64*p +: 64]), .m_axis_data_tuser(ln_m_tuser[16*p +: 16]),
            .m_axis_data_tvalid(ln_m_tvalid[p]), .m_axis_data_tlast(ln_m_tlast[p]),
            .event_frame_started(ln_ev_fs[p]), .event_tlast_unexpected(ln_ev_unexp[p]),
            .event_tlast_missing(ln_ev_miss[p]), .event_data_in_channel_halt(ln_ev_halt[p]));
    end endgenerate
    assign dbg_ip_tdata = ln_m_tdata;
    assign dbg_ip_k1    = ln_m_tuser[12:0];
    assign dbg_ip_v     = ln_m_tvalid[0];

    // ---- 鎖 ----
    wire [16*28-1:0] cr, ci;
    generate for (p = 0; p < NL; p = p + 1) begin : g_y
        assign cr[28*p +: 28] = ln_m_tdata[64*p      +: 28];
        assign ci[28*p +: 28] = ln_m_tdata[64*p + 32 +: 28];
    end endgenerate
    wire [12:0]  tw_addr, tw_k1, pk1;
    wire [575:0] tw;
    fine_tw #(.A_FILE(TA_FILE), .B_FILE(TB_FILE)) u_tw (.clk(clk), .addr(tw_addr), .tw(tw), .k1_out(tw_k1));
    wire [16*37-1:0] pw;
    wire             pv, tw_mis;
    wire [4:0]       psat;
    fine_chain u_chain (.clk(clk), .rst(rst), .y_re(cr), .y_im(ci), .y_k1(ln_m_tuser[12:0]), .y_v(ln_m_tvalid[0]),
        .tw_addr(tw_addr), .tw(tw), .tw_k1(tw_k1), .shift(shift), .p(pw), .p_v(pv), .p_k1(pk1), .p_sat(psat), .tw_mis(tw_mis));

    // ---- 帳簿を取り出す（鎖の出口のフレームの頭 = k1 0）----
    wire        fs = pv && (pk1 == 13'd0);
    wire        ls = pv && (pk1 == 13'd8191);
    reg [44:0]  cur;
    reg         inf_empty_err;
    always @(posedge clk) begin
        if (rst) begin inf_r <= 3'd0; inf_n <= 4'd0; inf_empty_err <= 1'b0; cur <= 45'd0; end
        else begin
            inf_n <= inf_n + (inf_push ? 4'd1 : 4'd0) - (fs && inf_n != 4'd0 ? 4'd1 : 4'd0);
            if (fs) begin
                if (inf_n == 4'd0) inf_empty_err <= 1'b1;
                else begin cur <= inf_q[inf_r]; inf_r <= inf_r + 3'd1; end
            end
        end
    end
    wire [44:0] cur_now  = fs ? inf_q[inf_r] : cur;           // フレームの頭の拍から使う
    // 帳簿の並び: {4'd0, nact[40:25], last[24], first[23], act[22], plane[21], k[20:16], c[15:0]}
`ifdef CORE_ACT_ERR
    wire        c_act    = cur_now[23];          // 陽性対照: first の bit を act として読む
`else
    wire        c_act    = cur_now[22];
`endif
    wire        c_first  = cur_now[23];
    wire        c_last   = cur_now[24];
    wire        c_pl     = cur_now[21];
    wire [4:0]  c_k      = cur_now[20:16];
    wire [15:0] c_c      = cur_now[15:0];
    wire [15:0] c_nact   = cur_now[40:25];

    // ---- 積分器と読み出し ----
    wire [16:0] rd_c; wire rd_pl; wire [63:0] rd_d;
    fine_acc u_acc (.clk(clk), .rst(rst), .p(pw), .p_v(pv), .p_k1(pk1), .t_act(c_act), .t_first(c_first), .t_plane(c_pl),
        .rd_c(rd_c), .rd_plane(rd_pl), .rd_d(rd_d));
    // ch の最後のフレームの最後の拍を積み終えてから（fine_acc の RMW は 4 段）読ませる
    reg [7:0]  rs_sh;
    reg        rs_pl; reg [4:0] rs_k; reg [15:0] rs_c, rs_n;
    always @(posedge clk) begin
        rs_sh <= {rs_sh[6:0], ls && c_last && !rst};
        if (ls && c_last) begin rs_pl <= c_pl; rs_k <= c_k; rs_c <= c_c; rs_n <= c_nact; end
    end
    wire rdo_busy, rdo_drop;
    wire [15:0] rdo_nd;
    fine_rdo u_rdo (.clk(clk), .rst(rst), .start(rs_sh[7]), .st_plane(rs_pl), .st_k(rs_k), .st_c({16'd0, rs_c}), .st_nfr(rs_n),
        .rd_c(rd_c), .rd_plane(rd_pl), .rd_d(rd_d), .m_axis_tdata(m_axis_tdata), .m_axis_tlast(m_axis_tlast), .m_axis_tvalid(m_axis_tvalid),
        .m_axis_tready(m_axis_tready), .busy(rdo_busy), .n_drop(rdo_nd), .f_drop(rdo_drop));

    // ---- フラグ ----
    always @(posedge clk) begin
        if (rst) begin flags <= 9'd0; n_rec <= 32'd0; end
        else begin
            if (q_ovf) flags[0] <= 1'b1;
            if (|ln_ev_unexp || |ln_ev_miss) flags[1] <= 1'b1;
            if (|ln_ev_halt) flags[2] <= 1'b1;
            if (tw_mis) flags[3] <= 1'b1;
            if (coef_mis) flags[4] <= 1'b1;
            if (rdo_drop) flags[5] <= 1'b1;
            if (inf_empty_err || (inf_push && inf_n == 4'd8)) flags[6] <= 1'b1;
            if (pfb_sat != 16'd0) flags[7] <= 1'b1;
            if (q_ovl) flags[8] <= 1'b1;
            if (rs_sh[7]) n_rec <= n_rec + 32'd1;
        end
    end
endmodule
