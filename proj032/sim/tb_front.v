// proj032 P-1 — spw_front（粗い PFB → 頭 → ddcb の入口の語長 → ddcb）の照合。sim/check_front.py が、頭の入口（粗い PFB の出口）から
//   M-3 の整数の模型（NCO・半帯域・丸め・飽和、model/win64_fixed.py の部品）で ddcb の出口を作り、bit 単位で照らす
//   入力: 雑音（σ ≒ 1500 LSB の 16 bit）＋ CW 3 本。窓 14 本（CFG 0 と同じ幅と lane、粗い ch は頭 0..6 が偶・7..13 が奇）
//   陽性対照 -DFRONT_POSCTL: 窓 3 の NCO の増分を 1 だけ変える（模型は変えない）→ 窓 3 が落ちる
//   記録: front_c.log（頭の入口、1 行に 14 頭）・front_y.log（ddcb の出口: lane 窓 re im）・front_cfg.log
`timescale 1ns / 1ps
module tb_front;
    localparam integer H = 14, E = 3;
`ifndef NCYC
`define NCYC 120000
`endif
    reg clk = 0; always #1.953 clk = ~clk;
    reg rst_pfb = 1, rst = 1;
    reg [2:0] ns [0:H-1]; reg [1:0] fl [0:H-1]; reg [5:0] wk [0:H-1]; reg [31:0] dp [0:H-1];
    integer w;
    initial begin
        ns[0] = 5; ns[1] = 5; ns[2] = 4; ns[3] = 3; ns[4] = 2; ns[5] = 1; for (w = 0; w < 6; w = w + 1) fl[w] = 0;
        ns[6] = 1; ns[7] = 1; fl[6] = 1; fl[7] = 1;
        ns[8] = 4; ns[9] = 4; ns[10] = 3; ns[11] = 2; ns[12] = 2; ns[13] = 2; for (w = 8; w < 14; w = w + 1) fl[w] = 2;
        for (w = 0; w < H; w = w + 1) begin
            wk[w] = (w < 7) ? 2 * (w + 3) : 2 * (w - 7) + 5;      // 偶 6..18 / 奇 5..17
            dp[w] = 32'h0123_4567 * (w + 1);
        end
    end
    wire [H*6-1:0] cwk; wire [H*32-1:0] cdp; wire [H*3-1:0] cns; wire [H*2-1:0] cfl;
    genvar g;
    generate for (g = 0; g < H; g = g + 1) begin : cf
        assign cwk[g*6 +: 6] = wk[g]; assign cdp[g*32 +: 32] = dp[g]
`ifdef FRONT_POSCTL
            + (g == 3)          // 記録（front_cfg）には元の値を書く（模型はそれで作る）
`endif
            ; assign cns[g*3 +: 3] = ns[g]; assign cfl[g*2 +: 2] = fl[g];
    end endgenerate
    // ---- ADC の入力: 雑音 ＋ CW（16 bit、lane 0 が先）----
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
    wire [E-1:0] yv; wire [E*4-1:0] ych; wire [E*20-1:0] yr, yi; wire [24*H-1:0] cr, ci; wire cv; wire [5:0] flags;
    spw_front #(.H(H), .E(E)) dut (.clk(clk), .rst_pfb(rst_pfb), .rst(rst), .s_tdata(x), .s_tvalid(xv),
        .cfg_wk(cwk), .cfg_dphi(cdp), .cfg_ns(cns), .cfg_fl(cfl), .y_v(yv), .y_ch(ych), .y_re(yr), .y_im(yi),
        .c_re(cr), .c_im(ci), .c_v(cv), .flags(flags));
    integer fc, fy, ff, e;
    initial begin
        fc = $fopen("front_c.log", "w"); fy = $fopen("front_y.log", "w"); ff = $fopen("front_cfg.log", "w");
        for (w = 0; w < H; w = w + 1) $fwrite(ff, "%0d %0d %0d %0d %0d\n", w, ns[w], fl[w], wk[w], dp[w]);
        $fclose(ff);
    end
    // P-5: 粗い PFB の入口（rst の明けた後の valid なビート、16 × 16 bit の hex）と、front_c の行ごとの粗い PFB のフレーム番号（check_pfb_chain.py）
    integer fxl, fml, pfm = 0;
    initial begin fxl = $fopen("front_x.log", "w"); fml = $fopen("front_m.log", "w"); end
    always @(posedge clk) begin
        if (xv && !rst_pfb) $fwrite(fxl, "%064x\n", x);
        if (rst_pfb) pfm = 0; else if (cv) begin if (!rst) $fwrite(fml, "%0d\n", pfm); pfm = pfm + 1; end
    end
    // 頭の入口は rst（WRST）の明けた後の c_v から（頭はそこから数える）
    always @(posedge clk) begin
        if (cv && !rst) begin
            for (w = 0; w < H; w = w + 1) $fwrite(fc, "%0d %0d ", $signed(cr[w*24 +: 24]), $signed(ci[w*24 +: 24]));
            $fwrite(fc, "\n");
        end
        for (e = 0; e < E; e = e + 1)
            if (yv[e]) $fwrite(fy, "%0d %0d %0d %0d\n", e, ych[e*4 +: 4], $signed(yr[e*20 +: 20]), $signed(yi[e*20 +: 20]));
    end
    initial begin
        repeat (10) @(posedge clk); rst_pfb <= 0;
        repeat (300) @(posedge clk); rst <= 0;
        repeat (`NCYC) @(posedge clk);
        $display("flags = %b", flags);
        $fclose(fc); $fclose(fy);
        $finish;
    end
endmodule
