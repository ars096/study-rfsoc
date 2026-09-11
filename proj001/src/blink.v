// SPDX-License-Identifier: BSD-3-Clause
`timescale 1ns / 1ps
//
// proj001 — PS を使わない最小構成の LED 点滅
//
// RFSoC4x2 には Si5395 が生成する自走 100 MHz（SYS_CLK_100M, LVDS）が PL に直結して
// いるため、Zynq MPSoC IP を一切置かずに動作する。PS の pl_clk0 を使うと PS が
// 構成されるまでクロックが出ず、JTAG 書き込み後も LED が動かないため、配線ミスと
// 区別できない状態になる。それを避けるのがこの構成の目的。
//
module blink (
    input  wire       sys_clk_p,
    input  wire       sys_clk_n,
    output wire [3:0] led
);

    // 自走 100 MHz を差動で受ける
    wire clk;
    IBUFDS u_ibufds (
        .I (sys_clk_p),
        .IB(sys_clk_n),
        .O (clk)
    );

    // 2^26 / 100e6 = 0.671 s ごとに cnt[26] が反転（周期 1.34 s ≒ 0.75 Hz）
    reg [26:0] cnt = 27'd0;
    always @(posedge clk)
        cnt <= cnt + 1'b1;

    // 隣どうしで倍速になるので、分周が効いていることが目視できる
    assign led = cnt[26:23];

endmodule
