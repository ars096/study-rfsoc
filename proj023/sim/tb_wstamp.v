// SPDX-License-Identifier: BSD-3-Clause
// proj016 — wspec_core ＋ dstamp の sim（S-T2: ダンプの開始のビートと健全性の語）
//   +NACC= +NDUMP= +GAP=<0: 毎クロック / n: 平均 n クロックに 1 個> +EVSEED=
//   FFT のモデルの遅れは -DFFT_LAT=（既定 200。実機の IP は 1〜2 フレーム。N = 1 で輪の深さを確かめるときは大きく）
// 判定（この tb の中）:
//   (a) ダンプ k の rd_t = その最初のフレーム（rd_f0）の最初の z を入れたクロックの T（tb が独立に数えた値）
//   (b) rd_f0 = RUN_F0 + k·N、rd_k = k（RUN を 2 回: 2 回目で k が 0 から）
//   (c) rd_h[7:0] = そのダンプの入力の区間 [頭(k), 頭(k+1)] に tb が入れた ev の OR（両端を含む）。rd_h[15:14] = 0
//   (d) RUN_T = RUN を入れたクロックの T
`timescale 1ns / 1ps
`ifndef FFT_LAT
`define FFT_LAT 200
`endif
module tb_wstamp;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg zv = 0;
    reg signed [17:0] zr = 0, zi = 0;
    reg run = 0, stop = 0, clr = 0;
    reg [31:0] nacc = 1, ndump = 1;
    reg [63:0] T = 0;
    reg [7:0]  ev = 0;
    wire [47:0] fin, fout, run_f0, rd_f0, snap_f0, snap_f1;
    wire sched, acc_on, rd_bank;
    wire [31:0] seq, rd_k, rd_n, rd_sat;
    wire [7:0] flags;
    wire [31:0] stall_cnt, rdy0;
    wire [63:0] rdat, rd_t, run_t;
    wire [15:0] rd_h;
    wire [35:0] sdat;
    wspec_core #(.G_L2(12)) dut (   // proj017: G_L2 12 = F0 の切り上げなし（従来の形）
       .clk(clk), .rst(rst), .z_valid(zv), .z_re(zr), .z_im(zi),
        .cmd_run(run), .cmd_stop(stop), .cmd_clr(clr), .r_nacc(nacc), .r_ndump(ndump), .r_shift(4'd7), .w_ns(4'd1),
        .fin(fin), .fout(fout), .run_f0(run_f0), .sched(sched), .acc_on(acc_on),
        .seq(seq), .rd_k(rd_k), .rd_n(rd_n), .rd_sat(rd_sat), .rd_f0(rd_f0), .rd_bank(rd_bank),
        .snap_f0(snap_f0), .snap_f1(snap_f1), .flags(flags), .stall_cnt(stall_cnt), .rdy0(rdy0),
        .rd_bk(1'b0), .rd_ch(12'd0), .rd_data(rdat), .sn_bk(1'b0), .sn_a(12'd0), .sn_data(sdat),
        .t_now(T), .ev(ev), .rd_t(rd_t), .rd_h(rd_h), .run_t(run_t));
    defparam dut.u_fft.LAT = `FFT_LAT;

    always @(posedge clk) T <= T + 1;
    integer gap, seed, evseed, ng, i, nz;
    // フレームの頭の z を入れたクロックの T（フレーム番号で引く）と、ev を入れたクロック（ビットごとに最大 4096 回）
    reg [63:0] t_fr [0:4095];
    reg [63:0] t_ev [0:7][0:4095];
    integer    n_ev [0:7];
    initial begin
        if (!$value$plusargs("NACC=%d", nacc)) nacc = 2;
        if (!$value$plusargs("NDUMP=%d", ndump)) ndump = 6;
        if (!$value$plusargs("GAP=%d", gap)) gap = 0;
        if (!$value$plusargs("EVSEED=%d", evseed)) evseed = 5;
        seed = 3; ng = 0; nz = 0;
        for (i = 0; i < 8; i = i + 1) n_ev[i] = 0;
        repeat (4) @(posedge clk);
        rst <= 0;
    end
    always @(posedge clk) begin
        if (rst) zv <= 0;
        else if (gap == 0 || ($random(seed) % gap) == 0) begin
            zr <= $random(seed) % 3000; zi <= $random(seed) % 3000; zv <= 1;
            if (nz % 4096 == 0) t_fr[nz / 4096] <= T + 1;    // この z はレジスタを抜けた次のクロックに wspec に入る
            nz = nz + 1;
        end else zv <= 0;
    end
    // ev: ビット 0〜6 はまれなパルス、ビット 7 はときどき長いレベル。入れたクロック（wspec が見るクロック = T + 1）を記録
    reg [7:0] ev_n;
    integer b;
    always @(posedge clk) begin
        ev_n = 8'd0;
        for (b = 0; b < 7; b = b + 1) if (($random(evseed) & 32'h1FFFF) == 0) ev_n[b] = 1'b1;
        if (T % 30000 > 27000) ev_n[7] = 1'b1;
        if (rst) ev_n = 8'd0;
        ev <= ev_n;
        for (b = 0; b < 7; b = b + 1) if (ev_n[b] && n_ev[b] < 4096) begin t_ev[b][n_ev[b]] = T + 1; n_ev[b] = n_ev[b] + 1; end
    end

    // ダンプの照合
    reg [63:0] t_run;
    reg [47:0] f0;
    integer k_exp, nd, r, e, hit, clean;
    reg [31:0] seq_seen;
    reg [63:0] lo, hi, tt;
    reg [7:0]  h_exp;
    task check_dump; begin
        if (rd_k !== k_exp) begin $display("wstamp: NG rd_k %0d（期待 %0d）", rd_k, k_exp); ng = ng + 1; end
        if (rd_f0 !== f0 + k_exp * nacc) begin $display("wstamp: NG rd_f0 %0d（期待 %0d）", rd_f0, f0 + k_exp * nacc); ng = ng + 1; end
        if (rd_t !== t_fr[rd_f0]) begin $display("wstamp: NG ダンプ %0d の rd_t %0d / 頭の z の T %0d", k_exp, rd_t, t_fr[rd_f0]); ng = ng + 1; end
        if (rd_h[15:14] !== 2'b00) begin $display("wstamp: NG ダンプ %0d の帳簿 H_OPEN/H_LOST %b", k_exp, rd_h[15:14]); ng = ng + 1; end
        lo = t_fr[rd_f0]; hi = t_fr[rd_f0 + nacc];
        h_exp = 8'd0;
        for (b = 0; b < 7; b = b + 1)
            for (e = 0; e < n_ev[b]; e = e + 1) if (t_ev[b][e] >= lo && t_ev[b][e] <= hi) h_exp[b] = 1'b1;
        // ビット 7（レベル）: wspec が見るクロック t に 1 ⇔ (t − 1) mod 30000 > 27000
        for (tt = lo; tt <= hi; tt = tt + 1) if ((tt - 1) % 30000 > 27000) h_exp[7] = 1'b1;
        if (rd_h[7:0] !== h_exp) begin $display("wstamp: NG ダンプ %0d の健全性 %b（期待 %b、区間 %0d..%0d）", k_exp, rd_h[7:0], h_exp, lo, hi); ng = ng + 1; end
        if (h_exp != 0) hit = hit + 1; else clean = clean + 1;
    end endtask
    initial begin
        nd = 0; hit = 0; clean = 0;
        wait (!rst);
        for (r = 0; r < 2; r = r + 1) begin
            wait (fin == 3 + r * 40);
            @(posedge clk); run <= 1; t_run = T + 1; @(posedge clk); run <= 0;
            @(posedge clk);
            f0 = run_f0;
            if (run_t !== t_run) begin $display("wstamp: NG RUN_T %0d（期待 %0d）", run_t, t_run); ng = ng + 1; end
            seq_seen = seq; k_exp = 0;
            while (k_exp < ndump) begin
                @(posedge clk);
                if (seq != seq_seen) begin
                    seq_seen = seq;
                    @(posedge clk);
                    check_dump;
                    k_exp = k_exp + 1; nd = nd + 1;
                end
            end
        end
        $display("wstamp: NACC=%0d NDUMP=%0d GAP=%0d FFT_LAT=%0d ダンプ %0d 個（ev の入ったダンプ %0d・入らないダンプ %0d）、FLAGS %02x", nacc, ndump, gap, `FFT_LAT, nd, hit, clean, flags);
        if (hit == 0 || clean == 0) begin $display("wstamp: NG ev の入ったダンプ %0d・入らないダンプ %0d（どちらかが 0 だと健全性の照合が片側だけ）", hit, clean); ng = ng + 1; end
        if (ng == 0) $display("wstamp: 結果: 全部通過");
        else         $display("wstamp: 結果: 失敗（%0d 件）", ng);
        $finish;
    end
endmodule
