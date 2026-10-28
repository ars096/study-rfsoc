// proj032 R-1b — spw_regs の単体の sim。T1 自己記述 / T2 WRST（約束を守る）/ T3 約束を破る WRST を断る（5 種）/ T4 予約と発火 / T5 取り消し・STOP
//   陽性対照 -DREGS_POSCTL（spw_regs が lane の和を数えない）: T3 の lane の和の超えが通り、不合格になる
`timescale 1ns / 1ps
module tb_spw_regs;
    localparam integer H = 14, E = 3, S = 6, NK = 8, G_L2 = 19;
    reg clk = 0, rst = 1;
    always #2 clk = ~clk;
    reg  [15:0] awaddr, araddr; reg awvalid = 0, wvalid = 0, arvalid = 0; reg [31:0] wdata;
    wire awready, wready, bvalid, arready, rvalid; wire [31:0] rdata; wire [1:0] bresp, rresp;
    reg  [63:0] tnow = 64'h0000_0001_0000_0000; always @(posedge clk) tnow <= tnow + 1;
    reg  fire = 0;
    wire wrst, cmd_run, cmd_stop; wire [31:0] ng, ndump;
    wire [H*6-1:0] cwk; wire [H*32-1:0] cdp; wire [H*3-1:0] cns; wire [H*2-1:0] cfl; wire [H*4-1:0] csl, cg, csh;
    reg  [H*64-1:0] t0 = 0;
    spw_regs #(.H(H), .E(E), .S(S), .NK(NK), .G_L2(G_L2), .CORE_PORT(2)) dut (.clk(clk), .rst(rst),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_wdata(wdata), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bvalid(bvalid), .s_axi_bresp(bresp), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rvalid(rvalid), .s_axi_rresp(rresp), .s_axi_rready(1'b1),
        .t_now(tnow), .fire(fire), .wrst(wrst), .cfg_wk(cwk), .cfg_dphi(cdp), .cfg_ns(cns), .cfg_fl(cfl), .cfg_sl(csl), .cfg_g(cg), .cfg_sh(csh),
        .ng(ng), .ndump(ndump), .cmd_run(cmd_run), .cmd_stop(cmd_stop),
        .g0(32'd77), .t0(t0), .eng_flags(48'd0), .ddr_flag(1'b0), .sink_flag(1'b0));
    task wr(input [15:0] a, input [31:0] d);
        begin
            @(negedge clk); awaddr = a; wdata = d; awvalid = 1; wvalid = 1;
            @(posedge clk); while (awready !== 1'b1) @(posedge clk);
            @(negedge clk); awvalid = 0; wvalid = 0;
            @(posedge clk);
        end
    endtask
    reg [31:0] rv;
    task rd(input [15:0] a);
        begin
            @(negedge clk); araddr = a; arvalid = 1;
            @(posedge clk); while (arready !== 1'b1) @(posedge clk);
            @(negedge clk); arvalid = 0;
            while (rvalid !== 1'b1) @(posedge clk);
            rv = rdata; @(posedge clk);
        end
    endtask
    function [15:0] sb(input integer s, input [9:0] o); sb = 16'h4000 + 16'h400 * s + o; endfunction
    integer fails = 0, w, nw, wl, runs, stops;
    reg [63:0] t_run, t_wrst_end;
    always @(posedge clk) begin
        if (cmd_run) begin runs = runs + 1; t_run = tnow; end
        if (cmd_stop) stops = stops + 1;
    end
    // wrst の長さを数える
    integer wlen, wcnt;
    always @(posedge clk) begin
        if (wrst) wlen = wlen + 1;
        if (!wrst && wlen > 0) begin wcnt = wcnt + 1; t_wrst_end = tnow; end
        if (!wrst && wlen > 0) wl = wlen;
        if (!wrst) wlen = 0;
    end
    // 照らしの番号 n（文字列を task に渡すと iverilog で化けるので番号で。番号は下の chk の順、行のコメントが中身）
    task chk(input c, input integer n); begin if (!c) begin fails = fails + 1; $display("  × 照らし %0d", n); end end endtask
    // 窓の組: 機関 0 = 8・8・16・32・64・128（和 256）、機関 1 = 128 × 2、機関 2 = 16・16・32・64 × 3。履歴の枠 = w（< 6 はチップ内、6..13 は DDR の枠 0..7）
    //   DDR の窓（w 6..13）の和 = 128 + 128 + 16 + 16 + 32 + 64·3 = 512 → 約束 [2] を破る。T2 では w 6・7 をチップ内（枠 4・5 と入れ替え）にする
    reg [2:0] ns [0:H-1]; reg [1:0] fl [0:H-1]; reg [3:0] sl [0:H-1];
    task set_all; begin for (w = 0; w < H; w = w + 1) begin wr(sb(w, 10'h108), ns[w]); wr(sb(w, 10'h120), fl[w]); wr(sb(w, 10'h124), sl[w]);
        wr(sb(w, 10'h100), w + 3); wr(sb(w, 10'h104), 32'h1000_0000 + w); wr(sb(w, 10'h128), 4'd9); wr(sb(w, 10'h014), 4'd5 + w % 3); end end endtask
    task do_wrst(input [15:0] s_, output integer ok);
        integer c0;
        begin c0 = wcnt; wr(sb(s_, 10'h008), 32'h1000); repeat (H + 80) @(posedge clk); ok = (wcnt == c0 + 1); end
    endtask
    integer ok;
    initial begin
        runs = 0; stops = 0; wlen = 0; wcnt = 0;
        for (w = 0; w < H; w = w + 1) t0[w*64 +: 64] = 64'h100 * w + 7;
        repeat (5) @(posedge clk); rst = 0; repeat (5) @(posedge clk);
        // T1
        rd(16'h0000); chk(rv == 32'h0207_0101, 1); // IF_ID
        rd(16'h0008); chk(rv == H, 2); // NSTREAM
        rd(sb(3, 10'h000)); chk(rv == 32'h0203_0300, 3); // SID s 3
        rd(sb(3, 10'h028)); chk(rv == 2, 4); // SRC
        rd(sb(13, 10'h114)); chk(rv == 32'h0000_0D07, 5); // WSTART 13
        rd(sb(14, 10'h000)); chk(rv == 0, 6); // s 14 は空き
        $display("T1 自己記述: 不合格 %0d", fails);
        // T2
        ns[0] = 5; ns[1] = 5; ns[2] = 4; ns[3] = 3; ns[4] = 2; ns[5] = 1; for (w = 0; w < 6; w = w + 1) fl[w] = 0;
        ns[6] = 1; ns[7] = 1; fl[6] = 1; fl[7] = 1;
        ns[8] = 4; ns[9] = 4; ns[10] = 3; ns[11] = 2; ns[12] = 2; ns[13] = 2; for (w = 8; w < 14; w = w + 1) fl[w] = 2;
        for (w = 0; w < H; w = w + 1) sl[w] = w;
        sl[6] = 4; sl[7] = 5; sl[4] = 6; sl[5] = 7;                      // DDR の窓: w 4・5（64・128）＋ 8..13（16・16・32・64 × 3）= 448 → まだ超える
        ns[4] = 5; ns[5] = 5; fl[4] = 0; fl[5] = 0;                       // w 4・5 を 8 MHz に: DDR = 8 + 8 + 16 + 16 + 32 + 192 = 272 → まだ
        ns[11] = 5; ns[12] = 5; ns[13] = 5;                               // DDR = 8 + 8 + 16 + 16 + 32 + 24 = 104 ≦ 256
        set_all;
        wr(sb(0, 10'h11C), 10);
        do_wrst(5, ok);
        chk(ok, 7); // T2 の WRST が通らない chk(wl == 10, 8); // wrst の長さ
        for (w = 0; w < H; w = w + 1) begin
            chk(cns[w*3 +: 3] == ns[w] && cfl[w*2 +: 2] == fl[w] && csl[w*4 +: 4] == sl[w] && cwk[w*6 +: 6] == w + 3 && cdp[w*32 +: 32] == 32'h1000_0000 + w && cg[w*4 +: 4] == 9,
                "T2 の設定の取り込み");
        end
        rd(sb(4, 10'h10C)); chk(rv == {21'd0, 3'd5, 2'd0, 6'd7}, 9); // WCUR 4
        rd(16'h0090); chk(rv == 1, 10); // WRST_CNT
        $display("T2 WRST: 不合格 %0d", fails);
        // T3 約束を破る 5 種（それぞれ 1 か所だけ変えて、断られ、設定はそのまま）
        begin : t3
            integer k; reg [5:1] want;
            for (k = 1; k <= 5; k = k + 1) begin
                case (k)
                    1: begin wr(sb(6, 10'h120), 2); wr(sb(7, 10'h120), 2); want = 5'b00001; end   // 機関 2（16・16・32・8・8・8 = 88）に 128 × 2 → 344
                    2: begin wr(sb(0, 10'h124), 8); wr(sb(8, 10'h124), 0);          // DDR の窓は T2 で 104 MHz。w 0（8）と w 8（16）の枠を入れ替えて 96、
                             wr(sb(6, 10'h124), 9); want = 5'b00010; end            // w 6（128）を DDR の枠 3 へ 224、下で w 7（128）も枠 4 へ → 352 > 256            // w 6（128）を DDR 3 へ → DDR 104 − 16 + 8 + 128 = 224 … まだ: さらに w 7 も
                    3: begin wr(sb(1, 10'h124), 2); want = 5'b00100; end           // チップ内の枠 2 が w 1 と w 2 で重なる
                    4: begin wr(sb(13, 10'h124), 15); want = 5'b01000; end         // DDR の枠 15 − 6 = 9 ≧ NK
                    5: begin wr(sb(3, 10'h108), 0); want = 5'b10000; end           // WNS 0
                endcase
                if (k == 2) wr(sb(7, 10'h124), 10);
                do_wrst(0, ok);
                rd(16'h008C);
                chk(!ok, 11); // T3 の WRST が断られない
                chk((rv[5:1] & want) != 0, 12); // WRST_BAD の印
                if (ok || (rv[5:1] & want) == 0) $display("    T3 の %0d: WRST_BAD %b", k, rv[5:1]);
                chk(cfl[6*2 +: 2] == 1 && csl[13*4 +: 4] == 13 && cns[3*3 +: 3] == 3, 13); // T3 で効いている設定が変わった
                // 元に戻す
                case (k)
                    1: begin wr(sb(6, 10'h120), 1); wr(sb(7, 10'h120), 1); end
                    2: begin wr(sb(0, 10'h124), 0); wr(sb(8, 10'h124), 8); wr(sb(6, 10'h124), 4); wr(sb(7, 10'h124), 5); end
                    3: wr(sb(1, 10'h124), 1);
                    4: wr(sb(13, 10'h124), 13);
                    5: wr(sb(3, 10'h108), 3);
                endcase
            end
        end
        rd(16'h0080); chk(rv[0] == 1, 14); // CORE_FLAGS[0]
        wr(sb(2, 10'h008), 32'h100); rd(16'h0080); chk(rv[0] == 0, 15); // CORE_FLAGS を消す
        $display("T3 断る: 不合格 %0d", fails);
        // T4 予約: ARM_WRST ＋ ARM_RUN → 発火で WRST、明けて RUN
        wr(16'h0084, 5); wr(16'h0088, 3); wr(sb(0, 10'h02C), 32'hC0FFEE);
        for (w = 0; w < H; w = w + 1) wr(sb(w, 10'h014), 4'd2 + w % 4);
        wr(sb(9, 10'h008), 32'h2004);                                        // ARM_WRST・ARM_RUN（流れ 9 に打ってもコアに効く）
        rd(sb(0, 10'h008)); chk(rv[6:5] == 2'b11, 16); // 予約の読み
        chk(runs == 0, 17); // 発火の前に RUN
        repeat (20) @(posedge clk); @(negedge clk); fire = 1; @(negedge clk); fire = 0;
        repeat (H + 40) @(posedge clk);
        chk(runs == 1, 18); // T4 の RUN が 1 回でない chk(t_run > t_wrst_end - 1, 19); // RUN が WRST の明けより前
        chk(ng == 5 && ndump == 3, 20); // NG・NDUMP の取り込み
        for (w = 0; w < H; w = w + 1) chk(csh[w*4 +: 4] == 4'd2 + w % 4, 21); // SHIFT の取り込み
        rd(sb(1, 10'h030)); chk(rv == 32'hC0FFEE, 22); // RUN_CFG
        rd(sb(1, 10'h00C)); chk(rv == (5 << (G_L2 - 12 - 5)), 23); // N_ACC（NS 5）
        rd(sb(6, 10'h068)); chk(rv == (77 << (G_L2 - 12 - 1)), 24); // RUN_F0（w 6、NS 1）
        rd(sb(0, 10'h008)); chk(rv[0] == 1 && rv[6:5] == 0, 25); // RUN の中・予約が消えた
        $display("T4 予約: 不合格 %0d", fails);
        // T5 取り消しと STOP
        wr(sb(0, 10'h008), 32'h4); wr(sb(0, 10'h008), 32'h8);
        @(negedge clk); fire = 1; @(negedge clk); fire = 0; repeat (10) @(posedge clk);
        chk(runs == 1, 26); // 取り消した予約で RUN
        wr(sb(0, 10'h008), 32'h2); repeat (3) @(posedge clk);
        chk(stops == 1, 27); // STOP
        $display("T5 取り消し・STOP: 不合格 %0d", fails);
`ifdef REGS_POSCTL
        if (fails > 0) $display("結果: 陽性対照は落ちた（期待どおり）"); else $display("結果: 陽性対照が落ちなかった ×");
`else
        if (fails == 0) $display("結果: 全部通過"); else $display("結果: 不合格 %0d", fails);
`endif
        $finish;
    end
endmodule
