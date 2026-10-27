// SPDX-License-Identifier: BSD-3-Clause
//
// tb_g24_ds — 2G-4 の FULL の流れの遅れ D_eff = D_S ＋ 1.5·L（INTERFACE 5.2）を出す sim（proj027 4d-2。proj025 の tb_g22_ds を L 4096 に）。proj023 の tb_wide_ds の形
//
// 問い: 同じ ADC のサンプルに、FULL（g24_spec のフレームの区切り T ≡ K_F mod 4096）と RAW（F-2 が adc_to_core を測る道）が付ける T の差
//       D_S = T_full − T_raw（ビート）。2e の予言は +1（FULL は axis_sel4 の 1 段の後で同じクロックの T を付け、RAW は 1 クロック前の T を付ける）。
// 配線はブロックデザインと同じ: ADC 4 本 → axis_sel4 × 2（FULL 用・RAW 用、出口 1 段）→ g24_s45_core。FULL も RAW も SRC 2（ADC_C）。
//   -DDS_POSCTL: FULL の口に ADC 2 を axis_sel4 を通さず直に入れる（陽性対照: D_S が 0 に動き、+1 の判定だけが落ちるはず）
// 刺激: ADC 2 だけ、0 の上に孤立した 1 サンプル（14 bit で A = 8000、レーン p）。ほかの ADC は 0。
//   (i)  RAW の新しいダンプの頭のフレーム（SNAP に写る 512 ビート）の中に 1 個。RAW の T と照らす
//   (ii) その 5 フレーム後より後で、FULL のフレームの位相 m = (T − K_F) mod 4096 が境目（4095・0・4094・1 の順）になる T に 1 個。RAW には写らない
//   RAW の N_ACC は 97 フレーム（49,664 ビート = 12.13 FULL フレーム。2G-2 は 193 = 12.06・2G-1 は 385 = 12.03 フレーム）: (i) と (ii) の PFB の 4 フレームの足が重ならない
// K_F 777（2e は 0。0 でない K_F で、フレームの区切りの位相を確かめる）
// 出力: $(OUT)/imp.txt   「imp T_imp lane kind」（tb が ADC 2 に入れたビートの T。kind 0 = (i)、1 = (ii)）
//       $(OUT)/lanes.txt IP の出口の 0 でない値「r k1 p re im」（r は出口のフレームの通し番号、ラベルは f_first ＋ r）
//       $(OUT)/rec.txt   レコード（tb_g24_s45 と同じ形）/ $(OUT)/meta.txt
// 判定: python3 sim/check_g24.py ds $(OUT) [posctl]
`timescale 1ns / 1ps
module tb_g24_ds;
    localparam integer KF    = 777;
    localparam integer L     = 4096;
    localparam integer NIMP  = `NIMP;              // (i) と (ii) の組の数 × 2
    localparam integer A16   = 8000 * 4;           // 14 bit の 8000 を ADC の 16 bit に
    localparam integer RAWN  = 97;

    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rstn = 0;
    reg [63:0] t = 0;
    always @(posedge clk) t <= t + 1;

    // ---- ADC 2 の刺激: T = t_imp のビートにインパルス（tb_g24_s45 と同じく、negedge で T = t のビートを置く）----
    reg  [63:0]  t_imp [0:1];                      // 0: (i)、1: (ii)
    reg  [3:0]   p_imp [0:1];
    initial begin t_imp[0] = 64'hFFFF_FFFF_FFFF_FFFF; t_imp[1] = 64'hFFFF_FFFF_FFFF_FFFF; p_imp[0] = 0; p_imp[1] = 0; end
    reg [255:0] a2 = 0;
    reg v = 0;
    always @(negedge clk) begin
        a2 <= (t == t_imp[0]) ? ({240'd0, A16[15:0]} << (16 * p_imp[0])) :
              (t == t_imp[1]) ? ({240'd0, A16[15:0]} << (16 * p_imp[1])) : 256'd0;
        v  <= rstn;
    end

    wire [1:0]   full_sel, raw_sel, rec_drop;
    wire [255:0] f_d, r_d;
    wire         f_v, r_v;
    axis_sel4 u_fsel (.aclk(clk), .aresetn(rstn),
        .s0_axis_tdata(256'd0), .s0_axis_tvalid(v), .s0_axis_tready(), .s1_axis_tdata(256'd0), .s1_axis_tvalid(v), .s1_axis_tready(),
        .s2_axis_tdata(a2), .s2_axis_tvalid(v), .s2_axis_tready(), .s3_axis_tdata(256'd0), .s3_axis_tvalid(v), .s3_axis_tready(),
        .m_axis_tdata(f_d), .m_axis_tvalid(f_v), .m_axis_tready(1'b1), .sel(full_sel),
        .gb_stat0(32'd0), .gb_stat1(32'd0), .gb_stat2(32'd0), .gb_stat3(32'd0),
        .adc_stat0(32'd0), .adc_stat1(32'd0), .adc_stat2(32'd0), .adc_stat3(32'd0), .gb_stat_o(), .adc_stat_o());
    axis_sel4 u_rsel (.aclk(clk), .aresetn(rstn),
        .s0_axis_tdata(256'd0), .s0_axis_tvalid(v), .s0_axis_tready(), .s1_axis_tdata(256'd0), .s1_axis_tvalid(v), .s1_axis_tready(),
        .s2_axis_tdata(a2), .s2_axis_tvalid(v), .s2_axis_tready(), .s3_axis_tdata(256'd0), .s3_axis_tvalid(v), .s3_axis_tready(),
        .m_axis_tdata(r_d), .m_axis_tvalid(r_v), .m_axis_tready(1'b1), .sel(raw_sel),
        .gb_stat0(32'd0), .gb_stat1(32'd0), .gb_stat2(32'd0), .gb_stat3(32'd0),
        .adc_stat0(32'd0), .adc_stat1(32'd0), .adc_stat2(32'd0), .adc_stat3(32'd0), .gb_stat_o(), .adc_stat_o());
`ifdef DS_POSCTL
    wire [255:0] fin_d = a2;                       // 陽性対照: FULL の口に axis_sel4 の 1 段が無い
    wire         fin_v = v;
`else
    wire [255:0] fin_d = f_d;
    wire         fin_v = f_v;
`endif

    reg  [15:0] awaddr = 0, araddr = 0;
    reg         awvalid = 0, wvalid = 0, arvalid = 0;
    reg  [31:0] wdata = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [31:0] rdata;
    wire [63:0] rec_d;
    wire        rec_v, rec_l, rec_u;
    // proj031: 共有の係数（sim だけの源 cu_src。中身は g24_cu）
    wire [11:0] cu_a; wire cu_av; wire [1151:0] cu_c; wire [11:0] cu_m; wire cu_v, cu_ok;
    cu_src u_cu (.clk(clk), .rst(~rstn), .addr(cu_a), .addr_v(cu_av), .coef(cu_c), .m_out(cu_m), .v_out(cu_v), .ok_out(cu_ok));
    g24_s45_core #(.BUILD_TAG(32'h2024_0d42), .CORE_PORT(0), .K_F(KF), .ST_N(256), .GF_L2(1), .SHIFT_DEFAULT(7),
                   .TA_FILE(`TA), .TB_FILE(`TB)) u (
        .aclk(clk), .aresetn(rstn),
        .coef_addr(cu_a), .coef_addr_v(cu_av), .coef_in(cu_c), .coef_m_in(cu_m), .coef_ok_in(cu_ok), .s_axis_tdata(256'd0), .s_axis_tvalid(v), .s_axis_tready(),
        .s_axis_full_tdata(fin_d), .s_axis_full_tvalid(fin_v), .s_axis_full_tready(), .full_sel(full_sel),
        .s_axis_raw_tdata(r_d), .s_axis_raw_tvalid(r_v), .s_axis_raw_tready(), .raw_sel(raw_sel),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wvalid), .s_axi_wready(wready), .s_axi_bresp(),
        .s_axi_bvalid(bvalid), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(), .s_axi_rvalid(rvalid), .s_axi_rready(1'b1),
        .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(32'd0), .adc_stat(32'd0),
        .t_in(t), .go_in(1'b0), .tev_in(4'd0),
        .m_axis_rec_tdata(rec_d), .m_axis_rec_tvalid(rec_v), .m_axis_rec_tready(1'b1), .m_axis_rec_tlast(rec_l), .m_axis_rec_tuser(rec_u),
        .rec_drop(rec_drop));

    // ---- 記録: IP の出口（0 でない値だけ）・レコード ----
    integer fl, fr, fi, fip, p, nrec, nzl;
    reg [31:0] vre, vim;
    initial begin fip = -1; nrec = 0; nzl = 0; end
    always @(posedge clk) begin
        if (u.u_full.dbg_ip_v) begin
            if (u.u_full.dbg_ip_k1 == 12'd0) fip = fip + 1;
            for (p = 0; p < 16; p = p + 1) begin
                vre = u.u_full.dbg_ip_tdata[64*p +: 32];
                vim = u.u_full.dbg_ip_tdata[64*p + 32 +: 32];
                if ((^vre === 1'bx) || (^vim === 1'bx)) begin
                    if (fip >= 0) $fwrite(fl, "%0d %0d %0d x x\n", fip, u.u_full.dbg_ip_k1, p);
                end else if (vre != 32'd0 || vim != 32'd0) begin
                    $fwrite(fl, "%0d %0d %0d %0d %0d\n", fip, u.u_full.dbg_ip_k1, p, $signed(vre), $signed(vim));
                    nzl = nzl + 1;
                end
            end
        end
        if (rec_v) begin
            $fwrite(fr, "%0d %0d %h\n", rec_l, rec_u, rec_d);
            if (rec_l) nrec = nrec + 1;
        end
    end

    // ---- インパルスを置く: RAW の新しいダンプの頭のビート（n_start）を見たら (i) をその頭のフレームの中に、(ii) を 5 フレーム後より後の境目に ----
    //   n_start のクロックの RAW の口のビートは、ADC では 1 クロック前のビート（axis_sel4 の 1 段）。頭から 8〜500 ビート後の窓に置けば RAW に写る
    integer nimp, j, tgt, cand, base, c2, kk;
    integer targets [0:7];
    integer btg [0:3];
    initial begin
        targets[0] = 4095; targets[1] = 0; targets[2] = 1; targets[3] = 4094;
        targets[4] = 2047; targets[5] = 2048; targets[6] = 5; targets[7] = 4088;
        btg[0] = 4095; btg[1] = 0; btg[2] = 4094; btg[3] = 1;
        nimp = 0;
    end
    function integer ph(input integer tt);         // FULL のフレームの位相 m = (T − K_F) mod 4096（T > K_F の範囲で使う）
        ph = (tt - KF) % L;
    endfunction
    always @(posedge clk) begin
        if (rstn && nimp < NIMP && u.g_raw.u_raw.n_start && t > 64'd0 && (nimp == 0 || t > t_imp[1])) begin
            base = t[31:0] + 8;
            cand = -1;
            for (j = 0; j < 8 && cand < 0; j = j + 1) begin
                tgt = targets[((nimp / 2) + j) % 8];
                if (((tgt - ph(base)) % L + L) % L <= 492) cand = base + ((tgt - ph(base)) % L + L) % L;
            end
            if (cand < 0) cand = base + ((nimp / 2) * 97) % 490;
            // (ii): cand ＋ 5 フレームより後で、位相が btg の最初の T
            kk = btg[(nimp / 2) % 4];
            c2 = cand + 5 * L;
            c2 = c2 + (((kk - ph(c2)) % L + L) % L);
            t_imp[0] <= cand;  p_imp[0] <= ((nimp / 2) * 7 + 3) % 16;
            t_imp[1] <= c2;    p_imp[1] <= ((nimp / 2) * 5 + 10) % 16;
            $fwrite(fi, "imp %0d %0d 0\n", cand, ((nimp / 2) * 7 + 3) % 16);
            $fwrite(fi, "imp %0d %0d 1\n", c2, ((nimp / 2) * 5 + 10) % 16);
            nimp = nimp + 2;
        end
    end

    task axi_wr(input [15:0] a, input [31:0] x);
        begin
            @(negedge clk); awaddr = a; wdata = x; awvalid = 1; wvalid = 1;
            @(posedge clk); while ((awready && wready) !== 1'b1) @(posedge clk);
            @(negedge clk); awvalid = 0; wvalid = 0;
            @(posedge clk); while (bvalid !== 1'b1) @(posedge clk);
        end
    endtask

    integer fm, wcnt;
    initial begin
        fl = $fopen({`OUT, "/lanes.txt"}, "w");
        fr = $fopen({`OUT, "/rec.txt"}, "w");
        fi = $fopen({`OUT, "/imp.txt"}, "w");
        repeat (6) @(posedge clk);
        @(negedge clk); rstn = 1;
        repeat (8) @(posedge clk);
        // FULL（s 0）: SRC 2 → WRST。RUN はしない（SPEC のレコードは 256 KiB で RAW の SNAP を待たせるので出さない。区切りの T は IP の出口で見る）
        axi_wr(16'h4028, 32'd2);
        axi_wr(16'h4008, 32'h0000_1000);
        // RAW（s 1）: SRC 2 → WRST・N_ACC 97・N_DUMP 0（続ける）・REC ALL → RUN
        axi_wr(16'h4428, 32'd2);
        axi_wr(16'h4408, 32'h0000_1000);
        axi_wr(16'h440C, RAWN);
        axi_wr(16'h4410, 32'd0);
        axi_wr(16'h4484, 32'd1);
        wait (u.u_full.u_spec.have_first);
        axi_wr(16'h4408, 32'h0000_0001);
        wcnt = 0;
        while (nimp < NIMP && wcnt < (NIMP / 2 + 3) * RAWN * 512) begin @(posedge clk); wcnt = wcnt + 1; end
        while (t <= t_imp[1] + 5 * L + 3000) @(posedge clk);           // 最後のインパルスの 4 フレームの足を IP の出口まで出し切る
        while (nrec < NIMP / 2 && wcnt < (NIMP / 2 + 3) * RAWN * 512) begin @(posedge clk); wcnt = wcnt + 1; end   // RAW の SNAP はダンプが閉じたときに出る。(i) の数だけ待つ
        fm = $fopen({`OUT, "/meta.txt"}, "w");
`ifdef DS_POSCTL
        $fwrite(fm, "POSCTL 1\n");
`else
        $fwrite(fm, "POSCTL 0\n");
`endif
        $fwrite(fm, "KF %0d\nf_first %0d\nflags %0d\nnrec %0d\nnimp %0d\nA %0d\nfull_sel %0d\nraw_sel %0d\nnzl %0d\nnfr %0d\n",
                KF, u.u_full.u_spec.f_first, u.u_full.flags, nrec, nimp, 8000, full_sel, raw_sel, nzl, fip + 1);
        $fclose(fm); $fclose(fl); $fclose(fr); $fclose(fi);
        $display("tb_g24_ds: インパルス %0d 個・レコード %0d 個・IP の出口のフレーム %0d・full_sel %0d・raw_sel %0d・flags %h",
                 nimp, nrec, fip + 1, full_sel, raw_sel, u.u_full.flags);
        $finish;
    end
    initial begin
        #(3.906 * (NIMP / 2 + 4) * RAWN * 512);
        $display("tb_g24_ds: 時間切れ（インパルス %0d 個）", nimp);
        $finish;
    end
endmodule
