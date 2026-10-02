// SPDX-License-Identifier: BSD-3-Clause
//
// win_core — ADC 1 本ぶんの窓の分光計（bit ③）。ギアボックスの出口 → pfb_core（NW 窓で共有）→ 窓ごとに ddc_core → wspec_core。
// AXI4-Lite で制御と読み出し。**proj015 手順 4: 1 ADC に NW 個の窓**（proj014 は 1 窓）
//
// ブロックデザインには module reference で置く（spec_core と同じ）。**全部が DSP ドメイン（256 MHz）**。AXI4-Lite も 256 MHz で受ける。
//
// ---- 窓の設定（WK・WDPHI・WNS）----
// 書いただけでは効かない。**CTRL[12] = WRST** で、書いておいた値を取り込み、その窓の ddc・wspec を WRST_T クロックだけリセットし、
// pfb の窓 w を始まり待ちにする（フレーム番号・積分も最初から）。**粗い PFB（分岐の和・16 点 DFT）は共有なので WRST では止めない**。
// 窓の最初のフレームは WRST の後の最初のビート（pfb_core の q_start。0x8C WSTART）から数える（pfb_core の冒頭）。
// ハードのリセットの後は既定値（WK = 0・WDPHI = 0・WNS = 1）で回る。
//   窓の中心 c（f の側、ゾーン 2 の IF の中心 C なら c = 4096 − C）→ WK = round(c / 128)、d = c − 128·WK、WDPHI = round(d / 512 · 2^32) mod 2^32
//   幅 W = 512 / 2^WNS MHz（WNS = 1..8 → 256..2 MHz。proj015 で 7・8 = 4・2 MHz を足した）
// **入力の途切れ（ギアボックスの出口の tvalid = 0）は値を変えない**: pfb_core は valid なビートだけで窓を進め、以降は組ごとに進む。
//
// ---- アドレスマップ（バイト。20 bit = 1 MiB）----
//   窓 w（0..NW−1）: 0x20000·w + 下の 128 KiB（proj014 の win_core と同じ並び）
//     0x00000–0x000FF  レジスタ（下の表）
//     0x08000–0x0FFFF  スナップショット: サンプル i の re が 0x08000 + 8i、im が +4（18 bit を 32 bit に符号拡張）。
//                      **ADC で 1 つを共有し、SNAP_SEL の窓だけが書く**（他の窓のこの範囲は 0 を返す）
//     0x10000–0x17FFF  スペクトル: ch b の 64 bit が 0x10000 + 8b（下位語）/ +4（上位語）
//   ADC の共通: 0x80000 + 下の表 A
//
//   0x00 ID        R   0x0016_0100（proj016 rev1: 時刻・設定番号・健全性。窓の中身は proj015 rev3 と同じ）。proj015: 0x0015_0300（proj015 rev3: 読み出しの応答に 1 段・LO の読みの固定を 1 クロック後に。rev2 = 0x0015_0200 は
//                       `-1` の最悪経路の 4 群に段を足した版、rev1 = 0x0015_0100 は WNS 1..8・G 5・1 ADC に NW 窓。値はどれも同じ）
//   0x04 PARAM     R   [7:0] log2 NFFT = 12 / [11:8] 今の WNS / [15:12] 今の G / [23:16] QW = 18 / [31:24] ZW = 18
//   0x08 CTRL      W   [0] RUN / [1] STOP / [8] FLAGS を消す / [12] WRST（窓の設定を取り込んで最初から）（1 を書いた瞬間だけ）
//                  R   [0] 積分中 / [1] 開始待ち / [3] z が流れ始めた / [4] WRST 中
//   0x0C N_ACC     RW  1 ダンプのフレーム数（0 は 1）。RUN の時点で取り込む。1 フレーム = 4096 / W µs
//   0x10 N_DUMP    RW  ダンプの回数。0 = 止めるまで
//   0x14 SHIFT     RW  [3:0] 電力の前の右シフト（FFT の出力 31 bit → 18 bit）。既定 SHIFT_DEFAULT
//   0x18 FLAGS     R   [7:0] wspec_core の FLAGS（粘着、CTRL[8] で消す）/ [8] pfb の飽和あり / [9] ddc の飽和あり /
//                      [10] ddc の時分割の追い越しあり（0 のはず）（[8]〜[10] は WRST で消える）
//   0x1C SEQ       R   閉じたダンプの通し番号
//   0x20 FIN_LO    R   溜め終えたフレーム数。**LO を読むと HI を固定**   0x24 FIN_HI
//   0x28 FOUT_LO   R   FFT を出たフレーム数（同上）                       0x2C FOUT_HI
//   0x30 DUMP_K / 0x34 DUMP_N / 0x38 DUMP_F0_LO / 0x3C DUMP_F0_HI / 0x40 DUMP_SAT   （spec_core と同じ）
//   0x44 SNAP_F_LO / 0x48 SNAP_F_HI   読み出し窓の面のスナップショットのフレーム番号（DUMP_F0 と一致すれば同じフレーム）
//   0x4C BANK      R   読み出し窓の面
//   0x50 RUN_F0_LO / 0x54 RUN_F0_HI
//   0x58 WK        RW  [4:0] 粗い ch（0..16）       次の WRST で効く。R は書いた値
//   0x5C WDPHI     RW  NCO の 1 サンプルの位相の増分（32 bit）
//   0x60 WNS       RW  [3:0] 半帯域の段数（1..8。範囲外は WRST で 1）
//   0x64 WCUR      R   今効いている [4:0] WK / [11:8] WNS（WDPHI は 0x68）
//   0x68 WCUR_DPHI R
//   0x6C PFB_SAT   R   pfb_core の飽和の回数（この窓の WRST 以来、飽和して止まる。共有の分岐の和の飽和も数える）
//   0x70 DDC_SAT   R   ddc_core の飽和の回数
//   0x74 BUILD     R   ビルドの指紋（build.tcl が与える）
//   0x78 WRST_T    RW  [15:0] WRST のリセットの長さ（クロック、0 は 1）。既定 64
//   0x7C WRST_CNT  R   WRST を受けた回数
//   0x80 WS_STALL  R   FFT IP に待たされたクロック数（WRST 以来、飽和）。FLAGS[4] の量
//   0x84 WS_RDY0   R   WRST の解除から FFT IP の s_axis_data_tready が最初に 1 になるまでのクロック数
//   0x88 DDC_OVR   R   ddc_core の時分割の段（hb2s）の追い越しの回数（WRST 以来、飽和）。構造で起きないはずの見張り
//   0x8C WSTART    R   この窓の始まりのビート（pfb_core の q_start。ビートは ADC のリセットから数える 32 bit、巻き戻る）
//   0x90 WIDX      R   この窓の番号 w
//   ---- proj016（時刻・設定番号・健全性）----
//   CTRL の書き込みに足したビット: [2] ARM_RUN（time_core の発火で RUN）/ [3] 予約の取り消し（STOP でも消える）/ [13] ARM_WRST（発火で WRST）
//   CTRL の読みに足したビット: [5] ARM_RUN 中 / [6] ARM_WRST 中 / [7] WRST の明けを待つ RUN（ARM_RUN と ARM_WRST が同じ発火を受けたとき）
//   **予約は発火・STOP・取り消しでしか消えない**（time_core の取り消しや「遅すぎ」では消えない。PS が窓の側も取り消すこと）
//   **SHIFT は RUN の時点で取り込む**（proj015 までは書いた瞬間に効いた。RUN の間に書いても次の RUN まで効かない。N_ACC・N_DUMP と同じ）
//   0x94 CFG_ID    RW  設定番号（PS が決める 32 bit）。WRST と RUN の時点で取り込む
//   0x98 RUN_CFG   R   今の RUN の CFG_ID        0x9C WRST_CFG  R  今の窓の設定（WRST）の CFG_ID
//   0xA0 DUMP_T_LO R   閉じたダンプの最初のフレームの最初の z が wspec に入ったビート（time_core の T）  0xA4 DUMP_T_HI
//   0xA8 DUMP_H    R   そのダンプの健全性（src/dstamp.v）: [0] PPS 来ていない / [1] 間隔の異常 / [2] グリッチ / [3] 原点なし /
//                      [4] ADC の振り切れ / [5] 入力の途切れ / [6] WRST_CFG ≠ RUN_CFG / [14] 帳簿の上書き / [15] 帳簿が閉じていない
//                      **ADC 側の [4]・[5] は ADC の時刻で、ダンプの区切りは z の時刻**（窓の遅れ D(NS) ぶん後ろへずれる。D は timebase.py）
//   0xAC DUMP_CFG  R   そのダンプの RUN の CFG_ID
//   0xB0 RUN_T_LO  R   RUN を受けたビート（予約なら START_AT + 1）  0xB4 RUN_T_HI
//   0xB8 RUN_SHIFT R   今の RUN の SHIFT
//   **DUMP_* は SEQ と同じ commit で切り替わる**（seqlock: SEQ → 中身 → SEQ）
//
//   表 A（0x80000 + ）
//   0x00 ID        R   0x0016_A100（ADC の共通。proj016 rev1）。proj015 rev3 は 0x0015_A300
//   0x04 NW        R   窓の数
//   0x08 SNAP_SEL  RW  [3:0] スナップショットを書く窓（既定 0）。変えたら、次のダンプからその窓のスナップショット
//   0x0C BUILD     R   ビルドの指紋
//   0x10 CTRL      W   [0] TP_RUN（total power の区切りを F0 = TFIN + 2 に揃える。1 を書いた瞬間だけ）
//                      proj016: [2] TP_ARM（time_core の発火で TP_RUN）/ [3] TP_ARM の取り消し / [4] TANCH（次の ADC のフレームの頭で (TFIN, T) を残す）
//   0x14 TFIN_LO   R   ADC のフレーム（8192 サンプル = 512 ビート = 2 µs）の数。**LO を読むと HI を固定**   0x18 TFIN_HI
//   0x1C GB_K      RW  [5:0] gb_gate のしきい値（ハードのリセットの起動に効く。既定 GB_K_RST = 2）
//   0x20 FULL_SEL  RW  [1:0] 全帯域の分光（spec_core_0）につなぐ ADC（0..3 = ADC_A..D）。**win_core_0 のものだけが効く**（build.tcl）
//   0x24 GB_STAT   R   gb_gate の見張り（spec_core の GB_STAT と同じ形）
//   0x28 ADC_STAT  R   gb_adc の見張り（ADC ドメインの値。2 回読んで一致を確かめる）
//   ---- proj016 ----
//   0x2C ANCH_F_LO R   TANCH で残した ADC のフレーム番号（TFIN と同じ物差し）  0x30 ANCH_F_HI
//   0x34 ANCH_T_LO R   そのフレームの頭のビートが入ったクロックの T  0x38 ANCH_T_HI
//                      **TP の区切り（リングの語 2 = フレーム番号）の時刻 = ANCH_T + (f − ANCH_F)·512**（その間 GAP_CNT が増えていなければ）
//   0x3C ANCH_STAT R   [0] TANCH 待ち / [1] 残した / [2] TP_ARM 中
//   0x40 TP_RUN_T_LO R TP_RUN を受けたビート  0x44 TP_RUN_T_HI
//   0x48 OVR_CNT   R   入力の振り切れたビートの数（|x| ≧ 32764、飽和）  0x4C GAP_CNT  R  最初の valid の後に valid が来なかったクロックの数
//   0x0100–0x01FF  total power のレジスタ（src/tp_core.v。spec_core の 0x0100– と同じ並び）
//   0x2000–0x3FFF  total power のリングバッファ（512 個 × 16 バイト）
//   total power は ADC のビートをそのまま積む（窓の WRST とは無関係。ADC のリセットからのフレームの上に区切る）
//
// **スナップショットはダンプの commit から (N_ACC − 2) フレーム以内に読む**（wspec_core の冒頭）

`timescale 1ns / 1ps

module win_core #(
    parameter integer NW            = 1,      // 1 ADC の窓の数（1..4）
    parameter integer N_ACC_DEFAULT = 6250,   // 256 MHz 窓で 100 ms
    parameter integer SHIFT_DEFAULT = 4,
    parameter integer BUILD_TAG     = 0,
    parameter integer TP            = 1,      // 1: ADC の total power（tp_core）を持つ
    parameter integer TPN_DEFAULT   = 500,    // 1 ms
    parameter integer GB_K_RST      = 2       // gb_gate のしきい値の既定（proj012 rev3 の K = 2）
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis:s_axi, ASSOCIATED_RESET aresetn:gb_dn_rstn" *)
    input  wire         aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire         aresetn,
    input  wire [255:0] s_axis_tdata,
    input  wire         s_axis_tvalid,
    output wire         s_axis_tready,
    input  wire [19:0]  s_axi_awaddr,
    input  wire [2:0]   s_axi_awprot,
    input  wire         s_axi_awvalid,
    output wire         s_axi_awready,
    input  wire [31:0]  s_axi_wdata,
    input  wire [3:0]   s_axi_wstrb,
    input  wire         s_axi_wvalid,
    output wire         s_axi_wready,
    output wire [1:0]   s_axi_bresp,
    output reg          s_axi_bvalid,
    input  wire         s_axi_bready,
    input  wire [19:0]  s_axi_araddr,
    input  wire [2:0]   s_axi_arprot,
    input  wire         s_axi_arvalid,
    output wire         s_axi_arready,
    output reg  [31:0]  s_axi_rdata,
    output wire [1:0]   s_axi_rresp,
    output reg          s_axi_rvalid,
    input  wire         s_axi_rready,
    // ギアボックスの制御と見張り（proj015: spec_core が 1 本になったので、ch ごとのギアボックスは win_core が持つ。GRST は無い）
    output wire         gb_hold,          // gb_adc へ: 0（書き込み側は rst_adc だけで解く）
    output wire [1:0]   gb_adj,           // gb_adc へ: 0
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 gb_dn_rstn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    output reg          gb_dn_rstn,       // gb_gate / gb_dn へ: aresetn を 1 段
    output wire [5:0]   gb_k,             // gb_gate へ: GB_K（0x8001C）
    input  wire [31:0]  gb_stat,          // gb_gate から（0x80024 で読む）
    input  wire [31:0]  adc_stat,         // gb_gate から（0x80028。ADC ドメインの数え。2 回読んで一致を確かめる）
    output wire [1:0]   full_sel,         // 全帯域の分光（spec_core_0）につなぐ ADC（axis_sel4 へ。0x80020。win_core_0 のものだけ使う）
    // proj016: time_core から（ここで 1 段受ける。受けた t_loc が time_core の T と同じ値になるよう、time_core が先に足して出す）
    input  wire [63:0]  t_in,
    input  wire         go_in,
    input  wire [3:0]   tev_in
);
    localparam integer FW = 48;
    localparam [31:0]  ID   = 32'h0016_0100;
    localparam [31:0]  ID_A = 32'h0016_A100;
    wire rst = ~aresetn;
    assign s_axis_tready = 1'b1;       // 上流に backpressure をかけない

    // ---- proj016: 時刻（time_core から 1 段）と入力の健全性 ----
    (* max_fanout = 32 *) reg [63:0] t_loc;
    reg        go_loc;
    reg [3:0]  tev_loc;
    always @(posedge aclk) begin t_loc <= t_in; go_loc <= go_in; tev_loc <= tev_in; end
    wire a_ovr, a_gap;
    adc_ev u_aev (.clk(aclk), .rst(rst), .tdata(s_axis_tdata), .tvalid(s_axis_tvalid), .ovr(a_ovr), .gap(a_gap));
    // 窓へ配る健全性の素: [0] PPS 来ていない / [1] 間隔 / [2] グリッチ / [3] 原点なし / [4] 振り切れ / [5] 入力の途切れ（[6] は窓ごと）
    reg [5:0]  ev_a;
    always @(posedge aclk) ev_a <= {a_gap, a_ovr, tev_loc};

    // ---- 書き込みの受け口（1 回に 1 つ）。番地の [19:17] = 窓（4 = ADC の共通）----
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    wire [2:0] wr_sel = s_axi_awaddr[19:17];
    wire       wr_reg = (s_axi_awaddr[16:8] == 9'd0);
    always @(posedge aclk) begin
        if (rst) s_axi_bvalid <= 1'b0;
        else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) s_axi_bvalid <= 1'b1;
        end
    end

    // ---- ADC の共通 ----
    reg [3:0] snap_sel;
    reg [5:0] r_gbk;
    reg [1:0] r_fsel;
    wire      wr_a = wr_go && wr_sel == 3'd4 && wr_reg;
    always @(posedge aclk) begin
        if (rst) begin snap_sel <= 4'd0; r_gbk <= GB_K_RST; r_fsel <= 2'd0; end
        else begin
            if (wr_a && s_axi_awaddr[7:2] == 6'h02) snap_sel <= s_axi_wdata[3:0];
            if (wr_a && s_axi_awaddr[7:2] == 6'h07) r_gbk    <= s_axi_wdata[5:0];
            if (wr_a && s_axi_awaddr[7:2] == 6'h08) r_fsel   <= s_axi_wdata[1:0];
        end
    end
    assign gb_hold = 1'b0;
    assign gb_adj = 2'd0;
    assign gb_k = r_gbk;
    assign full_sel = r_fsel;
    always @(posedge aclk) gb_dn_rstn <= aresetn;

    // ---- ADC のフレーム（total power の区切りの物差し）と total power ----
    reg  [56:0] a_cnt;                       // valid なビートの数
    always @(posedge aclk) begin
        if (rst) a_cnt <= 57'd0;
        else if (s_axis_tvalid) a_cnt <= a_cnt + 57'd1;
    end
    wire [FW-1:0] a_fin = a_cnt[56:9];
    reg  tp_run, tp_arm, anch_req, anch_done;
    reg  [FW-1:0] anch_f;
    reg  [63:0]   anch_t, tp_run_t;
    reg  [31:0]   n_ovr, n_gap;
    wire wr_tpc = wr_go && wr_sel == 3'd4 && wr_reg && s_axi_awaddr[7:2] == 6'h04;
    always @(posedge aclk) begin
        tp_run <= (wr_tpc && s_axi_wdata[0]) || (tp_arm && go_loc);
        if (rst) begin
            tp_arm <= 1'b0; anch_req <= 1'b0; anch_done <= 1'b0; anch_f <= {FW{1'b0}}; anch_t <= 64'd0; tp_run_t <= 64'd0;
            n_ovr <= 32'd0; n_gap <= 32'd0;
        end else begin
            if (wr_tpc && s_axi_wdata[2]) tp_arm <= 1'b1;
            else if ((wr_tpc && s_axi_wdata[3]) || go_loc) tp_arm <= 1'b0;
            // TANCH: 次の ADC のフレームの頭のビートで (フレーム番号, T) を組で残す
            if (wr_tpc && s_axi_wdata[4]) begin anch_req <= 1'b1; anch_done <= 1'b0; end
            else if (anch_req && s_axis_tvalid && a_cnt[8:0] == 9'd0) begin
                anch_req <= 1'b0; anch_done <= 1'b1; anch_f <= a_fin; anch_t <= t_loc;
            end
            if (tp_run) tp_run_t <= t_loc;
            if (a_ovr && n_ovr != 32'hFFFF_FFFF) n_ovr <= n_ovr + 32'd1;
            if (a_gap && n_gap != 32'hFFFF_FFFF) n_gap <= n_gap + 32'd1;
        end
    end
    wire [31:0] tp_ring_rd, tp_reg_rd;
    wire [15:0] tp_rd_addr;
    generate
        if (TP != 0) begin : g_tp
            tp_core #(.TPN_DEFAULT(TPN_DEFAULT), .FW(FW)) u_tp (
                .clk(aclk), .rst(rst), .in_acc(s_axis_tvalid), .m_in(a_cnt[8:0]), .fin(a_fin), .tdata(s_axis_tdata),
                .cmd_run(tp_run),
                .wr_en(wr_go && wr_sel == 3'd4 && s_axi_awaddr[16:8] == 9'h001), .wr_addr(s_axi_awaddr[7:2]), .wr_data(s_axi_wdata),
                .rd_addr(tp_rd_addr), .rd_ring(tp_ring_rd), .rd_reg(tp_reg_rd));
        end else begin : g_notp
            assign tp_ring_rd = 32'd0;
            assign tp_reg_rd  = 32'd0;
        end
    endgenerate

    // ---- 読み出しの受け口 ----
    reg [19:0]   ar_addr;
    reg [2:0]    ar_wait;
    reg          ar_busy;
    assign s_axi_arready = !ar_busy && !s_axi_rvalid;
    assign s_axi_rresp   = 2'b00;
    wire [2:0] ar_sel = ar_addr[19:17];
    assign tp_rd_addr = ar_addr[15:0];
    wire       ar_go  = s_axi_arvalid && s_axi_arready;
    // rev3: LO の読みで HI を固定するのは ar_go の 1 クロック後に、ar_addr（レジスタ）で決める。rev2 は SmartConnect の
    //   araddr から 48 bit の固定の enable を直に作っていて、`-1` の群 Y（ファンアウト 48）だった。応答は 4 クロック以上後なので中身は同じ
    reg        ar_go_d;
    always @(posedge aclk) ar_go_d <= rst ? 1'b0 : ar_go;

    // ---- 粗い PFB（共有）----
    wire [NW-1:0]    core_rst;            // 窓ごと: rst | WRST 中
    wire [5*NW-1:0]  kv;
    wire [24*NW-1:0] y0r, y0i, y1r, y1i;
    wire [NW-1:0]    y0ok, y1ok;
    wire             yv;
    wire [16*NW-1:0] pfb_sat;
    wire [32*NW-1:0] q_start;
    pfb_core #(.NW(NW), .QW(32)) u_pfb (.clk(aclk), .rst(rst), .w_rst(core_rst), .s_tdata(s_axis_tdata), .s_tvalid(s_axis_tvalid),
        .k(kv), .y0_re(y0r), .y0_im(y0i), .y1_re(y1r), .y1_im(y1i), .y0_ok(y0ok), .y1_ok(y1ok), .y_valid(yv),
        .sat_cnt(pfb_sat), .q_start(q_start));

    // ---- スナップショット（ADC で 1 つ。SNAP_SEL の窓が書く）----
    wire [NW-1:0]    sn_wen_v;
    wire [13*NW-1:0] sn_waddr_v;
    wire [36*NW-1:0] sn_wdata_v;
    reg  [35:0]      snap_mem [0:8191];
    reg              ax_bank;
    reg  [11:0]      ax_ch;
    reg  [35:0]      sn1, sn2;
    wire [3:0]       ss = (snap_sel < NW) ? snap_sel : 4'd0;
    // rev2: 書き込みを 2 段のレジスタで受ける（窓ごとに 1 段 → SNAP_SEL で選んで 1 段 → 記憶）。rev1 は wspec の fin == sn_next の
    //   48 bit の比べ → 4 窓の選び → BRAM の書き込みの入口が 1 クロックで、`-1` の最悪経路だった。書き込みが 2 クロック遅れるだけで、
    //   読むのはダンプが閉じた後（少なくとも 1 フレーム後）なので中身は同じ
    reg  [NW-1:0]    swe1;
    reg  [13*NW-1:0] swa1;
    reg  [36*NW-1:0] swd1;
    reg              swe2;
    reg  [12:0]      swa2;
    reg  [35:0]      swd2;
    always @(posedge aclk) begin
        swe1 <= sn_wen_v;  swa1 <= sn_waddr_v;  swd1 <= sn_wdata_v;
        swe2 <= swe1[ss];  swa2 <= swa1[13*ss +: 13];  swd2 <= swd1[36*ss +: 36];
        if (swe2) snap_mem[swa2] <= swd2;
        sn1 <= snap_mem[{ax_bank, ax_ch}];
        sn2 <= sn1;
    end

    // ---- 窓ごと ----
    wire [31:0]    reg_rd_v [0:NW-1];
    wire [63:0]    sp_data_v [0:NW-1];
    wire [NW-1:0]  rd_bank_v;
    genvar g;
    generate
        for (g = 0; g < NW; g = g + 1) begin : g_w
            wire wr_me = wr_go && wr_sel == g && wr_reg;
            reg [31:0] r_nacc, r_ndump, r_dphi;
            reg [3:0]  r_shift;
            reg [4:0]  r_k;
            reg [3:0]  r_ns;
            reg [15:0] r_wt;
            reg        cmd_run, cmd_stop, cmd_clr, cmd_wrst;
            reg        arm_run, arm_wrst;           // proj016: 予約（time_core の発火で RUN / WRST）
            reg [31:0] r_cfg;                       // proj016: 設定番号（RUN と WRST の時点で取り込む）
            reg [15:0] wr_cnt;                      // （下の WRST の塊が書く）
            reg        w_rst;
            // proj016: ARM_RUN と ARM_WRST が同じ発火を受けたら、**RUN は WRST が明けてから**出す（同時に出すと、RUN を受けた直後に
            //   w_rst が wspec をリセットして RUN が消える）。そのときの RUN_T は START_AT + 1 ではなく WRST の明けた後
            reg        run_defer;
            wire       wrst_idle = !w_rst && (wr_cnt == 16'd0) && !cmd_wrst;
            wire       run_go    = (go_loc && arm_run && !arm_wrst) || (run_defer && wrst_idle);
            always @(posedge aclk) begin
                cmd_run <= run_go; cmd_stop <= 1'b0; cmd_clr <= 1'b0; cmd_wrst <= go_loc && arm_wrst;
                if (run_defer && wrst_idle) run_defer <= 1'b0;
                if (go_loc && arm_run && arm_wrst) run_defer <= 1'b1;
                if (go_loc) begin arm_run <= 1'b0; arm_wrst <= 1'b0; end
                if (rst) begin
                    r_nacc <= N_ACC_DEFAULT; r_ndump <= 32'd0; r_shift <= SHIFT_DEFAULT;
                    r_k <= 5'd0; r_dphi <= 32'd0; r_ns <= 4'd1; r_wt <= 16'd64;
                    arm_run <= 1'b0; arm_wrst <= 1'b0; r_cfg <= 32'd0; run_defer <= 1'b0;
                end else if (wr_me) begin
                    case (s_axi_awaddr[7:2])
                        6'h02: begin
                            cmd_run  <= s_axi_wdata[0]  | run_go;
                            cmd_stop <= s_axi_wdata[1];
                            cmd_clr  <= s_axi_wdata[8];
                            cmd_wrst <= s_axi_wdata[12] | (go_loc && arm_wrst);
                            if (s_axi_wdata[2])  arm_run  <= 1'b1;
                            if (s_axi_wdata[13]) arm_wrst <= 1'b1;
                            if (s_axi_wdata[3] || s_axi_wdata[1]) begin arm_run <= 1'b0; arm_wrst <= 1'b0; run_defer <= 1'b0; end
                        end
                        6'h25: r_cfg   <= s_axi_wdata;
                        6'h03: r_nacc  <= s_axi_wdata;
                        6'h04: r_ndump <= s_axi_wdata;
                        6'h05: r_shift <= s_axi_wdata[3:0];
                        6'h16: r_k     <= s_axi_wdata[4:0];
                        6'h17: r_dphi  <= s_axi_wdata;
                        6'h18: r_ns    <= s_axi_wdata[3:0];
                        6'h1E: r_wt    <= s_axi_wdata[15:0];
                        default: ;
                    endcase
                end
            end

            // ---- WRST: 設定を取り込み、窓の経路を最初から ----
            reg [4:0]  c_k;
            reg [31:0] c_dphi;
            reg [3:0]  c_ns;
            reg [31:0] wrst_n;
            reg [31:0] c_cfg;
            always @(posedge aclk) begin
                if (rst) begin
                    c_k <= 5'd0; c_dphi <= 32'd0; c_ns <= 4'd1; c_cfg <= 32'd0;
                    wr_cnt <= 16'd0; w_rst <= 1'b1; wrst_n <= 32'd0;
                end else if (cmd_wrst) begin
                    c_k <= r_k; c_dphi <= r_dphi; c_ns <= (r_ns >= 4'd1 && r_ns <= 4'd8) ? r_ns : 4'd1; c_cfg <= r_cfg;
                    wr_cnt <= (r_wt == 16'd0) ? 16'd1 : r_wt;
                    w_rst <= 1'b1; wrst_n <= wrst_n + 32'd1;
                end else if (wr_cnt != 16'd0) begin
                    wr_cnt <= wr_cnt - 16'd1;
                    w_rst  <= (wr_cnt != 16'd1);
                end else w_rst <= 1'b0;
            end
            assign core_rst[g] = rst | w_rst;

            // ---- proj016: RUN の時点で取り込む設定（SHIFT・設定番号）。RUN の間に書いても次の RUN まで効かない ----
            //   N_ACC・N_DUMP は wspec_core が RUN で取り込む（proj014 から）
            reg [3:0]  run_shift;
            reg [31:0] run_cfg;
            reg        cfg_diff;
            always @(posedge aclk) begin
                if (rst) begin run_shift <= SHIFT_DEFAULT; run_cfg <= 32'd0; end
`ifdef WIN_POSCTL_SHIFT
                else run_shift <= r_shift;          // 陽性対照: 取り込みを外す（RUN の間の書き込みが混ざる。S-T4 が落ちること）
`else
                else if (cmd_run) begin run_shift <= r_shift; run_cfg <= r_cfg; end
`endif
`ifdef WIN_POSCTL_SHIFT
                if (cmd_run) run_cfg <= r_cfg;
`endif
                cfg_diff <= (run_cfg != c_cfg);
            end
            wire [7:0] wev = {1'b0, cfg_diff, ev_a};
            assign kv[5*g +: 5] = c_k;

            // ---- ddc・wspec ----
            wire [15:0] ddc_sat, ddc_ovr;
            wire [15:0] psat = pfb_sat[16*g +: 16];
            wire zv;
            wire signed [17:0] zr, zi;
            ddc_core u_ddc (.clk(aclk), .rst(core_rst[g]), .y_valid(yv), .y0_ok(y0ok[g]), .y1_ok(y1ok[g]),
                .y0_re(y0r[24*g +: 24]), .y0_im(y0i[24*g +: 24]), .y1_re(y1r[24*g +: 24]), .y1_im(y1i[24*g +: 24]),
                .dphi(c_dphi), .ns(c_ns), .z_valid(zv), .z_re(zr), .z_im(zi), .sat_cnt(ddc_sat), .ovr_cnt(ddc_ovr));
            wire [FW-1:0] fin, fout, run_f0, rd_f0, snap_f0, snap_f1;
            wire          sched, acc_on, rd_bank;
            wire [31:0]   seq, rd_k, rd_n, rd_sat;
            wire [7:0]    wflags;
            wire [63:0]   rd_t, run_t;
            wire [15:0]   rd_h;
            wire [31:0]   ws_stall, ws_rdy0;
            wire [35:0]   sn_unused;
            wspec_core #(.SNAP(0)) u_ws (.clk(aclk), .rst(core_rst[g]), .z_valid(zv), .z_re(zr), .z_im(zi),
                .cmd_run(cmd_run), .cmd_stop(cmd_stop), .cmd_clr(cmd_clr),
                .r_nacc(r_nacc), .r_ndump(r_ndump), .r_shift(run_shift),
                .fin(fin), .fout(fout), .run_f0(run_f0), .sched(sched), .acc_on(acc_on),
                .seq(seq), .rd_k(rd_k), .rd_n(rd_n), .rd_sat(rd_sat), .rd_f0(rd_f0), .rd_bank(rd_bank),
                .snap_f0(snap_f0), .snap_f1(snap_f1), .flags(wflags), .stall_cnt(ws_stall), .rdy0(ws_rdy0),
                .rd_bk(ax_bank), .rd_ch(ax_ch), .rd_data(sp_data_v[g]), .sn_bk(ax_bank), .sn_a(ax_ch), .sn_data(sn_unused),
                .sn_wen(sn_wen_v[g]), .sn_waddr(sn_waddr_v[13*g +: 13]), .sn_wdata(sn_wdata_v[36*g +: 36]),
                .t_now(t_loc), .ev(wev), .rd_t(rd_t), .rd_h(rd_h), .run_t(run_t));
            assign rd_bank_v[g] = rd_bank;
            // そのダンプの設定番号（commit = SEQ が変わったクロックの run_cfg。RUN の後にしか commit しないので RUN の値）
            reg [31:0] seq_d, rd_cfg;
            always @(posedge aclk) begin
                seq_d <= seq;
                if (rst) rd_cfg <= 32'd0;
                else if (seq != seq_d) rd_cfg <= run_cfg;
            end
            reg z_seen;
            always @(posedge aclk) begin
                if (core_rst[g]) z_seen <= 1'b0;
                else if (zv)     z_seen <= 1'b1;
            end

            // ---- 読み出し（FIN・FOUT の HI を固定する LO の読み）----
            reg [FW-1:0] fin_lat, fout_lat;
            always @(posedge aclk) begin
                if (rst) begin fin_lat <= {FW{1'b0}}; fout_lat <= {FW{1'b0}}; end
                else if (ar_go_d && ar_addr[19:17] == g) begin
                    if (ar_addr[16:2] == 15'h08) fin_lat  <= fin;
                    if (ar_addr[16:2] == 15'h0A) fout_lat <= fout;
                end
            end
            reg [31:0] rr;
            always @* begin
                case (ar_addr[7:2])
                    6'h00: rr = ID;
                    6'h01: rr = {8'd18, 8'd18, (c_ns >= 4'd7) ? 4'd5 : 4'd4, c_ns, 8'd12};
                    6'h02: rr = {24'd0, run_defer, arm_wrst, arm_run, w_rst, z_seen, 1'b0, sched, acc_on};
                    6'h03: rr = r_nacc;
                    6'h04: rr = r_ndump;
                    6'h05: rr = {28'd0, r_shift};
                    6'h06: rr = {21'd0, ddc_ovr != 16'd0, ddc_sat != 16'd0, psat != 16'd0, wflags};
                    6'h07: rr = seq;
                    6'h08: rr = fin_lat[31:0];
                    6'h09: rr = {{(64-FW){1'b0}}, fin_lat[FW-1:32]};
                    6'h0A: rr = fout_lat[31:0];
                    6'h0B: rr = {{(64-FW){1'b0}}, fout_lat[FW-1:32]};
                    6'h0C: rr = rd_k;
                    6'h0D: rr = rd_n;
                    6'h0E: rr = rd_f0[31:0];
                    6'h0F: rr = {{(64-FW){1'b0}}, rd_f0[FW-1:32]};
                    6'h10: rr = rd_sat;
                    6'h11: rr = rd_bank ? snap_f1[31:0] : snap_f0[31:0];
                    6'h12: rr = {{(64-FW){1'b0}}, rd_bank ? snap_f1[FW-1:32] : snap_f0[FW-1:32]};
                    6'h13: rr = {31'd0, rd_bank};
                    6'h14: rr = run_f0[31:0];
                    6'h15: rr = {{(64-FW){1'b0}}, run_f0[FW-1:32]};
                    6'h16: rr = {27'd0, r_k};
                    6'h17: rr = r_dphi;
                    6'h18: rr = {28'd0, r_ns};
                    6'h19: rr = {20'd0, c_ns, 3'd0, c_k};
                    6'h1A: rr = c_dphi;
                    6'h1B: rr = {16'd0, psat};
                    6'h1C: rr = {16'd0, ddc_sat};
                    6'h1D: rr = BUILD_TAG;
                    6'h1E: rr = {16'd0, r_wt};
                    6'h1F: rr = wrst_n;
                    6'h20: rr = ws_stall;
                    6'h21: rr = ws_rdy0;
                    6'h22: rr = {16'd0, ddc_ovr};
                    6'h23: rr = q_start[32*g +: 32];
                    6'h24: rr = g;
                    6'h25: rr = r_cfg;
                    6'h26: rr = run_cfg;
                    6'h27: rr = c_cfg;
                    6'h28: rr = rd_t[31:0];
                    6'h29: rr = rd_t[63:32];
                    6'h2A: rr = {16'd0, rd_h};
                    6'h2B: rr = rd_cfg;
                    6'h2C: rr = run_t[31:0];
                    6'h2D: rr = run_t[63:32];
                    6'h2E: rr = {28'd0, run_shift};
                    default: rr = 32'hDEAD_BEEF;
                endcase
            end
            assign reg_rd_v[g] = rr;
        end
    endgenerate

    // ---- ADC の共通の読み出し ----
    reg [FW-1:0] afin_lat;
    always @(posedge aclk) begin
        if (rst) afin_lat <= {FW{1'b0}};
        else if (ar_go_d && ar_addr[19:17] == 3'd4 && ar_addr[16:2] == 15'h05) afin_lat <= a_fin;
    end
    reg [31:0] reg_a;
    always @* begin
        case (ar_addr[7:2])
            6'h00: reg_a = ID_A;
            6'h01: reg_a = NW;
            6'h02: reg_a = {28'd0, snap_sel};
            6'h03: reg_a = BUILD_TAG;
            6'h05: reg_a = afin_lat[31:0];
            6'h06: reg_a = {{(64-FW){1'b0}}, afin_lat[FW-1:32]};
            6'h07: reg_a = {26'd0, r_gbk};
            6'h08: reg_a = {30'd0, r_fsel};
            6'h09: reg_a = gb_stat;
            6'h0A: reg_a = adc_stat;
            6'h0B: reg_a = anch_f[31:0];
            6'h0C: reg_a = {{(64-FW){1'b0}}, anch_f[FW-1:32]};
            6'h0D: reg_a = anch_t[31:0];
            6'h0E: reg_a = anch_t[63:32];
            6'h0F: reg_a = {29'd0, tp_arm, anch_done, anch_req};
            6'h10: reg_a = tp_run_t[31:0];
            6'h11: reg_a = tp_run_t[63:32];
            6'h12: reg_a = n_ovr;
            6'h13: reg_a = n_gap;
            default: reg_a = 32'hDEAD_BEEF;
        endcase
    end

    // ---- 読み出しの応答（5 クロック後）----
    // rev3: 候補を毎クロック 1 段のレジスタで受け（ADC の共通 1 本・窓ごと 1 本）、応答ではそれを ar_sel で選ぶだけにした。
    //   rev2 は「37 本の case → 窓の選び → 種類の選び」を応答のクロックで一度にやっていて、`-1` の群 X（snap_mem・rd_f0・tp_n・
    //   ar_addr → s_axi_rdata）だった。候補は rev2 が応答で使ったのと同じクロック（ar_wait == 3）の値を受けるので、中身は同じ。
    //   応答が 1 クロック遅れるだけ（AXI4-Lite の読み 1 回 ≒ 20 クロックのうちの 1）
    wire [35:0] sn_data = sn2;
    reg  [31:0] rq_a;
    reg  [31:0] rq_w [0:NW-1];
    always @(posedge aclk) begin
        rq_a <= (ar_addr[16:8] == 9'd0)      ? reg_a :
                (ar_addr[16:8] == 9'h001)    ? tp_reg_rd :
                (ar_addr[16:13] == 4'b0001)  ? tp_ring_rd : 32'hDEAD_BEEF;
    end
    generate
        for (g = 0; g < NW; g = g + 1) begin : g_rq
            always @(posedge aclk) begin
                if (ar_addr[16])
                    rq_w[g] <= ar_addr[2] ? sp_data_v[g][63:32] : sp_data_v[g][31:0];
                else if (ar_addr[15])
                    rq_w[g] <= (g != ss) ? 32'd0 :
                               ar_addr[2] ? {{14{sn_data[35]}}, sn_data[35:18]} : {{14{sn_data[17]}}, sn_data[17:0]};
                else
                    rq_w[g] <= reg_rd_v[g];
            end
        end
    endgenerate
    always @(posedge aclk) begin
        if (rst) begin
            ar_busy <= 1'b0; ar_wait <= 3'd0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0;
            ar_addr <= 20'd0; ax_bank <= 1'b0; ax_ch <= 12'd0;
        end else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (ar_go) begin
                ar_busy <= 1'b1;
                ar_wait <= 3'd0;
                ar_addr <= s_axi_araddr;
                ax_bank <= (s_axi_araddr[19:17] < NW) ? rd_bank_v[s_axi_araddr[19:17]] : 1'b0;
                ax_ch   <= s_axi_araddr[14:3];      // スナップショット・スペクトルとも 8 バイト / 語
            end else if (ar_busy) begin
                ar_wait <= ar_wait + 3'd1;
                if (ar_wait == 3'd4) begin          // rq_* は ar_wait == 3 のクロックの候補（rev2 の応答と同じ値）
                    ar_busy      <= 1'b0;
                    s_axi_rvalid <= 1'b1;
                    if (ar_sel == 3'd4)      s_axi_rdata <= rq_a;
                    else if (ar_sel >= NW)   s_axi_rdata <= 32'hDEAD_BEEF;
                    else                     s_axi_rdata <= rq_w[ar_sel];
                end
            end
        end
    end
endmodule
