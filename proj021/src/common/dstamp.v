// SPDX-License-Identifier: BSD-3-Clause
//
// dstamp — ダンプごとの時刻（開始のビート）と健全性の語（proj016）
//
// wspec_core（窓）と spec_core（全帯域）の中に 1 個ずつ置く。**入力側でダンプの区切りを数え、出力側の commit で渡す。**
//
// ---- 何を貼るか ----
//   ts（64 bit）: ダンプ k の最初のフレームの最初のサンプルがコアに入ったクロックの t_now（time_core のビート。
//                 コアの中の t_now は time_core のカウンタと同じ値になるよう、段数を time_core の側で先に足してある）
//   h（16 bit）  : ダンプ k の入力が入っていた間（最初のフレームの頭 〜 次のダンプの頭）に ev のどれかが 1 だったか（OR）
//                 ＋ [15] H_OPEN（commit の時点でその区切りがまだ閉じていない）/ [14] H_LOST（記憶が次の周回に上書きされた）
//   **ダンプ k の時刻 = ts(k)、長さ = N × L（L = フレーム長）。ts(k) − ts(0) = k·N·L が PS の照合**（窓では z の出方の揺れで ± 数クロック）
//
// ---- 区切りの数え方（spec_core / wspec_core のスナップショットの予約と同じ約束）----
//   RUN（cmd_run）の時点の fin を f として、最初のダンプはフレーム F0 = f + 2。以後 N フレームごと。N_DUMP（≠ 0）個で止める。
//   **F0 の判定は fin の下位 8 bit の一致だけ**で行う（F0 は RUN から 2 フレーム先なので、256 フレームの周回と取り違えない）。
//   proj017: wspec_core は RUN の次のクロックに F0 を時刻の格子へ寄せる（f0_adj_v・f0_adj、足す量 ≦ 254）。
//   F0 は RUN の fin から ≦ 256 フレーム先で、下位 8 bit の一致は F0 で初めて起きる（取り違えない）。spec_core は f0_adj_v = 0
//   2 個目以降は「ダンプの中のフレームの番号 fc が N − 1 だったか」をレジスタに置いておき（lastq）、次のフレームの頭で読む。
//   フレームは 512 クロック以上あるので、lastq はいつも間に合う（48 bit の比べを頭のクロックに置かない。`-1` の余裕のため）。
//   N_DUMP 個目のダンプも、次のフレームの頭で閉じる（入力は止まらないので、必ず来る）。
//
// ---- 記憶（DEPTH 個の輪）----
//   ダンプ k は輪の k mod DEPTH に置き、commit（出力側）で k mod DEPTH を読む。**入力から commit までの遅れが
//   (DEPTH − 1) ダンプを越えると上書きされる**（H_LOST）。N = 1 の 256 MHz 窓（フレーム 4096 クロック）で遅れ ≒ 2 フレーム、
//   全帯域（512 クロック）で ≒ 3 フレームなので DEPTH = 8 にした（sim で H_LOST = 0 を確かめる）。

`timescale 1ns / 1ps

module dstamp #(
    parameter integer FW    = 48,
    parameter integer DL2   = 3,          // 輪の深さ = 2^DL2
    parameter integer EVW   = 8
)(
    input  wire           clk,
    input  wire           rst,
    // 入力側
    input  wire           fstart,       // フレームの最初のサンプルを受けたクロック（1 クロック）
    input  wire [FW-1:0]  fin,          // そのフレームの番号（fstart のクロックの値）／ cmd_run のクロックの値
    input  wire           cmd_run,
    input  wire           cmd_stop,
    input  wire           f0_adj_v,     // proj017: F0 に f0_adj を足す（RUN の次のクロック。wspec_core の時刻の格子）
    input  wire [7:0]     f0_adj,
    input  wire [31:0]    r_nacc,       // RUN の時点で取り込む（0 は 1）
    input  wire [31:0]    r_ndump,
    input  wire [63:0]    t_now,
    input  wire [EVW-1:0] ev,           // 1 = 異常（毎クロック。レベルでもパルスでもよい）
    // 出力側
    input  wire           commit,       // ダンプが閉じた（1 クロック）
    input  wire [31:0]    commit_k,     // そのダンプの RUN の中の番号
    output reg  [63:0]    rd_t,
    output reg  [15:0]    rd_h,
    output reg  [63:0]    run_t         // RUN（cmd_run）を受けたクロックの t_now
);
    localparam integer D = 1 << DL2;
    reg  [7:0]     f0lo;
    reg            arm, on, lastq;
    reg  [31:0]    k, fc, nm1, nd;
    reg  [EVW-1:0] acc;
    reg  [63:0]    ts  [0:D-1];
    reg  [EVW-1:0] hs  [0:D-1];
    reg  [31:0]    tag [0:D-1];      // その場所に今いるダンプの番号（H_LOST の判定）
    reg  [D-1:0]   hv;               // 閉じた
    wire [31:0]    km1 = k - 32'd1;
    wire [DL2-1:0] sk   = k[DL2-1:0];
    wire [DL2-1:0] skm1 = km1[DL2-1:0];
    wire           begin0 = fstart && arm && (fin[7:0] == f0lo);
    wire           bnd    = fstart && on && lastq;            // 前のフレームがダンプの最後だった
    reg            klast;                                      // (N_DUMP ≠ 0) かつ k = N_DUMP（k が変わるのはフレームの頭だけなので、次の頭に間に合う）
    wire           done   = bnd && klast;
    wire           begin_ = begin0 || (bnd && !done);
    integer i;
    always @(posedge clk) begin
        if (rst) begin
            arm <= 1'b0; on <= 1'b0; lastq <= 1'b0; k <= 32'd0; fc <= 32'd0; nm1 <= 32'd0; nd <= 32'd0;
            f0lo <= 8'd0; acc <= {EVW{1'b0}}; hv <= {D{1'b0}}; run_t <= 64'd0; klast <= 1'b0;
            for (i = 0; i < D; i = i + 1) begin ts[i] <= 64'd0; hs[i] <= {EVW{1'b0}}; tag[i] <= 32'hFFFF_FFFF; end
        end else begin
            acc <= acc | ev;
            lastq <= (fc == nm1);
            klast <= (nd != 32'd0) && (k == nd);
            if (bnd) begin                       // ダンプ k − 1 を閉じる
                hs[skm1] <= acc | ev;
                hv[skm1] <= 1'b1;
            end
            if (begin_) begin                    // ダンプ k を始める
`ifdef DSTAMP_POSCTL
                ts[sk]  <= t_now + 64'd1;            // 陽性対照: 1 ビートずらす（S-T2 が落ちること）
`else
                ts[sk]  <= t_now;
`endif
                tag[sk] <= k;
                hv[sk]  <= 1'b0;
                acc     <= ev;
                k       <= k + 32'd1;
                fc      <= 32'd0;
            end else if (fstart && on) begin
                fc <= fc + 32'd1;
            end
            if (begin0) begin arm <= 1'b0; on <= 1'b1; end
            if (done)   on <= 1'b0;
            // コマンドは最後（同じクロックのフレームの頭より優先）
            if (cmd_run) begin
                arm <= 1'b1; on <= 1'b0; k <= 32'd0;
                f0lo <= fin[7:0] + 8'd2;
                nm1 <= (r_nacc == 32'd0) ? 32'd0 : r_nacc - 32'd1;
                nd <= r_ndump;
                run_t <= t_now;
            end
            if (f0_adj_v) f0lo <= f0lo + f0_adj;
            if (cmd_stop) begin arm <= 1'b0; on <= 1'b0; end
        end
    end
    // 出力側
    wire [DL2-1:0] sc = commit_k[DL2-1:0];
    always @(posedge clk) begin
        if (rst) begin
            rd_t <= 64'd0; rd_h <= 16'd0;
        end else if (commit) begin
            rd_t <= ts[sc];
            rd_h <= {!hv[sc], tag[sc] != commit_k, {(14-EVW){1'b0}}, hs[sc]};
        end
    end
endmodule
