// SPDX-License-Identifier: BSD-3-Clause
//
// wide_chain — SAM45-Wide の鎖の後半（proj023 手順 2c-1）: レーン FFT の出口 → ひねり係数 → 16 点 DFT → SHIFT・飽和 → 電力 → 束ね
//
// 仕様（sim/check_wide.py の chain_int ＋ bin_power と bit 単位で同じ）:
//   V[p] = round(Y[p] · W_32768^(p·k1) / 2^17)            （cmul、SH = 17 = 16 + D。Y 26 bit → V 25 bit）
//   Z[k2] = dft16(V)、k2 = 0..7                          （spec_core と同じ dft16。U 27・Z 29 bit）
//   q = sat18(Z >>> SHIFT)、p = q_re² + q_im²（37 bit）     細かい ch c = k1 + 2048·k2
//   束ね: 束ねた ch j = Σ_{b<B} p[B·j + b]、B = 2^LB（LB = 0・1・2）。c の続く B 個は**同じ銀行 k2 の続く B クロック**に出る
//   （2048 は B で割り切れるので、束ねは銀行をまたがない）。束ねた ch は銀行 k2 の中の番号 jb = k1 >> LB、全体の番号 j = jb + (2048 / B)·k2
//
// 入力はレーン FFT（IP）の出口。16 レーンが同じクロックに同じ k1 を出す（realtime・自然順。spec_core と同じ前提）。
// **ひねり係数は外の wide_tw_rom（4 ADC で 1 つ）から**: tw_addr（= S0 の k1）で引いたものが 2 クロック後（S2）に tw・tw_k1 で届く。
// tw_k1 と自分の k1 を比べて、違えば tw_mis（粘着、rst で消す）。
//
// SHIFT・LB は静的（コアが RUN・WRST の時点で取り込んだ値を与える）。
//
// ---- 段（spec_core の S 番号と同じ）----
//   S0 入力を受ける / S2 ひねり係数が届く / S6 V / S12 Z / S13 Q（飽和）/ S14 a / S15 積 / S16 電力 / S17 束ねの出口
//   出口: pb（8 銀行 × 39 bit）・pb_v（束ねの最後のクロックだけ 1）・pb_jb・pb_sat（その束の飽和の数 = 飽和した (ch, クロック) の数）
//   レイテンシ（入力 → pb_v）= 17 ＋ (B − 1)
//
// -DBIN_SKEW: 束ねの区切りを 1 ずらす（陽性対照。落ちるべき）

`timescale 1ns / 1ps

module wide_chain #(
    parameter integer YW = 26,
    parameter integer VW = 25,
    parameter integer UW = 27,
    parameter integer ZW = 29,
    parameter integer QW = 18,
    parameter integer PW = 37,
    parameter integer BW = 39
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [16*YW-1:0]  y_re,          // レーン p が [YW·p +: YW]
    input  wire [16*YW-1:0]  y_im,
    input  wire [10:0]       y_k1,
    input  wire              y_v,
    output wire [10:0]       tw_addr,       // 共有の wide_tw_rom へ（S0 の k1）
    input  wire [575:0]      tw,            // 2 クロック後
    input  wire [10:0]       tw_k1,
    input  wire [3:0]        shift,
    input  wire [1:0]        lb,            // log2 B（0・1・2）
    output reg  [8*BW-1:0]   pb,            // 銀行 k2 が [BW·k2 +: BW]
    output reg               pb_v,
    output reg  [10:0]       pb_jb,
    output reg  [5:0]        pb_sat,
    output reg               tw_mis
);
    localparam integer NL = 16, NB = 8;
    localparam integer S_V = 6, S_Z = 12, S_Q = 13, S_P = 16;

    // ---- タグの遅延線 {v, k1}。[0] = S0 ----
    reg [11:0] tag [0:S_P];
    integer ti;
    always @(posedge clk) begin
        if (rst) for (ti = 0; ti <= S_P; ti = ti + 1) tag[ti] <= 12'd0;
        else begin
            tag[0] <= {y_v, y_k1};
            for (ti = 1; ti <= S_P; ti = ti + 1) tag[ti] <= tag[ti-1];
        end
    end
    assign tw_addr = tag[0][10:0];

    // ---- S0 → S2 ----
    reg [16*YW-1:0] yr0, yi0, yr1, yi1, yr2, yi2;
    always @(posedge clk) begin
        yr0 <= y_re; yi0 <= y_im;
        yr1 <= yr0;  yi1 <= yi0;
        yr2 <= yr1;  yi2 <= yi1;
    end
    always @(posedge clk) begin
        if (rst) tw_mis <= 1'b0;
        else if (tag[2][11] && tw_k1 != tag[2][10:0]) tw_mis <= 1'b1;
    end

    // ---- ひねり係数（S2 → S6）----
    wire [16*VW-1:0] v_re, v_im;
    genvar p;
    generate
        for (p = 0; p < NL; p = p + 1) begin : g_tw
            cmul #(.AW(YW), .OW(VW), .SH(17)) u_mul (
                .clk(clk),
                .a_re(yr2[p*YW +: YW]), .a_im(yi2[p*YW +: YW]),
                .w_re(tw[36*p +: 18]),  .w_im(tw[36*p + 18 +: 18]),
                .y_re(v_re[p*VW +: VW]), .y_im(v_im[p*VW +: VW])
            );
        end
    endgenerate

    // ---- 16 点 DFT（S6 → S12）----
    wire [NB*ZW-1:0] z_re, z_im;
    dft16 #(.VW(VW), .UW(UW), .ZW(ZW)) u_dft (.clk(clk), .v_re(v_re), .v_im(v_im), .z_re(z_re), .z_im(z_im));

    // ---- SHIFT と飽和（S12 → S13）。spec_core と同じ ----
    localparam signed [ZW-1:0] QMAX =  (1 <<< (QW-1)) - 1;
    localparam signed [ZW-1:0] QMIN = -(1 <<< (QW-1));
    function [QW:0] sat;
        input signed [ZW-1:0] z;
        input [3:0]           sh;
        reg   signed [ZW-1:0] t;
        begin
            t = z >>> sh;
            if (t > QMAX)      sat = {1'b1, QMAX[QW-1:0]};
            else if (t < QMIN) sat = {1'b1, QMIN[QW-1:0]};
            else               sat = {1'b0, t[QW-1:0]};
        end
    endfunction
    reg [NB*QW-1:0] q_re, q_im;
    reg [NB-1:0]    q_sat;
    reg [QW:0]      sr, si;
    integer bi;
    always @(posedge clk) begin
        for (bi = 0; bi < NB; bi = bi + 1) begin
            sr = sat(z_re[bi*ZW +: ZW], shift);
            si = sat(z_im[bi*ZW +: ZW], shift);
            q_re[bi*QW +: QW] <= sr[QW-1:0];
            q_im[bi*QW +: QW] <= si[QW-1:0];
            q_sat[bi]         <= sr[QW] | si[QW];
        end
    end
    // 飽和の数（S13 → S16 に運ぶ）
    reg [3:0] satn, sat14, sat15, sat16;
    integer ci;
    always @* begin
        satn = 4'd0;
        for (ci = 0; ci < NB; ci = ci + 1) satn = satn + {3'd0, q_sat[ci]};
    end
    always @(posedge clk) begin
        sat14 <= tag[S_Q][11] ? satn : 4'd0;
        sat15 <= sat14;
        sat16 <= sat15;
    end

    // ---- 電力（S13 → S16）----
    wire [NB*PW-1:0] pw;
    genvar j;
    generate
        for (j = 0; j < NB; j = j + 1) begin : g_pw
            reg signed [QW-1:0]   a_re, a_im;
            reg signed [2*QW-1:0] m_re, m_im;
            reg [PW-1:0]          pwr;
            always @(posedge clk) begin
                a_re <= q_re[j*QW +: QW];
                a_im <= q_im[j*QW +: QW];
                m_re <= a_re * a_re;
                m_im <= a_im * a_im;
                pwr  <= m_re + m_im;
            end
            assign pw[j*PW +: PW] = pwr;
        end
    endgenerate

    // ---- 束ね（S16 → S17）----
    wire [10:0] k16  = tag[S_P][10:0];
    wire [1:0]  msk  = (lb == 2'd2) ? 2'd3 : (lb == 2'd1) ? 2'd1 : 2'd0;
`ifdef BIN_SKEW
    wire [1:0]  kk   = k16[1:0] + 2'd1;          // 陽性対照: 区切りを 1 ずらす
`else
    wire [1:0]  kk   = k16[1:0];
`endif
    wire        g_first = ((kk & msk) == 2'd0);
    wire        g_last  = ((kk & msk) == msk);
    reg  [8*BW-1:0] acc;
    reg  [5:0]      acc_sat;
    reg  [8*BW-1:0] nxt;
    integer bk;
    always @* begin
        for (bk = 0; bk < NB; bk = bk + 1)
            nxt[bk*BW +: BW] = (g_first ? {BW{1'b0}} : acc[bk*BW +: BW]) + {{(BW-PW){1'b0}}, pw[bk*PW +: PW]};
    end
    always @(posedge clk) begin
        if (rst) begin
            pb_v <= 1'b0; acc <= {8*BW{1'b0}}; acc_sat <= 6'd0;
        end else begin
            pb_v <= tag[S_P][11] && g_last;
            if (tag[S_P][11]) begin
                acc     <= nxt;
                acc_sat <= (g_first ? 6'd0 : acc_sat) + {2'd0, sat16};
                pb      <= nxt;
                pb_jb   <= k16 >> lb;
                pb_sat  <= (g_first ? 6'd0 : acc_sat) + {2'd0, sat16};
            end
        end
    end
endmodule
