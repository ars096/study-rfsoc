// SPDX-License-Identifier: BSD-3-Clause
//
// tb_wide_s45 — wide_s45_core（コアの共通 core_cmn ＋ wide_core ＋ RAW ＋ レコードの束ね）の sim（proj023 手順 3）。tb_wide_core を
// コアの 16 bit の番地（流れ 0・1 = 0x4000・0x4400、RAW = 0x4800、FFT_N = 0x0080）に写し、RAW の SNAP のレコードとコアの共通の読みを足したもの
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

module tb_wide_s45;
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
    reg  [15:0] awaddr = 0, araddr = 0;
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
    wire [1:0] full_sel;
    wide_s45_core #(.CORE_PORT(2), .K_F(KF), .ST_N(64), .GF_L2(`GF), .RAW(1), .RAW_N_ACC_DEFAULT(20)) dut (
        .aclk(clk), .aresetn(rstn), .s_axis_tdata(d), .s_axis_tvalid(1'b1), .s_axis_tready(),
        .s_axis_full_tdata(d), .s_axis_full_tvalid(1'b1), .s_axis_full_tready(), .full_sel(full_sel),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_wdata(wdata),
        .s_axi_wstrb(4'hF), .s_axi_wvalid(wvalid), .s_axi_wready(wready), .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rresp(rresp),
        .s_axi_rvalid(rvalid), .s_axi_rready(1'b1),
        .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(32'h1234_5678), .adc_stat(32'h8765_4321),
        .t_in(t), .go_in(go), .tev_in(tev),
        .coef_addr(coef_addr), .coef_addr_v(coef_addr_v), .coef_in(coef), .coef_m(coef_m),
        .tw_addr(tw_addr), .tw_in(tw), .tw_k1(tw_k1),
        .m_axis_rec_tdata(rec_d), .m_axis_rec_tvalid(rec_v), .m_axis_rec_tready(rec_r), .m_axis_rec_tlast(rec_l),
        .m_axis_rec_tuser(rec_u), .rec_drop(rec_drop));
    assign ip_d = dut.u_wide.dbg_ip_tdata;
    assign ip_k1 = dut.u_wide.dbg_ip_k1;
    assign ip_v = dut.u_wide.dbg_ip_v;

    // 手渡しは `!== 1'b1` で待つ（`!x` だと z・x を「準備よし」と読んで通る。ビルド 5 回目の arready の駆動漏れを sim が見逃した）
    task axw(input [15:0] a, input [31:0] v);
        begin
            @(posedge clk); awaddr <= a; wdata <= v; awvalid <= 1'b1; wvalid <= 1'b1;
            @(posedge clk); while (awready !== 1'b1) @(posedge clk);
            awvalid <= 1'b0; wvalid <= 1'b0;
            @(posedge clk); while (bvalid !== 1'b1) @(posedge clk);
        end
    endtask
    reg [31:0] rv;
    task axr(input [15:0] a);
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
        axw(16'h0080, 8'd15 - `LB);                      // コアの FFT_N（core_cmn → wide_core）
        axw(16'h480C, 20); axw(16'h4810, 2); axw(16'h4884, 1);   // RAW: N_ACC 20 フレーム・N_DUMP 2・REC_CTRL = ALL
        axw(16'h4100, `S00);  axw(16'h4500, `S01);
        axw(16'h4014, `SHIFT); axw(16'h4414, 4'd3);       // 流れ 1 の SHIFT は効かない（D-8）
        axw(16'h400C, `NACC); axw(16'h440C, `NACC);
        axw(16'h4010, NDUMP); axw(16'h4410, NDUMP);
        axw(16'h402C, 32'hC0F1); axw(16'h442C, 32'hC0F2);
        axw(16'h4084, 1);     axw(16'h4484, 1);           // REC_CTRL = ALL
        repeat (3 * 2048) @(posedge clk);
        axw(16'h4008, 32'h2000);                          // ARM_WRST（流れ 0）
        repeat (50) @(posedge clk);
        fire;
        repeat (100) @(posedge clk);
        axw(16'h4008, 32'h4); axw(16'h4408, 32'h4); axw(16'h4808, 32'h4);   // ARM_RUN（流れ 0・1 と RAW）
        repeat (50) @(posedge clk);
        @(posedge clk); fa_run = dut.u_wide.fa_now;             // 発火の 1 クロック前の fa（RUN は 2 クロック後に効くが、同じフレームの中）
        fire;
        nexp = NDUMP * ((`LB == 2) ? 1 : 2) + NDUMP;      // SPEC ＋ RAW の SNAP
`ifdef TEV
        // ダンプ 1 の入力の区間の中で、時刻の健全性 [1] を 1 クロックだけ立てる（DUMP_H の [1] がダンプ 1 にだけ出るはず）
        while (dut.u_wide.fa_now != dut.u_wide.run_f0[0] + `NACC + 1) @(posedge clk);
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
                T0, KF, dut.u_wide.c_lb, `S00, `S01, dut.u_wide.c_shift, `NACC, NDUMP, `GF, dut.u_wide.u_spec.f_first, fa_run, dut.u_wide.c_s0_0, dut.u_wide.c_s0_1);
        axr(16'h4018); $fwrite(fm, "flags %0d\n", rv);
        axr(16'h4000); $fwrite(fm, "SID0 %0d\n", rv);   axr(16'h4400); $fwrite(fm, "SID1 %0d\n", rv);
        axr(16'h4004); $fwrite(fm, "PARAM0 %0d\n", rv); axr(16'h4404); $fwrite(fm, "PARAM1 %0d\n", rv);
        axr(16'h4020); $fwrite(fm, "NCH0 %0d\n", rv);   axr(16'h4420); $fwrite(fm, "NCH1 %0d\n", rv);
        axr(16'h4024); $fwrite(fm, "FB %0d\n", rv);
        axr(16'h4104); $fwrite(fm, "S0CUR0 %0d\n", rv); axr(16'h4504); $fwrite(fm, "S0CUR1 %0d\n", rv);
        axr(16'h4038); $fwrite(fm, "RUN_SHIFT %0d\n", rv);
        axr(16'h401C); $fwrite(fm, "SEQ0 %0d\n", rv);
        axr(16'h403C); $fwrite(fm, "DUMP_K0 %0d\n", rv);
        axr(16'h4040); $fwrite(fm, "DUMP_F0_0 %0d\n", rv);
        axr(16'h4050); $fwrite(fm, "DUMP_T0_LO %0d\n", rv); axr(16'h4054); $fwrite(fm, "DUMP_T0_HI %0d\n", rv);
        axr(16'h4058); $fwrite(fm, "DUMP_H0 %0d\n", rv);
        axr(16'h405C); $fwrite(fm, "DUMP_CFG0 %0d\n", rv); axr(16'h445C); $fwrite(fm, "DUMP_CFG1 %0d\n", rv);
        axr(16'h4034); $fwrite(fm, "WRST_CFG %0d\n", rv);
        axr(16'h4068); $fwrite(fm, "RUN_F0_0 %0d\n", rv);
        axr(16'h4088); $fwrite(fm, "REC_LATE0 %0d\n", rv); axr(16'h4488); $fwrite(fm, "REC_LATE1 %0d\n", rv);
        axr(16'h0080); $fwrite(fm, "FFTN %0d\nnrec %0d\n", rv, nrec);
        axr(16'h0000); $fwrite(fm, "IF_ID %0d\n", rv);
        axr(16'h0004); $fwrite(fm, "PROJ %0d\n", rv);
        axr(16'h0008); $fwrite(fm, "NSTREAM %0d\n", rv);
        axr(16'h0018); $fwrite(fm, "CORE_PORT %0d\n", rv);
        axr(16'h0034); $fwrite(fm, "GB_STAT %0d\n", rv);
        axr(16'h4800); $fwrite(fm, "SID2 %0d\n", rv);
        axr(16'h4C00); $fwrite(fm, "NOBLK %0d\n", rv);
`ifdef TEV
        $fwrite(fm, "TEV_K 1\n");
`endif
        $fclose(fm); $fclose(fl); $fclose(fr);
        $display("tb_wide_s45: レコード %0d 個・flags %02x", nrec, dut.u_wide.flags);
        $finish;
    end
    initial begin
        #(4 * 450000);
        $display("tb_wide_s45: 時間切れ（レコード %0d 個）", nrec);
        $finish;
    end
endmodule
