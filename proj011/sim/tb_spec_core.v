// SPDX-License-Identifier: BSD-3-Clause
//
// tb_spec_core — spec_core を lane_fft のモデルと繋ぎ、AXI4-Lite から動かして結果を書き出す
//
// 入力:  $(OUT)/stim.hex        1 行 = 1 ビート（256 bit、下位が古いサンプル）。sim/check.py gen が作る
// 出力:  $(OUT)/lanes.txt       レーン FFT の出力（frame k1 re0 im0 … re15 im15）。bit 単位の照合用
//        $(OUT)/dump_<名前>.txt レジスタ・スナップショット・スペクトル
// 判定は sim/check.py が行う（ここでは書き出すだけ）。
//
// 試験:
//   t1  N_ACC = 1 / N_DUMP = 1   スナップショットの FFT とダンプが 1 対 1
//   t2  N_ACC = 3 / N_DUMP = 2   2 つ目のダンプ（k = 1）を読む。3 フレームの和
//   t3  N_ACC = 2 / N_DUMP = 0   止めるまで回し、途中で STOP。SEQ が止まること
// どの試験の後も FLAGS = 0 であること（check.py が見る）。

`timescale 1ns / 1ps

module tb_spec_core;
    parameter integer NBEAT = 8 * 512;     // stim.hex の行数（ループして流す）

    reg clk = 1'b0;
    always #2 clk = ~clk;                  // 周期は何でもよい（すべて同期）
    reg aresetn = 1'b0;

    reg  [255:0] stim [0:NBEAT-1];
    reg  [255:0] s_tdata;
    reg          s_tvalid;
    integer      sp;

    reg  [15:0] awaddr, araddr;
    reg         awvalid, wvalid, bready, arvalid, rready;
    reg  [31:0] wdata;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [1:0]  bresp, rresp;
    wire [31:0] rdata;

    spec_core #(.N_ACC_DEFAULT(50000), .SHIFT_DEFAULT(4)) dut (
        .aclk(clk), .aresetn(aresetn),
        .s_axis_tdata(s_tdata), .s_axis_tvalid(s_tvalid), .s_axis_tready(),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready)
    );

    // ---- ADC の流し込み（リセット解除から途切れなく。ループする）----
    // 実機のギアボックスと同じく **backpressure を見ない**。IP が受け始める前のビートは捨てられる。
    always @(posedge clk) begin
        if (!aresetn) begin
            sp <= 0; s_tvalid <= 1'b0; s_tdata <= 256'd0;
        end else begin
            s_tvalid <= 1'b1;
            s_tdata  <= stim[sp];
            sp       <= (sp + 1) % NBEAT;
        end
    end

    // ---- レーン FFT の出力を記録（bit 単位の照合用）----
    integer fl, lf, lp;
    reg [47:0] ld;
    always @(posedge clk) begin
        if (aresetn && dut.ln_m_tvalid[0]) begin
            // フレームの番号は spec_core の出力側の数え fout に、SRST の回数を 100000 倍して足したもの（rev4）。
            // SRST で fout は 0 に戻るので、回ごとに別の番号にする。途中で切られたフレームは埋まらないので check.py が捨てる
            $fwrite(fl, "%0d %0d", dut.sr_n * 100000 + dut.fout, dut.ln_m_tuser[8:0]);
            for (lp = 0; lp < 16; lp = lp + 1) begin
                ld = dut.ln_m_tdata[48*lp +: 48];
                $fwrite(fl, " %0d %0d", $signed(ld[23:0]), $signed(ld[47:24]));
            end
            $fwrite(fl, "\n");
            if (dut.ln_m_tuser[8:0] == 9'd511) lf = lf + 1;
        end
    end

    // ---- AXI4-Lite ----
    task axi_wr(input [15:0] a, input [31:0] d);
        begin
            @(posedge clk);
            awaddr <= a; wdata <= d; awvalid <= 1'b1; wvalid <= 1'b1; bready <= 1'b1;
            @(posedge clk);
            while (!(awready && wready)) @(posedge clk);
            awvalid <= 1'b0; wvalid <= 1'b0;
            while (!bvalid) @(posedge clk);
            @(posedge clk);
            bready <= 1'b0;
        end
    endtask

    task axi_rd(input [15:0] a, output [31:0] d);
        begin
            @(posedge clk);
            araddr <= a; arvalid <= 1'b1; rready <= 1'b1;
            @(posedge clk);
            while (!arready) @(posedge clk);
            arvalid <= 1'b0;
            while (!rvalid) @(posedge clk);
            d = rdata;
            @(posedge clk);
            rready <= 1'b0;
        end
    endtask

    reg [31:0] v, lo, hi, seq0;
    integer i, fo, guard;
    reg [8*64-1:0] path;

    task wait_seq(input [31:0] target);
        begin
            guard = 0;
            axi_rd(16'h001C, v);
            while (v < target) begin
                repeat (200) @(posedge clk);
                axi_rd(16'h001C, v);
                guard = guard + 1;
                if (guard > 2000) begin
                    $display("FAIL: SEQ が %0d に届かない（%0d のまま）", target, v);
                    $finish;
                end
            end
        end
    endtask

    task dump(input [8*16-1:0] name);
        begin
            $sformat(path, "%0s/dump_%0s.txt", `OUT, name);
            fo = $fopen(path, "w");
            for (i = 0; i < 31; i = i + 1) begin
                axi_rd(i * 4, v);
                $fwrite(fo, "reg %0d %0d\n", i * 4, v);
            end
            for (i = 0; i < 4096; i = i + 1) begin
                axi_rd(16'h4000 + i * 4, v);
                $fwrite(fo, "snap %0d %0d\n", i, v);
            end
            for (i = 0; i < 4096; i = i + 1) begin
                axi_rd(16'h8000 + i * 8, lo);
                axi_rd(16'h8000 + i * 8 + 4, hi);
                $fwrite(fo, "spec %0d %0d %0d\n", i, hi, lo);
            end
            axi_rd(16'h001C, v);
            $fwrite(fo, "seq_after %0d\n", v);
            $fclose(fo);
            $display("  wrote %0s", path);
        end
    endtask

    initial begin
        $readmemh({`OUT, "/stim.hex"}, stim);
        fl = $fopen({`OUT, "/lanes.txt"}, "w");
        lf = 0;
        awvalid = 0; wvalid = 0; bready = 0; arvalid = 0; rready = 0;
        awaddr = 0; araddr = 0; wdata = 0;
        repeat (10) @(posedge clk);
        aresetn = 1'b1;

        // 流れ始めるまで待ち、立ち上がりの隙間で立ったフラグを消す
        repeat (3000) @(posedge clk);
        axi_rd(16'h0000, v);
        $display("ID = %08h", v);
        axi_wr(16'h0008, 32'h100);
        axi_wr(16'h0014, `SHIFT);

        // ---- t1 ----
        $display("t1: N_ACC = 1 / N_DUMP = 1");
        axi_rd(16'h001C, seq0);
        axi_wr(16'h000C, 1);
        axi_wr(16'h0010, 1);
        axi_wr(16'h0008, 1);
        wait_seq(seq0 + 1);
        repeat (3000) @(posedge clk);     // 1 回で止まることを確かめるため少し待つ
        dump("t1");

        // ---- t2 ----
        $display("t2: N_ACC = 3 / N_DUMP = 2");
        axi_rd(16'h001C, seq0);
        axi_wr(16'h000C, 3);
        axi_wr(16'h0010, 2);
        axi_wr(16'h0008, 1);
        wait_seq(seq0 + 2);
        repeat (3000) @(posedge clk);
        dump("t2");

        // ---- t3 ----
        $display("t3: N_ACC = 2 / N_DUMP = 0 → STOP");
        axi_rd(16'h001C, seq0);
        axi_wr(16'h000C, 2);
        axi_wr(16'h0010, 0);
        axi_wr(16'h0008, 1);
        wait_seq(seq0 + 3);
        axi_wr(16'h0008, 2);
        repeat (6000) @(posedge clk);
        dump("t3");

        // ---- t4（rev4）: 起動のやり直しの後も同じように動く ----
        $display("t4: SRST（D = 7 / E = 3）→ N_ACC = 1 / N_DUMP = 1");
        axi_wr(16'h0070, 7);
        axi_wr(16'h0074, 3);
        axi_wr(16'h0008, 32'h400);
        repeat (3000) @(posedge clk);
        axi_rd(16'h001C, seq0);
        axi_wr(16'h000C, 1);
        axi_wr(16'h0010, 1);
        axi_wr(16'h0008, 1);
        wait_seq(seq0 + 1);
        repeat (3000) @(posedge clk);
        dump("t4");

        $fclose(fl);
        $display("done");
        $finish;
    end
endmodule
