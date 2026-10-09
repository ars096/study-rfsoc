// SPDX-License-Identifier: BSD-3-Clause
//
// tb_ring_u — s45_ring 単体（proj021 手順 2-2a、sim-ringu）。入口 4 本は作り物のレコード、HP0 は止まりをランダムに入れる記憶
//
//   入口 i: 本体のバイト数 P_i（i = 0: 32768、1: 1024、2: 512、3: 4096）のレコードを NREC 個。間はランダム。
//           ヘッダ w0 = {s = i, core = i, type 1, ver 1, "S45R"}、w1 = {K = 1000 + seq, SEQ}、w2..w6 = hw(i, seq, n)、w7 = P_i。
//           本体の語 j = pw(i, seq, j)（下の関数。check_ring.py が同じ式で作り直す）。
//           入口 1 は seq % 7 == 3 を tuser = 1（捨てる）で出す。入口 2 は seq % 5 == 4 の後に rec_drop を 1 クロック立てる
//   記憶: BASE = 0x1_2345_6040（256 バイト境でない）、SIZE = +SIZE（既定 64 KiB）。AW・W の ready と B の遅れはランダム。
//         見張り: バーストが 4 KiB の境を越えない・16 拍以下・16 バイト境・リングの範囲の中・W の拍の数 = awlen + 1
//   読み手（PS の代わり）: +NOREAD でなければ、ときどき W を読み、[R, W) を記憶から写してファイルへ（1 行 1 レコード、
//         PAD も）、R を書く。+BERR=n なら n 番目のバーストに SLVERR を返す（ERR が立ち、それ以後 W が進まないこと）
//   最後に W・R・DROP_CNT・REC_CNT・PEAK・CTRL を表示（check_ring.py が照合する）
`timescale 1ns / 1ps

module tb_ring_u;
    reg clk = 0, rstn = 0;
    always #2 clk = ~clk;

    localparam [48:0] BASE = 49'h1_2345_6040;
    integer SIZE, NREC, NOREAD, BERR, SEED;
    initial begin
        if (!$value$plusargs("SIZE=%d", SIZE)) SIZE = 65536;
        if (!$value$plusargs("NREC=%d", NREC)) NREC = 24;
        if (!$value$plusargs("BERR=%d", BERR)) BERR = 0;
        if (!$value$plusargs("SEED=%d", SEED)) SEED = 1;
        NOREAD = $test$plusargs("NOREAD");
    end

    // ---- 作り物の入口 ----
    function [63:0] pw(input integer i, input [31:0] sq, input integer j);
        reg [63:0] a;
        begin a = {sq, i[7:0], j[23:0]}; pw = a ^ (64'h9E37_79B9_7F4A_7C15 * (j + 1)) ^ {i[7:0], 56'd0}; end
    endfunction
    function [63:0] hw(input integer i, input [31:0] sq, input integer n);
        hw = {sq ^ 32'hA5A5_0000, 8'd0, i[7:0], 8'd0, n[7:0]};
    endfunction
    wire [63:0] s_d [0:3];
    wire [3:0]  s_v, s_r, s_l, s_u;
    reg  [1:0]  drop_p [0:3];
    integer n_gen [0:3];
    genvar gi;
    generate
        for (gi = 0; gi < 4; gi = gi + 1) begin : g_src
            localparam integer PB = (gi == 0) ? 32768 : (gi == 1) ? 1024 : (gi == 2) ? 512 : 4096;
            integer seq, j, gap, nw;
            reg     v;
            reg [63:0] d;
            reg     l, u;
            assign s_d[gi] = d; assign s_v[gi] = v; assign s_l[gi] = l; assign s_u[gi] = u;
            initial begin
                v = 0; d = 0; l = 0; u = 0; drop_p[gi] = 2'd0; n_gen[gi] = 0;
                @(posedge rstn);
                repeat (100 + 37 * gi) @(posedge clk);
                for (seq = 1; seq <= NREC; seq = seq + 1) begin
                    nw = 8 + PB / 8;
                    for (j = 0; j < nw; j = j + 1) begin
                        // ランダムな間（tvalid を落とす）
                        while (($random(SEED) & 15) == 0) begin v <= 0; @(posedge clk); end
                        v <= 1; l <= (j == nw - 1); u <= (j == nw - 1) && (gi == 1) && (seq % 7 == 3);
                        case (j)
                            0: d <= {gi[7:0], gi[7:0], 8'd1, 8'd1, 32'h5235_3453};
                            1: d <= {32'd1000 + seq, seq[31:0]};
                            2, 3, 4, 5, 6: d <= hw(gi, seq, j);
                            7: d <= {32'd0, PB[31:0]};
                            default: d <= pw(gi, seq, j - 8);
                        endcase
                        @(posedge clk);
                        while (!s_r[gi]) @(posedge clk);
                    end
                    v <= 0; l <= 0; u <= 0;
                    n_gen[gi] = n_gen[gi] + 1;
                    if (gi == 2 && seq % 5 == 4) begin drop_p[gi] <= 2'd1; @(posedge clk); drop_p[gi] <= 2'd0; end
                    gap = $random(SEED) & 511;
                    repeat (gap) @(posedge clk);
                end
            end
        end
    endgenerate

    // ---- AXI4-Lite ----
    reg  [11:0] awaddr = 0, araddr = 0;
    reg  [31:0] wdata = 0;
    reg         awvalid = 0, wvalid = 0, arvalid = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [31:0] rdata;
    task lw(input [11:0] a, input [31:0] v);
        begin
            @(posedge clk); awaddr <= a; wdata <= v; awvalid <= 1; wvalid <= 1;
            @(posedge clk); while (!(awready && wready)) @(posedge clk);
            awvalid <= 0; wvalid <= 0;
            while (!bvalid) @(posedge clk);
            @(posedge clk);
        end
    endtask
    reg [31:0] rv;
    task lr(input [11:0] a);
        begin
            @(posedge clk); araddr <= a; arvalid <= 1;
            @(posedge clk); while (!arready) @(posedge clk);
            arvalid <= 0;
            while (!rvalid) @(posedge clk);
            rv = rdata;
            @(posedge clk);
        end
    endtask

    // ---- HP0 の代わりの記憶 ----
    wire [48:0]  m_awaddr;
    wire [7:0]   m_awlen;
    wire [2:0]   m_awsize;
    wire [1:0]   m_awburst;
    wire [3:0]   m_awcache;
    wire         m_awvalid, m_wlast, m_wvalid, m_bready;
    reg          aw_ok = 0, w_ok = 0, m_bvalid = 0, in_burst = 0;
    wire         m_awready = aw_ok && !in_burst;       // 1 バーストずつ受ける（W は AW の後だけ）
    wire         m_wready  = w_ok && in_burst;
    reg  [1:0]   m_bresp = 0;
    wire [127:0] m_wdata;
    reg  [127:0] mem [0:(1 << 20) / 16 - 1];          // 1 MiB まで
    integer nerr = 0;
    integer nburst = 0;
    reg  [48:0]  cur_a;
    integer      cur_n, cur_len;
    reg  [1:0]   bq_resp [0:255];
    integer      bq_done = 0, bq_r = 0;
    always @(posedge clk) begin
        aw_ok <= ($random(SEED) & 3) != 0;
        w_ok  <= ($random(SEED) & 3) != 0;
        if (m_awvalid && m_awready) begin
            nburst = nburst + 1;
            cur_a <= m_awaddr; cur_n <= 0; cur_len <= m_awlen + 1; in_burst <= 1;
            if (m_awlen > 15) begin $display("tb_ring_u: NG バーストが 16 拍より長い（%0d）", m_awlen + 1); nerr = nerr + 1; end
            if (m_awaddr[3:0] != 0) begin $display("tb_ring_u: NG awaddr が 16 バイト境でない %h", m_awaddr); nerr = nerr + 1; end
            if ((m_awaddr[11:0] + 16 * (m_awlen + 1)) > 4096) begin $display("tb_ring_u: NG 4 KiB の境を越える %h len %0d", m_awaddr, m_awlen + 1); nerr = nerr + 1; end
            if (m_awaddr < BASE || m_awaddr + 16 * (m_awlen + 1) > BASE + SIZE) begin $display("tb_ring_u: NG リングの外 %h", m_awaddr); nerr = nerr + 1; end
            if (m_awsize != 3'b100 || m_awburst != 2'b01 || m_awcache != 4'b0011) begin $display("tb_ring_u: NG awsize・awburst・awcache"); nerr = nerr + 1; end
            bq_resp[(nburst - 1) % 256] = (BERR != 0 && nburst == BERR) ? 2'b10 : 2'b00;
        end
        if (m_wvalid && m_wready) begin
            mem[(cur_a - BASE) / 16 + cur_n] <= m_wdata;
            cur_n <= cur_n + 1;
            if (m_wlast != (cur_n + 1 == cur_len)) begin $display("tb_ring_u: NG wlast の位置（%0d / %0d）", cur_n + 1, cur_len); nerr = nerr + 1; end
            if (cur_n + 1 == cur_len) begin in_burst <= 0; bq_done = bq_done + 1; end
        end
        // B: 書き終えたバーストに、ランダムな遅れで順に返す
        if (m_bvalid && m_bready) begin m_bvalid <= 0; bq_r = bq_r + 1; end
        else if (!m_bvalid && bq_r < bq_done && ($random(SEED) & 7) == 0) begin
            m_bvalid <= 1; m_bresp <= bq_resp[bq_r % 256];
        end
    end

    // ---- DUT ----
    s45_ring #(.NIN(4)) dut (.aclk(clk), .aresetn(rstn),
        .s0_axis_tdata(s_d[0]), .s0_axis_tvalid(s_v[0]), .s0_axis_tready(s_r[0]), .s0_axis_tlast(s_l[0]), .s0_axis_tuser(s_u[0]),
        .s1_axis_tdata(s_d[1]), .s1_axis_tvalid(s_v[1]), .s1_axis_tready(s_r[1]), .s1_axis_tlast(s_l[1]), .s1_axis_tuser(s_u[1]),
        .s2_axis_tdata(s_d[2]), .s2_axis_tvalid(s_v[2]), .s2_axis_tready(s_r[2]), .s2_axis_tlast(s_l[2]), .s2_axis_tuser(s_u[2]),
        .s3_axis_tdata(s_d[3]), .s3_axis_tvalid(s_v[3]), .s3_axis_tready(s_r[3]), .s3_axis_tlast(s_l[3]), .s3_axis_tuser(s_u[3]),
        .rec_drop0(drop_p[0]), .rec_drop1(drop_p[1]), .rec_drop2(drop_p[2]), .rec_drop3(drop_p[3]),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(), .s_axi_bvalid(bvalid), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(), .s_axi_rvalid(rvalid), .s_axi_rready(1'b1),
        .m_axi_awaddr(m_awaddr), .m_axi_awlen(m_awlen), .m_axi_awsize(m_awsize), .m_axi_awburst(m_awburst),
        .m_axi_awlock(), .m_axi_awcache(m_awcache), .m_axi_awprot(), .m_axi_awqos(),
        .m_axi_awvalid(m_awvalid), .m_axi_awready(m_awready),
        .m_axi_wdata(m_wdata), .m_axi_wstrb(), .m_axi_wlast(m_wlast), .m_axi_wvalid(m_wvalid), .m_axi_wready(m_wready),
        .m_axi_bresp(m_bresp), .m_axi_bvalid(m_bvalid), .m_axi_bready(m_bready));

    // ---- 読み手 ----
    integer fo, k, nrd = 0;
    reg [31:0] w_now, r_now, p, len, ty;
    reg [63:0] w0, w7;
    function [63:0] mw(input [31:0] pos);        // リングの中の位置 pos（バイト）の 64 bit
        reg [127:0] b;
        begin b = mem[(pos % SIZE) / 16]; mw = pos[3] ? b[127:64] : b[63:0]; end
    endfunction
    task read_ring;
        begin
            lr(12'h014); w_now = rv;
            p = r_now;
            while (p != w_now) begin
                w0 = mw(p); w7 = mw(p + 56); ty = w0[47:40];
                len = (ty == 0) ? w7[31:0] : 64 + w7[31:0] + 64;
                $fwrite(fo, "R %0d", p);
                for (k = 0; k < len / 8 && (ty != 0 || k < 8); k = k + 1) $fwrite(fo, " %h", mw(p + 8 * k));
                $fwrite(fo, "\n");
                p = p + len;
                nrd = nrd + 1;
            end
            r_now = w_now;
            lw(12'h018, r_now);
        end
    endtask

    integer t, i, done;
    reg [31:0] ctrl0;
    initial begin
        fo = $fopen("ring_u.txt", "w");
        r_now = 0;
        repeat (10) @(posedge clk); rstn = 1;
        repeat (5) @(posedge clk);
        lr(12'h000); $display("tb_ring_u: IF_ID = %h", rv);
        if (rv !== 32'h0202_0103) begin $display("tb_ring_u: NG IF_ID"); nerr = nerr + 1; end
        lr(12'h02C); if (rv !== 32'h0021_0200) begin $display("tb_ring_u: NG PROJ %h", rv); nerr = nerr + 1; end
        lw(12'h008, BASE[31:0]); lw(12'h00C, {15'd0, BASE[48:32]}); lw(12'h010, SIZE);
        lr(12'h010); if (rv !== SIZE) begin $display("tb_ring_u: NG SIZE"); nerr = nerr + 1; end
        lw(12'h004, 32'd1);                   // EN
        lw(12'h010, 32'd4096);                // EN = 1 の間は書けない
        lr(12'h010); if (rv !== SIZE) begin $display("tb_ring_u: NG EN = 1 で SIZE が書けた"); nerr = nerr + 1; end
        done = 0;
        for (t = 0; t < 4000 && !done; t = t + 1) begin
            repeat (200 + ($random(SEED) & 1023)) @(posedge clk);
            if (!NOREAD) read_ring;
            done = (n_gen[0] == NREC && n_gen[1] == NREC && n_gen[2] == NREC && n_gen[3] == NREC);
        end
        repeat (3000) @(posedge clk);
        lr(12'h004); ctrl0 = rv;
        read_ring;                            // +NOREAD でも最後に 1 回（残ったレコードを数える）
        lr(12'h014); $display("tb_ring_u: W = %0d", rv);
        lr(12'h018); $display("tb_ring_u: R = %0d", rv);
        lr(12'h01C); $display("tb_ring_u: DROP_CNT = %0d", rv);
        lr(12'h020); $display("tb_ring_u: REC_CNT = %0d", rv);
        lr(12'h024); $display("tb_ring_u: PEAK = %0d", rv);
        lr(12'h028); $display("tb_ring_u: ERR_STAT = %h", rv);
        $display("tb_ring_u: CTRL = %h", ctrl0);
        $display("tb_ring_u: NREC = %0d SIZE = %0d BURST = %0d READ = %0d", NREC, SIZE, nburst, nrd);
        $display("tb_ring_u: 見張りの NG = %0d", nerr);
        // EN = 0 → RST
        lw(12'h004, 32'd0); repeat (50) @(posedge clk); lw(12'h004, 32'd2);
        lr(12'h014); if (rv !== 0) begin $display("tb_ring_u: NG RST の後の W = %0d", rv); nerr = nerr + 1; end
        lr(12'h004); if (rv[2] !== 1'b0) begin $display("tb_ring_u: NG RST で ERR が消えない"); nerr = nerr + 1; end
        $display("tb_ring_u: 結果の NG（見張り）= %0d", nerr);
        $fclose(fo);
        $finish;
    end
endmodule
