// SPDX-License-Identifier: BSD-3-Clause
//
// tb_wide_spec — wide_spec（PFB → IP の行動模型 → 鎖 → 束ね → 切り出しの積分器 → 帳簿）＋ 共有の ROM 2 つの sim（proj023 手順 2c-2、判定 A2・B・C）
//
// 入力:  $(OUT)/stim.hex（sim/check_wide.py gen が作る。ループして流す）
// 出力:  $(OUT)/meta.txt  T0・K_F・LB・S0・SHIFT・N_ACC・N_DUMP・GF_L2・f_first・run の時の fa・flags
//        $(OUT)/lanes.txt IP の出口「frame k1 re0 im0 … re15 im15」（frame は出口の通し番号 0 = PFB に入った最初のフレーム）
//        $(OUT)/dumps.txt ダンプごとに「dump s seq k f0 n sat plane」の行と、続いて 4096 行の「v」（読み出しの口で読んだ値）
// 判定:  python3 sim/check_wide.py spec $(OUT)
//
// 時刻 T は T0 から 1 クロックに 1。ビート n（0 から）は T = T0 + n と同じクロックに入れる（wide_spec が両方を 1 段受ける）。
// 流れ: rst → 口が開く（ST_N）→ WRST（LB・S0・SHIFT）→ RUN（流れ 0 と 1、同じクロック）→ ダンプが N_DUMP 個ずつ閉じるまで。
// ダンプが閉じる（commit）たびに、その流れの 4096 ch を読み出しの口で読む（N_ACC フレームの間に読み終える）。
// -DLB=・-DS00=・-DS01=・-DSHIFT=・-DNACC=・-DGF=（GF_L2）。-DPOSCTL_GRID: wide_spec の K_F を 1 ずらす（D-2 の陽性対照、C が落ちるべき）

`timescale 1ns / 1ps

module tb_wide_spec;
    localparam integer NSTIM = 6 * 2048;     // stim.hex の行数
    localparam integer T0    = 70001;
    localparam integer KF    = 777;
    localparam integer NDUMP = 2;
`ifdef POSCTL_GRID
    localparam integer KF_DUT = KF + 1;
`else
    localparam integer KF_DUT = KF;
`endif

    reg clk = 1'b0;
    always #2 clk = ~clk;

    reg  [255:0] stim [0:NSTIM-1];
    initial $readmemh({`OUT, "/stim.hex"}, stim);

    reg          rst = 1'b1;
    reg  [63:0]  t   = T0;
    integer      n   = 0;
    wire [255:0] d   = stim[n % NSTIM];
    always @(posedge clk) begin t <= t + 64'd1; n <= n + 1; end

    wire [10:0]   coef_addr, coef_m, tw_addr, tw_k1;
    wire          coef_addr_v, coef_v;
    wire [1151:0] coef;
    wire [575:0]  tw;
    wide_coef_rom #(.COEF_FILE(`COEF)) u_crom (.clk(clk), .addr(coef_addr), .addr_v(coef_addr_v), .coef(coef), .m_out(coef_m), .v_out(coef_v));
    wide_tw_rom   #(.TW_FILE(`TWF))    u_trom (.clk(clk), .addr(tw_addr), .tw(tw), .k1_out(tw_k1));

    reg         cmd_wrst = 1'b0;
    reg  [1:0]  cmd_run = 2'b00, cmd_stop = 2'b00;
    reg         rd_s = 1'b0;
    reg  [11:0] rd_i = 12'd0;
    wire [63:0] rd_d;
    wire [1:0]  commit, rd_plane, c_lb, c_en, st_sched, st_acc;
    wire [13:0] c_s0_0, c_s0_1;
    wire [3:0]  c_shift;
    wire        go;
    wire [47:0] fa_now, fo, df0_0, df0_1;
    wire [7:0]  flags;
    wire [31:0] seq0, seq1, dk0, dk1, dn0, dn1, dsat0, dsat1;
    wire [16*64-1:0] ip_d;
    wire [10:0] ip_k1;
    wire        ip_v;
    wide_spec #(.K_F(KF_DUT), .ST_N(64), .GF_L2(`GF)) dut (
        .clk(clk), .rst(rst), .s_tdata(d), .s_tvalid(1'b1), .t_in(t),
        .coef_addr(coef_addr), .coef_addr_v(coef_addr_v), .coef_in(coef), .coef_m(coef_m),
        .tw_addr(tw_addr), .tw_in(tw), .tw_k1(tw_k1),
        .cmd_wrst(cmd_wrst), .w_lb(2'd`LB), .w_s0_0(14'd`S00), .w_s0_1(14'd`S01), .w_shift(4'd`SHIFT),
        .cmd_run(cmd_run), .cmd_stop(cmd_stop), .r_nacc0(`NACC), .r_nacc1(`NACC), .r_ndump0(NDUMP), .r_ndump1(NDUMP),
        .flags_clr(1'b0),
        .c_lb(c_lb), .c_s0_0(c_s0_0), .c_s0_1(c_s0_1), .c_shift(c_shift), .c_en(c_en), .go(go), .fa_now(fa_now), .fo(fo),
        .flags(flags), .st_sched(st_sched), .st_acc(st_acc),
        .commit(commit), .seq0(seq0), .seq1(seq1), .dk0(dk0), .dk1(dk1), .df0_0(df0_0), .df0_1(df0_1),
        .dn0(dn0), .dn1(dn1), .dsat0(dsat0), .dsat1(dsat1), .rd_plane(rd_plane),
        .rd_s(rd_s), .rd_i(rd_i), .rd_d(rd_d),
        .dbg_ip_tdata(ip_d), .dbg_ip_k1(ip_k1), .dbg_ip_v(ip_v));

    // ---- IP の出口を記録（frame は出口の通し番号）----
    integer fl, fip, p;
    initial fip = -1;
    always @(posedge clk) begin
        if (ip_v) begin
            if (ip_k1 == 11'd0) fip = fip + 1;
            $fwrite(fl, "%0d %0d", fip, ip_k1);
            for (p = 0; p < 16; p = p + 1) $fwrite(fl, " %0d %0d", $signed(ip_d[64*p +: 26]), $signed(ip_d[64*p + 32 +: 26]));
            $fwrite(fl, "\n");
        end
    end

    // ---- ダンプの読み出し（commit ごと。流れ 0 → 1 の順に待ち行列）----
    integer fd, i, ndone, pend0, pend1;
    reg [63:0] fa_run;
    task read_dump(input integer s);
        integer k;
        begin
            $fwrite(fd, "dump %0d %0d %0d %0d %0d %0d %0d\n", s, s ? seq1 : seq0, s ? dk1 : dk0, s ? df0_1 : df0_0,
                    s ? dn1 : dn0, s ? dsat1 : dsat0, rd_plane[s]);
            // 番地を出したエッジから 4 エッジ目に rd_d が変わり、tb はエッジの直後（NBA の前）に読むので、5 回後に読める
            for (k = 0; k < 4096 + 5; k = k + 1) begin
                @(posedge clk);
                rd_s <= s; rd_i <= k;
                if (k >= 5) $fwrite(fd, "v %0d\n", rd_d);
            end
        end
    endtask
    always @(posedge clk) begin
        if (commit[0]) pend0 = pend0 + 1;
        if (commit[1]) pend1 = pend1 + 1;
    end

    integer fm;
    initial begin
        pend0 = 0; pend1 = 0; ndone = 0;
        fl = $fopen({`OUT, "/lanes.txt"}, "w");
        fd = $fopen({`OUT, "/dumps.txt"}, "w");
        repeat (10) @(posedge clk);
        rst <= 1'b0;
        wait (go);
        repeat (3 * 2048) @(posedge clk);
        @(posedge clk); cmd_wrst <= 1'b1;
        @(posedge clk); cmd_wrst <= 1'b0;
        repeat (100) @(posedge clk);
        @(posedge clk); cmd_run <= {c_en[1], 1'b1}; fa_run = fa_now;
        @(posedge clk); cmd_run <= 2'b00;
        while (ndone < NDUMP * (c_en[1] ? 2 : 1)) begin
            @(posedge clk);
            if (pend0 > 0) begin pend0 = pend0 - 1; read_dump(0); ndone = ndone + 1; end
            else if (pend1 > 0) begin pend1 = pend1 - 1; read_dump(1); ndone = ndone + 1; end
        end
        repeat (10) @(posedge clk);
        fm = $fopen({`OUT, "/meta.txt"}, "w");
        $fwrite(fm, "T0 %0d\nKF %0d\nLB %0d\nS00 %0d\nS01 %0d\nSHIFT %0d\nNACC %0d\nNDUMP %0d\nGF %0d\nf_first %0d\nfa_run %0d\nflags %0d\nc_s0_0 %0d\nc_s0_1 %0d\nen %0d\n",
                T0, KF, c_lb, `S00, `S01, c_shift, `NACC, NDUMP, `GF, dut.f_first, fa_run, flags, c_s0_0, c_s0_1, c_en);
        $fclose(fm); $fclose(fl); $fclose(fd);
        $display("tb_wide_spec: ダンプ %0d 個・flags %02x・f_first %0d・fo %0d", ndone, flags, dut.f_first, fo);
        $finish;
    end
    initial begin
        #(4 * 400000);
        $display("tb_wide_spec: 時間切れ（ダンプ %0d 個）", ndone);
        $finish;
    end
endmodule
