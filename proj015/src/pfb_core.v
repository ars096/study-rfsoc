// SPDX-License-Identifier: BSD-3-Clause
//
// pfb_core — 粗い PFB（ch 間隔 128 MHz・4 倍オーバーサンプリング）のうち、1 本の ch k を出す
//
// 仕様（model/win_model.py の冒頭）:
//   y_k[m] = Σ_n h[n] · x[p − n] · exp(−j2πk(p − n)/32)、p = 8m + (N − 1)、N = 96
// 実装（model/win_fixed.py の pfb_fixed と bit 単位で同じ）:
//   1. 分岐の和   u_r[m] = Σ_t h[r + 32t] · x[p − r − 32t]（r = 0..31、t = 0..2）→ 丸め（Q10）・飽和 22 bit
//   2. 32 点 実 DFT の 1 ch: z[n] = u[2n] + j·u[2n+1] → dft16f → A = Z[k] + conj(Z[16−k])、B = Z[k] − conj(Z[16−k])
//      → 2·X = A + (−j·W32^k)·B → 共役（仕様の exp(+j2πkr/32)）
//   3. (−j)^(k·m) を掛ける（仕様の exp(−j2πkp/32) の、m で変わる部分。定数の exp(−j2πk(N−1)/32) は落とした。電力に効かない）
//   4. 丸め（Q8）・飽和 24 bit → y
//
// 入力は 1 ビート 16 サンプル（ギアボックスの出口、サンプル番号 16q + lane）。ADC の 16 bit を >>> 2 して 14 bit にする（proj010 以来）。
// **1 ビートに 2 フレーム**（ホップ 8 サンプル）: ビート q で フレーム m0 = 2q − 11（p = 16q + 7）と m1 = 2q − 10（p = 16q + 15）。
// 窓はこのビートを含む直近 7 ビート（112 サンプル）。フレームの番号 m は rst の後の最初の valid なビートを q = 0 として数え、
// **m = 0 は模型の y[0]（x の最初の N 個で作るフレーム）と同じ**。m < 0 のフレームは y*_ok = 0 で出す。
//
// s_tvalid が落ちたビートは窓を進めない（入力のサンプル列だけで決まる。途切れても値は変わらない）。
// k は RUN の間は変えない（静的）。変えたら rst を打ち直す。
//
// レイテンシ（valid なビート → y_valid）: LAT = 18 クロック（下の段の数え）。
// DSP の見当: 分岐の和 2 × 96 = 192、dft16f 2 × 32 = 64、実数化の cmul 2 × 4 = 8（窓ごと）

`timescale 1ns / 1ps

module pfb_core #(
    parameter integer UF = 10,     // u の小数部
    parameter integer UW = 22,
    parameter integer YF = 8,      // y の小数部
    parameter integer YW = 24
)(
    input  wire              clk,
    input  wire              rst,          // 同期。フレームの番号と窓を最初からにする
    input  wire [255:0]      s_tdata,      // 16 × 16 bit、lane 0 が [15:0]
    input  wire              s_tvalid,
    input  wire [4:0]        k,            // 粗い ch 0..16
    output wire signed [YW-1:0] y0_re, y0_im,   // フレーム m0 = 2q − 11
    output wire signed [YW-1:0] y1_re, y1_im,   // フレーム m1 = 2q − 10
    output wire              y0_ok, y1_ok,  // そのフレームの番号 ≧ 0
    output wire              y_valid,
    output reg  [15:0]       sat_cnt        // 飽和の回数（u・z16・b27・y の合計、飽和して止まる）
);
`include "win_coef.vh"

    localparam integer NB   = 7;           // 窓のビート数
    localparam integer NS   = 16 * NB;     // 112
    localparam integer PW   = 14 + 18 + 2; // 分岐の和の幅（3 項）
    localparam integer ZW   = 26;
    localparam integer LAT  = 18;

    // ---- 窓（7 ビート）。s_tvalid のビートだけ進める ----
    reg  [255:0] hist [0:NB-2];            // hist[0] が 1 つ前のビート
    reg  [31:0]  q_cnt;
    integer i;
    always @(posedge clk) begin
        if (rst) begin
            for (i = 0; i < NB - 1; i = i + 1) hist[i] <= 256'd0;
            q_cnt <= 32'd0;
        end else if (s_tvalid) begin
            hist[0] <= s_tdata;
            for (i = 1; i < NB - 1; i = i + 1) hist[i] <= hist[i-1];
            q_cnt <= q_cnt + 32'd1;
        end
    end

    // xw[j]: j = 0..111 がサンプル番号 16(q − 6) + j（j = 111 が今のビートの lane 15）
    reg signed [13:0] xw [0:NS-1];
    reg               va;
    reg  [31:0]       qa;
    integer j;
    always @(posedge clk) begin
        for (j = 0; j < 16; j = j + 1) xw[96 + j] <= $signed(s_tdata[16*j +: 16]) >>> 2;
        for (i = 0; i < NB - 1; i = i + 1)
            for (j = 0; j < 16; j = j + 1)
                xw[16 * (NB - 2 - i) + j] <= $signed(hist[i][16*j +: 16]) >>> 2;
        va <= s_tvalid & ~rst;
        qa <= q_cnt;
    end

    // ---- 分岐の和: 2 フレーム × 32 分岐 × 3 タップ ----
    // 段 M: 積 / 段 S1: t0 + t1 / 段 S2: + t2 / 段 R: 丸め・飽和
    function signed [17:0] hc(input integer n);
        hc = PFB_H[n*18 +: 18];
    endfunction

    wire [32*UW-1:0] u_v [0:1];
    wire [31:0]      sat_u;
    genvar f, r;
    generate
        for (f = 0; f < 2; f = f + 1) begin : g_f
            localparam integer JP = (f == 0) ? 103 : 111;   // p の位置
            for (r = 0; r < 32; r = r + 1) begin : g_r
                reg signed [31:0]   m0, m1, m2;
                reg signed [PW-1:0] s01, m2d, s;
                reg signed [UW-1:0] u;
                reg                 su;
                wire signed [PW-1:0] rs = s + (1 <<< (PFB_SH - UF - 1));
                wire signed [PW-1:0] sh = rs >>> (PFB_SH - UF);
`ifdef PFB_POSCTL
                // 陽性対照: 丸めの定数を落とす（切り捨て）。1 LSB の違いを照合が捕まえること
                wire signed [PW-1:0] shp = s >>> (PFB_SH - UF);
`else
                wire signed [PW-1:0] shp = sh;
`endif
                always @(posedge clk) begin
                    m0  <= hc(r)      * xw[JP - r];
                    m1  <= hc(r + 32) * xw[JP - r - 32];
                    m2  <= hc(r + 64) * xw[JP - r - 64];
                    s01 <= m0 + m1;
                    m2d <= m2;
                    s   <= s01 + m2d;
                    if (shp > $signed((1 <<< (UW - 1)) - 1)) begin u <= (1 <<< (UW - 1)) - 1; su <= 1'b1; end
                    else if (shp < -$signed(1 <<< (UW - 1))) begin u <= -(1 <<< (UW - 1)); su <= 1'b1; end
                    else begin u <= shp[UW-1:0]; su <= 1'b0; end
                end
                assign u_v[f][r*UW +: UW] = u;
                if (f == 0) begin : g_s
                    assign sat_u[r] = su;
                end
            end
        end
    endgenerate

    // ---- 32 点 実 DFT: z[n] = u[2n] + j·u[2n+1] → dft16f ----
    wire [16*ZW-1:0] zr_v [0:1], zi_v [0:1];
    generate
        for (f = 0; f < 2; f = f + 1) begin : g_d
            wire [16*UW-1:0] zre, zim;
            for (r = 0; r < 16; r = r + 1) begin : g_pack
                assign zre[r*UW +: UW] = u_v[f][(2*r)*UW +: UW];
                assign zim[r*UW +: UW] = u_v[f][(2*r+1)*UW +: UW];
            end
            dft16f #(.VW(UW), .UW(UW + 2), .ZW(ZW)) u_dft (
                .clk(clk), .z_re(zre), .z_im(zim), .y_re(zr_v[f]), .y_im(zi_v[f]));
        end
    endgenerate

    // ---- 選んだ ch の実数化 ----
    wire [3:0] k1 = k[3:0];                       // k mod 16
    wire [3:0] k2 = 4'd0 - k[3:0];                // (16 − k) mod 16
    wire signed [17:0] w_re = POST_WR[k*18 +: 18];
    wire signed [17:0] w_im = POST_WI[k*18 +: 18];

    wire signed [ZW+1:0] yr_v [0:1], yi_v [0:1];   // X（28 bit）。**YW で宣言すると切り詰められて巻き戻る**（初版の誤り。sim の満杯の区間で 2 フレームだけ出た）
    generate
        for (f = 0; f < 2; f = f + 1) begin : g_p
            wire signed [ZW-1:0] z1r = zr_v[f][k1*ZW +: ZW], z1i = zi_v[f][k1*ZW +: ZW];
            wire signed [ZW-1:0] z2r = zr_v[f][k2*ZW +: ZW], z2i = zi_v[f][k2*ZW +: ZW];
            reg  signed [ZW:0]   ar, ai, br, bi;      // 27 bit
            reg  signed [ZW:0]   ard [0:3], aid [0:3];
            wire signed [ZW:0]   cr, ci;
            reg  signed [ZW+1:0] xr, xi;
            always @(posedge clk) begin
                ar <= z1r + z2r;   ai <= z1i - z2i;           // Z[k] + conj(Z[16−k])
                br <= z1r - z2r;   bi <= z1i + z2i;           // Z[k] − conj(Z[16−k])
                ard[0] <= ar;  aid[0] <= ai;
                ard[1] <= ard[0];  aid[1] <= aid[0];
                ard[2] <= ard[1];  aid[2] <= aid[1];
                ard[3] <= ard[2];  aid[3] <= aid[2];
                xr <= ard[3] + cr;
                xi <= -(aid[3] + ci);                          // 共役
            end
            cmul #(.AW(ZW + 1), .OW(ZW + 1)) u_post (
                .clk(clk), .a_re(br), .a_im(bi), .w_re(w_re), .w_im(w_im), .y_re(cr), .y_im(ci));
            assign yr_v[f] = xr;   // 後段で回して丸める（下）
            assign yi_v[f] = xi;
        end
    endgenerate

    // ---- タグ（valid・フレームの番号の下位）を LAT − 2 段運ぶ（最後の 2 段は下で回しと丸め）----
    // 段の数え: xw 1 → M 1 → S1 1 → S2 1 → R 1 → dft16f 6 → A/B 1 → cmul 4 → X 1 = 17、回し 1 = 18
    localparam integer TL = 16;             // qa（xw と同じ段）から X の段まで
    reg        tv  [0:TL-1];
    reg [31:0] tq  [0:TL-1];
    always @(posedge clk) begin
        tv[0] <= va;  tq[0] <= qa;
        for (i = 1; i < TL; i = i + 1) begin tv[i] <= tv[i-1]; tq[i] <= tq[i-1]; end
    end
    wire [31:0] qx = tq[TL-1];             // X の段にいるビートの q
    // m0 = 2q − 11 ≡ 2q + 1 (mod 4)、m1 = 2q − 10 ≡ 2q + 2 (mod 4)
    wire [1:0] m0m = {qx[0], 1'b1};
    wire [1:0] m1m = {~qx[0], 1'b0};
    wire [1:0] e0  = k[1:0] * m0m;          // (k·m) mod 4
    wire [1:0] e1  = k[1:0] * m1m;
    wire ok0 = (qx >= 32'd6);               // m0 ≧ 0
    wire ok1 = (qx >= 32'd5);               // m1 ≧ 0

    // ---- (−j)^e を掛け、丸めて飽和 ----
    localparam integer XW = ZW + 2;
    function signed [XW-1:0] rot_re(input signed [XW-1:0] r, input signed [XW-1:0] q, input [1:0] e);
        case (e) 2'd0: rot_re = r; 2'd1: rot_re = q; 2'd2: rot_re = -r; default: rot_re = -q; endcase
    endfunction
    function signed [XW-1:0] rot_im(input signed [XW-1:0] r, input signed [XW-1:0] q, input [1:0] e);
        case (e) 2'd0: rot_im = q; 2'd1: rot_im = -r; 2'd2: rot_im = -q; default: rot_im = r; endcase
    endfunction
    localparam integer SH2 = UF + 1 - YF;   // 3
    function signed [YW:0] rnd_sat(input signed [XW-1:0] a);   // [YW] = 飽和した
        reg signed [XW-1:0] t;
        begin
            t = (a + (1 <<< (SH2 - 1))) >>> SH2;
            if (t > $signed((1 <<< (YW - 1)) - 1))      rnd_sat = {1'b1, 1'b0, {(YW-1){1'b1}}};
            else if (t < -$signed(1 <<< (YW - 1)))      rnd_sat = {1'b1, 1'b1, {(YW-1){1'b0}}};
            else                                        rnd_sat = {1'b0, t[YW-1:0]};
        end
    endfunction

    reg signed [YW-1:0] o0r, o0i, o1r, o1i;
    reg                 ov, ook0, ook1;
    reg                 osat;
    wire [YW:0] a0r = rnd_sat(rot_re(yr_v[0], yi_v[0], e0));
    wire [YW:0] a0i = rnd_sat(rot_im(yr_v[0], yi_v[0], e0));
    wire [YW:0] a1r = rnd_sat(rot_re(yr_v[1], yi_v[1], e1));
    wire [YW:0] a1i = rnd_sat(rot_im(yr_v[1], yi_v[1], e1));
    always @(posedge clk) begin
        o0r <= a0r[YW-1:0];  o0i <= a0i[YW-1:0];
        o1r <= a1r[YW-1:0];  o1i <= a1i[YW-1:0];
        ov  <= tv[TL-1];
        ook0 <= ok0;  ook1 <= ok1;
        osat <= tv[TL-1] & (a0r[YW] | a0i[YW] | a1r[YW] | a1i[YW]);
    end
    assign y0_re = o0r;  assign y0_im = o0i;
    assign y1_re = o1r;  assign y1_im = o1i;
    assign y0_ok = ook0; assign y1_ok = ook1;
    assign y_valid = ov;

    // 飽和の回数（u は代表として f = 0 の 32 本の OR、y は出口。z16・b27 は語幅の上限から起きない — 模型で確かめる）
    always @(posedge clk) begin
        if (rst) sat_cnt <= 16'd0;
        else if ((osat | (|sat_u)) && sat_cnt != 16'hFFFF) sat_cnt <= sat_cnt + 16'd1;
    end
endmodule
