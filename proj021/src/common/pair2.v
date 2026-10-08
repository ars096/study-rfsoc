// SPDX-License-Identifier: BSD-3-Clause
// pair2 — 1 サンプルずつの流れを（偶, 奇）の組にまとめる。rst の後の最初のサンプルが偶（添字 0）
`timescale 1ns / 1ps
module pair2 #(parameter integer W = 24)(
    input  wire                clk,
    input  wire                rst,
    input  wire                in_v,
    input  wire signed [W-1:0] x_re, x_im,
    output reg                 out_v,
    output reg  signed [W-1:0] e_re, e_im, o_re, o_im
);
    reg               ph;          // 0 = 次は偶
    reg signed [W-1:0] hr, hi;
    always @(posedge clk) begin
        out_v <= 1'b0;
        if (rst) begin
            ph <= 1'b0;
        end else if (in_v) begin
            if (!ph) begin hr <= x_re; hi <= x_im; ph <= 1'b1; end
            else begin
                e_re <= hr;  e_im <= hi;  o_re <= x_re;  o_im <= x_im;
                out_v <= 1'b1;  ph <= 1'b0;
            end
        end
    end
endmodule
