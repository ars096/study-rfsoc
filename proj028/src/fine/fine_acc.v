// SPDX-License-Identifier: BSD-3-Clause
//
// fine_acc — 細かい側の積分器（proj028 F-3）。proj024 の g21_acc（cbf0674）を 16 銀行・8192 行に直したもの:
//   入力は fine_chain の出口: 1 クロックに 1 つの k1（bit 反転順）と、その 16 銀行 k2 = 0..15 の電力 p（37 bit）。bin b = k1 + 8192·k2。
//   記憶は面ごとに 8192 行（番地 = k1）× 768 bit（銀行 k2 が [48·k2 +: 48]）、URAM。1 クロックに 1 行を RMW するだけで銀行の衝突は無い。
//   面: 積んでいる面（t_plane）は RMW に 2 口、凍った面の口を読み出し（rd_*）に。読み出しは rd_c（b = 0..131071）・rd_plane の 4 クロック後に rd_d
//   -DACC_FIRST_ERR は g21_acc と同じ陽性対照
// （以下は g21_acc の本体を写したもの）

`timescale 1ns / 1ps

module fine_acc #(
    parameter integer PW = 37,
    parameter integer AW = 48
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [16*PW-1:0]  p,
    input  wire              p_v,
    input  wire [12:0]       p_k1,
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
    reg [16*AW-1:0] w1_d;
    reg [12:0]      w1_a;
    reg            w1_we, w1_first, w1_pl;
    integer b;
    always @(posedge clk) begin
        for (b = 0; b < 16; b = b + 1) w1_d[AW*b +: AW] <= {{(AW-PW){1'b0}}, p[PW*b +: PW]};
        w1_a     <= p_k1;
        w1_we    <= p_v && t_act && !rst;
        w1_first <= t_first;
        w1_pl    <= t_plane;
    end

    // ---- 読み出しの番地 ----
    reg [12:0] r_a;
    reg [3:0]  r_b, r_b1, r_b2;
    reg        r_pl, r_pl1, r_pl2;
    always @(posedge clk) begin
        r_a <= rd_c[12:0]; r_b <= rd_c[16:13]; r_pl <= rd_plane;
        r_b1 <= r_b; r_b2 <= r_b1;
        r_pl1 <= r_pl; r_pl2 <= r_pl1;
    end

    // ---- 記憶（面ごと）----
    wire [16*AW-1:0] rdo [0:1];
    genvar pl;
    generate
        for (pl = 0; pl < 2; pl = pl + 1) begin : g_pl
            (* ram_style = "ultra" *) reg [16*AW-1:0] mem [0:8191];
            reg [16*AW-1:0] rd1, rd2, d2, d3, wv;
            reg [12:0]      a2, a3;
            reg            rmw2, rmw3, f2, f3;
            wire           rmw = w1_we && (w1_pl == pl);
            wire [12:0]    ra  = rmw ? w1_a : r_a;
            integer k;
            always @(posedge clk) begin
                rd1 <= mem[ra];
                rd2 <= rd1;
                a2 <= w1_a;     a3 <= a2;
                rmw2 <= rmw;    rmw3 <= rmw2;
                f2 <= w1_first; f3 <= f2;
                d2 <= w1_d;     d3 <= d2;
                if (rmw3) begin
                    for (k = 0; k < 16; k = k + 1)
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
