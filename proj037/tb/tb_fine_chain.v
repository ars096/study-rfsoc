// SPDX-License-Identifier: BSD-3-Clause
// proj028 F-2 — fine_tw ＋ fine_chain の試験台。Y（1 行 = k1 ＋ 16 レーン × {re, im} 28 bit）を流し、出口の電力 16 銀行を書く
`timescale 1ns/1ps
`default_nettype none
module tb_fine_chain;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [12+16*56:0] mem [0:`NBEAT-1];     // [16*56 +: 13] = k1、レーン p が [56p +: 56] = {im 28, re 28}
    reg [16*28-1:0] y_re = 0, y_im = 0; reg [12:0] y_k1 = 0; reg y_v = 0;
    wire [12:0] tw_addr, tw_k1, p_k1; wire [575:0] tw; wire [16*37-1:0] p; wire p_v, tw_mis; wire [4:0] p_sat;
    fine_tw #(.A_FILE(`A_HEX), .B_FILE(`B_HEX)) u_tw (.clk(clk), .addr(tw_addr), .tw(tw), .k1_out(tw_k1));
    fine_chain u_ch (.clk(clk), .rst(rst), .y_re(y_re), .y_im(y_im), .y_k1(y_k1), .y_v(y_v), .tw_addr(tw_addr), .tw(tw), .tw_k1(tw_k1),
        .shift(4'd7), .p(p), .p_v(p_v), .p_k1(p_k1), .p_sat(p_sat), .tw_mis(tw_mis));
    integer i, k, fo, nout = 0;
    initial begin
        $readmemh(`IN_HEX, mem);
        fo = $fopen(`OUT_TXT, "w");
        repeat (4) @(posedge clk); @(negedge clk); rst = 0;
        for (i = 0; i < `NBEAT; i = i + 1) begin
            @(negedge clk);
            y_v = 1; y_k1 = mem[i][16*56 +: 13];
            for (k = 0; k < 16; k = k + 1) begin y_re[28*k +: 28] = mem[i][56*k +: 28]; y_im[28*k +: 28] = mem[i][56*k + 28 +: 28]; end
        end
        @(negedge clk); y_v = 0;
        repeat (40) @(posedge clk);
        $display("beats %0d tw_mis %0d", nout, tw_mis);
        $fclose(fo);
        $finish;
    end
    always @(posedge clk) if (p_v) begin
        $fwrite(fo, "%0d", p_k1);
        for (k = 0; k < 16; k = k + 1) $fwrite(fo, " %0d", p[37*k +: 37]);
        $fwrite(fo, "\n");
        nout = nout + 1;
    end
endmodule
`default_nettype wire
