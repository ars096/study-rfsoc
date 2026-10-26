// SPDX-License-Identifier: BSD-3-Clause
// proj028 F-5 — ギアボックスの出口（AXI4-Stream、gb_dn_0/M_AXIS）を coarse_stage の素の口（s_valid・s_data）に渡す受け口。
//   ブロックデザインでは IP のインタフェースの中の 1 本（m_axis_tvalid など）をネットでつなげないので、ここでインタフェースとして受ける。
//   tready は常に 1（上流に backpressure をかけてはいけない: RFDC がサンプルを落とす。proj024 のギアボックスの注釈）。中身は線だけ
`default_nettype none
module gb_tap #(
    parameter integer DW = 256
) (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis" *)
    input  wire          aclk,
    input  wire [DW-1:0] s_axis_tdata,
    input  wire          s_axis_tvalid,
    output wire          s_axis_tready,
    output wire [DW-1:0] m_data,
    output wire          m_valid
);
    assign s_axis_tready = 1'b1;
    assign m_data  = s_axis_tdata;
    assign m_valid = s_axis_tvalid;
endmodule
`default_nettype wire
