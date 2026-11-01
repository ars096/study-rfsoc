// SPDX-License-Identifier: BSD-3-Clause
// proj037 U-d — s2_s45_core（fine_core はスタブ）→ s45_ring（NIN 1）→ 止まりをランダムに入れる記憶。尾の CRC を見る
//
//   時刻と入力は tb_s2_strm と同じ（t_in = Tc + 1・go_in = (Tc + 1 == START_AT)、s_axis は「入口の T が Tc − 1」の雑音）。
//   STAGE2・RAW・コアの TP に同じ入力。コアの 16 bit の番地で:
//     STAGE2（0x4000）: N_DUMP・CFG_ID・REC_CTRL ALL・GAIN → CTRL ARM_RUN
//     RAW（0x4400）   : N_ACC 1・N_DUMP 2・REC_CTRL ALL → CTRL ARM_RUN（同じ go）
//   リング: BASE 0x1_2345_6040（256 バイト境でない）・SIZE 64 KiB・EN。記憶の AW・W の ready と B の遅れはランダム。
//     見張り（tb_ring_u と同じ）: 16 拍以下・16 バイト境・4 KiB の境を越えない・リングの中・wlast の位置
//   `RING_FLIP: 記憶に書かれたリングの 64 バイト目（最初のレコードの本体の語 0）の bit 0 を反転して書く（陽性対照）
//   書き出し: OUT_REC コアの出口の語「tlast tuser 語」・OUT_RING 終わりに [0, W) をレコードごとに「R 位置 語…」・OUT_REG リングのレジスタ
`timescale 1ns/1ps
`default_nettype none
module tb_s2_ring;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg aresetn = 0;
    reg [63:0] Tc = `T_BEGIN;
    always @(posedge clk) Tc <= Tc + 64'd1;
    wire [63:0] t_in = Tc + 64'd1;
    wire go_in = (Tc + 64'd1 == `START_AT);
    integer seed = 21, p;
    reg [255:0] d;
    reg signed [13:0] xs;
    always @(posedge clk) begin
        for (p = 0; p < 16; p = p + 1) begin
            xs = $random(seed) % 1024;
            d[16*p +: 16] <= {xs, 2'b00};
        end
    end
    // ---- コア ----
    reg  [15:0] aw = 0, ar = 0;
    reg         awv = 0, arv = 0;
    reg  [31:0] wd = 0;
    wire        awr, wr_, bv, arr, rv;
    wire [31:0] rdat;
    wire [511:0] ct_d; wire ct_u, ct_v;
    reg  [511:0] f_d = 0; reg [21:0] f_u = 0; reg f_l = 0, f_v = 0; wire f_r;
    wire [63:0] r_d; wire r_v, r_l, r_u, r_r; wire [1:0] drop;
    s2_s45_core #(.B_C(`B_C), .BASE_BEATS(`BASE), .REC_W(4), .RAW_N_ACC_DEFAULT(1)) dut (.aclk(clk), .aresetn(aresetn),
        .s_axis_tdata(d), .s_axis_tvalid(aresetn), .s_axis_tready(),
        .s_axis_s2_tdata(d), .s_axis_s2_tvalid(aresetn), .s_axis_s2_tready(), .s2_sel(),
        .ct_y(ct_d), .ct_mark(ct_u), .ct_valid(ct_v),
        .s_axis_ct_tdata(f_d), .s_axis_ct_tuser(f_u), .s_axis_ct_tlast(f_l), .s_axis_ct_tvalid(f_v), .s_axis_ct_tready(f_r),
        .s_axis_raw_tdata(d), .s_axis_raw_tvalid(aresetn), .s_axis_raw_tready(), .raw_sel(),
        .s_axi_awaddr(aw), .s_axi_awprot(3'd0), .s_axi_awvalid(awv), .s_axi_awready(awr),
        .s_axi_wdata(wd), .s_axi_wstrb(4'hF), .s_axi_wvalid(awv), .s_axi_wready(wr_), .s_axi_bresp(),
        .s_axi_bvalid(bv), .s_axi_bready(1'b1),
        .s_axi_araddr(ar), .s_axi_arprot(3'd0), .s_axi_arvalid(arv), .s_axi_arready(arr),
        .s_axi_rdata(rdat), .s_axi_rresp(), .s_axi_rvalid(rv), .s_axi_rready(1'b1),
        .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(32'd0), .adc_stat(32'd0),
        .t_in(t_in), .go_in(go_in), .tev_in(4'd0),
        .m_axis_rec_tdata(r_d), .m_axis_rec_tvalid(r_v), .m_axis_rec_tready(r_r), .m_axis_rec_tlast(r_l), .m_axis_rec_tuser(r_u),
        .rec_drop(drop));
    // ---- リング ----
    localparam [48:0] RBASE = 49'h1_2345_6040;
    localparam integer SIZE = 65536;
    reg  [11:0] gaw = 0, gar = 0;
    reg  [31:0] gwd = 0;
    reg         gawv = 0, garv = 0;
    wire        gawr, gwr, gbv, garr, grv;
    wire [31:0] grd;
    wire [48:0]  m_awaddr;
    wire [7:0]   m_awlen;
    wire [2:0]   m_awsize;
    wire [1:0]   m_awburst;
    wire [3:0]   m_awcache;
    wire         m_awvalid, m_wlast, m_wvalid, m_bready;
    wire [127:0] m_wdata;
    reg          aw_ok = 0, w_ok = 0, m_bvalid = 0, in_burst = 0;
    wire         m_awready = aw_ok && !in_burst;
    wire         m_wready  = w_ok && in_burst;
    s45_ring #(.NIN(1), .BIT_KIND(12), .BIT_REV(1), .PROJ(3604736)) u_ring (.aclk(clk), .aresetn(aresetn),
        .s0_axis_tdata(r_d), .s0_axis_tvalid(r_v), .s0_axis_tready(r_r), .s0_axis_tlast(r_l), .s0_axis_tuser(r_u),
        .s1_axis_tdata(64'd0), .s1_axis_tvalid(1'b0), .s1_axis_tready(), .s1_axis_tlast(1'b0), .s1_axis_tuser(1'b0),
        .s2_axis_tdata(64'd0), .s2_axis_tvalid(1'b0), .s2_axis_tready(), .s2_axis_tlast(1'b0), .s2_axis_tuser(1'b0),
        .s3_axis_tdata(64'd0), .s3_axis_tvalid(1'b0), .s3_axis_tready(), .s3_axis_tlast(1'b0), .s3_axis_tuser(1'b0),
        .rec_drop0(drop), .rec_drop1(2'd0), .rec_drop2(2'd0), .rec_drop3(2'd0),
        .s_axi_awaddr(gaw), .s_axi_awprot(3'd0), .s_axi_awvalid(gawv), .s_axi_awready(gawr),
        .s_axi_wdata(gwd), .s_axi_wstrb(4'hF), .s_axi_wvalid(gawv), .s_axi_wready(gwr),
        .s_axi_bresp(), .s_axi_bvalid(gbv), .s_axi_bready(1'b1),
        .s_axi_araddr(gar), .s_axi_arprot(3'd0), .s_axi_arvalid(garv), .s_axi_arready(garr),
        .s_axi_rdata(grd), .s_axi_rresp(), .s_axi_rvalid(grv), .s_axi_rready(1'b1),
        .m_axi_awaddr(m_awaddr), .m_axi_awlen(m_awlen), .m_axi_awsize(m_awsize), .m_axi_awburst(m_awburst),
        .m_axi_awlock(), .m_axi_awcache(m_awcache), .m_axi_awprot(), .m_axi_awqos(),
        .m_axi_awvalid(m_awvalid), .m_axi_awready(m_awready),
        .m_axi_wdata(m_wdata), .m_axi_wstrb(), .m_axi_wlast(m_wlast), .m_axi_wvalid(m_wvalid), .m_axi_wready(m_wready),
        .m_axi_bresp(2'b00), .m_axi_bvalid(m_bvalid), .m_axi_bready(m_bready));
    // ---- HP0 の代わりの記憶（tb_ring_u と同じ見張り）----
    reg  [127:0] mem [0:SIZE/16-1];
    integer nerr = 0, nburst = 0, cur_n, cur_len, bq_done = 0, bq_r = 0, mseed = 7;
    reg  [48:0]  cur_a;
    always @(posedge clk) begin
        aw_ok <= ($random(mseed) & 3) != 0;
        w_ok  <= ($random(mseed) & 3) != 0;
        if (m_awvalid && m_awready) begin
            nburst = nburst + 1;
            cur_a <= m_awaddr; cur_n <= 0; cur_len <= m_awlen + 1; in_burst <= 1;
            if (m_awlen > 15) begin $display("tb_s2_ring: NG バーストが 16 拍より長い"); nerr = nerr + 1; end
            if (m_awaddr[3:0] != 0) begin $display("tb_s2_ring: NG 16 バイト境でない %h", m_awaddr); nerr = nerr + 1; end
            if ((m_awaddr[11:0] + 16 * (m_awlen + 1)) > 4096) begin $display("tb_s2_ring: NG 4 KiB の境を越える %h", m_awaddr); nerr = nerr + 1; end
            if (m_awaddr < RBASE || m_awaddr + 16 * (m_awlen + 1) > RBASE + SIZE) begin $display("tb_s2_ring: NG リングの外 %h", m_awaddr); nerr = nerr + 1; end
            if (m_awsize != 3'b100 || m_awburst != 2'b01 || m_awcache != 4'b0011) begin $display("tb_s2_ring: NG awsize・awburst・awcache"); nerr = nerr + 1; end
        end
        if (m_wvalid && m_wready) begin
`ifdef RING_FLIP
            if ((cur_a - RBASE) / 16 + cur_n == 4) mem[4] <= m_wdata ^ 128'd1; else
`endif
            mem[(cur_a - RBASE) / 16 + cur_n] <= m_wdata;
            cur_n <= cur_n + 1;
            if (m_wlast != (cur_n + 1 == cur_len)) begin $display("tb_s2_ring: NG wlast の位置"); nerr = nerr + 1; end
            if (cur_n + 1 == cur_len) begin in_burst <= 0; bq_done = bq_done + 1; end
        end
        if (m_bvalid && m_bready) begin m_bvalid <= 0; bq_r = bq_r + 1; end
        else if (!m_bvalid && bq_r < bq_done && ($random(mseed) & 7) == 0) m_bvalid <= 1;
    end
    // ---- AXI4-Lite（コア・リング）----
    task wr(input [15:0] a, input [31:0] v); begin
        @(negedge clk); aw = a; wd = v; awv = 1;
        @(posedge clk); while (!awr) @(posedge clk);
        @(negedge clk); awv = 0;
        @(posedge clk); while (!bv) @(posedge clk);
        repeat (2) @(posedge clk);
    end endtask
    task gw(input [11:0] a, input [31:0] v); begin
        @(negedge clk); gaw = a; gwd = v; gawv = 1;
        @(posedge clk); while (!(gawr && gwr)) @(posedge clk);
        @(negedge clk); gawv = 0;
        while (!gbv) @(posedge clk);
        repeat (2) @(posedge clk);
    end endtask
    reg [31:0] rq;
    task gr(input [11:0] a); begin
        @(negedge clk); gar = a; garv = 1;
        @(posedge clk); while (!garr) @(posedge clk);
        @(negedge clk); garv = 0;
        while (!grv) @(posedge clk);
        rq = grd;
        repeat (2) @(posedge clk);
    end endtask
    // ---- 記録 ----
    integer fr, fo, fg, nrec = 0, k;
    always @(posedge clk) if (r_v && r_r) begin $fwrite(fr, "%0d %0d %h\n", r_l, r_u, r_d); if (r_l) nrec = nrec + 1; end
    task wait_rec(input integer n); begin while (nrec < n) @(posedge clk); repeat (20) @(posedge clk); end endtask
    integer seedf = 5, nbeat;
    task feed(input integer c, input integer kq, input integer nt, input integer nb); integer bb, ii; begin
        nbeat = (nt + nb) * 256;
        bb = 0;
        while (bb < nbeat) begin
            @(negedge clk);
            f_v = 1;
            for (ii = 0; ii < 32; ii = ii + 1) f_d[16*ii +: 16] = {$random(seedf)} % 65536 & 16'h1F1F;
            f_u = {c[15:0], kq[4:0], (bb < nt * 256) ? 1'b1 : 1'b0};
            f_l = (bb == nbeat - 1);
            @(posedge clk); if (f_r) bb = bb + 1;
        end
        @(negedge clk); f_v = 0; f_l = 0;
    end endtask
    // 読み手（終わりに 1 回）: [0, W) をレコードごとに
    function [63:0] mw(input [31:0] pos);
        reg [127:0] b;
        begin b = mem[(pos % SIZE) / 16]; mw = pos[3] ? b[127:64] : b[63:0]; end
    endfunction
    reg [31:0] wnow, pp, len, ty;
    reg [63:0] w0, w7;
    initial begin
        fr = $fopen(`OUT_REC, "w"); fo = $fopen(`OUT_RING, "w"); fg = $fopen(`OUT_REG, "w");
        repeat (10) @(posedge clk); @(negedge clk); aresetn = 1;
        repeat (10) @(posedge clk);
        gw(12'h008, RBASE[31:0]); gw(12'h00C, {15'd0, RBASE[48:32]}); gw(12'h010, SIZE); gw(12'h004, 32'd1);
        wr(16'h4010, `NDUMP);
        wr(16'h402C, 32'h0000_CF01);
        wr(16'h4084, 32'd1);
        for (k = 0; k < 32; k = k + 1) wr(16'h4100 + 4 * k, (k == 0) ? 262143 : 40000 + 2000 * k);
        wr(16'h440C, 32'd1); wr(16'h4410, 32'd2); wr(16'h4484, 32'd1);
        wr(16'h4008, 32'd4); wr(16'h4408, 32'd4);
        while (Tc < `START_AT + 2400) @(posedge clk);
        `FEED_LIST
        repeat (3000) @(posedge clk);
        gr(12'h014); wnow = rq; $fwrite(fg, "W %0d\n", rq);
        gr(12'h004); $fwrite(fg, "CTRL %0d\n", rq);
        gr(12'h01C); $fwrite(fg, "DROP_CNT %0d\n", rq);
        gr(12'h020); $fwrite(fg, "REC_CNT %0d\n", rq);
        gr(12'h028); $fwrite(fg, "ERR_STAT %0d\n", rq);
        gr(12'h000); $fwrite(fg, "IF_ID %0d\n", rq);
        $fwrite(fg, "NERR %0d\n", nerr);
        $fwrite(fg, "NBURST %0d\n", nburst);
        pp = 0;
        while (pp < wnow) begin
            w0 = mw(pp); w7 = mw(pp + 56); ty = w0[47:40];
            len = (ty == 0) ? w7[31:0] : 64 + w7[31:0] + 64;
            $fwrite(fo, "R %0d", pp);
            for (k = 0; k < len / 8 && (ty != 0 || k < 8); k = k + 1) $fwrite(fo, " %h", mw(pp + 8 * k));
            $fwrite(fo, "\n");
            pp = pp + len;
        end
        $display("done recs_core %0d W %0d bursts %0d nerr %0d", nrec, wnow, nburst, nerr);
        $fclose(fr); $fclose(fo); $fclose(fg);
        $finish;
    end
endmodule
`default_nettype wire
