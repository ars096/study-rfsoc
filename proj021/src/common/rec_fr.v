// SPDX-License-Identifier: BSD-3-Clause
//
// rec_fr — 閉じたダンプを SPEC のレコード（INTERFACE 4.4）にして AXI4-Stream（64 bit）に流す（proj021 手順 2-2a）
//
// 1 個のコアの中の NS 本の流れ（win_core の DDC の窓 / spec_core の FULL）に 1 個。流れの「凍ったバンク」を、
// 持ち主（win_core・spec_core）の AXI4-Lite の読みと**同じ読みの口**から読む（req → gnt の間だけ口を借りる）。
//
// ---- 流れ s ごと ----
//   seq[s] が +1 した（バンクが切り替わった）クロックに、REC_CTRL の ALL か ONE が立っていれば「出す予定」（pend）。
//   HOLD クロック待ってから（持ち主の DUMP_* が揃う）、順番に 1 本ずつ:
//     req → gnt（持ち主が AXI4-Lite の読みを止めて口を渡す）→ ヘッダ（hdr[s] の 6 語と、ここで作る w0・w7 を取り込む）
//     → ch 0..4095 の読み（rd_ch。LAT クロック後に rd_data）→ 64 bit × (8 + 4096) 語を m_axis に。最後の語で tlast
//   - 読み終わる前（4096 語を取り込む前）に同じ流れの seq がまた動いた → 最後の語に tuser = 1（捨てる）・late[s]
//   - 予定のまま、読み始める前に seq が +1 した → 古い予定は捨てて late[s]・drop[s]（リングの DROP_CNT にも数えさせる）
//   - seq が +1 以外に動いた（WRST・SRST のリセット）→ 予定を消す（読みかけなら tuser = 1・late[s]）
//   - tuser = 0 で出し終えたら one_clr[s]（持ち主が REC_CTRL の ONE を 0 に）
//   出たレコード（tuser = 0）は必ず 1 つの SEQ の、上書きされていないスペクトル。尾（CRC）はリング（s45_ring）が付ける
//
// ---- 口の時間 ----
//   rd_ch はここのレジスタ。持ち主は rd_ch をもう 1 段受けて記憶の番地にし、記憶の 2 段（rd1・rd2）の後にもう 1 段受けて rd_data にする
//   （LAT = 5: rd_ch → 番地 → rd1 → rd2 → rd_data。数えるのは「rd_ch に載ったクロック」から）。
//   取り込みは「出した番地の有効」を LAT 段遅らせたもので行う（持ち主の遅れが違えば sim で落ちる: tb_ring の照合）
//   出口の止まり（m_tready = 0）には FIFO（DEPTH 語。分散 RAM）で耐える。番地は FIFO の空き（出した数 − 出口に出した数）の範囲で出す
`timescale 1ns / 1ps

module rec_fr #(
    parameter integer NS     = 2,          // 流れの数（1..4）
    parameter integer S_BASE = 0,          // 流れの番号の最初（レコードの s = S_BASE + 流れ）
    parameter [7:0]   CORE   = 8'd0,       // レコードの core（CORE_PORT の ADC の番号）
    parameter integer LAT    = 5,          // rd_ch → rd_data（このモジュールから見て）
    parameter integer HOLD   = 8,          // seq が進んでからヘッダを取り込むまでの最小のクロック
    parameter integer DEPTH  = 32          // 出口の FIFO（2 の冪）
) (
    input  wire              clk,
    input  wire              rst,
    input  wire [32*NS-1:0]  seq,
    input  wire [384*NS-1:0] hdr,          // 流れごとに w1..w6（64 bit × 6、w1 が下位）。持ち主の DUMP_* を並べたもの
    input  wire [NS-1:0]     rec_all,
    input  wire [NS-1:0]     rec_one,
    output reg  [NS-1:0]     one_clr,
    output reg  [NS-1:0]     late,         // REC_LATE を +1
    output reg  [NS-1:0]     drop,         // リングの DROP_CNT を +1（読み始めなかった方。読みかけは tuser で）
    output reg               req,
    input  wire              gnt,
    output reg  [1:0]        rd_s,
    output reg  [11:0]       rd_ch,
    input  wire [63:0]       rd_data,
    output wire [63:0]       m_tdata,
    output wire              m_tvalid,
    input  wire              m_tready,
    output wire              m_tlast,
    output wire              m_tuser
);
    localparam integer NCH = 4096;
    localparam integer AW  = $clog2(DEPTH);
    localparam [31:0]  MAGIC = 32'h5235_3453;          // "S45R"（u32 の little endian）
    localparam [7:0]   REC_VER = 8'd1, TYPE_SPEC = 8'd1;
    localparam [7:0]   SB = S_BASE;

    // ---- 流れごとの見張り ----
    reg  [31:0] seq_d [0:NS-1];
    reg  [NS-1:0] pend;
    reg  [3:0]  age [0:NS-1];
    // proj021 2-2a ビルド 3 回目: 32 bit の +1 と比べ → 状態 → n_iss が 8 段で上位に出た。比べを 1 段受ける（気づくのが 1 クロック遅れるだけ。
    //   読みかけの判定は「取り込み終わる前」で見るので、遅れても上書きされた語を出すことはない: 取り込みは読みから 3 クロック遅れる）
    reg  [NS-1:0] inc, oth;
    wire [NS-1:0] rdy;
    genvar gs;
    generate
        for (gs = 0; gs < NS; gs = gs + 1) begin : g_s
            always @(posedge clk) begin
                inc[gs] <= !rst && (seq[32*gs +: 32] == seq_d[gs] + 32'd1);
                oth[gs] <= !rst && (seq[32*gs +: 32] != seq_d[gs]) && (seq[32*gs +: 32] != seq_d[gs] + 32'd1);
            end
            assign rdy[gs] = pend[gs] && (age[gs] >= HOLD);
        end
    endgenerate

    // ---- 状態 ----
    localparam [1:0] S_IDLE = 2'd0, S_REQ = 2'd1, S_RUN = 2'd2;
    reg  [1:0]  st;
    reg  [1:0]  rr;                         // 順番回しの次の候補
    reg  [511:0] hl;                        // 取り込んだヘッダ（w0..w7）
    reg         abort;
    reg  [12:0] n_iss;                      // 出した番地の数（0..4096）
    reg  [12:0] n_cap;                      // 取り込んだ語の数
    reg  [13:0] n_out;                      // 出口に出した語の数（0..8+4096）
    reg  [LAT-1:0] vsr;
    reg  [AW:0] occ;                        // 出したが出口に出していない本体の語（FIFO ＋ 道中）

    // 次の流れ（rr から順に、rdy のもの）
    reg  [1:0]  nx;
    reg         nx_v;
    integer i;
    always @* begin
        nx = 2'd0; nx_v = 1'b0;
        for (i = NS - 1; i >= 0; i = i - 1)
            if (rdy[(rr + i) % NS]) begin nx = (rr + i) % NS; nx_v = 1'b1; end
    end

    // ---- FIFO（本体の語）----
    reg  [63:0] fm [0:DEPTH-1];
    reg  [AW-1:0] fw, fr;
    wire        cap = vsr[LAT-1];
    always @(posedge clk) if (cap) fm[fw] <= rd_data;
    reg  [AW:0] fcnt;                       // FIFO の中の語
    wire        in_hdr  = (n_out < 14'd8);
    assign m_tvalid = (st == S_RUN) && (in_hdr || fcnt != 0);
    assign m_tdata  = in_hdr ? hl[64*n_out[2:0] +: 64] : fm[fr];
    assign m_tlast  = (n_out == 14'd8 + NCH - 1);
    assign m_tuser  = m_tlast && abort;
    wire        pop  = m_tvalid && m_tready;
    wire        popb = pop && !in_hdr;
    wire        iss  = (st == S_RUN) && (n_iss < NCH) && (occ < DEPTH);

    integer k;
    always @(posedge clk) begin
        one_clr <= {NS{1'b0}};
        late    <= {NS{1'b0}};
        drop    <= {NS{1'b0}};
        if (rst) begin
            st <= S_IDLE; rr <= 2'd0; req <= 1'b0; rd_s <= 2'd0; rd_ch <= 12'd0; abort <= 1'b0;
            n_iss <= 13'd0; n_cap <= 13'd0; n_out <= 14'd0; vsr <= {LAT{1'b0}}; occ <= 0; fcnt <= 0; fw <= 0; fr <= 0;
            pend <= {NS{1'b0}};
            for (k = 0; k < NS; k = k + 1) begin seq_d[k] <= seq[32*k +: 32]; age[k] <= 4'd0; end
        end else begin
            // ---- 流れごとの seq ----
            for (k = 0; k < NS; k = k + 1) begin
                seq_d[k] <= seq[32*k +: 32];
                if (age[k] != 4'hF) age[k] <= age[k] + 4'd1;
                if (inc[k]) begin
                    age[k] <= 4'd0;
                    pend[k] <= rec_all[k] | rec_one[k];
                    if (pend[k]) begin late[k] <= 1'b1; drop[k] <= 1'b1; end       // 読み始めなかった
                end else if (oth[k]) begin
                    pend[k] <= 1'b0;
                end
            end
            // ---- 読みかけの流れが動いた（取り込み終わる前）----
            if (st == S_RUN && (inc[rd_s] || oth[rd_s]) && n_cap < NCH && !abort) begin
                abort <= 1'b1;
                late[rd_s] <= 1'b1;
            end

            // ---- 番地と取り込み ----
            vsr <= {vsr[LAT-2:0], iss};
            if (iss) begin rd_ch <= n_iss[11:0]; n_iss <= n_iss + 13'd1; end
            if (cap) begin fw <= fw + 1'b1; n_cap <= n_cap + 13'd1; end
            if (popb) fr <= fr + 1'b1;
            occ  <= occ  + (iss ? 1 : 0) - (popb ? 1 : 0);
            fcnt <= fcnt + (cap ? 1 : 0) - (popb ? 1 : 0);
            if (pop) n_out <= n_out + 14'd1;

            case (st)
                S_IDLE: if (nx_v) begin
                    st <= S_REQ; rd_s <= nx; req <= 1'b1;
                end
                S_REQ: begin
                    if (!rdy[rd_s] || inc[rd_s] || oth[rd_s]) begin
                        st <= S_IDLE; req <= 1'b0;                // 待つ間に予定が動いた（新しいダンプは HOLD から）
                    end else if (gnt) begin
                        st <= S_RUN;
                        pend[rd_s] <= 1'b0;
                        abort <= 1'b0;
                        n_iss <= 13'd0; n_cap <= 13'd0; n_out <= 14'd0;
                        hl <= {64'd32768,
                               hdr[384*rd_s +: 384],
                               {SB + {6'd0, rd_s}, CORE, TYPE_SPEC, REC_VER, MAGIC}};
                    end
                end
                S_RUN: begin
                    if (n_cap == NCH - 1 && cap) req <= 1'b0;        // 口を返す（出口はまだ流れている）
                    if (pop && m_tlast) begin
                        st <= S_IDLE;
                        rr <= (rd_s + 2'd1 == NS) ? 2'd0 : rd_s + 2'd1;
                        if (!abort && !((inc[rd_s] || oth[rd_s]) && n_cap < NCH)) one_clr[rd_s] <= 1'b1;
                    end
                end
                default: st <= S_IDLE;
            endcase
        end
    end
endmodule
