// tb_wsb — 窓の分光の後段（wsb: 機関 E 組 ＋ 履歴の枠 ＋ 積分器）を、窓ごとの形と照らす（E-4・M-1）
//   入口は final の lane の形を真似る: 窓 w は 2^NS クロックに 1 標本が「来るべき」になり、lane は来るべき窓のうち NS の小さい・番号の小さい窓から 1 / クロック出す。
//   記録（sim/check_wsb.py が照らす）: in（窓ごとの入口の標本）・fi（FFT の入口の枠、札つき）・fo（FFT の出口の枠、札つき）・dmp（閉じたダンプの流れ）・run（g0）
//   構成（`CFG）: 0 3 lane とも幅の和 256 MHz（6・2・6 窓、NS を混ぜる）/ 1 2 lane（128 + 64 + 32 + 16 + 8 + 8・32 × 8）/ 2 1 lane に 128 × 2 だけ
//   陽性対照 ENG_POSCTL（eng.v）: 選びの NS の優先を外す → 幅の広い窓が遅れ、flags[1] と値の不一致
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
`define DLY 64
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
    wire [H*3-1:0] cfg_ns; wire [H*4-1:0] cfg_sl; wire [H*2-1:0] cfg_fl; wire [H*4-1:0] cfg_sh;
    genvar g;
    generate for (g = 0; g < H; g = g + 1) begin : cf
        assign cfg_ns[g*3 +: 3] = ns[g]; assign cfg_fl[g*2 +: 2] = fl[g];
        assign cfg_sl[g*4 +: 4] = g;     assign cfg_sh[g*4 +: 4] = 4'd5 + g % 3;
    end endgenerate

    // ---- 入口: lane ごとに、来るべき標本の数 due[w] から NS・番号の小さい順に 1 / クロック ----
    integer due [0:H-1];
    integer tick, e, best;
    reg  [E-1:0]   yv;
    reg  [E*4-1:0] ych;
    reg  [E*W-1:0] yr, yi;
    reg  signed [W-1:0] vr, vi;
    integer fin, rr;
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
                    $fwrite(fin, "%0d %0d %0d\n", best, vr, vi);
                end
            end
        end
    end

    reg  run = 0, stop = 0;
    wire go; wire [31:0] g0;
    wire [E-1:0] dv; wire [E*4-1:0] dw; wire [E*32-1:0] dk; wire [E*12-1:0] dch; wire [E*64-1:0] dd; wire [E*8-1:0] flags;
    wsb #(.H(H), .E(E), .S(H), .W(W), .G_L2(`G_L2), .D(`DLY)) dut (
        .clk(clk), .rst(rst), .y_v(yv), .y_ch(ych), .y_re(yr), .y_im(yi),
        .cfg_ns(cfg_ns), .cfg_fl(cfg_fl), .cfg_sl(cfg_sl), .cfg_sh(cfg_sh),
        .ng(32'd1), .ndump(32'd2), .cmd_run(run), .cmd_stop(stop),
        .go(go), .g0(g0), .d_v(dv), .d_w(dw), .d_k(dk), .d_ch(dch), .d_data(dd), .flags(flags));

    // ---- 記録 ----
    integer ffi, ffo, fdm, k;
    initial begin
        ffi = $fopen("wsb_fi.log", "w"); ffo = $fopen("wsb_fo.log", "w"); fdm = $fopen("wsb_dmp.log", "w");
    end
    generate for (g = 0; g < E; g = g + 1) begin : lg
        wire        pv8 = dut.en[g].u.pv[8], pf8 = dut.en[g].u.pf[8];
        wire [54:0] tg8 = dut.en[g].u.tg8;
        wire [17:0] fr8 = dut.en[g].u.fr8, fi8 = dut.en[g].u.fi8;
        wire        mv  = dut.en[g].u.m_tv;
        wire [11:0] mk  = dut.en[g].u.m_tu[11:0];
        wire [63:0] md  = dut.en[g].u.m_td;
        wire [54:0] hd  = dut.en[g].u.tq_head;
        reg         ivld, ovld;
        always @(posedge clk) begin
            if (pv8) begin
                if (pf8) begin ivld = tg8[54]; if (ivld) $fwrite(ffi, "F %0d %0d\n", g, tg8[53:50]); end
                if (ivld) $fwrite(ffi, "%0d %0d %0d\n", g, $signed(fr8), $signed(fi8));      // 行に機関の番号（E ≧ 2 で機関の行が混ざる）
            end
            if (mv) begin
                if (mk == 0) begin ovld = hd[54]; if (ovld) $fwrite(ffo, "O %0d %0d\n", g, hd[53:50]); end
                if (ovld) $fwrite(ffo, "%0d %0d %0d\n", g, $signed(md[31:0]), $signed(md[63:32]));
            end
            if (dv[g]) $fwrite(fdm, "%0d %0d %0d %0d %0d\n", g, dw[g*4 +: 4], dk[g*32 +: 32], dch[g*12 +: 12], dd[g*64 +: 64]);
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
        for (w = 0; w < H; w = w + 1) $fwrite(frun, "w %0d %0d %0d %0d %0d\n", w, act[w], ns[w], fl[w], 5 + w % 3);
        $fclose(frun);
        repeat (`NCYC) @(posedge clk);
        $display("flags = %h", flags);
        $fclose(fin); $fclose(ffi); $fclose(ffo); $fclose(fdm);
        $finish;
    end
endmodule
