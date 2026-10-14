// SPDX-License-Identifier: BSD-3-Clause
//
// tb_wide_pfb — wide_pfb ＋ wide_coef_rom の単体の sim（proj023 手順 2b、判定 A1）
//
// 入力:  $(OUT)/stim.hex   1 行 = 1 ビート（256 bit、下位が古いサンプル）。sim/check_wide.py gen が作る
// 出力:  $(OUT)/pfbout.txt 1 行 = 1 ビート「frame m y0 … y15」（frame は起動からの番号）
//        $(OUT)/pfbreg.txt coef_mis・sat_cnt
// 判定:  python3 sim/check_wide.py pfb $(OUT)（PFB の整数模型と bit 単位）
//
// 起動の型: rst を下ろした後、**フレームの途中（m = 2048 − PRE）から**ビートを流す（m は共通の数え、ROM の番地も同じ値）。
// PRE ビートはごみ（wide_pfb は m = 0 まで捨てるはず）。その後 stim の NF フレームを途切れなく。
// 履歴（hmem）には前の起動の残りに見立てたごみを入れてから始める（起動の直後の 3 フレームのマスクを試す）。
// -DPOSCTL: ROM の番地を 1 ずらす（係数の共有の食い違い）→ coef_mis が立ち、A1 が落ちるべき
// -DPFB_NOMASK（wide_pfb 側）: 起動の直後のマスクを外す → 最初の 3 フレームがごみを拾い、A1 が落ちるべき

`timescale 1ns / 1ps

module tb_wide_pfb;
    parameter integer NF  = 6;
    parameter integer PRE = 100;
    localparam integer NBEAT = NF * 2048;

    reg clk = 1'b0;
    always #2 clk = ~clk;

    reg  [255:0] stim [0:NBEAT-1];
    initial $readmemh({`OUT, "/stim.hex"}, stim);

    reg          rst = 1'b1;
    reg  [255:0] d   = 256'd0;
    reg          dv  = 1'b0;
    reg  [10:0]  m   = 11'd0;

    wire [1151:0] coef;
    wire [10:0]   coef_m;
    wire          coef_v;
`ifdef POSCTL
    wire [10:0]   rom_a = m + 11'd1;
`else
    wire [10:0]   rom_a = m;
`endif
    wide_coef_rom #(.COEF_FILE(`COEF)) u_rom (.clk(clk), .addr(rom_a), .addr_v(dv), .coef(coef), .m_out(coef_m), .v_out(coef_v));

    wire [16*15-1:0] y;
    wire             y_v, y_first, coef_mis;
    wire [10:0]      y_m;
    wire [1:0]       y_fr;
    wire [15:0]      sat_cnt;
    wide_pfb dut (.clk(clk), .rst(rst), .s_tdata(d), .s_tvalid(dv), .s_m(m), .coef(coef), .coef_m(coef_m),
                  .y(y), .y_v(y_v), .y_m(y_m), .y_first(y_first), .y_fr(y_fr), .sat_cnt(sat_cnt), .coef_mis(coef_mis));

    integer fo, fr, b, p;
    initial fr = -1;
    always @(posedge clk) begin
        if (y_v) begin
            if (y_first) fr = fr + 1;
            if (fr >= 0) begin
                $fwrite(fo, "%0d %0d", fr, y_m);
                for (p = 0; p < 16; p = p + 1) $fwrite(fo, " %0d", $signed(y[15*p +: 15]));
                $fwrite(fo, "\n");
            end
        end
    end

    integer h;
    initial begin
        // 履歴に前の起動の残り（ごみ）を入れておく（SRST・GRST の後と同じ。wide_pfb は fr でタップを 0 にするはず）
        for (h = 0; h < 2048; h = h + 1) dut.hmem[h] = {21{32'h5A5A_1234 ^ h}};
        fo = $fopen({`OUT, "/pfbout.txt"}, "w");
        repeat (10) @(posedge clk);
        rst <= 1'b0;
        repeat (3) @(posedge clk);
        for (b = 0; b < PRE; b = b + 1) begin                 // フレームの途中から（ごみ）
            @(posedge clk);
            d <= {16{16'h7FFC}}; dv <= 1'b1; m <= (2048 - PRE + b) % 2048;
        end
        for (b = 0; b < NBEAT; b = b + 1) begin
            @(posedge clk);
            d <= stim[b]; dv <= 1'b1; m <= b % 2048;
        end
        @(posedge clk);
        dv <= 1'b0;
        repeat (20) @(posedge clk);
        $fclose(fo);
        fo = $fopen({`OUT, "/pfbreg.txt"}, "w");
        $fwrite(fo, "coef_mis %0d\nsat_cnt %0d\n", coef_mis, sat_cnt);
        $fclose(fo);
        $display("tb_wide_pfb: フレーム %0d 個を書いた・coef_mis %0d・sat_cnt %0d", fr + 1, coef_mis, sat_cnt);
        $finish;
    end
endmodule
