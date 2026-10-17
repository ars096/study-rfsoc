// SPDX-License-Identifier: BSD-3-Clause
//
// tb_wide_ds — SLICE の遅れ D_S（INTERFACE 5.2）を出す sim（proj023 手順 4e）。wide_s45_core を丸ごと（wide_core ＋ RAW）
//
// 問い: 同じ ADC のサンプルに、SLICE（wide_spec のフレームの区切り T ≡ K_F）と RAW（F-2 が adc_to_core を測る道）が
//       付ける T は同じか。D_S = T_slice − T_raw（ビート）。utc_ns = beat_utc(dump_t) − adc_to_core − (D_S ＋ 1.5·L)。
// 刺激: 0 の上に孤立した 1 サンプル（インパルス、14 bit で A = 8000、レーン p）を、RAW のダンプの頭のフレーム（SNAP に写る 512 ビート）の中に置く。
//       実機の配線を写す: ギアボックスの出口 → axis_broadcaster（段なし）→ SLICE の口 / → axis_sel4（**1 段**）→ RAW の口。
//       tb は SLICE の口に T と同じクロックでビートを入れ、RAW の口には 1 クロック遅らせて入れる。-DDS_NODELAY: 遅らせない（陽性対照: D_S が 1 動く）
// 出力: $(OUT)/imp.txt   「imp T_imp lane」（tb が SLICE の口に入れたクロックの T）
//       $(OUT)/lanes.txt IP の出口の 0 でない行「frame k1 re0 im0 … re15 im15」（frame は出口の通し番号、ラベルは f_first ＋ frame）
//       $(OUT)/recs.txt  RAW の SNAP のレコード（tb_wide_s45 と同じ形）/ $(OUT)/meta.txt
// 判定: python3 sim/check_ds.py $(OUT) [posctl]
// RAW の N_ACC は 21 フレーム（10,752 ビート = 5.25 SLICE フレーム）: ダンプごとに RAW の頭の位相が SLICE のフレームに対して 512 ビートずつ動き、
//   4 個で SLICE のフレームの全部の位相（とくに境目 m = 2047・0）を通る。インパルスの間は 5.25 フレームで、PFB の 4 フレームの足が重ならない

`timescale 1ns / 1ps

module tb_wide_ds;
    localparam integer T0    = 70001;
    localparam integer KF    = 777;
    localparam integer NIMP  = `NIMP;
    localparam integer A16   = 8000 * 4;           // 14 bit の 8000 を ADC の 16 bit に

    reg clk = 1'b0;
    always #2 clk = ~clk;
    reg  rstn = 1'b0;
    reg  [63:0] t = T0;
    always @(posedge clk) t <= t + 64'd1;

    // ---- 刺激: SLICE の口のビートは T = t のクロックに。RAW の口は 1 段後（axis_sel4）----
    reg  [63:0]  t_imp = 64'hFFFF_FFFF_FFFF_FFFF;
    reg  [3:0]   p_imp = 4'd0;
    wire [255:0] d_w = (t == t_imp) ? ({240'd0, A16[15:0]} << (16 * p_imp)) : 256'd0;
    reg  [255:0] d_r = 256'd0;
    always @(posedge clk) d_r <= d_w;
`ifdef DS_NODELAY
    wire [255:0] d_raw = d_w;
`else
    wire [255:0] d_raw = d_r;
`endif

    wire [10:0]   coef_addr, coef_m, tw_addr, tw_k1;
    wire          coef_addr_v, coef_v;
    wire [1151:0] coef;
    wire [575:0]  tw;
    wide_coef_rom #(.COEF_FILE(`COEF)) u_crom (.clk(clk), .addr(coef_addr), .addr_v(coef_addr_v), .coef(coef), .m_out(coef_m), .v_out(coef_v));
    wide_tw_rom   #(.TW_FILE(`TWF))    u_trom (.clk(clk), .addr(tw_addr), .tw(tw), .k1_out(tw_k1));

    reg  [15:0] awaddr = 0, araddr = 0;
    reg         awvalid = 0, wvalid = 0, arvalid = 0;
    reg  [31:0] wdata = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [1:0]  bresp, rresp;
    wire [31:0] rdata;
    reg         go = 1'b0;
    wire [63:0] rec_d;
    wire        rec_v, rec_l, rec_u;
    wire [1:0]  rec_drop, full_sel;
    wide_s45_core #(.CORE_PORT(2), .K_F(KF), .ST_N(64), .GF_L2(2), .RAW(1), .RAW_N_ACC_DEFAULT(21)) dut (
        .aclk(clk), .aresetn(rstn), .s_axis_tdata(d_w), .s_axis_tvalid(1'b1), .s_axis_tready(),
        .s_axis_full_tdata(d_raw), .s_axis_full_tvalid(1'b1), .s_axis_full_tready(), .full_sel(full_sel),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_wdata(wdata),
        .s_axi_wstrb(4'hF), .s_axi_wvalid(wvalid), .s_axi_wready(wready), .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rresp(rresp),
        .s_axi_rvalid(rvalid), .s_axi_rready(1'b1),
        .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(32'd0), .adc_stat(32'd0),
        .t_in(t), .go_in(go), .tev_in(4'd0),
        .coef_addr(coef_addr), .coef_addr_v(coef_addr_v), .coef_in(coef), .coef_m(coef_m),
        .tw_addr(tw_addr), .tw_in(tw), .tw_k1(tw_k1),
        .m_axis_rec_tdata(rec_d), .m_axis_rec_tvalid(rec_v), .m_axis_rec_tready(1'b1), .m_axis_rec_tlast(rec_l),
        .m_axis_rec_tuser(rec_u), .rec_drop(rec_drop));
    wire [16*64-1:0] ip_d  = dut.u_wide.dbg_ip_tdata;
    wire [10:0]      ip_k1 = dut.u_wide.dbg_ip_k1;
    wire             ip_v  = dut.u_wide.dbg_ip_v;

    task axw(input [15:0] a, input [31:0] v);
        begin
            @(posedge clk); awaddr <= a; wdata <= v; awvalid <= 1'b1; wvalid <= 1'b1;
            @(posedge clk); while (awready !== 1'b1) @(posedge clk);
            awvalid <= 1'b0; wvalid <= 1'b0;
            @(posedge clk); while (bvalid !== 1'b1) @(posedge clk);
        end
    endtask
    task fire;
        begin @(posedge clk); go <= 1'b1; @(posedge clk); go <= 1'b0; end
    endtask

    // ---- 記録: IP の出口（0 でない行だけ）・RAW のレコード ----
    integer fl, fr, fi, fip, p, nw, nrec, nz;
    initial begin fip = -1; nw = 0; nrec = 0; end
    always @(posedge clk) begin
        if (ip_v) begin
            if (ip_k1 == 11'd0) fip = fip + 1;
            nz = 0;
            for (p = 0; p < 16; p = p + 1) if (ip_d[64*p +: 26] != 26'd0 || ip_d[64*p + 32 +: 26] != 26'd0) nz = 1;
            if (nz) begin
                $fwrite(fl, "%0d %0d", fip, ip_k1);
                for (p = 0; p < 16; p = p + 1) $fwrite(fl, " %0d %0d", $signed(ip_d[64*p +: 26]), $signed(ip_d[64*p + 32 +: 26]));
                $fwrite(fl, "\n");
            end
        end
        if (rec_v) begin
            $fwrite(fr, "r %0d %016x\n", nw, rec_d);
            nw = nw + 1;
            if (rec_l) begin $fwrite(fr, "end %0d\n", rec_u); nw = 0; nrec = nrec + 1; end
        end
    end

    // ---- インパルスを置く: RAW の新しいダンプの頭のビート（n_start）を見たら、その頭のフレーム（512 ビート）の中に 1 個 ----
    //   n_start のクロックの RAW の口のビートは、SLICE の口では 1 クロック前（-DDS_NODELAY では同じクロック）のビート。
    //   狙う SLICE の位相 m = (T − K_F) mod 2048 を順に変え、窓（頭から 8〜500 ビート後）に入らなければ窓の中の別の点に置く
    integer nimp, j, tgt, cand, base;
    integer targets [0:7];
    initial begin
        targets[0] = 2047; targets[1] = 0; targets[2] = 1; targets[3] = 2046;
        targets[4] = 1023; targets[5] = 1024; targets[6] = 5; targets[7] = 2040;
        nimp = 0;
    end
    always @(posedge clk) begin
        if (rstn && nimp < NIMP && dut.g_raw.u_raw.n_start && (nimp == 0 || t > t_imp)) begin
            base = t[31:0] + 8;
            cand = -1;
            for (j = -1; j < 8 && cand < 0; j = j + 1) begin
                // 最初に境目（2047・0・2046 を 4 個おきに替える）、窓に入らなければ表の順
                tgt = (j < 0) ? ((((nimp / 4) % 3) == 0) ? 2047 : (((nimp / 4) % 3) == 1) ? 0 : 2046) : targets[(nimp + j) % 8];
                // base 以上で (T − K_F) mod 2048 = tgt の最初の T
                if (((tgt - (base - KF)) % 2048 + 2048) % 2048 <= 492) cand = base + ((tgt - (base - KF)) % 2048 + 2048) % 2048;
            end
            if (cand < 0) cand = base + (nimp * 37) % 490;
            t_imp <= cand;                                         // T は 2^31 より十分小さい（T0 70001 から sim の長さぶん）
            p_imp <= (nimp * 7 + 3) % 16;
            $fwrite(fi, "imp %0d %0d\n", cand, (nimp * 7 + 3) % 16);
            nimp = nimp + 1;
        end
    end

    integer fm, wcnt;
    initial begin
        fl = $fopen({`OUT, "/lanes.txt"}, "w");
        fr = $fopen({`OUT, "/recs.txt"}, "w");
        fi = $fopen({`OUT, "/imp.txt"}, "w");
        repeat (10) @(posedge clk);
        rstn <= 1'b1;
        repeat (200) @(posedge clk);
        axw(16'h480C, 21); axw(16'h4810, 0); axw(16'h4884, 1);   // RAW: N_ACC 21 フレーム・N_DUMP 0（続ける）・REC_CTRL = ALL
        repeat (3 * 2048) @(posedge clk);
        axw(16'h4808, 32'h4);                                     // ARM_RUN（RAW）
        repeat (20) @(posedge clk);
        fire;
        wcnt = 0;
        while (nrec < NIMP + 2 && wcnt < (NIMP + 4) * 21 * 512) begin @(posedge clk); wcnt = wcnt + 1; end
        repeat (5 * 2048) @(posedge clk);                         // 最後のインパルスの 4 フレームの足を出し切る
        fm = $fopen({`OUT, "/meta.txt"}, "w");
`ifdef DS_NODELAY
        $fwrite(fm, "NODELAY 1\n");
`else
        $fwrite(fm, "NODELAY 0\n");
`endif
        $fwrite(fm, "T0 %0d\nKF %0d\nf_first %0d\nflags %0d\nnrec %0d\nnimp %0d\nA %0d\n", T0, KF, dut.u_wide.u_spec.f_first, dut.u_wide.flags, nrec, nimp, 8000);
        $fclose(fm); $fclose(fl); $fclose(fr); $fclose(fi);
        $display("tb_wide_ds: インパルス %0d 個・RAW のレコード %0d 個・flags %02x", nimp, nrec, dut.u_wide.flags);
        $finish;
    end
    initial begin
        #(4 * 64'd3000000);
        $display("tb_wide_ds: 時間切れ");
        $finish;
    end
endmodule
