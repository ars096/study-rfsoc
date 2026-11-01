// SPDX-License-Identifier: BSD-3-Clause
// proj028 C-4 — ct_rd の試験台。メモリの模型（読みだけ、中身は hex）に対して chunk_done を 3 回与え、出口の拍を書く
//   チャンク 1 は読み途中に閉じる（待ちの経路）。出口の tready をランダムに落とす
`timescale 1ns/1ps
`default_nettype none
module tb_ct_rd;
    localparam integer MB = `MB;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg aresetn = 0;
    reg chunk_done = 0; reg [31:0] chunk_idx = 0;
    wire [31:0] m_araddr; wire [7:0] m_arlen; wire m_arvalid, m_rready;
    reg m_arready = 0, m_rvalid = 0, m_rlast = 0; reg [511:0] m_rdata = 0;
    wire [511:0] tdata; wire [21:0] tuser; wire tlast, tvalid; reg tready = 0;
    reg [7:0] awaddr = 0, araddr = 0; reg awvalid = 0, wvalid = 0, arvalid = 0; reg [31:0] wdata = 0;
    wire awready, wready, bvalid, arready, rvalid; wire [1:0] bresp, rresp; wire [31:0] rdata;
`ifndef NOUT
`define NOUT 4
`endif
    ct_rd #(.NOUT(`NOUT)) dut (.clk(clk), .aresetn(aresetn), .chunk_done(chunk_done), .chunk_idx(chunk_idx),
        .m_axi_arid(), .m_axi_araddr(m_araddr), .m_axi_arlen(m_arlen), .m_axi_arsize(), .m_axi_arburst(), .m_axi_arlock(),
        .m_axi_arcache(), .m_axi_arprot(), .m_axi_arqos(), .m_axi_arvalid(m_arvalid), .m_axi_arready(m_arready),
        .m_axi_rid(4'd0), .m_axi_rdata(m_rdata), .m_axi_rresp(2'b00), .m_axi_rlast(m_rlast), .m_axi_rvalid(m_rvalid), .m_axi_rready(m_rready),
        .m_axis_tdata(tdata), .m_axis_tuser(tuser), .m_axis_tlast(tlast), .m_axis_tvalid(tvalid), .m_axis_tready(tready),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_wdata(wdata), .s_axi_wvalid(wvalid),
        .s_axi_wready(wready), .s_axi_bvalid(bvalid), .s_axi_bresp(bresp), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rvalid(rvalid),
        .s_axi_rresp(rresp), .s_axi_rready(1'b1));
    reg [511:0] mem [0:MB-1];
    reg [31:0] arq_a [0:15]; reg [7:0] arq_l [0:15]; reg [3:0] arq_h = 0, arq_t = 0;
    wire [3:0] arq_n = arq_t - arq_h;
    reg [7:0] ri = 0; integer seedr = 9, errs = 0;
    reg [3:0] maxq = 0;                          // 同時に出ていた AR の最大（速さの照合、F-5d）
    always @(posedge clk) if (arq_n > maxq) maxq <= arq_n;
    always @(posedge clk) begin
        m_arready <= arq_n < 4'd12 && ($random(seedr) % 4 != 0);
        if (m_arvalid && m_arready) begin
            arq_a[arq_t] <= m_araddr; arq_l[arq_t] <= m_arlen; arq_t <= arq_t + 1;
            if (m_araddr % 64 != 0 || m_araddr / 64 + m_arlen + 1 > MB) begin $display("ERROR: AR の番地 %0d", m_araddr); errs = errs + 1; end
        end
        if (m_rvalid && m_rready) begin
            m_rvalid <= 0;
            if (m_rlast) begin ri <= 0; arq_h <= arq_h + 1; end else ri <= ri + 1;
        end else if (!m_rvalid && arq_n != 0 && ($random(seedr) % 3 != 0)) begin
            m_rdata <= mem[arq_a[arq_h] / 64 + ri];
            m_rlast <= (ri == arq_l[arq_h]);
            m_rvalid <= 1;
        end
        tready <= ($random(seedr) % 3 != 0);
    end
    task wr(input [7:0] a, input [31:0] d); begin
        @(negedge clk); awaddr = a; wdata = d; awvalid = 1; wvalid = 1;
        @(posedge clk); while (awready !== 1'b1) @(posedge clk);
        @(negedge clk); awvalid = 0; wvalid = 0;
        while (bvalid !== 1'b1) @(negedge clk);
        @(negedge clk);
    end endtask
    reg [31:0] rd_v;
    task rd(input [7:0] a); begin
        @(negedge clk); araddr = a; arvalid = 1;
        @(posedge clk); while (arready !== 1'b1) @(posedge clk);
        @(negedge clk); arvalid = 0;
        while (rvalid !== 1'b1) @(negedge clk);
        rd_v = rdata; @(negedge clk);
    end endtask
    integer fo, nbeat = 0;
    always @(posedge clk) if (tvalid && tready) begin $fwrite(fo, "%0d %0d %h\n", tuser, tlast, tdata); nbeat = nbeat + 1; end
    task pulse(input [31:0] c); begin @(negedge clk); chunk_done = 1; chunk_idx = c; @(negedge clk); chunk_done = 0; end endtask
    initial begin
        $readmemh(`IN_HEX, mem);
        fo = $fopen(`OUT_TXT, "w");
        repeat (5) @(posedge clk); aresetn = 1; repeat (3) @(posedge clk);
        wr(8'h08, `BASE); wr(8'h0C, `CHS); wr(8'h10, `PS); wr(8'h14, 3); wr(8'h18, `HB);
        wr(8'h04, 1);
        pulse(0);
        wait (nbeat == 100);
        pulse(1);                                    // 読み途中 → 待ち
        rd(8'h20); $display("STATUS（チャンク 1 の直後）%0d（期待 3 = 読み途中 ＋ 待ち）", rd_v);
        wait (nbeat == `NEXP2);
        repeat (50) @(posedge clk);
        pulse(2);
        wait (nbeat == `NEXP);
        repeat (300) @(posedge clk);
        $fclose(fo);
        rd(8'h24); $display("DONE %0d", rd_v);
        rd(8'h28); $display("DROP %0d", rd_v);
        rd(8'h2C); $display("FLAGS %0d", rd_v);
        rd(8'h20); $display("STATUS %0d", rd_v);
        $display("ERRS %0d", errs);
        $display("MAXQ %0d", maxq);
        $display("beats %0d", nbeat);
        $finish;
    end
    initial begin #50_000_000; $display("ERROR: 時間切れ（beats %0d）", nbeat); $finish; end
endmodule
`default_nettype wire
