// tb_hbmc — hbmc（多 ch の半帯域）の ch ごとの出力が、ch ごとに 1 つずつ置いた hb2 と bit 単位で同じかを確かめる（E-3）
//   `FINAL を定義すると final（N 67）、しないと light（N 15）。ch は NU 本を使い、乱数の順で（同じ ch の連続・途切れ・毎クロックを含む）。
//   値は乱数（ときどき飽和する大きさ）。陽性対照 HBMC_POSCTL: hbmc の書き戻しの ch を 1 つずらす → 落ちるはず
`timescale 1ns / 1ps
module tb_hbmc;
`include "hb_coef.vh"
`ifdef FINAL
    localparam integer N = FINAL_N, SH = FINAL_SH;
    localparam [18*N-1:0] HH = FINAL_H;
`else
    localparam integer N = LIGHT_N, SH = LIGHT_SH;
    localparam [18*N-1:0] HH = LIGHT_H;
`endif
    localparam integer NCH = 16, CW = 4, NU = 13, W = 24, NP = 6000, QD = 4096;
    reg clk = 0; always #1.953 clk = ~clk;
    reg rst = 1, v = 0;
    reg [CW-1:0] ch = 0;
    reg signed [W-1:0] er = 0, ei = 0, orr = 0, oi = 0;

    wire dv; wire [CW-1:0] dch; wire signed [W-1:0] dr, di; wire dsat;
    hbmc #(.N(N), .SH(SH), .H(HH), .W(W), .NCH(NCH), .CW(CW)) dut (
        .clk(clk), .rst(rst), .in_v(v), .in_ch(ch), .e_re(er), .e_im(ei), .o_re(orr), .o_im(oi),
        .out_v(dv), .out_ch(dch), .y_re(dr), .y_im(di), .sat(dsat));

    // 参照: ch ごとの hb2
    reg  signed [W-1:0] rq_r [0:NU*QD-1], rq_i [0:NU*QD-1];
    reg                 rq_s [0:NU*QD-1];
    integer rn [0:NU-1], dn [0:NU-1];
    integer nerr, nout, nsat, k;
    genvar g;
    generate for (g = 0; g < NU; g = g + 1) begin : rf
        wire rv, rs; wire signed [W-1:0] rr, ri;
        hb2 #(.N(N), .SH(SH), .H(HH), .W(W)) u (
            .clk(clk), .rst(rst), .in_v(v && ch == g), .e_re(er), .e_im(ei), .o_re(orr), .o_im(oi),
            .out_v(rv), .y_re(rr), .y_im(ri), .sat(rs));
        always @(negedge clk) if (rv) begin   // 記録は立ち下がりで
            rq_r[g*QD + rn[g]] = rr; rq_i[g*QD + rn[g]] = ri; rq_s[g*QD + rn[g]] = rs; rn[g] = rn[g] + 1;
        end
    end endgenerate

    always @(posedge clk) if (dv) begin   // 照合は立ち上がりで（参照は立ち下がりで記録済み）
        nout = nout + 1;
        if (dch >= NU) begin
            nerr = nerr + 1; if (nerr < 10) $display("NG: 使っていない ch %0d が出た", dch);
        end else begin
            if (dn[dch] >= rn[dch] || rq_r[dch*QD + dn[dch]] !== dr || rq_i[dch*QD + dn[dch]] !== di || rq_s[dch*QD + dn[dch]] !== dsat) begin
                nerr = nerr + 1;
                if (nerr < 10) $display("NG: ch %0d の %0d 番目: dut (%0d, %0d) 参照 (%0d, %0d)（参照の数 %0d）",
                                        dch, dn[dch], dr, di, rq_r[dch*QD + dn[dch]], rq_i[dch*QD + dn[dch]], rn[dch]);
            end
            if (dsat) nsat = nsat + 1;
            dn[dch] = dn[dch] + 1;
        end
    end

    function signed [W-1:0] rv24(input integer big);
        rv24 = big ? $random : ($random >>> 9);     // 大きい（飽和しうる）か、15 bit 程度
    endfunction
    integer t, mode, big, seed;
    initial begin
        nerr = 0; nout = 0; nsat = 0;
        for (k = 0; k < NU; k = k + 1) begin rn[k] = 0; dn[k] = 0; end
        repeat (4) @(posedge clk); rst <= 0;
        for (t = 0; t < NP; t = t + 1) begin
            @(posedge clk);
            mode = ($random & 32'h7fffffff) % 10;
            big  = ((t / 300) % 7 == 3);                  // 大きい値が続く区間（飽和の道も照合する）
            if (mode < 2) v <= 0;                            // 途切れ
            else begin
                v <= 1;
                if (mode < 4) ch <= ch;                      // 同じ ch が続く
                else ch <= ($random & 32'h7fffffff) % NU;
                er <= rv24(big); ei <= rv24(big); orr <= rv24(big); oi <= rv24(big);
            end
            if (t == NP / 2) begin                            // 途中で rst（ch ごとの数えが 0 に戻るか）。流れているものが出きってから
                @(posedge clk); v <= 0; repeat (60) @(posedge clk); rst <= 1; @(posedge clk); rst <= 0;
            end
        end
        @(posedge clk); v <= 0;
        repeat (60) @(posedge clk);
        for (k = 0; k < NU; k = k + 1)
            if (dn[k] != rn[k]) begin nerr = nerr + 1; $display("NG: ch %0d の数 dut %0d 参照 %0d", k, dn[k], rn[k]); end
        $display("N %0d・ch %0d 本・出力 %0d・飽和 %0d・不一致 %0d", N, NU, nout, nsat, nerr);
        if (nerr == 0 && nout > 1000) $display("結果: 全部通過"); else $display("結果: 不合格");
        $finish;
    end
endmodule
