// SPDX-License-Identifier: BSD-3-Clause
//
// tp_core — 全帯域の total power（Σ x²）を 1 ms ごとに積み、リングバッファに残す（proj013 rev1）
//
// proj017: FLAGS[4]「区切りの中に ADC の振り切れ（|x16| ≧ OVR_TH のサンプル）があった」を足した。TP_PARAM の版 1 → 2。
//   判定は adc_ev と同じ式（16 bit の値で ±32764 = 8191 << 2）。sim の陽性対照 TP_OVR_POSCTL は ≧ を > にする（+32764 を見落とす）
//
// spec_core の中に 1 個置く（ch ごとに 1 個）。spec_core と同じ DSP ドメイン（256 MHz）で動き、
// **入力のビート・フレーム番号（fin）・RUN はすべて spec_core のものをそのまま使う**。だから
// total power の区切りとスペクトルのダンプは同じフレーム番号の上に並ぶ。
//
// ---- 何を積むか ----
// レーン FFT に入れるのと同じ 14 bit の値 x = ADC の 16 bit >>> 2 の二乗の和。1 ビート 16 サンプル。
//   1 区切り = TP_N フレーム（既定 500 = 1.000 ms。1 フレーム = 8192 サンプル = 2 µs）
//   |x| ≦ 2^13 → x² ≦ 2^26。1 区切りの和 ≦ 2^26 · 8192 · TP_N。**64 bit の和は TP_N < 2^25 フレーム（67 s）まで溢れない**
// スペクトルとの突き合わせ（パーセバルの定理）: Σ_{n} x[n]² = (1/8192) Σ_{k=0}^{8191} |X[k]|²（フレームごと）
//
// ---- 区切り ----
// 区切りはフレームの頭（m_in = 0 のビート）にだけ置く。次のどれかのフレームの頭で新しい区切りを始める:
//   (a) 起動（リセット・GRST・SRST）の後の最初のビート
//   (b) RUN で予約した開始フレーム F0（= RUN の時点の fin + 2。**spec_core の RUN_F0 と同じ式・同じクロック**）
//   (c) 今の区切りが TP_N フレームに達した（今効いている TP_N 以上。等号にすると、F0 を取りこぼしたまま TP_N を
//       小さくしたとき区切りが二度と閉じない。sim の陽性対照で WP が 7 で止まって見つけた）
// RUN の前は (a) から TP_N フレームずつ自走する。RUN の後は **F0 + TP_N·n** に揃う（100 ms のダンプ 1 回 = 1 ms の区切り 100 個）。
// (b) で打ち切られた区切りは TP_N に満たない（FLAGS[0] 短い）。TP_N は RUN の時点で取り込む（N_ACC と同じ）。
//   **RUN を書いた直後の 2 クロックに来るフレームの頭は、旧い TP_N で判定されることがある**（pre_* の遅れ）。
//   F0 は必ず 2 フレーム以上先なので、F0 からの区切りは新しい TP_N で揃う。
//
// ---- 時間の決め方（proj012 rev3 の `-1` の最悪経路から）----
// - ファブリックの加算から DSP の入口へ直につながない: 二乗の DSP は入口にレジスタを 2 段（AREG/BREG = 2）、
//   出口に M・P を置き、加算木は 1 段ごとにレジスタで区切る（16 → 8 → 4 → 2 → 1）
// - 入力は s1 で 1 回だけ受ける（spec_core の入力のファンアウトに足すのはこの 256 本だけ）
// - フレームの頭の判定に使う 48 bit の比較は、前のクロックにレジスタへ置く（pre_*。spec_core rev2 と同じ考え方）
//
// ---- リングバッファ（512 個 × 16 バイト = 8 KiB、BRAM36 × 2）----
// 区切りが閉じるたびに 1 個書き、TP_WP（書いた個数。リセット以来、巻き戻らない）を 1 増やす。個 i は slot i mod 512。
//   語 0  和 [31:0]
//   語 1  和 [63:32]
//   語 2  区切りの最初のフレームの番号 [31:0]（**個が自分がどの区切りかを持つ**。読み出しの食い違いはこれで見つける）
//   語 3  [31:24] FLAGS / [23:0] フレーム数
//   FLAGS: [0] 短い（フレーム数 ≠ その区切りの TP_N）/ [1] F0 で始まった（RUN の最初の区切り）/
//          [2] 隙間（区切りの中で入力のビートが来ないクロックがあった）/ [3] 起動の後の最初の区切り /
//          [4] 振り切れ（区切りの中に |x16| ≧ OVR_TH のサンプル。proj017）
// 512 個 = 1 ms × 512 = 0.512 s。PS は TP_WP を読み → 個を読み → TP_WP を読み直す。その間に 512 個進まなければ中身は正しい。
//
// ---- レジスタ（spec_core の窓の 0x0100–0x01FF。語の番号 = A[7:2]）----
//   0x100 TP_N     RW  [23:0] 1 区切りのフレーム数（0 は 1 とみなす）。RUN の時点で取り込む。既定 TPN_DEFAULT
//   0x104 TP_NEFF  R   [23:0] 今効いている TP_N
//   0x108 TP_WP    R   閉じた区切りの個数（リセット以来）
//   0x10C TP_F0_LO R   最後の RUN の F0（RUN_F0 と一致するはず）/ 0x110 TP_F0_HI
//   0x114 TP_PARAM R   [31:16] 個の数 512 / [15:8] 個のバイト数 16 / [7:0] 版 2（proj017: FLAGS[4]。proj013〜016 は 1）
//   0x118 TP_STAT  R   [0] F0 待ち / [1] 区切りの途中（起動の後に最初のビートを見た）
// リングバッファは 0x2000–0x3FFF（個 i の語 w は 0x2000 + 16·(i mod 512) + 4·w）

`timescale 1ns / 1ps

module tp_core #(
    parameter integer TPN_DEFAULT = 500,
    parameter integer FW          = 48,
    parameter integer OVR_TH      = 32764,
    // proj021 2-2b: TP のレコード（INTERFACE 4.6、type 2）。REC = 1 は win_core の TP だけ（FULL の TP は 0 で今どおり）
    parameter integer REC         = 0,
    parameter [7:0]   REC_CORE    = 8'd0,
    parameter integer REC_EN_DEFAULT = 0
)(
    input  wire          clk,
    input  wire          rst,          // spec_core の rst_core（起動のやり直しでも張り直す）
    input  wire          in_acc,       // このクロックのビートを IP が受けた（spec_core の in_acc）
    input  wire [8:0]    m_in,         // そのビートのフレーム内の番号
    input  wire [FW-1:0] fin,          // そのビートのフレーム番号
    input  wire [255:0]  tdata,        // 16 サンプル × 16 bit（下位が古い）
    input  wire          cmd_run,      // RUN（1 クロック）
    input  wire          wr_en,        // 0x0100–0x01FF への書き込み
    input  wire [5:0]    wr_addr,
    input  wire [31:0]   wr_data,
    input  wire [15:0]   rd_addr,      // spec_core が保持している読み出しの番地
    output wire [31:0]   rd_ring,      // リングバッファの語（rd_addr から 2 クロック後に有効）
    output reg  [31:0]   rd_reg,       // レジスタ（rd_addr から組み合わせ）
    // proj021 2-2b: TP のレコード（REC = 1 のときだけ使う）
    input  wire [63:0]   t_now,        // このクロックの T（win_core の t_loc。TANCH の ANCH_T と同じ物差し）
    output wire [63:0]   m_tdata,
    output wire          m_tvalid,
    input  wire          m_tready,
    output wire          m_tlast,
    output wire          m_tuser,
    output reg           rec_drop      // レコードを 1 個捨てた（1 クロック）
);
    localparam integer NL = 16;
    localparam integer DEPTH_L2 = 9;
    localparam integer NW = 24;        // フレーム数の語幅

    // =====================================================================
    // s0: フレームの頭の判定
    // =====================================================================
    reg  [NW-1:0] r_tpn, tp_n, tpn_m1;
    reg  [NW-1:0] fcur;                // 今の区切りの中でのフレームの番号（0..TP_N−1）
    reg  [FW-1:0] pend_f0, pend_m1;
    reg           pend_arm, started;
    reg           pre_f0hit, pre_nhit;
    reg  [63:0]   t_s0;                // proj021 2-2b
    wire [NW-1:0] tpn_eff    = (tp_n == {NW{1'b0}}) ? {{(NW-1){1'b0}}, 1'b1} : tp_n;
    wire          first_beat = in_acc && (m_in == 9'd0);
    wire          hit_f0     = pend_arm && pre_f0hit;
    wire          bnd        = !started || hit_f0 || pre_nhit;

    always @(posedge clk) begin
        if (rst) begin
            r_tpn <= TPN_DEFAULT;
        end else if (wr_en && wr_addr == 6'h00) begin
            r_tpn <= wr_data[NW-1:0];
        end
    end

    always @(posedge clk) begin
        tpn_m1 <= tpn_eff - 1'b1;
        if (rst) begin
            tp_n <= TPN_DEFAULT;
            fcur <= {NW{1'b0}};
            pend_f0 <= {FW{1'b1}}; pend_m1 <= {FW{1'b1}}; pend_arm <= 1'b0;
            started <= 1'b0; pre_f0hit <= 1'b0; pre_nhit <= 1'b0;
        end else begin
            // 次に来るビートがフレームの頭なら、そのフレームの番号は m_in = 0 のとき fin、それ以外は fin + 1。
            // **隙間（valid = 0）が tlast と次の頭の間に入っても正しい**（fin は tlast で進むので、待っている間は fin そのもの）
`ifdef TP_POSCTL
            pre_f0hit <= cmd_run ? 1'b0 : (fin == pend_m1);           // 陽性対照: 隙間を考えない素朴な形（sim で落ちるはず）
`else
            pre_f0hit <= cmd_run ? 1'b0 : ((m_in == 9'd0) ? (fin == pend_f0) : (fin == pend_m1));
`endif
            pre_nhit  <= (fcur >= tpn_m1);                            // ≥: TP_N を小さくしても区切りが止まらない（陽性対照で見つけた）
            if (first_beat && bnd) t_s0 <= t_now;                   // proj021 2-2b: 区切りの最初のビートの T
            if (first_beat) begin
                started <= 1'b1;
                fcur    <= bnd ? {NW{1'b0}} : fcur + 1'b1;
                if (hit_f0) pend_arm <= 1'b0;
            end
            if (cmd_run) begin                                        // 最後に書く（同じクロックのフレームの頭より優先）
                pend_arm <= 1'b1;
                pend_f0  <= fin + 2;
                pend_m1  <= fin + 1;
                tp_n     <= r_tpn;
            end
        end
    end

    // =====================================================================
    // s1..s9: 二乗と加算木（データ）、s1..s9 の制御の遅延
    // =====================================================================
    localparam integer CD = 9;         // 制御の段数（s1..s9）
    reg           c_v [1:CD];
    reg           c_f [1:CD];          // 区切りの最初のビート
    reg           c_r [1:CD];          // F0 で始まる区切り
    reg [FW-1:0]  c_fin [1:CD];
    reg [NW-1:0]  c_n [1:CD];          // その区切りの TP_N
    reg [15:0]    o_hit;               // s1: レーンごとの振り切れ（proj017）
    reg           c_o [2:CD];          // s2..: そのビートに振り切れ
    integer i;
    always @(posedge clk) begin
        c_v[1]   <= in_acc && !rst;
        c_f[1]   <= first_beat && bnd;
        c_r[1]   <= first_beat && hit_f0;
        c_fin[1] <= fin;
        c_n[1]   <= tpn_eff;
        for (i = 2; i <= CD; i = i + 1) begin
            c_v[i] <= c_v[i-1]; c_f[i] <= c_f[i-1]; c_r[i] <= c_r[i-1];
            c_fin[i] <= c_fin[i-1]; c_n[i] <= c_n[i-1];
        end
        for (i = 0; i < NL; i = i + 1)
`ifdef TP_OVR_POSCTL
            o_hit[i] <= ($signed(tdata[16*i +: 16]) >  $signed(OVR_TH)) || ($signed(tdata[16*i +: 16]) < -$signed(OVR_TH));   // 陽性対照
`else
            o_hit[i] <= ($signed(tdata[16*i +: 16]) >= $signed(OVR_TH)) || ($signed(tdata[16*i +: 16]) <= -$signed(OVR_TH));
`endif
        c_o[2] <= |o_hit;              // valid でないビートの値は c_v で捨てる
        for (i = 3; i <= CD; i = i + 1) c_o[i] <= c_o[i-1];
        if (rst) for (i = 1; i <= CD; i = i + 1) c_v[i] <= 1'b0;
    end

    wire [27*NL-1:0] sq;               // s5 の二乗（27 bit、非負）
    genvar p;
    generate
        for (p = 0; p < NL; p = p + 1) begin : g_sq
            wire signed [15:0] xs = tdata[16*p +: 16];
            reg  signed [13:0] xr;                            // s1（ファブリック）
            (* use_dsp = "yes" *) reg signed [13:0] a1, a2;   // s2・s3（AREG/BREG = 2 に吸われる）
            (* use_dsp = "yes" *) reg signed [26:0] m, pp;    // s4（MREG）・s5（PREG）
            always @(posedge clk) begin
                xr <= xs >>> 2;
                a1 <= xr;
                a2 <= a1;
                m  <= a2 * a2;
                pp <= m;
            end
            assign sq[27*p +: 27] = pp;
        end
    endgenerate

    reg [27:0] t8 [0:7];               // s6
    reg [28:0] t4 [0:3];               // s7
    reg [29:0] t2 [0:1];               // s8
    reg [30:0] t1;                     // s9
    always @(posedge clk) begin
        for (i = 0; i < 8; i = i + 1) t8[i] <= {1'b0, sq[27*(2*i) +: 27]} + {1'b0, sq[27*(2*i+1) +: 27]};
        for (i = 0; i < 4; i = i + 1) t4[i] <= {1'b0, t8[2*i]} + {1'b0, t8[2*i+1]};
        for (i = 0; i < 2; i = i + 1) t2[i] <= {1'b0, t4[2*i]} + {1'b0, t4[2*i+1]};
        t1 <= {1'b0, t2[0]} + {1'b0, t2[1]};
    end

    // =====================================================================
    // s10: 区切りの和。s11: リングバッファへ
    // =====================================================================
    reg [63:0]        acc;
    reg [FW-1:0]      b_f0;
    reg [NW+8:0]      b_beats;         // ビートの数（フレーム数 × 512）
    reg [NW-1:0]      b_n;
    reg               b_run, b_gap, b_boot, b_ovr, have, boot;
    reg               e_we;
    reg [127:0]       e_data;
    reg [FW-1:0]      e_f0;            // proj021 2-2b: 個の最初のフレーム（48 bit）
    reg [63:0]        b_t, e_t;        // proj021 2-2b: 区切りの最初のビートの T
    reg [31:0]        wp;
    wire [NW-1:0]     b_nfr   = b_beats[NW+8:9];
    wire              b_short = (b_beats[8:0] != 9'd0) || (b_nfr != b_n);

    always @(posedge clk) begin
        e_we <= 1'b0;
        if (rst) begin
            have <= 1'b0; boot <= 1'b1;
            acc <= 64'd0; b_f0 <= {FW{1'b0}}; b_beats <= 0; b_n <= 0;
            b_run <= 1'b0; b_gap <= 1'b0; b_boot <= 1'b0; b_ovr <= 1'b0;
        end else if (c_v[CD]) begin
            if (c_f[CD]) begin
                if (have) begin
                    e_we   <= 1'b1;
                    e_data <= {{3'd0, b_ovr, b_boot, b_gap, b_run, b_short}, b_nfr, b_f0[31:0], acc};
                    e_f0   <= b_f0;
                    e_t    <= b_t;
                end
                acc <= {33'd0, t1}; b_f0 <= c_fin[CD]; b_beats <= 1; b_n <= c_n[CD];
                b_t <= t_s0;                   // s0 で取った T（次の区切りの頭は 1 フレーム以上先なので、まだ書き換わっていない）
                b_run <= c_r[CD]; b_gap <= 1'b0; b_boot <= boot; boot <= 1'b0; have <= 1'b1;
                b_ovr <= c_o[CD];
            end else begin
                acc     <= acc + {33'd0, t1};
                b_beats <= b_beats + 1'b1;
                if (c_o[CD]) b_ovr <= 1'b1;
            end
        end else if (have) begin
            b_gap <= 1'b1;
        end
    end

    reg [127:0] ring [0:(1<<DEPTH_L2)-1];
    always @(posedge clk) begin
        if (rst) wp <= 32'd0;
        else if (e_we) wp <= wp + 32'd1;
        if (e_we) ring[wp[DEPTH_L2-1:0]] <= e_data;
    end

    // =====================================================================
    // 読み出し
    // =====================================================================
    reg [127:0] q1, q2;
    always @(posedge clk) begin
        q1 <= ring[rd_addr[DEPTH_L2+3:4]];
        q2 <= q1;
    end
    assign rd_ring = q2[32*rd_addr[3:2] +: 32];

    always @* begin
        case (rd_addr[7:2])
            6'h00: rd_reg = {{(32-NW){1'b0}}, r_tpn};
            6'h01: rd_reg = {{(32-NW){1'b0}}, tpn_eff};
            6'h02: rd_reg = wp;
            6'h03: rd_reg = pend_f0[31:0];
            6'h04: rd_reg = {{(64-FW){1'b0}}, pend_f0[FW-1:32]};
            6'h05: rd_reg = {16'd512, 8'd16, 8'd2};
            6'h06: rd_reg = {30'd0, started, pend_arm};
            6'h07: rd_reg = (REC != 0) ? {19'd0, rc_k, 7'd0, rc_en} : 32'hDEAD_BEEF;   // proj021 2-2b: 0x11C TP_REC_CTRL
            6'h08: rd_reg = (REC != 0) ? rc_late : 32'hDEAD_BEEF;                       // 0x120 TP_REC_LATE
            default: rd_reg = 32'hDEAD_BEEF;
        endcase
    end

    // =====================================================================
    // proj021 2-2b: TP のレコード（type 2）。個（e_we）を K 個ずつ 1 レコードに
    //   区切り: K 個 / F0 で始まった個（FLAGS[1]）の前 / 短い個（FLAGS[0]）の後
    //   溜め 2 面。2 面とも埋まっているときに始まったレコードは丸ごと捨てる（rc_late・rec_drop）
    //   頭: w0 {0xFF, core, 2, 1, "S45R"} / w1 SEQ（最初の個の番号）/ w2 F0（48 bit）/ w3 T / w5 DUMP_N / w7 中身のバイト数
    // =====================================================================
    reg        rc_en;
    reg [4:0]  rc_k;
    reg [31:0] rc_late;
    wire [4:0] kk = (rc_k == 5'd0) ? 5'd10 : (rc_k > 5'd16) ? 5'd16 : rc_k;
    always @(posedge clk) begin
        if (rst) begin rc_en <= (REC_EN_DEFAULT != 0); rc_k <= 5'd10; end
        else if (wr_en && wr_addr == 6'h07) begin rc_en <= wr_data[0]; rc_k <= wr_data[12:8]; end
    end
    generate
        if (REC != 0) begin : g_rec
            reg [127:0] bm [0:31];            // {面, 個 4 bit}
            reg [1:0]   full;                 // 面ごと: 出すのを待っている
            reg [4:0]   bn [0:1];             // 面ごとの個の数
            reg [31:0]  bseq [0:1];
            reg [FW-1:0] bf0 [0:1];
            reg [63:0]  bt [0:1];
            reg         cb;                   // 埋めている面
            reg [4:0]   cnt;                  // 今のレコードの個の数（捨てているレコードも数える）
            reg         dropping;
            // 出す側
            reg         eb;                   // 出している面
            reg         busy;
            reg [5:0]   oi;                   // 出した語（頭 8 ＋ 中身）
            reg [5:0]   olen;                 // 語の数（8 ＋ 中身の語）
            wire [63:0] w_hdr = (oi == 6'd0) ? {8'hFF, REC_CORE, 8'd2, 8'd1, 32'h5235_3453} :
                                (oi == 6'd1) ? {32'd0, bseq[eb]} :
                                (oi == 6'd2) ? {{(64-FW){1'b0}}, bf0[eb]} :
                                (oi == 6'd3) ? bt[eb] :
                                (oi == 6'd5) ? {27'd0, bn[eb]} :
                                (oi == 6'd7) ? {32'd0, 19'd0, (bn[eb] + 5'd3) >> 2, 6'd0} : 64'd0;
            wire [5:0]  pi  = oi - 6'd8;      // 中身の語の番号（個 = pi >> 1）
            wire [127:0] it = bm[{eb, pi[4:1]}];
            wire [63:0] w_pay = (pi[5:1] < bn[eb]) ? (pi[0] ? it[127:64] : it[63:0]) : 64'd0;
            assign m_tdata  = (oi < 6'd8) ? w_hdr : w_pay;
            assign m_tvalid = busy;
            assign m_tlast  = busy && (oi == olen - 6'd1);
            assign m_tuser  = 1'b0;
            wire go = busy && m_tready;

            // 個を受ける側
            wire        f_run   = e_data[121];          // FLAGS[1]: F0 で始まった
            wire        f_short = e_data[120];          // FLAGS[0]: 短い
            reg         c1;                             // 今のクロックで「先に閉じる」
            reg         nb, nd;                         // 新しく始めるときの面・捨てるか
            reg [4:0]   nc;
            always @(posedge clk) begin
                rec_drop <= 1'b0;
                if (rst) begin
                    full <= 2'b00; cb <= 1'b0; cnt <= 5'd0; dropping <= 1'b0; rc_late <= 32'd0;
                    eb <= 1'b0; busy <= 1'b0; oi <= 6'd0; olen <= 6'd0;
                end else begin
                    // ---- 出す ----
                    if (!busy && full[eb]) begin
                        busy <= 1'b1; oi <= 6'd0;
                        olen <= 6'd8 + {((bn[eb] + 5'd3) >> 2), 3'd0};
                    end else if (go) begin
                        if (oi == olen - 6'd1) begin
                            busy <= 1'b0; full[eb] <= 1'b0; eb <= ~eb;
                        end else oi <= oi + 6'd1;
                    end
                    // ---- 受ける ----
                    if (!rc_en) begin
                        cnt <= 5'd0; dropping <= 1'b0;
                    end else if (e_we) begin
                        nb = cb; nd = dropping; nc = cnt;
                        // F0 で始まった個の前で閉じる
`ifdef TP_REC_POSCTL
                        if (1'b0) begin                     // 陽性対照: F0 で始まった個の前で区切らない（sim-tprec-p で落ちるべき）
`else
                        if (f_run && nc != 5'd0) begin
`endif
                            if (nd) begin rc_late <= rc_late + 32'd1; rec_drop <= 1'b1; end
                            else begin full[nb] <= 1'b1; nb = ~nb; end
                            nc = 5'd0;
                        end
                        // 新しいレコードの頭: 面が空いていなければ捨てる
                        if (nc == 5'd0) begin
                            nd = full[nb] || (nb != cb && full[nb]) ;
                            if (!nd) begin bseq[nb] <= wp; bf0[nb] <= e_f0; bt[nb] <= e_t; end
                        end
                        if (!nd) begin bm[{nb, nc[3:0]}] <= e_data; bn[nb] <= nc + 5'd1; end
                        nc = nc + 5'd1;
                        // K 個・短い個の後で閉じる
                        if (nc == kk || f_short) begin
                            if (nd) begin rc_late <= rc_late + 32'd1; rec_drop <= 1'b1; end
                            else begin full[nb] <= 1'b1; nb = ~nb; end
                            nc = 5'd0; nd = 1'b0;
                        end
                        cb <= nb; cnt <= nc; dropping <= nd;
                    end
                end
            end
        end else begin : g_norec
            assign m_tdata = 64'd0; assign m_tvalid = 1'b0; assign m_tlast = 1'b0; assign m_tuser = 1'b0;
            always @(posedge clk) begin rec_drop <= 1'b0; rc_late <= 32'd0; end
        end
    endgenerate
endmodule
