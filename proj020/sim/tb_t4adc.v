// SPDX-License-Identifier: BSD-3-Clause
// proj017 S-2 — time_core 1 個 ＋ win_core（NW = 2・TP）× 4 を BD と同じくつないだ sim（4 ADC の同時開始）
//   t_out・go_out・ev_out を 4 個の win_core の t_in・go_in・tev_in へ直につなぐ（build.tcl の shared_nets と同じ）。
//   ADC ごとに入力の始まりを 37·i クロックずらす（ADC のフレームの格子の位相が ADC ごとに違う、実機と同じ状況）
// 判定（「tb_t4adc: NG」を数える）:
//   1. ARM した 8 窓と TP 4 本が、どれも T = START_AT + 1 のクロックに RUN を受ける（tb がコアの中を覗いて記録）
//   2. 8 窓の RUN_T・4 本の TP_RUN_T のレジスタ = START_AT + 1、time_core の FIRED = START_AT
//   3. ARM していない窓（2 回目の予約で ADC 1 の窓 1 だけを ARM）は RUN を受けない
// 陽性対照（-DT4_POSCTL）: ADC 3 の t_in・go_in だけ 1 段遅らせる → 1 が落ちるはず（make sim-t4adc-p）。
//   **2（RUN_T のレジスタ）は落ちない**: コアの中の時刻も同じ 1 段遅れるので、遅れた RUN を遅れた時計で読み、START_AT + 1 と出る。
//   時刻のバスの段の食い違いはコアの自己申告では見えない（build.tcl の結線の照合と、この sim の外からの観測だけが見る）
`timescale 1ns / 1ps
module tb_t4adc;
    reg clk = 0, cclk = 0;
    always #1.953 clk = ~clk;
    always #5.000 cclk = ~cclk;
    reg aresetn = 0, crstn = 0;
    // AXI: 0..3 = win_core_i（20 bit）/ 4 = time_core（8 bit）
    reg  [19:0] awaddr = 0, araddr = 0;
    reg  [4:0]  awv = 0, wv = 0, arv = 0;
    reg  [31:0] wdata = 0;
    wire [4:0]  awr, wr_, bv, arr, rv_;
    wire [31:0] rdw [0:4];
    wire [63:0] t_out; wire go_out; wire [3:0] ev_out;
    time_core u_t (.aclk(clk), .aresetn(aresetn), .ctrl_aclk(cclk), .ctrl_aresetn(crstn), .pps_trig_i(1'b0), .pps_comp_i(1'b0),
        .s_axi_awaddr(awaddr[7:0]), .s_axi_awprot(3'd0), .s_axi_awvalid(awv[4]), .s_axi_awready(awr[4]),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wv[4]), .s_axi_wready(wr_[4]), .s_axi_bresp(), .s_axi_bvalid(bv[4]), .s_axi_bready(1'b1),
        .s_axi_araddr(araddr[7:0]), .s_axi_arprot(3'd0), .s_axi_arvalid(arv[4]), .s_axi_arready(arr[4]),
        .s_axi_rdata(rdw[4]), .s_axi_rresp(), .s_axi_rvalid(rv_[4]), .s_axi_rready(1'b1),
        .t_out(t_out), .go_out(go_out), .ev_out(ev_out));
    wire [63:0] T = u_t.T;

    // 陽性対照: ADC 3 だけ時刻のバスを 1 段遅らせる
    reg [63:0] t_d; reg go_d; reg [3:0] ev_d;
    always @(posedge clk) begin t_d <= t_out; go_d <= go_out; ev_d <= ev_out; end

    integer seed = 11;
    genvar g;
    generate for (g = 0; g < 4; g = g + 1) begin : g_adc
        reg [255:0] tdata = 0;
        reg         tvalid = 0;
        integer     l, cnt = 0;
        always @(posedge clk) begin
            if (!aresetn) begin tvalid <= 0; cnt <= 0; end
            else begin
                cnt <= cnt + 1;
                for (l = 0; l < 16; l = l + 1) tdata[16*l +: 16] <= ($random(seed) % 2000);
                tvalid <= (cnt >= 37 * g);
            end
        end
`ifdef T4_POSCTL
        wire [63:0] ti = (g == 3) ? t_d : t_out;
        wire        gi = (g == 3) ? go_d : go_out;
        wire [3:0]  ei = (g == 3) ? ev_d : ev_out;
`else
        wire [63:0] ti = t_out;
        wire        gi = go_out;
        wire [3:0]  ei = ev_out;
`endif
        win_core #(.NW(2), .N_ACC_DEFAULT(2), .G_L2(12)) u_w (
            .aclk(clk), .aresetn(aresetn), .s_axis_tdata(tdata), .s_axis_tvalid(tvalid), .s_axis_tready(),
            .s_axi_awaddr(awaddr), .s_axi_awprot(3'd0), .s_axi_awvalid(awv[g]), .s_axi_awready(awr[g]),
            .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wv[g]), .s_axi_wready(wr_[g]), .s_axi_bresp(), .s_axi_bvalid(bv[g]), .s_axi_bready(1'b1),
            .s_axi_araddr(araddr), .s_axi_arprot(3'd0), .s_axi_arvalid(arv[g]), .s_axi_arready(arr[g]),
            .s_axi_rdata(rdw[g]), .s_axi_rresp(), .s_axi_rvalid(rv_[g]), .s_axi_rready(1'b1),
            .gb_hold(), .gb_adj(), .gb_dn_rstn(), .gb_k(), .gb_stat(32'd0), .adc_stat(32'd0), .full_sel(),
            .t_in(ti), .go_in(gi), .tev_in(ei));
        // RUN を受けたクロック（窓 0・窓 1・TP）
        reg [63:0] t_r0 = 0, t_r1 = 0, t_rtp = 0;
        integer n_r0 = 0, n_r1 = 0, n_rtp = 0;
        always @(posedge clk) begin
            if (u_w.g_w[0].cmd_run) begin t_r0  <= T; n_r0  = n_r0 + 1; end
            if (u_w.g_w[1].cmd_run) begin t_r1  <= T; n_r1  = n_r1 + 1; end
            if (u_w.tp_run)         begin t_rtp <= T; n_rtp = n_rtp + 1; end
        end
    end endgenerate

    integer ng = 0, i;
    task axw(input integer s, input [19:0] a, input [31:0] d); begin
        @(posedge clk); awaddr <= a; wdata <= d; awv[s] <= 1; wv[s] <= 1;
        @(posedge clk); while (!awr[s]) @(posedge clk);
        awv[s] <= 0; wv[s] <= 0;
        while (!bv[s]) @(posedge clk);
    end endtask
    reg [31:0] rv;
    task axr(input integer s, input [19:0] a); begin
        @(posedge clk); araddr <= a; arv[s] <= 1;
        @(posedge clk); while (!arr[s]) @(posedge clk);
        arv[s] <= 0;
        while (!rv_[s]) @(posedge clk);
        rv = rdw[s];
    end endtask
    reg [63:0] r64;
    task axr64(input integer s, input [19:0] a); reg [31:0] lo; begin axr(s, a); lo = rv; axr(s, a + 4); r64 = {rv, lo}; end endtask

    reg [63:0] sa, sa2, tr [0:11];
    integer nr [0:11];
    initial begin
        #40 crstn = 1;
        repeat (8) @(posedge clk);
        aresetn <= 1;
        repeat (16) @(posedge clk);
        for (i = 0; i < 4; i = i + 1) begin
            axr(i, 20'h00000); if (rv !== 32'h0017_0100) begin $display("tb_t4adc: NG win_core_%0d の ID %08x", i, rv); ng = ng + 1; end
            axr(i, 20'h80004); if (rv !== 2) begin $display("tb_t4adc: NG win_core_%0d の NW %0d", i, rv); ng = ng + 1; end
        end
        axr(4, 20'h00); if (rv !== 32'h0017_7101) begin $display("tb_t4adc: NG time_core の ID %08x", rv); ng = ng + 1; end
        // ---- 1・2. 8 窓と TP 4 本を ARM して予約 ----
        sa = T + 3000;
        axw(4, 20'h10, sa[31:0]); axw(4, 20'h14, sa[63:32]);
        for (i = 0; i < 4; i = i + 1) begin
            axw(i, 20'h00008, 32'h4); axw(i, 20'h20008, 32'h4); axw(i, 20'h80010, 32'h4);
        end
        axw(4, 20'h08, 32'h1);
        while (T < sa + 4) @(posedge clk);
        for (i = 0; i < 4; i = i + 1) begin
            case (i)
                0: begin tr[0] = g_adc[0].t_r0; tr[1] = g_adc[0].t_r1; tr[2] = g_adc[0].t_rtp; nr[0] = g_adc[0].n_r0; nr[1] = g_adc[0].n_r1; nr[2] = g_adc[0].n_rtp; end
                1: begin tr[3] = g_adc[1].t_r0; tr[4] = g_adc[1].t_r1; tr[5] = g_adc[1].t_rtp; nr[3] = g_adc[1].n_r0; nr[4] = g_adc[1].n_r1; nr[5] = g_adc[1].n_rtp; end
                2: begin tr[6] = g_adc[2].t_r0; tr[7] = g_adc[2].t_r1; tr[8] = g_adc[2].t_rtp; nr[6] = g_adc[2].n_r0; nr[7] = g_adc[2].n_r1; nr[8] = g_adc[2].n_rtp; end
                3: begin tr[9] = g_adc[3].t_r0; tr[10] = g_adc[3].t_r1; tr[11] = g_adc[3].t_rtp; nr[9] = g_adc[3].n_r0; nr[10] = g_adc[3].n_r1; nr[11] = g_adc[3].n_rtp; end
            endcase
        end
        for (i = 0; i < 12; i = i + 1) begin
            if (nr[i] !== 1 || tr[i] !== sa + 1) begin
                $display("tb_t4adc: NG ADC %0d のコア %0d（0 = 窓 0・1 = 窓 1・2 = TP）: RUN %0d 回・T %0d（START_AT + 1 = %0d）",
                         i / 3, i % 3, nr[i], tr[i], sa + 1); ng = ng + 1; end
        end
        $display("tb_t4adc: 1. 8 窓・TP 4 本の RUN のクロック（START_AT + 1 = %0d との差）: %0d %0d %0d / %0d %0d %0d / %0d %0d %0d / %0d %0d %0d",
                 sa + 1, tr[0] - sa - 1, tr[1] - sa - 1, tr[2] - sa - 1, tr[3] - sa - 1, tr[4] - sa - 1, tr[5] - sa - 1,
                 tr[6] - sa - 1, tr[7] - sa - 1, tr[8] - sa - 1, tr[9] - sa - 1, tr[10] - sa - 1, tr[11] - sa - 1);
        for (i = 0; i < 4; i = i + 1) begin
            axr64(i, 20'h000B0); if (r64 !== sa + 1) begin $display("tb_t4adc: NG ADC %0d 窓 0 の RUN_T %0d", i, r64); ng = ng + 1; end
            axr64(i, 20'h200B0); if (r64 !== sa + 1) begin $display("tb_t4adc: NG ADC %0d 窓 1 の RUN_T %0d", i, r64); ng = ng + 1; end
            axr64(i, 20'h80040); if (r64 !== sa + 1) begin $display("tb_t4adc: NG ADC %0d の TP_RUN_T %0d", i, r64); ng = ng + 1; end
            axr(i, 20'h8010C); $display("tb_t4adc: 2. ADC %0d の TP の F0 = フレーム %0d（ADC ごとの格子。入力の始まりを 37·%0d クロックずらした）", i, rv, i);
        end
        axr64(4, 20'h50); if (r64 !== sa) begin $display("tb_t4adc: NG FIRED %0d", r64); ng = ng + 1; end
        // ---- 3. 2 回目の予約: ADC 1 の窓 1 だけ ----
        sa2 = T + 3000;
        axw(4, 20'h10, sa2[31:0]); axw(4, 20'h14, sa2[63:32]);
        axw(1, 20'h20008, 32'h2);                       // STOP（いったん止める）
        axw(1, 20'h20008, 32'h4);
        axw(4, 20'h08, 32'h1);
        while (T < sa2 + 4) @(posedge clk);
        if (g_adc[1].n_r1 !== 2 || g_adc[1].t_r1 !== sa2 + 1) begin
            $display("tb_t4adc: NG 3. ADC 1 窓 1 の 2 回目の RUN %0d 回・T %0d（期待 %0d）", g_adc[1].n_r1, g_adc[1].t_r1, sa2 + 1); ng = ng + 1; end
        if (g_adc[0].n_r0 !== 1 || g_adc[0].n_r1 !== 1 || g_adc[0].n_rtp !== 1 ||
            g_adc[1].n_r0 !== 1 ||                         g_adc[1].n_rtp !== 1 ||
            g_adc[2].n_r0 !== 1 || g_adc[2].n_r1 !== 1 || g_adc[2].n_rtp !== 1 ||
            g_adc[3].n_r0 !== 1 || g_adc[3].n_r1 !== 1 || g_adc[3].n_rtp !== 1) begin
            $display("tb_t4adc: NG 3. ARM していないコアが 2 回目の発火で RUN を受けた"); ng = ng + 1; end
        else $display("tb_t4adc: 3. 2 回目の発火は ADC 1 の窓 1 だけが受けた（T %0d）", g_adc[1].t_r1);
`ifdef T4_POSCTL
        $display("tb_t4adc: 陽性対照（ADC 3 の時刻のバスを 1 段遅らせた）: NG %0d 件", ng);
        if (ng > 0) $display("tb_t4adc: 結果: 全部通過（陽性対照が落ちるべきところで落ちた）");
        else        $display("tb_t4adc: 結果: 陽性対照が落ちなかった（見張りが効いていない）");
`else
        if (ng == 0) $display("tb_t4adc: 結果: 全部通過");
        else         $display("tb_t4adc: 結果: 失敗（%0d 件）", ng);
`endif
        $finish;
    end
    initial begin #20000000; $display("tb_t4adc: NG 時間切れ"); $display("tb_t4adc: 結果: 失敗"); $finish; end
endmodule
