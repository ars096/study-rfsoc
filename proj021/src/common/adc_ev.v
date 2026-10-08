// SPDX-License-Identifier: BSD-3-Clause
//
// adc_ev — 入力（ギアボックスの出口、16 サンプル × 16 bit）の健全性の素（proj016）
//   ovr: そのビートの 16 サンプルのどれかが |x| ≧ TH（ADC の振り切れ。14 bit を 16 bit の上に詰めた値で 32764 = 8191 << 2）
//   gap: 最初の valid の後に valid が来ないクロック（起動の直後の途切れ。**時刻とサンプルの対応がずれる**）
// どちらも 2 段遅れのレベル（ダンプの区切りの精度に対して無視できる）
`timescale 1ns / 1ps
module adc_ev #(
    parameter integer TH = 32764
)(
    input  wire         clk,
    input  wire         rst,
    input  wire [255:0] tdata,
    input  wire         tvalid,
    output reg          ovr,
    output reg          gap
);
    reg [15:0] hit;
    reg        seen, v1;
    integer i;
    always @(posedge clk) begin
        for (i = 0; i < 16; i = i + 1)
            hit[i] <= tvalid && ($signed(tdata[16*i +: 16]) >= $signed(TH) || $signed(tdata[16*i +: 16]) <= -$signed(TH));
        v1 <= tvalid;
        if (rst) begin seen <= 1'b0; ovr <= 1'b0; gap <= 1'b0; end
        else begin
            if (v1) seen <= 1'b1;
            ovr <= |hit;
            gap <= seen && !v1;
        end
    end
endmodule
