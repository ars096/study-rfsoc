// SPDX-License-Identifier: BSD-3-Clause
//
// win_core — 窓 1 つの分光計（bit ③ の 1 ADC × 1 窓）。ギアボックスの出口 → pfb_core → ddc_core → wspec_core。AXI4-Lite で制御と読み出し
//
// ブロックデザインには module reference で置く（spec_core と同じ）。**全部が DSP ドメイン（256 MHz）**。AXI4-Lite も 256 MHz で受ける。
//
// ---- 窓の設定（WK・WDPHI・WNS）----
// 書いただけでは効かない。**CTRL[12] = WRST** で、書いておいた値を取り込み、pfb・ddc・wspec を WRST_T クロックだけリセットして
// 最初から回し直す（フレーム番号・積分も最初から）。ハードのリセットの後は既定値（WK = 0・WDPHI = 0・WNS = 1）で回る。
//   窓の中心 c（f の側、ゾーン 2 の IF の中心 C なら c = 4096 − C）→ WK = round(c / 128)、d = c − 128·WK、WDPHI = round(d / 512 · 2^32) mod 2^32
//   幅 W = 512 / 2^WNS MHz（WNS = 1..6 → 256..8 MHz）
// **入力の途切れ（ギアボックスの出口の tvalid = 0）は値を変えない**: pfb_core は valid なビートだけで窓を進め、以降は組ごとに進む。
// realtime の FFT IP に直につながないので、proj011〜013 の起動の途切れの守り（見張り・GRST）はこの経路では要らない。
//
// ---- アドレスマップ（バイト。17 bit = 128 KiB）----
//   0x00000–0x000FF  レジスタ（下の表）
//   0x08000–0x0FFFF  スナップショット: サンプル i の re が 0x08000 + 8i、im が +4（18 bit を 32 bit に符号拡張）
//   0x10000–0x17FFF  スペクトル: ch b の 64 bit が 0x10000 + 8b（下位語）/ +4（上位語）。ch b ↔ ν = b·W/4096（b < 2048）/ (b − 4096)·W/4096
//
//   0x00 ID        R   0x0014_0100（proj014 rev1、窓）
//   0x04 PARAM     R   [7:0] log2 NFFT = 12 / [10:8] 今の WNS / [23:16] QW = 18 / [31:24] ZW = 18
//   0x08 CTRL      W   [0] RUN / [1] STOP / [8] FLAGS を消す / [12] WRST（窓の設定を取り込んで最初から）（1 を書いた瞬間だけ）
//                  R   [0] 積分中 / [1] 開始待ち / [3] z が流れ始めた / [4] WRST 中
//   0x0C N_ACC     RW  1 ダンプのフレーム数（0 は 1）。RUN の時点で取り込む。1 フレーム = 4096 / W µs（256 MHz で 16 µs、8 MHz で 512 µs）
//   0x10 N_DUMP    RW  ダンプの回数。0 = 止めるまで
//   0x14 SHIFT     RW  [3:0] 電力の前の右シフト（FFT の出力 31 bit → 18 bit）。既定 SHIFT_DEFAULT
//   0x18 FLAGS     R   [7:0] wspec_core の FLAGS（粘着、CTRL[8] で消す）/ [8] pfb の飽和あり / [9] ddc の飽和あり（WRST で消える）
//   0x1C SEQ       R   閉じたダンプの通し番号
//   0x20 FIN_LO    R   溜め終えたフレーム数。**LO を読むと HI を固定**   0x24 FIN_HI
//   0x28 FOUT_LO   R   FFT を出たフレーム数（同上）                       0x2C FOUT_HI
//   0x30 DUMP_K / 0x34 DUMP_N / 0x38 DUMP_F0_LO / 0x3C DUMP_F0_HI / 0x40 DUMP_SAT   （spec_core と同じ）
//   0x44 SNAP_F_LO / 0x48 SNAP_F_HI   読み出し窓の面のスナップショットのフレーム番号（DUMP_F0 と一致すれば同じフレーム）
//   0x4C BANK      R   読み出し窓の面
//   0x50 RUN_F0_LO / 0x54 RUN_F0_HI
//   0x58 WK        RW  [4:0] 粗い ch（0..16）       次の WRST で効く。R は書いた値
//   0x5C WDPHI     RW  NCO の 1 サンプルの位相の増分（32 bit）
//   0x60 WNS       RW  [2:0] 半帯域の段数（1..6）
//   0x64 WCUR      R   今効いている [4:0] WK / [10:8] WNS（WDPHI は 0x68）
//   0x68 WCUR_DPHI R
//   0x6C PFB_SAT   R   pfb_core の飽和の回数（WRST 以来、飽和して止まる）
//   0x70 DDC_SAT   R   ddc_core の飽和の回数
//   0x74 BUILD     R   ビルドの指紋（build.tcl が与える）
//   0x78 WRST_T    RW  [15:0] WRST のリセットの長さ（クロック、0 は 1）。既定 64
//   0x7C WRST_CNT  R   WRST を受けた回数
//
// **スナップショットはダンプの commit から (N_ACC − 2) フレーム以内に読む**（wspec_core の冒頭）

`timescale 1ns / 1ps

module win_core #(
    parameter integer N_ACC_DEFAULT = 6250,   // 256 MHz 窓で 100 ms
    parameter integer SHIFT_DEFAULT = 4,
    parameter integer BUILD_TAG     = 0
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis:s_axi, ASSOCIATED_RESET aresetn" *)
    input  wire         aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire         aresetn,
    input  wire [255:0] s_axis_tdata,
    input  wire         s_axis_tvalid,
    output wire         s_axis_tready,
    input  wire [16:0]  s_axi_awaddr,
    input  wire [2:0]   s_axi_awprot,
    input  wire         s_axi_awvalid,
    output wire         s_axi_awready,
    input  wire [31:0]  s_axi_wdata,
    input  wire [3:0]   s_axi_wstrb,
    input  wire         s_axi_wvalid,
    output wire         s_axi_wready,
    output wire [1:0]   s_axi_bresp,
    output reg          s_axi_bvalid,
    input  wire         s_axi_bready,
    input  wire [16:0]  s_axi_araddr,
    input  wire [2:0]   s_axi_arprot,
    input  wire         s_axi_arvalid,
    output wire         s_axi_arready,
    output reg  [31:0]  s_axi_rdata,
    output wire [1:0]   s_axi_rresp,
    output reg          s_axi_rvalid,
    input  wire         s_axi_rready
);
    localparam integer FW = 48;
    localparam [31:0]  ID = 32'h0014_0100;
    wire rst = ~aresetn;
    assign s_axis_tready = 1'b1;       // 上流に backpressure をかけない

    // ---- 書き込み（レジスタ）----
    reg [31:0] r_nacc, r_ndump, r_dphi;
    reg [3:0]  r_shift;
    reg [4:0]  r_k;
    reg [2:0]  r_ns;
    reg [15:0] r_wt;
    reg        cmd_run, cmd_stop, cmd_clr, cmd_wrst;
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    always @(posedge aclk) begin
        cmd_run <= 1'b0; cmd_stop <= 1'b0; cmd_clr <= 1'b0; cmd_wrst <= 1'b0;
        if (rst) begin
            s_axi_bvalid <= 1'b0;
            r_nacc <= N_ACC_DEFAULT; r_ndump <= 32'd0; r_shift <= SHIFT_DEFAULT;
            r_k <= 5'd0; r_dphi <= 32'd0; r_ns <= 3'd1; r_wt <= 16'd64;
        end else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) begin
                s_axi_bvalid <= 1'b1;
                if (s_axi_awaddr[16:8] == 9'd0) case (s_axi_awaddr[7:2])
                    6'h02: begin
                        cmd_run  <= s_axi_wdata[0];
                        cmd_stop <= s_axi_wdata[1];
                        cmd_clr  <= s_axi_wdata[8];
                        cmd_wrst <= s_axi_wdata[12];
                    end
                    6'h03: r_nacc  <= s_axi_wdata;
                    6'h04: r_ndump <= s_axi_wdata;
                    6'h05: r_shift <= s_axi_wdata[3:0];
                    6'h16: r_k     <= s_axi_wdata[4:0];
                    6'h17: r_dphi  <= s_axi_wdata;
                    6'h18: r_ns    <= s_axi_wdata[2:0];
                    6'h1E: r_wt    <= s_axi_wdata[15:0];
                    default: ;
                endcase
            end
        end
    end

    // ---- WRST: 設定を取り込み、窓の経路を最初から ----
    reg [4:0]  c_k;
    reg [31:0] c_dphi;
    reg [2:0]  c_ns;
    reg [15:0] wr_cnt;
    reg        w_rst;
    reg [31:0] wrst_n;
    always @(posedge aclk) begin
        if (rst) begin
            c_k <= 5'd0; c_dphi <= 32'd0; c_ns <= 3'd1;
            wr_cnt <= 16'd0; w_rst <= 1'b1; wrst_n <= 32'd0;
        end else if (cmd_wrst) begin
            c_k <= r_k; c_dphi <= r_dphi; c_ns <= (r_ns >= 3'd1 && r_ns <= 3'd6) ? r_ns : 3'd1;
            wr_cnt <= (r_wt == 16'd0) ? 16'd1 : r_wt;
            w_rst <= 1'b1; wrst_n <= wrst_n + 32'd1;
        end else if (wr_cnt != 16'd0) begin
            wr_cnt <= wr_cnt - 16'd1;
            w_rst  <= (wr_cnt != 16'd1);
        end else w_rst <= 1'b0;
    end
    wire core_rst = rst | w_rst;

    // ---- 窓の経路 ----
    wire signed [23:0] y0r, y0i, y1r, y1i;
    wire y0ok, y1ok, yv;
    wire [15:0] pfb_sat, ddc_sat;
    pfb_core u_pfb (.clk(aclk), .rst(core_rst), .s_tdata(s_axis_tdata), .s_tvalid(s_axis_tvalid), .k(c_k),
                    .y0_re(y0r), .y0_im(y0i), .y1_re(y1r), .y1_im(y1i),
                    .y0_ok(y0ok), .y1_ok(y1ok), .y_valid(yv), .sat_cnt(pfb_sat));
    wire zv;
    wire signed [17:0] zr, zi;
    ddc_core u_ddc (.clk(aclk), .rst(core_rst), .y_valid(yv), .y0_ok(y0ok), .y1_ok(y1ok),
                    .y0_re(y0r), .y0_im(y0i), .y1_re(y1r), .y1_im(y1i),
                    .dphi(c_dphi), .ns(c_ns), .z_valid(zv), .z_re(zr), .z_im(zi), .sat_cnt(ddc_sat));
    wire [FW-1:0] fin, fout, run_f0, rd_f0, snap_f0, snap_f1;
    wire          sched, acc_on, rd_bank;
    wire [31:0]   seq, rd_k, rd_n, rd_sat;
    wire [7:0]    wflags;
    reg           ax_bank;
    reg  [11:0]   ax_ch;
    wire [63:0]   sp_data;
    wire [35:0]   sn_data;
    wspec_core u_ws (.clk(aclk), .rst(core_rst), .z_valid(zv), .z_re(zr), .z_im(zi),
        .cmd_run(cmd_run), .cmd_stop(cmd_stop), .cmd_clr(cmd_clr),
        .r_nacc(r_nacc), .r_ndump(r_ndump), .r_shift(r_shift),
        .fin(fin), .fout(fout), .run_f0(run_f0), .sched(sched), .acc_on(acc_on),
        .seq(seq), .rd_k(rd_k), .rd_n(rd_n), .rd_sat(rd_sat), .rd_f0(rd_f0), .rd_bank(rd_bank),
        .snap_f0(snap_f0), .snap_f1(snap_f1), .flags(wflags),
        .rd_bk(ax_bank), .rd_ch(ax_ch), .rd_data(sp_data), .sn_bk(ax_bank), .sn_a(ax_ch), .sn_data(sn_data));
    reg z_seen;
    always @(posedge aclk) begin
        if (core_rst) z_seen <= 1'b0;
        else if (zv)  z_seen <= 1'b1;
    end

    // ---- 読み出し ----
    reg [16:0]   ar_addr;
    reg [2:0]    ar_wait;
    reg          ar_busy;
    reg [FW-1:0] fin_lat, fout_lat;
    assign s_axi_arready = !ar_busy && !s_axi_rvalid;
    assign s_axi_rresp   = 2'b00;
    reg [31:0] reg_rd;
    always @* begin
        case (ar_addr[7:2])
            6'h00: reg_rd = ID;
            6'h01: reg_rd = {8'd18, 8'd18, 5'd0, c_ns, 8'd12};
            6'h02: reg_rd = {27'd0, w_rst, z_seen, 1'b0, sched, acc_on};
            6'h03: reg_rd = r_nacc;
            6'h04: reg_rd = r_ndump;
            6'h05: reg_rd = {28'd0, r_shift};
            6'h06: reg_rd = {22'd0, ddc_sat != 16'd0, pfb_sat != 16'd0, wflags};
            6'h07: reg_rd = seq;
            6'h08: reg_rd = fin_lat[31:0];
            6'h09: reg_rd = {{(64-FW){1'b0}}, fin_lat[FW-1:32]};
            6'h0A: reg_rd = fout_lat[31:0];
            6'h0B: reg_rd = {{(64-FW){1'b0}}, fout_lat[FW-1:32]};
            6'h0C: reg_rd = rd_k;
            6'h0D: reg_rd = rd_n;
            6'h0E: reg_rd = rd_f0[31:0];
            6'h0F: reg_rd = {{(64-FW){1'b0}}, rd_f0[FW-1:32]};
            6'h10: reg_rd = rd_sat;
            6'h11: reg_rd = rd_bank ? snap_f1[31:0] : snap_f0[31:0];
            6'h12: reg_rd = {{(64-FW){1'b0}}, rd_bank ? snap_f1[FW-1:32] : snap_f0[FW-1:32]};
            6'h13: reg_rd = {31'd0, rd_bank};
            6'h14: reg_rd = run_f0[31:0];
            6'h15: reg_rd = {{(64-FW){1'b0}}, run_f0[FW-1:32]};
            6'h16: reg_rd = {27'd0, r_k};
            6'h17: reg_rd = r_dphi;
            6'h18: reg_rd = {29'd0, r_ns};
            6'h19: reg_rd = {21'd0, c_ns, 3'd0, c_k};
            6'h1A: reg_rd = c_dphi;
            6'h1B: reg_rd = {16'd0, pfb_sat};
            6'h1C: reg_rd = {16'd0, ddc_sat};
            6'h1D: reg_rd = BUILD_TAG;
            6'h1E: reg_rd = {16'd0, r_wt};
            6'h1F: reg_rd = wrst_n;
            default: reg_rd = 32'hDEAD_BEEF;
        endcase
    end
    always @(posedge aclk) begin
        if (rst) begin
            ar_busy <= 1'b0; ar_wait <= 3'd0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0;
            ar_addr <= 17'd0; ax_bank <= 1'b0; ax_ch <= 12'd0;
            fin_lat <= {FW{1'b0}}; fout_lat <= {FW{1'b0}};
        end else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin
                ar_busy <= 1'b1;
                ar_wait <= 3'd0;
                ar_addr <= s_axi_araddr;
                ax_bank <= rd_bank;
                ax_ch   <= s_axi_araddr[14:3];      // スナップショット・スペクトルとも 8 バイト / 語
                if (s_axi_araddr[16:2] == 15'h08) fin_lat  <= fin;
                if (s_axi_araddr[16:2] == 15'h0A) fout_lat <= fout;
            end else if (ar_busy) begin
                ar_wait <= ar_wait + 3'd1;
                if (ar_wait == 3'd3) begin
                    ar_busy      <= 1'b0;
                    s_axi_rvalid <= 1'b1;
                    if (ar_addr[16])
                        s_axi_rdata <= ar_addr[2] ? sp_data[63:32] : sp_data[31:0];
                    else if (ar_addr[15])
                        s_axi_rdata <= ar_addr[2] ? {{14{sn_data[35]}}, sn_data[35:18]} : {{14{sn_data[17]}}, sn_data[17:0]};
                    else
                        s_axi_rdata <= reg_rd;
                end
            end
        end
    end
endmodule
