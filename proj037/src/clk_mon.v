// SPDX-License-Identifier: BSD-3-Clause
// proj028 S-2 — MIG のクロックに依らない見張り（pl_clk0 の側の AXI4-Lite）。PS は ddr_tg に触る前にここを読む
//   2026-10-23 の実機: ddr_tg（UI クロックの側）を較正の前に読んで応答が返らず、PS ごと止まった。
//   ここは pl_clk0 だけで動くので、参照クロックや UI クロックが無くても読める
//
// 見るもの: 参照クロック（200 MHz、BUFG の出口）と UI クロック（≒ 300 MHz）の速さ、MIG の較正（calib）、UI のリセット（ui_rst）
//   各クロックの側で 4 bit の数えを回し、その最上位（f/16）を pl_clk0 へ 2 段の同期器（ASYNC_REG）で受けて、上がりの数を数える。
//   窓は pl_clk0 の WIN 拍（100 MHz で 1 s）。f/16 は 12.5・18.75 MHz で、pl_clk0 の半分（50 MHz）より遅い
// レジスタ: 0x00 ID  0x04 STATUS: [0] calib [1] ui_rst（どちらも同期器の後）[2] 窓を 1 回以上数えた
//           0x08 REF_CNT（直前の窓の上がりの数。×16 / 窓の秒 = Hz）  0x0C UI_CNT  0x10 WIN（窓の拍数）
`default_nettype none
module clk_mon #(
    parameter [31:0] ID  = 32'h0280_00C1,
    parameter [31:0] WIN = 32'd100_000_000
) (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET aresetn" *)
    input  wire        clk,             // pl_clk0
    input  wire        aresetn,
    input  wire        ref_clk,         // DDR4 の参照クロック（BUFG の出口）
    input  wire        ui_clk,          // MIG の UI クロック
    input  wire        calib,           // c0_init_calib_complete（UI クロックの側）
    input  wire        ui_rst,          // c0_ddr4_ui_clk_sync_rst（UI クロックの側、高で効く）
    input  wire [7:0]  s_axi_awaddr,
    input  wire        s_axi_awvalid,
    output wire        s_axi_awready,
    input  wire [31:0] s_axi_wdata,
    input  wire        s_axi_wvalid,
    output wire        s_axi_wready,
    output reg         s_axi_bvalid,
    output wire [1:0]  s_axi_bresp,
    input  wire        s_axi_bready,
    input  wire [7:0]  s_axi_araddr,
    input  wire        s_axi_arvalid,
    output wire        s_axi_arready,
    output reg  [31:0] s_axi_rdata,
    output reg         s_axi_rvalid,
    output wire [1:0]  s_axi_rresp,
    input  wire        s_axi_rready
);
    wire rst = ~aresetn;
    // ---- 各クロックの側の数え（リセットなし。電源投入の初期値 0）----
    reg [3:0] ref_div = 4'd0, ui_div = 4'd0;
    always @(posedge ref_clk) ref_div <= ref_div + 4'd1;
    always @(posedge ui_clk)  ui_div  <= ui_div + 4'd1;
    // ---- pl_clk0 への同期器 ----
    (* ASYNC_REG = "TRUE" *) reg [1:0] s_ref = 2'b00, s_ui = 2'b00, s_cal = 2'b00, s_rst = 2'b00;
    reg ref_q = 1'b0, ui_q = 1'b0;
    always @(posedge clk) begin
        s_ref <= {s_ref[0], ref_div[3]};
        s_ui  <= {s_ui[0], ui_div[3]};
        s_cal <= {s_cal[0], calib};
        s_rst <= {s_rst[0], ui_rst};
        ref_q <= s_ref[1];
        ui_q  <= s_ui[1];
    end
    // ---- 窓ごとの上がりの数 ----
    reg [31:0] win_c, ref_c, ui_c, ref_n, ui_n;
    reg        won;
    always @(posedge clk) begin
        if (rst) begin
            win_c <= 32'd0; ref_c <= 32'd0; ui_c <= 32'd0; ref_n <= 32'd0; ui_n <= 32'd0; won <= 1'b0;
        end else if (win_c == WIN - 1) begin
            win_c <= 32'd0; won <= 1'b1;
            ref_n <= ref_c + (s_ref[1] && !ref_q); ui_n <= ui_c + (s_ui[1] && !ui_q);
            ref_c <= 32'd0; ui_c <= 32'd0;
        end else begin
            win_c <= win_c + 32'd1;
            if (s_ref[1] && !ref_q) ref_c <= ref_c + 32'd1;
            if (s_ui[1] && !ui_q) ui_c <= ui_c + 32'd1;
        end
    end
    // ---- AXI4-Lite（書き込みは受けて捨てる。リセット中は ready を出さない）----
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !rst;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_rresp   = 2'b00;
    assign s_axi_arready = !s_axi_rvalid && !rst;
    always @(posedge clk) begin
        if (rst) begin s_axi_bvalid <= 1'b0; s_axi_rvalid <= 1'b0; end
        else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) s_axi_bvalid <= 1'b1;
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1'b1;
                case (s_axi_araddr[7:2])
                    6'h00: s_axi_rdata <= ID;
                    6'h01: s_axi_rdata <= {29'd0, won, s_rst[1], s_cal[1]};
                    6'h02: s_axi_rdata <= ref_n;
                    6'h03: s_axi_rdata <= ui_n;
                    6'h04: s_axi_rdata <= WIN;
                    default: s_axi_rdata <= 32'hDEAD_BEEF;
                endcase
            end
        end
    end
endmodule
`default_nettype wire
