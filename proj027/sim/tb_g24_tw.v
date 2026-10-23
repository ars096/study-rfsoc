// SPDX-License-Identifier: BSD-3-Clause
// tb_g24_tw — g24_tw の単体（proj027 手順 1b）。k1 を IP の出口と同じ bit 反転順で 1 フレーム（4096）＋ 次のフレームの頭 256 流す。
// 流す前は番地を 4095 に置いておき、k1_out に最初の 0 が出たクロックでレイテンシを数える。
// 毎クロックの (k1_out, tw) を `OUT/tw.txt に書く。判定は sim/check_g24.py tw（tw が模型の tw_prod[k1_out] と同じ・k1_out の並びが入れた並び）
`timescale 1ns / 1ps
module tb_g24_tw;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg  [11:0] addr = 12'd4095;
    wire [575:0] tw;
    wire [11:0] k1_out;
    g24_tw #(.A_FILE(`TA), .B_FILE(`TB)) u (.clk(clk), .addr(addr), .tw(tw), .k1_out(k1_out));

    function [11:0] brev(input [11:0] n);
        integer b;
        begin for (b = 0; b < 12; b = b + 1) brev[11 - b] = n[b]; end
    endfunction

    integer cyc = 0, fd, t0 = -1, lat = -1, i;
    reg run = 0;
    always @(posedge clk) begin
        cyc <= cyc + 1;
        if (run) $fwrite(fd, "%0d %h\n", k1_out, tw);
        if (run && lat < 0 && k1_out == 12'd0) lat = cyc - t0;
    end
    initial begin
        fd = $fopen({`OUT, "/tw.txt"}, "w");
        repeat (10) @(posedge clk);
        run = 1;
        for (i = 0; i < 4096 + 256; i = i + 1) begin
            @(negedge clk);
            addr = brev(i[11:0]);
            if (i == 0) t0 = cyc;
        end
        @(negedge clk); addr = 12'd4095;
        repeat (12) @(posedge clk);
        run = 0;
        $fclose(fd);
        $display("tb_g24_tw: 流した %0d・レイテンシ %0d クロック（tb の数え）", 4096 + 256, lat);
        $display("tb: 口の振る舞い %s", (lat > 0) ? "OK" : "NG");
        $finish;
    end
endmodule
