// SPDX-License-Identifier: BSD-3-Clause
//
// tb_gearbox — ギアボックスの起動の途切れの仕組みを確かめる模型（proj011 rev6。`make sim-gb`）
//
// 実機の gb_fifo（axis_data_fifo、非同期）の中身は iverilog で回せないので、**仕組みの見立てを写した模型**を置く:
//   - クロック: VCO（1024 MHz 相当）を 3 分周 = ADC ドメイン、4 分周 = DSP ドメイン。**比は厳密に 3 : 4**
//   - 書き込み: gb_up の代わりに、ADC の 4 クロックに 1 語（語には通し番号）。リセットの解除から数え始める
//   - FIFO: 深さ 32、書き込みポインタは gray（6 bit）。**gray の各ビットは、ビットごとの遅延 DLY[b] で読み出し側に着く**
//           （配線の違いを写す）。読み出し側は 2 段で取り込み、空なら valid = 0（FWFT）
//   - 読み出し: gb_gate（DUT）→ gb_dn の代わり（1 語を 3 拍に割る。最後の拍と同じクロックで次の語を受ける）
//   - リセット: gb_adc（DUT）が DSP の hold を取り込んで書き込み側を放す。adj で位相を選ぶ。読み出し側は hold が落ちたら放す
//
// 遅延の組（DLY）× 再起動の位相（hold の長さ 3 通り × adj 4 通り = 12 通り）× しきい値 K（0 / 4）を回し、
// 出口（gb_dn の後）の valid が最初の拍の後に何回落ちたか・最初に落ちた位置・データの通し番号の連続を数える。
//
// 見立て（README の rev6 の節）の予言:
//   同じ遅延     → どの位相でも途切れ 0
//   bit 2 だけ遅い → K = 0 で、位相によって途切れが**ちょうど 1 回**、位置は語 3 の受け渡し（= 2^2 − 1）。K = 4 で 0
//   bit 0 だけ遅い → 途切れ 0（最初に動くビットが一番遅ければ、後から余裕を食うビットがない）
//   どの場合も通し番号は欠けも重複もない（FIFO は語を落とさない。落ちるのは valid だけ）

`timescale 1ps / 1ps

module tb_gearbox;
    localparam integer VCO = 976;        // VCO の周期（ps。1024 MHz ≒ 976.6 ps。比が厳密なら丸めは効かない）
    localparam integer NW  = 6;          // ポインタの幅（深さ 32 + 1 bit）
    localparam integer RUN = 600;        // 1 回の起動で見る DSP クロック数

    // ---- クロック ----
    reg vco = 0;
    always #(VCO/2) vco = ~vco;
    reg [1:0] c3 = 0;
    reg [1:0] c4 = 0;
    reg clk_adc = 0, clk_dsp = 0;
    always @(posedge vco) begin
        c3 <= (c3 == 2) ? 0 : c3 + 1;
        c4 <= c4 + 1;
        clk_adc <= (c3 == 0);
        clk_dsp <= (c4 == 0);
    end

    // ---- 試験の設定 ----
    integer DLY [0:NW-1];
    reg  [5:0] K;
    reg        hold;
    reg  [1:0] adj;
    reg        aresetn_adc, dsp_rstn;

    // ---- gb_adc（DUT）: 書き込み側のリセット ----
    wire        gb_rstn;
    wire [16:0] adc_out;
    wire        rfdc_tready;
    gb_adc #(.DW(8)) u_adc (
        .aclk(clk_adc), .aresetn(aresetn_adc),
        .s_axis_tdata(8'd0), .s_axis_tvalid(1'b1), .s_axis_tready(rfdc_tready),
        .m_axis_tdata(), .m_axis_tvalid(), .m_axis_tready(1'b1),
        .hold(hold), .adj(adj), .gb_rstn(gb_rstn), .adc_out(adc_out));

    // ---- 書き込み（gb_up の代わり）と FIFO ----
    reg  [1:0]    wp4;
    reg  [NW-1:0] wbin, wgray;
    reg  [15:0]   wseq;
    reg  [15:0]   mem [0:31];
    wire [NW-1:0] wbin1 = wbin + 1'b1;        // **6 bit で折り返す**（32 bit の文脈で gray を作ると 63 → 0 で bit 5 が動かない）
    always @(posedge clk_adc) begin
        if (!gb_rstn) begin
            wp4 <= 0; wbin <= 0; wgray <= 0; wseq <= 0;
        end else begin
            wp4 <= wp4 + 1;
            if (wp4 == 2'd3) begin
                mem[wbin[4:0]] <= wseq;
                wseq  <= wseq + 1;
                wbin  <= wbin1;
                wgray <= wbin1 ^ (wbin1 >> 1);
            end
        end
    end
    // gray の各ビットが読み出し側の最初の同期段に着くまでの遅延（ビットごと。transport）
    reg [NW-1:0] wgray_d = 0;
    genvar gb;
    generate for (gb = 0; gb < NW; gb = gb + 1) begin : g_dly
        always @(wgray[gb]) wgray_d[gb] <= #(DLY[gb]) wgray[gb];
    end endgenerate

    // 読み出し側（DSP）
    reg  [NW-1:0] s1, s2, rbin;
    function [NW-1:0] g2b(input [NW-1:0] g);
        integer i; begin
            g2b[NW-1] = g[NW-1];
            for (i = NW - 2; i >= 0; i = i - 1) g2b[i] = g2b[i+1] ^ g[i];
        end
    endfunction
    wire [NW-1:0] wsync = g2b(s2);
    wire          f_valid = (wsync != rbin);
    wire [15:0]   f_data  = mem[rbin[4:0]];
    wire [NW-1:0] f_count = wsync - rbin;
    wire          f_ready;

    // ---- gb_gate（DUT）----
    wire [15:0] g_data;
    wire        g_valid, g_ready;
    wire [31:0] gb_stat, adc_stat;
    gb_gate #(.DW(16), .CW(NW)) u_gate (
        .aclk(clk_dsp), .aresetn(dsp_rstn),
        .s_axis_tdata(f_data), .s_axis_tvalid(f_valid), .s_axis_tready(f_ready),
        .m_axis_tdata(g_data), .m_axis_tvalid(g_valid), .m_axis_tready(g_ready),
        .rd_count(f_count), .k(K), .gb_stat(gb_stat),
        .adc_in(adc_out), .adc_stat(adc_stat));

    always @(posedge clk_dsp) begin
        if (!dsp_rstn) begin
            s1 <= 0; s2 <= 0; rbin <= 0;
        end else begin
            s1 <= wgray_d; s2 <= s1;
            if (f_valid && f_ready) rbin <= rbin + 1;
        end
    end

    // ---- gb_dn の代わり: 1 語 → 3 拍 ----
    reg  [1:0]  left;
    reg  [15:0] cur;
    reg  [1:0]  beat;
    assign g_ready = (left == 0) || (left == 1);
    wire        o_valid = (left != 0);
    always @(posedge clk_dsp) begin
        if (!dsp_rstn) begin
            left <= 0; cur <= 0; beat <= 0;
        end else begin
            if (g_valid && g_ready) begin
                left <= 3; cur <= g_data; beat <= 0;
            end else if (left != 0) begin
                left <= left - 1; beat <= beat + 1;
            end
        end
    end

    // ---- 見張り ----
    integer ncyc, seen, prev, gaps, first_gap, first_word, nbeats, errs, exp_seq;
    reg [15:0] last_seq;
    always @(posedge clk_dsp) begin
        if (!dsp_rstn) begin
            ncyc = 0; seen = 0; prev = 0; gaps = 0; first_gap = -1; first_word = -1; nbeats = 0; errs = 0; exp_seq = 0;
        end else begin
            if (seen) ncyc = ncyc + 1;
            if (o_valid) begin
                if (!seen) seen = 1;
                if (beat == 0) begin
                    if (cur != exp_seq[15:0]) errs = errs + 1;
                    exp_seq = cur + 1;
                end
                nbeats = nbeats + 1;
            end
            if (seen && prev && !o_valid) begin
                gaps = gaps + 1;
                if (first_gap < 0) begin first_gap = ncyc; first_word = exp_seq; end
            end
            prev = o_valid;
        end
    end

    // ---- 1 回の起動 ----
    task start(input integer h, input integer a, input integer kk, output integer g, output integer fg,
               output integer fw, output integer e, output integer cmin);
        integer i;
        begin
            K = kk; adj = a;
            @(posedge clk_dsp); hold <= 1; dsp_rstn <= 0;
            repeat (8 + h) @(posedge clk_dsp);
            hold <= 0;
            repeat (2) @(posedge clk_dsp);
            dsp_rstn <= 1;
            repeat (RUN) @(posedge clk_dsp);
            g = gaps; fg = first_gap; fw = first_word; e = errs; cmin = gb_stat[21:16];
        end
    endtask

    integer prof, kk, h, a, g, fg, fw, e, cmin, ngap, nerr, nmulti, fwset, bad, runs;
    integer gap_by_phase;
    initial begin
        hold = 1; dsp_rstn = 0; aresetn_adc = 0; adj = 0; K = 0;
        for (h = 0; h < NW; h = h + 1) DLY[h] = 300;
        repeat (20) @(posedge clk_adc);
        aresetn_adc = 1;
        bad = 0;
        for (prof = 0; prof < 5; prof = prof + 1) begin
            for (h = 0; h < NW; h = h + 1) DLY[h] = 300;
            case (prof)
                0: ;
                1: DLY[2] = 300 + 800;
                2: DLY[2] = 300 + 1800;
                3: DLY[0] = 300 + 1800;
                4: begin DLY[0] = 410; DLY[1] = 655; DLY[2] = 1230; DLY[3] = 380; DLY[4] = 920; DLY[5] = 700; end
            endcase
            for (kk = 0; kk <= 4; kk = kk + 4) begin
                ngap = 0; nerr = 0; nmulti = 0; fwset = 0; runs = 0; gap_by_phase = 0;
                for (h = 0; h < 3; h = h + 1)
                    for (a = 0; a < 4; a = a + 1) begin
                        start(h, a, kk, g, fg, fw, e, cmin);
                        runs = runs + 1;
                        if (g > 0) begin ngap = ngap + 1; fwset = fwset | (1 << (fw > 30 ? 30 : fw)); end
                        if (g > 1) nmulti = nmulti + 1;
                        if (e > 0) nerr = nerr + 1;
                        if (g > 0) gap_by_phase = gap_by_phase | (1 << (h * 4 + a));
                    end
                case (prof)
                    0: $write("同じ遅延（300 ps × 6）      ");
                    1: $write("bit 2 だけ +800 ps          ");
                    2: $write("bit 2 だけ +1800 ps         ");
                    3: $write("bit 0 だけ +1800 ps         ");
                    4: $write("ばらばら（410〜1230 ps）   ");
                endcase
                $display(" / K %0d: 途切れた起動 %0d / %0d（2 回以上 %0d）・途切れた語 %b・位相 %012b・通し番号の誤り %0d",
                         kk, ngap, runs, nmulti, fwset[15:0], gap_by_phase[11:0], nerr);
                // 判定
                if (nerr != 0) bad = bad + 1;
                if (nmulti != 0) bad = bad + 1;
                if (prof == 0 && ngap != 0) bad = bad + 1;
                if (prof == 3 && ngap != 0) bad = bad + 1;
                if ((prof == 1 || prof == 2) && kk == 0 && (ngap == 0 || ngap == runs || fwset != (1 << 3))) bad = bad + 1;
                if (prof == 1 && kk == 0 && ngap * 2 > runs) bad = bad + 1;          // 4 位相のうち 1 つ（≒ 800 / 976 を切り下げ）
                if (prof == 2 && kk == 0 && ngap * 4 < runs) bad = bad + 1;          // 4 位相のうち 2 つ
                if (kk == 4 && ngap != 0) bad = bad + 1;
            end
        end
        if (bad == 0) $display("結果: 全部通過");
        else          $display("結果: NG %0d 件", bad);
        $finish;
    end
endmodule
