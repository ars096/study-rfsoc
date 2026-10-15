// SPDX-License-Identifier: BSD-3-Clause
//
// tb_wide_core — wide_core（流れのブロック × 2・FFT_N・ARM_WRST / ARM_RUN・DUMP_H・SPEC のレコード）の sim（proj023 手順 2c-3）
//
// 入力:  $(OUT)/stim.hex（sim/check_wide.py gen。ループして流す）
// 出力:  $(OUT)/meta.txt（tb_wide_spec と同じ形 ＋ レジスタの読み）/ $(OUT)/lanes.txt（IP の出口）/
//        $(OUT)/recs.txt  SPEC のレコード: 1 行 = 1 語「r 語番号 16 進 64 bit」、レコードの終わりに「end tuser」
// 判定:  python3 sim/check_wide.py core $(OUT)
//
// PS がすることを AXI4-Lite で: FFT_N（コアの 0x80 → fftn_we）・S0（0x100）・SHIFT・N_ACC・N_DUMP・CFG_ID・REC_CTRL = ALL を書き、
// ARM_WRST（流れ 0 の CTRL [13]）→ time_core の発火（go_in）→ ARM_RUN（流れ 0・1）→ 発火。レコードを N_DUMP × 流れの数だけ受けたら、
// レジスタ（SID・PARAM・NCH・FRAME_BEATS・S0_CUR・DUMP_*・FFT_N）を読む。
// -DLB・-DS00・-DS01・-DSHIFT・-DNACC・-DGF（tb_wide_spec と同じ）。-DSTALL: 出口の tready をときどき落とす（rec_fr の FIFO を試す）。
// -DTEV: ダンプ 1 の入力の区間で tev_in[1] を 1 クロック立てる（DUMP_H）。-DW7_POSCTL（wide_core 側）: 語 7 の S0_CUR を入れない（陽性対照）

`timescale 1ns / 1ps

module tb_wide_core;
    localparam integer NSTIM = 6 * 2048;
    localparam integer T0    = 70001;
    localparam integer KF    = 777;
    localparam integer NDUMP = 2;

    reg clk = 1'b0;
    always #2 clk = ~clk;

    reg  [255:0] stim [0:NSTIM-1];
    initial $readmemh({`OUT, "/stim.hex"}, stim);
    reg  rstn = 1'b0;
    reg  [63:0] t = T0;
    integer n = 0;
    always @(posedge clk) begin t <= t + 64'd1; n <= n + 1; end
    wire [255:0] d = stim[n % NSTIM];

    wire [10:0]   coef_addr, coef_m, tw_addr, tw_k1;
    wire          coef_addr_v, coef_v;
    wire [1151:0] coef;
    wire [575:0]  tw;
    wide_coef_rom #(.COEF_FILE(`COEF)) u_crom (.clk(clk), .addr(coef_addr), .addr_v(coef_addr_v), .coef(coef), .m_out(coef_m), .v_out(coef_v));
    wide_tw_rom   #(.TW_FILE(`TWF))    u_trom (.clk(clk), .addr(tw_addr), .tw(tw), .k1_out(tw_k1));

    // AXI4-Lite
    reg  [10:0] awaddr = 0, araddr = 0;
    reg         awvalid = 0, wvalid = 0, arvalid = 0;
    reg  [31:0] wdata = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [1:0]  bresp, rresp;
    wire [31:0] rdata;
    reg         go = 1'b0;
    reg  [3:0]  tev = 4'd0;
    reg         fftn_we = 1'b0;
    reg  [7:0]  fftn_wd = 8'd13;
    wire [31:0] fftn_rd;
    wire [63:0] rec_d;
    wire        rec_v, rec_l, rec_u;
    wire [1:0]  rec_drop;
    reg         rec_r = 1'b1;
    wire [16*64-1:0] ip_d;
    wire [10:0] ip_k1;
    wire        ip_v;
    wide_core #(.SID_S(0), .REC_CORE(2), .K_F(KF), .ST_N(64), .GF_L2(`GF)) dut (
        .aclk(clk), .aresetn(rstn), .s_axis_tdata(d), .s_axis_tvalid(1'b1), .s_axis_tready(),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_wdata(wdata), .s_axi_wvalid(wvalid),
        .s_axi_wready(wready), .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rresp(rresp),
        .s_axi_rvalid(rvalid), .s_axi_rready(1'b1),
        .fftn_we(fftn_we), .fftn_wdata(fftn_wd), .fftn_rd(fftn_rd),
        .t_in(t), .go_in(go), .tev_in(tev),
        .coef_addr(coef_addr), .coef_addr_v(coef_addr_v), .coef_in(coef), .coef_m(coef_m),
        .tw_addr(tw_addr), .tw_in(tw), .tw_k1(tw_k1),
        .m_axis_rec_tdata(rec_d), .m_axis_rec_tvalid(rec_v), .m_axis_rec_tready(rec_r), .m_axis_rec_tlast(rec_l),
        .m_axis_rec_tuser(rec_u), .rec_drop(rec_drop),
        .dbg_ip_tdata(ip_d), .dbg_ip_k1(ip_k1), .dbg_ip_v(ip_v));

    task axw(input [10:0] a, input [31:0] v);
        begin
            @(posedge clk); awaddr <= a; wdata <= v; awvalid <= 1'b1; wvalid <= 1'b1;
            @(posedge clk); while (awready !== 1'b1) @(posedge clk);
            awvalid <= 1'b0; wvalid <= 1'b0;
            @(posedge clk); while (bvalid !== 1'b1) @(posedge clk);
        end
    endtask
    reg [31:0] rv;
    task axr(input [10:0] a);
        begin
            @(posedge clk); araddr <= a; arvalid <= 1'b1;
            @(posedge clk); while (arready !== 1'b1) @(posedge clk);
            arvalid <= 1'b0;
            @(posedge clk); while (rvalid !== 1'b1) @(posedge clk);
            rv = rdata;
        end
    endtask
    task fire;                                       // time_core の発火（1 クロック）
        begin @(posedge clk); go <= 1'b1; @(posedge clk); go <= 1'b0; end
    endtask

    // ---- IP の出口・レコードを記録 ----
    integer fl, fr, fip, p, nw, nrec;
    initial begin fip = -1; nw = 0; nrec = 0; end
    always @(posedge clk) begin
        if (ip_v) begin
            if (ip_k1 == 11'd0) fip = fip + 1;
            $fwrite(fl, "%0d %0d", fip, ip_k1);
            for (p = 0; p < 16; p = p + 1) $fwrite(fl, " %0d %0d", $signed(ip_d[64*p +: 26]), $signed(ip_d[64*p + 32 +: 26]));
            $fwrite(fl, "\n");
        end
        if (rec_v && rec_r) begin
            $fwrite(fr, "r %0d %016x\n", nw, rec_d);
            nw = nw + 1;
            if (rec_l) begin $fwrite(fr, "end %0d\n", rec_u); nw = 0; nrec = nrec + 1; end
        end
    end
`ifdef STALL
    integer sd = 7;
    always @(posedge clk) rec_r <= ($random(sd) % 16) != 0;    // 16 クロックに 1 回くらい止める（4 に 1 回では N_ACC 5 のダンプ 2 本を出し切れず、rec_fr が正しく late にした。2c-3 の 1 回目）
`endif

    integer fm, nexp, wcnt;
    reg [63:0] fa_run;
    initial begin
        fl = $fopen({`OUT, "/lanes.txt"}, "w");
        fr = $fopen({`OUT, "/recs.txt"}, "w");
        repeat (10) @(posedge clk);
        rstn <= 1'b1;
        repeat (200) @(posedge clk);
        // 設定
        @(posedge clk); fftn_we <= 1'b1; fftn_wd <= 8'd15 - `LB;
        @(posedge clk); fftn_we <= 1'b0;
        axw(11'h100, `S00);  axw(11'h500, `S01);
        axw(11'h014, `SHIFT); axw(11'h414, 4'd3);       // 流れ 1 の SHIFT は効かない（D-8）
        axw(11'h00C, `NACC); axw(11'h40C, `NACC);
        axw(11'h010, NDUMP); axw(11'h410, NDUMP);
        axw(11'h02C, 32'hC0F1); axw(11'h42C, 32'hC0F2);
        axw(11'h084, 1);     axw(11'h484, 1);           // REC_CTRL = ALL
        repeat (3 * 2048) @(posedge clk);
        axw(11'h008, 32'h2000);                          // ARM_WRST（流れ 0）
        repeat (50) @(posedge clk);
        fire;
        repeat (100) @(posedge clk);
        axw(11'h008, 32'h4); axw(11'h408, 32'h4);        // ARM_RUN（流れ 0・1）
        repeat (50) @(posedge clk);
        @(posedge clk); fa_run = dut.fa_now;             // 発火の 1 クロック前の fa（RUN は 2 クロック後に効くが、同じフレームの中）
        fire;
        nexp = NDUMP * ((`LB == 2) ? 1 : 2);
`ifdef TEV
        // ダンプ 1 の入力の区間の中で、時刻の健全性 [1] を 1 クロックだけ立てる（DUMP_H の [1] がダンプ 1 にだけ出るはず）
        while (dut.fa_now != dut.run_f0[0] + `NACC + 1) @(posedge clk);
        repeat (300) @(posedge clk);
        @(posedge clk); tev <= 4'b0010;
        @(posedge clk); tev <= 4'd0;
`endif
        wcnt = 0;                                        // 期待の数が来ないとき（陽性対照）は、ダンプが出揃うはずの時間 ＋ 余裕で打ち切る
        while (nrec < nexp && wcnt < (`NACC * NDUMP + 40) * 2048) begin @(posedge clk); wcnt = wcnt + 1; end
        repeat (20) @(posedge clk);
        fm = $fopen({`OUT, "/meta.txt"}, "w");
        $fwrite(fm, "LB_REQ %0d\nS00_REQ %0d\nS01_REQ %0d\nSHIFT_REQ %0d\n", `LB, `S00, `S01, `SHIFT);
        $fwrite(fm, "T0 %0d\nKF %0d\nLB %0d\nS00 %0d\nS01 %0d\nSHIFT %0d\nNACC %0d\nNDUMP %0d\nGF %0d\nf_first %0d\nfa_run %0d\nc_s0_0 %0d\nc_s0_1 %0d\n",
                T0, KF, dut.c_lb, `S00, `S01, dut.c_shift, `NACC, NDUMP, `GF, dut.u_spec.f_first, fa_run, dut.c_s0_0, dut.c_s0_1);
        axr(11'h018); $fwrite(fm, "flags %0d\n", rv);
        axr(11'h000); $fwrite(fm, "SID0 %0d\n", rv);   axr(11'h400); $fwrite(fm, "SID1 %0d\n", rv);
        axr(11'h004); $fwrite(fm, "PARAM0 %0d\n", rv); axr(11'h404); $fwrite(fm, "PARAM1 %0d\n", rv);
        axr(11'h020); $fwrite(fm, "NCH0 %0d\n", rv);   axr(11'h420); $fwrite(fm, "NCH1 %0d\n", rv);
        axr(11'h024); $fwrite(fm, "FB %0d\n", rv);
        axr(11'h104); $fwrite(fm, "S0CUR0 %0d\n", rv); axr(11'h504); $fwrite(fm, "S0CUR1 %0d\n", rv);
        axr(11'h038); $fwrite(fm, "RUN_SHIFT %0d\n", rv);
        axr(11'h01C); $fwrite(fm, "SEQ0 %0d\n", rv);
        axr(11'h03C); $fwrite(fm, "DUMP_K0 %0d\n", rv);
        axr(11'h040); $fwrite(fm, "DUMP_F0_0 %0d\n", rv);
        axr(11'h050); $fwrite(fm, "DUMP_T0_LO %0d\n", rv); axr(11'h054); $fwrite(fm, "DUMP_T0_HI %0d\n", rv);
        axr(11'h058); $fwrite(fm, "DUMP_H0 %0d\n", rv);
        axr(11'h05C); $fwrite(fm, "DUMP_CFG0 %0d\n", rv); axr(11'h45C); $fwrite(fm, "DUMP_CFG1 %0d\n", rv);
        axr(11'h034); $fwrite(fm, "WRST_CFG %0d\n", rv);
        axr(11'h068); $fwrite(fm, "RUN_F0_0 %0d\n", rv);
        axr(11'h088); $fwrite(fm, "REC_LATE0 %0d\n", rv); axr(11'h488); $fwrite(fm, "REC_LATE1 %0d\n", rv);
        $fwrite(fm, "FFTN %0d\nnrec %0d\n", fftn_rd, nrec);
`ifdef TEV
        $fwrite(fm, "TEV_K 1\n");
`endif
        $fclose(fm); $fclose(fl); $fclose(fr);
        $display("tb_wide_core: レコード %0d 個・flags %02x", nrec, dut.flags);
        $finish;
    end
    initial begin
        #(4 * 450000);
        $display("tb_wide_core: 時間切れ（レコード %0d 個）", nrec);
        $finish;
    end
endmodule
