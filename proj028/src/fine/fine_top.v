// SPDX-License-Identifier: BSD-3-Clause
//
// fine_top — fine_core（細かい側の全体）に AXI4-Lite の口をつけた包み（proj028 F-5）。ブロックデザインに module reference で置く
//   入口: ct_rd の AXI4-Stream（512 bit・tuser 22 bit・tlast）。出口: レコード（64 bit・tlast）→ s45_ring の s0_axis（tuser = 0）
//   全部が DSP のクロック（256 MHz）
//
// レジスタ（AXI4-Lite 256 B、リセット中は ready を出さない。ct_rd と同じ形）:
//   0x00 ID  0x04 CTRL: [0] SRST（1 の間 fine_core をリセットに保つ。粘着の FLAGS を消す。**ct_wr・ct_rd を止めてから**使う:
//        流れの途中で解くと、ch の途中の拍を ch の頭として読む）
//   0x08 SHIFT [3:0]（電力の前の右シフト。既定 SHIFT_DEFAULT）
//   0x10 FLAGS（fine_core の粘着の 9 bit: [0] 待ち行列の溢れ [1] IP の TLAST [2] IP の halt [3] tw の番地 [4] 係数の番地
//        [5] 読み出しを捨てた [6] 帳簿 [7] PFB の飽和 [8] 空のフレームの重なり）
//   0x14 N_REC（読み出しを始めたレコードの数）
//   0x20 GB_STAT・0x24 ADC_STAT: ギアボックスの見張り（proj024 の gb_gate の gb_stat・adc_stat をそのまま読む。core_cmn を載せないので、ここに置いた）
`timescale 1ns / 1ps

module fine_top #(
    parameter [31:0]  ID = 32'h0280_00F6,
    parameter integer SHIFT_DEFAULT = 7,
    parameter LO_FILE = "fine_coef_lo.hex",
    parameter HI_FILE = "fine_coef_hi.hex",
    parameter TA_FILE = "fine_tw_a.hex",
    parameter TB_FILE = "fine_tw_b.hex"
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:s_axis:m_axis, ASSOCIATED_RESET aresetn" *)
    input  wire          aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire          aresetn,
    input  wire [511:0]  s_axis_tdata,
    input  wire [21:0]   s_axis_tuser,
    input  wire          s_axis_tlast,
    input  wire          s_axis_tvalid,
    output wire          s_axis_tready,
    output wire [63:0]   m_axis_tdata,
    output wire          m_axis_tlast,
    output wire          m_axis_tuser,
    output wire          m_axis_tvalid,
    input  wire          m_axis_tready,
    input  wire [31:0]   gb_stat,
    input  wire [31:0]   adc_stat,
    input  wire [7:0]    s_axi_awaddr,
    input  wire          s_axi_awvalid,
    output wire          s_axi_awready,
    input  wire [31:0]   s_axi_wdata,
    input  wire          s_axi_wvalid,
    output wire          s_axi_wready,
    output reg           s_axi_bvalid,
    output wire [1:0]    s_axi_bresp,
    input  wire          s_axi_bready,
    input  wire [7:0]    s_axi_araddr,
    input  wire          s_axi_arvalid,
    output wire          s_axi_arready,
    output reg  [31:0]   s_axi_rdata,
    output reg           s_axi_rvalid,
    output wire [1:0]    s_axi_rresp,
    input  wire          s_axi_rready
);
    wire rst = !aresetn;

    // ---- レジスタ ----
    reg       srst;
    reg [3:0] shift;
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !rst;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    always @(posedge aclk) begin
        if (rst) begin
            s_axi_bvalid <= 1'b0; srst <= 1'b0; shift <= SHIFT_DEFAULT[3:0];
        end else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) begin
                s_axi_bvalid <= 1'b1;
                case (s_axi_awaddr[7:2])
                    6'h01: srst  <= s_axi_wdata[0];
                    6'h02: shift <= s_axi_wdata[3:0];
                    default: ;
                endcase
            end
        end
    end

    // fine_core のリセット: 外のリセットか SRST。1 段のレジスタで受ける（fine_core の中で広く配られる）
    reg core_rst = 1'b1;
    always @(posedge aclk) core_rst <= rst || srst;

    wire [8:0]  flags;
    wire [31:0] n_rec;
    fine_core #(.LO_FILE(LO_FILE), .HI_FILE(HI_FILE), .TA_FILE(TA_FILE), .TB_FILE(TB_FILE)) u_core (
        .clk(aclk), .rst(core_rst),
        .s_axis_tdata(s_axis_tdata), .s_axis_tuser(s_axis_tuser), .s_axis_tlast(s_axis_tlast),
        .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(s_axis_tready),
        .shift(shift),
        .m_axis_tdata(m_axis_tdata), .m_axis_tlast(m_axis_tlast), .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready),
        .flags(flags), .n_rec(n_rec),
        .dbg_ip_tdata(), .dbg_ip_k1(), .dbg_ip_v());
    assign m_axis_tuser = 1'b0;

    assign s_axi_arready = !s_axi_rvalid && !rst;
    assign s_axi_rresp   = 2'b00;
    always @(posedge aclk) begin
        if (rst) s_axi_rvalid <= 1'b0;
        else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1'b1;
                case (s_axi_araddr[7:2])
                    6'h00: s_axi_rdata <= ID;
                    6'h01: s_axi_rdata <= {31'd0, srst};
                    6'h02: s_axi_rdata <= {28'd0, shift};
                    6'h04: s_axi_rdata <= {23'd0, flags};
                    6'h05: s_axi_rdata <= n_rec;
                    6'h08: s_axi_rdata <= gb_stat;
                    6'h09: s_axi_rdata <= adc_stat;
                    default: s_axi_rdata <= 32'd0;
                endcase
            end
        end
    end
endmodule
