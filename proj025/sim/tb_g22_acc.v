// SPDX-License-Identifier: BSD-3-Clause
// tb_g22_acc — g22_acc の単体（proj024 手順 2b）。電力 p は決まった式の擬似乱数（sim/check_g22.py の acc_p と同じ）:
//   p(f, k1, b) = ((f·1315423911 + k1·2654435761 + b·97531 + 12345) · 2246822519) mod 2^35（64 bit で掛けて下 35 bit）
// 3 つのダンプ（各 NA = 9 フレーム）: A = フレーム 0〜8（面 0）、B = 9〜17（面 1）、C = 18〜26（面 0、面 0 の 2 回目）。k1 は bit 反転順。
// B を積んでいる間に A（面 0）を、C を積んでいる間に B（面 1）を、終わってから C（面 0）を、全 131072 ch 読み出して `OUT/rd_<名前>.txt に
`timescale 1ns / 1ps
module tb_g22_acc;
    localparam integer M = 16384, NA = 9, NFR = 3 * NA, NCH = 131072, RLAT = 4;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [295:0] p = 0;
    reg pv = 0;
    reg [13:0] k1 = 0;
    reg act = 0, first = 0, plane = 0;
    reg [16:0] rc = 0;
    reg rpl = 0;
    wire [63:0] rd;
    g22_acc u (.clk(clk), .rst(rst), .p(p), .p_v(pv), .p_k1(k1), .t_act(act), .t_first(first), .t_plane(plane),
        .rd_c(rc), .rd_plane(rpl), .rd_d(rd));

    function [13:0] brev(input [13:0] n);
        integer q;
        begin for (q = 0; q < 14; q = q + 1) brev[13 - q] = n[q]; end
    endfunction
    function [36:0] pv_of(input integer f, input integer kk, input integer bb);
        reg [63:0] t;
        begin
            t = (64'd1315423911 * f + 64'd2654435761 * kk + 64'd97531 * bb + 64'd12345) * 64'd2246822519;
            pv_of = {2'b00, t[34:0]};
        end
    endfunction

    // ---- 書き: フレーム f のビート i ----
    integer f, i, bb;
    initial begin
        repeat (6) @(posedge clk);
        @(negedge clk); rst = 0;
        for (f = 0; f < NFR; f = f + 1)
            for (i = 0; i < M; i = i + 1) begin
                @(negedge clk);
                k1 = brev(i[13:0]);
                for (bb = 0; bb < 8; bb = bb + 1) p[37*bb +: 37] = pv_of(f, k1, bb);
                pv = 1; act = 1; first = (f % NA) == 0; plane = (f / NA) % 2;
            end
        @(negedge clk); pv = 0; act = 0;
    end

    // ---- 読み出し: ダンプ d（面 d % 2）を、ダンプ d + 1 の最初のフレームの 10 ビート目から ----
    integer fd, d, c, nrd = 0;
    reg rv [0:RLAT];
    integer rq [0:RLAT];
    integer j;
    always @(posedge clk) begin
        if (rv[RLAT]) begin $fwrite(fd, "%0d %0d\n", rq[RLAT], rd); nrd = nrd + 1; end
        for (j = RLAT; j > 0; j = j - 1) begin rv[j] <= rv[j-1]; rq[j] <= rq[j-1]; end
    end
    task read_dump(input integer dd);
        begin
            case (dd)
                0: fd = $fopen({`OUT, "/rd_A.txt"}, "w");
                1: fd = $fopen({`OUT, "/rd_B.txt"}, "w");
                default: fd = $fopen({`OUT, "/rd_C.txt"}, "w");
            endcase
            for (c = 0; c < NCH; c = c + 1) begin
                @(negedge clk); rc = c; rpl = dd % 2; rv[0] = 1; rq[0] = c;
            end
            @(negedge clk); rv[0] = 0;
            repeat (RLAT + 2) @(posedge clk);
            $fclose(fd);
        end
    endtask
    initial begin
        for (j = 0; j <= RLAT; j = j + 1) begin rv[j] = 0; rq[j] = 0; end
        for (d = 0; d < 3; d = d + 1) begin
            if (d < 2) wait (f == (d + 1) * NA && i == 10);
            else wait (pv == 0 && f == NFR);
            repeat (8) @(posedge clk);
            read_dump(d);
        end
        $display("tb_g22_acc: 書いたフレーム %0d・読み出し 3 回", NFR);
        $finish;
    end
endmodule
