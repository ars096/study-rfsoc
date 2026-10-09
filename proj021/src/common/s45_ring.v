// SPDX-License-Identifier: BSD-3-Clause
//
// s45_ring — PL が書くリング（INTERFACE 4.。proj021 手順 2-2a）。CORE_KIND 3、AXI4-Lite 4 KiB
//
// 入口 NIN 本（コアごとの m_axis_rec。rec_fr のレコード: ヘッダ 8 語 ＋ 本体、tlast・tuser = 捨てる）を
// レコード単位の順番回し（rec_arb）で 1 本にし、PS の DDR のリング（BASE・SIZE）へ自作の AXI4 の書き手（128 bit）で書く。
//
// ---- 1 レコードの流れ ----
//   1. ヘッダ 8 語を受ける（w7 の下位 32 bit = 本体のバイト数 P）。長さ L = 64 + P + 64（尾）
//   2. 空きを見る: pos = W mod SIZE、端まで E = SIZE − pos。L > E なら PAD（type 0 のヘッダ 1 個、w7 = E）を pos に書き、
//      レコードは 0 から。要る量 = L（＋ PAD なら E）。EN = 1・ERR = 0・要る量 ≦ SIZE − (W − R) でなければ
//      **丸ごと捨てる**（入口から tlast まで読む。EN = 1 なら DROP_CNT +1）
//   3. 書く語: [PAD 8 語] → ヘッダ 8 語 → 本体 P/8 語 → 尾 8 語（w0 = "S45E" | SEQ、w1 = CRC-32、残り 0）。
//      CRC-32 は zlib.crc32 と同じ式（反転入力・反転出力、多項式 0xEDB88320）でヘッダ ＋ 本体。64 bit を 1 クロックで
//   4. 2 語を 1 拍（128 bit、下位が先）に束ねて FIFO（512 拍）へ。FIFO に拍が揃ったらバースト（≦ 16 拍。番地の 256 バイト境で切る
//      ので 4 KiB の境を越えない）。AW と W は 1 バーストずつ（AW が受かり W を出し切ったら次）
//   5. 最後のバーストまで出し、BRESP を全部受けたら: tuser = 0 なら W += 要る量・REC_CNT +1・PEAK。tuser = 1 なら W は動かさず
//      DROP_CNT +1（書いたぶんは W より先なので PS には見えない）。BRESP が OKAY でなければ ERR（粘着）・ERR_STAT、以後は捨てる
//   - 入口の rec_drop（コアの rec_fr が「読み始めなかった」ダンプの数。コアごとに 2 bit）も DROP_CNT に足す
//
// ---- レジスタ（INTERFACE 4.2）----
//   0x00 IF_ID {2, BIT_KIND, BIT_REV, 3} / 0x04 CTRL W:[0]EN [1]RST（EN = 0 のときだけ） R:[0]EN [1]busy [2]ERR
//   0x08/0C BASE_LO/HI（EN = 0 のときだけ）/ 0x10 SIZE（2 の冪、EN = 0 のときだけ）/ 0x14 W / 0x18 R（PS が書く）
//   0x1C DROP_CNT / 0x20 REC_CNT / 0x24 PEAK / 0x28 ERR_STAT（[1:0] BRESP・[31:6] そのレコードの頭の W）/ 0x2C PROJ
`timescale 1ns / 1ps

module s45_ring #(
    parameter integer NIN      = 4,
    parameter integer BIT_KIND = 2,
    parameter integer BIT_REV  = 1,
    parameter integer PROJ     = 2163200,       // = 0x0021_0200（10 進で書く。time_core と同じ理由）
    parameter integer FDEPTH   = 512            // 書き手の FIFO（拍）
) (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:m_axi:s0_axis:s1_axis:s2_axis:s3_axis, ASSOCIATED_RESET aresetn" *)
    input  wire              aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire              aresetn,
    // 入口（コア 0..3）
    input  wire [63:0]       s0_axis_tdata,
    input  wire              s0_axis_tvalid,
    output wire              s0_axis_tready,
    input  wire              s0_axis_tlast,
    input  wire              s0_axis_tuser,
    input  wire [63:0]       s1_axis_tdata,
    input  wire              s1_axis_tvalid,
    output wire              s1_axis_tready,
    input  wire              s1_axis_tlast,
    input  wire              s1_axis_tuser,
    input  wire [63:0]       s2_axis_tdata,
    input  wire              s2_axis_tvalid,
    output wire              s2_axis_tready,
    input  wire              s2_axis_tlast,
    input  wire              s2_axis_tuser,
    input  wire [63:0]       s3_axis_tdata,
    input  wire              s3_axis_tvalid,
    output wire              s3_axis_tready,
    input  wire              s3_axis_tlast,
    input  wire              s3_axis_tuser,
    input  wire [1:0]        rec_drop0,
    input  wire [1:0]        rec_drop1,
    input  wire [1:0]        rec_drop2,
    input  wire [1:0]        rec_drop3,
    // AXI4-Lite
    input  wire [11:0]       s_axi_awaddr,
    input  wire [2:0]        s_axi_awprot,
    input  wire              s_axi_awvalid,
    output wire              s_axi_awready,
    input  wire [31:0]       s_axi_wdata,
    input  wire [3:0]        s_axi_wstrb,
    input  wire              s_axi_wvalid,
    output wire              s_axi_wready,
    output wire [1:0]        s_axi_bresp,
    output reg               s_axi_bvalid,
    input  wire              s_axi_bready,
    input  wire [11:0]       s_axi_araddr,
    input  wire [2:0]        s_axi_arprot,
    input  wire              s_axi_arvalid,
    output wire              s_axi_arready,
    output reg  [31:0]       s_axi_rdata,
    output wire [1:0]        s_axi_rresp,
    output reg               s_axi_rvalid,
    input  wire              s_axi_rready,
    // AXI4 の書き手（PS の S_AXI_HP0_FPD へ。書くだけ）
    output wire [48:0]       m_axi_awaddr,
    output wire [7:0]        m_axi_awlen,
    output wire [2:0]        m_axi_awsize,
    output wire [1:0]        m_axi_awburst,
    output wire              m_axi_awlock,
    output wire [3:0]        m_axi_awcache,
    output wire [2:0]        m_axi_awprot,
    output wire [3:0]        m_axi_awqos,
    output reg               m_axi_awvalid,
    input  wire              m_axi_awready,
    output wire [127:0]      m_axi_wdata,
    output wire [15:0]       m_axi_wstrb,
    output wire              m_axi_wlast,
    output wire              m_axi_wvalid,
    input  wire              m_axi_wready,
    input  wire [1:0]        m_axi_bresp,
    input  wire              m_axi_bvalid,
    output wire              m_axi_bready
);
    localparam [7:0]  BK8 = BIT_KIND, BR8 = BIT_REV;
    localparam [31:0] IF_ID = {8'd2, BK8, BR8, 8'd3};
    localparam [31:0] MAGIC_R = 32'h5235_3453, MAGIC_E = 32'h4535_3453;
    localparam integer FAW = $clog2(FDEPTH);
    localparam [3:0]  INM = (1 << NIN) - 1;
    wire rst = ~aresetn;

    // =====================================================================
    // レジスタ
    // =====================================================================
    reg         en, err;
    reg  [63:0] base;
    reg  [31:0] size, w_pos, r_pos, drop_cnt, rec_cnt, peak, err_stat;
    wire        busy;
    wire        wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    wire [9:0]  wa = s_axi_awaddr[11:2];
    reg         cmd_rst;
    always @(posedge aclk) begin
        cmd_rst <= 1'b0;
        if (rst) begin
            s_axi_bvalid <= 1'b0; en <= 1'b0; base <= 64'd0; size <= 32'h0001_0000; r_pos <= 32'd0;
        end else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) begin
                s_axi_bvalid <= 1'b1;
                case (wa)
                    10'h001: begin en <= s_axi_wdata[0]; cmd_rst <= s_axi_wdata[1] && !en && !s_axi_wdata[0] && !busy; end
                    10'h002: if (!en) base[31:0]  <= s_axi_wdata;
                    10'h003: if (!en) base[63:32] <= s_axi_wdata;
                    10'h004: if (!en) size <= s_axi_wdata;
                    10'h006: r_pos <= s_axi_wdata;
                    default: ;
                endcase
            end
            if (cmd_rst) r_pos <= 32'd0;
        end
    end
    reg  [9:0]  ra;
    reg         ar_busy;
    assign s_axi_arready = !ar_busy && !s_axi_rvalid;
    assign s_axi_rresp   = 2'b00;
    always @(posedge aclk) begin
        if (rst) begin ar_busy <= 1'b0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0; ra <= 10'd0; end
        else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin ar_busy <= 1'b1; ra <= s_axi_araddr[11:2]; end
            else if (ar_busy) begin
                ar_busy <= 1'b0; s_axi_rvalid <= 1'b1;
                case (ra)
                    10'h000: s_axi_rdata <= IF_ID;
                    10'h001: s_axi_rdata <= {29'd0, err, busy, en};
                    10'h002: s_axi_rdata <= base[31:0];
                    10'h003: s_axi_rdata <= base[63:32];
                    10'h004: s_axi_rdata <= size;
                    10'h005: s_axi_rdata <= w_pos;
                    10'h006: s_axi_rdata <= r_pos;
                    10'h007: s_axi_rdata <= drop_cnt;
                    10'h008: s_axi_rdata <= rec_cnt;
                    10'h009: s_axi_rdata <= peak;
                    10'h00A: s_axi_rdata <= err_stat;
                    10'h00B: s_axi_rdata <= PROJ;
                    default: s_axi_rdata <= 32'd0;
                endcase
            end
        end
    end

    // =====================================================================
    // 入口の束ね
    // =====================================================================
    wire [63:0] in_d;
    wire        in_v, in_l, in_u;
    reg         in_r;
    rec_arb #(.N(4)) u_arb (.clk(aclk), .rst(rst),
        .s_tdata({s3_axis_tdata, s2_axis_tdata, s1_axis_tdata, s0_axis_tdata}),
        .s_tvalid({s3_axis_tvalid, s2_axis_tvalid, s1_axis_tvalid, s0_axis_tvalid} & INM),
        .s_tready({s3_axis_tready, s2_axis_tready, s1_axis_tready, s0_axis_tready}),
        .s_tlast({s3_axis_tlast, s2_axis_tlast, s1_axis_tlast, s0_axis_tlast}),
        .s_tuser({s3_axis_tuser, s2_axis_tuser, s1_axis_tuser, s0_axis_tuser}),
        .m_tdata(in_d), .m_tvalid(in_v), .m_tready(in_r), .m_tlast(in_l), .m_tuser(in_u));
    wire        in_go = in_v && in_r;

    // コアの rec_drop の和（1 クロックに最大 4 × 3）
    reg  [3:0]  ext_drop;
    always @(posedge aclk) ext_drop <= rec_drop0 + rec_drop1 + rec_drop2 + rec_drop3;

    // =====================================================================
    // CRC-32（zlib）。64 bit を 1 クロック。バイトの順 = little endian = bit 0 から
    // =====================================================================
    function [31:0] crc64(input [31:0] c, input [63:0] d);
        integer b;
        reg [31:0] x;
        begin
            x = c;
            for (b = 0; b < 64; b = b + 1)
                x = (x[0] ^ d[b]) ? ((x >> 1) ^ 32'hEDB8_8320) : (x >> 1);
            crc64 = x;
        end
    endfunction

    // =====================================================================
    // FIFO（拍 128 bit。先読みの出口レジスタ付き）
    // =====================================================================
    reg  [127:0] fmem [0:FDEPTH-1];
    reg  [FAW-1:0] fwp, frp;
    reg  [FAW:0]  fin_mem;                 // 記憶の中の拍
    reg  [127:0]  fout;
    reg           fov;
    reg  [FAW:0]  fav;                     // 押した − W で出した（記憶 ＋ 出口）
    reg           push;
    reg  [127:0]  pdata;
    wire          wgo;                      // W の拍が受かった
    wire          f_ld = (fin_mem != 0) && (!fov || wgo);
    always @(posedge aclk) begin
        if (push) fmem[fwp] <= pdata;
        if (f_ld) fout <= fmem[frp];
    end
    always @(posedge aclk) begin
        if (rst || cmd_rst) begin fwp <= 0; frp <= 0; fin_mem <= 0; fov <= 1'b0; fav <= 0; end
        else begin
            if (push) fwp <= fwp + 1'b1;
            if (f_ld) frp <= frp + 1'b1;
            fin_mem <= fin_mem + (push ? 1 : 0) - (f_ld ? 1 : 0);
            if (f_ld) fov <= 1'b1; else if (wgo) fov <= 1'b0;
            fav <= fav + (push ? 1 : 0) - (wgo ? 1 : 0);
        end
    end
    wire f_room = (fav < FDEPTH - 4);

    // =====================================================================
    // 語を作る側（G）
    // =====================================================================
    localparam [3:0] G_HDR = 4'd0, G_DEC = 4'd1, G_WAIT = 4'd2, G_PAD = 4'd3, G_REC = 4'd4, G_TAIL = 4'd5, G_FIN = 4'd6, G_DISC = 4'd7,
                     G_FILL = 4'd8;
    reg  [3:0]  gs;
    reg         no_last;                    // tlast が来ないまま長さに達した（残りを G_DISC で捨てる）
    reg  [63:0] hb [0:7];
    reg  [2:0]  hi;
    reg  [31:0] pay_w;                      // 本体の残りの語
    reg  [31:0] rec_len, need, e_len_l, w_start, pos_l;
    reg         pad, abort_r, hdr_out;
    reg  [31:0] crc;
    reg  [63:0] lo;
    reg         half;
    reg  [63:0] gw;
    reg         gv;
    wire        seg_done;
    reg         bad_seen;
    reg  [1:0]  bad_resp;
    reg         sg_start;                   // 書き手へ: この区間を書け（1 クロック）

    wire [31:0] mask  = size - 32'd1;
    wire [31:0] pos   = w_pos & mask;
    wire [31:0] e_len = size - pos;
    wire [31:0] used  = w_pos - r_pos;

    always @* begin
        in_r = 1'b0; gw = 64'd0; gv = 1'b0;
        case (gs)
            G_HDR:  in_r = 1'b1;
            G_DISC: in_r = 1'b1;
            G_PAD:  if (f_room) begin gv = 1'b1;
                        gw = (hi == 3'd0) ? {8'd0, 8'd0, 8'd0, 8'd1, MAGIC_R} : (hi == 3'd7) ? {32'd0, e_len_l} : 64'd0; end
            G_REC:  if (f_room) begin
                        if (hdr_out) begin gv = 1'b1; gw = hb[hi]; end
                        else begin in_r = 1'b1; gv = in_v; gw = in_d; end
                    end
            G_FILL: if (f_room) begin gv = 1'b1; gw = 64'd0; end
            G_TAIL: if (f_room) begin gv = 1'b1;
                        gw = (hi == 3'd0) ? {hb[1][31:0], MAGIC_E} : (hi == 3'd1) ? {32'd0, ~crc} : 64'd0; end
            default: ;
        endcase
    end

    reg  [3:0]  dinc;
    always @(posedge aclk) begin
        push <= 1'b0;
        sg_start <= 1'b0;
        dinc = ext_drop;
        if (rst || cmd_rst) begin
            gs <= G_HDR; hi <= 3'd0; pay_w <= 32'd0; pad <= 1'b0; no_last <= 1'b0; abort_r <= 1'b0; hdr_out <= 1'b0; crc <= 32'hFFFF_FFFF;
            half <= 1'b0; lo <= 64'd0;
            w_pos <= 32'd0; drop_cnt <= 32'd0; rec_cnt <= 32'd0; peak <= 32'd0; err_stat <= 32'd0; err <= 1'b0;
            rec_len <= 32'd0; need <= 32'd0; e_len_l <= 32'd0; w_start <= 32'd0; pos_l <= 32'd0;
        end else begin
            if (gv) begin
                if (!half) begin lo <= gw; half <= 1'b1; end
                else begin pdata <= {gw, lo}; push <= 1'b1; half <= 1'b0; end
            end
            case (gs)
                G_HDR: if (in_go) begin
                    hb[hi] <= in_d;
                    hi <= hi + 3'd1;
                    if (in_l) hi <= 3'd0;                                  // 8 語より短い（来ないはず）: 捨てる
                    else if (hi == 3'd7) gs <= G_DEC;
                end
                G_DEC: begin
                    rec_len <= 32'd128 + hb[7][31:0];
                    pad     <= (32'd128 + hb[7][31:0]) > e_len;
                    e_len_l <= e_len;
                    pos_l   <= pos;
                    need    <= 32'd128 + hb[7][31:0] + (((32'd128 + hb[7][31:0]) > e_len) ? e_len : 32'd0);
                    w_start <= w_pos;
                    pay_w   <= {3'd0, hb[7][31:3]};
                    abort_r <= 1'b0;
                    crc     <= 32'hFFFF_FFFF;
                    hi      <= 3'd0;
                    gs      <= G_WAIT;
                end
                G_WAIT: begin
                    if (!en || err || need > size || need > size - used || pay_w == 32'd0) begin
                        if (en) dinc = dinc + 4'd1;
                        gs <= G_DISC;
                    end else begin
                        sg_start <= 1'b1;
                        hdr_out <= 1'b1;
                        gs <= pad ? G_PAD : G_REC;
                    end
                end
                G_DISC: if (in_go && in_l) begin gs <= G_HDR; hi <= 3'd0; end
                G_PAD: if (gv) begin
                    hi <= hi + 3'd1;
                    if (hi == 3'd7) gs <= G_REC;
                end
                G_REC: if (gv) begin
                    crc <= crc64(crc, gw);
                    if (hdr_out) begin
                        hi <= hi + 3'd1;
                        if (hi == 3'd7) hdr_out <= 1'b0;
                    end else begin
                        pay_w <= pay_w - 32'd1;
                        // tlast と長さが合わない（壊れた入口。rec_fr からは来ないはず）も捨てる:
                        //   tlast が早い → 残りを 0 で埋めて尾へ（書き手は長さのぶんの拍を待っている）
                        //   tlast が来ない → 尾へ。入口の残りは次のヘッダの前に G_DISC で捨てる
                        if (in_l || pay_w == 32'd1) begin
                            abort_r <= in_u || !(in_l && pay_w == 32'd1);
                            no_last <= !in_l;
                            gs <= (in_l && pay_w != 32'd1) ? G_FILL : G_TAIL;
                        end
                    end
                end
                G_FILL: if (gv) begin
                    crc <= crc64(crc, gw);
                    pay_w <= pay_w - 32'd1;
                    if (pay_w == 32'd1) gs <= G_TAIL;
                end
                G_TAIL: if (gv) begin
                    hi <= hi + 3'd1;
                    if (hi == 3'd7) gs <= G_FIN;
                end
                G_FIN: if (seg_done) begin
                    if (bad_seen) begin
                        if (!err) err_stat <= {w_start[31:6], 4'd0, bad_resp};
                        err <= 1'b1;
                        dinc = dinc + 4'd1;
                    end else if (abort_r) begin
                        dinc = dinc + 4'd1;
                    end else begin
                        w_pos   <= w_pos + need;
                        rec_cnt <= rec_cnt + 32'd1;
                        if (w_pos + need - r_pos > peak) peak <= w_pos + need - r_pos;
                    end
                    gs <= no_last ? G_DISC : G_HDR; hi <= 3'd0; no_last <= 1'b0;
                end
                default: gs <= G_HDR;
            endcase
            if (dinc != 4'd0) drop_cnt <= (drop_cnt > 32'hFFFF_FFF0) ? 32'hFFFF_FFFF : drop_cnt + dinc;
        end
    end

    // =====================================================================
    // 書き手（AW・W・B）
    // =====================================================================
    localparam [1:0] A_IDLE = 2'd0, A_BURST = 2'd1, A_NEXT = 2'd2, A_DRAIN = 2'd3;
    reg  [1:0]  as;
    reg         seg1;                       // 今の区間（0 = PAD、1 = レコード）
    reg  [31:0] off, left;
    reg  [4:0]  blen;                       // 今のバーストの拍
    reg  [4:0]  wcnt;                       // 今のバーストの残りの W
    reg         aw_done;
    reg  [8:0]  ob;                         // BRESP 待ちのバースト
    wire [48:0] baddr = base[48:0] + {17'd0, off};
    wire [4:0]  to256 = 5'd16 - {1'b0, baddr[7:4]};
    wire [4:0]  bl_c  = (left < to256) ? left[4:0] : to256;     // ≦ 16（left は 4 の倍数）
    assign m_axi_awaddr  = baddr_q;
    reg  [48:0] baddr_q;
    assign m_axi_awlen   = {3'd0, blen - 5'd1};
    assign m_axi_awsize  = 3'b100;          // 16 バイト
    assign m_axi_awburst = 2'b01;           // INCR
    assign m_axi_awlock  = 1'b0;
    assign m_axi_awcache = 4'b0011;
    assign m_axi_awprot  = 3'b000;
    assign m_axi_awqos   = 4'd0;
    assign m_axi_wdata   = fout;
    assign m_axi_wstrb   = 16'hFFFF;
    assign m_axi_wvalid  = (as == A_BURST) && (wcnt != 5'd0) && fov;
    assign m_axi_wlast   = (wcnt == 5'd1);
    assign m_axi_bready  = 1'b1;
    assign wgo = m_axi_wvalid && m_axi_wready;
    wire   bgo = m_axi_bvalid;
    wire   awgo = m_axi_awvalid && m_axi_awready;
    assign seg_done = (as == A_DRAIN) && (ob == 9'd0);
    assign busy = (gs != G_HDR) || (hi != 3'd0) || (as != A_IDLE);

    always @(posedge aclk) begin
        if (rst || cmd_rst) begin
            as <= A_IDLE; seg1 <= 1'b0; off <= 32'd0; left <= 32'd0; blen <= 5'd0; wcnt <= 5'd0; aw_done <= 1'b0;
            ob <= 9'd0; m_axi_awvalid <= 1'b0; bad_seen <= 1'b0; bad_resp <= 2'd0; baddr_q <= 49'd0;
        end else begin
            ob <= ob + (awgo ? 9'd1 : 9'd0) - (bgo ? 9'd1 : 9'd0);
            if (bgo && m_axi_bresp != 2'b00 && !bad_seen) begin bad_seen <= 1'b1; bad_resp <= m_axi_bresp; end
            if (awgo) begin m_axi_awvalid <= 1'b0; aw_done <= 1'b1; end
            if (wgo) wcnt <= wcnt - 5'd1;
            case (as)
                A_IDLE: if (sg_start) begin
                    bad_seen <= 1'b0;
                    seg1 <= !pad;
                    off  <= pos_l;
                    left <= pad ? 32'd4 : (rec_len >> 4);
                    as   <= A_NEXT;
                end
                A_NEXT: begin
                    if (left == 32'd0) begin
                        if (!seg1) begin seg1 <= 1'b1; off <= 32'd0; left <= rec_len >> 4; end
                        else as <= A_DRAIN;
                    end else if (fav >= {{(FAW-4){1'b0}}, bl_c}) begin
                        blen <= bl_c; wcnt <= bl_c; baddr_q <= baddr;
                        m_axi_awvalid <= 1'b1; aw_done <= 1'b0;
                        off <= off + {23'd0, bl_c, 4'd0};
                        left <= left - {27'd0, bl_c};
                        as <= A_BURST;
                    end
                end
                A_BURST: if ((aw_done || awgo) && (wcnt == 5'd0 || (wcnt == 5'd1 && wgo))) as <= A_NEXT;
                A_DRAIN: if (ob == 9'd0 && gs == G_FIN) as <= A_IDLE;
                default: as <= A_IDLE;
            endcase
        end
    end
endmodule
