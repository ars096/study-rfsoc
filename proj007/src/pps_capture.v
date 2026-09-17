// SPDX-License-Identifier: BSD-3-Clause
//
// pps_capture — 1PPS の受信とサンプルカウンタ（proj007）
//
// 役割は 3 つ。
//
//   1. **時刻の実体を作る。** AXIS ドメイン（153.6 MHz）で 64 bit のビートカウンタを
//      自走させる。1 ビート = 8 サンプル = 6.5104 ns で、**1 秒 = 153,600,000 ビート
//      ちょうど**（fs = 1,228,800,000 が整数だから成立する）
//
//   2. **PPS にタイムスタンプを打つ。** 基板の PPS 入力は 1 本の SMA から
//      コンパレータ出力（IRIG_COMP_OUT）とシュミットトリガ出力（IRIG_TRIG_OUT）の
//      2 系統が PL へ出ている。**両方に独立のタイムスタンプとグリッチ計数を持たせる。**
//      片方だけを見ていると、波形の汚れと回路の遅延を区別できない
//
//   3. **予約時刻で発火する。** `beat_count == start_at` で 1 クロックの `trig` を出し、
//      capture_gate を起動する。**PPS を直接トリガにしない。**
//      PPS は start_at を決める基準点であって、毎秒叩く信号ではない
//      （毎秒叩くと、ケーブル長差とコンパレータ遅延が毎回データの時刻に乗る）。
//
// **`pps_interval` がそのまま周波数確度の測定器になる。**
// 期待値は 153,600,000 ビートちょうど。100 秒ぶん積めば 0.065 ppb まで見える
// （proj004 の CW によるサブビン補間は 15 ppb が限界だった）。
// proj004 で踏んだ「基準が切れても PLLLockStatus は 2 のまま 90 ppm ずれる」は、
// これを観測中ずっと走らせておけば恒久的に検出できる。
//
// ---- 乗り換えについて ----
// `start_at` と `ctrl` は ctrl_aclk（pl_clk0）から来る。同期器を通していないのは
// capture_gate の `n_beats` と同じ理由で、**ソフトが値を書き終えてから arm / snap を
// 立てる**（データ＋ハンドシェイク）。1 bit のハンドシェイク側は 3 段の同期器を通る。
// **report_cdc は必ず CDC-1 (Critical) を出す。** ソフト側の手順は Vivado からは
// 見えないので、これは構造上避けられない。

`timescale 1ns / 1ps

module pps_capture #(
    // 1 秒あたりのビート数。fs / SPW = 1228.8e6 / 8。
    parameter integer BEATS_PER_SEC = 153600000,
    // これより短い間隔で来たエッジはグリッチとして捨てる（既定 0.5 秒）
    parameter integer BLANK_BEATS   = 76800000,
    // これより長く来なければ「PPS が無い」とする（既定 1.5 秒）
    parameter integer MISS_BEATS    = 230400000
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_RESET aresetn" *)
    input  wire        aclk,          // AXIS ドメイン 153.6 MHz
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire        aresetn,
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 ctrl_aclk CLK" *)
    input  wire        ctrl_aclk,     // PS の pl_clk0（制御系）

    // ---- 基板の PPS 入力（非同期。パッド直結）----
    input  wire        pps_trig_i,    // IRIG_TRIG_OUT (AH13) シュミットトリガ側
    input  wire        pps_comp_i,    // IRIG_COMP_OUT (AJ13) コンパレータ直結側

    // ---- AXI GPIO gpio_time_ctrl ----
    input  wire [31:0] start_at,      // ch1 出力: 発火するビート（下位 32 bit）
    input  wire [31:0] ctrl,          // ch2 出力: [0] snap / [4:1] sel / [5] pps_pol
    // ---- AXI GPIO gpio_time_stat ----
    output reg  [31:0] rdata,         // ch1 入力: sel で選んだ語
    output reg  [31:0] flags,         // ch2 入力: 状態ビット

    // ---- capture_gate との接続（すべて aclk ドメイン）----
    input  wire        arm_pulse,     // arm の立ち上がり（同期済み・1 クロック）
    input  wire        trig_mode,     // 0 = 即時 / 1 = 予約時刻
    input  wire        started,       // キャプチャが実際に始まった（1 クロック）
    output wire        trig           // 予約時刻に達した（1 クロック）
);

    // ---- 識別子。GPIO の配線が正しいかを実機で 1 回で確かめるため ----
    localparam [31:0] MAGIC = 32'h0007_0001;   // proj007 / rev 1

    // ---- 制御ビット ----
    wire        snap_i   = ctrl[0];
    wire [3:0]  sel      = ctrl[4:1];
    wire        pol_i    = ctrl[5];
    // ctrl[31:6] は予約

    // ================================================================ aclk 側

    // 極性と trig_mode は静定した 1 bit なので 2 段で足りる。
    (* ASYNC_REG = "TRUE" *) reg [1:0] pol_s  = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0] mode_s = 2'b00;
    always @(posedge aclk) begin
        pol_s  <= {pol_s[0],  pol_i};
        mode_s <= {mode_s[0], trig_mode};
    end
    wire pol  = pol_s[1];
    wire mode = mode_s[1];

    // ---- PPS のエッジ検出 ----
    // **極性を同期器の手前で吸収する。** pol は静定しているので、ここで XOR しても
    // 準安定の段数は減らない。3 段（proj006 で ASYNC_REG を付けたのと同じ構成）。
    (* ASYNC_REG = "TRUE" *) reg [2:0] tsync;
    (* ASYNC_REG = "TRUE" *) reg [2:0] csync;
    always @(posedge aclk) begin
        if (!aresetn) begin
            tsync <= 3'b000;
            csync <= 3'b000;
        end else begin
            tsync <= {tsync[1:0], pps_trig_i ^ pol};
            csync <= {csync[1:0], pps_comp_i ^ pol};
        end
    end
    wire t_edge = tsync[1] & ~tsync[2];
    wire c_edge = csync[1] & ~csync[2];

    // ---- ビートカウンタ（時刻の実体）----
    // **aresetn 以外では止めないし戻さない。** Overlay のロードが時刻の原点になる。
    reg [63:0] beat_count;
    always @(posedge aclk) begin
        if (!aresetn) beat_count <= 64'd0;
        else          beat_count <= beat_count + 64'd1;
    end
    wire [31:0] beat_lo = beat_count[31:0];

    // ---- タイムスタンプ（TRIG 経路 / COMP 経路で同じ構造を 2 組）----
    reg [31:0] t_age,   c_age;      // 直前の採用エッジからのビート数（飽和）
    reg [63:0] t_stamp, c_stamp;
    reg [31:0] t_count, t_interval;
    reg [15:0] t_glitch, c_glitch;

    wire t_ok = (t_age >= BLANK_BEATS);
    wire c_ok = (c_age >= BLANK_BEATS);
    wire t_accept = t_edge &  t_ok;
    wire c_accept = c_edge &  c_ok;

    always @(posedge aclk) begin
        if (!aresetn) begin
            t_age <= MISS_BEATS; c_age <= MISS_BEATS;
            t_stamp <= 64'd0;    c_stamp <= 64'd0;
            t_count <= 32'd0;    t_interval <= 32'd0;
            t_glitch <= 16'd0;   c_glitch <= 16'd0;
        end else begin
            // 年齢カウンタ。**飽和させる。**巻き戻すと alive の判定が壊れる
            if (t_accept)                t_age <= 32'd0;
            else if (t_age < MISS_BEATS) t_age <= t_age + 32'd1;
            if (c_accept)                c_age <= 32'd0;
            else if (c_age < MISS_BEATS) c_age <= c_age + 32'd1;

            if (t_accept) begin
                t_stamp    <= beat_count;
                // **間隔はスタンプの差で取る。**年齢カウンタから作ると 1 ずれる
                t_interval <= beat_lo - t_stamp[31:0];
                t_count    <= t_count + 32'd1;
            end
            if (c_accept) c_stamp <= beat_count;

            // グリッチ = ブランキング窓の中に来たエッジ。**飽和させる**
            if (t_edge && !t_ok && (t_glitch != 16'hFFFF)) t_glitch <= t_glitch + 16'd1;
            if (c_edge && !c_ok && (c_glitch != 16'hFFFF)) c_glitch <= c_glitch + 16'd1;
        end
    end

    wire t_alive = (t_age < MISS_BEATS);
    wire c_alive = (c_age < MISS_BEATS);

    // ---- 予約時刻での発火 ----
    //
    // **一致検出は 2 段に分ける。** 153.6 MHz は 6.51 ns しかなく、proj006 の
    // WNS は +0.588 ns しか余裕が無い。32 bit の一致比較を 1 段で作らない。
    //
    //   hi_eq は「**次の** beat_count の上位 16 bit が target と一致するか」を
    //   1 クロック前に登録しておく。次のクロックでは beat_count がその値に
    //   なっているので、hi_eq は現在の beat_count に対する正しい比較結果になる。
    //   これなら target[15:0] が 0 のとき（上位が桁上がりする瞬間）も破綻しない。
    //
    // **発火は target = start_at - 1 で行う。** trig の 1 クロック後に
    // capture_gate の running が立つので、**実際に取り始めるビートが
    // ちょうど start_at になる**。t_start と start_at が一致することが判定条件。
    reg        pending;
    reg        late_r;
    reg [31:0] target;
    reg        hi_eq;

    wire [31:0] beat_nxt = beat_lo + 32'd1;
    wire signed [31:0] margin = start_at - beat_lo;   // 2 の補数の差（巻き戻り込み）

    always @(posedge aclk) begin
        if (!aresetn) begin
            pending <= 1'b0;
            late_r  <= 1'b0;
            target  <= 32'd0;
            hi_eq   <= 1'b0;
        end else begin
            hi_eq <= (beat_nxt[31:16] == target[31:16]);

            if (arm_pulse) begin
                if (!mode) begin
                    // 即時モード。予約は使わない
                    pending <= 1'b0;
                    late_r  <= 1'b0;
                end else if (margin < 32'sd16) begin
                    // **ソフトが間に合わなかった。** ここで late を立てておかないと
                    // 「2^32 ビート待つ」という止まり方になり、原因が遠くなる
                    pending <= 1'b0;
                    late_r  <= 1'b1;
                end else begin
                    pending <= 1'b1;
                    late_r  <= 1'b0;
                    target  <= start_at - 32'd1;
                end
            end else if (trig) begin
                pending <= 1'b0;
            end
        end
    end

    assign trig = pending & hi_eq & (beat_lo[15:0] == target[15:0]);

    // ---- キャプチャが始まったビート ----
    reg [63:0] t_start;
    always @(posedge aclk) begin
        if (!aresetn)     t_start <= 64'd0;
        else if (started) t_start <= beat_count;
    end

    // ---- スナップショット ----
    // **64 bit を 32 bit で 2 回読むと桁が裂ける。** snap の立ち上がりで全部を
    // 影レジスタへ写し、あとはゆっくり読む。写し終わったことは snap_ack で返す
    // （待ち時間で誤魔化さない。壊れたときに気づける形にする）。
    (* ASYNC_REG = "TRUE" *) reg [2:0] snap_s;
    always @(posedge aclk) begin
        if (!aresetn) snap_s <= 3'b000;
        else          snap_s <= {snap_s[1:0], snap_i};
    end
    wire snap_rise = snap_s[1] & ~snap_s[2];

    reg        snap_done;
    reg [63:0] s_beat, s_stamp, s_tstart;
    reg [31:0] s_count, s_interval, s_cstamp, s_glitch;
    always @(posedge aclk) begin
        if (!aresetn) begin
            snap_done <= 1'b0;
        end else if (snap_rise) begin
            s_beat     <= beat_count;
            s_stamp    <= t_stamp;
            s_tstart   <= t_start;
            s_count    <= t_count;
            s_interval <= t_interval;
            s_cstamp   <= c_stamp[31:0];
            s_glitch   <= {c_glitch, t_glitch};
            snap_done  <= 1'b1;
        end else if (!snap_s[1]) begin
            snap_done  <= 1'b0;      // snap を落とせば ack も落ちる
        end
    end

    // ============================================================ ctrl_aclk 側

    // 影レジスタは snap と snap_ack の間でしか変わらないので、ここは静定した値を
    // 読んでいる（データ＋ハンドシェイク）。1 段だけ登録して終点を定める。
    always @(posedge ctrl_aclk) begin
        case (sel)
            4'd0:  rdata <= s_beat[31:0];
            4'd1:  rdata <= s_beat[63:32];
            4'd2:  rdata <= s_stamp[31:0];
            4'd3:  rdata <= s_stamp[63:32];
            4'd4:  rdata <= s_count;
            4'd5:  rdata <= s_interval;
            4'd6:  rdata <= s_tstart[31:0];
            4'd7:  rdata <= s_tstart[63:32];
            4'd8:  rdata <= s_cstamp;
            4'd9:  rdata <= s_glitch;
            4'd15: rdata <= MAGIC;
            // **未使用の sel はそれと分かる値を返す。** 0 を返すと
            // 「配線が死んでいる」と区別がつかない
            default: rdata <= {28'hBAD0000, sel};
        endcase
    end

    (* ASYNC_REG = "TRUE" *) reg [1:0] f_alive  = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0] f_late   = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0] f_arm    = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0] f_ack    = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0] f_calive = 2'b00;
    always @(posedge ctrl_aclk) begin
        f_alive  <= {f_alive[0],  t_alive};
        f_late   <= {f_late[0],   late_r};
        f_arm    <= {f_arm[0],    pending};
        f_ack    <= {f_ack[0],    snap_done};
        f_calive <= {f_calive[0], c_alive};
        flags    <= {27'd0, f_calive[1], f_ack[1], f_arm[1], f_late[1], f_alive[1]};
    end

endmodule
