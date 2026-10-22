// SPDX-License-Identifier: BSD-3-Clause
//
// axis_sel4 — 4 本の ADC の流れ（ギアボックスの出口）から 1 本を選んで、全帯域の分光（spec_core_0）へ（proj015）
//
// sel は win_core_0 の FULL_SEL（静的。**変えたら spec_core_0 を SRST で起動し直す**。途中で変えると 1 ビートで流れが入れ替わる）。
// 出口は 1 段のレジスタ（tready は見ない。spec_core は backpressure をかけない。入口の tready は 1）。
// spec_core の見張りの入口（gb_stat・adc_stat）も同じ sel で選んで渡す（spec_core_0 が読むのは、いまつないでいる ch の gb_gate）
`timescale 1ns / 1ps
module axis_sel4 #(
    parameter integer DW = 256
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s0_axis:s1_axis:s2_axis:s3_axis:m_axis, ASSOCIATED_RESET aresetn" *)
    input  wire          aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire          aresetn,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s0_axis TDATA" *)  input  wire [DW-1:0] s0_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s0_axis TVALID" *) input  wire          s0_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s0_axis TREADY" *) output wire          s0_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s1_axis TDATA" *)  input  wire [DW-1:0] s1_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s1_axis TVALID" *) input  wire          s1_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s1_axis TREADY" *) output wire          s1_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s2_axis TDATA" *)  input  wire [DW-1:0] s2_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s2_axis TVALID" *) input  wire          s2_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s2_axis TREADY" *) output wire          s2_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s3_axis TDATA" *)  input  wire [DW-1:0] s3_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s3_axis TVALID" *) input  wire          s3_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 s3_axis TREADY" *) output wire          s3_axis_tready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TDATA" *)   output reg  [DW-1:0] m_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TVALID" *)  output reg           m_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 m_axis TREADY" *)  input  wire          m_axis_tready,
    input  wire [1:0]    sel,
    input  wire [31:0]   gb_stat0, gb_stat1, gb_stat2, gb_stat3,
    input  wire [31:0]   adc_stat0, adc_stat1, adc_stat2, adc_stat3,
    output reg  [31:0]   gb_stat_o,
    output reg  [31:0]   adc_stat_o
);
    assign s0_axis_tready = 1'b1;
    assign s1_axis_tready = 1'b1;
    assign s2_axis_tready = 1'b1;
    assign s3_axis_tready = 1'b1;
    // proj017: 選択の bit を複製させる（proj016 の `-1` の最悪経路: sr[1] → 256 bit の出口、ファンアウト 303・配線 94 %）。
    //   段は足さない（全帯域のコアの入口の遅れ = M を変えない）
    (* max_fanout = 32 *) reg [1:0] sr;
    always @(posedge aclk) begin
        sr <= sel;
        if (!aresetn) begin
            m_axis_tvalid <= 1'b0;
        end else begin
            case (sr)
                2'd0: begin m_axis_tdata <= s0_axis_tdata; m_axis_tvalid <= s0_axis_tvalid; end
                2'd1: begin m_axis_tdata <= s1_axis_tdata; m_axis_tvalid <= s1_axis_tvalid; end
                2'd2: begin m_axis_tdata <= s2_axis_tdata; m_axis_tvalid <= s2_axis_tvalid; end
                default: begin m_axis_tdata <= s3_axis_tdata; m_axis_tvalid <= s3_axis_tvalid; end
            endcase
        end
        case (sr)
            2'd0: begin gb_stat_o <= gb_stat0; adc_stat_o <= adc_stat0; end
            2'd1: begin gb_stat_o <= gb_stat1; adc_stat_o <= adc_stat1; end
            2'd2: begin gb_stat_o <= gb_stat2; adc_stat_o <= adc_stat2; end
            default: begin gb_stat_o <= gb_stat3; adc_stat_o <= adc_stat3; end
        endcase
    end
endmodule
