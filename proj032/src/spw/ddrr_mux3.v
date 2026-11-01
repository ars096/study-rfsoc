// SPDX-License-Identifier: BSD-3-Clause
//
// ddrr_mux3 — DDR の読み手（ddrr、機関ごと）3 本の AXI4 の読みを 1 本に（proj032 P-9、b3 rev 6）
//
//   - smc_ddr の口を 4 ADC で 16 → 8 に減らすため（SmartConnect の LUT ≒ −10,000、配線の混みを下げる）
//   - AR は順番に（前に出した口の次から探す）。出した口の番号を待ち行列に積み、R は行列の頭の口へ返す
//     （ID は持たない。1 本の口の中で R は AR の順に返るので、rlast で行列を 1 つ進める）
//   - ddrr は R を止めずに受ける（rready 常に 1）ので、ここも m_rready を 1 にする。R は 1 段のレジスタを通して配る（rdata は 3 本に共通）
//   - 行列が満ちたら AR を出さない（出した arvalid は行列が満ちても下がらない: 行列が増えるのは AR を受けたときだけ）
//   陽性対照 -DDDRR_MUX_POSCTL: 2 本以上の読みが出ているときに R を行列の頭の次の口へ返す
`timescale 1ns / 1ps

module ddrr_mux3 #(
    parameter integer AW    = 32,
    parameter integer QD_L2 = 5             // 出ている読みの数の上限 2^QD_L2
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [3*AW-1:0]   s_araddr,
    input  wire [2:0]        s_arvalid,
    output wire [2:0]        s_arready,
    output reg  [127:0]      s_rdata,
    output reg  [2:0]        s_rvalid,
    output reg  [2:0]        s_rlast,
    output wire [AW-1:0]     m_araddr,
    output wire              m_arvalid,
    input  wire              m_arready,
    input  wire [127:0]      m_rdata,
    input  wire              m_rvalid,
    input  wire              m_rlast,
    output wire              m_rready
);
    localparam integer QD = 1 << QD_L2;
    assign m_rready = 1'b1;

    // ---- AR ----
    reg  [1:0]        sel = 2'd0, prev = 2'd2;
    reg               lk = 1'b0;
    reg  [QD_L2:0]    cnt = 0;
    wire              full = cnt[QD_L2];
    assign m_araddr  = s_araddr[sel*AW +: AW];
    assign m_arvalid = lk && s_arvalid[sel] && !full;
    wire              ar_hs = m_arvalid && m_arready;
    assign s_arready = {3{lk && m_arready && !full}} & {sel == 2'd2, sel == 2'd1, sel == 2'd0};

    // 前に出した口の次から、arvalid の立っている最初の口（3 本なので 0..2 で回す）
    wire [1:0] p1 = (prev == 2'd2) ? 2'd0 : prev + 2'd1;
    wire [1:0] p2 = (p1 == 2'd2) ? 2'd0 : p1 + 2'd1;
    wire [1:0] nxt = s_arvalid[p1] ? p1 : s_arvalid[p2] ? p2 : prev;

    // ---- 出した口の行列 ----
    (* ram_style = "distributed" *) reg [1:0] q [0:QD-1];
    reg  [QD_L2-1:0]  wp = 0, rp = 0;
    wire              pop = m_rvalid && m_rlast;
`ifdef DDRR_MUX_POSCTL
    wire [1:0]        head = (cnt > 1) ? q[rp + 1'b1] : q[rp];
`else
    wire [1:0]        head = q[rp];
`endif

    always @(posedge clk) begin
        if (ar_hs) q[wp] <= sel;
        if (rst) begin
            lk <= 1'b0; sel <= 2'd0; prev <= 2'd2;
            wp <= 0; rp <= 0; cnt <= 0;
            s_rvalid <= 3'd0; s_rlast <= 3'd0;
        end else begin
            if (ar_hs) begin wp <= wp + 1'b1; lk <= 1'b0; prev <= sel; end
            else if (!lk && |s_arvalid) begin sel <= nxt; lk <= 1'b1; end
            if (pop) rp <= rp + 1'b1;
            cnt <= cnt + ar_hs - pop;
            s_rvalid <= {3{m_rvalid}} & {head == 2'd2, head == 2'd1, head == 2'd0};
            s_rlast  <= {3{m_rvalid && m_rlast}} & {head == 2'd2, head == 2'd1, head == 2'd0};
        end
        s_rdata <= m_rdata;
    end
endmodule
