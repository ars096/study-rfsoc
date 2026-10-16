// SPDX-License-Identifier: BSD-3-Clause
//
// lane_fft_w の振る舞いモデル（**シミュレーション専用。合成しない**）。proj023 手順 2c-2: sim/lane_fft_model.v（spec_core の 512 点）を
// SAM45-Wide のレーン FFT（2048 点・固定長）に写したもの。spec_core の sim を変えないよう、別の名前（lane_fft_w）・別のファイルにした。
//
// 実機では build.tcl が Xilinx FFT IP を lane_fft_w の名前で生成する（手順 3）。**モデルが守る約束**（IP の設定と対）:
//   - 2048 点・固定長・順変換・unscaled（入力 15 bit を 16 bit に符号拡張、出力 26 bit = 15 + 11）
//   - 自然順で出力し、m_axis_data_tuser[10:0] に XK_INDEX（= k1）を載せる
//   - realtime: 出力側の tready は無い。入力の途切れは data_in_channel_halt を立てるだけ（途切れたときの IP の振る舞いはモデルしていない）
//   - tdata の並び: 入力 {im[31:16], re[15:0]} / 出力 {im[63:32], re[31:0]}（26 bit をバイト境界の 32 bit に符号拡張。PG109 の並び）
// 値は倍精度で計算した DFT を丸めたもの（floor(x + 0.5)）。**IP と bit 単位では一致しない**。自作部分の bit 単位の照合は、
// このモデルの出力を記録して sim/check_wide.py の模型に通す（A2）ので、ここが IP と一致している必要はない。
// レイテンシは LAT クロック（IP の値とは違ってよい。wide_core はフレーム番号で対応を取る）。

`timescale 1ns / 1ps

module lane_fft_w #(
    parameter integer LAT = 900,
    parameter integer READY_DELAY = 5
)(
    input  wire        aclk,
    input  wire        aresetn,
    input  wire [7:0]  s_axis_config_tdata,
    input  wire        s_axis_config_tvalid,
    output wire        s_axis_config_tready,
    input  wire [31:0] s_axis_data_tdata,
    input  wire        s_axis_data_tvalid,
    output reg         s_axis_data_tready,
    input  wire        s_axis_data_tlast,
    output reg  [63:0] m_axis_data_tdata,
    output reg  [15:0] m_axis_data_tuser,
    output reg         m_axis_data_tvalid,
    output reg         m_axis_data_tlast,
    output wire        event_frame_started,
    output reg         event_tlast_unexpected,
    output reg         event_tlast_missing,
    output reg         event_data_in_channel_halt
);
    localparam integer M = 2048;
    localparam integer LM = 11;
    localparam integer QF = 16;             // 出力待ちのフレーム数の上限
    real PI;
    real ct [0:M-1];
    real st [0:M-1];
    integer i;
    initial begin
        PI = 3.14159265358979323846;
        for (i = 0; i < M; i = i + 1) begin
            ct[i] = $cos(2.0 * PI * i / M);
            st[i] = $sin(2.0 * PI * i / M);
        end
    end

    assign s_axis_config_tready = 1'b1;
    // frame_started はフレームの最初のサンプルを受けた次のクロックに 1 回（rev3 の診断用）
    reg ev_fs_r;
    assign event_frame_started = ev_fs_r;
`ifdef TLAST_SKEW
    localparam integer SKEW = `TLAST_SKEW;   // **TLAST の検査の数えだけ**を SKEW サンプルずらす（診断の陽性対照）
`else
    localparam integer SKEW = 0;
`endif

`ifdef FFT_READY_DELAY
    localparam integer RD = `FFT_READY_DELAY;   // proj023 4b: リセットの後に tready を上げるまでのクロック（実機の「IP が受けない」の模型。陽性対照）
`else
    localparam integer RD = READY_DELAY;
`endif
    reg signed [15:0] xin [0:M-1];
    integer cnt, rdy_cnt, started;
    integer n_acc, stall_st;    // 受けたビートの通算・FFT_STALL_AT の状態（0 まだ / 1 下げている / 2 済み）
    integer slip;               // rev5: 入力の途切れ 1 クロックごとに、TLAST の検査の数えだけが 1 進む（realtime の IP の振る舞いの模型）
    integer q_re [0:QF*M-1];
    integer q_im [0:QF*M-1];
    integer q_w, q_r;           // 書いたサンプル数 / 出したサンプル数（通算）
    integer lat_cnt;
    reg [31:0] t_re, t_im, t_k;

    // 基数 2 の FFT（倍精度）。素直な DFT（512²）では vvp が遅すぎる
    real fr_ [0:M-1];
    real fi_ [0:M-1];
    task compute_frame;
        integer k, n, r, b, len, half, s, t, tw;
        real ur, ui, vr, vi, wr, wi;
        begin
            for (n = 0; n < M; n = n + 1) begin
                r = 0;
                for (b = 0; b < LM; b = b + 1) r = r | (((n >> b) & 1) << (LM - 1 - b));
                fr_[r] = xin[n];
                fi_[r] = 0.0;
            end
            len = 2;
            while (len <= M) begin
                half = len / 2;
                for (s = 0; s < M; s = s + len) begin
                    for (t = 0; t < half; t = t + 1) begin
                        tw = t * (M / len);
                        wr = ct[tw]; wi = -st[tw];
                        ur = fr_[s + t];        ui = fi_[s + t];
                        vr = fr_[s + t + half] * wr - fi_[s + t + half] * wi;
                        vi = fr_[s + t + half] * wi + fi_[s + t + half] * wr;
                        fr_[s + t]        = ur + vr;  fi_[s + t]        = ui + vi;
                        fr_[s + t + half] = ur - vr;  fi_[s + t + half] = ui - vi;
                    end
                end
                len = len * 2;
            end
            for (k = 0; k < M; k = k + 1) begin
                q_re[(q_w + k) % (QF*M)] = $rtoi($floor(fr_[k] + 0.5));
                q_im[(q_w + k) % (QF*M)] = $rtoi($floor(fi_[k] + 0.5));
            end
            q_w = q_w + M;
        end
    endtask

    always @(posedge aclk) begin
        event_tlast_unexpected     <= 1'b0;
        event_tlast_missing        <= 1'b0;
        event_data_in_channel_halt <= 1'b0;
        ev_fs_r                    <= 1'b0;
        if (!aresetn) begin
            cnt = 0; rdy_cnt = 0; started = 0; n_acc = 0; stall_st = 0; q_w = 0; q_r = 0; lat_cnt = 0; slip = 0;
            s_axis_data_tready <= 1'b0;
            m_axis_data_tvalid <= 1'b0;
            m_axis_data_tlast  <= 1'b0;
            m_axis_data_tdata  <= 64'd0;
            m_axis_data_tuser  <= 16'd0;
        end else begin
            // ---- 入力 ----
            if (rdy_cnt < RD) rdy_cnt = rdy_cnt + 1;
            else if (stall_st != 1)    s_axis_data_tready <= 1'b1;
            if (s_axis_data_tvalid && s_axis_data_tready) begin
                started = 1;
                n_acc = n_acc + 1;
                xin[cnt] = s_axis_data_tdata[15:0];
                if (cnt == 0) ev_fs_r <= 1'b1;
                // 検査は (cnt + SKEW) mod M で行う。**枠（cnt）は変えない** — 実機の見立てと同じ形
                if (s_axis_data_tlast && ((cnt + SKEW + slip) % M) != M-1) event_tlast_unexpected <= 1'b1;
                if (!s_axis_data_tlast && ((cnt + SKEW + slip) % M) == M-1) event_tlast_missing   <= 1'b1;
                if (cnt == M-1) begin
                    cnt = 0;
                    compute_frame;
                end else begin
                    cnt = cnt + 1;
                end
            end else if (started && s_axis_data_tready) begin
                event_data_in_channel_halt <= 1'b1;
                slip = slip + 1;         // 実機の realtime の IP: 待たずに進み、制御側の数えだけがずれる（データの枠はずれない）
            end
`ifdef FFT_STALL_AT
            // proj023 4b 実機 5 回目: realtime の IP は最初の入力の近くで 1 回 tready を下げる（proj011・proj014 の実機）。
            // 受けたビートが通算 FFT_STALL_AT 個になった次のクロックだけ tready を 0 にする（陽性対照: 待ち行列の無い RTL は 0x30 で落ちる）
            if (stall_st == 1) begin s_axis_data_tready <= 1'b1; stall_st = 2; end
            else if (stall_st == 0 && n_acc == `FFT_STALL_AT) begin s_axis_data_tready <= 1'b0; stall_st = 1; end
`endif
            // ---- 出力（最初のフレームが揃ってから LAT 待つ）----
            if (q_w > 0 && lat_cnt < LAT) lat_cnt = lat_cnt + 1;
            if (lat_cnt >= LAT && q_r < q_w) begin
                t_re = q_re[q_r % (QF*M)];
                t_im = q_im[q_r % (QF*M)];
                t_k  = q_r % M;
                m_axis_data_tvalid <= 1'b1;
                m_axis_data_tdata  <= {t_im[31:0], t_re[31:0]};
                m_axis_data_tuser  <= {5'd0, t_k[10:0]};
                m_axis_data_tlast  <= (q_r % M) == M-1;
                q_r = q_r + 1;
            end else begin
                m_axis_data_tvalid <= 1'b0;
                m_axis_data_tlast  <= 1'b0;
            end
        end
    end
endmodule
