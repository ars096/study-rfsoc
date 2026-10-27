// SPDX-License-Identifier: BSD-3-Clause
//
// g24_cu — 2G-4 の PFB の係数を URAM に置き、4 コアで 1 組を共有する（proj031 P-1）。g24_coef（線形補間、DSP 64 / コア）の置き換え
//
// 中身（README の「形」、model/cu_model.py・pynq/g24cu.py）:
//   行 m（0..4095）= 16 レーン × {t 0, t 1} × 18 bit = 576 bit（係数 j = 2p + t が [18j +: 18]）。4096 × 576 bit = URAM288 × 8。
//   **ポート A** は番地 m（t 0・t 1）、**ポート B** は番地 4095 − m（レーンを逆順にして t 3 = t 0・t 2 = t 1。係数の対称性）。
//   出口は g24_coef と同じ 1152 bit の並び（レーン p が [72p +: 72]、タップ t が [18t +: 18]）。値は proj030 の g24_coef と bit 単位で同じ。
//
// **URAM は初期値を持てない**ので、起動のときに PS が AXI4-Lite で書く（2026-10-27、西村さん）:
//   DATA[0..17] に 18 語（576 bit、bit k が語 k div 32 の bit k mod 32）を書き、ROW に番地 m を書くと URAM[m] に書く（ポート A）。
//   CTRL の VERIFY で、PL が URAM の 4096 行をポート A で読み直して CRC を取り、**焼き込みの COEF_CRC と一致したら OK を立てる**。
//   書き（ROW）と VERIFY の始まりは OK を落とす（VERIFY の間はポート A の読みが走りの番地でなくなる）。
//   CRC は zlib.crc32（行 m = 0..4095 の 72 バイト。1 拍に 32 bit、src/g24/crc32_d32.vh、tools/gen_crc32.py）。
//
// 走りの読み: 番地 addr は s45_core_0 の m（T から作る、4 コアで同じ値）。毎拍読む。
//   遅れ: addr → coef が LAT = 3（URAM の読み 1・URAM の出口のレジスタ 1・並べ替え 1）。m_out・v_out・ok_out は同じ拍にそろえる。
//   コア 0 の番地のレジスタ 1 と各コアの受けの 1 段（coef_q）を足して 5 = g24_coef の LAT と同じ。
//
// ---- レジスタ（AXI4-Lite、0x000–0x3FF）----
//   0x00 ID 0x6375_0001 / 0x04 PROJ / 0x08 CTRL（W: [0] VERIFY・[1] CLR（NROW・VDONE・VMIS・WROTE を消す。OK は変えない））
//     CTRL の読み = STAT: [0] OK / [1] VERIFY 中 / [2] VERIFY を終えた / [3] 終えた VERIFY の CRC が COEF_CRC と違った / [4] CLR の後に ROW の書きがあった
//   0x0C ROW（W: 番地 m → DATA の 18 語を URAM[m] に。R: 最後に書いた番地）/ 0x10 COEF_CRC（焼き込み）/ 0x14 CRC（最後の VERIFY で取れた値）/
//   0x18 NROW（CLR の後の ROW の書きの数、飽和 16 bit）/ 0x40〜0x84 DATA[0..17]（W・R）
//   自作の AXI4-Lite の口はリセット中に ready を出さない（LESSONS、proj028）
//
// -DCU_MIRROR_ERR: ポート B の番地を 4094 − m にする（陽性対照。coef が g24_coef と違って落ちるべき。OK は立つ: CRC は中身を見るので）
// -DCU_NOREV: ポート B のレーンを逆順にしない（陽性対照。同じく落ちるべき）

`timescale 1ns / 1ps

module g24_cu #(
    // **integer の 10 進で書く**（32'h で書くと Vivado が CONFIG を読み返しで別の形にする、time_core の注）。COEF_CRC は 2^31 を越えるので 16 bit ずつ 2 つ
    parameter integer COEF_CRC_HI = 35099,         // 0x891B（make model-cu の COEF_CRC 0x891BE197 の上 16 bit）
    parameter integer COEF_CRC_LO = 57751,         // 0xE197
    parameter integer PROJ        = 3211520        // 0x0031_0100（proj031）
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET aresetn" *)
    input  wire          aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire          aresetn,
    // 走りの読み
    input  wire [11:0]   addr,
    input  wire          addr_v,
    output reg  [1151:0] coef,
    output reg  [11:0]   m_out,
    output reg           v_out,
    output reg           ok_out,
    // AXI4-Lite
    input  wire [9:0]    s_axi_awaddr,
    input  wire          s_axi_awvalid,
    output wire          s_axi_awready,
    input  wire [31:0]   s_axi_wdata,
    input  wire          s_axi_wvalid,
    output wire          s_axi_wready,
    output wire [1:0]    s_axi_bresp,
    output reg           s_axi_bvalid,
    input  wire          s_axi_bready,
    input  wire [9:0]    s_axi_araddr,
    input  wire          s_axi_arvalid,
    output wire          s_axi_arready,
    output reg  [31:0]   s_axi_rdata,
    output wire [1:0]    s_axi_rresp,
    output reg           s_axi_rvalid,
    input  wire          s_axi_rready
);
    localparam integer RW = 576;
    localparam integer NW = 18;
    localparam [31:0] COEF_CRC = (COEF_CRC_HI << 16) | COEF_CRC_LO;
    localparam [31:0] PROJ_W   = PROJ;
    wire clk = aclk;

    // リセットは 3 段で受ける（LESSONS: コアの中で 3 段）
    (* max_fanout = 64 *) reg rst = 1'b1;
    reg rst1 = 1'b1, rst2 = 1'b1;
    always @(posedge clk) begin rst1 <= ~aresetn; rst2 <= rst1; rst <= rst2; end

`include "crc32_d32.vh"

    // ---- AXI4-Lite の書き ----
    reg  [31:0] dat [0:NW-1];
    reg         ok;
    reg         vbusy, vdone, vmis, wrote;
    reg  [15:0] nrow;
    reg  [11:0] last_row;
    reg  [31:0] crc_got;
    reg         we_a;               // ポート A の書き（ROW を書いた次の拍）
    reg  [11:0] wa_a;
    reg         cmd_verify;
    wire        wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !rst;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    integer k;
    always @(posedge clk) begin
        we_a <= 1'b0; cmd_verify <= 1'b0;
        if (rst) begin
            s_axi_bvalid <= 1'b0; nrow <= 16'd0; wrote <= 1'b0; last_row <= 12'd0;
        end else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) begin
                s_axi_bvalid <= 1'b1;
                if (s_axi_awaddr[9:6] == 4'd1)                                              // 0x40〜0x7C（DATA 0..15）
                    dat[s_axi_awaddr[5:2]] <= s_axi_wdata;
                else if (s_axi_awaddr[9:2] == 8'h20 || s_axi_awaddr[9:2] == 8'h21)          // 0x80・0x84（DATA 16・17）
                    dat[16 + s_axi_awaddr[2]] <= s_axi_wdata;
                else case (s_axi_awaddr[9:2])
                    8'h02: begin
                        cmd_verify <= s_axi_wdata[0];
                        if (s_axi_wdata[1]) begin nrow <= 16'd0; wrote <= 1'b0; end
                    end
                    8'h03: begin
                        we_a <= 1'b1; wa_a <= s_axi_wdata[11:0]; last_row <= s_axi_wdata[11:0];
                        wrote <= 1'b1;
                        if (nrow != 16'hFFFF) nrow <= nrow + 16'd1;
                    end
                    default: ;
                endcase
            end
        end
    end
    wire [RW-1:0] din_a;
    genvar g;
    generate
        for (g = 0; g < NW; g = g + 1) begin : g_din
            assign din_a[32*g +: 32] = dat[g];
        end
    endgenerate

    // ---- URAM（4096 × 576、2 ポート）----
    reg  [11:0] vrow;               // VERIFY の読みの番地
    wire [11:0] ad_a = we_a ? wa_a : vbusy ? vrow : addr;
`ifdef CU_MIRROR_ERR
    wire [11:0] ad_b = 12'd4094 - addr;
`else
    wire [11:0] ad_b = ~addr;       // 4095 − m
`endif
    // URAM の本体は型どおりの小さなモジュール（g24_cu_ram、下）に切り出す。g24_cu の中に直に書くと、ポート A が READ_FIRST と読まれ
    // 「invalid write mode」（Synth 8-5792）で URAM の指定が無視され、BRAM 64 に落ちた（proj031 S の 1〜2 回目。単体の型では URAM 8 に入った）
    wire [RW-1:0] ra1, rb1;
    reg  [RW-1:0] ra2, rb2;
    g24_cu_ram #(.W(RW)) u_ram (.clk(clk), .wea(we_a), .aa(ad_a), .da(din_a), .qa(ra1), .ab(ad_b), .qb(rb1));
    always @(posedge clk) begin
        ra2 <= ra1;
        rb2 <= rb1;
    end

    // ---- 走りの出口: 並べ替え（LAT 3）----
    reg [11:0] m1, m2;
    reg        v1, v2, ok1, ok2;
    integer p;
    always @(posedge clk) begin
        m1 <= addr; v1 <= addr_v; ok1 <= ok;
        m2 <= m1;   v2 <= v1;     ok2 <= ok1;
        for (p = 0; p < 16; p = p + 1) begin
`ifdef CU_NOREV
            coef[72*p +  0 +: 18] <= ra2[36*p      +: 18];
            coef[72*p + 18 +: 18] <= ra2[36*p + 18 +: 18];
            coef[72*p + 36 +: 18] <= rb2[36*p + 18 +: 18];
            coef[72*p + 54 +: 18] <= rb2[36*p      +: 18];
`else
            coef[72*p +  0 +: 18] <= ra2[36*p             +: 18];   // t 0 = A のレーン p の t 0
            coef[72*p + 18 +: 18] <= ra2[36*p + 18        +: 18];   // t 1 = A のレーン p の t 1
            coef[72*p + 36 +: 18] <= rb2[36*(15 - p) + 18 +: 18];   // t 2 = B のレーン 15 − p の t 1
            coef[72*p + 54 +: 18] <= rb2[36*(15 - p)      +: 18];   // t 3 = B のレーン 15 − p の t 0
`endif
        end
        m_out <= m2; v_out <= v2; ok_out <= ok2 & ~rst;
    end

    // ---- VERIFY: 行を読み（ポート A、2 拍後に ra2）、18 拍で CRC を取る ----
    reg [RW-1:0] sh;
    reg [4:0]    nw;                // 行の中の語（0..17）。NW = 行を待っている
    reg [1:0]    wt;                // 読みを出してからの拍
    reg [31:0]   crc;
    reg          vlast;             // 今の行が 4095
    always @(posedge clk) begin
        if (rst) begin
            ok <= 1'b0; vbusy <= 1'b0; vdone <= 1'b0; vmis <= 1'b0; crc_got <= 32'd0;
        end else if (we_a) begin
            ok <= 1'b0; vbusy <= 1'b0;                          // 書きは VERIFY を打ち切る
        end else if (cmd_verify) begin
            ok <= 1'b0; vbusy <= 1'b1; vdone <= 1'b0; vmis <= 1'b0;
            vrow <= 12'd0; wt <= 2'd0; nw <= NW[4:0]; crc <= 32'hFFFFFFFF; vlast <= 1'b0;
        end else if (vbusy) begin
            if (nw == NW[4:0]) begin
                // 行を待つ: wt 0 の拍で ad_a = vrow → ra1（+1）→ ra2（+2）
                wt <= wt + 2'd1;
                if (wt == 2'd2) begin sh <= ra2; nw <= 5'd0; vlast <= (vrow == 12'd4095); end
            end else begin
                crc <= crc32_d32(crc, sh[31:0]);
                sh  <= sh >> 32;
                if (nw == NW[4:0] - 5'd1) begin
                    nw <= NW[4:0];
                    if (vlast) begin
                        vbusy <= 1'b0; vdone <= 1'b1;
                        crc_got <= crc32_d32(crc, sh[31:0]) ^ 32'hFFFFFFFF;
                        vmis <= (crc32_d32(crc, sh[31:0]) ^ 32'hFFFFFFFF) != COEF_CRC;
                        ok   <= (crc32_d32(crc, sh[31:0]) ^ 32'hFFFFFFFF) == COEF_CRC;
                    end else begin
                        vrow <= vrow + 12'd1; wt <= 2'd0;
                    end
                end else nw <= nw + 5'd1;
            end
        end
    end

    // ---- AXI4-Lite の読み ----
    assign s_axi_arready = !s_axi_rvalid && !rst;
    assign s_axi_rresp   = 2'b00;
    reg [31:0] rd;
    always @(*) begin
        rd = 32'd0;
        if (s_axi_araddr[9:6] == 4'd1) rd = dat[s_axi_araddr[5:2]];
        else if (s_axi_araddr[9:2] == 8'h20 || s_axi_araddr[9:2] == 8'h21) rd = dat[16 + s_axi_araddr[2]];
        else case (s_axi_araddr[9:2])
            8'h00: rd = 32'h6375_0001;
            8'h01: rd = PROJ_W;
            8'h02: rd = {27'd0, wrote, vmis, vdone, vbusy, ok};
            8'h03: rd = {20'd0, last_row};
            8'h04: rd = COEF_CRC;
            8'h05: rd = crc_got;
            8'h06: rd = {16'd0, nrow};
            default: rd = 32'd0;
        endcase
    end
    always @(posedge clk) begin
        if (rst) s_axi_rvalid <= 1'b0;
        else if (s_axi_arvalid && s_axi_arready) begin s_axi_rvalid <= 1'b1; s_axi_rdata <= rd; end
        else if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
    end
endmodule

// g24_cu_ram — 4096 × W の URAM（UG901 の型。ポート A は書きと読み（NO_CHANGE: 書く拍は qa を更新しない）、ポート B は読みだけ。読みの遅れ 1）
module g24_cu_ram #(
    parameter integer W = 576
)(
    input  wire          clk,
    input  wire          wea,
    input  wire [11:0]   aa,
    input  wire [W-1:0]  da,
    output reg  [W-1:0]  qa,
    input  wire [11:0]   ab,
    output reg  [W-1:0]  qb
);
    (* ram_style = "ultra" *) reg [W-1:0] mem [0:4095];
`ifdef __ICARUS__
    // URAM は構成の後に 0（sim はそれに合わせる。書き忘れの陽性対照の CRC は「全部 0」の値になる）。iverilog だけ
    integer z;
    initial for (z = 0; z < 4096; z = z + 1) mem[z] = {W{1'b0}};
`endif
    always @(posedge clk) begin
        if (wea) mem[aa] <= da;
        else     qa <= mem[aa];
    end
    always @(posedge clk) qb <= mem[ab];
endmodule
