// SPDX-License-Identifier: BSD-3-Clause
// sfifo — 小さな FIFO（LUTRAM、先頭は非同期読みで常に見える）。proj032 E-3 の lane の入口の溜め
//   push と pop は同じクロックでもよい。満ちているときの push は（同じクロックに pop があっても）捨てて ovf を 1 クロック立てる
//   （書き込みの許可を pop から切り離す: pop は取り出しの選びの論理の後ろにあり、E-3 の ddcb で最悪経路になった）
`timescale 1ns / 1ps
module sfifo #(parameter integer DW = 8, parameter integer AW = 4) (
    input  wire          clk, rst,
    input  wire          push, input wire [DW-1:0] din,
    input  wire          pop,
    output wire [DW-1:0] dout,
    output wire          empty,
    output reg           ovf
);
    (* ram_style = "distributed" *) reg [DW-1:0] m [0:(1<<AW)-1];
    reg [AW:0] wp, rp;
    wire full = (wp - rp) == (1 << AW);
    assign empty = (wp == rp);
    assign dout  = m[rp[AW-1:0]];
    always @(posedge clk) begin
        ovf <= 1'b0;
        if (rst) begin wp <= 0; rp <= 0; end
        else begin
            if (push) begin
                if (full) ovf <= 1'b1;
                else begin m[wp[AW-1:0]] <= din; wp <= wp + 1'b1; end
            end
            if (pop && !empty) rp <= rp + 1'b1;
        end
    end
endmodule
