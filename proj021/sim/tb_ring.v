// SPDX-License-Identifier: BSD-3-Clause
//
// tb_ring — s45_core（NW 2 ＋ FULL）→ s45_ring → 止まりの入る HP0 の記憶（proj021 手順 2-2a、sim-ring。S22a-1 の予言 1・2 (c)）
//
//   入力: ランダムな ADC のビート（16 × 13 bit）。DDC の流れ 0・1 は NS 1、FULL は 1 本（同じ入力）
//   変種（+MODE）:
//     all  : 流れ 0 と FULL を REC_CTRL の ALL、流れ 1 は途中で ONE を 1 回。ダンプは 16384 クロック（DDC N_ACC 4・FULL N_ACC 32）。
//            読み出し 4096 クロック × 3 本が間に合う → REC_LATE 0・DROP 0 であるべき（WANT = nolate）。
//            ダンプごとに AXI4-Lite で DUMP_*（seqlock）と仮の読み窓のスペクトル 16 ch を読む（**rec_fr が口を持っている間に読みが待たされる**道）
//     late : 全部 ALL、DDC の N_ACC 2（8192 クロック）・FULL の N_ACC 16 → 3 本の読み出し（12,300 クロック）が追いつかない（WANT = late）。
//            AXI4-Lite は読まない。**N_ACC 1（4096 クロック）では 4096 語の読み出しが 1 本も間に合わず、レコードが 1 個も出ない**（1 回目で見た）
//   照合の材料（check_ring.py core）:
//     Q 行: SEQ が進んだ 2 クロック後に、凍ったバンクを記憶から直に写したもの（本体 4096 語）
//     H 行: その SEQ の DUMP_* を AXI4-Lite で読んで組んだ頭 w1..w6（seqlock が崩れたら書かない）
//     ring.txt: 読み手（PS の代わり）がリングから写したレコード
//   tb の中の照合: AXI4-Lite の 16 ch = Q の同じ ch（AXI_CMP）、ONE で 1 個出た後 REC_CTRL の [1] が 0（ONE）
`timescale 1ns / 1ps

module tb_ring;
    reg clk = 0, rstn = 0;
    always #1.953 clk = ~clk;
    localparam [48:0] BASE = 49'h0_8000_0040;
    localparam integer SIZE = 262144;
    reg [8*8-1:0] mode;
    integer is_late;
    integer NDUMP;
    initial begin
        if (!$value$plusargs("MODE=%s", mode)) mode = "all";
        is_late = (mode == "late");
        if (!$value$plusargs("NDUMP=%d", NDUMP)) NDUMP = is_late ? 10 : 5;
    end

    // ---- 入力 ----
    reg  [255:0] tdata = 0;
    reg          tvalid = 0;
    integer seed = 11, l;
    always @(posedge clk) if (rstn) begin
        tvalid <= 1;
        for (l = 0; l < 16; l = l + 1) tdata[16*l +: 16] <= {{3{1'b0}}, 13'd0} + ($random(seed) % 4096);
    end
    reg [63:0] tcnt = 0;
    always @(posedge clk) tcnt <= tcnt + 1;

    // ---- コアの AXI4-Lite ----
    reg  [19:0] awaddr = 0, araddr = 0;
    reg  [31:0] wdata = 0;
    reg         awvalid = 0, wvalid = 0, arvalid = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [31:0] rdata;
    task axw(input [19:0] a, input [31:0] d); begin
        @(posedge clk); awaddr <= a; wdata <= d; awvalid <= 1; wvalid <= 1;
        @(posedge clk); while (!awready) @(posedge clk);
        awvalid <= 0; wvalid <= 0;
        while (!bvalid) @(posedge clk);
    end endtask
    reg [31:0] rv;
    task axr(input [19:0] a); begin
        @(posedge clk); araddr <= a; arvalid <= 1;
        @(posedge clk); while (!arready) @(posedge clk);
        arvalid <= 0;
        while (!rvalid) @(posedge clk);
        rv = rdata;
    end endtask
    function [19:0] B(input integer st, input [11:0] o); B = 20'h04000 + 20'h00400 * st + o; endfunction

    // ---- コア 0（NW 2 ＋ FULL）----
    wire [63:0] rec_d;
    wire        rec_v, rec_r, rec_l, rec_u;
    wire [1:0]  rec_dp;
    s45_core #(.NW(2), .G_L2(12), .BUILD_TAG(32'h1234_0000), .CORE_PORT(16'h2200), .FULL(1), .FULL_BUILD_TAG(32'h5678_0000),
               .FULL_STABLE_N(0)) u_c0 (
        .aclk(clk), .aresetn(rstn), .s_axis_tdata(tdata), .s_axis_tvalid(tvalid), .s_axis_tready(),
        .s_axis_full_tdata(tdata), .s_axis_full_tvalid(tvalid), .s_axis_full_tready(), .full_gb_stat(32'd0), .full_adc_stat(32'd0), .full_sel(),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wvalid), .s_axi_wready(wready), .s_axi_bresp(), .s_axi_bvalid(bvalid), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(), .s_axi_rvalid(rvalid), .s_axi_rready(1'b1),
        .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(32'd0), .adc_stat(32'd0),
        .t_in(tcnt), .go_in(1'b0), .tev_in(4'd0),
        .m_axis_rec_tdata(rec_d), .m_axis_rec_tvalid(rec_v), .m_axis_rec_tready(rec_r), .m_axis_rec_tlast(rec_l),
        .m_axis_rec_tuser(rec_u), .rec_drop(rec_dp));

    // ---- リング ＋ HP0 の代わりの記憶（tb_ring_u と同じ見張り）----
    reg  [11:0] r_awaddr = 0, r_araddr = 0;
    reg  [31:0] r_wdata = 0;
    reg         r_awvalid = 0, r_wvalid = 0, r_arvalid = 0;
    wire        r_awready, r_wready, r_bvalid, r_arready, r_rvalid;
    wire [31:0] r_rdata;
    task lw(input [11:0] a, input [31:0] v); begin
        @(posedge clk); r_awaddr <= a; r_wdata <= v; r_awvalid <= 1; r_wvalid <= 1;
        @(posedge clk); while (!(r_awready && r_wready)) @(posedge clk);
        r_awvalid <= 0; r_wvalid <= 0;
        while (!r_bvalid) @(posedge clk);
        @(posedge clk);
    end endtask
    reg [31:0] lrv;
    task lr(input [11:0] a); begin
        @(posedge clk); r_araddr <= a; r_arvalid <= 1;
        @(posedge clk); while (!r_arready) @(posedge clk);
        r_arvalid <= 0;
        while (!r_rvalid) @(posedge clk);
        lrv = r_rdata;
        @(posedge clk);
    end endtask
    wire [48:0]  m_awaddr;
    wire [7:0]   m_awlen;
    wire         m_awvalid, m_wlast, m_wvalid, m_bready;
    reg          aw_ok = 0, w_ok = 0, m_bvalid = 0, in_burst = 0;
    wire         m_awready = aw_ok && !in_burst;
    wire         m_wready  = w_ok && in_burst;
    wire [127:0] m_wdata;
    reg  [127:0] mem [0:SIZE / 16 - 1];
    integer nerr = 0, nburst = 0, bq_done = 0, bq_r = 0, cur_n, cur_len;
    reg  [48:0]  cur_a;
    always @(posedge clk) begin
        aw_ok <= ($random(seed) & 3) != 0;
        w_ok  <= ($random(seed) & 7) != 0;
        if (m_awvalid && m_awready) begin
            nburst = nburst + 1;
            cur_a <= m_awaddr; cur_n <= 0; cur_len <= m_awlen + 1; in_burst <= 1;
            if (m_awlen > 15 || m_awaddr[3:0] != 0 || (m_awaddr[11:0] + 16 * (m_awlen + 1)) > 4096 ||
                m_awaddr < BASE || m_awaddr + 16 * (m_awlen + 1) > BASE + SIZE) begin
                $display("tb_ring: NG バースト %h len %0d", m_awaddr, m_awlen + 1); nerr = nerr + 1;
            end
        end
        if (m_wvalid && m_wready) begin
            mem[(cur_a - BASE) / 16 + cur_n] <= m_wdata;
            cur_n <= cur_n + 1;
            if (m_wlast != (cur_n + 1 == cur_len)) begin $display("tb_ring: NG wlast"); nerr = nerr + 1; end
            if (cur_n + 1 == cur_len) begin in_burst <= 0; bq_done = bq_done + 1; end
        end
        if (m_bvalid && m_bready) begin m_bvalid <= 0; bq_r = bq_r + 1; end
        else if (!m_bvalid && bq_r < bq_done && ($random(seed) & 3) == 0) m_bvalid <= 1;
    end
    s45_ring #(.NIN(1)) u_ring (.aclk(clk), .aresetn(rstn),
        .s0_axis_tdata(rec_d), .s0_axis_tvalid(rec_v), .s0_axis_tready(rec_r), .s0_axis_tlast(rec_l), .s0_axis_tuser(rec_u),
        .s1_axis_tdata(64'd0), .s1_axis_tvalid(1'b0), .s1_axis_tready(), .s1_axis_tlast(1'b0), .s1_axis_tuser(1'b0),
        .s2_axis_tdata(64'd0), .s2_axis_tvalid(1'b0), .s2_axis_tready(), .s2_axis_tlast(1'b0), .s2_axis_tuser(1'b0),
        .s3_axis_tdata(64'd0), .s3_axis_tvalid(1'b0), .s3_axis_tready(), .s3_axis_tlast(1'b0), .s3_axis_tuser(1'b0),
        .rec_drop0(rec_dp), .rec_drop1(2'd0), .rec_drop2(2'd0), .rec_drop3(2'd0),
        .s_axi_awaddr(r_awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(r_awvalid), .s_axi_awready(r_awready),
        .s_axi_wdata(r_wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(r_wvalid), .s_axi_wready(r_wready),
        .s_axi_bresp(), .s_axi_bvalid(r_bvalid), .s_axi_bready(1'b1),
        .s_axi_araddr(r_araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(r_arvalid), .s_axi_arready(r_arready),
        .s_axi_rdata(r_rdata), .s_axi_rresp(), .s_axi_rvalid(r_rvalid), .s_axi_rready(1'b1),
        .m_axi_awaddr(m_awaddr), .m_axi_awlen(m_awlen), .m_axi_awsize(), .m_axi_awburst(), .m_axi_awlock(), .m_axi_awcache(),
        .m_axi_awprot(), .m_axi_awqos(), .m_axi_awvalid(m_awvalid), .m_axi_awready(m_awready),
        .m_axi_wdata(m_wdata), .m_axi_wstrb(), .m_axi_wlast(m_wlast), .m_axi_wvalid(m_wvalid), .m_axi_wready(m_wready),
        .m_axi_bresp(2'b00), .m_axi_bvalid(m_bvalid), .m_axi_bready(m_bready));

    // ---- 凍ったバンクを直に写す（Q 行）----
    wire [31:0] seq0 = u_c0.u_win.g_w[0].seq, seq1 = u_c0.u_win.g_w[1].seq, seq2 = u_c0.g_full.u_full.seq;
    wire        bk0 = u_c0.u_win.g_w[0].rd_bank, bk1 = u_c0.u_win.g_w[1].rd_bank, bk2 = u_c0.g_full.u_full.rd_bank;
    reg  [63:0] pk [0:3*4096-1];
    reg  [2:0]  pk_tg = 0;
    reg  [2:0]  pk_bk;
    genvar gg, bb, jj;
    generate
        for (gg = 0; gg < 2; gg = gg + 1) for (bb = 0; bb < 2; bb = bb + 1) begin : g_pd
            integer i;
            always @(pk_tg[gg]) if (pk_bk[gg] == bb) for (i = 0; i < 4096; i = i + 1) pk[gg * 4096 + i] = u_c0.u_win.g_w[gg].u_ws.g_bank[bb].mem[i];
        end
        for (jj = 0; jj < 8; jj = jj + 1) for (bb = 0; bb < 2; bb = bb + 1) begin : g_pf
            integer i;
            always @(pk_tg[2]) if (pk_bk[2] == bb) for (i = 0; i < 512; i = i + 1) pk[2 * 4096 + jj * 512 + i] = u_c0.g_full.u_full.g_bin[jj].g_bank[bb].mem[i];
        end
    endgenerate
    integer fq, fr;
    integer nq [0:2];
    reg [31:0] pseq [0:2];                 // 写した SEQ（AXI4-Lite の照合の相手）
    reg [63:0] p16 [0:47];                 // 写した 16 ch（流れ × 16）
    reg [2:0]  todo = 0;                   // AXI4-Lite で読む流れ
    function integer cht(input integer n);  // 照らす ch
        cht = (n == 0) ? 0 : (n == 1) ? 1 : (n == 15) ? 4095 : (n * 271 + 3) % 4096;
    endfunction
    reg [31:0] sq_d [0:2];
    integer s_, n_, kq;
    initial begin nq[0] = 0; nq[1] = 0; nq[2] = 0; sq_d[0] = 0; sq_d[1] = 0; sq_d[2] = 0; end
    always @(posedge clk) if (rstn) begin
        for (s_ = 0; s_ < 3; s_ = s_ + 1) begin
            if (((s_ == 0) ? seq0 : (s_ == 1) ? seq1 : seq2) == sq_d[s_] + 1) begin
                sq_d[s_] = sq_d[s_] + 1;
                pk_bk[s_] = (s_ == 0) ? bk0 : (s_ == 1) ? bk1 : bk2;
                pk_tg[s_] = ~pk_tg[s_];
                #0.1;
                $fwrite(fq, "Q 0 %0d %0d", s_, sq_d[s_]);
                for (kq = 0; kq < 4096; kq = kq + 1) $fwrite(fq, " %h", pk[s_ * 4096 + kq]);
                $fwrite(fq, "\n");
                for (n_ = 0; n_ < 16; n_ = n_ + 1) p16[s_ * 16 + n_] = pk[s_ * 4096 + cht(n_)];
                pseq[s_] = sq_d[s_];
                nq[s_] = nq[s_] + 1;
                todo[s_] = 1'b1;
            end else if (((s_ == 0) ? seq0 : (s_ == 1) ? seq1 : seq2) != sq_d[s_]) begin
                sq_d[s_] = (s_ == 0) ? seq0 : (s_ == 1) ? seq1 : seq2;       // リセット
            end
        end
    end

    // ---- 読み手（PS の代わり）----
    integer k, nrd = 0, stop_rd = 0;
    reg [31:0] w_now, r_now, p, len, ty;
    reg [63:0] w0, w7;
    function [63:0] mw(input [31:0] pos);
        reg [127:0] b;
        begin b = mem[(pos % SIZE) / 16]; mw = pos[3] ? b[127:64] : b[63:0]; end
    endfunction
    task read_ring; begin
        lr(12'h014); w_now = lrv;
        p = r_now;
        while (p != w_now) begin
            w0 = mw(p); w7 = mw(p + 56); ty = w0[47:40];
            len = (ty == 0) ? w7[31:0] : 64 + w7[31:0] + 64;
            $fwrite(fr, "R %0d", p);
            for (k = 0; k < len / 8 && (ty != 0 || k < 8); k = k + 1) $fwrite(fr, " %h", mw(p + 8 * k));
            $fwrite(fr, "\n");
            p = p + len; nrd = nrd + 1;
        end
        r_now = w_now;
        lw(12'h018, r_now);
    end endtask
    initial begin
        r_now = 0;
        @(posedge rstn);
        forever begin
            repeat (3000) @(posedge clk);
            if (u_ring.en) read_ring;
        end
    end

    // ---- 本体 ----
    integer ng = 0, ncmp = 0, nskip = 0, nh = 0, st, n, one_done = 0;
    reg [31:0] h_seq, h_k, h_f0l, h_f0h, h_tl, h_th, h_par, h_sh, h_src, h_h, h_n, h_sat, h_fl, h_cfg, h_seq2;
    reg [63:0] a16 [0:15];
    task serve(input integer s); begin
        // DUMP_*（seqlock）
        axr(B(s, 12'h01C)); h_seq = rv;
        axr(B(s, 12'h03C)); h_k = rv;   axr(B(s, 12'h040)); h_f0l = rv; axr(B(s, 12'h044)); h_f0h = rv;
        axr(B(s, 12'h050)); h_tl = rv;  axr(B(s, 12'h054)); h_th = rv;  axr(B(s, 12'h004)); h_par = rv;
        axr(B(s, 12'h038)); h_sh = rv;  axr(B(s, 12'h028)); h_src = rv; axr(B(s, 12'h058)); h_h = rv;
        axr(B(s, 12'h048)); h_n = rv;   axr(B(s, 12'h04C)); h_sat = rv; axr(B(s, 12'h018)); h_fl = rv;
        axr(B(s, 12'h05C)); h_cfg = rv;
        // 仮の読み窓のスペクトル 16 ch（LO・HI）
        for (n = 0; n < 16; n = n + 1) begin
            axr((s < 2) ? (20'h90000 + 20'h20000 * s + 8 * cht(n)) : (20'hC8000 + 8 * cht(n))); a16[n][31:0] = rv;
            axr((s < 2) ? (20'h90004 + 20'h20000 * s + 8 * cht(n)) : (20'hC8004 + 8 * cht(n))); a16[n][63:32] = rv;
        end
        axr(B(s, 12'h01C)); h_seq2 = rv;
        if (h_seq != h_seq2 || h_seq != pseq[s]) nskip = nskip + 1;
        else begin
            nh = nh + 1;
            $fwrite(fq, "H 0 %0d %0d %h %h %h %h %h %h\n", s, h_seq,
                {h_k, h_seq}, {h_f0h, h_f0l}, {h_th, h_tl},
                {h_h[15:0], {4'd0, h_src[3:0]}, 8'd0, (s < 2) ? {4'd0, h_par[15:12]} : 8'd0, {4'd0, h_sh[3:0]},
                 (s < 2) ? {4'd0, h_par[11:8]} : 8'd0, (s < 2) ? 8'd12 : 8'd13},
                {h_sat, h_n}, {h_fl, h_cfg});
            for (n = 0; n < 16; n = n + 1) begin
                ncmp = ncmp + 1;
                if (a16[n] !== p16[s * 16 + n]) begin
                    $display("tb_ring: NG AXI4-Lite の ch %0d（流れ %0d SEQ %0d）= %h / 凍ったバンク %h", cht(n), s, h_seq, a16[n], p16[s * 16 + n]);
                    ng = ng + 1;
                end
            end
        end
    end endtask

    initial begin
        fq = $fopen("peek.txt", "w");
        fr = $fopen("ring.txt", "w");
        repeat (8) @(posedge clk);
        rstn <= 1;
        repeat (8) @(posedge clk);
        // リング
        lw(12'h008, BASE[31:0]); lw(12'h00C, {15'd0, BASE[48:32]}); lw(12'h010, SIZE); lw(12'h004, 1);
        // 窓: 流れ 0（k 5）・流れ 1（k 9）、NS 1
        for (st = 0; st < 2; st = st + 1) begin
            axw(B(st, 12'h100), (st == 0) ? 5 : 9); axw(B(st, 12'h104), 32'h1234_5678 * (st + 1)); axw(B(st, 12'h108), 1);
            axw(B(st, 12'h00C), is_late ? 2 : 4); axw(B(st, 12'h010), 0); axw(B(st, 12'h014), 4);
            axw(B(st, 12'h02C), 32'hC0F0_0000 + st);
            axw(B(st, 12'h008), 32'h1000);         // WRST
        end
        axw(B(2, 12'h00C), is_late ? 16 : 32); axw(B(2, 12'h010), 0); axw(B(2, 12'h014), 6); axw(B(2, 12'h02C), 32'hC0F0_0002);
        axw(B(0, 12'h084), 1);                                  // ALL
        axw(B(1, 12'h084), is_late ? 1 : 0);
        axw(B(2, 12'h084), 1);
        rv = 0;
        while (rv < 3) begin repeat (2000) @(posedge clk); axr(B(0, 12'h070)); end
        axw(B(0, 12'h008), 1); axw(B(1, 12'h008), 1); axw(B(2, 12'h008), 1);    // RUN
        while (nq[0] < NDUMP) begin
            @(posedge clk);
            if (!is_late) begin
                for (st = 0; st < 3; st = st + 1) if (todo[st]) begin todo[st] = 1'b0; serve(st); end
                if (nq[0] == 2 && !one_done) begin one_done = 1; axw(B(1, 12'h084), 2); end   // 流れ 1 に ONE
            end
        end
        // 止めて出し切る
        axw(B(0, 12'h084), 0); axw(B(1, 12'h084), 0); axw(B(2, 12'h084), 0);
        repeat (20000) @(posedge clk);
        lw(12'h004, 0);
        repeat (2000) @(posedge clk);
        read_ring;
        $display("tb_ring: MODE = %0s", mode);
        $display("tb_ring: WANT = %0s", is_late ? "late" : "nolate");
        $display("tb_ring: SIZE = %0d", SIZE);
        lr(12'h014); $display("tb_ring: W = %0d", lrv);
        lr(12'h01C); $display("tb_ring: DROP_CNT = %0d", lrv);
        lr(12'h020); $display("tb_ring: REC_CNT = %0d", lrv);
        lr(12'h024); $display("tb_ring: PEAK = %0d", lrv);
        for (st = 0; st < 3; st = st + 1) begin axr(B(st, 12'h088)); $display("tb_ring: REC_LATE%0d = %0d", st, rv); end
        axr(B(1, 12'h084));
        if (!is_late) begin
            if (rv[1] !== 1'b0) begin $display("tb_ring: NG ONE が 0 に戻らない（REC_CTRL %h）", rv); ng = ng + 1; end
            $display("tb_ring: ONE = %0s", (rv[1] === 1'b0) ? "OK" : "NG");
        end
        $display("tb_ring: AXI_CMP = %0s", (ng == 0) ? "OK" : "NG");
        $display("tb_ring: Q = %0d %0d %0d / H = %0d / seqlock で飛ばした %0d / 照らした ch %0d / バースト %0d / 読んだ %0d",
                 nq[0], nq[1], nq[2], nh, nskip, ncmp, nburst, nrd);
        $display("tb_ring: NG = %0d", ng + nerr);
        $fclose(fq); $fclose(fr);
        $finish;
    end
endmodule
