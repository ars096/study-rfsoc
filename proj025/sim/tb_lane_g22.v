// SPDX-License-Identifier: BSD-3-Clause
// tb_lane_g22 — lane_fft_g22 の行動模型の単体（proj025 手順 2a。proj024 の tb_lane_g21 を 8192 点に）。1 レーンに 3 フレーム（`OUT/lx.hex、1 行 = 1 サンプル 16 bit）を
// AXI の手渡しで流す（tready が 0 なら同じサンプルを出し続ける。TLAST はフレームの最後）。出口の (XK_INDEX, re, im, tlast) を `OUT/lane.txt に。
// -DFFT_STALL_AT=n で流し始めの tready の下げを入れる（実機の振る舞い。手渡しで吸えていればデータは欠けない）
`timescale 1ns / 1ps
module tb_lane_g22;
    localparam integer M = 8192, NF = 3;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rstn = 0;
    reg [31:0] din = 0;
    reg dv = 0, dl = 0;
    wire dr;
    wire [63:0] q;
    wire [15:0] qu;
    wire qv, ql;
    wire efs, etu, etm, ehalt;
    lane_fft_g22 #(.LAT(300), .READY_DELAY(5)) u (.aclk(clk), .aresetn(rstn),
        .s_axis_config_tdata(8'd1), .s_axis_config_tvalid(1'b0), .s_axis_config_tready(),
        .s_axis_data_tdata(din), .s_axis_data_tvalid(dv), .s_axis_data_tready(dr), .s_axis_data_tlast(dl),
        .m_axis_data_tdata(q), .m_axis_data_tuser(qu), .m_axis_data_tvalid(qv), .m_axis_data_tlast(ql),
        .event_frame_started(efs), .event_tlast_unexpected(etu), .event_tlast_missing(etm), .event_data_in_channel_halt(ehalt));

    reg [15:0] xm [0:NF*M-1];
    integer fd, i = 0, nout = 0, nstall = 0, nwait0 = 0, ntu = 0, ntm = 0;
    reg acc1 = 0;                           // 最初のサンプルを受けた後か（リセットの後の tready の遅れと、流し始めの下げを分けて数える）
    always @(posedge clk) begin
        if (qv) begin
            $fwrite(fd, "%0d %0d %0d %0d\n", qu[12:0], $signed(q[31:0]), $signed(q[63:32]), ql);
            nout = nout + 1;
        end
        if (rstn && dv && dr) acc1 <= 1;
        if (rstn && dv && !dr) begin if (acc1) nstall = nstall + 1; else nwait0 = nwait0 + 1; end
        if (etu) ntu = ntu + 1;
        if (etm) ntm = ntm + 1;
    end
    // 手渡し: 受けられたら次のサンプルへ
    always @(posedge clk) if (rstn && dv && dr) i <= i + 1;
    always @(negedge clk) if (rstn) begin
        if (i < NF * M) begin
            din <= {16'd0, xm[i]}; dv <= 1; dl <= ((i % M) == M - 1);
        end else begin
            dv <= 0; dl <= 0;
        end
    end
    initial begin
        $readmemh({`OUT, "/lx.hex"}, xm);
        fd = $fopen({`OUT, "/lane.txt"}, "w");
        repeat (4) @(posedge clk);
        rstn = 1;
        wait (nout == NF * M);
        repeat (5) @(posedge clk);
        $fclose(fd);
        $display("tb_lane_g22: 出た %0d・tready で待った %0d クロック（最初に受ける前の待ち %0d）・TLAST の事象 %0d / %0d", nout, nstall, nwait0, ntu, ntm);
        $finish;
    end
    initial begin #(4.0 * 8192 * 12); $display("tb_lane_g22: 時間切れ（出た %0d）", nout); $finish; end
endmodule
