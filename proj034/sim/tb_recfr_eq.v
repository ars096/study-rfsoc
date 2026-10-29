// SPDX-License-Identifier: BSD-3-Clause
// tb_recfr_eq — rec_fr に NCH を引数にした版（proj024 手順 2d）が、NCH 4096 では 567fda2 の版（sim/rec_fr_ref.v）と
// 同じ振る舞いをすることを、同じ入力で並べて回し、全部の出口をクロックごとに比べて確かめる。
//   組 A: NS 2・SNAP 0・W7HI 1（wide_core の形）/ 組 B: NS 1・SNAP 1・NSN 2048（spec_core の形）
//   入力: seq はでたらめな間隔で +1（ときどき +1 以外に跳ぶ）、REC_CTRL・snap_ok・m_tready もでたらめ。
//   rd_data は各 DUT が出した rd_ch・rd_s・rd_snap から LAT 段遅れで作る（持ち主の口の模型。DUT ごとに別に持つ）
// -DEQ_POSCTL: 新しい版を NCH 2048 にする（陽性対照。違いが出るべき）
`timescale 1ns / 1ps
module tb_recfr_eq;
    localparam integer NCLK = 3000000;
`ifdef EQ_POSCTL
    localparam integer NCH_NEW = 2048;
`else
    localparam integer NCH_NEW = 4096;
`endif
    reg clk = 0;
    always #2 clk = ~clk;
    reg rst = 1;
    integer cyc = 0, ndiff = 0, first_diff = -1;
    integer nrec_ok [0:1], nrec_bad [0:1], nlate [0:1];
    initial begin nrec_ok[0] = 0; nrec_ok[1] = 0; nrec_bad[0] = 0; nrec_bad[1] = 0; nlate[0] = 0; nlate[1] = 0; end

    // ---- 共通の入力 ----
    reg [31:0] seqA0 = 0, seqA1 = 100, seqB0 = 7;
    reg [1:0]  allA = 0, oneA = 0;
    reg        allB = 0, oneB = 0, snapB = 0, sokB = 1;
    reg        trdy = 1;
    reg [31:0] cdA0 = 3000, cdA1 = 5000, cdB0 = 4000;
    reg [63:0] w7 = 64'h0000_1234_0000_0567;
    wire [767:0] hdrA = {{12{32'hA5A5_0000}} ^ {24{seqA1[15:0]}}, {12{32'h5A5A_0000}} ^ {24{seqA0[15:0]}}};
    wire [383:0] hdrB = {12{32'h3C3C_0000}} ^ {24{seqB0[15:0]}};
    always @(posedge clk) begin
        cyc <= cyc + 1;
        trdy <= ($random % 8) != 0;
        if (($random % 4096) == 0) allA <= $random;
        if (($random % 4096) == 0) begin allB <= $random; snapB <= $random; end
        if (($random % 3000) == 0) oneA <= $random;
        if (($random % 3000) == 0) oneB <= $random;
        if (($random % 512) == 0) sokB <= ($random % 8) != 0;
        if (cdA0 == 0) begin seqA0 <= seqA0 + ((($random % 16) == 0) ? 32'd5 : 32'd1); cdA0 <= 2000 + ({$random} % 12000); end else cdA0 <= cdA0 - 1;
        if (cdA1 == 0) begin seqA1 <= seqA1 + ((($random % 16) == 0) ? 32'd9 : 32'd1); cdA1 <= 2000 + ({$random} % 12000); end else cdA1 <= cdA1 - 1;
        if (cdB0 == 0) begin seqB0 <= seqB0 + ((($random % 16) == 0) ? 32'd3 : 32'd1); cdB0 <= 2000 + ({$random} % 14000); end else cdB0 <= cdB0 - 1;
        if (($random % 50000) == 0) w7 <= {$random, $random};
    end

    // ---- 持ち主の口の模型（LAT 5: rd_ch → 4 段 → rd_data）----
    function [63:0] dat(input [1:0] s, input sn, input [16:0] ch);
        dat = {ch * 32'h9E37_79B1, 12'd0, sn, s, ch};
    endfunction

    // ---- 組 A ----
    wire        rA_req, rA_rdsn, rB_req, rB_rdsn, nA_req, nA_rdsn, nB_req, nB_rdsn;
    wire [1:0]  rA_oc, rA_late, rA_drop, nA_oc, nA_late, nA_drop, rA_s, nA_s, rB_s, nB_s;
    wire        rB_oc, rB_late, rB_drop, nB_oc, nB_late, nB_drop;
    wire [11:0] rA_ch, rB_ch;
    wire [$clog2(NCH_NEW)-1:0] nA_ch, nB_ch;
    wire [63:0] rA_d, rB_d, nA_d, nB_d;
    wire        rA_v, rA_l, rA_u, rB_v, rB_l, rB_u, nA_v, nA_l, nA_u, nB_v, nB_l, nB_u;
    reg         gA_r = 0, gA_n = 0, gB_r = 0, gB_n = 0;
    always @(posedge clk) begin gA_r <= !rst && rA_req; gA_n <= !rst && nA_req; gB_r <= !rst && rB_req; gB_n <= !rst && nB_req; end
    reg [63:0] pA_r [1:4], pA_n [1:4], pB_r [1:4], pB_n [1:4];
    integer j;
    always @(posedge clk) begin
        pA_r[1] <= dat(rA_s, rA_rdsn, {5'd0, rA_ch}); pA_n[1] <= dat(nA_s, nA_rdsn, {{(17-$clog2(NCH_NEW)){1'b0}}, nA_ch});
        pB_r[1] <= dat(rB_s, rB_rdsn, {5'd0, rB_ch}); pB_n[1] <= dat(nB_s, nB_rdsn, {{(17-$clog2(NCH_NEW)){1'b0}}, nB_ch});
        for (j = 2; j <= 4; j = j + 1) begin pA_r[j] <= pA_r[j-1]; pA_n[j] <= pA_n[j-1]; pB_r[j] <= pB_r[j-1]; pB_n[j] <= pB_n[j-1]; end
    end

    rec_fr_ref #(.NS(2), .S_BASE(3), .CORE(8'd2), .LAT(5), .SNAP(0), .W7HI(1)) u_rA (.clk(clk), .rst(rst),
        .seq({seqA1, seqA0}), .hdr(hdrA), .rec_all(allA), .rec_one(oneA), .rec_snap(2'b00), .snap_ok(2'b00),
        .rd_snap(rA_rdsn), .one_clr(rA_oc), .late(rA_late), .drop(rA_drop), .req(rA_req), .gnt(gA_r), .rd_s(rA_s), .rd_ch(rA_ch),
        .rd_data(pA_r[4]), .m_tdata(rA_d), .m_tvalid(rA_v), .m_tready(trdy), .m_tlast(rA_l), .m_tuser(rA_u), .w7hi(w7));
    rec_fr #(.NS(2), .S_BASE(3), .CORE(8'd2), .LAT(5), .SNAP(0), .W7HI(1), .NCH(NCH_NEW)) u_nA (.clk(clk), .rst(rst),
        .seq({seqA1, seqA0}), .hdr(hdrA), .rec_all(allA), .rec_one(oneA), .rec_snap(2'b00), .snap_ok(2'b00),
        .rd_snap(nA_rdsn), .one_clr(nA_oc), .late(nA_late), .drop(nA_drop), .req(nA_req), .gnt(gA_n), .rd_s(nA_s), .rd_ch(nA_ch),
        .rd_data(pA_n[4]), .m_tdata(nA_d), .m_tvalid(nA_v), .m_tready(trdy), .m_tlast(nA_l), .m_tuser(nA_u), .w7hi(w7));
    // ---- 組 B ----
    rec_fr_ref #(.NS(1), .S_BASE(2), .CORE(8'd0), .LAT(5), .SNAP(1), .NSN(2048)) u_rB (.clk(clk), .rst(rst),
        .seq(seqB0), .hdr(hdrB), .rec_all(allB), .rec_one(oneB), .rec_snap(snapB), .snap_ok(sokB),
        .rd_snap(rB_rdsn), .one_clr(rB_oc), .late(rB_late), .drop(rB_drop), .req(rB_req), .gnt(gB_r), .rd_s(rB_s), .rd_ch(rB_ch),
        .rd_data(pB_r[4]), .m_tdata(rB_d), .m_tvalid(rB_v), .m_tready(trdy), .m_tlast(rB_l), .m_tuser(rB_u), .w7hi(32'd0));
    rec_fr #(.NS(1), .S_BASE(2), .CORE(8'd0), .LAT(5), .SNAP(1), .NSN(2048), .NCH(NCH_NEW)) u_nB (.clk(clk), .rst(rst),
        .seq(seqB0), .hdr(hdrB), .rec_all(allB), .rec_one(oneB), .rec_snap(snapB), .snap_ok(sokB),
        .rd_snap(nB_rdsn), .one_clr(nB_oc), .late(nB_late), .drop(nB_drop), .req(nB_req), .gnt(gB_n), .rd_s(nB_s), .rd_ch(nB_ch),
        .rd_data(pB_n[4]), .m_tdata(nB_d), .m_tvalid(nB_v), .m_tready(trdy), .m_tlast(nB_l), .m_tuser(nB_u), .w7hi(32'd0));

    // ---- 比べる（全部の出口。m_tdata は m_tvalid のときだけ）----
    wire [255:0] oA_r = {rA_rdsn, rA_oc, rA_late, rA_drop, rA_req, rA_s, 5'd0, rA_ch, rA_v, rA_l, rA_u, rA_v ? rA_d : 64'd0};
    wire [255:0] oA_n = {nA_rdsn, nA_oc, nA_late, nA_drop, nA_req, nA_s, {(17-$clog2(NCH_NEW)){1'b0}}, nA_ch, nA_v, nA_l, nA_u, nA_v ? nA_d : 64'd0};
    wire [255:0] oB_r = {rB_rdsn, rB_oc, rB_late, rB_drop, rB_req, rB_s, 5'd0, rB_ch, rB_v, rB_l, rB_u, rB_v ? rB_d : 64'd0};
    wire [255:0] oB_n = {nB_rdsn, nB_oc, nB_late, nB_drop, nB_req, nB_s, {(17-$clog2(NCH_NEW)){1'b0}}, nB_ch, nB_v, nB_l, nB_u, nB_v ? nB_d : 64'd0};
    always @(posedge clk) if (!rst) begin
        if (oA_r !== oA_n || oB_r !== oB_n) begin
            if (first_diff < 0) begin
                first_diff = cyc;
                $display("tb_recfr_eq: 最初の違い cyc %0d A %h / %h  B %h / %h", cyc, oA_r[95:0], oA_n[95:0], oB_r[95:0], oB_n[95:0]);
            end
            ndiff = ndiff + 1;
        end
        // 出たレコードを数える（旧版の側）
        if (rA_v && trdy && rA_l) begin if (rA_u) nrec_bad[0] = nrec_bad[0] + 1; else nrec_ok[0] = nrec_ok[0] + 1; end
        if (rB_v && trdy && rB_l) begin if (rB_u) nrec_bad[1] = nrec_bad[1] + 1; else nrec_ok[1] = nrec_ok[1] + 1; end
        nlate[0] = nlate[0] + rA_late[0] + rA_late[1];
        nlate[1] = nlate[1] + rB_late;
    end
    initial begin
        repeat (8) @(posedge clk);
        @(negedge clk) rst = 0;
        repeat (NCLK) @(posedge clk);
        $display("tb_recfr_eq: NCH %0d・%0d クロック・違うクロック %0d（最初 %0d）・組 A のレコード 出た %0d / 捨てた %0d / late %0d・組 B 出た %0d / 捨てた %0d / late %0d",
                 NCH_NEW, NCLK, ndiff, first_diff, nrec_ok[0], nrec_bad[0], nlate[0], nrec_ok[1], nrec_bad[1], nlate[1]);
        if (ndiff == 0 && nrec_ok[0] > 50 && nrec_ok[1] > 20 && nrec_bad[0] > 0 && nrec_bad[1] > 0)
            $display("結果: 全部通過");
        else
            $display("結果: 不合格");
        $finish;
    end
endmodule
