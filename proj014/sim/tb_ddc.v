// SPDX-License-Identifier: BSD-3-Clause
// proj014 — ddc_core の単体の sim。入力 y.txt（1 行 1 ビート: y0_ok y0_re y0_im y1_ok y1_re y1_im。pfb_core の出力と同じ並び）
//   → z.txt（「実部 虚部」を出る順に）
//   +NS=<1..6> +DPHI=<32 bit 符号なし> +GAP=<0|1> +IN= +OUT= +NBEAT=
// 照合は sim/check_ddc.py（model/win_fixed.py の ddc_fixed と bit 単位で）
`timescale 1ns / 1ps
module tb_ddc;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg yv = 0, y0ok = 0, y1ok = 0;
    reg signed [23:0] y0r = 0, y0i = 0, y1r = 0, y1i = 0;
    reg [31:0] dphi = 0;
    reg [2:0]  ns = 1;
    wire zv;
    wire signed [17:0] zr, zi;
    wire [15:0] satc;
    ddc_core dut (.clk(clk), .rst(rst), .y_valid(yv), .y0_ok(y0ok), .y1_ok(y1ok),
                  .y0_re(y0r), .y0_im(y0i), .y1_re(y1r), .y1_im(y1i),
                  .dphi(dphi), .ns(ns), .z_valid(zv), .z_re(zr), .z_im(zi), .sat_cnt(satc));
    integer fi, fo, nb, b, gap, seed, nsv, nout, r;
    integer a0, a3;
    integer b1, b2, b4, b5;
    reg [8*256-1:0] fin, fout;
    reg [31:0] dp;
    initial begin
        if (!$value$plusargs("NS=%d", nsv)) nsv = 1;
        if (!$value$plusargs("DPHI=%d", dp)) dp = 0;
        if (!$value$plusargs("GAP=%d", gap)) gap = 0;
        if (!$value$plusargs("NBEAT=%d", nb)) nb = 1000;
        if (!$value$plusargs("IN=%s", fin)) fin = "y.txt";
        if (!$value$plusargs("OUT=%s", fout)) fout = "z.txt";
        ns = nsv; dphi = dp; seed = 7;
        fi = $fopen(fin, "r");
        fo = $fopen(fout, "w");
        nout = 0;
        repeat (4) @(posedge clk);
        rst <= 0;
        b = 0;
        while (b < nb) begin
            @(posedge clk);
            if (gap && (($random(seed) & 3) == 0)) begin
                yv <= 0;
            end else begin
                r = $fscanf(fi, "%d %d %d %d %d %d\n", a0, b1, b2, a3, b4, b5);
                y0ok <= a0; y0r <= b1; y0i <= b2; y1ok <= a3; y1r <= b4; y1i <= b5;
                yv <= 1;
                b = b + 1;
            end
        end
        @(posedge clk);
        yv <= 0;
        repeat (60) @(posedge clk);
        $display("ddc: NS=%0d DPHI=%0d GAP=%0d 入力 %0d ビート → 出力 %0d、飽和 %0d", nsv, dp, gap, nb, nout, satc);
        $fclose(fo);
        $finish;
    end
    always @(posedge clk) if (zv) begin $fwrite(fo, "%0d %0d\n", zr, zi); nout = nout + 1; end
endmodule
