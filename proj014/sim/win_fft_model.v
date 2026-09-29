// SPDX-License-Identifier: BSD-3-Clause
//
// win_fft の振る舞いモデル（**シミュレーション専用。合成しない**）。proj013 の lane_fft_model.v の型
//
// 実機では build.tcl が Xilinx FFT IP を win_fft の名前で生成する（複素 4096 点・順変換・unscaled・自然順・XK_INDEX・realtime、
// 入力 18 bit、tools/ip_survey.tcl の win4096_res_lut と同じ設定）。モデルが守る約束:
//   - tdata の並び: 入力 {im[47:24], re[23:0]}（18 bit を 24 bit に符号拡張）/ 出力 {im[63:32], re[31:0]}（31 bit を 32 bit に）
//   - m_axis_data_tuser[11:0] = XK_INDEX。フレームは受けた順に、1 ch / クロックで途切れなく出る
//   - 値は倍精度の DFT を丸めたもの。**IP と bit 単位では一致しない**（IP は内部で係数を丸める）。
//     下流（電力・積分）の bit 単位の照合は、このモデルの出力を記録して sim/check_wspec.py の模型に通す
//   - 入力の途切れ（フレームの途中の tvalid = 0）は data_in_channel_halt を立てる（wspec_core は溜めから途切れなく流すので起きないはず）
`timescale 1ns / 1ps
module win_fft #(
    parameter integer LAT = 200
)(
    input  wire        aclk,
    input  wire        aresetn,
    input  wire [7:0]  s_axis_config_tdata,
    input  wire        s_axis_config_tvalid,
    output wire        s_axis_config_tready,
    input  wire [47:0] s_axis_data_tdata,
    input  wire        s_axis_data_tvalid,
    output wire        s_axis_data_tready,
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
    localparam integer M = 4096;
    localparam integer QF = 8;
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
    assign s_axis_data_tready   = 1'b1;
    assign event_frame_started  = 1'b0;

    real xr [0:M-1];
    real xi [0:M-1];
    real fr_ [0:M-1];
    real fi_ [0:M-1];
    integer q_re [0:QF*M-1];
    integer q_im [0:QF*M-1];
    integer cnt, q_w, q_r, lat_cnt, busy;

    task compute_frame;
        integer k, n, r, b, len, half, s, t, tw;
        real ur, ui, vr, vi, wr, wi;
        begin
            for (n = 0; n < M; n = n + 1) begin
                r = 0;
                for (b = 0; b < 12; b = b + 1) r = r | (((n >> b) & 1) << (11 - b));
                fr_[r] = xr[n];
                fi_[r] = xi[n];
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

    reg signed [23:0] ir, ii;
    reg [11:0] kk;
    always @(posedge aclk) begin
        event_tlast_unexpected <= 1'b0;
        event_tlast_missing <= 1'b0;
        event_data_in_channel_halt <= 1'b0;
        m_axis_data_tvalid <= 1'b0;
        m_axis_data_tlast  <= 1'b0;
        if (!aresetn) begin
            cnt = 0; q_w = 0; q_r = 0; lat_cnt = 0;
        end else begin
            if (s_axis_data_tvalid) begin
                ir = s_axis_data_tdata[23:0];
                ii = s_axis_data_tdata[47:24];
                xr[cnt] = ir; xi[cnt] = ii;
                if (s_axis_data_tlast && cnt != M - 1) event_tlast_unexpected <= 1'b1;
                if (!s_axis_data_tlast && cnt == M - 1) event_tlast_missing <= 1'b1;
                if (cnt == M - 1) begin cnt = 0; compute_frame; end
                else cnt = cnt + 1;
            end else if (cnt != 0) begin
                event_data_in_channel_halt <= 1'b1;
            end
            // 出力: 最初のフレームだけ LAT クロック待ち、以後は溜まっている限り 1 ch / クロックで途切れなく
            if (q_w > q_r) begin
                if (lat_cnt < LAT) lat_cnt = lat_cnt + 1;
                else begin
                    kk = q_r % M;
                    m_axis_data_tdata  <= {q_im[q_r % (QF*M)][31:0], q_re[q_r % (QF*M)][31:0]};
                    m_axis_data_tuser  <= {4'd0, kk};
                    m_axis_data_tvalid <= 1'b1;
                    m_axis_data_tlast  <= (kk == M - 1);
                    q_r = q_r + 1;
                end
            end
        end
    end
endmodule
