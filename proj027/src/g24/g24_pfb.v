// SPDX-License-Identifier: BSD-3-Clause
//
// g24_pfb — 2G-2 の PFB（proj025 手順 1c。proj024 の g21_pfb を写した）: g24_coef（係数の補間）＋ 入力の遅延線 ＋ g24_pfb_core（8192 ビート）
//
// wide_pfb は係数が「入力のビートの 2 クロック後」に届く前提（wide_coef_rom の LAT 2）。g24_coef の LAT は 5 なので、
// **係数は遅らせる前の s_m で引き、本体への入力（s_tdata・s_tvalid・s_m）を DLY = 5 − 2 = 3 クロック遅らせる**（README 1a）。
// 食い違えば本体の coef_mis が立つ（粘着）。仕様は model/g24_fixed.py の pfb_int（係数は coef_interp）と bit 単位で同じ。
// 出口は wide_pfb と同じ（y・y_v・y_m・y_first・y_fr・sat_cnt・coef_mis）。入口 → 出口のレイテンシは wide_pfb の 7 ＋ DLY 3 = 10。
//
// -DPFB_DLY_ERR: 遅延線を 2 にする（係数が 1 ビートずれる）。陽性対照（coef_mis が立ち、y が模型と違うはず）

`timescale 1ns / 1ps

module g24_pfb #(
    parameter LO_FILE = "g24_coef_lo.hex",
    parameter HI_FILE = "g24_coef_hi.hex"
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [255:0]      s_tdata,
    input  wire              s_tvalid,
    input  wire [12:0]       s_m,
    output wire [16*15-1:0]  y,
    output wire              y_v,
    output wire [12:0]       y_m,
    output wire              y_first,
    output wire [1:0]        y_fr,
    output wire [15:0]       sat_cnt,
    output wire              coef_mis
);
`ifdef PFB_DLY_ERR
    localparam integer DLY = 2;
`else
    localparam integer DLY = 3;
`endif

    wire [1151:0] coef;
    wire [12:0]   coef_m;
    wire          coef_v;
    g24_coef #(.LO_FILE(LO_FILE), .HI_FILE(HI_FILE)) u_coef (
        .clk(clk), .addr(s_m), .addr_v(s_tvalid), .coef(coef), .m_out(coef_m), .v_out(coef_v)
    );

    reg [255:0] dd [0:DLY-1];
    reg [12:0]  dm [0:DLY-1];
    reg         dv [0:DLY-1];
    integer i;
    always @(posedge clk) begin
        dd[0] <= s_tdata; dm[0] <= s_m; dv[0] <= s_tvalid & ~rst;
        for (i = 1; i < DLY; i = i + 1) begin dd[i] <= dd[i-1]; dm[i] <= dm[i-1]; dv[i] <= dv[i-1] & ~rst; end
    end

    g24_pfb_core #(.XW(14), .CW(18), .CF(16), .YW(15)) u_pfb (
        .clk(clk), .rst(rst),
        .s_tdata(dd[DLY-1]), .s_tvalid(dv[DLY-1]), .s_m(dm[DLY-1]),
        .coef(coef), .coef_m(coef_m),
        .y(y), .y_v(y_v), .y_m(y_m), .y_first(y_first), .y_fr(y_fr), .sat_cnt(sat_cnt), .coef_mis(coef_mis)
    );
endmodule
