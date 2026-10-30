// proj032 P-2 — spw_core（レジスタ ＋ 前段 ＋ wsb ＋ dsink）を ring128 と DDR の模型につないだ通しの sim。
//   PS の役: レジスタに窓を書き、CTRL に WRST ＋ RUN（水抜き → 取り込み → リセット → 明けて RUN）。20,000 クロックごとにリングを読む
//   照らしは 3 段を既存の照合で（記録は統合した RTL の中から取る）:
//     check_front: 頭の入口（粗い PFB の出口、front_c）→ ddcb の出口（front_y）を M-3 の整数の模型と bit 単位で
//     check_wsb:   wsb の入口（wsb_in）→ FFT の入口・出口 → ダンプ（wsb_dmp）を窓ごとの形の模型と bit 単位で
//     check_ring:  ダンプ → リングのレコード（頭・尾・CRC・f32 の本体・DUMP_F0・DUMP_T）
//   構成（sim を短くする）: H 6・G_L2 14（NS 1・2 だけ）・S 3（窓 3..5 は DDR の枠）・NG 1・NDUMP 2
//     lane 0: 窓 0 NS1・1 NS2・2 NS2（256 MHz）/ lane 1: 窓 3 NS2・5 NS1 / lane 2: 窓 4 NS2。DDR の窓の和 = 64 + 64 + 128 = 256 MHz
//   変種 -DCORE_STOP: 窓 2 を止める窓（WFL 3）にし、その枠を窓 0 と同じ 0 にする（spw_regs は止める窓の枠を数えない）。窓 2 は何も出さず、ほかの窓はそのまま
//   陽性対照 -DCORE_POSCTL: レジスタに書く窓 1 の NCO の増分を 1 だけ変える（記録の front_cfg は変えない）→ check_front の窓 1 が落ちる
//   P-6: コアの共通（core_cmn）と TP のレコード。共通部の読み書き（IF_ID・PROJ・NSTREAM・CAPS・GB_K・GB_STAT・ADC_STAT と 0x80 CORE_FLAGS の振り分け）を照らし、
//     TP_N 2・TP_REC_CTRL（4 個で 1 レコード）・TP_RUN を打つ。tb はリセットの明けから数えた 512 ビートのフレームごとに Σ(x16 >>> 2)² を tp_x.log に書き、
//     check_ring が TP のレコード（type 2）の個をこれと照らす（窓のレコードと同じリングに混ざる）
//   陽性対照 -DTPX_POSCTL: tp_x.log のフレーム 40 の和に 1 を足す（記録の側）→ その区切りを含む TP のレコードだけが落ちる
`timescale 1ns / 1ps
module tb_core;
    localparam integer H = 6, E = 3, S = 3, NK = 8, W = 20, G_L2 = 14;
`ifndef NCYC
`define NCYC 110000
`endif
`ifndef TAIL
`define TAIL 20000
`endif
    reg clk = 0; always #1.953 clk = ~clk;
    reg rst = 1;
    reg [2:0] ns [0:H-1]; reg [1:0] fl [0:H-1]; reg [5:0] wk [0:H-1]; reg [31:0] dp [0:H-1]; reg [3:0] sl [0:H-1];
    integer w;
    initial begin
        ns[0] = 1; ns[1] = 2; ns[2] = 2; fl[0] = 0; fl[1] = 0; fl[2] = 0;
        ns[3] = 2; ns[5] = 1; fl[3] = 1; fl[5] = 1;
        ns[4] = 2; fl[4] = 2;
        for (w = 0; w < H; w = w + 1) begin
            wk[w] = (w < H / 2) ? 2 * (w + 3) : 2 * (w - H / 2) + 5;   // 偶 6・8・10 / 奇 5・7・9
            dp[w] = 32'h0123_4567 * (w + 1);
            sl[w] = w;
        end
`ifdef CORE_STOP
        fl[2] = 3; sl[2] = 0;
`endif
    end
    // ---- ADC の入力: 雑音 ＋ CW（tb_front と同じ）----
    reg  [255:0] x; reg xv = 0;
    integer n = 0, l;
    real ph1 = 0, ph2 = 0, ph3 = 0, v;
    always @(posedge clk) begin
        for (l = 0; l < 16; l = l + 1) begin
            v = 1500.0 * ($dist_normal(n, 0, 1000) / 1000.0)
              + 3000.0 * $sin(ph1) + 800.0 * $sin(ph2) + 200.0 * $sin(ph3);
            ph1 = ph1 + 2.0 * 3.14159265358979 * 0.0911; ph2 = ph2 + 2.0 * 3.14159265358979 * 0.2137; ph3 = ph3 + 2.0 * 3.14159265358979 * 0.3301;
            x[l*16 +: 16] <= $rtoi(v);
            n = n + 1;
        end
        xv <= 1;
    end
    reg  [63:0] tnow = 64'h0000_0012_3456_7000;
    always @(posedge clk) tnow <= tnow + 64'd1;

    // ---- コア ----
    reg  [15:0] ca_aw, ca_ar; reg ca_awv = 0, ca_wv = 0, ca_arv = 0; reg [31:0] ca_wd;
    wire ca_awr, ca_wr, ca_bv, ca_arr, ca_rv; wire [31:0] ca_rd; wire [1:0] ca_br, ca_rr;
    wire [31:0] awaddr; wire [7:0] awlen; wire awvalid, awready, wlast, wvalid, wready, bvalid; wire [63:0] wdata;
    wire [E*32-1:0] araddr; wire [E-1:0] arvalid, arready, rvalid, rlast; wire [E*128-1:0] rdata;
    wire [127:0] st_d; wire st_v, st_r, st_l; wire [E:0] sdrop; wire [5:0] gbk;
    spw_core #(.H(H), .E(E), .S(S), .NK(NK), .W(W), .G_L2(G_L2), .NU(2), .ADC(0)) dut (.clk(clk), .rst(rst),
        .s_axi_awaddr(ca_aw), .s_axi_awvalid(ca_awv), .s_axi_awready(ca_awr), .s_axi_wdata(ca_wd), .s_axi_wvalid(ca_wv), .s_axi_wready(ca_wr),
        .s_axi_bvalid(ca_bv), .s_axi_bresp(ca_br), .s_axi_bready(1'b1),
        .s_axi_araddr(ca_ar), .s_axi_arvalid(ca_arv), .s_axi_arready(ca_arr), .s_axi_rdata(ca_rd), .s_axi_rvalid(ca_rv), .s_axi_rresp(ca_rr), .s_axi_rready(1'b1),
        .s_tdata(x), .s_tvalid(xv), .t_now(tnow), .fire(1'b0),
        .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(gbk), .gb_stat(32'h5A5A_0011), .adc_stat(32'h0000_C3C3),
        .m_awaddr(awaddr), .m_awlen(awlen), .m_awvalid(awvalid), .m_awready(awready), .m_wdata(wdata), .m_wlast(wlast),
        .m_wvalid(wvalid), .m_wready(wready), .m_bvalid(bvalid),
        .m_araddr(araddr), .m_arvalid(arvalid), .m_arready(arready), .m_rdata(rdata), .m_rvalid(rvalid), .m_rlast(rlast),
        .m_tdata(st_d), .m_tvalid(st_v), .m_tready(st_r), .m_tlast(st_l), .drop(sdrop));
    axi_mem_model #(.NR(E)) u_mem (.clk(clk), .rst(rst), .awaddr(awaddr), .awvalid(awvalid), .awready(awready),
        .wdata(wdata), .wvalid(wvalid), .wready(wready), .wlast(wlast), .bvalid(bvalid),
        .araddr(araddr), .arvalid(arvalid), .arready(arready), .rdata(rdata), .rvalid(rvalid), .rlast(rlast));

    // ---- リング → PS の DDR の模型（tb_wsb と同じ）----
    reg  [11:0] la_aw, la_ar; reg la_awv = 0, la_wv = 0, la_arv = 0; reg [31:0] la_wd;
    wire la_awr, la_wr, la_bv, la_arr, la_rv; wire [31:0] la_rd; wire [1:0] la_br, la_rr;
    wire [48:0] h_awaddr; wire [7:0] h_awlen; wire [2:0] h_awsize, h_awprot; wire [1:0] h_awburst; wire h_awlock; wire [3:0] h_awcache, h_awqos;
    wire h_awvalid, h_wlast, h_wvalid, h_bready; wire [127:0] h_wdata; wire [15:0] h_wstrb;
    reg  h_awready = 0, h_wready = 0, h_bvalid = 0;
    ring128 #(.NX(E + 1)) u_ring (.aclk(clk), .aresetn(!rst), .s_axis_tdata(st_d), .s_axis_tvalid(st_v), .s_axis_tready(st_r), .s_axis_tlast(st_l),
        .ext_drop(sdrop),
        .s_axi_awaddr(la_aw), .s_axi_awprot(3'd0), .s_axi_awvalid(la_awv), .s_axi_awready(la_awr), .s_axi_wdata(la_wd), .s_axi_wstrb(4'hF),
        .s_axi_wvalid(la_wv), .s_axi_wready(la_wr), .s_axi_bresp(la_br), .s_axi_bvalid(la_bv), .s_axi_bready(1'b1),
        .s_axi_araddr(la_ar), .s_axi_arprot(3'd0), .s_axi_arvalid(la_arv), .s_axi_arready(la_arr), .s_axi_rdata(la_rd), .s_axi_rresp(la_rr),
        .s_axi_rvalid(la_rv), .s_axi_rready(1'b1),
        .m_axi_awaddr(h_awaddr), .m_axi_awlen(h_awlen), .m_axi_awsize(h_awsize), .m_axi_awburst(h_awburst), .m_axi_awlock(h_awlock),
        .m_axi_awcache(h_awcache), .m_axi_awprot(h_awprot), .m_axi_awqos(h_awqos), .m_axi_awvalid(h_awvalid), .m_axi_awready(h_awready),
        .m_axi_wdata(h_wdata), .m_axi_wstrb(h_wstrb), .m_axi_wlast(h_wlast), .m_axi_wvalid(h_wvalid), .m_axi_wready(h_wready),
        .m_axi_bresp(2'b00), .m_axi_bvalid(h_bvalid), .m_axi_bready(h_bready));
    localparam integer RB = 32'h2000_0000, RS = 1 << 18;
    reg  [7:0]  rmem [0:RS-1];
    reg  [48:0] hq [0:63]; integer hqn = 0, hb_ = 0, hk, hj; integer bq_ [0:63]; integer bqn = 0;
    always @(posedge clk) begin
        h_awready <= ({$random} % 100) < 75;
        if (h_awvalid && h_awready) begin hq[hqn] = h_awaddr; hqn = hqn + 1; end
        if (h_wvalid && h_wready) begin
            for (hj = 0; hj < 16; hj = hj + 1) rmem[(hq[0] - RB + hb_ * 16 + hj) % RS] = h_wdata[hj*8 +: 8];
            hb_ = hb_ + 1;
            if (h_wlast) begin
                hb_ = 0; for (hk = 0; hk < 63; hk = hk + 1) hq[hk] = hq[hk + 1]; hqn = hqn - 1;
                bq_[bqn] = 20 + {$random} % 60; bqn = bqn + 1;
            end
        end
        h_wready <= (({$random} % 100) < 90) && hqn > 0;
        h_bvalid <= 0;
        if (bqn > 0) begin
            if (bq_[0] <= 0) begin h_bvalid <= 1; for (hk = 0; hk < 63; hk = hk + 1) bq_[hk] = bq_[hk + 1]; bqn = bqn - 1; end
            for (hk = 0; hk < bqn; hk = hk + 1) bq_[hk] = bq_[hk] - 1;
        end
    end
    // AXI4-Lite の書き・読み（コア・リング）
    task la_write(input [11:0] a, input [31:0] d);
        begin
            @(negedge clk); la_aw = a; la_wd = d; la_awv = 1; la_wv = 1;
            @(posedge clk); while (la_awr !== 1'b1) @(posedge clk);
            @(negedge clk); la_awv = 0; la_wv = 0;
        end
    endtask
    task wr(input [15:0] a, input [31:0] d);
        begin
            @(negedge clk); ca_aw = a; ca_wd = d; ca_awv = 1; ca_wv = 1;
            @(posedge clk); while (ca_awr !== 1'b1) @(posedge clk);
            @(negedge clk); ca_awv = 0; ca_wv = 0;
            @(posedge clk);
        end
    endtask
    reg [31:0] rv;
    task rd(input [15:0] a);
        begin
            @(negedge clk); ca_ar = a; ca_arv = 1;
            @(posedge clk); while (ca_arr !== 1'b1) @(posedge clk);
            @(negedge clk); ca_arv = 0;
            while (ca_rv !== 1'b1) @(posedge clk);
            rv = ca_rd; @(posedge clk);
        end
    endtask
    function [15:0] sb(input integer s, input [9:0] o); sb = 16'h4000 + 16'h400 * s + o; endfunction
    integer frg, rpos = 0, wpos, ri;
    task ps_drain;
        begin
            wpos = u_ring.w_pos;
            for (ri = rpos; ri < wpos; ri = ri + 16)
                $fwrite(frg, "%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x%02x\n",
                    rmem[(ri + 0) % RS], rmem[(ri + 1) % RS], rmem[(ri + 2) % RS], rmem[(ri + 3) % RS], rmem[(ri + 4) % RS], rmem[(ri + 5) % RS],
                    rmem[(ri + 6) % RS], rmem[(ri + 7) % RS], rmem[(ri + 8) % RS], rmem[(ri + 9) % RS], rmem[(ri + 10) % RS], rmem[(ri + 11) % RS],
                    rmem[(ri + 12) % RS], rmem[(ri + 13) % RS], rmem[(ri + 14) % RS], rmem[(ri + 15) % RS]);
            rpos = wpos;
            la_write(12'h018, rpos);
        end
    endtask
    initial begin
        frg = $fopen("wsb_ring.log", "w");
        repeat (30) @(posedge clk);
        la_write(12'h008, RB); la_write(12'h00C, 0); la_write(12'h010, RS); la_write(12'h004, 1);
        forever begin repeat (20000) @(posedge clk); ps_drain; end
    end

    // ---- 記録（統合した RTL の中から）----
    reg  dm_on = 1, seen = 0;                       // seen: 最初の WRST が明けた
    wire wrst = dut.u_regs.wrst;
    always @(posedge clk) if (wrst) seen <= 1'b1;
    wire          cv = dut.u_front.c_v;
    wire [24*H-1:0] cr = dut.u_front.c_re, ci = dut.u_front.c_im;
    wire [E-1:0]  fyv = dut.u_front.y_v;
    wire [E*4-1:0] fych = dut.u_front.y_ch;
    wire [E*W-1:0] fyr = dut.u_front.y_re, fyi = dut.u_front.y_im;
    wire [E-1:0]  wyv = dut.u_wsb.y_v;              // wsb の入口（rst_d で止めた後）
    integer fc, fy, ff, fin, ftl, e, nsmp [0:H-1];
    initial begin
        fc = $fopen("front_c.log", "w"); fy = $fopen("front_y.log", "w"); fin = $fopen("wsb_in.log", "w"); ftl = $fopen("wsb_t.log", "w");
        ff = $fopen("front_cfg.log", "w");
        for (w = 0; w < H; w = w + 1) begin $fwrite(ff, "%0d %0d %0d %0d %0d\n", w, ns[w], fl[w], wk[w], dp[w]); nsmp[w] = 0; end
        $fclose(ff);
    end
    // P-5: 粗い PFB の入口（rst の明けた後の valid なビート、16 × 16 bit の hex）と、front_c の行ごとの粗い PFB のフレーム番号（check_pfb_chain.py）
    integer fxl, fml, pfm = 0;
    initial begin fxl = $fopen("front_x.log", "w"); fml = $fopen("front_m.log", "w"); end
    always @(posedge clk) begin
        if (xv && !rst) $fwrite(fxl, "%064x\n", x);
        if (rst) pfm = 0; else if (cv) begin if (dm_on && seen && !wrst) $fwrite(fml, "%0d\n", pfm); pfm = pfm + 1; end
    end
    always @(posedge clk) if (dm_on && seen && !wrst) begin
        if (cv) begin
            for (w = 0; w < H; w = w + 1) $fwrite(fc, "%0d %0d ", $signed(cr[w*24 +: 24]), $signed(ci[w*24 +: 24]));
            $fwrite(fc, "\n");
        end
        for (e = 0; e < E; e = e + 1) begin
            if (fyv[e]) $fwrite(fy, "%0d %0d %0d %0d\n", e, fych[e*4 +: 4], $signed(fyr[e*W +: W]), $signed(fyi[e*W +: W]));
            if (wyv[e]) begin
                $fwrite(fin, "%0d %0d %0d\n", fych[e*4 +: 4], $signed(fyr[e*W +: W]), $signed(fyi[e*W +: W]));
                if (nsmp[fych[e*4 +: 4]] % 4096 == 0) $fwrite(ftl, "%0d %0d %0d\n", fych[e*4 +: 4], nsmp[fych[e*4 +: 4]] / 4096, tnow);
                nsmp[fych[e*4 +: 4]] = nsmp[fych[e*4 +: 4]] + 1;
            end
        end
    end
    integer ffi, ffo, fdm;
    initial begin ffi = $fopen("wsb_fi.log", "w"); ffo = $fopen("wsb_fo.log", "w"); fdm = $fopen("wsb_dmp.log", "w"); end
    wire [E-1:0] dv = dut.u_wsb.d_v; wire [E*4-1:0] dw = dut.u_wsb.d_w; wire [E*32-1:0] dk = dut.u_wsb.d_k;
    wire [E*12-1:0] dch = dut.u_wsb.d_ch; wire [E*64-1:0] dd = dut.u_wsb.d_data;
    genvar g;
    generate for (g = 0; g < E; g = g + 1) begin : lg
        wire        pv8 = dut.u_wsb.en[g].u.pv[8], pf8 = dut.u_wsb.en[g].u.pf[8];
        wire [58:0] tg8 = dut.u_wsb.en[g].u.tg8;
        wire [17:0] fr8 = dut.u_wsb.en[g].u.fr8, fi8 = dut.u_wsb.en[g].u.fi8;
        wire        mv  = dut.u_wsb.en[g].u.m_tv;
        wire [11:0] mk  = dut.u_wsb.en[g].u.m_tu[11:0];
        wire [63:0] md  = dut.u_wsb.en[g].u.m_td;
        wire [58:0] hd  = dut.u_wsb.en[g].u.tq_head;
        reg         ivld, ovld;
        always @(posedge clk) if (seen && !wrst) begin
            if (pv8 && dm_on) begin
                if (pf8) begin ivld = tg8[58]; if (ivld) $fwrite(ffi, "F %0d %0d\n", g, tg8[57:54]); end
                if (ivld) $fwrite(ffi, "%0d %0d %0d\n", g, $signed(fr8), $signed(fi8));
            end
            if (mv && dm_on) begin
                if (mk == 0) begin ovld = hd[58]; if (ovld) $fwrite(ffo, "O %0d %0d\n", g, hd[57:54]); end
                if (ovld) $fwrite(ffo, "%0d %0d %0d\n", g, $signed(md[31:0]), $signed(md[63:32]));
            end
            if (dv[g] && dm_on) $fwrite(fdm, "%0d %0d %0d %0d %0d\n", g, dw[g*4 +: 4], dk[g*32 +: 32], dch[g*12 +: 12], dd[g*64 +: 64]);
        end
    end endgenerate

    // P-6: TP の模型（リセットの明けから数えた 512 ビートのフレームごとの Σ(x16 >>> 2)²。core_cmn の a_cnt と同じビートを数える）
    integer ftp, tpl; reg [8:0] tpb = 0; reg [31:0] tpf = 0; reg [63:0] tps = 0; reg signed [15:0] tq; reg signed [31:0] tq2;
    initial ftp = $fopen("tp_x.log", "w");
    always @(posedge clk) if (!rst && xv) begin
        for (tpl = 0; tpl < 16; tpl = tpl + 1) begin tq = $signed(x[tpl*16 +: 16]) >>> 2; tq2 = tq * tq; tps = tps + tq2; end   // 符号つきの 32 bit で二乗してから足す
        if (tpb == 9'd511) begin
`ifdef TPX_POSCTL
            if (tpf == 40) tps = tps + 1;
`endif
            $fwrite(ftp, "%0d %0d\n", tpf, tps); tps = 0; tpf = tpf + 1;
        end
        tpb <= tpb + 9'd1;
    end

    // ---- PS の手順 ----
    integer frun, fails = 0;
    initial begin
        repeat (20) @(posedge clk);
        rst <= 0;
        repeat (20) @(posedge clk);
        rd(16'h0000); if (rv !== 32'h0207_0101) begin fails = fails + 1; $display("IF_ID %h", rv); end
        // P-6: コアの共通（core_cmn）と振り分け
        rd(16'h0004); if (rv !== 32'h0032_0200) begin fails = fails + 1; $display("PROJ %h", rv); end
        rd(16'h0008); if (rv !== H) begin fails = fails + 1; $display("NSTREAM %0d", rv); end
        rd(16'h000C); if (rv !== 32'd3) begin fails = fails + 1; $display("CAPS %h", rv); end
        rd(16'h002C); if (rv !== 32'd2 || gbk !== 6'd2) begin fails = fails + 1; $display("GB_K の既定 %0d・%0d", rv, gbk); end
        wr(16'h002C, 5); rd(16'h002C); if (rv !== 32'd5 || gbk !== 6'd5) begin fails = fails + 1; $display("GB_K %0d・%0d", rv, gbk); end
        rd(16'h0034); if (rv !== 32'h5A5A_0011) begin fails = fails + 1; $display("GB_STAT %h", rv); end
        rd(16'h0038); if (rv !== 32'h0000_C3C3) begin fails = fails + 1; $display("ADC_STAT %h", rv); end
        wr(16'h0084, 7); rd(16'h0084); if (rv !== 32'd7) begin fails = fails + 1; $display("NG（spw_regs）%0d", rv); end
        rd(16'h0080); if (rv !== 32'd0) begin fails = fails + 1; $display("CORE_FLAGS（spw_regs）%h", rv); end
        rd(16'h0114); if (rv !== 32'h0200_1002) begin fails = fails + 1; $display("TP_PARAM %h", rv); end
        wr(16'h0100, 2); wr(16'h011C, 32'h0000_0401); wr(16'h0020, 1);      // TP_N 2・TP_REC_CTRL（4 個・有効）・TP_RUN
        rd(16'h0104); if (rv !== 32'd2) begin fails = fails + 1; $display("TP_NEFF %0d", rv); end
        for (w = 0; w < H; w = w + 1) begin
            wr(sb(w, 10'h100), wk[w]);
`ifdef CORE_POSCTL
            wr(sb(w, 10'h104), (w == 1) ? dp[w] + 1 : dp[w]);
`else
            wr(sb(w, 10'h104), dp[w]);
`endif
            wr(sb(w, 10'h108), ns[w]); wr(sb(w, 10'h120), fl[w]); wr(sb(w, 10'h124), sl[w]);
            wr(sb(w, 10'h128), 10); wr(sb(w, 10'h014), 5 + w % 3);
        end
        wr(16'h0084, 1); wr(16'h0088, 2);
        wr(sb(0, 10'h008), 32'h1001);                         // WRST ＋ RUN
        wait (dut.u_regs.cmd_run); @(posedge clk); @(posedge clk);
        frun = $fopen("wsb_run.log", "w");
        $fwrite(frun, "g0 %0d G_L2 %0d E %0d CFG %0d G0A %0d AL 1\n", dut.u_wsb.g0, G_L2, E, 9, dut.u_wsb.g0a);
        for (w = 0; w < H; w = w + 1) $fwrite(frun, "w %0d %0d %0d %0d %0d %0d %0d\n", w, fl[w] < E, ns[w], fl[w], 5 + w % 3, sl[w] >= S, 10);
        $fclose(frun);
        rd(16'h0080); $display("CORE_FLAGS（RUN の直後）= %h", rv);
        repeat (`NCYC) @(posedge clk);
        dm_on = 0; $fclose(fc); $fclose(fy); $fclose(fin); $fclose(ftl); $fclose(ffi); $fclose(ffo); $fclose(fdm);
        repeat (`TAIL) @(posedge clk);
        $fclose(ftp);
        rd(16'h0108); $display("TP_WP %0d", rv);
        ps_drain;
        rd(16'h0080);
        $display("flags = %h dflags = %h CORE_FLAGS = %h front %b", dut.eng_flags, dut.dflags, rv, dut.fflags);
        $display("ring: REC_CNT %0d DROP_CNT %0d EXT_CNT %0d PEAK %0d sflags %h", u_ring.rec_cnt, u_ring.drop_cnt, u_ring.ext_cnt, u_ring.peak, dut.sflags);
        if (rv !== 32'd0) begin fails = fails + 1; $display("CORE_FLAGS が 0 でない"); end
        if (fails) $display("結果: 不合格 %0d（レジスタの読み）", fails); else $display("レジスタの読み: 結果: 全部通過");
        $fclose(frg);
        $finish;
    end
endmodule
