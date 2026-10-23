// SPDX-License-Identifier: BSD-3-Clause
//
// lane_fft_g24 の振る舞いモデル（**シミュレーション専用。合成しない**）。proj025 手順 2a: proj024（proj024-m0）の sim/lane_fft_g21_model.v
// （16384 点・bit 反転順。proj023 の lane_fft_w_model.v を写したもの）を、2G-2 のレーン FFT（**8192 点**・固定長・bit 反転順）に縮めたもの。
//
// 実機では build.tcl が Xilinx FFT IP を lane_fft_g24 の名前で生成する（手順 2f）。**モデルが守る約束**（IP の設定と対。S-1・S-2 の設定）:
//   - 8192 点・固定長・順変換・unscaled（入力 15 bit を 16 bit に符号拡張、出力 28 bit = 15 + 13 を 32 bit に符号拡張）
//   - **bit 反転順で出力**し、m_axis_data_tuser[12:0] に XK_INDEX（= そのサンプルの本当の k1。出る順は 0, 4096, 2048, …）を載せる
//   - realtime・TLAST の検査・入力の途切れ（halt）・リセットの後の tready の遅れ・FFT_STALL_AT（流し始めの 1 回の tready の下げ）は lane_fft_w_model と同じ
// 値は倍精度で計算した DFT を丸めたもの（floor(x + 0.5)）。**IP と bit 単位では一致しない**（自作部分の照合は、この出力を記録して模型に通す。Wide と同じ）。
// 出力待ちのフレーム数 QF は 4（proj024 の lane_fft_g21_model と同じ。lane_fft_w_model は 16）。
`timescale 1ns / 1ps

module lane_fft_g24 #(
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
    localparam integer M = 8192;
    localparam integer LM = 13;
    localparam integer QF = 4;              // 出力待ちのフレーム数の上限（lane_fft_w_model は 16）
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
    integer kb, fb, bb;                     // bit 反転順の出力: kb = フレームの中の出す順番の bit 反転、fb = そのフレームの頭

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
                kb = 0;
                for (bb = 0; bb < LM; bb = bb + 1) kb = kb | ((((q_r % M) >> bb) & 1) << (LM - 1 - bb));
                fb = q_r - (q_r % M);
                t_re = q_re[(fb + kb) % (QF*M)];
                t_im = q_im[(fb + kb) % (QF*M)];
                t_k  = kb;
                m_axis_data_tvalid <= 1'b1;
                m_axis_data_tdata  <= {t_im[31:0], t_re[31:0]};
                m_axis_data_tuser  <= {3'd0, t_k[12:0]};
                m_axis_data_tlast  <= (q_r % M) == M-1;
                q_r = q_r + 1;
            end else begin
                m_axis_data_tvalid <= 1'b0;
                m_axis_data_tlast  <= 1'b0;
            end
        end
    end
endmodule
