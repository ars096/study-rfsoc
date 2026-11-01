// SPDX-License-Identifier: BSD-3-Clause
// proj028 C-4 — corner turn の読み手。ct_wr がチャンク c を閉じたら、ch k = 0..31 の順に
//   「前のチャンクの末尾 HB バイト（c ≧ 1 のとき）→ チャンク c の本体 CHS バイト」を 64 拍のバーストで読み、AXI4-Stream で出す
// 番地（ct_wr と同じ配置）: 面の頭 P(c) = BASE ＋ (c mod NPLANE)·PLANE_STRIDE、ch k の本体 = P(c) ＋ k·CHS、末尾 = P(c − 1) ＋ k·CHS ＋ CHS − HB
// 出口: 512 bit（32 サンプル）、tuser = {c[15:0], k[4:0], 末尾 1 / 本体 0}（22 bit）、tlast = ch の最後の拍（本体の最後）
// 読み途中に次のチャンクが閉じたら 1 つだけ待たせる。2 つ溜まったら捨てて数える（粘着の FLAGS）
// DSP のクロック（256 MHz）で動く。MIG とは SmartConnect で乗り換える
//
// レジスタ（AXI4-Lite、リセット中は ready を出さない）:
//   0x00 ID  0x04 CTRL: [0] RUN（0 → 1 で数えを消す）  0x08 BASE  0x0C CHSTRIDE  0x10 PLANE_STRIDE  0x14 NPLANE  0x18 HB（64·64 の倍数）
//   0x20 STATUS: [0] 読み途中 [1] 待ち在り  0x24 DONE（読み終えたチャンクの数）  0x28 DROP（捨てたチャンクの数）  0x2C FLAGS: [0] 捨てた [1] RRESP ≠ 0
`default_nettype none
module ct_rd #(
    parameter integer AW  = 32,
    parameter integer IDW = 4,
    parameter integer BL  = 64,                    // バーストの拍数
    parameter integer NOUT = 4,                    // 先に出すバーストの数（溜めの中 ＋ 来る予定 ≦ NOUT·BL 拍）。1 は直す前（sim の陽性対照）
    parameter [31:0]  ID  = 32'h0280_00C4
) (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:m_axi:m_axis, ASSOCIATED_RESET aresetn" *)
    input  wire           clk,
    input  wire           aresetn,
    input  wire           chunk_done,
    input  wire [31:0]    chunk_idx,
    // AXI4（読みだけ）
    output wire [IDW-1:0] m_axi_arid,
    output reg  [AW-1:0]  m_axi_araddr,
    output wire [7:0]     m_axi_arlen,
    output wire [2:0]     m_axi_arsize,
    output wire [1:0]     m_axi_arburst,
    output wire           m_axi_arlock,
    output wire [3:0]     m_axi_arcache,
    output wire [2:0]     m_axi_arprot,
    output wire [3:0]     m_axi_arqos,
    output reg            m_axi_arvalid,
    input  wire           m_axi_arready,
    input  wire [IDW-1:0] m_axi_rid,
    input  wire [511:0]   m_axi_rdata,
    input  wire [1:0]     m_axi_rresp,
    input  wire           m_axi_rlast,
    input  wire           m_axi_rvalid,
    output wire           m_axi_rready,
    // AXI4-Stream（細かい側へ）
    output wire [511:0]   m_axis_tdata,
    output wire [21:0]    m_axis_tuser,
    output wire           m_axis_tlast,
    output wire           m_axis_tvalid,
    input  wire           m_axis_tready,
    // AXI4-Lite
    input  wire [7:0]     s_axi_awaddr,
    input  wire           s_axi_awvalid,
    output wire           s_axi_awready,
    input  wire [31:0]    s_axi_wdata,
    input  wire           s_axi_wvalid,
    output wire           s_axi_wready,
    output reg            s_axi_bvalid,
    output wire [1:0]     s_axi_bresp,
    input  wire           s_axi_bready,
    input  wire [7:0]     s_axi_araddr,
    input  wire           s_axi_arvalid,
    output wire           s_axi_arready,
    output reg  [31:0]    s_axi_rdata,
    output reg            s_axi_rvalid,
    output wire [1:0]     s_axi_rresp,
    input  wire           s_axi_rready
);
    localparam integer FD = 16;                    // 出口の溜め（拍）
    wire rst = ~aresetn;
    assign m_axi_arid = {IDW{1'b0}}; assign m_axi_arlen = BL - 1; assign m_axi_arsize = 3'd6; assign m_axi_arburst = 2'b01;
    assign m_axi_arlock = 1'b0; assign m_axi_arcache = 4'b0011; assign m_axi_arprot = 3'b000; assign m_axi_arqos = 4'd0;

    // ---- 制御 ----
    reg        run;
    reg [31:0] r_base, r_chs, r_ps, r_hb;
    reg [2:0]  r_np;
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !rst;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    wire start = wr_go && s_axi_awaddr[7:2] == 6'h01 && s_axi_wdata[0] && !run;
    always @(posedge clk) begin
        if (rst) begin
            s_axi_bvalid <= 1'b0; run <= 1'b0;
            r_base <= 32'd0; r_chs <= 32'd0; r_ps <= 32'd0; r_hb <= 32'd0; r_np <= 3'd3;
        end else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) begin
                s_axi_bvalid <= 1'b1;
                case (s_axi_awaddr[7:2])
                    6'h01: run <= s_axi_wdata[0];
                    6'h02: r_base <= s_axi_wdata;
                    6'h03: r_chs  <= s_axi_wdata;
                    6'h04: r_ps   <= s_axi_wdata;
                    6'h05: r_np   <= s_axi_wdata[2:0];
                    6'h06: r_hb   <= s_axi_wdata;
                    default: ;
                endcase
            end
        end
    end

    // ---- チャンクの待ち（1 つ）と面の頭 ----
    // 面の頭は chunk_done ごとに PLANE_STRIDE を足して巻き戻す（ct_wr と同じ並び。チャンク 0 が面 0）
    reg        busy, pend, f_drop, f_rresp;
    reg [31:0] pend_c, cur_c, n_done, n_drop;
    reg [31:0] pb_next, pb_pend, pb_ppend, pb_last;   // 面の頭: 次に閉じるチャンク・待ち・待ちの前・直前に閉じたチャンク
    reg        has_prev_pend, has_prev;
    reg [2:0]  pm;
    // 読みの並び: ch k、区間（0 = 末尾、1 = 本体）、区間の中の位置
    reg [5:0]  ck;                   // 0..32
    reg        seg;
    reg [31:0] off;
    reg [31:0] chb, chp;             // ch k の本体の頭（P(c) ＋ k·CHS）と末尾の頭（P(c − 1) ＋ k·CHS ＋ CHS − HB）。掛け算をやめて ch ごとに CHS を足す（256 MHz に入らなかった）
    reg [3:0]  outs;                 // 出した AR のうち R を受け終えていない本数
    reg [5:0]  room;                 // 溜めの空き − 出した AR の拍（拍 / BL の単位で数える）
    wire       seg_end = seg ? (off + BL * 64 >= r_chs) : (off + BL * 64 >= r_hb);   // 区間の最後のバースト（本体 CHS・末尾 HB）
    wire       ar_fire = m_axi_arvalid && m_axi_arready;
    // 溜め
    reg [511:0] fd [0:FD-1];
    reg [21:0]  fu [0:FD-1];
    reg         fl [0:FD-1];
    reg [4:0]   fn;
    reg [3:0]   fh, ft;
    wire r_fire = m_axi_rvalid && m_axi_rready;
    wire o_fire = m_axis_tvalid && m_axis_tready;
    // R の拍に付ける印は AR を出した順に溜める（読みの区間・ch・最後の拍か）
    reg [21:0] tq_u [0:15];
    reg        tq_l [0:15];
    reg [3:0]  tq_h, tq_t;
    reg [7:0]  rbeat;
    // 出した AR の拍と溜めの拍の合計が FD を超えないように AR を出す
    reg [11:0] committed;            // 溜めの中 ＋ 来る予定の拍
    // 溜めは FD 拍、ただし R を止めて待たせるので NOUT バースト分まで先に出す。
    //   F-5d（実機）: 前は上限が FD·4 = 64 = BL で、溜めが空になるまで次の AR を出せず（同時に 1 本）、往復の待ちが隙間になって
    //   読みが ≒ 4.6 GB/s（1 チャンク 297 ms > 286.72 ms）に留まった
    wire can_ar = busy && ck != 6'd32 && (committed + BL <= NOUT * BL) && outs < 4'd8;
    assign m_axi_rready = (fn < FD);
    always @(posedge clk) begin
        if (rst || start) begin
            busy <= 1'b0; pend <= 1'b0; n_done <= 32'd0; n_drop <= 32'd0; f_drop <= 1'b0; f_rresp <= 1'b0;
            pb_next <= r_base; pb_last <= r_base; pm <= 3'd0; has_prev_pend <= 1'b0; has_prev <= 1'b0;
            m_axi_arvalid <= 1'b0; ck <= 6'd0; seg <= 1'b0; off <= 32'd0; outs <= 4'd0; committed <= 12'd0;
            fn <= 5'd0; fh <= 4'd0; ft <= 4'd0; tq_h <= 4'd0; tq_t <= 4'd0; rbeat <= 8'd0;
        end else begin
            // チャンクが閉じた: 面の頭を進める
            if (chunk_done && run) begin
                pb_last <= pb_next;
                if (pm == r_np - 3'd1) begin pm <= 3'd0; pb_next <= r_base; end
                else begin pm <= pm + 3'd1; pb_next <= pb_next + r_ps; end
                if (!busy && !pend) begin end
                else if (!pend) begin pend <= 1'b1; pend_c <= chunk_idx; pb_pend <= pb_next; pb_ppend <= pb_last; has_prev_pend <= (chunk_idx != 32'd0); end
                else begin n_drop <= n_drop + 32'd1; f_drop <= 1'b1; end
            end
            // 読みを始める（待ちから、または今閉じたチャンクから）
            if (!busy && ((chunk_done && run && !pend) || pend)) begin
                busy <= 1'b1;
                // 前の面: 待ちからなら待ちに入れたときの「直前に閉じたチャンク」、今閉じたチャンクなら今の pb_last（どちらも NBA の前の値）
                if (pend) begin cur_c <= pend_c; chb <= pb_pend; chp <= pb_ppend + r_chs - r_hb; has_prev <= has_prev_pend; pend <= 1'b0; end
                else begin cur_c <= chunk_idx; chb <= pb_next; chp <= pb_last + r_chs - r_hb; has_prev <= (chunk_idx != 32'd0); end
                ck <= 6'd0; off <= 32'd0;
                seg <= 1'b0;             // 末尾から（無ければ下で本体へ）
            end
            // 区間の選び: 末尾が無い（チャンク 0 か HB = 0）なら本体へ
            if (busy && ck != 6'd32 && !seg && (!has_prev || r_hb == 32'd0) && off == 32'd0 && !m_axi_arvalid) seg <= 1'b1;
            // AR
            if (ar_fire) begin
                m_axi_arvalid <= 1'b0;
                if (seg_end) begin
                    off <= 32'd0;
                    if (!seg) seg <= 1'b1;
                    else begin seg <= 1'b0; ck <= ck + 6'd1; chb <= chb + r_chs; chp <= chp + r_chs; end
                end else off <= off + BL * 64;
            end else if (!m_axi_arvalid && can_ar && !(!seg && (!has_prev || r_hb == 32'd0))) begin
                m_axi_arvalid <= 1'b1;
                m_axi_araddr  <= seg ? (chb + off) : (chp + off);
                tq_u[tq_t] <= {cur_c[15:0], ck[4:0], ~seg};
                tq_l[tq_t] <= seg && (off + BL * 64 >= r_chs);
                tq_t <= tq_t + 4'd1;
            end
            outs <= outs + (ar_fire ? 4'd1 : 4'd0) - ((r_fire && m_axi_rlast) ? 4'd1 : 4'd0);
            committed <= committed + ((!m_axi_arvalid && can_ar && !(!seg && (!has_prev || r_hb == 32'd0))) ? BL[11:0] : 12'd0) - (o_fire ? 12'd1 : 12'd0);
            // R → 溜め
            if (r_fire) begin
                fd[ft] <= m_axi_rdata;
                fu[ft] <= tq_u[tq_h];
                fl[ft] <= tq_l[tq_h] && m_axi_rlast;
                ft <= ft + 4'd1;
                if (m_axi_rlast) tq_h <= tq_h + 4'd1;
                if (m_axi_rresp != 2'b00) f_rresp <= 1'b1;
            end
            if (o_fire) fh <= fh + 4'd1;
            fn <= fn + (r_fire ? 5'd1 : 5'd0) - (o_fire ? 5'd1 : 5'd0);
            // チャンクを読み終えた: 全部の AR を出し、全部の拍を出口へ
            if (busy && ck == 6'd32 && outs == 4'd0 && fn == 5'd0 && !m_axi_arvalid && !(chunk_done && run) ) begin
                busy <= 1'b0; n_done <= n_done + 32'd1;
            end
        end
    end
    assign m_axis_tvalid = (fn != 5'd0);
    assign m_axis_tdata  = fd[fh];
    assign m_axis_tuser  = fu[fh];
    assign m_axis_tlast  = fl[fh];

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
                    6'h01: s_axi_rdata <= {31'd0, run};
                    6'h02: s_axi_rdata <= r_base;
                    6'h03: s_axi_rdata <= r_chs;
                    6'h04: s_axi_rdata <= r_ps;
                    6'h05: s_axi_rdata <= {29'd0, r_np};
                    6'h06: s_axi_rdata <= r_hb;
                    6'h08: s_axi_rdata <= {30'd0, pend, busy};
                    6'h09: s_axi_rdata <= n_done;
                    6'h0A: s_axi_rdata <= n_drop;
                    6'h0B: s_axi_rdata <= {30'd0, f_rresp, f_drop};
                    default: s_axi_rdata <= 32'hDEAD_BEEF;
                endcase
            end
        end
    end
endmodule
`default_nettype wire
