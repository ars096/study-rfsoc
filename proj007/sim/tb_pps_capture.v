`timescale 1ns/1ps
//
// pps_capture + capture_gate の結合テストベンチ（proj007）
//
// **Vivado もライセンスも要らない。** RTL を触ったらまずこれを通す。
// 1 秒を 1000 ビートに縮めてある（BEATS_PER_SEC = 1000）ので、実機の
// 153,600,000 ビートと同じ構造を数 µs で流せる。
//
// 確かめるもの:
//   1. PPS を受けて pps_count が増え、pps_interval が 1 周期ちょうどになる
//   2. ブランキング窓の中のエッジは **捨てられ、グリッチとして数えられる**
//   3. 予約時刻での発火で **t_start が start_at と完全に一致する**
//   4. 予約が過去なら **late が立ち、キャプチャは始まらない**
//   5. スナップショットが桁の裂けない値を返す（snap_ack のハンドシェイク）
//
// **3 が本題である。** 1 ビートずれる実装は実機でも動いてしまい、
// 「ケーブル長差かソフトの遅れか」と区別がつかなくなる。

module tb;
  localparam integer W     = 128;
  localparam integer BPS   = 1000;   // 「1 秒」= 1000 ビート
  localparam integer BLANK = 500;
  localparam integer MISS  = 1500;

  reg aclk = 0, aresetn = 0, ctrl_aclk = 0;
  always #3.255 aclk      = ~aclk;   // 153.6 MHz
  always #5.000 ctrl_aclk = ~ctrl_aclk;

  // ---- capture_gate 側 ----
  reg  [31:0] gctrl = 0;
  wire [31:0] gstatus;
  reg  [W-1:0] s_tdata = 0;
  reg  s_tvalid = 1;
  wire s_tready;
  wire [W-1:0] m_tdata;
  wire m_tvalid, m_tlast;
  reg  m_tready = 1;

  // ---- pps_capture 側 ----
  reg  [31:0] tctrl = 0;      // [0] snap / [4:1] sel / [5] pol
  reg  [31:0] tstart = 0;
  wire [31:0] trdata, tflags;
  // **自動生成と手動注入を別のレジスタにする。** 1 本の reg を 2 つの手続きブロックから
  // 叩くと後勝ちになり、グリッチ試験が黙って空振りする
  reg  pps_auto = 0, pps_man = 0;
  wire pps_t = pps_auto | pps_man;
  wire pps_c = pps_auto;

  wire trig, trig_mode, arm_pulse, started;

  capture_gate #(.DATA_W(W)) gate (
    .aclk(aclk), .aresetn(aresetn), .ctrl_aclk(ctrl_aclk),
    .ctrl(gctrl), .status(gstatus),
    .trig(trig), .trig_mode_o(trig_mode),
    .arm_pulse(arm_pulse), .started(started),
    .s_axis_tdata(s_tdata), .s_axis_tvalid(s_tvalid), .s_axis_tready(s_tready),
    .m_axis_tdata(m_tdata), .m_axis_tvalid(m_tvalid), .m_axis_tready(m_tready),
    .m_axis_tlast(m_tlast));

  pps_capture #(.BEATS_PER_SEC(BPS), .BLANK_BEATS(BLANK), .MISS_BEATS(MISS)) pps (
    .aclk(aclk), .aresetn(aresetn), .ctrl_aclk(ctrl_aclk),
    .pps_trig_i(pps_t), .pps_comp_i(pps_c),
    .start_at(tstart), .ctrl(tctrl), .rdata(trdata), .flags(tflags),
    .arm_pulse(arm_pulse), .trig_mode(trig_mode), .started(started), .trig(trig));

  always @(posedge aclk) if (aresetn && s_tvalid && s_tready) s_tdata <= s_tdata + 1;

  integer got, lasts, fails;
  always @(posedge aclk) if (aresetn && m_tvalid && m_tready) begin
    got <= got + 1;
    if (m_tlast) lasts <= lasts + 1;
  end

  // ---- 影レジスタの読み出し（実機のソフトと同じ順序）----
  reg [31:0] v;
  task snap_take;
    integer guard;
    begin
      tctrl[0] = 1'b1;
      guard = 0;
      while (!tflags[3] && guard < 200) begin @(posedge ctrl_aclk); guard = guard + 1; end
      if (!tflags[3]) begin $display("  !! FAIL snap_ack が返らない"); fails = fails + 1; end
    end
  endtask
  task snap_release;
    integer guard;
    begin
      tctrl[0] = 1'b0;
      guard = 0;
      while (tflags[3] && guard < 200) begin @(posedge ctrl_aclk); guard = guard + 1; end
    end
  endtask
  task rd(input [3:0] s);
    begin
      tctrl[4:1] = s;
      repeat (4) @(posedge ctrl_aclk);
      v = trdata;
    end
  endtask

  task check(input integer cond, input [1023:0] msg);
    begin if (!cond) begin $display("  !! FAIL %0s", msg); fails = fails + 1; end end
  endtask

  // ---- PPS の生成。幅 100 ビートのパルスを period ビートごとに出す ----
  integer pps_period, pps_left, pps_run;
  integer bcnt;
  initial begin pps_period = 0; pps_run = 0; pps_left = 0; bcnt = 0; end
  always @(posedge aclk) begin
    if (pps_run) begin
      bcnt <= bcnt + 1;
      if (bcnt >= pps_period - 1) begin bcnt <= 0; pps_auto <= 1; pps_left <= 100; end
      else if (pps_left > 0) begin
        pps_left <= pps_left - 1;
        if (pps_left == 1) pps_auto <= 0;
      end
    end
  end

  task pulse_now;        // ブランキングの試験用に 1 発だけ手で出す（TRIG 経路のみ）
    begin
      @(posedge aclk) pps_man = 1;
      repeat (20) @(posedge aclk);
      pps_man = 0;
      repeat (5) @(posedge aclk);
    end
  endtask

  integer stamp, cnt0, cnt1, iv, gl;

  initial begin
    fails = 0; got = 0; lasts = 0;
    repeat (10) @(posedge aclk);
    aresetn = 1;
    repeat (20) @(posedge aclk);

    // ---- 0. 識別子 ----
    snap_take; rd(4'd15); snap_release;
    $display("MAGIC = %08x", v);
    check(v === 32'h0007_0001, "MAGIC が読めない（GPIO の配線かセレクタ）");

    // ---- 1. PPS が無い状態 ----
    check(tflags[0] === 1'b0, "PPS が無いのに alive が立っている");

    // ---- 2. PPS を出す ----
    pps_period = BPS; pps_run = 1;
    repeat (BPS * 3 + 200) @(posedge aclk);
    snap_take; rd(4'd4); cnt0 = v; rd(4'd5); iv = v; rd(4'd2); stamp = v; snap_release;
    $display("PPS  count=%0d interval=%0d stamp=%0d alive=%b", cnt0, iv, stamp, tflags[0]);
    check(cnt0 >= 2,          "PPS が数えられていない");
    check(iv === BPS,         "pps_interval が 1 周期になっていない");
    check(tflags[0] === 1'b1, "PPS が来ているのに alive が立たない");

    // ---- 3. ブランキング窓の中のエッジはグリッチ ----
    snap_take; rd(4'd4); cnt0 = v; rd(4'd9); gl = v & 32'hFFFF; snap_release;
    pulse_now;                                   // 直前の PPS から BLANK 未満
    repeat (50) @(posedge aclk);
    snap_take; rd(4'd4); cnt1 = v; rd(4'd9); v = v & 32'hFFFF; snap_release;
    $display("グリッチ: count %0d -> %0d / glitch %0d -> %0d", cnt0, cnt1, gl, v);
    check(cnt1 === cnt0, "ブランキング窓の中のエッジを採用してしまった");
    check(v === gl + 1,  "グリッチが数えられていない");

    // ---- 4. 予約時刻での発火。**t_start が start_at と一致すること** ----
    got = 0; lasts = 0;
    snap_take; rd(4'd0); v = v; snap_release;
    tstart = v + 300;                            // 300 ビート先
    gctrl  = 32'd8 | 32'h4000_0000;              // n_beats = 8 / trig_mode = 1 / arm = 0
    repeat (10) @(posedge ctrl_aclk);
    gctrl  = 32'd8 | 32'h4000_0000 | 32'h8000_0000;   // arm
    repeat (600) @(posedge aclk);
    snap_take; rd(4'd6); snap_release;
    $display("予約発火: start_at=%0d t_start=%0d got=%0d lasts=%0d late=%b",
             tstart, v, got, lasts, tflags[1]);
    check(v === tstart,      "**t_start が start_at と一致しない**");
    check(got === 8,         "予約発火でビート数が違う");
    check(lasts === 1,       "予約発火で TLAST が 1 回でない");
    check(tflags[1] === 1'b0, "late が立っている");
    gctrl = 0;
    repeat (20) @(posedge ctrl_aclk);

    // ---- 5. 予約が過去なら late。キャプチャは始まらない ----
    got = 0; lasts = 0;
    snap_take; rd(4'd0); snap_release;
    tstart = v - 100;                            // 過去
    gctrl  = 32'd8 | 32'h4000_0000;
    repeat (10) @(posedge ctrl_aclk);
    gctrl  = 32'd8 | 32'h4000_0000 | 32'h8000_0000;
    repeat (800) @(posedge aclk);
    $display("late: got=%0d late=%b armed=%b", got, tflags[1], tflags[2]);
    check(got === 0,          "過去の予約で発火してしまった");
    check(tflags[1] === 1'b1, "**late が立っていない**（2^32 ビート待つ止まり方になる）");
    gctrl = 0;
    repeat (20) @(posedge ctrl_aclk);

    // ---- 6. 即時モードは proj006 と同じであること ----
    got = 0; lasts = 0;
    gctrl = 32'd16;
    repeat (10) @(posedge ctrl_aclk);
    gctrl = 32'd16 | 32'h8000_0000;
    repeat (400) @(posedge aclk);
    $display("即時モード: got=%0d lasts=%0d status=%08x", got, lasts, gstatus);
    check(got === 16,   "即時モードでビート数が違う");
    check(lasts === 1,  "即時モードで TLAST が 1 回でない");
    gctrl = 0;

    if (fails == 0) begin
      $display("=== ALL PASS ===");
      $finish;
    end else begin
      $display("=== FAIL が %0d 件 ===", fails);
      $fatal(1);
    end
  end

  initial begin
    #500000;
    $display("=== TIMEOUT ===");
    $fatal(1);
  end
endmodule
