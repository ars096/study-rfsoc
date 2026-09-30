// SPDX-License-Identifier: BSD-3-Clause
// proj014 — pfb_core → ddc_core を 1 本につないだ sim（窓 1 つ、ADC 1 本）。入力 x.hex（1 行 16 bit）→ z.txt
//   +K= +NS= +DPHI= +GAP= +NSAMP= +IN= +OUT=
// 照合は sim/check_win.py（model/win_fixed.py の pfb_fixed → ddc_fixed と bit 単位で）。つなぎ目（ok・組のまとめ直し・m = 0 の揃え）の試験
`timescale 1ns / 1ps
module tb_win;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg  [255:0] tdata = 0;
    reg          tvalid = 0;
    reg  [4:0]   k = 0;
    reg  [31:0]  dphi = 0;
    reg  [3:0]   ns = 1;
    wire signed [23:0] y0r, y0i, y1r, y1i;
    wire y0ok, y1ok, yv;
    wire [15:0] s1, s2;
    wire zv;
    wire signed [17:0] zr, zi;
    pfb_core u_pfb (.clk(clk), .rst(rst), .s_tdata(tdata), .s_tvalid(tvalid), .k(k),
                    .y0_re(y0r), .y0_im(y0i), .y1_re(y1r), .y1_im(y1i),
                    .y0_ok(y0ok), .y1_ok(y1ok), .y_valid(yv), .sat_cnt(s1));
    ddc_core u_ddc (.clk(clk), .rst(rst), .y_valid(yv), .y0_ok(y0ok), .y1_ok(y1ok),
                    .y0_re(y0r), .y0_im(y0i), .y1_re(y1r), .y1_im(y1i),
                    .dphi(dphi), .ns(ns), .z_valid(zv), .z_re(zr), .z_im(zi), .sat_cnt(s2));
    reg [15:0] mem [0:(1<<22)-1];
    integer nsamp, nbeat, b, l, fo, kk, gap, seed, nout, nsv;
    reg [31:0] dp;
    reg [8*256-1:0] fin, fout;
    initial begin
        if (!$value$plusargs("K=%d", kk)) kk = 5;
        if (!$value$plusargs("NS=%d", nsv)) nsv = 1;
        if (!$value$plusargs("DPHI=%d", dp)) dp = 0;
        if (!$value$plusargs("GAP=%d", gap)) gap = 0;
        if (!$value$plusargs("NSAMP=%d", nsamp)) nsamp = 16 * 4096;
        if (!$value$plusargs("IN=%s", fin)) fin = "x.hex";
        if (!$value$plusargs("OUT=%s", fout)) fout = "z.txt";
        $readmemh(fin, mem, 0, nsamp - 1);
        k = kk; ns = nsv; dphi = dp; seed = 21;
        nbeat = nsamp / 16;
        fo = $fopen(fout, "w");
        nout = 0;
        repeat (4) @(posedge clk);
        rst <= 0;
        b = 0;
        while (b < nbeat) begin
            @(posedge clk);
            if (gap && (($random(seed) & 7) == 0)) begin
                tvalid <= 0;
            end else begin
                for (l = 0; l < 16; l = l + 1) tdata[16*l +: 16] <= mem[16*b + l];
                tvalid <= 1;
                b = b + 1;
            end
        end
        @(posedge clk);
        tvalid <= 0;
        repeat (100) @(posedge clk);
        $display("win: K=%0d NS=%0d DPHI=%0d GAP=%0d 入力 %0d ビート → 出力 %0d、飽和 pfb %0d / ddc %0d", kk, nsv, dp, gap, nbeat, nout, s1, s2);
        $fclose(fo);
        $finish;
    end
    always @(posedge clk) if (zv) begin $fwrite(fo, "%0d %0d\n", zr, zi); nout = nout + 1; end
endmodule
