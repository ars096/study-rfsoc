// SPDX-License-Identifier: BSD-3-Clause
// proj028 S-1 — cfft32 の数値の確かめ。入力 hex（1 行 = z_r 64 個 × 18 bit）を 7 拍に 2 回（荒い PFB の出口の拍）入れ、出口を書く
`timescale 1ns/1ps
`default_nettype none
module tb_cfft32;
    localparam NB = 200;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg [64*18-1:0] mem [0:NB-1];
    reg s_valid = 0;
    reg [64*18-1:0] s_z = 0;
    wire m_valid;
    wire [32*2*24-1:0] m_f;
    cfft32 dut (.clk(clk), .s_valid(s_valid), .s_z(s_z), .m_valid(m_valid), .m_f(m_f));
    integer i, k, nin, nout, fo;
    initial begin
        $readmemh(`IN_HEX, mem);
        fo = $fopen(`OUT_TXT, "w");
        nin = 0; nout = 0;
        repeat (5) @(posedge clk);
        for (i = 0; i < NB * 7 / 2 + 40; i = i + 1) begin
            @(negedge clk);
            if ((i % 7 == 0 || i % 7 == 3) && nin < NB) begin s_valid = 1; s_z = mem[nin]; nin = nin + 1; end
            else begin s_valid = 0; s_z = {64*18{1'bx}}; end
        end
        repeat (60) @(posedge clk);
        $display("in %0d out %0d", nin, nout);
        $fclose(fo);
        $finish;
    end
    always @(posedge clk) if (m_valid) begin
        for (k = 0; k < 32; k = k + 1)
            $fwrite(fo, "%0d %0d ", $signed(m_f[k*48 +: 24]), $signed(m_f[k*48 + 24 +: 24]));
        $fwrite(fo, "\n");
        nout = nout + 1;
    end
endmodule
`default_nettype wire
