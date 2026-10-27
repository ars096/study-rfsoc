// SPDX-License-Identifier: BSD-3-Clause
// tb_g24_x4 — 2G-4 のコア 4 個（proj027 手順 2e-2。proj025 の tb_g22_x2（2 コア）を 4 コアに）。ブロックデザインと同じく s45_core_0〜3 を並べ（**4 個とも RAW = 1**、F-5）、
// FULL の口はコアごとの axis_sel4（出口 1 段）。**4 コアとも SRC 2（同じ ADC）**にして、凍った面（ダンプの中身）がコア 0 と bit 単位で同じになることを見る
// （F-4 の「複数のコアに同じ ADC = 同等の陽性対照」の sim 版）。あわせて 4 コアとも RAW の流れのブロックを持つこと（NSTREAM 2・SID1）と、
// RAW の SRC をコアごとに違う値（コア c に c）で書いて raw_sel がそれぞれに出ること（RAW はコアごと、F-5）を読む。
// ADC 0・1・3 は tb_g24_s45 と同じ式、ADC 2 は 2c の x.hex。設定は 4 コアとも WRST・SHIFT 4・N_ACC 2・N_DUMP 1 → PFB が始まったら RUN を
// コア 0 → 3 の順に（AXI の書きは十数クロック × 4。格子 2 フレーム（GF_L2 1、8192 ビート）の中なので同じ F0 になるはず。違えば「F0 違い」として別に出す）。
//   -DX4_DLY: コア 3 の FULL の口に 1 段多く入れる（陽性対照: サンプルが 1 ビートずれ、コア 3 のダンプだけが違うはず）
// 判定は tb の中で（最後の「結果:」の行）。
`timescale 1ns / 1ps
module tb_g24_x4;
    localparam integer NB = 12 * 4096;   // tb_g24_spec と同じ x.hex（12 フレーム）
    localparam integer M  = 4096;
    localparam integer NC = 4;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rstn = 0;
    reg [63:0] t = 0;
    reg [255:0] a0 = 0, a1 = 0, a2 = 0, a3 = 0;
    reg v = 0;

    function [15:0] smp(input [1:0] adc, input [63:0] tt, input integer p);
        reg [31:0] n, h;
        begin
            n = tt[27:0] * 16 + p;
            h = (n * 32'h9E37_79B1) ^ ({30'd0, adc} << 20);
            smp = {h[30:17], 2'b00};
        end
    endfunction
    reg [255:0] xm [0:NB-1];
    integer p;
    always @(posedge clk) t <= t + 1;
    always @(negedge clk) begin
        for (p = 0; p < 16; p = p + 1) begin
            a0[16*p +: 16] <= smp(2'd0, t, p);
            a1[16*p +: 16] <= smp(2'd1, t, p);
            a3[16*p +: 16] <= smp(2'd3, t, p);
        end
        a2 <= (t < NB) ? xm[t] : 256'd0;
        v  <= rstn;
    end

    // ---- AXI4-Lite（コアごとに口。tb の task が c で選ぶ）----
    reg  [15:0] awaddr = 0, araddr = 0;
    reg  [31:0] wdata = 0;
    reg         awv = 0, wv = 0, arv = 0;
    reg  [1:0]  csel = 0;
    wire [NC-1:0] awready, wready, bvalid, arready, rvalid;
    wire [31:0] rdata [0:NC-1];
    wire [1:0]  fsel [0:NC-1];
    wire [1:0]  rsel [0:NC-1];
    wire [255:0] f_d [0:NC-1];
    wire [NC-1:0] f_v;
    wire [NC-1:0] commit;

    genvar c;
    // proj031: 共有の係数（sim だけの源 cu_src。中身は g24_cu）。番地は s45_core_0、出口は 4 コアへ同じものを配る（ブロックデザインと同じ）
    wire [11:0] cu_a; wire cu_av; wire [1151:0] cu_c; wire [11:0] cu_m; wire cu_v, cu_ok;
    cu_src u_cu (.clk(clk), .rst(~rstn), .addr(cu_a), .addr_v(cu_av), .coef(cu_c), .m_out(cu_m), .v_out(cu_v), .ok_out(cu_ok));
    generate
        for (c = 0; c < NC; c = c + 1) begin : g_c
            wire [255:0] sd;
            wire         sv;
            axis_sel4 u_fsel (.aclk(clk), .aresetn(rstn),
                .s0_axis_tdata(a0), .s0_axis_tvalid(v), .s0_axis_tready(), .s1_axis_tdata(a1), .s1_axis_tvalid(v), .s1_axis_tready(),
                .s2_axis_tdata(a2), .s2_axis_tvalid(v), .s2_axis_tready(), .s3_axis_tdata(a3), .s3_axis_tvalid(v), .s3_axis_tready(),
                .m_axis_tdata(sd), .m_axis_tvalid(sv), .m_axis_tready(1'b1), .sel(fsel[c]),
                .gb_stat0(32'd0), .gb_stat1(32'd0), .gb_stat2(32'd0), .gb_stat3(32'd0),
                .adc_stat0(32'd0), .adc_stat1(32'd0), .adc_stat2(32'd0), .adc_stat3(32'd0), .gb_stat_o(), .adc_stat_o());
`ifdef X4_DLY
            reg [255:0] dd = 0;
            reg         dv = 0;
            always @(posedge clk) begin dd <= sd; dv <= sv; end
            assign f_d[c] = (c == 3) ? dd : sd;
            assign f_v[c] = (c == 3) ? dv : sv;
`else
            assign f_d[c] = sd;
            assign f_v[c] = sv;
`endif
            wire [11:0] ca; wire cav;
            if (c == 0) begin : g_a
                assign cu_a = ca; assign cu_av = cav;
            end
            g24_s45_core #(.BUILD_TAG(32'h2027_0e00 + c), .CORE_PORT(c), .RAW(1), .K_F(0), .ST_N(256), .GF_L2(1), .SHIFT_DEFAULT(7),
                           .TA_FILE(`TA), .TB_FILE(`TB)) u (
                .aclk(clk), .aresetn(rstn),
                .coef_addr(ca), .coef_addr_v(cav), .coef_in(cu_c), .coef_m_in(cu_m), .coef_ok_in(cu_ok),
                .s_axis_tdata(c == 0 ? a0 : c == 1 ? a1 : c == 2 ? a2 : a3), .s_axis_tvalid(v), .s_axis_tready(),
                .s_axis_full_tdata(f_d[c]), .s_axis_full_tvalid(f_v[c]), .s_axis_full_tready(), .full_sel(fsel[c]),
                .s_axis_raw_tdata(256'd0), .s_axis_raw_tvalid(v), .s_axis_raw_tready(), .raw_sel(rsel[c]),
                .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awv && csel == c), .s_axi_awready(awready[c]),
                .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wv && csel == c), .s_axi_wready(wready[c]), .s_axi_bresp(),
                .s_axi_bvalid(bvalid[c]), .s_axi_bready(1'b1),
                .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arv && csel == c), .s_axi_arready(arready[c]),
                .s_axi_rdata(rdata[c]), .s_axi_rresp(), .s_axi_rvalid(rvalid[c]), .s_axi_rready(1'b1),
                .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(32'd0), .adc_stat(32'd0),
                .t_in(t), .go_in(1'b0), .tev_in(4'd0),
                .m_axis_rec_tdata(), .m_axis_rec_tvalid(), .m_axis_rec_tready(1'b1), .m_axis_rec_tlast(), .m_axis_rec_tuser(),
                .rec_drop());
            assign commit[c] = u.u_full.commit;
        end
    endgenerate

    // ---- ダンプ: commit の次のクロックで凍った面を写す（コアごと）----
    reg [383:0] snap [0:NC-1][0:M-1];
    integer k, nd [0:NC-1];
    reg [47:0] f0 [0:NC-1];
    initial for (k = 0; k < NC; k = k + 1) begin nd[k] = 0; f0[k] = 0; end
    generate
        for (c = 0; c < NC; c = c + 1) begin : g_d
            integer kk;
            always @(posedge clk) if (commit[c]) begin
                #0.1;
                for (kk = 0; kk < M; kk = kk + 1)
                    snap[c][kk] = g_c[c].u.u_full.rd_plane ? g_c[c].u.u_full.u_spec.u_acc.g_pl[1].mem[kk] : g_c[c].u.u_full.u_spec.u_acc.g_pl[0].mem[kk];
                f0[c] = g_c[c].u.u_full.df0; nd[c] = nd[c] + 1;
            end
        end
    endgenerate

    // AXI の待ちは !== 1'b1 で（LESSONS）
    task axi_wr(input [1:0] cc, input [15:0] a, input [31:0] x);
        begin
            @(negedge clk); csel = cc; awaddr = a; wdata = x; awv = 1; wv = 1;
            @(posedge clk); while ((awready[cc] && wready[cc]) !== 1'b1) @(posedge clk);
            @(negedge clk); awv = 0; wv = 0;
            @(posedge clk); while (bvalid[cc] !== 1'b1) @(posedge clk);
        end
    endtask
    reg [31:0] rd_v;
    task axi_rd(input [1:0] cc, input [15:0] a);
        begin
            @(negedge clk); csel = cc; araddr = a; arv = 1;
            @(posedge clk); while (arready[cc] !== 1'b1) @(posedge clk);
            @(negedge clk); arv = 0;
            @(posedge clk); while (rvalid[cc] !== 1'b1) @(posedge clk);
            rd_v = rdata[cc];
        end
    endtask
    // レジスタの照合: 読んだ値を期待と比べ、違えば数える
    integer nreg_bad = 0;
    task reg_chk(input [1:0] cc, input [15:0] a, input [31:0] e, input [8*24-1:0] name);
        begin
            axi_rd(cc, a);
            $display("tb_g24_x4: コア %0d %0s（0x%04h）= %h（期待 %h）%0s", cc, name, a, rd_v, e, (rd_v === e) ? "" : " ← 違う");
            if (rd_v !== e) nreg_bad = nreg_bad + 1;
        end
    endtask

    integer cc, nmis [0:NC-1], first_mis [0:NC-1], ok, f0_same;
    initial begin
        $readmemh({`OUT, "/x.hex"}, xm);
        repeat (6) @(posedge clk);
        @(negedge clk); rstn = 1;
        repeat (8) @(posedge clk);
        // 4 コアとも同じ ID・RAW の流れのブロックを持つ（INTERFACE 2.4・2.5）。CORE_PORT はコアの番号
        for (cc = 0; cc < NC; cc = cc + 1) begin
            reg_chk(cc, 16'h0000, 32'h0203_0101, "IF_ID");
            reg_chk(cc, 16'h0004, 32'h0031_0200, "PROJ");
            reg_chk(cc, 16'h0008, 32'd2, "NSTREAM");
            reg_chk(cc, 16'h0018, cc, "CORE_PORT");
            reg_chk(cc, 16'h4000, 32'h0201_0000, "SID0");
            reg_chk(cc, 16'h4400, 32'h0204_0100, "SID1(RAW)");
            reg_chk(cc, 16'h4020, 32'd32768, "NCH0");
        end
        for (cc = 0; cc < NC; cc = cc + 1) begin
            axi_wr(cc, 16'h4028, 32'd2);             // SRC 2（同じ ADC）
            axi_wr(cc, 16'h4008, 32'h0000_1000);     // WRST
            axi_wr(cc, 16'h4014, 32'd4);             // SHIFT 4
            axi_wr(cc, 16'h400C, 32'd2);             // N_ACC
            axi_wr(cc, 16'h4010, 32'd1);             // N_DUMP
            axi_wr(cc, 16'h4428, cc);                // RAW の SRC をコアごとに違う値で（コア c に c）
            axi_wr(cc, 16'h4408, 32'h0000_1000);     // RAW の WRST（SRC を取り込む）
        end
        for (cc = 0; cc < NC; cc = cc + 1) begin
            reg_chk(cc, 16'h4028, 32'h8000_0002, "SRC0");
            reg_chk(cc, 16'h4428, 32'h8000_0000 | cc, "SRC1(RAW)");
        end
        wait (g_c[0].u.u_full.u_spec.have_first && g_c[1].u.u_full.u_spec.have_first &&
              g_c[2].u.u_full.u_spec.have_first && g_c[3].u.u_full.u_spec.have_first);
        for (cc = 0; cc < NC; cc = cc + 1) axi_wr(cc, 16'h4008, 32'h0000_0001);   // RUN（コア 0 → 3）
        wait (nd[0] == 1 && nd[1] == 1 && nd[2] == 1 && nd[3] == 1);
        repeat (20) @(posedge clk);
        f0_same = 1;
        for (cc = 1; cc < NC; cc = cc + 1) begin
            nmis[cc] = 0; first_mis[cc] = -1;
            for (k = 0; k < M; k = k + 1)
                if (snap[0][k] !== snap[cc][k]) begin nmis[cc] = nmis[cc] + 1; if (first_mis[cc] < 0) first_mis[cc] = k; end
            if (f0[cc] != f0[0]) f0_same = 0;
        end
`ifdef TB_CU_CLR
        // proj031 rev 2: OK を落とした後（TB_CU_DROP）。立った coef_mis を flags_clr（CTRL の bit 8、PS の START と同じ）で消す。
        // OK を戻してあれば（TB_CU_BACK）0 に戻るべき、戻していなければ次の拍にまた立つべき（陽性対照）
        for (cc = 0; cc < NC; cc = cc + 1) reg_chk(cc, 16'h4018, 32'd1, "FLAGS0 pre-clr");
        for (cc = 0; cc < NC; cc = cc + 1) axi_wr(cc, 16'h4008, 32'h0000_0100);
        repeat (50) @(posedge clk);
        for (cc = 0; cc < NC; cc = cc + 1) reg_chk(cc, 16'h4018, 32'd0, "FLAGS0 post-clr");
`else
        for (cc = 0; cc < NC; cc = cc + 1) reg_chk(cc, 16'h4018, 32'd0, "FLAGS0");
`endif
        $display("tb_g24_x4: ダンプ %0d・%0d・%0d・%0d・DUMP_F0 %0d・%0d・%0d・%0d・full_sel %0d・%0d・%0d・%0d・raw_sel %0d・%0d・%0d・%0d",
                 nd[0], nd[1], nd[2], nd[3], f0[0], f0[1], f0[2], f0[3], fsel[0], fsel[1], fsel[2], fsel[3], rsel[0], rsel[1], rsel[2], rsel[3]);
        $display("tb_g24_x4: コア 0 と違う行（/ %0d）: コア 1 %0d（最初 %0d）・コア 2 %0d（最初 %0d）・コア 3 %0d（最初 %0d）・レジスタの違い %0d",
                 M, nmis[1], first_mis[1], nmis[2], first_mis[2], nmis[3], first_mis[3], nreg_bad);
        if (!f0_same) $display("tb_g24_x4: F0 違い（RUN が格子を跨いだ。tb の作り。判定できない）");
        ok = f0_same && (nmis[1] == 0) && (nmis[2] == 0) && (nmis[3] == 0) && (nreg_bad == 0)
             && fsel[0] == 2 && fsel[1] == 2 && fsel[2] == 2 && fsel[3] == 2
             && rsel[0] == 0 && rsel[1] == 1 && rsel[2] == 2 && rsel[3] == 3;
        // 三項演算子に長さの違う文字列を渡すと、短いほうの頭に 0 が詰まって化ける（proj025 で踏んだ）。if で分ける
        if (ok) $display("結果: 全部通過"); else $display("結果: 不合格");
        $finish;
    end
    initial begin #(3.906 * 24 * 4096); $display("tb_g24_x4: 時間切れ（ダンプ %0d・%0d・%0d・%0d）", nd[0], nd[1], nd[2], nd[3]); $display("結果: 不合格"); $finish; end
endmodule
