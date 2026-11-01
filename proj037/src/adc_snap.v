// SPDX-License-Identifier: BSD-3-Clause
// proj028 F-8 — 荒い段の入口（gb_tap の m_data・m_valid）の生の標本を BRAM に溜めて、PS から AXI4-Lite で読む
//   目的: F-7 の f ± k·fs/56 の線・線の裾・F-6e の床の揺れが、荒い段より前（ADC の標本）に在るかを見る
//   荒い段の口を横から聞くだけ（s_data・s_valid は coarse_stage にもそのまま行く）。DSP クロックの側だけで動く
//
// 溜め方: ARM（CTRL[0] に 1 を書く）の後、valid の拍を DEPTH 拍そのまま溜める（16 標本 × DEPTH）。溜め終えたら DONE
//   拍の中の並び: 標本 i（0 が先）は s_data[16i +: 16]。BRAM は 32 bit の帯 8 本（帯 j = 標本 2j・2j+1）
// レジスタ（addr[18] = 0）: 0x00 ID  0x04 書き: [0] ARM / 読み: STATUS [0] 溜め中 [1] 溜め終えた
//           0x08 溜めた拍の数  0x0C DEPTH  0x10 ARM してから溜め始めるまでに落ちた（valid が 0 の）拍の数（参考）
//           0x14 溜めている間に valid が 0 だった拍の数（0 でなければ標本は続いていない）
// 標本（addr[18] = 1）: 語の番号 w = addr[17:2] → 拍 w[15:3]・帯 w[2:0]。読みは 2 拍遅れで rvalid
`default_nettype none
module adc_snap #(
    parameter [31:0] ID    = 32'h0280_00C8,
    parameter integer DW    = 256,
    parameter integer DEPTH = 8192,
    parameter integer AW    = 13           // log2(DEPTH)
) (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET aresetn" *)
    input  wire          clk,
    input  wire          aresetn,
    input  wire [DW-1:0] s_data,
    input  wire          s_valid,
    input  wire [18:0]   s_axi_awaddr,
    input  wire          s_axi_awvalid,
    output wire          s_axi_awready,
    input  wire [31:0]   s_axi_wdata,
    input  wire          s_axi_wvalid,
    output wire          s_axi_wready,
    output reg           s_axi_bvalid,
    output wire [1:0]    s_axi_bresp,
    input  wire          s_axi_bready,
    input  wire [18:0]   s_axi_araddr,
    input  wire          s_axi_arvalid,
    output wire          s_axi_arready,
    output reg  [31:0]   s_axi_rdata,
    output reg           s_axi_rvalid,
    output wire [1:0]    s_axi_rresp,
    input  wire          s_axi_rready
);
    localparam integer NL = DW / 32;       // 帯の数（8）
    wire rst = ~aresetn;

    // ---- 溜め ----
    reg          busy, done;
    reg [AW:0]   wp;
    reg [31:0]   pre_gap, gap;
    reg          arm_req;
    reg [DW-1:0] d_q;
    reg          v_q;
    always @(posedge clk) begin
        d_q <= s_data;
        v_q <= s_valid;
    end
    wire we = busy && v_q;
    always @(posedge clk) begin
        if (rst) begin
            busy <= 1'b0; done <= 1'b0; wp <= 0; pre_gap <= 32'd0; gap <= 32'd0;
        end else if (arm_req) begin
            busy <= 1'b1; done <= 1'b0; wp <= 0; pre_gap <= 32'd0; gap <= 32'd0;
        end else if (busy) begin
            if (v_q) begin
                wp <= wp + 1'b1;
                if (wp == DEPTH - 1) begin busy <= 1'b0; done <= 1'b1; end
            end else if (wp == 0) pre_gap <= pre_gap + 32'd1;
            else gap <= gap + 32'd1;
        end
    end

    // ---- BRAM（32 bit の帯 NL 本、書きは DW を一度に、読みは 1 本）----
    reg  [AW-1:0] ra;
    reg  [2:0]    rl, rl_q;
    wire [DW-1:0] rd_all;
    genvar j;
    generate
        for (j = 0; j < NL; j = j + 1) begin : lane
            (* ram_style = "block" *) reg [31:0] mem [0:DEPTH-1];
            reg [31:0] q;
            always @(posedge clk) begin
                if (we) mem[wp[AW-1:0]] <= d_q[32*j +: 32];
                q <= mem[ra];
            end
            assign rd_all[32*j +: 32] = q;
        end
    endgenerate

    // ---- AXI4-Lite ----
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !rst;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_rresp   = 2'b00;
    reg [1:0]  rph;                        // 0 空き・1 番地を BRAM へ・2 BRAM の出口を読む
    reg        r_mem;
    reg [5:0]  r_reg;
    assign s_axi_arready = (rph == 2'd0) && !s_axi_rvalid && !rst;
    always @(posedge clk) begin
        if (rst) begin
            s_axi_bvalid <= 1'b0; s_axi_rvalid <= 1'b0; arm_req <= 1'b0; rph <= 2'd0;
        end else begin
            arm_req <= wr_go && s_axi_awaddr[18] == 1'b0 && s_axi_awaddr[7:2] == 6'h01 && s_axi_wdata[0];
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) s_axi_bvalid <= 1'b1;
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            case (rph)
                2'd0: if (s_axi_arvalid && s_axi_arready) begin
                    r_mem <= s_axi_araddr[18];
                    r_reg <= s_axi_araddr[7:2];
                    ra    <= s_axi_araddr[AW+4:5];
                    rl    <= s_axi_araddr[4:2];
                    rph   <= 2'd1;
                end
                2'd1: begin rl_q <= rl; rph <= 2'd2; end           // BRAM が ra を読む拍
                default: begin
                    rph <= 2'd0;
                    s_axi_rvalid <= 1'b1;
                    if (r_mem) s_axi_rdata <= rd_all[32*rl_q +: 32];
                    else case (r_reg)
                        6'h00: s_axi_rdata <= ID;
                        6'h01: s_axi_rdata <= {30'd0, done, busy};
                        6'h02: s_axi_rdata <= {{(31 - AW){1'b0}}, wp};
                        6'h03: s_axi_rdata <= DEPTH;
                        6'h04: s_axi_rdata <= pre_gap;
                        6'h05: s_axi_rdata <= gap;
                        default: s_axi_rdata <= 32'hDEAD_BEEF;
                    endcase
                end
            endcase
        end
    end
endmodule
`default_nettype wire
