// SPDX-License-Identifier: BSD-3-Clause
//
// wide_acc — SAM45-Wide の切り出しの積分器（proj023 手順 2c-2）。8 銀行 × 2 面 × 1024 × 64 bit（BRAM36 × 32 / ADC の見込み）
//
// 入力は wide_chain の束ねの出口（1 クロックに銀行 k2 = 0..7 の束ねた ch j = jb + Cb·k2、Cb = 2048 / B）。
// 流れ s の ch i = j − S0_s（0 ≦ i < 4096）だけを積む。i = a + Cb·q（a = i mod Cb、q = ⌊i / Cb⌋）として、記憶の銀行 mb と番地を
//   B 1（Cb 2048）: mb = 2·(2s + q) + (a >> 10)、番地 a & 1023（流れ s は mb 4s .. 4s + 3）
//   B 2（Cb 1024）: mb = 4s + q、番地 a
//   B 4（Cb  512）: mb = q（流れ 0 だけ）、番地 a（0..511）
// に置く（proj022 の M-5 を束ねに広げたもの）。1 クロックに来る束ねた ch は、どの流れも a が同じで q が違う（4096 は Cb の倍数）ので、
// **1 クロックに 1 記憶の銀行 1 書き込み**になる（陽性対照: sim で確かめる）。
// 記憶の銀行 mb が、このクロックの銀行 k2 のどれを受けるか: 流れ s の S0 = Cb·σ + ρ として k2 = q + σ + (jb < ρ)、a = (jb − ρ) mod Cb。
//
// 面: 流れごとに、積んでいる面（tag_plane）と読み出す面（凍った面）がある。記憶の (mb, 面) の読みの口は、積んでいる面なら RMW、
// そうでなければ読み出し（rd_*）に使う。書きは RMW だけ。同じ番地をもう一度 RMW するのは 1 フレーム（2048 クロック）後。
//
// 段: W0 = 入力（束ねの出口）/ W1 = 番地と選択のレジスタ / W2 = 読み 1 / W3 = 読み 2 / W4 = 書き（和）
// 読み出し: rd_s・rd_i を出して 4 クロック後に rd_d（番地のレジスタ → 記憶 → 出力レジスタ → 選択）
// -DACC_POSCTL: B 1 で番地の上の bit を見ずに書く（陽性対照。wr_coll が立ち A2 が落ちるべき）

`timescale 1ns / 1ps

module wide_acc #(
    parameter integer BW = 39
)(
    input  wire              clk,
    input  wire              rst,
    // 設定（今効いている値。WRST の間だけ変わる）
    input  wire [1:0]        lb,
    input  wire [13:0]       s0_0,          // 束ねた ch の単位（0 .. 16384/B − 4096）
    input  wire [13:0]       s0_1,
    input  wire [1:0]        en,            // 流れ s を積むか（B 4 の流れ 1 は 0 = 空の流れ）
    // 束ねの出口
    input  wire [8*BW-1:0]   pb,
    input  wire              pb_v,
    input  wire [10:0]       pb_jb,
    // 流れごとのこのフレームの帳簿（pb と同じクロックで有効）
    input  wire [1:0]        t_act,         // 積む
    input  wire [1:0]        t_first,       // ダンプの最初のフレーム（足さずに書く）
    input  wire [1:0]        t_plane,
    // 読み出し（凍った面）
    input  wire              rd_s,
    input  wire [11:0]       rd_i,
    input  wire [1:0]        rd_plane,      // 流れごとの凍った面
    output reg  [63:0]       rd_d,
    output reg               wr_coll        // 1 クロックに同じ記憶の銀行へ 2 つ以上（起きてはいけない。粘着、rst で消す）
);
    // ---- 記憶の銀行 mb の持ち主（流れ s）・q・hi（B 1 の番地の上の bit）----
    function [3:0] owner;                    // {s, q[2:0]}
        input [1:0] l; input [2:0] mb;
        case (l)
            2'd0:    owner = {mb[2], 1'b0, 1'b0, mb[1]};
            2'd1:    owner = {mb[2], 1'b0, mb[1:0]};
            default: owner = {1'b0, mb};
        endcase
    endfunction

    wire [11:0] cb = (lb == 2'd0) ? 12'd2048 : (lb == 2'd1) ? 12'd1024 : 12'd512;
    // 流れごとの σ・ρ（S0 = Cb·σ + ρ）
    wire [13:0] s0 [0:1];
    assign s0[0] = s0_0;
    assign s0[1] = s0_1;
    reg [3:0]  sig [0:1];
    reg [10:0] rho [0:1];
    integer s;
    always @* begin
        for (s = 0; s < 2; s = s + 1) begin
            sig[s] = s0[s] >> (11 - lb);
            rho[s] = s0[s] & (cb - 1);
        end
    end

    // ---- W1: 記憶の銀行ごとに、受ける k2・番地・書くか ----
    reg [BW-1:0]  w1_d  [0:7];
    reg [9:0]     w1_a  [0:7];
    reg [7:0]     w1_we, w1_first;
    reg [7:0]     w1_pl;
    reg [3:0]     ow;
    reg [10:0]    aa;
    reg [4:0]     k2;
    reg           c;
    reg [3:0]     nw [0:7];
    integer mb, kk;
    always @(posedge clk) begin
        for (mb = 0; mb < 8; mb = mb + 1) begin
            ow = owner(lb, mb[2:0]);
            c  = (pb_jb < rho[ow[3]]);
            aa = (pb_jb - rho[ow[3]]) & (cb - 1);
            k2 = {2'd0, ow[2:0]} + {1'b0, sig[ow[3]]} + {4'd0, c};
            w1_d[mb]     <= pb[BW*k2[2:0] +: BW];
            w1_a[mb]     <= aa[9:0];
`ifdef ACC_POSCTL
            w1_we[mb]    <= pb_v && en[ow[3]] && t_act[ow[3]] && (k2 <= 5'd7);      // 陽性対照: B 1 で番地の上の bit を見ない（2 つの記憶の銀行に同じ ch）
`else
            w1_we[mb]    <= pb_v && en[ow[3]] && t_act[ow[3]] && (k2 <= 5'd7) && ((lb != 2'd0) || (aa[10] == mb[0]));
`endif
            w1_first[mb] <= t_first[ow[3]];
            w1_pl[mb]    <= t_plane[ow[3]];
        end
    end

    // ---- 衝突の見張り: 1 クロックに同じ記憶の銀行に来る束ねた ch の数（k2 ごとに数える。正しければ ≦ 1）----
    //   流れ s の (k2) → mb の逆の対応を数え直すのは重いので、「書く記憶の銀行の数 = 窓に入った束ねた ch の数」で見る
    reg [3:0] n_in, n_we;
    integer t;
    always @* begin
        n_in = 4'd0;
        for (s = 0; s < 2; s = s + 1)
            for (t = 0; t < 8; t = t + 1)
                if (en[s] && t_act[s] && !(s == 1 && lb == 2'd2) &&
                    ({3'd0, pb_jb} + {3'd0, cb} * t >= {1'b0, s0[s]}) && ({3'd0, pb_jb} + {3'd0, cb} * t < {1'b0, s0[s]} + 15'd4096))
                    n_in = n_in + 4'd1;
    end
    reg [3:0] n_in1;
    always @* begin
        n_we = 4'd0;
        for (t = 0; t < 8; t = t + 1) n_we = n_we + {3'd0, w1_we[t]};
    end
    reg v1;
    always @(posedge clk) begin
        v1 <= pb_v; n_in1 <= pb_v ? n_in : 4'd0;
        if (rst) wr_coll <= 1'b0;
        else if (v1 && n_we != n_in1) wr_coll <= 1'b1;
    end

    // ---- 読み出しの番地（流れ rd_s の ch rd_i → mb・番地）----
    reg [2:0]  r_mb;
    reg [9:0]  r_a;
    reg        r_pl;
    reg [2:0]  r_mb1, r_mb2;
    always @(posedge clk) begin
        case (lb)
            2'd0:    begin r_mb <= {rd_s, rd_i[11], rd_i[10]}; r_a <= rd_i[9:0]; end           // q = i[11]、a = i[10:0]
            2'd1:    begin r_mb <= {rd_s, rd_i[11:10]};        r_a <= rd_i[9:0]; end           // q = i[11:10]
            default: begin r_mb <= rd_i[11:9];                 r_a <= {1'b0, rd_i[8:0]}; end   // q = i[11:9]
        endcase
        r_pl  <= rd_plane[(lb == 2'd2) ? 1'b0 : rd_s];
        r_mb1 <= r_mb; r_mb2 <= r_mb1;
    end

    // ---- 記憶（mb × 面）----
    wire [63:0] rdo [0:15];
    genvar g, pl;
    generate
        for (g = 0; g < 8; g = g + 1) begin : g_mb
            for (pl = 0; pl < 2; pl = pl + 1) begin : g_pl
                (* ram_style = "block" *) reg [63:0] mem [0:1023];
                reg [63:0] rd1, rd2;
                reg [9:0]  a2, a3;
                reg        rmw2, rmw3, f2, f3;
                reg [BW-1:0] d2, d3;
                wire       rmw = w1_we[g] && (w1_pl[g] == pl);
                wire [9:0] ra  = rmw ? w1_a[g] : r_a;
                always @(posedge clk) begin
                    rd1 <= mem[ra];
                    rd2 <= rd1;
                    a2 <= w1_a[g]; a3 <= a2;
                    rmw2 <= rmw;   rmw3 <= rmw2;
                    f2 <= w1_first[g]; f3 <= f2;
                    d2 <= w1_d[g]; d3 <= d2;
                    if (rmw3) mem[a3] <= f3 ? {{(64-BW){1'b0}}, d3} : rd2 + {{(64-BW){1'b0}}, d3};
                end
                assign rdo[2*g + pl] = rd2;
            end
        end
    endgenerate
    reg r_pl1, r_pl2;
    always @(posedge clk) begin
        r_pl1 <= r_pl; r_pl2 <= r_pl1;
        rd_d <= rdo[2*r_mb2 + r_pl2];
    end
endmodule
