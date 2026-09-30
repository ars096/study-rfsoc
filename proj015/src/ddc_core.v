// SPDX-License-Identifier: BSD-3-Clause
//
// ddc_core — 粗い ch（pfb_core の出力）→ NCO → 半帯域 × NS 段 → FFT の入力 z（1 窓ぶん）
//
// 仕様と丸め: model/win_fixed.py の ddc_fixed と bit 単位で同じ。
//   v[m] = round((y[m] · (cos φ − j sin φ)) / 2^17)、φ = 2π(a + 1/2) / 2^14、a = (m·Δ mod 2^32) の上位 14 bit
//   半帯域: light × (NS − 1) → final × 1（NS = 1..8 → 幅 256 / 128 / 64 / 32 / 16 / 8 / 4 / 2 MHz。proj015 で 4・2 MHz を足した）
//   z = sat18(round(v / 2^(VF − G)))、G = NS ≧ GNS なら GH（5）、それ以外は G（4）（win_fixed.py の gz）
// m = 0 は pfb_core の最初の ok なフレーム（y1 側に出る m = 2q − 10 = 0）。NCO の位相はそこで 0。
//
// 流れ:
//   pfb_core は 1 ビートに（y0 = 奇 m, y1 = 偶 m）を出す。組（偶 m, 奇 m + 1）は「このビートの y1」と「次のビートの y0」
//   → 組にまとめ直して NCO へ（2 サンプル / 組）。NCO の出力の組 → 1 段目の半帯域（hb2）→ 1 サンプル → pair2 → 2 段目 …
//   最終段（final）の入力は NS で選ぶ: NS = 1 なら NCO の組そのもの、NS ≧ 2 なら light の (NS − 1) 段目の出力を組にしたもの
// NS・Δ は RUN の間は変えない。変えたら rst。
//
// 資源（この版、時分割なし）: NCO の乗算 8、light 7 段 × 10、final 36 → 114 DSP（proj014 は light 5 段で 94）。表は 2 口の ROM × 2（1/4 波 4096 語 × 18 bit）

`timescale 1ns / 1ps

module ddc_core #(
    parameter integer YW = 24,
    parameter integer VW = 24,
    parameter integer VF = 8,
    parameter integer ZW = 18,
    parameter integer G  = 4,      // NS < GNS の FFT の入力の小数
    parameter integer GH = 5,      // NS ≧ GNS（4・2 MHz）の FFT の入力の小数（proj015）
    parameter integer GNS = 7,
    parameter integer P  = 14
)(
    input  wire                 clk,
    input  wire                 rst,
    input  wire                 y_valid,
    input  wire                 y0_ok, y1_ok,
    input  wire signed [YW-1:0] y0_re, y0_im, y1_re, y1_im,
    input  wire [31:0]          dphi,
    input  wire [3:0]           ns,           // 1..8
    output reg                  z_valid,
    output reg  signed [ZW-1:0] z_re, z_im,
    output reg  [15:0]          sat_cnt
);
`include "win_coef.vh"

    // ---- 組にまとめ直す: (このビートの y1, 次のビートの y0) ----
    reg                 hv;
    reg signed [YW-1:0] hr, hi;
    reg                 pv;
    reg signed [YW-1:0] per, pei, por, poi;
    always @(posedge clk) begin
        pv <= 1'b0;
        if (rst) begin
            hv <= 1'b0;
        end else if (y_valid) begin
            if (hv & y0_ok) begin
                per <= hr;  pei <= hi;  por <= y0_re;  poi <= y0_im;
                pv  <= 1'b1;
            end
            hr <= y1_re;  hi <= y1_im;  hv <= y1_ok;
        end
    end

    // ---- NCO: 組 n で θe = 2nΔ、θo = 2nΔ + Δ ----
    reg  [31:0] acc;
    reg  [31:0] th_e, th_o;
    reg         nv1;
    reg signed [YW-1:0] d1er, d1ei, d1or, d1oi;
    always @(posedge clk) begin
        nv1 <= 1'b0;
        if (rst) acc <= 32'd0;
        else if (pv) begin
            th_e <= acc;
            th_o <= acc + dphi;
            acc  <= acc + {dphi[30:0], 1'b0};
            nv1  <= 1'b1;
            d1er <= per; d1ei <= pei; d1or <= por; d1oi <= poi;
        end
    end
    localparam integer QA = P - 2;
`ifdef DDC_POSCTL
    wire [P-1:0]  ae = th_e[31 -: P] + 1'b1;         // 陽性対照: 偶の側の NCO の番地を 1 つずらす
`else
    wire [P-1:0]  ae = th_e[31 -: P];
`endif
    wire [P-1:0]  ao = th_o[31 -: P];
    wire [QA-1:0] re_ = ae[QA-1:0], ro_ = ao[QA-1:0];
    wire [QA-1:0] qm = {QA{1'b1}};
    wire signed [17:0] te_a, te_b, to_a, to_b;     // T[r]、T[q − 1 − r]
    nco_rom u_rom_e (.clk(clk), .a0(re_), .a1(qm - re_), .d0(te_a), .d1(te_b));
    nco_rom u_rom_o (.clk(clk), .a0(ro_), .a1(qm - ro_), .d0(to_a), .d1(to_b));
    reg [1:0] qde, qdo;
    reg       nv2;
    reg signed [YW-1:0] d2er, d2ei, d2or, d2oi;
    always @(posedge clk) begin
        qde <= ae[P-1 -: 2];  qdo <= ao[P-1 -: 2];
        nv2 <= nv1;
        d2er <= d1er; d2ei <= d1ei; d2or <= d1or; d2oi <= d1oi;
    end
    // 象限 0: s = a, c = b / 1: s = b, c = −a / 2: s = −a, c = −b / 3: s = −b, c = a
    function signed [17:0] fsin(input [1:0] qd, input signed [17:0] a, input signed [17:0] b);
        case (qd) 2'd0: fsin = a; 2'd1: fsin = b; 2'd2: fsin = -a; default: fsin = -b; endcase
    endfunction
    function signed [17:0] fcos(input [1:0] qd, input signed [17:0] a, input signed [17:0] b);
        case (qd) 2'd0: fcos = b; 2'd1: fcos = -a; 2'd2: fcos = -b; default: fcos = a; endcase
    endfunction
    reg signed [17:0] ce, se, co, so;
    reg               nv3;
    reg signed [YW-1:0] d3er, d3ei, d3or, d3oi;
    always @(posedge clk) begin
        ce <= fcos(qde, te_a, te_b);  se <= fsin(qde, te_a, te_b);
        co <= fcos(qdo, to_a, to_b);  so <= fsin(qdo, to_a, to_b);
        nv3 <= nv2;
        d3er <= d2er; d3ei <= d2ei; d3or <= d2or; d3oi <= d2oi;
    end
    // 混合: (yr + j yi)(c − j s) = (yr c + yi s) + j (yi c − yr s)
    localparam integer MW = YW + 18;
    reg signed [MW-1:0] m1, m2, m3, m4, m5, m6, m7, m8;
    reg                 nv4;
    always @(posedge clk) begin
        m1 <= d3er * ce;  m2 <= d3ei * se;  m3 <= d3ei * ce;  m4 <= d3er * se;
        m5 <= d3or * co;  m6 <= d3oi * so;  m7 <= d3oi * co;  m8 <= d3or * so;
        nv4 <= nv3;
    end
    localparam integer SHV = 17 + 8 - VF;           // Y_F = 8
    function signed [VW:0] rsat(input signed [MW:0] a);   // [VW] = 飽和
        reg signed [MW:0] t;
        begin
            t = (a + (1 <<< (SHV - 1))) >>> SHV;
            if (t > $signed((1 <<< (VW - 1)) - 1))  rsat = {1'b1, 1'b0, {(VW-1){1'b1}}};
            else if (t < -$signed(1 <<< (VW - 1)))  rsat = {1'b1, 1'b1, {(VW-1){1'b0}}};
            else                                    rsat = {1'b0, t[VW-1:0]};
        end
    endfunction
    reg signed [MW:0] s1, s2, s3, s4;
    reg               nv5;
    always @(posedge clk) begin
        s1 <= m1 + m2;  s2 <= m3 - m4;  s3 <= m5 + m6;  s4 <= m7 - m8;
        nv5 <= nv4;
    end
    wire [VW:0] ver = rsat(s1), vei = rsat(s2), vor = rsat(s3), voi = rsat(s4);
    reg               vv;                             // NCO の出力の組
    reg signed [VW-1:0] ver_r, vei_r, vor_r, voi_r;
    reg               vsat;
    always @(posedge clk) begin
        ver_r <= ver[VW-1:0]; vei_r <= vei[VW-1:0]; vor_r <= vor[VW-1:0]; voi_r <= voi[VW-1:0];
        vv    <= nv5 & ~rst;
        vsat  <= nv5 & (ver[VW] | vei[VW] | vor[VW] | voi[VW]);
    end

    // ---- 半帯域の縦続 ----
    // pr*[0] = NCO の組、pr*[j] = light の j 段目の出力を組にしたもの（j = 1..NL）
    localparam integer NL = 7;
    wire                 pv_a [0:NL];
    wire signed [VW-1:0] pa_er [0:NL], pa_ei [0:NL], pa_or [0:NL], pa_oi [0:NL];
    assign pv_a[0] = vv;
    assign pa_er[0] = ver_r; assign pa_ei[0] = vei_r; assign pa_or[0] = vor_r; assign pa_oi[0] = voi_r;
    wire [NL-1:0] lsat;
    genvar j;
    generate
        for (j = 1; j <= NL; j = j + 1) begin : g_l
            wire                 lv;
            wire signed [VW-1:0] lr, li;
            hb2 #(.N(HBL_N), .SH(HBL_SH), .H(HBL_H), .W(VW)) u_hb (
                .clk(clk), .rst(rst), .in_v(pv_a[j-1]),
                .e_re(pa_er[j-1]), .e_im(pa_ei[j-1]), .o_re(pa_or[j-1]), .o_im(pa_oi[j-1]),
                .out_v(lv), .y_re(lr), .y_im(li), .sat(lsat[j-1]));
            pair2 #(.W(VW)) u_pair (
                .clk(clk), .rst(rst), .in_v(lv), .x_re(lr), .x_im(li),
                .out_v(pv_a[j]), .e_re(pa_er[j]), .e_im(pa_ei[j]), .o_re(pa_or[j]), .o_im(pa_oi[j]));
        end
    endgenerate
    // 最終段の入力: pr[NS − 1]
    wire [2:0] sel = (ns >= 4'd1 && ns <= 4'd8) ? ns[2:0] - 3'd1 : 3'd0;   // ns = 8 → 3'b000 − 1 = 7
    wire                 fv;
    wire signed [VW-1:0] fr, fi;
    wire                 fsat;
    hb2 #(.N(HBF_N), .SH(HBF_SH), .H(HBF_H), .W(VW)) u_final (
        .clk(clk), .rst(rst), .in_v(pv_a[sel]),
        .e_re(pa_er[sel]), .e_im(pa_ei[sel]), .o_re(pa_or[sel]), .o_im(pa_oi[sel]),
        .out_v(fv), .y_re(fr), .y_im(fi), .sat(fsat));

    // ---- z = sat18(round(v / 2^(VF − G)))。G は NS で選ぶ（静的。NS は RUN の間は変えない）----
    localparam integer SHZ = VF - G;
    localparam integer SHH = VF - GH;
`ifdef DDC_POSCTL_G
    wire               zg  = 1'b0;               // 陽性対照: NS に依らず G（4）。NS 7・8 だけ模型と合わなくなるはず
`else
    wire               zg  = (ns >= GNS);
`endif
    wire signed [VW:0] zr0l = ($signed({fr[VW-1], fr}) + (1 <<< (SHZ - 1))) >>> SHZ;
    wire signed [VW:0] zi0l = ($signed({fi[VW-1], fi}) + (1 <<< (SHZ - 1))) >>> SHZ;
    wire signed [VW:0] zr0h = ($signed({fr[VW-1], fr}) + (1 <<< (SHH - 1))) >>> SHH;
    wire signed [VW:0] zi0h = ($signed({fi[VW-1], fi}) + (1 <<< (SHH - 1))) >>> SHH;
    wire signed [VW:0] zr0 = zg ? zr0h : zr0l;
    wire signed [VW:0] zi0 = zg ? zi0h : zi0l;
    localparam signed [VW:0] ZMX = (1 <<< (ZW - 1)) - 1;
    localparam signed [VW:0] ZMN = -(1 <<< (ZW - 1));
    reg zsat;
    always @(posedge clk) begin
        z_re    <= (zr0 > ZMX) ? ZMX[ZW-1:0] : (zr0 < ZMN) ? ZMN[ZW-1:0] : zr0[ZW-1:0];
        z_im    <= (zi0 > ZMX) ? ZMX[ZW-1:0] : (zi0 < ZMN) ? ZMN[ZW-1:0] : zi0[ZW-1:0];
        z_valid <= fv & ~rst;
        zsat    <= fv & ((zr0 > ZMX) | (zr0 < ZMN) | (zi0 > ZMX) | (zi0 < ZMN));
    end

    // 飽和の回数（NCO の出口・使っている light の段・final・z。使っていない light の段は数えない）
    wire [NL-1:0] lmask = (sel == 3'd0) ? {NL{1'b0}} : (({{(NL-1){1'b0}}, 1'b1} << sel) - 1'b1);
    always @(posedge clk) begin
        if (rst) sat_cnt <= 16'd0;
        else if ((vsat | (|(lsat & lmask)) | fsat | zsat) && sat_cnt != 16'hFFFF) sat_cnt <= sat_cnt + 16'd1;
    end
endmodule
