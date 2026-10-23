// SPDX-License-Identifier: BSD-3-Clause
//
// g24_tw — 2G-2 のひねり係数 W_131072^(p·k1) を 2 つの小さな表の積で作る（proj025 手順 1b。proj024 の g21_tw を写し、長さを 2G-2 に）。wide_tw_rom と同じ口
//
// 仕様（model/g24_fixed.py の tw_prod と bit 単位で同じ）:
//   k1 = hi·128 + lo（hi = k1[12:7]（0..63）、lo = k1[6:0]）、A[p][hi] = round(2^16·W_N^(p·128·hi))、B[p][lo] = round(2^16·W_N^(p·lo))、
//   w = cmul(A, B, SH 16) = ((A·B の各成分) + 2^15) >>> 16（cmul.v そのもの）。18 bit・2^16 = 1.0。
//   レーン 0 は常に 1.0（65536, 0）なので掛けずに同じ遅れで通す（DSP は 15 レーン × 4 = 60）。
// 表: src/g24/g24_tw_a.hex（64 行）・g24_tw_b.hex（128 行、各 576 bit、レーン p が [36p +: 36] = {im, re}。tools/gen_g24_tables.py の生成物）。
// 出力の並びは wide_tw_rom と同じ（tw のレーン p が [36p +: 36] = {im[17:0], re[17:0]}）。k1_out はその番地（wide_chain の tw_mis の見張り用）。
//
// 段: 番地のレジスタ（ROM の中）/ ROM の出力レジスタ / cmul 4 段 → LAT = 6（wide_tw_rom の数えで。wide_tw_rom は 2）
// 2G-2 はコアが 2 個。**IP の出口の k1 で引く ROM なので、コアごとに 1 個ずつ置く**（LESSONS、proj023 4b）。
//
// -DTW_HI_ERR: hi の番地を 1 ずらす（k1 の上位を +1）。陽性対照（落ちるべき）

`timescale 1ns / 1ps

module g24_tw #(
    parameter A_FILE = "g24_tw_a.hex",
    parameter B_FILE = "g24_tw_b.hex"
)(
    input  wire         clk,
    input  wire [12:0]  addr,           // k1（レーン FFT の出口の XK_INDEX）
    output wire [575:0] tw,
    output reg  [12:0]  k1_out
);
    localparam integer LAT = 6;

    (* rom_style = "block" *) reg [575:0] rom_a [0:63];
    (* rom_style = "block" *) reg [575:0] rom_b [0:127];
    initial begin
        $readmemh(A_FILE, rom_a);
        $readmemh(B_FILE, rom_b);
    end

    // ---- ROM: 番地のレジスタ → 出力のレジスタ（2 段）----
    reg [5:0]   ha;
    reg [6:0]   la;
    reg [575:0] da, db;
    reg [12:0]  k [0:LAT-1];
    integer i;
    always @(posedge clk) begin
`ifdef TW_HI_ERR
        ha <= addr[12:7] + 6'd1;
`else
        ha <= addr[12:7];
`endif
        la <= addr[6:0];
        da <= rom_a[ha];
        db <= rom_b[la];
        k[0] <= addr;
        for (i = 1; i < LAT; i = i + 1) k[i] <= k[i-1];
        k1_out <= k[LAT-2];
    end

    // ---- レーン 1..15: cmul（4 段）/ レーン 0: 1.0 を 4 段遅らせる ----
    genvar p;
    generate
        for (p = 1; p < 16; p = p + 1) begin : g_mul
            wire signed [17:0] yr, yi;
            cmul #(.AW(18), .OW(18), .SH(16)) u_mul (
                .clk(clk),
                .a_re(da[36*p +: 18]), .a_im(da[36*p + 18 +: 18]),
                .w_re(db[36*p +: 18]), .w_im(db[36*p + 18 +: 18]),
                .y_re(yr), .y_im(yi)
            );
            assign tw[36*p +: 36] = {yi, yr};
        end
    endgenerate
    assign tw[0 +: 36] = {18'sd0, 18'sd65536};
endmodule
