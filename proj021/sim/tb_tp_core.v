// SPDX-License-Identifier: BSD-3-Clause
//
// tb_tp_core — tp_core 単体の試験台（proj013 rev1）。spec_core の入力側の数え（m_in / fin）だけを真似て流し、
// 最後にレジスタとリングバッファを全部書き出す。判定は sim/check_tp.py（ここでは書き出すだけ）。
//
// 入力:  $(OUT)/tp_valid.hex  1 行 = 1 クロックの valid（0/1）。行数 NCYC
//        $(OUT)/tp_beat.hex   1 行 = 1 ビート（valid のクロックだけ順に消費。256 bit、下位が古いサンプル）
//        $(OUT)/tp_cmd.hex    1 行 = {クロック 32 bit, 種類 8 bit, 値 32 bit}。種類 1 = TP_N の書き込み / 2 = RUN。末尾は種類 0
// 出力:  $(OUT)/tp_out.txt    REG 名 値 / SLOT i 語0 語1 語2 語3 / RUNF0 k 値（RUN ごとの fin + 2 の実際の値）
// TP_POSCTL を定義すると tp_core が陽性対照の形（隙間を考えない F0 の判定）になり、check_tp.py は落ちるはず。

`timescale 1ns / 1ps

module tb_tp_core;
    parameter integer NCYC  = 1;
    parameter integer NBEAT = 1;
    parameter integer TPN   = 3;

    reg clk = 1'b0;
    always #2 clk = ~clk;
    reg rst = 1'b1;

    reg  [0:0]   vmem [0:NCYC-1];
    reg  [255:0] bmem [0:NBEAT-1];
    reg  [71:0]  cmem [0:63];

    reg          in_acc;
    reg  [255:0] tdata;
    reg  [8:0]   m_in;
    reg  [47:0]  fin;
    reg          cmd_run, wr_en;
    reg  [31:0]  wr_data;
    reg  [15:0]  rd_addr;
    wire [31:0]  rd_ring, rd_reg;

    // proj021 2-2b: -DTP_REC で REC = 1（TP のレコード）。出口の tready はランダムに落とし、STALL0 から STALL_LEN クロックは止める
    reg  [63:0]  t_now = 64'd0;
    reg          m_tready = 1'b1;
    wire [63:0]  m_tdata;
    wire         m_tvalid, m_tlast, m_tuser, rec_drop;
`ifdef TP_REC
    tp_core #(.TPN_DEFAULT(TPN), .REC(1), .REC_CORE(8'd3), .REC_EN_DEFAULT(1)) dut (
`else
    tp_core #(.TPN_DEFAULT(TPN)) dut (
`endif
        .clk(clk), .rst(rst), .in_acc(in_acc), .m_in(m_in), .fin(fin), .tdata(tdata),
        .cmd_run(cmd_run), .wr_en(wr_en), .wr_addr(6'h00), .wr_data(wr_data),
        .rd_addr(rd_addr), .rd_ring(rd_ring), .rd_reg(rd_reg),
        .t_now(t_now), .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast), .m_tuser(m_tuser),
        .rec_drop(rec_drop));
`ifdef TP_REC
    integer fr, nw, ndrop = 0, seed = 7;
    always @(posedge clk) begin
        if (m_tvalid && m_tready) begin
            if (nw == 0) $fwrite(fr, "R");
            $fwrite(fr, " %h", m_tdata);
            nw = nw + 1;
            if (m_tlast) begin $fwrite(fr, "\n"); nw = 0; end
        end
        if (rec_drop) ndrop = ndrop + 1;
    end
`endif

    integer cyc, bp, cp, fo, k, w, nrun;
    reg [31:0] word [0:3];

    // spec_core の入力側と同じ数え: in_acc のビートで m_in が進み、m_in = 511 のビートで fin が進む
    always @(posedge clk) begin
        if (rst) begin
            m_in <= 9'd0; fin <= 48'd0;
        end else if (in_acc) begin
            m_in <= m_in + 9'd1;
            if (m_in == 9'd511) fin <= fin + 48'd1;
        end
    end

    task rd(input [15:0] a, output [31:0] v);
        begin
            @(negedge clk) rd_addr = a;
            repeat (4) @(negedge clk);
            v = rd_addr[13] ? rd_ring : rd_reg;
        end
    endtask

    reg [31:0] v;
    initial begin
        $readmemh({`OUT, "/tp_valid.hex"}, vmem);
        $readmemh({`OUT, "/tp_beat.hex"}, bmem);
        $readmemh({`OUT, "/tp_cmd.hex"}, cmem);
        fo = $fopen({`OUT, "/tp_out.txt"}, "w");
`ifdef TP_REC
        fr = $fopen({`OUT, "/tp_rec.txt"}, "w"); nw = 0;
`endif
        in_acc = 1'b0; tdata = 256'd0; cmd_run = 1'b0; wr_en = 1'b0; wr_data = 32'd0; rd_addr = 16'h0100;
        repeat (8) @(negedge clk);
        rst = 1'b0;
        bp = 0; cp = 0; nrun = 0;
        for (cyc = 0; cyc < NCYC; cyc = cyc + 1) begin
            // 入力は立ち下がりで変える（立ち上がりで DUT と数えが同時に見る）
            in_acc  = vmem[cyc][0];
            t_now   = cyc;
`ifdef TP_REC
            m_tready = (cyc >= `STALL0 && cyc < `STALL0 + `STALL_LEN) ? 1'b0 : (($random(seed) & 3) != 0);
`endif
            tdata   = in_acc ? bmem[bp] : 256'd0;
            if (in_acc) bp = bp + 1;
            cmd_run = 1'b0; wr_en = 1'b0;
            if (cmem[cp][39:32] != 8'd0 && cmem[cp][71:40] == cyc) begin
                if (cmem[cp][39:32] == 8'd1) begin wr_en = 1'b1; wr_data = cmem[cp][31:0]; end
                if (cmem[cp][39:32] == 8'd2) begin
                    cmd_run = 1'b1;
                    $fdisplay(fo, "RUNF0 %0d %0d", nrun, fin + 2);
                    nrun = nrun + 1;
                end
                cp = cp + 1;
            end
            @(negedge clk);
        end
        in_acc = 1'b0; cmd_run = 1'b0; wr_en = 1'b0;
`ifdef TP_REC
        m_tready = 1'b1;
        repeat (2000) @(negedge clk);       // 溜めに残ったレコードを出し切る
`endif
        repeat (20) @(negedge clk);
        rd(16'h0100, v); $fdisplay(fo, "REG TP_N %0d", v);
        rd(16'h0104, v); $fdisplay(fo, "REG TP_NEFF %0d", v);
        rd(16'h0108, v); $fdisplay(fo, "REG TP_WP %0d", v);
        rd(16'h010C, v); $fdisplay(fo, "REG TP_F0_LO %0d", v);
        rd(16'h0110, v); $fdisplay(fo, "REG TP_F0_HI %0d", v);
        rd(16'h0114, v); $fdisplay(fo, "REG TP_PARAM %0d", v);
        rd(16'h0118, v); $fdisplay(fo, "REG TP_STAT %0d", v);
        rd(16'h011C, v); $fdisplay(fo, "REG TP_7 %0d", v);
        rd(16'h0120, v); $fdisplay(fo, "REG TP_8 %0d", v);
`ifdef TP_REC
        $fdisplay(fo, "RECDROP %0d", ndrop);
        $fclose(fr);
`endif
        for (k = 0; k < 512; k = k + 1) begin
            for (w = 0; w < 4; w = w + 1) begin
                rd(16'h2000 + 16 * k + 4 * w, v);
                word[w] = v;
            end
            $fdisplay(fo, "SLOT %0d %0d %0d %0d %0d", k, word[0], word[1], word[2], word[3]);
        end
        $fdisplay(fo, "BEATS %0d", bp);
        $fclose(fo);
        $finish;
    end
endmodule
