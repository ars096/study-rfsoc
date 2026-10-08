// SPDX-License-Identifier: BSD-3-Clause
// proj016 — time_core 単体の sim（S-T1）。1 秒を BPS クロックに縮めて、PPS・予約発火・原点・エポックを確かめる
//   判定はこの tb の中（「tb_time: NG ...」を数え、最後に「結果: 全部通過」/「結果: 失敗」）
`timescale 1ns / 1ps
module tb_time;
    localparam integer BPS = 2000, BLANK = 1000, MISS = 3000;
    reg clk = 0, cclk = 0;
    always #1.953 clk = ~clk;
    always #5.000 cclk = ~cclk;      // ctrl_aclk（非同期）
    reg rstn = 0, crstn = 0;
    reg ptrig = 0, pcomp = 0;
    reg  [7:0]  awaddr = 0, araddr = 0;
    reg         awvalid = 0, wvalid = 0, bready = 1, arvalid = 0, rready = 1;
    reg  [31:0] wdata = 0;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [1:0]  bresp, rresp;
    wire [31:0] rdata;
    wire [63:0] t_out;
    wire        go_out;
    wire [3:0]  ev_out;
    time_core #(.BEATS_PER_SEC(BPS), .BLANK_BEATS(BLANK), .MISS_BEATS(MISS)) dut (
        .aclk(clk), .aresetn(rstn), .ctrl_aclk(cclk), .ctrl_aresetn(crstn), .pps_trig_i(ptrig), .pps_comp_i(pcomp),
        .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .t_out(t_out), .go_out(go_out), .ev_out(ev_out));
    // コアの側の 1 段
    reg [63:0] t_loc; reg go_loc; reg [3:0] ev_loc;
    always @(posedge clk) begin t_loc <= t_out; go_loc <= go_out; ev_loc <= ev_out; end

    integer ng = 0;
    task axw(input [7:0] a, input [31:0] d); begin
        @(posedge clk); awaddr <= a; wdata <= d; awvalid <= 1; wvalid <= 1;
        @(posedge clk); while (!(awready)) @(posedge clk);
        awvalid <= 0; wvalid <= 0;
        while (!bvalid) @(posedge clk);
    end endtask
    reg [31:0] rd_v;
    task axr(input [7:0] a); begin
        @(posedge clk); araddr <= a; arvalid <= 1;
        @(posedge clk); while (!arready) @(posedge clk);
        arvalid <= 0;
        while (!rvalid) @(posedge clk);
        rd_v = rdata;
    end endtask

    // コアの t_loc と time_core の T がいつも一致すること
    always @(posedge clk) if (rstn && dut.T > 4 && t_loc !== dut.T) begin
        $display("tb_time: NG t_loc %0d != T %0d", t_loc, dut.T); ng = ng + 1;
    end
    // 発火: go_loc が立ったクロックの T を記録
    reg [63:0] go_t; integer n_go = 0;
    always @(posedge clk) if (go_loc) begin go_t <= dut.T; n_go = n_go + 1; end

    // PPS の発生器（周期 per、幅 100 クロック。gl > 0 なら縁の gl クロック後にもう 1 発）
    integer per = BPS, gl = 0, pps_on = 1, cnt = 1990;   // 解除の頃に PPS が H になる位相
    // リセットの間も回す（解除の瞬間に PPS が H のときに偽の縁を作らないことも、ここで確かめている）
    always @(posedge clk) begin
        cnt <= (cnt + 1 >= per) ? 0 : cnt + 1;
        ptrig <= pps_on && ((cnt < 100) || (gl > 0 && cnt >= gl && cnt < gl + 20));
        pcomp <= pps_on && (cnt < 100);
    end

    reg [63:0] t0, sa; reg [31:0] lo, hi, c0;
    integer i, b0, g0, m0;
    initial begin
        #50 crstn = 1;
        #50 rstn = 1;
        repeat (20) @(posedge clk);
        // ---- 原点 ----
        if (ev_loc[3] !== 1'b1) begin $display("tb_time: NG ANCHORED の既定が 0 でない（ev[3] が 0）"); ng = ng + 1; end
        axw(8'h08, 32'h8);   // ANCHORED を 1
        repeat (4) @(posedge clk);
        if (ev_loc[3] !== 1'b0) begin $display("tb_time: NG ANCHORED を立てても ev[3] が 1"); ng = ng + 1; end
        axr(8'h00); if (rd_v !== 32'h0020_7101) begin $display("tb_time: NG ID"); ng = ng + 1; end
        axr(8'h04); if (rd_v !== BPS) begin $display("tb_time: NG PARAM"); ng = ng + 1; end
        // ---- T の読み（LO で HI を固定）----
        axr(8'h18); lo = rd_v; axr(8'h1C); hi = rd_v;
        if ({hi, lo} > dut.T || dut.T - {hi, lo} > 40) begin $display("tb_time: NG T_LO/HI"); ng = ng + 1; end
        // ---- PPS: 3 秒ぶん。間隔 = BPS、BAD 0 ----
        repeat (3 * BPS + 200) @(posedge clk);
        axr(8'h20); axr(8'h28); if (rd_v !== BPS) begin $display("tb_time: PT_INT %0d", rd_v); begin $display("tb_time: NG TRIG の間隔"); ng = ng + 1; end end
        axr(8'h2C); c0 = rd_v; if (c0 < 3) begin $display("tb_time: NG TRIG の数"); ng = ng + 1; end
        axr(8'h30); axr(8'h38); if (rd_v !== BPS) begin $display("tb_time: NG COMP の間隔"); ng = ng + 1; end
        axr(8'h44); if (rd_v !== 0) begin $display("tb_time: NG BAD が 0 でない（正しい間隔で）"); ng = ng + 1; end
        axr(8'h08); if (rd_v[5] !== 1'b1 || rd_v[6] !== 1'b1) begin $display("tb_time: NG alive が立たない"); ng = ng + 1; end
        // ---- 許容の内（+1）は BAD にならない・外（+3）は BAD ----
        per = BPS + 1; repeat (3 * BPS) @(posedge clk);
        axr(8'h44); if (rd_v !== 0) begin $display("tb_time: NG 間隔 +1 で BAD（許容 1 の内）"); ng = ng + 1; end
        b0 = 0;
        per = BPS + 3;
        fork
            begin repeat (3 * BPS) @(posedge clk); end
            begin repeat (3 * BPS) begin @(posedge clk); if (ev_loc[1]) b0 = b0 + 1; end end
        join
        axr(8'h44); if (rd_v < 2) begin $display("tb_time: NG 間隔 +3 で BAD が数えられない"); ng = ng + 1; end
        if (b0 < 2) begin $display("tb_time: NG 間隔 +3 で ev[1] が立たない"); ng = ng + 1; end
        per = BPS;
        repeat (2 * BPS) @(posedge clk);
        // ---- グリッチ ----
        g0 = 0; gl = 300;
        fork
            begin repeat (2 * BPS) @(posedge clk); end
            begin repeat (2 * BPS) begin @(posedge clk); if (ev_loc[2]) g0 = g0 + 1; end end
        join
        gl = 0;
        axr(8'h40); if (rd_v[15:0] < 1) begin $display("tb_time: NG グリッチが数えられない"); ng = ng + 1; end
        if (rd_v[31:16] !== 0) begin $display("tb_time: NG COMP 側にグリッチ（入れていない）"); ng = ng + 1; end
        if (g0 < 1) begin $display("tb_time: NG グリッチで ev[2] が立たない"); ng = ng + 1; end
        axr(8'h44); if (rd_v !== 32'd2 && rd_v !== 32'd3 && rd_v !== 32'd4) begin $display("tb_time: BAD %0d", rd_v); end
        // ---- 欠落 ----
        m0 = 0; pps_on = 0;
        fork
            begin repeat (2 * MISS) @(posedge clk); end
            begin repeat (2 * MISS) begin @(posedge clk); if (ev_loc[0]) m0 = m0 + 1; end end
        join
        axr(8'h48); if (rd_v !== 1) begin $display("tb_time: NG MISS が 1 にならない"); ng = ng + 1; end
        if (m0 < 100) begin $display("tb_time: NG 欠落で ev[0] が立たない"); ng = ng + 1; end
        axr(8'h08); if (rd_v[5] !== 1'b0) begin $display("tb_time: NG 欠落で alive が落ちない"); ng = ng + 1; end
        pps_on = 1; repeat (2 * BPS) @(posedge clk);
        if (ev_loc[0] !== 1'b0) begin $display("tb_time: NG PPS が戻っても ev[0] が落ちない"); ng = ng + 1; end
        // ---- 予約発火: 3 通りの先（100・777・5 秒先）----
        for (i = 0; i < 3; i = i + 1) begin
            t0 = dut.T;
            sa = t0 + ((i == 0) ? 100 : (i == 1) ? 777 : 5 * BPS + 13);
            n_go = 0;
            axw(8'h10, sa[31:0]); axw(8'h14, sa[63:32]); axw(8'h08, 32'h1);
            while (dut.T < sa + 10) @(posedge clk);
            if (n_go !== 1) begin $display("tb_time: NG 発火が 1 回でない"); ng = ng + 1; end
            else if (go_t !== sa) begin $display("tb_time: go_t %0d / START_AT %0d", go_t, sa); begin $display("tb_time: NG 発火のビートが START_AT と違う"); ng = ng + 1; end end
            axr(8'h50); lo = rd_v; axr(8'h54); hi = rd_v;
            if ({hi, lo} !== sa) begin $display("tb_time: NG FIRED が START_AT と違う"); ng = ng + 1; end
            axr(8'h08); if (rd_v[3] !== 1'b1 || rd_v[0] !== 1'b0) begin $display("tb_time: NG 発火の後の状態"); ng = ng + 1; end
        end
        // 遅すぎ（5 ビート先）・遠すぎ（2^41 先）・取り消し
        sa = dut.T + 100; n_go = 0;
        axw(8'h10, sa[31:0]); axw(8'h14, sa[63:32]);
        while (dut.T < sa - 12) @(posedge clk);
        axw(8'h08, 32'h1);
        repeat (40) @(posedge clk);
        axr(8'h08); if (rd_v[1] !== 1'b1) begin $display("tb_time: NG 遅すぎが立たない"); ng = ng + 1; end
        if (n_go !== 0) begin $display("tb_time: NG 遅すぎで発火した"); ng = ng + 1; end
        sa = dut.T + 64'h0000_0200_0000_0000;
        axw(8'h10, sa[31:0]); axw(8'h14, sa[63:32]); axw(8'h08, 32'h1);
        repeat (4) @(posedge clk);
        axr(8'h08); if (rd_v[2] !== 1'b1 || rd_v[0] !== 1'b0) begin $display("tb_time: NG 遠すぎが立たない"); ng = ng + 1; end
        sa = dut.T + 600; n_go = 0;
        axw(8'h10, sa[31:0]); axw(8'h14, sa[63:32]); axw(8'h08, 32'h1);
        repeat (50) @(posedge clk);
        axw(8'h08, 32'h2);
        while (dut.T < sa + 10) @(posedge clk);
        if (n_go !== 0) begin $display("tb_time: NG 取り消しても発火した"); ng = ng + 1; end
        // ---- エポック: リセットを 1 回 → 2、ANCHORED は 0 に戻る ----
        axr(8'h4C); if (rd_v !== 1) begin $display("tb_time: EPOCH %0d", rd_v); begin $display("tb_time: NG EPOCH が 1 でない"); ng = ng + 1; end end
        @(posedge clk); rstn <= 0; repeat (10) @(posedge clk); rstn <= 1;
        repeat (40) @(posedge clk);
        axr(8'h4C); if (rd_v !== 2) begin $display("tb_time: EPOCH %0d", rd_v); begin $display("tb_time: NG リセットの後 EPOCH が 2 でない"); ng = ng + 1; end end
        if (ev_loc[3] !== 1'b1) begin $display("tb_time: NG リセットの後も ANCHORED のまま"); ng = ng + 1; end
        if (ng == 0) $display("tb_time: 結果: 全部通過");
        else         $display("tb_time: 結果: 失敗（%0d 件）", ng);
        $finish;
    end
endmodule
