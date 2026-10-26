// SPDX-License-Identifier: BSD-3-Clause
//
// g24_coef — 2G-4 の PFB の係数を線形補間で作る（proj027 手順 1a。proj025 の g22_coef を写し、長さ・幅・G を 2G-4 に）。wide_coef_rom と同じ口
//
// 仕様（model/g24_fixed.py の coef_beat と bit 単位で同じ）:
//   N = 65536、L = 4N、1 フレーム = 4096 ビート（m）× 16 レーン（p）、タップ t（0..3）の番地 i = t·N + 16m + p。
//   左右で折り返した片側 2048 区間の表: 節 V[s]（**22 bit**）・傾き S[s]（13 bit）、c = (V·64 + S·f + 2^9) >>> 10（**G 4**。G 5 は S 14 で 37 bit になり RAMB36 の幅を越える、proj027 M-a）。
//   a = m >> 2（0..1023）、b = 1023 − a、q = m & 3 として:
//     t 0: 前半の表[a]・f = 16q + p        t 1: 後半の表[a]・f = 16q + p
//     t 2: 後半の表[b]・f = 63 − 16q − p   t 3: 前半の表[b]・f = 63 − 16q − p
//   → 前半・後半の表を 2 ポートの ROM（1024 × 35 bit）にし、どちらも番地 a と b で引く（RAMB36 2 個の見込み、M-a）。
//
// 出力: coef = 16 レーン × 4 タップ × 18 bit（レーン p が [72p +: 72]、タップ t が [18t +: 18]。wide_coef_rom と同じ並び）。
// m_out・v_out はその係数の番地と有効（wide_pfb が自分の m と比べて見張る）。レイテンシは LAT（下）。
// wide_coef_rom の LAT は 2 なので、使う側（g24_pfb）が入力を LAT − 2 だけ遅らせる。
//
// 段: 0 番地のレジスタ（a・b・q）/ 1 ROM の読み / 2 ROM の出力レジスタ / 3 S·f（13 × 6 bit。合成では DSP に入る: proj027 F-2 の OOC で DSP 64・LUT 16）と V·64 ＋ 丸め / 4 和 → >>> 10
//
// -DCOEF_FRAC_ERR: t 2・3 の端数を折り返さない（f = 16q + p のまま）。陽性対照（落ちるべき）

`timescale 1ns / 1ps

module g24_coef #(
    parameter LO_FILE = "g24_coef_lo.hex",
    parameter HI_FILE = "g24_coef_hi.hex"
)(
    input  wire          clk,
    input  wire [11:0]   addr,          // m（フレームの中のビート 0..4095）
    input  wire          addr_v,
    output reg  [1151:0] coef,
    output reg  [11:0]   m_out,
    output reg           v_out
);
    localparam integer LAT = 5;         // addr → coef（tb が数えて確かめる）
    localparam integer VW = 22, SW = 13, G = 4;

    (* rom_style = "block" *) reg [VW+SW-1:0] rom_lo [0:1023];
    (* rom_style = "block" *) reg [VW+SW-1:0] rom_hi [0:1023];
    initial begin
        $readmemh(LO_FILE, rom_lo);
        $readmemh(HI_FILE, rom_hi);
    end

    // ---- 0: 番地 ----
    reg [9:0]  a0, b0;
    reg [1:0]  q0;
    reg [11:0] m0;
    reg        v0;
    always @(posedge clk) begin
        a0 <= addr[11:2];
        b0 <= ~addr[11:2];              // 1023 − a
        q0 <= addr[1:0];
        m0 <= addr; v0 <= addr_v;
    end

    // ---- 1・2: ROM（2 ポート × 2）----
    reg [VW+SW-1:0] la1, lb1, ha1, hb1, la2, lb2, ha2, hb2;
    reg [1:0]  q1, q2;
    reg [11:0] m1, m2;
    reg        v1, v2;
    always @(posedge clk) begin
        la1 <= rom_lo[a0]; lb1 <= rom_lo[b0];
        ha1 <= rom_hi[a0]; hb1 <= rom_hi[b0];
        la2 <= la1; lb2 <= lb1; ha2 <= ha1; hb2 <= hb1;
        q1 <= q0; m1 <= m0; v1 <= v0;
        q2 <= q1; m2 <= m1; v2 <= v1;
    end

    // タップ t の {S, V}: t 0 = 前半[a]、t 1 = 後半[a]、t 2 = 後半[b]、t 3 = 前半[b]
    wire [VW+SW-1:0] w2 [0:3];
    assign w2[0] = la2;
    assign w2[1] = ha2;
    assign w2[2] = hb2;
    assign w2[3] = lb2;

    // ---- 3: S·f と V·64 ＋ 丸め ----
    reg signed [SW+6:0]   sf3 [0:63];   // [4p + t]、S（13 bit）× f（0..63、符号なし 6 bit）
    reg signed [VW+6:0]   vr3 [0:3];    // V·64 + 2^(G+5)（レーンに依らない）
    reg [11:0] m3; reg v3;
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

    // ---- 4: 和 → >>> (G + 6) で 18 bit ----
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
