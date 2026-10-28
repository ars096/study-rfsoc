// SPDX-License-Identifier: BSD-3-Clause
//
// g21_acc — 2G-1 の FULL の積分器（proj024 手順 2b）。src/common/wide_acc.v（567fda2）の RMW・面の型を、切り出しなしの全 ch に
//
// 入力は g21_chain の出口: 1 クロックに 1 つの k1（bit 反転順で来る）と、その 8 銀行 k2 = 0..7 の電力 p（37 bit）。ch c = k1 + 16384·k2。
// 記憶は面ごとに 1 つ: 16384 行（番地 = k1）× 384 bit（銀行 k2 が [48·k2 +: 48]）。**1 クロックに 1 行を RMW するだけ**で、
// 銀行の衝突は起きない（1 クロックの 8 個はどれも同じ k1）。同じ行にもう一度来るのは 16384 クロック後（M-8d）。
// URAM288（4096 × 72）× 6 列 × 4 段 = 24 / 面、計 48（README の見積もり「48 bit・URAM」と同じ数）。
// 48 bit で足りる（M-5: p ≦ 2^35、N_ACC ≦ 8191 なら溢れない）。読み出しは 64 bit（上の 16 bit は 0。リングのレコードは u64 のまま）。
//
// 面: 積んでいる面（t_plane）は RMW に 2 つの口を使い、もう 1 つの面（凍った面）の口を読み出し（rd_*）に使う。
// 段: W0 入力 / W1 番地と選択のレジスタ / W2 読み 1 / W3 読み 2 / W4 書き（和）。wide_acc と同じ
// 読み出し: rd_c（ch 0..131071）・rd_plane を出して 4 クロック後に rd_d（番地のレジスタ → 記憶 → 出力レジスタ → 銀行の選択）
//
// -DACC_FIRST_ERR: ダンプの最初のフレームで前の値に足してしまう（消さない）。陽性対照（面を 2 回目に使うダンプが落ちるべき）

`timescale 1ns / 1ps

module g21_acc #(
    parameter integer PW = 37,
    parameter integer AW = 48
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [8*PW-1:0]   p,
    input  wire              p_v,
    input  wire [13:0]       p_k1,
    // このフレームの帳簿（p と同じクロックで有効）
    input  wire              t_act,         // 積む
    input  wire              t_first,       // ダンプの最初のフレーム（足さずに書く）
    input  wire              t_plane,
    // 読み出し（凍った面）
    input  wire [16:0]       rd_c,
    input  wire              rd_plane,
    output reg  [63:0]       rd_d
);
    // ---- W1 ----
    reg [8*AW-1:0] w1_d;
    reg [13:0]     w1_a;
    reg            w1_we, w1_first, w1_pl;
    integer b;
    always @(posedge clk) begin
        for (b = 0; b < 8; b = b + 1) w1_d[AW*b +: AW] <= {{(AW-PW){1'b0}}, p[PW*b +: PW]};
        w1_a     <= p_k1;
        w1_we    <= p_v && t_act && !rst;
        w1_first <= t_first;
        w1_pl    <= t_plane;
    end

    // ---- 読み出しの番地 ----
    reg [13:0] r_a;
    reg [2:0]  r_b, r_b1, r_b2;
    reg        r_pl, r_pl1, r_pl2;
    always @(posedge clk) begin
        r_a <= rd_c[13:0]; r_b <= rd_c[16:14]; r_pl <= rd_plane;
        r_b1 <= r_b; r_b2 <= r_b1;
        r_pl1 <= r_pl; r_pl2 <= r_pl1;
    end

    // ---- 記憶（面ごと）----
    wire [8*AW-1:0] rdo [0:1];
    genvar pl;
    generate
        for (pl = 0; pl < 2; pl = pl + 1) begin : g_pl
            (* ram_style = "ultra" *) reg [8*AW-1:0] mem [0:16383];
            reg [8*AW-1:0] rd1, rd2, d2, d3, wv;
            reg [13:0]     a2, a3;
            reg            rmw2, rmw3, f2, f3;
            wire           rmw = w1_we && (w1_pl == pl);
            wire [13:0]    ra  = rmw ? w1_a : r_a;
            integer k;
            always @(posedge clk) begin
                rd1 <= mem[ra];
                rd2 <= rd1;
                a2 <= w1_a;     a3 <= a2;
                rmw2 <= rmw;    rmw3 <= rmw2;
                f2 <= w1_first; f3 <= f2;
                d2 <= w1_d;     d3 <= d2;
                if (rmw3) begin
                    for (k = 0; k < 8; k = k + 1)
`ifdef ACC_FIRST_ERR
                        wv[AW*k +: AW] = rd2[AW*k +: AW] + d3[AW*k +: AW];
`else
                        wv[AW*k +: AW] = f3 ? d3[AW*k +: AW] : rd2[AW*k +: AW] + d3[AW*k +: AW];
`endif
                    mem[a3] <= wv;
                end
            end
            assign rdo[pl] = rd2;
        end
    endgenerate
    always @(posedge clk) rd_d <= {{(64-AW){1'b0}}, rdo[r_pl2][AW*r_b2 +: AW]};
endmodule
