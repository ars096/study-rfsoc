// SPDX-License-Identifier: BSD-3-Clause
//
// rmux128 — SpW の窓のレコード（dsink、128 bit）とコアの TP のレコード（tp_core、64 bit）を ring128 の 1 本の入口へ（proj032 P-6）
//
//   - TP の 64 bit は 2 語を 1 拍に詰める（先の語が下位 = リングの中のバイトの並びは s45_ring と同じ）。
//     TP のレコードは頭 8 語 ＋ 中身（64 バイトの倍数）で語の数は必ず偶数。奇数の語で tlast が来る形は扱わない
//   - レコード単位で順番に（tlast まで同じ口）。空いたときは前に出さなかったほうを先に（窓のレコードが続いても TP を待たせ続けない）
//   - 出口は 1 段のレジスタ（m_tready → 入口の tready は組み合わせで 1 段）
`timescale 1ns / 1ps

module rmux128 (
    input  wire         clk,
    input  wire         rst,
    input  wire [127:0] a_tdata,
    input  wire         a_tvalid,
    output wire         a_tready,
    input  wire         a_tlast,
    input  wire [63:0]  b_tdata,
    input  wire         b_tvalid,
    output wire         b_tready,
    input  wire         b_tlast,
    output reg  [127:0] m_tdata,
    output reg          m_tvalid,
    input  wire         m_tready,
    output reg          m_tlast
);
    // ---- TP: 2 語を 1 拍に ----
    reg  [63:0]  lo;
    reg          hl, pv, pl;
    reg  [127:0] pd;
    wire         p_take;
    assign b_tready = !hl || !pv || p_take;
    always @(posedge clk) begin
        if (rst) begin hl <= 1'b0; pv <= 1'b0; pl <= 1'b0; lo <= 64'd0; pd <= 128'd0; end
        else begin
            if (p_take) pv <= 1'b0;
            if (b_tvalid && b_tready) begin
                if (!hl) begin lo <= b_tdata; hl <= 1'b1; end
                else begin
`ifdef RMUX_POSCTL
                    pd <= {lo, b_tdata};                    // 陽性対照: 語の順を入れ替える
`else
                    pd <= {b_tdata, lo};
`endif
                    pl <= b_tlast; pv <= 1'b1; hl <= 1'b0;
                end
            end
        end
    end

    // ---- レコード単位の選び ----
    reg  lk, lsel, last;                // lk: レコードの途中（lsel の口）。last: 前に出した口（0 = a・1 = b）
    wire pick = lk ? lsel : (a_tvalid && pv) ? !last : !a_tvalid;
    wire o_free = !m_tvalid || m_tready;
    wire sv = pick ? pv : a_tvalid;
    wire go = o_free && sv;
    assign a_tready = o_free && !pick;
    assign p_take   = go && pick;
    always @(posedge clk) begin
        if (rst) begin m_tvalid <= 1'b0; m_tlast <= 1'b0; m_tdata <= 128'd0; lk <= 1'b0; lsel <= 1'b0; last <= 1'b1; end
        else begin
            if (go) begin
                m_tvalid <= 1'b1;
                m_tdata  <= pick ? pd : a_tdata;
                m_tlast  <= pick ? pl : a_tlast;
                lk       <= !(pick ? pl : a_tlast);
                lsel     <= pick;
                last     <= pick;
            end else if (m_tready) m_tvalid <= 1'b0;
        end
    end
endmodule
