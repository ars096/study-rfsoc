// SPDX-License-Identifier: BSD-3-Clause
//
// gb_adc — ギアボックスの入口（ADC ドメイン、341.33 MHz）に置く、再起動のリセットと RFDC の見張り（proj011 rev6）
//
// - RFDC の AXI4-Stream を**素通し**する（レジスタを挟まない。tdata / tvalid / tready とも配線だけ）
// - spec_core の GRST（ギアボックスごとの起動のやり直し）の間、gb_up と gb_fifo の書き込み側をリセットに保つ:
//     gb_rstn = aresetn & ~hold（hold は DSP ドメインから 2 段で取り込む）
//   解除は hold が落ちてから、さらに adj（0〜3）クロック遅らせる。**gb_up が語をまとめ始める位相（4 通り）を選ぶため**
//   （hold の長さは DSP の 3 クロック = ADC の 4 クロックでしか刻めず、それだけでは 4 通りのうち 3 通りしか選べない）
// - RFDC の tvalid が落ちた回数を数える（ハードのリセットと GRST で数え直す）。gb_gate が DSP ドメインに取り込む
//
// hold と adj は DSP ドメインのレジスタから来る。hold は ASYNC_REG の 2 段、adj は GRST の前に書いて止まっている
// 静的な値（同じく 2 段）。どちらも取り込みの揺れは 1 クロック以内で、再起動の位相の揺れとして結果に出る。

`timescale 1ns / 1ps

module gb_adc #(
    parameter integer DW = 192       // RFDC の語幅（spw_adc × 16 bit）。build.tcl が与える
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis:m_axis, ASSOCIATED_RESET aresetn:gb_rstn" *)
    input  wire          aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire          aresetn,

    input  wire [DW-1:0] s_axis_tdata,
    input  wire          s_axis_tvalid,
    output wire          s_axis_tready,

    output wire [DW-1:0] m_axis_tdata,
    output wire          m_axis_tvalid,
    input  wire          m_axis_tready,

    input  wire          hold,           // spec_core の gb_hold（DSP ドメイン）
    input  wire [1:0]    adj,            // spec_core の GRST_ADJ（DSP ドメイン、静的）
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 gb_rstn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    output wire          gb_rstn,        // gb_up / gb_fifo の書き込み側へ
    output wire [16:0]   adc_out         // {seen, gaps}（gb_gate が取り込む）
);
    assign m_axis_tdata  = s_axis_tdata;
    assign m_axis_tvalid = s_axis_tvalid;
    assign s_axis_tready = m_axis_tready;

    (* ASYNC_REG = "TRUE" *) reg h1, h2;
    (* ASYNC_REG = "TRUE" *) reg [1:0] a1, a2;
    reg [1:0] dly;
    reg       rstn_r;
    always @(posedge aclk) begin
        h1 <= hold; h2 <= h1;
        a1 <= adj;  a2 <= a1;
        if (!aresetn) begin
            rstn_r <= 1'b0; dly <= 2'd0;
        end else if (h2) begin
            rstn_r <= 1'b0; dly <= a2;
        end else if (dly != 2'd0) begin
            dly <= dly - 2'd1;
        end else begin
            rstn_r <= 1'b1;
        end
    end
    assign gb_rstn = rstn_r;

    // RFDC の valid の見張り
    reg        seen, prev;
    reg [15:0] gaps;
    always @(posedge aclk) begin
        if (!aresetn || h2) begin
            seen <= 1'b0; prev <= 1'b0; gaps <= 16'd0;
        end else begin
            prev <= s_axis_tvalid;
            if (s_axis_tvalid) seen <= 1'b1;
            if (seen && prev && !s_axis_tvalid && gaps != 16'hFFFF) gaps <= gaps + 16'd1;
        end
    end
    assign adc_out = {seen, gaps};
endmodule
