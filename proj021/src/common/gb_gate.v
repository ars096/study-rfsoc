// SPDX-License-Identifier: BSD-3-Clause
//
// gb_gate — ギアボックスの非同期 FIFO（gb_fifo）の出口に置く「読み出しの開始のしきい値」と見張り（proj011 rev6）
//
// **なぜ要るか**（README の rev6 の節）: gb_fifo の書き込み（341.33 MHz、4 クロックに 1 語）と読み出し
// （256 MHz、3 クロックに 1 語）は、同じ MMCM の VCO（1024 MHz）を 3 分周・4 分周したクロックで、語の周期は
// どちらも 12 VCO 周期（11.72 ns）で厳密に等しい。FIFO は空でなくなった瞬間に読み始めるので、起動の直後は
// 残量 1 語・余裕 0 クロックのまま定常になる。書き込みポインタ（gray）の各ビットが読み出し側の同期段に着く時刻は
// ビットごとに配線で違い、遅いビットが捕まえる縁を 1 つ越えると、その語だけが 1 クロック遅れて見える。
// 余裕 0 のときにそれが起きると、読み出しが 1 回だけ空振りして出口の valid が 1 クロック落ちる（その後は
// 余裕が 1 クロックできるので二度と起きない）。realtime の FFT IP はこの 1 回を待たずに進む。
//
// **対策**: 起動（このモジュールのリセットの解除）の後、FIFO に K 語溜まるまで読み出しを止める。
// 余裕が K − 1 語（≒ 3 (K − 1) クロック）でき、ビットごとの遅れの差（最大 1 クロック）では空にならない。
// 止めるのは起動の 1 回だけ。溜まった K 語は定常の残量として残る（FIFO の深さ 32 に対して K ≦ 24）。
// K = 0 なら素通し（rev5 までと同じ）。
//
// 見張り（spec_core に渡す。PS から読む）:
//   gb_stat[31]    開始した（armed）
//   gb_stat[29:24] 開始したときの残量（rd_count。63 で飽和）
//   gb_stat[21:16] 最初の受け渡しの後に見た残量の最小
//   gb_stat[15:0]  最初の受け渡しの後に、下流が欲しいのに FIFO が空だったクロック数（空振り。飽和）
// adc_stat: gb_adc（ADC ドメイン）の数えを 2 段で取り込んだもの。**静的な値として読む**（起動の後にしか変わらない。
//           PS は 2 回読んで一致を確かめる）。[31] RFDC の valid を見た / [15:0] RFDC の valid が落ちた回数
//
// **全部が DSP ドメイン（gb_fifo の m_axis_aclk）。**乗り換えは adc_in の取り込みだけ（ASYNC_REG）。

`timescale 1ns / 1ps

module gb_gate #(
    parameter integer DW = 768,      // 語幅（gb_mid × 16 bit）。build.tcl が与える
    parameter integer CW = 32        // gb_fifo の axis_rd_data_count の幅。build.tcl がピンの幅を読んで与える
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis:m_axis, ASSOCIATED_RESET aresetn" *)
    input  wire          aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire          aresetn,

    input  wire [DW-1:0] s_axis_tdata,
    input  wire          s_axis_tvalid,
    output wire          s_axis_tready,

    output wire [DW-1:0] m_axis_tdata,
    output wire          m_axis_tvalid,
    input  wire          m_axis_tready,

    input  wire [CW-1:0] rd_count,       // gb_fifo の axis_rd_data_count（m_axis_aclk に同期）
    input  wire [5:0]    k,              // しきい値（spec_core の GB_K）。起動の瞬間の値が効く
    output wire [31:0]   gb_stat,

    input  wire [16:0]   adc_in,         // gb_adc の {seen, gaps[15:0]}（ADC ドメイン）
    output wire [31:0]   adc_stat
);
    wire rst = ~aresetn;

    reg        armed, moved;
    reg  [5:0] cnt_arm, cnt_min;
    reg [15:0] under;
    wire [5:0] cnt6 = (rd_count > 63) ? 6'd63 : rd_count[5:0];

    assign m_axis_tdata  = s_axis_tdata;
    assign m_axis_tvalid = armed & s_axis_tvalid;
    assign s_axis_tready = armed & m_axis_tready;

    always @(posedge aclk) begin
        if (rst) begin
            armed <= 1'b0; moved <= 1'b0; cnt_arm <= 6'd0; cnt_min <= 6'd63; under <= 16'd0;
        end else begin
            if (!armed && cnt6 >= k) begin
                armed   <= 1'b1;
                cnt_arm <= cnt6;
            end
            if (armed && s_axis_tvalid && m_axis_tready) moved <= 1'b1;
            if (moved) begin
                if (cnt6 < cnt_min) cnt_min <= cnt6;
                if (m_axis_tready && !s_axis_tvalid && under != 16'hFFFF) under <= under + 16'd1;
            end
        end
    end
    assign gb_stat = {armed, 1'b0, cnt_arm, 2'b00, cnt_min, under};

    // ADC ドメインの数えの取り込み（静的な値として読む）
    (* ASYNC_REG = "TRUE" *) reg [16:0] adc_s1, adc_s2;
    always @(posedge aclk) begin
        adc_s1 <= adc_in;
        adc_s2 <= adc_s1;
    end
    assign adc_stat = {adc_s2[16], 15'd0, adc_s2[15:0]};
endmodule
