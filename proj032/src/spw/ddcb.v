// SPDX-License-Identifier: BSD-3-Clause
//
// ddcb — 窓の頭の後ろ（light 2〜4 段目 ＋ final）を全窓で共有する（proj032 E-3）。1 ADC ぶん、窓の頭 H 本（≦ 16）
//
// 窓 w の値は、窓ごとに hb2 を縦に並べた形（Fine の ddc_core の light 2 段目以降と final）と bit 単位で同じ:
//   頭の出口 x_w（NS ≧ 2 は light 1 段目の後 128 MS/s、NS = 1 は light 1 段目を通らない 256 MS/s）
//   → light 2 段目 → 3 段目 → 4 段目 → final。final の入口は NS で選ぶ: NS 1・2 は x_w、3 は light 2 段目の出口、4 は 3 段目、5 は 4 段目
//   （NS 1..5 = 幅 128・64・32・16・8 MHz）。組（偶 e, 奇 o）は各段の入口で、rst の後の最初の標本を e として作る（hb2 の約束）
//
// 共有の形（どれも hbmc、1 組 / クロック）:
//   light 2 段目: lane l が頭 4l..4l+3（入口は 1 頭 0.25 組 / クロック → 4 頭で 1）
//   light 3 段目: lane m が窓 8m..8m+7（2 段目の lane 2m・2m+1 の出口）、4 段目: lane k が窓 16k..（3 段目の lane 2k・2k+1）
//   **light は NS ≧ 2 のどの窓も全段に通す**（割り当てが静的になる。狭くない窓の 3・4 段目は捨てるだけ）。H 14 で lane 4 + 2 + 1 = 7
//   final: NF 本の lane。窓 w は cfg_fl[w] の lane（PS が WRST で、lane ごとの幅の和 ≦ 256 MHz になるよう決める）
//   final の入口は窓ごとに 4 組まで待たせ、lane は「NS の小さい（速い）窓から先に」選ぶ（周期が 2 のべきなので、和 ≦ 1 組 / クロックなら間に合う）
//
// 見張り（粘着、rst で消す）: flags[0] light の入口の溜めが溢れた / [1] final の入口の待ち（窓ごとに 4 組）が溢れた / [2] hbmc の飽和

`timescale 1ns / 1ps

module ddcb #(
    parameter integer H  = 14,
    parameter integer NF = 3,
    parameter integer W  = 24,
    parameter integer R  = 3            // hbmc の和の木
)(
    input  wire                 clk,
    input  wire                 rst,
    input  wire [H-1:0]         x_v,
    input  wire [H*W-1:0]       x_re, x_im,
    input  wire [H*3-1:0]       cfg_ns,     // 窓ごとの NS（1..5）。RUN の間は変えない
    input  wire [H*2-1:0]       cfg_fl,     // 窓ごとの final の lane
    output wire [NF-1:0]        y_v,
    output wire [NF*4-1:0]      y_ch,       // 窓の番号
    output wire [NF*W-1:0]      y_re, y_im,
    output reg  [2:0]           flags
);
`include "hb_coef.vh"
    localparam integer N2 = (H + 3) / 4, N3 = (H + 7) / 8, N4 = (H + 15) / 16;

    // ======== light 2 段目: 頭ごとに組にし、4 頭を 1 lane へ（固定の時分割）========
    //   NS = 1（128 MHz）の窓は light を通らない（light 1 段目も通らず 256 MS/s で来るので、light 2 段目に入れると lane が溢れる）
    //   頭の出口は 2 クロックに 1 標本以下 → 組は 4 クロックに 1 つ以下。組の入れ物（pd）を枠にし、lane は 2 bit の数え（枠の番号）で
    //   4 クロックに 1 回ずつ各枠を見て、埋まっていれば送り出す。組が埋まってから 4 クロック以内に必ず見に来るので、次の組が来る前に空く
    //   （E-3: FIFO と選びの論理を除いた。前提が破れたら flags[0]）
    integer i, j, k;
    genvar g, q2;
    reg  [1:0]       tdm;                          // 枠の番号（全 lane 共通）
    always @(posedge clk) tdm <= rst ? 2'd0 : tdm + 2'd1;
    wire [H-1:0]     hfull, hov;
    wire [4*W-1:0]   hpd [0:H-1];
    generate for (g = 0; g < H; g = g + 1) begin : hd
        wire        lv = x_v[g] && cfg_ns[g*3 +: 3] != 3'd1;
        wire        take = hfull[g] && tdm == (g % 4);
        reg         have, full, ov;
        reg [2*W-1:0] eh;
        reg [4*W-1:0] pd;
        always @(posedge clk) begin
            ov <= 1'b0;
            if (rst) begin have <= 1'b0; full <= 1'b0; end
            else begin
                if (take) full <= 1'b0;
                if (lv) begin
                    if (!have) eh <= {x_re[g*W +: W], x_im[g*W +: W]};
                    else begin
                        pd <= {eh, x_re[g*W +: W], x_im[g*W +: W]}; full <= 1'b1;
                        if (full && !take) ov <= 1'b1;
                    end
                    have <= ~have;
                end
            end
        end
        assign hfull[g] = full; assign hpd[g] = pd; assign hov[g] = ov;
    end endgenerate

    reg  [N2-1:0]  l2_v;
    reg  [1:0]     l2_ch [0:N2-1];
    reg  [W-1:0]   l2_er [0:N2-1], l2_ei [0:N2-1], l2_or [0:N2-1], l2_oi [0:N2-1];
    generate for (g = 0; g < N2; g = g + 1) begin : a2
        wire sel_ok = (4*g + tdm < H) && hfull[4*g + tdm];
        always @(posedge clk) begin
            l2_v[g]  <= sel_ok & ~rst;
            l2_ch[g] <= tdm;
            {l2_er[g], l2_ei[g], l2_or[g], l2_oi[g]} <= hpd[4*g + tdm];
        end
    end endgenerate
    wire ovf_l = |hov;

    // ======== lane の出口 → 次の段（窓ごとに組にして、2 つの lane を 1 つへ）========
    wire [N2-1:0]  o2_v;  wire [1:0] o2_ch [0:N2-1];  wire [W-1:0] o2_r [0:N2-1], o2_i [0:N2-1];
    wire [N3-1:0]  o3_v;  wire [2:0] o3_ch [0:N3-1];  wire [W-1:0] o3_r [0:N3-1], o3_i [0:N3-1];
    wire [N4-1:0]  o4_v;  wire [3:0] o4_ch [0:N4-1];  wire [W-1:0] o4_r [0:N4-1], o4_i [0:N4-1];
    wire [N2+N3+N4-1:0] lsat;
    wire [N3+N4-1:0]    lnx_ovf;
    generate for (g = 0; g < N2; g = g + 1) begin : ln2
        hbmc #(.N(LIGHT_N), .SH(LIGHT_SH), .H(LIGHT_H), .W(W), .NCH(4), .CW(2), .R(R)) u (
            .clk(clk), .rst(rst), .in_v(l2_v[g]), .in_ch(l2_ch[g]),
            .e_re(l2_er[g]), .e_im(l2_ei[g]), .o_re(l2_or[g]), .o_im(l2_oi[g]),
            .out_v(o2_v[g]), .out_ch(o2_ch[g]), .y_re(o2_r[g]), .y_im(o2_i[g]), .sat(lsat[g]));
    end endgenerate

    // 段 s（3・4）の lane m: 前の段の lane 2m・2m+1 の出口（ch の bit を 1 つ足す）を、ch ごとに組にして、2 段の溜めで 1 つへ
    //   前の段の出口は 1 lane あたり 0.5 標本 / クロック以下 → 組は 0.25 以下。2 本で 0.5 以下なので、溜めは浅くてよい
    generate for (g = 0; g < N3 + N4; g = g + 1) begin : lnx
        localparam integer S3 = (g < N3);
        localparam integer M  = S3 ? g : g - N3;
        localparam integer CI = S3 ? 2 : 3;              // 入口の ch の bit（前の段の lane の）
        localparam integer CO = CI + 1;
        localparam integer NP = S3 ? N2 : N3;            // 前の段の lane の数
        wire          a_v = (2*M < NP)     ? (S3 ? o2_v[2*M]   : o3_v[2*M])   : 1'b0;
        wire          b_v = (2*M + 1 < NP) ? (S3 ? o2_v[2*M+1] : o3_v[2*M+1]) : 1'b0;
        wire [CI-1:0] a_c = S3 ? o2_ch[2*M] : o3_ch[2*M];
        wire [CI-1:0] b_c = (2*M + 1 < NP) ? (S3 ? o2_ch[2*M+1] : o3_ch[2*M+1]) : {CI{1'b0}};
        wire [W-1:0]  a_r = S3 ? o2_r[2*M] : o3_r[2*M], a_i = S3 ? o2_i[2*M] : o3_i[2*M];
        wire [W-1:0]  b_r = (2*M + 1 < NP) ? (S3 ? o2_r[2*M+1] : o3_r[2*M+1]) : {W{1'b0}};
        wire [W-1:0]  b_i = (2*M + 1 < NP) ? (S3 ? o2_i[2*M+1] : o3_i[2*M+1]) : {W{1'b0}};
        // 窓ごとの e（2^CO 語）と「e を持っている」
        reg  [2*W-1:0] em [0:(1<<CO)-1];
        reg  [(1<<CO)-1:0] have;
        reg               pav, pbv;
        reg  [CO+4*W-1:0] pa, pb;
        always @(posedge clk) begin
            pav <= 1'b0; pbv <= 1'b0;
            if (rst) have <= 0;
            else begin
                // 組にする（a は窓 0..2^CI−1、b は 2^CI..）
                if (a_v) begin
                    if (!have[{1'b0, a_c}]) em[{1'b0, a_c}] <= {a_r, a_i};
                    else begin pa <= {1'b0, a_c, em[{1'b0, a_c}], a_r, a_i}; pav <= 1'b1; end
                    have[{1'b0, a_c}] <= ~have[{1'b0, a_c}];
                end
                if (b_v) begin
                    if (!have[{1'b1, b_c}]) em[{1'b1, b_c}] <= {b_r, b_i};
                    else begin pb <= {1'b1, b_c, em[{1'b1, b_c}], b_r, b_i}; pbv <= 1'b1; end
                    have[{1'b1, b_c}] <= ~have[{1'b1, b_c}];
                end
            end
        end
        // 溜め: 入口ごとに FIFO（頭がそろって動くので、前の段の lane は窓の数だけ続けて出す。2 本が重なると瞬間は 2 組 / クロック）
        //   2 本を交互に取り出す
        wire [CO+4*W-1:0] qa, qb;
        wire              ea, eb, ova, ovb;
        reg               turn;
        wire              popa = !ea && (eb || !turn);
        wire              popb = !eb && !popa;
        sfifo #(.DW(CO + 4*W), .AW(4)) fa (.clk(clk), .rst(rst), .push(pav), .din(pa), .pop(popa), .dout(qa), .empty(ea), .ovf(ova));
        sfifo #(.DW(CO + 4*W), .AW(4)) fb (.clk(clk), .rst(rst), .push(pbv), .din(pb), .pop(popb), .dout(qb), .empty(eb), .ovf(ovb));
        reg               iv; reg [CO-1:0] ic; reg [W-1:0] ier, iei, ior, ioi;
        reg               ovf;
        always @(posedge clk) begin
            iv  <= (popa | popb) & ~rst;
            {ic, ier, iei, ior, ioi} <= popa ? qa : qb;
            if (rst) turn <= 1'b0; else if (popa | popb) turn <= popa;
            ovf <= ova | ovb;
        end
        assign lnx_ovf[g] = ovf;
        wire [CO-1:0] oc; wire ov; wire [W-1:0] or_, oi_;
        hbmc #(.N(LIGHT_N), .SH(LIGHT_SH), .H(LIGHT_H), .W(W), .NCH(1 << CO), .CW(CO), .R(R)) u (
            .clk(clk), .rst(rst), .in_v(iv), .in_ch(ic),
            .e_re(ier), .e_im(iei), .o_re(ior), .o_im(ioi),
            .out_v(ov), .out_ch(oc), .y_re(or_), .y_im(oi_), .sat(lsat[N2 + g]));
        if (S3) begin : o3
            assign o3_v[M] = ov; assign o3_ch[M] = oc; assign o3_r[M] = or_; assign o3_i[M] = oi_;
        end else begin : o4
            assign o4_v[M] = ov; assign o4_ch[M] = oc; assign o4_r[M] = or_; assign o4_i[M] = oi_;
        end
    end endgenerate

    // ======== final の入口: 窓ごとに NS で選んだ流れを組にし、FIFO（4 組）で待たせる ========
    wire [H-1:0]   fq_e, fq_ov, fpop;
    wire [4*W-1:0] fq_d [0:H-1];
    generate for (g = 0; g < H; g = g + 1) begin : fw
        reg          sv; reg [W-1:0] sr, si;
        always @(posedge clk) begin
            case (cfg_ns[g*3 +: 3])
                3'd3:    begin sv <= o2_v[g/4]  && o2_ch[g/4]  == g % 4;  sr <= o2_r[g/4];  si <= o2_i[g/4];  end
                3'd4:    begin sv <= o3_v[g/8]  && o3_ch[g/8]  == g % 8;  sr <= o3_r[g/8];  si <= o3_i[g/8];  end
                3'd5:    begin sv <= o4_v[g/16] && o4_ch[g/16] == g % 16; sr <= o4_r[g/16]; si <= o4_i[g/16]; end
                default: begin sv <= x_v[g];  sr <= x_re[g*W +: W];  si <= x_im[g*W +: W];  end
            endcase
            if (rst) sv <= 1'b0;
        end
        reg have; reg [2*W-1:0] eh; reg pv; reg [4*W-1:0] pd;
        always @(posedge clk) begin
            pv <= 1'b0;
            if (rst) have <= 1'b0;
            else if (sv) begin
                if (!have) eh <= {sr, si};
                else begin pd <= {eh, sr, si}; pv <= 1'b1; end
                have <= ~have;
            end
        end
        sfifo #(.DW(4*W), .AW(2)) q (.clk(clk), .rst(rst), .push(pv), .din(pd), .pop(fpop[g]), .dout(fq_d[g]), .empty(fq_e[g]), .ovf(fq_ov[g]));
    end endgenerate
    wire ovf_f = |fq_ov;

    // final の lane f: cfg_fl = f で待ちのある窓のうち、NS の小さい窓（同じなら番号の小さい窓）を選ぶ
    wire [NF-1:0]   fsat;
    wire [NF*H-1:0] lpop;
    generate for (g = 0; g < NF; g = g + 1) begin : lnf
        // 設定から作る候補の印（窓 w が この lane で NS = c）はレジスタに置く（RUN の間は変わらない）。
        //   選び: 級（NS 1..5）ごとに「候補 ∧ 空でない」→ 最初の空でない級 → その中の最下位の 1 bit（x & −x）。逐次の比べの鎖を作らない
        reg  [H-1:0] cm [1:5];
        integer w, c;
        always @(posedge clk)
            for (c = 1; c <= 5; c = c + 1)
                for (w = 0; w < H; w = w + 1)
`ifdef DDCB_NOPRI
                    cm[c][w] <= (cfg_fl[w*2 +: 2] == g) && (c == 1);   // 変種: 級を 1 つにまとめる（番号の小さい窓から）
`else
                    cm[c][w] <= (cfg_fl[w*2 +: 2] == g) && (cfg_ns[w*3 +: 3] == c);
`endif
        reg       hold;                              // 陽性対照 DDCB_POSCTL: lane が 2 クロックに 1 回しか受けない → 溢れるはず
        always @(posedge clk) hold <= rst ? 1'b0 : ~hold;
        reg  [H-1:0] rdy, oh;
        reg  [3:0]   best;
        reg          found;
        always @(*) begin
            rdy = {H{1'b0}};
            for (c = 5; c >= 1; c = c - 1)
                if (|(cm[c] & ~fq_e)) rdy = cm[c] & ~fq_e;
`ifdef DDCB_POSCTL
            if (hold) rdy = {H{1'b0}};
`endif
            oh = rdy & (~rdy + 1'b1);
            found = |rdy;
            best = 4'd0;
            for (w = 0; w < H; w = w + 1) if (oh[w]) best = best | w[3:0];
        end
        assign lpop[g*H +: H] = oh;
        reg          iv; reg [3:0] ic; reg [W-1:0] ier, iei, ior, ioi;
        always @(posedge clk) begin
            iv <= found & ~rst;
            ic <= best;
            {ier, iei, ior, ioi} <= fq_d[best];
        end
        hbmc #(.N(FINAL_N), .SH(FINAL_SH), .H(FINAL_H), .W(W), .NCH(16), .CW(4), .R(R)) u (
            .clk(clk), .rst(rst), .in_v(iv), .in_ch(ic),
            .e_re(ier), .e_im(iei), .o_re(ior), .o_im(ioi),
            .out_v(y_v[g]), .out_ch(y_ch[g*4 +: 4]), .y_re(y_re[g*W +: W]), .y_im(y_im[g*W +: W]), .sat(fsat[g]));
    end endgenerate
    // 取り出し: lane ごとの選びを OR（窓はちょうど 1 つの lane に属するので重ならない）
    reg [H-1:0] fpop_r;
    integer f;
    always @(*) begin
        fpop_r = 0;
        for (f = 0; f < NF; f = f + 1) fpop_r = fpop_r | lpop[f*H +: H];
    end
    assign fpop = fpop_r;

    // 見張り
    always @(posedge clk) begin
        if (rst) flags <= 3'd0;
        else begin
            if (ovf_l | (|lnx_ovf)) flags[0] <= 1'b1;
            if (ovf_f) flags[1] <= 1'b1;
            if (|lsat | |fsat) flags[2] <= 1'b1;
        end
    end
endmodule
