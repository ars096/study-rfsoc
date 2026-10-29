// SPDX-License-Identifier: BSD-3-Clause
// tb_g22_chain — g22_tw ＋ g22_chain の単体（proj025 手順 1d）。入力は `OUT/yre.hex・yim.hex（sim/check_g22.py chain-gen が書く。
// 1 行 = 1 ビートのレーン FFT の出口 16 × 28 bit）。k1 は IP の出口と同じ bit 反転順（ビート i の k1 = bitrev13(i mod 8192)）。
// 3 フレームを続けて流し、出口の (p_k1, p_sat, p) を `OUT/p.txt に、終わりに tw_mis を tb.log に書く。SHIFT は -DSHIFT=n
`timescale 1ns / 1ps
module tb_g22_chain;
    localparam integer NF = 3, NB = NF * 8192;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [447:0] yr = 0, yi = 0;
    reg [12:0] k1 = 0;
    reg v = 0;
    wire [12:0] tw_addr, tw_k1, p_k1;
    wire [575:0] tw;
    wire [295:0] p;
    wire p_v, tw_mis;
    wire [3:0] p_sat;
    g22_tw #(.A_FILE(`TA), .B_FILE(`TB)) u_tw (.clk(clk), .addr(tw_addr), .tw(tw), .k1_out(tw_k1));
    g22_chain u (.clk(clk), .rst(rst), .y_re(yr), .y_im(yi), .y_k1(k1), .y_v(v), .tw_addr(tw_addr), .tw(tw), .tw_k1(tw_k1),
        .shift(4'd`SHIFT), .p(p), .p_v(p_v), .p_k1(p_k1), .p_sat(p_sat), .tw_mis(tw_mis));

    function [12:0] brev(input [12:0] n);
        integer b;
        begin for (b = 0; b < 13; b = b + 1) brev[12 - b] = n[b]; end
    endfunction

    reg [447:0] mre [0:NB-1];
    reg [447:0] mim [0:NB-1];
    integer fd, i, nout = 0;
    always @(posedge clk) if (p_v === 1'b1) begin
        $fwrite(fd, "%0d %0d %h\n", p_k1, p_sat, p);
        nout = nout + 1;
    end
    initial begin
        $readmemh({`OUT, "/yre.hex"}, mre);
        $readmemh({`OUT, "/yim.hex"}, mim);
        fd = $fopen({`OUT, "/p.txt"}, "w");
        repeat (8) @(posedge clk);
        @(negedge clk); rst = 0;
        repeat (4) @(negedge clk);
        for (i = 0; i < NB; i = i + 1) begin
            @(negedge clk);
            yr = mre[i]; yi = mim[i]; k1 = brev(i[12:0]); v = 1;
        end
        @(negedge clk); v = 0;
        repeat (40) @(posedge clk);
        $fclose(fd);
        $display("tb_g22_chain: 入れた %0d ビート・出た %0d ビート・SHIFT %0d・tw_mis %0d", NB, nout, `SHIFT, tw_mis);
        $finish;
    end
endmodule
