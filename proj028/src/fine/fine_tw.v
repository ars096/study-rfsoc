// SPDX-License-Identifier: BSD-3-Clause
//
// fine_tw — 細かい側のひねり係数 W_131072^(p·k1) を 2 つの小さな表の積で作る（proj028 F-2）。proj024 の g21_tw（cbf0674）を写して直したもの:
//   k1 = hi·128 + lo（hi = k1[12:7]、0..63）、A[p][hi] = round(2^16·W_N^(p·128·hi))、B[p][lo] = round(2^16·W_N^(p·lo))、w = cmul(A, B, SH 16)
// 表: src/fine/fine_tw_a.hex（64 行）・fine_tw_b.hex（128 行）、各 576 bit（レーン p が [36p +: 36] = {im, re}）。LAT 6。-DTW_HI_ERR は陽性対照

`timescale 1ns / 1ps

module fine_tw #(
    parameter A_FILE = "fine_tw_a.hex",
    parameter B_FILE = "fine_tw_b.hex"
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
