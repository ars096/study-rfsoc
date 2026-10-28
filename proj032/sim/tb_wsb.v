// tb_wsb — 窓の分光の後段（wsb: 機関 E 組 ＋ 履歴の枠 ＋ 積分器）を、窓ごとの形と照らす（E-4・M-1）
//   入口は final の lane の形を真似る: 窓 w は 2^NS クロックに 1 標本が「来るべき」になり、lane は来るべき窓のうち NS の小さい・番号の小さい窓から 1 / クロック出す。
//   記録（sim/check_wsb.py が照らす）: in（窓ごとの入口の標本）・fi（FFT の入口の枠、札つき）・fo（FFT の出口の枠、札つき）・dmp（閉じたダンプの流れ）・run（g0）
//   構成（`CFG）: 0 3 lane とも幅の和 256 MHz（6・2・6 窓、NS を混ぜる）/ 1 2 lane（128 + 64 + 32 + 16 + 8 + 8・32 × 8）/ 2 1 lane に 128 × 2 だけ
//   陽性対照 ENG_POSCTL（eng.v）: 選びの NS の優先を外す → 幅の広い窓が遅れ、flags[1] と値の不一致
//   K-2: 閉じたダンプの流れ → dsink（f32・機関ごとの溜め NU 個の URAM、TB_NU）→ ring128 → PS の DDR の模型（hp_mem、+HP_SLOW で wready 3 %）。
//     PS の役: 20,000 クロックごとに W を読み、[R, W) を wsb_ring.log に写して R = W（sim/check_ring.py が dmp と照らす）
//   D-2: 窓 w ≧ TB_S は履歴を DDR に（枠 w、DDR の枠 w − TB_S、8 bit の利得 g = 10）。DDR は sim/axi_mem_model.v（遅れ 20〜300 クロック、+MEM_SLOW で 1500〜2500）
`timescale 1ns / 1ps
module tb_wsb;
    localparam integer H = 14, W = 20;
`ifndef CFG
`define CFG 0
`endif
`ifndef G_L2
`define G_L2 17
`endif
`ifndef NCYC
`define NCYC 900000
`endif
`ifndef DLY
`define DLY 1024
`endif
`ifndef TB_S
`define TB_S 14
`endif
`ifndef TB_NU
`define TB_NU 2
`endif
    localparam integer E = (`CFG == 0) ? 3 : (`CFG == 1) ? 2 : 1;
    reg clk = 0; always #1.953 clk = ~clk;
    reg rst = 1;
    reg [2:0] ns [0:H-1];
    reg [1:0] fl [0:H-1];
    reg [H-1:0] act;
    integer w;
    initial begin
        for (w = 0; w < H; w = w + 1) begin ns[w] = 5; fl[w] = 0; end
        act = {H{1'b1}};
        if (`CFG == 0) begin
            ns[0] = 5; ns[1] = 5; ns[2] = 4; ns[3] = 3; ns[4] = 2; ns[5] = 1;              // lane 0: 8 + 8 + 16 + 32 + 64 + 128（番号の小さい窓ほど狭い）
            ns[6] = 1; ns[7] = 1; fl[6] = 1; fl[7] = 1;                                      // lane 1: 128 × 2
            ns[8] = 4; ns[9] = 4; ns[10] = 3; ns[11] = 2; ns[12] = 2; ns[13] = 2;            // lane 2: 16 + 16 + 32 + 64 × 3
            for (w = 8; w < 14; w = w + 1) fl[w] = 2;
        end else if (`CFG == 1) begin
            ns[0] = 5; ns[1] = 5; ns[2] = 4; ns[3] = 3; ns[4] = 2; ns[5] = 1;
            for (w = 6; w < 14; w = w + 1) begin ns[w] = 3; fl[w] = 1; end
        end else begin
            ns[0] = 1; ns[1] = 1;
            act = 14'b00000000000011;
        end
    end
    wire [H*3-1:0] cfg_ns; wire [H*4-1:0] cfg_sl; wire [H*2-1:0] cfg_fl; wire [H*4-1:0] cfg_sh, cfg_g;
    genvar g;
    generate for (g = 0; g < H; g = g + 1) begin : cf
        assign cfg_ns[g*3 +: 3] = ns[g]; assign cfg_fl[g*2 +: 2] = fl[g];
        assign cfg_sl[g*4 +: 4] = g;     assign cfg_sh[g*4 +: 4] = 4'd5 + g % 3;
        assign cfg_g[g*4 +: 4]  = 4'd10;
    end endgenerate

    // ---- 入口: lane ごとに、来るべき標本の数 due[w] から NS・番号の小さい順に 1 / クロック ----
    integer due [0:H-1];
    integer tick, e, best;
    reg  [E-1:0]   yv;
    reg  [E*4-1:0] ych;
    reg  [E*W-1:0] yr, yi;
    reg  signed [W-1:0] vr, vi;
    integer fin, rr;
    reg     dm_on = 1;                    // 記録を取っている（終わりの待ちの間は取らない）
    // R-1: time_core の T の真似（上位の bit も通るよう大きな値から）。窓ごとにフレームの頭（標本 4096·r）が入口に入るビートを wsb_t.log に
    reg  [63:0] tnow = 64'h0000_0012_3456_7000;
    always @(posedge clk) tnow <= tnow + 64'd1;
    integer nsmp [0:H-1];
    integer ftl;
    initial begin ftl = $fopen("wsb_t.log", "w"); for (w = 0; w < H; w = w + 1) nsmp[w] = 0; end
    initial begin
        fin = $fopen("wsb_in.log", "w");
        for (w = 0; w < H; w = w + 1) due[w] = 0;
        tick = 0; yv = 0;
    end
    always @(posedge clk) begin
        yv <= 0;
        if (!rst) begin
            tick = tick + 1;
            for (w = 0; w < H; w = w + 1)
                if (act[w] && ((tick + 7 * w) % (1 << ns[w])) == 0) due[w] = due[w] + 1;
            for (e = 0; e < E; e = e + 1) begin
                best = -1;
                for (w = H - 1; w >= 0; w = w - 1)
                    if (fl[w] == e && due[w] > 0 && (best < 0 || ns[w] <= ns[best])) best = w;
                if (best >= 0) begin
                    due[best] = due[best] - 1;
                    // 値: 多くは 18 bit に収まる大きさ、まれに 20 bit の端（入口の飽和を通す）
                    rr = $random; vr = rr >>> 15; if (($random & 255) == 0) vr = ($random & 1) ? 20'sh7FFFF : 20'sh80000;
                    rr = $random; vi = rr >>> 15; if (($random & 255) == 0) vi = ($random & 1) ? 20'sh7FFFF : 20'sh80000;
                    yv[e] <= 1'b1; ych[e*4 +: 4] <= best; yr[e*W +: W] <= vr; yi[e*W +: W] <= vi;
                    if (dm_on) $fwrite(fin, "%0d %0d %0d\n", best, vr, vi);
                    if (dm_on && nsmp[best] % 4096 == 0) $fwrite(ftl, "%0d %0d %0d\n", best, nsmp[best] / 4096, tnow + 64'd1);   // wsb が t_now を取るのは次のクロック
                    nsmp[best] = nsmp[best] + 1;
                end
            end
        end
    end

    reg  run = 0, stop = 0;
    wire go; wire [31:0] g0;
    wire [E-1:0] dv; wire [E*4-1:0] dw; wire [E*32-1:0] dk; wire [E*12-1:0] dch; wire [E*64-1:0] dd; wire [E*16-1:0] flags;
    wire [2*E+1:0] dflags;
    wire [H*64-1:0] t0w;
    wire [31:0] awaddr; wire [7:0] awlen; wire awvalid, awready, wlast, wvalid, wready, bvalid; wire [63:0] wdata;
    wire [E*32-1:0] araddr; wire [E-1:0] arvalid, arready, rvalid, rlast; wire [E*128-1:0] rdata;
    wsb #(.H(H), .E(E), .S(`TB_S), .W(W), .G_L2(`G_L2), .D(`DLY)) dut (
        .clk(clk), .rst(rst), .y_v(yv), .y_ch(ych), .y_re(yr), .y_im(yi),
        .cfg_ns(cfg_ns), .cfg_fl(cfg_fl), .cfg_sl(cfg_sl), .cfg_sh(cfg_sh), .cfg_g(cfg_g), .ddr_base(32'd0),
        .ng(32'd1), .ndump(32'd2), .cmd_run(run), .cmd_stop(stop),
        .t_now(tnow), .t0(t0w),
        .go(go), .g0(g0), .d_v(dv), .d_w(dw), .d_k(dk), .d_ch(dch), .d_data(dd), .flags(flags), .dflags(dflags),
        .m_awaddr(awaddr), .m_awlen(awlen), .m_awvalid(awvalid), .m_awready(awready), .m_wdata(wdata), .m_wlast(wlast),
        .m_wvalid(wvalid), .m_wready(wready), .m_bvalid(bvalid),
        .m_araddr(araddr), .m_arvalid(arvalid), .m_arready(arready), .m_rdata(rdata), .m_rvalid(rvalid), .m_rlast(rlast));
    axi_mem_model #(.NR(E)) u_mem (.clk(clk), .rst(rst), .awaddr(awaddr), .awvalid(awvalid), .awready(awready),
        .wdata(wdata), .wvalid(wvalid), .wready(wready), .wlast(wlast), .bvalid(bvalid),
        .araddr(araddr), .arvalid(arvalid), .arready(arready), .rdata(rdata), .rvalid(rvalid), .rlast(rlast));


    // ---- K-2: 受け手 → リング → PS の DDR の模型 ----
    wire [127:0] st_d; wire st_v, st_r, st_l; wire [E-1:0] sdrop; wire [3:0] sflags;
    dsink #(.E(E), .H(H), .NU(`TB_NU), .G_L2(`G_L2), .ADC(0)) u_sink (.clk(clk), .rst(rst),
        .d_v(dv), .d_w(dw), .d_k(dk), .d_ch(dch), .d_data(dd), .cfg_ns(cfg_ns), .cfg_sh(cfg_sh), .cfg_g(cfg_g), .ng(32'd1), .g0(g0), .t0(t0w),
        .m_tdata(st_d), .m_tvalid(st_v), .m_tready(st_r), .m_tlast(st_l), .drop(sdrop), .flags(sflags));
    reg  [11:0] la_aw, la_ar; reg la_awv = 0, la_wv = 0, la_arv = 0; reg [31:0] la_wd;
    wire la_awr, la_wr, la_bv, la_arr, la_rv; wire [31:0] la_rd; wire [1:0] la_br, la_rr;
    wire [48:0] h_awaddr; wire [7:0] h_awlen; wire [2:0] h_awsize, h_awprot; wire [1:0] h_awburst; wire h_awlock; wire [3:0] h_awcache, h_awqos;
    wire h_awvalid, h_wlast, h_wvalid, h_bready; wire [127:0] h_wdata; wire [15:0] h_wstrb;
    reg  h_awready = 0, h_wready = 0, h_bvalid = 0;
    ring128 #(.NX(E)) u_ring (.aclk(clk), .aresetn(!rst), .s_axis_tdata(st_d), .s_axis_tvalid(st_v), .s_axis_tready(st_r), .s_axis_tlast(st_l),
        .ext_drop(sdrop),
        .s_axi_awaddr(la_aw), .s_axi_awprot(3'd0), .s_axi_awvalid(la_awv), .s_axi_awready(la_awr), .s_axi_wdata(la_wd), .s_axi_wstrb(4'hF),
        .s_axi_wvalid(la_wv), .s_axi_wready(la_wr), .s_axi_bresp(la_br), .s_axi_bvalid(la_bv), .s_axi_bready(1'b1),
        .s_axi_araddr(la_ar), .s_axi_arprot(3'd0), .s_axi_arvalid(la_arv), .s_axi_arready(la_arr), .s_axi_rdata(la_rd), .s_axi_rresp(la_rr),
        .s_axi_rvalid(la_rv), .s_axi_rready(1'b1),
        .m_axi_awaddr(h_awaddr), .m_axi_awlen(h_awlen), .m_axi_awsize(h_awsize), .m_axi_awburst(h_awburst), .m_axi_awlock(h_awlock),
        .m_axi_awcache(h_awcache), .m_axi_awprot(h_awprot), .m_axi_awqos(h_awqos), .m_axi_awvalid(h_awvalid), .m_axi_awready(h_awready),
        .m_axi_wdata(h_wdata), .m_axi_wstrb(h_wstrb), .m_axi_wlast(h_wlast), .m_axi_wvalid(h_wvalid), .m_axi_wready(h_wready),
        .m_axi_bresp(2'b00), .m_axi_bvalid(h_bvalid), .m_axi_bready(h_bready));
    // PS の DDR の模型（書くだけ。リングの 256 KiB だけ持つ）
    localparam integer RB = 32'h2000_0000, RS = 1 << 18;
    reg  [7:0]  rmem [0:RS-1];
    reg  [48:0] hq [0:63]; integer hqn = 0, hb_ = 0, hk, hj; integer bq_ [0:63]; integer bqn = 0;
    integer hp_pct;
    initial hp_pct = $test$plusargs("HP_SLOW") ? 3 : 90;      // HP_SLOW: 0.03 拍 / クロック < ダンプの平均（≒ 0.11）→ 受け手が捨てる（陽性対照）
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
        h_wready <= (({$random} % 100) < hp_pct) && hqn > 0;   // W は AW を受けてから（AW より先の W を受けると番地が無い）
        h_bvalid <= 0;
        if (bqn > 0) begin
            if (bq_[0] <= 0) begin h_bvalid <= 1; for (hk = 0; hk < 63; hk = hk + 1) bq_[hk] = bq_[hk + 1]; bqn = bqn - 1; end
            for (hk = 0; hk < bqn; hk = hk + 1) bq_[hk] = bq_[hk] - 1;
        end
    end
    task la_write(input [11:0] a, input [31:0] d);
        begin
            @(negedge clk); la_aw = a; la_wd = d; la_awv = 1; la_wv = 1;
            @(posedge clk); while (la_awr !== 1'b1) @(posedge clk);
            @(negedge clk); la_awv = 0; la_wv = 0;
        end
    endtask
    // PS の役: [R, W) を写して R = W
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

    // ---- 記録 ----
    integer ffi, ffo, fdm, k;
    initial begin
        ffi = $fopen("wsb_fi.log", "w"); ffo = $fopen("wsb_fo.log", "w"); fdm = $fopen("wsb_dmp.log", "w");
    end
    generate for (g = 0; g < E; g = g + 1) begin : lg
        wire        pv8 = dut.en[g].u.pv[8], pf8 = dut.en[g].u.pf[8];
        wire [58:0] tg8 = dut.en[g].u.tg8;
        wire [17:0] fr8 = dut.en[g].u.fr8, fi8 = dut.en[g].u.fi8;
        wire        mv  = dut.en[g].u.m_tv;
        wire [11:0] mk  = dut.en[g].u.m_tu[11:0];
        wire [63:0] md  = dut.en[g].u.m_td;
        wire [58:0] hd  = dut.en[g].u.tq_head;
        reg         ivld, ovld;
        always @(posedge clk) begin
            if (pv8 && dm_on) begin
                if (pf8) begin ivld = tg8[58]; if (ivld) $fwrite(ffi, "F %0d %0d\n", g, tg8[57:54]); end
                if (ivld) $fwrite(ffi, "%0d %0d %0d\n", g, $signed(fr8), $signed(fi8));      // 行に機関の番号（E ≧ 2 で機関の行が混ざる）
            end
            if (mv && dm_on) begin
                if (mk == 0) begin ovld = hd[58]; if (ovld) $fwrite(ffo, "O %0d %0d\n", g, hd[57:54]); end
                if (ovld) $fwrite(ffo, "%0d %0d %0d\n", g, $signed(md[31:0]), $signed(md[63:32]));
            end
            if (dv[g] && dm_on) $fwrite(fdm, "%0d %0d %0d %0d %0d\n", g, dw[g*4 +: 4], dk[g*32 +: 32], dch[g*12 +: 12], dd[g*64 +: 64]);
        end
    end endgenerate

    integer frun;
    initial begin
        repeat (20) @(posedge clk);
        rst <= 0;
        repeat (40000) @(posedge clk);
        run <= 1; @(posedge clk); run <= 0;
        @(posedge clk);
        frun = $fopen("wsb_run.log", "w");
        $fwrite(frun, "g0 %0d G_L2 %0d E %0d CFG %0d\n", g0, `G_L2, E, `CFG);
        for (w = 0; w < H; w = w + 1) $fwrite(frun, "w %0d %0d %0d %0d %0d %0d %0d\n", w, act[w], ns[w], fl[w], 5 + w % 3, w >= `TB_S, 10);
        $fclose(frun);
        repeat (`NCYC) @(posedge clk);
        $display("flags = %h dflags = %h", flags, dflags);
        dm_on = 0; $fclose(fdm); $fclose(fin); $fclose(ftl); $fclose(ffi); $fclose(ffo);   // 記録はここまで。揃ったダンプがリングに届くのを待つ（HP_SLOW で 14 ダンプ ≒ 12 万クロック）
        repeat (200000) @(posedge clk);
        ps_drain;
        $display("ring: REC_CNT %0d DROP_CNT %0d EXT_CNT %0d PEAK %0d sflags %h", u_ring.rec_cnt, u_ring.drop_cnt, u_ring.ext_cnt, u_ring.peak, sflags);
        $fclose(frg);
        $finish;
    end
endmodule
