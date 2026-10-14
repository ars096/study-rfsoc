// SPDX-License-Identifier: BSD-3-Clause
// proj021 手順 2-5 — sim-raw: s45_core（RAW = 1）の生サンプルの流れ（raw_core、KIND 4）を AXI4-Lite とレコードで確かめる
//
// 入力（s_axis_full）は作り物: ビート bn（リセットから数えた有効なビートの番号）のレーン i（16 bit）= pat(bn, i)。
// レーン 0・1 に bn そのもの（下位・上位 16 bit）を入れるので、レコードの中身から「どのビートか」が bit 単位で分かる。
// tb は頭のビート（bn mod 512 = 0）を口で受けたクロックの raw_core の t_loc を覗いて head_t[フレーム] に取っておく。
// レコードの出口（m_axis_rec_tready）はでたらめに止める（rec_arb・raw_core の送りの止まりに耐えるか）。
//
//   (e) SRC = 3 を書いて WRST → full_sel = 3・SRC の読み = {1, …, 3}
//   (a) ALL・N 8・N_DUMP 6: SNAP のレコード 6 個。中身 = フレーム DUMP_F0 の 512 ビート（bit 単位）・DUMP_F0(k) = RUN_F0 + 8k・
//       DUMP_T = head_t[DUMP_F0]・DUMP_T(k) − DUMP_T(0) = k·8·512（途切れ無し）・SEQ・DUMP_K が続く・頭 w0/w4/w5/w7
//   (b) ONE・N 4・N_DUMP 3: レコードは 1 個だけ・REC_CTRL が 0 に戻る・SEQ は 3 進む
//   (c) N 1・ALL・N_DUMP 12・入力に途切れ: 面が足りず REC_LATE > 0・出たレコードは全部正しい・出た数 + REC_LATE = 12・
//       s45_core の rec_drop の和 = REC_LATE・FLAGS[4]（途切れ）が立つ
//   (d) ARM_RUN と go（t = SA）: RUN_T = SA + 1・RUN_F0 = （その時のフレーム）+ 2・最初のレコードの DUMP_F0 = RUN_F0
//   ほか: IF_ID 0x0202_0301・NSTREAM 3・SID 0x0204_0200・PARAM 13・NCH 0・FRAME_BEATS 512
// 陽性対照（-DRAW_POSCTL）: 照合の側で中身を 1 語ずらす → 落ちる
`timescale 1ns / 1ps
module tb_raw;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg aresetn = 0;
    reg  [15:0] awaddr = 0, araddr = 0;
    reg         awvalid = 0, wvalid = 0, bready = 1, arvalid = 0, rready = 1;
    reg  [31:0] wdata = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [31:0] rdata;
    wire [1:0]  bresp, rresp, full_sel, rec_drop;
    reg  [255:0] fdata = 0;
    reg          fvalid = 0;
    reg  [63:0]  tcnt = 64'd1000;
    reg  [63:0]  sa = 64'hFFFF_FFFF_FFFF_FFFF;
    wire         go = (tcnt == sa);
    wire [63:0] rec_d; wire rec_v, rec_l, rec_u;
    reg          rec_r = 1;
    s45_core #(.NW(2), .N_ACC_DEFAULT(2), .G_L2(12), .RAW(1), .RAW_N_ACC_DEFAULT(1)) dut (
        .aclk(clk), .aresetn(aresetn), .s_axis_tdata(256'd0), .s_axis_tvalid(1'b0), .s_axis_tready(),
        .s_axis_full_tdata(fdata), .s_axis_full_tvalid(fvalid), .s_axis_full_tready(), .full_gb_stat(32'd0), .full_adc_stat(32'd0),
        .full_sel(full_sel),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(32'd0), .adc_stat(32'd0),
        .t_in(tcnt), .go_in(go), .tev_in(4'd0),
        .m_axis_rec_tdata(rec_d), .m_axis_rec_tvalid(rec_v), .m_axis_rec_tready(rec_r), .m_axis_rec_tlast(rec_l), .m_axis_rec_tuser(rec_u),
        .rec_drop(rec_drop));

    localparam [15:0] B = 16'h4800;            // RAW の流れ（s = 2）のブロック
    integer nerr = 0;
    // （NG の文は $display に直に書く。iverilog は日本語の文字列をタスクの引数のベクタに入れると壊す）

    task axw(input [15:0] a, input [31:0] d);
        begin
            @(posedge clk); awaddr <= a; wdata <= d; awvalid <= 1; wvalid <= 1;
            @(posedge clk); while (!(awready && wready)) @(posedge clk);
            awvalid <= 0; wvalid <= 0;
            @(posedge clk); while (!bvalid) @(posedge clk);
        end
    endtask
    reg [31:0] rv;
    task axr(input [15:0] a);
        begin
            @(posedge clk); araddr <= a; arvalid <= 1;
            @(posedge clk); while (!arready) @(posedge clk);
            arvalid <= 0;
            while (!rvalid) @(posedge clk);
            rv = rdata;
        end
    endtask

    // ---- 入力（作り物）----
    function [15:0] pat(input [31:0] bn, input integer i);
        pat = (i == 0) ? bn[15:0] : (i == 1) ? bn[31:16] : (bn[15:0] * 16'd7 + i * 16'd4099);
    endfunction
    function [255:0] beat(input [31:0] bn);
        integer i;
        for (i = 0; i < 16; i = i + 1) beat[16*i +: 16] = pat(bn, i);
    endfunction
    // ビートの番号は 2 つ: bs = 出したビートの通し番号（作り物の値 pat の引数）/ bn = raw_core が数えたビートの数（リセットが明けてから。
    //   s45_core はリセットをコアの中で 3 段遅らせるので、最初の数ビートは raw_core に数えられない）。raw_core のビート b の値 = beat(off + b)
    reg  [31:0] bs = 0, cur_bs = 0, off = 0;
    reg  [31:0] bn = 0;
    reg         off_set = 0;
    integer     gap_pct = 0;
    integer     seed = 7;
    reg  [63:0] head_t [0:4095];
    integer     ndrop = 0;
    always @(posedge clk) begin
        tcnt <= tcnt + 64'd1;
        rec_r <= ($random(seed) & 3) != 0;
        if (rec_drop != 2'd0) ndrop = ndrop + rec_drop;
        // raw_core が口で受けたビート（このクロックの fvalid・fdata。raw_core のリセットが明けていること）を数える
        if (fvalid && !dut.g_raw.u_raw.rst) begin
            if (!off_set) begin off = cur_bs; off_set = 1; end
            if (bn[8:0] == 9'd0) head_t[bn[20:9]] = dut.g_raw.u_raw.t_loc;
            bn = bn + 1;
        end
        if (!aresetn) begin fvalid <= 1'b0; end
        else if (gap_pct != 0 && ($random(seed) % 100 + 100) % 100 < gap_pct) fvalid <= 1'b0;
        else begin fvalid <= 1'b1; fdata <= beat(bs); cur_bs <= bs; bs = bs + 1; end
    end

    // ---- レコードの受け手（SNAP・s = 2 だけ。来るたびに照合）----
    reg  [63:0] hdr [0:7];
    reg  [63:0] body [0:2047];
    integer     w = 0, j, nrec = 0, nbad = 0, nwrong = 0;
    reg  [47:0] r_f0 [0:63];
    reg  [63:0] r_t  [0:63];
    reg  [31:0] r_seq [0:63], r_k [0:63], r_n [0:63];
    reg  [7:0]  r_src [0:63];
    reg  [31:0] eb;
    reg  [63:0] ew;
    integer     jj;
    always @(posedge clk) if (rec_v && rec_r) begin
        if (w < 8) hdr[w] = rec_d; else if (w - 8 < 2048) body[w - 8] = rec_d;
        if (rec_l) begin
            if (hdr[0][47:40] == 8'd4 && hdr[0][63:56] == 8'd2) begin
                if (rec_u) nbad = nbad + 1;
                else if (hdr[0] !== {8'd2, 8'd0, 8'd4, 8'd1, 32'h5235_3453} || hdr[7] !== 64'd16384 || w + 1 != 2056 ||
                         hdr[4][7:0] !== 8'd13 || hdr[4][39:8] !== 32'd0 || hdr[5][63:32] !== 32'd0) begin
                    nbad = nbad + 1;
                    $display("tb_raw: 頭の形が違う w0 %016x w4 %016x w5 %016x w7 %016x 長さ %0d", hdr[0], hdr[4], hdr[5], hdr[7], w + 1);
                end else begin
                    if (nrec < 64) begin
                        r_f0[nrec] = hdr[2][47:0]; r_t[nrec] = hdr[3]; r_seq[nrec] = hdr[1][31:0]; r_k[nrec] = hdr[1][63:32];
                        r_n[nrec] = hdr[5][31:0]; r_src[nrec] = hdr[4][47:40];
                    end
                    // 中身: 語 j = ビート F0·512 + j/4 のレーン 4(j mod 4)〜+3
                    for (j = 0; j < 2048; j = j + 1) begin
`ifdef RAW_POSCTL
                        jj = (j + 1) % 2048;
`else
                        jj = j;
`endif
                        eb = off + hdr[2][31:0] * 512 + jj / 4;
                        ew = beat(eb) >> (64 * (jj % 4));
                        if (body[j] !== ew) begin
                            if (nwrong < 4) $display("tb_raw: 中身が違う（F0 %0d 語 %0d: %016x、期待 %016x）", hdr[2][31:0], j, body[j], ew);
                            nwrong = nwrong + 1;
                        end
                    end
                    if (head_t[hdr[2][11:0]] !== hdr[3]) begin
                        $display("tb_raw: DUMP_T が違う（F0 %0d: %0d、覗いた頭のビートの T %0d）", hdr[2][31:0], hdr[3], head_t[hdr[2][11:0]]);
                        nbad = nbad + 1;
                    end
                    nrec = nrec + 1;
                end
            end
            w = 0;
        end else w = w + 1;
    end

    task wait_idle; begin repeat (6000) @(posedge clk); end endtask
    integer i, k, n0, d0, seq0, late0, nexp;
    reg [31:0] f0_run, tsv;
    initial begin
        repeat (8) @(posedge clk);
        aresetn <= 1;
        repeat (20) @(posedge clk);
        // ---- 自己記述 ----
        axr(16'h0000); if (rv !== 32'h0202_0301) begin begin $display("tb_raw: NG IF_ID"); nerr = nerr + 1; end $display("  %08x", rv); end
        axr(16'h0008); if (rv !== 32'd3) begin begin $display("tb_raw: NG NSTREAM"); nerr = nerr + 1; end $display("  %0d", rv); end
        axr(B + 16'h00); if (rv !== 32'h0204_0200) begin begin $display("tb_raw: NG SID"); nerr = nerr + 1; end $display("  %08x", rv); end
        axr(B + 16'h04); if (rv[7:0] !== 8'd13) begin $display("tb_raw: NG PARAM"); nerr = nerr + 1; end
        axr(B + 16'h20); if (rv !== 32'd0) begin $display("tb_raw: NG NCH"); nerr = nerr + 1; end
        axr(B + 16'h24); if (rv !== 32'd512) begin $display("tb_raw: NG FRAME_BEATS"); nerr = nerr + 1; end
        axr(B + 16'h80); if (rv !== 32'd0) begin $display("tb_raw: NG NFFT_MIN_MAX"); nerr = nerr + 1; end
        axr(B + 16'h100); if (rv !== 32'd0) begin $display("tb_raw: NG 0x100 は 0"); nerr = nerr + 1; end
        // ---- (e) SRC と WRST ----
        axw(B + 16'h28, 3); axw(B + 16'h2C, 32'h0025_0001);
        repeat (10) @(posedge clk);
        if (full_sel !== 2'd0) begin $display("tb_raw: NG (e) WRST の前に full_sel が変わった"); nerr = nerr + 1; end
        axw(B + 16'h08, 32'h1000);
        repeat (10) @(posedge clk);
        if (full_sel !== 2'd3) begin $display("tb_raw: NG (e) full_sel"); nerr = nerr + 1; end
        axr(B + 16'h28); if (rv !== 32'h8000_0003) begin begin $display("tb_raw: NG (e) SRC の読み"); nerr = nerr + 1; end $display("  %08x", rv); end
        axr(B + 16'h34); if (rv !== 32'h0025_0001) begin $display("tb_raw: NG (e) WRST_CFG"); nerr = nerr + 1; end
        $display("tb_raw: (e) 済み（full_sel %0d）", full_sel);
        // ---- (a) ALL・N 8・N_DUMP 6 ----
        repeat (3000) @(posedge clk);
        n0 = nrec;
        axw(B + 16'h0C, 8); axw(B + 16'h10, 6); axw(B + 16'h84, 1);
        axr(B + 16'h1C); seq0 = rv;
        axw(B + 16'h08, 32'h1);
        axr(B + 16'h68); f0_run = rv;
        i = 0; while (nrec < n0 + 6 && i < 200) begin repeat (1000) @(posedge clk); i = i + 1; end
        wait_idle;
        if (nrec != n0 + 6) begin begin $display("tb_raw: NG (a) レコードの数"); nerr = nerr + 1; end $display("  %0d", nrec - n0); end
        for (k = 0; k < 6 && n0 + k < nrec; k = k + 1) begin
            if (r_f0[n0 + k] != f0_run + 8 * k) begin begin $display("tb_raw: NG (a) DUMP_F0"); nerr = nerr + 1; end $display("  k %0d: %0d（RUN_F0 %0d）", k, r_f0[n0 + k], f0_run); end
            if (r_t[n0 + k] - r_t[n0] != 8 * 512 * k) begin begin $display("tb_raw: NG (a) DUMP_T の間隔"); nerr = nerr + 1; end $display("  k %0d: %0d", k, r_t[n0 + k] - r_t[n0]); end
            if (r_seq[n0 + k] != seq0 + 1 + k || r_k[n0 + k] != k || r_n[n0 + k] != 8 || r_src[n0 + k] != 3) begin
                begin $display("tb_raw: NG (a) SEQ・DUMP_K・DUMP_N・SRC"); nerr = nerr + 1; end $display("  k %0d: %0d %0d %0d %0d", k, r_seq[n0 + k], r_k[n0 + k], r_n[n0 + k], r_src[n0 + k]);
            end
        end
        axr(B + 16'h1C); if (rv != seq0 + 6) begin $display("tb_raw: NG (a) SEQ の読み"); nerr = nerr + 1; end
        axr(B + 16'h3C); if (rv != 5) begin $display("tb_raw: NG (a) DUMP_K の読み"); nerr = nerr + 1; end
        axr(B + 16'h48); if (rv != 8) begin $display("tb_raw: NG (a) DUMP_N の読み"); nerr = nerr + 1; end
        axr(B + 16'h40); if (rv != f0_run + 40) begin $display("tb_raw: NG (a) DUMP_F0 の読み"); nerr = nerr + 1; end
        axr(B + 16'h50); tsv = rv; if (tsv != r_t[n0 + 5][31:0]) begin $display("tb_raw: NG (a) DUMP_T の読み"); nerr = nerr + 1; end
        axr(B + 16'h88); if (rv != 0) begin $display("tb_raw: NG (a) REC_LATE"); nerr = nerr + 1; end
        $display("tb_raw: (a) 済み（レコード %0d・RUN_F0 %0d・DUMP_T の間隔 %0d）", nrec - n0, f0_run, r_t[n0 + 1] - r_t[n0]);
        // ---- (b) ONE ----
        n0 = nrec;
        axw(B + 16'h0C, 4); axw(B + 16'h10, 3); axw(B + 16'h84, 2);
        axr(B + 16'h1C); seq0 = rv;
        axw(B + 16'h08, 32'h1);
        repeat (3 * 4 * 512 + 3000) @(posedge clk);
        wait_idle;
        if (nrec != n0 + 1) begin begin $display("tb_raw: NG (b) レコードの数"); nerr = nerr + 1; end $display("  %0d", nrec - n0); end
        axr(B + 16'h84); if (rv != 0) begin $display("tb_raw: NG (b) ONE が 0 に戻らない"); nerr = nerr + 1; end
        axr(B + 16'h1C); if (rv != seq0 + 3) begin $display("tb_raw: NG (b) SEQ"); nerr = nerr + 1; end
        if (nrec > n0 && (r_seq[n0] != seq0 + 1 || r_k[n0] != 0)) begin $display("tb_raw: NG (b) 出たのは最初のダンプ"); nerr = nerr + 1; end
        $display("tb_raw: (b) 済み（レコード %0d）", nrec - n0);
        // ---- (c) N 1・ALL・途切れ ----
        n0 = nrec; d0 = ndrop;
        axr(B + 16'h88); late0 = rv;
        gap_pct = 5;
        axw(B + 16'h08, 32'h100);               // FLAGS を消す
        axw(B + 16'h0C, 1); axw(B + 16'h10, 12); axw(B + 16'h84, 1);
        axw(B + 16'h08, 32'h1);
        repeat (14 * 600 + 3000) @(posedge clk);
        wait_idle;
        axr(B + 16'h88);
        if (rv - late0 == 0) begin $display("tb_raw: NG (c) REC_LATE が 0（面が足りなくなるはず）"); nerr = nerr + 1; end
        if (nrec - n0 + (rv - late0) != 12) begin begin $display("tb_raw: NG (c) 出た数 + REC_LATE ≠ 12"); nerr = nerr + 1; end $display("  %0d + %0d", nrec - n0, rv - late0); end
        if (ndrop - d0 != rv - late0) begin begin $display("tb_raw: NG (c) rec_drop の和 ≠ REC_LATE"); nerr = nerr + 1; end $display("  %0d / %0d", ndrop - d0, rv - late0); end
        axr(B + 16'h18); if (rv[4] !== 1'b1) begin $display("tb_raw: NG (c) FLAGS[4]（途切れ）"); nerr = nerr + 1; end
        $display("tb_raw: (c) 済み（レコード %0d・REC_LATE %0d・rec_drop %0d）", nrec - n0, ndrop - d0, ndrop - d0);
        gap_pct = 0;
        // ---- (d) ARM_RUN ----
        n0 = nrec;
        axw(B + 16'h0C, 2); axw(B + 16'h10, 2); axw(B + 16'h84, 1);
        axw(B + 16'h08, 32'h4);                 // ARM_RUN
        axr(B + 16'h08); if (rv[5] !== 1'b1) begin $display("tb_raw: NG (d) ARM_RUN 中が立たない"); nerr = nerr + 1; end
        @(posedge clk); sa <= tcnt + 2000;
        wait (tcnt == sa + 2);                  // cmd_run が効くクロック（t_loc = SA + 1）
        f0_run = (bn >> 9) + 2;                 // そのクロックに受ける前のビートの数で数えたフレーム + 2
        wait_idle; repeat (3000) @(posedge clk);
        axr(B + 16'h60); tsv = rv - sa[31:0]; if (rv != sa[31:0] + 1) begin begin $display("tb_raw: NG (d) RUN_T"); nerr = nerr + 1; end $display("  %0d（SA %0d）", rv, sa); end
        axr(B + 16'h68); if (rv != f0_run) begin begin $display("tb_raw: NG (d) RUN_F0"); nerr = nerr + 1; end $display("  %0d（期待 %0d）", rv, f0_run); end
        if (nrec != n0 + 2) begin $display("tb_raw: NG (d) レコードの数"); nerr = nerr + 1; end
        else if (r_f0[n0] != f0_run) begin $display("tb_raw: NG (d) 最初の DUMP_F0"); nerr = nerr + 1; end
        axr(B + 16'h08); if (rv[5] !== 1'b0) begin $display("tb_raw: NG (d) ARM_RUN 中が消えない"); nerr = nerr + 1; end
        $display("tb_raw: (d) 済み（RUN_T − SA = %0d・RUN_F0 %0d）", tsv, f0_run);
        // ---- まとめ ----
        if (nbad != 0) begin begin $display("tb_raw: NG 頭・DUMP_T の不一致・捨てられたレコード"); nerr = nerr + 1; end $display("  %0d", nbad); end
        if (nwrong != 0) begin begin $display("tb_raw: NG 中身の不一致"); nerr = nerr + 1; end $display("  %0d 語", nwrong); end
        $display("tb_raw: レコード %0d 個・中身の不一致 %0d 語・頭の不一致 %0d", nrec, nwrong, nbad);
        if (nerr == 0) $display("tb_raw: PASS"); else $display("tb_raw: FAIL（%0d）", nerr);
        $finish;
    end
endmodule
