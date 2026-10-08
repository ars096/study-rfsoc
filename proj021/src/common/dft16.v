// SPDX-License-Identifier: BSD-3-Clause
//
// dft16 — レーンをまたぐ 16 点 DFT（順変換）。出力は k2 = 0..7 の 8 本だけ
//
// 8192 点 FFT を 16 × 512 に分解した後段。入力 V[p]（p = 0..15、ひねり係数を掛けた後）から
//   Z[k2] = Σ_p W16^(p·k2) · V[p]        W16 = exp(-2πi/16)
// を作る。実数入力なので k2 = 8..15 は k2 = 0..7 の複素共役の鏡像で、要らない。
//
// 4 × 4 に分解する。p = 4a + b、k2 = c + 4d（a, b, c, d = 0..3）:
//   段 1: U[b][c] = Σ_a W4^(a·c) · V[4a+b]       4 点 DFT（±1, ±j だけ = 加減算）
//   段 2: T[b][c] = W16^(b·c) · U[b][c]           ひねり係数（cmul 16 個。自明なものも通す）
//   段 3: Z[c+4d] = Σ_b W4^(b·d) · T[b][c]        4 点 DFT。d = 0, 1 だけ使う
//
// **自明な係数（1, −j）も cmul に通す**のは、レイテンシを全経路で揃えるため。
// 2^16 = 1.0 を掛けて丸めて 16 bit 戻すのは厳密に恒等なので、値は変わらない。
//
// レイテンシ **6 クロック固定**（段 1 = 1、段 2 = 4、段 3 = 1）。
//
// 語幅（spec_core.v の冒頭の上限の議論による）:
//   V 25 bit → U 27 bit（4 個の和）→ T 27 bit（|W| = 1）→ Z 29 bit（4 個の和）

`timescale 1ns / 1ps

module dft16 #(
    parameter integer VW = 25,
    parameter integer UW = 27,
    parameter integer ZW = 29
)(
    input  wire                 clk,
    input  wire [16*VW-1:0]     v_re,    // p 番目が [p*VW +: VW]
    input  wire [16*VW-1:0]     v_im,
    output wire [8*ZW-1:0]      z_re,    // k2 番目が [k2*ZW +: ZW]
    output wire [8*ZW-1:0]      z_im
);
    // W16^e の定数（2^16 = 1.0）。e = 0..9 だけ要る（b·c ≦ 9）
    function signed [17:0] wre(input integer e);
        case (e)
            0: wre =  18'sd65536;   1: wre =  18'sd60547;   2: wre =  18'sd46341;
            3: wre =  18'sd25080;   4: wre =  18'sd0;       6: wre = -18'sd46341;
            9: wre = -18'sd60547;
            default: wre = 18'sd0;
        endcase
    endfunction
    function signed [17:0] wim(input integer e);
        case (e)
            0: wim =  18'sd0;       1: wim = -18'sd25080;   2: wim = -18'sd46341;
            3: wim = -18'sd60547;   4: wim = -18'sd65536;   6: wim = -18'sd46341;
            9: wim =  18'sd25080;
            default: wim = 18'sd0;
        endcase
    endfunction

    // ---- 段 1: 4 点 DFT over a ----
    //   X0 = x0 + x1 + x2 + x3
    //   X1 = x0 − j·x1 − x2 + j·x3
    //   X2 = x0 − x1 + x2 − x3
    //   X3 = x0 + j·x1 − x2 − j·x3
    // −j·(r + i·q) = q − i·r
    // **配列要素を複数の always から駆動しない**（Vivado が多重駆動と見なすことがある）。
    // 各段のレジスタは generate の中で宣言し、平らなベクタに assign で並べる。
    wire [16*UW-1:0] u_re_v, u_im_v;   // [(b*4+c)*UW +: UW]

    genvar b, c;
    generate
        for (b = 0; b < 4; b = b + 1) begin : g_s1
            wire signed [VW-1:0] x0r = v_re[(0*4+b)*VW +: VW], x0i = v_im[(0*4+b)*VW +: VW];
            wire signed [VW-1:0] x1r = v_re[(1*4+b)*VW +: VW], x1i = v_im[(1*4+b)*VW +: VW];
            wire signed [VW-1:0] x2r = v_re[(2*4+b)*VW +: VW], x2i = v_im[(2*4+b)*VW +: VW];
            wire signed [VW-1:0] x3r = v_re[(3*4+b)*VW +: VW], x3i = v_im[(3*4+b)*VW +: VW];
            reg signed [UW-1:0] r0, i0, r1, i1, r2, i2, r3, i3;
            always @(posedge clk) begin
                r0 <= x0r + x1r + x2r + x3r;
                i0 <= x0i + x1i + x2i + x3i;
                r1 <= x0r + x1i - x2r - x3i;
                i1 <= x0i - x1r - x2i + x3r;
                r2 <= x0r - x1r + x2r - x3r;
                i2 <= x0i - x1i + x2i - x3i;
                r3 <= x0r - x1i - x2r + x3i;
                i3 <= x0i + x1r - x2i - x3r;
            end
            assign u_re_v[(b*4+0)*UW +: UW] = r0;  assign u_im_v[(b*4+0)*UW +: UW] = i0;
            assign u_re_v[(b*4+1)*UW +: UW] = r1;  assign u_im_v[(b*4+1)*UW +: UW] = i1;
            assign u_re_v[(b*4+2)*UW +: UW] = r2;  assign u_im_v[(b*4+2)*UW +: UW] = i2;
            assign u_re_v[(b*4+3)*UW +: UW] = r3;  assign u_im_v[(b*4+3)*UW +: UW] = i3;
        end
    endgenerate

    // ---- 段 2: ひねり係数 W16^(b·c) ----
    wire [16*UW-1:0] t_re_v, t_im_v;   // [(b*4+c)*UW +: UW]
    generate
        for (b = 0; b < 4; b = b + 1) begin : g_s2b
            for (c = 0; c < 4; c = c + 1) begin : g_s2c
                cmul #(.AW(UW), .OW(UW)) u_tw (
                    .clk(clk),
                    .a_re(u_re_v[(b*4+c)*UW +: UW]), .a_im(u_im_v[(b*4+c)*UW +: UW]),
                    .w_re(wre(b*c)),                 .w_im(wim(b*c)),
                    .y_re(t_re_v[(b*4+c)*UW +: UW]), .y_im(t_im_v[(b*4+c)*UW +: UW])
                );
            end
        end
    endgenerate

    // ---- 段 3: 4 点 DFT over b。d = 0, 1 だけ ----
    //   d = 0: Z[c]   = T0 + T1 + T2 + T3
    //   d = 1: Z[c+4] = T0 − j·T1 − T2 + j·T3
    generate
        for (c = 0; c < 4; c = c + 1) begin : g_s3
            wire signed [UW-1:0] y0r = t_re_v[(0*4+c)*UW +: UW], y0i = t_im_v[(0*4+c)*UW +: UW];
            wire signed [UW-1:0] y1r = t_re_v[(1*4+c)*UW +: UW], y1i = t_im_v[(1*4+c)*UW +: UW];
            wire signed [UW-1:0] y2r = t_re_v[(2*4+c)*UW +: UW], y2i = t_im_v[(2*4+c)*UW +: UW];
            wire signed [UW-1:0] y3r = t_re_v[(3*4+c)*UW +: UW], y3i = t_im_v[(3*4+c)*UW +: UW];
            reg signed [ZW-1:0] zr0, zi0, zr1, zi1;   // d = 0 → Z[c] / d = 1 → Z[c+4]
            always @(posedge clk) begin
                zr0 <= y0r + y1r + y2r + y3r;
                zi0 <= y0i + y1i + y2i + y3i;
                zr1 <= y0r + y1i - y2r - y3i;
                zi1 <= y0i - y1r - y2i + y3r;
            end
            assign z_re[c*ZW +: ZW]     = zr0;
            assign z_im[c*ZW +: ZW]     = zi0;
            assign z_re[(c+4)*ZW +: ZW] = zr1;
            assign z_im[(c+4)*ZW +: ZW] = zi1;
        end
    endgenerate
endmodule
