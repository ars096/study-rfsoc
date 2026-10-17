// SPDX-License-Identifier: BSD-3-Clause
// tb_g21_pfb — g21_pfb の単体（proj024 手順 1c）。入力は `OUT/x.hex（sim/check_g21.py pfb-gen が書く。1 行 = 1 ビート 256 bit）。
// 流し方: リセットの後、m = 16000 から 384 ビート（フレームの途中。本体は m = 0 まで捨てるはず）→ m = 0 から 5 フレーム（81,920 ビート）。
// 出口の (y_m, y_fr, y_first, y) を `OUT/y.txt に、終わりに sat_cnt・coef_mis を tb.log に書く。判定は sim/check_g21.py pfb
`timescale 1ns / 1ps
module tb_g21_pfb;
    localparam integer PRE = 384, NF = 5, NB = PRE + NF * 16384;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [255:0] d = 0;
    reg v = 0;
    reg [13:0] m = 0;
    wire [239:0] y;
    wire y_v, y_first, coef_mis;
    wire [13:0] y_m;
    wire [1:0] y_fr;
    wire [15:0] sat_cnt;
    g21_pfb #(.LO_FILE(`LO), .HI_FILE(`HI)) u (.clk(clk), .rst(rst), .s_tdata(d), .s_tvalid(v), .s_m(m),
        .y(y), .y_v(y_v), .y_m(y_m), .y_first(y_first), .y_fr(y_fr), .sat_cnt(sat_cnt), .coef_mis(coef_mis));

    reg [255:0] xm [0:NB-1];
    integer fd, i, nout = 0;
    always @(posedge clk) if (y_v === 1'b1) begin
        $fwrite(fd, "%0d %0d %0d %h\n", y_m, y_fr, y_first, y);
        nout = nout + 1;
    end
    initial begin
        $readmemh({`OUT, "/x.hex"}, xm);
        fd = $fopen({`OUT, "/y.txt"}, "w");
        repeat (8) @(posedge clk);
        @(negedge clk); rst = 0;
        repeat (4) @(negedge clk);
        for (i = 0; i < NB; i = i + 1) begin
            @(negedge clk);
            d = xm[i]; v = 1;
            m = (i < PRE) ? (16000 + i) : (i - PRE) % 16384;
        end
        @(negedge clk); v = 0;
        repeat (30) @(posedge clk);
        $fclose(fd);
        $display("tb_g21_pfb: 入れた %0d ビート・出た %0d ビート・sat_cnt %0d・coef_mis %0d", NB, nout, sat_cnt, coef_mis);
        $finish;
    end
endmodule
