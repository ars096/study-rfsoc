// SPDX-License-Identifier: BSD-3-Clause
// proj028 C-1 — coarse_pfb の試験台。入力 hex（1 行 = 1 拍 256 bit）を流し、出口の z を書く。`GAP を定義すると時々 valid を落とす
`timescale 1ns/1ps
`default_nettype none
module tb_coarse_pfb;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [255:0] mem [0:`NBEAT-1];
    reg s_valid = 0;
    reg [255:0] s_data = 0;
    wire m_valid;
    wire [64*18-1:0] m_z;
    coarse_pfb dut (.clk(clk), .rst(rst), .s_valid(s_valid), .s_data(s_data), .m_valid(m_valid), .m_z(m_z));
    integer i, k, fo, nout = 0, seed = 3;
    initial begin
        $readmemh(`IN_HEX, mem);
        fo = $fopen(`OUT_TXT, "w");
        repeat (4) @(posedge clk);
        @(negedge clk); rst = 0;
        i = 0;
        while (i < `NBEAT) begin
            @(negedge clk);
`ifdef GAP
            if ($random(seed) % 9 == 0) begin s_valid = 0; s_data = {256{1'bx}}; end
            else begin s_valid = 1; s_data = mem[i]; i = i + 1; end
`else
            s_valid = 1; s_data = mem[i]; i = i + 1;
`endif
        end
        @(negedge clk); s_valid = 0;
        repeat (20) @(posedge clk);
        $display("blocks %0d", nout);
        $fclose(fo);
        $finish;
    end
    always @(posedge clk) if (m_valid) begin
        for (k = 0; k < 64; k = k + 1) $fwrite(fo, "%0d ", $signed(m_z[k*18 +: 18]));
        $fwrite(fo, "\n");
        nout = nout + 1;
    end
endmodule
`default_nettype wire
