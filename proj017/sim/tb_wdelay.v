// SPDX-License-Identifier: BSD-3-Clause
// proj016 — 窓の遅れ D(NS) を出す sim（pfb_core → ddc_core）。timebase.py の WIN_DELAY_BEATS の出どころ
//   入力のビート B0 の 1 サンプルにインパルス（それ以外 0）を入れ、z の |z|² の重心が wspec に入るクロックを測る。
//   **D = 重心のクロック − インパルスのビートが pfb に入ったクロック**（ビート。小数）。線形位相なので重心 = 群遅延 ＋ 経路の遅れ
//   +NS= +K= +LEN=（インパルスの後に回すクロック数）
// proj017: **最初の z の遅れ F(NS)** も出す: rst（= w_rst）の後の窓の始まりのビート WSTART（q_s = 5 のビートが pfb に入ったクロック）から、
//   最初の z（窓のフレーム 0 の頭）が wspec に入るまで。窓の区切りの実効の時刻（DUMP_T − D(NS)）は WSTART ＋ F0·L ＋ (F(NS) − D(NS))
//   なので、幅の違う窓の区切りの差は X(NS) = F(NS) − D(NS) で決まる（2026-10-03 の F-4 で NS ごとの一定の差として見えた）
`timescale 1ns / 1ps
module tb_wdelay;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg  [255:0] tdata = 0;
    reg          tvalid = 0;
    reg  [4:0]   k = 0;
    reg  [3:0]   ns = 1;
    wire signed [23:0] y0r, y0i, y1r, y1i;
    wire y0ok, y1ok, yv;
    wire [15:0] s1, s2, ovrc;
    wire zv;
    wire signed [17:0] zr, zi;
    pfb_core u_pfb (.clk(clk), .rst(rst), .w_rst(rst), .s_tdata(tdata), .s_tvalid(tvalid), .k(k),
                    .y0_re(y0r), .y0_im(y0i), .y1_re(y1r), .y1_im(y1i),
                    .y0_ok(y0ok), .y1_ok(y1ok), .y_valid(yv), .sat_cnt(s1));
    ddc_core u_ddc (.clk(clk), .rst(rst), .y_valid(yv), .y0_ok(y0ok), .y1_ok(y1ok),
                    .y0_re(y0r), .y0_im(y0i), .y1_re(y1r), .y1_im(y1i),
                    .dphi(32'd0), .ns(ns), .z_valid(zv), .z_re(zr), .z_im(zi), .sat_cnt(s2), .ovr_cnt(ovrc));
    integer T = 0, len, nsv, kk, b, t_imp, nz;
    real e, et, w, pk;
    integer t_pk, t_v0, t_z0;
    always @(posedge clk) T <= T + 1;
    initial begin
        if (!$value$plusargs("NS=%d", nsv)) nsv = 1;
        if (!$value$plusargs("K=%d", kk)) kk = 5;
        if (!$value$plusargs("LEN=%d", len)) len = 60000;
        k = kk; ns = nsv;
        e = 0; et = 0; pk = 0; t_pk = 0; nz = 0; t_z0 = -1;
        repeat (4) @(posedge clk);
        rst <= 0;
        // 5000 ビートの 0 の後、ビート 5000 のサンプル 0 にインパルス
        for (b = 0; b < 5000 + len; b = b + 1) begin
            @(posedge clk);
            tdata <= 256'd0;
            if (b == 0) t_v0 = T + 1;                       // 最初の valid なビートが pfb に入るクロック（q = 0）
            if (b == 5000) begin tdata[15:0] <= 16'sd16000; t_imp = T + 1; end
            tvalid <= 1;
        end
        $display("wdelay: NS=%0d K=%0d インパルスのビート T %0d / z %0d 個 / 重心 %.2f ビート / 最大 %0d ビート",
                 nsv, kk, t_imp, nz, et / e - t_imp, t_pk - t_imp);
        $display("wfirst: NS=%0d 最初の z の遅れ F = %0d ビート（WSTART = q 5 のクロックから）/ X = F − D = %.2f ビート",
                 nsv, t_z0 - (t_v0 + 5), (t_z0 - (t_v0 + 5)) - (et / e - t_imp));
        $finish;
    end
    // z が wspec に入るのは zv の立ったクロック（win_core では ddc の出口がそのまま wspec の z_valid）
    always @(posedge clk) if (zv && t_z0 < 0) t_z0 = T;
    always @(posedge clk) if (zv && T > 6000 - 1000) begin
        w = $itor(zr) * $itor(zr) + $itor(zi) * $itor(zi);
        e = e + w; et = et + w * T; nz = nz + 1;
        if (w > pk) begin pk = w; t_pk = T; end
    end
endmodule
