// SPDX-License-Identifier: BSD-3-Clause
//
// dft16f — 16 点 複素 DFT（順変換）。**出力 16 本とも**（proj013 の dft16 は実数入力の 8 本だけ）
//
//   Z[k] = Σ_n W16^(n·k) · z[n]        W16 = exp(−2πi/16)
// proj013 の dft16 と同じ 4 × 4 の分解（n = 4a + b、k = c + 4d）:
//   段 1: U[b][c] = Σ_a W4^(a·c) · z[4a+b]       4 点 DFT（加減算）
//   段 2: T[b][c] = W16^(b·c) · U[b][c]           ひねり係数
//   段 3: Z[c+4d] = Σ_b W4^(b·d) · T[b][c]        4 点 DFT（d = 0..3）
//
// **自明な係数（b·c = 0 → 1、b·c = 4 → −j）は cmul を通さず、4 クロックの遅延線で揃える。**
// cmul に 1 や −j を通した値と bit 単位で同じ（(a·65536 + 2^15) >> 16 = a）なので、proj013 の dft16 と値は変わらない。
// 自明でないのは b·c ∈ {1, 2, 3, 2, 6, 3, 6, 9} の 8 個だけ → cmul 8 個（DSP 32）。
//
// レイテンシ **6 クロック固定**（段 1 = 1、段 2 = 4、段 3 = 1）。
// 語幅: z VW → U VW+2（4 個の和）→ T UW（|W| = 1）→ Z UW+2
// 対応する模型: model/win_fixed.py の dft16_int

`timescale 1ns / 1ps

module dft16f #(
    parameter integer VW = 22,
    parameter integer UW = 24,
    parameter integer ZW = 26
)(
    input  wire                 clk,
    input  wire [16*VW-1:0]     z_re,    // n 番目が [n*VW +: VW]
    input  wire [16*VW-1:0]     z_im,
    output wire [16*ZW-1:0]     y_re,    // k 番目が [k*ZW +: ZW]
    output wire [16*ZW-1:0]     y_im
);
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
    wire [16*UW-1:0] u_re_v, u_im_v;   // [(b*4+c)*UW +: UW]
    genvar b, c;
    generate
        for (b = 0; b < 4; b = b + 1) begin : g_s1
            wire signed [VW-1:0] x0r = z_re[(0*4+b)*VW +: VW], x0i = z_im[(0*4+b)*VW +: VW];
            wire signed [VW-1:0] x1r = z_re[(1*4+b)*VW +: VW], x1i = z_im[(1*4+b)*VW +: VW];
            wire signed [VW-1:0] x2r = z_re[(2*4+b)*VW +: VW], x2i = z_im[(2*4+b)*VW +: VW];
            wire signed [VW-1:0] x3r = z_re[(3*4+b)*VW +: VW], x3i = z_im[(3*4+b)*VW +: VW];
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

    // ---- 段 2: ひねり係数 W16^(b·c)。自明なもの（b·c = 0, 4）は遅延線 ----
    wire [16*UW-1:0] t_re_v, t_im_v;
    generate
        for (b = 0; b < 4; b = b + 1) begin : g_s2b
            for (c = 0; c < 4; c = c + 1) begin : g_s2c
                if (b * c == 0 || b * c == 4) begin : g_triv
                    reg signed [UW-1:0] dr [0:3];
                    reg signed [UW-1:0] di [0:3];
                    wire signed [UW-1:0] ar = u_re_v[(b*4+c)*UW +: UW];
                    wire signed [UW-1:0] ai = u_im_v[(b*4+c)*UW +: UW];
                    integer j;
                    always @(posedge clk) begin
                        if (b * c == 0) begin dr[0] <= ar;  di[0] <= ai;  end
                        else            begin dr[0] <= ai;  di[0] <= -ar; end   // −j·(r + i·q) = q − i·r
                        for (j = 1; j < 4; j = j + 1) begin dr[j] <= dr[j-1]; di[j] <= di[j-1]; end
                    end
                    assign t_re_v[(b*4+c)*UW +: UW] = dr[3];
                    assign t_im_v[(b*4+c)*UW +: UW] = di[3];
                end else begin : g_cm
                    cmul #(.AW(UW), .OW(UW)) u_tw (
                        .clk(clk),
                        .a_re(u_re_v[(b*4+c)*UW +: UW]), .a_im(u_im_v[(b*4+c)*UW +: UW]),
                        .w_re(wre(b*c)),                 .w_im(wim(b*c)),
                        .y_re(t_re_v[(b*4+c)*UW +: UW]), .y_im(t_im_v[(b*4+c)*UW +: UW])
                    );
                end
            end
        end
    endgenerate

    // ---- 段 3: 4 点 DFT over b（d = 0..3）----
    generate
        for (c = 0; c < 4; c = c + 1) begin : g_s3
            wire signed [UW-1:0] y0r = t_re_v[(0*4+c)*UW +: UW], y0i = t_im_v[(0*4+c)*UW +: UW];
            wire signed [UW-1:0] y1r = t_re_v[(1*4+c)*UW +: UW], y1i = t_im_v[(1*4+c)*UW +: UW];
            wire signed [UW-1:0] y2r = t_re_v[(2*4+c)*UW +: UW], y2i = t_im_v[(2*4+c)*UW +: UW];
            wire signed [UW-1:0] y3r = t_re_v[(3*4+c)*UW +: UW], y3i = t_im_v[(3*4+c)*UW +: UW];
            reg signed [ZW-1:0] zr0, zi0, zr1, zi1, zr2, zi2, zr3, zi3;
            always @(posedge clk) begin
                zr0 <= y0r + y1r + y2r + y3r;   zi0 <= y0i + y1i + y2i + y3i;
                zr1 <= y0r + y1i - y2r - y3i;   zi1 <= y0i - y1r - y2i + y3r;
                zr2 <= y0r - y1r + y2r - y3r;   zi2 <= y0i - y1i + y2i - y3i;
                zr3 <= y0r - y1i - y2r + y3i;   zi3 <= y0i + y1r - y2i - y3r;
            end
            assign y_re[(c+0)*ZW +: ZW]  = zr0;  assign y_im[(c+0)*ZW +: ZW]  = zi0;
            assign y_re[(c+4)*ZW +: ZW]  = zr1;  assign y_im[(c+4)*ZW +: ZW]  = zi1;
            assign y_re[(c+8)*ZW +: ZW]  = zr2;  assign y_im[(c+8)*ZW +: ZW]  = zi2;
            assign y_re[(c+12)*ZW +: ZW] = zr3;  assign y_im[(c+12)*ZW +: ZW] = zi3;
        end
    endgenerate
endmodule
