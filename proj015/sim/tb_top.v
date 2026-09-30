// SPDX-License-Identifier: BSD-3-Clause
// proj014 — win_core を AXI4-Lite 越しに動かす sim（端から端まで）。x.hex（1 行 16 bit）→ ギアボックスの出口の形で流す
//   +K= +DPHI= +NS= +NACC= +NDUMP= +SHIFT= +GAP=<0|1> +NSAMP= +IN= +DIR=
// ダンプが閉じたら**入力を止めて**（tvalid = 0。窓の経路は valid なビートだけで進むので値は変わらない）、
// レジスタ・スナップショット・スペクトルを AXI で全部読み、入力を再開する。
// 出力（tb_wspec と同じ形 ＋ z）: DIR/z.txt（ddc_core の出力）/ fft.txt / dumps.txt / snaps.txt / meta.txt
`timescale 1ns / 1ps
module tb_top;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg aresetn = 0;
    reg  [255:0] tdata = 0;
    reg          tvalid = 0;
    reg  [16:0] awaddr = 0, araddr = 0;
    reg         awvalid = 0, wvalid = 0, bready = 1, arvalid = 0, rready = 1;
    reg  [31:0] wdata = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [31:0] rdata;
    wire [1:0]  bresp, rresp;
    wire        tready;
    win_core #(.N_ACC_DEFAULT(2)) dut (
        .aclk(clk), .aresetn(aresetn), .s_axis_tdata(tdata), .s_axis_tvalid(tvalid), .s_axis_tready(tready),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready));

    task axw(input [16:0] a, input [31:0] d);
        begin
            @(posedge clk); awaddr <= a; wdata <= d; awvalid <= 1; wvalid <= 1;
            @(posedge clk); while (!(awready && wready)) @(posedge clk);
            awvalid <= 0; wvalid <= 0;
            @(posedge clk); while (!bvalid) @(posedge clk);
        end
    endtask
    reg [31:0] rv;
    task axr(input [16:0] a);
        begin
            @(posedge clk); araddr <= a; arvalid <= 1;
            @(posedge clk); while (!arready) @(posedge clk);
            arvalid <= 0;
            while (!rvalid) @(posedge clk);
            rv = rdata;
        end
    endtask

    reg [15:0] mem [0:(1<<22)-1];
    integer nsamp, nbeat, b, l, gap, seed, kk, nsv, na, ndm, shv;
    reg [31:0] dp;
    reg pause = 1;
    reg [8*256-1:0] fin_s, dir;
    integer fz, ff, fd, fs, fm, i, nd, s0, hi;
    integer rc;
    reg [31:0] rc_w;
    reg [31:0] seq_seen, dk, dn, df0, dsat, dbk, dsnf, lo;
    initial begin
        if (!$value$plusargs("K=%d", kk)) kk = 5;
        if (!$value$plusargs("DPHI=%d", dp)) dp = 0;
        if (!$value$plusargs("NS=%d", nsv)) nsv = 1;
        if (!$value$plusargs("NACC=%d", na)) na = 2;
        if (!$value$plusargs("NDUMP=%d", ndm)) ndm = 3;
        if (!$value$plusargs("SHIFT=%d", shv)) shv = 4;
        if (!$value$plusargs("GAP=%d", gap)) gap = 1;
        if (!$value$plusargs("NSAMP=%d", nsamp)) nsamp = 16 * 4096;
        if (!$value$plusargs("IN=%s", fin_s)) fin_s = "x.hex";
        if (!$value$plusargs("DIR=%s", dir)) dir = ".";
        $readmemh(fin_s, mem, 0, nsamp - 1);
        nbeat = nsamp / 16;
        seed = 5;
        fz = $fopen({dir, "/z.txt"}, "w");
        ff = $fopen({dir, "/fft.txt"}, "w");
        fd = $fopen({dir, "/dumps.txt"}, "w");
        fs = $fopen({dir, "/snaps.txt"}, "w");
        fm = $fopen({dir, "/meta.txt"}, "w");
        repeat (8) @(posedge clk);
        aresetn <= 1;
        repeat (8) @(posedge clk);
        axr(17'h00000);
        if (rv !== 32'h0015_0100) $display("tb_top: ID が違う %08x", rv);
        $fwrite(fm, "id %0d\n", rv);
        // proj015: WNS の 4 bit（7・8 = 4・2 MHz）と範囲外（9・0 → 1）、PARAM の G を読み返す（入力は止めたまま）
        for (rc = 0; rc < 4; rc = rc + 1) begin
            axw(17'h00060, (rc == 0) ? 7 : (rc == 1) ? 8 : (rc == 2) ? 9 : 0);
            axw(17'h00008, 32'h1000);             // WRST
            repeat (100) @(posedge clk);
            axr(17'h00064); rc_w = rv;
            axr(17'h00004);
            $fwrite(fm, "regchk%0d %0d %0d\n", rc, rc_w, rv);
        end
        axw(17'h00058, kk); axw(17'h0005C, dp); axw(17'h00060, nsv);
        axw(17'h0000C, na); axw(17'h00010, ndm); axw(17'h00014, shv);
        axw(17'h00008, 32'h1000);                 // WRST
        repeat (100) @(posedge clk);
        axr(17'h00064);
        $fwrite(fm, "wcur %0d\n", rv);
        pause <= 0;
        // 3 フレーム溜まるまで待つ（FIN を読む）
        rv = 0;
        while (rv < 3) begin repeat (2000) @(posedge clk); axr(17'h00020); end
        axw(17'h00008, 32'h1);                    // RUN
        axr(17'h00050); $fwrite(fm, "run_f0 %0d\n", rv);
        axr(17'h0001C); seq_seen = rv;
        nd = 0;
        while (nd < ndm) begin
            repeat (500) @(posedge clk);
            axr(17'h0001C);
            if (rv != seq_seen) begin
                pause <= 1;
                repeat (20) @(posedge clk);
                seq_seen = rv;
                axr(17'h00030); dk = rv;  axr(17'h00034); dn = rv;  axr(17'h00038); df0 = rv;
                axr(17'h00040); dsat = rv; axr(17'h0004C); dbk = rv; axr(17'h00044); dsnf = rv;
                $fwrite(fd, "# %0d %0d %0d %0d %0d %0d %0d\n", seq_seen, dk, df0, dn, dsat, dbk, dsnf);
                for (i = 0; i < 4096; i = i + 1) begin
                    axr(17'h08000 + 8 * i);     lo = rv;
                    axr(17'h08000 + 8 * i + 4);
                    $fwrite(fs, "%0d %0d\n", $signed(lo), $signed(rv));
                end
                for (i = 0; i < 4096; i = i + 1) begin
                    axr(17'h10000 + 8 * i);     lo = rv;
                    axr(17'h10000 + 8 * i + 4);
                    $fwrite(fd, "%0d\n", {rv, lo});
                end
                axr(17'h0001C);
                if (rv != seq_seen) $display("tb_top: 読み出しの間に SEQ が進んだ（%0d → %0d）", seq_seen, rv);
                nd = nd + 1;
                pause <= 0;
            end
        end
        pause <= 1;
        repeat (100) @(posedge clk);
        axr(17'h00018); $fwrite(fm, "flags %0d\n", rv & 32'hFF);
        $fwrite(fm, "satflags %0d\n", (rv >> 8) & 3);
        axr(17'h00020); lo = rv; axr(17'h00028);
        $fwrite(fm, "fin %0d fout %0d\n", lo, rv);
        axr(17'h00080); $fwrite(fm, "stall %0d\n", rv);
        axr(17'h00084); $fwrite(fm, "rdy0 %0d\n", rv);
        $display("tb_top: K=%0d NS=%0d NACC=%0d NDUMP=%0d SHIFT=%0d ダンプ %0d 個、入力 %0d / %0d ビート", kk, nsv, na, ndm, shv, nd, b, nbeat);
        $fclose(fz); $fclose(ff); $fclose(fd); $fclose(fs); $fclose(fm);
        $finish;
    end
    // 入力（pause の間は止める。GAP なら 1/8 で落とす）
    initial b = 0;
    always @(posedge clk) begin
        if (!aresetn || pause || b >= nbeat || (gap && (($random(seed) & 7) == 0))) tvalid <= 0;
        else begin
            for (l = 0; l < 16; l = l + 1) tdata[16*l +: 16] <= mem[16*b + l];
            tvalid <= 1;
            b = b + 1;
        end
    end
    always @(posedge clk) begin
        if (dut.zv) $fwrite(fz, "%0d %0d\n", dut.zr, dut.zi);
        if (dut.u_ws.m_tv) $fwrite(ff, "%0d %0d %0d\n", dut.u_ws.m_tu[11:0], $signed(dut.u_ws.m_td[30:0]), $signed(dut.u_ws.m_td[62:32]));
    end
endmodule
