// SPDX-License-Identifier: BSD-3-Clause
//
// wsb — 窓の分光の後段 1 ADC ぶん（proj032 E-4）: 機関 E 組（eng）＋ 履歴の枠 S（5 面 × 4096 × 36 bit、BRAM）＋ 窓ごとの積分器 H（4096 × 64 bit、URAM）
//
// 機関 e の入口は ddcb の final の lane e（窓 w は cfg_fl[w] の lane = 機関）。履歴は窓 w を枠 cfg_sl[w] に置く（S 以上は DDR の窓: E-4 ではまだ無い）。
// 全機関で共通のもの:
//   - 枠の中の番地 a（P0）。全機関の FFT の tready が 1 になってから回し始め（go）、以後は止めない
//   - PFB の係数 ROM（番地 a。Fine の pfb4_rom を 1 組）。履歴の枠は全部の面を番地 a で毎クロック読む（読みの番地の選びが要らない）
//   - 時刻の格子: rst から 2^G_L2 クロックごとに gidx を数え、RUN で g0 = gidx + 2
// 積分器 w の読み書きは、機関 cfg_fl[w] のものだけを受ける。読みは機関の S2 に番地 → S3 番地のレジスタ → S4 読み → S5 出力のレジスタ → S6 機関ごとの選び

`timescale 1ns / 1ps

module wsb #(
    parameter integer H    = 14,
    parameter integer E    = 3,
    parameter integer S    = 6,
    parameter integer W    = 20,
    parameter integer G_L2 = 19,
    parameter integer D    = 64
)(
    input  wire                 clk,
    input  wire                 rst,
    input  wire [E-1:0]         y_v,
    input  wire [E*4-1:0]       y_ch,
    input  wire [E*W-1:0]       y_re, y_im,
    input  wire [H*3-1:0]       cfg_ns,
    input  wire [H*2-1:0]       cfg_fl,
    input  wire [H*4-1:0]       cfg_sl,     // 窓ごとの履歴の枠（S 以上は枠なし）
    input  wire [H*4-1:0]       cfg_sh,
    input  wire [31:0]          ng, ndump,
    input  wire                 cmd_run, cmd_stop,
    output reg                  go,
    output reg  [31:0]          g0,
    output wire [E-1:0]         d_v,
    output wire [E*4-1:0]       d_w,
    output wire [E*32-1:0]      d_k,
    output wire [E*12-1:0]      d_ch,
    output wire [E*64-1:0]      d_data,
    output wire [E*8-1:0]       flags
);
    integer i;
    genvar g, b;

    // ---- 番地 a・格子 ----
    reg  [11:0]          a;
    wire [E-1:0]         rdy;
    reg  [G_L2-1:0]      gsub;
    reg  [31:0]          gidx;
    always @(posedge clk) begin
        if (rst) begin
            go <= 1'b0; a <= 12'd0; gsub <= 0; gidx <= 32'd0; g0 <= 32'd0;
        end else begin
            if (&rdy) go <= 1'b1;
            if (go) a <= a + 12'd1;
            gsub <= gsub + 1'b1;
            if (&gsub) gidx <= gidx + 32'd1;
            if (cmd_run) g0 <= gidx + 32'd2;
        end
    end
    wire signed [17:0]   c0, c1, c2, c3;
    pfb4_rom #(.P(0)) u_rom0 (.clk(clk), .addr_a(a), .addr_b(12'd4095 - a), .c_a(c0), .c_b(c3));
    pfb4_rom #(.P(1)) u_rom1 (.clk(clk), .addr_a(a), .addr_b(12'd4095 - a), .c_a(c1), .c_b(c2));

    // ---- 機関 ----
    wire [E-1:0]         hw_v;
    wire [3:0]           hw_s [0:E-1];
    wire [2:0]           hw_b [0:E-1];
    wire [11:0]          hw_a [0:E-1];
    wire [35:0]          hw_d [0:E-1];
    wire [S*5*36-1:0]    hq;
    wire [3:0]           i_rw [0:E-1], i_ww [0:E-1];
    wire [11:0]          i_ra [0:E-1], i_wa [0:E-1];
    wire [E-1:0]         i_we;
    wire [63:0]          i_wd [0:E-1];
    reg  [63:0]          i_rd [0:E-1];
    generate for (g = 0; g < E; g = g + 1) begin : en
        eng #(.H(H), .S(S), .W(W), .G_L2(G_L2), .D(D)) u (
            .clk(clk), .rst(rst),
            .in_v(y_v[g]), .in_w(y_ch[g*4 +: 4]), .in_re(y_re[g*W +: W]), .in_im(y_im[g*W +: W]),
            .cfg_ns(cfg_ns), .cfg_sl(cfg_sl), .cfg_sh(cfg_sh),
            .go(go), .a(a), .g0(g0), .ng(ng), .ndump(ndump), .cmd_run(cmd_run), .cmd_stop(cmd_stop),
            .rdy(rdy[g]),
            .hw_v(hw_v[g]), .hw_s(hw_s[g]), .hw_b(hw_b[g]), .hw_a(hw_a[g]), .hw_d(hw_d[g]),
            .hq(hq), .c0(c0), .c1(c1), .c2(c2), .c3(c3),
            .i_rw(i_rw[g]), .i_ra(i_ra[g]), .i_rd(i_rd[g]),
            .i_we(i_we[g]), .i_ww(i_ww[g]), .i_wa(i_wa[g]), .i_wd(i_wd[g]),
            .d_v(d_v[g]), .d_w(d_w[g*4 +: 4]), .d_k(d_k[g*32 +: 32]), .d_ch(d_ch[g*12 +: 12]), .d_data(d_data[g*64 +: 64]),
            .flags(flags[g*8 +: 8]));
    end endgenerate

    // ---- 履歴の枠: 書きは持ち主の機関から、読みは全部の面を番地 a で ----
    generate for (g = 0; g < S; g = g + 1) begin : sl
        reg  [1:0]   own_c, own;                    // 枠を使う窓の機関（設定から。@(*) は設定が変わったときだけ動く: sim の速さ）
        integer      q;
        always @(*) begin
            own_c = 2'd0;
            for (q = 0; q < H; q = q + 1) if (cfg_sl[q*4 +: 4] == g) own_c = cfg_fl[q*2 +: 2];
        end
        always @(posedge clk) own <= own_c;
        reg          wv;
        reg  [2:0]   wbk;
        reg  [11:0]  wad;
        reg  [35:0]  wdt;
        always @(posedge clk) begin
            wv  <= !rst && hw_v[own] && hw_s[own] == g;
            wbk <= hw_b[own]; wad <= hw_a[own]; wdt <= hw_d[own];
        end
        for (b = 0; b < 5; b = b + 1) begin : bk
            (* ram_style = "block" *) reg [35:0] m [0:4095];
            reg [35:0] q1, q2;
            always @(posedge clk) begin
                if (wv && wbk == b) m[wad] <= wdt;
                q1 <= m[a];
                q2 <= q1;
            end
            assign hq[(g*5 + b)*36 +: 36] = q2;
        end
    end endgenerate

    // ---- 積分器: 窓ごとに 1 面。読み書きは機関 cfg_fl[w] から ----
    wire [63:0]          iq [0:H-1];
    generate for (g = 0; g < H; g = g + 1) begin : ig
        reg  [1:0]   own;
        always @(posedge clk) own <= cfg_fl[g*2 +: 2];
        reg  [11:0]  ra, wa;
        reg          we;
        reg  [63:0]  wd;
        (* ram_style = "ultra" *) reg [63:0] m [0:4095];
        reg  [63:0]  q1, q2;
        always @(posedge clk) begin
            ra <= i_ra[own];
            we <= !rst && i_we[own] && i_ww[own] == g;
            wa <= i_wa[own]; wd <= i_wd[own];
            if (we) m[wa] <= wd;
            q1 <= m[ra];
            q2 <= q1;
        end
        assign iq[g] = q2;
    end endgenerate
    // 機関ごとの選び（S5 の窓 = S2 の i_rw を 3 クロック遅らせた）
    generate for (g = 0; g < E; g = g + 1) begin : rs
        reg [3:0] w3, w4, w5;
        always @(posedge clk) begin
            w3 <= i_rw[g]; w4 <= w3; w5 <= w4;
            i_rd[g] <= iq[w5];
        end
    end endgenerate
endmodule
