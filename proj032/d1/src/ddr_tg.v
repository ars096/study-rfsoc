// SPDX-License-Identifier: BSD-3-Clause
// proj028 S-2 — PL DDR4 の負荷発生器（MIG の UI クロックの上。書き手・読み手の AXI4 512 bit、読み返しの照合）
// proj032 D-1 — 多数の窓が交互に書き読みする形を足した（流れの数 NS・流れごとの区画 REG。書き手と読み手で別に。読み手のバースト長 BL_R も別に）:
//   NS ≧ 2 のとき、バースト n は流れ s = n mod NS の区画 [BASE + s·REG, BASE + (s + 1)·REG) の中を順に進む（全部の流れが同じ位置 o を
//   使い、s が一巡するたびに o を BL ＋ 1 拍進め、REG で頭に戻る）。番地は s·REG ＋ o。NS ≦ 1 は proj028 のまま（範囲を順に）。
//   NS ≧ 2 の運転は DUR で止める（ONE_PASS は使わない）。データの式は番地だけで決まるので、先に範囲を ONE_PASS で書いておけば
//   どの順に読んでも照合できる。W と R の照合のために、出したバーストの頭の番地を溜め（OUTS 本）に入れて順に使う
//
// 書き手: 範囲 [BASE, BASE + SIZE) を BL 拍のバーストで順に書く（端で頭に戻る）。速さの上限は W の拍ごとの許可（WR_RATE / 65536 拍 / クロック）
// 読み手: 同じ範囲を順に読み、データを番地と SEED から作る式と照らす。速さの上限は AR ごとに BL 拍分の許可（RD_RATE）
// 書くデータ（拍の番地 a = 番地 >> 6、レーン i = 0..7 の 64 bit）: {~(a ^ SEED) ^ (i·0x01010101), a ^ SEED}
//   → 番地ごとに違う値（容量の折り返しを見る）、SEED を替えると全部の値が替わる
// ONE_PASS: 範囲を 1 周したら止まる（容量の試験・最初の書き込み）。DUR: 0 でなければその拍数だけ走って止まる（数えの窓）
//
// レジスタ（AXI4-Lite、32 bit、UI クロック。pl_clk0 からは SmartConnect で乗り換える）:
//   0x00 ID（読みだけ）          0x04 CTRL: [0] WR_EN [1] RD_EN [2] ONE_PASS [3] CLR（数えと FLAGS を消す）
//        WR_EN か RD_EN を立てて書くと走り始め、数えと FLAGS も消える。wr_busy・rd_busy が立っている間の起動は無視する（止める書き込み = 両方 0 は受ける）
//   0x08 BL（バーストの拍数 − 1、0..255）  0x0C WR_RATE（0..65536、65536 = 毎拍）  0x10 RD_RATE
//   0x14 BASE_LO  0x18 BASE_HI  0x1C SIZE_LO  0x20 SIZE_HI（バイト、BL 拍 × 64 B の倍数）  0x24 SEED  0x28 DUR（拍、0 = 止めるまで）
//   proj032: 0x2C NS_W  0x30 REG_W（バイト）  0x34 BL_R（読み手のバーストの拍数 − 1）  0x38 NS_R  0x3C REG_R（バイト）
//   0x40 STATUS: [0] calib [1] wr_busy [2] rd_busy [3] done（DUR か ONE_PASS で止まった）  0x44 FLAGS（粘着）: [0] 読みの不一致 [1] BRESP ≠ 0 [2] RRESP ≠ 0
//   0x48/4C CYC（走った拍）  0x50/54 WR_BEATS  0x58/5C RD_BEATS  0x60/64 WR_WAIT（W を出したいのに wready が無い拍）  0x68/6C RD_ERR（不一致の拍）
//   0x70/74 FIRST_ERR_ADDR（最初の不一致の番地）
`default_nettype none
module ddr_tg #(
    parameter integer AW = 32,                      // MIG の AXI のアドレスの幅（8 Gb × 4 = 4 GiB で 32。2026-10-23 の実機の容量）
    parameter integer IDW = 4,                      // MIG の AXI の ID の幅（C0.DDR4_AxiIDWidth の既定）
    parameter [31:0]  ID = 32'h0320_0D11
) (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:m_axi, ASSOCIATED_RESET aresetn" *)
    input  wire          clk,
    input  wire          aresetn,
    input  wire          calib,
    // AXI4-Lite（制御）
    input  wire [7:0]    s_axi_awaddr,
    input  wire          s_axi_awvalid,
    output wire          s_axi_awready,
    input  wire [31:0]   s_axi_wdata,
    input  wire          s_axi_wvalid,
    output wire          s_axi_wready,
    output reg           s_axi_bvalid,
    output wire [1:0]    s_axi_bresp,
    input  wire          s_axi_bready,
    input  wire [7:0]    s_axi_araddr,
    input  wire          s_axi_arvalid,
    output wire          s_axi_arready,
    output reg  [31:0]   s_axi_rdata,
    output reg           s_axi_rvalid,
    output wire [1:0]    s_axi_rresp,
    input  wire          s_axi_rready,
    // AXI4（MIG へ）
    output wire [IDW-1:0] m_axi_awid,
    output reg  [AW-1:0] m_axi_awaddr,
    output wire [7:0]    m_axi_awlen,
    output wire [2:0]    m_axi_awsize,
    output wire [1:0]    m_axi_awburst,
    output wire          m_axi_awlock,
    output wire [3:0]    m_axi_awcache,
    output wire [2:0]    m_axi_awprot,
    output wire [3:0]    m_axi_awqos,
    output reg           m_axi_awvalid,
    input  wire          m_axi_awready,
    output wire [511:0]  m_axi_wdata,
    output wire [63:0]   m_axi_wstrb,
    output wire          m_axi_wlast,
    output wire          m_axi_wvalid,
    input  wire          m_axi_wready,
    input  wire [IDW-1:0] m_axi_bid,
    input  wire [1:0]    m_axi_bresp,
    input  wire          m_axi_bvalid,
    output wire          m_axi_bready,
    output wire [IDW-1:0] m_axi_arid,
    output reg  [AW-1:0] m_axi_araddr,
    output wire [7:0]    m_axi_arlen,
    output wire [2:0]    m_axi_arsize,
    output wire [1:0]    m_axi_arburst,
    output wire          m_axi_arlock,
    output wire [3:0]    m_axi_arcache,
    output wire [2:0]    m_axi_arprot,
    output wire [3:0]    m_axi_arqos,
    output reg           m_axi_arvalid,
    input  wire          m_axi_arready,
    input  wire [IDW-1:0] m_axi_rid,
    input  wire [511:0]  m_axi_rdata,
    input  wire [1:0]    m_axi_rresp,
    input  wire          m_axi_rlast,
    input  wire          m_axi_rvalid,
    output wire          m_axi_rready
);
    localparam integer BA = AW - 6;                 // 拍の番地の幅
    localparam integer OUTS = 8;                    // 先に出してよいバーストの数
    wire rst = ~aresetn;
    // ID は 1 つ（順序どおりに返る）。lock・cache・prot・qos は定数
    assign m_axi_awid = {IDW{1'b0}}; assign m_axi_arid = {IDW{1'b0}};
    assign m_axi_awlock = 1'b0; assign m_axi_arlock = 1'b0;
    assign m_axi_awcache = 4'b0011; assign m_axi_arcache = 4'b0011;
    assign m_axi_awprot = 3'b000; assign m_axi_arprot = 3'b000;
    assign m_axi_awqos = 4'd0; assign m_axi_arqos = 4'd0;

    // ---- データの式（書き手・読み手で同じ）----
    function [511:0] pat;
        input [BA-1:0] a;
        input [31:0]   seed;
        integer i;
        reg [31:0] x;
        begin
            x = {{(32 > BA ? 32 - BA : 0){1'b0}}, a[BA-1:0]} ^ seed;
            for (i = 0; i < 8; i = i + 1) pat[i*64 +: 64] = {~x ^ (32'h0101_0101 * i), x};
        end
    endfunction

    // ---- 制御のレジスタ ----
    reg        r_wen, r_ren, r_one;
    reg  [7:0] r_bl;
    reg  [16:0] r_wrate, r_rrate;
    reg  [63:0] r_base, r_size;                    // 64 bit で持つ（AW 32 で範囲がちょうど 4 GiB = 2^32 でも表せるように）
    reg  [31:0] r_seed, r_dur;
    reg  [7:0]  r_blr;                              // proj032: 読み手のバースト長 − 1
    reg  [15:0] r_nsw, r_nsr;                       // proj032: 流れの数（≦ 1 は順に）
    reg  [31:0] r_regw, r_regr;                     // proj032: 流れごとの区画（バイト）
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !rst;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    // （wr_go と s_axi_arready はリセット中に 0。リセット中に握手が成立すると応答が返らず、PS ごと止まる: 2026-10-23 の実機）
    assign s_axi_bresp   = 2'b00;
    wire [5:0] wa = s_axi_awaddr[7:2];
    wire clr = wr_go && wa == 6'h01 && s_axi_wdata[3];
    reg  done;
    wire wr_busy, rd_busy;
    // 走っている間の起動は受けない（書き手・読み手の状態を途中で消すと AXI の約束を破る）
    wire start = wr_go && wa == 6'h01 && (s_axi_wdata[0] || s_axi_wdata[1]) && !wr_busy && !rd_busy;
    always @(posedge clk) begin
        if (rst) begin
            s_axi_bvalid <= 1'b0;
            r_wen <= 1'b0; r_ren <= 1'b0; r_one <= 1'b0; r_bl <= 8'd255; r_wrate <= 17'd65536; r_rrate <= 17'd65536;
            r_base <= 64'd0; r_size <= 64'd0; r_seed <= 32'd0; r_dur <= 32'd0;
            r_blr <= 8'd255; r_nsw <= 16'd0; r_nsr <= 16'd0; r_regw <= 32'd0; r_regr <= 32'd0;
        end else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) s_axi_bvalid <= 1'b1;
            if (wr_go) case (wa)
                6'h01: if (start || !(s_axi_wdata[0] || s_axi_wdata[1])) begin r_wen <= s_axi_wdata[0]; r_ren <= s_axi_wdata[1]; r_one <= s_axi_wdata[2]; end
                6'h02: r_bl <= s_axi_wdata[7:0];
                6'h03: r_wrate <= (s_axi_wdata[16:0] > 17'd65536) ? 17'd65536 : s_axi_wdata[16:0];
                6'h04: r_rrate <= (s_axi_wdata[16:0] > 17'd65536) ? 17'd65536 : s_axi_wdata[16:0];
                6'h05: r_base[31:0] <= {s_axi_wdata[31:6], 6'd0};
                6'h06: r_base[63:32] <= s_axi_wdata;
                6'h07: r_size[31:0] <= {s_axi_wdata[31:6], 6'd0};
                6'h08: r_size[63:32] <= s_axi_wdata;
                6'h09: r_seed <= s_axi_wdata;
                6'h0A: r_dur <= s_axi_wdata;
                6'h0B: r_nsw <= s_axi_wdata[15:0];
                6'h0C: r_regw <= {s_axi_wdata[31:6], 6'd0};
                6'h0D: r_blr <= s_axi_wdata[7:0];
                6'h0E: r_nsr <= s_axi_wdata[15:0];
                6'h0F: r_regr <= {s_axi_wdata[31:6], 6'd0};
                default: ;
            endcase
            else if (done) begin r_wen <= 1'b0; r_ren <= 1'b0; end
        end
    end

    // ---- 走る窓と数え ----
    reg  [63:0] n_cyc, n_wb, n_rb, n_ww, n_err;
    reg  [AW-1:0] first_err;
    reg  [2:0]  flags;
    wire run = r_wen || r_ren;

    // 速さの上限（許可の溜め。止まっている間に溜まりすぎないよう 2 バースト分で頭打ち）
    reg  [24:0] wtok, rtok;
    wire [24:0] tcap = {r_bl, 16'd0} + 25'd65536 + 25'd65536;   // ≒ (BL + 2) 拍
    wire [24:0] tcapr = {r_blr, 16'd0} + 25'd65536 + 25'd65536;  // proj032: 読み手は BL_R で
    // ---- 書き手 ----
    reg  [BA:0]   aw_beat, w_beat;                 // 次に出す AW・W の拍の範囲の中の位置（範囲が 2^BA 拍ちょうどでも数えられるよう 1 bit 広い）
    reg  [7:0]    w_cnt;
    reg  [3:0]    aw_out;                          // AW を出して W を出し終えていないバースト
    reg  [3:0]    b_out;                           // W を出し終えて B を待つバースト
    reg           wr_wrapped, w_wrapped;
    // proj032: 流れの番地
    wire          wst = r_nsw > 16'd1;
    reg  [15:0]   ws_i;                            // 今の流れ
    reg  [BA:0]   ws_b, ws_o;                      // 流れの区画の頭（s·REG）と区画の中の位置（拍）
    wire [BA:0]   regw_b = {{(BA+1-26){1'b0}}, r_regw[31:6]};
    // W の番地: 出したバーストの頭を溜めに入れ、W はその頭 ＋ w_cnt
    reg  [BA-1:0] awq [0:OUTS-1];
    reg  [2:0]    awq_h, awq_t;
    wire [BA:0]   size_b = r_size[AW:6];
    wire [BA-1:0] base_b = r_base[AW-1:6];
    wire [BA:0]   bl1 = {{(BA-7){1'b0}}, r_bl} + 1'b1;
    wire aw_room = (aw_out + b_out) < OUTS;
    wire aw_can = r_wen && !(r_one && wr_wrapped) && aw_room && !done && calib;   // MIG の較正が済むまで出さない
    wire w_tok  = (r_wrate == 17'd65536) || (wtok >= 25'd65536);
    assign m_axi_wvalid = (aw_out != 4'd0) && w_tok;
    assign m_axi_wlast  = (w_cnt == r_bl);
    wire [BA-1:0] w_addr = wst ? (awq[awq_h] + {{(BA-8){1'b0}}, w_cnt}) : (base_b + w_beat[BA-1:0]);
    assign m_axi_wdata  = pat(w_addr, r_seed);
    assign m_axi_wstrb  = {64{1'b1}};
    assign m_axi_awlen = r_bl; assign m_axi_awsize = 3'd6; assign m_axi_awburst = 2'b01;
    assign m_axi_bready = 1'b1;
    wire w_fire  = m_axi_wvalid && m_axi_wready;
    wire aw_fire = m_axi_awvalid && m_axi_awready;
    wire b_fire  = m_axi_bvalid;
    always @(posedge clk) begin
        if (rst || start) begin
            m_axi_awvalid <= 1'b0; aw_beat <= {(BA+1){1'b0}}; w_beat <= {(BA+1){1'b0}}; w_cnt <= 8'd0;
            aw_out <= 4'd0; b_out <= 4'd0; wr_wrapped <= 1'b0; wtok <= 25'd0;
            ws_i <= 16'd0; ws_b <= {(BA+1){1'b0}}; ws_o <= {(BA+1){1'b0}}; awq_h <= 3'd0; awq_t <= 3'd0;
        end else begin
            // 許可
            if (w_fire && r_wrate != 17'd65536) wtok <= ((wtok + r_wrate > tcap) ? tcap : wtok + r_wrate) - 25'd65536;
            else if (r_wen || aw_out != 4'd0) wtok <= (wtok + r_wrate > tcap) ? tcap : wtok + r_wrate;   // 止めた後も残りの W を流す
            // AW
            if (aw_fire) begin
                m_axi_awvalid <= 1'b0;
                if (wst) begin
                    if (ws_i + 16'd1 >= r_nsw) begin
                        ws_i <= 16'd0; ws_b <= {(BA+1){1'b0}};
                        ws_o <= (ws_o + bl1 >= regw_b) ? {(BA+1){1'b0}} : ws_o + bl1;
                    end else begin
                        ws_i <= ws_i + 16'd1; ws_b <= ws_b + regw_b;
                    end
                end else if (aw_beat + bl1 >= size_b) begin aw_beat <= {(BA+1){1'b0}}; wr_wrapped <= 1'b1; end
                else aw_beat <= aw_beat + bl1;
            end else if (!m_axi_awvalid && aw_can) begin
                m_axi_awvalid <= 1'b1;
                m_axi_awaddr  <= wst ? {base_b + ws_b[BA-1:0] + ws_o[BA-1:0], 6'd0} : {base_b + aw_beat[BA-1:0], 6'd0};
                awq[awq_t]    <= wst ? (base_b + ws_b[BA-1:0] + ws_o[BA-1:0]) : (base_b + aw_beat[BA-1:0]);
                awq_t         <= awq_t + 3'd1;
            end
            if (w_fire && m_axi_wlast) awq_h <= awq_h + 3'd1;
            // W
            if (w_fire) begin
                w_cnt  <= m_axi_wlast ? 8'd0 : w_cnt + 8'd1;
                w_beat <= (w_beat + 1'b1 >= size_b) ? {(BA+1){1'b0}} : w_beat + 1'b1;
            end
            aw_out <= aw_out + (aw_fire ? 4'd1 : 4'd0) - ((w_fire && m_axi_wlast) ? 4'd1 : 4'd0);
            b_out  <= b_out + ((w_fire && m_axi_wlast) ? 4'd1 : 4'd0) - (b_fire ? 4'd1 : 4'd0);
        end
    end
    assign wr_busy = m_axi_awvalid || aw_out != 4'd0 || b_out != 4'd0;

    // ---- 読み手 ----
    reg  [BA:0]   ar_beat, r_beat;
    reg  [3:0]    ar_out;                          // AR を出して最後の R を受けていないバースト
    reg           rd_wrapped;
    wire          rst_ = r_nsr > 16'd1;            // proj032: 流れの番地（読み手）
    reg  [15:0]   rs_i;
    reg  [BA:0]   rs_b, rs_o;
    wire [BA:0]   regr_b = {{(BA+1-26){1'b0}}, r_regr[31:6]};
    wire [BA:0]   blr1 = {{(BA-7){1'b0}}, r_blr} + 1'b1;
    reg  [BA-1:0] arq [0:OUTS-1];
    reg  [2:0]    arq_h, arq_t;
    reg  [7:0]    r_cnt;
    wire r_tok  = (r_rrate == 17'd65536) || (rtok >= {r_blr, 16'd0} + 25'd65536);
    wire ar_can = r_ren && !(r_one && rd_wrapped) && (ar_out < OUTS) && r_tok && !done && calib;
    assign m_axi_arlen = r_blr; assign m_axi_arsize = 3'd6; assign m_axi_arburst = 2'b01;
    assign m_axi_rready = 1'b1;
    wire ar_fire = m_axi_arvalid && m_axi_arready;
    wire r_fire  = m_axi_rvalid;
    // 照合は 1 段遅らせる（512 bit の比べ）
    reg          rq_v;
    reg  [511:0] rq_d, rq_e;
    reg  [BA-1:0] rq_a;
    always @(posedge clk) begin
        if (rst || start) begin
            m_axi_arvalid <= 1'b0; ar_beat <= {(BA+1){1'b0}}; r_beat <= {(BA+1){1'b0}}; ar_out <= 4'd0; rd_wrapped <= 1'b0; rtok <= 25'd0;
            rs_i <= 16'd0; rs_b <= {(BA+1){1'b0}}; rs_o <= {(BA+1){1'b0}}; arq_h <= 3'd0; arq_t <= 3'd0; r_cnt <= 8'd0;
            rq_v <= 1'b0;
        end else begin
            if (ar_fire && r_rrate != 17'd65536) rtok <= ((rtok + r_rrate > tcapr) ? tcapr : rtok + r_rrate) - ({r_blr, 16'd0} + 25'd65536);
            else if (r_ren) rtok <= (rtok + r_rrate > tcapr) ? tcapr : rtok + r_rrate;
            if (ar_fire) begin
                m_axi_arvalid <= 1'b0;
                if (rst_) begin
                    if (rs_i + 16'd1 >= r_nsr) begin
                        rs_i <= 16'd0; rs_b <= {(BA+1){1'b0}};
                        rs_o <= (rs_o + blr1 >= regr_b) ? {(BA+1){1'b0}} : rs_o + blr1;
                    end else begin
                        rs_i <= rs_i + 16'd1; rs_b <= rs_b + regr_b;
                    end
                end else if (ar_beat + blr1 >= size_b) begin ar_beat <= {(BA+1){1'b0}}; rd_wrapped <= 1'b1; end
                else ar_beat <= ar_beat + blr1;
            end else if (!m_axi_arvalid && ar_can) begin
                m_axi_arvalid <= 1'b1;
                m_axi_araddr  <= rst_ ? {base_b + rs_b[BA-1:0] + rs_o[BA-1:0], 6'd0} : {base_b + ar_beat[BA-1:0], 6'd0};
                arq[arq_t]    <= rst_ ? (base_b + rs_b[BA-1:0] + rs_o[BA-1:0]) : (base_b + ar_beat[BA-1:0]);
                arq_t         <= arq_t + 3'd1;
            end
            if (r_fire) begin
                r_cnt <= m_axi_rlast ? 8'd0 : r_cnt + 8'd1;
                if (m_axi_rlast) arq_h <= arq_h + 3'd1;
            end
            ar_out <= ar_out + (ar_fire ? 4'd1 : 4'd0) - ((r_fire && m_axi_rlast) ? 4'd1 : 4'd0);
            if (r_fire) r_beat <= (r_beat + 1'b1 >= size_b) ? {(BA+1){1'b0}} : r_beat + 1'b1;
            rq_v <= r_fire;
            rq_d <= m_axi_rdata;
            rq_e <= pat(arq[arq_h] + {{(BA-8){1'b0}}, r_cnt}, r_seed);   // proj032: バーストの頭 ＋ 拍（順の運転でも同じ値）
            rq_a <= arq[arq_h] + {{(BA-8){1'b0}}, r_cnt};
        end
    end
    assign rd_busy = m_axi_arvalid || ar_out != 4'd0;
    wire mism = rq_v && (rq_d != rq_e);

    // ---- 止まる条件・数え ----
    wire one_done = r_one && (!r_wen || (wr_wrapped && !wr_busy)) && (!r_ren || (rd_wrapped && !rd_busy)) && run;
    wire dur_done = (r_dur != 32'd0) && (n_cyc[31:0] >= r_dur) && run;
    always @(posedge clk) begin
        if (rst || clr || start) begin              // 走らせるたびに数えと FLAGS を消す（1 回 = 1 つの測り）
            n_cyc <= 64'd0; n_wb <= 64'd0; n_rb <= 64'd0; n_ww <= 64'd0; n_err <= 64'd0; first_err <= {AW{1'b0}};
            flags <= 3'd0; done <= 1'b0;
        end else begin
            if (one_done || dur_done) done <= 1'b1;
            // 帯域の数えは窓の中だけ（done の後の残りのバーストは数えない）。照合は全部の拍で
            if (run && !done) n_cyc <= n_cyc + 64'd1;
            if (w_fire && !done) n_wb <= n_wb + 64'd1;
            if (r_fire && !done) n_rb <= n_rb + 64'd1;
            if (r_wen && !done && (aw_out != 4'd0) && w_tok && !m_axi_wready) n_ww <= n_ww + 64'd1;
            if (mism) begin
                if (n_err == 64'd0) first_err <= {rq_a, 6'd0};
                n_err <= n_err + 64'd1;
                flags[0] <= 1'b1;
            end
            if (b_fire && m_axi_bresp != 2'b00) flags[1] <= 1'b1;
            if (r_fire && m_axi_rresp != 2'b00) flags[2] <= 1'b1;
        end
    end

    // ---- 読み出し ----
    assign s_axi_arready = !s_axi_rvalid && !rst;
    assign s_axi_rresp   = 2'b00;
    wire [63:0] fe64 = {{(64-AW){1'b0}}, first_err};
    always @(posedge clk) begin
        if (rst) s_axi_rvalid <= 1'b0;
        else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1'b1;
                case (s_axi_araddr[7:2])
                    6'h00: s_axi_rdata <= ID;
                    6'h01: s_axi_rdata <= {29'd0, r_one, r_ren, r_wen};
                    6'h02: s_axi_rdata <= {24'd0, r_bl};
                    6'h03: s_axi_rdata <= {15'd0, r_wrate};
                    6'h04: s_axi_rdata <= {15'd0, r_rrate};
                    6'h05: s_axi_rdata <= r_base[31:0];
                    6'h06: s_axi_rdata <= r_base[63:32];
                    6'h07: s_axi_rdata <= r_size[31:0];
                    6'h08: s_axi_rdata <= r_size[63:32];
                    6'h09: s_axi_rdata <= r_seed;
                    6'h0A: s_axi_rdata <= r_dur;
                    6'h0B: s_axi_rdata <= {16'd0, r_nsw};
                    6'h0C: s_axi_rdata <= r_regw;
                    6'h0D: s_axi_rdata <= {24'd0, r_blr};
                    6'h0E: s_axi_rdata <= {16'd0, r_nsr};
                    6'h0F: s_axi_rdata <= r_regr;
                    6'h10: s_axi_rdata <= {28'd0, done, rd_busy, wr_busy, calib};
                    6'h11: s_axi_rdata <= {29'd0, flags};
                    6'h12: s_axi_rdata <= n_cyc[31:0];   6'h13: s_axi_rdata <= n_cyc[63:32];
                    6'h14: s_axi_rdata <= n_wb[31:0];    6'h15: s_axi_rdata <= n_wb[63:32];
                    6'h16: s_axi_rdata <= n_rb[31:0];    6'h17: s_axi_rdata <= n_rb[63:32];
                    6'h18: s_axi_rdata <= n_ww[31:0];    6'h19: s_axi_rdata <= n_ww[63:32];
                    6'h1A: s_axi_rdata <= n_err[31:0];   6'h1B: s_axi_rdata <= n_err[63:32];
                    6'h1C: s_axi_rdata <= fe64[31:0];    6'h1D: s_axi_rdata <= fe64[63:32];
                    default: s_axi_rdata <= 32'hDEAD_BEEF;
                endcase
            end
        end
    end
endmodule
`default_nettype wire
