// SPDX-License-Identifier: BSD-3-Clause
// proj028 S-2 — clk_mon の試験台。pl_clk0 100 MHz・参照 200 MHz・UI 300 MHz（または止めた UI）で数えを照らす
//   -DNO_UI: UI クロックを止める（陽性対照: UI_CNT が 0、それでも読みは返る）
`timescale 1ns/1ps
`default_nettype none
module tb_clk_mon;
    localparam [31:0] WIN = 32'd20000;              // 200 µs の窓（sim を短く）
    reg clk = 0, ref_clk = 0, ui_clk = 0;
    always #5.000 clk = ~clk;
    always #2.500 ref_clk = ~ref_clk;
`ifndef NO_UI
    always #1.6667 ui_clk = ~ui_clk;
`endif
    reg aresetn = 0, calib = 0, ui_rst = 1;
    reg [7:0] araddr = 0; reg arvalid = 0;
    wire arready, rvalid, bvalid, awready, wready; wire [31:0] rdata; wire [1:0] bresp, rresp;
    clk_mon #(.WIN(WIN)) dut (.clk(clk), .aresetn(aresetn), .ref_clk(ref_clk), .ui_clk(ui_clk), .calib(calib), .ui_rst(ui_rst),
        .s_axi_awaddr(8'd0), .s_axi_awvalid(1'b0), .s_axi_awready(awready), .s_axi_wdata(32'd0), .s_axi_wvalid(1'b0), .s_axi_wready(wready),
        .s_axi_bvalid(bvalid), .s_axi_bresp(bresp), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rvalid(rvalid),
        .s_axi_rresp(rresp), .s_axi_rready(1'b1));
    reg [31:0] v;
    task rd(input [7:0] a); begin
        @(negedge clk); araddr = a; arvalid = 1;
        @(posedge clk); while (arready !== 1'b1) @(posedge clk);
        @(negedge clk); arvalid = 0;
        while (rvalid !== 1'b1) @(negedge clk);
        v = rdata; @(negedge clk);
    end endtask
    integer fails = 0;
    initial begin
        repeat (10) @(posedge clk); aresetn = 1;
        rd(8'h00); if (v !== 32'h0280_00C1) begin $display("  ×  ID %h", v); fails = fails + 1; end
        rd(8'h04); $display("STATUS（較正の前）%b", v[2:0]); if (v[1:0] !== 2'b10) fails = fails + 1;
        #300; ui_rst = 0; calib = 1;
        repeat (2 * WIN + 10) @(posedge clk);
        rd(8'h04); $display("STATUS（較正の後）%b", v[2:0]); if (v[2:0] !== 3'b101) fails = fails + 1;
        rd(8'h08); $display("REF_CNT %0d（期待 %0d = 200 MHz / 16 × 窓）", v, WIN * 2 / 16);
        if (v < WIN * 2 / 16 - 2 || v > WIN * 2 / 16 + 2) fails = fails + 1;
        rd(8'h0C); $display("UI_CNT %0d", v);
`ifdef NO_UI
        if (v !== 0) fails = fails + 1;
        if (fails == 0) $display("結果: 陽性対照（NO_UI）: UI クロックが無くても読みが返り、UI_CNT 0"); else $display("結果: 不合格");
`else
        if (v < WIN * 3 / 16 - 2 || v > WIN * 3 / 16 + 2) fails = fails + 1;
        if (fails == 0) $display("結果: 全部通過"); else $display("結果: 不合格");
`endif
        $finish;
    end
endmodule
`default_nettype wire
