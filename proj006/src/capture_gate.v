// SPDX-License-Identifier: BSD-3-Clause
//
// capture_gate — AXI4-Stream の有限長スナップショット
//
// proj005 で **ただ一つ書く自作 RTL**。既製 IP で代用できない役割が 2 つある。
//
//   1. **TLAST を作る。** RFDC の AXI4-Stream には TLAST が無い。AXI DMA の S2MM は
//      パケットの終端を TLAST で認識するため、長さだけに頼ると転送の完了条件が
//      DMA の実装依存になる。ここで N ビート目に TLAST を立てて、記録の終端を
//      設計側で確定させる
//
//   2. **記録の連続性を保証する。** 待機中に下流の FIFO へデータを流し込むと、
//      次のキャプチャの先頭が「前回の取りこぼし」で埋まり、記録の途中に
//      位相の飛びが入る。FFT では見かけ上のノイズフロアとして現れ、
//      「ADC が悪いのか経路が悪いのか」が切り分けられなくなる。
//      **待機中は上流を受け取って捨てる**ことで、下流を常に空にしておく
//
// 待機中に s_axis_tready を 1 に保つのは意図的である。上流に backpressure を
// かけると RFDC 側がサンプルを落とすため、ADC のストリームは常に流し続ける。

`timescale 1ns / 1ps

module capture_gate #(
    parameter integer DATA_W = 128
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis:m_axis, ASSOCIATED_RESET aresetn" *)
    input  wire                 aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire                 aresetn,

    // 制御系のクロック（PS の pl_clk0）。status をこちらへ渡すためだけに使う
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 ctrl_aclk CLK" *)
    input  wire                 ctrl_aclk,

    // AXI GPIO と直結する。ビットの割り当てはソフト側と合わせること
    //   ctrl  [23:0] n_beats（キャプチャするビート数） / [31] arm（立ち上がりで起動）
    //   status [0] busy / [1] done（arm でクリアされる）
    input  wire [31:0]          ctrl,
    output wire [31:0]          status,

    input  wire [DATA_W-1:0]    s_axis_tdata,
    input  wire                 s_axis_tvalid,
    output wire                 s_axis_tready,

    output wire [DATA_W-1:0]    m_axis_tdata,
    output wire                 m_axis_tvalid,
    input  wire                 m_axis_tready,
    output wire                 m_axis_tlast
);

    wire [23:0] n_beats = ctrl[23:0];
    wire        arm     = ctrl[31];

    // ---- arm の乗り換え（ctrl_aclk → aclk）と立ち上がり検出 ----
    // n_beats は arm より前にソフトが書き終えており、arm_rise の時点では
    // 十分に静定している。したがってバス自体の同期は取らない（データ＋ハンドシェイク）。
    //
    // **ASYNC_REG は必須。** 無いと同期器の段が離れた場所に置かれうる。
    // 段の間の配線が延びたぶんだけ準安定の収束に使える時間が減り、MTBF が落ちる。
    // 機能は変わらないので気づけない。report_cdc の CDC-2 が唯一の検出手段だった
    // （2026-09-17 に proj006 で指摘され、proj005 から引き継いでいた漏れと判明）。
    (* ASYNC_REG = "TRUE" *)
    reg [2:0] arm_sync;
    always @(posedge aclk) begin
        if (!aresetn) arm_sync <= 3'b000;
        else          arm_sync <= {arm_sync[1:0], arm};
    end
    wire arm_rise = arm_sync[1] & ~arm_sync[2];

    reg [23:0] remain;
    reg        running;
    reg        done_r;

    // 待機中は捨てる / キャプチャ中は下流の tready をそのまま上流へ返す
    assign s_axis_tready = running ? m_axis_tready : 1'b1;
    assign m_axis_tvalid = running & s_axis_tvalid;
    assign m_axis_tdata  = s_axis_tdata;
    assign m_axis_tlast  = running & (remain == 24'd1);

    wire beat = m_axis_tvalid & m_axis_tready;

    always @(posedge aclk) begin
        if (!aresetn) begin
            running <= 1'b0;
            remain  <= 24'd0;
            done_r  <= 1'b0;
        end else if (arm_rise && !running && (n_beats != 24'd0)) begin
            running <= 1'b1;
            remain  <= n_beats;
            done_r  <= 1'b0;
        end else if (running && beat) begin
            if (remain == 24'd1) begin
                running <= 1'b0;
                remain  <= 24'd0;
                done_r  <= 1'b1;
            end else begin
                remain <= remain - 24'd1;
            end
        end
    end

    // ---- status の乗り換え（aclk → ctrl_aclk）----
    // ゆっくり変わる 1 bit の状態なので 2FF で足りる。**ASYNC_REG は上と同じ理由で必須。**
    (* ASYNC_REG = "TRUE" *) reg [1:0] busy_sync = 2'b00;
    (* ASYNC_REG = "TRUE" *) reg [1:0] done_sync = 2'b00;
    always @(posedge ctrl_aclk) begin
        busy_sync <= {busy_sync[0], running};
        done_sync <= {done_sync[0], done_r};
    end

    assign status = {30'd0, done_sync[1], busy_sync[1]};

endmodule
