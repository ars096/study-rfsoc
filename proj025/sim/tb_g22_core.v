// SPDX-License-Identifier: BSD-3-Clause
// tb_g22_core — g22_core の単体（proj024 手順 2d）。入力は 2c と同じ `OUT/x.hex（check_g22.py spec-gen）。T は 0 から、s_axis = x[T]（同じクロック）。
// AXI4-Lite で PS と同じ手順を踏む: SRC 2 → WRST / SHIFT 4・N_ACC 2・N_DUMP 1・CFG_ID・REC_CTRL ALL / TP_N 16・TP_REC_CTRL（4 個で 1 レコード）
//   → PFB が始まったら RUN。SHIFT は RUN で効く（RUN の前と後で RUN_SHIFT を読む）。
// 記録: IP の出口（`OUT/ip.txt）・ダンプ（commit の瞬間に凍った面の記憶 `OUT/dump1.txt）・レコードの出口の全部の語（`OUT/rec.txt。
//   1 行 = {tlast tuser 語}）・レジスタ（`OUT/regs.txt）。m_axis_rec_tready は 1/8 で下げる（s45_ring の止まりの代わり）。
// 判定は check_g22.py core。
`timescale 1ns / 1ps
module tb_g22_core;
    localparam integer NB = 10 * 16384;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rstn = 0;
    reg [63:0] t = 0;
    reg [255:0] d = 0;
    reg v = 0;
    // AXI4-Lite
    reg  [9:0]  awaddr = 0, araddr = 0;
    reg         awvalid = 0, wvalid = 0, arvalid = 0;
    reg  [31:0] wdata = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [1:0]  bresp, rresp;
    wire [31:0] rdata;
    wire [1:0]  src_sel, rec_drop;
    wire [63:0] rec_d;
    wire        rec_v, rec_l, rec_u;
    reg         rec_r = 1;
    wire [1023:0] ip_td;
    wire [13:0] ip_k1;
    wire        ip_v;
    g22_core #(.SID_S(2), .REC_CORE(1), .K_F(0), .ST_N(256), .GF_L2(1), .SHIFT_DEFAULT(7), .TPN_DEFAULT(512), .BUILD_TAG(32'h2024_0d00),
               .LO_FILE(`LO), .HI_FILE(`HI), .TA_FILE(`TA), .TB_FILE(`TB)) u (
        .aclk(clk), .aresetn(rstn), .s_axis_tdata(d), .s_axis_tvalid(v), .s_axis_tready(),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_wdata(wdata), .s_axi_wvalid(wvalid),
        .s_axi_wready(wready), .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rresp(rresp),
        .s_axi_rvalid(rvalid), .s_axi_rready(1'b1),
        .src_sel(src_sel), .t_in(t), .go_in(1'b0), .tev_in(4'd0),
        .m_axis_rec_tdata(rec_d), .m_axis_rec_tvalid(rec_v), .m_axis_rec_tready(rec_r), .m_axis_rec_tlast(rec_l), .m_axis_rec_tuser(rec_u),
        .rec_drop(rec_drop), .dbg_ip_tdata(ip_td), .dbg_ip_k1(ip_k1), .dbg_ip_v(ip_v));

    reg [255:0] xm [0:NB-1];
    integer fi, fr, fg, fdmp, k, ndump = 0, nspec = 0, nrec = 0, ndrop = 0;
    reg [383:0] snap [0:16383];
    always @(posedge clk) t <= t + 1;
    always @(negedge clk) begin d <= (t < NB) ? xm[t] : 256'd0; v <= rstn; end   // NB の後は 0 を流し続ける（途切れにしない）
    always @(negedge clk) rec_r <= ($random % 8) != 0;
    always @(posedge clk) begin
        if (ip_v) $fwrite(fi, "%0d %h\n", ip_k1, ip_td);
        if (rec_v && rec_r) begin
            $fwrite(fr, "%0d %0d %h\n", rec_l, rec_u, rec_d);
            if (rec_l) nrec = nrec + 1;
        end
        if (rstn && rec_drop != 2'b00) ndrop = ndrop + 1;
    end
    // SPEC のレコードの終わり（頭の語 0 の type を見ておく）
    reg in_rec = 0;
    reg [7:0] rtype = 0;
    always @(posedge clk) if (rec_v && rec_r) begin
        if (!in_rec) rtype = rec_d[47:40];
        in_rec = !rec_l;
        if (rec_l && rtype == 8'd1) nspec = nspec + 1;
    end
    // ダンプ: commit の次のクロックで凍った面を写す（2c と同じ）
    always @(posedge clk) if (u.commit) begin
        #0.1;
        for (k = 0; k < 16384; k = k + 1) snap[k] = u.rd_plane ? u.u_spec.u_acc.g_pl[1].mem[k] : u.u_spec.u_acc.g_pl[0].mem[k];
        fdmp = $fopen({`OUT, "/dump1.txt"}, "w");
        $fwrite(fdmp, "# seq %0d dk %0d df0 %0d dn %0d dsat %0d plane %0d f_first %0d\n", u.seq, u.dk, u.df0, u.dn, u.dsat, u.rd_plane, u.u_spec.f_first);
        for (k = 0; k < 16384; k = k + 1) $fwrite(fdmp, "%h\n", snap[k]);
        $fclose(fdmp);
        ndump = ndump + 1;
    end

    // AXI の待ちは !== 1'b1 で（LESSONS: while (!x) は z・x を「準備よし」と読む）
    task axi_wr(input [9:0] a, input [31:0] x);
        begin
            @(negedge clk); awaddr = a; wdata = x; awvalid = 1; wvalid = 1;
            @(posedge clk); while ((awready && wready) !== 1'b1) @(posedge clk);
            @(negedge clk); awvalid = 0; wvalid = 0;
            @(posedge clk); while (bvalid !== 1'b1) @(posedge clk);
        end
    endtask
    reg [31:0] rd_v;
    task axi_rd(input [9:0] a);
        begin
            @(negedge clk); araddr = a; arvalid = 1;
            @(posedge clk); while (arready !== 1'b1) @(posedge clk);
            @(negedge clk); arvalid = 0;
            @(posedge clk); while (rvalid !== 1'b1) @(posedge clk);
            rd_v = rdata;
        end
    endtask
    task reg_log(input [9:0] a, input [8*12-1:0] name);
        begin axi_rd(a); $fwrite(fg, "%0s 0x%03h %h\n", name, a, rd_v); end
    endtask

    initial begin
        $readmemh({`OUT, "/x.hex"}, xm);
        fi = $fopen({`OUT, "/ip.txt"}, "w");
        fr = $fopen({`OUT, "/rec.txt"}, "w");
        fg = $fopen({`OUT, "/regs.txt"}, "w");
        repeat (6) @(posedge clk);
        @(negedge clk); rstn = 1;
        axi_wr(10'h028, 32'd2);              // SRC 2（次の WRST で効く）
        reg_log(10'h028, "SRC_pre");
        axi_wr(10'h02C, 32'h00C0_FFEE);      // CFG_ID
        axi_wr(10'h008, 32'h0000_1000);      // WRST
        reg_log(10'h028, "SRC");
        reg_log(10'h034, "WRST_CFG");
        axi_wr(10'h014, 32'd4);              // SHIFT 4（RUN で効く）
        axi_wr(10'h00C, 32'd2);              // N_ACC
        axi_wr(10'h010, 32'd1);              // N_DUMP
        axi_wr(10'h084, 32'd1);              // REC_CTRL ALL
        axi_wr(10'h100, 32'd16);             // TP_N 16 小フレーム（= 0.5 フレーム）
        axi_wr(10'h11C, 32'h0000_0401);      // TP_REC_CTRL: 4 個で 1 レコード・出す
        reg_log(10'h038, "RUN_SHIFT0");      // RUN の前: 既定 7
        wait (u.u_spec.have_first);
        axi_wr(10'h008, 32'h0000_0001);      // RUN
        reg_log(10'h038, "RUN_SHIFT1");      // RUN の後: 4
        reg_log(10'h068, "RUN_F0");
        reg_log(10'h10C, "TP_F0");
        reg_log(10'h104, "TP_NEFF");
        wait (nspec == 1);
        repeat (40000) @(posedge clk);       // TP のレコードをもう少し
        reg_log(10'h000, "SID");
        reg_log(10'h004, "PARAM");
        reg_log(10'h008, "CTRL");
        reg_log(10'h018, "FLAGS");
        reg_log(10'h01C, "SEQ");
        reg_log(10'h020, "NCH");
        reg_log(10'h024, "FRAME_BEATS");
        reg_log(10'h03C, "DUMP_K");
        reg_log(10'h040, "DUMP_F0");
        reg_log(10'h048, "DUMP_N");
        reg_log(10'h04C, "DUMP_SAT");
        reg_log(10'h050, "DUMP_T_LO");
        reg_log(10'h054, "DUMP_T_HI");
        reg_log(10'h058, "DUMP_H");
        reg_log(10'h05C, "DUMP_CFG");
        reg_log(10'h080, "NFFT_MM");
        reg_log(10'h084, "REC_CTRL");
        reg_log(10'h088, "REC_LATE");
        reg_log(10'h120, "TP_REC_LATE");
        reg_log(10'h208, "BUILD_TAG");
        $fclose(fi); $fclose(fr); $fclose(fg);
        $display("tb_g22_core: ダンプ %0d・SPEC のレコード %0d・レコード %0d・src_sel %0d・rec_drop のクロック %0d・flags %h",
                 ndump, nspec, nrec, src_sel, ndrop, u.flags);
        $finish;
    end
    initial begin #(3.906 * 40 * 16384); $display("tb_g22_core: 時間切れ（ダンプ %0d・SPEC のレコード %0d）", ndump, nspec); $finish; end
endmodule
