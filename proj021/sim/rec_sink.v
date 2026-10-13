// SPDX-License-Identifier: BSD-3-Clause
// proj021 2-2d — tb のレコードの受け手（s45_core・spec_core の m_axis_rec を受ける。tready は常に 1）
//   2-2c までの tb は、スペクトル・スナップショット・FULL の TP のリングを AXI4-Lite の仮の読み窓で読んでいた。2-2d で仮の読み窓が
//   無くなったので、同じ値をレコードから取る。レコードは捨てられずに（tuser = 0 で）終わったものだけを、流れ s ごとの最新として残す:
//     spec_m[4096·(s mod 4) + i]・spec_seq[s mod 4]・spec_hdr[8·(s mod 4) + w]（SPEC の本体・SEQ・頭）
//     snap_m[4096·(s mod 4) + j]・snap_seq[s mod 4]（SNAP の本体。DDC は 4096 語、FULL は 2048 語）
//     tp_m[個の番号 mod 1024]（TP のレコードの個 {語 1, 語 0}）・tp_n（来た個の数）・tp_end（最後の個の番号 + 1）。s = TP_S の TP だけ
//   n_rec・n_drop（tuser = 1）・n_bad（magic・長さの不一致）も数える
`timescale 1ns / 1ps
module rec_sink #(
    parameter [7:0] TP_S = 8'hFF          // 受ける TP のレコードの s（コアの TP は 0xFF、FULL の TP は FULL の流れの s）
)(
    input  wire        clk,
    input  wire [63:0] tdata,
    input  wire        tvalid,
    input  wire        tlast,
    input  wire        tuser
);
    reg [63:0]  spec_m [0:4*4096-1];
    reg [63:0]  snap_m [0:4*4096-1];
    reg [63:0]  spec_hdr [0:31];
    reg [31:0]  spec_seq [0:3];
    reg [31:0]  snap_seq [0:3];
    reg [127:0] tp_m [0:1023];
    integer     tp_n = 0, n_rec = 0, n_drop = 0, n_bad = 0;
    reg [31:0]  tp_end = 0;
    // 受けている途中のレコード
    reg [63:0]  buf_m [0:4095];
    reg [63:0]  hdr [0:7];
    integer     w = 0, i;
    reg [7:0]   ty, s;
    reg [31:0]  seq, nb;
    initial begin
        for (i = 0; i < 4; i = i + 1) begin spec_seq[i] = 32'hFFFF_FFFF; snap_seq[i] = 32'hFFFF_FFFF; end
    end
    always @(posedge clk) if (tvalid) begin
        if (w < 8) hdr[w] = tdata;
        else if (w - 8 < 4096) buf_m[w - 8] = tdata;
        if (tlast) begin
            ty = hdr[0][47:40]; s = hdr[0][63:56]; seq = hdr[1][31:0]; nb = hdr[7][31:0];
            if (tuser) n_drop = n_drop + 1;
            else if (hdr[0][31:0] !== 32'h5235_3453 || (w + 1 - 8) * 8 != nb) n_bad = n_bad + 1;
            else begin
                n_rec = n_rec + 1;
                if (ty == 8'd1) begin
                    for (i = 0; i < 4096; i = i + 1) spec_m[4096 * s[1:0] + i] = buf_m[i];
                    for (i = 0; i < 8; i = i + 1) spec_hdr[8 * s[1:0] + i] = hdr[i];
                    spec_seq[s[1:0]] = seq;
                end else if (ty == 8'd4) begin
                    for (i = 0; i < nb / 8; i = i + 1) snap_m[4096 * s[1:0] + i] = buf_m[i];
                    snap_seq[s[1:0]] = seq;
                end else if (ty == 8'd2 && s == TP_S) begin
                    for (i = 0; i < hdr[5][31:0]; i = i + 1) tp_m[(seq + i) % 1024] = {buf_m[2 * i + 1], buf_m[2 * i]};
                    tp_n = tp_n + hdr[5][31:0];
                    tp_end = seq + hdr[5][31:0];
                end
            end
            w = 0;
        end else w = w + 1;
    end
endmodule
