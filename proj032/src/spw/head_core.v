// SPDX-License-Identifier: BSD-3-Clause
//
// head_core — 窓の頭（proj032 E-2b）: 粗い ch（pfb64_core の出口、1 標本 / クロック）→ NCO → light 1 段目（半帯域 ÷2）→ 0.5 標本 / クロック
//   NCO と混合は proj021 の ddc_core（2 標本 / クロック）の片側だけ、light 1 段目は proj021 の hb2s（C 2）をそのまま使う
//   **E-2b の資源を数えるための版**（値の照合は P の段で。窓ごとの始まり・飽和の数えはまだ）
//
//   v[m] = round((y[m] · (cos φ − j sin φ)) / 2^SHV)、φ = 2π(a + 1/2) / 2^14、a = (m·Δ mod 2^32) の上位 14 bit
//   組（偶 m, 奇 m + 1）にして hb2s へ（組は 2 クロックに 1 回 → C 2 で足りる）

`timescale 1ns / 1ps

module head_core #(
    parameter integer YW = 24,
    parameter integer VW = 24,
    parameter integer VF = 8,
    parameter integer P  = 14
)(
    input  wire                 clk,
    input  wire                 rst,
    input  wire                 y_valid,
    input  wire signed [YW-1:0] y_re, y_im,
    input  wire [31:0]          dphi,
    output wire                 z_valid,
    output wire signed [VW-1:0] z_re, z_im,
    output wire                 sat,
    output wire                 ovr
);
    // ---- NCO ----
    reg  [31:0] acc, th;
    reg         nv1;
    reg signed [YW-1:0] d1r, d1i;
    always @(posedge clk) begin
        nv1 <= 1'b0;
        if (rst) acc <= 32'd0;
        else if (y_valid) begin
            th  <= acc;
            acc <= acc + dphi;
            nv1 <= 1'b1;
            d1r <= y_re; d1i <= y_im;
        end
    end
    localparam integer QA = P - 2;
    wire [P-1:0]  aa = th[31 -: P];
    wire [QA-1:0] ra = aa[QA-1:0];
    wire [QA-1:0] qm = {QA{1'b1}};
    wire signed [17:0] ta, tb;
    nco_rom u_rom (.clk(clk), .a0(ra), .a1(qm - ra), .d0(ta), .d1(tb));
    reg [1:0] qd;
    reg       nv2;
    reg signed [YW-1:0] d2r, d2i;
    always @(posedge clk) begin qd <= aa[P-1 -: 2]; nv2 <= nv1; d2r <= d1r; d2i <= d1i; end
    function signed [17:0] fsin(input [1:0] q, input signed [17:0] a, input signed [17:0] b);
        case (q) 2'd0: fsin = a; 2'd1: fsin = b; 2'd2: fsin = -a; default: fsin = -b; endcase
    endfunction
    function signed [17:0] fcos(input [1:0] q, input signed [17:0] a, input signed [17:0] b);
        case (q) 2'd0: fcos = b; 2'd1: fcos = -a; 2'd2: fcos = -b; default: fcos = a; endcase
    endfunction
    reg signed [17:0] c, s;
    reg               nv3;
    reg signed [YW-1:0] d3r, d3i;
    always @(posedge clk) begin c <= fcos(qd, ta, tb); s <= fsin(qd, ta, tb); nv3 <= nv2; d3r <= d2r; d3i <= d2i; end
    localparam integer MW = YW + 18;
    reg signed [MW-1:0] m1, m2, m3, m4;
    reg                 nv4;
    always @(posedge clk) begin m1 <= d3r * c; m2 <= d3i * s; m3 <= d3i * c; m4 <= d3r * s; nv4 <= nv3; end
    localparam integer SHV = 17 + 8 - VF;
    reg signed [MW:0] s1, s2;
    reg               nv5;
    always @(posedge clk) begin s1 <= m1 + m2; s2 <= m3 - m4; nv5 <= nv4; end
    function signed [VW-1:0] rsat(input signed [MW:0] a);
        reg signed [MW:0] t;
        begin
            t = (a + (1 <<< (SHV - 1))) >>> SHV;
            if (t > $signed((1 <<< (VW - 1)) - 1))  rsat = (1 <<< (VW - 1)) - 1;
            else if (t < -$signed(1 <<< (VW - 1)))  rsat = -(1 <<< (VW - 1));
            else                                    rsat = t[VW-1:0];
        end
    endfunction
    reg signed [VW-1:0] vr, vi;
    reg                 nv6;
    always @(posedge clk) begin vr <= rsat(s1); vi <= rsat(s2); nv6 <= nv5; end

    // ---- 組にして light 1 段目 ----
    reg                 ph, pv;
    reg signed [VW-1:0] er, ei, pr, pi, por, poi;
    always @(posedge clk) begin
        pv <= 1'b0;
        if (rst) ph <= 1'b0;
        else if (nv6) begin
            if (!ph) begin er <= vr; ei <= vi; end
            else begin pr <= er; pi <= ei; por <= vr; poi <= vi; pv <= 1'b1; end
            ph <= ~ph;
        end
    end
    // light: model/win64_model.py（M-0）の N 15・SH 17
    localparam [18*15-1:0] LIGHT_H = {-18'sd393, 18'sd0, 18'sd2436, 18'sd0, -18'sd9156, 18'sd0, 18'sd39878, 18'sd65542,
                                      18'sd39878, 18'sd0, -18'sd9156, 18'sd0, 18'sd2436, 18'sd0, -18'sd393};
    hb2s #(.N(15), .SH(17), .H(LIGHT_H), .W(VW), .C(2)) u_l1 (
        .clk(clk), .rst(rst), .in_v(pv), .e_re(pr), .e_im(pi), .o_re(por), .o_im(poi),
        .out_v(z_valid), .y_re(z_re), .y_im(z_im), .sat(sat), .ovr(ovr));
endmodule
