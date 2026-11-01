// SPDX-License-Identifier: BSD-3-Clause
//
// rmux4 — コア 4 個のレコード（spw_core の m_axis_rec、128 bit）を ring128 の 1 本の入口へ（proj032 P-9、b3）
//
//   - レコード単位で順番に（tlast まで同じ口）。次の口は前に出した口の次から探す（どの口も待たせ続けない）
//   - 口を選ぶクロックではデータを通さない（レコードの頭ごとに 1 拍の空き。レコードは 8 拍以上なので速さは足りる）
//   - 出口は 1 段のレジスタ（m_tready → 入口の tready は組み合わせで 1 段。rmux128 と同じ）
//   - レコードの中身は変えない（どのコアのものかはレコードの w0 の core = ADC で分かる）
//   - コアごとの rec_drop（機関 E ＋ 1 = 4 本）を ring128 の ext_drop（16 本）に並べるだけの口も持つ（BD に xlconcat を置かないため。組み合わせ）
`timescale 1ns / 1ps

module rmux4 (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s0_axis:s1_axis:s2_axis:s3_axis:m_axis, ASSOCIATED_RESET aresetn" *)
    input  wire         aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire         aresetn,
    input  wire [127:0] s0_axis_tdata,
    input  wire         s0_axis_tvalid,
    output wire         s0_axis_tready,
    input  wire         s0_axis_tlast,
    input  wire [127:0] s1_axis_tdata,
    input  wire         s1_axis_tvalid,
    output wire         s1_axis_tready,
    input  wire         s1_axis_tlast,
    input  wire [127:0] s2_axis_tdata,
    input  wire         s2_axis_tvalid,
    output wire         s2_axis_tready,
    input  wire         s2_axis_tlast,
    input  wire [127:0] s3_axis_tdata,
    input  wire         s3_axis_tvalid,
    output wire         s3_axis_tready,
    input  wire         s3_axis_tlast,
    output reg  [127:0] m_axis_tdata,
    output reg          m_axis_tvalid,
    input  wire         m_axis_tready,
    output reg          m_axis_tlast,
    input  wire [3:0]   d0_drop,
    input  wire [3:0]   d1_drop,
    input  wire [3:0]   d2_drop,
    input  wire [3:0]   d3_drop,
    output wire [15:0]  m_drop
);
    assign m_drop = {d3_drop, d2_drop, d1_drop, d0_drop};
    reg rst_q1 = 1'b1, rst = 1'b1;
    always @(posedge aclk) begin rst_q1 <= !aresetn; rst <= rst_q1; end

    wire [3:0] v = {s3_axis_tvalid, s2_axis_tvalid, s1_axis_tvalid, s0_axis_tvalid};
    wire [3:0] l = {s3_axis_tlast,  s2_axis_tlast,  s1_axis_tlast,  s0_axis_tlast};
    reg  [1:0] sel, prev;
    reg        lk;                      // レコードの途中（sel の口）
    wire       o_free = !m_axis_tvalid || m_axis_tready;
    wire       go = lk && o_free && v[sel];
    assign s0_axis_tready = lk && o_free && sel == 2'd0;
    assign s1_axis_tready = lk && o_free && sel == 2'd1;
    assign s2_axis_tready = lk && o_free && sel == 2'd2;
    assign s3_axis_tready = lk && o_free && sel == 2'd3;

    // 前に出した口の次から、valid の立っている最初の口
    wire [1:0] p1 = prev + 2'd1, p2 = prev + 2'd2, p3 = prev + 2'd3;
    wire [1:0] nxt = v[p1] ? p1 : v[p2] ? p2 : v[p3] ? p3 : prev;

    reg [127:0] d;
    always @(*) case (sel)
        2'd0: d = s0_axis_tdata;  2'd1: d = s1_axis_tdata;
        2'd2: d = s2_axis_tdata;  default: d = s3_axis_tdata;
    endcase

    always @(posedge aclk) begin
        if (rst) begin
            m_axis_tvalid <= 1'b0; m_axis_tlast <= 1'b0; m_axis_tdata <= 128'd0;
            lk <= 1'b0; sel <= 2'd0; prev <= 2'd3;
        end else begin
            if (m_axis_tready) m_axis_tvalid <= 1'b0;
            if (go) begin
                m_axis_tdata <= d; m_axis_tvalid <= 1'b1; m_axis_tlast <= l[sel];
`ifdef RMUX4_POSCTL
                if (l[sel] || d[0]) begin lk <= 1'b0; prev <= sel; end    // 陽性対照: レコードの途中でも口を放す
`else
                if (l[sel]) begin lk <= 1'b0; prev <= sel; end
`endif
            end
            if (!lk && |v) begin sel <= nxt; lk <= 1'b1; end
        end
    end
endmodule
