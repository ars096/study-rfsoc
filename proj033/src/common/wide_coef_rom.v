// SPDX-License-Identifier: BSD-3-Clause
//
// wide_coef_rom — SAM45-Wide の PFB の係数 ROM（proj023 手順 2b）。**4 ADC の wide_pfb で 1 つを共有する**（README D-6・D-7）
//
// 番地 m（フレームの中のビート 0..2047）→ 1152 bit = 16 レーン × 4 タップ × 18 bit（レーン p が [72p +: 72]、タップ t が [18t +: 18]）。
// 中身は src/sam45wide/wide_coef.hex（tools/gen_wide_coef.py の生成物、sim/check_wide.py の coef_words() と同じ）。
// **BRAM に置く**（URAM は初期値を持てない）。2048 × 1152 bit = RAMB36（512 × 72）× 64 の見込み。
//
// 出力は番地から LAT = 2 クロック後（番地のレジスタ ＋ 出力のレジスタ。BRAM の DOA_REG）。
// m_out はその係数の番地（wide_pfb が自分の番地と比べて、共有の食い違いを見張る）。
// 番地は time_core の T から作る共通の数え（全部の ADC のフレームの頭が T の同じ位相にある。D-2）。

`timescale 1ns / 1ps

module wide_coef_rom #(
    parameter COEF_FILE = "wide_coef.hex"
)(
    input  wire          clk,
    input  wire [10:0]   addr,
    input  wire          addr_v,
    output reg  [1151:0] coef,
    output reg  [10:0]   m_out,
    output reg           v_out
);
    (* rom_style = "block" *) reg [1151:0] rom [0:2047];
    initial $readmemh(COEF_FILE, rom);

    reg [10:0] a1;
    reg        v1;
    reg [1151:0] d1;
    always @(posedge clk) begin
        a1    <= addr;
        v1    <= addr_v;
        d1    <= rom[addr];
        coef  <= d1;
        m_out <= a1;
        v_out <= v1;
    end
endmodule
