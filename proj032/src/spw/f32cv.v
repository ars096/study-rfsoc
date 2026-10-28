// SPDX-License-Identifier: BSD-3-Clause
//
// f32cv — u64 → IEEE 754 binary32（最近接・偶数への丸め）を 3 段で（proj032 K-2）
//
// 積分器の値（u64）を PL で f32 にする（K-1: PL → PS は f32）。PS（proj029 の C）は u64 → double → float の 2 回の丸め。
// u < 2^53 では double が厳密なので、ここの 1 回の丸めと bit 単位で同じ。u ≧ 2^53 は 1 回の丸めの値（2 回の丸めと違いうる。積分器では届かない）
// 0 → +0。上限 2^64 − 1 は 2^64（f32 で表せる、溢れない）
// 段: C1 先頭の 1 の位置（lz）→ C2 左に寄せる → C3 丸め・指数
//   値 = 1.m × 2^(63 − lz)、指数の符号 = 127 + 63 − lz。寄せた 64 bit の上 24 bit が仮数（隠れた 1 を含む）、次が丸めの bit、残りが粘り

`timescale 1ns / 1ps

module f32cv (
    input  wire        clk,
    input  wire        in_v,
    input  wire [63:0] in_u,
    output reg         out_v,
    output reg  [31:0] out_f
);
    // ---- C1: 先頭の 1 ----
    reg  [5:0]  lz;
    integer     i;
    always @(*) begin
        lz = 6'd63;
        for (i = 0; i < 64; i = i + 1)
            if (in_u[i]) lz = 6'd63 - i[5:0];
    end
    reg         v1, z1;
    reg  [63:0] u1;
    reg  [5:0]  lz1;
    always @(posedge clk) begin
        v1 <= in_v; u1 <= in_u; lz1 <= lz; z1 <= (in_u == 64'd0);
    end
    // ---- C2: 左に寄せる ----
    reg         v2, z2;
    reg  [63:0] n2;
    reg  [5:0]  lz2;
    always @(posedge clk) begin
        v2 <= v1; z2 <= z1; lz2 <= lz1; n2 <= u1 << lz1;
    end
    // ---- C3: 丸め ----
    wire [23:0] man  = n2[63:40];
    wire        rb   = n2[39];
    wire        st   = |n2[38:0];
    wire        up   = rb && (st || man[0]);
    wire [24:0] mr   = {1'b0, man} + {24'd0, up};
    wire [7:0]  ex   = 8'd190 - {2'd0, lz2} + {7'd0, mr[24]};     // 127 + 63 − lz（仮数が 2.0 に繰り上がれば + 1）
    wire [22:0] fr   = mr[24] ? mr[23:1] : mr[22:0];
    always @(posedge clk) begin
        out_v <= v2;
        out_f <= z2 ? 32'd0 : {1'b0, ex, fr};
    end
endmodule
