// SPDX-License-Identifier: BSD-3-Clause
//
// spw_core — SpW のコア 1 ADC ぶん（proj032 P-2）: レジスタ（spw_regs、64 KiB）＋ 前段（spw_front）＋ 窓の分光の後段（wsb）＋ ダンプの受け手（dsink）
//   P-6: コアの共通（core_cmn、SAM45-Fine と同じ: ギアボックスの制御・コアの TP・TANCH）＋ レコードの合流（rmux128: 窓のレコードと TP のレコード → リング 1 本）
//
// 外にあるもの（BD）: ギアボックス（s_tdata・gb_*）・time_core（t_now・fire）・PL の DDR（wsb の履歴の枠、m_*）・リング（ring128。m_tdata と drop を渡す）
// 番地の振り分け（取り引き 1 つずつ、g24_s45_core と同じ形）:
//   0x0000–0x007F・0x0100–0x3FFF → core_cmn（IF_ID・…・0x20〜0x5C の CTRL（TP_RUN・TP_ARM・TANCH）・GB_K・GB_STAT・ADC_STAT・ANCH_*・…・0x100〜 TP のレジスタ・0x2000〜 TP のリング）
//   0x0080–0x00FF・0x4000– → spw_regs（CORE_FLAGS・NG・NDUMP・WRST_BAD・WRST_CNT・流れのブロック）。spw_regs の 0x00〜0x18 は届かない（core_cmn が同じ値を返す）
// drop: [E−1:0] 受け手で捨てたダンプ（機関ごと）・[E] 捨てた TP のレコード
// リセット: rst = ハード（レジスタ・粗い PFB）。WRST（spw_regs の wrst）は頭・ddcb・wsb・dsink を最初から（窓の t0 も取り直す）
// 設定は spw_regs の効いている値だけを使う（WRST・RUN で取り込んだもの）
// WRST は水抜きの後（spw_regs の drain → dsink が開いたレコードを送り終えて idle → 設定を取り込みリセット）。リングに切れたレコードを渡さない
`timescale 1ns / 1ps

module spw_core #(
    parameter integer H          = 14,
    parameter integer E          = 3,
    parameter integer S          = 6,
    parameter integer NK         = 8,
    parameter integer W          = 20,
    parameter integer G_L2       = 19,
    parameter integer D          = 1024,
    parameter integer NU         = 2,
    parameter integer ADC        = 0,
    parameter integer PSPLIT     = 1,
    parameter integer DDR_BASE   = 0,
    parameter integer BUILD_TAG  = 0,
    parameter integer BASE_BEATS = 2621440,
    parameter integer BIT_KIND   = 7,
    parameter integer BIT_REV    = 1,
    parameter integer PROJ       = 3277312,     // 0x0032_0200（10 進で書く）
    parameter integer TPN_DEFAULT = 512,
    parameter integer GB_K_RST   = 2
)(
    input  wire                 clk,
    input  wire                 rst,
    // AXI4-Lite（コアの 64 KiB）
    input  wire [15:0]          s_axi_awaddr,
    input  wire                 s_axi_awvalid,
    output wire                 s_axi_awready,
    input  wire [31:0]          s_axi_wdata,
    input  wire                 s_axi_wvalid,
    output wire                 s_axi_wready,
    output wire                 s_axi_bvalid,
    output wire [1:0]           s_axi_bresp,
    input  wire                 s_axi_bready,
    input  wire [15:0]          s_axi_araddr,
    input  wire                 s_axi_arvalid,
    output wire                 s_axi_arready,
    output wire [31:0]          s_axi_rdata,
    output wire                 s_axi_rvalid,
    output wire [1:0]           s_axi_rresp,
    input  wire                 s_axi_rready,
    // ギアボックスの出口
    input  wire [255:0]         s_tdata,
    input  wire                 s_tvalid,
    // ギアボックスの制御と見張り（core_cmn）
    output wire                 gb_hold,
    output wire [1:0]           gb_adj,
    output wire                 gb_dn_rstn,
    output wire [5:0]           gb_k,
    input  wire [31:0]          gb_stat,
    input  wire [31:0]          adc_stat,
    // 時刻
    input  wire [63:0]          t_now,
    input  wire                 fire,
    // PL の DDR（履歴の枠 S..S+NK−1）
    output wire [31:0]          m_awaddr,
    output wire [7:0]           m_awlen,
    output wire                 m_awvalid,
    input  wire                 m_awready,
    output wire [63:0]          m_wdata,
    output wire                 m_wlast,
    output wire                 m_wvalid,
    input  wire                 m_wready,
    input  wire                 m_bvalid,
    output wire [E*32-1:0]      m_araddr,
    output wire [E-1:0]         m_arvalid,
    input  wire [E-1:0]         m_arready,
    input  wire [E*128-1:0]     m_rdata,
    input  wire [E-1:0]         m_rvalid,
    input  wire [E-1:0]         m_rlast,
    // リングへ（ring128 の s_axis・ext_drop）
    output wire [127:0]         m_tdata,
    output wire                 m_tvalid,
    input  wire                 m_tready,
    output wire                 m_tlast,
    output wire [E:0]           drop
);
    // ---- AXI4-Lite の 1 → 2 の振り分け（g24_s45_core と同じ: 取り引き 1 つずつ・全部レジスタで受け渡す）----
    localparam [2:0] S_IDLE = 3'd0, S_WREQ = 3'd1, S_WRSP = 3'd2, S_RREQ = 3'd3, S_RRSP = 3'd4, S_DONE = 3'd5;
    reg  [2:0]  st;
    reg  [15:0] q_addr;
    reg  [31:0] q_wdata;
    reg         q_dst;                     // 0 = core_cmn・1 = spw_regs
    reg         r_bvalid, r_rvalid;
    reg  [31:0] r_rdata;
    function automatic dst(input [15:0] a);
        dst = (a[15:14] != 2'd0) || (a[15:7] == 9'd1);
    endfunction
    wire take_w = (st == S_IDLE) && s_axi_awvalid && s_axi_wvalid;
    wire take_r = (st == S_IDLE) && s_axi_arvalid && !take_w;
    assign s_axi_awready = take_w;
    assign s_axi_wready  = take_w;
    assign s_axi_arready = take_r;
    assign s_axi_bvalid  = r_bvalid;
    assign s_axi_rvalid  = r_rvalid;
    assign s_axi_rdata   = r_rdata;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_rresp   = 2'b00;
    wire d_aw = (st == S_WREQ), d_ar = (st == S_RREQ), d_b = (st == S_WRSP), d_r = (st == S_RRSP);
    wire [1:0]  awr, wr_, bv, arr, rv;
    wire [31:0] rd0, rd1;
    always @(posedge clk) begin
        if (rst) begin
            st <= S_IDLE; q_addr <= 16'd0; q_wdata <= 32'd0; q_dst <= 1'b0; r_bvalid <= 1'b0; r_rvalid <= 1'b0; r_rdata <= 32'd0;
        end else begin
            case (st)
                S_IDLE: if (take_w) begin st <= S_WREQ; q_addr <= s_axi_awaddr; q_wdata <= s_axi_wdata; q_dst <= dst(s_axi_awaddr); end
                        else if (take_r) begin st <= S_RREQ; q_addr <= s_axi_araddr; q_dst <= dst(s_axi_araddr); end
                S_WREQ: if (awr[q_dst] & wr_[q_dst]) st <= S_WRSP;
                S_WRSP: if (bv[q_dst]) begin r_bvalid <= 1'b1; st <= S_DONE; end
                S_RREQ: if (arr[q_dst]) st <= S_RRSP;
                S_RRSP: if (rv[q_dst]) begin r_rvalid <= 1'b1; r_rdata <= q_dst ? rd1 : rd0; st <= S_DONE; end
                S_DONE: begin
                    if (r_bvalid && s_axi_bready) begin r_bvalid <= 1'b0; st <= S_IDLE; end
                    if (r_rvalid && s_axi_rready) begin r_rvalid <= 1'b0; st <= S_IDLE; end
                end
                default: st <= S_IDLE;
            endcase
        end
    end

    wire          wrst, drain, dp_idle, cmd_run, cmd_stop;
    wire [H*6-1:0]  cfg_wk;
    wire [H*32-1:0] cfg_dphi;
    wire [H*3-1:0]  cfg_ns;
    wire [H*2-1:0]  cfg_fl;
    wire [H*4-1:0]  cfg_sl, cfg_g, cfg_sh;
    wire [31:0]   ng, ndump, g0, g0a;
    wire [H*64-1:0] t0;
    wire [E*16-1:0] eng_flags;
    wire [2*E+1:0]  dflags;
    wire [3:0]    sflags;
    wire [5:0]    fflags;
    // WRST の間とその直後は前段の出口を受けない（rst を 1 段そろえる）
    // 最初の WRST が通るまでは前段・wsb・dsink をリセットに留める（既定の設定は全窓が止める窓で、データの道はまだ扱えない。
    //   動かすと ddcb の印が粘着の CORE_FLAGS[4] に残る。P-2 の sim で見つけた）
    reg           cfg_ok, rst_d;
    wire          dp_rst = rst || wrst || !cfg_ok;
    always @(posedge clk) begin
        if (rst) cfg_ok <= 1'b0; else if (wrst) cfg_ok <= 1'b1;
        rst_d <= dp_rst;
    end

    spw_regs #(.H(H), .E(E), .S(S), .NK(NK), .G_L2(G_L2), .BUILD_TAG(BUILD_TAG), .CORE_PORT(ADC), .PSPLIT(PSPLIT), .BASE_BEATS(BASE_BEATS),
              .BIT_KIND(BIT_KIND), .BIT_REV(BIT_REV), .PROJ(PROJ)) u_regs (
        .clk(clk), .rst(rst),
        .s_axi_awaddr(q_addr), .s_axi_awvalid(d_aw && q_dst), .s_axi_awready(awr[1]),
        .s_axi_wdata(q_wdata), .s_axi_wvalid(d_aw && q_dst), .s_axi_wready(wr_[1]),
        .s_axi_bvalid(bv[1]), .s_axi_bresp(), .s_axi_bready(d_b && q_dst),
        .s_axi_araddr(q_addr), .s_axi_arvalid(d_ar && q_dst), .s_axi_arready(arr[1]),
        .s_axi_rdata(rd1), .s_axi_rvalid(rv[1]), .s_axi_rresp(), .s_axi_rready(d_r && q_dst),
        .t_now(t_now), .fire(fire), .wrst(wrst), .drain(drain), .dp_idle(dp_idle),
        .cfg_wk(cfg_wk), .cfg_dphi(cfg_dphi), .cfg_ns(cfg_ns), .cfg_fl(cfg_fl), .cfg_sl(cfg_sl), .cfg_g(cfg_g), .cfg_sh(cfg_sh),
        .ng(ng), .ndump(ndump), .cmd_run(cmd_run), .cmd_stop(cmd_stop),
        .g0(g0a), .t0(t0), .eng_flags(eng_flags), .ddr_flag(|dflags), .sink_flag(|sflags), .front_flag(|fflags));

    wire [E-1:0]   y_v;
    wire [E*4-1:0] y_ch;
    wire [E*W-1:0] y_re, y_im;
    spw_front #(.H(H), .E(E), .PSPLIT(PSPLIT), .BW(W)) u_front (
        .clk(clk), .rst_pfb(rst), .rst(dp_rst),
        .s_tdata(s_tdata), .s_tvalid(s_tvalid),
        .cfg_wk(cfg_wk), .cfg_dphi(cfg_dphi), .cfg_ns(cfg_ns), .cfg_fl(cfg_fl),
        .y_v(y_v), .y_ch(y_ch), .y_re(y_re), .y_im(y_im), .c_re(), .c_im(), .c_v(), .flags(fflags));

    wire [E-1:0]    d_v;
    wire [E*4-1:0]  d_w;
    wire [E*32-1:0] d_k;
    wire [E*12-1:0] d_ch;
    wire [E*64-1:0] d_data;
    wsb #(.H(H), .E(E), .S(S), .W(W), .G_L2(G_L2), .D(D), .NK(NK)) u_wsb (
        .clk(clk), .rst(rst_d), .y_v(y_v & {E{!rst_d}}), .y_ch(y_ch), .y_re(y_re), .y_im(y_im),
        .cfg_ns(cfg_ns), .cfg_fl(cfg_fl), .cfg_sl(cfg_sl), .cfg_sh(cfg_sh), .cfg_g(cfg_g), .ddr_base(DDR_BASE),
        .ng(ng), .ndump(ndump), .cmd_run(cmd_run), .cmd_stop(cmd_stop),
        .go(), .g0(g0), .g0a(g0a), .d_v(d_v), .d_w(d_w), .d_k(d_k), .d_ch(d_ch), .d_data(d_data), .flags(eng_flags), .dflags(dflags),
        .t_now(t_now), .t0(t0),
        .m_awaddr(m_awaddr), .m_awlen(m_awlen), .m_awvalid(m_awvalid), .m_awready(m_awready), .m_wdata(m_wdata), .m_wlast(m_wlast),
        .m_wvalid(m_wvalid), .m_wready(m_wready), .m_bvalid(m_bvalid),
        .m_araddr(m_araddr), .m_arvalid(m_arvalid), .m_arready(m_arready), .m_rdata(m_rdata), .m_rvalid(m_rvalid), .m_rlast(m_rlast));

    wire [127:0] a_d;
    wire         a_v, a_r, a_l;
    wire [63:0]  b_d;
    wire         b_v, b_r, b_l;
    dsink #(.E(E), .H(H), .NU(NU), .G_L2(G_L2), .ADC(ADC)) u_sink (
        .clk(clk), .rst(rst_d), .d_v(d_v), .d_w(d_w), .d_k(d_k), .d_ch(d_ch), .d_data(d_data),
        .cfg_ns(cfg_ns), .cfg_sh(cfg_sh), .cfg_g(cfg_g), .ng(ng), .g0(g0), .g0a(g0a), .t0(t0),
        .m_tdata(a_d), .m_tvalid(a_v), .m_tready(a_r), .m_tlast(a_l), .drop(drop[E-1:0]), .flags(sflags), .drain(drain), .idle(dp_idle));

    // ---- コアの共通（SAM45-Fine と同じ。入力はこのコアの ADC。FFT_N（0x80）は持たない: 0x80 は spw_regs へ振り分ける）----
    core_cmn #(.BUILD_TAG(BUILD_TAG), .TP(1), .TPN_DEFAULT(TPN_DEFAULT), .GB_K_RST(GB_K_RST), .BIT_KIND(BIT_KIND), .BIT_REV(BIT_REV),
               .PROJ(PROJ), .CORE_PORT(ADC), .NSTREAM(H), .BASE_BEATS(BASE_BEATS)) u_cmn (
        .aclk(clk), .aresetn(!rst), .s_axis_tdata(s_tdata), .s_axis_tvalid(s_tvalid),
        .s_axi_awaddr(q_addr), .s_axi_awvalid(d_aw && !q_dst), .s_axi_awready(awr[0]),
        .s_axi_wdata(q_wdata), .s_axi_wvalid(d_aw && !q_dst), .s_axi_wready(wr_[0]),
        .s_axi_bvalid(bv[0]), .s_axi_bready(d_b && !q_dst),
        .s_axi_araddr(q_addr), .s_axi_arvalid(d_ar && !q_dst), .s_axi_arready(arr[0]),
        .s_axi_rdata(rd0), .s_axi_rvalid(rv[0]), .s_axi_rready(d_r && !q_dst),
        .gb_hold(gb_hold), .gb_adj(gb_adj), .gb_dn_rstn(gb_dn_rstn), .gb_k(gb_k), .gb_stat(gb_stat), .adc_stat(adc_stat),
        .t_in(t_now), .go_in(fire), .tev_in(4'd0), .fftn_we(), .fftn_wdata(), .fftn_rd(32'd0),
        .m_axis_rec_tdata(b_d), .m_axis_rec_tvalid(b_v), .m_axis_rec_tready(b_r), .m_axis_rec_tlast(b_l), .m_axis_rec_tuser(),
        .rec_drop(drop[E]));

    // ---- レコードの合流（窓のレコード 128 bit ＋ TP のレコード 64 bit → リング）----
    rmux128 u_mux (.clk(clk), .rst(rst),
        .a_tdata(a_d), .a_tvalid(a_v), .a_tready(a_r), .a_tlast(a_l),
        .b_tdata(b_d), .b_tvalid(b_v), .b_tready(b_r), .b_tlast(b_l),
        .m_tdata(m_tdata), .m_tvalid(m_tvalid), .m_tready(m_tready), .m_tlast(m_tlast));
endmodule
