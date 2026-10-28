// SPDX-License-Identifier: BSD-3-Clause
//
// ddrw — DDR の窓の履歴の書き手（proj032 D-2）。1 ADC に 1 つ（機関 E 組の DDR の窓をまとめる）
//
// 機関は DDR の窓の 4 標本（8 bit の I/Q × 4 = 64 bit）を語にして出す（dw_*: 枠 k・窓 w・フレームの下 3 bit f・語の番号 row = a / 4）。
// 溜め: 枠 k ごとに 2 KiB（区画 1 つ = 256 語）× 2 半分（区画の偶奇）。区画の最後の語が来たら 2 KiB を 1 本で書く（AXI 64 bit・256 拍。D-1: 書きは 2 KiB 以上で入る）
//   番地 = base + k·64 KiB + b·16 KiB + f·2 KiB（ddrr と同じ配置）
// フレームの区画 3 の書き込みの応答（B）が来たら、そのフレームが DDR に揃ったので、機関 e に窓 w の書き終わり（fl_*）を知らせる
// flags（粘着）: [0] 機関の語の FIFO が溢れた / [1] 書き終えていない半分に次の区画の語が来た（DDR が遅い）

`timescale 1ns / 1ps

module ddrw #(
    parameter integer E   = 3,
    parameter integer NK  = 8,          // DDR の枠の数
    parameter integer AW  = 32
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [AW-1:0]     base,
    input  wire [E-1:0]      dw_v,
    input  wire [E*4-1:0]    dw_k, dw_w,
    input  wire [E*3-1:0]    dw_f,
    input  wire [E*10-1:0]   dw_row,
    input  wire [E*64-1:0]   dw_d,
    output reg  [E-1:0]      fl_v,
    output reg  [E*4-1:0]    fl_w,
    // AXI4 の書き（64 bit、ID 1 つ）
    output reg  [AW-1:0]     m_awaddr,
    output wire [7:0]        m_awlen,
    output wire [2:0]        m_awsize,
    output wire [1:0]        m_awburst,
    output reg               m_awvalid,
    input  wire              m_awready,
    output wire [63:0]       m_wdata,
    output wire [7:0]        m_wstrb,
    output wire              m_wlast,
    output wire              m_wvalid,
    input  wire              m_wready,
    input  wire              m_bvalid,
    output wire              m_bready,
    output reg  [1:0]        flags
);
    localparam integer KB = $clog2(NK);
    assign m_awlen = 8'd255, m_awsize = 3'd3, m_awburst = 2'b01, m_wstrb = 8'hFF, m_bready = 1'b1;
    integer i;
    genvar g;

    // ---- 機関ごとの語の FIFO → 順番に溜めへ ----
    //   1 語 = {k 4, w 4, f 3, row 10, d 64}。機関は 4 クロックに 1 語以下なので、深さ 4 で足りる
    localparam integer QW = 4 + 4 + 3 + 10 + 64;
    wire [E-1:0]     q_empty, q_ovf;
    wire [QW-1:0]    q_dout [0:E-1];
    reg  [E-1:0]     q_pop;
    generate for (g = 0; g < E; g = g + 1) begin : wq
        sfifo #(.DW(QW), .AW(2)) u (.clk(clk), .rst(rst), .push(dw_v[g]),
            .din({dw_k[g*4 +: 4], dw_w[g*4 +: 4], dw_f[g*3 +: 3], dw_row[g*10 +: 10], dw_d[g*64 +: 64]}),
            .pop(q_pop[g]), .dout(q_dout[g]), .empty(q_empty[g]), .ovf(q_ovf[g]));
    end endgenerate
    reg  [1:0]       rr;                // 次に見る機関
    reg  [1:0]       sel;
    reg              selv;
    always @(*) begin
        selv = 1'b0; sel = 2'd0; q_pop = {E{1'b0}};
        for (i = E - 1; i >= 0; i = i - 1)
            if (!q_empty[(rr + i) % E]) begin selv = 1'b1; sel = (rr + i) % E; end
        if (selv) q_pop[sel] = 1'b1;
    end
    wire [QW-1:0]    hd = q_dout[sel];
    wire [3:0]       hk = hd[QW-1 -: 4];
    wire [3:0]       hw = hd[QW-5 -: 4];
    wire [2:0]       hf = hd[QW-9 -: 3];
    wire [9:0]       hrow = hd[QW-12 -: 10];
    wire [63:0]      hdat = hd[63:0];
    (* ram_style = "block" *) reg [63:0] stg [0:NK*512-1];      // {k, 半分, 行}
    reg  [NK*2-1:0]  busy;              // 半分が書き待ち（区画が揃ってから W を出し終えるまで）
    // 区画の待ち行列: {k, b, f, w, e}
    localparam integer BQ = 4 + 2 + 3 + 4 + 2;
    reg              bq_push;
    reg  [BQ-1:0]    bq_din;
    wire [BQ-1:0]    bq_head;
    wire             bq_empty, bq_ovf;
    reg              bq_pop;
    sfifo #(.DW(BQ), .AW(4)) u_bq (.clk(clk), .rst(rst), .push(bq_push), .din(bq_din), .pop(bq_pop),
                                   .dout(bq_head), .empty(bq_empty), .ovf(bq_ovf));
    reg              clr_v;
    reg  [KB:0]      clr_h;             // W を出し終えた半分 {k, 半分}
    always @(posedge clk) begin
        bq_push <= 1'b0;
        if (selv) stg[{hk[KB-1:0], hrow[8], hrow[7:0]}] <= hdat;
        if (rst) begin
            rr <= 2'd0; busy <= 0; flags <= 2'd0;
        end else begin
            if (selv) rr <= (sel + 1) % E;
            if (selv && hrow[7:0] == 8'hFF) begin
                bq_push <= 1'b1;
                bq_din  <= {hk, hrow[9:8], hf, hw, sel};
            end
            for (i = 0; i < NK * 2; i = i + 1)
                busy[i] <= (busy[i] && !(clr_v && clr_h == i)) || (selv && hrow[7:0] == 8'hFF && {hk[KB-1:0], hrow[8]} == i);
            flags <= flags | {selv && hrow[7:0] == 8'h00 && busy[{hk[KB-1:0], hrow[8]}], |q_ovf | bq_ovf};
        end
    end

    // ---- AW と W（1 本ずつ）----
    reg              wact;              // W を出している
    reg  [KB:0]      wh;                // その半分
    reg  [8:0]       rd_n;              // 溜めから読み出した語の数（256 で終わり）
    reg  [8:0]       wn;                // 出した拍
    reg  [3:0]       cr;                // 読みかけ ＋ FIFO の中の語（≦ 4）
    // 溜めの読み（2 クロック）→ 小さな FIFO → W
    reg              r1v, r2v;
    reg  [63:0]      r2d;
    wire             wf_empty, wf_ovf;
    wire [63:0]      wf_dout;
    wire             wpop = m_wvalid && m_wready;
    sfifo #(.DW(64), .AW(2)) u_wf (.clk(clk), .rst(rst), .push(r2v), .din(r2d), .pop(wpop),
                                   .dout(wf_dout), .empty(wf_empty), .ovf(wf_ovf));
    assign m_wvalid = !wf_empty;
    assign m_wdata  = wf_dout;
    assign m_wlast  = (wn == 9'd255);
    wire             rd_go = wact && rd_n != 9'd256 && cr < 4'd4;
    reg  [63:0]      r1d;
    // B の待ち: {f? 使わない, b, w, e}
    reg  [BQ-1:0]    bh [0:15];
    reg  [3:0]       bw_p, br_p;
    always @(posedge clk) begin
        r1v <= rd_go; r1d <= stg[{wh, rd_n[7:0]}];
        r2v <= r1v;   r2d <= r1d;
        bq_pop <= 1'b0; clr_v <= 1'b0;
        fl_v <= {E{1'b0}};
        if (rst) begin
            m_awvalid <= 1'b0; wact <= 1'b0; rd_n <= 9'd0; wn <= 9'd0; cr <= 4'd0; bw_p <= 4'd0; br_p <= 4'd0;
        end else begin
            cr <= cr + {3'd0, rd_go} - {3'd0, wpop};
            if (rd_go) rd_n <= rd_n + 9'd1;
            if (wpop) begin
                wn <= wn + 9'd1;
                if (wn == 9'd255) begin wact <= 1'b0; clr_v <= 1'b1; clr_h <= wh; end
            end
            if (m_awvalid && m_awready) begin
                m_awvalid <= 1'b0; wact <= 1'b1; rd_n <= 9'd0; wn <= 9'd0;
            end else if (!m_awvalid && !wact && !bq_empty && !bq_pop) begin
                // 区画 {k, b, f}: 番地 = base + k·64 KiB + b·16 KiB + f·2 KiB
                m_awaddr  <= base + {bq_head[BQ-1 -: 4], 16'd0} + {bq_head[BQ-5 -: 2], 14'd0} + {bq_head[BQ-7 -: 3], 11'd0};
                m_awvalid <= 1'b1;
                wh        <= {bq_head[BQ-1-4+KB -: KB], bq_head[BQ-6]};
                bh[bw_p]  <= bq_head; bw_p <= bw_p + 4'd1;
                bq_pop    <= 1'b1;
            end
            if (m_bvalid) begin
                br_p <= br_p + 4'd1;
                if (bh[br_p][BQ-5 -: 2] == 2'd3) begin                  // 区画 3 = フレームの最後
                    fl_v[bh[br_p][1:0]] <= 1'b1;
                    fl_w[bh[br_p][1:0]*4 +: 4] <= bh[br_p][5:2];
                end
            end
        end
    end
endmodule
