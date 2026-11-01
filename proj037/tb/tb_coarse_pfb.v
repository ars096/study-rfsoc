// SPDX-License-Identifier: BSD-3-Clause
// proj028 C-1 — coarse_pfb の試験台。入力 hex（1 行 = 1 拍 256 bit）を流し、出口の z を書く。`GAP を定義すると時々 valid を落とす
// proj037 U-a: 拍のラベル s_t を付ける。ふつうは mem[i] の拍に T0 ＋ i（valid を落とすときも i で数える = 数えが valid の拍だけで進む今までの形）。
//   `GAPT: valid を落とした拍も T を進める（本物の T。位相の見張りが立つべき）。出口の行の頭に {o_t0, o_blk_b} を書く（窓を写した順 = 出口の順）
`timescale 1ns/1ps
`default_nettype none
module tb_coarse_pfb;
`ifndef T0
`define T0 0
`endif
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [255:0] mem [0:`NBEAT-1];
    reg s_valid = 0;
    reg [255:0] s_data = 0;
    reg [63:0] s_t = 0;
    wire m_valid, o_blk, o_blk_b, ph_lock, ph_err;
    wire [63:0] o_t0;
    wire [64*18-1:0] m_z;
    coarse_pfb dut (.clk(clk), .rst(rst), .s_valid(s_valid), .s_data(s_data), .s_t(s_t), .ph_clr(1'b0), .m_valid(m_valid), .m_z(m_z),
        .o_blk(o_blk), .o_blk_b(o_blk_b), .o_t0(o_t0), .ph_lock(ph_lock), .ph_err(ph_err));
    integer i, k, fo, nout = 0, seed = 3, nq = 0, nr = 0;
    reg [64:0] q [0:4095];
    reg [63:0] tclk = `T0;
    always @(posedge clk) if (o_blk) begin q[nq] <= {o_blk_b, o_t0}; nq <= nq + 1; end
    initial begin
        $readmemh(`IN_HEX, mem);
        fo = $fopen(`OUT_TXT, "w");
        repeat (4) @(posedge clk);
        @(negedge clk); rst = 0;
        i = 0;
        while (i < `NBEAT) begin
            @(negedge clk);
`ifdef GAPT
            tclk = tclk + 1;
            if ($random(seed) % 9 == 0) begin s_valid = 0; s_data = {256{1'bx}}; end
            else begin s_valid = 1; s_data = mem[i]; s_t = tclk; i = i + 1; end
`elsif GAP
            if ($random(seed) % 9 == 0) begin s_valid = 0; s_data = {256{1'bx}}; end
            else begin s_valid = 1; s_data = mem[i]; s_t = `T0 + i; i = i + 1; end
`else
            s_valid = 1; s_data = mem[i]; s_t = `T0 + i; i = i + 1;
`endif
        end
        @(negedge clk); s_valid = 0;
        repeat (20) @(posedge clk);
        $display("blocks %0d lock %0d err %0d", nout, ph_lock, ph_err);
        $fclose(fo);
        $finish;
    end
    always @(posedge clk) if (m_valid) begin
        $fwrite(fo, "%0d %0d ", q[nr][64], q[nr][63:0]); nr = nr + 1;
        for (k = 0; k < 64; k = k + 1) $fwrite(fo, "%0d ", $signed(m_z[k*18 +: 18]));
        $fwrite(fo, "\n");
        nout = nout + 1;
    end
endmodule
`default_nettype wire
