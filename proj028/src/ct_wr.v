// SPDX-License-Identifier: BSD-3-Clause
// proj028 C-3 — corner turn の書き手。荒い段の出口（1 ブロック 1 語 512 bit = 32 ch × 16 bit）を ch ごとに並べ替えて DDR へ
//
// 並べ替え: 32 個の銀行（各 16 bit × 2 面 × 32 ch × QB）。ブロック b（群の中、0..32·QB−1）の ch k を銀行 (k + b) mod 32 の番地
//   {面, k, ⌊b/32⌋} に書く。読みは全部の銀行を番地 {面, k, q} で読み、要素 i を銀行 (k + i) mod 32 から取ると ch k のブロック
//   32q + i（i = 0..31）が 1 拍（512 bit、i 番を [16i +: 16]）になる
// 群（32·QB ブロック）が満ちたら ch k = 0..31 の順に QB 拍のバースト。番地 = 面の頭 ＋ 群の位置 ＋ k·CHSTRIDE
//   面の頭: チャンク（GPD 群）ごとに PLANE_STRIDE を足し、NPLANE 面で BASE に戻る。群の位置: 群ごとに QB·64 を足し、チャンクで 0 に
// チャンクの最後の B を受けたら chunk_done（1 拍）と chunk_idx（閉じたチャンクの通し番号、0 から）
// チップ内の 2 面が空く前に次の群が満ちたら溢れ（数えと粘着の FLAGS。データは壊れる）
// DSP のクロック（256 MHz）で動く。MIG とは SmartConnect で乗り換える
//
// レジスタ（AXI4-Lite、リセット中は ready を出さない）:
//   0x00 ID  0x04 CTRL: [0] RUN（0 → 1 で数えを消して走り始める。0 で入口を止め、溜まっている群は書き切る）
//   0x08 BASE  0x0C CHSTRIDE  0x10 PLANE_STRIDE  0x14 GPD  0x18 NPLANE（1..4）
//   0x20 STATUS: [0] busy（溜めに群が在るか書き途中）  0x24 CHUNKS（閉じたチャンクの数）  0x28 OVF（溢れた群の数）
//   0x2C GROUPS（満ちた群の数）  0x30 FLAGS: [0] 溢れ [1] BRESP ≠ 0
`default_nettype none
module ct_wr #(
    parameter integer QB  = 64,
    parameter integer AW  = 32,
    parameter integer IDW = 4,
    parameter [31:0]  ID  = 32'h0280_00C3
) (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi:m_axi, ASSOCIATED_RESET aresetn" *)
    input  wire           clk,
    input  wire           aresetn,
    input  wire           s_valid,
    input  wire [511:0]   s_y,
    output reg            chunk_done,
    output reg  [31:0]    chunk_idx,
    // AXI4（書きだけ）
    output wire [IDW-1:0] m_axi_awid,
    output reg  [AW-1:0]  m_axi_awaddr,
    output wire [7:0]     m_axi_awlen,
    output wire [2:0]     m_axi_awsize,
    output wire [1:0]     m_axi_awburst,
    output wire           m_axi_awlock,
    output wire [3:0]     m_axi_awcache,
    output wire [2:0]     m_axi_awprot,
    output wire [3:0]     m_axi_awqos,
    output reg            m_axi_awvalid,
    input  wire           m_axi_awready,
    output wire [511:0]   m_axi_wdata,
    output wire [63:0]    m_axi_wstrb,
    output wire           m_axi_wlast,
    output wire           m_axi_wvalid,
    input  wire           m_axi_wready,
    input  wire [IDW-1:0] m_axi_bid,
    input  wire [1:0]     m_axi_bresp,
    input  wire           m_axi_bvalid,
    output wire           m_axi_bready,
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
    localparam integer QBW = $clog2(QB);
    localparam integer MAW = 1 + 5 + QBW;           // 銀行の番地 {面, k, q}
    wire rst = ~aresetn;
    assign m_axi_awid = {IDW{1'b0}}; assign m_axi_awlen = QB - 1; assign m_axi_awsize = 3'd6; assign m_axi_awburst = 2'b01;
    assign m_axi_awlock = 1'b0; assign m_axi_awcache = 4'b0011; assign m_axi_awprot = 3'b000; assign m_axi_awqos = 4'd0;
    assign m_axi_wstrb = {64{1'b1}};
    assign m_axi_bready = 1'b1;

    // ---- 制御 ----
    reg        run;
    reg [31:0] r_base, r_chs, r_ps, r_gpd;
    reg [2:0]  r_np;
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !rst;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    wire start = wr_go && s_axi_awaddr[7:2] == 6'h01 && s_axi_wdata[0] && !run;
    always @(posedge clk) begin
        if (rst) begin
            s_axi_bvalid <= 1'b0; run <= 1'b0;
            r_base <= 32'd0; r_chs <= 32'd0; r_ps <= 32'd0; r_gpd <= 32'd1; r_np <= 3'd3;
        end else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) begin
                s_axi_bvalid <= 1'b1;
                case (s_axi_awaddr[7:2])
                    6'h01: run <= s_axi_wdata[0];
                    6'h02: r_base <= s_axi_wdata;
                    6'h03: r_chs  <= s_axi_wdata;
                    6'h04: r_ps   <= s_axi_wdata;
                    6'h05: r_gpd  <= s_axi_wdata;
                    6'h06: r_np   <= s_axi_wdata[2:0];
                    default: ;
                endcase
            end
        end
    end

    // ---- 入口: 回して銀行に書く ----
    reg [4:0]     bq;                // b mod 32
    reg [QBW-1:0] qg;                // ⌊b/32⌋
    reg           wp;                // 書いている面
    reg [1:0]     full;              // 面が満ちて書き出し待ち
    reg [31:0]    gw, pbase, goff, n_grp, n_ovf;
    reg [2:0]     cm;
    reg [31:0]    daddr [0:1];       // 面ごとの「面の頭 ＋ 群の位置」
    reg           f_ovf, f_bresp;
    reg [31:0]    bcnt, n_chunk;
    reg           we1;
    reg [15:0]    wd1 [0:31];
    reg [MAW-1:0] wa1 [0:31];
    wire take = s_valid && run && !rst;
    wire g_end = take && bq == 5'd31 && qg == {QBW{1'b1}};
    integer j;
    reg [4:0] kj;
    always @(posedge clk) begin
        we1 <= take;
        for (j = 0; j < 32; j = j + 1) begin
            kj = j - bq;                                   // (j − b) mod 32
            wd1[j] <= s_y[16 * kj +: 16];
            wa1[j] <= {wp, kj, qg};
        end
    end
    genvar gb;
    reg [15:0] rd2 [0:31];
    reg [MAW-1:0] ra;                // 読みの番地（全部の銀行で同じ）
    reg           re;
    generate for (gb = 0; gb < 32; gb = gb + 1) begin : g_bank
        (* ram_style = "block" *) reg [15:0] mem [0:(1 << MAW) - 1];
        always @(posedge clk) begin
            if (we1) mem[wa1[gb]] <= wd1[gb];
            if (re) rd2[gb] <= mem[ra];
        end
    end endgenerate

    // 群の終わり: 書きは we1 の 1 拍後に銀行に入るので、満ちた印は 2 拍遅らせて立てる
    reg ge1, ge2, gp1, gp2;
    reg [31:0] da1, da2;
    always @(posedge clk) begin
        ge1 <= g_end; ge2 <= ge1; gp1 <= wp; gp2 <= gp1; da1 <= pbase + goff; da2 <= da1;
        if (rst || start) begin
            bq <= 5'd0; qg <= {QBW{1'b0}}; wp <= 1'b0; gw <= 32'd0; pbase <= r_base; goff <= 32'd0; cm <= 3'd0;
            n_grp <= 32'd0; n_ovf <= 32'd0; f_ovf <= 1'b0;
        end else if (take) begin
            {qg, bq} <= {qg, bq} + 1'b1;
            if (g_end) begin
                wp <= ~wp;
                if (full[~wp]) begin n_ovf <= n_ovf + 32'd1; f_ovf <= 1'b1; end
                if (gw == r_gpd - 32'd1) begin
                    gw <= 32'd0; goff <= 32'd0;
                    if (cm == r_np - 3'd1) begin cm <= 3'd0; pbase <= r_base; end
                    else begin cm <= cm + 3'd1; pbase <= pbase + r_ps; end
                end else begin
                    gw <= gw + 32'd1; goff <= goff + QB * 64;
                end
            end
        end
        if (ge2) begin n_grp <= n_grp + 32'd1; daddr[gp2] <= da2; end
    end

    // ---- 書き出し: 面 rp を ch 0..31 の順に ----
    reg        rp;
    reg [5:0]  ak;                   // 出した AW の数（この面、0..32）
    reg [5:0]  rk;                   // 読んでいる ch（0..32）
    reg [QBW-1:0] rq;
    reg [3:0]  outs;                 // B を待つバースト
    reg [31:0] aw_next;
    wire draining = full[rp];
    wire rd_done  = (rk == 6'd32);
    wire aw_done  = (ak == 6'd32);
    // W の溜め（4 段）と読みの段（銀行 1 拍 ＋ 回し 1 拍）
    reg [511:0] fq [0:3];
    reg [2:0]   fn;                  // 溜めの数
    reg [1:0]   fh, ft;
    reg [2:0]   infl;                // 読み途中の数（re・re1・re2 の段、0..4）
    reg         re1, re2;
    reg [4:0]   rk1, rk2;
    reg [511:0] rot;
    wire can_rd = draining && !rd_done && ({1'b0, fn} + {1'b0, infl}) < 4'd4;   // 溜め 4 段を溢れさせない
    wire w_fire = m_axi_wvalid && m_axi_wready;
    // W は AW を受けてもらったバーストの分だけ出す（AXI4 は W が先でもよいが、受け手に頼らない。QB 64 の sim で模型が W の先行を見つけた）
    reg [3:0]   aw_ahead;            // AW を受けてもらって W を出し終えていないバースト
    assign m_axi_wvalid = (fn != 3'd0) && (aw_ahead != 4'd0);
    assign m_axi_wdata  = fq[fh];
    reg [QBW-1:0] wq;
    assign m_axi_wlast  = (wq == {QBW{1'b1}});
    wire aw_fire = m_axi_awvalid && m_axi_awready;
    integer i;
    always @(posedge clk) begin
        // 銀行の読み（re の次の拍に rd2）→ 回し（rot）→ 溜めへ
        re  <= can_rd;
        if (can_rd) ra <= {rp, rk[4:0], rq};
        re1 <= re; rk1 <= ra[QBW +: 5];
        if (re1) for (i = 0; i < 32; i = i + 1) rot[16 * i +: 16] <= rd2[(rk1 + i) & 31];
        re2 <= re1;
    end
    always @(posedge clk) begin
        if (rst || start) begin
            full <= 2'b00; rp <= 1'b0; ak <= 6'd0; rk <= 6'd0; rq <= {QBW{1'b0}}; outs <= 4'd0; m_axi_awvalid <= 1'b0;
            fn <= 3'd0; fh <= 2'd0; ft <= 2'd0; infl <= 3'd0; wq <= {QBW{1'b0}}; aw_ahead <= 4'd0;
            chunk_done <= 1'b0; chunk_idx <= 32'hFFFF_FFFF; f_bresp <= 1'b0;
        end else begin
            if (ge2) full[gp2] <= 1'b1;
            // 読みの数え
            if (can_rd) begin
                if (rq == {QBW{1'b1}}) begin rq <= {QBW{1'b0}}; rk <= rk + 6'd1; end else rq <= rq + 1'b1;
            end
            infl <= infl + (can_rd ? 3'd1 : 3'd0) - (re2 ? 3'd1 : 3'd0);
            // 溜め
            if (re2) begin fq[ft] <= rot; ft <= ft + 2'd1; end
            fn <= fn + (re2 ? 3'd1 : 3'd0) - (w_fire ? 3'd1 : 3'd0);
            if (w_fire) begin fh <= fh + 2'd1; wq <= wq + 1'b1; end
            // AW（先に出してよいのは 8 本まで）
            if (aw_fire) begin
                m_axi_awvalid <= 1'b0; ak <= ak + 6'd1; aw_next <= aw_next + r_chs;
            end else if (!m_axi_awvalid && draining && !aw_done && outs < 4'd8) begin
                m_axi_awvalid <= 1'b1;
                m_axi_awaddr  <= (ak == 6'd0) ? daddr[rp][AW-1:0] : aw_next[AW-1:0];
                if (ak == 6'd0) aw_next <= daddr[rp];
            end
            outs <= outs + (aw_fire ? 4'd1 : 4'd0) - (m_axi_bvalid ? 4'd1 : 4'd0);
            aw_ahead <= aw_ahead + (aw_fire ? 4'd1 : 4'd0) - ((w_fire && m_axi_wlast) ? 4'd1 : 4'd0);
            // 面を書き切った（全部読んで溜めも空、AW も全部）→ 空ける
            if (draining && rd_done && aw_done && infl == 3'd0 && fn == 3'd0) begin
                full[rp] <= 1'b0; rp <= ~rp; ak <= 6'd0; rk <= 6'd0;
            end
            if (m_axi_bvalid && m_axi_bresp != 2'b00) f_bresp <= 1'b1;
            chunk_done <= 1'b0;
            if (m_axi_bvalid) begin
                if (bcnt == 32 * r_gpd - 1) begin chunk_done <= 1'b1; chunk_idx <= chunk_idx + 32'd1; end
            end
        end
    end
    // B の数え（チャンクで巻き戻す）
    always @(posedge clk) begin
        if (rst || start) begin bcnt <= 32'd0; n_chunk <= 32'd0; end
        else if (m_axi_bvalid) begin
            if (bcnt == 32 * r_gpd - 1) begin bcnt <= 32'd0; n_chunk <= n_chunk + 32'd1; end
            else bcnt <= bcnt + 32'd1;
        end
    end
    wire busy = (full != 2'b00) || (outs != 4'd0) || m_axi_awvalid;

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
                    6'h05: s_axi_rdata <= r_gpd;
                    6'h06: s_axi_rdata <= {29'd0, r_np};
                    6'h08: s_axi_rdata <= {31'd0, busy};
                    6'h09: s_axi_rdata <= n_chunk;
                    6'h0A: s_axi_rdata <= n_ovf;
                    6'h0B: s_axi_rdata <= n_grp;
                    6'h0C: s_axi_rdata <= {30'd0, f_bresp, f_ovf};
                    default: s_axi_rdata <= 32'hDEAD_BEEF;
                endcase
            end
        end
    end
endmodule
`default_nettype wire
