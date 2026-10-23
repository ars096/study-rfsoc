// SPDX-License-Identifier: BSD-3-Clause
// proj028 C-2 — coarse_stage の試験台。利得を書いてから入力（1 行 1 拍）を流し、出口の 512 bit を書く。
//   出口が WARM ブロックに達したら NACC を書き（数えを始め直す）、最後に SEQ・POW・CLIP を読んで書く
`timescale 1ns/1ps
`default_nettype none
module tb_coarse_stage;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg aresetn = 0;
    reg [255:0] mem [0:`NBEAT-1];
    reg [17:0] gmem [0:31];
    reg s_valid = 0;
    reg [255:0] s_data = 0;
    wire m_valid;
    wire [511:0] m_y;
    reg [11:0] awaddr = 0, araddr = 0; reg awvalid = 0, wvalid = 0, arvalid = 0; reg [31:0] wdata = 0;
    wire awready, wready, bvalid, arready, rvalid; wire [1:0] bresp, rresp; wire [31:0] rdata;
    coarse_stage dut (.clk(clk), .aresetn(aresetn), .s_valid(s_valid), .s_data(s_data), .m_valid(m_valid), .m_y(m_y),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_wdata(wdata), .s_axi_wvalid(wvalid),
        .s_axi_wready(wready), .s_axi_bvalid(bvalid), .s_axi_bresp(bresp), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rvalid(rvalid),
        .s_axi_rresp(rresp), .s_axi_rready(1'b1));
    task wr(input [11:0] a, input [31:0] d); begin
        @(negedge clk); awaddr = a; wdata = d; awvalid = 1; wvalid = 1;
        @(posedge clk); while (awready !== 1'b1) @(posedge clk);
        @(negedge clk); awvalid = 0; wvalid = 0;
        while (bvalid !== 1'b1) @(negedge clk);
        @(negedge clk);
    end endtask
    reg [31:0] rd_v;
    task rd(input [11:0] a); begin
        @(negedge clk); araddr = a; arvalid = 1;
        @(posedge clk); while (arready !== 1'b1) @(posedge clk);
        @(negedge clk); arvalid = 0;
        while (rvalid !== 1'b1) @(negedge clk);
        rd_v = rdata; @(negedge clk);
    end endtask
    integer i, k, fo, fr, nout = 0;
    reg go = 0, done_in = 0, nacc_set = 0;
    initial begin
        $readmemh(`IN_HEX, mem);
        $readmemh(`GAIN_HEX, gmem);
        fo = $fopen(`OUT_TXT, "w");
        repeat (5) @(posedge clk); aresetn = 1; repeat (5) @(posedge clk);
        for (k = 0; k < 32; k = k + 1) wr(12'h100 + 4 * k, gmem[k]);
        go = 1;
    end
    initial begin
        wait (go);
        for (i = 0; i < `NBEAT; i = i + 1) begin @(negedge clk); s_valid = 1; s_data = mem[i]; end
        @(negedge clk); s_valid = 0;
        repeat (60) @(posedge clk);
        done_in = 1;
    end
    initial begin
        wait (nout >= `WARM);
        wr(12'h004, `NACC);
        nacc_set = 1;
        wait (done_in);
        fr = $fopen(`REG_TXT, "w");
        rd(12'h008); $fwrite(fr, "SEQ %0d\n", rd_v);
        for (k = 0; k < 32; k = k + 1) begin
            rd(12'h200 + 8 * k); $fwrite(fr, "POW %0d %0d", k, rd_v); rd(12'h204 + 8 * k); $fwrite(fr, " %0d", rd_v);
            rd(12'h400 + 4 * k); $fwrite(fr, " CLIP %0d\n", rd_v);
        end
        $fclose(fr); $fclose(fo);
        $display("blocks %0d", nout);
        $finish;
    end
    always @(posedge clk) if (m_valid) begin
        $fwrite(fo, "%0d %h\n", nacc_set, m_y);
        nout = nout + 1;
    end
endmodule
`default_nettype wire
