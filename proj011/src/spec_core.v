// SPDX-License-Identifier: BSD-3-Clause
//
// spec_core — 8192 点 FFT → 電力 → 積分（4096 ch）。AXI4-Lite で制御と読み出し
//
// proj011 の分光計コア。ブロックデザインには module reference で置く。
// proj010 からの差分は 2 点だけ: FFT IP を realtime にした（m_axis_data_tready の接続を外した）/
// ID の下位 8 bit に FFT の設定の符号 FFT_CFG を載せた。
// rev2: フレーム頭の判定の加算・比較を前もってレジスタに置いた（pre_*。rev1 の最悪経路 cur_k → t_last）。振る舞いは rev1 と同じ。
// rev3: 診断のレジスタ（0x58–0x68）を足した。realtime の FFT IP の TLAST 事象（起動の 7/20 で立ち続ける）を切り分けるため。
//       データの経路には触らない。CTRL[9] で診断だけを消す（FLAGS の CTRL[8] とは別）。
// **全部が DSP ドメイン（256 MHz）で動く。**AXI4-Lite も 256 MHz で受け、
// PS（pl_clk0）との乗り換えは SmartConnect に任せる。自作の CDC はここに無い。
//
// ---- FFT の分解 ----
// 入力は 1 ビート 16 サンプル（ギアボックスの出口）。サンプル番号 n = 16·m + p
// （m = 0..511 はフレーム内のビート、p = 0..15 はレーン）。8192 点 FFT を
//   X[k1 + 512·k2] = Σ_p W16^(p·k2) · { W8192^(p·k1) · Y_p[k1] }
//   Y_p[k1]        = Σ_m x[16m + p] · W512^(m·k1)           （レーンごとの 512 点 FFT）
// と分ける（k1 = 0..511、k2 = 0..15）。
//   1. レーン FFT   lane_fft（Xilinx FFT IP）× 16。**自然順で出し、XK_INDEX = k1 を読む**
//   2. ひねり係数   tw_rom + cmul × 16
//   3. 16 点 DFT    dft16。実数入力なので k2 = 0..7（X[0..4095]）だけ作る
//   4. 丸めと飽和   SHIFT だけ右シフトし、18 bit に飽和（飽和した回数を数える）
//   5. 電力         re² + im²（37 bit）
//   6. 積分         64 bit。k2 ごとに 1 本、二面（交互）で 16 個の BRAM
// 1 クロックに k1 が 1 つ進み、そのとき X[k1 + 512·k2]（k2 = 0..7）の 8 本が出る。
//
// ---- 語幅の上限（ここから各段の bit 数を決めた）----
// 入力 |x| ≦ 2^13（14 bit）。**実数入力の DFT の成分は Σ|x| を越えない**ので:
//   Y（512 点）  |Y| ≦ 2^22            → IP の unscaled 出力 24 bit（= 14 + 9 + 1）で足りる
//   V = W·Y      |V| = |Y| ≦ 2^22      → 25 bit（丸めの余裕 1 bit）
//   U（4 点和）  |U| ≦ 2^24            → 27 bit（DSP の A ポート 27 bit にちょうど載る）
//   Z（16 点）   |Z| ≦ 2^26            → 29 bit
//
// ---- 積分の単位 ----
// 1 フレーム = 8192 サンプル = 512 ビート = **2.000 µs**。N_ACC フレームを 1 ダンプに積む。
//   100 ms = 50,000 フレーム / 1 s = 500,000 フレーム
// 64 bit の積分器は 37 bit の電力を 2^27 フレーム（268 s）積んでも溢れない。
//
// ---- 積分の開始と「どのフレームか」----
// 入力側と出力側に **フレーム番号のカウンタ**（fin / fout）を持つ。リセット後の最初の
// フレームを 0 とし、IP は取りこぼさない限りフレームを順に出すので、**出力のフレーム fout は
// 入力のフレーム fin = fout そのもの**である（fin − fout はパイプラインの深さで一定。
// PS 側で一定であることを確かめる）。
// RUN を書くと、開始フレーム F0 = fin + 2（確実に未来）を決め、両側がこの番号を見る:
//   入力側: フレーム F0 + k·N の生サンプルをスナップショットに残す（k = ダンプ番号）
//   出力側: フレーム F0 から N フレームずつ積み、ダンプごとに面を交互に替える
// **スナップショットと積分が同じフレームを指すことは、番号の一致として読み出せる**
// （SNAP_F == DUMP_F0）。N_ACC = 1 にすればスナップショットの FFT とダンプが 1 対 1 に対応する。
//
// ---- 読み出し（seqlock）----
// ダンプが閉じるたびに SEQ が 1 増え、DUMP_* とスペクトル窓・スナップショット窓が
// その面に切り替わる。**SEQ を読む → 中身を読む → SEQ を読む**で、SEQ が変わっていなければ
// 読んだ中身は 1 つのダンプのもの。面はダンプ 1 つおきに再利用されるので、
// 積分時間より十分速く読めばよい（100 ms に対して数 ms〜10 ms）。
//
// ---- アドレスマップ（バイト。16 bit）----
//   0x0000–0x00FF  レジスタ（下の表）
//   0x4000–0x7FFF  スナップショット: 32 bit 語 i = サンプル 2i（下位 16 bit）と 2i+1（上位）
//                  サンプルは ADC の 16 bit のまま（下位 2 bit は常に 0）
//   0x8000–0xFFFF  スペクトル: ch k の 64 bit が 0x8000 + 8k（下位語）/ +4（上位語）
//
//   0x00 ID        R   0x0011_03CC（proj011 rev3。rev2 は 0x0011_02CC、rev1 は 0x0011_01CC。CC = FFT_CFG: [0] realtime / [1] 乗算器 use_mults_resources /
//                      [2] バタフライ use_luts / [3] 乗算器 use_luts。build.tcl が src/fft_cfg.tcl から設定する）
//   0x04 PARAM     R   [7:0] log2 NFFT = 13 / [15:8] log2 レーン = 4 / [23:16] QW = 18 / [31:24] IW = 14
//   0x08 CTRL      W   [0] RUN（開始を予約）/ [1] STOP / [8] FLAGS を消す / [9] 診断（0x58–0x68）を消す（いずれも 1 を書いた瞬間だけ）
//                  R   [0] 積分中 / [1] 開始待ち / [2] スナップショット予約中 / [3] 入力が流れ始めた
//   0x0C N_ACC     RW  1 ダンプのフレーム数（0 は 1 とみなす）。RUN の時点で取り込む。既定 50000 = 100 ms
//   0x10 N_DUMP    RW  ダンプの回数。0 = 止めるまで。RUN の時点で取り込む
//   0x14 SHIFT     RW  [3:0] 電力の前に右シフトする bit 数（Z 29 bit → 18 bit）。既定 4
//   0x18 FLAGS     R   粘着する異常フラグ（下の表）
//   0x1C SEQ       R   閉じたダンプの通し番号（リセット以来。RUN で戻さない）
//   0x20 FIN_LO    R   入力のフレーム番号。**LO を読むと HI を固定する**
//   0x24 FIN_HI    R
//   0x28 FOUT_LO   R   出力のフレーム番号（同上）
//   0x2C FOUT_HI   R
//   0x30 DUMP_K    R   閉じたダンプの RUN 内での番号（0, 1, 2, …）
//   0x34 DUMP_N    R   そのダンプのフレーム数
//   0x38 DUMP_F0_LO R  そのダンプの最初のフレーム番号
//   0x3C DUMP_F0_HI R
//   0x40 DUMP_SAT  R   そのダンプで 18 bit に飽和した回数（ch × フレーム）
//   0x44 SNAP_F_LO R   スナップショット窓が持つフレームの番号。**DUMP_F0 と一致すれば同じフレーム**
//   0x48 SNAP_F_HI R
//   0x4C BANK      R   読み出し窓が指している面（0/1）
//   0x50 RUN_F0_LO R   RUN で予約した開始フレーム
//   0x54 RUN_F0_HI R
//   0x58 DIAG_TL   R   [15:0] レーンごとの TLAST unexpected / [31:16] missing（粘着。CTRL[9] で消す。rev3）
//   0x5C DIAG_EV   R   [31] レーン 0 に TLAST 事象があった / [30:29] {missing, unexpected} / [8:0] 最初の事象の m_in
//   0x60 DIAG_FS   R   [31] レーン 0 の frame_started を見た / [30] 以後 m_in が違った / [29] レーン間で揃わなかった / [8:0] 最初の m_in
//   0x64 DIAG_EVCNT R  レーン 0 の TLAST 事象のクロック数
//   0x68 DIAG_FSCNT R  レーン 0 の frame_started の回数
//
// FLAGS（粘着。CTRL[8] で消す）:
//   [0] レーンの出力 valid が揃っていない     [1] レーンの XK_INDEX が揃っていない
//   [2] レーンの入力 ready が揃っていない     [3] 入力を IP が受けなかった（サンプルを落とした）
//   [4] 入力に隙間があった（valid = 0）        [5] IP の TLAST 事象（unexpected / missing）
//   [6] IP の data_in_channel_halt            [7] XK_INDEX が 1 ずつ進まなかった
// **どれか 1 つでも立っていれば、そのあいだのスペクトルは信用しない。**

`timescale 1ns / 1ps

module spec_core #(
    parameter integer N_ACC_DEFAULT = 50000,
    parameter integer SHIFT_DEFAULT = 4,
    parameter integer FFT_CFG       = 0      // ID の下位 8 bit。lane_fft の設定の符号（build.tcl が与える）
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axis:s_axi, ASSOCIATED_RESET aresetn" *)
    input  wire         aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire         aresetn,

    // ---- ADC（ギアボックスの出口。16 サンプル × 16 bit、下位が古い）----
    input  wire [255:0] s_axis_tdata,
    input  wire         s_axis_tvalid,
    output wire         s_axis_tready,

    // ---- AXI4-Lite（制御と読み出し）----
    input  wire [15:0]  s_axi_awaddr,
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
    input  wire [15:0]  s_axi_araddr,
    input  wire [2:0]   s_axi_arprot,
    input  wire         s_axi_arvalid,
    output wire         s_axi_arready,
    output reg  [31:0]  s_axi_rdata,
    output wire [1:0]   s_axi_rresp,
    output reg          s_axi_rvalid,
    input  wire         s_axi_rready
);
    localparam integer NL = 16;        // レーン
    localparam integer NB = 8;         // 1 クロックに出る ch（k2 = 0..7）
    localparam integer IW = 14;        // IP の入力語幅（ADC の有効 14 bit）
    localparam integer YW = 24;        // IP の出力語幅（unscaled = 14 + 9 + 1）
    localparam integer VW = 25;
    localparam integer UW = 27;
    localparam integer ZW = 29;
    localparam integer QW = 18;        // 電力の入力
    localparam integer PW = 2 * QW + 1;
    localparam integer FW = 48;        // フレーム番号（2 µs × 2^48 = 17 年）
    localparam [7:0]   FFT_CFG8 = FFT_CFG;
    localparam [31:0]  ID = {16'h0011, 8'h03, FFT_CFG8};

    // 固定のパイプライン段数（S0 = レーン出力を受けたクロック）
    //   S0  +2 ROM → +4 cmul → V@6  +6 dft16 → Z@12  +1 飽和 → Q@13
    //   Q@13 → 電力 P@16 / BRAM の読み出し番地を S14 で出し、読み値が S16 / 和と書き込み S17
    localparam integer S_Q   = 13;
    localparam integer S_RD  = 14;
    localparam integer S_SUM = 17;

    wire rst = ~aresetn;
    assign s_axis_tready = 1'b1;       // **上流に backpressure をかけない**（RFDC がサンプルを落とす）

    // =====================================================================
    // AXI4-Lite の書き込み側（レジスタ）
    // =====================================================================
    reg [31:0] r_nacc, r_ndump;
    reg [3:0]  r_shift;
    reg        cmd_run, cmd_stop, cmd_clr, cmd_dclr;   // 1 クロックのパルス

    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;

    always @(posedge aclk) begin
        cmd_run <= 1'b0; cmd_stop <= 1'b0; cmd_clr <= 1'b0; cmd_dclr <= 1'b0;
        if (rst) begin
            s_axi_bvalid <= 1'b0;
            r_nacc  <= N_ACC_DEFAULT;
            r_ndump <= 32'd0;
            r_shift <= SHIFT_DEFAULT;
        end else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) begin
                s_axi_bvalid <= 1'b1;
                case (s_axi_awaddr[15:2])
                    14'h02: begin
                        cmd_run  <= s_axi_wdata[0];
                        cmd_stop <= s_axi_wdata[1];
                        cmd_clr  <= s_axi_wdata[8];
                        cmd_dclr <= s_axi_wdata[9];
                    end
                    14'h03: r_nacc  <= s_axi_wdata;
                    14'h04: r_ndump <= s_axi_wdata;
                    14'h05: r_shift <= s_axi_wdata[3:0];
                    default: ;
                endcase
            end
        end
    end

    // RUN の時点で取り込む値（積分中にレジスタを書き換えても、走っている RUN は変わらない）
    reg  [31:0]   run_n, run_ndump;
    reg  [FW-1:0] run_f0;

    // =====================================================================
    // 入力側: レーン FFT への供給・フレーム番号・スナップショット
    // =====================================================================
    wire [NL-1:0] ln_s_tready;
    wire [NL-1:0] ln_ev_tlast_unexp, ln_ev_tlast_miss, ln_ev_in_halt, ln_ev_fs;
    wire [NL-1:0] ln_m_tvalid, ln_m_tlast;
    wire [NL*48-1:0] ln_m_tdata;
    wire [NL*16-1:0] ln_m_tuser;

    reg  [8:0]    m_in;          // フレーム内のビート
    reg  [FW-1:0] fin;           // 入力のフレーム番号
    reg           started;       // 最初のビートを IP が受けた
    wire          in_acc = s_axis_tvalid && ln_s_tready[0];
    wire          in_tlast = (m_in == 9'd511);

    // スナップショットの予約（入力側）
    reg           in_on;
    reg  [FW-1:0] in_next;
    reg  [31:0]   in_k;
    reg           snap_act;      // このフレームを記録中
    reg           snap_buf;
    reg  [FW-1:0] snap_f0, snap_f1;
    wire          snap_hit = in_on && (fin == in_next);   // m_in == 0 のときだけ意味を持つ

    reg [255:0] snap_mem [0:1023];   // {面, m}。2 面 × 512 ビート × 256 bit = BRAM36 × 8
    wire        snap_we  = in_acc && ((m_in == 9'd0) ? snap_hit : snap_act);
    wire        snap_wb  = (m_in == 9'd0) ? in_k[0] : snap_buf;
    always @(posedge aclk) begin
        if (snap_we) snap_mem[{snap_wb, m_in}] <= s_axis_tdata;
    end

    always @(posedge aclk) begin
        if (rst) begin
            m_in <= 9'd0; fin <= {FW{1'b0}}; started <= 1'b0;
            in_on <= 1'b0; in_next <= {FW{1'b0}}; in_k <= 32'd0;
            snap_act <= 1'b0; snap_buf <= 1'b0;
            snap_f0 <= {FW{1'b1}}; snap_f1 <= {FW{1'b1}};
        end else begin
            if (in_acc) begin
                started <= 1'b1;
                m_in    <= m_in + 9'd1;
                if (in_tlast) begin
                    fin      <= fin + 1'b1;
                    snap_act <= 1'b0;
                end
                if (m_in == 9'd0 && snap_hit) begin
                    snap_act <= 1'b1;
                    snap_buf <= in_k[0];
                    if (in_k[0]) snap_f1 <= fin; else snap_f0 <= fin;
                    in_k    <= in_k + 1;
                    in_next <= in_next + ((run_n == 0) ? 1 : run_n);
                    if (run_ndump != 0 && in_k + 1 == run_ndump) in_on <= 1'b0;
                end
            end
            // コマンドは最後に書く（同じクロックのフレーム頭より優先）
            if (cmd_run) begin
                in_on   <= 1'b1;
                in_next <= fin + 2;
                in_k    <= 32'd0;
            end
            if (cmd_stop) in_on <= 1'b0;
        end
    end

    // =====================================================================
    // レーン FFT（Xilinx FFT IP。build.tcl が lane_fft の名前で生成する）
    // =====================================================================
    genvar p, j;
    generate
        for (p = 0; p < NL; p = p + 1) begin : g_lane
            // 16 bit の ADC 値を 2 bit 右へ（下位 2 bit は常に 0）。IP の入力は 14 bit を 16 bit に詰めたもの
            wire signed [15:0] xs  = s_axis_tdata[16*p +: 16];
            wire signed [15:0] xin = xs >>> 2;
            lane_fft u_fft (
                .aclk                   (aclk),
                .aresetn                (aresetn),
                .s_axis_config_tdata    (8'h01),       // FWD_INV = 1（順変換）
                .s_axis_config_tvalid   (1'b1),
                .s_axis_config_tready   (),
                .s_axis_data_tdata      ({16'h0000, xin}),
                .s_axis_data_tvalid     (s_axis_tvalid),
                .s_axis_data_tready     (ln_s_tready[p]),
                .s_axis_data_tlast      (in_tlast),
                .m_axis_data_tdata      (ln_m_tdata[48*p +: 48]),
                .m_axis_data_tuser      (ln_m_tuser[16*p +: 16]),
                .m_axis_data_tvalid     (ln_m_tvalid[p]),
                // m_axis_data_tready は無い（realtime の IP には出力側の tready が無い。PG109）
                .m_axis_data_tlast      (ln_m_tlast[p]),
                .event_frame_started    (ln_ev_fs[p]),
                .event_tlast_unexpected (ln_ev_tlast_unexp[p]),
                .event_tlast_missing    (ln_ev_tlast_miss[p]),
                .event_data_in_channel_halt (ln_ev_in_halt[p])
            );
        end
    endgenerate

    // =====================================================================
    // 出力側: フレームの判定（どのダンプの何フレーム目か）
    // =====================================================================
    wire          o_valid = ln_m_tvalid[0];
    wire [8:0]    o_k1    = ln_m_tuser[8:0];
    reg  [FW-1:0] fout;
    reg  [8:0]    k1_exp;

    reg           sched;         // 開始待ち
    reg           acc_on;        // 積分中
    reg  [31:0]   cur_k, cur_idx;
    reg           cur_act, cur_first, cur_last, cur_bank;
    reg  [FW-1:0] pend_f0_0, pend_f0_1;
    reg  [31:0]   pend_k_0, pend_k_1;

    wire [31:0] n_eff = (run_n == 0) ? 32'd1 : run_n;

    // ---- フレーム頭の判定に使う加算・比較を、前もってレジスタに置く（proj011 rev2）----
    // rev1 はフレーム頭（fs）の 1 クロックで「cur_k + 1 == run_ndump → d_idx の選択 → d_idx == n_eff − 1」と
    // 32 bit の加算・比較を 2 段直列に通していて、これが最悪経路だった（CARRY8 5〜7 段。ビルドで +0.16〜+0.51 ns 動いた）。
    // **入力（cur_k・cur_idx・run_ndump・run_n）は fs と cmd_run でしか変わらない**ので、変わった次のクロックには
    // pre_* が追いつく。fs と fs の間は 512 クロック、cmd_run から最初の開始（fout == run_f0 = fin + 2）までは
    // 2 フレーム以上あるので、fs で読む pre_* は必ず新しい。
    // pre_f0hit だけは fout そのものが fs の直前（k1 == 511）に進むので、同じ瞬間に「進んだ後の fout」と比べる。
    // cmd_run と同じクロックでは消す（新しい run_f0 は fin + 2 なので、どのみち一致しない）。
    // **rev1 と振る舞いは bit 単位で同じ**（make sim の A 層が rev1 と同じ数字を出すことで確かめる）。
    reg [31:0] pre_kp1, pre_idxp1;
    reg        pre_end, pre_idxp1_is0, pre_nxt_last, pre_zero_last, pre_f0hit;
    always @(posedge aclk) begin
        pre_kp1       <= cur_k + 32'd1;
        pre_end       <= (run_ndump != 32'd0) && (cur_k + 32'd1 == run_ndump);
        pre_idxp1     <= cur_idx + 32'd1;
        pre_idxp1_is0 <= (cur_idx == 32'hFFFF_FFFF);
        pre_nxt_last  <= (cur_idx + 32'd1 == n_eff - 32'd1);
        pre_zero_last <= (n_eff == 32'd1);
        if (rst)
            pre_f0hit <= 1'b0;
        else if (cmd_run)
            pre_f0hit <= 1'b0;
        else if (o_valid && o_k1 == 9'd511)
            pre_f0hit <= (fout + 1'b1 == run_f0);
    end

    // フレーム頭（k1 == 0）での判定。**幅のある演算は pre_* に追い出した**ので、ここは選択だけ
    reg        d_act, d_newrun, d_stop, d_zero;
    reg [31:0] d_k, d_idx;
    reg        d_idx_is0, d_idx_last;
    always @* begin
        d_act = 1'b0; d_newrun = 1'b0; d_stop = 1'b0;
        d_k = cur_k; d_zero = 1'b0;                       // d_zero = 0 なら d_idx = cur_idx + 1
        if (sched && pre_f0hit) begin
            d_act = 1'b1; d_newrun = 1'b1; d_k = 32'd0; d_zero = 1'b1;
        end else if (acc_on) begin
            if (cur_last) begin
                if (pre_end) begin
                    d_stop = 1'b1;
                end else begin
                    d_act = 1'b1; d_k = pre_kp1; d_zero = 1'b1;
                end
            end else begin
                d_act = 1'b1;
            end
        end
        d_idx      = d_zero ? 32'd0 : pre_idxp1;
        d_idx_is0  = d_zero ? 1'b1  : pre_idxp1_is0;      // = (d_idx == 0)
        d_idx_last = d_zero ? pre_zero_last : pre_nxt_last; // = (d_idx == n_eff − 1)
    end
    wire fs      = o_valid && (o_k1 == 9'd0);
    wire t_act   = fs ? d_act : cur_act;
    wire t_first = fs ? d_idx_is0 : cur_first;
    wire t_last  = fs ? d_idx_last : cur_last;
    wire t_bank  = fs ? d_k[0] : cur_bank;

    always @(posedge aclk) begin
        if (rst) begin
            fout <= {FW{1'b0}}; k1_exp <= 9'd0;
            sched <= 1'b0; acc_on <= 1'b0;
            cur_k <= 0; cur_idx <= 0;
            cur_act <= 1'b0; cur_first <= 1'b0; cur_last <= 1'b0; cur_bank <= 1'b0;
            pend_f0_0 <= 0; pend_f0_1 <= 0; pend_k_0 <= 0; pend_k_1 <= 0;
            run_n <= 32'd1; run_ndump <= 32'd0; run_f0 <= {FW{1'b0}};
        end else begin
            if (o_valid) begin
                k1_exp <= o_k1 + 9'd1;
                if (o_k1 == 9'd511) fout <= fout + 1'b1;
            end
            if (fs) begin
                cur_act   <= d_act;
                cur_first <= d_idx_is0;
                cur_last  <= d_act && d_idx_last;
                cur_bank  <= d_k[0];
                cur_k     <= d_k;
                cur_idx   <= d_idx;
                if (d_newrun) begin sched <= 1'b0; acc_on <= 1'b1; end
                if (d_stop)   acc_on <= 1'b0;
                if (d_act && d_idx_is0) begin
                    if (d_k[0]) begin pend_f0_1 <= fout; pend_k_1 <= d_k; end
                    else        begin pend_f0_0 <= fout; pend_k_0 <= d_k; end
                end
            end
            if (cmd_run) begin
                sched     <= 1'b1;
                acc_on    <= 1'b0;
                cur_act   <= 1'b0;
                run_n     <= r_nacc;
                run_ndump <= r_ndump;
                run_f0    <= fin + 2;
            end
            if (cmd_stop) begin
                sched <= 1'b0; acc_on <= 1'b0; cur_act <= 1'b0;
            end
        end
    end

    // =====================================================================
    // データ経路
    // =====================================================================
    // ---- タグの遅延線 [0] = S0 ----
    //   {valid, act, first, last, bank, k1[8:0]}
    localparam integer TW = 14;
    reg [TW-1:0] tag [0:S_SUM];
    integer ti;
    always @(posedge aclk) begin
        if (rst) begin
            for (ti = 0; ti <= S_SUM; ti = ti + 1) tag[ti] <= {TW{1'b0}};
        end else begin
            tag[0] <= {o_valid, o_valid && t_act, t_first, t_last, t_bank, o_k1};
            for (ti = 1; ti <= S_SUM; ti = ti + 1) tag[ti] <= tag[ti-1];
        end
    end
    `define TG_V(t)  tag[t][13]
    `define TG_A(t)  tag[t][12]
    `define TG_F(t)  tag[t][11]
    `define TG_L(t)  tag[t][10]
    `define TG_B(t)  tag[t][9]
    `define TG_K(t)  tag[t][8:0]

    // ---- S0: レーン出力を受ける → S2 まで遅らせる（ROM の 2 クロックに合わせる）----
    reg [NL*YW-1:0] y_re0, y_im0, y_re1, y_im1, y_re2, y_im2;
    integer li;
    always @(posedge aclk) begin
        for (li = 0; li < NL; li = li + 1) begin
            y_re0[li*YW +: YW] <= ln_m_tdata[48*li      +: YW];
            y_im0[li*YW +: YW] <= ln_m_tdata[48*li + 24 +: YW];
        end
        y_re1 <= y_re0; y_im1 <= y_im0;
        y_re2 <= y_re1; y_im2 <= y_im1;
    end

    // ---- ひねり係数（S2 → V@S6）----
    wire [NL*VW-1:0] v_re, v_im;
    generate
        for (p = 0; p < NL; p = p + 1) begin : g_tw
            wire signed [17:0] w_re, w_im;
            tw_rom #(.P(p)) u_rom (
                .clk(aclk), .addr(`TG_K(0)), .w_re(w_re), .w_im(w_im)
            );
            cmul #(.AW(YW), .OW(VW)) u_mul (
                .clk(aclk),
                .a_re(y_re2[p*YW +: YW]), .a_im(y_im2[p*YW +: YW]),
                .w_re(w_re), .w_im(w_im),
                .y_re(v_re[p*VW +: VW]), .y_im(v_im[p*VW +: VW])
            );
        end
    endgenerate

    // ---- 16 点 DFT（V@S6 → Z@S12）----
    wire [NB*ZW-1:0] z_re, z_im;
    dft16 #(.VW(VW), .UW(UW), .ZW(ZW)) u_dft (
        .clk(aclk), .v_re(v_re), .v_im(v_im), .z_re(z_re), .z_im(z_im)
    );

    // ---- 右シフトと 18 bit への飽和（Z@S12 → Q@S13）----
    localparam signed [ZW-1:0] QMAX =  (1 <<< (QW-1)) - 1;
    localparam signed [ZW-1:0] QMIN = -(1 <<< (QW-1));
    function [QW:0] sat;      // {飽和した, 値}
        input signed [ZW-1:0] z;
        input [3:0]           sh;
        reg   signed [ZW-1:0] t;
        begin
            t = z >>> sh;
            if (t > QMAX)      sat = {1'b1, QMAX[QW-1:0]};
            else if (t < QMIN) sat = {1'b1, QMIN[QW-1:0]};
            else               sat = {1'b0, t[QW-1:0]};
        end
    endfunction

    reg [NB*QW-1:0] q_re, q_im;
    reg [NB-1:0]    q_sat;
    integer bi;
    reg [QW:0] sr, si;
    always @(posedge aclk) begin
        for (bi = 0; bi < NB; bi = bi + 1) begin
            sr = sat(z_re[bi*ZW +: ZW], r_shift);
            si = sat(z_im[bi*ZW +: ZW], r_shift);
            q_re[bi*QW +: QW] <= sr[QW-1:0];
            q_im[bi*QW +: QW] <= si[QW-1:0];
            q_sat[bi]         <= sr[QW] | si[QW];
        end
    end

    // 飽和の数（Q@S13 の飽和を数えて S14 に置き、S17 まで運ぶ）
    reg [3:0] satn;
    reg [3:0] satc14, satc15, satc16, satc17;
    integer ci;
    always @* begin
        satn = 4'd0;
        for (ci = 0; ci < NB; ci = ci + 1) satn = satn + q_sat[ci];
    end
    always @(posedge aclk) begin
        satc14 <= (`TG_V(S_Q) && `TG_A(S_Q)) ? satn : 4'd0;
        satc15 <= satc14;
        satc16 <= satc15;
        satc17 <= satc16;
    end

    // ---- 電力（Q@S13 → P@S16）と積分（S14 読み・S17 書き）----
    wire [NB*PW-1:0] pw;
    wire [63:0] acc_rd [0:1][0:NB-1];
    reg  [8:0]  axi_k1;                  // AXI 側の読み出し番地（凍っている面に使う）

    generate
        for (j = 0; j < NB; j = j + 1) begin : g_bin
            // 電力: DSP の A/B → M → 和
            reg signed [QW-1:0] a_re, a_im;
            reg signed [2*QW-1:0] m_re, m_im;
            reg [PW-1:0] pwr;
            always @(posedge aclk) begin
                a_re <= q_re[j*QW +: QW];
                a_im <= q_im[j*QW +: QW];
                m_re <= a_re * a_re;
                m_im <= a_im * a_im;
                pwr  <= m_re + m_im;
            end
            assign pw[j*PW +: PW] = pwr;

            // 二面の積分メモリ。面ごとに 512 × 64 bit（BRAM36 × 1）
            genvar bk;
            for (bk = 0; bk < 2; bk = bk + 1) begin : g_bank
                reg [63:0] mem [0:511];
                reg [63:0] rd1, rd2;
                reg [8:0]  wa;
                reg [63:0] wd;
                reg        we;
                // 読み出しポート: 積分中の面なら RMW、そうでなければ AXI
                wire rmw = `TG_V(S_RD) && `TG_A(S_RD) && !`TG_F(S_RD) && (`TG_B(S_RD) == bk);
                wire [8:0] ra = rmw ? `TG_K(S_RD) : axi_k1;
                always @(posedge aclk) begin
                    rd1 <= mem[ra];
                    rd2 <= rd1;
                    if (we) mem[wa] <= wd;
                end
                assign acc_rd[bk][j] = rd2;

                // S16 の読み値と電力を足して S17 で書く
                always @(posedge aclk) begin
                    we <= `TG_V(S_SUM-1) && `TG_A(S_SUM-1) && (`TG_B(S_SUM-1) == bk);
                    wa <= `TG_K(S_SUM-1);
                    wd <= `TG_F(S_SUM-1) ? {27'd0, pwr} : rd2 + {27'd0, pwr};
                end
            end
        end
    endgenerate

    // ---- ダンプを閉じる（S17 の最後のビート）----
    reg [31:0]   seq, rd_k, rd_n, rd_sat, sat_run;
    reg [FW-1:0] rd_f0;
    reg          rd_bank;
    wire commit = `TG_V(S_SUM) && `TG_A(S_SUM) && `TG_L(S_SUM) && (`TG_K(S_SUM) == 9'd511);
    always @(posedge aclk) begin
        if (rst) begin
            seq <= 0; rd_k <= 0; rd_n <= 0; rd_sat <= 0; sat_run <= 0;
            rd_f0 <= {FW{1'b1}}; rd_bank <= 1'b0;
        end else begin
            if (`TG_V(S_SUM) && `TG_A(S_SUM)) begin
                if (`TG_F(S_SUM) && `TG_K(S_SUM) == 9'd0) sat_run <= satc17;
                else                                      sat_run <= sat_run + satc17;
            end
            if (commit) begin
                seq     <= seq + 1;
                rd_bank <= `TG_B(S_SUM);
                rd_sat  <= sat_run + satc17;
                rd_n    <= n_eff;
                rd_f0   <= `TG_B(S_SUM) ? pend_f0_1 : pend_f0_0;
                rd_k    <= `TG_B(S_SUM) ? pend_k_1  : pend_k_0;
            end
        end
    end

    // =====================================================================
    // 異常フラグ（粘着）
    // =====================================================================
    reg [7:0] flags;
    wire [7:0] f_now;
    assign f_now[0] = started && (ln_m_tvalid != {NL{1'b0}}) && (ln_m_tvalid != {NL{1'b1}});
    reg f_k1_mis;
    integer fi;
    always @* begin
        f_k1_mis = 1'b0;
        for (fi = 1; fi < NL; fi = fi + 1)
            if (ln_m_tvalid[fi] && ln_m_tuser[16*fi +: 9] != o_k1) f_k1_mis = 1'b1;
    end
    assign f_now[1] = f_k1_mis;
    assign f_now[2] = s_axis_tvalid && (ln_s_tready != {NL{1'b0}}) && (ln_s_tready != {NL{1'b1}});
    assign f_now[3] = started && s_axis_tvalid && !ln_s_tready[0];
    assign f_now[4] = started && !s_axis_tvalid;
    assign f_now[5] = |(ln_ev_tlast_unexp | ln_ev_tlast_miss);
    assign f_now[6] = started && (|ln_ev_in_halt);
    assign f_now[7] = o_valid && (o_k1 != k1_exp);
    always @(posedge aclk) begin
        if (rst || cmd_clr) flags <= 8'd0;
        else                flags <= flags | f_now;
    end

    // =====================================================================
    // 診断（rev3）。TLAST 事象を「どのレーンで・どちらの種類で・入力側の数え m_in のどこで」に分ける
    // =====================================================================
    // 見立て: realtime の IP は、TLAST を照合する数えと実際に FFT に切る枠が別で、起動によって前者だけがずれる。
    // これを確かめるため、IP が枠を始めた位置（event_frame_started の m_in）と、TLAST 事象の位置（m_in）を別々に取る。
    //   枠の位置が立つ起動と立たない起動で同じ → 枠は同じ（照合が通ったことと合う）
    //   事象の位置が一定 → 検査の数えが一定量ずれている（その量が読める）
    // m_in は IP の事象の出力（登録済み）と同じクロックで読むので、IP の遅延ぶんの一定の足しが入る。**比べるのは起動どうしの差**
    reg [NL-1:0] dg_unexp, dg_miss;     // レーンごと・粘着
    reg          dg_ev_seen;
    reg  [1:0]   dg_ev_type;            // {missing, unexpected}（レーン 0 の最初の事象）
    reg  [8:0]   dg_ev_min;             // その m_in
    reg          dg_fs_seen, dg_fs_var, dg_fs_lanes;
    reg  [8:0]   dg_fs_min;             // レーン 0 の最初の frame_started の m_in。以後違えば dg_fs_var
    reg  [31:0]  dg_evcnt, dg_fscnt;    // レーン 0 の TLAST 事象のクロック数 / frame_started の回数
    wire         ev0 = ln_ev_tlast_unexp[0] | ln_ev_tlast_miss[0];
    always @(posedge aclk) begin
        if (rst || cmd_dclr) begin
            dg_unexp <= {NL{1'b0}}; dg_miss <= {NL{1'b0}};
            dg_ev_seen <= 1'b0; dg_ev_type <= 2'd0; dg_ev_min <= 9'd0;
            dg_fs_seen <= 1'b0; dg_fs_var <= 1'b0; dg_fs_lanes <= 1'b0; dg_fs_min <= 9'd0;
            dg_evcnt <= 32'd0; dg_fscnt <= 32'd0;
        end else begin
            dg_unexp <= dg_unexp | ln_ev_tlast_unexp;
            dg_miss  <= dg_miss  | ln_ev_tlast_miss;
            if (ev0) begin
                dg_evcnt <= dg_evcnt + 32'd1;
                if (!dg_ev_seen) begin
                    dg_ev_seen <= 1'b1;
                    dg_ev_type <= {ln_ev_tlast_miss[0], ln_ev_tlast_unexp[0]};
                    dg_ev_min  <= m_in;
                end
            end
            if (ln_ev_fs[0]) begin
                dg_fscnt <= dg_fscnt + 32'd1;
                if (!dg_fs_seen) begin
                    dg_fs_seen <= 1'b1;
                    dg_fs_min  <= m_in;
                end else if (m_in != dg_fs_min) begin
                    dg_fs_var <= 1'b1;
                end
            end
            if (ln_ev_fs != {NL{1'b0}} && ln_ev_fs != {NL{1'b1}}) dg_fs_lanes <= 1'b1;
        end
    end

    // =====================================================================
    // AXI4-Lite の読み出し側
    // =====================================================================
    // 受けたら 4 クロック待って返す（番地の登録 → BRAM → 出力レジスタ → 選択）
    reg [15:0] ar_addr;
    reg [2:0]  ar_wait;
    reg        ar_busy;
    reg        ar_bank;
    reg [FW-1:0] fin_lat, fout_lat;
    assign s_axi_arready = !ar_busy && !s_axi_rvalid;
    assign s_axi_rresp   = 2'b00;

    reg [8:0] snap_ra;
    reg [255:0] snap_rd1, snap_rd2;
    always @(posedge aclk) begin
        snap_rd1 <= snap_mem[{ar_bank, snap_ra}];
        snap_rd2 <= snap_rd1;
    end

    reg [31:0] reg_rd;
    always @* begin
        case (ar_addr[7:2])
            6'h00: reg_rd = ID;
            6'h01: reg_rd = {8'd14, 8'd18, 8'd4, 8'd13};
            6'h02: reg_rd = {28'd0, started, in_on, sched, acc_on};
            6'h03: reg_rd = r_nacc;
            6'h04: reg_rd = r_ndump;
            6'h05: reg_rd = {28'd0, r_shift};
            6'h06: reg_rd = {24'd0, flags};
            6'h07: reg_rd = seq;
            6'h08: reg_rd = fin_lat[31:0];
            6'h09: reg_rd = {{(64-FW){1'b0}}, fin_lat[FW-1:32]};
            6'h0A: reg_rd = fout_lat[31:0];
            6'h0B: reg_rd = {{(64-FW){1'b0}}, fout_lat[FW-1:32]};
            6'h0C: reg_rd = rd_k;
            6'h0D: reg_rd = rd_n;
            6'h0E: reg_rd = rd_f0[31:0];
            6'h0F: reg_rd = {{(64-FW){1'b0}}, rd_f0[FW-1:32]};
            6'h10: reg_rd = rd_sat;
            6'h11: reg_rd = rd_bank ? snap_f1[31:0] : snap_f0[31:0];
            6'h12: reg_rd = {{(64-FW){1'b0}}, rd_bank ? snap_f1[FW-1:32] : snap_f0[FW-1:32]};
            6'h13: reg_rd = {31'd0, rd_bank};
            6'h14: reg_rd = run_f0[31:0];
            6'h15: reg_rd = {{(64-FW){1'b0}}, run_f0[FW-1:32]};
            6'h16: reg_rd = {dg_miss, dg_unexp};
            6'h17: reg_rd = {dg_ev_seen, dg_ev_type, 20'd0, dg_ev_min};
            6'h18: reg_rd = {dg_fs_seen, dg_fs_var, dg_fs_lanes, 20'd0, dg_fs_min};
            6'h19: reg_rd = dg_evcnt;
            6'h1A: reg_rd = dg_fscnt;
            default: reg_rd = 32'hDEAD_BEEF;
        endcase
    end

    always @(posedge aclk) begin
        if (rst) begin
            ar_busy <= 1'b0; ar_wait <= 3'd0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0;
            ar_addr <= 16'd0; ar_bank <= 1'b0; axi_k1 <= 9'd0; snap_ra <= 9'd0;
            fin_lat <= {FW{1'b0}}; fout_lat <= {FW{1'b0}};
        end else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin
                ar_busy <= 1'b1;
                ar_wait <= 3'd0;
                ar_addr <= s_axi_araddr;
                ar_bank <= rd_bank;
                axi_k1  <= s_axi_araddr[11:3];   // スペクトル: k1 = A[11:3]
                snap_ra <= s_axi_araddr[13:5];   // スナップショット: m = A[13:5]
                if (s_axi_araddr[15:2] == 14'h08) fin_lat  <= fin;
                if (s_axi_araddr[15:2] == 14'h0A) fout_lat <= fout;
            end else if (ar_busy) begin
                ar_wait <= ar_wait + 3'd1;
                if (ar_wait == 3'd3) begin
                    ar_busy      <= 1'b0;
                    s_axi_rvalid <= 1'b1;
                    if (ar_addr[15]) begin
                        // スペクトル: k2 = A[14:12]、上位語 = A[2]
                        s_axi_rdata <= ar_addr[2] ? acc_rd[ar_bank][ar_addr[14:12]][63:32]
                                                  : acc_rd[ar_bank][ar_addr[14:12]][31:0];
                    end else if (ar_addr[14]) begin
                        s_axi_rdata <= snap_rd2[32*ar_addr[4:2] +: 32];
                    end else begin
                        s_axi_rdata <= reg_rd;
                    end
                end
            end
        end
    end

    `undef TG_V
    `undef TG_A
    `undef TG_F
    `undef TG_L
    `undef TG_B
    `undef TG_K
endmodule
