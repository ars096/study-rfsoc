// SPDX-License-Identifier: BSD-3-Clause
// proj032 D-3 — PS の DDR へ HP の口（AXI4 128 bit）から書く負荷発生器。ダンプの受け手の溜めの形を真似て、要る溜めの大きさを数える
//
// 「流れ」: 走っている間、溜めに RATE / 65536 拍 / クロックで拍が入る（ON・PERIOD を決めれば、PERIOD クロックごとに最初の ON クロックだけ入る = ダンプの山）。
//   溜めに BL ＋ 1 拍が揃ったら AW を 1 本出し（出しかけのバーストは OUTS 本まで）、W は揃った拍を続けて出す。
//   溜めの中身 = 入った拍 − W で出した拍。**その最大（BACKLOG_MAX）が、この速さの流れを受けるのに要る溜め**
//   RATE = 65536・ON = 0 は溜めがいつも満ちている形（口の天井を測る。溜めは 2^30 拍で頭打ち・FLAGS[2]）
// 番地: [BASE, BASE + SIZE) を BL ＋ 1 拍のバーストで順に（端で頭に戻る）。BASE は 4 KiB 揃え、(BL ＋ 1)·16 は 4096 の約数（PS 側で守る）
// 書くデータ（拍の番地 a = 番地 >> 4 の下 32 bit、x = a ^ SEED）: 32 bit のレーン i = 0..3 が x ^ (0x01010101·i)、レーン 3 だけ反転
// DUR クロック走ったら、新しい AW を止め、出しかけを出し切って止まる（done）。数え（CYC・拍）は DUR の中だけ
//
// レジスタ（AXI4-Lite、32 bit、aclk の上。pl_clk0 からは SmartConnect で乗り換える）:
//   0x00 ID（読みだけ）  0x04 CTRL: [0] EN（立てて書くと走り始め、数えと FLAGS を消す。走っている間の起動は無視、0 を書くと止める）
//   0x08 BL（拍数 − 1）  0x0C RATE（0..65536）  0x10 BASE_LO  0x14 BASE_HI  0x18 SIZE（バイト）  0x1C SEED  0x20 DUR（クロック）
//   0x24 ON（クロック、0 = いつも）  0x28 PERIOD（クロック）  0x2C OUTS（1..15）
//   0x40 STATUS: [1] busy [3] done   0x44 FLAGS（粘着）: [1] BRESP ≠ 0 [2] 溜めの頭打ち
//   0x48/4C CYC  0x50/54 WR_BEATS  0x58/5C B_CNT  0x60/64 WR_WAIT（W を出したいのに wready が無い拍）  0x68 BACKLOG_MAX（拍）
//   0x6C AW_WAIT（AW を出したのに awready が無いクロック、下 32 bit）  0x70 LAT_MAX（wlast から B までの最大クロック）
`default_nettype none
module hp_tg #(
    parameter [31:0] ID = 32'h0320_0D31
) (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:m_axi, ASSOCIATED_RESET aresetn" *)
    input  wire          clk,
    input  wire          aresetn,
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
    // AXI4（PS の S_AXI_HPn_FPD へ。書きだけ）
    output wire [5:0]    m_axi_awid,
    output reg  [48:0]   m_axi_awaddr,
    output wire [7:0]    m_axi_awlen,
    output wire [2:0]    m_axi_awsize,
    output wire [1:0]    m_axi_awburst,
    output wire          m_axi_awlock,
    output wire [3:0]    m_axi_awcache,
    output wire [2:0]    m_axi_awprot,
    output wire [3:0]    m_axi_awqos,
    output reg           m_axi_awvalid,
    input  wire          m_axi_awready,
    output wire [127:0]  m_axi_wdata,
    output wire [15:0]   m_axi_wstrb,
    output wire          m_axi_wlast,
    output wire          m_axi_wvalid,
    input  wire          m_axi_wready,
    input  wire [5:0]    m_axi_bid,
    input  wire [1:0]    m_axi_bresp,
    input  wire          m_axi_bvalid,
    output wire          m_axi_bready,
    // 読みの口（使わない。PS の口に合わせて置く）
    output wire [5:0]    m_axi_arid,
    output wire [48:0]   m_axi_araddr,
    output wire [7:0]    m_axi_arlen,
    output wire [2:0]    m_axi_arsize,
    output wire [1:0]    m_axi_arburst,
    output wire          m_axi_arlock,
    output wire [3:0]    m_axi_arcache,
    output wire [2:0]    m_axi_arprot,
    output wire [3:0]    m_axi_arqos,
    output wire          m_axi_arvalid,
    input  wire          m_axi_arready,
    input  wire [5:0]    m_axi_rid,
    input  wire [127:0]  m_axi_rdata,
    input  wire [1:0]    m_axi_rresp,
    input  wire          m_axi_rlast,
    input  wire          m_axi_rvalid,
    output wire          m_axi_rready
);
    wire rst = ~aresetn;
    assign m_axi_awid = 6'd0; assign m_axi_awlock = 1'b0; assign m_axi_awcache = 4'b0011; assign m_axi_awprot = 3'b000; assign m_axi_awqos = 4'd0;
    assign m_axi_arid = 6'd0; assign m_axi_araddr = 49'd0; assign m_axi_arlen = 8'd0; assign m_axi_arsize = 3'd4; assign m_axi_arburst = 2'b01;
    assign m_axi_arlock = 1'b0; assign m_axi_arcache = 4'b0011; assign m_axi_arprot = 3'b000; assign m_axi_arqos = 4'd0;
    assign m_axi_arvalid = 1'b0; assign m_axi_rready = 1'b1;

    // ---- 制御のレジスタ ----
    reg         r_en;
    reg  [7:0]  r_bl;
    reg  [16:0] r_rate;
    reg  [48:0] r_base;
    reg  [31:0] r_size, r_seed, r_dur, r_on, r_per;
    reg  [3:0]  r_outs;
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !rst;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    wire [5:0] wa = s_axi_awaddr[7:2];
    reg  done;
    wire busy;
    wire start = wr_go && wa == 6'h01 && s_axi_wdata[0] && !busy && !r_en;
    always @(posedge clk) begin
        if (rst) begin
            s_axi_bvalid <= 1'b0;
            r_en <= 1'b0; r_bl <= 8'd15; r_rate <= 17'd65536; r_base <= 49'd0; r_size <= 32'd0; r_seed <= 32'd0;
            r_dur <= 32'd0; r_on <= 32'd0; r_per <= 32'd0; r_outs <= 4'd8;
        end else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) s_axi_bvalid <= 1'b1;
            if (wr_go) case (wa)
                6'h01: if (start || !s_axi_wdata[0]) r_en <= s_axi_wdata[0];
                6'h02: r_bl   <= s_axi_wdata[7:0];
                6'h03: r_rate <= (s_axi_wdata[16:0] > 17'd65536) ? 17'd65536 : s_axi_wdata[16:0];
                6'h04: r_base[31:0] <= {s_axi_wdata[31:12], 12'd0};
                6'h05: r_base[48:32] <= s_axi_wdata[16:0];
                6'h06: r_size <= {s_axi_wdata[31:4], 4'd0};
                6'h07: r_seed <= s_axi_wdata;
                6'h08: r_dur  <= s_axi_wdata;
                6'h09: r_on   <= s_axi_wdata;
                6'h0A: r_per  <= s_axi_wdata;
                6'h0B: r_outs <= (s_axi_wdata[3:0] == 4'd0) ? 4'd1 : s_axi_wdata[3:0];
                default: ;
            endcase
            else if (done) r_en <= 1'b0;
        end
    end

    // ---- 流れ（溜めに入る拍）----
    reg  [63:0] n_cyc;
    reg  [31:0] ph;                                // PERIOD の中の位置
    wire in_on = (r_on == 32'd0) || (ph < r_on);
    reg  [47:0] dem;                               // 入った拍（16 bit の小数つき）
    reg  [31:0] w_sent, aw_beats;                  // W で出した拍・AW で受けた拍（溜めの位置、2^32 で回る）
    wire [31:0] dem_b = dem[47:16];
    wire [31:0] backlog = dem_b - w_sent;
    wire        cap = backlog[31:30] != 2'b00;     // 2^30 拍で頭打ち
    wire        feeding = r_en && !done;
    // ---- 書き手 ----
    reg  [31:0] ofs;                               // 次の AW の範囲の中の位置（バイト）
    reg  [7:0]  w_cnt;
    reg  [3:0]  aw_out, b_out;                     // AW を出して W を出し終えていない・B を待つバースト
    reg  [31:0] w_addr;                            // 今の W の拍の番地 >> 4
    reg  [31:0] awq [0:15];                        // 出した AW の番地 >> 4
    reg  [3:0]  awq_h, awq_t;
    wire [31:0] bl1 = {24'd0, r_bl} + 32'd1;
    wire        avail = (dem_b - aw_beats) >= bl1; // 溜めに AW 1 本ぶん揃った（まだ AW を出していない拍で）
    reg         stopping;                          // DUR を過ぎた: 新しい AW は出さず、出しかけを出し切る
    wire        aw_can = feeding && !stopping && avail && (aw_out + b_out) < r_outs;
    assign m_axi_wvalid = (aw_out != 4'd0);
    assign m_axi_wlast  = (w_cnt == r_bl);
    wire [31:0] wcur = awq[awq_h] + {24'd0, w_cnt};
    wire [31:0] x = wcur ^ r_seed;
    assign m_axi_wdata  = {~(x ^ 32'h0303_0303), x ^ 32'h0202_0202, x ^ 32'h0101_0101, x};
    assign m_axi_wstrb  = 16'hFFFF;
    assign m_axi_awlen = r_bl; assign m_axi_awsize = 3'd4; assign m_axi_awburst = 2'b01;
    assign m_axi_bready = 1'b1;
    wire w_fire  = m_axi_wvalid && m_axi_wready;
    wire aw_fire = m_axi_awvalid && m_axi_awready;
    wire b_fire  = m_axi_bvalid;
    // B の待ち時間: wlast の時刻を溜めに
    reg  [31:0] tq [0:15];
    reg  [3:0]  tq_h, tq_t;
    reg  [31:0] now;
    always @(posedge clk) begin
        if (rst || start) begin
            m_axi_awvalid <= 1'b0; ofs <= 32'd0; w_cnt <= 8'd0; aw_out <= 4'd0; b_out <= 4'd0;
            awq_h <= 4'd0; awq_t <= 4'd0; tq_h <= 4'd0; tq_t <= 4'd0;
            dem <= 48'd0; w_sent <= 32'd0; aw_beats <= 32'd0; ph <= 32'd0;
        end else begin
            if (feeding) begin
                ph <= (r_per != 32'd0 && ph + 32'd1 >= r_per) ? 32'd0 : ph + 32'd1;
                if (in_on && !cap) dem <= dem + {31'd0, r_rate};
            end
            if (aw_fire) m_axi_awvalid <= 1'b0;
            else if (!m_axi_awvalid && aw_can) begin
                m_axi_awvalid <= 1'b1;
                m_axi_awaddr  <= r_base + {17'd0, ofs};
                awq[awq_t]    <= r_base[35:4] + {4'd0, ofs[31:4]};
                awq_t         <= awq_t + 4'd1;
                aw_beats      <= aw_beats + bl1;
                ofs           <= (ofs + {bl1[27:0], 4'd0} >= r_size) ? 32'd0 : ofs + {bl1[27:0], 4'd0};
            end
            if (w_fire) begin
                w_sent <= w_sent + 32'd1;
                w_cnt  <= m_axi_wlast ? 8'd0 : w_cnt + 8'd1;
                if (m_axi_wlast) begin awq_h <= awq_h + 4'd1; tq[tq_t] <= now; tq_t <= tq_t + 4'd1; end
            end
            if (b_fire) tq_h <= tq_h + 4'd1;
            aw_out <= aw_out + (aw_fire ? 4'd1 : 4'd0) - ((w_fire && m_axi_wlast) ? 4'd1 : 4'd0);
            b_out  <= b_out + ((w_fire && m_axi_wlast) ? 4'd1 : 4'd0) - (b_fire ? 4'd1 : 4'd0);
        end
    end
    assign busy = m_axi_awvalid || aw_out != 4'd0 || b_out != 4'd0;

    // ---- 止まる条件・数え ----
    reg  [63:0] n_wb, n_b, n_ww;
    reg  [31:0] n_aww, bl_max, lat_max;
    reg  [2:0]  flags;
    wire dur_end = (r_dur != 32'd0) && (n_cyc[31:0] >= r_dur);
    always @(posedge clk) begin
        now <= rst ? 32'd0 : now + 32'd1;
        if (rst || start) begin
            n_cyc <= 64'd0; n_wb <= 64'd0; n_b <= 64'd0; n_ww <= 64'd0; n_aww <= 32'd0; bl_max <= 32'd0; lat_max <= 32'd0;
            flags <= 3'd0; done <= 1'b0; stopping <= 1'b0;
        end else begin
            if (r_en && (dur_end || stopping)) stopping <= 1'b1;
            if (stopping && !busy) done <= 1'b1;
            if (feeding && !stopping && !dur_end) begin
                n_cyc <= n_cyc + 64'd1;
                if (w_fire) n_wb <= n_wb + 64'd1;
                if (b_fire) n_b <= n_b + 64'd1;
                if (m_axi_wvalid && !m_axi_wready) n_ww <= n_ww + 64'd1;
                if (m_axi_awvalid && !m_axi_awready) n_aww <= n_aww + 32'd1;
                if (backlog > bl_max) bl_max <= backlog;
            end
            if (b_fire && (now - tq[tq_h]) > lat_max) lat_max <= now - tq[tq_h];
            if (b_fire && m_axi_bresp != 2'b00) flags[1] <= 1'b1;
            if (feeding && cap) flags[2] <= 1'b1;
        end
    end
    // ---- 読み出し ----
    assign s_axi_arready = !s_axi_rvalid && !rst;
    assign s_axi_rresp   = 2'b00;
    always @(posedge clk) begin
        if (rst) s_axi_rvalid <= 1'b0;
        else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1'b1;
                case (s_axi_araddr[7:2])
                    6'h00: s_axi_rdata <= ID;
                    6'h01: s_axi_rdata <= {31'd0, r_en};
                    6'h02: s_axi_rdata <= {24'd0, r_bl};
                    6'h03: s_axi_rdata <= {15'd0, r_rate};
                    6'h04: s_axi_rdata <= r_base[31:0];
                    6'h05: s_axi_rdata <= {15'd0, r_base[48:32]};
                    6'h06: s_axi_rdata <= r_size;
                    6'h07: s_axi_rdata <= r_seed;
                    6'h08: s_axi_rdata <= r_dur;
                    6'h09: s_axi_rdata <= r_on;
                    6'h0A: s_axi_rdata <= r_per;
                    6'h0B: s_axi_rdata <= {28'd0, r_outs};
                    6'h10: s_axi_rdata <= {28'd0, done, 1'b0, busy, 1'b0};
                    6'h11: s_axi_rdata <= {29'd0, flags};
                    6'h12: s_axi_rdata <= n_cyc[31:0];  6'h13: s_axi_rdata <= n_cyc[63:32];
                    6'h14: s_axi_rdata <= n_wb[31:0];   6'h15: s_axi_rdata <= n_wb[63:32];
                    6'h16: s_axi_rdata <= n_b[31:0];    6'h17: s_axi_rdata <= n_b[63:32];
                    6'h18: s_axi_rdata <= n_ww[31:0];   6'h19: s_axi_rdata <= n_ww[63:32];
                    6'h1A: s_axi_rdata <= bl_max;
                    6'h1B: s_axi_rdata <= n_aww;
                    6'h1C: s_axi_rdata <= lat_max;
                    default: s_axi_rdata <= 32'hDEAD_BEEF;
                endcase
            end
        end
    end
endmodule
`default_nettype wire
