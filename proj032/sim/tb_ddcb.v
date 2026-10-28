// tb_ddcb — ddcb（窓の頭の後ろを共有）の窓ごとの出力が、窓ごとに hb2 を縦に並べた参照と bit 単位で同じかを確かめる（E-3）
//   頭の流れは全窓で同じ位相（NS 1 は毎クロック、NS ≧ 2 は 2 クロックに 1 回）、ときどき全窓そろって途切れる（粗い PFB の途切れ）。
//   構成（`CFG）: 0 混ぜ（3 lane に幅の和 256・224・176 MHz）/ 1 全部 8 MHz を 1 lane に / 2 128 MHz × 6（2 本ずつ 3 lane、残り 8 頭は止める）/
//     3 どの lane も 256 MHz ちょうど（幅を混ぜ、番号の小さい窓ほど狭い）
//   陽性対照 DDCB_POSCTL: final の lane が 2 クロックに 1 回しか受けない → CFG 3 で final の待ちが溢れ、数が合わないはず
//   変種 DDCB_NOPRI: final の lane の選びから NS の優先を外す（情報: 窓ごとの待ち 4 組で間に合うか）
`timescale 1ns / 1ps
module tb_ddcb;
`include "hb_coef.vh"
    localparam integer H = 14, NF = 3, W = 24, NCYC = 24000, QD = 8192;
    reg clk = 0; always #1.953 clk = ~clk;
    reg rst = 1;
`ifndef CFG
`define CFG 0
`endif
    // 窓ごとの NS と lane
    reg [2:0] ns [0:H-1];
    reg [1:0] fl [0:H-1];
    reg [H-1:0] act;
    integer w;
    initial begin
        for (w = 0; w < H; w = w + 1) begin ns[w] = 5; fl[w] = 2; end
        act = {H{1'b1}};
        if (`CFG == 0) begin
            ns[0] = 1; fl[0] = 0;  ns[1] = 1; fl[1] = 0;                                    // 128 × 2 = 256
            ns[2] = 2; fl[2] = 1;  ns[3] = 2; fl[3] = 1;  ns[4] = 3; fl[4] = 1;  ns[5] = 3; fl[5] = 1;  ns[6] = 3; fl[6] = 1;   // 224
            ns[7] = 2; fl[7] = 2;  ns[8] = 2; fl[8] = 2;  ns[9] = 4; fl[9] = 2;             // 64 × 2 + 16 + 8 × 4 = 176
            ns[10] = 5; ns[11] = 5; ns[12] = 5; ns[13] = 5;
        end else if (`CFG == 3) begin
            // どの lane も幅の和 256 MHz ちょうど。番号の小さい窓ほど狭い（優先を外すと 128 MHz の窓が待たされる並び）
            ns[0] = 5; ns[1] = 5; ns[2] = 4; ns[3] = 3; ns[4] = 2; ns[5] = 1;               // lane 0: 8 + 8 + 16 + 32 + 64 + 128
            for (w = 0; w < 6; w = w + 1) fl[w] = 0;
            ns[6] = 2; ns[7] = 2; ns[8] = 1; fl[6] = 1; fl[7] = 1; fl[8] = 1;               // lane 1: 64 + 64 + 128
            ns[9] = 2; ns[10] = 2; ns[11] = 2; ns[12] = 2;                                   // lane 2: 64 × 4
            for (w = 9; w < 13; w = w + 1) fl[w] = 2;
            act = 14'b01111111111111;
        end else if (`CFG == 1) begin
            for (w = 0; w < H; w = w + 1) begin ns[w] = 5; fl[w] = 1; end
        end else begin
            for (w = 0; w < H; w = w + 1) begin ns[w] = 1; fl[w] = w % 3; end
            act = 14'b00000000111111;
        end
    end
    wire [H*3-1:0] cfg_ns; wire [H*2-1:0] cfg_fl;
    genvar g;
    generate for (g = 0; g < H; g = g + 1) begin : cf
        assign cfg_ns[g*3 +: 3] = ns[g]; assign cfg_fl[g*2 +: 2] = fl[g];
    end endgenerate

    // 頭の流れ
    reg  [H-1:0]   xv = 0;
    reg  [H*W-1:0] xr = 0, xi = 0;
    reg            ph = 0, gap = 0;
    integer t;
    always @(posedge clk) begin
        gap <= (($random & 63) == 0) ? ~gap : gap;
        if (!gap && !rst) ph <= ~ph;
        for (t = 0; t < H; t = t + 1) begin
`ifdef TB_FAST
            xv[t] <= !rst && !gap && act[t];                  // 陽性対照: NS ≧ 2 の頭も毎クロック → light 2 段目の枠が溢れ、flags[0] が立つはず
`else
            xv[t] <= !rst && !gap && act[t] && (ns[t] == 1 || ph);
`endif
            xr[t*W +: W] <= $random >>> 12;
            xi[t*W +: W] <= $random >>> 12;
        end
    end

    wire [NF-1:0] yv; wire [NF*4-1:0] ych; wire [NF*W-1:0] yr, yi; wire [2:0] flags;
    ddcb #(.H(H), .NF(NF), .W(W)) dut (.clk(clk), .rst(rst), .x_v(xv), .x_re(xr), .x_im(xi),
        .cfg_ns(cfg_ns), .cfg_fl(cfg_fl), .y_v(yv), .y_ch(ych), .y_re(yr), .y_im(yi), .flags(flags));

    // 参照: 窓ごとに 組 → light → 組 → light → 組 → light、final の入口は NS で選ぶ
    reg signed [W-1:0] rq_r [0:H*QD-1], rq_i [0:H*QD-1];
    integer rn [0:H-1], dn [0:H-1];
    generate for (g = 0; g < H; g = g + 1) begin : rf
        wire        p2v, p3v, p4v, pfv;
        wire [W-1:0] p2e_r, p2e_i, p2o_r, p2o_i, p3e_r, p3e_i, p3o_r, p3o_i, p4e_r, p4e_i, p4o_r, p4o_i, pfe_r, pfe_i, pfo_r, pfo_i;
        wire        l2v, l3v, l4v, fv, s2, s3, s4, sf;
        wire signed [W-1:0] l2r, l2i, l3r, l3i, l4r, l4i, fr, fi;
        pairer #(W) a2 (clk, rst, xv[g], xr[g*W +: W], xi[g*W +: W], p2v, p2e_r, p2e_i, p2o_r, p2o_i);
        hb2 #(.N(LIGHT_N), .SH(LIGHT_SH), .H(LIGHT_H), .W(W)) u2 (clk, rst, p2v, p2e_r, p2e_i, p2o_r, p2o_i, l2v, l2r, l2i, s2);
        pairer #(W) a3 (clk, rst, l2v, l2r, l2i, p3v, p3e_r, p3e_i, p3o_r, p3o_i);
        hb2 #(.N(LIGHT_N), .SH(LIGHT_SH), .H(LIGHT_H), .W(W)) u3 (clk, rst, p3v, p3e_r, p3e_i, p3o_r, p3o_i, l3v, l3r, l3i, s3);
        pairer #(W) a4 (clk, rst, l3v, l3r, l3i, p4v, p4e_r, p4e_i, p4o_r, p4o_i);
        hb2 #(.N(LIGHT_N), .SH(LIGHT_SH), .H(LIGHT_H), .W(W)) u4 (clk, rst, p4v, p4e_r, p4e_i, p4o_r, p4o_i, l4v, l4r, l4i, s4);
        wire        sv = (ns[g] <= 2) ? xv[g] : (ns[g] == 3) ? l2v : (ns[g] == 4) ? l3v : l4v;
        wire [W-1:0] sr = (ns[g] <= 2) ? xr[g*W +: W] : (ns[g] == 3) ? l2r : (ns[g] == 4) ? l3r : l4r;
        wire [W-1:0] si = (ns[g] <= 2) ? xi[g*W +: W] : (ns[g] == 3) ? l2i : (ns[g] == 4) ? l3i : l4i;
        pairer #(W) af (clk, rst, sv, sr, si, pfv, pfe_r, pfe_i, pfo_r, pfo_i);
        hb2 #(.N(FINAL_N), .SH(FINAL_SH), .H(FINAL_H), .W(W)) uf (clk, rst, pfv, pfe_r, pfe_i, pfo_r, pfo_i, fv, fr, fi, sf);
        always @(negedge clk) if (fv) begin rq_r[g*QD + rn[g]] = fr; rq_i[g*QD + rn[g]] = fi; rn[g] = rn[g] + 1; end
    end endgenerate

    integer nerr, nout, f, c;
    always @(posedge clk) for (f = 0; f < NF; f = f + 1) if (yv[f]) begin
        c = ych[f*4 +: 4];
        nout = nout + 1;
        if (c >= H || fl[c] != f) begin nerr = nerr + 1; if (nerr < 10) $display("NG: lane %0d に窓 %0d", f, c); end
        else begin
            if (dn[c] >= rn[c] || rq_r[c*QD + dn[c]] !== $signed(yr[f*W +: W]) || rq_i[c*QD + dn[c]] !== $signed(yi[f*W +: W])) begin
                nerr = nerr + 1;
                if (nerr < 10) $display("NG: 窓 %0d の %0d 番目: dut (%0d, %0d) 参照 (%0d, %0d)（参照の数 %0d）", c, dn[c],
                                        $signed(yr[f*W +: W]), $signed(yi[f*W +: W]), rq_r[c*QD + dn[c]], rq_i[c*QD + dn[c]], rn[c]);
            end
            dn[c] = dn[c] + 1;
        end
    end

    integer k, nmin;
    initial begin
        nerr = 0; nout = 0;
        for (k = 0; k < H; k = k + 1) begin rn[k] = 0; dn[k] = 0; end
        repeat (4) @(posedge clk); rst <= 0;
        repeat (NCYC) @(posedge clk);
        force xv = 0;
        repeat (400) @(posedge clk);
        nmin = 1 << 30;
        for (k = 0; k < H; k = k + 1) if (act[k]) begin
            if (dn[k] != rn[k]) begin nerr = nerr + 1; $display("NG: 窓 %0d の数 dut %0d 参照 %0d", k, dn[k], rn[k]); end
            if (rn[k] < nmin) nmin = rn[k];
            $display("窓 %2d NS %0d lane %0d: 出力 %0d", k, ns[k], fl[k], dn[k]);
        end
        $display("CFG %0d: 出力 %0d・最少の窓 %0d・不一致 %0d・flags %b", `CFG, nout, nmin, nerr, flags);
        if (nerr == 0 && flags == 3'b000 && nmin > 100) $display("結果: 全部通過"); else $display("結果: 不合格");
        $finish;
    end
endmodule

// 組にする（rst の後の最初の標本を e に）
module pairer #(parameter integer W = 24) (
    input wire clk, rst, v, input wire [W-1:0] r, i,
    output reg pv, output reg [W-1:0] er, ei, orr, oi);
    reg have = 0; reg [W-1:0] hr, hi;
    always @(posedge clk) begin
        pv <= 1'b0;
        if (rst) have <= 1'b0;
        else if (v) begin
            if (!have) begin hr <= r; hi <= i; end
            else begin er <= hr; ei <= hi; orr <= r; oi <= i; pv <= 1'b1; end
            have <= ~have;
        end
    end
endmodule
