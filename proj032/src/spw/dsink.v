// SPDX-License-Identifier: BSD-3-Clause
//
// dsink — 閉じたダンプの流れの受け手 1 ADC ぶん（proj032 K-2）: 機関 E 組の d_* → f32 → 機関ごとの溜め（URAM）→ レコード（AXIS 128 bit）
//
// 機関 e は、ダンプ 1 つ（4096 ch、FFT の ch の順 k = 0..4095）を 1 ch / クロックで流す（eng の d_*、u64）。
//   - f32cv で f32 に（K-1 の決め: PL → PS は f32。PS の u64 → double → float と bit 単位で同じ）
//   - f32 を PK = 2·NU 個ずつ束ねて 1 語（64·NU bit）にし、機関ごとの溜め（4096 語 = URAM NU 個 = ダンプ PK 個ぶん）に順に書く
//   - ダンプの頭（k = 0）で、溜めに 1 ダンプぶん（DE = 4096 / PK 語）の空きが無ければ、そのダンプを丸ごと捨てて drop[e] を 1 クロック
//     （書き始めたダンプは必ず最後まで書ける。レコードは欠けない）
// レコード（INTERFACE 4.4 の形、頭 8 語 ＋ 本体 16 KiB。尾は ring128 が付ける）: 頭が溜めに入ったダンプを、機関の順番で 1 つずつ。
//   **書き始めたダンプが揃うのを待たない**（K-2 の模型: 待つより溜めが小さい）。本体の語がまだ書かれていなければ、出口は待つ
//   NU 2: 1 語 = 1 拍。NU 1: 2 語 = 1 拍（出口は最大 0.5 拍 / クロック = 2 GB/s）
// 頭の語（u64、リトルエンディアン）:
//   w0 magic "S45R" / rec_ver 2 / type 5（SpW の窓）/ core = ADC / s = 窓 w      w1 SEQ（この受け手のレコードの番号）/ DUMP_K
//   w2 DUMP_F0 = (g0a ＋ k·ng)·2^(G_L2 − 12 − NS)（窓のフレーム、T の原点から。P-4）・w3 DUMP_T = t0[w] ＋ (g0 ＋ k·ng)·2^G_L2（R-1: ダンプの最初のフレームの z 0 のビート。ng は下 16 bit）
//   w4 log2 NFFT 12 / NS / SHIFT / G / fmt 1（f32）/ src = ADC / DUMP_H 0        w5 DUMP_N = ng·2^(G_L2 − 12 − NS) / DUMP_SAT 0
//   w6 DUMP_CFG 0 / FLAGS 0                                                       w7 本体のバイト数 16384 / 0
// 水抜き（P-2）: drain の間は新しいレコードを始めない。idle = 開いたレコードが無く出口の FIFO も空（WRST はこれを待つ。spw_regs）
// flags（粘着）: [0] 札の FIFO の溢れ [1] 出口の FIFO の溢れ [2] ダンプを捨てた [3] ダンプの途中で ch が飛んだ

`timescale 1ns / 1ps

module dsink #(
    parameter integer E    = 3,
    parameter integer H    = 14,
    parameter integer NU   = 2,         // 機関ごとの URAM（1 か 2）
    parameter integer G_L2 = 19,
    parameter integer ADC  = 0
)(
    input  wire                 clk,
    input  wire                 rst,
    input  wire [E-1:0]         d_v,
    input  wire [E*4-1:0]       d_w,
    input  wire [E*32-1:0]      d_k,
    input  wire [E*12-1:0]      d_ch,
    input  wire [E*64-1:0]      d_data,
    input  wire [H*3-1:0]       cfg_ns,
    input  wire [H*4-1:0]       cfg_sh,
    input  wire [H*4-1:0]       cfg_g,
    input  wire [31:0]          ng,
    input  wire [31:0]          g0,             // rst から数えた格子（DUMP_T 用）
    input  wire [31:0]          g0a,            // T の原点から数えた格子（DUMP_F0 用）
    input  wire [H*64-1:0]      t0,
    output wire [127:0]         m_tdata,
    output wire                 m_tvalid,
    input  wire                 m_tready,
    output wire                 m_tlast,
    output reg  [E-1:0]         drop,
    output reg  [3:0]           flags,
    input  wire                 drain,
    output wire                 idle
);
    localparam integer PW = 64 * NU;    // 語の幅
    localparam integer PK = 2 * NU;     // 語の中の f32
    localparam integer PL = (PK == 4) ? 2 : 1;
    localparam integer DE = 4096 / PK;  // ダンプ 1 つの語
    genvar g;
    integer i;

    // ---- 機関ごとの書きの側 ----
    reg  [12:0]      rp [0:E-1];        // 読みを出した語（読みの側が進める）
    wire [12:0]      wpv [0:E-1];
    wire [E-1:0]     t_empty, t_ovf, gap;
    wire [35:0]      t_head [0:E-1];
    reg  [E-1:0]     t_pop;
    reg  [E-1:0]     re;                // 読みを出す
    reg  [11:0]      ra;
    wire [PW-1:0]    mq2 [0:E-1];
    generate for (g = 0; g < E; g = g + 1) begin : en
        wire        cv;
        wire [31:0] cf;
        f32cv u_cv (.clk(clk), .in_v(d_v[g]), .in_u(d_data[g*64 +: 64]), .out_v(cv), .out_f(cf));
        reg  [11:0] c1, c2, c3;
        reg  [3:0]  w1, w2, w3;
        reg  [31:0] k1, k2, k3;
        always @(posedge clk) begin
            c1 <= d_ch[g*12 +: 12]; c2 <= c1; c3 <= c2;
            w1 <= d_w[g*4 +: 4];    w2 <= w1; w3 <= w2;
            k1 <= d_k[g*32 +: 32];  k2 <= k1; k3 <= k2;
        end
        reg  [12:0]   wp;
        wire [12:0]   used = wp - rp[g];
        wire          room = (13'd4096 - used) >= DE;
        reg           keep;
        reg  [11:0]   cexp;             // 次に来るはずの ch
        reg  [PW-33:0] acc;
        reg           we;
        reg  [11:0]   wa;
        reg  [PW-1:0] wd;
        reg           tpush, gp;
        reg  [35:0]   tdin;
        always @(posedge clk) begin
            tpush <= 1'b0; we <= 1'b0; gp <= 1'b0;
            if (rst) begin
                wp <= 13'd0; keep <= 1'b0; cexp <= 12'd0;
            end else if (cv) begin
                cexp <= c3 + 12'd1;
                if (c3 != 12'd0 && c3 != cexp) gp <= 1'b1;
                if (c3 == 12'd0) begin
                    keep  <= room;
                    tpush <= room;
                    tdin  <= {w3, k3};
                end
                if (c3[PL-1:0] != PK - 1) acc[c3[PL-1:0]*32 +: 32] <= cf;
                else if (c3 == 12'd0 ? room : keep) begin
                    we <= 1'b1; wa <= wp[11:0]; wd <= {cf, acc};
                    wp <= wp + 13'd1;
                end
            end
        end
        always @(posedge clk) drop[g] <= !rst && cv && c3 == 12'd0 && !room;
        // 読みの側に見せる書いた語の数は 2 クロック遅らせる（wp が進んだ次のクロックに mem に書かれる。同じ番地の読みが追い越さない）
        reg  [12:0]   wpd1, wpd2;
        always @(posedge clk) begin wpd1 <= rst ? 13'd0 : wp; wpd2 <= rst ? 13'd0 : wpd1; end
        assign wpv[g] = wpd2;
        assign gap[g] = gp;
        sfifo #(.DW(36), .AW(3)) u_tag (.clk(clk), .rst(rst), .push(tpush), .din(tdin), .pop(t_pop[g]),
                                        .dout(t_head[g]), .empty(t_empty[g]), .ovf(t_ovf[g]));
        // 溜め（URAM。読みは 2 段: 番地 → mq → mq2）
        (* ram_style = "ultra" *) reg [PW-1:0] mem [0:4095];
        reg  [PW-1:0] mq, mqr;
        always @(posedge clk) begin
            if (we) mem[wa] <= wd;
            if (re[g]) mq <= mem[ra];
            mqr <= mq;
        end
        assign mq2[g] = mqr;
    end endgenerate

    // ---- 読みの側: レコードを 1 つずつ ----
    localparam [1:0] R_IDLE = 2'd0, R_PRE = 2'd3, R_HDR = 2'd1, R_BODY = 2'd2;
    reg  [1:0]   rs;
    reg  [2:0]   pre;                   // R_PRE: 頭の値（下の 4 段）が cur に揃うのを待つ
    reg  [1:0]   cur, rr;
    reg  [1:0]   hb;
    reg  [11:0]  left;                  // 本体の残りの語（読みを出す数）
    reg  [31:0]  seq;
    reg  [4:0]   oc;                    // 出口の拍で、出すと決めて出口から出ていないもの
    reg  [3:0]   cw;
    reg  [31:0]  ck;
    reg  [63:0]  w0, w1h, w2, w3, w4, w5;
    wire         o_room = oc < 5'd10;
    wire [12:0]  avail = wpv[cur] - rp[cur];
    // 出口の FIFO（{last, 拍}）
    reg          op;
    reg  [128:0] od;
    wire         o_empty, o_ovf;
    wire [128:0] o_dout;
    wire         o_pop = m_tready && !o_empty;
    sfifo #(.DW(129), .AW(4)) u_out (.clk(clk), .rst(rst), .push(op), .din(od), .pop(o_pop), .dout(o_dout), .empty(o_empty), .ovf(o_ovf));
    assign m_tvalid = !o_empty;
    assign m_tdata  = o_dout[127:0];
    assign m_tlast  = o_dout[128];
    assign idle     = (rs == R_IDLE) && o_empty;
    // 読みの段の印: P0 出す → P1 mq → P2 mqr を選んで出口へ
    reg  [1:0]   s1, s2;
    reg          v1, v2, l1, l2, h1, h2;    // 有効・最後・（NU 1）2 語目
    reg  [63:0]  lo;                         // NU 1: 1 語目
    reg  [2:0]   ns_c;
    reg  [3:0]   sh_c, g_c;
    wire         rd_go = (rs == R_BODY) && avail != 13'd0 && o_room && left != 12'd0;
    always @(*) begin
        re = {E{1'b0}};
        if (rd_go) re[cur] = 1'b1;
        ra = rp[cur][11:0];
        t_pop = {E{1'b0}};
        if (rs == R_BODY && left == 12'd0 && !v1 && !v2) t_pop[cur] = 1'b1;
    end
    always @(posedge clk) begin
        op <= 1'b0;
        v1 <= rd_go; s1 <= cur; l1 <= (left == 12'd1); h1 <= (NU == 1) ? left[0] == 1'b1 : 1'b1;
        v2 <= v1;    s2 <= s1;  l2 <= l1;              h2 <= h1;
        if (rst) begin
            rs <= R_IDLE; cur <= 2'd0; rr <= 2'd0; hb <= 2'd0; left <= 12'd0; seq <= 32'd0; oc <= 5'd0;
            for (i = 0; i < E; i = i + 1) rp[i] <= 13'd0;
            v1 <= 1'b0; v2 <= 1'b0;
        end else begin
            oc <= oc + ((rs == R_HDR && o_room) ? 5'd1 : 5'd0) + ((rd_go && ((NU == 2) || left[0] == 1'b1)) ? 5'd1 : 5'd0) - (o_pop ? 5'd1 : 5'd0);
            if (rd_go) begin rp[cur] <= rp[cur] + 13'd1; left <= left - 12'd1; end
            // P2: 本体の拍
            if (v2) begin
                if (NU == 2) begin op <= 1'b1; od <= {l2, mq2[s2][127:0]}; end
                else if (!h2) lo <= mq2[s2][63:0];
                else begin op <= 1'b1; od <= {l2, mq2[s2][63:0], lo}; end
            end
            case (rs)
                R_IDLE: begin
                    // 頭が溜めに入ったダンプを持つ機関を、rr から順に
                    for (i = E - 1; i >= 0; i = i - 1)
                        if (!t_empty[(rr + i) % E]) cur <= (rr + i) % E;
                    if (|(~t_empty) && !drain) begin
                        rs <= R_PRE; pre <= 3'd0; hb <= 2'd0;
                    end
                end
                R_PRE: begin
                    pre <= pre + 3'd1;
                    if (pre == 3'd4) rs <= R_HDR;
                end
                R_HDR: begin
                    if (o_room) begin
                        op <= 1'b1;
                        case (hb)
                            2'd0: od <= {1'b0, ck, seq, w0};
                            2'd1: od <= {1'b0, w3, w2};
                            2'd2: od <= {1'b0, w5, w4};
                            default: od <= {1'b0, {32'd0, 32'd16384}, 64'd0};
                        endcase
                        hb <= hb + 2'd1;
                        if (hb == 2'd3) begin rs <= R_BODY; left <= DE[11:0]; seq <= seq + 32'd1; end
                    end
                end
                R_BODY: if (t_pop[cur]) begin rs <= R_IDLE; rr <= (cur + 2'd1) % E; end
                default: rs <= R_IDLE;
            endcase
        end
    end
    // 頭の値（cur と札の頭から毎クロック 4 段で作る。R_PRE で 5 クロック待ってから R_HDR で出す）
    wire [35:0]  th = t_head[cur];
    always @(posedge clk) begin
        cw   <= th[35:32];
        ck   <= th[31:0];
        ns_c <= cfg_ns[th[35:32]*3 +: 3];
        sh_c <= cfg_sh[th[35:32]*4 +: 4];
        g_c  <= cfg_g[th[35:32]*4 +: 4];
        w0   <= {4'd0, cw, ADC[7:0], 8'd5, 8'd2, 32'h5235_3453};
        w4   <= {16'd0, ADC[7:0], 8'd1, 4'd0, g_c, 4'd0, sh_c, 5'd0, ns_c, 8'd12};
        w5   <= {32'd0, ng << (G_L2 - 12 - ns_c)};
    end
    // 時刻: k·ng（DSP）→ g0 ＋ → 格子からフレーム・ビートへ
    reg  [47:0]  kn;
    reg  [63:0]  t0c, t0d;
    reg  [47:0]  gk, gka;
    reg  [2:0]   ns_d, ns_e;
    always @(posedge clk) begin
        kn   <= ck * ng[15:0];
        t0c  <= t0[cw*64 +: 64];
        ns_d <= ns_c;
        gk   <= {16'd0, g0} + kn;
        gka  <= {16'd0, g0a} + kn;
        t0d  <= t0c;
        ns_e <= ns_d;
        w2   <= {16'd0, gka} << (G_L2 - 12 - ns_e);
        w3   <= t0d + ({16'd0, gk} << G_L2);
    end

    always @(posedge clk) begin
        if (rst) flags <= 4'd0;
        else flags <= flags | {|gap, |drop, o_ovf, |t_ovf};
    end
endmodule
