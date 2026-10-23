// SPDX-License-Identifier: BSD-3-Clause
// tb_g24_x2 — 2G-2 のコア 2 個（proj025 手順 2e-2）。ブロックデザインと同じく s45_core_0（RAW = 1）・s45_core_1（RAW = 0）を並べ、
// FULL の口はコアごとの axis_sel4（出口 1 段）。**2 コアとも SRC 2（同じ ADC）**にして、凍った面（ダンプの中身）が bit 単位で同じになることを見る
// （E-4 の「2 コアに同じ ADC = 同等の陽性対照」の sim 版）。あわせて RAW = 0 のコアの形（NSTREAM 1・0x4400 の流れのブロックが 0・raw_sel 0）を読む。
// ADC 0・1・3 は tb_g24_s45 と同じ式、ADC 2 は 2c の x.hex。設定は 2 コアとも WRST・SHIFT 4・N_ACC 2・N_DUMP 1 → PFB が始まったら RUN を
// コア 0、コア 1 の順に（AXI の書きは十数クロック。格子 2 フレーム（GF_L2 1）の中なので同じ F0 になるはず。違えば「F0 違い」として別に出す）。
//   -DX2_DLY: コア 1 の FULL の口に 1 段多く入れる（陽性対照: サンプルが 1 ビートずれ、ダンプが違うはず）
// 判定は tb の中で（最後の「結果:」の行）。
`timescale 1ns / 1ps
module tb_g24_x2;
    localparam integer NB = 10 * 8192;
    localparam integer M  = 8192;
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
    reg         csel = 0;
    wire [1:0]  awready, wready, bvalid, arready, rvalid;
    wire [31:0] rdata [0:1];
    wire [1:0]  fsel [0:1];
    wire [1:0]  rsel [0:1];
    wire [255:0] f_d [0:1];
    wire [1:0]   f_v;
    wire [1:0]   commit;

    genvar c;
    generate
        for (c = 0; c < 2; c = c + 1) begin : g_c
            wire [255:0] sd;
            wire         sv;
            axis_sel4 u_fsel (.aclk(clk), .aresetn(rstn),
                .s0_axis_tdata(a0), .s0_axis_tvalid(v), .s0_axis_tready(), .s1_axis_tdata(a1), .s1_axis_tvalid(v), .s1_axis_tready(),
                .s2_axis_tdata(a2), .s2_axis_tvalid(v), .s2_axis_tready(), .s3_axis_tdata(a3), .s3_axis_tvalid(v), .s3_axis_tready(),
                .m_axis_tdata(sd), .m_axis_tvalid(sv), .m_axis_tready(1'b1), .sel(fsel[c]),
                .gb_stat0(32'd0), .gb_stat1(32'd0), .gb_stat2(32'd0), .gb_stat3(32'd0),
                .adc_stat0(32'd0), .adc_stat1(32'd0), .adc_stat2(32'd0), .adc_stat3(32'd0), .gb_stat_o(), .adc_stat_o());
`ifdef X2_DLY
            reg [255:0] dd = 0;
            reg         dv = 0;
            always @(posedge clk) begin dd <= sd; dv <= sv; end
            assign f_d[c] = (c == 1) ? dd : sd;
            assign f_v[c] = (c == 1) ? dv : sv;
`else
            assign f_d[c] = sd;
            assign f_v[c] = sv;
`endif
            g24_s45_core #(.BUILD_TAG(32'h2025_0e00 + c), .CORE_PORT(c), .RAW(c == 0 ? 1 : 0), .K_F(0), .ST_N(256), .GF_L2(1), .SHIFT_DEFAULT(7),
                           .LO_FILE(`LO), .HI_FILE(`HI), .TA_FILE(`TA), .TB_FILE(`TB)) u (
                .aclk(clk), .aresetn(rstn),
                .s_axis_tdata(c == 0 ? a0 : a1), .s_axis_tvalid(v), .s_axis_tready(),
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
    reg [383:0] snap0 [0:M-1];
    reg [383:0] snap1 [0:M-1];
    integer k, nd0 = 0, nd1 = 0;
    reg [47:0] f00 = 0, f01 = 0;
    always @(posedge clk) if (commit[0]) begin
        #0.1;
        for (k = 0; k < M; k = k + 1)
            snap0[k] = g_c[0].u.u_full.rd_plane ? g_c[0].u.u_full.u_spec.u_acc.g_pl[1].mem[k] : g_c[0].u.u_full.u_spec.u_acc.g_pl[0].mem[k];
        f00 = g_c[0].u.u_full.df0; nd0 = nd0 + 1;
    end
    always @(posedge clk) if (commit[1]) begin
        #0.1;
        for (k = 0; k < M; k = k + 1)
            snap1[k] = g_c[1].u.u_full.rd_plane ? g_c[1].u.u_full.u_spec.u_acc.g_pl[1].mem[k] : g_c[1].u.u_full.u_spec.u_acc.g_pl[0].mem[k];
        f01 = g_c[1].u.u_full.df0; nd1 = nd1 + 1;
    end

    // AXI の待ちは !== 1'b1 で（LESSONS）
    task axi_wr(input cc, input [15:0] a, input [31:0] x);
        begin
            @(negedge clk); csel = cc; awaddr = a; wdata = x; awv = 1; wv = 1;
            @(posedge clk); while ((awready[cc] && wready[cc]) !== 1'b1) @(posedge clk);
            @(negedge clk); awv = 0; wv = 0;
            @(posedge clk); while (bvalid[cc] !== 1'b1) @(posedge clk);
        end
    endtask
    reg [31:0] rd_v;
    task axi_rd(input cc, input [15:0] a);
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
    task reg_chk(input cc, input [15:0] a, input [31:0] e, input [8*24-1:0] name);
        begin
            axi_rd(cc, a);
            $display("tb_g24_x2: コア %0d %0s（0x%04h）= %h（期待 %h）%0s", cc, name, a, rd_v, e, (rd_v === e) ? "" : " ← 違う");
            if (rd_v !== e) nreg_bad = nreg_bad + 1;
        end
    endtask

    integer cc, nmis, first_mis, ok;
    initial begin
        $readmemh({`OUT, "/x.hex"}, xm);
        repeat (6) @(posedge clk);
        @(negedge clk); rstn = 1;
        repeat (8) @(posedge clk);
        // RAW = 0 のコアの形（INTERFACE 2.4・2.5）と、コア 0 との違い
        reg_chk(0, 16'h0000, 32'h020A_0101, "IF_ID");
        reg_chk(1, 16'h0000, 32'h020A_0101, "IF_ID");
        reg_chk(0, 16'h0004, 32'h0025_0100, "PROJ");
        reg_chk(1, 16'h0004, 32'h0025_0100, "PROJ");
        reg_chk(0, 16'h0008, 32'd2, "NSTREAM");
        reg_chk(1, 16'h0008, 32'd1, "NSTREAM");
        reg_chk(0, 16'h0018, 32'd0, "CORE_PORT");
        reg_chk(1, 16'h0018, 32'd1, "CORE_PORT");
        reg_chk(1, 16'h4000, 32'h0201_0000, "SID0");
        reg_chk(1, 16'h4400, 32'd0, "SID1(なし)");
        reg_chk(1, 16'h4420, 32'd0, "NCH1(なし)");
        reg_chk(1, 16'h4020, 32'd65536, "NCH0");
        for (cc = 0; cc < 2; cc = cc + 1) begin
            axi_wr(cc, 16'h4028, 32'd2);             // SRC 2（同じ ADC）
            axi_wr(cc, 16'h4008, 32'h0000_1000);     // WRST
            axi_wr(cc, 16'h4014, 32'd4);             // SHIFT 4
            axi_wr(cc, 16'h400C, 32'd2);             // N_ACC
            axi_wr(cc, 16'h4010, 32'd1);             // N_DUMP
        end
        // RAW = 0 のコアに RAW の SRC を書いても何も起きない（0x4400– は 0 を返す）
        axi_wr(1, 16'h4428, 32'd3);
        reg_chk(1, 16'h4428, 32'd0, "SRC1(なし)");
        reg_chk(0, 16'h4028, 32'h8000_0002, "SRC0");
        reg_chk(1, 16'h4028, 32'h8000_0002, "SRC0");
        wait (g_c[0].u.u_full.u_spec.have_first && g_c[1].u.u_full.u_spec.have_first);
        axi_wr(0, 16'h4008, 32'h0000_0001);          // RUN（コア 0 → コア 1）
        axi_wr(1, 16'h4008, 32'h0000_0001);
        wait (nd0 == 1 && nd1 == 1);
        repeat (20) @(posedge clk);
        nmis = 0; first_mis = -1;
        for (k = 0; k < M; k = k + 1)
            if (snap0[k] !== snap1[k]) begin nmis = nmis + 1; if (first_mis < 0) first_mis = k; end
        reg_chk(0, 16'h4018, 32'd0, "FLAGS0");
        reg_chk(1, 16'h4018, 32'd0, "FLAGS0");
        $display("tb_g24_x2: ダンプ %0d / %0d・DUMP_F0 %0d / %0d・full_sel %0d / %0d・raw_sel %0d / %0d・2 コアで違う行 %0d / %0d（最初 %0d）・レジスタの違い %0d",
                 nd0, nd1, f00, f01, fsel[0], fsel[1], rsel[0], rsel[1], nmis, M, first_mis, nreg_bad);
        if (f00 != f01) $display("tb_g24_x2: F0 違い（RUN が格子を跨いだ。tb の作り。判定できない）");
        ok = (f00 == f01) && (nmis == 0) && (nreg_bad == 0) && fsel[0] == 2 && fsel[1] == 2 && rsel[1] == 0;
        // 三項演算子に長さの違う文字列を渡すと、短いほうの頭に 0 が詰まって化ける（1 回目に踏んだ）。if で分ける
        if (ok) $display("結果: 全部通過"); else $display("結果: 不合格");
        $finish;
    end
    initial begin #(3.906 * 20 * 8192); $display("tb_g24_x2: 時間切れ（ダンプ %0d / %0d）", nd0, nd1); $display("結果: 不合格"); $finish; end
endmodule
