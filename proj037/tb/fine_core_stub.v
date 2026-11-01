// SPDX-License-Identifier: BSD-3-Clause
// proj037 U-c — fine_core の口だけ同じスタブ（sim 専用。s2_strm の帳簿と頭の組み立てだけを速く見る）
//
//   本物の fine_core は荒い段といっしょに回すと 1 レコード（114,696 語）に iverilog で数十分かかる。帳簿と頭は s2_strm の中なので、
//   細かい側は「ch を受けて rdo_go を出し、受けた頭で短いレコードを出す」だけにする。中身の道は sim-fcore・sim-facc が見ている。
//   - s_axis: いつも受ける。ch の最後の拍（tlast）で、その ch の {k, c}・本体のフレームの数 nb（tuser[0] = 0 の拍 / 256）を覚え、
//     10 拍後に rdo_go（rdo_n = nb）
//   - rdo_en = 1 なら hdr_v を待ち、w0（fine_rdo と同じ形）＋ hdr の 7 語 ＋ 本体 4 語（0..3）を出す。最後の語で tlast、tuser = hdr_bad
//   - rdo_en = 0 なら出さない
`timescale 1ns / 1ps
module fine_core #(
    parameter [7:0] SID_S    = 8'd0,
    parameter [7:0] REC_CORE = 8'd0,
    parameter LO_FILE = "",
    parameter HI_FILE = "",
    parameter TA_FILE = "",
    parameter TB_FILE = "",
    parameter integer ST_N = 64,
    parameter integer FB_LOG = 14
)(
    input  wire          clk,
    input  wire          rst,
    input  wire [511:0]  s_axis_tdata,
    input  wire [21:0]   s_axis_tuser,
    input  wire          s_axis_tlast,
    input  wire          s_axis_tvalid,
    output wire          s_axis_tready,
    input  wire [3:0]    shift,
    output wire [63:0]   m_axis_tdata,
    output wire          m_axis_tlast,
    output wire          m_axis_tuser,
    output wire          m_axis_tvalid,
    input  wire          m_axis_tready,
    output reg           rdo_go,
    output reg  [4:0]    rdo_k,
    output reg  [15:0]   rdo_c,
    output reg  [15:0]   rdo_n,
    input  wire          rdo_en,
    input  wire          hdr_v,
    input  wire [447:0]  hdr,
    input  wire          hdr_bad,
    output wire [15:0]   rdo_ndrop,
    output reg  [8:0]    flags,
    output reg  [31:0]   n_rec,
    output wire [16*64-1:0] dbg_ip_tdata,
    output wire [12:0]   dbg_ip_k1,
    output wire          dbg_ip_v
);
    assign s_axis_tready = !rst;
    assign rdo_ndrop = 16'd0;
    assign dbg_ip_tdata = 0; assign dbg_ip_k1 = 0; assign dbg_ip_v = 0;
    localparam [31:0] MAGIC = 32'h5235_3453;
    reg [31:0] nbb;
    reg [4:0]  lk; reg [15:0] lc; reg [15:0] ln;
    reg [3:0]  dl;
    reg        busy, hok, bad;
    reg [447:0] hl;
    reg [3:0]  wi;
    always @(posedge clk) begin
        rdo_go <= 1'b0;
        if (rst) begin nbb <= 0; dl <= 0; busy <= 1'b0; hok <= 1'b0; wi <= 0; flags <= 9'd0; n_rec <= 0; end
        else begin
            if (s_axis_tvalid) begin
                if (!s_axis_tuser[0]) nbb <= nbb + 1;
                if (s_axis_tlast) begin
                    lk <= s_axis_tuser[5:1]; lc <= s_axis_tuser[21:6]; ln <= (nbb + (s_axis_tuser[0] ? 0 : 1)) / 256;
                    nbb <= 0; dl <= 4'd10;
                end
            end
            if (dl != 0) begin
                dl <= dl - 1;
                if (dl == 1) begin
                    rdo_go <= 1'b1; rdo_k <= lk; rdo_c <= lc; rdo_n <= ln;
                end
            end
            if (rdo_go && rdo_en) begin busy <= 1'b1; hok <= 1'b0; wi <= 0; n_rec <= n_rec + 1; end
            if (busy && hdr_v && !hok) begin hl <= hdr; bad <= hdr_bad; hok <= 1'b1; end
            if (m_axis_tvalid && m_axis_tready) begin
                if (wi == 4'd11) begin busy <= 1'b0; wi <= 0; end else wi <= wi + 1;
            end
        end
    end
    assign m_axis_tvalid = busy && hok;
    assign m_axis_tdata  = (wi == 0) ? {SID_S, REC_CORE, 8'd1, 8'd1, MAGIC} : (wi <= 7) ? hl[64*(wi-1) +: 64] : {60'd0, wi - 4'd8};
    assign m_axis_tlast  = (wi == 4'd11);
    assign m_axis_tuser  = (wi == 4'd11) && bad;
endmodule
