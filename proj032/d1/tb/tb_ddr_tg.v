// SPDX-License-Identifier: BSD-3-Clause
// proj028 S-2 — ddr_tg の試験台（proj032 D-1: T6 流れの番地・T7 その陽性対照を足した）。相手は AXI4 のメモリの模型（AW・AR を溜めて順に処理、wready・rvalid をランダムに落とす）
//   -DALIAS: 模型の番地を MEMB 拍で折り返す（4 GB の DDR に 8 GB の番地を出したときの形。容量の試験の陽性対照）
//   T1 書き 1 周 → T2 読み 1 周（誤り 0）→ T3 速さの上限をかけた同時の読み書き（DUR）→ T4 1 bit 化けを数える（陽性対照）
//   → T5 容量: 区間 A（0）と B（MEMB 拍）に違う SEED で書き、A を読む（ALIAS では A が B の値で上書きされ、誤りが出るはず）
`timescale 1ns/1ps
`default_nettype none
module tb_ddr_tg;
`ifdef AW33
    localparam integer AW = 33;
`else
    localparam integer AW = 32;                // 実機の MIG（8 Gb × 4 = 4 GiB）
`endif
    localparam integer MEMB = 4096;            // 模型の拍の数（256 KiB）
    reg clk = 0;
    always #1.667 clk = ~clk;                  // 300 MHz
    reg aresetn = 0;
    // AXI4-Lite
    reg  [7:0] awaddr = 0, araddr = 0; reg awvalid = 0, wvalid = 0, arvalid = 0; reg [31:0] wdata = 0;
    wire awready, wready, bvalid, arready, rvalid; wire [1:0] bresp, rresp; wire [31:0] rdata;
    // AXI4
    wire [AW-1:0] m_awaddr, m_araddr; wire [7:0] m_awlen, m_arlen; wire [2:0] m_awsize, m_arsize; wire [1:0] m_awburst, m_arburst;
    wire m_awvalid, m_wlast, m_wvalid, m_bready, m_arvalid, m_rready; wire [511:0] m_wdata; wire [63:0] m_wstrb;
    reg  m_awready = 0, m_wready = 0, m_bvalid = 0, m_arready = 0, m_rvalid = 0, m_rlast = 0;
    reg  [511:0] m_rdata = 0; reg [1:0] m_bresp = 0, m_rresp = 0;

    ddr_tg #(.AW(AW)) dut (
        .clk(clk), .aresetn(aresetn), .calib(1'b1),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_wdata(wdata), .s_axi_wvalid(wvalid),
        .s_axi_wready(wready), .s_axi_bvalid(bvalid), .s_axi_bresp(bresp), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rvalid(rvalid),
        .s_axi_rresp(rresp), .s_axi_rready(1'b1),
        .m_axi_awaddr(m_awaddr), .m_axi_awlen(m_awlen), .m_axi_awsize(m_awsize), .m_axi_awburst(m_awburst), .m_axi_awvalid(m_awvalid),
        .m_axi_awready(m_awready), .m_axi_wdata(m_wdata), .m_axi_wstrb(m_wstrb), .m_axi_wlast(m_wlast), .m_axi_wvalid(m_wvalid),
        .m_axi_wready(m_wready), .m_axi_bresp(m_bresp), .m_axi_bvalid(m_bvalid), .m_axi_bready(m_bready),
        .m_axi_araddr(m_araddr), .m_axi_arlen(m_arlen), .m_axi_arsize(m_arsize), .m_axi_arburst(m_arburst), .m_axi_arvalid(m_arvalid),
        .m_axi_arready(m_arready), .m_axi_rdata(m_rdata), .m_axi_rresp(m_rresp), .m_axi_rlast(m_rlast), .m_axi_rvalid(m_rvalid),
        .m_axi_rready(m_rready),
        .m_axi_awid(), .m_axi_awlock(), .m_axi_awcache(), .m_axi_awprot(), .m_axi_awqos(), .m_axi_bid(4'd0),
        .m_axi_arid(), .m_axi_arlock(), .m_axi_arcache(), .m_axi_arprot(), .m_axi_arqos(), .m_axi_rid(4'd0));

    // ---- メモリの模型 ----
    reg [511:0] mem [0:MEMB-1];
    function integer mi; input [AW-1:0] byte_a; reg [AW-1:0] b; begin
        b = byte_a >> 6;
`ifdef ALIAS
        mi = b % MEMB;
`else
        mi = (b < 2*MEMB) ? b % MEMB : 0;     // 区間 B（MEMB..2·MEMB−1）は別の配列に
`endif
    end endfunction
    reg [511:0] memb [0:MEMB-1];
    reg [AW-1:0] awq_a [0:15]; reg [7:0] awq_l [0:15]; reg [3:0] awq_h = 0, awq_t = 0;
    reg [AW-1:0] arq_a [0:15]; reg [7:0] arq_l [0:15]; reg [3:0] arq_h = 0, arq_t = 0;
    reg [7:0] wi = 0, ri = 0; reg r_act = 0;
    wire [3:0] awq_n = awq_t - awq_h, arq_n = arq_t - arq_h;   // 溜めの数（4 bit で差を取る。32 bit で比べると巻き戻りで負になる）
    integer seedr = 7;
    integer bpend = 0;
    reg [AW-1:0] wa_b, ra_b;
    always @(posedge clk) begin
        // AW・AR を受ける（溜めに空きがあれば、ときどき待たせる）
        m_awready <= awq_n < 4'd12 && ($random(seedr) % 4 != 0);
        m_arready <= arq_n < 4'd12 && ($random(seedr) % 4 != 0);
        if (m_awvalid && m_awready) begin awq_a[awq_t] <= m_awaddr; awq_l[awq_t] <= m_awlen; awq_t <= awq_t + 1; end
        if (m_arvalid && m_arready) begin arq_a[arq_t] <= m_araddr; arq_l[arq_t] <= m_arlen; arq_t <= arq_t + 1; end
        // W
        m_wready <= (awq_t != awq_h) && ($random(seedr) % 5 != 0);
        if (m_wvalid && m_wready) begin
            if (awq_t == awq_h) begin $display("ERROR: AW の無い W"); $finish; end
            wa_b = awq_a[awq_h] + (wi << 6);
            if ((wa_b >> 6) >= MEMB && (wa_b >> 6) < 2*MEMB) begin
`ifdef ALIAS
                mem[mi(wa_b)] <= m_wdata;
`else
                memb[(wa_b >> 6) - MEMB] <= m_wdata;
`endif
            end else mem[mi(wa_b)] <= m_wdata;
            if (m_wlast != (wi == awq_l[awq_h])) begin $display("ERROR: WLAST の位置（wi %0d・awlen %0d・dut w_cnt %0d・bl %0d・awq_h %0d・awq_t %0d・t %0t）", wi, awq_l[awq_h], dut.w_cnt, dut.r_bl, awq_h, awq_t, $time); $finish; end
            if (m_wlast) begin wi <= 0; awq_h <= awq_h + 1; bpend = bpend + 1; end else wi <= wi + 1;
        end
        // B
        if (m_bvalid && m_bready) m_bvalid <= 0;
        else if (!m_bvalid && bpend > 0) begin m_bvalid <= 1; bpend = bpend - 1; end
        // R
        if (m_rvalid && m_rready) begin
            m_rvalid <= 0;
            if (m_rlast) begin ri <= 0; arq_h <= arq_h + 1; end else ri <= ri + 1;
        end else if (!m_rvalid && arq_t != arq_h && ($random(seedr) % 4 != 0)) begin
            ra_b = arq_a[arq_h] + (ri << 6);
`ifdef ALIAS
            m_rdata <= mem[mi(ra_b)];
`else
            m_rdata <= ((ra_b >> 6) >= MEMB && (ra_b >> 6) < 2*MEMB) ? memb[(ra_b >> 6) - MEMB] : mem[mi(ra_b)];
`endif
            m_rlast <= (ri == arq_l[arq_h]);
            m_rvalid <= 1;
        end
    end

    integer fails = 0;
    // ---- AXI4-Lite の手続き ----
    // ready は posedge の直前の値で見る（negedge で見ると、bvalid の上がり下がりと競合して同じ書き込みを 2 回出した）
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
        rd_v = rdata;
        @(negedge clk);
    end endtask
    reg [63:0] v64;
    task rd64(input [7:0] a); begin rd(a); v64[31:0] = rd_v; rd(a + 4); v64[63:32] = rd_v; end endtask
    task wait_idle; integer k; begin
        k = 0; rd(8'h40);
        while ((rd_v[3] !== 1'b1 || rd_v[2:1] != 2'b00) && k < 400000) begin rd(8'h40); k = k + 1; end
        if (k >= 400000) begin $display("ERROR: 終わらない（STATUS %h）", rd_v); $finish; end
    end endtask
    task setup(input [7:0] bl, input [31:0] base, input [31:0] size, input [31:0] seed, input [16:0] wrate, input [16:0] rrate, input [31:0] dur); begin
        wr(8'h08, bl); wr(8'h14, base); wr(8'h18, 0); wr(8'h1C, size); wr(8'h20, 0); wr(8'h24, seed);
        wr(8'h0C, wrate); wr(8'h10, rrate); wr(8'h28, dur);
        wr(8'h34, bl); wr(8'h2C, 0); wr(8'h38, 0);       // proj032: 読み手も同じ BL・順の運転
    end endtask
    // proj032: AW の番地を記録する（T6 で流れの番地の並びを照らす）
    reg [AW-1:0] aw_log [0:63]; integer aw_n = 0; reg aw_rec = 0;
    always @(posedge clk) if (aw_rec && m_awvalid && m_awready && aw_n < 64) begin aw_log[aw_n] <= m_awaddr; aw_n <= aw_n + 1; end

    task expect64(input [8*96-1:0] what, input [63:0] got, input [63:0] lo, input [63:0] hi); begin
        if (got < lo || got > hi) begin $display("  ×  %0s = %0d（期待 %0d〜%0d）", what, got, lo, hi); fails = fails + 1; end
        else $display("  ○  %0s = %0d", what, got);
    end endtask

    reg [63:0] wb, rb, er, cy;
    initial begin
        // T0 リセット中の読みは受けない（2026-10-23 の実機で、リセット中に AR の握手が成立して応答が返らず PS ごと止まった）
        repeat (3) @(posedge clk);
        @(negedge clk); araddr = 8'h00; arvalid = 1;
        repeat (10) begin @(posedge clk); if (arready === 1'b1) begin $display("  ×  T0: リセット中に arready が立った"); fails = fails + 1; end end
        @(negedge clk); awaddr = 8'h04; wdata = 0; awvalid = 1; wvalid = 1;
        repeat (5) begin @(posedge clk); if (awready === 1'b1) begin $display("  ×  T0: リセット中に awready が立った"); fails = fails + 1; end end
        @(negedge clk); awvalid = 0; wvalid = 0;
        aresetn = 1;
        @(posedge clk); while (arready !== 1'b1) @(posedge clk);
        @(negedge clk); arvalid = 0;
        while (rvalid !== 1'b1) @(negedge clk);
        if (rdata !== 32'h0320_0D11) begin $display("  ×  T0: リセット明けの読みが %h", rdata); fails = fails + 1; end
        else $display("T0 リセット中の読みは待たされ、明けてから返った（ID %h）", rdata);
        @(negedge clk); repeat (5) @(posedge clk);
        rd(8'h00); $display("ID %h", rd_v);
        // T1 書き 1 周（BL 16 拍、256 KiB = 4096 拍）
        $display("T1 書き 1 周");
        setup(15, 0, MEMB * 64, 32'h1111_0000, 65536, 65536, 0);
        wr(8'h04, 32'b101); wait_idle;
        rd64(8'h50); expect64("WR_BEATS", v64, MEMB, MEMB);
        rd(8'h44); expect64("FLAGS", rd_v, 0, 0);
        // T2 読み 1 周
        $display("T2 読み 1 周");
        wr(8'h04, 32'b110); wait_idle;
        rd64(8'h58); expect64("RD_BEATS", v64, MEMB, MEMB);
        rd64(8'h68); expect64("RD_ERR", v64, 0, 0);
        rd64(8'h70); $display("     FIRST_ERR_ADDR %0d（拍 %0d）", v64, v64 >> 6);
        // T3 同時（各 1/4 拍）、20000 拍の窓。BL 64 拍
        $display("T3 同時の読み書き（WR_RATE・RD_RATE = 1/4）");
        setup(63, 0, MEMB * 64, 32'h1111_0000, 16384, 16384, 20000);
        wr(8'h04, 32'b011); wait_idle;
        rd64(8'h48); cy = v64; expect64("CYC", cy, 20000, 20001);
        rd64(8'h50); expect64("WR_BEATS (~5000)", v64, 4800, 5100);
        rd64(8'h58); expect64("RD_BEATS (~5000)", v64, 4700, 5100);
        rd64(8'h68); expect64("RD_ERR", v64, 0, 0);
        // T3b 速さの上限なし（模型の待たせ方で決まる。数えが動くことだけ）
        $display("T3b 同時・上限なし（BL 256 拍）");
        setup(255, 0, MEMB * 64, 32'h1111_0000, 65536, 65536, 20000);
        wr(8'h04, 32'b011); wait_idle;
        rd64(8'h50); wb = v64; rd64(8'h58); rb = v64; rd64(8'h60);
        $display("     WR_BEATS %0d・RD_BEATS %0d・WR_WAIT %0d（20000 拍）", wb, rb, v64);
        expect64("WR_BEATS > 5000", wb, 5001, 20000);
        rd64(8'h68); expect64("RD_ERR", v64, 0, 0);
        // T4 陽性対照: 1 bit 化け
        $display("T4 陽性対照: 拍 100 の 1 bit を化けさせて読む");
        mem[100][300] = ~mem[100][300];
        setup(15, 0, MEMB * 64, 32'h1111_0000, 65536, 65536, 0);
        wr(8'h04, 32'b110); wait_idle;
        rd64(8'h68); expect64("RD_ERR", v64, 1, 1);
        rd64(8'h70); expect64("FIRST_ERR_ADDR", v64, 100 * 64, 100 * 64);
        rd(8'h44); expect64("FLAGS", rd_v, 1, 1);
        mem[100][300] = ~mem[100][300];
        // T5 容量: A（0）に SEED 1、B（MEMB 拍）に SEED 2、A を SEED 1 で読む
        $display("T5 容量の試験（区間 B = 拍 %0d から）", MEMB);
        setup(15, 0, MEMB * 64, 32'hAAAA_0001, 65536, 65536, 0);
        wr(8'h04, 32'b101); wait_idle;
        setup(15, MEMB * 64, MEMB * 64, 32'hBBBB_0002, 65536, 65536, 0);
        wr(8'h04, 32'b101); wait_idle;
        setup(15, 0, MEMB * 64, 32'hAAAA_0001, 65536, 65536, 0);
        wr(8'h04, 32'b110); wait_idle;
        rd64(8'h68); er = v64;
`ifdef ALIAS
        expect64("RD_ERR (alias: all)", er, MEMB, MEMB);
`else
        expect64("RD_ERR (no alias)", er, 0, 0);
`endif
`ifndef ALIAS
        // T6 proj032: 流れの番地。書き手 14 本 × 区画 16 KiB（BL 16 拍）、読み手 14 本 × 16 KiB（BL_R 128 拍）、各 1/4、30000 拍
        $display("T6 流れの番地（書き 14 本・BL 16、読み 14 本・BL_R 128、各 1/4）");
        setup(15, 0, MEMB * 64, 32'h1111_0000, 65536, 65536, 0);
        wr(8'h04, 32'b101); wait_idle;                     // 範囲を SEED 1111 で書いておく
        setup(15, 0, MEMB * 64, 32'h1111_0000, 16384, 16384, 30000);
        wr(8'h2C, 14); wr(8'h30, 16384); wr(8'h34, 127); wr(8'h38, 14); wr(8'h3C, 16384);
        aw_n = 0; aw_rec = 1;
        wr(8'h04, 32'b011); wait_idle; aw_rec = 0;
        rd64(8'h50); expect64("WR_BEATS (~7500)", v64, 7000, 7600);
        rd64(8'h58); expect64("RD_BEATS (~7500)", v64, 6900, 7700);
        rd64(8'h68); expect64("RD_ERR", v64, 0, 0);
        // 番地の並び: n 番目は (n mod 14)·16384 ＋ (n div 14)·1024
        begin : chk_aw
            integer n, bad; bad = 0;
            for (n = 0; n < 32; n = n + 1)
                if (aw_log[n] !== (n % 14) * 16384 + (n / 14) * 1024) begin
                    if (bad < 3) $display("     AW %0d: %0d（期待 %0d）", n, aw_log[n], (n % 14) * 16384 + (n / 14) * 1024);
                    bad = bad + 1;
                end
            expect64("AW の番地の並びの違い", bad, 0, 0);
        end
        // T7 陽性対照: 流れ 5 の区画の中の 1 拍を化けさせる → 読み手が数える
        $display("T7 陽性対照: 流れ 5 の区画の拍 5·256 + 20 を化けさせて T6 と同じ読みだけ");
        mem[5 * 256 + 20][7] = ~mem[5 * 256 + 20][7];
        setup(15, 0, MEMB * 64, 32'h1111_0000, 65536, 16384, 30000);
        wr(8'h34, 127); wr(8'h38, 14); wr(8'h3C, 16384);
        wr(8'h04, 32'b010); wait_idle;
        rd64(8'h68); expect64("RD_ERR ≧ 1", v64, 1, 1000);
        rd64(8'h70); expect64("FIRST_ERR_ADDR", v64, (5 * 256 + 20) * 64, (5 * 256 + 20) * 64);
        mem[5 * 256 + 20][7] = ~mem[5 * 256 + 20][7];
`endif
`ifdef ALIAS
        if (fails == 0) $display("結果: 陽性対照（ALIAS）: 折り返しを数えた。ほかも全部期待どおり"); else $display("結果: 不合格");
`else
        if (fails == 0) $display("結果: 全部通過"); else $display("結果: 不合格");
`endif
        $finish;
    end
    initial begin #20_000_000; $display("ERROR: 時間切れ"); $finish; end
endmodule
`default_nettype wire
