// SPDX-License-Identifier: BSD-3-Clause
// proj028 F-8 — adc_snap の単体の sim。標本 = 通し番号（valid の拍ごとに 16 ずつ進む 16 bit）を流し、ARM → DONE → AXI4-Lite で全部読んで照合する
//   照合: (1) ID・DEPTH  (2) 溜めた拍の数 = DEPTH  (3) 語 w の中身 = {標本 2j+1, 標本 2j}（拍 w>>3・帯 j = w&7）で、標本は base + 16·拍 + i と続く
//         (4) base は ARM を書いた時点の通し番号の後で、数拍の内  (5) 溜め中の valid の欠けの数 = 流した欠けの数
//   -DGAPS: 溜めている間にも valid を落とす（標本は valid の拍だけで続く）  -DBAD: 陽性対照（読む帯をずらす → (3) で落ちる）
//   -DDEPTH_FULL: 本番の深さ 8192
`timescale 1ns/1ps
`default_nettype none
module tb_adc_snap;
`ifdef DEPTH_FULL
    localparam integer DEPTH = 8192, AW = 13;
`else
    localparam integer DEPTH = 64, AW = 6;
`endif
    reg clk = 1'b0, aresetn = 1'b0;
    always #2 clk = ~clk;
    reg  [255:0] s_data;
    reg          s_valid = 1'b0;
    reg  [18:0]  awaddr = 0, araddr = 0;
    reg          awvalid = 0, wvalid = 0, bready = 1, arvalid = 0, rready = 1;
    reg  [31:0]  wdata = 0;
    wire         awready, wready, bvalid, arready, rvalid;
    wire [1:0]   bresp, rresp;
    wire [31:0]  rdata;
    adc_snap #(.DEPTH(DEPTH), .AW(AW)) dut (
        .clk(clk), .aresetn(aresetn), .s_data(s_data), .s_valid(s_valid),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_wdata(wdata), .s_axi_wvalid(wvalid),
        .s_axi_wready(wready), .s_axi_bvalid(bvalid), .s_axi_bresp(bresp), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rvalid(rvalid),
        .s_axi_rresp(rresp), .s_axi_rready(rready));

    // 標本の源: valid の拍ごとに通し番号 cnt を 16 進める。欠けは疑似乱数で
    reg [15:0] cnt = 16'd0;
    reg [31:0] lfsr = 32'h1234_5678;
    reg        gaps_on = 1'b1;               // ARM の前は欠けを入れる（pre_gap を動かす）
    integer    ngap_cap = 0;
    integer    i;
    always @(posedge clk) begin
        lfsr <= {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
        s_valid <= !(gaps_on && lfsr[3:0] == 4'd0);
        if (s_valid) cnt <= cnt + 16'd16;
    end
    always @(*) for (i = 0; i < 16; i = i + 1) s_data[16*i +: 16] = cnt + i[15:0];
    always @(posedge clk) if (dut.busy && !dut.v_q) ngap_cap = ngap_cap + 1;   // DUT が数える拍と同じ定義

    task axi_w(input [18:0] a, input [31:0] d);
        begin
            @(posedge clk); awaddr <= a; wdata <= d; awvalid <= 1; wvalid <= 1;
            @(posedge clk); while (!(awready && wready)) @(posedge clk);
            awvalid <= 0; wvalid <= 0;
            while (!bvalid) @(posedge clk);
        end
    endtask
    task axi_r(input [18:0] a, output [31:0] d);
        begin
            @(posedge clk); araddr <= a; arvalid <= 1;
            @(posedge clk); while (!arready) @(posedge clk);
            arvalid <= 0;
            while (!rvalid) @(posedge clk);
            d = rdata;
        end
    endtask

    reg [31:0] v, st, nb, dep, gp;
    reg [15:0] base, arm_cnt, e0, e1;
    integer    w, b, l, nbad, t0;
    initial begin
        nbad = 0;
        repeat (10) @(posedge clk);
        aresetn <= 1'b1;
        repeat (20) @(posedge clk);
        axi_r(19'h00, v);   if (v !== 32'h0280_00C8) begin $display("NG: ID %h", v); nbad = nbad + 1; end
        axi_r(19'h0C, dep); if (dep !== DEPTH) begin $display("NG: DEPTH %0d", dep); nbad = nbad + 1; end
`ifndef GAPS
        gaps_on <= 1'b0;
`endif
        arm_cnt = cnt;
        axi_w(19'h04, 32'd1);
        t0 = 0;
        st = 0;
        while (!(st & 2) && t0 < DEPTH * 4 + 100) begin axi_r(19'h04, st); t0 = t0 + 1; end
        if (!(st & 2)) begin $display("NG: DONE が立たない（STATUS %h）", st); nbad = nbad + 1; end
        gaps_on <= 1'b1;
        axi_r(19'h08, nb); if (nb !== DEPTH) begin $display("NG: 溜めた拍 %0d", nb); nbad = nbad + 1; end
        axi_r(19'h14, gp); if (gp !== ngap_cap) begin $display("NG: 溜め中の欠け %0d（流した %0d）", gp, ngap_cap); nbad = nbad + 1; end
        for (w = 0; w < DEPTH * 8; w = w + 1) begin
`ifdef BAD
            axi_r(19'h40000 | (((w ^ 1) & 19'h3FFFF) << 2), v);
`else
            axi_r(19'h40000 | (w << 2), v);
`endif
            b = w >> 3; l = w & 7;
            if (w == 0) base = v[15:0];
            e0 = base + 16 * b + 2 * l;
            e1 = e0 + 16'd1;
            if (v !== {e1, e0}) begin
                if (nbad < 8) $display("NG: 語 %0d（拍 %0d 帯 %0d）= %h（期待 %h）", w, b, l, v, {e1, e0});
                nbad = nbad + 1;
            end
        end
        if (base - arm_cnt > 16'd16 * 8) begin $display("NG: 溜め始めが ARM から遠い（ARM 時 %0d・溜め始め %0d）", arm_cnt, base); nbad = nbad + 1; end
        $display("溜め中の欠け %0d・ARM 時の通し番号 %0d・溜め始め %0d・読んだ語 %0d", gp, arm_cnt, base, DEPTH * 8);
        if (nbad == 0) $display("結果: 全部通過");
        else $display("結果: 不合格（違い %0d）", nbad);
        $finish;
    end
endmodule
`default_nettype wire
