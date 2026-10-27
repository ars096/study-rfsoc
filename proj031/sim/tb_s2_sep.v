// SPDX-License-Identifier: BSD-3-Clause
// tb_s2_sep — s2_sep の単体（proj030 P-1）。入力は `OUT/zre.hex・zim.hex（sim/check_s2.py gen が書く。1 行 = 1 ビートの IP 8 個の Z）。
// k1 は IP の出口と同じ bit 反転順（ビート i の k1 = bitrev12(i mod 4096)）。3 フレームを流し、出口の (行, 2Y re, 2Y im) を `OUT/y.txt に、
// 終わりに pos_mis を tb.log に書く。-DTB_GAP: valid にランダムな空き / -DTB_SKIP: 1 フレーム目の途中で k1 を 1 つ飛ばす（見張りの陽性対照）
`timescale 1ns / 1ps
module tb_s2_sep;
    localparam integer NF = 3, NB = NF * 4096;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [223:0] zr = 0, zi = 0;
    reg [11:0] k1 = 0;
    reg v = 0;
    wire [463:0] yr, yi;
    wire [11:0] yk;
    wire yv, pos_mis;
    s2_sep u (.clk(clk), .rst(rst), .z_re(zr), .z_im(zi), .z_k1(k1), .z_v(v), .clr(1'b0),
              .y_re(yr), .y_im(yi), .y_k(yk), .y_v(yv), .pos_mis(pos_mis));

    function [11:0] brev(input [11:0] n);
        integer b;
        begin for (b = 0; b < 12; b = b + 1) brev[11 - b] = n[b]; end
    endfunction

    reg [223:0] mre [0:NB-1];
    reg [223:0] mim [0:NB-1];
    integer fd, i, nout = 0, seed = 5;
    always @(posedge clk) if (yv === 1'b1) begin
        $fwrite(fd, "%0d %h %h\n", yk, yr, yi);
        nout = nout + 1;
    end
    initial begin
        $readmemh({`OUT, "/zre.hex"}, mre);
        $readmemh({`OUT, "/zim.hex"}, mim);
        fd = $fopen({`OUT, "/y.txt"}, "w");
        repeat (8) @(posedge clk);
        @(negedge clk); rst = 0;
        repeat (4) @(negedge clk);
        for (i = 0; i < NB; i = i + 1) begin
`ifdef TB_GAP
            while (($random(seed) & 3) == 0) begin @(negedge clk); v = 0; end
`endif
            @(negedge clk);
            zr = mre[i]; zi = mim[i]; k1 = brev(i[11:0]); v = 1;
`ifdef TB_SKIP
            if (i == 1000) k1 = brev(12'd1001);
`endif
        end
        @(negedge clk); v = 0;
        repeat (20) @(posedge clk);
        $fclose(fd);
        $display("tb_s2_sep: 入れた %0d ビート・出た %0d 行・pos_mis %0d", NB, nout, pos_mis);
        $finish;
    end
endmodule
