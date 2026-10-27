// SPDX-License-Identifier: BSD-3-Clause
// tb_g24_cu — g24_cu の単体（proj031 P-1）。**比べる相手は proj030 の g24_coef の RTL そのもの**（同じ番地を入れ、出口の 1152 bit を m ごとに比べる）。
// 手順: リセット中に ready を出さないか → ID・PROJ・COEF_CRC → 4096 行を書く（`WORDS、pynq/g24cu.py の words）→ VERIFY → STAT・CRC・NROW →
//       番地 m を 3 フレーム途切れなく流し、2・3 フレーム目の出口を g24_coef と比べる → 最後に STAT を読み直す。
// 判定は sim/check_cu.py（tb.log の「KEY 値」の行を読む）。
// 変種（tb の側）: -DTB_NOWRITE（書かずに VERIFY）/ -DTB_ONEBIT（行 100 の語 3 の bit 5 を反転して書く）/ -DTB_AFTERWRITE（照合の後に行 5 を書き直す）
`timescale 1ns / 1ps
module tb_g24_cu;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;

    reg  [11:0] addr = 0;
    reg         addr_v = 0;
    wire [1151:0] coef, rcoef;
    wire [11:0] m_out, rm_out;
    wire        v_out, ok_out, rv_out;

    reg  [9:0]  awaddr = 0, araddr = 0;
    reg  [31:0] wdata = 0;
    reg         awvalid = 0, wvalid = 0, bready = 1, arvalid = 0, rready = 1;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [1:0]  bresp, rresp;
    wire [31:0] rdata;

    g24_cu u (.aclk(clk), .aresetn(~rst), .addr(addr), .addr_v(addr_v), .coef(coef), .m_out(m_out), .v_out(v_out), .ok_out(ok_out),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_wdata(wdata), .s_axi_wvalid(wvalid),
        .s_axi_wready(wready), .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rresp(rresp),
        .s_axi_rvalid(rvalid), .s_axi_rready(rready));
    g24_coef #(.LO_FILE(`LO), .HI_FILE(`HI)) uref (.clk(clk), .addr(addr), .addr_v(addr_v), .coef(rcoef), .m_out(rm_out), .v_out(rv_out));

    reg [575:0] rows [0:4095];
    integer cyc = 0;
    always @(posedge clk) cyc <= cyc + 1;

    // リセット中の ready（LESSONS、proj028）
    integer rst_rdy = 0;
    always @(posedge clk) if (rst && (awready === 1'b1 || wready === 1'b1 || arready === 1'b1)) rst_rdy = rst_rdy + 1;

    // AXI の待ちは !== 1'b1 で（LESSONS）
    task axi_wr(input [9:0] a, input [31:0] x);
        begin
            @(negedge clk); awaddr = a; wdata = x; awvalid = 1; wvalid = 1;
            @(posedge clk); while ((awready && wready) !== 1'b1) @(posedge clk);
            @(negedge clk); awvalid = 0; wvalid = 0;
            @(posedge clk); while (bvalid !== 1'b1) @(posedge clk);
        end
    endtask
    reg [31:0] rd_v;
    task axi_rd(input [9:0] a);
        begin
            @(negedge clk); araddr = a; arvalid = 1;
            @(posedge clk); while (arready !== 1'b1) @(posedge clk);
            @(negedge clk); arvalid = 0;
            @(posedge clk); while (rvalid !== 1'b1) @(posedge clk);
            rd_v = rdata;
        end
    endtask
    task write_row(input [11:0] m, input [575:0] r);
        integer k;
        begin
            for (k = 0; k < 18; k = k + 1) axi_wr(10'h040 + 4 * k, r[32*k +: 32]);
            axi_wr(10'h00C, {20'd0, m});
        end
    endtask

    // ---- 出口を m ごとに記録（cu と g24_coef）。フレームの番号は tb が数える ----
    reg [1151:0] cu_c [0:4095];
    reg [1151:0] rf_c [0:4095];
    integer frame_cu = -1, frame_rf = -1, n_nok = 0, n_cu = 0, n_rf = 0, n_mo = 0;
    integer t_in [0:4095];
    integer lat_cu = -1, lat_rf = -1, lat_bad = 0, nmis = 0, m_first = -1, i, k2;
    reg cmp_on = 0;
    always @(posedge clk) begin
        if (cmp_on && v_out === 1'b1) begin
            if (m_out == 12'd0) frame_cu = frame_cu + 1;
            if (frame_cu >= 1) begin
                cu_c[m_out] <= coef; n_cu = n_cu + 1;
                if (ok_out !== 1'b1) n_nok = n_nok + 1;
                if (lat_cu < 0) lat_cu = cyc - t_in[m_out];
                else if (cyc - t_in[m_out] != lat_cu) lat_bad = lat_bad + 1;
            end
        end
        if (cmp_on && rv_out === 1'b1) begin
            if (rm_out == 12'd0) frame_rf = frame_rf + 1;
            if (frame_rf >= 1) begin rf_c[rm_out] <= rcoef; n_rf = n_rf + 1; if (lat_rf < 0) lat_rf = cyc - t_in[rm_out]; end
        end
    end

    integer m, f;
    reg [575:0] r;
    initial begin
        $readmemh(`WORDS, rows);
        repeat (20) @(posedge clk);
        @(negedge clk) rst = 0;
        repeat (4) @(posedge clk);
        $display("RST_READY %0d", rst_rdy);
        axi_rd(10'h000); $display("ID %h", rd_v);
        axi_rd(10'h004); $display("PROJ %h", rd_v);
        axi_rd(10'h010); $display("COEF_CRC %h", rd_v);
        axi_wr(10'h008, 32'h2);                            // CLR
`ifndef TB_NOWRITE
        for (m = 0; m < 4096; m = m + 1) begin
            r = rows[m];
`ifdef TB_ONEBIT
            if (m == 100) r[32*3 + 5] = ~r[32*3 + 5];
`endif
            write_row(m[11:0], r);
        end
`endif
        // DATA の読み返し（最後に書いた行の語 17）
        axi_rd(10'h084); $display("DATA17 %h", rd_v);
        $display("DATA17_WANT %h", rows[4095][32*17 +: 32]);
        axi_rd(10'h008); $display("STAT_PRE %h", rd_v);
        axi_wr(10'h008, 32'h1);                            // VERIFY
        f = cyc;
        axi_rd(10'h008);
        while (rd_v[1] === 1'b1) axi_rd(10'h008);
        $display("VERIFY_CYC %0d", cyc - f);
        $display("STAT %h", rd_v);
        axi_rd(10'h014); $display("CRC %h", rd_v);
        axi_rd(10'h018); $display("NROW %0d", rd_v);
        axi_rd(10'h00C); $display("LAST_ROW %0d", rd_v);

        // 走りの読み: 3 フレーム途切れなく
        @(negedge clk); cmp_on = 1;
        for (f = 0; f < 3; f = f + 1)
            for (m = 0; m < 4096; m = m + 1) begin
                @(negedge clk); addr = m; addr_v = 1; t_in[m] = cyc + 1;    // 次の立ち上がりで取り込まれる
            end
        @(negedge clk); addr_v = 0;
        repeat (16) @(posedge clk);
        cmp_on = 0;
        for (m = 0; m < 4096; m = m + 1) if (cu_c[m] !== rf_c[m]) begin
            nmis = nmis + 1;
            if (m_first < 0) m_first = m;
        end
        $display("N_OUT %0d %0d", n_cu, n_rf);
        $display("LAT %0d %0d", lat_cu, lat_bad);
        $display("LAT_REF %0d", lat_rf);
        $display("NOK %0d", n_nok);
        $display("MISMATCH %0d", nmis);
        if (m_first >= 0) $display("FIRST_MIS %0d cu %h ref %h", m_first, cu_c[m_first][71:0], rf_c[m_first][71:0]);

`ifdef TB_AFTERWRITE
        write_row(12'd5, rows[5]);
`endif
        axi_rd(10'h008); $display("STAT_END %h", rd_v);
        $display("DONE");
        $finish;
    end
endmodule
