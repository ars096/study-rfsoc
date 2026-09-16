`timescale 1ns/1ps
// capture_gate のテストベンチ。
// m_tready は negedge で動かし、チェッカは posedge で見る（レース回避）。
module tb;
  localparam integer W = 128;
  reg aclk=0, aresetn=0, ctrl_aclk=0;
  always #4.07 aclk = ~aclk;            // 122.88 MHz
  always #5.00 ctrl_aclk = ~ctrl_aclk;  // 100 MHz

  reg  [31:0] ctrl = 0;
  wire [31:0] status;
  reg  [W-1:0] s_tdata = 0;
  reg  s_tvalid = 1;
  wire s_tready;
  wire [W-1:0] m_tdata;
  wire m_tvalid, m_tlast;
  reg  m_tready = 1;
  reg  bp = 0;

  integer got, lasts, gap_errors, fails;
  reg [W-1:0] expect_next;
  reg seen_first;

  capture_gate #(.DATA_W(W)) dut (
    .aclk(aclk), .aresetn(aresetn), .ctrl_aclk(ctrl_aclk),
    .ctrl(ctrl), .status(status),
    .s_axis_tdata(s_tdata), .s_axis_tvalid(s_tvalid), .s_axis_tready(s_tready),
    .m_axis_tdata(m_tdata), .m_axis_tvalid(m_tvalid), .m_axis_tready(m_tready),
    .m_axis_tlast(m_tlast));

  always @(posedge aclk) if (aresetn && s_tvalid && s_tready) s_tdata <= s_tdata + 1;
  always @(negedge aclk) m_tready <= bp ? (($random % 4) != 0) : 1'b1;

  always @(posedge aclk) begin
    if (aresetn && m_tvalid && m_tready) begin
      got <= got + 1;
      if (m_tlast) lasts <= lasts + 1;
      if (seen_first && (m_tdata !== expect_next)) begin
        gap_errors <= gap_errors + 1;
        $display("  !! 不連続: 期待 %0d / 実際 %0d", expect_next, m_tdata);
      end
      seen_first  <= 1'b1;
      expect_next <= m_tdata + 1;
    end
  end

  task check(input integer cond, input [255:0] msg);
    begin if (!cond) begin $display("  !! FAIL %0s", msg); fails = fails + 1; end end
  endtask

  task do_capture(input integer nbeats, input integer backpressure);
    integer guard;
    begin
      @(posedge aclk);
      got = 0; lasts = 0; gap_errors = 0; seen_first = 0;
      ctrl = nbeats;                        // arm = 0
      repeat (20) @(posedge aclk);
      bp = backpressure;
      ctrl = nbeats | 32'h8000_0000;        // arm 立ち上がり
      guard = 0;
      while (lasts == 0 && guard < nbeats*20 + 500) begin
        @(posedge aclk); guard = guard + 1;
      end
      repeat (20) @(posedge aclk);
      bp = 0;
      ctrl = nbeats;                        // arm を落とす
      repeat (20) @(posedge aclk);
      $display("nbeats=%0d bp=%0d -> got=%0d lasts=%0d gaps=%0d status=%08x",
               nbeats, backpressure, got, lasts, gap_errors, status);
      check(got === nbeats,   "ビート数が違う");
      check(lasts === 1,      "TLAST が 1 回でない");
      check(gap_errors === 0, "記録が不連続");
      check(status === 32'h2, "status が done のみでない");
    end
  endtask

  initial begin
    fails = 0; got = 0; lasts = 0; gap_errors = 0; seen_first = 0;
    repeat (10) @(posedge aclk);
    aresetn = 1;
    repeat (20) @(posedge aclk);
    $display("待機中: s_tready=%b m_tvalid=%b status=%08x", s_tready, m_tvalid, status);
    check(s_tready === 1'b1, "待機中に上流を止めている");
    check(m_tvalid === 1'b0, "待機中に下流へ流している");

    do_capture(8, 0);
    do_capture(100, 0);
    do_capture(8192, 0);      // 実運用の 65536 サンプル / 8
    do_capture(64, 1);        // 下流が詰まるケース
    do_capture(16, 0);        // 連続 2 回

    // arm を上げっぱなしにして二重起動しないこと
    got = 0; lasts = 0; seen_first = 0;
    ctrl = 32'h8000_0000 | 32'd4;
    repeat (400) @(posedge aclk);
    $display("arm 保持: got=%0d lasts=%0d (4 と 1 であること)", got, lasts);
    check(got === 4 && lasts === 1, "arm 保持中に再起動している");
    ctrl = 0;
    repeat (20) @(posedge aclk);

    // n_beats = 0 では起動しないこと
    got = 0; lasts = 0;
    ctrl = 32'h8000_0000;
    repeat (200) @(posedge aclk);
    $display("n_beats=0: got=%0d (0 であること)", got);
    check(got === 0, "n_beats=0 で起動している");

    if (fails == 0) $display("=== ALL PASS ===");
    else $display("=== FAIL が %0d 件 ===", fails);
    $finish;
  end
endmodule
