// SPDX-License-Identifier: BSD-3-Clause
//
// eng — 窓の機関 1 組（proj032 E-4）: final の lane 1 本の出口 → 窓ごとの履歴（5 面）→ PFB（T = 4）→ 複素 4096 点 FFT → 電力 → 積分
//
// 窓 w の値は、窓ごとに Fine の wspec_core を 1 組ずつ置いた形（溜め 5 面 → PFB → FFT → 電力 → 積分）と同じ。違いは:
//   - **枠（4096 クロック）ごとに 1 窓**。枠は全機関で共通の番地 a（上位の wsb が数える）で回り、FFT には空の枠（0）も流して途切れなく回す
//     （realtime の IP は途切れを halt と数える: proj028 F-4）。係数の ROM と履歴の読みの番地は全機関で共有（a）
//   - 枠の頭で、溜まった窓（pend）から **NS の小さい（周期の短い）窓を先に**、同じ NS は番号の小さい窓を選ぶ。周期が 2 のべきの固定優先なので、
//     機関の幅の和 ≦ 256 MHz なら、フレーム r の読み始めは「r が溜まった時刻 + 窓の周期」より前（E-4 の模型 sched: 最悪 3 クロック前）
//   - **履歴の書き込みを D クロック遅らせる**: 上の余裕は 0 に近づきうる（溜まった時刻が枠の頭の直後なら）。読みの番地 0 が、
//     フレーム r + 2（r − 3 の面に入る）の番地 0 の書き込みより先になるよう、書き込みだけを遅らせる。溜まった印は遅らせないが、
//     読みが番地 4095 に来るのは選ばれてから 4095 クロック以上後なので、D < 4000 なら読みが書き込みを追い越さない
//   - **D-2: DDR の窓**（cfg_sl[w] ≧ S。DDR の枠 k = cfg_sl[w] − S）: z を窓ごとの利得で 8 bit に（h = sat8(round(z / 2^g))、M-2）、
//     4 標本を 64 bit の語にまとめて dw_* に出す（上位の ddrw が 2 KiB ずつ DDR に書く）。フレームが DDR に書き終わった知らせ（fl_*）で溜まった印を立てる。
//     DDR の窓を選んだら rq_* で読み手（ddrr）に先読みを頼み、枠の中では dd（4 タップ × 8 bit の I/Q、P2）を h·2^g に戻して使う。
//     **選びを枠の頭の LEAD クロック前に早める**（DDR の最初の区画 8 KiB を先に読むため）。チップ内の窓の始まりの遅れは最悪 LEAD 増えるので、D > LEAD
//     （E-4 の模型を前倒しつきに: LEAD 960 で始まりの最悪は「着き ＋ 周期」の前のまま、理屈の上限は ＋ LEAD）
//   - 積分器は窓ごとに 1 面（URAM 1、上位の wsb）。**ダンプの区切りの最初のフレームで、前のダンプの値を読み出して流し（d_*）、同じ番地に p を書く**
//     （proj028 F-3 の形）。最後のダンプは、その次のフレームで読み出すだけ（FLUSH）
//
// 窓の状態（窓の番号で引く LUTRAM）:
//   書きの側 ws[w] = {fin 32, nf 2, wb 3, wa 12}: 溜めたフレームの数・前に溜まったフレームの数（3 で止める）・書いている面・番地
//   仕事 jt[w] = {fin, wb}: 最後に溜まったフレーム r = fin とその面。有効なタップ（r − 3 + t ≧ 0）は r から
//   溜まった仕事は窓ごとに 2 つまで（pend・pend2）。選ばれるのと同じクロックに同じ窓の次のフレームが溜まることがある
//   （始まりの余裕は 0 に近づきうる: 上）。2 つあれば古いほう（r − 1、面 wb − 1）を先に出す。E-4 の最初の版は 1 つで、tb の CFG 2 で 1 フレーム落とした
//   積分 it[w] = {k 32, j 32}: ダンプの番号・ダンプの中のフレーム。on・st（RUN の中・最初のフレームを過ぎた）はレジスタ
// 時刻の格子（Fine の proj017 と同じ考え）: 上位が格子 G = 2^G_L2 クロックを rst から数え、RUN で g0 = 格子の番号 + 2。
//   窓 w のフレーム長は L = 2^(12 + NS) クロックなので、格子 1 つは M = 2^e フレーム（e = G_L2 − 12 − NS）。F0 = g0·M、ダンプの長さ N = ng·M
//
// 入口の値: y（W bit・小数 B_F = 4 + 持ち上げ）→ z = sat18(round(y / 2^bs))、bs = 0, 0, 1, 1, 2（NS 1..5。M-3）
// 電力: q = sat18(Y >>> sh)（sh は窓ごと）、p = q_re² + q_im²（37 bit）、64 bit で積む
//
// 段（書きの側）: I0 入口のレジスタ → I1 ws を引いて z・次の状態（書き戻し）・溜まった印 → 遅れ D → 上位の履歴へ
// 段（読みの側、a が P0）: P2 履歴（全枠の 5 面）と係数 → P3 枠を選ぶ → P4 タップ → P5 積 → P6 2 つずつ → P7 和 → P8 右へ・飽和 → FFT
// 段（出口）: S0 FFT の出口（k = 0 で札を取る）→ S1 → S2 q・積分器の読みを出す → S3 二乗 → S4 p → S5 → S6 積分器の値（上位から）→ S7 書き・流す
//
// flags（粘着、rst で消す）: [0] 溜まった印が残っているうちに次が溜まった / [1] 履歴の書き込みが未読の番地に来た / [2] FFT が tready を下げた /
//   [3] PFB の出口の飽和 / [4] RUN の最初のフレームを過ぎていた / [5] 札の FIFO の溢れ・空 / [6] 入口の z の飽和 / [7] FFT の事象（TLAST・halt） /
//   [8] DDR の窓の 8 bit の飽和
// ENG_POSCTL: 陽性対照。優先を窓の番号だけにする（NS を見ない）→ 幅の広い窓が締め切りに遅れて flags[1]・値の不一致

`timescale 1ns / 1ps

module eng #(
    parameter integer H    = 14,
    parameter integer S    = 6,         // 上位の履歴の枠の数
    parameter integer W    = 20,
    parameter integer G_L2 = 19,
    parameter integer D    = 1024,      // 履歴の書き込みの遅れ（> LEAD ＋ 選びの段。≧ 128 は BRAM の輪）
    parameter integer LEAD = 960        // 選びを枠の頭の何クロック前に始めるか（DDR の先読み）
)(
    input  wire                 clk,
    input  wire                 rst,
    input  wire                 in_v,
    input  wire [3:0]           in_w,
    input  wire [W-1:0]         in_re, in_im,
    input  wire [H*3-1:0]       cfg_ns,     // 窓ごとの NS（1..5）
    input  wire [H*4-1:0]       cfg_sl,     // 窓ごとの履歴の枠（4 bit。E-4 の tb で 3 bit の枠の番号が窓 13 → 5 に重なった）
    input  wire [H*4-1:0]       cfg_sh,     // 窓ごとの電力の前の右シフト
    input  wire [H*4-1:0]       cfg_g,      // DDR の窓の 8 bit の利得（右シフト 0..10）
    input  wire                 go,         // 枠が回っている（a が進む）
    input  wire [11:0]          a,          // 枠の中の番地（P0）
    input  wire [31:0]          g0, ng, ndump,
    input  wire                 cmd_run, cmd_stop,
    output wire                 rdy,        // FFT の tready
    // 履歴の書き（D クロック遅らせた）
    output wire                 hw_v,
    output wire [3:0]           hw_s,
    output wire [2:0]           hw_b,
    output wire [11:0]          hw_a,
    output wire [35:0]          hw_d,
    // DDR の窓: 書く語（4 標本）・書き終わりの知らせ・先読みの頼み・読んだタップ（P2）
    output reg                  dw_v,
    output reg  [3:0]           dw_k, dw_w,
    output reg  [2:0]           dw_f,       // フレームの番号の下 3 bit（DDR の 8 フレームの輪）
    output reg  [9:0]           dw_row,     // 語の番号（番地 a / 4）
    output reg  [63:0]          dw_d,
    input  wire                 fl_v,
    input  wire [3:0]           fl_w,
    output reg                  rq_v,
    output reg  [3:0]           rq_k,
    output reg  [31:0]          rq_r,
    input  wire [63:0]          dd,
    // 履歴の読み（全枠 × 5 面、P2）と係数（P2）
    input  wire [S*5*36-1:0]    hq,
    input  wire signed [17:0]   c0, c1, c2, c3,
    // 積分器: 読み（S2 に番地、S6 に値）・書き（S7）
    output reg  [3:0]           i_rw,
    output reg  [11:0]          i_ra,
    input  wire [63:0]          i_rd,
    output reg                  i_we,
    output reg  [3:0]           i_ww,
    output reg  [11:0]          i_wa,
    output reg  [63:0]          i_wd,
    // 閉じたダンプの流れ
    output reg                  d_v,
    output reg  [3:0]           d_w,
    output reg  [31:0]          d_k,
    output reg  [11:0]          d_ch,
    output reg  [63:0]          d_data,
    output reg  [15:0]          flags
);
    localparam [2:0] M_NONE = 3'd0, M_FIRST = 3'd1, M_ACC = 3'd2, M_OUTW = 3'd3, M_FLUSH = 3'd4;
    localparam integer SEL = 4096 - LEAD;     // 選びの始まり（a）
    integer i;

    function [2:0] bplus;                     // (b + k) mod 5（b ≦ 4、k ≦ 4）
        input [2:0] b, k;
        reg   [3:0] s;
        begin s = b + k; bplus = (s >= 4'd5) ? s - 4'd5 : s[2:0]; end
    endfunction
    function [2:0] ewin;                      // e = G_L2 − 12 − NS（0 で止める）
        input [2:0] ns;
        integer t;
        begin t = G_L2 - 12 - ns; ewin = (t < 0) ? 3'd0 : (t > 7) ? 3'd7 : t[2:0]; end
    endfunction

    // =====================================================================
    // 書きの側
    // =====================================================================
    reg              v0;
    reg  [3:0]       w0;
    reg  signed [W-1:0] yr0, yi0;
    always @(posedge clk) begin
        v0 <= in_v && !rst; w0 <= in_w; yr0 <= in_re; yi0 <= in_im;
    end
    (* ram_style = "distributed" *) reg [48:0] ws [0:H-1];       // {fin, nf, wb, wa}
    (* ram_style = "distributed" *) reg [34:0] jt [0:H-1];       // {fin, wb}
    reg  [H-1:0]     wv;                          // ws[w] を書いたことがある（LUTRAM は rst で消さず、これで 0 と読む）
    wire [48:0]      st  = wv[w0] ? ws[w0] : 49'd0;
    wire [11:0]      wa  = st[11:0];
    wire [2:0]       wb  = st[14:12];
    wire [1:0]       nf  = st[16:15];
    wire [31:0]      fin = st[48:17];
    wire [2:0]       ns0 = cfg_ns[w0*3 +: 3];
    wire [1:0]       bs  = (ns0 <= 3'd2) ? 2'd0 : (ns0 <= 3'd4) ? 2'd1 : 2'd2;
    localparam signed [W:0] ZMAX = 131071, ZMIN = -131072;
    wire signed [W:0] tr = ($signed({yr0[W-1], yr0}) + ((bs == 2'd0) ? 0 : (1 <<< (bs - 1)))) >>> bs;
    wire signed [W:0] ti = ($signed({yi0[W-1], yi0}) + ((bs == 2'd0) ? 0 : (1 <<< (bs - 1)))) >>> bs;
    wire [17:0]      zr = (tr > ZMAX) ? 18'h1FFFF : (tr < ZMIN) ? 18'h20000 : tr[17:0];
    wire [17:0]      zi = (ti > ZMAX) ? 18'h1FFFF : (ti < ZMIN) ? 18'h20000 : ti[17:0];
    wire             zsat = v0 && ((tr > ZMAX) || (tr < ZMIN) || (ti > ZMAX) || (ti < ZMIN));
    wire             fdone = v0 && (wa == 12'd4095);
    wire [3:0]       sl0 = cfg_sl[w0*4 +: 4];
    wire             ddr0 = (sl0 >= S);
    // DDR の窓: 8 bit に（h = sat8(round(z / 2^g))）、4 標本を語に（as[w] = 前の 3 標本）。z を作る段の 1 つ後（I2）で
    //   （D-2 の OOC の 1 回目は z と同じ段に縦に並べ、WNS −1.528 ns）
    reg              d1_v;
    reg  [3:0]       d1_w, d1_k, g0w;
    reg  [2:0]       d1_f;
    reg  [11:0]      d1_a;
    reg  signed [17:0] zrs, zis;
    always @(posedge clk) begin
        d1_v <= v0 && ddr0 && !rst; d1_w <= w0; d1_k <= sl0 - S; d1_f <= fin[2:0]; d1_a <= wa;
        g0w <= cfg_g[w0*4 +: 4]; zrs <= zr; zis <= zi;
    end
    wire signed [18:0] ur = ($signed({zrs[17], zrs}) + ((g0w == 4'd0) ? 0 : (1 <<< (g0w - 1)))) >>> g0w;
    wire signed [18:0] ui = ($signed({zis[17], zis}) + ((g0w == 4'd0) ? 0 : (1 <<< (g0w - 1)))) >>> g0w;
    wire [7:0]       hr = (ur > 127) ? 8'h7F : (ur < -128) ? 8'h80 : ur[7:0];
    wire [7:0]       hi = (ui > 127) ? 8'h7F : (ui < -128) ? 8'h80 : ui[7:0];
    wire             hsat = d1_v && ((ur > 127) || (ur < -128) || (ui > 127) || (ui < -128));
    (* ram_style = "distributed" *) reg [47:0] as [0:H-1];
    always @(posedge clk) begin
        if (d1_v) as[d1_w] <= {hi, hr, as[d1_w][47:16]};
        dw_v   <= d1_v && (d1_a[1:0] == 2'd3) && !rst;
        dw_k   <= d1_k; dw_w <= d1_w; dw_f <= d1_f; dw_row <= d1_a[11:2];
        dw_d   <= {hi, hr, as[d1_w]};
    end
    reg  [H-1:0]     pend, pend2;
    reg              pend_ovf;
    reg              h1_v = 1'b0;
    reg  [3:0]       h1_w;
    reg  [3:0]       h1_s;
    reg  [2:0]       h1_b;
    reg  [11:0]      h1_a;
    reg  [35:0]      h1_d;
    // 選び（下）が今のクロックで pend を消す窓
    reg              s2_v;
    reg  [3:0]       s2_w;
    reg  [H-1:0]     pset;
    always @(*) begin
        pset = {H{1'b0}};
        if (fdone && !ddr0) pset[w0] = 1'b1;
        if (fl_v)           pset[fl_w] = 1'b1;
    end
    always @(posedge clk) begin
        pend_ovf <= 1'b0;
        if (rst) begin
            wv <= {H{1'b0}};
            pend <= {H{1'b0}}; pend2 <= {H{1'b0}};
        end else begin
            for (i = 0; i < H; i = i + 1) begin
                // 立てる: チップ内の窓は溜まったとき、DDR の窓は DDR に書き終わったとき。消す: 選んだとき。同じクロックなら数は変わらない
                if (pset[i] && !(s2_v && s2_w == i)) begin
                    if (pend2[i])     pend_ovf <= 1'b1;
                    else if (pend[i]) pend2[i] <= 1'b1;
                    else              pend[i]  <= 1'b1;
                end else if (!pset[i] && s2_v && s2_w == i) begin
                    if (pend2[i]) pend2[i] <= 1'b0;
                    else          pend[i]  <= 1'b0;
                end
            end
            if (v0) begin
                wv[w0] <= 1'b1;
                if (fdone) ws[w0] <= {fin + 32'd1, (nf == 2'd3) ? 2'd3 : nf + 2'd1, bplus(wb, 3'd1), 12'd0};
                else       ws[w0] <= {fin, nf, wb, wa + 12'd1};
            end
            if (fdone) jt[w0] <= {fin, wb};
        end
        h1_v <= v0 && !ddr0; h1_w <= w0; h1_s <= cfg_sl[w0*4 +: 4]; h1_b <= wb; h1_a <= wa; h1_d <= {zi, zr};
    end
    // 遅れ D: 小さければ SRL、≧ 128 は BRAM の輪（読んでから書く、遅れ D）。valid も輪に入れ、rst の後 D クロックは 0 と読む
    wire [59:0]      dq_all;
    generate if (D < 128) begin : g_srl
        reg  [59:0]  dl [0:D-1];
        always @(posedge clk) begin
            dl[0] <= {h1_v && !rst, h1_w, h1_s, h1_b, h1_a, h1_d};
            for (i = 1; i < D; i = i + 1) dl[i] <= dl[i-1];
        end
        assign dq_all = dl[D-1];
    end else begin : g_ring
        (* ram_style = "block" *) reg [59:0] dl [0:D-2];
        reg  [$clog2(D)-1:0] dp;
        reg  [59:0]  dqr;
        always @(posedge clk) begin
            dqr <= dl[dp];
            dl[dp] <= {h1_v && !rst, h1_w, h1_s, h1_b, h1_a, h1_d};
            dp <= rst ? 0 : (dp == D - 2) ? 0 : dp + 1'b1;
        end
        reg  [$clog2(D):0] dfill;
        always @(posedge clk) dfill <= rst ? 0 : (dfill == D) ? dfill : dfill + 1'b1;
        assign dq_all = (dfill == D) ? dqr : 60'd0;
    end endgenerate
    wire [58:0]      dq = dq_all[58:0];
    wire             dq_v = dq_all[59];
    wire [3:0]       dq_w = dq[58:55];
    assign hw_v = dq_v;
    assign hw_s = dq[54:51];
    assign hw_b = dq[50:48];
    assign hw_a = dq[47:36];
    assign hw_d = dq[35:0];

    // =====================================================================
    // 選び（枠の頭の前、a = SEL .. SEL + 3）
    // =====================================================================
    reg  [H-1:0]     cm_c [0:4], cm [0:4];        // NS の級ごとの窓（設定から。@(*) は設定が変わったときだけ動く）
    integer          q;
    always @(*)
        for (i = 0; i < 5; i = i + 1)
            for (q = 0; q < H; q = q + 1) cm_c[i][q] = (cfg_ns[q*3 +: 3] == i + 1);
    always @(posedge clk)
        for (i = 0; i < 5; i = i + 1) cm[i] <= cm_c[i];
    reg  [H-1:0]     s0_m [0:4];
    reg  [H-1:0]     s1_oh;
    always @(posedge clk) begin
        for (i = 0; i < 5; i = i + 1) s0_m[i] <= pend & cm[i];
`ifdef ENG_POSCTL
        s1_oh <= pend & (~pend + 1'b1);
`else
        if      (|s0_m[0]) s1_oh <= s0_m[0] & (~s0_m[0] + 1'b1);
        else if (|s0_m[1]) s1_oh <= s0_m[1] & (~s0_m[1] + 1'b1);
        else if (|s0_m[2]) s1_oh <= s0_m[2] & (~s0_m[2] + 1'b1);
        else if (|s0_m[3]) s1_oh <= s0_m[3] & (~s0_m[3] + 1'b1);
        else               s1_oh <= s0_m[4] & (~s0_m[4] + 1'b1);
`endif
    end
    reg  [3:0]       oh_w;
    always @(*) begin
        oh_w = 4'd0;
        for (i = 0; i < H; i = i + 1) if (s1_oh[i]) oh_w = i;
    end
    // s2: 選んだ窓（pend を消す）。s3: 仕事と積分の状態を引いて札を作る
    wire             at_s1 = go && (a == SEL + 1);
    always @(posedge clk) begin
        s2_v <= !rst && at_s1 && (|s1_oh);
        s2_w <= oh_w;
    end
    // s2 のクロックに jt を引き、古いほうの仕事を取る（同じクロックの書き込みの前の値）
    wire [34:0]      jq2 = jt[s2_w];
    reg              s3_v;
    reg  [3:0]       s3_w;
    reg  [31:0]      jr;
    reg  [2:0]       jwb;
    always @(posedge clk) begin
        s3_v <= s2_v; s3_w <= s2_w;
        jr   <= pend2[s2_w] ? jq2[34:3] - 32'd1 : jq2[34:3];
        jwb  <= pend2[s2_w] ? bplus(jq2[2:0], 3'd4) : jq2[2:0];
    end
    wire [1:0]       jnf = (jr >= 32'd3) ? 2'd3 : jr[1:0];
    (* ram_style = "distributed" *) reg [63:0] it [0:H-1];       // {k, j}
    reg  [H-1:0]     on, stt;
    wire [63:0]      iq  = it[s3_w];
    wire [31:0]      ik  = iq[63:32], ij = iq[31:0];
    wire [2:0]       ns3 = cfg_ns[s3_w*3 +: 3];
    wire [2:0]       e3  = ewin(ns3);
    wire [31:0]      f0w = g0 << e3;
    wire [31:0]      nw  = ng << e3;
    reg  [2:0]       md;
    reg  [31:0]      nk, nj;
    reg              n_on, n_st, smiss;
    always @(*) begin
        md = M_NONE; nk = ik; nj = ij; n_on = on[s3_w]; n_st = stt[s3_w]; smiss = 1'b0;
        if (on[s3_w]) begin
            if (!stt[s3_w]) begin
                if (jr == f0w) begin
                    md = M_FIRST; n_st = 1'b1; nk = 32'd0; nj = 32'd1;
                    if (nw == 32'd1) begin nj = 32'd0; nk = 32'd1; end
                end else if (jr > f0w) smiss = 1'b1;
            end else if (ij == 32'd0) begin
                if (ndump != 32'd0 && ik == ndump) begin md = M_FLUSH; n_on = 1'b0; end
                else begin
                    md = M_OUTW; nj = 32'd1;
                    if (nw == 32'd1) begin nj = 32'd0; nk = ik + 32'd1; end
                end
            end else begin
                md = M_ACC; nj = ij + 32'd1;
                if (ij + 32'd1 == nw) begin nj = 32'd0; nk = ik + 32'd1; end
            end
        end
    end
    // 次の枠の仕事（札）: {v, w, 枠 s, 面 wb, タップの有効 vm, mode, dk, sh}
    reg              nx_v;
    reg  [3:0]       nx_w, nx_sh, nx_s, nx_g;
    reg  [2:0]       nx_b, nx_md;
    reg  [3:0]       nx_vm;
    reg  [31:0]      nx_dk;
    reg              start_miss;
    always @(posedge clk) begin
        rq_v <= s3_v && (cfg_sl[s3_w*4 +: 4] >= S) && !rst;      // DDR の窓: 先読みを頼む（DDR の枠と r）
        rq_k <= cfg_sl[s3_w*4 +: 4] - S; rq_r <= jr;
    end
    always @(posedge clk) begin
        start_miss <= 1'b0;
        if (rst) begin
            on <= {H{1'b0}}; stt <= {H{1'b0}}; nx_v <= 1'b0;
        end else begin
            if (go && a == 12'd4095) nx_v <= 1'b0;          // 枠の頭で cur に移した
            if (s3_v) begin
                it[s3_w] <= {nk, nj};
                on[s3_w] <= n_on; stt[s3_w] <= n_st;
                start_miss <= smiss;
                nx_v <= 1'b1; nx_w <= s3_w; nx_s <= cfg_sl[s3_w*4 +: 4]; nx_b <= jwb;
                nx_vm <= {1'b1, jnf >= 2'd1, jnf >= 2'd2, jnf == 2'd3};
                nx_md <= md; nx_dk <= ik - 32'd1; nx_sh <= cfg_sh[s3_w*4 +: 4]; nx_g <= cfg_g[s3_w*4 +: 4];
            end
            if (cmd_run)  begin on <= {H{1'b1}}; stt <= {H{1'b0}}; end
            if (cmd_stop) on <= {H{1'b0}};
        end
    end

    // =====================================================================
    // 読みの側（a が P0。枠の仕事 cur は a = 0 .. 4095 の間そのまま）
    // =====================================================================
    reg              cur_v;
    reg  [3:0]       cur_w, cur_sh, cur_vm, cur_s, cur_g;
    reg  [2:0]       cur_b, cur_md;
    reg  [31:0]      cur_dk;
    always @(posedge clk) begin
        if (rst) cur_v <= 1'b0;
        else if (go && a == 12'd4095) begin
            cur_v <= nx_v; cur_w <= nx_w; cur_s <= nx_s; cur_b <= nx_b; cur_vm <= nx_vm;
            cur_md <= nx_v ? nx_md : M_NONE; cur_dk <= nx_dk; cur_sh <= nx_sh; cur_g <= nx_g;
        end
    end
    // 札 = {v, w 4, s 4, g 4, b 3, vm 4, md 3, dk 32, sh 4} = 59 bit。P0 で cur（a = 0 のとき、cur は今の枠のもの）
    //   cur は a = 4095 の立ち上がりで替わるので、a（P0）と同じ枠のものが同じクロックに並ぶ
    wire [58:0]      tg0 = {cur_v, cur_w, cur_s, cur_g, cur_b, cur_vm, cur_md, cur_dk, cur_sh};
    reg  [58:0]      tg1, tg2, tg3, tg4, tg5, tg6, tg7;
    reg  [8:1]       pv, pl, pf;                  // 枠が回っている・a = 4095・a = 0（P1..P8）
    always @(posedge clk) begin
        tg1 <= tg0; tg2 <= tg1; tg3 <= tg2; tg4 <= tg3; tg5 <= tg4; tg6 <= tg5; tg7 <= tg6;
        if (rst) pv <= 8'd0;
        else     pv <= {pv[7:1], go};
        pl <= {pl[7:1], a == 12'd4095};
        pf <= {pf[7:1], a == 12'd0};
    end
    `define TV(t)  t[58]
    `define TW(t)  t[57:54]
    `define TS(t)  t[53:50]
    `define TG(t)  t[49:46]
    `define TB(t)  t[45:43]
    `define TVM(t) t[42:39]
    `define TMD(t) t[38:36]
    `define TDK(t) t[35:4]
    `define TSH(t) t[3:0]
    // P3: 枠を選ぶ（5 面 × 36 bit）・係数
    reg  [179:0]     hs3;
    reg  [63:0]      dd3;
    reg  signed [17:0] cc3 [0:3], cc4 [0:3];
    always @(posedge clk) begin
        hs3 <= hq[`TS(tg2)*180 +: 180];
        dd3 <= dd;
        cc3[0] <= c0; cc3[1] <= c1; cc3[2] <= c2; cc3[3] <= c3;
        for (i = 0; i < 4; i = i + 1) cc4[i] <= cc3[i];
    end
    // P4: タップ t の面 = b + 2 + t（mod 5）、無効なタップと空の枠は 0。DDR の窓はタップの順に並んだ 8 bit を h·2^g に
    reg  signed [17:0] zr4 [0:3], zi4 [0:3];
    reg  [35:0]      zsel;
    reg  signed [17:0] xr, xi;
    always @(posedge clk) begin
        for (i = 0; i < 4; i = i + 1) begin
            xr = $signed(dd3[i*16 +: 8]) <<< `TG(tg3);
            xi = $signed(dd3[i*16 + 8 +: 8]) <<< `TG(tg3);
            zsel = (`TS(tg3) >= S) ? {xi, xr} : hs3[bplus(`TB(tg3), 3'd2 + i)*36 +: 36];
            if (`TV(tg3) && `TVM(tg3) >> i & 1'b1) begin
                zr4[i] <= zsel[17:0]; zi4[i] <= zsel[35:18];
            end else begin
                zr4[i] <= 18'd0; zi4[i] <= 18'd0;
            end
        end
    end
    // P5: 積・P6: 2 つずつ・P7: 和と丸めの定数・P8: 右へ・飽和
    reg  signed [35:0] mr5 [0:3], mi5 [0:3];
    reg  signed [36:0] ar6 [0:1], ai6 [0:1];
    reg  signed [37:0] ar7, ai7;
    always @(posedge clk) begin
        for (i = 0; i < 4; i = i + 1) begin
            mr5[i] <= zr4[i] * cc4[i];
            mi5[i] <= zi4[i] * cc4[i];
        end
        ar6[0] <= mr5[0] + mr5[1]; ar6[1] <= mr5[2] + mr5[3];
        ai6[0] <= mi5[0] + mi5[1]; ai6[1] <= mi5[2] + mi5[3];
        ar7 <= ar6[0] + ar6[1] + (1 <<< 15);
        ai7 <= ai6[0] + ai6[1] + (1 <<< 15);
    end
    localparam signed [37:0] YMAX = 131071, YMIN = -131072;
    wire signed [37:0] yr7 = ar7 >>> 16, yi7 = ai7 >>> 16;
    reg  [17:0]      fr8, fi8;
    reg              pfb_sat;
    always @(posedge clk) begin
        fr8 <= (yr7 > YMAX) ? 18'h1FFFF : (yr7 < YMIN) ? 18'h20000 : yr7[17:0];
        fi8 <= (yi7 > YMAX) ? 18'h1FFFF : (yi7 < YMIN) ? 18'h20000 : yi7[17:0];
        pfb_sat <= pv[7] && ((yr7 > YMAX) || (yr7 < YMIN) || (yi7 > YMAX) || (yi7 < YMIN));
    end
    // 札の FIFO（FFT の入口で積み、出口の k = 0 で取る）
    wire [58:0]      tg8;
    reg  [58:0]      tg8r;
    always @(posedge clk) tg8r <= tg7;
    assign tg8 = tg8r;
    wire             tq_push = pv[8] && pf[8];
    wire             tq_pop;
    wire [58:0]      tq_head;
    wire             tq_empty, tq_ovf;
    sfifo #(.DW(59), .AW(3)) u_tq (.clk(clk), .rst(rst), .push(tq_push), .din(tg8), .pop(tq_pop),
                                   .dout(tq_head), .empty(tq_empty), .ovf(tq_ovf));

    // =====================================================================
    // FFT（build では Xilinx FFT IP、sim では sim/win_fft_model.v、OOC では黒箱）
    // =====================================================================
    wire [47:0]      s_td = {{6{fi8[17]}}, fi8, {6{fr8[17]}}, fr8};
    wire [63:0]      m_td;
    wire [15:0]      m_tu;
    wire             m_tv, m_tl, s_tready;
    wire             ev_tu, ev_tm, ev_halt, ev_fs;
    win_fft u_fft (
        .aclk(clk), .aresetn(~rst),
        .s_axis_config_tdata(8'h01), .s_axis_config_tvalid(1'b1), .s_axis_config_tready(),
        .s_axis_data_tdata(s_td), .s_axis_data_tvalid(pv[8]), .s_axis_data_tready(s_tready), .s_axis_data_tlast(pl[8]),
        .m_axis_data_tdata(m_td), .m_axis_data_tuser(m_tu), .m_axis_data_tvalid(m_tv), .m_axis_data_tlast(m_tl),
        .event_frame_started(ev_fs), .event_tlast_unexpected(ev_tu), .event_tlast_missing(ev_tm),
        .event_data_in_channel_halt(ev_halt));
    assign rdy = s_tready;

    // =====================================================================
    // 出口: 電力と積分
    // =====================================================================
    wire             k0 = m_tv && (m_tu[11:0] == 12'd0);
    assign tq_pop = k0;
    reg              s1_v, s2o_v, s3o_v, s4_v, s5_v, s6_v;
    reg  [11:0]      k1, k2, k3, k4, k5, k6;
    reg  signed [30:0] y1r, y1i;
    reg  [58:0]      ot;                          // 今のフレームの札（S1 から）
    reg              tq_und;
    always @(posedge clk) begin
        tq_und <= k0 && tq_empty;
        if (k0) ot <= tq_head;
        s1_v <= m_tv && !rst; k1 <= m_tu[11:0];
        y1r <= m_td[30:0]; y1i <= m_td[62:32];
    end
    // S2: q = sat18(Y >>> sh)、積分器の読みを出す
    localparam signed [30:0] QMAX = 131071, QMIN = -131072;
    wire signed [30:0] sr1 = y1r >>> `TSH(ot), si1 = y1i >>> `TSH(ot);
    reg  signed [17:0] q2r, q2i;
    reg  [2:0]       md2, md3, md4, md5, md6;
    reg  [3:0]       w2, w3, w4, w5, w6;
    reg  [31:0]      dk2, dk3, dk4, dk5, dk6;
    always @(posedge clk) begin
        q2r <= (sr1 > QMAX) ? 18'h1FFFF : (sr1 < QMIN) ? 18'h20000 : sr1[17:0];
        q2i <= (si1 > QMAX) ? 18'h1FFFF : (si1 < QMIN) ? 18'h20000 : si1[17:0];
        s2o_v <= s1_v && !rst; k2 <= k1;
        md2 <= `TV(ot) ? `TMD(ot) : M_NONE; w2 <= `TW(ot); dk2 <= `TDK(ot);
        i_ra <= k1; i_rw <= `TW(ot);
    end
    // S3: 二乗・S4: 和・S5・S6: 積分器の値を待つ
    reg  [35:0]      p3r, p3i;
    reg  [36:0]      p4, p5, p6;
    always @(posedge clk) begin
        p3r <= q2r * q2r; p3i <= q2i * q2i;
        p4 <= p3r + p3i;
        p5 <= p4; p6 <= p5;
        s3o_v <= s2o_v && !rst; s4_v <= s3o_v && !rst; s5_v <= s4_v && !rst; s6_v <= s5_v && !rst;
        k3 <= k2; k4 <= k3; k5 <= k4; k6 <= k5;
        md3 <= md2; md4 <= md3; md5 <= md4; md6 <= md5;
        w3 <= w2; w4 <= w3; w5 <= w4; w6 <= w5;
        dk3 <= dk2; dk4 <= dk3; dk5 <= dk4; dk6 <= dk5;
    end
    // S7: 書き・流す
    always @(posedge clk) begin
        i_we <= s6_v && (md6 == M_FIRST || md6 == M_ACC || md6 == M_OUTW);
        i_ww <= w6; i_wa <= k6;
        i_wd <= (md6 == M_ACC) ? i_rd + {27'd0, p6} : {27'd0, p6};
        d_v  <= s6_v && (md6 == M_OUTW || md6 == M_FLUSH);
        d_w  <= w6; d_k <= dk6; d_ch <= k6; d_data <= i_rd;
    end

    // =====================================================================
    // 見張り
    // =====================================================================
    // 履歴の書き込み（遅れの後）が、読み中の仕事・次の仕事・溜まった仕事の最古の面（b − 3 = b + 2）の未読の番地に来た
    wire [2:0]       cur_old = bplus(cur_b, 3'd2);
    wire [2:0]       nx_old  = bplus(nx_b, 3'd2);
    wire [34:0]      jdq     = jt[dq_w];
    wire [2:0]       pd_old  = bplus(jdq[2:0], pend2[dq_w] ? 3'd1 : 3'd2);
    reg              h_ovr;
    always @(posedge clk)
        h_ovr <= dq_v && ((cur_v && dq_w == cur_w && hw_b == cur_old && hw_a >= a) ||
                          (nx_v && dq_w == nx_w && hw_b == nx_old) ||
                          (pend[dq_w] && hw_b == pd_old));
    always @(posedge clk) begin
        if (rst) flags <= 16'd0;
        else flags <= flags | {7'd0, hsat, ev_tu | ev_tm | ev_halt, zsat, tq_ovf | tq_und, start_miss, pfb_sat,
                               pv[8] && !s_tready, h_ovr, pend_ovf};
    end
endmodule
