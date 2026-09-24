// SPDX-License-Identifier: BSD-3-Clause
//
// lane_fft の振る舞いモデル（**シミュレーション専用。合成しない**）
//
// 実機では build.tcl が Xilinx FFT IP を lane_fft の名前で生成する。iverilog には IP が無いので、
// 同じポートを持ち、同じ約束で動くモデルをここに置く。**モデルが守る約束**（IP の設定と対）:
//   - 512 点・順変換・unscaled（出力 24 bit = 14 + 9 + 1）
//   - 自然順で出力し、m_axis_data_tuser[8:0] に XK_INDEX（= k1）を載せる
//   - realtime（proj011）: 出力側の tready は無い（IP と同じ）。入力の途切れは data_in_channel_halt を立てるだけで、
//     **途切れたときの IP の振る舞い（待つか、待たずに進むか）はモデルしていない**（spec_core は途切れを FLAGS で捕まえる）。
//     フレームは受けた順に出る
//   - tdata の並び: 入力 {im[31:16], re[15:0]}（re は 14 bit を 16 bit に符号拡張）/
//                   出力 {im[47:24], re[23:0]}
// 値は倍精度で計算した DFT を丸めたもの。**IP と bit 単位では一致しない**（IP は内部で
// 係数を量子化する）。自作部分の bit 単位の照合は、このモデルの出力を記録して
// sim/check.py の模型に通すので、ここが IP と一致している必要はない。
//
// レイテンシは LAT クロック（フレームが揃ってから最初の出力まで）。IP の値とは違ってよい
// — spec_core はレイテンシに依存しない作りになっている（フレーム番号で対応を取る）。

`timescale 1ns / 1ps

module lane_fft #(
    parameter integer LAT = 300,
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
    output reg  [47:0] m_axis_data_tdata,
    output reg  [15:0] m_axis_data_tuser,
    output reg         m_axis_data_tvalid,
    output reg         m_axis_data_tlast,
    output wire        event_frame_started,
    output reg         event_tlast_unexpected,
    output reg         event_tlast_missing,
    output reg         event_data_in_channel_halt
);
    localparam integer M = 512;
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
    assign event_frame_started  = 1'b0;

    reg signed [15:0] xin [0:M-1];
    integer cnt, rdy_cnt, started;
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
                for (b = 0; b < 9; b = b + 1) r = r | (((n >> b) & 1) << (8 - b));
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
        if (!aresetn) begin
            cnt = 0; rdy_cnt = 0; started = 0; q_w = 0; q_r = 0; lat_cnt = 0;
            s_axis_data_tready <= 1'b0;
            m_axis_data_tvalid <= 1'b0;
            m_axis_data_tlast  <= 1'b0;
            m_axis_data_tdata  <= 48'd0;
            m_axis_data_tuser  <= 16'd0;
        end else begin
            // ---- 入力 ----
            if (rdy_cnt < READY_DELAY) rdy_cnt = rdy_cnt + 1;
            else                       s_axis_data_tready <= 1'b1;
            if (s_axis_data_tvalid && s_axis_data_tready) begin
                started = 1;
                xin[cnt] = s_axis_data_tdata[15:0];
                if (s_axis_data_tlast && cnt != M-1) event_tlast_unexpected <= 1'b1;
                if (!s_axis_data_tlast && cnt == M-1) event_tlast_missing   <= 1'b1;
                if (cnt == M-1) begin
                    cnt = 0;
                    compute_frame;
                end else begin
                    cnt = cnt + 1;
                end
            end else if (started && s_axis_data_tready) begin
                event_data_in_channel_halt <= 1'b1;
            end
            // ---- 出力（最初のフレームが揃ってから LAT 待つ）----
            if (q_w > 0 && lat_cnt < LAT) lat_cnt = lat_cnt + 1;
            if (lat_cnt >= LAT && q_r < q_w) begin
                t_re = q_re[q_r % (QF*M)];
                t_im = q_im[q_r % (QF*M)];
                t_k  = q_r % M;
                m_axis_data_tvalid <= 1'b1;
                m_axis_data_tdata  <= {t_im[23:0], t_re[23:0]};
                m_axis_data_tuser  <= {7'd0, t_k[8:0]};
                m_axis_data_tlast  <= (q_r % M) == M-1;
                q_r = q_r + 1;
            end else begin
                m_axis_data_tvalid <= 1'b0;
                m_axis_data_tlast  <= 1'b0;
            end
        end
    end
endmodule
