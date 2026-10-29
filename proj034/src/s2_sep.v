// SPDX-License-Identifier: BSD-3-Clause
//
// s2_sep — レーン FFT の 2-for-1 の分け（proj030 P-1。proj033 で 2G-1-Fast の既定に、proj034 で 2G-2 の既定に: ZW 29・KB 13）。IP 8 個（z_q = y_q + j·y_(q+8)）の出口 Z から、実のレーン 16 本の 2Y を作る。
//   2·Y_q[k]     = (Zr[k] + Zr[−k]) + j(Zi[k] − Zi[−k])
//   2·Y_(q+8)[k] = (Zi[k] + Zi[−k]) + j(Zr[−k] − Zr[k])        （加減算だけ。½ は捨てない。proj034 の鎖は 2 bit 丸めて SH 18 で受ける）
// 定義は model/s2_model.py の sep_Z。
//
// 入口は IP の出口の bit 反転順（ビートの位置 n = bitrev(k1)）。k と −k は区間 [h, 2h)（h = 2^⌊log2 n⌋）の鏡の位置 3h − 1 − n にある:
//   - 前半（n < 1.5h）: 待つ値の溜め（M/4 × 2·NQ·ZW bit。2G-2 で 2,048 × 464 bit）の番地 n − h に書く
//   - 後半: 番地 2h − 1 − n を読み、組がそろう → 出口に行 r = min(k, M − k) を 1 本
//   - n = 0・1（k 0・M/2）は自己共役で、相手は自分
// 番地は IP の k1（tuser）から決める（T では引かない。IP の出口の位相はコアで揃う保証が無い、LESSONS）。
// 書きと読みの番地を同じ段（s1）で取り込むので、相手が 1 拍前でも読みは書きの後になる（迂回の道は要らない）。
// 出口は組がそろった拍だけ（1 フレームに M/2 + 1 行。(B) の鎖が受ける）。遅れは入口から 5 拍（valid の空きがあっても段は毎拍進む）。
//
// pos_mis（粘着、clr で消す）: k1 が bit 反転順の次でない（k1 = 0 から数え始める）
//
// 陽性対照（sim 用）: -DSEP_ADDR_ERR 読みの番地を 1 ずらす / -DSEP_SWAP_ERR k > M/2 で入れ替えない

`timescale 1ns / 1ps

module s2_sep #(
    parameter integer NQ = 8,
    parameter integer ZW = 29,
    parameter integer KB = 13
)(
    input  wire                    clk,
    input  wire                    rst,
    input  wire [NQ*ZW-1:0]        z_re,
    input  wire [NQ*ZW-1:0]        z_im,
    input  wire [KB-1:0]           z_k1,
    input  wire                    z_v,
    input  wire                    clr,
    output reg  [2*NQ*(ZW+1)-1:0]  y_re,      // レーン p = 0..15 の 2Y（ZW + 1 bit）
    output reg  [2*NQ*(ZW+1)-1:0]  y_im,
    output reg  [KB-1:0]           y_k,       // 行 r（0..2^(KB−1)）
    output reg                     y_v,
    output reg                     pos_mis
);
    localparam integer W  = 2 * NQ * ZW;     // 溜めの 1 語（2G-2 で 464 bit）
    localparam integer AB = KB - 2;          // 溜めの番地の bit（2G-2 で 2,048 語）
    localparam integer YW = ZW + 1;

    function [KB-1:0] brev(input [KB-1:0] x);
        integer b;
        begin for (b = 0; b < KB; b = b + 1) brev[KB - 1 - b] = x[b]; end
    endfunction

    // ---- s0: 入口の受け ----
    reg [W-1:0]  d0;
    reg [KB-1:0] k0;
    reg          v0 = 1'b0;
    always @(posedge clk) begin
        v0 <= rst ? 1'b0 : z_v;
        d0 <= {z_im, z_re};
        k0 <= z_k1;
    end

    // ---- s0 → s1: 位置・区間・番地 ----
    wire [KB-1:0] n0 = brev(k0);
    reg  [KB-1:0] h0;
    integer i;
    always @(*) begin
        h0 = {KB{1'b0}};
        for (i = 0; i < KB; i = i + 1) if (n0[i]) h0 = {KB{1'b0}} | (1 << i);
    end
    wire          self0  = (n0 < 2);
    wire          first0 = !self0 && (n0 < h0 + (h0 >> 1));
    wire [KB-1:0] wa0    = n0 - h0;
`ifdef SEP_ADDR_ERR
    wire [KB-1:0] ra0    = 2 * h0 - n0;
`else
    wire [KB-1:0] ra0    = 2 * h0 - 1 - n0;
`endif

    reg [W-1:0]  d1;
    reg [KB-1:0] k1;
    reg          v1 = 1'b0, self1, first1;
    reg [AB-1:0] wa1, ra1;
    always @(posedge clk) begin
        v1 <= rst ? 1'b0 : v0;
        d1 <= d0; k1 <= k0;
        self1 <= self0; first1 <= first0;
        wa1 <= wa0[AB-1:0]; ra1 <= ra0[AB-1:0];
    end

    // 見張り: 次の位置は bitrev(k1) + 1（k1 = 0 から数え始める）
    reg          have = 1'b0;
    reg [KB-1:0] n_exp;
    always @(posedge clk) begin
        if (rst) begin have <= 1'b0; pos_mis <= 1'b0; end
        else begin
            if (clr) pos_mis <= 1'b0;
            if (v0) begin
                if (have && n0 != n_exp) pos_mis <= 1'b1;
                if (have || k0 == {KB{1'b0}}) begin have <= 1'b1; n_exp <= n0 + 1'b1; end
            end
        end
    end

    // ---- 待つ値の溜め（s1 で書き・番地を取り込み、2 段で読む）----
    (* ram_style = "block" *) reg [W-1:0] mem [0:(1<<AB)-1];
    reg [W-1:0] m_q, m_q2;
    always @(posedge clk) begin
        if (v1 && first1) mem[wa1] <= d1;
        m_q  <= mem[ra1];
        m_q2 <= m_q;
    end

    // 今の値は溜めの読みに合わせて 2 段遅らせる
    reg [W-1:0]  d2, d3;
    reg [KB-1:0] k2, k3;
    reg          v2 = 1'b0, v3 = 1'b0, s2v, s3v, f2, f3;
    always @(posedge clk) begin
        v2 <= rst ? 1'b0 : v1;  v3 <= rst ? 1'b0 : v2;
        d2 <= d1; d3 <= d2;
        k2 <= k1; k3 <= k2;
        s2v <= self1; s3v <= s2v;
        f2 <= first1; f3 <= f2;
    end

    // ---- s3 → 出口: 入れ替えと加減算 ----
    wire          neg3 = (k3 > (1 << (KB - 1)));       // k > M/2: 溜めの値が Z[r]、今の値が Z[−r]
    wire [W-1:0]  pm3  = s3v ? d3 : m_q2;              // 相手
`ifdef SEP_SWAP_ERR
    wire [W-1:0]  zk   = d3;
    wire [W-1:0]  zm   = pm3;
`else
    wire [W-1:0]  zk   = neg3 ? pm3 : d3;
    wire [W-1:0]  zm   = neg3 ? d3 : pm3;
`endif
    wire [KB-1:0] r3   = neg3 ? ((1 << KB) - k3) : k3;

    genvar q;
    generate
        for (q = 0; q < NQ; q = q + 1) begin : g_q
            wire signed [ZW-1:0] akr = zk[ZW*q +: ZW],         aki = zk[NQ*ZW + ZW*q +: ZW];
            wire signed [ZW-1:0] amr = zm[ZW*q +: ZW],         ami = zm[NQ*ZW + ZW*q +: ZW];
            always @(posedge clk) begin
                y_re[YW*q        +: YW] <= akr + amr;
                y_im[YW*q        +: YW] <= aki - ami;
                y_re[YW*(q + NQ) +: YW] <= aki + ami;
                y_im[YW*(q + NQ) +: YW] <= amr - akr;
            end
        end
    endgenerate
    always @(posedge clk) begin
        y_v <= rst ? 1'b0 : (v3 && !f3);
        y_k <= r3;
    end
endmodule
