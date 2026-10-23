// SPDX-License-Identifier: BSD-3-Clause
// proj028 C-3 — ct_wr の試験台。ブロック（1 行 512 bit）を 7 拍に 2 回流し、AXI4 のメモリの模型に書かせて、最後に中身とレジスタを書く
//   -DSTALL: 途中で wready を長く落とす（溢れを数えるはず）
`timescale 1ns/1ps
`default_nettype none
module tb_ct_wr;
    localparam integer QB = `QB, GPD = `GPD, NP = 3, BASE = 4096;
    localparam integer CHS = GPD * QB * 64, PS = 32 * CHS;
    localparam integer MB = (BASE + NP * PS) / 64;      // 模型の拍の数
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg aresetn = 0;
    reg [511:0] blk [0:`NBLK-1];
    reg s_valid = 0; reg [511:0] s_y = 0;
    wire chunk_done; wire [31:0] chunk_idx;
    wire [31:0] m_awaddr; wire [7:0] m_awlen; wire m_awvalid, m_wlast, m_wvalid, m_bready; wire [511:0] m_wdata;
    reg m_awready = 0, m_wready = 0, m_bvalid = 0;
    reg [7:0] awaddr = 0, araddr = 0; reg awvalid = 0, wvalid = 0, arvalid = 0; reg [31:0] wdata = 0;
    wire awready, wready, bvalid, arready, rvalid; wire [1:0] bresp, rresp; wire [31:0] rdata;
    ct_wr #(.QB(QB)) dut (.clk(clk), .aresetn(aresetn), .s_valid(s_valid), .s_y(s_y), .chunk_done(chunk_done), .chunk_idx(chunk_idx),
        .m_axi_awid(), .m_axi_awaddr(m_awaddr), .m_axi_awlen(m_awlen), .m_axi_awsize(), .m_axi_awburst(), .m_axi_awlock(),
        .m_axi_awcache(), .m_axi_awprot(), .m_axi_awqos(), .m_axi_awvalid(m_awvalid), .m_axi_awready(m_awready),
        .m_axi_wdata(m_wdata), .m_axi_wstrb(), .m_axi_wlast(m_wlast), .m_axi_wvalid(m_wvalid), .m_axi_wready(m_wready),
        .m_axi_bid(4'd0), .m_axi_bresp(2'b00), .m_axi_bvalid(m_bvalid), .m_axi_bready(m_bready),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_wdata(wdata), .s_axi_wvalid(wvalid),
        .s_axi_wready(wready), .s_axi_bvalid(bvalid), .s_axi_bresp(bresp), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rvalid(rvalid),
        .s_axi_rresp(rresp), .s_axi_rready(1'b1));
    // ---- メモリの模型（書きだけ）----
    reg [511:0] mem [0:MB-1];
    reg [31:0] awq_a [0:15]; reg [7:0] awq_l [0:15]; reg [3:0] awq_h = 0, awq_t = 0;
    wire [3:0] awq_n = awq_t - awq_h;
    reg [7:0] wi = 0; integer bpend = 0, seedr = 5, errs = 0; reg stall = 0;
    reg [31:0] wa;
    always @(posedge clk) begin
        m_awready <= awq_n < 4'd12 && ($random(seedr) % 4 != 0);
        if (m_awvalid && m_awready) begin
            awq_a[awq_t] <= m_awaddr; awq_l[awq_t] <= m_awlen; awq_t <= awq_t + 1;
            if (m_awaddr % 64 != 0 || m_awaddr / 64 + m_awlen + 1 > MB) begin $display("ERROR: AW の番地 %0d", m_awaddr); errs = errs + 1; end
        end
        m_wready <= !stall && ($random(seedr) % 5 != 0);
        if (m_wvalid && m_wready) begin
            wa = awq_a[awq_h] / 64 + wi;
            if (awq_n == 0) begin $display("ERROR: AW より先の W（模型は受けない）"); errs = errs + 1; end
            else mem[wa] <= m_wdata;
            if (m_wlast != (wi == awq_l[awq_h])) begin $display("ERROR: WLAST の位置"); errs = errs + 1; end
            if (m_wlast) begin wi <= 0; awq_h <= awq_h + 1; bpend = bpend + 1; end else wi <= wi + 1;
        end
        if (m_bvalid && m_bready) m_bvalid <= 0;
        else if (!m_bvalid && bpend > 0) begin m_bvalid <= 1; bpend = bpend - 1; end
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
    integer i, fo, fc, nchunk = 0;
    always @(posedge clk) if (chunk_done) begin $fwrite(fc, "%0d\n", chunk_idx); nchunk = nchunk + 1; end
    initial begin
        $readmemh(`IN_HEX, blk);
        fc = $fopen(`CHK_TXT, "w");
        repeat (5) @(posedge clk); aresetn = 1; repeat (3) @(posedge clk);
        wr(8'h08, BASE); wr(8'h0C, CHS); wr(8'h10, PS); wr(8'h14, GPD); wr(8'h18, NP);
        wr(8'h04, 1);
        for (i = 0; i < `NBLK; i = i + 1) begin
            @(negedge clk); s_valid = 1; s_y = blk[i];
            @(negedge clk); s_valid = 0; s_y = {512{1'bx}};
            @(negedge clk);
            if (i % 2 == 1) @(negedge clk);
`ifdef STALL
            if (i == `NBLK / 2) stall = 1;
            if (i == `NBLK / 2 + 3 * 32 * QB) stall = 0;
`endif
        end
        repeat (3000) @(posedge clk);
        fo = $fopen(`OUT_TXT, "w");
        for (i = 0; i < MB; i = i + 1) $fwrite(fo, "%h\n", mem[i]);
        $fclose(fo);
        rd(8'h24); $fwrite(fc, "CHUNKS %0d\n", rd_v);
        rd(8'h28); $fwrite(fc, "OVF %0d\n", rd_v);
        rd(8'h2C); $fwrite(fc, "GROUPS %0d\n", rd_v);
        rd(8'h30); $fwrite(fc, "FLAGS %0d\n", rd_v);
        rd(8'h20); $fwrite(fc, "BUSY %0d\n", rd_v);
        $fwrite(fc, "ERRS %0d\n", errs);
        $fclose(fc);
        $display("chunk_done %0d", nchunk);
        $finish;
    end
endmodule
`default_nettype wire
