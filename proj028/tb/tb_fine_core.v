// SPDX-License-Identifier: BSD-3-Clause
// proj028 F-4 — fine_core の試験台。入口（1 行 = {tlast, tuser 22, tdata 512}）を valid を時々落として流し、
//   IP の出口（k1 ＋ 16 レーン）とレコード（64 bit）を書く。出口の tready はランダム
`timescale 1ns/1ps
`default_nettype none
module tb_fine_core;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [534:0] mem [0:`NBEAT-1];
    reg [511:0] tdata = 0; reg [21:0] tuser = 0; reg tlast = 0, tvalid = 0; wire tready;
    wire [63:0] o_d; wire o_l, o_v; reg o_r = 0;
    wire [8:0] flags; wire [31:0] n_rec; wire [16*64-1:0] ip_d; wire [12:0] ip_k1; wire ip_v;
    fine_core #(.LO_FILE(`LO_HEX), .HI_FILE(`HI_HEX), .TA_FILE(`TA_HEX), .TB_FILE(`TB_HEX)) dut (.clk(clk), .rst(rst),
        .s_axis_tdata(tdata), .s_axis_tuser(tuser), .s_axis_tlast(tlast), .s_axis_tvalid(tvalid), .s_axis_tready(tready),
        .shift(4'd7), .m_axis_tdata(o_d), .m_axis_tlast(o_l), .m_axis_tvalid(o_v), .m_axis_tready(o_r),
        .flags(flags), .n_rec(n_rec), .dbg_ip_tdata(ip_d), .dbg_ip_k1(ip_k1), .dbg_ip_v(ip_v));
    integer i, k, fi, fr, seed = 8, nrec_w = 0;
    reg took = 0;
    always @(posedge clk) took <= tvalid && tready;
    always @(posedge clk) o_r <= ($random(seed) % 5 != 0);
    always @(posedge clk) if (o_v && o_r) begin $fwrite(fr, "%0d %h\n", o_l, o_d); nrec_w = nrec_w + 1; end
    always @(posedge clk) if (ip_v) begin
        $fwrite(fi, "%0d", ip_k1);
        for (k = 0; k < 16; k = k + 1) $fwrite(fi, " %0d %0d", $signed(ip_d[64*k +: 28]), $signed(ip_d[64*k + 32 +: 28]));
        $fwrite(fi, "\n");
    end
    initial begin
        $readmemh(`IN_HEX, mem);
        fi = $fopen(`IP_TXT, "w"); fr = $fopen(`REC_TXT, "w");
        repeat (20) @(posedge clk); @(negedge clk); rst = 0;
        i = 0;
        while (i < `NBEAT) begin
            @(negedge clk);
            if (took) i = i + 1;                    // 握手は posedge で記録したもの（negedge で tready を見ると数え違える）
            if (took && mem[i-1][534]) begin             // ch の最後の拍を渡したら、読み出しの分だけ間を空ける（本番の ch は 163 フレームで十分長い）
                tvalid = 0; repeat (`CHGAP) @(negedge clk);
            end
            if (i < `NBEAT && ($random(seed) % 6 != 0)) begin
                tvalid = 1; tdata = mem[i][511:0]; tuser = mem[i][533:512]; tlast = mem[i][534];
            end else tvalid = 0;
        end
        @(negedge clk); tvalid = 0;
        wait (nrec_w == `NREC);
        repeat (50) @(posedge clk);
        $display("flags %0d n_rec %0d words %0d", flags, n_rec, nrec_w);
        $fclose(fi); $fclose(fr);
        $finish;
    end
    initial begin #`TMAX; $display("ERROR: 時間切れ（words %0d n_rec %0d flags %0d）", nrec_w, n_rec, flags); $fclose(fi); $fclose(fr); $finish; end
endmodule
`default_nettype wire
