// SPDX-License-Identifier: BSD-3-Clause
//
// g24_pfb_core — 2G-4 の PFB の本体（T = 4、65536 点 = 1 フレーム 4096 ビート）。proj027 手順 1c
//
// **proj025 の g22_pfb_core（proj024 の g21_pfb_core = wide_pfb.v を機械的に伸ばしたもの、の 2G-2 版）を 2G-4 の長さにしたもの**: m を 12 bit、フレームの最後を 4095、履歴の深さを 4096。
// 式・段・見張りは wide_pfb と同じ（diff で比べられるように、それ以外は変えていない。下の注釈も wide_pfb のまま）:
//   y_r[n] = sat15( round( Σ_{t=0..3} c[t·N + n] · x[(r − 3 + t)·N + n] / 2^16 ) )、N = 65536、n = 16m + p
//   （m = フレームの中のビート 0..4095、p = レーン 0..15。round は (v + 2^15) >>> 16）
//   起動の直後は履歴 0: r − 3 + t < 0 のタップは 0（模型の「0 の履歴」）。
// 係数は g24_pfb（包み）の中の g24_coef から。履歴は 4096 × 672 bit = 2.75 Mbit / ADC（**BRAM**。proj025 2f ビルド 1 で URAM から移したのを引き継いだ。下の 1・2 の注）。
//
// ---- 以下 wide_pfb の注釈 ----
//
// 入力は 1 ビート 16 サンプル（ギアボックスの出口、lane p が [16p +: 16]）。ADC の 16 bit を >>> 2 して 14 bit にする（proj010 以来）。
// s_m はそのビートのフレームの中の番号 m。**コア（wide_core）が time_core の T から作る**（フレームの頭は T ≡ K_F mod 2048、README D-2）。
// rst の後は s_m = 0 のビートから始める（それより前のビートは捨てる）。s_tvalid が落ちたビートは進めない
// （途切れはフレームを壊すので、コアが FLAGS で捕まえる。ここでは数えない）。
//
// ---- 履歴（3 フレーム）----
//   hmem[m] = {h2, h1, h0}（各 16 レーン × 14 bit = 224 bit、計 672 bit）。h0 = x_{r−1}、h1 = x_{r−2}、h2 = x_{r−3}（同じ m・p）。
//   ビート m で hmem[m] を読み、{h1, h0, x_r} を同じ番地に書き戻す（次に同じ番地を読むのは 4096 ビート後。wide_pfb は 2048）。
//   （wide_pfb の注: URAM に置く（2048 × 672 → URAM288 × 10）。2G-2 は BRAM に、下の注）。初期値は要らない（起動の直後は fr でタップを 0 にする）。
//
// ---- 係数（外の wide_coef_rom、4 ADC で共有。proj031: g24_cu、coef_ok が 0 のビートも coef_mis）----
//   coef は「LAT_C = 2 クロック前に入ったビートの m」の係数（ROM の番地は共通の数えで、このコアの s_m と同じ値のはず）。
//   coef_m（ROM が読んだ番地）と自分の m を比べ、違えば coef_mis を立てる（粘着、rst か clr で消す。proj031 rev 2: clr = g24_spec の flags_clr = PS の START）。**共有の食い違いの見張り**
//   （D-6 の「一番危ないところ」。陽性対照: sim で ROM の番地を 1 ずらす）。
//
// ---- 段（入力のクロックを 0）----
//   0: 入力・hmem の読みの番地 / 1: hmem の読み / 2: hmem の出力レジスタ・係数が届く・書き戻し・見張り /
//   3: タップの選択（履歴 0 のマスク）/ 4: 積（18 × 14 → 32 bit）/ 5: 2 つずつの和 / 6: 和（34 bit）/ 7: 丸め・飽和 → y
//   LAT = 7（入力 → y_v）。DSP は 1 タップ 1 個（16 × 4 = 64 / ADC、PCIN の縦続は合成に任せる）

`timescale 1ns / 1ps

module g24_pfb_core #(
    parameter integer XW = 14,
    parameter integer CW = 18,
    parameter integer CF = 16,
    parameter integer YW = 15
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [255:0]      s_tdata,
    input  wire              s_tvalid,
    input  wire [11:0]       s_m,
    input  wire [1151:0]     coef,          // 2 クロック前のビートの係数（wide_coef_rom）
    input  wire [11:0]       coef_m,
    input  wire              coef_ok,       // proj031: 共有の g24_cu の OK（coef と同じ段）。0 のビートも coef_mis に数える
    input  wire              clr,           // proj031 rev 2: coef_mis を消す（flags_clr。食い違いが続いていれば次の拍にまた立つ）
    output reg  [16*YW-1:0]  y,             // レーン p が [YW·p +: YW]
    output reg               y_v,
    output reg  [11:0]       y_m,
    output reg               y_first,       // フレームの最初のビート（y_m = 0）
    output reg  [1:0]        y_fr,          // 起動からのフレームの数（3 で止まる。3 = 履歴が全部埋まった）
    output reg  [15:0]       sat_cnt,       // 飽和した（ビート × レーン）の数。飽和して止まる。rst で 0
    output reg               coef_mis       // 係数の番地が自分の m と違った（粘着）
);
    localparam integer HW = 16 * XW;        // 224
    localparam integer PW = XW + CW;        // 32（積）
    localparam integer AW = PW + 2;         // 34（4 項の和）

    // ---- 0: 入力。rst の後は m = 0 のビートから ----
    reg        go;                          // 始まった
    reg [1:0]  fr;                          // 今のビートのフレームが、起動から何番目か（3 で止まる）
    wire       acc_in = s_tvalid && (go || s_m == 12'd0);
    always @(posedge clk) begin
        if (rst) begin
            go <= 1'b0; fr <= 2'd0;
        end else if (acc_in) begin
            go <= 1'b1;
            if (s_m == 12'd4095 && fr != 2'd3) fr <= fr + 2'd1;
        end
    end

    reg [HW-1:0] x1, x2;
    reg [11:0]   m1, m2;
    reg          v1, v2;
    reg [1:0]    f1, f2;
    integer p;
    always @(posedge clk) begin
        for (p = 0; p < 16; p = p + 1) x1[XW*p +: XW] <= s_tdata[16*p + 2 +: XW];   // >>> 2
        m1 <= s_m; v1 <= acc_in & ~rst;
`ifdef PFB_NOMASK
        f1 <= 2'd3;                         // 陽性対照: 起動の直後も履歴を使う（残りのごみを拾うはず）
`else
        f1 <= fr;
`endif
        x2 <= x1; m2 <= m1; v2 <= v1; f2 <= f1;
    end

    // ---- 1・2: 履歴の読み・書き戻し ----
    // proj025 2f ビルド 1: **BRAM に置く**。URAM で書くと 1 コア 20 個 ＋ 積分器 24 個で、2 コアで 88 個 > 80 個（DRC UTLZ-1 で配置の前に止まった）。
    // 2G-1（コア 1 個）は合成が 1 回の run の中で溢れを見て履歴を BRAM に回したが、2G-2 はコアごとに別の OOC の run なので、run の中では 44 個で収まって見える
    (* ram_style = "block" *) reg [3*HW-1:0] hmem [0:4095];
    reg [3*HW-1:0] hr1, hr2;
    always @(posedge clk) begin
        hr1 <= hmem[s_m];
        hr2 <= hr1;
        if (v2) hmem[m2] <= {hr2[0 +: 2*HW], x2};      // {h1, h0, x_r} → 次のフレームの {h2, h1, h0}
    end

    // ---- 2: 係数の見張り ----
    always @(posedge clk) begin
        if (rst || clr) coef_mis <= 1'b0;
        else if (v2 && (coef_m != m2 || !coef_ok)) coef_mis <= 1'b1;
    end

    // ---- 3: タップの選択。タップ t（0 = いちばん古い x_{r−3}）は fr ≧ 3 − t のときだけ（それ以外は履歴 0）----
    reg signed [XW-1:0] xa [0:63];          // [4p + t]
    reg signed [CW-1:0] ca [0:63];
    reg        v3; reg [11:0] m3; reg [1:0] f3;
    integer t;
    always @(posedge clk) begin
        for (p = 0; p < 16; p = p + 1) begin
            xa[4*p + 3] <= x2[XW*p +: XW];
            xa[4*p + 2] <= (f2 >= 2'd1) ? hr2[0*HW + XW*p +: XW] : {XW{1'b0}};
            xa[4*p + 1] <= (f2 >= 2'd2) ? hr2[1*HW + XW*p +: XW] : {XW{1'b0}};
            xa[4*p + 0] <= (f2 >= 2'd3) ? hr2[2*HW + XW*p +: XW] : {XW{1'b0}};
            for (t = 0; t < 4; t = t + 1) ca[4*p + t] <= coef[72*p + 18*t +: CW];
        end
        v3 <= v2; m3 <= m2; f3 <= f2;
    end

    // ---- 4: 積 / 5: 2 つずつ / 6: 和 ----
    reg signed [PW-1:0] pr [0:63];
    reg signed [PW:0]   s2 [0:31];
    reg signed [AW-1:0] s4 [0:15];
    reg        v4, v5, v6; reg [11:0] m4, m5, m6; reg [1:0] f4, f5, f6;
    always @(posedge clk) begin
        for (p = 0; p < 64; p = p + 1) pr[p] <= ca[p] * xa[p];
        for (p = 0; p < 32; p = p + 1) s2[p] <= pr[2*p] + pr[2*p + 1];
        for (p = 0; p < 16; p = p + 1) s4[p] <= s2[2*p] + s2[2*p + 1];
        v4 <= v3; m4 <= m3; f4 <= f3;
        v5 <= v4; m5 <= m4; f5 <= f4;
        v6 <= v5; m6 <= m5; f6 <= f5;
    end

    // ---- 7: 丸め・飽和 ----
    localparam signed [AW-CF-1:0] YMAX = (1 <<< (YW - 1)) - 1;
    localparam signed [AW-CF-1:0] YMIN = -(1 <<< (YW - 1));
    wire [15:0] sat6;
    wire [16*YW-1:0] y6;
    genvar g;
    generate
        for (g = 0; g < 16; g = g + 1) begin : g_rnd
            wire signed [AW-1:0]    rs = s4[g] + $signed({{(AW-CF){1'b0}}, 1'b1, {(CF-1){1'b0}}});
            wire signed [AW-CF-1:0] rr = rs >>> CF;
            assign sat6[g] = (rr > YMAX) || (rr < YMIN);
            assign y6[YW*g +: YW] = (rr > YMAX) ? YMAX[YW-1:0] : (rr < YMIN) ? YMIN[YW-1:0] : rr[YW-1:0];
        end
    endgenerate
    reg [4:0] ns;
    integer k;
    always @(*) begin
        ns = 5'd0;
        for (k = 0; k < 16; k = k + 1) ns = ns + {4'd0, sat6[k]};
    end
    always @(posedge clk) begin
        y <= y6;
        y_v <= v6 & ~rst; y_m <= m6; y_first <= v6 && m6 == 12'd0; y_fr <= f6;
        if (rst) sat_cnt <= 16'd0;
        else if (v6 && ns != 5'd0) sat_cnt <= (sat_cnt > 16'hFFFF - {11'd0, ns}) ? 16'hFFFF : sat_cnt + {11'd0, ns};
    end
endmodule
