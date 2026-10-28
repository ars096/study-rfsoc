// SPDX-License-Identifier: BSD-3-Clause
// hbmc_ooc — hbmc を light（N 15）・final（N 67）の係数で包んだもの（OOC で数えるため。係数の長いベクトルを generic で渡さずに済ませる）
`timescale 1ns / 1ps
module hbmc_light #(parameter integer NCH = 16, parameter integer CW = 4, parameter integer PRE = 1, parameter integer R = 2) (
    input wire clk, rst, in_v, input wire [CW-1:0] in_ch,
    input wire signed [23:0] e_re, e_im, o_re, o_im,
    output wire out_v, output wire [CW-1:0] out_ch, output wire signed [23:0] y_re, y_im, output wire sat);
`include "hb_coef.vh"
    hbmc #(.N(LIGHT_N), .SH(LIGHT_SH), .H(LIGHT_H), .W(24), .NCH(NCH), .CW(CW), .PRE(PRE), .R(R)) u (
        .clk(clk), .rst(rst), .in_v(in_v), .in_ch(in_ch), .e_re(e_re), .e_im(e_im), .o_re(o_re), .o_im(o_im),
        .out_v(out_v), .out_ch(out_ch), .y_re(y_re), .y_im(y_im), .sat(sat));
endmodule
module hbmc_final #(parameter integer NCH = 16, parameter integer CW = 4, parameter integer PRE = 1, parameter integer R = 2) (
    input wire clk, rst, in_v, input wire [CW-1:0] in_ch,
    input wire signed [23:0] e_re, e_im, o_re, o_im,
    output wire out_v, output wire [CW-1:0] out_ch, output wire signed [23:0] y_re, y_im, output wire sat);
`include "hb_coef.vh"
    hbmc #(.N(FINAL_N), .SH(FINAL_SH), .H(FINAL_H), .W(24), .NCH(NCH), .CW(CW), .PRE(PRE), .R(R)) u (
        .clk(clk), .rst(rst), .in_v(in_v), .in_ch(in_ch), .e_re(e_re), .e_im(e_im), .o_re(o_re), .o_im(o_im),
        .out_v(out_v), .out_ch(out_ch), .y_re(y_re), .y_im(y_im), .sat(sat));
endmodule
