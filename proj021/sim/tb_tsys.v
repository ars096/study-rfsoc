// SPDX-License-Identifier: BSD-3-Clause
// proj016 — time_core ＋ win_core（NW = 2・TP）＋ spec_core をつないだ sim（S-T3 同時開始・S-T4 設定の取り込み・S-T2 の系での確かめ）
//   実機の BD と同じく、t_out・go_out・ev_out を win_core・spec_core の t_in・go_in・tev_in へ直につなぐ。入力は毎クロック valid
// 判定（この tb の中、「tb_tsys: NG」を数える）:
//   1. ARM した窓 0・窓 1・TP・全帯域が、どれも T = START_AT + 1 のクロックに RUN を受ける（RUN_T・TP_RUN_T も START_AT + 1）
//   2. ダンプの DUMP_T = そのダンプの最初のフレームの最初のサンプルがコアに入ったクロックの T（tb がコアの中を覗いて独立に記録）。
//      全帯域は DUMP_T(k) − DUMP_T(0) = k·N·512 ちょうど、窓は k·N·4096 からのずれを報告（z の出方の揺れ）
//   3. RUN の間に SHIFT・CFG_ID を書き換えても、その RUN の間ずっと使われる SHIFT（窓 0 の sh_q・全帯域の run_shift）は RUN の値、
//      DUMP_CFG は RUN の CFG_ID
//   4. 健全性: PPS をつないでいない → [0] = 1、ANCHORED → [3] = 0、入力に 1 回だけ振り切れを入れる → [4] がそのダンプに立つ、
//      窓 1 は WRST の後に CFG_ID を変えてから RUN → [6] = 1、帳簿 [15:14] = 0
//   5. TANCH: (ANCH_F, ANCH_T) = ADC のフレーム ANCH_F の頭のビートが入ったクロックの T
//   6. 予約の WRST: 窓 1 だけ ARM_WRST → T = START_AT2 + 1 に WRST、ARM していない窓 0・全帯域は RUN も WRST も受けない
//   7. 窓 1 に ARM_RUN と ARM_WRST を両方 → WRST は START_AT3 + 1、RUN は WRST が明けてから。ダンプ 0 が閉じる
`timescale 1ns / 1ps
module tb_tsys;
    reg clk = 0, cclk = 0;
    always #1.953 clk = ~clk;
    always #5.000 cclk = ~cclk;
    reg aresetn = 0, crstn = 0;
    reg  [255:0] tdata = 0;
    reg          tvalid = 0;
    // AXI: 0 = 窓・1 = 全帯域（どちらも s45_core_0。旧番地で書き xa で直す）/ 2 = time_core（8 bit）
    reg  [19:0] awaddr = 0, araddr = 0;
    reg  [2:0]  awv = 0, wv = 0, arv = 0;
    reg  [31:0] wdata = 0;
    wire [2:0]  awr, wr_, bv, arr, rv_;
    wire [31:0] rd0, rd1, rd2;
    wire [63:0] t_out; wire go_out; wire [3:0] ev_out;
    time_core u_t (.aclk(clk), .aresetn(aresetn), .ctrl_aclk(cclk), .ctrl_aresetn(crstn), .pps_trig_i(1'b0), .pps_comp_i(1'b0),
        .s_axi_awaddr(awaddr[7:0]), .s_axi_awprot(3'd0), .s_axi_awvalid(awv[2]), .s_axi_awready(awr[2]),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wv[2]), .s_axi_wready(wr_[2]), .s_axi_bresp(), .s_axi_bvalid(bv[2]), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr[7:0]), .s_axi_arprot(3'd0), .s_axi_arvalid(arv[2]), .s_axi_arready(arr[2]),
        .s_axi_rdata(rd2), .s_axi_rresp(), .s_axi_rvalid(rv_[2]), .s_axi_rready(1'b1),
        .t_out(t_out), .go_out(go_out), .ev_out(ev_out));
    // proj021 手順 2-1: BD と同じく s45_core（FULL = 1）1 個に。窓（0）と全帯域（1）の AXI はどちらもこのコアへ。
    //   tb の中の番地は旧番地のまま書き、タスクで v2 の番地に直す（xa。表は proj021/README の手順 2-1）
    wire        c_awr, c_wr, c_bv, c_arr, c_rv;
    wire [31:0] c_rd;
    reg  [19:0] c_aw = 0, c_ar = 0;
    s45_core #(.NW(2), .N_ACC_DEFAULT(2), .G_L2(12), .FULL(1), .FULL_N_ACC_DEFAULT(8), .FULL_STABLE_N(0)) u_c (
        .aclk(clk), .aresetn(aresetn), .s_axis_tdata(tdata), .s_axis_tvalid(tvalid), .s_axis_tready(),
        .s_axis_full_tdata(tdata), .s_axis_full_tvalid(tvalid), .s_axis_full_tready(), .full_gb_stat(32'd0), .full_adc_stat(32'd0), .full_sel(),
        .s_axi_awaddr(c_aw), .s_axi_awprot(3'd0), .s_axi_awvalid(awv[0] | awv[1]), .s_axi_awready(c_awr),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wv[0] | wv[1]), .s_axi_wready(c_wr), .s_axi_bresp(), .s_axi_bvalid(c_bv), .s_axi_bready(1'b1),
        .s_axi_araddr(c_ar), .s_axi_arprot(3'd0), .s_axi_arvalid(arv[0] | arv[1]), .s_axi_arready(c_arr),
        .s_axi_rdata(c_rd), .s_axi_rresp(), .s_axi_rvalid(c_rv), .s_axi_rready(1'b1),
        .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(32'd0), .adc_stat(32'd0),
        .t_in(t_out), .go_in(go_out), .tev_in(ev_out));
    assign awr[1:0] = {2{c_awr}}; assign wr_[1:0] = {2{c_wr}}; assign bv[1:0] = {2{c_bv}};
    assign arr[1:0] = {2{c_arr}}; assign rv_[1:0] = {2{c_rv}}; assign rd0 = c_rd; assign rd1 = c_rd;
    // 旧番地 → v2 の番地
    function [11:0] wmap(input [7:0] o);   // 窓の旧レジスタ → 流れのブロックの中
        case (o)
            8'h00: wmap = 12'h000; 8'h04: wmap = 12'h004; 8'h08: wmap = 12'h008; 8'h0C: wmap = 12'h00C; 8'h10: wmap = 12'h010;
            8'h14: wmap = 12'h014; 8'h18: wmap = 12'h018; 8'h1C: wmap = 12'h01C; 8'h20: wmap = 12'h070; 8'h24: wmap = 12'h074;
            8'h28: wmap = 12'h078; 8'h2C: wmap = 12'h07C; 8'h30: wmap = 12'h03C; 8'h34: wmap = 12'h048; 8'h38: wmap = 12'h040;
            8'h3C: wmap = 12'h044; 8'h40: wmap = 12'h04C; 8'h44: wmap = 12'h218; 8'h48: wmap = 12'h21C; 8'h4C: wmap = 12'h220;
            8'h50: wmap = 12'h068; 8'h54: wmap = 12'h06C; 8'h58: wmap = 12'h100; 8'h5C: wmap = 12'h104; 8'h60: wmap = 12'h108;
            8'h64: wmap = 12'h10C; 8'h68: wmap = 12'h110; 8'h6C: wmap = 12'h200; 8'h70: wmap = 12'h204; 8'h78: wmap = 12'h11C;
            8'h7C: wmap = 12'h214; 8'h80: wmap = 12'h208; 8'h84: wmap = 12'h20C; 8'h88: wmap = 12'h210; 8'h8C: wmap = 12'h114;
            8'h94: wmap = 12'h02C; 8'h98: wmap = 12'h030; 8'h9C: wmap = 12'h034; 8'hA0: wmap = 12'h050; 8'hA4: wmap = 12'h054;
            8'hA8: wmap = 12'h058; 8'hAC: wmap = 12'h05C; 8'hB0: wmap = 12'h060; 8'hB4: wmap = 12'h064; 8'hB8: wmap = 12'h038;
            default: begin wmap = 12'hFFF; $display("tb_tsys: NG 旧番地の表に無い窓のレジスタ %02x", o); end
        endcase
    endfunction
    function [11:0] smap(input [7:0] o);   // 全帯域の旧レジスタ → 流れのブロックの中
        if (o < 8'h20 || o == 8'h40) smap = (o == 8'h40) ? 12'h04C : o;
        else if (o >= 8'h58 && o <= 8'hB4) smap = o + 12'h1A8;
        else case (o)
            8'h20: smap = 12'h070; 8'h24: smap = 12'h074; 8'h28: smap = 12'h078; 8'h2C: smap = 12'h07C; 8'h30: smap = 12'h03C;
            8'h34: smap = 12'h048; 8'h38: smap = 12'h040; 8'h3C: smap = 12'h044; 8'h44: smap = 12'h260; 8'h48: smap = 12'h264;
            8'h4C: smap = 12'h268; 8'h50: smap = 12'h068; 8'h54: smap = 12'h06C; 8'hC0: smap = 12'h02C; 8'hC4: smap = 12'h030;
            8'hC8: smap = 12'h050; 8'hCC: smap = 12'h054; 8'hD0: smap = 12'h058; 8'hD4: smap = 12'h05C; 8'hD8: smap = 12'h060;
            8'hDC: smap = 12'h064; 8'hE0: smap = 12'h038;
            default: begin smap = 12'hFFF; $display("tb_tsys: NG 旧番地の表に無い全帯域のレジスタ %02x", o); end
        endcase
    endfunction
    function [19:0] xa(input integer s, input [19:0] a);
        if (s == 2) xa = a;
        else if (s == 1) xa = (a[15:8] == 8'h00) ? 20'h04800 + smap(a[7:0]) : 20'hC0000 + a[15:0] + ((a[15:8] == 8'h01) ? 20'h01000 : 20'h0);
        else if (a[19:17] == 3'd4) begin                // ADC の共通（表 A）
            if (a[16:8] != 9'd0) xa = {4'd0, a[15:0]};   // TP のレジスタ・リング
            else if (a[7:0] >= 8'h10) xa = a[7:0] + 20'h10;
            else begin xa = 20'hFFFFF; $display("tb_tsys: NG 旧番地の表に無い表 A %02x", a[7:0]); end
        end else if (a[16:15] != 2'd0) xa = 20'h80000 + a;                   // 仮の読み窓
        else xa = 20'h04000 + 20'h00400 * a[19:17] + wmap(a[7:0]);
    endfunction
    wire [63:0] T = u_t.T;

    integer ng = 0;
    task axw(input integer s, input [19:0] a, input [31:0] d); begin
        @(posedge clk); awaddr <= a; c_aw <= xa(s, a); wdata <= d; awv[s] <= 1; wv[s] <= 1;
        @(posedge clk); while (!awr[s]) @(posedge clk);
        awv[s] <= 0; wv[s] <= 0;
        while (!bv[s]) @(posedge clk);
    end endtask
    reg [31:0] rv;
    task axr(input integer s, input [19:0] a); begin
        @(posedge clk); araddr <= a; c_ar <= xa(s, a); arv[s] <= 1;
        @(posedge clk); while (!arr[s]) @(posedge clk);
        arv[s] <= 0;
        while (!rv_[s]) @(posedge clk);
        rv = (s == 0) ? rd0 : (s == 1) ? rd1 : rd2;
    end endtask
    reg [63:0] r64;
    task axr64(input integer s, input [19:0] a); reg [31:0] lo; begin axr(s, a); lo = rv; axr(s, a + 4); r64 = {rv, lo}; end endtask

    // ---- 入力: 小さな雑音、OVR_AT のビートだけ 1 サンプルを振り切れに ----
    integer seed = 7, l;
    reg [63:0] t_ovr = 0;
    reg [63:0] ovr_at = 64'hFFFF_FFFF_FFFF_FFFF;
    always @(posedge clk) begin
        if (!aresetn) tvalid <= 0;
        else begin
            for (l = 0; l < 16; l = l + 1) tdata[16*l +: 16] <= ($random(seed) % 2000);
            if (T == ovr_at) begin tdata[16*5 +: 16] <= 16'sd32767; t_ovr <= T + 1; end
            tvalid <= 1;
        end
    end

    // ---- コアの中を覗いて独立に記録 ----
    // 窓 0: フレーム f の最初の z が wspec に入ったクロックの T / 全帯域: フレーム f の最初のビートを受けたクロックの T / ADC のフレーム
    reg [63:0] tw0 [0:255], ts [0:1023], ta [0:1023];
    always @(posedge clk) begin
        if (u_c.u_win.g_w[0].zv && u_c.u_win.g_w[0].u_ws.wa == 12'd0) tw0[u_c.u_win.g_w[0].u_ws.fin[7:0]] <= T;
        if (u_c.g_full.u_full.in_acc && u_c.g_full.u_full.m_in == 9'd0) ts[u_c.g_full.u_full.fin[9:0]] <= T;
        if (tvalid && u_c.u_win.a_cnt[8:0] == 9'd0) ta[u_c.u_win.a_fin[9:0]] <= T;
    end
    // RUN・WRST を受けたクロック
    reg [63:0] t_r0, t_r1, t_rtp, t_rs, t_wr0, t_wr1;
    integer n_r0 = 0, n_r1 = 0, n_rtp = 0, n_rs = 0, n_wr0 = 0, n_wr1 = 0;
    always @(posedge clk) begin
        if (u_c.u_win.g_w[0].cmd_run)  begin t_r0  <= T; n_r0  = n_r0 + 1; end
        if (u_c.u_win.g_w[1].cmd_run)  begin t_r1  <= T; n_r1  = n_r1 + 1; end
        if (u_c.u_win.tp_run)          begin t_rtp <= T; n_rtp = n_rtp + 1; end
        if (u_c.g_full.u_full.cmd_run)         begin t_rs  <= T; n_rs  = n_rs + 1; end
        if (u_c.u_win.g_w[0].cmd_wrst) begin t_wr0 <= T; n_wr0 = n_wr0 + 1; end
        if (u_c.u_win.g_w[1].cmd_wrst) begin t_wr1 <= T; n_wr1 = n_wr1 + 1; end
    end
    // 3. RUN の間に使われる SHIFT
    reg  chk_sh = 0;
    integer n_shbad_w = 0, n_shbad_s = 0;
    always @(posedge clk) if (chk_sh) begin
        if (u_c.u_win.g_w[0].u_ws.sh_q !== 4'd7) n_shbad_w = n_shbad_w + 1;
        if (u_c.g_full.u_full.run_shift !== 4'd7)        n_shbad_s = n_shbad_s + 1;
    end

    localparam NDW = 4, NAW = 2, NDS = 6, NAS = 8;
    reg [63:0] sa, sa2, dt0w, dt0s, dtk;
    reg [31:0] seqw, seqs, dk, df0, dh, dcfg;
    integer kw, ks, maxdev, dev, ovr_w, ovr_s;
    reg [63:0] dts [0:15], dtw [0:15];
    reg [31:0] dhs [0:15], dhw [0:15];
    initial begin
        #40 crstn = 1;
        repeat (8) @(posedge clk);
        aresetn <= 1;
        repeat (16) @(posedge clk);
        axr(0, 20'h00000); if (rv !== 32'h0203_0000) begin $display("tb_tsys: NG 窓 0 の SID %08x", rv); ng = ng + 1; end
        axr(1, 20'h00000); if (rv !== 32'h0201_0200) begin $display("tb_tsys: NG 全帯域の SID %08x", rv); ng = ng + 1; end
        axr(2, 20'h00);    if (rv !== 32'h0202_0102) begin $display("tb_tsys: NG time_core の IF_ID %08x", rv); ng = ng + 1; end
        $display("tb_tsys: 起動（T %0d）", T);
        axw(2, 20'h08, 32'h8);                         // ANCHORED
        // 窓 0・1: k 5・NS 1、窓 0 は CFG 0x1234 で WRST、窓 1 も 0x1234 で WRST した後 CFG を 0x5555 に（[6] が立つはず）
        axw(0, 20'h00094, 32'h1234); axw(0, 20'h20094, 32'h1234);
        axw(0, 20'h00058, 5); axw(0, 20'h00060, 1); axw(0, 20'h20058, 9); axw(0, 20'h20060, 1);
        axw(0, 20'h00008, 32'h1000); axw(0, 20'h20008, 32'h1000);
        axw(0, 20'h20094, 32'h5555);
        axw(0, 20'h0000C, NAW); axw(0, 20'h00010, NDW); axw(0, 20'h00014, 7);
        axw(0, 20'h2000C, NAW); axw(0, 20'h20010, NDW); axw(0, 20'h20014, 7);
        axw(1, 20'h0C0, 32'h1234); axw(1, 20'h00C, NAS); axw(1, 20'h010, NDS); axw(1, 20'h014, 7);
        repeat (3000) @(posedge clk);
        $display("tb_tsys: 設定を書いた（T %0d）", T);
        // TANCH
        axw(0, 20'h80010, 32'h10);
        repeat (1200) @(posedge clk);
        axr(0, 20'h8003C); if (rv[1:0] !== 2'b10) begin $display("tb_tsys: NG TANCH が終わらない %b", rv[1:0]); ng = ng + 1; end
        axr64(0, 20'h8002C); dk = r64[31:0]; axr64(0, 20'h80034);
        if (r64 !== ta[dk[9:0]]) begin $display("tb_tsys: NG ANCH_T %0d / フレーム %0d の頭の T %0d", r64, dk, ta[dk[9:0]]); ng = ng + 1; end
        // ---- 1. 予約の RUN（窓 0・1・TP・全帯域を ARM）----
        sa = T + 4000;
        axw(2, 20'h10, sa[31:0]); axw(2, 20'h14, sa[63:32]);
        axw(0, 20'h00008, 32'h4); axw(0, 20'h20008, 32'h4); axw(0, 20'h80010, 32'h4); axw(1, 20'h008, 32'h4);
        axw(2, 20'h08, 32'h1);
        while (T < sa + 4) @(posedge clk);
        if (n_r0 !== 1 || n_r1 !== 1 || n_rtp !== 1 || n_rs !== 1) begin $display("tb_tsys: NG RUN の回数 %0d %0d %0d %0d", n_r0, n_r1, n_rtp, n_rs); ng = ng + 1; end
        if (t_r0 !== sa + 1 || t_r1 !== sa + 1 || t_rtp !== sa + 1 || t_rs !== sa + 1) begin
            $display("tb_tsys: NG RUN のクロック 窓0 %0d 窓1 %0d TP %0d 全帯域 %0d（START_AT + 1 = %0d）", t_r0, t_r1, t_rtp, t_rs, sa + 1); ng = ng + 1; end
        else $display("tb_tsys: 4 コアとも T = START_AT + 1 = %0d に RUN", sa + 1);
        axr64(0, 20'h000B0); if (r64 !== sa + 1) begin $display("tb_tsys: NG 窓 0 の RUN_T %0d", r64); ng = ng + 1; end
        axr64(0, 20'h80040); if (r64 !== sa + 1) begin $display("tb_tsys: NG TP_RUN_T %0d", r64); ng = ng + 1; end
        axr64(1, 20'h0D8);   if (r64 !== sa + 1) begin $display("tb_tsys: NG 全帯域の RUN_T %0d", r64); ng = ng + 1; end
        axr64(2, 20'h50);    if (r64 !== sa) begin $display("tb_tsys: NG FIRED %0d", r64); ng = ng + 1; end
        // ---- 3. RUN の間に SHIFT・CFG を書き換える ----
        repeat (40) @(posedge clk);
        chk_sh = 1;
        axw(0, 20'h00014, 3); axw(0, 20'h00094, 32'h9999); axw(1, 20'h014, 3); axw(1, 20'h0C0, 32'h9999);
        // 振り切れを全帯域のダンプ 2 の中ほどに（窓では z の時刻が遅れるので、どのダンプに立つかは範囲で見る）
        ovr_at = sa + 2 + 512 * NAS * 2 + 2000;
        // ---- 2・4. ダンプを読む ----
        axr(0, 20'h0001C); seqw = rv; axr(1, 20'h01C); seqs = rv;
        kw = 0; ks = 0;
        while (kw < NDW || ks < NDS) begin
            repeat (200) @(posedge clk);
            if (ks < NDS) begin
                axr(1, 20'h01C);
                if (rv != seqs) begin
                    seqs = rv;
                    axr(1, 20'h030); dk = rv; axr(1, 20'h038); df0 = rv;
                    axr64(1, 20'h0C8); dts[ks] = r64; axr(1, 20'h0D0); dhs[ks] = rv; axr(1, 20'h0D4); dcfg = rv;
                    if (dk !== ks) begin $display("tb_tsys: NG 全帯域 DUMP_K %0d（期待 %0d）", dk, ks); ng = ng + 1; end
                    if (r64 !== ts[df0[9:0]]) begin $display("tb_tsys: NG 全帯域 ダンプ %0d の DUMP_T %0d / 頭の T %0d", ks, r64, ts[df0[9:0]]); ng = ng + 1; end
                    if (r64 - dts[0] !== ks * NAS * 512) begin $display("tb_tsys: NG 全帯域 ダンプ %0d の間隔 %0d", ks, r64 - dts[0]); ng = ng + 1; end
                    if (dcfg !== 32'h1234) begin $display("tb_tsys: NG 全帯域 DUMP_CFG %08x", dcfg); ng = ng + 1; end
                    ks = ks + 1;
                    $display("tb_tsys: 全帯域 ダンプ %0d（T %0d）", ks - 1, T);
                end
            end
            if (kw < NDW) begin
                axr(0, 20'h0001C);
                if (rv != seqw) begin
                    seqw = rv;
                    axr(0, 20'h00030); dk = rv; axr(0, 20'h00038); df0 = rv;
                    axr64(0, 20'h000A0); dtw[kw] = r64; axr(0, 20'h000A8); dhw[kw] = rv; axr(0, 20'h000AC); dcfg = rv;
                    if (dk !== kw) begin $display("tb_tsys: NG 窓 0 DUMP_K %0d（期待 %0d）", dk, kw); ng = ng + 1; end
                    if (r64 !== tw0[df0[7:0]]) begin $display("tb_tsys: NG 窓 0 ダンプ %0d の DUMP_T %0d / 頭の z の T %0d", kw, r64, tw0[df0[7:0]]); ng = ng + 1; end
                    if (dcfg !== 32'h1234) begin $display("tb_tsys: NG 窓 0 DUMP_CFG %08x", dcfg); ng = ng + 1; end
                    kw = kw + 1;
                    $display("tb_tsys: 窓 0 ダンプ %0d（T %0d）", kw - 1, T);
                end
            end
        end
        chk_sh = 0;
        if (n_shbad_w != 0 || n_shbad_s != 0) begin $display("tb_tsys: NG RUN の間の SHIFT が RUN の値でない（窓 0 %0d クロック・全帯域 %0d クロック）", n_shbad_w, n_shbad_s); ng = ng + 1; end
        else $display("tb_tsys: RUN の間の SHIFT は RUN の値（7）のまま（書き換えは 3）");
        maxdev = 0;
        for (kw = 1; kw < NDW; kw = kw + 1) begin
            dev = (dtw[kw] - dtw[0]) - kw * NAW * 4096; if (dev < 0) dev = -dev; if (dev > maxdev) maxdev = dev;
        end
        $display("tb_tsys: 窓 0 のダンプの間隔の k·N·4096 からのずれ 最大 %0d クロック", maxdev);
        if (maxdev > 16) begin $display("tb_tsys: NG 窓 0 の間隔のずれが大きい"); ng = ng + 1; end
        // 健全性
        ovr_s = 0; ovr_w = 0;
        for (ks = 0; ks < NDS; ks = ks + 1) begin
            if (dhs[ks][0] !== 1'b1 || dhs[ks][3] !== 1'b0 || dhs[ks][5] !== 1'b0 || dhs[ks][15:14] !== 2'b00) begin
                $display("tb_tsys: NG 全帯域 ダンプ %0d の健全性 %016b", ks, dhs[ks]); ng = ng + 1; end
            if (dhs[ks][4]) begin
                ovr_s = ovr_s + 1;
                if (!(t_ovr >= dts[ks] && (ks == NDS - 1 || t_ovr < dts[ks + 1] + 8))) begin
                    $display("tb_tsys: NG 全帯域 振り切れがダンプ %0d に立った（入れたのは T %0d）", ks, t_ovr); ng = ng + 1; end
            end
        end
        for (kw = 0; kw < NDW; kw = kw + 1) begin
            if (dhw[kw][0] !== 1'b1 || dhw[kw][3] !== 1'b0 || dhw[kw][6] !== 1'b0 || dhw[kw][15:14] !== 2'b00) begin
                $display("tb_tsys: NG 窓 0 ダンプ %0d の健全性 %016b", kw, dhw[kw]); ng = ng + 1; end
            if (dhw[kw][4]) ovr_w = ovr_w + 1;
        end
        if (ovr_s !== 1) begin $display("tb_tsys: NG 全帯域 振り切れの立ったダンプ %0d 個（期待 1）", ovr_s); ng = ng + 1; end
        if (ovr_w < 1 || ovr_w > 2) begin $display("tb_tsys: NG 窓 0 振り切れの立ったダンプ %0d 個（期待 1〜2）", ovr_w); ng = ng + 1; end
        axr(0, 20'h80048); if (rv !== 1) begin $display("tb_tsys: NG OVR_CNT %0d", rv); ng = ng + 1; end
        axr(0, 20'h8004C); if (rv !== 0) begin $display("tb_tsys: NG GAP_CNT %0d", rv); ng = ng + 1; end
        // 窓 1: [6]（WRST の後に CFG を変えた）
        repeat (30000) @(posedge clk);
        axr(0, 20'h200A8); if (rv[6] !== 1'b1) begin $display("tb_tsys: NG 窓 1 の健全性 [6] が立たない %016b", rv[15:0]); ng = ng + 1; end
        axr(0, 20'h200AC); if (rv !== 32'h5555) begin $display("tb_tsys: NG 窓 1 DUMP_CFG %08x", rv); ng = ng + 1; end
        // ---- 6. 予約の WRST（窓 1 だけ）----
        n_r0 = 0; n_r1 = 0; n_rs = 0; n_wr0 = 0; n_wr1 = 0;
        axr(0, 20'h2007C); dk = rv;
        sa2 = T + 3000;
        axw(2, 20'h10, sa2[31:0]); axw(2, 20'h14, sa2[63:32]);
        axw(0, 20'h20008, 32'h2000);
        axw(2, 20'h08, 32'h1);
        while (T < sa2 + 4) @(posedge clk);
        if (n_wr1 !== 1 || t_wr1 !== sa2 + 1) begin $display("tb_tsys: NG 予約の WRST（回数 %0d・T %0d / 期待 %0d）", n_wr1, t_wr1, sa2 + 1); ng = ng + 1; end
        if (n_r0 !== 0 || n_r1 !== 0 || n_rs !== 0 || n_wr0 !== 0) begin $display("tb_tsys: NG ARM していないコアが受けた（%0d %0d %0d %0d）", n_r0, n_r1, n_rs, n_wr0); ng = ng + 1; end
        repeat (200) @(posedge clk);
        axr(0, 20'h2007C); if (rv !== dk + 1) begin $display("tb_tsys: NG WRST_CNT %0d → %0d", dk, rv); ng = ng + 1; end
        // ---- 7. 窓 1 に ARM_RUN と ARM_WRST を両方: WRST は T = START_AT3 + 1、RUN は WRST が明けてから（RUN が WRST に消されない）----
        n_r1 = 0; n_wr1 = 0;
        axr(0, 20'h2001C); seqw = rv;
        axw(0, 20'h20010, 1);
        sa = T + 3000;
        axw(2, 20'h10, sa[31:0]); axw(2, 20'h14, sa[63:32]);
        axw(0, 20'h20008, 32'h2004);
        axw(2, 20'h08, 32'h1);
        while (T < sa + 200) @(posedge clk);
        if (n_wr1 !== 1 || t_wr1 !== sa + 1) begin $display("tb_tsys: NG 7. WRST（回数 %0d・T %0d / 期待 %0d）", n_wr1, t_wr1, sa + 1); ng = ng + 1; end
        if (n_r1 !== 1 || !(t_r1 > sa + 1 + 64)) begin $display("tb_tsys: NG 7. RUN（回数 %0d・T %0d。WRST の明け %0d より後のはず）", n_r1, t_r1, sa + 1 + 64); ng = ng + 1; end
        else $display("tb_tsys: 7. WRST は T %0d、RUN は WRST が明けた後の T %0d", t_wr1, t_r1);
        axr64(0, 20'h200B0); if (r64 !== t_r1) begin $display("tb_tsys: NG 7. 窓 1 の RUN_T %0d（RUN を受けた T %0d）", r64, t_r1); ng = ng + 1; end
        kw = 0;
        while (kw < 60) begin
            repeat (1000) @(posedge clk);
            axr(0, 20'h2001C);
            if (rv != seqw) kw = 100; else kw = kw + 1;
        end
        if (kw != 100) begin $display("tb_tsys: NG 7. 窓 1 のダンプが閉じない（RUN が消えた）"); ng = ng + 1; end
        else begin
            axr(0, 20'h20030); dk = rv; axr64(0, 20'h200A0);
            if (dk !== 0 || !(r64 > t_r1)) begin $display("tb_tsys: NG 7. 窓 1 の DUMP_K %0d・DUMP_T %0d", dk, r64); ng = ng + 1; end
            else $display("tb_tsys: 7. 窓 1 のダンプ 0 が閉じた（DUMP_T %0d）", r64);
        end
        if (ng == 0) $display("tb_tsys: 結果: 全部通過");
        else         $display("tb_tsys: 結果: 失敗（%0d 件）", ng);
        $finish;
    end
endmodule
