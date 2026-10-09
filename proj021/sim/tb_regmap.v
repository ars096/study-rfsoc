// SPDX-License-Identifier: BSD-3-Clause
// proj021 手順 2-1 S21-1 — コアの番地（INTERFACE.md v2 の 2.4・2.5、proj021/README の手順 2-1 の表）を端から確かめる sim
//   time_core 1 個 ＋ s45_core_0（FULL = 1、CORE_PORT = ADC_A = タイル 2・スライス 2）＋ s45_core_1（FULL = 0、ADC_B = タイル 2・スライス 0。CORE_PORT 0x0201）
//   入力は流さない（番地と自己記述だけを見る。中身は sim-top・sim-win4・sim-tsys・sim-t4adc・sim が見る）
// 判定（「tb_regmap: NG」を数える）:
//   1. コアの共通: IF_ID・PROJ・NSTREAM・CAPS・BASE_BEATS・BUILD・CORE_PORT・予約は 0
//   2. 流れのブロック: SID・PARAM・NCH・FRAME_BEATS・SRC・NFFT_MIN_MAX・REC_CTRL・REC_LATE・NS_MIN_MAX。無い流れ・予約は 0
//      （2-2a: CAPS = 1。REC_CTRL を 3 に入れて書いて読み返す）
//   3. 書けるレジスタ（N_ACC・N_DUMP・SHIFT・CFG_ID・WK・WDPHI・WNS・WRST_T・GB_K）を流れごとに違う値で書いて読み返す（ほかの流れに漏れない）
//   4. WRST: 窓の WCUR・FRAME_BEATS・PARAM の NS が書いた WNS に、WRST_CFG が CFG_ID に。FULL の SRC は書いただけでは効かず、
//      WRST（CTRL[12]）で効き、full_sel に出る。ARM_WRST（CTRL[13]）は time_core の発火で効く
//   5. TP のレジスタ（0x100）・FULL の TP（仮の 0xC1100）・仮の SNAP_SEL（0xE0000）・仮の範囲の空き（0xDEADBEEF）
//   6. time_core の IF_ID・PROJ
// 陽性対照（-DREGMAP_POSCTL）: tb の流れのブロックの番地を 4 バイトずらす → 落ちること
`timescale 1ns / 1ps
module tb_regmap;
    reg clk = 0, cclk = 0;
    always #1.953 clk = ~clk;
    always #5.000 cclk = ~cclk;
    reg aresetn = 0, crstn = 0;
`ifdef REGMAP_POSCTL
    localparam [19:0] PX = 20'h4;
`else
    localparam [19:0] PX = 20'h0;
`endif
    // AXI: 0 = s45_core_0 / 1 = s45_core_1 / 2 = time_core
    reg  [19:0] awaddr = 0, araddr = 0;
    reg  [2:0]  awv = 0, wv = 0, arv = 0;
    reg  [31:0] wdata = 0;
    wire [2:0]  awr, wr_, bv, arr, rv_;
    wire [31:0] rdw [0:2];
    wire [63:0] t_out; wire go_out; wire [3:0] ev_out;
    wire [1:0]  fsel0, fsel1;
    time_core u_t (.aclk(clk), .aresetn(aresetn), .ctrl_aclk(cclk), .ctrl_aresetn(crstn), .pps_trig_i(1'b0), .pps_comp_i(1'b0),
        .s_axi_awaddr(awaddr[7:0]), .s_axi_awprot(3'd0), .s_axi_awvalid(awv[2]), .s_axi_awready(awr[2]),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wv[2]), .s_axi_wready(wr_[2]), .s_axi_bresp(), .s_axi_bvalid(bv[2]), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr[7:0]), .s_axi_arprot(3'd0), .s_axi_arvalid(arv[2]), .s_axi_arready(arr[2]),
        .s_axi_rdata(rdw[2]), .s_axi_rresp(), .s_axi_rvalid(rv_[2]), .s_axi_rready(1'b1),
        .t_out(t_out), .go_out(go_out), .ev_out(ev_out));
    wire [63:0] T = u_t.T;
    s45_core #(.NW(2), .G_L2(12), .BUILD_TAG(32'h1234_0000), .CORE_PORT(16'h2200), .FULL(1), .FULL_BUILD_TAG(32'h5678_0000),
               .FULL_FFT_CFG(8'hA5), .FULL_STABLE_N(0)) u_c0 (
        .aclk(clk), .aresetn(aresetn), .s_axis_tdata(256'd0), .s_axis_tvalid(1'b0), .s_axis_tready(),
        .s_axis_full_tdata(256'd0), .s_axis_full_tvalid(1'b0), .s_axis_full_tready(), .full_gb_stat(32'd0), .full_adc_stat(32'd0), .full_sel(fsel0),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awv[0]), .s_axi_awready(awr[0]),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wv[0]), .s_axi_wready(wr_[0]), .s_axi_bresp(), .s_axi_bvalid(bv[0]), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arv[0]), .s_axi_arready(arr[0]),
        .s_axi_rdata(rdw[0]), .s_axi_rresp(), .s_axi_rvalid(rv_[0]), .s_axi_rready(1'b1),
        .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(32'd0), .adc_stat(32'd0),
        .t_in(t_out), .go_in(go_out), .tev_in(ev_out));
    s45_core #(.NW(2), .G_L2(12), .BUILD_TAG(32'h1234_0001), .CORE_PORT(16'h0201), .FULL(0)) u_c1 (
        .aclk(clk), .aresetn(aresetn), .s_axis_tdata(256'd0), .s_axis_tvalid(1'b0), .s_axis_tready(),
        .s_axis_full_tdata(256'd0), .s_axis_full_tvalid(1'b0), .s_axis_full_tready(), .full_gb_stat(32'd0), .full_adc_stat(32'd0), .full_sel(fsel1),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awv[1]), .s_axi_awready(awr[1]),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wv[1]), .s_axi_wready(wr_[1]), .s_axi_bresp(), .s_axi_bvalid(bv[1]), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arv[1]), .s_axi_arready(arr[1]),
        .s_axi_rdata(rdw[1]), .s_axi_rresp(), .s_axi_rvalid(rv_[1]), .s_axi_rready(1'b1),
        .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(32'd0), .adc_stat(32'd0),
        .t_in(t_out), .go_in(go_out), .tev_in(ev_out));

    integer ng = 0, nchk = 0;
    task axw(input integer s, input [19:0] a, input [31:0] d); begin
        @(posedge clk); awaddr <= a; wdata <= d; awv[s] <= 1; wv[s] <= 1;
        @(posedge clk); while (!awr[s]) @(posedge clk);
        awv[s] <= 0; wv[s] <= 0;
        while (!bv[s]) @(posedge clk);
    end endtask
    reg [31:0] rv;
    task axr(input integer s, input [19:0] a); begin
        @(posedge clk); araddr <= a; arv[s] <= 1;
        @(posedge clk); while (!arr[s]) @(posedge clk);
        arv[s] <= 0;
        while (!rv_[s]) @(posedge clk);
        rv = rdw[s];
    end endtask
    task expect(input integer s, input [19:0] a, input [31:0] want, input [8*40-1:0] what); begin
        axr(s, a); nchk = nchk + 1;
        if (rv !== want) begin $display("tb_regmap: NG コア %0d 0x%05x %0s = %08x（期待 %08x）", s, a, what, rv, want); ng = ng + 1; end
    end endtask
    task expectm(input integer s, input [19:0] a, input [31:0] mask, input [31:0] want, input [8*40-1:0] what); begin
        axr(s, a); nchk = nchk + 1;
        if ((rv & mask) !== want) begin $display("tb_regmap: NG コア %0d 0x%05x %0s = %08x（期待 %08x / マスク %08x）", s, a, what, rv, want, mask); ng = ng + 1; end
    end endtask
    // 流れのブロックの番地（陽性対照では PX だけずらす）
    function [19:0] B(input integer st, input [11:0] o); B = 20'h04000 + 20'h00400 * st + o + PX; endfunction

    integer c, st, k, fd;
    reg [8*256-1:0] dump_fn;
    reg [63:0] sa;
    initial begin
        #40 crstn = 1;
        repeat (8) @(posedge clk);
        aresetn <= 1;
        repeat (16) @(posedge clk);
        // ---- 1. コアの共通 ----
        for (c = 0; c < 2; c = c + 1) begin
            expect(c, 20'h00000, 32'h0202_0101, "IF_ID");
            expect(c, 20'h00004, 32'h0021_0200, "PROJ");
            expect(c, 20'h00008, (c == 0) ? 3 : 2, "NSTREAM");
            expect(c, 20'h0000C, 1, "CAPS（[0] DMA のレコード。2-2a）");
            expect(c, 20'h00010, 2621440, "BASE_BEATS");
            expect(c, 20'h00014, 32'h1234_0000 + c, "BUILD");
            expect(c, 20'h00018, (c == 0) ? 32'h2200 : 32'h0201, "CORE_PORT");
            expect(c, 20'h0001C, 0, "予約 0x1C");
            expect(c, 20'h00030, 0, "予約 0x30（旧 FULL_SEL）");
            expect(c, 20'h0002C, 2, "GB_K（既定）");
            expect(c, 20'h00060, 0, "予約 0x60");
            expect(c, 20'h000FC, 0, "予約 0xFC");
            expect(c, 20'h01000, 0, "予約 0x1000");
        end
        // ---- 2. 流れのブロック ----
        for (c = 0; c < 2; c = c + 1) for (st = 0; st < 2; st = st + 1) begin
            expect(c, B(st, 12'h000), 32'h0203_0000 | (st << 8), "SID（DDC）");
            expect(c, B(st, 12'h004), 32'h0040_410C, "PARAM（NS 1・G 4）");
            expect(c, B(st, 12'h020), 4096, "NCH");
            expect(c, B(st, 12'h024), 4096, "FRAME_BEATS（NS 1）");
            expect(c, B(st, 12'h028), (c == 0) ? 0 : 1, "SRC（固定）");
            expect(c, B(st, 12'h080), 32'h0000_0C0C, "NFFT_MIN_MAX");
            expect(c, B(st, 12'h084), 0, "REC_CTRL");
            expect(c, B(st, 12'h088), 0, "REC_LATE");
            expect(c, B(st, 12'h08C), 0, "予約 0x8C");
            expect(c, B(st, 12'h0FC), 0, "予約 0xFC");
            expect(c, B(st, 12'h118), 32'h0000_0801, "NS_MIN_MAX");
            expect(c, B(st, 12'h11C), 64, "WRST_T（既定）");
            expect(c, B(st, 12'h120), 0, "種類に固有の空き");
            expect(c, B(st, 12'h2FC), 0, "診断の空き");
        end
        expect(0, B(2, 12'h000), 32'h0201_0200, "SID（FULL）");
        expect(0, B(2, 12'h004), 32'h0040_A50D, "PARAM（FULL、FFT_CFG A5）");
        expect(0, B(2, 12'h020), 4096, "NCH（FULL）");
        expect(0, B(2, 12'h024), 512, "FRAME_BEATS（FULL）");
        expect(0, B(2, 12'h028), 32'h8000_0000, "SRC（FULL、書き換えられる）");
        expect(0, B(2, 12'h080), 32'h0000_0D0D, "NFFT_MIN_MAX（FULL）");
        expect(0, B(2, 12'h084), 0, "REC_CTRL（FULL）");
        expect(0, B(2, 12'h100), 0, "FULL の種類に固有（なし）");
        expect(0, B(2, 12'h214), 32'h5678_0000, "FULL の診断の BUILD（0x214）");
        expect(0, B(3, 12'h000), 0, "無い流れ s = 3");
        expect(1, B(2, 12'h000), 0, "無い流れ s = 2（コア 1）");
        expect(0, 20'h0FC00, 0, "無い流れ s = 47");
        // ---- 3. 書けるレジスタ: 流れごとに違う値 ----
        for (c = 0; c < 2; c = c + 1) begin
            axw(c, 20'h0002C, 3 + c);
            for (st = 0; st < 2 + (c == 0); st = st + 1) begin
                k = 16 * c + st;
                axw(c, B(st, 12'h00C), 100 + k); axw(c, B(st, 12'h010), 200 + k); axw(c, B(st, 12'h014), (5 + k) & 15);
                axw(c, B(st, 12'h02C), 32'hC0F0_0000 + k);
                axw(c, B(st, 12'h084), 32'hFFFF_FFF8 | ((k + 5) & 7));   // REC_CTRL（[2:0] だけ）。ダンプが無いので ONE は残る
                if (st < 2) begin
                    axw(c, B(st, 12'h100), (k + 1) & 31); axw(c, B(st, 12'h104), 32'h1357_0000 + k);
                    axw(c, B(st, 12'h108), 3 + st); axw(c, B(st, 12'h11C), 80 + k);
                end
            end
        end
        for (c = 0; c < 2; c = c + 1) begin
            expect(c, 20'h0002C, 3 + c, "GB_K");
            for (st = 0; st < 2 + (c == 0); st = st + 1) begin
                k = 16 * c + st;
                expect(c, B(st, 12'h00C), 100 + k, "N_ACC");
                expect(c, B(st, 12'h010), 200 + k, "N_DUMP");
                expect(c, B(st, 12'h014), (5 + k) & 15, "SHIFT");
                expect(c, B(st, 12'h02C), 32'hC0F0_0000 + k, "CFG_ID");
                expect(c, B(st, 12'h084), (k + 5) & 7, "REC_CTRL（2-2a）");
                expect(c, B(st, 12'h088), 0, "REC_LATE（2-2a）");
                axw(c, B(st, 12'h084), 0);
                if (st < 2) begin
                    expect(c, B(st, 12'h100), (k + 1) & 31, "WK");
                    expect(c, B(st, 12'h104), 32'h1357_0000 + k, "WDPHI");
                    expect(c, B(st, 12'h108), 3 + st, "WNS");
                    expect(c, B(st, 12'h11C), 80 + k, "WRST_T");
                    expect(c, B(st, 12'h024), 4096, "FRAME_BEATS（WRST の前は NS 1 のまま）");
                end
            end
        end
        // ---- 4. WRST ----
        axw(0, B(2, 12'h028), 3);                         // FULL の SRC = ADC_D（まだ効かない）
        repeat (20) @(posedge clk);
        expect(0, B(2, 12'h028), 32'h8000_0000, "SRC（WRST の前）");
        if (fsel0 !== 2'd0) begin $display("tb_regmap: NG full_sel が WRST の前に変わった %0d", fsel0); ng = ng + 1; end
        axw(0, B(2, 12'h008), 32'h1000);                  // WRST
        repeat (4) @(posedge clk);
        expect(0, B(2, 12'h028), 32'h8000_0003, "SRC（WRST の後）");
        expect(0, B(2, 12'h034), 32'hC0F0_0002, "WRST_CFG（FULL）");
        if (fsel0 !== 2'd3) begin $display("tb_regmap: NG full_sel %0d（期待 3）", fsel0); ng = ng + 1; end
        if (fsel1 !== 2'd0) begin $display("tb_regmap: NG FULL の無いコアの full_sel %0d", fsel1); ng = ng + 1; end
        for (c = 0; c < 2; c = c + 1) for (st = 0; st < 2; st = st + 1) axw(c, B(st, 12'h008), 32'h1000);
        repeat (200) @(posedge clk);
        for (c = 0; c < 2; c = c + 1) for (st = 0; st < 2; st = st + 1) begin
            k = 16 * c + st;
            expect(c, B(st, 12'h10C), ((3 + st) << 8) | ((k + 1) & 31), "WCUR");
            expect(c, B(st, 12'h110), 32'h1357_0000 + k, "WCUR_DPHI");
            expect(c, B(st, 12'h024), 2048 << (3 + st), "FRAME_BEATS（WRST の後）");
            expect(c, B(st, 12'h004), 32'h0040_400C | ((3 + st) << 8), "PARAM（WRST の後、G 4）");
            expect(c, B(st, 12'h034), 32'hC0F0_0000 + k, "WRST_CFG");
            expect(c, B(st, 12'h214), 1, "WRST_CNT");
        end
        // ARM_WRST: FULL の SRC を 1 に、time_core の発火で効く
        axw(0, B(2, 12'h028), 1);
        axw(0, B(2, 12'h008), 32'h2000);                  // ARM_WRST
        expectm(0, B(2, 12'h008), 32'h40, 32'h0000_0040, "CTRL の [6] ARM_WRST 中");
        sa = T + 2000;
        axw(2, 20'h10, sa[31:0]); axw(2, 20'h14, sa[63:32]); axw(2, 20'h08, 32'h1);
        while (T < sa - 2) @(posedge clk);
        if (fsel0 !== 2'd3) begin $display("tb_regmap: NG ARM_WRST が発火の前に効いた %0d", fsel0); ng = ng + 1; end
        while (T < sa + 8) @(posedge clk);
        if (fsel0 !== 2'd1) begin $display("tb_regmap: NG ARM_WRST が発火で効かない %0d", fsel0); ng = ng + 1; end
        expectm(0, B(2, 12'h008), 32'h40, 32'h0000_0000, "CTRL の [6]（発火の後）");
        // ---- 5. TP・仮の範囲 ----
        for (c = 0; c < 2; c = c + 1) expect(c, 20'h00114, (512 << 16) | (16 << 8) | 2, "TP_PARAM（0x114）");
        expect(0, 20'hC1114, (512 << 16) | (16 << 8) | 2, "FULL の TP_PARAM（仮 0xC1114）");
        expect(0, 20'hE0000, 0, "仮の SNAP_SEL（既定）");
        axw(0, 20'hE0000, 1);
        expect(0, 20'hE0000, 1, "仮の SNAP_SEL");
        expect(0, 20'hD0000, 32'hDEAD_BEEF, "仮の範囲の空き（窓 2 は無い）");
        expect(1, 20'hC0000, 32'hDEAD_BEEF, "仮の範囲の空き（コア 1 に FULL は無い）");
        expect(0, 20'hC0400, 32'hDEAD_BEEF, "FULL の仮の範囲の空き（0xC0400）");
        expect(0, 20'hC001C, 0, "FULL の仮の範囲の 0x1C = SEQ（0）");
        // ---- 7. +DUMP=ファイル: 約束の番地の読みを全部書き出す（pynq/test_regmap.py が s45core.py の自己記述の読み手を、この値で回す）----
        if ($value$plusargs("DUMP=%s", dump_fn)) begin
            fd = $fopen(dump_fn, "w");
            for (c = 0; c < 2; c = c + 1) begin
                for (k = 0; k < 64; k = k + 1) begin axr(c, 4 * k); $fwrite(fd, "%0d %05x %08x\n", c, 4 * k, rv); end
                for (k = 0; k < 64; k = k + 1) begin axr(c, 20'h00100 + 4 * k); $fwrite(fd, "%0d %05x %08x\n", c, 20'h00100 + 4 * k, rv); end
                for (st = 0; st < 3; st = st + 1)        // 流れのブロックの使っている所だけ（0x000–0x08C・0x100–0x11C・0x200–0x26C）
                    for (k = 0; k < 256; k = k + 1) if (k < 36 || (k >= 64 && k < 72) || (k >= 128 && k < 156)) begin
                        axr(c, 20'h04000 + 20'h400 * st + 4 * k); $fwrite(fd, "%0d %05x %08x\n", c, 20'h04000 + 20'h400 * st + 4 * k, rv); end
            end
            for (k = 0; k < 64; k = k + 1) begin axr(0, 20'hC1100 + 4 * k); $fwrite(fd, "0 %05x %08x\n", 20'hC1100 + 4 * k, rv); end
            axr(0, 20'hE0000); $fwrite(fd, "0 e0000 %08x\n", rv);
            for (k = 0; k < 24; k = k + 1) begin axr(2, 4 * k); $fwrite(fd, "2 %05x %08x\n", 4 * k, rv); end
            $fclose(fd);
            $display("tb_regmap: 書き出した %0s", dump_fn);
        end
        // ---- 6. time_core ----
        expect(2, 20'h00, 32'h0202_0102, "time_core の IF_ID");
        expect(2, 20'h5C, 32'h0021_0200, "time_core の PROJ");
`ifdef REGMAP_POSCTL
        $display("tb_regmap: 陽性対照（流れのブロックの番地を 4 バイトずらした）: NG %0d 件 / %0d", ng, nchk);
        if (ng > 0) $display("tb_regmap: 結果: 全部通過（陽性対照が落ちるべきところで落ちた）");
        else        $display("tb_regmap: 結果: 陽性対照が落ちなかった（見張りが効いていない）");
`else
        if (ng == 0) $display("tb_regmap: 結果: 全部通過（%0d 項目）", nchk);
        else         $display("tb_regmap: 結果: 失敗（%0d 件 / %0d 項目）", ng, nchk);
`endif
        $finish;
    end
    initial begin #5000000; $display("tb_regmap: NG 時間切れ"); $display("tb_regmap: 結果: 失敗"); $finish; end
endmodule
