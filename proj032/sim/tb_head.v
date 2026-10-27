// tb_head — head_core の動きの確かめ（E-2b。値の bit 単位の照合は P の段で）。複素の CW を入れ、出口の周波数と振幅を check_head.py で見る
`timescale 1ns / 1ps
module tb_head;
    reg clk = 0; always #1.953 clk = ~clk;
    reg rst = 1, yv = 0;
    reg signed [23:0] yr = 0, yi = 0;
    wire zv; wire signed [23:0] zr, zi; wire sat, ovr;
    // 入力 f = 23.4375 MHz（256 MS/s で）、NCO f0 = 20 MHz → 出口 3.4375 MHz（128 MS/s）
    localparam real F = 23.4375, F0 = 20.0, A = 1000000.0;
    head_core dut (.clk(clk), .rst(rst), .y_valid(yv), .y_re(yr), .y_im(yi), .dphi(32'd335544320), .z_valid(zv), .z_re(zr), .z_im(zi), .sat(sat), .ovr(ovr));
    integer m, fo, novr;
    initial begin
        fo = $fopen(`ZOUT, "w"); novr = 0;
        repeat (4) @(posedge clk); rst <= 0;
        for (m = 0; m < 8192; m = m + 1) begin
            @(posedge clk); yv <= 1;
            yr <= $rtoi(A * $cos(2.0 * 3.14159265358979 * F / 256.0 * m));
            yi <= $rtoi(A * $sin(2.0 * 3.14159265358979 * F / 256.0 * m));
        end
        @(posedge clk); yv <= 0; repeat (40) @(posedge clk);
        $fclose(fo); $display("ovr %0d", novr); $finish;
    end
    always @(posedge clk) begin if (zv) $fwrite(fo, "%0d %0d\n", zr, zi); if (ovr) novr = novr + 1; end
endmodule
