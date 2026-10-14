// SPDX-License-Identifier: BSD-3-Clause
//
// cmul — 複素乗算 y = round(a · w / 2^SH)。w は 18 bit 符号付き・2^16 = 1.0。SH は既定 16（proj023: SAM45-Wide のひねり係数は SH 17 = 16 + D）
//
// レイテンシは **4 クロック固定**（valid を持たない。呼ぶ側が同じ段数の遅延線でタグを運ぶ）。
//   1: 入力を受ける（DSP の A/B レジスタ）
//   2: 4 つの積（M レジスタ）
//   3: 和と差 + 丸めの定数 2^15（P レジスタ）
//   4: 算術右シフト SH で OW bit に切り詰める
//
// **|w| ≦ 1 なので |y| ≦ |a|。**成分の最大値は √2 倍になりうるので、OW は
// 呼ぶ側で「成分 ≦ |a| の上限」から決めること（spec_core.v の冒頭に理由がある）。
// AW ≦ 27 なら積 1 つが DSP48E2（27 × 18）1 個に収まる。

`timescale 1ns / 1ps

module cmul #(
    parameter integer AW = 24,
    parameter integer OW = 25,
    parameter integer SH = 16      // proj023: 既定 16 のままなら今までと bit 単位で同じ
)(
    input  wire                 clk,
    input  wire signed [AW-1:0] a_re,
    input  wire signed [AW-1:0] a_im,
    input  wire signed [17:0]   w_re,
    input  wire signed [17:0]   w_im,
    output reg  signed [OW-1:0] y_re,
    output reg  signed [OW-1:0] y_im
);
    localparam integer PW = AW + 18;

    reg signed [AW-1:0] ar, ai;
    reg signed [17:0]   wr, wi;
    reg signed [PW-1:0] m_rr, m_ii, m_ri, m_ir;
    reg signed [PW:0]   s_re, s_im;

    always @(posedge clk) begin
        ar <= a_re;  ai <= a_im;
        wr <= w_re;  wi <= w_im;

        m_rr <= ar * wr;
        m_ii <= ai * wi;
        m_ri <= ar * wi;
        m_ir <= ai * wr;

        s_re <= m_rr - m_ii + (1 <<< (SH - 1));
        s_im <= m_ri + m_ir + (1 <<< (SH - 1));

        y_re <= s_re >>> SH;
        y_im <= s_im >>> SH;
    end
endmodule
