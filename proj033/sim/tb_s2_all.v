// SPDX-License-Identifier: BSD-3-Clause
// tb_s2_all — s2_sep → s2_chain（＋ g21_tw）→ s2_q をつないだ単体（proj030 P-2・P-3 の tb を proj033 で 2G-1-Fast の寸法に）。
// 入力は `OUT/zre.hex・zim.hex（sim/check_s2.py gen、3 フレーム）を 2 周回して 6 フレーム流す。
// 出口（積分器の口: p_k1・p_sat・p）を `OUT/p.txt に、フレームの境ごとの dmax と、終わりの見張りを tb.log に書く。
// -DSHIFT=n / -DTB_GAP: s2_sep の入口の valid にランダムな空き
`timescale 1ns / 1ps
module tb_s2_all;
    localparam integer NQ = 8, ZW = 30, KB = 14, M = 1 << KB, AB = 11;
    localparam integer NIN = 3 * M, NB = 6 * M;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [NQ*ZW-1:0] zr = 0, zi = 0;
    reg [KB-1:0] k1 = 0;
    reg v = 0;
    wire [2*NQ*(ZW+1)-1:0] yr, yi;
    wire [KB-1:0] yk, tw_addr, tw_k1, qk, pk;
    wire yv, pos_mis, qv, ysat, tw_mis, pv, ovf;
    wire [575:0] tw;
    wire [287:0] qre, qim;
    wire [15:0] qsat;
    wire [295:0] p;
    wire [3:0] psat;
    wire [AB+1:0] dmax;
    wire [AB:0] cmax;
    s2_sep   #(.NQ(NQ), .ZW(ZW), .KB(KB)) u_sep (.clk(clk), .rst(rst), .z_re(zr), .z_im(zi), .z_k1(k1), .z_v(v), .clr(1'b0),
                    .y_re(yr), .y_im(yi), .y_k(yk), .y_v(yv), .pos_mis(pos_mis));
    g21_tw   #(.A_FILE(`TA), .B_FILE(`TB)) u_tw (.clk(clk), .addr(tw_addr), .tw(tw), .k1_out(tw_k1));
    s2_chain u_ch  (.clk(clk), .rst(rst), .y_re(yr), .y_im(yi), .y_k(yk), .y_v(yv), .tw_addr(tw_addr), .tw(tw), .tw_k1(tw_k1),
                    .shift(4'd`SHIFT), .q_re(qre), .q_im(qim), .q_sat(qsat), .q_k(qk), .q_v(qv), .y_sat(ysat), .tw_mis(tw_mis));
    s2_q     #(.AB(AB), .KB(KB)) u_q (.clk(clk), .rst(rst), .clr(1'b0), .q_re(qre), .q_im(qim), .q_sat(qsat), .q_k(qk), .q_v(qv),
                    .p(p), .p_v(pv), .p_k1(pk), .p_sat(psat), .ovf(ovf), .dmax(dmax), .cmax(cmax));

    function [KB-1:0] brev(input [KB-1:0] n);
        integer b;
        begin for (b = 0; b < KB; b = b + 1) brev[KB - 1 - b] = n[b]; end
    endfunction

    reg [NQ*ZW-1:0] mre [0:NIN-1];
    reg [NQ*ZW-1:0] mim [0:NIN-1];
    integer fd, i, nout = 0, nysat = 0, seed = 5;
    always @(posedge clk) begin
        if (pv === 1'b1) begin $fwrite(fd, "%0d %0d %h\n", pk, psat, p); nout = nout + 1; end
        if (qv === 1'b1 && ysat === 1'b1) nysat = nysat + 1;
    end
    initial begin
        $readmemh({`OUT, "/zre.hex"}, mre);
        $readmemh({`OUT, "/zim.hex"}, mim);
        fd = $fopen({`OUT, "/p.txt"}, "w");
        repeat (8) @(posedge clk);
        @(negedge clk); rst = 0;
        repeat (4) @(negedge clk);
        for (i = 0; i < NB; i = i + 1) begin
`ifdef TB_GAP
            while (($random(seed) & 7) == 0) begin @(negedge clk); v = 0; end
`endif
            @(negedge clk);
            zr = mre[i % NIN]; zi = mim[i % NIN]; k1 = brev(i[KB-1:0]); v = 1;
            if (i % M == M - 1) $display("frame %0d dmax %0d", i / M, dmax);
        end
        @(negedge clk); v = 0;
        repeat (5000) @(posedge clk);
        $fclose(fd);
        $display("tb_s2_all: 入れた %0d ビート・出た %0d 行・SHIFT %0d・dmax %0d・cmax %0d・ovf %0d・tw_mis %0d・pos_mis %0d・ysat %0d",
                 NB, nout, `SHIFT, dmax, cmax, ovf, tw_mis, pos_mis, nysat);
        $finish;
    end
endmodule
