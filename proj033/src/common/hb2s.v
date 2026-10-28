// SPDX-License-Identifier: BSD-3-Clause
//
// hb2s — hb2（半帯域 ÷2、複素）の時分割版。**値は hb2 と bit 単位で同じ**（同じ項・同じ係数の整数の和。足す順だけが違い、和は厳密）
//
//   y[q] = Σ_i h[2i] · e[q + i] + h[2L − 1] · o[q + L − 1]、前置加算で項は L + 1 個 / 成分（hb2 の冒頭）
//
// hb2 は L + 1 個の乗算を並列に持つ。hb2s は乗算 M 個を C クロック使い回す（M = ceil((L + 1) / C)）:
//   出力が揃った組で、前置加算した L + 1 項と係数を「項の列」に取り込み、毎クロック先頭の M 項を掛けて足し、列を M 項ずつ送る。
//   C クロック後に丸め（>>> SH、+2^(SH−1)）・飽和 W bit（hb2 と同じ）。
// **前提: 組の間隔が C クロック以上**（ddc_core の light の j 段目は、組が 2^(j−1) クロックに 1 回以下しか来ない。
//   pfb_core は 1 クロックに 1 組まで、各段は 1 組で 1 サンプル、pair2 は 2 サンプルで 1 組なので、構造で決まる）。
//   前提が破れたら（最後のクロックより前に次の出力が揃ったら）ovr を 1 クロック立て、**前の計算を打ち切って**次を始める
//   （値は壊れる。ovr を見張る）。組の間隔がちょうど C なら、最後のクロックと次の取り込みが重なり、間に合う
// 組の間隔は自由（in_v が来たときだけ進む）。レイテンシは hb2 より長い（取り込み 1 ＋ C ＋ 丸め 2）。
//
// 資源: 乗算 2M（複素）。L = 4（light）なら C 2 → M 3・C 4 → M 2・C ≧ 5 → M 1

`timescale 1ns / 1ps

module hb2s #(
    parameter integer N  = 15,
    parameter integer SH = 17,
    parameter [18*N-1:0] H = 0,
    parameter integer W  = 24,
    parameter integer C  = 2
)(
    input  wire                clk,
    input  wire                rst,
    input  wire                in_v,
    input  wire signed [W-1:0] e_re, e_im, o_re, o_im,
    output reg                 out_v,
    output reg  signed [W-1:0] y_re, y_im,
    output reg                 sat,
    output reg                 ovr
);
    localparam integer L  = (N + 1) / 4;
    localparam integer T  = L + 1;              // 項の数 / 成分
    localparam integer M  = (T + C - 1) / C;    // 乗算の数 / 成分
    localparam integer NT = M * C;              // 項の列の長さ（端は 0 で埋める）
    localparam integer PW = W + 1 + 18 + 6;

    function signed [17:0] hc(input integer j);
        hc = H[j*18 +: 18];
    endfunction
    // 項 t の係数: t < L は h[2t]（前置加算の対）、t = L は中心 h[2L − 1]、それより後ろは 0
    function signed [17:0] tc(input integer t);
        tc = (t < L) ? hc(2 * t) : (t == L) ? hc(2 * L - 1) : 18'sd0;
    endfunction

    // ---- 履歴（hb2 と同じ）----
    reg signed [W-1:0] ehr [0:2*L-1], ehi [0:2*L-1];
    reg signed [W-1:0] ohr [0:L],     ohi [0:L];
    reg [7:0]          ncnt;
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
            v1 <= (ncnt == 2 * L - 1);
        end
    end

    // ---- 項の列: v1 で取り込み、毎クロック M 項ずつ送る ----
    reg signed [W:0]   tr [0:NT-1], ti [0:NT-1];
    reg signed [17:0]  tk [0:NT-1];
    reg [7:0]          left;                     // 残りのクロック（0 = 休み）
    reg                first;                    // この出力の最初のクロック（和を 0 から）
    always @(posedge clk) begin
        ovr <= 1'b0;
        if (rst) begin
            left <= 8'd0;
        end else if (v1) begin
            ovr <= (left > 8'd1);                 // left = 1 はこのクロックで最後の M 項を掛けている（間に合う）
            for (i = 0; i < NT; i = i + 1) begin
                if (i < L) begin
                    tr[i] <= ehr[2*L-1-i] + ehr[i];
                    ti[i] <= ehi[2*L-1-i] + ehi[i];
                end else if (i == L) begin
                    tr[i] <= ohr[L];
                    ti[i] <= ohi[L];
                end else begin
                    tr[i] <= 0;  ti[i] <= 0;
                end
                tk[i] <= tc(i);
            end
            left <= C;
        end else if (left != 8'd0) begin
            for (i = 0; i < NT; i = i + 1) begin
                if (i + M < NT) begin tr[i] <= tr[i+M]; ti[i] <= ti[i+M]; tk[i] <= tk[i+M]; end
                else begin tr[i] <= 0; ti[i] <= 0; tk[i] <= 0; end
            end
            left <= left - 8'd1;
        end
    end

    // ---- 積（先頭の M 項）→ 和（C クロックぶん）----
    wire busy = (left != 8'd0);                // このクロックの列の先頭 M 項は有効（v1 と重なっても、掛けるのは取り込む前の列）
    reg signed [W+18:0] mr [0:M-1], mi [0:M-1];
    reg                 mv, mfirst, mlast;
    always @(posedge clk) begin
        for (i = 0; i < M; i = i + 1) begin
            mr[i] <= tr[i] * tk[i];
            mi[i] <= ti[i] * tk[i];
        end
        mv     <= busy & ~rst;
        mfirst <= busy & (left == C);
        mlast  <= busy & (left == 8'd1);
    end
    reg signed [PW-1:0] acr, aci, sr, si;
    reg signed [PW-1:0] ar, ai;                  // 途中（ブロッキング）
    reg                 v4;
    always @(posedge clk) begin
        v4 <= 1'b0;
        if (rst) begin
            acr <= 0; aci <= 0;
        end else if (mv) begin
            ar = mfirst ? 0 : acr;  ai = mfirst ? 0 : aci;
            for (i = 0; i < M; i = i + 1) begin ar = ar + mr[i]; ai = ai + mi[i]; end
            acr <= ar;  aci <= ai;
            if (mlast) begin sr <= ar; si <= ai; v4 <= 1'b1; end
        end
    end

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
