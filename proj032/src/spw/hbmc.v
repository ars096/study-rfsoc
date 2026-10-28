// SPDX-License-Identifier: BSD-3-Clause
//
// hbmc — 半帯域 ÷2（複素）の多 ch 版（proj032 E-3）。**ch ごとの値は hb2 と bit 単位で同じ**（同じ項・同じ和の木・同じ丸め）
//
//   hb2 の履歴（シフトレジスタ eh[0..2L−1]・oh[0..L]）を、ch で引く小さな記憶（LUTRAM）に置き換えたもの。
//   組（e, o）は ch の番号を付けて、どの順で来てもよい（同じ ch が続けて来ても、毎クロックでも）。1 クロックに 1 組まで。
//   組が来たクロックに、その ch の履歴を読み（非同期）、1 つずらして書き戻す（同期）。前置加算の項は読んだ値と新しい組から作る。
//   次のクロックに同じ ch が来ても、書き戻しは済んでいる（LUTRAM は同期書き・非同期読み）ので、追い越しは起きない。
//   積と和の木・丸め・飽和は hb2 と同じ（和の木は 2 項ずつ、丸めの +2^(SH−1) は項 0 で足す）。
//
//   ch ごとの「最初の出力」も hb2 と同じ: その ch の 2L 個目の組（n = 2L − 1）で q = 0 が出る。rst で全 ch の数えを 0 に。
//   rst は流れている途中の組も捨てる（hb2 は rst の前のクロックに受けた組を出す。WRST の前に流れを止める使い方では同じ）。
//   履歴の中身は rst で消さない（数えが 2L − 1 に達するまでは出力しないので、古い中身は出てこない）。
//
// 資源: 乗算 2(L + 1)（hb2 と同じ。1 組 / クロック）、履歴の記憶 (2L − 1 + L) 本 × 2W bit × NCH 語（LUTRAM）

`timescale 1ns / 1ps

module hbmc #(
    parameter integer N   = 15,
    parameter integer SH  = 17,
    parameter [18*N-1:0] H = 0,
    parameter integer W   = 24,
    parameter integer NCH = 16,
    parameter integer CW  = 4,       // ch の番号の bit（NCH ≦ 2^CW）
    parameter integer R   = 2,       // 和の木の 1 段の項の数（2・3）
    parameter integer PRE = 1        // 1: 前置加算を DSP の中で（A・D のレジスタ → AD → M。1 クロック遅くなる）/ 0: LUT で（E-3 の 1 回目）
)(
    input  wire                clk,
    input  wire                rst,
    input  wire                in_v,
    input  wire [CW-1:0]       in_ch,
    input  wire signed [W-1:0] e_re, e_im, o_re, o_im,
    output reg                 out_v,
    output reg  [CW-1:0]       out_ch,
    output reg  signed [W-1:0] y_re, y_im,
    output reg                 sat
);
    localparam integer L  = (N + 1) / 4;
    localparam integer PW = W + 1 + 18 + 6;

    function signed [17:0] hc(input integer j);
        hc = H[j*18 +: 18];
    endfunction

    // ---- 入口のレジスタ ----
    reg                v0;
    reg [CW-1:0]       c0;
    reg signed [W-1:0] e0r, e0i, o0r, o0i;
    always @(posedge clk) begin
        v0 <= in_v & ~rst;
        c0 <= in_ch;
        e0r <= e_re; e0i <= e_im; o0r <= o_re; o0i <= o_im;
    end

    // ---- 履歴: 位置 k ごとに NCH 語の記憶。eh[k] = e[n − k]、oh[k] = o[n − k]（n = 今の組）----
    //   読むのは古い eh[0..2L−2]・oh[0..L−1]、新しい履歴は eh'[0] = e、eh'[k] = eh[k − 1]（hb2 のシフトと同じ）
    wire signed [W-1:0] er [0:2*L-1], ei [0:2*L-1];      // 新しい履歴 eh'[k]
    wire signed [W-1:0] orr [0:L], oii [0:L];             // 新しい履歴 oh'[k]
    assign er[0] = e0r;  assign ei[0] = e0i;
    assign orr[0] = o0r; assign oii[0] = o0i;
    genvar g;
    generate
        for (g = 0; g < 2 * L - 1; g = g + 1) begin : ge
            (* ram_style = "distributed" *) reg [2*W-1:0] m [0:NCH-1];
            wire [2*W-1:0] rd = m[c0];
            assign er[g+1] = rd[2*W-1:W];
            assign ei[g+1] = rd[W-1:0];
`ifdef HBMC_POSCTL
            always @(posedge clk) if (v0) m[c0 ^ 1'b1] <= {er[g], ei[g]};   // 陽性対照: 書き戻しの ch をずらす
`else
            always @(posedge clk) if (v0) m[c0] <= {er[g], ei[g]};
`endif
        end
        for (g = 0; g < L; g = g + 1) begin : go
            (* ram_style = "distributed" *) reg [2*W-1:0] m [0:NCH-1];
            wire [2*W-1:0] rd = m[c0];
            assign orr[g+1] = rd[2*W-1:W];
            assign oii[g+1] = rd[W-1:0];
            always @(posedge clk) if (v0) m[c0] <= {orr[g], oii[g]};
        end
    endgenerate

    // ch ごとの組の数（2L − 1 で止める）
    reg [7:0] ncnt [0:NCH-1];
    integer i;
    reg     v1;
    reg [CW-1:0] c1;
    always @(posedge clk) begin
        v1 <= 1'b0;
        if (rst) begin
            for (i = 0; i < NCH; i = i + 1) ncnt[i] <= 8'd0;
        end else if (v0) begin
            if (ncnt[c0] != 2 * L - 1) ncnt[c0] <= ncnt[c0] + 8'd1;
            v1 <= (ncnt[c0] == 2 * L - 1);
        end
        c1 <= c0;
    end

    // 前置加算: pa_i = eh'[2L − 1 − i] + eh'[i]、中心 oh'[L]（hb2 の v1 → v2 の段を、読みと同じクロックに）
    //   PRE = 1 は、読んだ値を A・D のレジスタに取り、AD（前置加算）→ M（積）を DSP の中で（DSP48E2 の前置加算 27 bit に W + 1 が入る）
    reg signed [W:0]    par [0:L-1], pai [0:L-1];
    reg signed [W-1:0]  aar [0:L-1], aai [0:L-1], adr [0:L-1], adi [0:L-1];
    reg signed [W-1:0]  cr, ci, cr2, ci2;
    reg signed [W+18:0] mr [0:L], mi [0:L];
    reg                 v2, v3;
    reg [CW-1:0]        c2, c3;
    generate if (PRE) begin : gp
        always @(posedge clk) begin
            for (i = 0; i < L; i = i + 1) begin
                aar[i] <= er[2*L-1-i]; adr[i] <= er[i];
                aai[i] <= ei[2*L-1-i]; adi[i] <= ei[i];
            end
            cr <= orr[L];  ci <= oii[L];
            v2 <= v1 & ~rst; c2 <= c1;
        end
        always @(posedge clk) begin
            for (i = 0; i < L; i = i + 1) begin
                par[i] <= aar[i] + adr[i];
                pai[i] <= aai[i] + adi[i];
            end
            cr2 <= cr;  ci2 <= ci;
        end
        always @(posedge clk) begin
            for (i = 0; i < L; i = i + 1) begin
                mr[i] <= par[i] * hc(2 * i);
                mi[i] <= pai[i] * hc(2 * i);
            end
            mr[L] <= cr2 * hc(2 * L - 1);
            mi[L] <= ci2 * hc(2 * L - 1);
        end
        always @(posedge clk) begin v3 <= v2 & ~rst; c3 <= c2; end   // v1 は aar と、v2 は par と、v3 は mr とそろう
    end else begin : gl
        always @(posedge clk) begin
            for (i = 0; i < L; i = i + 1) begin
                par[i] <= er[2*L-1-i] + er[i];
                pai[i] <= ei[2*L-1-i] + ei[i];
            end
            cr <= orr[L];  ci <= oii[L];
        end
        always @(posedge clk) begin
            for (i = 0; i < L; i = i + 1) begin
                mr[i] <= par[i] * hc(2 * i);
                mi[i] <= pai[i] * hc(2 * i);
            end
            mr[L] <= cr * hc(2 * L - 1);
            mi[L] <= ci * hc(2 * L - 1);
            v3 <= v1 & ~rst;
            c3 <= c1;
        end
    end endgenerate

    // 和の木: R 項ずつ（R = 2 は hb2 と同じ形、R = 3 は 3 入力の加算で段と LUT を減らす。整数の和なので値は同じ）
    //   別のモジュール hbsum に置き、そこだけ use_dsp = "no"（M-3: 20 bit にすると合成が加算を DSP に寄せた。信号に付けると掛け算まで LUT になった）
    localparam integer T  = L + 1;
    function integer nlv_of(input integer t, input integer r);
        integer c, k; begin c = t; k = 0; while (c > 1) begin c = (c + r - 1) / r; k = k + 1; end nlv_of = (k > 0) ? k : 1; end
    endfunction
    localparam integer NLV = nlv_of(T, R);
    localparam integer MW = W + 19;
    wire [T*MW-1:0] mrf, mif;
    genvar gt;
    generate for (gt = 0; gt < T; gt = gt + 1) begin : pk
        assign mrf[gt*MW +: MW] = mr[gt]; assign mif[gt*MW +: MW] = mi[gt];
    end endgenerate
    wire signed [PW-1:0] sr, si;
    hbsum #(.T(T), .R(R), .MW(MW), .PW(PW), .SH(SH)) u_sr (.clk(clk), .m(mrf), .s(sr));
    hbsum #(.T(T), .R(R), .MW(MW), .PW(PW), .SH(SH)) u_si (.clk(clk), .m(mif), .s(si));
    reg [NLV:0]         tv;
    reg [CW-1:0]        tc [0:NLV];
    integer lv;
    always @(posedge clk) begin
        tv <= {tv[NLV-1:0], v3 & ~rst};
        tc[0] <= c3;
        for (lv = 1; lv <= NLV; lv = lv + 1) tc[lv] <= tc[lv-1];
    end
    wire                 v4 = tv[NLV];

    wire signed [PW-1:0] rr = sr >>> SH;
    wire signed [PW-1:0] ri = si >>> SH;
    localparam signed [PW-1:0] MX = (1 <<< (W - 1)) - 1;
    localparam signed [PW-1:0] MN = -(1 <<< (W - 1));
    always @(posedge clk) begin
        y_re   <= (rr > MX) ? MX[W-1:0] : (rr < MN) ? MN[W-1:0] : rr[W-1:0];
        y_im   <= (ri > MX) ? MX[W-1:0] : (ri < MN) ? MN[W-1:0] : ri[W-1:0];
        sat    <= v4 & ((rr > MX) | (rr < MN) | (ri > MX) | (ri < MN));
        out_v  <= v4 & ~rst;
        out_ch <= tc[NLV];
    end
endmodule

// hbsum — hbmc の和の木（T 項 → 1、R 項ずつ、段ごとにレジスタ。丸めの +2^(SH−1) は項 0 で足す）。LUT で作る
(* use_dsp = "no" *)
module hbsum #(
    parameter integer T = 5, parameter integer R = 3, parameter integer MW = 43, parameter integer PW = 49, parameter integer SH = 17
)(
    input  wire                 clk,
    input  wire [T*MW-1:0]      m,
    output wire signed [PW-1:0] s
);
    function integer nlv_of(input integer t, input integer r);
        integer c, k; begin c = t; k = 0; while (c > 1) begin c = (c + r - 1) / r; k = k + 1; end nlv_of = (k > 0) ? k : 1; end
    endfunction
    localparam integer NLV = nlv_of(T, R);
    function integer cnt_at(input integer lv);
        integer c, k; begin c = T; for (k = 0; k < lv; k = k + 1) c = (c + R - 1) / R; cnt_at = c; end
    endfunction
    localparam signed [PW-1:0] RND = 1 <<< (SH - 1);
    reg signed [PW-1:0] tr [0:(NLV+1)*T-1];
    reg signed [PW-1:0] ar;
    integer lv, n, j;
    always @(posedge clk) begin
        for (n = 0; n < T; n = n + 1)
            tr[n] <= (n == 0) ? $signed(m[n*MW +: MW]) + RND : $signed(m[n*MW +: MW]);
        for (lv = 0; lv < NLV; lv = lv + 1)
            for (n = 0; n < T; n = n + 1)
                if (R * n < cnt_at(lv)) begin
                    ar = 0;
                    for (j = 0; j < R; j = j + 1)
                        if (R * n + j < cnt_at(lv)) ar = ar + tr[lv*T + R*n + j];
                    tr[(lv+1)*T + n] <= ar;
                end
    end
    assign s = tr[NLV*T];
endmodule
