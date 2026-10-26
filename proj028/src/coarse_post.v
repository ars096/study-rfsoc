// SPDX-License-Identifier: BSD-3-Clause
// proj028 C-2 — 荒い段の後段: cfft32 の F → Y への詰め替え → ch ごとの利得 → 8 bit（丸め・飽和）→ ch ごとの電力と飽和の数え
//   Y_{2m} = F_m（m < 16）、Y_{2m+1} = conj(F_{31−m})（M-1d）
//   y = sat8((Y·g_k + 2^15) >>> 16)（成分ごと）。g_k は 18 bit の正の数（PS が書く、既定 0 = 出口 0）（M-3）
//   出口: 1 ブロックに 1 語 512 bit、ch k を [16k +: 16] = {y_im[7:0], y_re[7:0]}
//   電力: NACC ブロックごとに Σ(y_re² + y_im²) を ch ごとに 2 面で積み、閉じたら読み出し用に写す。飽和の数え（成分ごと）も同じ区切りで。
//         NACC を書くと積みかけを捨てて始め直す（0 なら数えない）
// レジスタ（AXI4-Lite、同じクロック。リセット中は ready を出さない）:
//   0x000 ID  0x004 NACC（ブロック、0 = 数えない）  0x008 SEQ（閉じた区切りの通し番号、読みだけ）
//   0x100 + 4k GAIN[k]（k = 0..31）  0x200 + 8k POW[k]（64 bit、下・上）  0x400 + 4k CLIP[k]
`default_nettype none
module coarse_post #(
    parameter [31:0] ID = 32'h0280_00C2,
    parameter integer FW = 24
) (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET aresetn" *)
    input  wire               clk,
    input  wire               aresetn,
    input  wire               s_valid,
    input  wire [32*2*FW-1:0] s_f,          // F_m（m = 0..31）、[2FW·m +: FW] = 実部、その上 = 虚部
    output reg                m_valid,
    output reg  [511:0]       m_y,
    input  wire [11:0]        s_axi_awaddr,
    input  wire               s_axi_awvalid,
    output wire               s_axi_awready,
    input  wire [31:0]        s_axi_wdata,
    input  wire               s_axi_wvalid,
    output wire               s_axi_wready,
    output reg                s_axi_bvalid,
    output wire [1:0]         s_axi_bresp,
    input  wire               s_axi_bready,
    input  wire [11:0]        s_axi_araddr,
    input  wire               s_axi_arvalid,
    output wire               s_axi_arready,
    output reg  [31:0]        s_axi_rdata,
    output reg                s_axi_rvalid,
    output wire [1:0]         s_axi_rresp,
    input  wire               s_axi_rready
);
    wire rst = ~aresetn;
    // ---- 制御 ----
    reg [17:0] gain [0:31];
    reg [31:0] nacc, nacc_m1;
    wire wr_go = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid && !rst;
    wire nacc_we = wr_go && (s_axi_awaddr == 12'h004);   // NACC を書くと数えを始め直す
    assign s_axi_awready = wr_go;
    assign s_axi_wready  = wr_go;
    assign s_axi_bresp   = 2'b00;
    integer i;
    always @(posedge clk) begin
        if (rst) begin
            s_axi_bvalid <= 1'b0; nacc <= 32'd0; nacc_m1 <= 32'hFFFF_FFFF;
            for (i = 0; i < 32; i = i + 1) gain[i] <= 18'd0;
        end else begin
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 1'b0;
            if (wr_go) begin
                s_axi_bvalid <= 1'b1;
                if (s_axi_awaddr == 12'h004) begin nacc <= s_axi_wdata; nacc_m1 <= s_axi_wdata - 32'd1; end
                if (s_axi_awaddr[11:7] == 5'b00010) gain[s_axi_awaddr[6:2]] <= s_axi_wdata[17:0];   // 0x100..0x17C
            end
        end
    end

    // ---- Y への詰め替え（配線と符号）→ 利得（2 段）→ 丸め・飽和（1 段）----
    genvar k;
    reg v1, v2, v3;
    wire [511:0] m_y_w;
    wire [31:0] pow_lo [0:31];
    wire [31:0] pow_hi [0:31];
    wire [31:0] clip_r [0:31];
    // 区切り: v3 のブロックを数え、NACC 個目で閉じる
    reg [31:0] bcnt, seq;
    reg v4, close4;
    // F-5b: nacc − 1 はレジスタで持ち、NACC と同じクロックで書く（全体のビルドで bcnt == nacc − 1 → seq が WNS −0.153 ns）
    wire close = (nacc != 32'd0) && (bcnt == nacc_m1);
    generate for (k = 0; k < 32; k = k + 1) begin : g_k
        localparam integer M2 = (k % 2 == 0) ? (k / 2) : (31 - (k - 1) / 2);
        wire signed [FW-1:0] fr = s_f[2*FW*M2 +: FW];
        wire signed [FW-1:0] fi = s_f[2*FW*M2 + FW +: FW];
        reg  signed [FW-1:0] yr, yi;
        always @(posedge clk) begin
            yr <= fr;
            yi <= (k % 2 == 0) ? fi : -fi;          // 奇数の ch は共役
        end
        (* use_dsp = "yes" *) reg signed [FW+18:0] pr, pi;
        always @(posedge clk) begin
            pr <= yr * $signed({1'b0, gain[k]});
            pi <= yi * $signed({1'b0, gain[k]});
        end
        wire signed [FW+18:0] rr = (pr + (1 <<< 15)) >>> 16;
        wire signed [FW+18:0] ri = (pi + (1 <<< 15)) >>> 16;
        reg signed [7:0] qr, qi;
        reg cr, ci;
        always @(posedge clk) begin
            qr <= (rr > 127) ? 8'sd127 : (rr < -127) ? -8'sd127 : rr[7:0];
            qi <= (ri > 127) ? 8'sd127 : (ri < -127) ? -8'sd127 : ri[7:0];
            cr <= (rr > 127) || (rr < -127);
            ci <= (ri > 127) || (ri < -127);
        end
        assign m_y_w[16*k +: 16] = {qi, qr};
        // 2 乗は符号付きで別に（符号なしと混ぜると式全体が符号なしになり、−127 の 2 乗を誤る）
        wire signed [15:0] sq_r = qr * qr;
        wire signed [15:0] sq_i = qi * qi;
        // F-5b: 2 乗の和を 1 段で受けてから積む（全体のビルドで qr → 2 乗 → 和 → 64 bit の積算が論理 16 段・WNS −0.426 ns だった）。
        //   区切り（close）と v も 1 段遅らせる（v4・close4）。NACC を書いたクロックの v3 は bcnt と同じく数えない（v4 を落とす）
        reg [16:0] pw;
        reg [1:0]  nclip;
        always @(posedge clk) begin
            pw    <= {1'b0, sq_r} + {1'b0, sq_i};
            nclip <= {1'b0, cr} + {1'b0, ci};
        end
        // 電力と飽和の数え（2 面）
        reg [63:0] pacc, pout;
        reg [31:0] cacc, cout;
        always @(posedge clk) begin
            if (rst || nacc_we) begin pacc <= 64'd0; cacc <= 32'd0; if (rst) begin pout <= 64'd0; cout <= 32'd0; end end
            else if (v4 && nacc != 32'd0) begin
                if (close4) begin
                    pout <= pacc + pw; cout <= cacc + nclip;
                    pacc <= 64'd0; cacc <= 32'd0;
                end else begin
                    pacc <= pacc + pw; cacc <= cacc + nclip;
                end
            end
        end
        assign pow_lo[k] = pout[31:0];
        assign pow_hi[k] = pout[63:32];
        assign clip_r[k] = cout;
    end endgenerate
    always @(posedge clk) begin
        v4 <= v3 && !rst && !nacc_we; close4 <= close;
    end
    always @(posedge clk) begin
        v1 <= s_valid && !rst; v2 <= v1 && !rst; v3 <= v2 && !rst;
        m_valid <= v3 && !rst;
        if (v3) m_y <= m_y_w;
    end
    always @(posedge clk) begin
        if (rst || nacc_we) bcnt <= 32'd0;
        else if (v3 && nacc != 32'd0) begin
            if (close) bcnt <= 32'd0;
            else bcnt <= bcnt + 32'd1;
        end
    end
    // SEQ は POW・CLIP の写し（v4・close4）と同じクロックで進める（PS が SEQ を見てから読む）
    always @(posedge clk) begin
        if (rst) seq <= 32'd0;
        else if (v4 && close4 && nacc != 32'd0) seq <= seq + 32'd1;
    end

    // ---- 読み出し ----
    assign s_axi_arready = !s_axi_rvalid && !rst;
    assign s_axi_rresp   = 2'b00;
    always @(posedge clk) begin
        if (rst) s_axi_rvalid <= 1'b0;
        else begin
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 1'b0;
            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1'b1;
                casez (s_axi_araddr)
                    12'h000: s_axi_rdata <= ID;
                    12'h004: s_axi_rdata <= nacc;
                    12'h008: s_axi_rdata <= seq;
                    12'b0001_0???_??00: s_axi_rdata <= {14'd0, gain[s_axi_araddr[6:2]]};
                    12'b0010_????_?000: s_axi_rdata <= pow_lo[s_axi_araddr[7:3]];
                    12'b0010_????_?100: s_axi_rdata <= pow_hi[s_axi_araddr[7:3]];
                    12'b0100_0???_??00: s_axi_rdata <= clip_r[s_axi_araddr[6:2]];
                    default: s_axi_rdata <= 32'hDEAD_BEEF;
                endcase
            end
        end
    end
endmodule
`default_nettype wire
