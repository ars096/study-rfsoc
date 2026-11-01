// SPDX-License-Identifier: BSD-3-Clause
//
// fine_rdo — 細かい側の読み出し（proj028 F-3）。積分が閉じた面から、荒い ch k の 7/8 の bin をつないだ順に出す
//
// つないだ順 i = 0..114687（G = k·114688 ＋ i）: j = ⌊i / 8192⌋（0..13）、k1 = i mod 8192、**k2 = (j ＋ s_k − 7) mod 16**、s_k = (14k + 7) mod 16
//   （bin の巡回 sh_k = s_k·8192 は銀行の入れ替えだけ。M-4・README の F-3）。b = k1 + 8192·k2 を fine_acc の rd_c に
// 出口: AXI4-Stream 64 bit。頭 8 語 → 114,688 語（fine_acc の 48 bit を u64 に）、最後の語で tlast
//   **proj037 U-4: 頭は INTERFACE 4.4 の形**。w0 = {s, core, type 1, rec_ver 1, "S45R"}（ここで作る）、w1..w7 は外（帳簿、s2_strm）が作る（口の名前は hdr_w）:
//   start の後に hdr_v（1 拍）で hdr（w1 が下位、64 bit × 7）と hdr_bad を受け、受けるまで w1 を出さない。
//   hdr_bad = 1 のレコードは最後の語に tuser = 1（s45_ring が捨てる）
// 番地 → データは RL 拍（fine_acc の 4 段 ＋ 番地のレジスタ 1）。溜め FD 語の空き（溜めの中 ＋ 読み途中）を数えて読む
// 読み途中（busy）に start が来たら捨てて数える（n_drop、粘着の f_drop）
// -DRDO_K2_ERR: k2 の式の 7 を 6 にする（陽性対照）
// proj028 の頭（w0 = {ID, 114688}・w1 = {k, c}・w2 = 積んだ数・w3 = s_k）は proj037 で 4.4 の形に替えた。st_c・st_nfr は外が頭に使う

`timescale 1ns / 1ps

module fine_rdo #(
    parameter [7:0] SID_S    = 8'd0,
    parameter [7:0] REC_CORE = 8'd0,
    parameter integer RL = 5
)(
    input  wire        clk,
    input  wire        rst,
    input  wire        start,
    input  wire        st_plane,
    input  wire [4:0]  st_k,
    input  wire [31:0] st_c,
    input  wire [15:0] st_nfr,
    output reg  [16:0] rd_c,
    output reg         rd_plane,
    input  wire [63:0] rd_d,
    input  wire        hdr_v,
    input  wire [447:0] hdr_w,
    input  wire        hdr_bad,
    output wire [63:0] m_axis_tdata,
    output wire        m_axis_tlast,
    output wire        m_axis_tuser,
    output wire        m_axis_tvalid,
    input  wire        m_axis_tready,
    output reg         busy,
    output reg  [15:0] n_drop,
    output reg         f_drop
);
    localparam integer FD = 8;
`ifdef RDO_K2_ERR
    localparam [3:0] K2OFF = 4'd6;
`else
    localparam [3:0] K2OFF = 4'd7;
`endif
    reg        hdr;                 // 頭を出している
    reg [2:0]  hi;                  // 頭の語の番号
    reg [3:0]  j;                   // 0..13
    reg [12:0] k1;
    reg [3:0]  s;                   // s_k
    reg [447:0] hl;                 // 受けた w1..w7
    reg        hok, bad;
    reg        issued_all;
    // 溜め
    reg [63:0] fd [0:FD-1];
    reg        fl [0:FD-1];
    reg [3:0]  fn;
    reg [2:0]  fh, ft;
    reg [RL-1:0] pv, pl;            // 読み途中の印（データ・最後の語か）
    reg [3:0]  infl;
    wire o_fire = m_axis_tvalid && m_axis_tready;
    wire room   = ({1'b0, fn} + {1'b0, infl}) < FD;
    wire do_hdr = busy && hdr && room && (hi == 3'd0 || hok);
    wire do_rd  = busy && !hdr && !issued_all && room;
    wire last_rd = (j == 4'd13) && (k1 == 13'd8191);
    localparam [31:0] MAGIC = 32'h5235_3453;    // "S45R"（u32 の little endian）
    wire [63:0] hw = (hi == 3'd0) ? {SID_S, REC_CORE, 8'd1, 8'd1, MAGIC} : hl[64*(hi-1) +: 64];
    integer i;
    always @(posedge clk) begin
        if (rst) begin
            busy <= 1'b0; hdr <= 1'b0; issued_all <= 1'b0; hok <= 1'b0; bad <= 1'b0; fn <= 4'd0; fh <= 3'd0; ft <= 3'd0; pv <= {RL{1'b0}}; pl <= {RL{1'b0}};
            infl <= 4'd0; n_drop <= 16'd0; f_drop <= 1'b0;
        end else begin
            // 始める
            if (start) begin
                if (busy) begin n_drop <= n_drop + 16'd1; f_drop <= 1'b1; end
                else begin
                    busy <= 1'b1; hdr <= 1'b1; hi <= 3'd0; j <= 4'd0; k1 <= 13'd0; issued_all <= 1'b0;
                    s <= 4'd7 - {st_k[2:0], 1'b0};                       // (14k + 7) mod 16 = (7 − 2k) mod 16（4 bit で巻き戻る）
                    rd_plane <= st_plane; hok <= 1'b0;
                end
            end
            if (hdr_v && busy && hdr && !hok) begin hl <= hdr_w; bad <= hdr_bad; hok <= 1'b1; end
            // 頭
            if (do_hdr) begin
                fd[ft] <= hw; fl[ft] <= 1'b0; ft <= ft + 3'd1;
                if (hi == 3'd7) hdr <= 1'b0;
                hi <= hi + 3'd1;
            end
            // 読みの番地
            if (do_rd) begin
                rd_c <= {(j + s - K2OFF) & 4'hF, k1};
                if (k1 == 13'd8191) begin k1 <= 13'd0; j <= j + 4'd1; end else k1 <= k1 + 13'd1;
                if (last_rd) issued_all <= 1'b1;
            end
            pv <= {pv[RL-2:0], do_rd};
            pl <= {pl[RL-2:0], do_rd && last_rd};
            if (pv[RL-1]) begin fd[ft] <= rd_d; fl[ft] <= pl[RL-1]; ft <= ft + 3'd1; end
            infl <= infl + (do_rd ? 4'd1 : 4'd0) - (pv[RL-1] ? 4'd1 : 4'd0);
            fn <= fn + ((do_hdr || pv[RL-1]) ? 4'd1 : 4'd0) - (o_fire ? 4'd1 : 4'd0);
            if (o_fire) fh <= fh + 3'd1;
            // 終わり: 全部の番地を出し、読み途中も溜めも空
            if (busy && !hdr && issued_all && infl == 4'd0 && fn == 4'd0 && !start) busy <= 1'b0;
        end
    end
    assign m_axis_tvalid = (fn != 4'd0);
    assign m_axis_tdata  = fd[fh];
    assign m_axis_tlast  = fl[fh];
    assign m_axis_tuser  = fl[fh] && bad;
endmodule
