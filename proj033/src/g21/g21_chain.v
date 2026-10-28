// SPDX-License-Identifier: BSD-3-Clause
//
// g21_chain — 2G-1 の鎖の後半（proj024 手順 1d）: レーン FFT の出口 → Y の丸め → ひねり係数 → 16 点 DFT → SHIFT・飽和 → 電力
//
// src/common/wide_chain.v（567fda2）を写して直したもの。直したところ:
//   1. Y は 29 bit（16384 点・unscaled・入力 15 bit）。**S1 で下 2 bit を丸める**: Yd = (Y + 2) >>> 2（27 bit、cmul の A ポート。D-7・M-7）
//   2. cmul の SH 17 → **18**（V 25 bit。dft16 は今のまま U 27・Z 29）
//   3. k1 は 14 bit。**ひねり係数は g21_tw（LAT 6）から**: wide_chain は tw が tw_addr の 2 クロック後に届く前提（S2）だったので、
//      段の番号を S_T = TW_LAT 起点にした（S_T = 2 で wide_chain と同じ段）。tw_addr は S0 の k1（TW_EARLY は無い）
//   4. 束ねを外した（2G は束ねも切り出しも無い）。出口は 8 銀行の電力 p（37 bit）・p_v・p_k1・p_sat（そのビートの飽和の数）
// 仕様（model/g21_fixed.py の chain_Y ＋ power と bit 単位で同じ）:
//   Yd = (Y + 2) >>> 2、V[p] = (Yd · w[p][k1] + 2^17) >>> 18、Z[k2] = dft16(V)、q = sat18(Z >>> SHIFT)、p = q_re² + q_im²、ch c = k1 + 16384·k2
// tw_mis: tw_k1 と自分の k1 が S_T で違えば立てる（粘着、rst で消す。M-8・1c の教訓: 番地の 1 ずれは値の比べで見えにくい）。
//
// ---- 段 ----
//   S0 入力 / S1 丸め / … / S_T ひねり係数が届く（TW_LAT 6）/ S_T+4 V / S_T+10 Z / S_T+11 Q（飽和）/ S_T+14 電力 / S_T+15 出口のレジスタ
//   レイテンシ（入力 → p_v）= TW_LAT + 15 = 21
//
// -DCHAIN_TW_LAT_ERR: TW_LAT を 5 にする（ひねり係数が 1 ビートずれる）。陽性対照（tw_mis が立ち、値が違うはず）
// -DCHAIN_NORND: Y を丸めずに切り捨てる（>>> 2 だけ）。陽性対照（bit 単位で違うはず）

`timescale 1ns / 1ps

module g21_chain #(
    parameter integer YW = 29,
    parameter integer DW = 27,           // 丸めた Yd
    parameter integer VW = 25,
    parameter integer UW = 27,
    parameter integer ZW = 29,
    parameter integer QW = 18,
    parameter integer PW = 37,
`ifdef CHAIN_TW_LAT_ERR
    parameter integer TW_LAT = 5
`else
    parameter integer TW_LAT = 6
`endif
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [16*YW-1:0]  y_re,          // レーン p が [YW·p +: YW]
    input  wire [16*YW-1:0]  y_im,
    input  wire [13:0]       y_k1,
    input  wire              y_v,
    output wire [13:0]       tw_addr,       // g21_tw へ（S0 の k1）
    input  wire [575:0]      tw,            // TW_LAT クロック後
    input  wire [13:0]       tw_k1,
    input  wire [3:0]        shift,
    output reg  [8*PW-1:0]   p,             // 銀行 k2 が [PW·k2 +: PW]
    output reg               p_v,
    output reg  [13:0]       p_k1,
    output reg  [3:0]        p_sat,
    output reg               tw_mis
);
    localparam integer NL = 16, NB = 8;
    localparam integer S_T = TW_LAT, S_V = S_T + 4, S_Z = S_V + 6, S_Q = S_Z + 1, S_P = S_Q + 3;

    // ---- タグの遅延線 {v, k1}。[0] = S0 ----
    reg [14:0] tag [0:S_P];
    integer ti;
    always @(posedge clk) begin
        if (rst) for (ti = 0; ti <= S_P; ti = ti + 1) tag[ti] <= 15'd0;
        else begin
            tag[0] <= {y_v, y_k1};
            for (ti = 1; ti <= S_P; ti = ti + 1) tag[ti] <= tag[ti-1];
        end
    end
    assign tw_addr = tag[0][13:0];

    // ---- S0 → S1（丸め）→ S_T ----
    reg [16*YW-1:0] yr0, yi0;
    reg [16*DW-1:0] yd [1:S_T];
    reg [16*DW-1:0] yq [1:S_T];
    integer lp, si;
    reg signed [YW-1:0] tr, tq;
    always @(posedge clk) begin
        yr0 <= y_re; yi0 <= y_im;
        for (lp = 0; lp < NL; lp = lp + 1) begin
            tr = $signed(yr0[YW*lp +: YW]);
            tq = $signed(yi0[YW*lp +: YW]);
`ifdef CHAIN_NORND
            yd[1][DW*lp +: DW] <= tr >>> 2;
            yq[1][DW*lp +: DW] <= tq >>> 2;
`else
            yd[1][DW*lp +: DW] <= (tr + 2) >>> 2;
            yq[1][DW*lp +: DW] <= (tq + 2) >>> 2;
`endif
        end
        for (si = 2; si <= S_T; si = si + 1) begin yd[si] <= yd[si-1]; yq[si] <= yq[si-1]; end
    end
    always @(posedge clk) begin
        if (rst) tw_mis <= 1'b0;
        else if (tag[S_T][14] && tw_k1 != tag[S_T][13:0]) tw_mis <= 1'b1;
    end

    // ---- ひねり係数（S_T → S_V）----
    wire [16*VW-1:0] v_re, v_im;
    genvar g;
    generate
        for (g = 0; g < NL; g = g + 1) begin : g_tw
            cmul #(.AW(DW), .OW(VW), .SH(18)) u_mul (
                .clk(clk),
                .a_re(yd[S_T][g*DW +: DW]), .a_im(yq[S_T][g*DW +: DW]),
                .w_re(tw[36*g +: 18]),       .w_im(tw[36*g + 18 +: 18]),
                .y_re(v_re[g*VW +: VW]),     .y_im(v_im[g*VW +: VW])
            );
        end
    endgenerate

    // ---- 16 点 DFT（S_V → S_Z）----
    wire [NB*ZW-1:0] z_re, z_im;
    dft16 #(.VW(VW), .UW(UW), .ZW(ZW)) u_dft (.clk(clk), .v_re(v_re), .v_im(v_im), .z_re(z_re), .z_im(z_im));

    // ---- SHIFT と飽和（S_Z → S_Q）。wide_chain と同じ ----
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
    reg [QW:0]      sr, sq;
    integer bi;
    always @(posedge clk) begin
        for (bi = 0; bi < NB; bi = bi + 1) begin
            sr = sat(z_re[bi*ZW +: ZW], shift);
            sq = sat(z_im[bi*ZW +: ZW], shift);
            q_re[bi*QW +: QW] <= sr[QW-1:0];
            q_im[bi*QW +: QW] <= sq[QW-1:0];
            q_sat[bi]         <= sr[QW] | sq[QW];
        end
    end
    reg [3:0] satn, sat1, sat2, sat3;
    integer ci;
    always @* begin
        satn = 4'd0;
        for (ci = 0; ci < NB; ci = ci + 1) satn = satn + {3'd0, q_sat[ci]};
    end
    always @(posedge clk) begin
        sat1 <= tag[S_Q][14] ? satn : 4'd0;
        sat2 <= sat1;
        sat3 <= sat2;
    end

    // ---- 電力（S_Q → S_P）----
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

    // ---- 出口（S_P → S_P + 1）----
    always @(posedge clk) begin
        if (rst) p_v <= 1'b0;
        else     p_v <= tag[S_P][14];
        p     <= pw;
        p_k1  <= tag[S_P][13:0];
        p_sat <= sat3;
    end
endmodule
