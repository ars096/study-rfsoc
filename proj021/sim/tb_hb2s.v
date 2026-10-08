// SPDX-License-Identifier: BSD-3-Clause
// tb_hb2s — hb2s（時分割）が hb2 と bit 単位で同じ出力を出すか（make sim-hb2s）
//   +C=<時分割の数> +GAP=<組の間隔の最小> +FINAL=<0: light / 1: final の係数> +NPAIR= +SEED=
//   組の間隔は GAP 〜 GAP + 3 の乱数。GAP < C なら前提が破れる（陽性対照: ovr が立ち、一致しなくなるはず）
`timescale 1ns / 1ps
module tb_hb2s;
`include "win_coef.vh"
    reg clk = 0;
    always #1 clk = ~clk;
    reg rst = 1;
    reg in_v = 0;
    reg signed [23:0] er, ei, or_, oi;
    wire va, vb, sa, sb, ovr;
    wire signed [23:0] yar, yai, ybr, ybi;
`ifdef HB_FINAL
    localparam integer HN = HBF_N, HSH = HBF_SH;
    localparam [18*HBF_N-1:0] HH = HBF_H;
`else
    localparam integer HN = HBL_N, HSH = HBL_SH;
    localparam [18*HBL_N-1:0] HH = HBL_H;
`endif
`ifndef HB_C
`define HB_C 2
`endif
    hb2  #(.N(HN), .SH(HSH), .H(HH), .W(24)) u_a (.clk(clk), .rst(rst), .in_v(in_v),
        .e_re(er), .e_im(ei), .o_re(or_), .o_im(oi), .out_v(va), .y_re(yar), .y_im(yai), .sat(sa));
    hb2s #(.N(HN), .SH(HSH), .H(HH), .W(24), .C(`HB_C)) u_b (.clk(clk), .rst(rst), .in_v(in_v),
        .e_re(er), .e_im(ei), .o_re(or_), .o_im(oi), .out_v(vb), .y_re(ybr), .y_im(ybi), .sat(sb), .ovr(ovr));

    // 両方の出力を溜めて、最後に並べて比べる（レイテンシが違うので、同じクロックに出ることも前後することもある）
    reg signed [23:0] qr [0:65535], qi [0:65535], rr [0:65535], ri [0:65535];
    integer na = 0, nb = 0, bad = 0, novr = 0, nsa = 0, nsb = 0;
    always @(posedge clk) begin
        if (va) begin qr[na] <= yar; qi[na] <= yai; na <= na + 1; if (sa) nsa <= nsa + 1; end
        if (vb) begin rr[nb] <= ybr; ri[nb] <= ybi; nb <= nb + 1; if (sb) nsb <= nsb + 1; end
        if (ovr) novr <= novr + 1;
    end
    integer gap, np, seed, p, w, big, n;
    initial begin
        if (!$value$plusargs("GAP=%d", gap)) gap = `HB_C;
        if (!$value$plusargs("NPAIR=%d", np)) np = 20000;
        if (!$value$plusargs("SEED=%d", seed)) seed = 3;
        repeat (4) @(posedge clk);
        rst <= 0;
        for (p = 0; p < np; p = p + 1) begin
            // 振幅: ふつうは ±2^20、ときどき満杯の近く（飽和の経路も通す）
            big = ((p % 1000) < 40);                // 40 組続けて満杯の近く（同符号）→ 飽和の経路も通す
            er  <= big ? 24'sh7FFFF0 : ($random(seed) >>> 11);
            ei  <= big ? 24'sh7FFFF0 : ($random(seed) >>> 11);
            or_ <= big ? 24'sh7FFFF0 : ($random(seed) >>> 11);
            oi  <= big ? 24'sh7FFFF0 : ($random(seed) >>> 11);
            in_v <= 1;
            @(posedge clk);
            in_v <= 0;
            w = gap + ($random(seed) & 3);
            repeat (w - 1) @(posedge clk);
        end
        repeat (200) @(posedge clk);
        for (n = 0; n < na && n < nb; n = n + 1) if (qr[n] !== rr[n] || qi[n] !== ri[n]) bad = bad + 1;
        $display("hb2s: C=%0d GAP=%0d %s: 組 %0d → hb2 %0d 個 / hb2s %0d 個、不一致 %0d、ovr %0d、飽和 hb2 %0d / hb2s %0d",
                 `HB_C, gap, (HN == HBF_N) ? "final" : "light", np, na, nb, bad, novr, nsa, nsb);
        if (na == nb && bad == 0 && novr == 0 && nsa == nsb && na > 0) $display("hb2s: 一致");
        else $display("hb2s: 不一致");
        $finish;
    end
endmodule
