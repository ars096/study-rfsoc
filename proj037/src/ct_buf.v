// SPDX-License-Identifier: BSD-3-Clause
// proj028 S-1 — corner turn の書き込みの溜め（32 ch × 2 面 × 4 KiB = 256 KiB）。資源を数えるための形
//   書き: 256 MHz の側、256 bit（32 B）/ 拍。読み: DDR の AXI の側（300 MHz）、256 bit / 拍
`default_nettype none
module ct_buf #(parameter AW = 13, parameter DW = 256) (
    input  wire          wclk,
    input  wire          we,
    input  wire [AW-1:0] waddr,
    input  wire [DW-1:0] wdata,
    input  wire          rclk,
    input  wire          re,
    input  wire [AW-1:0] raddr,
    output reg  [DW-1:0] rdata
);
    (* ram_style = "block" *) reg [DW-1:0] mem [0:(1<<AW)-1];
    reg [DW-1:0] rq;
    always @(posedge wclk) if (we) mem[waddr] <= wdata;
    always @(posedge rclk) begin
        if (re) rq <= mem[raddr];
        rdata <= rq;
    end
endmodule
`default_nettype wire
