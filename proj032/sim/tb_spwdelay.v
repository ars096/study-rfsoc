// SPDX-License-Identifier: BSD-3-Clause
// proj032 P-12 — SpW の窓の遅れ D(NS)（コアの入口のビート → z が wsb の入口に来るまで）。proj016・021 の tb_wdelay の SpW 版
//   wsb は窓の t0（DUMP_T のもと）を wsb の入口（ddcb の final の lane、y_v・y_ch）で取るので、D はそこまでの遅れ。utc の補正は D_eff = D(NS) ＋ 1.5·L(NS)（eng の PFB T = 4）
//   入力は 0 に、間隔 GAP ビートでインパルス（1 標本 16000）を NIMP 個。i 個目はビート 5000 ＋ i·GAP ＋ (i·5 mod NPH)・標本の位置 (i·7 mod 16)
//   （ddcb の枠の数え tdm・hold は WRST から数え、データの来る時刻とは関係がない。間引きの位相とともに NPH 通りの位相を全部なめて平均する）
//   tvalid は WRST の前から 1（実機と同じ。頭の組の位相も WRST からになる）
//   窓は実機の P-10b の 2 回目（runs/p10_plan2）と同じ 8 本（WDPHI ≠ 0・2 番目に近い粗い ch・lane を分け合う）
//   記録: dly_imp.log（インパルスのビートが spw_front に入ったクロック・標本の位置）・dly_y.log（クロック 窓 re im、y_v のたびに）。重心は sim/check_spwdelay.py
//   陽性対照 -DDLY_POSCTL=N: 入口に N 段のレジスタを足す → D がちょうど ＋N 動くはず（N = 1 は位相の平均が要る。N が系の周期の倍数なら位相ごとに一致）
`timescale 1ns / 1ps
module tb_spwdelay;
    localparam integer H = 8, E = 3;
`ifndef NIMP
`define NIMP 64
`endif
`ifndef GAP
`define GAP 3072
`endif
`ifndef NPH
`define NPH 64
`endif
    reg clk = 0; always #1.953 clk = ~clk;
    reg rst_pfb = 1, rst = 1;
    // (s: WK, NS, lane, WDPHI) = runs/p10_plan2 の計画
    reg [2:0] ns [0:H-1]; reg [1:0] fl [0:H-1]; reg [5:0] wk [0:H-1]; reg [31:0] dp [0:H-1];
    initial begin
        wk[0] = 4;  ns[0] = 2; fl[0] = 1; dp[0] = 32'hce000000;
        wk[1] = 4;  ns[1] = 5; fl[1] = 2; dp[1] = 32'hcd000000;
        wk[2] = 12; ns[2] = 1; fl[2] = 1; dp[2] = 32'h1c000000;
        wk[3] = 12; ns[3] = 3; fl[3] = 2; dp[3] = 32'h26000000;
        wk[4] = 3;  ns[4] = 1; fl[4] = 0; dp[4] = 32'h04000000;
        wk[5] = 3;  ns[5] = 2; fl[5] = 0; dp[5] = 32'h0e000000;
        wk[6] = 3;  ns[6] = 4; fl[6] = 2; dp[6] = 32'h0c000000;
        wk[7] = 23; ns[7] = 1; fl[7] = 2; dp[7] = 32'he6000000;
    end
    wire [H*6-1:0] cwk; wire [H*32-1:0] cdp; wire [H*3-1:0] cns; wire [H*2-1:0] cfl;
    genvar g;
    generate for (g = 0; g < H; g = g + 1) begin : cf
        assign cwk[g*6 +: 6] = wk[g]; assign cdp[g*32 +: 32] = dp[g]; assign cns[g*3 +: 3] = ns[g]; assign cfl[g*2 +: 2] = fl[g];
    end endgenerate
    reg  [255:0] x = 0; reg xv = 1;
`ifdef DLY_POSCTL
    reg  [255:0] xd [0:`DLY_POSCTL-1];
    integer di;
    initial for (di = 0; di < `DLY_POSCTL; di = di + 1) xd[di] = 0;
    always @(posedge clk) begin xd[0] <= x; for (di = 1; di < `DLY_POSCTL; di = di + 1) xd[di] <= xd[di-1]; end
    wire [255:0] xin = xd[`DLY_POSCTL-1]; wire xinv = xv;
`else
    wire [255:0] xin = x; wire xinv = xv;
`endif
    wire [E-1:0] yv; wire [E*4-1:0] ych; wire [E*20-1:0] yr, yi; wire [24*H-1:0] cr, ci; wire cv; wire [5:0] flags;
    spw_front #(.H(H), .E(E)) dut (.clk(clk), .rst_pfb(rst_pfb), .rst(rst), .s_tdata(xin), .s_tvalid(xinv),
        .cfg_wk(cwk), .cfg_dphi(cdp), .cfg_ns(cns), .cfg_fl(cfl), .y_v(yv), .y_ch(ych), .y_re(yr), .y_im(yi),
        .c_re(cr), .c_im(ci), .c_v(cv), .flags(flags));
    integer T = 0;
    always @(posedge clk) T <= T + 1;
    integer fi, fy, e, i, b, ln; reg done = 0;
    initial begin fi = $fopen("dly_imp.log", "w"); fy = $fopen("dly_y.log", "w"); end
    always @(posedge clk)
        for (e = 0; e < E; e = e + 1)
            if (yv[e] && !rst && !done) $fwrite(fy, "%0d %0d %0d %0d\n", T, ych[e*4 +: 4], $signed(yr[e*20 +: 20]), $signed(yi[e*20 +: 20]));
    initial begin
        repeat (10) @(posedge clk); rst_pfb <= 0;
        repeat (300) @(posedge clk); rst <= 0;
        for (i = 0; i < `NIMP; i = i + 1) begin
            b = 5000 + i * `GAP + (i * 5) % `NPH;
            ln = (i * 7) % 16;
            while (T < b) @(posedge clk);
            x <= 256'd0; x[ln*16 +: 16] <= 16'sd16000;
            $fwrite(fi, "%0d %0d\n", T + 1, ln);       // このビートが spw_front（の入口のレジスタ）に入るクロック
            @(posedge clk); x <= 256'd0;
        end
        while (T < 5000 + `NIMP * `GAP) @(posedge clk);
        $display("flags = %b", flags);
        done = 1; @(posedge clk);
        $fclose(fi); $fclose(fy);
        $finish;
    end
endmodule
