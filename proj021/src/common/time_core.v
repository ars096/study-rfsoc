// SPDX-License-Identifier: BSD-3-Clause
//
// time_core — 時刻の実体（proj016）。proj007 の pps_capture を fs = 4096 MSPS（DSP ドメイン 256 MHz）に置き直したもの
//
// 役割は 4 つ。
//   1. **ビートカウンタ T**（64 bit、DSP のクロック 1 個 = 1 ビート = 3.90625 ns）。**1 s = 256,000,000 ビートちょうど**
//      （DSP のクロックは clk_adc2 = fs/16 から MMCM で作る。fs が 10 MHz の基準に乗っている限り整数）。aresetn 以外では止めない
//   2. **PPS のスタンプ**: 基板の PPS（1 本の SMA から IRIG_TRIG_OUT / IRIG_COMP_OUT の 2 系統）の両方に、独立のスタンプ・間隔・
//      グリッチの数え。**スタンプは同期器（3 段）を抜けて縁を検出したクロックの T**（実際の縁より 2〜3 クロック後。定数）
//   3. **予約発火**: START_AT に書いた T で、ARM しておいたコアが同じクロックに RUN（や WRST）を受ける。PPS を毎秒のトリガにしない
//   4. **健全性の素**（ev_out）: [0] PPS が来ていない（選んだ系統、1.5 s）/ [1] 間隔が 256,000,000 ± PPS_TOL を外れた（パルス）/
//      [2] グリッチ（ブランキングの中の縁、パルス）/ [3] 原点が未設定（ANCHORED = 0。リセットで 0、PS が UTC と結んだら 1）
//
// ---- バスの段数（ここが肝）----
// t_out・go_out・ev_out は各コアで 1 段受けてから使う（コアの t_loc・go_loc）。**time_core の中で段数 LAT = 2 を先に足して出す**:
//   t_out = T + LAT − 1 を出す → コアの t_loc（1 段後）= T + LAT − 1 − 1 + 1 … を、下の式で「コアの中の t_loc == その時の T」に揃える。
//   go_out は「T == START_AT − 1」のクロックで立つ → コアの go_loc は T == START_AT のクロックに立つ。
// **つまりコアが RUN を受けるクロックの T（コアの t_loc）がちょうど START_AT**。sim（tb_time）で両方を確かめる。
//
// ---- 原点（エポック）----
// aresetn（rst_dsp）は MMCM のロックが外れても立つ。そのとき T は 0 に戻り、PS が持っている「T と UTC の対応」は黙って無効になる。
//   - ANCHORED（[4]）はリセットで 0。PS が対応を取ったら CTRL[3] で 1 にする。**ダンプの健全性の [3] がこれの否定**なので、
//     リセットを跨いだダンプは「原点なし」と分かる
//   - EPOCH は ctrl_aclk 側（rst_ctrl。MMCM に依らない）で aresetn の解除を数える（proj007 rev2 と同じ）。gray で DSP 側へ渡す
//
// ---- レジスタ（AXI4-Lite、DSP ドメイン。番地はバイト）----
//   0x00 ID        R   proj021 手順 2-1: **IF_ID**（INTERFACE 2.4 の形。[31:24] IF_VER 2 / [23:16] BIT_KIND / [15:8] BIT_REV / [7:0] CORE_KIND 2 = 時刻のコア）。
//                      proj021 1b までは 0x0021_7101 のような数値（proj016・time_core rev1 = 0x0016_7101）
//   0x5C PROJ      R   proj021 手順 2-1: 作った proj と rev（0x0021_0200）。**timebase.CAL の鍵**（追跡のため。IF_ID は bit の種類と版しか持たない）
//   0x04 PARAM     R   1 秒のビート数（256,000,000）
//   0x08 CTRL      W   [0] ARM（START_AT で発火）/ [1] 取り消し / [3] ANCHORED を 1 / [4] ANCHORED を 0 / [8] 数え（GLITCH・BAD・MISS）を 0
//                  R   [0] 予約中 / [1] 遅すぎ（START_AT − T < 16）/ [2] 遠すぎ（≧ 2^40 ≒ 72 分）/ [3] 発火した（次の ARM まで）/
//                      [4] ANCHORED / [5] TRIG 系統の PPS が来ている / [6] COMP 系統 / [7] 極性 / [8] ev の系統（0 TRIG・1 COMP）
//   0x0C CFG       RW  [0] 極性（1 = 反転）/ [1] ev_out・間隔の判定に使う系統（0 = TRIG・1 = COMP）/ [15:8] PPS_TOL（既定 1）
//   0x10 START_LO  RW  / 0x14 START_HI
//   0x18 T_LO      R   今の T。**LO を読むと HI を固定**   0x1C T_HI
//   0x20 PT_LO     R   TRIG 系統の最後のスタンプ。**LO を読むと HI・PT_INT・PT_CNT を固定**   0x24 PT_HI
//   0x28 PT_INT    R   TRIG 系統の最後の間隔（スタンプの差）  0x2C PT_CNT  R  採用した縁の数
//   0x30 PC_LO     R   COMP 系統（同じ並び）   0x34 PC_HI   0x38 PC_INT   0x3C PC_CNT
//   0x40 GLITCH    R   [31:16] COMP / [15:0] TRIG（飽和）
//   0x44 BAD       R   選んだ系統で間隔が許容を外れた回数（飽和）  0x48 MISS  R  選んだ系統が「来ていない」になった回数（飽和）
//   0x4C EPOCH     R   aresetn が解除された回数（ctrl_aclk 側で数える。0 = 一度も）
//   0x50 FIRED_LO  R   最後に発火したときのコアの T（= START_AT のはず）  0x54 FIRED_HI
//   0x58 BUILD     R   ビルドの指紋
//
// **report_cdc は EPOCH（gray、静的）の CDC を出す**（構造上避けられない。値は aresetn の解除の後にしか変わらない）。

`timescale 1ns / 1ps

module time_core #(
    parameter integer BEATS_PER_SEC = 256000000,
    parameter integer BLANK_BEATS   = 128000000,    // 0.5 s より短い間隔の縁はグリッチ
    parameter integer MISS_BEATS    = 384000000,    // 1.5 s 来なければ「来ていない」
    parameter integer BUILD_TAG     = 0,
    parameter integer BIT_KIND      = 2,            // proj021 手順 2-1: SAM45-Fine
    parameter integer BIT_REV       = 1,
    parameter integer PROJ          = 2163200   // = 0x0021_0200。**10 進で書く**（32'h で書くと Vivado が CONFIG.PROJ を読み返しで別の形にし、build.tcl の照合が落ちた。2026-10-09）
)(
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET aresetn" *)
    input  wire         aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire         aresetn,
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 ctrl_aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_RESET ctrl_aresetn" *)
    input  wire         ctrl_aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 ctrl_aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  wire         ctrl_aresetn,
    input  wire         pps_trig_i,
    input  wire         pps_comp_i,
    input  wire [7:0]   s_axi_awaddr,
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
    input  wire [7:0]   s_axi_araddr,
    input  wire [2:0]   s_axi_arprot,
    input  wire         s_axi_arvalid,
    output wire         s_axi_arready,
    output reg  [31:0]  s_axi_rdata,
    output wire [1:0]   s_axi_rresp,
    output reg          s_axi_rvalid,
    input  wire         s_axi_rready,
    // コアへ（各コアで 1 段受ける）
    output reg  [63:0]  t_out,
    output reg          go_out,
    output reg  [3:0]   ev_out
);
    localparam [7:0]  BK8 = BIT_KIND, BR8 = BIT_REV;
    localparam [31:0] ID = {8'd2, BK8, BR8, 8'd2};   // proj021 手順 2-1: IF_ID（CORE_KIND 2）。旧: 0x0021_7101（proj021 1b: 中身は proj020 と同一（ギアボックスの遅れが変わり timebase.CAL を測り直すため ID だけ）。proj020: 中身は proj017 と同一（timebase.CAL を bit ごとに持つため）。proj017 0x0017_7101: 中身は proj016 rev1 と同一。ID だけ（timebase.CAL を bit ごと・ADC ごとに持つため）
    wire rst = ~aresetn;

    // ---------------------------------------------------------------- 書き込み
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    reg [63:0] start_at;
    reg        r_pol, r_src;
    reg [7:0]  r_tol;
    reg        c_arm, c_cancel, c_aset, c_aclr, c_nclr;
    always @(posedge aclk) begin
        c_arm <= 1'b0; c_cancel <= 1'b0; c_aset <= 1'b0; c_aclr <= 1'b0; c_nclr <= 1'b0;
        if (rst) begin
            s_axi_bvalid <= 1'b0; start_at <= 64'd0; r_pol <= 1'b0; r_src <= 1'b0; r_tol <= 8'd1;
        end else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) begin
                s_axi_bvalid <= 1'b1;
                case (s_axi_awaddr[7:2])
                    6'h02: begin
                        c_arm <= s_axi_wdata[0]; c_cancel <= s_axi_wdata[1];
                        c_aset <= s_axi_wdata[3]; c_aclr <= s_axi_wdata[4]; c_nclr <= s_axi_wdata[8];
                    end
                    6'h03: begin r_pol <= s_axi_wdata[0]; r_src <= s_axi_wdata[1]; r_tol <= s_axi_wdata[15:8]; end
                    6'h04: start_at[31:0]  <= s_axi_wdata;
                    6'h05: start_at[63:32] <= s_axi_wdata;
                    default: ;
                endcase
            end
        end
    end

    // ---------------------------------------------------------------- T
    reg [63:0] T;
    always @(posedge aclk) begin
        if (rst) T <= 64'd0;
        else     T <= T + 64'd1;
    end
    // t_out は T の 1 クロック先（コアが 1 段受けると、コアの t_loc == その時の T）。T とは別の自走のカウンタにして加算器を挟まない
    always @(posedge aclk) begin
        if (rst) t_out <= 64'd1;
        else     t_out <= t_out + 64'd1;
    end

    // ---------------------------------------------------------------- PPS
    (* ASYNC_REG = "TRUE" *) reg [2:0] tsync;
    (* ASYNC_REG = "TRUE" *) reg [2:0] csync;
    always @(posedge aclk) begin
        if (rst) begin tsync <= 3'b111; csync <= 3'b111; end   // 1 で始める: 解除の瞬間に PPS が H でも縁にしない
        else begin
            tsync <= {tsync[1:0], pps_trig_i ^ r_pol};
            csync <= {csync[1:0], pps_comp_i ^ r_pol};
        end
    end
    wire t_edge = tsync[1] & ~tsync[2];
    wire c_edge = csync[1] & ~csync[2];

    reg [31:0] t_age, c_age;
    reg [63:0] t_stamp, c_stamp;
    reg [31:0] t_int, c_int, t_cnt, c_cnt;
    reg [15:0] t_gl, c_gl;
    wire t_ok = (t_age >= BLANK_BEATS);
    wire c_ok = (c_age >= BLANK_BEATS);
    wire t_acc = t_edge & t_ok;
    wire c_acc = c_edge & c_ok;
    always @(posedge aclk) begin
        if (rst || c_nclr) begin
            t_gl <= 16'd0; c_gl <= 16'd0;
        end else begin
            if (t_edge && !t_ok && t_gl != 16'hFFFF) t_gl <= t_gl + 16'd1;
            if (c_edge && !c_ok && c_gl != 16'hFFFF) c_gl <= c_gl + 16'd1;
        end
        if (rst) begin
            t_age <= MISS_BEATS; c_age <= MISS_BEATS;
            t_stamp <= 64'd0; c_stamp <= 64'd0; t_int <= 32'd0; c_int <= 32'd0; t_cnt <= 32'd0; c_cnt <= 32'd0;
        end else begin
            if (t_acc)                   t_age <= 32'd0;
            else if (t_age < MISS_BEATS) t_age <= t_age + 32'd1;
            if (c_acc)                   c_age <= 32'd0;
            else if (c_age < MISS_BEATS) c_age <= c_age + 32'd1;
            if (t_acc) begin t_stamp <= T; t_int <= T[31:0] - t_stamp[31:0]; t_cnt <= t_cnt + 32'd1; end
            if (c_acc) begin c_stamp <= T; c_int <= T[31:0] - c_stamp[31:0]; c_cnt <= c_cnt + 32'd1; end
        end
    end
    // 来ているか（比べの出口は 1 段受ける。proj007 の t_alive と同じ理由）
    reg t_alive, c_alive;
    always @(posedge aclk) begin
        if (rst) begin t_alive <= 1'b0; c_alive <= 1'b0; end
        else begin t_alive <= (t_age < MISS_BEATS); c_alive <= (c_age < MISS_BEATS); end
    end
    // 選んだ系統の間隔の判定: 採用した縁の次のクロックに間隔 − 1 秒（dev）を受け、その次のクロックに 2 個目以降なら |dev| > TOL を 1 クロック
    //   （減算と比べを別のクロックに分ける。`-1` の 3.9 ns に 2 本の桁上げを並べない）
    reg        s_acc_d, s_acc_d2, cnt2;
    reg signed [32:0] dev_q;
    reg        bad_p, gl_p, alive_s, alive_d;
    reg [15:0] n_bad, n_miss;
    wire [31:0] s_int = r_src ? c_int : t_int;
    wire [31:0] s_cnt = r_src ? c_cnt : t_cnt;
    wire signed [32:0] dev = $signed({1'b0, s_int}) - $signed({1'b0, BEATS_PER_SEC[31:0]});
    always @(posedge aclk) begin
        if (rst) begin
            s_acc_d <= 1'b0; s_acc_d2 <= 1'b0; cnt2 <= 1'b0; dev_q <= 33'sd0; bad_p <= 1'b0; gl_p <= 1'b0; alive_s <= 1'b0; alive_d <= 1'b0;
        end else begin
            s_acc_d  <= r_src ? c_acc : t_acc;
            s_acc_d2 <= s_acc_d;
            dev_q    <= dev;
            cnt2     <= (s_cnt >= 32'd2);
            bad_p    <= s_acc_d2 && cnt2 && (dev_q > $signed({25'd0, r_tol}) || dev_q < -$signed({25'd0, r_tol}));
            gl_p    <= r_src ? (c_edge && !c_ok) : (t_edge && !t_ok);
            alive_s <= r_src ? c_alive : t_alive;
            alive_d <= alive_s;
        end
        if (rst || c_nclr) begin n_bad <= 16'd0; n_miss <= 16'd0; end
        else begin
            if (bad_p && n_bad != 16'hFFFF) n_bad <= n_bad + 16'd1;
            if (alive_d && !alive_s && n_miss != 16'hFFFF) n_miss <= n_miss + 16'd1;
        end
    end
    reg anchored;
    always @(posedge aclk) begin
        if (rst) anchored <= 1'b0;
        else if (c_aset) anchored <= 1'b1;
        else if (c_aclr) anchored <= 1'b0;
    end
    // 「来ていない」（ev[0]）はリセットから最初の縁までも 1（縁を一度も見ていない = 来ていない）
    always @(posedge aclk) begin
        if (rst) ev_out <= 4'b1001;
        else     ev_out <= {!anchored, gl_p, bad_p, !alive_s};
    end

    // ---------------------------------------------------------------- 予約発火
    // **取り消し（CTRL[1]）と発火が同じクロックなら発火が勝つ**（FIRED で分かる）。取り消し・「遅すぎ」でもコアの側の ARM は残るので、
    // PS はコアの側も取り消す（pynq/timebase.py の TimeCore.arm が失敗したら timetest.py は全部のコアを DISARM する）
    // diff = START_AT − T（毎クロック。1 クロック前の T に対する値）。ARM の次のクロックの diff で範囲を判定し、
    // 残り rem（T が START_AT − 1 になるまでのクロック数）を下へ数える。比べは「rem == 1」をレジスタに置いておく
    reg [63:0] diff;
    always @(posedge aclk) diff <= start_at - T;
    reg        arm_d, pend, late, far, fired;
    reg [39:0] rem;
    reg        rem1;
    reg [63:0] fired_t;
    always @(posedge aclk) begin
        go_out <= 1'b0;
        if (rst) begin
            arm_d <= 1'b0; pend <= 1'b0; late <= 1'b0; far <= 1'b0; fired <= 1'b0; rem <= 40'd0; rem1 <= 1'b0; fired_t <= 64'd0;
        end else begin
            arm_d <= c_arm;
            // arm_d のクロック: diff = START_AT − T(前のクロック) = START_AT − T + 1
            //   コアの go_loc が立つクロックの T = START_AT（sim の tb_time で合わせた。rem の初期値 diff − 3）
            if (arm_d) begin
                late  <= diff[63] || (diff < 64'd16);
                far   <= !diff[63] && (diff[62:40] != 23'd0);
                pend  <= !diff[63] && (diff >= 64'd16) && (diff[62:40] == 23'd0);
`ifdef TIME_POSCTL
                rem   <= diff[39:0] - 40'd4;   // 陽性対照: 1 クロック早く発火する（sim の S-T1 が落ちること）
`else
                rem   <= diff[39:0] - 40'd3;
`endif
                rem1  <= 1'b0;
                fired <= 1'b0;
            end else if (pend) begin
                rem  <= rem - 40'd1;
                rem1 <= (rem == 40'd2);         // 次のクロックで rem == 1 → その次のクロック（rem == 0）で発火
                if (rem1) begin
                    go_out <= 1'b1;
                    pend   <= 1'b0;
                    fired  <= 1'b1;
                    fired_t <= T + 64'd2;      // コアの go_loc が立つクロックの T（go_out の 1 段後）
                end
            end
            if (c_cancel) pend <= 1'b0;
        end
    end

    // ---------------------------------------------------------------- エポック（ctrl_aclk 側）
    (* ASYNC_REG = "TRUE" *) reg [2:0] rstn_s;
    reg [31:0] epoch, epoch_g;
    always @(posedge ctrl_aclk) begin
        if (!ctrl_aresetn) begin
            rstn_s <= 3'b000; epoch <= 32'd0; epoch_g <= 32'd0;
        end else begin
            rstn_s <= {rstn_s[1:0], aresetn};
            if (rstn_s[1] & ~rstn_s[2]) epoch <= epoch + 32'd1;
            epoch_g <= epoch ^ (epoch >> 1);
        end
    end
    (* ASYNC_REG = "TRUE" *) reg [31:0] eg1, eg2;
    always @(posedge aclk) begin eg1 <= epoch_g; eg2 <= eg1; end
    reg [31:0] epoch_b;
    integer bi;
    always @* begin
        epoch_b[31] = eg2[31];
        for (bi = 30; bi >= 0; bi = bi - 1) epoch_b[bi] = epoch_b[bi+1] ^ eg2[bi];
    end

    // ---------------------------------------------------------------- 読み出し
    reg [7:0]  ar_addr;
    reg [1:0]  ar_wait;
    reg        ar_busy;
    assign s_axi_arready = !ar_busy && !s_axi_rvalid;
    assign s_axi_rresp   = 2'b00;
    wire ar_go = s_axi_arvalid && s_axi_arready;
    reg [31:0] t_hi_l, pt_hi_l, pt_int_l, pt_cnt_l, pc_hi_l, pc_int_l, pc_cnt_l;
    reg [31:0] rr;
    always @* begin
        case (ar_addr[7:2])
            6'h00: rr = ID;
            6'h01: rr = BEATS_PER_SEC;
            6'h02: rr = {23'd0, r_src, r_pol, c_alive, t_alive, anchored, fired, far, late, pend};
            6'h03: rr = {16'd0, r_tol, 6'd0, r_src, r_pol};
            6'h04: rr = start_at[31:0];
            6'h05: rr = start_at[63:32];
            6'h06: rr = T[31:0];
            6'h07: rr = t_hi_l;
            6'h08: rr = t_stamp[31:0];
            6'h09: rr = pt_hi_l;
            6'h0A: rr = pt_int_l;
            6'h0B: rr = pt_cnt_l;
            6'h0C: rr = c_stamp[31:0];
            6'h0D: rr = pc_hi_l;
            6'h0E: rr = pc_int_l;
            6'h0F: rr = pc_cnt_l;
            6'h10: rr = {c_gl, t_gl};
            6'h11: rr = {16'd0, n_bad};
            6'h12: rr = {16'd0, n_miss};
            6'h13: rr = epoch_b;
            6'h14: rr = fired_t[31:0];
            6'h15: rr = fired_t[63:32];
            6'h16: rr = BUILD_TAG;
            6'h17: rr = PROJ;
            default: rr = 32'hDEAD_BEEF;
        endcase
    end
    always @(posedge aclk) begin
        if (rst) begin
            ar_busy <= 1'b0; ar_wait <= 2'd0; s_axi_rvalid <= 1'b0; s_axi_rdata <= 32'd0; ar_addr <= 8'd0;
            t_hi_l <= 32'd0; pt_hi_l <= 32'd0; pt_int_l <= 32'd0; pt_cnt_l <= 32'd0; pc_hi_l <= 32'd0; pc_int_l <= 32'd0; pc_cnt_l <= 32'd0;
        end else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (ar_go) begin
                ar_busy <= 1'b1; ar_wait <= 2'd0; ar_addr <= s_axi_araddr;
            end else if (ar_busy) begin
                ar_wait <= ar_wait + 2'd1;
                if (ar_wait == 2'd0) begin
                    // LO の読みで、同じ瞬間の HI（と組の値）を固定する
                    if (ar_addr[7:2] == 6'h06) t_hi_l <= T[63:32];
                    if (ar_addr[7:2] == 6'h08) begin pt_hi_l <= t_stamp[63:32]; pt_int_l <= t_int; pt_cnt_l <= t_cnt; end
                    if (ar_addr[7:2] == 6'h0C) begin pc_hi_l <= c_stamp[63:32]; pc_int_l <= c_int; pc_cnt_l <= c_cnt; end
                    s_axi_rdata <= rr;
                end
                if (ar_wait == 2'd1) begin
                    ar_busy <= 1'b0;
                    s_axi_rvalid <= 1'b1;
                end
            end
        end
    end
endmodule
