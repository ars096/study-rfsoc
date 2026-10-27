// SPDX-License-Identifier: BSD-3-Clause
//
// pfb64_core — 粗い PFB（ch 間隔 64 MHz・4 倍オーバーサンプリング・1 ch 256 MSPS = 1 標本 / クロック）。
//   NH 個の窓の頭に、それぞれの粗い ch k_h（0..32）を出す（proj032 E-2。proj021 の pfb_core を M 32 → 64 に写した）
//
// 仕様（model/win64_model.py の冒頭）:
//   y_k[m] = Σ_n h[n] · x[p − n] · exp(−j2πk(p − n)/64)、p = 16m + (N − 1)、N = 192
// 実装:
//   1. 分岐の和   u_r[m] = Σ_t h[r + 64t] · x[p − r − 64t]（r = 0..63、t = 0..2）→ 丸め（UF）・飽和 UW bit
//   2. 64 点の実 DFT の 1 ch: z[n] = u[2n] + j·u[2n+1]（n = 0..31）→ 32 点の複素 DFT
//        = dft16f（偶の z）と dft16f（奇の z）→ T[k] = W32^k · O[k] → Z[k] = E[k] + T[k]、Z[k+16] = E[k] − T[k]
//        → 頭ごとに A = Z[k] + conj(Z[32−k])、B = Z[k] − conj(Z[32−k]) → 2·X = A + (−j·W64^k)·B → 共役
//   3. (−j)^(k·m) を掛ける（p = 16m + 191 なので exp(−j2πkp/64) の m で変わる部分は exp(−jπkm/2)）
//   4. 丸め（YF）・飽和 YW bit → y
// **E-2 の資源を数えるための版**（窓ごとの始まり・飽和の数え・ok の印は proj021 の pfb_core から後で写す）。
// 値の照合（整数の模型と bit 単位）はまだ。
//
// 入力は 1 ビート 16 サンプル（ギアボックスの出口）。ADC の 16 bit を >>> 2 して 14 bit（proj010 以来）。
// **1 ビートに 1 フレーム**（ホップ 16）: ビート q でフレーム m = q − 11（p = 16q + 15）。窓は直近 12 ビート（192 サンプル）。
// 語幅: |u| ≦ 8191 × max_r Σ_t |h[r + 64t]| = 514（M-0 の係数）→ 整数 10 bit ＋ 符号 ＋ UF 10 = **UW 21**（proj021 は 22。分岐が倍で枝の和が半分）
//   dft16f: 21 → 25、回転 25、Z = E ± T で 26、A・B 27（**cmul の AW ≦ 27 で積 1 つが DSP 1 個**）

`timescale 1ns / 1ps

module pfb64_core #(
    parameter integer UF = 10,
    parameter integer UW = 21,
    parameter integer YF = 8,
    parameter integer YW = 24,
    parameter integer NH = 16,     // 窓の頭の数
    parameter integer PSPLIT = 0   // 1: 頭を粗い ch の偶奇で 2 組に（頭 0..NH/2−1 は偶の k だけ、残りは奇の k だけ）。選択が 32:1 → 16:1
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [255:0]      s_tdata,      // 16 × 16 bit、lane 0 が [15:0]
    input  wire              s_tvalid,
    input  wire [6*NH-1:0]   k,            // 頭 h の粗い ch 0..32 が [6h +: 6]（静的）
    output wire [YW*NH-1:0]  y_re, y_im,   // 頭 h が [YW·h +: YW]。フレーム m = q − 11
    output wire              y_valid
);
`include "pfb64_coef.vh"

    localparam integer NB = 12;            // 窓のビート数
    localparam integer NS = 16 * NB;       // 192
    localparam integer PW = 14 + 18 + 2;
    localparam integer DW = UW + 4;        // dft16f の出口 25
    localparam integer ZW = DW + 1;        // 26
    localparam integer AW = ZW + 1;        // 27

    // ---- 窓（12 ビート）----
    reg  [255:0] hist [0:NB-2];
    reg  [3:0]   g_cnt;                    // 11 で止まる（窓が埋まった）
    reg  [1:0]   m_cnt;                    // フレームの番号 mod 4（窓が埋まった最初のフレームが 0）
    integer i, j;
    always @(posedge clk) begin
        if (rst) begin
            g_cnt <= 4'd0; m_cnt <= 2'd0;
        end else if (s_tvalid) begin
            hist[0] <= s_tdata;
            for (i = 1; i < NB - 1; i = i + 1) hist[i] <= hist[i-1];
            if (g_cnt != 4'd11) g_cnt <= g_cnt + 4'd1;
            else                m_cnt <= m_cnt + 2'd1;
        end
    end

    // xw[j]: j = 0..191 がサンプル番号 16(q − 11) + j（j = 191 が今のビートの lane 15）
    reg signed [13:0] xw [0:NS-1];
    reg               va;
    reg  [1:0]        vm;
    integer i2, j2;
    always @(posedge clk) begin
        for (j2 = 0; j2 < 16; j2 = j2 + 1) xw[NS - 16 + j2] <= $signed(s_tdata[16*j2 +: 16]) >>> 2;
        for (i2 = 0; i2 < NB - 1; i2 = i2 + 1)
            for (j2 = 0; j2 < 16; j2 = j2 + 1)
                xw[16 * (NB - 2 - i2) + j2] <= $signed(hist[i2][16*j2 +: 16]) >>> 2;
        va <= s_tvalid & ~rst & (g_cnt == 4'd11);
        vm <= m_cnt;
    end

    // ---- 分岐の和: 64 分岐 × 3 タップ ----
    function signed [17:0] hc(input integer n);
        hc = PFB64_H[n*18 +: 18];
    endfunction

    wire [64*UW-1:0] u_v;
    genvar r;
    generate
        for (r = 0; r < 64; r = r + 1) begin : g_r
            reg signed [31:0]   m0, m1, m2;
            reg signed [PW-1:0] s01, m2d, s;
            reg signed [UW-1:0] u;
            wire signed [PW-1:0] rs = s + (1 <<< (PFB64_SH - UF - 1));
            wire signed [PW-1:0] sh = rs >>> (PFB64_SH - UF);
            always @(posedge clk) begin
                m0  <= hc(r)       * xw[NS - 1 - r];
                m1  <= hc(r + 64)  * xw[NS - 1 - r - 64];
                m2  <= hc(r + 128) * xw[NS - 1 - r - 128];
                s01 <= m0 + m1;
                m2d <= m2;
                s   <= s01 + m2d;
                if (sh > $signed((1 <<< (UW - 1)) - 1))  u <= (1 <<< (UW - 1)) - 1;
                else if (sh < -$signed(1 <<< (UW - 1)))  u <= -(1 <<< (UW - 1));
                else                                      u <= sh[UW-1:0];
            end
            assign u_v[r*UW +: UW] = u;
        end
    endgenerate

    // ---- 32 点の複素 DFT ----
    // z[n] = u[2n] + j·u[2n+1]。偶の z[2a] = u[4a] + j·u[4a+1]、奇の z[2a+1] = u[4a+2] + j·u[4a+3]（a = 0..15）
    wire [16*UW-1:0] er, ei, or_, oi;
    genvar a;
    generate
        for (a = 0; a < 16; a = a + 1) begin : g_pack
            assign er [a*UW +: UW] = u_v[(4*a)*UW   +: UW];
            assign ei [a*UW +: UW] = u_v[(4*a+1)*UW +: UW];
            assign or_[a*UW +: UW] = u_v[(4*a+2)*UW +: UW];
            assign oi [a*UW +: UW] = u_v[(4*a+3)*UW +: UW];
        end
    endgenerate
    wire [16*DW-1:0] Er, Ei, Or, Oi;
    dft16f #(.VW(UW), .UW(UW + 2), .ZW(DW)) u_dfte (.clk(clk), .z_re(er),  .z_im(ei), .y_re(Er), .y_im(Ei));
    dft16f #(.VW(UW), .UW(UW + 2), .ZW(DW)) u_dfto (.clk(clk), .z_re(or_), .z_im(oi), .y_re(Or), .y_im(Oi));

    // 回転 T[k] = W32^k · O[k]（k = 0: 1、k = 8: −j は cmul を通さず遅延線。cmul と bit 単位で同じ）
    wire [16*ZW-1:0] Zr, Zi;                 // Z[0..15]
    wire [16*ZW-1:0] Zr2, Zi2;               // Z[16..31]
    genvar kk;
    generate
        for (kk = 0; kk < 16; kk = kk + 1) begin : g_tw
            wire signed [DW-1:0] o_r = Or[kk*DW +: DW], o_i = Oi[kk*DW +: DW];
            wire signed [DW-1:0] t_r, t_i;
            reg  signed [DW-1:0] ed_r [0:3], ed_i [0:3];
            integer ii;
            if (kk == 0 || kk == 8) begin : g_triv
                reg signed [DW-1:0] td_r [0:3], td_i [0:3];
                integer it;
                always @(posedge clk) begin
                    td_r[0] <= (kk == 0) ? o_r :  o_i;          // −j·(r + ji) = i − jr
                    td_i[0] <= (kk == 0) ? o_i : -o_r;
                    for (it = 1; it < 4; it = it + 1) begin td_r[it] <= td_r[it-1]; td_i[it] <= td_i[it-1]; end
                end
                assign t_r = td_r[3]; assign t_i = td_i[3];
            end else begin : g_cm
                cmul #(.AW(DW), .OW(DW)) u_tw (
                    .clk(clk), .a_re(o_r), .a_im(o_i),
                    .w_re(TW32_R[kk*18 +: 18]), .w_im(TW32_I[kk*18 +: 18]), .y_re(t_r), .y_im(t_i));
            end
            always @(posedge clk) begin
                ed_r[0] <= Er[kk*DW +: DW];  ed_i[0] <= Ei[kk*DW +: DW];
                for (ii = 1; ii < 4; ii = ii + 1) begin ed_r[ii] <= ed_r[ii-1]; ed_i[ii] <= ed_i[ii-1]; end
            end
            reg signed [ZW-1:0] z1r, z1i, z2r, z2i;
            always @(posedge clk) begin
                z1r <= ed_r[3] + t_r;  z1i <= ed_i[3] + t_i;
                z2r <= ed_r[3] - t_r;  z2i <= ed_i[3] - t_i;
            end
            assign Zr [kk*ZW +: ZW] = z1r;  assign Zi [kk*ZW +: ZW] = z1i;
            assign Zr2[kk*ZW +: ZW] = z2r;  assign Zi2[kk*ZW +: ZW] = z2i;
        end
    endgenerate
    wire [32*ZW-1:0] ZR = {Zr2, Zr};
    wire [32*ZW-1:0] ZI = {Zi2, Zi};

    // ---- valid と m を出口まで運ぶ ----
    // 段の数え: xw 1 → M 1 → S1 1 → S2 1 → R 1 → dft16f 6 → 回転 4 → Z 1 → 選択 1 → A/B 1 → B の遅れ 1 → cmul 4 → X 1 → 出口 1
    localparam integer TL = 1 + 1 + 1 + 1 + 6 + 4 + 1 + 1 + 1 + 1 + 4 + 1;   // va から X の段まで 23
    reg       tv [0:TL-1];
    reg [1:0] tm [0:TL-1];
    integer it2;
    always @(posedge clk) begin
        tv[0] <= va; tm[0] <= vm;
        for (it2 = 1; it2 < TL; it2 = it2 + 1) begin tv[it2] <= tv[it2-1]; tm[it2] <= tm[it2-1]; end
    end
    reg ov;
    always @(posedge clk) ov <= tv[TL-1];
    assign y_valid = ov;

    localparam integer XW = AW + 1;
    function signed [XW-1:0] rot_re(input signed [XW-1:0] p, input signed [XW-1:0] q, input [1:0] e);
        case (e) 2'd0: rot_re = p; 2'd1: rot_re = q; 2'd2: rot_re = -p; default: rot_re = -q; endcase
    endfunction
    function signed [XW-1:0] rot_im(input signed [XW-1:0] p, input signed [XW-1:0] q, input [1:0] e);
        case (e) 2'd0: rot_im = q; 2'd1: rot_im = -p; 2'd2: rot_im = -q; default: rot_im = p; endcase
    endfunction
    localparam integer SH2 = UF + 1 - YF;
    function signed [YW-1:0] rnd_sat(input signed [XW-1:0] v);
        reg signed [XW-1:0] t;
        begin
            t = (v + (1 <<< (SH2 - 1))) >>> SH2;
            if (t > $signed((1 <<< (YW - 1)) - 1))  rnd_sat = (1 <<< (YW - 1)) - 1;
            else if (t < -$signed(1 <<< (YW - 1)))  rnd_sat = -(1 <<< (YW - 1));
            else                                    rnd_sat = t[YW-1:0];
        end
    endfunction

    // ---- 頭ごとの実数化 ----
    genvar g;
    generate
        for (g = 0; g < NH; g = g + 1) begin : g_h
            wire [5:0] kh = k[6*g +: 6];
            wire [4:0] k1 = kh[4:0];                   // k mod 32
            wire [4:0] k2 = 5'd0 - kh[4:0];            // (32 − k) mod 32（k と偶奇が同じ）
            // PSPLIT: この頭の偶奇 PB の Z だけを並べた 16 本から、k1 / 2・k2 / 2 で選ぶ（k の最下位 bit は PB に固定）
            localparam integer PB = (g < NH / 2) ? 0 : 1;
            wire [16*ZW-1:0] ZRp, ZIp;
            genvar jj;
            for (jj = 0; jj < 16; jj = jj + 1) begin : g_pk
                assign ZRp[jj*ZW +: ZW] = ZR[(2*jj + PB)*ZW +: ZW];
                assign ZIp[jj*ZW +: ZW] = ZI[(2*jj + PB)*ZW +: ZW];
            end
            reg  signed [17:0] w_re, w_im;
            always @(posedge clk) begin w_re <= POST64_WR[kh*18 +: 18]; w_im <= POST64_WI[kh*18 +: 18]; end
            reg  signed [ZW-1:0] s1r, s1i, s2r, s2i;
            reg  signed [AW-1:0] ar, ai, br, bi, brd, bid;
            reg  signed [AW-1:0] ard [0:4], aid [0:4];
            wire signed [AW-1:0] cr, ci;
            reg  signed [XW-1:0] xr, xi;
            integer ih;
            always @(posedge clk) begin
                if (PSPLIT) begin
                    s1r <= ZRp[k1[4:1]*ZW +: ZW];  s1i <= ZIp[k1[4:1]*ZW +: ZW];
                    s2r <= ZRp[k2[4:1]*ZW +: ZW];  s2i <= ZIp[k2[4:1]*ZW +: ZW];
                end else begin
                    s1r <= ZR[k1*ZW +: ZW];  s1i <= ZI[k1*ZW +: ZW];
                    s2r <= ZR[k2*ZW +: ZW];  s2i <= ZI[k2*ZW +: ZW];
                end
                ar <= s1r + s2r;  ai <= s1i - s2i;          // Z[k] + conj(Z[32−k])
                br <= s1r - s2r;  bi <= s1i + s2i;          // Z[k] − conj(Z[32−k])
                brd <= br;  bid <= bi;
                ard[0] <= ar;  aid[0] <= ai;
                for (ih = 1; ih < 5; ih = ih + 1) begin ard[ih] <= ard[ih-1]; aid[ih] <= aid[ih-1]; end
                xr <= ard[4] + cr;
                xi <= -(aid[4] + ci);                       // 共役
            end
            cmul #(.AW(AW), .OW(AW)) u_post (
                .clk(clk), .a_re(brd), .a_im(bid), .w_re(w_re), .w_im(w_im), .y_re(cr), .y_im(ci));

`ifdef PFB64_POSCTL
            wire [1:0] e = kh[1:0] * (tm[TL-1] + 2'd1);   // 陽性対照: m を 1 ずらす（フレームの番号の取り違え）
`else
            wire [1:0] e = kh[1:0] * tm[TL-1];            // (k·m) mod 4
`endif
            reg signed [YW-1:0] o_r, o_i;
            always @(posedge clk) begin
                o_r <= rnd_sat(rot_re(xr, xi, e));
                o_i <= rnd_sat(rot_im(xr, xi, e));
            end
            assign y_re[YW*g +: YW] = o_r;
            assign y_im[YW*g +: YW] = o_i;
        end
    endgenerate
endmodule
