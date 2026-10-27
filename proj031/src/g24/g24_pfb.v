// SPDX-License-Identifier: BSD-3-Clause
//
// g24_pfb — 2G-4 の PFB（proj027 手順 1c。proj025 の g22_pfb を写した）: 入力の遅延線 ＋ g24_pfb_core（4096 ビート）
//
// **proj031 P-2: 係数は外の共有の g24_cu（URAM、4 コアで 1 組）から**。中の g24_coef（線形補間、DSP 64）を外した。
//   coef_addr（= s_m を 1 段受けたもの）を外へ出す（使うのは s45_core_0 のものだけ）。g24_cu の LAT 3 ＋ ここの受けの 1 段（coef_q）で、
//   s_m → 係数が 1 + 3 + 1 = 5 クロック = g24_coef の LAT と同じ。遅延線 DLY 3 は今のまま。値は proj030 と bit 単位で同じ（sim-cu）。
//   coef_ok_in（g24_cu の OK）は係数と同じ段で受け、g24_pfb_core が「OK が 0 のビート」も coef_mis に数える。coef_ok は g24_spec の起動の見張りにも出す
// 以下は proj030 までの注:
// wide_pfb は係数が「入力のビートの 2 クロック後」に届く前提（wide_coef_rom の LAT 2）。g24_coef の LAT は 5 なので、
// **係数は遅らせる前の s_m で引き、本体への入力（s_tdata・s_tvalid・s_m）を DLY = 5 − 2 = 3 クロック遅らせる**（README 1a）。
// 食い違えば本体の coef_mis が立つ（粘着）。仕様は model/g24_fixed.py の pfb_int（係数は coef_interp）と bit 単位で同じ。
// 出口は wide_pfb と同じ（y・y_v・y_m・y_first・y_fr・sat_cnt・coef_mis）。入口 → 出口のレイテンシは wide_pfb の 7 ＋ DLY 3 = 10。
//
// -DPFB_DLY_ERR: 遅延線を 2 にする（係数が 1 ビートずれる）。陽性対照（coef_mis が立ち、y が模型と違うはず）

`timescale 1ns / 1ps

module g24_pfb (
    input  wire              clk,
    input  wire              rst,
    input  wire [255:0]      s_tdata,
    input  wire              s_tvalid,
    input  wire [11:0]       s_m,
    output reg  [11:0]       coef_addr,     // g24_cu の番地（s45_core_0 のものだけ使う）
    output reg               coef_addr_v,
    input  wire [1151:0]     coef_in,       // g24_cu の出口（coef_addr の 3 クロック後）
    input  wire [11:0]       coef_m_in,
    input  wire              coef_ok_in,
    output wire              coef_ok,       // 受けた OK（g24_spec の起動の見張りへ）
    output wire [16*15-1:0]  y,
    output wire              y_v,
    output wire [11:0]       y_m,
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

    // 番地を出す 1 段と、共有の出口を受ける 1 段（Wide の coef_q。DSP の A レジスタに吸わせない）
    (* dont_touch = "true" *) reg [1151:0] coef_q;
    (* dont_touch = "true" *) reg [11:0]   coef_mq;
    reg           coef_okq;
    always @(posedge clk) begin
        coef_addr <= s_m; coef_addr_v <= s_tvalid;
        coef_q <= coef_in; coef_mq <= coef_m_in; coef_okq <= coef_ok_in & ~rst;
    end
    assign coef_ok = coef_okq;

    reg [255:0] dd [0:DLY-1];
    reg [11:0]  dm [0:DLY-1];
    reg         dv [0:DLY-1];
    integer i;
    always @(posedge clk) begin
        dd[0] <= s_tdata; dm[0] <= s_m; dv[0] <= s_tvalid & ~rst;
        for (i = 1; i < DLY; i = i + 1) begin dd[i] <= dd[i-1]; dm[i] <= dm[i-1]; dv[i] <= dv[i-1] & ~rst; end
    end

    g24_pfb_core #(.XW(14), .CW(18), .CF(16), .YW(15)) u_pfb (
        .clk(clk), .rst(rst),
        .s_tdata(dd[DLY-1]), .s_tvalid(dv[DLY-1]), .s_m(dm[DLY-1]),
        .coef(coef_q), .coef_m(coef_mq), .coef_ok(coef_okq),
        .y(y), .y_v(y_v), .y_m(y_m), .y_first(y_first), .y_fr(y_fr), .sat_cnt(sat_cnt), .coef_mis(coef_mis)
    );
endmodule
