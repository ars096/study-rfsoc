// SPDX-License-Identifier: BSD-3-Clause
//
// wide_tw_rom — SAM45-Wide のひねり係数 ROM（proj023 手順 2c）。**4 ADC の wide_chain で 1 つを共有する**（README D-6・D-7）
//
// 番地 k1（レーン FFT の出口の XK_INDEX 0..2047）→ 576 bit = 16 レーン × 36 bit（レーン p が [36p +: 36]、{im[17:0], re[17:0]}）。
// 値は W_32768^(p·k1)、18 bit・2^16 = 1.0。中身は src/sam45wide/wide_tw.hex（tools/gen_wide_tw.py の生成物、sim/check_wide.py の TWR・TWI と同じ式）。
// BRAM に置く（2048 × 576 bit → RAMB36 × 32 の見込み。レーン 0 は常に 1 だが、揃えのために持つ）。
//
// 出力は番地から LAT = 2 クロック後（tw_rom と同じ）。k1_out はその番地（wide_chain が自分の k1 と比べて共有の食い違いを見張る）。
// 番地は 4 ADC で同じ（フレームの頭が T の同じ位相にあり、レーン FFT の遅れも同じ。D-2）ので、どれか 1 つのコア（ADC_A）の k1 で引く。

`timescale 1ns / 1ps

module wide_tw_rom #(
    parameter TW_FILE = "wide_tw.hex"
)(
    input  wire         clk,
    input  wire [10:0]  addr,
    output reg  [575:0] tw,
    output reg  [10:0]  k1_out
);
    (* rom_style = "block" *) reg [575:0] rom [0:2047];
    initial $readmemh(TW_FILE, rom);

    reg [10:0]  a1;
    reg [575:0] d1;
    always @(posedge clk) begin
        a1     <= addr;
        d1     <= rom[addr];
        tw     <= d1;
        k1_out <= a1;
    end
endmodule
