// SPDX-License-Identifier: BSD-3-Clause
//
// rec_arb — N 本のレコードの AXI4-Stream（64 bit・tlast・tuser）を、**レコード単位**の順番回しで 1 本に（proj021 手順 2-2a）
//
// レコードの途中では入口を替えない（tlast まで同じ入口）。入口の tvalid を見て、今の入口の次から順に選ぶ。
// 出口はレジスタ 1 段（スキッドの 2 語）で受ける。s45_core（win_core と FULL の 2 本）と s45_ring（コア 4 本）で使う
`timescale 1ns / 1ps

module rec_arb #(
    parameter integer N = 4
) (
    input  wire            clk,
    input  wire            rst,
    input  wire [64*N-1:0] s_tdata,
    input  wire [N-1:0]    s_tvalid,
    output wire [N-1:0]    s_tready,
    input  wire [N-1:0]    s_tlast,
    input  wire [N-1:0]    s_tuser,
    output wire [63:0]     m_tdata,
    output wire            m_tvalid,
    input  wire            m_tready,
    output wire            m_tlast,
    output wire            m_tuser
);
    localparam integer SW = (N > 1) ? $clog2(N) : 1;
    reg  [SW-1:0] cur;
    reg           lock;                  // レコードの途中
    reg  [SW-1:0] nx;
    reg           nx_v;
    integer i;
    always @* begin
        nx = cur; nx_v = 1'b0;
        for (i = N; i >= 1; i = i - 1)
            if (s_tvalid[(cur + i) % N]) begin nx = (cur + i) % N; nx_v = 1'b1; end
    end
    wire [SW-1:0] sel = lock ? cur : nx;
    wire          sv  = lock ? s_tvalid[cur] : nx_v;

    // 出口のスキッド（2 語）
    reg  [65:0] q0, q1;                  // {tuser, tlast, tdata}
    reg         v0, v1;
    wire        in_rdy = !v1;
    wire        take = sv && in_rdy;
    genvar g;
    generate
        for (g = 0; g < N; g = g + 1) begin : g_r
            assign s_tready[g] = in_rdy && (sel == g) && (lock || nx_v);
        end
    endgenerate
    wire [65:0] din = {s_tuser[sel], s_tlast[sel], s_tdata[64*sel +: 64]};
    assign m_tvalid = v0;
    assign {m_tuser, m_tlast, m_tdata} = q0;
    wire pop = v0 && m_tready;
    always @(posedge clk) begin
        if (rst) begin
            cur <= {SW{1'b0}}; lock <= 1'b0; v0 <= 1'b0; v1 <= 1'b0; q0 <= 66'd0; q1 <= 66'd0;
        end else begin
            if (take) begin
                cur  <= sel;
                lock <= !s_tlast[sel];
            end
            // スキッド: q0 が出口、q1 が控え
            case ({take, pop})
                2'b10: if (!v0) begin q0 <= din; v0 <= 1'b1; end else begin q1 <= din; v1 <= 1'b1; end
                2'b01: if (v1) begin q0 <= q1; v1 <= 1'b0; end else v0 <= 1'b0;
                2'b11: if (v1) begin q0 <= q1; q1 <= din; end else q0 <= din;
                default: ;
            endcase
        end
    end
endmodule
