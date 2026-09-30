// SPDX-License-Identifier: BSD-3-Clause
// proj014 — wspec_core の単体の sim。z.txt（1 行 1 サンプル「re im」）を流し、RUN を打ってダンプを全部読む
//   +NACC= +NDUMP= +SHIFT= +GAP=<0: 途切れなし（W = 256 相当）/ n: 平均 n クロックに 1 個> +IN= +DIR=
// 出力: DIR/fft.txt（FFT のモデルの出力「k re im」）/ DIR/dumps.txt（「# k f0 n sat bank snap_f」＋ 4096 行）/
//       DIR/snaps.txt（ダンプごとのスナップショット 4096 行「re im」）/ DIR/meta.txt（run_f0 と FLAGS）
`timescale 1ns / 1ps
module tb_wspec;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg zv = 0;
    reg signed [17:0] zr = 0, zi = 0;
    reg run = 0, stop = 0, clr = 0;
    reg [31:0] nacc = 1, ndump = 1;
    reg [3:0]  shift = 4;
    wire [47:0] fin, fout, run_f0, rd_f0, snap_f0, snap_f1;
    wire sched, acc_on, rd_bank;
    wire [31:0] seq, rd_k, rd_n, rd_sat;
    wire [7:0] flags;
    wire [31:0] stall_cnt, rdy0;
    reg        rbk = 0, sbk = 0;
    reg [11:0] rch = 0, sa = 0;
    wire [63:0] rdat;
    wire [35:0] sdat;
    wspec_core dut (.clk(clk), .rst(rst), .z_valid(zv), .z_re(zr), .z_im(zi),
        .cmd_run(run), .cmd_stop(stop), .cmd_clr(clr), .r_nacc(nacc), .r_ndump(ndump), .r_shift(shift),
        .fin(fin), .fout(fout), .run_f0(run_f0), .sched(sched), .acc_on(acc_on),
        .seq(seq), .rd_k(rd_k), .rd_n(rd_n), .rd_sat(rd_sat), .rd_f0(rd_f0), .rd_bank(rd_bank),
        .snap_f0(snap_f0), .snap_f1(snap_f1), .flags(flags), .stall_cnt(stall_cnt), .rdy0(rdy0),
        .rd_bk(rbk), .rd_ch(rch), .rd_data(rdat), .sn_bk(sbk), .sn_a(sa), .sn_data(sdat));

    integer fi, ff, fd, fs, fm, r, a0, a1, gap, seed, nd, i, done;
    reg [8*256-1:0] fin_s, dir;
    reg [31:0] seq_seen;
    initial begin
        if (!$value$plusargs("NACC=%d", nacc)) nacc = 2;
        if (!$value$plusargs("NDUMP=%d", ndump)) ndump = 4;
        if (!$value$plusargs("SHIFT=%d", shift)) shift = 4;
        if (!$value$plusargs("GAP=%d", gap)) gap = 0;
        if (!$value$plusargs("IN=%s", fin_s)) fin_s = "z.txt";
        if (!$value$plusargs("DIR=%s", dir)) dir = ".";
        seed = 3;
        fi = $fopen(fin_s, "r");
        ff = $fopen({dir, "/fft.txt"}, "w");
        fd = $fopen({dir, "/dumps.txt"}, "w");
        fs = $fopen({dir, "/snaps.txt"}, "w");
        fm = $fopen({dir, "/meta.txt"}, "w");
        repeat (4) @(posedge clk);
        rst <= 0;
    end
    // 入力の流し込み
    always @(posedge clk) begin
        if (rst) zv <= 0;
        else if (gap == 0 || ($random(seed) % gap) == 0) begin
            r = $fscanf(fi, "%d %d\n", a0, a1);
            if (r == 2) begin zr <= a0; zi <= a1; zv <= 1; end
            else zv <= 0;
        end else zv <= 0;
    end
    // FFT の出力を記録
    always @(posedge clk) if (dut.m_tv) $fwrite(ff, "%0d %0d %0d\n", dut.m_tu[11:0], $signed(dut.m_td[30:0]), $signed(dut.m_td[62:32]));
    // RUN（3 フレーム溜まった後）とダンプの読み出し
    initial begin
        nd = 0; done = 0;
        wait (!rst);
        wait (fin == 3);
        @(posedge clk); run <= 1; @(posedge clk); run <= 0;
        @(posedge clk);
        $fwrite(fm, "run_f0 %0d\n", run_f0);
        seq_seen = seq;
        while (nd < ndump) begin
            @(posedge clk);
            if (seq != seq_seen) begin
                seq_seen = seq;
                $fwrite(fd, "# %0d %0d %0d %0d %0d %0d %0d\n", seq, rd_k, rd_f0, rd_n, rd_sat, rd_bank, rd_bank ? snap_f1 : snap_f0);
                rbk <= rd_bank; sbk <= rd_bank;
                // 1 クロックに 1 語（番地を毎クロック出し、2 クロック後の値を拾う）。スナップショットを先に:
                // 次の次のダンプのスナップショットが同じ面に書かれ始めるまでに読む（commit から N − 2 フレーム以内）
                for (i = 0; i < 4096 + 2; i = i + 1) begin
                    if (i < 4096) sa <= i;
                    @(posedge clk);
                    if (i >= 2) $fwrite(fs, "%0d %0d\n", $signed(sdat[17:0]), $signed(sdat[35:18]));
                end
                for (i = 0; i < 4096 + 2; i = i + 1) begin
                    if (i < 4096) rch <= i;
                    @(posedge clk);
                    if (i >= 2) $fwrite(fd, "%0d\n", rdat);
                end
                nd = nd + 1;
            end
        end
        $fwrite(fm, "flags %0d\n", flags);
        $fwrite(fm, "fin %0d fout %0d\n", fin, fout);
        $fwrite(fm, "stall %0d\n", stall_cnt);
        $fwrite(fm, "rdy0 %0d\n", rdy0);
        $display("wspec: NACC=%0d NDUMP=%0d SHIFT=%0d GAP=%0d ダンプ %0d 個、FLAGS %02x、fin %0d fout %0d、待たされた %0d クロック、tready まで %0d クロック", nacc, ndump, shift, gap, nd, flags, fin, fout, stall_cnt, rdy0);
        $fclose(ff); $fclose(fd); $fclose(fs); $fclose(fm);
        $finish;
    end
endmodule
