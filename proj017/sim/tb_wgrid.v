// SPDX-License-Identifier: BSD-3-Clause
// proj017 S-4 — wspec_core の F0 の格子（F0 = (⌊fin / M⌋ + 2)·M）で、幅の違う窓のダンプの区切りがサンプルの時刻で揃うこと
//
// 幅 NS = 1..6 の wspec_core を 6 個並べる。時刻の格子を sim では G = 2^17 ビート（G_L2 = 17）に縮める
// （NS 1..6 の L = 2^(11+NS) = 4096 … 131072 ビート、M = G / L = 32・16・8・4・2・1）。どの窓も **同じ WSTART = S0** から
// z を 2^(NS−1) クロックに 1 個流し（窓の出力のレート）、窓ごとの遅れ D(NS)（proj016 の sim-wdelay の値を丸めた 58〜748 ビート）
// だけ遅れて wspec に入る。フレーム f の最初の z が入るのは S0 + D(NS) + f·L。
// RUN は 3 回、全部の窓に同じクロックで入れる:
//   R1: S0 + 2G − 70（実機の形: WRST・RUN の START_AT を G の倍数に置くと、RUN − WSTART = 整数 × G − (WRST の長さ ＋ 数クロック)）
//   R2: S0 + 5G + G/2（格子の真ん中。フレームの位相は窓ごとにばらばら）
//   R3: S0 + 10G + 12345
// 判定（「wgrid: NG」を数える）:
//   1. 各窓の RUN_F0 = (⌊fin_RUN / M⌋ + 2)·M（tb が RUN のクロックの fin から独立に計算）
//   2. **RUN_F0·L が 6 窓で同じ**（同じ格子の点）
//   3. ダンプ k（N_ACC = M なので N·L = G）の DUMP_T − D(NS) − S0 = (g0 + k)·G が 6 窓で一致（k = 0, 1）。DUMP_K = k
// 陽性対照（-DWSPEC_NOGRID: 格子に寄せない = 従来の F0 = fin + 2）→ 2・3 が落ちるはず（make sim-wgrid-p）
`timescale 1ns / 1ps
module tb_wgrid;
    localparam integer GL2 = 17;
    localparam [63:0]  G   = 64'd1 << GL2;
    localparam [63:0]  S0  = 64'd1000;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [63:0] T = 0;
    always @(posedge clk) T <= T + 1;
    reg run = 0;
    integer ng = 0;

    genvar g;
    generate for (g = 0; g < 6; g = g + 1) begin : w
        localparam integer NS = g + 1;
        localparam integer DL = (g == 0) ? 58 : (g == 1) ? 87 : (g == 2) ? 136 : (g == 3) ? 229 : (g == 4) ? 408 : 748;
        localparam [63:0]  L  = 64'd4096 << g;
        localparam integer M  = 1 << (5 - g);
        reg zv = 0;
        reg signed [17:0] zr = 0, zi = 0;
        integer seed = 3 + g;
        // z は S0 + DL から 2^(NS−1) クロックに 1 個（このレジスタを抜けた次のクロックに wspec に入るので、1 クロック前に立てる）
        always @(posedge clk) begin
            if (T + 1 >= S0 + DL && ((T + 1 - S0 - DL) % (64'd1 << g)) == 0) begin
                zv <= 1; zr <= $random(seed) % 3000; zi <= $random(seed) % 3000;
            end else zv <= 0;
        end
        wire [47:0] fin, fout, run_f0, rd_f0, snap_f0, snap_f1;
        wire sched, acc_on, rd_bank;
        wire [31:0] seq, rd_k, rd_n, rd_sat, stall_cnt, rdy0;
        wire [7:0] flags;
        wire [63:0] rdat, rd_t, run_t;
        wire [15:0] rd_h;
        wire [35:0] sdat;
        wspec_core #(.G_L2(GL2)) dut (.clk(clk), .rst(rst), .z_valid(zv), .z_re(zr), .z_im(zi),
            .cmd_run(run), .cmd_stop(1'b0), .cmd_clr(1'b0), .r_nacc(M), .r_ndump(32'd2), .r_shift(4'd7), .w_ns(NS[3:0]),
            .fin(fin), .fout(fout), .run_f0(run_f0), .sched(sched), .acc_on(acc_on),
            .seq(seq), .rd_k(rd_k), .rd_n(rd_n), .rd_sat(rd_sat), .rd_f0(rd_f0), .rd_bank(rd_bank),
            .snap_f0(snap_f0), .snap_f1(snap_f1), .flags(flags), .stall_cnt(stall_cnt), .rdy0(rdy0),
            .rd_bk(1'b0), .rd_ch(12'd0), .rd_data(rdat), .sn_bk(1'b0), .sn_a(12'd0), .sn_data(sdat),
            .t_now(T), .ev(8'd0), .rd_t(rd_t), .rd_h(rd_h), .run_t(run_t));
        defparam dut.u_fft.LAT = 200;
        // RUN のクロックの fin・閉じたダンプの記録
        reg [47:0] fin_run;
        reg [63:0] dt [0:1];
        reg [31:0] dk [0:1];
        integer nd = 0;
        reg [31:0] seq_q = 0;
        always @(posedge clk) begin
            if (run) begin fin_run <= fin; nd = 0; end
            seq_q <= seq;
            if (seq != seq_q && nd < 2) begin dt[nd] = rd_t; dk[nd] = rd_k; nd = nd + 1; end
        end
    end endgenerate

    // 窓ごとの値を配列に（generate の外から読む）
    reg [63:0] f0L [0:5], ex [0:5], dtn [0:5][0:1];
    reg [47:0] f0w [0:5], finr [0:5];
    integer    ndw [0:5];
    reg [31:0] dkw [0:5][0:1];
    task grab; begin
        f0w[0] = w[0].run_f0; f0w[1] = w[1].run_f0; f0w[2] = w[2].run_f0; f0w[3] = w[3].run_f0; f0w[4] = w[4].run_f0; f0w[5] = w[5].run_f0;
        finr[0] = w[0].fin_run; finr[1] = w[1].fin_run; finr[2] = w[2].fin_run; finr[3] = w[3].fin_run; finr[4] = w[4].fin_run; finr[5] = w[5].fin_run;
        ndw[0] = w[0].nd; ndw[1] = w[1].nd; ndw[2] = w[2].nd; ndw[3] = w[3].nd; ndw[4] = w[4].nd; ndw[5] = w[5].nd;
        dtn[0][0] = w[0].dt[0] - 58;  dtn[0][1] = w[0].dt[1] - 58;
        dtn[1][0] = w[1].dt[0] - 87;  dtn[1][1] = w[1].dt[1] - 87;
        dtn[2][0] = w[2].dt[0] - 136; dtn[2][1] = w[2].dt[1] - 136;
        dtn[3][0] = w[3].dt[0] - 229; dtn[3][1] = w[3].dt[1] - 229;
        dtn[4][0] = w[4].dt[0] - 408; dtn[4][1] = w[4].dt[1] - 408;
        dtn[5][0] = w[5].dt[0] - 748; dtn[5][1] = w[5].dt[1] - 748;
        dkw[0][0] = w[0].dk[0]; dkw[0][1] = w[0].dk[1]; dkw[1][0] = w[1].dk[0]; dkw[1][1] = w[1].dk[1];
        dkw[2][0] = w[2].dk[0]; dkw[2][1] = w[2].dk[1]; dkw[3][0] = w[3].dk[0]; dkw[3][1] = w[3].dk[1];
        dkw[4][0] = w[4].dk[0]; dkw[4][1] = w[4].dk[1]; dkw[5][0] = w[5].dk[0]; dkw[5][1] = w[5].dk[1];
    end endtask

    integer i, k, r;
    reg [63:0] t_r, g0;
    reg [63:0] runs [0:2];
    initial begin
        runs[0] = S0 + 2 * G - 70;
        runs[1] = S0 + 5 * G + G / 2;
        runs[2] = S0 + 10 * G + 12345;
        repeat (4) @(posedge clk);
        rst <= 0;
        for (r = 0; r < 3; r = r + 1) begin
            t_r = runs[r];
            while (T + 1 < t_r) @(posedge clk);
            run <= 1; @(posedge clk); run <= 0;           // wspec はこのクロック（T = t_r）に cmd_run を見る
            repeat (4) @(posedge clk);
            grab;
            for (i = 0; i < 6; i = i + 1) begin
                // 1. tb が RUN のクロックの fin から計算した F0
                ex[i] = ((finr[i] >> (5 - i)) + 2) << (5 - i);
`ifndef WSPEC_NOGRID
                if (f0w[i] !== ex[i]) begin $display("wgrid: NG R%0d NS %0d: RUN_F0 %0d（期待 %0d、RUN の fin %0d、M %0d）", r + 1, i + 1, f0w[i], ex[i], finr[i], 1 << (5 - i)); ng = ng + 1; end
`endif
                f0L[i] = f0w[i] * (64'd4096 << i);
            end
            for (i = 1; i < 6; i = i + 1)
                if (f0L[i] !== f0L[0]) begin $display("wgrid: NG R%0d: RUN_F0·L が窓で違う（NS 1 %0d / NS %0d %0d）", r + 1, f0L[0], i + 1, f0L[i]); ng = ng + 1; end
            g0 = f0L[0] / G;
            $display("wgrid: R%0d（RUN − S0 = %0d = %0d·G + %0d）: RUN_F0 = %0d %0d %0d %0d %0d %0d / F0·L = %0d %0d %0d %0d %0d %0d（G 単位で %0d）",
                     r + 1, t_r - S0, (t_r - S0) / G, (t_r - S0) % G, f0w[0], f0w[1], f0w[2], f0w[3], f0w[4], f0w[5],
                     f0L[0] / G, f0L[1] / G, f0L[2] / G, f0L[3] / G, f0L[4] / G, f0L[5] / G, g0);
            // 3. ダンプ 0・1 の DUMP_T（最長の窓のダンプが 2 つ閉じるまで待つ。FFT の遅れ ＋ 余裕）
            while (T < S0 + (g0 + 2) * G + 6000 + 2 * 4096) @(posedge clk);
            repeat (64) @(posedge clk);
            grab;
            for (i = 0; i < 6; i = i + 1) begin
                if (ndw[i] < 2) begin $display("wgrid: NG R%0d NS %0d: ダンプが %0d 個しか閉じない", r + 1, i + 1, ndw[i]); ng = ng + 1; end
                for (k = 0; k < 2; k = k + 1) begin
                    if (dkw[i][k] !== k) begin $display("wgrid: NG R%0d NS %0d: DUMP_K %0d（期待 %0d）", r + 1, i + 1, dkw[i][k], k); ng = ng + 1; end
                    if (dtn[i][k] !== dtn[0][k]) begin
                        $display("wgrid: NG R%0d ダンプ %0d: DUMP_T − D が窓で違う（NS 1 %0d / NS %0d %0d、差 %0d ビート）", r + 1, k,
                                 dtn[0][k], i + 1, dtn[i][k], $signed(dtn[i][k] - dtn[0][k])); ng = ng + 1; end
`ifndef WSPEC_NOGRID
                    if (dtn[i][k] !== S0 + (g0 + k) * G) begin
                        $display("wgrid: NG R%0d NS %0d ダンプ %0d: DUMP_T − D − S0 = %0d（期待 (g0 + k)·G = %0d）", r + 1, i + 1, k,
                                 dtn[i][k] - S0, (g0 + k) * G); ng = ng + 1; end
`endif
                end
            end
            $display("wgrid: R%0d: ダンプ 0・1 の DUMP_T − D(NS) − S0 = %0d・%0d（NS 1）… %0d・%0d（NS 6）", r + 1,
                     dtn[0][0] - S0, dtn[0][1] - S0, dtn[5][0] - S0, dtn[5][1] - S0);
        end
`ifdef WSPEC_NOGRID
        if (ng > 0) $display("wgrid: 結果: 全部通過（陽性対照が落ちるべきところで落ちた: NG %0d 件）", ng);
        else        $display("wgrid: 結果: 陽性対照が落ちなかった（見張りが効いていない）");
`else
        if (ng == 0) $display("wgrid: 結果: 全部通過");
        else         $display("wgrid: 結果: 失敗（%0d 件）", ng);
`endif
        $finish;
    end
endmodule
