// SPDX-License-Identifier: BSD-3-Clause
// tb_g24_s45 — g24_s45_core の単体（proj027 手順 2e。proj025 の tb_g22_s45 を 2G-4 の長さに。コア 0 の 1 個だけ）。ブロックデザインと同じく、ADC 4 本・axis_sel4 × 2（FULL と RAW、出口 1 段）を外に置く。
// ADC: 0・1・3 は式（check_g24.py の adc_x と同じ）、2 は 2c の x.hex（T < NB、その後は 0）。コアの ADC は 0（s_axis は直に）。
// AXI4-Lite（コアの 16 bit の番地）で: 共通・流れのブロックの読み / RAW: SRC 1 → WRST・N_ACC 64・N_DUMP 2・REC ALL → RUN /
//   FULL: SRC 2 → WRST・SHIFT 4・N_ACC 2・N_DUMP 1・REC ALL・TP_N 8・TP_REC 4 個 / コアの TP: TP_N 8・TP_REC 4 個・TP_RUN →
//   PFB が始まったら FULL の RUN。SPEC のレコードが出たら 40,000 クロック待ってレジスタを読む。
// 記録: IP の出口（ip.txt）・ダンプ（dump1.txt）・レコード（rec.txt）・レジスタ（regs.txt）・rec_drop の和。判定は check_g24.py s45
`timescale 1ns / 1ps
module tb_g24_s45;
    localparam integer NB = 12 * 4096;   // proj027: 10 → 12 フレーム（2 個目のダンプの後の 4200 クロックの待ちの間に入力が尽きないように。2G-2 の 10 フレームは 2G-4 では 1 フレーム足りない）
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rstn = 0;
    reg [63:0] t = 0;
    reg [255:0] a0 = 0, a1 = 0, a2 = 0, a3 = 0;
    reg v = 0;
    reg  [15:0] awaddr = 0, araddr = 0;
    reg         awvalid = 0, wvalid = 0, arvalid = 0;
    reg  [31:0] wdata = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [31:0] rdata;
    wire [1:0]  full_sel, raw_sel, rec_drop;
    wire [63:0] rec_d;
    wire        rec_v, rec_l, rec_u;
    reg         rec_r = 1;
    wire [255:0] f_d, r_d;
    wire         f_v, r_v;

    // ---- ADC 0・1・3 の式（check_g24.py の adc_x と同じ）: n = 16·T + p、32 bit で n·0x9E3779B1 ^ (adc << 20) の [30:17] を 14 bit の符号つきに ----
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

    // ---- axis_sel4 × 2（ブロックデザインと同じ）----
    axis_sel4 u_fsel (.aclk(clk), .aresetn(rstn),
        .s0_axis_tdata(a0), .s0_axis_tvalid(v), .s0_axis_tready(), .s1_axis_tdata(a1), .s1_axis_tvalid(v), .s1_axis_tready(),
        .s2_axis_tdata(a2), .s2_axis_tvalid(v), .s2_axis_tready(), .s3_axis_tdata(a3), .s3_axis_tvalid(v), .s3_axis_tready(),
        .m_axis_tdata(f_d), .m_axis_tvalid(f_v), .m_axis_tready(1'b1), .sel(full_sel),
        .gb_stat0(32'd0), .gb_stat1(32'd0), .gb_stat2(32'd0), .gb_stat3(32'd0),
        .adc_stat0(32'd0), .adc_stat1(32'd0), .adc_stat2(32'd0), .adc_stat3(32'd0), .gb_stat_o(), .adc_stat_o());
    axis_sel4 u_rsel (.aclk(clk), .aresetn(rstn),
        .s0_axis_tdata(a0), .s0_axis_tvalid(v), .s0_axis_tready(), .s1_axis_tdata(a1), .s1_axis_tvalid(v), .s1_axis_tready(),
        .s2_axis_tdata(a2), .s2_axis_tvalid(v), .s2_axis_tready(), .s3_axis_tdata(a3), .s3_axis_tvalid(v), .s3_axis_tready(),
        .m_axis_tdata(r_d), .m_axis_tvalid(r_v), .m_axis_tready(1'b1), .sel(raw_sel),
        .gb_stat0(32'd0), .gb_stat1(32'd0), .gb_stat2(32'd0), .gb_stat3(32'd0),
        .adc_stat0(32'd0), .adc_stat1(32'd0), .adc_stat2(32'd0), .adc_stat3(32'd0), .gb_stat_o(), .adc_stat_o());

    g24_s45_core #(.BUILD_TAG(32'h2024_0e00), .CORE_PORT(0), .K_F(0), .ST_N(256), .GF_L2(1), .SHIFT_DEFAULT(7),
                   .LO_FILE(`LO), .HI_FILE(`HI), .TA_FILE(`TA), .TB_FILE(`TB)) u (
        .aclk(clk), .aresetn(rstn),
        .s_axis_tdata(a0), .s_axis_tvalid(v), .s_axis_tready(),
        .s_axis_full_tdata(f_d), .s_axis_full_tvalid(f_v), .s_axis_full_tready(), .full_sel(full_sel),
        .s_axis_raw_tdata(r_d), .s_axis_raw_tvalid(r_v), .s_axis_raw_tready(), .raw_sel(raw_sel),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wvalid), .s_axi_wready(wready), .s_axi_bresp(),
        .s_axi_bvalid(bvalid), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(), .s_axi_rvalid(rvalid), .s_axi_rready(1'b1),
        .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(32'd0), .adc_stat(32'd0),
        .t_in(t), .go_in(1'b0), .tev_in(4'd0),
        .m_axis_rec_tdata(rec_d), .m_axis_rec_tvalid(rec_v), .m_axis_rec_tready(rec_r), .m_axis_rec_tlast(rec_l), .m_axis_rec_tuser(rec_u),
        .rec_drop(rec_drop));

    integer fi, fr, fg, fdmp, k, ndump = 0, nspec = 0, nrec = 0, ndrop = 0;
    reg [383:0] snap [0:4095];
    always @(negedge clk) rec_r <= ($random % 8) != 0;
    always @(posedge clk) begin
        if (u.u_full.dbg_ip_v) $fwrite(fi, "%0d %h\n", u.u_full.dbg_ip_k1, u.u_full.dbg_ip_tdata);
        if (rec_v && rec_r) begin
            $fwrite(fr, "%0d %0d %h\n", rec_l, rec_u, rec_d);
            if (rec_l) nrec = nrec + 1;
        end
        if (rstn) ndrop = ndrop + rec_drop;
    end
    reg in_rec = 0;
    reg [7:0] rtype = 0;
    always @(posedge clk) if (rec_v && rec_r) begin
        if (!in_rec) rtype = rec_d[47:40];
        in_rec = !rec_l;
        if (rec_l && rtype == 8'd1) nspec = nspec + 1;
    end
    always @(posedge clk) if (u.u_full.commit) begin
        #0.1;
        for (k = 0; k < 4096; k = k + 1)
            snap[k] = u.u_full.rd_plane ? u.u_full.u_spec.u_acc.g_pl[1].mem[k] : u.u_full.u_spec.u_acc.g_pl[0].mem[k];
        fdmp = $fopen({`OUT, "/dump1.txt"}, "w");
        $fwrite(fdmp, "# seq %0d dk %0d df0 %0d dn %0d dsat %0d plane %0d f_first %0d\n",
                u.u_full.seq, u.u_full.dk, u.u_full.df0, u.u_full.dn, u.u_full.dsat, u.u_full.rd_plane, u.u_full.u_spec.f_first);
        for (k = 0; k < 4096; k = k + 1) $fwrite(fdmp, "%h\n", snap[k]);
        $fclose(fdmp);
        ndump = ndump + 1;
    end

    // AXI の待ちは !== 1'b1 で（LESSONS）
    task axi_wr(input [15:0] a, input [31:0] x);
        begin
            @(negedge clk); awaddr = a; wdata = x; awvalid = 1; wvalid = 1;
            @(posedge clk); while ((awready && wready) !== 1'b1) @(posedge clk);
            @(negedge clk); awvalid = 0; wvalid = 0;
            @(posedge clk); while (bvalid !== 1'b1) @(posedge clk);
        end
    endtask
    reg [31:0] rd_v;
    task axi_rd(input [15:0] a);
        begin
            @(negedge clk); araddr = a; arvalid = 1;
            @(posedge clk); while (arready !== 1'b1) @(posedge clk);
            @(negedge clk); arvalid = 0;
            @(posedge clk); while (rvalid !== 1'b1) @(posedge clk);
            rd_v = rdata;
        end
    endtask
    task reg_log(input [15:0] a, input [8*14-1:0] name);
        begin axi_rd(a); $fwrite(fg, "%0s 0x%04h %h\n", name, a, rd_v); end
    endtask

    initial begin
        $readmemh({`OUT, "/x.hex"}, xm);
        fi = $fopen({`OUT, "/ip.txt"}, "w");
        fr = $fopen({`OUT, "/rec.txt"}, "w");
        fg = $fopen({`OUT, "/regs.txt"}, "w");
        repeat (6) @(posedge clk);
        @(negedge clk); rstn = 1;
        repeat (8) @(posedge clk);
        reg_log(16'h0000, "IF_ID");
        reg_log(16'h0004, "PROJ");
        reg_log(16'h0008, "NSTREAM");
        reg_log(16'h0080, "FFT_N");
        reg_log(16'h4000, "SID0");
        reg_log(16'h4400, "SID1");
        reg_log(16'h4800, "SID_none");
        reg_log(16'h4020, "NCH0");
        reg_log(16'h4420, "NCH1");
        // RAW（s 1）: ADC 1
        axi_wr(16'h4428, 32'd1);
        axi_wr(16'h4408, 32'h0000_1000);     // WRST
        axi_wr(16'h440C, 32'd64);            // N_ACC 64 フレーム（512 ビート）
        axi_wr(16'h4410, 32'd2);             // N_DUMP 2
        axi_wr(16'h4484, 32'd1);             // REC_CTRL ALL
        axi_wr(16'h4408, 32'h0000_0001);     // RUN
        // FULL（s 0）: ADC 2
        axi_wr(16'h4028, 32'd2);
        axi_wr(16'h4008, 32'h0000_1000);     // WRST
        axi_wr(16'h4014, 32'd4);             // SHIFT 4
        axi_wr(16'h400C, 32'd2);             // N_ACC
        axi_wr(16'h4010, 32'd1);             // N_DUMP
        axi_wr(16'h4084, 32'd1);             // REC_CTRL ALL
        axi_wr(16'h4100, 32'd8);             // FULL の TP_N 8 小フレーム（= 1 フレーム。proj027: 2G-2 の 16 のままだと 2 フレームで、256 KiB の SPEC が塞ぐ間に TP の溜めが溢れず「捨てた」の見張りが立たなかった）
        axi_wr(16'h411C, 32'h0000_0401);     // FULL の TP_REC_CTRL（4 個で 1 レコード）
        // コアの TP（ADC 0）
        axi_wr(16'h0100, 32'd8);             // コアの TP_N も 8
        axi_wr(16'h011C, 32'h0000_0401);
        axi_wr(16'h0020, 32'h0000_0001);     // TP_RUN
        reg_log(16'h4028, "SRC0");
        reg_log(16'h4428, "SRC1");
        wait (u.u_full.u_spec.have_first);
        axi_wr(16'h4008, 32'h0000_0001);     // FULL の RUN
        reg_log(16'h4068, "RUN_F0_0");
        reg_log(16'h410C, "TP_F0_0");
        wait (nspec == 1);
        repeat (40000) @(posedge clk);
        reg_log(16'h4018, "FLAGS0");
        reg_log(16'h401C, "SEQ0");
        reg_log(16'h4088, "REC_LATE0");
        reg_log(16'h4120, "TP_REC_LATE0");
        reg_log(16'h441C, "SEQ1");
        reg_log(16'h4418, "FLAGS1");
        reg_log(16'h4488, "REC_LATE1");
        reg_log(16'h0120, "TP_REC_LATEc");
        reg_log(16'h0108, "TP_WPc");
        $fclose(fi); $fclose(fr); $fclose(fg);
        $display("tb_g24_s45: ダンプ %0d・SPEC のレコード %0d・レコード %0d・full_sel %0d・raw_sel %0d・rec_drop の和 %0d・flags %h",
                 ndump, nspec, nrec, full_sel, raw_sel, ndrop, u.u_full.flags);
        $finish;
    end
    initial begin #(3.906 * 40 * 4096); $display("tb_g24_s45: 時間切れ（ダンプ %0d・SPEC のレコード %0d）", ndump, nspec); $finish; end
endmodule
