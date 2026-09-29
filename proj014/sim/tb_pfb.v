// SPDX-License-Identifier: BSD-3-Clause
// proj014 — pfb_core の単体の sim。入力 x.hex（1 行 16 bit、16 行で 1 ビート）→ y.txt（フレームの順に「実部 虚部」）
//   +K=<0..16>   粗い ch
//   +GAP=<0|1>   1 なら s_tvalid をときどき落とす（窓は valid なビートだけ進むので、出力は変わらないはず）
//   +IN=<path> +OUT=<path>
// 照合は sim/check_pfb.py（model/win_fixed.py の pfb_fixed と bit 単位で）
`timescale 1ns / 1ps
module tb_pfb;
    reg clk = 0;
    always #1.953 clk = ~clk;   // 256 MHz
    reg rst = 1;
    reg  [255:0] tdata = 0;
    reg          tvalid = 0;
    reg  [4:0]   k = 0;
    wire signed [23:0] y0r, y0i, y1r, y1i;
    wire y0ok, y1ok, yv;
    wire [15:0] satc;

    pfb_core dut (.clk(clk), .rst(rst), .s_tdata(tdata), .s_tvalid(tvalid), .k(k),
                  .y0_re(y0r), .y0_im(y0i), .y1_re(y1r), .y1_im(y1i),
                  .y0_ok(y0ok), .y1_ok(y1ok), .y_valid(yv), .sat_cnt(satc));

    reg [15:0] mem [0:(1<<22)-1];
    integer nsamp, nbeat, b, l, fo, kk, gap, seed, nout;
    reg [8*256-1:0] fin, fout;
    initial begin
        if (!$value$plusargs("K=%d", kk)) kk = 5;
        if (!$value$plusargs("GAP=%d", gap)) gap = 0;
        if (!$value$plusargs("NSAMP=%d", nsamp)) nsamp = 16 * 1024;
        if (!$value$plusargs("IN=%s", fin)) fin = "x.hex";
        if (!$value$plusargs("OUT=%s", fout)) fout = "y.txt";
        $readmemh(fin, mem, 0, nsamp - 1);
        k = kk;
        seed = 14;
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
                tdata  <= {16{16'hDEAD}};    // valid でないビートの中身は使われないこと
            end else begin
                for (l = 0; l < 16; l = l + 1) tdata[16*l +: 16] <= mem[16*b + l];
                tvalid <= 1;
                b = b + 1;
            end
        end
        @(posedge clk);
        tvalid <= 0;
        repeat (40) @(posedge clk);
        $display("pfb: K=%0d GAP=%0d 入力 %0d ビート → 出力 %0d フレーム、飽和 %0d", kk, gap, nbeat, nout, satc);
        $fclose(fo);
        $finish;
    end
    always @(posedge clk) begin
        if (yv) begin
            if (y0ok) begin $fwrite(fo, "%0d %0d\n", y0r, y0i); nout = nout + 1; end
            if (y1ok) begin $fwrite(fo, "%0d %0d\n", y1r, y1i); nout = nout + 1; end
        end
    end
endmodule
