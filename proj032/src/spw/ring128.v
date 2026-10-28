// SPDX-License-Identifier: BSD-3-Clause
//
// ring128 — PL が書くリング、入口 128 bit の 1 本（proj032 K-2。proj028 の s45_ring（proj021 手順 2-2a）を写して入口を広げた）
//
// s45_ring の入口は 64 bit（1 語 / クロック = 2 GB/s）で、SpW のダンプの山（ADC あたり 3.07 GB/s、K-1・D-3）を受けられない。変えたところ:
//   - 入口は AXI4-Stream 128 bit の 1 本（受け手 dsink がレコード単位で機関を順番に。rec_arb は使わない）。tuser なし（捨てる印は無い）
//     レコード = 頭 4 拍（u64 × 8。w7 = 拍 3 の [95:64] = 本体のバイト数 P、16 の倍数）＋ 本体 P / 16 拍（最後の拍で tlast）
//   - CRC-32 は 128 bit を 1 クロック（crc128。係数は tools/crc128_masks.py が zlib.crc32 と照らして作る）
//   - 尾（4 拍）の拍 0 に CRC が入るので、本体の最後の拍が CRC に入るまで 2 クロック待つ（G_TW）
//   - バーストは ≦ 64 拍（1 KiB の境で切る。s45_ring は 16 拍・256 B）。D-3: 口 1 本は 4.1 GB/s まで出る
//   - 捨てたダンプの数（受け手の溜めが溢れた: ext_drop）を DROP_CNT に足し、0x30 EXT_CNT にも別に数える
// 1 レコードの流れ・PAD・空き・捨てる・BRESP の扱い・レジスタは s45_ring と同じ（その頭のコメント）。
// レジスタ: 0x00 IF_ID / 0x04 CTRL / 0x08・0C BASE / 0x10 SIZE（2 の冪）/ 0x14 W / 0x18 R / 0x1C DROP_CNT / 0x20 REC_CNT / 0x24 PEAK /
//   0x28 ERR_STAT / 0x2C PROJ / 0x30 EXT_CNT（受け手で捨てたダンプ）
`timescale 1ns / 1ps

module ring128 #(
    parameter integer NX       = 3,              // ext_drop の本数（機関）
    parameter integer BIT_KIND = 5,
    parameter integer BIT_REV  = 1,
    parameter integer PROJ     = 3277312,        // = 0x0032_0200
    parameter integer FDEPTH   = 512             // 書き手の FIFO（拍）
) (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:m_axi:s_axis, ASSOCIATED_RESET aresetn" *)
    input  wire              aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire              aresetn,
    input  wire [127:0]      s_axis_tdata,
    input  wire              s_axis_tvalid,
    output wire              s_axis_tready,
    input  wire              s_axis_tlast,
    input  wire [NX-1:0]     ext_drop,
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
    reg rstn_q1 = 1'b0, rstn_q2 = 1'b0;      // proj021 2-2a: リセットを 2 段受けてから配る（s45_core と同じ理由）
    (* max_fanout = 50 *) reg rstn_l = 1'b0;
    always @(posedge aclk) begin rstn_q1 <= aresetn; rstn_q2 <= rstn_q1; rstn_l <= rstn_q2; end
    wire rst = ~rstn_l;

    // =====================================================================
    // レジスタ
    // =====================================================================
    reg         en, err;
    reg  [63:0] base;
    reg  [31:0] size, w_pos, r_pos, drop_cnt, rec_cnt, peak, err_stat;
    reg  [31:0] ext_cnt;                     // proj032: 受け手で捨てたダンプ
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
                    10'h00C: s_axi_rdata <= ext_cnt;
                    default: s_axi_rdata <= 32'd0;
                endcase
            end
        end
    end

    // =====================================================================
    // 入口と、受け手で捨てた数
    // =====================================================================
    wire [127:0] in_d = s_axis_tdata;
    wire         in_v = s_axis_tvalid, in_l = s_axis_tlast;
    reg          in_r;
    assign s_axis_tready = in_r;
    wire         in_go = in_v && in_r;
    reg  [3:0]   ext_n;
    integer      xi;
    always @(posedge aclk) begin
        ext_n = 4'd0;
        for (xi = 0; xi < NX; xi = xi + 1) ext_n = ext_n + {3'd0, ext_drop[xi]};
    end
    reg  [3:0]   ext_drop_q;
    always @(posedge aclk) ext_drop_q <= ext_n;

    // =====================================================================
    // CRC-32（zlib）。128 bit を 1 クロック。バイトの順 = little endian = bit 0 から
    // =====================================================================
    // tools/crc128_masks.py が作った（zlib.crc32 と 200 通り照らした）
    function [31:0] crc128(input [31:0] c, input [127:0] d);
        begin
            crc128[ 0] = ^(c & 32'hEB46DE2F) ^ ^(d & 128'h04D101DF481B4E5AF182FA07EB46DE2F);
            crc128[ 1] = ^(c & 32'hD68DBC5E) ^ ^(d & 128'h09A203BE90369CB5E305F40FD68DBC5E);
            crc128[ 2] = ^(c & 32'hAD1B78BC) ^ ^(d & 128'h1344077D206D396BC60BE81FAD1B78BC);
            crc128[ 3] = ^(c & 32'h5A36F178) ^ ^(d & 128'h26880EFA40DA72D78C17D03F5A36F178);
            crc128[ 4] = ^(c & 32'hB46DE2F1) ^ ^(d & 128'h4D101DF481B4E5AF182FA07EB46DE2F1);
            crc128[ 5] = ^(c & 32'h68DBC5E2) ^ ^(d & 128'h9A203BE90369CB5E305F40FD68DBC5E2);
            crc128[ 6] = ^(c & 32'h3AF155EA) ^ ^(d & 128'h3091760D4EC8D8E6913C7BFD3AF155EA);
            crc128[ 7] = ^(c & 32'h75E2ABD5) ^ ^(d & 128'h6122EC1A9D91B1CD2278F7FA75E2ABD5);
            crc128[ 8] = ^(c & 32'hEBC557AB) ^ ^(d & 128'hC245D8353B23639A44F1EFF4EBC557AB);
            crc128[ 9] = ^(c & 32'h3CCC7178) ^ ^(d & 128'h805AB1B53E5D896E786125EE3CCC7178);
            crc128[10] = ^(c & 32'h92DE3CDE) ^ ^(d & 128'h046462B534A05C860140B1DB92DE3CDE);
            crc128[11] = ^(c & 32'h25BC79BC) ^ ^(d & 128'h08C8C56A6940B90C028163B725BC79BC);
            crc128[12] = ^(c & 32'h4B78F379) ^ ^(d & 128'h11918AD4D28172180502C76E4B78F379);
            crc128[13] = ^(c & 32'h96F1E6F2) ^ ^(d & 128'h232315A9A502E4300A058EDC96F1E6F2);
            crc128[14] = ^(c & 32'h2DE3CDE4) ^ ^(d & 128'h46462B534A05C860140B1DB92DE3CDE4);
            crc128[15] = ^(c & 32'h5BC79BC9) ^ ^(d & 128'h8C8C56A6940B90C028163B725BC79BC9);
            crc128[16] = ^(c & 32'h5CC9E9BC) ^ ^(d & 128'h1DC9AC92600C6FDAA1AE8CE35CC9E9BC);
            crc128[17] = ^(c & 32'hB993D378) ^ ^(d & 128'h3B935924C018DFB5435D19C6B993D378);
            crc128[18] = ^(c & 32'h7327A6F0) ^ ^(d & 128'h7726B2498031BF6A86BA338D7327A6F0);
            crc128[19] = ^(c & 32'hE64F4DE1) ^ ^(d & 128'hEE4D649300637ED50D74671AE64F4DE1);
            crc128[20] = ^(c & 32'h27D845EC) ^ ^(d & 128'hD84BC8F948DDB3F0EB6A343227D845EC);
            crc128[21] = ^(c & 32'hA4F655F7) ^ ^(d & 128'hB446902DD9A029BB27569263A4F655F7);
            crc128[22] = ^(c & 32'hA2AA75C1) ^ ^(d & 128'h6C5C2184FB5B1D2CBF2FDEC0A2AA75C1);
            crc128[23] = ^(c & 32'h4554EB82) ^ ^(d & 128'hD8B84309F6B63A597E5FBD814554EB82);
            crc128[24] = ^(c & 32'h61EF092A) ^ ^(d & 128'hB5A187CCA5773AE80D3D810561EF092A);
            crc128[25] = ^(c & 32'h2898CC7B) ^ ^(d & 128'h6F920E4602F53B8AEBF9F80D2898CC7B);
            crc128[26] = ^(c & 32'h513198F7) ^ ^(d & 128'hDF241C8C05EA7715D7F3F01A513198F7);
            crc128[27] = ^(c & 32'h4925EFC1) ^ ^(d & 128'hBA9938C743CFA0715E651A334925EFC1);
            crc128[28] = ^(c & 32'h790D01AC) ^ ^(d & 128'h71E37051CF840EB84D48CE61790D01AC);
            crc128[29] = ^(c & 32'hF21A0359) ^ ^(d & 128'hE3C6E0A39F081D709A919CC2F21A0359);
            crc128[30] = ^(c & 32'h0F72D89C) ^ ^(d & 128'hC35CC098760B74BBC4A1C3820F72D89C);
            crc128[31] = ^(c & 32'hF5A36F17) ^ ^(d & 128'h826880EFA40DA72D78C17D03F5A36F17);
        end
    endfunction

    // =====================================================================
    // FIFO（拍 128 bit。先読みの出口レジスタ付き。s45_ring と同じ）
    // =====================================================================
    reg  [127:0] fmem [0:FDEPTH-1];
    reg  [FAW-1:0] fwp, frp;
    reg  [FAW:0]  fin_mem;
    reg  [127:0]  fout;
    reg           fov;
    reg  [FAW:0]  fav;
    reg           push;
    reg  [127:0]  pdata;
    wire          wgo;
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
    reg f_room;
    always @(posedge aclk) f_room <= (fav < FDEPTH - 6);

    // =====================================================================
    // 拍を作る側（G）: gw（このクロックの拍）→ gq（レジスタ）→ FIFO・CRC
    // =====================================================================
    localparam [3:0] G_HDR = 4'd0, G_DEC = 4'd1, G_WAIT = 4'd2, G_PAD = 4'd3, G_REC = 4'd4, G_TAIL = 4'd5, G_FIN = 4'd6, G_DISC = 4'd7,
                     G_FILL = 4'd8, G_TW = 4'd9;
    reg  [3:0]   gs;
    reg          no_last;
    reg  [127:0] hb [0:3];
    reg  [2:0]   hi;
    reg  [31:0]  pay_w;                      // 本体の残りの拍
    reg  [31:0]  rec_len, need, e_len_l, w_start, pos_l;
    reg          pad, abort_r, hdr_out;
    reg  [31:0]  crc;
    reg  [127:0] gw, gq;
    reg          gv, gc, gqv, gqc;
    wire         seg_done;
    reg          bad_seen;
    reg  [1:0]   bad_resp;
    reg          sg_start;
    wire [31:0]  hdr_p = hb[3][95:64];       // w7 の下位 = 本体のバイト数

    reg  [31:0]  used_q, free_q, pos_q, elen_q;
    always @(posedge aclk) begin
        used_q <= w_pos - r_pos;
        free_q <= size - used_q;
        pos_q  <= w_pos & (size - 32'd1);
        elen_q <= size - pos_q;
    end

    always @* begin
        in_r = 1'b0; gw = 128'd0; gv = 1'b0; gc = 1'b0;
        case (gs)
            G_HDR:  in_r = 1'b1;
            G_DISC: in_r = 1'b1;
            G_PAD:  if (f_room) begin gv = 1'b1;
                        gw = (hi == 3'd0) ? {64'd0, 8'd0, 8'd0, 8'd0, 8'd1, MAGIC_R} : (hi == 3'd3) ? {32'd0, e_len_l, 64'd0} : 128'd0; end
            G_REC:  if (f_room) begin
                        gc = 1'b1;
                        if (hdr_out) begin gv = 1'b1; gw = hb[hi[1:0]]; end
                        else begin in_r = 1'b1; gv = in_v; gw = in_d; end
                    end
            G_FILL: if (f_room) begin gv = 1'b1; gc = 1'b1; gw = 128'd0; end
            G_TAIL: if (f_room) begin gv = 1'b1;
                        // 拍 0 = {w1 = ~CRC, w0 = SEQ・"S45E"}。本体の最後の拍は G_TW の 2 クロックで crc に入っている
                        gw = (hi == 3'd0) ? {32'd0, ~crc, hb[0][95:64], MAGIC_E} : 128'd0; end
            default: ;
        endcase
    end

    reg  [3:0]  dinc, dinc_q;
    always @(posedge aclk) begin
        push <= 1'b0;
        sg_start <= 1'b0;
        dinc = ext_drop_q;
        gq <= gw; gqv <= gv; gqc <= gc;
        if (rst || cmd_rst) begin
            gs <= G_HDR; hi <= 3'd0; pay_w <= 32'd0; pad <= 1'b0; abort_r <= 1'b0; hdr_out <= 1'b0; crc <= 32'hFFFF_FFFF;
            no_last <= 1'b0; gqv <= 1'b0; gqc <= 1'b0;
            w_pos <= 32'd0; drop_cnt <= 32'd0; rec_cnt <= 32'd0; err_stat <= 32'd0; err <= 1'b0; dinc_q <= 4'd0; ext_cnt <= 32'd0;
            rec_len <= 32'd0; need <= 32'd0; e_len_l <= 32'd0; w_start <= 32'd0; pos_l <= 32'd0;
        end else begin
            if (gqv) begin pdata <= gq; push <= 1'b1; end
            if (gqv && gqc) crc <= crc128(crc, gq);
            if (ext_drop_q != 4'd0) ext_cnt <= ext_cnt + {28'd0, ext_drop_q};
            case (gs)
                G_HDR: if (in_go) begin
                    hb[hi[1:0]] <= in_d;
                    hi <= hi + 3'd1;
                    if (in_l) hi <= 3'd0;                                  // 4 拍より短い（来ないはず）: 捨てる
                    else if (hi == 3'd3) gs <= G_DEC;
                end
                G_DEC: begin
                    rec_len <= 32'd128 + hdr_p;
                    pad     <= (32'd128 + hdr_p) > elen_q;
                    e_len_l <= elen_q;
                    pos_l   <= pos_q;
                    need    <= 32'd128 + hdr_p + (((32'd128 + hdr_p) > elen_q) ? elen_q : 32'd0);
                    w_start <= w_pos;
                    pay_w   <= {4'd0, hdr_p[31:4]};
                    abort_r <= 1'b0;
                    crc     <= 32'hFFFF_FFFF;
                    hi      <= 3'd0;
                    gs      <= G_WAIT;
                end
                G_WAIT: begin
                    if (!en || err || need > size || need > free_q || pay_w == 32'd0) begin
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
                    if (hi == 3'd3) begin gs <= G_REC; hi <= 3'd0; end
                end
                G_REC: if (gv) begin
                    if (hdr_out) begin
                        hi <= hi + 3'd1;
                        if (hi == 3'd3) begin hdr_out <= 1'b0; hi <= 3'd0; end
                    end else begin
                        pay_w <= pay_w - 32'd1;
                        if (in_l || pay_w == 32'd1) begin
                            abort_r <= !(in_l && pay_w == 32'd1);
                            no_last <= !in_l;
                            hi <= 3'd0;
                            gs <= (in_l && pay_w != 32'd1) ? G_FILL : G_TW;
                        end
                    end
                end
                G_FILL: if (gv) begin
                    pay_w <= pay_w - 32'd1;
                    if (pay_w == 32'd1) begin gs <= G_TW; hi <= 3'd0; end
                end
                G_TW: begin                                                // 最後の拍が gq → crc に入るのを待つ
                    hi <= hi + 3'd1;
                    if (hi == 3'd1) begin gs <= G_TAIL; hi <= 3'd0; end
                end
                G_TAIL: if (gv) begin
                    hi <= hi + 3'd1;
                    if (hi == 3'd3) gs <= G_FIN;
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
                    end
                    gs <= no_last ? G_DISC : G_HDR; hi <= 3'd0; no_last <= 1'b0;
                end
                default: gs <= G_HDR;
            endcase
            dinc_q <= dinc;
            if (dinc_q != 4'd0 && drop_cnt[31:4] != 28'hFFF_FFFF) drop_cnt <= drop_cnt + {28'd0, dinc_q};
        end
    end
    always @(posedge aclk) begin
        if (rst || cmd_rst) peak <= 32'd0;
        else if (used_q > peak) peak <= used_q;
    end

    // =====================================================================
    // 書き手（AW・W・B）
    //   2026-10-09 ビルド 1 回目: 番地の足し算（BASE ＋ off、49 bit）→ 256 バイト境までの拍 → バーストの長さ → FIFO の拍との比べ、
    //   を 1 クロックでしていて上位に出た。A_CALC（番地）→ A_LEN（長さ）→ A_NEXT（比べて出す）の 3 段に分けた（バースト 1 本に 2 クロック足すだけ）
    // =====================================================================
    localparam [2:0] A_IDLE = 3'd0, A_CALC = 3'd1, A_LEN = 3'd2, A_NEXT = 3'd3, A_BURST = 3'd4, A_DRAIN = 3'd5;
    reg  [2:0]  as;
    reg         seg1;                       // 今の区間（0 = PAD、1 = レコード）
    reg  [31:0] off, left;
    reg  [6:0]  blen;                       // 今のバーストの拍（≦ 64）
    reg  [6:0]  wcnt;                       // 今のバーストの残りの W
    reg         aw_done;
    reg  [8:0]  ob;                         // BRESP 待ちのバースト
    reg  [48:0] baddr_q;
    wire [6:0]  to1k = 7'd64 - {1'b0, baddr_q[9:4]};       // proj032 K-2: 1 KiB の境まで（4 KiB を越えない）
    assign m_axi_awaddr  = baddr_q;
    assign m_axi_awlen   = {1'b0, blen - 7'd1};
    assign m_axi_awsize  = 3'b100;          // 16 バイト
    assign m_axi_awburst = 2'b01;           // INCR
    assign m_axi_awlock  = 1'b0;
    assign m_axi_awcache = 4'b0011;
    assign m_axi_awprot  = 3'b000;
    assign m_axi_awqos   = 4'd0;
    assign m_axi_wdata   = fout;
    assign m_axi_wstrb   = 16'hFFFF;
    assign m_axi_wvalid  = (as == A_BURST) && (wcnt != 7'd0) && fov;
    assign m_axi_wlast   = (wcnt == 7'd1);
    assign m_axi_bready  = 1'b1;
    assign wgo = m_axi_wvalid && m_axi_wready;
    wire   bgo = m_axi_bvalid;
    wire   awgo = m_axi_awvalid && m_axi_awready;
    assign seg_done = (as == A_DRAIN) && (ob == 9'd0);
    assign busy = (gs != G_HDR) || (hi != 3'd0) || (as != A_IDLE);

    always @(posedge aclk) begin
        if (rst || cmd_rst) begin
            as <= A_IDLE; seg1 <= 1'b0; off <= 32'd0; left <= 32'd0; blen <= 7'd0; wcnt <= 7'd0; aw_done <= 1'b0;
            ob <= 9'd0; m_axi_awvalid <= 1'b0; bad_seen <= 1'b0; bad_resp <= 2'd0; baddr_q <= 49'd0;
        end else begin
            ob <= ob + (awgo ? 9'd1 : 9'd0) - (bgo ? 9'd1 : 9'd0);
            if (bgo && m_axi_bresp != 2'b00 && !bad_seen) begin bad_seen <= 1'b1; bad_resp <= m_axi_bresp; end
            if (awgo) begin m_axi_awvalid <= 1'b0; aw_done <= 1'b1; end
            if (wgo) wcnt <= wcnt - 7'd1;
            case (as)
                A_IDLE: if (sg_start) begin
                    bad_seen <= 1'b0;
                    seg1 <= !pad;
                    off  <= pos_l;
                    left <= pad ? 32'd4 : (rec_len >> 4);
                    as   <= A_CALC;
                end
                A_CALC: begin
                    if (left == 32'd0) begin
                        if (!seg1) begin seg1 <= 1'b1; off <= 32'd0; left <= rec_len >> 4; end
                        else as <= A_DRAIN;
                    end else begin
                        baddr_q <= base[48:0] + {17'd0, off};
                        as <= A_LEN;
                    end
                end
                A_LEN: begin
                    blen <= (left < {25'd0, to1k}) ? left[6:0] : to1k;       // ≦ 64（left は 4 の倍数）
                    as <= A_NEXT;
                end
                A_NEXT: if (fav >= {{(FAW-6){1'b0}}, blen}) begin
                    wcnt <= blen;
                    m_axi_awvalid <= 1'b1; aw_done <= 1'b0;
                    off <= off + {21'd0, blen, 4'd0};
                    left <= left - {25'd0, blen};
                    as <= A_BURST;
                end
                A_BURST: if ((aw_done || awgo) && (wcnt == 7'd0 || (wcnt == 7'd1 && wgo))) as <= A_CALC;
                A_DRAIN: if (ob == 9'd0 && gs == G_FIN) as <= A_IDLE;
                default: as <= A_IDLE;
            endcase
        end
    end
endmodule
