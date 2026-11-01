// proj032 P-9 — rmux4 の照合（自己判定）。口 4 本がそれぞれ長さの乱れたレコードを出し（valid の途切れあり）、出口の tready も乱す。
//   照らすこと: 出口のレコードは 1 つの口のものが途切れずに続く・口ごとの順番・拍の数と tlast の位置・失くしも重ねも無い・どの口も進む
//   後半は tready を 1 に固定し、口が全部詰まっているときの速さ（拍 / クロック）を測る
//   -DRMUX4_POSCTL（rmux4 の陽性対照: レコードの途中で口を放す）では落ちることを見る
`timescale 1ns / 1ps
module tb_rmux4;
    reg clk = 0;
    always #2 clk = ~clk;
    reg aresetn = 0;
    localparam integer NREC = 300;       // 口ごとのレコードの数

    reg  [127:0] sd [0:3];
    reg  [3:0]   sv = 0, sl = 0;
    wire [3:0]   sr;
    wire [127:0] md;
    wire         mv, ml;
    reg          mr = 0;
    wire [15:0]  mdrop;
    rmux4 dut (.aclk(clk), .aresetn(aresetn),
        .s0_axis_tdata(sd[0]), .s0_axis_tvalid(sv[0]), .s0_axis_tready(sr[0]), .s0_axis_tlast(sl[0]),
        .s1_axis_tdata(sd[1]), .s1_axis_tvalid(sv[1]), .s1_axis_tready(sr[1]), .s1_axis_tlast(sl[1]),
        .s2_axis_tdata(sd[2]), .s2_axis_tvalid(sv[2]), .s2_axis_tready(sr[2]), .s2_axis_tlast(sl[2]),
        .s3_axis_tdata(sd[3]), .s3_axis_tvalid(sv[3]), .s3_axis_tready(sr[3]), .s3_axis_tlast(sl[3]),
        .m_axis_tdata(md), .m_axis_tvalid(mv), .m_axis_tready(mr), .m_axis_tlast(ml),
        .d0_drop(4'h1), .d1_drop(4'h2), .d2_drop(4'h4), .d3_drop(4'h8), .m_drop(mdrop));

    // ---- 口ごとの出し手: 拍 = {口 8・レコード番号 32・拍の番号 16・長さ 16・乱数 56} ----
    integer rec [0:3], bt [0:3], len [0:3];
    reg     gap_on = 1;
    integer i, seed = 7;
    function [15:0] rlen(input integer s, input integer r);
        rlen = 8 + ((s * 7919 + r * 104729) % 33);
    endfunction
    initial for (i = 0; i < 4; i = i + 1) begin rec[i] = 0; bt[i] = 0; len[i] = rlen(i, 0); sd[i] = 0; end
    always @(posedge clk) if (aresetn) begin : prod
        integer k;
        for (k = 0; k < 4; k = k + 1) begin
            if (!sv[k] || sr[k]) begin                  // この拍が受けられた（か、出していない）ので、次の拍を出してよい
                if (sv[k]) begin
                    if (bt[k] + 1 == len[k]) begin rec[k] = rec[k] + 1; bt[k] = 0; len[k] = rlen(k, rec[k]); end
                    else bt[k] = bt[k] + 1;
                end
                if (rec[k] < NREC && (!gap_on || ($random(seed) & 3) != 0)) begin
                    sv[k] <= 1'b1;
                    sd[k] <= {k[7:0], rec[k][31:0], bt[k][15:0], len[k][15:0], {24'd0, $random(seed)}};
                    sl[k] <= (bt[k] + 1 == len[k]);
                end else sv[k] <= 1'b0;
            end                                          // 受けられていなければ valid と中身を保つ
        end
    end

    // ---- 出口の照らし ----
    integer fails = 0, got [0:3], cur = -1, cbt = 0, beats = 0, nrec = 0;
    integer t_fast0 = 0, b_fast0 = 0;
    reg     fast = 0;
    initial for (i = 0; i < 4; i = i + 1) got[i] = 0;
    always @(posedge clk) if (mv && mr) begin : chk
        integer s, r, b, n;
        s = md[127:120]; r = md[119:88]; b = md[87:72]; n = md[71:56];
        beats = beats + 1;
        if (cur < 0) begin
            if (b != 0) begin fails = fails + 1; if (fails < 8) $display("  × 頭でない拍でレコードが始まった（口 %0d・レコード %0d・拍 %0d）", s, r, b); end
            if (s > 3) begin fails = fails + 1; if (fails < 8) $display("  × 口 %0d", s); end
            else if (r != got[s]) begin fails = fails + 1; if (fails < 8) $display("  × 口 %0d のレコード %0d（期待 %0d）", s, r, got[s]); end
            cur = s; cbt = 0;
        end else begin
            if (s != cur || b != cbt) begin fails = fails + 1; if (fails < 8) $display("  × レコードの途中に別の拍（口 %0d 拍 %0d、期待 口 %0d 拍 %0d）", s, b, cur, cbt); end
        end
        if (ml != (b + 1 == n)) begin fails = fails + 1; if (fails < 8) $display("  × tlast の位置（口 %0d レコード %0d 拍 %0d / %0d、tlast %0d）", s, r, b, n, ml); end
        cbt = cbt + 1;
        if (ml) begin if (cur >= 0 && cur <= 3) got[cur] = got[cur] + 1; cur = -1; nrec = nrec + 1; end
    end

    integer c, t;
    initial begin
        repeat (10) @(posedge clk);
        aresetn = 1;
        // 前半: 入口に途切れ・出口の tready を乱す
        for (t = 0; t < 40000 && (got[0] + got[1] + got[2] + got[3]) < 2 * NREC; t = t + 1) begin
            @(negedge clk); mr = ($random(seed) % 4) != 0;
        end
        // 後半: 入口は途切れなし・tready 1。拍 / クロックを測る
        @(negedge clk); gap_on = 0; mr = 1; fast = 1; t_fast0 = $time; b_fast0 = beats;
        for (t = 0; t < 100000 && (got[0] + got[1] + got[2] + got[3]) < 4 * NREC; t = t + 1) @(negedge clk);
        repeat (20) @(negedge clk);
        $display("レコード: 口 0 %0d・口 1 %0d・口 2 %0d・口 3 %0d（各 %0d が期待）・拍 %0d", got[0], got[1], got[2], got[3], NREC, beats);
        $display("速さ（後半、入口に途切れなし）: %0d 拍 / %0d クロック = %.3f", beats - b_fast0, ($time - t_fast0) / 4, (beats - b_fast0) * 4.0 / ($time - t_fast0));
        if (mdrop !== 16'h8421) begin fails = fails + 1; $display("  × m_drop = %h（期待 8421）", mdrop); end
        for (c = 0; c < 4; c = c + 1) if (got[c] != NREC) begin fails = fails + 1; $display("  × 口 %0d のレコードが %0d", c, got[c]); end
`ifdef RMUX4_POSCTL
        if (fails > 0) $display("結果: 陽性対照は落ちた（期待どおり、%0d 件）", fails); else $display("結果: 陽性対照が落ちなかった ×");
`else
        if (fails == 0) $display("結果: 全部通過"); else $display("結果: 不合格 %0d", fails);
`endif
        $finish;
    end
endmodule
