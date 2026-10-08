// SPDX-License-Identifier: BSD-3-Clause
//
// wspec_core — 窓 1 つの分光: z（複素 18 bit・Q4）→ フレームの溜め（5 面）→ PFB（T = 4）→ 複素 4096 点 FFT → 電力 → 積分（4096 ch）
//
// **proj020: 溜めと FFT の間に PFB（T = 4）**。ch の応答のサイドローブを矩形の −13 dB から ≧ 1 ch で −54 dB に、隣の ch と −3 dB で交わる形で（原型 sinc × Kaiser β 5・bw 1.198、
// Σh² = 4096 で雑音の電力を保つ。model/pfb4.py が正）。溜めを 5 面のリング（URAM）にして履歴を兼ね、IP へ流す 4096 語を
// 4 面から同じ番地で読んで積和する。出力フレームの番号は最新の入力フレーム（fin・F0・dstamp の区切りの意味は変えない）。
// 出力フレーム r は入力フレーム r − 3 … r を重みつきで含むので、**区切りの重心は矩形より 1.5·L 前**（L = 窓のフレーム長。PS の側で扱う）。
// スナップショットは PFB の出口（FFT の入力）を残す。読みの段は自走で、tready の握手は段の後の FIFO（深さ 16）と出口のレジスタで取る。
// 以下の rev2 の話の「出口のレジスタ」はその FIFO の後ろのもの。
//
// **溜めを置く理由**: realtime の FFT IP は入力の途切れを待たずに進む（proj011）。窓の出力は W MSPS（W = 8 なら 32 クロックに 1 個）で
// 必ず途切れるので、4096 語を 2 面の溜めに書き、溜まった面を 4096 クロック途切れなく IP へ流す。次のフレームが溜まるには
// 4096 クロック以上かかる（入力は 1 / クロック以下）ので、読み出しは必ず間に合う（間に合わなければ FLAGS[1]）。
//
// **rev2: IP の s_axis_data_tready を守る**。rev1 は tready を見ずに流し、実機 1 回目で WRST の直後に tready = 0 の間の
// サンプルを IP が受けず、IP の中のフレームの枠が溜めの枠からずれたまま回った（FLAGS[2] が立ち続け、--golden が NG）。
// rev2 は出口のレジスタ（fd・f_v・f_last）を「空いている か IP が受けた」ときだけ進める（AXI の握手）。待たされても
// 1 語も落とさないので、IP の枠 = 溜めの枠がいつも保たれる。待たされたぶん読み出しが遅れても、次の面の開始は pend で
// 予約して遅れて始める（書き込みが未読の番地に追いついたときだけ FLAGS[1]）。
//
// ---- フレームと ch ----
// フレーム f = z の 4096f … 4096f + 4095 番目（rst の後の最初の z を 0 番とする）。fin = 溜め終えたフレームの数。
// FFT は順変換・unscaled（出力 31 bit = 18 + 12 + 1）・自然順。ch b（0..4095）は ν = b·W/4096（b < 2048）/ (b − 4096)·W/4096（b ≧ 2048）。
// **並べ替え（fftshift）とゾーン 2 の反転（IF = 4096 − c − ν）は PS 側**。
//
// ---- 電力と積分（spec_core と同じ約束）----
//   q = sat18(Y >>> SHIFT)、p = q_re² + q_im²（37 bit）、64 bit で N_ACC フレーム積む。二面（ダンプごとに交互）。
//   RUN: F0 = fin + 2（確実に未来）。フレーム F0 + k·N … F0 + k·N + N − 1 をダンプ k に積む。N_DUMP = 0 なら止めるまで。
//   **proj017: F0 を時刻の格子に切り上げる。**格子 G = 2^G_L2 ビート（既定 19 = 524,288 ビート = 2.048 ms）、窓のフレーム長は
//   L = 4096·2^(NS−1) = 2^(11+NS) ビート。M = G / L = 2^e フレーム（e = max(0, G_L2 − 11 − NS)。NS 1..8 → M = 128 … 1）として
//     **F0 = (⌊fin / M⌋ + 2)·M**（格子の番号 g0 = ⌊fin / M⌋ + 2。F0 − fin は M + 1 〜 2M、M = 1 なら従来の fin + 2 と同じ）
//   フレームの番号は WRST からの数（窓の WSTART が 0 番の頭）。WSTART が全窓で G の格子の同じ位相にあれば、⌊fin / M⌋ は
//   「RUN の時点で、WSTART から数えて何個目の格子まで z が溜まったか」で、窓の幅に依らず同じ値になる（窓の遅れ D(NS) と
//   WSTART からの位相の和が格子 1 個の中に収まる限り）。**だから F0·L（= ダンプの区切りのサンプルの時刻）が全窓で同じ格子の点になり、
//   N·L も G の倍数に取れば、以後のダンプの区切りも全窓で揃う**（同じ k どうし）。切り上げ（⌈(fin + 2) / M⌉）では、格子の点の近くで
//   RUN を受けたとき M = 1 の窓だけ 1 個先の点に行く（WRST と RUN を同じ発火にかけた場合に起きる）ので取らない。
//   段: RUN のクロックに fin + 2（従来どおり、run_f0・sn_next・dstamp）、次のクロック（run_q）に g_add = F0 − (fin + 2)
//   = 2M − 2 − (fin mod M)（≦ 254）を足す。F0 は 2 フレーム以上先なので、足す前の値が 1 クロック残っても
//   フレームの頭の比べ（sn_hit・dstamp・pre_f0hit）には当たらない。dstamp の下位 8 bit の比べは F0 − fin ≦ 256 で取り違えない。
//   sim で古い試験の形（NS 1・短い入力）を保つときは G_L2 を小さく（12 なら NS ≧ 1 で M = 1 = 従来どおり）。陽性対照 WSPEC_NOGRID は M = 1
//   ダンプが閉じるたびに SEQ が 1 増え、rd_* と読み出しの面がその面に切り替わる（seqlock。PS は SEQ → 中身 → SEQ）。
//   スナップショット: ダンプ k の最初のフレーム（F0 + k·N）の z を 4096 語、面 k mod 2 に残す（snap_f* がその番号）。
//   **N_ACC = 1 ならスナップショットの FFT とダンプが 1 対 1**（PS 側の --golden の型）
//
// FLAGS（粘着、cmd_clr で消す）: [0] XK_INDEX が 1 ずつ進まなかった / [1] 溜めの読み出しが間に合わなかった /
//   [2] IP の TLAST 事象 / [3] IP の data_in_channel_halt / [4] IP に待たされた（f_v = 1 で tready = 0。rev2 はデータを保って待つ）/
//   [5] proj020: PFB の出口が 18 bit で飽和した
// 見張り（rst から）: stall_cnt = 待たされたクロック数（飽和）/ rdy0 = rst の解除から tready が最初に 1 になるまでのクロック数
//
// 段（FFT の出力を受けたクロックを S0）: S1 丸めと飽和 → S2 二乗の入口・積分の読み出し番地 → S3 二乗 → S4 電力・読み値
// → S5 書き込み（初回は p、以降は 読み値 + p）。同じ ch は 4096 クロックおきにしか来ないので、読み書きの追い越しは起きない

`timescale 1ns / 1ps

module wspec_core #(
    parameter integer FW = 48,
    parameter integer ZW = 18,
    parameter integer SNAP = 1,    // 1: スナップショットの記憶を中に持つ / 0: 持たず、書き込みを sn_w* に出す（ADC ごとに 1 つを共有する。proj015）
    parameter integer G_L2 = 19    // proj017: 時刻の格子 G = 2^G_L2 ビート（F0 の切り上げ。冒頭）
)(
    input  wire                 clk,
    input  wire                 rst,
    input  wire                 z_valid,
    input  wire signed [ZW-1:0] z_re, z_im,
    // 制御（1 クロックのパルス）と設定
    input  wire                 cmd_run, cmd_stop, cmd_clr,
    input  wire [31:0]          r_nacc, r_ndump,
    input  wire [3:0]           r_shift,
    input  wire [3:0]           w_ns,          // proj017: 今の窓の NS（1..8。WRST で決まり、RUN の間は変わらない）
    // 状態
    output reg  [FW-1:0]        fin,
    output reg  [FW-1:0]        fout,
    output reg  [FW-1:0]        run_f0,
    output reg                  sched, acc_on,
    output reg  [31:0]          seq, rd_k, rd_n, rd_sat,
    output reg  [FW-1:0]        rd_f0,
    output reg                  rd_bank,
    output reg  [FW-1:0]        snap_f0, snap_f1,
    output reg  [7:0]           flags,
    output reg  [31:0]          stall_cnt,
    output reg  [31:0]          rdy0,
    // 読み出し（2 クロック）: スペクトル（面 rd_bk の ch rd_ch）/ スナップショット（面 sn_bk の語 sn_a、{im, re}）
    input  wire                 rd_bk,
    input  wire [11:0]          rd_ch,
    output wire [63:0]          rd_data,
    input  wire                 sn_bk,
    input  wire [11:0]          sn_a,
    output wire [2*ZW-1:0]      sn_data,
    // スナップショットの書き込み（SNAP = 0 のとき外の記憶が使う。SNAP = 1 でも出る）: 面・番地 {sn_wbank, sn_waddr}、{im, re}
    output wire                 sn_wen,
    output wire [12:0]          sn_waddr,
    output wire [2*ZW-1:0]      sn_wdata,
    // proj016: 時刻と健全性（src/dstamp.v）。t_now = time_core のビート（コアの中で time_core と同じ値）
    input  wire [63:0]          t_now,
    input  wire [7:0]           ev,
    output wire [63:0]          rd_t,           // 閉じたダンプの最初のフレームの最初の z が入ったビート（rd_* と同じ commit で切り替わる）
    output wire [15:0]          rd_h,           // そのダンプの健全性（dstamp.v の冒頭）
    output wire [63:0]          run_t           // RUN を受けたビート
);
    localparam integer NF = 4096;
    localparam integer YW = ZW + 13;       // 31
    localparam integer QW = 18;
    localparam integer PW = 2 * QW + 1;    // 37

    // =====================================================================
    // 溜め（proj020: 5 面のリング × 4096 × {im, re}、URAM）→ PFB（T = 4）→ 小さな FIFO → IP
    // =====================================================================
    // 面: フレーム f は面 f mod 5（WRST の後の 0 番から）。フレーム r が溜まったら、出力フレーム r（最新の入力フレームの番号で呼ぶ）を
    //   面 r − 3 … r（= rbk + 2, + 3, + 4, + 0 mod 5）から同じ番地 a で読み、y[a] = sat18((Σ_t c[a + 4096t]·z_{r−3+t}[a] + 2^15) >> 16)。
    //   r − 3 + t < 0 のタップは 0（WRST の直後の 3 フレーム。面に前の走りの値が残っていても混ぜない）。式の正は model/pfb4.py
    // 読みは自走の段（P0 … P7）で、IP の tready では止めない。段の出口を深さ 16 の FIFO に入れ、IP へは FIFO から握手で出す。
    //   読みを出す（issue）のは、出して FIFO から抜けていない語の数 ocnt < 16 のときだけ（貸し借り。FIFO は溢れない）
    // 書き込みが、読み中の出力の最古の面（rbk − 3）の未読の番地（≧ ra）/ 予約中の出力の最古の面 に来たら FLAGS[1]（従来と同じ意味）
    localparam integer NB = 5;
    localparam integer CF = 16;            // 係数の小数部（model/pfb4.py）
    localparam integer FD = 16;            // FIFO の深さ
    reg [11:0]     wa;
    reg [2:0]      wb;                    // 書いている面（0..4）
    reg            rd_go;                 // 読み出し中（ra = 次に出す番地）
    reg [2:0]      rbk;                   // 読み中の出力フレームの最新の面
    reg [3:0]      rvm;                   // 読み中の出力のタップの有効（[t]、t = 3 が最新）
    reg            rsn, rsn_b;            // 読み中の出力をスナップショットに残す・その面
    reg [11:0]     ra;
    reg            pend;                  // 溜まったがまだ読み始めていない出力
    reg [2:0]      pbk;
    reg [FW-1:0]   pfr;
    reg            ovr;
    reg [4:0]      ocnt;                  // 出して FIFO から抜けていない語の数（≦ 16）
    reg            f_v, f_last;           // 出口（IP の入力）
    wire           s_tready;
    wire           issue  = rd_go && (ocnt < FD);
    wire           rd_end = issue && (ra == 12'd4095);
    wire           fdone  = z_valid && (wa == 12'd4095);
    wire           can_st = !rd_go || rd_end;
    wire           st_now = can_st && (pend || fdone);
    wire [FW-1:0]  st_fr  = pend ? pfr : fin;               // 読み始める出力の番号
    function [2:0] bplus;                                   // (b + k) mod 5（b ≦ 4、k ≦ 4）
        input [2:0] b, k;
        reg   [3:0] s;
        begin s = b + k; bplus = (s >= 4'd5) ? s - 4'd5 : s[2:0]; end
    endfunction
    wire [2:0]     r_old = bplus(rbk, 3'd2);                // 読み中の出力の最古の面（rbk − 3）
    wire [2:0]     p_old = bplus(pbk, 3'd2);
    // スナップショットの予約（ダンプ k の最初のフレーム = 出力フレーム F0 + k·N）。proj020: 読みの側で PFB の出口（FFT の入力）を残す
    reg            sn_on;                 // RUN から N_DUMP 回ぶん
    reg  [FW-1:0]  sn_next;
    reg  [31:0]    sn_k;
    reg  [31:0]    run_n, run_ndump;
    wire [31:0]    n_eff = (run_n == 0) ? 32'd1 : run_n;
    wire           st_hit = sn_on && (st_fr == sn_next);
    // proj017: F0 を格子に（冒頭）。gmask = M − 1（≦ 127）、run_q = RUN の次のクロック、g_add = 2M − 2 − (fin mod M)
    reg  [7:0]     gmask;
    reg            run_q;
    integer        g_e;
    always @(posedge clk) begin
        g_e = G_L2 - 11 - $signed({1'b0, w_ns});
`ifdef WSPEC_NOGRID
        gmask <= 8'd0;                                         // 陽性対照: 切り上げない（S-4 が落ちること）
`else
        gmask <= (g_e <= 0) ? 8'd0 : (g_e >= 7) ? 8'd127 : ((8'd1 << g_e) - 8'd1);
`endif
        run_q <= cmd_run && !rst;
    end
    wire [7:0]     g_fin = run_f0[7:0] - 8'd2;                          // RUN の時点の fin の下位（run_f0 は fin + 2 のまま）
    wire [7:0]     g_add = {gmask[6:0], 1'b0} - (g_fin & gmask);        // 2(M − 1) − (fin mod M) = 2M − 2 − (fin mod M)

    always @(posedge clk) begin
        ovr <= 1'b0;
        if (rst) begin
            wa <= 12'd0; wb <= 3'd0; fin <= {FW{1'b0}};
            rd_go <= 1'b0; rbk <= 3'd0; rvm <= 4'd0; rsn <= 1'b0; rsn_b <= 1'b0; ra <= 12'd0;
            pend <= 1'b0; pbk <= 3'd0; pfr <= {FW{1'b0}};
            sn_on <= 1'b0; sn_next <= {FW{1'b0}}; sn_k <= 32'd0;
            snap_f0 <= {FW{1'b1}}; snap_f1 <= {FW{1'b1}};
        end else begin
            if (issue) begin
                ra <= ra + 12'd1;
                if (ra == 12'd4095) rd_go <= 1'b0;
            end
            // 出力の読み始め: 予約（pend）が先、無ければ今溜まった出力。読み中なら予約する
            if (st_now) begin
                rd_go <= 1'b1; ra <= 12'd0; rbk <= pend ? pbk : wb;
                rvm   <= {1'b1, st_fr >= 1, st_fr >= 2, st_fr >= 3};
                rsn   <= st_hit; rsn_b <= sn_k[0];
                if (st_hit) begin
                    if (sn_k[0]) snap_f1 <= st_fr; else snap_f0 <= st_fr;
                    sn_k    <= sn_k + 32'd1;
                    sn_next <= sn_next + n_eff;
                    if (run_ndump != 32'd0 && sn_k + 32'd1 == run_ndump) sn_on <= 1'b0;
                end
                pend  <= pend && fdone;
            end else if (fdone) begin
                pend <= 1'b1;
            end
            if (fdone) begin pbk <= wb; pfr <= fin; end
            // 書き込みが未読のところを潰す
            if (z_valid && ((rd_go && wb == r_old && wa >= ra) || (pend && wb == p_old))) ovr <= 1'b1;
            if (z_valid) begin
                wa <= wa + 12'd1;
                if (wa == 12'd4095) begin
                    wb  <= bplus(wb, 3'd1);
                    fin <= fin + 1'b1;
                end
            end
            if (cmd_run) begin
                sn_on <= 1'b1; sn_next <= fin + 2; sn_k <= 32'd0;
            end
            if (run_q) sn_next <= sn_next + g_add;              // proj017: 格子へ（run_f0 と同じ量）
            if (cmd_stop) sn_on <= 1'b0;
        end
    end

    // ---- 読みの段 P0 … P7（自走）----
    // P0: 番地・印 → P1: 面と ROM の読み → P2: 出力レジスタ → P3: タップの選択・係数 → P4: 積 → P5: 2 つずつの和 → P6: 和・丸めの定数 → P7: 右へ・飽和
    reg            p0_v, p0_l, p0_sn, p0_snb;
    reg [11:0]     p0_a;
    reg [2:0]      p0_bk;
    reg [3:0]      p0_vm;
    reg [22:0]     p1_t, p2_t, p3_t, p4_t, p5_t, p6_t;     // {v, l, sn, snb, a[11:0], bk[2:0], vm[3:0]}（下の define）
    always @(posedge clk) begin
        if (rst) begin
            p0_v <= 1'b0;
            p1_t <= 23'd0; p2_t <= 23'd0; p3_t <= 23'd0; p4_t <= 23'd0; p5_t <= 23'd0; p6_t <= 23'd0;
        end else begin
            p0_v <= issue;
            p1_t <= {p0_v, p0_l, p0_sn, p0_snb, p0_a, p0_bk, p0_vm};
            p2_t <= p1_t; p3_t <= p2_t; p4_t <= p3_t; p5_t <= p4_t; p6_t <= p5_t;
        end
        p0_l <= (ra == 12'd4095); p0_a <= ra; p0_bk <= rbk; p0_vm <= rvm; p0_sn <= rsn; p0_snb <= rsn_b;
    end
    `define PV(t)   t[22]
    `define PL(t)   t[21]
    `define PSN(t)  t[20]
    `define PSB(t)  t[19]
    `define PA(t)   t[18:7]
    `define PBK(t)  t[6:4]
    `define PVM(t)  t[3:0]
    // 面（URAM）。読みの番地は P0 の p0_a、値は P2 に出る
    wire [2*ZW-1:0] bq [0:NB-1];
    genvar gb;
    generate
        for (gb = 0; gb < NB; gb = gb + 1) begin : g_ring
            (* ram_style = "ultra" *) reg [2*ZW-1:0] mem [0:NF-1];
            reg [2*ZW-1:0] q1, q2;
            always @(posedge clk) begin
                if (z_valid && wb == gb) mem[wa] <= {z_im, z_re};
                q1 <= mem[p0_a];
                q2 <= q1;
            end
            assign bq[gb] = q2;
        end
    endgenerate
    // 係数（P2 に出る）: タップ 0・3 = ROM 0 の番地 a・4095 − a、タップ 1・2 = ROM 1 の番地 a・4095 − a
    wire signed [17:0] c0, c1, c2, c3;
    pfb4_rom #(.P(0)) u_rom0 (.clk(clk), .addr_a(p0_a), .addr_b(12'd4095 - p0_a), .c_a(c0), .c_b(c3));
    pfb4_rom #(.P(1)) u_rom1 (.clk(clk), .addr_a(p0_a), .addr_b(12'd4095 - p0_a), .c_a(c1), .c_b(c2));
    // P3: タップ t の面 = rbk + 2 + t（mod 5）、無効なタップは 0
    reg signed [ZW-1:0] zr3 [0:3], zi3 [0:3];
    reg signed [17:0]   cc3 [0:3];
    reg [2*ZW-1:0]      zsel;
    integer             tt;
    always @(posedge clk) begin
        for (tt = 0; tt < 4; tt = tt + 1) begin
`ifdef WSPEC_PFB_POSCTL
            // 陽性対照: フレームの順を逆に（タップ t に面 rbk − t を当てる。有効の印も同じ面に付けて X を混ぜない）→ スナップショットが模型と合わないこと
            zsel = bq[bplus(`PBK(p2_t), 3'd5 - tt)];
            if (p2_t[3 - tt]) begin
`else
            zsel = bq[bplus(`PBK(p2_t), 3'd2 + tt)];
            if (p2_t[tt]) begin
`endif
                zr3[tt] <= zsel[ZW-1:0]; zi3[tt] <= zsel[2*ZW-1:ZW];
            end else begin
                zr3[tt] <= {ZW{1'b0}};   zi3[tt] <= {ZW{1'b0}};
            end
        end
        cc3[0] <= c0; cc3[1] <= c1; cc3[2] <= c2; cc3[3] <= c3;
    end
    // P4: 積（18 × 18）
    reg signed [ZW+17:0] mr4 [0:3], mi4 [0:3];
    always @(posedge clk) for (tt = 0; tt < 4; tt = tt + 1) begin
        mr4[tt] <= zr3[tt] * cc3[tt];
        mi4[tt] <= zi3[tt] * cc3[tt];
    end
    // P5: 2 つずつ
    reg signed [ZW+18:0] ar5 [0:1], ai5 [0:1];
    always @(posedge clk) begin
        ar5[0] <= mr4[0] + mr4[1]; ar5[1] <= mr4[2] + mr4[3];
        ai5[0] <= mi4[0] + mi4[1]; ai5[1] <= mi4[2] + mi4[3];
    end
    // P6: 和と丸めの定数
    reg signed [ZW+19:0] ar6, ai6;
    always @(posedge clk) begin
        ar6 <= ar5[0] + ar5[1] + (1 <<< (CF - 1));
        ai6 <= ai5[0] + ai5[1] + (1 <<< (CF - 1));
    end
    // P7: 右へ・飽和 → FIFO とスナップショット
    localparam signed [ZW+19:0] YMAX =  (1 <<< (ZW-1)) - 1;
    localparam signed [ZW+19:0] YMIN = -(1 <<< (ZW-1));
    wire signed [ZW+19:0] yr6 = ar6 >>> CF, yi6 = ai6 >>> CF;
    reg  signed [ZW-1:0]  pf_re, pf_im;
    reg                   pf_sat, p7_v, p7_l, p7_sn, p7_snb;
    reg  [11:0]           p7_a;
    always @(posedge clk) begin
        pf_re  <= (yr6 > YMAX) ? YMAX[ZW-1:0] : (yr6 < YMIN) ? YMIN[ZW-1:0] : yr6[ZW-1:0];
        pf_im  <= (yi6 > YMAX) ? YMAX[ZW-1:0] : (yi6 < YMIN) ? YMIN[ZW-1:0] : yi6[ZW-1:0];
        pf_sat <= `PV(p6_t) && ((yr6 > YMAX) || (yr6 < YMIN) || (yi6 > YMAX) || (yi6 < YMIN));
        p7_v   <= !rst && `PV(p6_t);
        p7_l   <= `PL(p6_t); p7_sn <= `PSN(p6_t); p7_snb <= `PSB(p6_t); p7_a <= `PA(p6_t);
    end
    wire pfb_sat = p7_v && pf_sat;

    // FIFO（深さ 16、{last, im, re}）と出口
    reg [2*ZW:0]  ff [0:FD-1];
    reg [4:0]     fwp, frp;
    wire          f_ne = (fwp != frp);
`ifdef WSPEC_NOREADY
    wire          oadv = 1'b1;                    // 陽性対照: rev1 と同じく tready を見ない
`else
    wire          oadv = !f_v || s_tready;        // 出口が空いている / IP が今の語を受けた
`endif
    wire          f_pop = f_ne && oadv;
    reg [2*ZW-1:0] fd;
    always @(posedge clk) begin
        if (p7_v) ff[fwp[3:0]] <= {p7_l, pf_im, pf_re};
        if (rst) begin
            fwp <= 5'd0; frp <= 5'd0; ocnt <= 5'd0; f_v <= 1'b0; f_last <= 1'b0;
        end else begin
            if (p7_v)  fwp <= fwp + 5'd1;
            if (f_pop) frp <= frp + 5'd1;
            ocnt <= ocnt + {4'd0, issue} - {4'd0, f_pop};
            if (oadv) begin
                f_v    <= f_ne;
                f_last <= f_ne && ff[frp[3:0]][2*ZW];
            end
        end
        if (oadv) fd <= ff[frp[3:0]][2*ZW-1:0];
    end
    // スナップショットの書き込み（P7、出力の番地 a）
    assign sn_wen   = p7_v && p7_sn;
    assign sn_waddr = {p7_snb, p7_a};
    assign sn_wdata = {pf_im, pf_re};
    // 見張り
    reg rdy_seen;
    always @(posedge clk) begin
        if (rst) begin
            stall_cnt <= 32'd0; rdy0 <= 32'd0; rdy_seen <= 1'b0;
        end else begin
            if (f_v && !s_tready && stall_cnt != 32'hFFFF_FFFF) stall_cnt <= stall_cnt + 32'd1;
            if (s_tready) rdy_seen <= 1'b1;
            else if (!rdy_seen && rdy0 != 32'hFFFF_FFFF) rdy0 <= rdy0 + 32'd1;
        end
    end

    // =====================================================================
    // FFT（build では Xilinx FFT IP、sim では sim/win_fft_model.v。同じポート）
    // =====================================================================
    wire [47:0] s_td = {{(24-ZW){fd[2*ZW-1]}}, fd[2*ZW-1:ZW], {(24-ZW){fd[ZW-1]}}, fd[ZW-1:0]};
    wire [63:0] m_td;
    wire [15:0] m_tu;
    wire        m_tv, m_tl;
    wire        ev_tu, ev_tm, ev_halt, ev_fs;
    win_fft u_fft (
        .aclk                        (clk),
        .aresetn                     (~rst),
        .s_axis_config_tdata         (8'h01),
        .s_axis_config_tvalid        (1'b1),
        .s_axis_config_tready        (),
        .s_axis_data_tdata           (s_td),
        .s_axis_data_tvalid          (f_v),
        .s_axis_data_tready          (s_tready),
        .s_axis_data_tlast           (f_last),
        .m_axis_data_tdata           (m_td),
        .m_axis_data_tuser           (m_tu),
        .m_axis_data_tvalid          (m_tv),
        .m_axis_data_tlast           (m_tl),
        .event_frame_started         (ev_fs),
        .event_tlast_unexpected      (ev_tu),
        .event_tlast_missing         (ev_tm),
        .event_data_in_channel_halt  (ev_halt)
    );

    // =====================================================================
    // 出力側: フレームの判定（spec_core と同じ。fs = ch 0 のクロック）
    // =====================================================================
    wire        o_valid = m_tv;
    wire [11:0] o_k     = m_tu[11:0];
    reg  [11:0] k_exp;
    reg  [31:0] cur_k, cur_idx;
    reg         cur_act, cur_first, cur_last, cur_bank;
    reg  [FW-1:0] pend_f0_0, pend_f0_1;
    reg  [31:0] pend_k_0, pend_k_1;

    reg [31:0] pre_kp1, pre_idxp1;
    reg        pre_end, pre_idxp1_is0, pre_nxt_last, pre_zero_last, pre_f0hit;
    always @(posedge clk) begin
        pre_kp1       <= cur_k + 32'd1;
        pre_end       <= (run_ndump != 32'd0) && (cur_k + 32'd1 == run_ndump);
        pre_idxp1     <= cur_idx + 32'd1;
        pre_idxp1_is0 <= (cur_idx == 32'hFFFF_FFFF);
        pre_nxt_last  <= (cur_idx + 32'd1 == n_eff - 32'd1);
        pre_zero_last <= (n_eff == 32'd1);
        if (rst || cmd_run)                     pre_f0hit <= 1'b0;
        else if (o_valid && o_k == 12'd4095)    pre_f0hit <= (fout + 1'b1 == run_f0);
    end

    reg        d_act, d_newrun, d_stop, d_zero;
    reg [31:0] d_k, d_idx;
    reg        d_idx_is0, d_idx_last;
    always @* begin
        d_act = 1'b0; d_newrun = 1'b0; d_stop = 1'b0; d_k = cur_k; d_zero = 1'b0;
        if (sched && pre_f0hit) begin
            d_act = 1'b1; d_newrun = 1'b1; d_k = 32'd0; d_zero = 1'b1;
        end else if (acc_on) begin
            if (cur_last) begin
                if (pre_end) d_stop = 1'b1;
                else begin d_act = 1'b1; d_k = pre_kp1; d_zero = 1'b1; end
            end else d_act = 1'b1;
        end
        d_idx      = d_zero ? 32'd0 : pre_idxp1;
        d_idx_is0  = d_zero ? 1'b1  : pre_idxp1_is0;
        d_idx_last = d_zero ? pre_zero_last : pre_nxt_last;
    end
    wire fs      = o_valid && (o_k == 12'd0);
    wire t_act   = fs ? d_act : cur_act;
    wire t_first = fs ? d_idx_is0 : cur_first;
    wire t_last  = fs ? d_idx_last : cur_last;
    wire t_bank  = fs ? d_k[0] : cur_bank;

    always @(posedge clk) begin
        if (rst) begin
            fout <= {FW{1'b0}}; k_exp <= 12'd0;
            sched <= 1'b0; acc_on <= 1'b0;
            cur_k <= 0; cur_idx <= 0;
            cur_act <= 1'b0; cur_first <= 1'b0; cur_last <= 1'b0; cur_bank <= 1'b0;
            pend_f0_0 <= 0; pend_f0_1 <= 0; pend_k_0 <= 0; pend_k_1 <= 0;
            run_n <= 32'd1; run_ndump <= 32'd0; run_f0 <= {FW{1'b0}};
        end else begin
            if (o_valid) begin
                k_exp <= o_k + 12'd1;
                if (o_k == 12'd4095) fout <= fout + 1'b1;
            end
            if (fs) begin
                cur_act   <= d_act;
                cur_first <= d_idx_is0;
                cur_last  <= d_act && d_idx_last;
                cur_bank  <= d_k[0];
                cur_k     <= d_k;
                cur_idx   <= d_idx;
                if (d_newrun) begin sched <= 1'b0; acc_on <= 1'b1; end
                if (d_stop)   acc_on <= 1'b0;
                if (d_act && d_idx_is0) begin
                    if (d_k[0]) begin pend_f0_1 <= fout; pend_k_1 <= d_k; end
                    else        begin pend_f0_0 <= fout; pend_k_0 <= d_k; end
                end
            end
            if (cmd_run) begin
                sched <= 1'b1; acc_on <= 1'b0; cur_act <= 1'b0;
                run_n <= r_nacc; run_ndump <= r_ndump; run_f0 <= fin + 2;
            end
            if (run_q) run_f0 <= run_f0 + g_add;                // proj017: 格子へ（F0 = (⌊fin / M⌋ + 2)·M）
            if (cmd_stop) begin sched <= 1'b0; acc_on <= 1'b0; cur_act <= 1'b0; end
        end
    end

    // =====================================================================
    // データ経路: タグ {valid, act, first, last, bank, k[11:0]}
    // =====================================================================
    localparam integer TW = 17;
    localparam integer S_RD = 2, S_SUM = 5;
    reg [TW-1:0] tag [0:S_SUM];
    integer ti;
    always @(posedge clk) begin
        if (rst) for (ti = 0; ti <= S_SUM; ti = ti + 1) tag[ti] <= {TW{1'b0}};
        else begin
            tag[0] <= {o_valid, o_valid && t_act, t_first, t_last, t_bank, o_k};
            for (ti = 1; ti <= S_SUM; ti = ti + 1) tag[ti] <= tag[ti-1];
        end
    end
    `define WV(t)  tag[t][16]
    `define WA(t)  tag[t][15]
    `define WF(t)  tag[t][14]
    `define WL(t)  tag[t][13]
    `define WB(t)  tag[t][12]
    `define WK(t)  tag[t][11:0]

    reg signed [YW-1:0] y_re, y_im;          // S0
    always @(posedge clk) begin
        y_re <= m_td[YW-1:0];
        y_im <= m_td[32 +: YW];
    end
    localparam signed [YW-1:0] QMAX =  (1 <<< (QW-1)) - 1;
    localparam signed [YW-1:0] QMIN = -(1 <<< (QW-1));
    function [QW:0] sat;
        input signed [YW-1:0] z;
        input [3:0]           sh;
        reg   signed [YW-1:0] t;
        begin
            t = z >>> sh;
            if (t > QMAX)      sat = {1'b1, QMAX[QW-1:0]};
            else if (t < QMIN) sat = {1'b1, QMIN[QW-1:0]};
            else               sat = {1'b0, t[QW-1:0]};
        end
    endfunction
    reg signed [QW-1:0] q_re, q_im;           // S1
    reg                 q_sat;
    reg [QW:0] sr, si;
    // rev3: SHIFT をここで受け直す（`-1` の群 W: win_core の r_shift から 64 本へ配る配線が長かった）。SHIFT は RUN の外で
    //   書く静的な設定なので、1 クロック遅れて効くだけで中身は同じ
    (* max_fanout = 16 *) reg [3:0] sh_q = 4'd0;
    always @(posedge clk) sh_q <= r_shift;
    always @(posedge clk) begin
        sr = sat(y_re, sh_q);
        si = sat(y_im, sh_q);
        q_re <= sr[QW-1:0]; q_im <= si[QW-1:0]; q_sat <= sr[QW] | si[QW];
    end
    reg signed [QW-1:0]   a_re, a_im;         // S2
    reg                   a_sat;
    reg signed [2*QW-1:0] m_re, m_im;         // S3
    reg                   m_sat;
    reg [PW-1:0]          pwr;                // S4
    reg                   p_sat;
    always @(posedge clk) begin
        a_re <= q_re; a_im <= q_im; a_sat <= q_sat;
        m_re <= a_re * a_re; m_im <= a_im * a_im; m_sat <= a_sat;
        pwr  <= m_re + m_im; p_sat <= m_sat;
    end

    // 二面の積分メモリ（面ごとに 4096 × 64 bit）
    wire [63:0] acc_rd [0:1];
    genvar bk;
    generate
        for (bk = 0; bk < 2; bk = bk + 1) begin : g_bank
            reg [63:0] mem [0:NF-1];
            integer mi;
            initial for (mi = 0; mi < NF; mi = mi + 1) mem[mi] = 64'd0;   // 初期値 0（BRAM の初期化。sim で X を出さないため）
            reg [63:0] rd1, rd2;
            reg [11:0] wa_;
            reg [63:0] wd;
            reg        we;
            wire rmw = `WV(S_RD) && `WA(S_RD) && !`WF(S_RD) && (`WB(S_RD) == bk);
            always @(posedge clk) begin
                rd1 <= mem[rmw ? `WK(S_RD) : rd_ch];
                rd2 <= rd1;
                if (we) mem[wa_] <= wd;
            end
            assign acc_rd[bk] = rd2;
            always @(posedge clk) begin
                we  <= `WV(S_SUM-1) && `WA(S_SUM-1) && (`WB(S_SUM-1) == bk);
                wa_ <= `WK(S_SUM-1);
`ifdef WSPEC_POSCTL
                // 陽性対照: 初回のフレームでも読み値に足す（前のダンプの残りが混ざる）
                wd  <= rd2 + {27'd0, pwr};
`else
                wd  <= `WF(S_SUM-1) ? {27'd0, pwr} : rd2 + {27'd0, pwr};
`endif
            end
        end
    endgenerate
    assign rd_data = acc_rd[rd_bk];

    // ---- ダンプの閉じ（S5 の最後の ch）----
    reg [31:0] sat_run;
    reg        s5_sat;
    always @(posedge clk) s5_sat <= p_sat;     // S5 に揃える
    wire commit = `WV(S_SUM) && `WA(S_SUM) && `WL(S_SUM) && (`WK(S_SUM) == 12'd4095);
    always @(posedge clk) begin
        if (rst) begin
            seq <= 0; rd_k <= 0; rd_n <= 0; rd_sat <= 0; sat_run <= 0;
            rd_f0 <= {FW{1'b1}}; rd_bank <= 1'b0;
        end else begin
            if (`WV(S_SUM) && `WA(S_SUM)) begin
                if (`WF(S_SUM) && `WK(S_SUM) == 12'd0) sat_run <= {31'd0, s5_sat};
                else                                   sat_run <= sat_run + {31'd0, s5_sat};
            end
            if (commit) begin
                seq     <= seq + 1;
                rd_bank <= `WB(S_SUM);
                rd_sat  <= sat_run + {31'd0, s5_sat};
                rd_n    <= n_eff;
                rd_f0   <= `WB(S_SUM) ? pend_f0_1 : pend_f0_0;
                rd_k    <= `WB(S_SUM) ? pend_k_1  : pend_k_0;
            end
        end
    end

    // ---- proj016: ダンプの時刻と健全性（入力側で区切り、commit で渡す）----
    dstamp #(.FW(FW)) u_ds (.clk(clk), .rst(rst),
        .fstart(z_valid && (wa == 12'd0)), .fin(fin), .cmd_run(cmd_run), .cmd_stop(cmd_stop),
        .f0_adj_v(run_q), .f0_adj(g_add),
        .r_nacc(r_nacc), .r_ndump(r_ndump), .t_now(t_now), .ev(ev),
        .commit(commit), .commit_k(`WB(S_SUM) ? pend_k_1 : pend_k_0),
        .rd_t(rd_t), .rd_h(rd_h), .run_t(run_t));

    // ---- スナップショットの読み出し ----
    generate
        if (SNAP != 0) begin : g_snap
            reg [2*ZW-1:0] snap_mem [0:2*NF-1];
            reg [2*ZW-1:0] sn1, sn2;
            always @(posedge clk) begin
                if (sn_wen) snap_mem[sn_waddr] <= sn_wdata;
                sn1 <= snap_mem[{sn_bk, sn_a}];
                sn2 <= sn1;
            end
            assign sn_data = sn2;
        end else begin : g_nosnap
            assign sn_data = {2*ZW{1'b0}};
        end
    endgenerate

    // ---- FLAGS ----
    wire [7:0] f_now = {2'd0, pfb_sat, f_v && !s_tready, ev_halt, ev_tu | ev_tm, ovr, o_valid && (o_k != k_exp)};
    always @(posedge clk) begin
        if (rst || cmd_clr) flags <= 8'd0;
        else                flags <= flags | f_now;
    end
endmodule
