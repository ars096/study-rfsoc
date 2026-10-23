// SPDX-License-Identifier: BSD-3-Clause
//
// fine_coef — 細かい PFB の係数を線形補間で作る（proj028 F-1）。proj024 の g21_coef（cbf0674）を写して直したもの
//
// 仕様（model/fine_fixed.py の coef_beat と bit 単位で同じ）:
//   N = 131072、L = 4N、1 フレーム = 8192 ビート（m）× 16 レーン（p）、タップ t（0..3）の番地 i = t·N + 16m + p。
//   左右で折り返した片側 4096 区間の表: 節 V[s]（23 bit）・傾き S[s]（13 bit。g21 の 12 bit から 1 bit 増）、c = (V·64 + S·f + 2^10) >>> 11（G 5）。
//   a = m >> 2（0..2047）、b = 2047 − a、q = m & 3 として:
//     t 0: 前半の表[a]・f = 16q + p        t 1: 後半の表[a]・f = 16q + p
//     t 2: 後半の表[b]・f = 63 − 16q − p   t 3: 前半の表[b]・f = 63 − 16q − p
// 出力: coef = 16 レーン × 4 タップ × 18 bit（レーン p が [72p +: 72]、タップ t が [18t +: 18]）。LAT 5（addr → coef）
// -DCOEF_FRAC_ERR: t 2・3 の端数を折り返さない（陽性対照）

`timescale 1ns / 1ps

module fine_coef #(
    parameter LO_FILE = "fine_coef_lo.hex",
    parameter HI_FILE = "fine_coef_hi.hex"
)(
    input  wire          clk,
    input  wire [12:0]   addr,
    input  wire          addr_v,
    output reg  [1151:0] coef,
    output reg  [12:0]   m_out,
    output reg           v_out
);
    localparam integer VW = 23, SW = 13, G = 5;

    (* rom_style = "block" *) reg [VW+SW-1:0] rom_lo [0:2047];
    (* rom_style = "block" *) reg [VW+SW-1:0] rom_hi [0:2047];
    initial begin
        $readmemh(LO_FILE, rom_lo);
        $readmemh(HI_FILE, rom_hi);
    end

    reg [10:0] a0, b0;
    reg [1:0]  q0;
    reg [12:0] m0;
    reg        v0;
    always @(posedge clk) begin
        a0 <= addr[12:2];
        b0 <= ~addr[12:2];              // 2047 − a
        q0 <= addr[1:0];
        m0 <= addr; v0 <= addr_v;
    end

    reg [VW+SW-1:0] la1, lb1, ha1, hb1, la2, lb2, ha2, hb2;
    reg [1:0]  q1, q2;
    reg [12:0] m1, m2;
    reg        v1, v2;
    always @(posedge clk) begin
        la1 <= rom_lo[a0]; lb1 <= rom_lo[b0];
        ha1 <= rom_hi[a0]; hb1 <= rom_hi[b0];
        la2 <= la1; lb2 <= lb1; ha2 <= ha1; hb2 <= hb1;
        q1 <= q0; m1 <= m0; v1 <= v0;
        q2 <= q1; m2 <= m1; v2 <= v1;
    end

    wire [VW+SW-1:0] w2 [0:3];
    assign w2[0] = la2;
    assign w2[1] = ha2;
    assign w2[2] = hb2;
    assign w2[3] = lb2;

    reg signed [SW+6:0]   sf3 [0:63];
    reg signed [VW+6:0]   vr3 [0:3];
    reg [12:0] m3; reg v3;
    integer p, t;
    reg [5:0] f;
    always @(posedge clk) begin
        for (t = 0; t < 4; t = t + 1)
            vr3[t] <= ($signed(w2[t][VW-1:0]) <<< 6) + (1 <<< (G + 5));
        for (p = 0; p < 16; p = p + 1)
            for (t = 0; t < 4; t = t + 1) begin
`ifdef COEF_FRAC_ERR
                f = {q2, 4'd0} + p;
`else
                f = (t < 2) ? ({q2, 4'd0} + p) : (6'd63 - {q2, 4'd0} - p);
`endif
                sf3[4*p + t] <= $signed(w2[t][VW +: SW]) * $signed({1'b0, f});
            end
        m3 <= m2; v3 <= v2;
    end

    reg signed [VW+7:0] s4;
    always @(posedge clk) begin
        for (p = 0; p < 16; p = p + 1)
            for (t = 0; t < 4; t = t + 1) begin
                s4 = vr3[t] + sf3[4*p + t];
                coef[72*p + 18*t +: 18] <= s4[G + 6 +: 18];
            end
        m_out <= m3; v_out <= v3;
    end
endmodule
