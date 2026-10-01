// SPDX-License-Identifier: BSD-3-Clause
//
// hb2 — 半帯域フィルタで ÷2（複素）。入力は 1 回に 2 サンプルの組（偶 e[n] = x[2n]、奇 o[n] = x[2n+1]）
//
//   y[q] = Σ_j h[j] · x[2q + j]（j = 0..N−1、N = 4L − 1）          ← model/win_fixed.py の fir_decim_int と同じ添字
// 半帯域なので 0 でない係数は偶数番目 j = 2i（i = 0..2L−1）と中心 j = 2L − 1 だけ:
//   y[q] = Σ_i h[2i] · e[q + i] + h[2L − 1] · o[q + L − 1]
// 対称 h[2i] = h[2(2L − 1 − i)] なので前置加算で乗算は L + 1 個 / 成分。
// **最初の出力 q = 0 は組 n = 2L − 1 が来たとき**（x[0..N−1] が揃ったとき）。rst の後の最初の組を n = 0 とする。
//
// 段: 組を受ける（履歴）→ 前置加算 → 積 → 2 項ずつの和の木（ceil(log2(L + 1)) + 1 段。rev2）→ 丸め（>>> SH、+2^(SH−1)）・飽和 W bit
// **組の間隔は自由**（in_v が来たときだけ進む）。出力の間隔は入力の組の間隔と同じ。
//
// 資源: 乗算 2(L + 1)（複素）を並列に持つ（1 組 / クロックまで受けられる）。
// 2 段目より後ろは組が 2 クロックに 1 回以下なので時分割で半分にできる（後で。値は変わらない）

`timescale 1ns / 1ps

module hb2 #(
    parameter integer N  = 15,
    parameter integer SH = 17,
    parameter [18*N-1:0] H = 0,
    parameter integer W  = 24
)(
    input  wire                clk,
    input  wire                rst,
    input  wire                in_v,
    input  wire signed [W-1:0] e_re, e_im, o_re, o_im,
    output reg                 out_v,
    output reg  signed [W-1:0] y_re, y_im,
    output reg                 sat
);
    localparam integer L  = (N + 1) / 4;
    localparam integer PW = W + 1 + 18 + 6;     // 前置加算 1 bit、係数 18 bit、和の余裕

    function signed [17:0] hc(input integer j);
        hc = H[j*18 +: 18];
    endfunction

    // 履歴: eh[0] = e[n]（今の組）… eh[2L−1] = e[n − 2L + 1]、oh[0] = o[n] … oh[L] = o[n − L]
    reg signed [W-1:0] ehr [0:2*L-1], ehi [0:2*L-1];
    reg signed [W-1:0] ohr [0:L],     ohi [0:L];
    reg [7:0]          ncnt;                    // 組の数（2L − 1 で止める）
    reg                v1;
    integer i;
    always @(posedge clk) begin
        v1 <= 1'b0;
        if (rst) begin
            ncnt <= 8'd0;
        end else if (in_v) begin
            ehr[0] <= e_re;  ehi[0] <= e_im;
            ohr[0] <= o_re;  ohi[0] <= o_im;
            for (i = 1; i < 2 * L; i = i + 1) begin ehr[i] <= ehr[i-1]; ehi[i] <= ehi[i-1]; end
            for (i = 1; i <= L; i = i + 1)    begin ohr[i] <= ohr[i-1]; ohi[i] <= ohi[i-1]; end
            if (ncnt != 2 * L - 1) ncnt <= ncnt + 8'd1;
            v1 <= (ncnt == 2 * L - 1);           // この組で q ≧ 0 の出力が揃う
        end
    end

    // q = n − (2L − 1): e[q + i] = eh[2L − 1 − i]、o[q + L − 1] = oh[L]
    // 前置加算: pa_i = e[q + i] + e[q + 2L − 1 − i] = eh[2L − 1 − i] + eh[i]（i = 0..L−1）
    reg signed [W:0]    par [0:L-1], pai [0:L-1];
    reg signed [W-1:0]  cr, ci;
    reg                 v2;
    always @(posedge clk) begin
        for (i = 0; i < L; i = i + 1) begin
            par[i] <= ehr[2*L-1-i] + ehr[i];
            pai[i] <= ehi[2*L-1-i] + ehi[i];
        end
        cr <= ohr[L];  ci <= ohi[L];
        v2 <= v1;
    end

    reg signed [W+18:0] mr [0:L], mi [0:L];
    reg                 v3;
    always @(posedge clk) begin
        for (i = 0; i < L; i = i + 1) begin
            mr[i] <= par[i] * hc(2 * i);
            mi[i] <= pai[i] * hc(2 * i);
        end
        mr[L] <= cr * hc(2 * L - 1);
        mi[L] <= ci * hc(2 * L - 1);
        v3 <= v2;
    end

    // 和: 2 項ずつの木（1 段ごとにレジスタ）。rev2（proj015）: proj014 の「4 項ずつの部分和 → その和（5 項）」は、final（18 項 × 43 bit）で
    // `-1` の最悪経路の群のひとつになった（DSP の出口 → 4 項の加算 / 5 項の加算、CARRY8 が 7〜9 段）。18 → 9 → 5 → 3 → 2 → 1 の 5 段。
    // 整数の和なので値は変わらない（足す順が違うだけ）
    localparam integer T  = L + 1;
    function integer clog2(input integer n);
        integer v; begin v = n - 1; clog2 = 0; while (v > 0) begin v = v >> 1; clog2 = clog2 + 1; end end
    endfunction
    localparam integer NLV = (T > 1) ? clog2(T) : 1;
    function integer cnt_at(input integer lv);       // 段 lv の項の数
        integer c, k; begin c = T; for (k = 0; k < lv; k = k + 1) c = (c + 1) / 2; cnt_at = c; end
    endfunction
    reg signed [PW-1:0] tr [0:(NLV+1)*T-1], ti [0:(NLV+1)*T-1];
    reg [NLV:0]         tv;
    integer lv, n;
    always @(posedge clk) begin
        for (n = 0; n < T; n = n + 1) begin tr[n] <= mr[n]; ti[n] <= mi[n]; end
        for (lv = 0; lv < NLV; lv = lv + 1)
            for (n = 0; n < T; n = n + 1)
                if (2 * n + 1 < cnt_at(lv)) begin
                    tr[(lv+1)*T + n] <= tr[lv*T + 2*n] + tr[lv*T + 2*n + 1];
                    ti[(lv+1)*T + n] <= ti[lv*T + 2*n] + ti[lv*T + 2*n + 1];
                end else if (2 * n < cnt_at(lv)) begin
                    tr[(lv+1)*T + n] <= tr[lv*T + 2*n];
                    ti[(lv+1)*T + n] <= ti[lv*T + 2*n];
                end
        tv <= {tv[NLV-1:0], v3};
    end
    wire signed [PW-1:0] sr = tr[NLV*T];
    wire signed [PW-1:0] si = ti[NLV*T];
    wire                 v4 = tv[NLV];

    wire signed [PW-1:0] rr = (sr + (1 <<< (SH - 1))) >>> SH;
    wire signed [PW-1:0] ri = (si + (1 <<< (SH - 1))) >>> SH;
    localparam signed [PW-1:0] MX = (1 <<< (W - 1)) - 1;
    localparam signed [PW-1:0] MN = -(1 <<< (W - 1));
    always @(posedge clk) begin
        y_re  <= (rr > MX) ? MX[W-1:0] : (rr < MN) ? MN[W-1:0] : rr[W-1:0];
        y_im  <= (ri > MX) ? MX[W-1:0] : (ri < MN) ? MN[W-1:0] : ri[W-1:0];
        sat   <= v4 & ((rr > MX) | (rr < MN) | (ri > MX) | (ri < MN));
        out_v <= v4 & ~rst;
    end
endmodule
