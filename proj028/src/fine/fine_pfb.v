// SPDX-License-Identifier: BSD-3-Clause
//
// fine_pfb — 細かい PFB（T = 4、131072 点 = 1 フレーム 8192 ビート、複素の入力）。proj028 F-1
// proj024 の g21_pfb（包み）と g21_pfb_core（cbf0674）を写して 1 つにし、直したもの:
//   - 入力は荒い段の 8 bit の複素（レーン p が [16p +: 16] = {im, re}）。実部・虚部は同じ係数（fine_coef）
//   - m（フレームの中のビート）はここで数える。**s_first（ch の流れの最初の拍）で m と「埋まったフレームの数」fr を 0 に戻す**
//     （ch ごとに履歴を空にする。末尾の 3 フレームで履歴が埋まり、本体のフレームは y_fr = 3）
//   - y = sat15((Σ_t c·x + 2^11) >>> 12)（端数を 4 bit 残す）。タップ t（0 = いちばん古い）は fr ≧ 3 − t のときだけ（ほかは履歴 0）
// 段は g21_pfb_core と同じ（入力 → y_v が LAT 8、係数は fine_coef の LAT 6 に合わせて入力を 4 拍遅らせる。F-5b で係数の段を 1 つ足した）
// -DNO_CH_RESET: s_first で fr を戻さない（陽性対照: 前の ch の履歴を拾う）
// valid の段はどれもリセットで 0 にする（F-4 の sim: 段の数がリセットの長さより多く、明けた後に不定の y_v が残って下流の数えを壊した）

`timescale 1ns / 1ps

module fine_pfb #(
    parameter LO_FILE = "fine_coef_lo.hex",
    parameter HI_FILE = "fine_coef_hi.hex"
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [255:0]      s_tdata,
    input  wire              s_tvalid,
    input  wire              s_first,
    output reg  [16*15-1:0]  y_re,
    output reg  [16*15-1:0]  y_im,
    output reg               y_v,
    output reg  [12:0]       y_m,
    output reg               y_first,
    output reg  [1:0]        y_fr,
    output reg  [15:0]       sat_cnt,
    output reg               coef_mis
);
    localparam integer XW = 8, CW = 18, SHY = 12, YW = 15;
    localparam integer HW = 16 * XW;        // 128（1 成分）
    localparam integer PW = XW + CW;        // 26
    localparam integer AW = PW + 2;         // 28
    localparam integer DLY = 4;

    // ---- m と fr（ch の頭で戻す）----
    reg [12:0] m_cnt;
    reg [1:0]  fr;
    wire [12:0] m_in  = s_first ? 13'd0 : m_cnt;
`ifdef NO_CH_RESET
    wire [1:0]  fr_in = fr;
`else
    wire [1:0]  fr_in = s_first ? 2'd0 : fr;
`endif
    always @(posedge clk) begin
        if (rst) begin m_cnt <= 13'd0; fr <= 2'd0; end
        else if (s_tvalid) begin
            m_cnt <= m_in + 13'd1;
            fr <= (m_in == 13'd8191 && fr_in != 2'd3) ? fr_in + 2'd1 : fr_in;
        end
    end

    wire [1151:0] coef;
    wire [12:0]   coef_m;
    wire          coef_v;
    fine_coef #(.LO_FILE(LO_FILE), .HI_FILE(HI_FILE)) u_coef (
        .clk(clk), .addr(m_in), .addr_v(s_tvalid), .coef(coef), .m_out(coef_m), .v_out(coef_v)
    );

    // ---- 入力を係数に合わせて遅らせる ----
    reg [255:0] dd [0:DLY-1];
    reg [12:0]  dm [0:DLY-1];
    reg [1:0]   df [0:DLY-1];
    reg         dv [0:DLY-1];
    integer i, p, t;
    always @(posedge clk) begin
        dd[0] <= s_tdata; dm[0] <= m_in; df[0] <= fr_in; dv[0] <= s_tvalid & ~rst;
        for (i = 1; i < DLY; i = i + 1) begin dd[i] <= dd[i-1]; dm[i] <= dm[i-1]; df[i] <= df[i-1]; dv[i] <= dv[i-1] & ~rst; end
    end
    wire [255:0] s_d = dd[DLY-1];
    wire [12:0]  s_m = dm[DLY-1];
    wire [1:0]   s_f = df[DLY-1];
    wire         s_v = dv[DLY-1];

    // ---- 0: 入力（実部・虚部に分ける）----
    reg [HW-1:0] xr1, xi1, xr2, xi2;
    reg [12:0]   m1, m2;
    reg          v1, v2;
    reg [1:0]    f1, f2;
    always @(posedge clk) begin
        for (p = 0; p < 16; p = p + 1) begin
            xr1[XW*p +: XW] <= s_d[16*p +: 8];
            xi1[XW*p +: XW] <= s_d[16*p + 8 +: 8];
        end
        m1 <= s_m; v1 <= s_v & ~rst; f1 <= s_f;
        xr2 <= xr1; xi2 <= xi1; m2 <= m1; v2 <= v1 & ~rst; f2 <= f1;
    end

    // ---- 1・2: 履歴（{h2, h1, h0} × 実部・虚部）----
    (* ram_style = "ultra" *) reg [6*HW-1:0] hmem [0:8191];
    reg [6*HW-1:0] hr1, hr2;
    always @(posedge clk) begin
        hr1 <= hmem[s_m];
        hr2 <= hr1;
        if (v2) hmem[m2] <= {hr2[3*HW +: 2*HW], xi2, hr2[0 +: 2*HW], xr2};   // 実部 [0 +: 3HW]、虚部 [3HW +: 3HW]
    end

    always @(posedge clk) begin
        if (rst) coef_mis <= 1'b0;
        else if (v2 && coef_m != m2) coef_mis <= 1'b1;
    end

    // ---- 3: タップの選択 ----
    reg signed [XW-1:0] xa [0:63];          // 実部 [4p + t]
    reg signed [XW-1:0] xb [0:63];          // 虚部
    reg signed [CW-1:0] ca [0:63];
    reg        v3; reg [12:0] m3; reg [1:0] f3;
    always @(posedge clk) begin
        for (p = 0; p < 16; p = p + 1) begin
            xa[4*p + 3] <= xr2[XW*p +: XW];
            xa[4*p + 2] <= (f2 >= 2'd1) ? hr2[0*HW + XW*p +: XW] : {XW{1'b0}};
            xa[4*p + 1] <= (f2 >= 2'd2) ? hr2[1*HW + XW*p +: XW] : {XW{1'b0}};
            xa[4*p + 0] <= (f2 >= 2'd3) ? hr2[2*HW + XW*p +: XW] : {XW{1'b0}};
            xb[4*p + 3] <= xi2[XW*p +: XW];
            xb[4*p + 2] <= (f2 >= 2'd1) ? hr2[3*HW + XW*p +: XW] : {XW{1'b0}};
            xb[4*p + 1] <= (f2 >= 2'd2) ? hr2[4*HW + XW*p +: XW] : {XW{1'b0}};
            xb[4*p + 0] <= (f2 >= 2'd3) ? hr2[5*HW + XW*p +: XW] : {XW{1'b0}};
            for (t = 0; t < 4; t = t + 1) ca[4*p + t] <= coef[72*p + 18*t +: CW];
        end
        v3 <= v2 & ~rst; m3 <= m2; f3 <= f2;
    end

    // ---- 4: 積 / 5: 2 つずつ / 6: 和 ----
    reg signed [PW-1:0] pra [0:63], prb [0:63];
    reg signed [PW:0]   s2a [0:31], s2b [0:31];
    reg signed [AW-1:0] s4a [0:15], s4b [0:15];
    reg        v4, v5, v6; reg [12:0] m4, m5, m6; reg [1:0] f4, f5, f6;
    always @(posedge clk) begin
        for (p = 0; p < 64; p = p + 1) begin pra[p] <= ca[p] * xa[p]; prb[p] <= ca[p] * xb[p]; end
        for (p = 0; p < 32; p = p + 1) begin s2a[p] <= pra[2*p] + pra[2*p + 1]; s2b[p] <= prb[2*p] + prb[2*p + 1]; end
        for (p = 0; p < 16; p = p + 1) begin s4a[p] <= s2a[2*p] + s2a[2*p + 1]; s4b[p] <= s2b[2*p] + s2b[2*p + 1]; end
        v4 <= v3 & ~rst; m4 <= m3; f4 <= f3;
        v5 <= v4 & ~rst; m5 <= m4; f5 <= f4;
        v6 <= v5 & ~rst; m6 <= m5; f6 <= f5;
    end

    // ---- 7: 丸め・飽和 ----
    localparam signed [AW-SHY-1:0] YMAX = (1 <<< (YW - 1)) - 1;
    localparam signed [AW-SHY-1:0] YMIN = -(1 <<< (YW - 1));
    wire [31:0] sat6;
    wire [16*YW-1:0] ya6, yb6;
    genvar g;
    generate
        for (g = 0; g < 16; g = g + 1) begin : g_rnd
            wire signed [AW-1:0]     ra = s4a[g] + $signed({{(AW-SHY){1'b0}}, 1'b1, {(SHY-1){1'b0}}});
            wire signed [AW-1:0]     rb = s4b[g] + $signed({{(AW-SHY){1'b0}}, 1'b1, {(SHY-1){1'b0}}});
            wire signed [AW-SHY-1:0] qa = ra >>> SHY;
            wire signed [AW-SHY-1:0] qb = rb >>> SHY;
            assign sat6[g]      = (qa > YMAX) || (qa < YMIN);
            assign sat6[16 + g] = (qb > YMAX) || (qb < YMIN);
            assign ya6[YW*g +: YW] = (qa > YMAX) ? YMAX[YW-1:0] : (qa < YMIN) ? YMIN[YW-1:0] : qa[YW-1:0];
            assign yb6[YW*g +: YW] = (qb > YMAX) ? YMAX[YW-1:0] : (qb < YMIN) ? YMIN[YW-1:0] : qb[YW-1:0];
        end
    endgenerate
    reg [5:0] ns;
    integer k;
    always @(*) begin
        ns = 6'd0;
        for (k = 0; k < 32; k = k + 1) ns = ns + {5'd0, sat6[k]};
    end
    always @(posedge clk) begin
        y_re <= ya6; y_im <= yb6;
        y_v <= v6 & ~rst; y_m <= m6; y_first <= v6 && m6 == 13'd0; y_fr <= f6;
        if (rst) sat_cnt <= 16'd0;
        else if (v6 && ns != 6'd0) sat_cnt <= (sat_cnt > 16'hFFFF - {10'd0, ns}) ? 16'hFFFF : sat_cnt + {10'd0, ns};
    end
endmodule
