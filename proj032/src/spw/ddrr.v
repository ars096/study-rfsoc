// SPDX-License-Identifier: BSD-3-Clause
//
// ddrr — DDR の窓の履歴の読み手（proj032 D-2）。機関 1 組に 1 つ
//
// DDR の配置（ddrw と同じ）: 枠 k の区画は 64 KiB = 区画 b（0..3、1024 標本ずつ）× フレーム f mod 8 × 2 KiB。
//   番地 = base + k·64 KiB + b·16 KiB + (f mod 8)·2 KiB。1 標本 = 2 B（{im 8, re 8}）、2 KiB = 1024 標本
// 仕事（rq: 枠 k・フレーム r）は枠の頭の LEAD クロック前に来る。区画 b ごとに、タップ t = 0..3（フレーム r − 3 + t）の 2 KiB を 1 本ずつ読む
//   （AXI 128 bit・128 拍。無効なタップ（r − 3 + t < 0）も読む: 機関がタップの有効の印で 0 にする）。
//   溜めはタップごとに 2 半分（区画の偶奇）× 128 行 × 128 bit。区画 b を読み始めてよいのは、その半分を前の区画が使い終えてから:
//     区画 0: すぐ（前の仕事の区画 2 は a = 3072 で使い終えている。LEAD < 1024）/ 1: 枠の頭を過ぎてから / 2: a ≧ 1024 / 3: a ≧ 2048
// 出口 dd（P2）: 番地 a（P0）の 4 タップ × {im, re}。機関は DDR の窓の枠でだけ使う
// flags（粘着）: [0] 使う区画がまだ埋まっていない（DDR が遅い）/ [1] 前の仕事の読みが終わる前に次の頼みが来た

`timescale 1ns / 1ps

module ddrr #(
    parameter integer AW = 32
)(
    input  wire              clk,
    input  wire              rst,
    input  wire              go,
    input  wire [11:0]       a,
    input  wire [AW-1:0]     base,
    input  wire              rq_v,
    input  wire [3:0]        rq_k,
    input  wire [31:0]       rq_r,
    // AXI4 の読み（128 bit、ID 1 つ）
    output reg  [AW-1:0]     m_araddr,
    output wire [7:0]        m_arlen,
    output wire [2:0]        m_arsize,
    output wire [1:0]        m_arburst,
    output reg               m_arvalid,
    input  wire              m_arready,
    input  wire [127:0]      m_rdata,
    input  wire              m_rvalid,
    input  wire              m_rlast,
    output wire              m_rready,
    output wire [63:0]       dd,
    output reg  [1:0]        flags
);
    assign m_arlen = 8'd127, m_arsize = 3'd4, m_arburst = 2'b01, m_rready = 1'b1;
    integer i;

    // ---- 仕事と区画の出し方 ----
    reg          jv;                // 仕事を持っている（区画 3 まで出し終えたら 0）
    reg          ins;               // 仕事の枠に入った（枠の頭を過ぎた）
    reg  [3:0]   jk;
    reg  [31:0]  jr;
    reg  [2:0]   nb;                // 次に出す区画
    reg  [1:0]   nt;                // 次に出すタップ
    reg          act;               // 今の枠が DDR の仕事（溜めを使う）
    wire         blk_ok = (nb == 3'd0) || (ins && (nb == 3'd1 || (nb == 3'd2 && a >= 12'd1024) || (nb == 3'd3 && a >= 12'd2048)));
    wire [2:0]   fr = jr[2:0] - 3'd3 + {1'b0, nt};
    // AR の札（R の拍がどのタップ・半分に入るか）。区画ごとに 4 本、出しすぎない（溜めの半分を越えない）
    reg  [2:0]   arq [0:7];         // {半分, タップ}
    reg  [3:0]   aw_p, ar_p;
    wire         arq_full = (aw_p - ar_p) == 4'd8;
    always @(posedge clk) begin
        flags[1] <= flags[1] | (rq_v && jv);
        if (rst) begin
            jv <= 1'b0; ins <= 1'b0; act <= 1'b0; m_arvalid <= 1'b0; aw_p <= 4'd0; flags[1] <= 1'b0;
        end else begin
            if (go && a == 12'd4095) begin
                ins <= jv;                                  // 仕事があれば、その枠に入る
                act <= jv;
            end
            if (rq_v) begin
                jv <= 1'b1; ins <= 1'b0; jk <= rq_k; jr <= rq_r; nb <= 3'd0; nt <= 2'd0;
            end else if (m_arvalid && m_arready) begin
                m_arvalid <= 1'b0;
            end else if (!m_arvalid && jv && nb != 3'd4 && blk_ok && !arq_full) begin
                m_araddr  <= base + {jk, 16'd0} + {nb[1:0], 14'd0} + {fr, 11'd0};
                m_arvalid <= 1'b1;
                arq[aw_p[2:0]] <= {nb[0], nt};
                aw_p <= aw_p + 4'd1;
                nt <= nt + 2'd1;
                if (nt == 2'd3) begin
                    nb <= nb + 3'd1;
                    if (nb == 3'd3) jv <= 1'b0;
                end
            end
        end
    end

    // ---- R の拍を溜めに ----
    reg  [6:0]   beat;
    wire [2:0]   rq_hd = arq[ar_p[2:0]];
    reg  [9:0]   cnt [0:1];         // 半分ごとに入った拍（512 で埋まった）
    // 溜め: BRAM 4 つ（512 行 × 64 bit）。行 = 4 標本の組の番号 q（半分 1 bit ＋ 組 8 bit）、タップ t の組 q は BRAM (t + q) mod 4 に
    //   書き: 拍（タップ t、組 2j と 2j+1 の 8 標本）は BRAM (t + 2j) と (t + 2j + 1) の 2 つに 64 bit ずつ（同じ BRAM に重ならない）
    //   読み: 番地 a の組 q を 4 つの BRAM から同じ行で読むと、BRAM m にタップ (m − q) mod 4 が出る
    //   （D-2 の最初の版はタップごとに 128 bit 幅の BRAM 2 つ・半分しか使わず、機関ごとに 8。D-2b でこの形にして 4）
    (* ram_style = "block" *) reg [63:0] bm0 [0:511], bm1 [0:511], bm2 [0:511], bm3 [0:511];
    wire [8:0]   ql = {rq_hd[2], beat, 1'b0}, qh = {rq_hd[2], beat, 1'b1};
    wire [1:0]   ml = rq_hd[1:0] + {beat[0], 1'b0}, mh = rq_hd[1:0] + {beat[0], 1'b1};
    // BRAM ごとに書く番地とデータを先に選び、書き込みは 1 文に（D-2b の 1 回目は if / else if の 2 文で書き、BRAM にならず LUTRAM に: LUT +19,000）
    wire [3:0]   wen;
    wire [8:0]   wa [0:3];
    wire [63:0]  wd [0:3];
    genvar       gm;
    generate for (gm = 0; gm < 4; gm = gm + 1) begin : wsel
        assign wen[gm] = m_rvalid && (ml == gm || mh == gm);
        assign wa[gm]  = (ml == gm) ? ql : qh;
        assign wd[gm]  = (ml == gm) ? m_rdata[63:0] : m_rdata[127:64];
    end endgenerate
    always @(posedge clk) begin
        if (wen[0]) bm0[wa[0]] <= wd[0];
        if (wen[1]) bm1[wa[1]] <= wd[1];
        if (wen[2]) bm2[wa[2]] <= wd[2];
        if (wen[3]) bm3[wa[3]] <= wd[3];
    end
    // 埋まりの数え: 拍で増やし、区画の最後の番地（使い終えた時）で 0 に。DDR の仕事でない枠でも同じ所で消す
    //   （次の仕事の区画はどれも消した後に読み始めるので、拍を落とさない。act で絞ると、使わなかった区画の数が残り、次の仕事で数え違える）
    wire         used0 = go && (a == 12'd1023 || a == 12'd3071);
    wire         used1 = go && (a == 12'd2047 || a == 12'd4095);
    always @(posedge clk) begin
        if (rst) begin
            beat <= 7'd0; ar_p <= 4'd0; cnt[0] <= 10'd0; cnt[1] <= 10'd0;
        end else begin
            if (m_rvalid) begin
                beat <= beat + 7'd1;
                if (beat == 7'd127) ar_p <= ar_p + 4'd1;
            end
            cnt[0] <= used0 ? 10'd0 : cnt[0] + {9'd0, m_rvalid && !rq_hd[2]};
            cnt[1] <= used1 ? 10'd0 : cnt[1] + {9'd0, m_rvalid &&  rq_hd[2]};
        end
    end
    // 使う区画の頭で埋まっていなければ flags[0]（区画 b の頭 a = 1024 b。半分 b mod 2 の拍 512）
    always @(posedge clk) begin
        if (rst) flags[0] <= 1'b0;
        else if (go && act && a[9:0] == 10'd0 && cnt[a[10]] != 10'd512) flags[0] <= 1'b1;
    end

    // ---- 読み（P0 の a → P1 行 → P2 タップを並べ替えて標本を選ぶ）----
    reg  [63:0]  q0, q1, q2, q3;
    reg  [1:0]   s1, r1;            // 組の中の標本・組の番号の下 2 bit
    always @(posedge clk) begin
        q0 <= bm0[{a[10], a[9:2]}]; q1 <= bm1[{a[10], a[9:2]}];
        q2 <= bm2[{a[10], a[9:2]}]; q3 <= bm3[{a[10], a[9:2]}];
        s1 <= a[1:0]; r1 <= a[3:2];
    end
    // タップ t は BRAM (t + q) mod 4
    wire [63:0]  qq [0:3];
    assign qq[0] = q0, qq[1] = q1, qq[2] = q2, qq[3] = q3;
    reg  [63:0]  ddr_q;
    integer      t;
    always @(posedge clk)
        for (t = 0; t < 4; t = t + 1) ddr_q[t*16 +: 16] <= qq[(t + r1) % 4][s1*16 +: 16];
    assign dd = ddr_q;
endmodule
