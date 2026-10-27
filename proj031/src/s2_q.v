// SPDX-License-Identifier: BSD-3-Clause
//
// s2_q — (B) の均し（proj030 P-3）: s2_chain の出口（そろった拍に行 r の q 16 個）を待ち行列に積み、1 拍に 1 行ずつ電力にして積分器（g24_acc）へ渡す
//
// 1 項目 = そろった行 r の q 16 個（k2 = 0..15）。出口は 1 項目から:
//   1 行目: 行 r の銀行 b = k2 b（b = 0..7）
//   2 行目: 行 4096 − r の銀行 b = k2 15 − b（共役の側。r = 0・2048 は 2 行目なし）
// 1 フレーム 4,096 拍で 4,096 行を出すので**出口の余裕は 0**。項目があるのに出さない拍を作らない（先読み 6 段で途切れなく出す）。
// 記憶に残る項目の最大は模型で 513（README の M-2b の後）。書きから出口まで 4 拍かかるので、sim では全体が 515 になった（P-3 の 1 回目、
// 先読み 3 段で記憶がちょうど 512 で満ちた）→ **先読みを 6 段**にして、記憶の山を 509 に下げた（余裕 3）。
//   記憶: q（576 bit）は BRAM（512 × 576 = RAMB36 8）、行 r・2 行目の有無・飽和の印（29 bit）は LUTRAM
// 電力: p = q_re² + q_im²（37 bit、段は a → m → p）。出口は g24_acc の口（p・p_v・p_k1）と同じ
//
// ovf（粘着、clr で消す）: 記憶が満ちているのに積もうとした（その項目は捨てる）
// dmax: 記憶 ＋ 先読み ＋ 読みの途中の項目の数の最大（sim の見張り。フレームを重ねても増えないこと）。cmax: 記憶の項目の数の最大
//
// -DQ_BUBBLE: 先読みを 1 段にする。陽性対照（項目があるのに出さない拍ができ、dmax がフレームごとに増えてあふれるはず）

`timescale 1ns / 1ps

module s2_q #(
    parameter integer QW = 18,
    parameter integer PW = 37,
    parameter integer AB = 9               // 記憶の番地の bit（512 項目）
)(
    input  wire              clk,
    input  wire              rst,
    input  wire              clr,
    input  wire [16*QW-1:0]  q_re,
    input  wire [16*QW-1:0]  q_im,
    input  wire [15:0]       q_sat,
    input  wire [11:0]       q_k,
    input  wire              q_v,
    output reg  [8*PW-1:0]   p,             // 銀行 b が [PW·b +: PW]
    output reg               p_v,
    output reg  [11:0]       p_k1,          // 行
    output reg  [3:0]        p_sat,
    output reg               ovf,
    output reg  [AB+1:0]     dmax,
    output reg  [AB:0]       cmax
);
    localparam integer QB = 16 * QW;       // 288
    localparam integer DW = 2 * QB;        // 576（BRAM）
    localparam integer SW = 16 + 12 + 1;   // 飽和の印・行・2 行目の有無（LUTRAM）
`ifdef Q_BUBBLE
    localparam integer NS = 1;
`else
    localparam integer NS = 6;
`endif

    // ---- 書き ----
    (* ram_style = "block" *)       reg [DW-1:0] mem_d [0:(1<<AB)-1];
    (* ram_style = "distributed" *) reg [SW-1:0] mem_s [0:(1<<AB)-1];
    reg  [AB:0] wp = 0, rp = 0;
    wire [AB:0] cnt  = wp - rp;
    wire        full = (cnt == (1 << AB));
    wire        two  = (q_k != 12'd0) && (q_k != 12'd2048);
    always @(posedge clk) begin
        if (rst) begin wp <= 0; ovf <= 1'b0; end
        else begin
            if (clr) ovf <= 1'b0;
            if (q_v) begin
                if (full) ovf <= 1'b1;
                else begin
                    mem_d[wp[AB-1:0]] <= {q_im, q_re};
                    mem_s[wp[AB-1:0]] <= {q_sat, q_k, two};
                    wp <= wp + 1'b1;
                end
            end
        end
    end

    // ---- 先読み: 読み（2 段）→ 先読みの段（NS 個）----
    reg  [DW-1:0] rd1, rd2;
    reg  [SW-1:0] rs1, rs2;
    reg           pv1 = 1'b0, pv2 = 1'b0;
    reg  [DW-1:0] sk_d [0:NS-1];
    reg  [SW-1:0] sk_s [0:NS-1];
    reg  [2:0]    sk_n = 3'd0;               // 先読みの段にある項目の数（[0] が先頭）
    wire          pop;                       // 今の拍に先頭を取る
    wire [3:0]    after = sk_n - pop + pv1 + pv2;
    wire          rd_en = (cnt != 0) && (after < NS);
    always @(posedge clk) begin
        if (rst) begin rp <= 0; pv1 <= 1'b0; pv2 <= 1'b0; end
        else begin
            if (rd_en) rp <= rp + 1'b1;
            pv1 <= rd_en;
            pv2 <= pv1;
        end
        rd1 <= mem_d[rp[AB-1:0]];  rs1 <= mem_s[rp[AB-1:0]];
        rd2 <= rd1;                rs2 <= rs1;
    end
    // 先読みの段: 取る（pop）と入る（pv2）を同じ拍に
    integer si;
    always @(posedge clk) begin
        if (rst) sk_n <= 3'd0;
        else begin
            if (pop) for (si = 0; si < NS - 1; si = si + 1) begin sk_d[si] <= sk_d[si+1]; sk_s[si] <= sk_s[si+1]; end
            if (pv2) begin sk_d[sk_n - pop] <= rd2; sk_s[sk_n - pop] <= rs2; end
            sk_n <= sk_n - pop + pv2;
        end
    end

    // ---- 出口: 今の項目（cur）から 1 拍に 1 行 ----
    reg  [DW-1:0] cur_d;
    reg  [SW-1:0] cur_s;
    reg           cur_v = 1'b0, half = 1'b0;
    wire          cur_two = cur_s[0];
    wire          done = !cur_v || half || !cur_two;    // 今の拍で今の項目を出し終える（か、空）
    assign pop = done && (sk_n != 0);
    always @(posedge clk) begin
        if (rst) begin cur_v <= 1'b0; half <= 1'b0; end
        else if (done) begin
            cur_v <= (sk_n != 0);
            half  <= 1'b0;
            if (sk_n != 0) begin cur_d <= sk_d[0]; cur_s <= sk_s[0]; end
        end
        else half <= 1'b1;
    end

    // 1 行の 8 銀行を選ぶ（O0）
    reg [8*QW-1:0] o_re, o_im;
    reg [7:0]      o_sat;
    reg [11:0]     o_k;
    reg            o_v = 1'b0;
    integer b, kk;
    always @(posedge clk) begin
        for (b = 0; b < 8; b = b + 1) begin
            kk = half ? 15 - b : b;
            o_re[QW*b +: QW] <= cur_d[QW*kk +: QW];
            o_im[QW*b +: QW] <= cur_d[QB + QW*kk +: QW];
            o_sat[b]         <= cur_s[13 + kk];
        end
        o_k <= half ? (12'd0 - cur_s[12:1]) : cur_s[12:1];    // 4096 − r（12 bit で巻く）
        o_v <= rst ? 1'b0 : cur_v;
    end

    // ---- 電力 ----
    reg [3:0]  sn, s1, s2;
    reg [11:0] k1, k2;
    reg        v1, v2;
    integer ci;
    always @* begin
        sn = 4'd0;
        for (ci = 0; ci < 8; ci = ci + 1) sn = sn + {3'd0, o_sat[ci]};
    end
    // 段: a（v1）→ m（v2）→ p（p_v）
    always @(posedge clk) begin
        s1 <= sn; s2 <= s1; p_sat <= s2;
        k1 <= o_k; k2 <= k1; p_k1 <= k2;
        if (rst) begin v1 <= 1'b0; v2 <= 1'b0; p_v <= 1'b0; end
        else begin v1 <= o_v; v2 <= v1; p_v <= v2; end
    end
    genvar j;
    generate
        for (j = 0; j < 8; j = j + 1) begin : g_pw
            reg signed [QW-1:0]   a_re, a_im;
            reg signed [2*QW-1:0] m_re, m_im;
            always @(posedge clk) begin
                a_re <= o_re[j*QW +: QW];
                a_im <= o_im[j*QW +: QW];
                m_re <= a_re * a_re;
                m_im <= a_im * a_im;
                p[j*PW +: PW] <= m_re + m_im;
            end
        end
    endgenerate

    // ---- 見張り: 記憶 ＋ 読みの途中 ＋ 先読みの項目の数の最大 ----
    always @(posedge clk) begin
        if (rst || clr) begin dmax <= 0; cmax <= 0; end
        else begin
            if (cnt + pv1 + pv2 + sk_n > dmax) dmax <= cnt + pv1 + pv2 + sk_n;
            if (cnt > cmax) cmax <= cnt;
        end
    end
endmodule
