// SPDX-License-Identifier: BSD-3-Clause
// proj015 — win_core を 1 ADC × 4 窓（NW = 4）で AXI 越しに（make sim-win4）
//   窓ごとに別の k・d・NS、WRST を入力の流れの途中の別の時刻に打つ（窓 3 は入力の前）。入力はときどき途切れる。
//   窓 1 だけ RUN（N_ACC 1・N_DUMP 1）し、SNAP_SEL = 1 のスナップショットを AXI で全部読む。窓 0 のスナップショットの範囲は 0 のはず
//   +IN=x.hex +NSAMP= +DIR= +CFG=<cfg.txt: 1 行 1 窓「k dphi ns wrst のビート」>
//   出力: DIR/z_w<g>.txt（窓 g の z を出た順に）/ DIR/snap.txt / DIR/meta.txt
`timescale 1ns / 1ps
module tb_win4;
    localparam integer NW = 4;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg aresetn = 0;
    reg  [255:0] tdata = 0;
    reg          tvalid = 0;
    reg  [19:0] awaddr = 0, araddr = 0;
    reg         awvalid = 0, wvalid = 0, bready = 1, arvalid = 0, rready = 1;
    reg  [31:0] wdata = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [31:0] rdata;
    wire [1:0]  bresp, rresp;
    wire        tready;
    win_core #(.NW(NW), .N_ACC_DEFAULT(2)) dut (
        .aclk(clk), .aresetn(aresetn), .s_axis_tdata(tdata), .s_axis_tvalid(tvalid), .s_axis_tready(tready),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready));

    task axw(input [19:0] a, input [31:0] d);
        begin
            @(posedge clk); awaddr <= a; wdata <= d; awvalid <= 1; wvalid <= 1;
            @(posedge clk); while (!(awready && wready)) @(posedge clk);
            awvalid <= 0; wvalid <= 0;
            @(posedge clk); while (!bvalid) @(posedge clk);
        end
    endtask
    reg [31:0] rv;
    task axr(input [19:0] a);
        begin
            @(posedge clk); araddr <= a; arvalid <= 1;
            @(posedge clk); while (!arready) @(posedge clk);
            arvalid <= 0;
            while (!rvalid) @(posedge clk);
            rv = rdata;
        end
    endtask

    // ---- 入力の流れ（pause = 0 の間。ときどき途切れる）----
    reg [15:0] mem [0:(1<<22)-1];
    integer nsamp, nbeat, b, l, seed;
    reg pause = 1;
    always @(posedge clk) begin
        if (!pause && b < nbeat && !(($random(seed) & 7) == 0)) begin
            for (l = 0; l < 16; l = l + 1) tdata[16*l +: 16] <= mem[16*b + l];
            tvalid <= 1;
            b = b + 1;
        end else begin
            tvalid <= 0;
            tdata  <= {16{16'hDEAD}};
        end
    end

    // ---- z を窓ごとに。**窓の WRST（w_rst が立った）ごとに「# W」の行を書く**（リセットの後は既定の設定で回っているので、
    //      照合は最後の「# W」の後だけ）----
    integer fz0, fz1, fz2, fz3;
    reg [3:0] wr_prev = 4'b1111;
    always @(posedge clk) begin
        if (dut.g_w[0].zv) $fwrite(fz0, "%0d %0d\n", dut.g_w[0].zr, dut.g_w[0].zi);
        if (dut.g_w[1].zv) $fwrite(fz1, "%0d %0d\n", dut.g_w[1].zr, dut.g_w[1].zi);
        if (dut.g_w[2].zv) $fwrite(fz2, "%0d %0d\n", dut.g_w[2].zr, dut.g_w[2].zi);
        if (dut.g_w[3].zv) $fwrite(fz3, "%0d %0d\n", dut.g_w[3].zr, dut.g_w[3].zi);
        // 「# W」は z の後に書く: w_rst が立ったクロックに出ている z は、その前のクロックに（リセットの前の設定で）作られたもの
        // （rev2 で 1 個だけ「# W」の後に紛れ、窓 0・1・2 が模型より 1 個多かった）
        if (dut.g_w[0].w_rst && !wr_prev[0]) $fwrite(fz0, "# W\n");
        if (dut.g_w[1].w_rst && !wr_prev[1]) $fwrite(fz1, "# W\n");
        if (dut.g_w[2].w_rst && !wr_prev[2]) $fwrite(fz2, "# W\n");
        if (dut.g_w[3].w_rst && !wr_prev[3]) $fwrite(fz3, "# W\n");
        wr_prev <= {dut.g_w[3].w_rst, dut.g_w[2].w_rst, dut.g_w[1].w_rst, dut.g_w[0].w_rst};
    end

    reg [8*256-1:0] fin_s, dir, cfg_s;
    integer fm, fs, fc, ft, r, g, i, tpn;
    reg [31:0] lo, hi, f0w;
    integer ck [0:NW-1], cn [0:NW-1], cb [0:NW-1];
    reg [31:0] cd [0:NW-1];
    reg [NW-1:0] done_w;
    reg [31:0] seq0;
    initial begin
        if (!$value$plusargs("NSAMP=%d", nsamp)) nsamp = 16 * 65536;
        if (!$value$plusargs("IN=%s", fin_s)) fin_s = "x.hex";
        if (!$value$plusargs("DIR=%s", dir)) dir = ".";
        if (!$value$plusargs("CFG=%s", cfg_s)) cfg_s = "cfg.txt";
        $readmemh(fin_s, mem, 0, nsamp - 1);
        fc = $fopen(cfg_s, "r");
        for (g = 0; g < NW; g = g + 1) r = $fscanf(fc, "%d %d %d %d\n", ck[g], cd[g], cn[g], cb[g]);
        $fclose(fc);
        nbeat = nsamp / 16; b = 0; seed = 9;
        fz0 = $fopen({dir, "/z_w0.txt"}, "w"); fz1 = $fopen({dir, "/z_w1.txt"}, "w");
        fz2 = $fopen({dir, "/z_w2.txt"}, "w"); fz3 = $fopen({dir, "/z_w3.txt"}, "w");
        fm = $fopen({dir, "/meta.txt"}, "w");
        fs = $fopen({dir, "/snap.txt"}, "w");
        repeat (8) @(posedge clk);
        aresetn <= 1;
        repeat (8) @(posedge clk);
        // ADC の共通
        axr(20'h80000); $fwrite(fm, "id_a %0d\n", rv);
        axr(20'h80004); $fwrite(fm, "nw %0d\n", rv);
        axw(20'h80008, 1);
        axw(20'h80100, 8);                        // total power: TP_N 8 フレーム（16 µs）。RUN で取り込む
        axr(20'h80008); $fwrite(fm, "snap_sel %0d\n", rv);
        for (g = 0; g < NW; g = g + 1) begin
            axr(20'h20000 * g + 20'h00000); $fwrite(fm, "id%0d %0d\n", g, rv);
            axr(20'h20000 * g + 20'h00090); $fwrite(fm, "widx%0d %0d\n", g, rv);
            axw(20'h20000 * g + 20'h00058, ck[g]); axw(20'h20000 * g + 20'h0005C, cd[g]); axw(20'h20000 * g + 20'h00060, cn[g]);
        end
        axw(20'h20000 * 1 + 20'h0000C, 1); axw(20'h20000 * 1 + 20'h00010, 1); axw(20'h20000 * 1 + 20'h00014, 4);   // 窓 1: N_ACC 1・N_DUMP 1・SHIFT 4
        // WRST: cb[g] = 0 の窓は入力の前に、ほかは b ≧ cb[g] になったとき
        done_w = 0;
        for (g = 0; g < NW; g = g + 1) if (cb[g] == 0) begin axw(20'h20000 * g + 20'h00008, 32'h1000); done_w[g] = 1'b1; end
        repeat (100) @(posedge clk);
        pause <= 0;
        while (done_w != {NW{1'b1}}) begin
            @(posedge clk);
            for (g = 0; g < NW; g = g + 1) if (!done_w[g] && b >= cb[g]) begin
                $fwrite(fm, "wrst%0d_b %0d\n", g, b);
                axw(20'h20000 * g + 20'h00008, 32'h1000); done_w[g] = 1'b1;
            end
        end
        axw(20'h80010, 1);                        // TP_RUN
        axr(20'h8010C); $fwrite(fm, "tp_f0 %0d\n", rv);
        // 窓 1: 3 フレーム溜まってから RUN → ダンプ 1 個 → スナップショットを読む
        rv = 0;
        while (rv < 3) begin repeat (2000) @(posedge clk); axr(20'h20000 + 20'h00020); end
        axr(20'h20000 + 20'h0001C); seq0 = rv;
        axw(20'h20000 + 20'h00008, 32'h1);
        while (rv == seq0) begin repeat (2000) @(posedge clk); axr(20'h20000 + 20'h0001C); end
        axr(20'h20000 + 20'h00038); $fwrite(fm, "dump_f0 %0d\n", rv);
        axr(20'h20000 + 20'h00044); $fwrite(fm, "snap_f %0d\n", rv);
        for (i = 0; i < 4096; i = i + 1) begin
            axr(20'h20000 + 20'h08000 + 8 * i); lo = rv;
            axr(20'h20000 + 20'h08000 + 8 * i + 4);
            $fwrite(fs, "%0d %0d\n", $signed(lo), $signed(rv));
        end
        axr(20'h00000 + 20'h08000 + 8 * 5); $fwrite(fm, "snap_w0 %0d\n", rv);      // 選ばれていない窓は 0
        axr(20'h00000 + 20'h08000 + 8 * 5 + 4); $fwrite(fm, "snap_w0i %0d\n", rv);
        // 入力の終わりまで
        while (b < nbeat) @(posedge clk);
        repeat (3000) @(posedge clk);
        for (g = 0; g < NW; g = g + 1) begin
            axr(20'h20000 * g + 20'h0008C); $fwrite(fm, "wstart%0d %0d\n", g, rv);
            axr(20'h20000 * g + 20'h00018); $fwrite(fm, "flags%0d %0d\n", g, rv);
            axr(20'h20000 * g + 20'h00064); $fwrite(fm, "wcur%0d %0d\n", g, rv);
            axr(20'h20000 * g + 20'h00088); $fwrite(fm, "ovr%0d %0d\n", g, rv);
        end
        axr(20'hA0000); $fwrite(fm, "bad_sel %0d\n", rv);                           // 窓 5 は無い → DEAD_BEEF
        axr(20'h80108); $fwrite(fm, "tp_wp %0d\n", rv); tpn = (rv > 512) ? 512 : rv;
        axr(20'h80104); $fwrite(fm, "tp_neff %0d\n", rv);
        axr(20'h80014); $fwrite(fm, "tfin %0d\n", rv);
        ft = $fopen({dir, "/tp.txt"}, "w");
        for (i = 0; i < tpn; i = i + 1) begin          // 書かれた個だけ（書いていない番地は sim で x）
            axr(20'h82000 + 16 * i);     lo = rv;
            axr(20'h82000 + 16 * i + 4); hi = rv;
            axr(20'h82000 + 16 * i + 8); f0w = rv;
            axr(20'h82000 + 16 * i + 12);
            $fwrite(ft, "%0d %0d %0d %0d\n", lo, hi, f0w, rv);
        end
        $fclose(ft);
        $fclose(fz0); $fclose(fz1); $fclose(fz2); $fclose(fz3); $fclose(fm); $fclose(fs);
        $display("tb_win4: 入力 %0d ビート、終わり", b);
        $finish;
    end
endmodule
