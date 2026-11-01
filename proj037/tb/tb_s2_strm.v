// SPDX-License-Identifier: BSD-3-Clause
// proj037 U-b・U-c・U-e — s2_strm の試験台（B_C を縮めて）
//
//   拍ごとの T（Tc）を数え、time_core の代わりに t_in = Tc + 1・go_in = (Tc + 1 == START_AT) を渡す（コアの t_loc = Tc、go_loc は Tc = START_AT の拍）。
//   s_axis は axis_sel4 の出口の代わり: 拍 Tc に「コアの入口の T が Tc − 1 のサンプル」を出す。
//   サンプル（14 bit、拍の中の p 番）: `NOISE なら $random の雑音（± 1023）、そうでなければ 0。`IMP_T の拍の `IMP_P 番に IMP_A（孤立したサンプル）
//   手順: N_DUMP・CFG_ID・REC_CTRL（ALL）・GAIN を書き、CTRL に ARM_RUN（`DIRECT なら RUN）。
//   書き出し:
//     OUT_BLK: 荒い段の出口（m_axis_ct の valid の拍）ごとに「ブロックの番号（出口で数えた）・tuser」
//     OUT_Z  : coarse_pfb の出口のブロックごとに「番号・0 でない z の {r, 値}」（`IMP_A のとき）
//     OUT_SAT: 印から数えたチャンク c・荒い ch k ごとの飽和の数（coarse_post の m_clip を数え直したもの）
//     OUT_REC: レコードの語「tlast tuser 語」
//     OUT_REG: 終わりに流れのブロックの 0x00〜0x88 と診断 0x3D0
//   `FEED: s_axis_ct に (c, k, 末尾, 本体) の ch を流す（fine_core。`FEED_LIST の数だけ。1 本ずつ、レコードが出切るまで待つ）
`timescale 1ns/1ps
`default_nettype none
module tb_s2_strm;
`ifndef IMP_A
`define IMP_A 0
`endif
`ifndef IMP_T
`define IMP_T 0
`endif
`ifndef IMP_P
`define IMP_P 0
`endif
`ifndef NFEED
`define NFEED 0
`endif
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg aresetn = 0;
    reg [63:0] Tc = `T_BEGIN;
    always @(posedge clk) Tc <= Tc + 64'd1;
    wire [63:0] t_in = Tc + 64'd1;
    wire go_in = (Tc + 64'd1 == `START_AT);
    // ADC（入口の T が Tc − 1 のビート）
    integer seed = 21, p;
    reg [255:0] d;
    reg signed [13:0] xs;
    always @(posedge clk) begin
        for (p = 0; p < 16; p = p + 1) begin
`ifdef NOISE
            xs = $random(seed) % 1024;
`else
            xs = 14'sd0;
`endif
            if (Tc == `IMP_T && p == `IMP_P) xs = `IMP_A;
            d[16*p +: 16] <= {xs, 2'b00};
        end
    end
    // d は次の拍に出る: 拍 Tc に作った d は拍 Tc + 1 の s_axis（= 入口の T が Tc のサンプル）
    reg [9:0]  aw = 0, ar = 0;
    reg        awv = 0, arv = 0;
    reg [31:0] wd = 0;
    wire       awr, wr_, bv, arr, rv;
    wire [31:0] rdat;
    wire [511:0] ct_d; wire ct_u, ct_v;
    reg  [511:0] f_d = 0; reg [21:0] f_u = 0; reg f_l = 0, f_v = 0; wire f_r;
    wire [63:0] r_d; wire r_v, r_l, r_u, drop; reg r_r = 1;
    wire [1:0] src_sel;
    s2_strm #(.B_C(`B_C), .BASE_BEATS(`BASE)) dut (.aclk(clk), .aresetn(aresetn), .s_axis_tdata(d), .s_axis_tvalid(aresetn),
        .s_axi_awaddr(aw), .s_axi_awvalid(awv), .s_axi_awready(awr), .s_axi_wdata(wd), .s_axi_wvalid(awv), .s_axi_wready(wr_),
        .s_axi_bvalid(bv), .s_axi_bready(1'b1), .s_axi_araddr(ar), .s_axi_arvalid(arv), .s_axi_arready(arr),
        .s_axi_rdata(rdat), .s_axi_rvalid(rv), .s_axi_rready(1'b1),
        .src_sel(src_sel), .t_in(t_in), .go_in(go_in), .tev_in(4'd0),
        .m_axis_ct_tdata(ct_d), .m_axis_ct_tuser(ct_u), .m_axis_ct_tvalid(ct_v),
        .s_axis_ct_tdata(f_d), .s_axis_ct_tuser(f_u), .s_axis_ct_tlast(f_l), .s_axis_ct_tvalid(f_v), .s_axis_ct_tready(f_r),
        .m_axis_rec_tdata(r_d), .m_axis_rec_tvalid(r_v), .m_axis_rec_tready(r_r), .m_axis_rec_tlast(r_l), .m_axis_rec_tuser(r_u),
        .rec_drop(drop));
    task wr(input [9:0] a, input [31:0] v); begin
        @(negedge clk); aw = a; wd = v; awv = 1;
        @(posedge clk); while (!awr) @(posedge clk);
        @(negedge clk); awv = 0;
        repeat (3) @(posedge clk);
    end endtask
    reg [31:0] rq;
    task rd(input [9:0] a); begin
        @(negedge clk); ar = a; arv = 1;
        @(posedge clk); while (!arr) @(posedge clk);
        @(negedge clk); arv = 0;
        @(posedge clk); while (!rv) @(posedge clk);
        rq = rdat;
        repeat (2) @(posedge clk);
    end endtask
    // ---- 記録 ----
    integer fb, fz, fs, fr, fg, nob = 0, nzb = 0, i, k, c_now;
    always @(posedge clk) if (ct_v) begin $fwrite(fb, "%0d %0d\n", nob, ct_u); nob = nob + 1; end
    always @(posedge clk) if (dut.zv) begin
        if (`IMP_A != 0) begin
            $fwrite(fz, "%0d", nzb);
            for (k = 0; k < 64; k = k + 1) if ($signed(dut.z[18*k +: 18]) != 0) $fwrite(fz, " %0d %0d", k, $signed(dut.z[18*k +: 18]));
            $fwrite(fz, "\n");
        end
        nzb = nzb + 1;
    end
    // 飽和: 印から数えたブロックで c を数える
    integer sat [0:31];
    integer bo = -1;
    always @(posedge clk) if (ct_v) begin
        if (ct_u) bo = 0;
        if (bo >= 0) begin
            if (bo % `B_C == 0) for (k = 0; k < 32; k = k + 1) sat[k] = 0;
            for (k = 0; k < 32; k = k + 1) sat[k] = sat[k] + dut.cp_clip[2*k +: 2];
            if (bo % `B_C == `B_C - 1) begin
                $fwrite(fs, "%0d", bo / `B_C);
                for (k = 0; k < 32; k = k + 1) $fwrite(fs, " %0d", sat[k]);
                $fwrite(fs, "\n");
            end
            bo = bo + 1;
        end
    end
    integer nrec = 0;
    always @(posedge clk) if (r_v && r_r) begin $fwrite(fr, "%0d %0d %h\n", r_l, r_u, r_d); if (r_l) nrec = nrec + 1; end
    task wait_rec(input integer n); begin while (nrec < n) @(posedge clk); repeat (20) @(posedge clk); end endtask
    // ---- 細かい側に流す ch ----
    integer fc [0:7], fk [0:7], ft [0:7], fnb [0:7];
    integer fi, b, nbeat;
    task feed(input integer c, input integer kq, input integer nt, input integer nb); integer bb, ii; begin
        nbeat = (nt + nb) * 256;                             // 1 フレーム = 8192 サンプル = 256 拍（32 サンプル / 拍）
        bb = 0;
        while (bb < nbeat) begin
            @(negedge clk);
            f_v = 1;
            for (ii = 0; ii < 32; ii = ii + 1) f_d[16*ii +: 16] = {$random(seed)} % 65536 & 16'h1F1F;
            f_u = {c[15:0], kq[4:0], (bb < nt * 256) ? 1'b1 : 1'b0};
            f_l = (bb == nbeat - 1);
            @(posedge clk); if (f_r) bb = bb + 1;
        end
        @(negedge clk); f_v = 0; f_l = 0;
    end endtask
    initial begin
        fb = $fopen(`OUT_BLK, "w"); fz = $fopen(`OUT_Z, "w"); fs = $fopen(`OUT_SAT, "w"); fr = $fopen(`OUT_REC, "w"); fg = $fopen(`OUT_REG, "w");
        repeat (10) @(posedge clk); @(negedge clk); aresetn = 1;
        repeat (10) @(posedge clk);
        wr(10'h010, `NDUMP);
        wr(10'h02C, 32'h0000_CF01);
        wr(10'h084, 32'd1);
        for (k = 0; k < 32; k = k + 1) wr(10'h100 + 4 * k, (k == 0) ? 262143 : 40000 + 2000 * k);
`ifdef DIRECT
        wr(10'h008, 32'd1);
`else
        wr(10'h008, 32'd4);
`endif
        // 区切りが全部済むまで（入口と出口）
        while (Tc < `START_AT + `BASE * `NDUMP + 400) @(posedge clk);
`ifdef FEED
        `FEED_LIST
`endif
        repeat (50) @(posedge clk);
        for (i = 0; i <= 34; i = i + 1) begin rd(4 * i); $fwrite(fg, "%0d %0d\n", 4 * i, rq); end
        rd(10'h3D0); $fwrite(fg, "%0d %0d\n", 976, rq);
        $fwrite(fg, "%0d %0d\n", 9999, dut.n_run);
        $display("done blocks_out %0d z_blocks %0d", nob, nzb);
        $fclose(fb); $fclose(fz); $fclose(fs); $fclose(fr); $fclose(fg);
        $finish;
    end
endmodule
`default_nettype wire
