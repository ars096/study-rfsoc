// SPDX-License-Identifier: BSD-3-Clause
//
// s2_chain — (B) の鎖（proj030 P-2 を proj033 で 2G-1-Fast に）: s2_sep の出口（そろった行 r の 16 レーンの 2Y）→ 3 bit 丸めて 27 bit → ひねり係数 → 16 点 DFT の 16 出口 → SHIFT・飽和
//
// proj030 の s2_chain（proj027 の g24_chain を写して直したもの）を、proj033 で 2G-1-Fast の鎖（proj024 の g21_chain）に合わせた:
//   1. 入口は 2Y（31 bit）。S1 で **下 3 bit を丸める**: a = (2Y + 4) >>> 3（g21_chain の (Y + 2) >>> 2 と同じ目盛り。README の M-1b の (i)）。
//      |2Y| < 2^29 なので a は 27 bit（cmul の A 口）に必ず入る。27 bit の飽和は**起きないはずのことの見張り**として残し、y_sat に出す
//   2. cmul の SH は 18 のまま（g21_chain と同じ。V 25 bit）
//   3. 16 点 DFT は **dft16f**（16 出口。自明な係数は cmul を通さない）。k2 8..15 は共役で行 M − r の銀行 15 − k2（s2_q が振り分ける）
//   4. 電力は作らない（q を出す）。電力は待ち行列の後（s2_q）で 1 拍に 8 個
//   5. 入口は 1 拍に 1 行まで、valid の空きあり（そろった拍だけ）
// 仕様（model/s2_model.py の chain_s2 と bit 単位で同じ）:
//   a = sat27((2Y + 4) >>> 3)、V = (a · w[p][r] + 2^17) >>> 18、Z[k2] = dft16f(V)（k2 = 0..15）、q = sat18(Z >>> SHIFT)（共役にする前の Z）
// tw_mis: tw_k1 と自分の r が S_T で違えば立てる（粘着、rst で消す）
//
// ---- 段 ----
//   S0 入力 / S1 丸めと飽和（g21_chain の丸めの段と同じ位置）/ … / S_T ひねり係数が届く（TW_LAT 6）/ S_T+4 V / S_T+10 Z / S_T+11 Q（出口）
//   レイテンシ（入力 → q_v）= TW_LAT + 11 = 17
//
// -DCHAIN_D2: 丸めを 2 bit にする（V が 2 倍になる）/ -DCHAIN_NORND: 丸めずに切り捨てる（>>> 3 だけ）。どちらも陽性対照（bit 単位で違うはず）

`timescale 1ns / 1ps

module s2_chain #(
    parameter integer IW = 31,           // 入口の 2Y
    parameter integer DW = 27,           // cmul の A 口
    parameter integer VW = 25,
    parameter integer UW = 27,
    parameter integer ZW = 29,
    parameter integer QW = 18,
    parameter integer TW_LAT = 6
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [16*IW-1:0]  y_re,          // レーン p が [IW·p +: IW]
    input  wire [16*IW-1:0]  y_im,
    input  wire [13:0]       y_k,           // 行 r（0..8192）
    input  wire              y_v,
    output wire [13:0]       tw_addr,       // g21_tw へ（S0 の r）
    input  wire [575:0]      tw,            // TW_LAT クロック後
    input  wire [13:0]       tw_k1,
    input  wire [3:0]        shift,
    output reg  [16*QW-1:0]  q_re,          // k2 が [QW·k2 +: QW]
    output reg  [16*QW-1:0]  q_im,
    output reg  [15:0]       q_sat,         // k2 ごとの飽和
    output reg  [13:0]       q_k,
    output reg               q_v,
    output reg               y_sat,         // このビートの丸めた 2Y が 27 bit で飽和した（q と同じ拍。起きないはず）
    output reg               tw_mis
);
    localparam integer NL = 16;
    localparam integer S_T = TW_LAT, S_V = S_T + 4, S_Z = S_V + 6;
    localparam integer SH = 18;
`ifdef CHAIN_D2
    localparam integer RD = 2;
`else
    localparam integer RD = 3;
`endif

    // ---- タグの遅延線 {v, r}。[0] = S0 ----
    reg [14:0] tag [0:S_Z];
    integer ti;
    always @(posedge clk) begin
        if (rst) for (ti = 0; ti <= S_Z; ti = ti + 1) tag[ti] <= 15'd0;
        else begin
            tag[0] <= {y_v, y_k};
            for (ti = 1; ti <= S_Z; ti = ti + 1) tag[ti] <= tag[ti-1];
        end
    end
    assign tw_addr = tag[0][13:0];

    // ---- S0 → S1（丸めて 27 bit に飽和）→ S_T ----
    localparam signed [IW-1:0] DMAX =  (1 <<< (DW-1)) - 1;
    localparam signed [IW-1:0] DMIN = -(1 <<< (DW-1));
    reg [16*IW-1:0] yr0, yi0;
    reg [16*DW-1:0] yd [1:S_T];
    reg [16*DW-1:0] yq [1:S_T];
    reg             ys [1:S_Z];
    integer lp, si;
    reg signed [IW-1:0] tr, tq;
    reg                 any;
    always @(posedge clk) begin
        yr0 <= y_re; yi0 <= y_im;
        any = 1'b0;
        for (lp = 0; lp < NL; lp = lp + 1) begin
            tr = $signed(yr0[IW*lp +: IW]);
            tq = $signed(yi0[IW*lp +: IW]);
`ifdef CHAIN_NORND
            tr = tr >>> RD;
            tq = tq >>> RD;
`else
            tr = (tr + (1 <<< (RD - 1))) >>> RD;
            tq = (tq + (1 <<< (RD - 1))) >>> RD;
`endif
            if (tr > DMAX) begin tr = DMAX; any = 1'b1; end else if (tr < DMIN) begin tr = DMIN; any = 1'b1; end
            if (tq > DMAX) begin tq = DMAX; any = 1'b1; end else if (tq < DMIN) begin tq = DMIN; any = 1'b1; end
            yd[1][DW*lp +: DW] <= tr[DW-1:0];
            yq[1][DW*lp +: DW] <= tq[DW-1:0];
        end
        ys[1] <= any;
        for (si = 2; si <= S_T; si = si + 1) begin yd[si] <= yd[si-1]; yq[si] <= yq[si-1]; end
        for (si = 2; si <= S_Z; si = si + 1) ys[si] <= ys[si-1];
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
            cmul #(.AW(DW), .OW(VW), .SH(SH)) u_mul (
                .clk(clk),
                .a_re(yd[S_T][g*DW +: DW]), .a_im(yq[S_T][g*DW +: DW]),
                .w_re(tw[36*g +: 18]),       .w_im(tw[36*g + 18 +: 18]),
                .y_re(v_re[g*VW +: VW]),     .y_im(v_im[g*VW +: VW])
            );
        end
    endgenerate

    // ---- 16 点 DFT、16 出口（S_V → S_Z）----
    wire [16*ZW-1:0] z_re, z_im;
    dft16f #(.VW(VW), .UW(UW), .ZW(ZW)) u_dft (.clk(clk), .z_re(v_re), .z_im(v_im), .y_re(z_re), .y_im(z_im));

    // ---- SHIFT と飽和（S_Z → 出口）。g21_chain と同じ ----
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
    reg [QW:0] sr, sq;
    integer bi;
    always @(posedge clk) begin
        for (bi = 0; bi < 16; bi = bi + 1) begin
            sr = sat(z_re[bi*ZW +: ZW], shift);
            sq = sat(z_im[bi*ZW +: ZW], shift);
            q_re[bi*QW +: QW] <= sr[QW-1:0];
            q_im[bi*QW +: QW] <= sq[QW-1:0];
            q_sat[bi]         <= sr[QW] | sq[QW];
        end
        if (rst) q_v <= 1'b0;
        else     q_v <= tag[S_Z][14];
        q_k   <= tag[S_Z][13:0];
        y_sat <= tag[S_Z][14] & ys[S_Z];
    end
endmodule
