// SPDX-License-Identifier: BSD-3-Clause
// proj028 F-1 — fine_pfb の試験台。入力（1 行 = 1 拍 256 bit ＋ s_first）を流し、出口の y（実部・虚部）・m・fr を書く。`GAP で valid を時々落とす
`timescale 1ns/1ps
`default_nettype none
module tb_fine_pfb;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [256:0] mem [0:`NBEAT-1];         // [256] = s_first
    reg s_tvalid = 0, s_first = 0; reg [255:0] s_tdata = 0;
    wire [16*15-1:0] y_re, y_im; wire y_v, y_first, coef_mis; wire [12:0] y_m; wire [1:0] y_fr; wire [15:0] sat_cnt;
    fine_pfb #(.LO_FILE(`LO_HEX), .HI_FILE(`HI_HEX)) dut (.clk(clk), .rst(rst), .s_tdata(s_tdata), .s_tvalid(s_tvalid), .s_first(s_first),
        .y_re(y_re), .y_im(y_im), .y_v(y_v), .y_m(y_m), .y_first(y_first), .y_fr(y_fr), .sat_cnt(sat_cnt), .coef_mis(coef_mis));
    integer i, k, fo, seed = 4, nout = 0;
    initial begin
        $readmemh(`IN_HEX, mem);
        fo = $fopen(`OUT_TXT, "w");
        repeat (4) @(posedge clk); @(negedge clk); rst = 0;
        i = 0;
        while (i < `NBEAT) begin
            @(negedge clk);
`ifdef GAP
            if ($random(seed) % 7 == 0) begin s_tvalid = 0; s_first = 0; s_tdata = {256{1'bx}}; end
            else begin s_tvalid = 1; s_first = mem[i][256]; s_tdata = mem[i][255:0]; i = i + 1; end
`else
            s_tvalid = 1; s_first = mem[i][256]; s_tdata = mem[i][255:0]; i = i + 1;
`endif
        end
        @(negedge clk); s_tvalid = 0; s_first = 0;
        repeat (20) @(posedge clk);
        $display("beats %0d coef_mis %0d sat %0d", nout, coef_mis, sat_cnt);
        $fclose(fo);
        $finish;
    end
    always @(posedge clk) if (y_v) begin
        $fwrite(fo, "%0d %0d", y_m, y_fr);
        for (k = 0; k < 16; k = k + 1) $fwrite(fo, " %0d %0d", $signed(y_re[15*k +: 15]), $signed(y_im[15*k +: 15]));
        $fwrite(fo, "\n");
        nout = nout + 1;
    end
endmodule
`default_nettype wire
