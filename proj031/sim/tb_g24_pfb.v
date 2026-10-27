// SPDX-License-Identifier: BSD-3-Clause
// tb_g24_pfb — g24_pfb の単体（proj027 手順 1c）。入力は `OUT/x.hex（sim/check_g24.py pfb-gen が書く。1 行 = 1 ビート 256 bit）。
// 流し方: リセットの後、m = 3700 から 384 ビート（フレームの途中。本体は m = 0 まで捨てるはず）→ m = 0 から 5 フレーム（20,480 ビート）。
// 出口の (y_m, y_fr, y_first, y) を `OUT/y.txt に、終わりに sat_cnt・coef_mis を tb.log に書く。判定は sim/check_g24.py pfb
`timescale 1ns / 1ps
module tb_g24_pfb;
    localparam integer PRE = 384, NF = 5, NB = PRE + NF * 4096;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [255:0] d = 0;
    reg v = 0;
    reg [11:0] m = 0;
    wire [239:0] y;
    wire y_v, y_first, coef_mis;
    wire [11:0] y_m;
    wire [1:0] y_fr;
    wire [15:0] sat_cnt;
    // proj031: 共有の係数（sim だけの源 cu_src。中身は g24_cu）
    wire [11:0] cu_a; wire cu_av; wire [1151:0] cu_c; wire [11:0] cu_m; wire cu_v, cu_ok;
    cu_src u_cu (.clk(clk), .rst(rst), .addr(cu_a), .addr_v(cu_av), .coef(cu_c), .m_out(cu_m), .v_out(cu_v), .ok_out(cu_ok));
    g24_pfb u (.clk(clk), .rst(rst), .s_tdata(d), .s_tvalid(v), .s_m(m),
        .coef_addr(cu_a), .coef_addr_v(cu_av), .coef_in(cu_c), .coef_m_in(cu_m), .coef_ok_in(cu_ok), .clr(1'b0), .y(y), .y_v(y_v), .y_m(y_m), .y_first(y_first), .y_fr(y_fr), .sat_cnt(sat_cnt), .coef_mis(coef_mis));

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
            m = (i < PRE) ? (3700 + i) : (i - PRE) % 4096;
        end
        @(negedge clk); v = 0;
        repeat (30) @(posedge clk);
        $fclose(fd);
        $display("tb_g24_pfb: 入れた %0d ビート・出た %0d ビート・sat_cnt %0d・coef_mis %0d", NB, nout, sat_cnt, coef_mis);
        $finish;
    end
endmodule
