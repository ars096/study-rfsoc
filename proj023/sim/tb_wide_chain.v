// SPDX-License-Identifier: BSD-3-Clause
//
// tb_wide_chain — wide_chain ＋ wide_tw_rom の単体の sim（proj023 手順 2c-1、判定 A2 の後半: ひねり係数〜束ね）
//
// 入力:  $(OUT)/lanes_in.txt 1 行 = 1 クロック「k1 re0 im0 … re15 im15」（レーン FFT の出口。sim/check_wide.py genchain が
//        PFB の整数模型 → IP の行動模型（倍精度の DFT の丸め）で作る。**IP を通さずに鎖の後半だけを試す**）
// 出力:  $(OUT)/chain_out.txt 1 行 = 束ね 1 つ「frame jb sat pb0 … pb7」/ $(OUT)/chainreg.txt tw_mis
// 判定:  python3 sim/check_wide.py chain $(OUT) LB SHIFT
// -DLB=0|1|2・-DSHIFT=n。-DPOSCTL: ROM の番地を 1 ずらす（tw_mis が立ち A2 が落ちるべき）/ -DBIN_SKEW（wide_chain 側）: 束ねの区切りを 1 ずらす

`timescale 1ns / 1ps

module tb_wide_chain;
    parameter integer NF = 4;
    localparam integer NL = NF * 2048;

    reg clk = 1'b0;
    always #2 clk = ~clk;

    reg  rst = 1'b1;
    reg  [16*26-1:0] yr = 0, yi = 0;
    reg  [10:0]      k1 = 0;
    reg              yv = 1'b0;

    wire [10:0]  tw_addr, tw_k1;
    wire [575:0] tw;
`ifdef POSCTL
    wire [10:0]  rom_a = tw_addr + 11'd1;
`else
    wire [10:0]  rom_a = tw_addr;
`endif
    wide_tw_rom #(.TW_FILE(`TWF)) u_rom (.clk(clk), .addr(rom_a), .tw(tw), .k1_out(tw_k1));

    wire [8*39-1:0] pb;
    wire            pb_v, tw_mis;
    wire [10:0]     pb_jb;
    wire [5:0]      pb_sat;
    wide_chain dut (.clk(clk), .rst(rst), .y_re(yr), .y_im(yi), .y_k1(k1), .y_v(yv),
                    .tw_addr(tw_addr), .tw(tw), .tw_k1(tw_k1), .shift(4'd`SHIFT), .lb(2'd`LB),
                    .pb(pb), .pb_v(pb_v), .pb_jb(pb_jb), .pb_sat(pb_sat), .tw_mis(tw_mis));

    integer fo, fi, fr, n, p, kk, r;
    integer vr [0:15];
    integer vi [0:15];
    initial fr = -1;
    always @(posedge clk) begin
        if (pb_v) begin
            if (pb_jb == 11'd0) fr = fr + 1;
            $fwrite(fo, "%0d %0d %0d", fr, pb_jb, pb_sat);
            for (p = 0; p < 8; p = p + 1) $fwrite(fo, " %0d", pb[39*p +: 39]);
            $fwrite(fo, "\n");
        end
    end

    initial begin
        fo = $fopen({`OUT, "/chain_out.txt"}, "w");
        fi = $fopen({`OUT, "/lanes_in.txt"}, "r");
        repeat (10) @(posedge clk);
        rst <= 1'b0;
        repeat (3) @(posedge clk);
        for (n = 0; n < NL; n = n + 1) begin
            r = $fscanf(fi, "%d", kk);
            for (p = 0; p < 16; p = p + 1) r = $fscanf(fi, "%d %d", vr[p], vi[p]);
            @(posedge clk);
            k1 <= kk; yv <= 1'b1;
            for (p = 0; p < 16; p = p + 1) begin
                yr[26*p +: 26] <= vr[p];
                yi[26*p +: 26] <= vi[p];
            end
        end
        @(posedge clk);
        yv <= 1'b0;
        repeat (40) @(posedge clk);
        $fclose(fo); $fclose(fi);
        fo = $fopen({`OUT, "/chainreg.txt"}, "w");
        $fwrite(fo, "tw_mis %0d\n", tw_mis);
        $fclose(fo);
        $display("tb_wide_chain: LB %0d・SHIFT %0d・フレーム %0d 個・tw_mis %0d", `LB, `SHIFT, fr + 1, tw_mis);
        $finish;
    end
endmodule
