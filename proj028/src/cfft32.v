// SPDX-License-Identifier: BSD-3-Clause
// proj028 S-1 — 荒い FFT（tools/gen_cfft32.py が作る。手で直さない）
// 前掛け e^{jπn/64} → 32 点 DIF の全並列。遅れ 29 拍（前掛け 4 ＋ 5 段 × 5）
`default_nettype none
module cfft32_cmul #(parameter W = 18, parameter WO = 18, parameter signed [17:0] CR = 0, parameter signed [17:0] CI = 0) (
    input  wire clk,
    input  wire signed [W-1:0] xr, xi,
    output reg  signed [WO-1:0] yr, yi);
    // (xr + j xi)(CR + j CI)、4 乗算・4 拍。積は小数 17 bit を丸めて落とす
    (* use_dsp = "yes" *) reg signed [W+18:0] p_rr, p_ii, p_ri, p_ir;
    reg signed [W-1:0] ar, ai;
    reg signed [W+19:0] sr, si;
    always @(posedge clk) begin
        ar <= xr; ai <= xi;
        p_rr <= ar * CR; p_ii <= ai * CI; p_ri <= ar * CI; p_ir <= ai * CR;
        sr <= p_rr - p_ii + (1 <<< 16);
        si <= p_ri + p_ir + (1 <<< 16);
        yr <= sr >>> 17; yi <= si >>> 17;
    end
endmodule

module cfft32_dly #(parameter W = 18, parameter D = 4) (input wire clk, input wire [W-1:0] x, output wire [W-1:0] y);
    reg [W-1:0] r [0:D-1];
    integer i;
    always @(posedge clk) begin r[0] <= x; for (i = 1; i < D; i = i + 1) r[i] <= r[i-1]; end
    assign y = r[D-1];
endmodule

module cfft32 (
    input  wire clk,
    input  wire s_valid,
    input  wire [1151:0] s_z,            // z_r（r = 0..63）、各 18 bit
    output wire m_valid,
    output wire [1535:0] m_f           // F_m（m = 0..31、自然順）、各 実部 24 bit ＋ 虚部 24 bit（実部が下）
);
    // ---- 前掛け: w_n = (z_n + j z_{n+32})·e^{jπn/64}
    wire signed [18:0] w0r_0, w0i_0;
    cfft32_dly #(.W(19)) u_pd0_r (.clk(clk), .x({s_z[17], s_z[0*18 +: 18]}), .y(w0r_0));
    cfft32_dly #(.W(19)) u_pd0_i (.clk(clk), .x({s_z[593], s_z[32*18 +: 18]}), .y(w0i_0));
    wire signed [18:0] w0r_1, w0i_1;
    cfft32_cmul #(.W(18), .WO(19), .CR(130913), .CI(6431)) u_pm1 (.clk(clk), .xr(s_z[1*18 +: 18]), .xi(s_z[33*18 +: 18]), .yr(w0r_1), .yi(w0i_1));
    wire signed [18:0] w0r_2, w0i_2;
    cfft32_cmul #(.W(18), .WO(19), .CR(130440), .CI(12847)) u_pm2 (.clk(clk), .xr(s_z[2*18 +: 18]), .xi(s_z[34*18 +: 18]), .yr(w0r_2), .yi(w0i_2));
    wire signed [18:0] w0r_3, w0i_3;
    cfft32_cmul #(.W(18), .WO(19), .CR(129652), .CI(19232)) u_pm3 (.clk(clk), .xr(s_z[3*18 +: 18]), .xi(s_z[35*18 +: 18]), .yr(w0r_3), .yi(w0i_3));
    wire signed [18:0] w0r_4, w0i_4;
    cfft32_cmul #(.W(18), .WO(19), .CR(128553), .CI(25571)) u_pm4 (.clk(clk), .xr(s_z[4*18 +: 18]), .xi(s_z[36*18 +: 18]), .yr(w0r_4), .yi(w0i_4));
    wire signed [18:0] w0r_5, w0i_5;
    cfft32_cmul #(.W(18), .WO(19), .CR(127143), .CI(31848)) u_pm5 (.clk(clk), .xr(s_z[5*18 +: 18]), .xi(s_z[37*18 +: 18]), .yr(w0r_5), .yi(w0i_5));
    wire signed [18:0] w0r_6, w0i_6;
    cfft32_cmul #(.W(18), .WO(19), .CR(125427), .CI(38048)) u_pm6 (.clk(clk), .xr(s_z[6*18 +: 18]), .xi(s_z[38*18 +: 18]), .yr(w0r_6), .yi(w0i_6));
    wire signed [18:0] w0r_7, w0i_7;
    cfft32_cmul #(.W(18), .WO(19), .CR(123409), .CI(44156)) u_pm7 (.clk(clk), .xr(s_z[7*18 +: 18]), .xi(s_z[39*18 +: 18]), .yr(w0r_7), .yi(w0i_7));
    wire signed [18:0] w0r_8, w0i_8;
    cfft32_cmul #(.W(18), .WO(19), .CR(121094), .CI(50159)) u_pm8 (.clk(clk), .xr(s_z[8*18 +: 18]), .xi(s_z[40*18 +: 18]), .yr(w0r_8), .yi(w0i_8));
    wire signed [18:0] w0r_9, w0i_9;
    cfft32_cmul #(.W(18), .WO(19), .CR(118487), .CI(56040)) u_pm9 (.clk(clk), .xr(s_z[9*18 +: 18]), .xi(s_z[41*18 +: 18]), .yr(w0r_9), .yi(w0i_9));
    wire signed [18:0] w0r_10, w0i_10;
    cfft32_cmul #(.W(18), .WO(19), .CR(115594), .CI(61786)) u_pm10 (.clk(clk), .xr(s_z[10*18 +: 18]), .xi(s_z[42*18 +: 18]), .yr(w0r_10), .yi(w0i_10));
    wire signed [18:0] w0r_11, w0i_11;
    cfft32_cmul #(.W(18), .WO(19), .CR(112423), .CI(67384)) u_pm11 (.clk(clk), .xr(s_z[11*18 +: 18]), .xi(s_z[43*18 +: 18]), .yr(w0r_11), .yi(w0i_11));
    wire signed [18:0] w0r_12, w0i_12;
    cfft32_cmul #(.W(18), .WO(19), .CR(108982), .CI(72819)) u_pm12 (.clk(clk), .xr(s_z[12*18 +: 18]), .xi(s_z[44*18 +: 18]), .yr(w0r_12), .yi(w0i_12));
    wire signed [18:0] w0r_13, w0i_13;
    cfft32_cmul #(.W(18), .WO(19), .CR(105277), .CI(78079)) u_pm13 (.clk(clk), .xr(s_z[13*18 +: 18]), .xi(s_z[45*18 +: 18]), .yr(w0r_13), .yi(w0i_13));
    wire signed [18:0] w0r_14, w0i_14;
    cfft32_cmul #(.W(18), .WO(19), .CR(101319), .CI(83151)) u_pm14 (.clk(clk), .xr(s_z[14*18 +: 18]), .xi(s_z[46*18 +: 18]), .yr(w0r_14), .yi(w0i_14));
    wire signed [18:0] w0r_15, w0i_15;
    cfft32_cmul #(.W(18), .WO(19), .CR(97117), .CI(88022)) u_pm15 (.clk(clk), .xr(s_z[15*18 +: 18]), .xi(s_z[47*18 +: 18]), .yr(w0r_15), .yi(w0i_15));
    wire signed [18:0] w0r_16, w0i_16;
    cfft32_cmul #(.W(18), .WO(19), .CR(92681), .CI(92681)) u_pm16 (.clk(clk), .xr(s_z[16*18 +: 18]), .xi(s_z[48*18 +: 18]), .yr(w0r_16), .yi(w0i_16));
    wire signed [18:0] w0r_17, w0i_17;
    cfft32_cmul #(.W(18), .WO(19), .CR(88022), .CI(97117)) u_pm17 (.clk(clk), .xr(s_z[17*18 +: 18]), .xi(s_z[49*18 +: 18]), .yr(w0r_17), .yi(w0i_17));
    wire signed [18:0] w0r_18, w0i_18;
    cfft32_cmul #(.W(18), .WO(19), .CR(83151), .CI(101319)) u_pm18 (.clk(clk), .xr(s_z[18*18 +: 18]), .xi(s_z[50*18 +: 18]), .yr(w0r_18), .yi(w0i_18));
    wire signed [18:0] w0r_19, w0i_19;
    cfft32_cmul #(.W(18), .WO(19), .CR(78079), .CI(105277)) u_pm19 (.clk(clk), .xr(s_z[19*18 +: 18]), .xi(s_z[51*18 +: 18]), .yr(w0r_19), .yi(w0i_19));
    wire signed [18:0] w0r_20, w0i_20;
    cfft32_cmul #(.W(18), .WO(19), .CR(72819), .CI(108982)) u_pm20 (.clk(clk), .xr(s_z[20*18 +: 18]), .xi(s_z[52*18 +: 18]), .yr(w0r_20), .yi(w0i_20));
    wire signed [18:0] w0r_21, w0i_21;
    cfft32_cmul #(.W(18), .WO(19), .CR(67384), .CI(112423)) u_pm21 (.clk(clk), .xr(s_z[21*18 +: 18]), .xi(s_z[53*18 +: 18]), .yr(w0r_21), .yi(w0i_21));
    wire signed [18:0] w0r_22, w0i_22;
    cfft32_cmul #(.W(18), .WO(19), .CR(61786), .CI(115594)) u_pm22 (.clk(clk), .xr(s_z[22*18 +: 18]), .xi(s_z[54*18 +: 18]), .yr(w0r_22), .yi(w0i_22));
    wire signed [18:0] w0r_23, w0i_23;
    cfft32_cmul #(.W(18), .WO(19), .CR(56040), .CI(118487)) u_pm23 (.clk(clk), .xr(s_z[23*18 +: 18]), .xi(s_z[55*18 +: 18]), .yr(w0r_23), .yi(w0i_23));
    wire signed [18:0] w0r_24, w0i_24;
    cfft32_cmul #(.W(18), .WO(19), .CR(50159), .CI(121094)) u_pm24 (.clk(clk), .xr(s_z[24*18 +: 18]), .xi(s_z[56*18 +: 18]), .yr(w0r_24), .yi(w0i_24));
    wire signed [18:0] w0r_25, w0i_25;
    cfft32_cmul #(.W(18), .WO(19), .CR(44156), .CI(123409)) u_pm25 (.clk(clk), .xr(s_z[25*18 +: 18]), .xi(s_z[57*18 +: 18]), .yr(w0r_25), .yi(w0i_25));
    wire signed [18:0] w0r_26, w0i_26;
    cfft32_cmul #(.W(18), .WO(19), .CR(38048), .CI(125427)) u_pm26 (.clk(clk), .xr(s_z[26*18 +: 18]), .xi(s_z[58*18 +: 18]), .yr(w0r_26), .yi(w0i_26));
    wire signed [18:0] w0r_27, w0i_27;
    cfft32_cmul #(.W(18), .WO(19), .CR(31848), .CI(127143)) u_pm27 (.clk(clk), .xr(s_z[27*18 +: 18]), .xi(s_z[59*18 +: 18]), .yr(w0r_27), .yi(w0i_27));
    wire signed [18:0] w0r_28, w0i_28;
    cfft32_cmul #(.W(18), .WO(19), .CR(25571), .CI(128553)) u_pm28 (.clk(clk), .xr(s_z[28*18 +: 18]), .xi(s_z[60*18 +: 18]), .yr(w0r_28), .yi(w0i_28));
    wire signed [18:0] w0r_29, w0i_29;
    cfft32_cmul #(.W(18), .WO(19), .CR(19232), .CI(129652)) u_pm29 (.clk(clk), .xr(s_z[29*18 +: 18]), .xi(s_z[61*18 +: 18]), .yr(w0r_29), .yi(w0i_29));
    wire signed [18:0] w0r_30, w0i_30;
    cfft32_cmul #(.W(18), .WO(19), .CR(12847), .CI(130440)) u_pm30 (.clk(clk), .xr(s_z[30*18 +: 18]), .xi(s_z[62*18 +: 18]), .yr(w0r_30), .yi(w0i_30));
    wire signed [18:0] w0r_31, w0i_31;
    cfft32_cmul #(.W(18), .WO(19), .CR(6431), .CI(130913)) u_pm31 (.clk(clk), .xr(s_z[31*18 +: 18]), .xi(s_z[63*18 +: 18]), .yr(w0r_31), .yi(w0i_31));
    // ---- 段 0（span 16、出口 20 bit）
    reg signed [19:0] s0_0r, s0_0i, d0_16r, d0_16i;
    always @(posedge clk) begin s0_0r <= w0r_0 + w0r_16; s0_0i <= w0i_0 + w0i_16; d0_16r <= w0r_0 - w0r_16; d0_16i <= w0i_0 - w0i_16; end
    wire signed [19:0] o0_0r, o0_0i, o0_16r, o0_16i;
    cfft32_dly #(.W(20), .D(4)) u_s0_0_r (.clk(clk), .x(s0_0r), .y(o0_0r));
    cfft32_dly #(.W(20), .D(4)) u_s0_0_i (.clk(clk), .x(s0_0i), .y(o0_0i));
    cfft32_dly #(.W(20), .D(4)) u_d0_16_r (.clk(clk), .x(d0_16r), .y(o0_16r));
    cfft32_dly #(.W(20), .D(4)) u_d0_16_i (.clk(clk), .x(d0_16i), .y(o0_16i));
    reg signed [19:0] s0_1r, s0_1i, d0_17r, d0_17i;
    always @(posedge clk) begin s0_1r <= w0r_1 + w0r_17; s0_1i <= w0i_1 + w0i_17; d0_17r <= w0r_1 - w0r_17; d0_17i <= w0i_1 - w0i_17; end
    wire signed [19:0] o0_1r, o0_1i, o0_17r, o0_17i;
    cfft32_dly #(.W(20), .D(4)) u_s0_1_r (.clk(clk), .x(s0_1r), .y(o0_1r));
    cfft32_dly #(.W(20), .D(4)) u_s0_1_i (.clk(clk), .x(s0_1i), .y(o0_1i));
    cfft32_cmul #(.W(20), .WO(20), .CR(128553), .CI(25571)) u_cm0_17 (.clk(clk), .xr(d0_17r), .xi(d0_17i), .yr(o0_17r), .yi(o0_17i));
    reg signed [19:0] s0_2r, s0_2i, d0_18r, d0_18i;
    always @(posedge clk) begin s0_2r <= w0r_2 + w0r_18; s0_2i <= w0i_2 + w0i_18; d0_18r <= w0r_2 - w0r_18; d0_18i <= w0i_2 - w0i_18; end
    wire signed [19:0] o0_2r, o0_2i, o0_18r, o0_18i;
    cfft32_dly #(.W(20), .D(4)) u_s0_2_r (.clk(clk), .x(s0_2r), .y(o0_2r));
    cfft32_dly #(.W(20), .D(4)) u_s0_2_i (.clk(clk), .x(s0_2i), .y(o0_2i));
    cfft32_cmul #(.W(20), .WO(20), .CR(121094), .CI(50159)) u_cm0_18 (.clk(clk), .xr(d0_18r), .xi(d0_18i), .yr(o0_18r), .yi(o0_18i));
    reg signed [19:0] s0_3r, s0_3i, d0_19r, d0_19i;
    always @(posedge clk) begin s0_3r <= w0r_3 + w0r_19; s0_3i <= w0i_3 + w0i_19; d0_19r <= w0r_3 - w0r_19; d0_19i <= w0i_3 - w0i_19; end
    wire signed [19:0] o0_3r, o0_3i, o0_19r, o0_19i;
    cfft32_dly #(.W(20), .D(4)) u_s0_3_r (.clk(clk), .x(s0_3r), .y(o0_3r));
    cfft32_dly #(.W(20), .D(4)) u_s0_3_i (.clk(clk), .x(s0_3i), .y(o0_3i));
    cfft32_cmul #(.W(20), .WO(20), .CR(108982), .CI(72819)) u_cm0_19 (.clk(clk), .xr(d0_19r), .xi(d0_19i), .yr(o0_19r), .yi(o0_19i));
    reg signed [19:0] s0_4r, s0_4i, d0_20r, d0_20i;
    always @(posedge clk) begin s0_4r <= w0r_4 + w0r_20; s0_4i <= w0i_4 + w0i_20; d0_20r <= w0r_4 - w0r_20; d0_20i <= w0i_4 - w0i_20; end
    wire signed [19:0] o0_4r, o0_4i, o0_20r, o0_20i;
    cfft32_dly #(.W(20), .D(4)) u_s0_4_r (.clk(clk), .x(s0_4r), .y(o0_4r));
    cfft32_dly #(.W(20), .D(4)) u_s0_4_i (.clk(clk), .x(s0_4i), .y(o0_4i));
    cfft32_cmul #(.W(20), .WO(20), .CR(92681), .CI(92681)) u_cm0_20 (.clk(clk), .xr(d0_20r), .xi(d0_20i), .yr(o0_20r), .yi(o0_20i));
    reg signed [19:0] s0_5r, s0_5i, d0_21r, d0_21i;
    always @(posedge clk) begin s0_5r <= w0r_5 + w0r_21; s0_5i <= w0i_5 + w0i_21; d0_21r <= w0r_5 - w0r_21; d0_21i <= w0i_5 - w0i_21; end
    wire signed [19:0] o0_5r, o0_5i, o0_21r, o0_21i;
    cfft32_dly #(.W(20), .D(4)) u_s0_5_r (.clk(clk), .x(s0_5r), .y(o0_5r));
    cfft32_dly #(.W(20), .D(4)) u_s0_5_i (.clk(clk), .x(s0_5i), .y(o0_5i));
    cfft32_cmul #(.W(20), .WO(20), .CR(72819), .CI(108982)) u_cm0_21 (.clk(clk), .xr(d0_21r), .xi(d0_21i), .yr(o0_21r), .yi(o0_21i));
    reg signed [19:0] s0_6r, s0_6i, d0_22r, d0_22i;
    always @(posedge clk) begin s0_6r <= w0r_6 + w0r_22; s0_6i <= w0i_6 + w0i_22; d0_22r <= w0r_6 - w0r_22; d0_22i <= w0i_6 - w0i_22; end
    wire signed [19:0] o0_6r, o0_6i, o0_22r, o0_22i;
    cfft32_dly #(.W(20), .D(4)) u_s0_6_r (.clk(clk), .x(s0_6r), .y(o0_6r));
    cfft32_dly #(.W(20), .D(4)) u_s0_6_i (.clk(clk), .x(s0_6i), .y(o0_6i));
    cfft32_cmul #(.W(20), .WO(20), .CR(50159), .CI(121094)) u_cm0_22 (.clk(clk), .xr(d0_22r), .xi(d0_22i), .yr(o0_22r), .yi(o0_22i));
    reg signed [19:0] s0_7r, s0_7i, d0_23r, d0_23i;
    always @(posedge clk) begin s0_7r <= w0r_7 + w0r_23; s0_7i <= w0i_7 + w0i_23; d0_23r <= w0r_7 - w0r_23; d0_23i <= w0i_7 - w0i_23; end
    wire signed [19:0] o0_7r, o0_7i, o0_23r, o0_23i;
    cfft32_dly #(.W(20), .D(4)) u_s0_7_r (.clk(clk), .x(s0_7r), .y(o0_7r));
    cfft32_dly #(.W(20), .D(4)) u_s0_7_i (.clk(clk), .x(s0_7i), .y(o0_7i));
    cfft32_cmul #(.W(20), .WO(20), .CR(25571), .CI(128553)) u_cm0_23 (.clk(clk), .xr(d0_23r), .xi(d0_23i), .yr(o0_23r), .yi(o0_23i));
    reg signed [19:0] s0_8r, s0_8i, d0_24r, d0_24i;
    always @(posedge clk) begin s0_8r <= w0r_8 + w0r_24; s0_8i <= w0i_8 + w0i_24; d0_24r <= w0r_8 - w0r_24; d0_24i <= w0i_8 - w0i_24; end
    wire signed [19:0] o0_8r, o0_8i, o0_24r, o0_24i;
    cfft32_dly #(.W(20), .D(4)) u_s0_8_r (.clk(clk), .x(s0_8r), .y(o0_8r));
    cfft32_dly #(.W(20), .D(4)) u_s0_8_i (.clk(clk), .x(s0_8i), .y(o0_8i));
    wire signed [19:0] nj0_24 = -d0_24i;
    cfft32_dly #(.W(20), .D(4)) u_d0_24_r (.clk(clk), .x(nj0_24), .y(o0_24r));
    cfft32_dly #(.W(20), .D(4)) u_d0_24_i (.clk(clk), .x(d0_24r), .y(o0_24i));
    reg signed [19:0] s0_9r, s0_9i, d0_25r, d0_25i;
    always @(posedge clk) begin s0_9r <= w0r_9 + w0r_25; s0_9i <= w0i_9 + w0i_25; d0_25r <= w0r_9 - w0r_25; d0_25i <= w0i_9 - w0i_25; end
    wire signed [19:0] o0_9r, o0_9i, o0_25r, o0_25i;
    cfft32_dly #(.W(20), .D(4)) u_s0_9_r (.clk(clk), .x(s0_9r), .y(o0_9r));
    cfft32_dly #(.W(20), .D(4)) u_s0_9_i (.clk(clk), .x(s0_9i), .y(o0_9i));
    cfft32_cmul #(.W(20), .WO(20), .CR(-25571), .CI(128553)) u_cm0_25 (.clk(clk), .xr(d0_25r), .xi(d0_25i), .yr(o0_25r), .yi(o0_25i));
    reg signed [19:0] s0_10r, s0_10i, d0_26r, d0_26i;
    always @(posedge clk) begin s0_10r <= w0r_10 + w0r_26; s0_10i <= w0i_10 + w0i_26; d0_26r <= w0r_10 - w0r_26; d0_26i <= w0i_10 - w0i_26; end
    wire signed [19:0] o0_10r, o0_10i, o0_26r, o0_26i;
    cfft32_dly #(.W(20), .D(4)) u_s0_10_r (.clk(clk), .x(s0_10r), .y(o0_10r));
    cfft32_dly #(.W(20), .D(4)) u_s0_10_i (.clk(clk), .x(s0_10i), .y(o0_10i));
    cfft32_cmul #(.W(20), .WO(20), .CR(-50159), .CI(121094)) u_cm0_26 (.clk(clk), .xr(d0_26r), .xi(d0_26i), .yr(o0_26r), .yi(o0_26i));
    reg signed [19:0] s0_11r, s0_11i, d0_27r, d0_27i;
    always @(posedge clk) begin s0_11r <= w0r_11 + w0r_27; s0_11i <= w0i_11 + w0i_27; d0_27r <= w0r_11 - w0r_27; d0_27i <= w0i_11 - w0i_27; end
    wire signed [19:0] o0_11r, o0_11i, o0_27r, o0_27i;
    cfft32_dly #(.W(20), .D(4)) u_s0_11_r (.clk(clk), .x(s0_11r), .y(o0_11r));
    cfft32_dly #(.W(20), .D(4)) u_s0_11_i (.clk(clk), .x(s0_11i), .y(o0_11i));
    cfft32_cmul #(.W(20), .WO(20), .CR(-72819), .CI(108982)) u_cm0_27 (.clk(clk), .xr(d0_27r), .xi(d0_27i), .yr(o0_27r), .yi(o0_27i));
    reg signed [19:0] s0_12r, s0_12i, d0_28r, d0_28i;
    always @(posedge clk) begin s0_12r <= w0r_12 + w0r_28; s0_12i <= w0i_12 + w0i_28; d0_28r <= w0r_12 - w0r_28; d0_28i <= w0i_12 - w0i_28; end
    wire signed [19:0] o0_12r, o0_12i, o0_28r, o0_28i;
    cfft32_dly #(.W(20), .D(4)) u_s0_12_r (.clk(clk), .x(s0_12r), .y(o0_12r));
    cfft32_dly #(.W(20), .D(4)) u_s0_12_i (.clk(clk), .x(s0_12i), .y(o0_12i));
    cfft32_cmul #(.W(20), .WO(20), .CR(-92681), .CI(92681)) u_cm0_28 (.clk(clk), .xr(d0_28r), .xi(d0_28i), .yr(o0_28r), .yi(o0_28i));
    reg signed [19:0] s0_13r, s0_13i, d0_29r, d0_29i;
    always @(posedge clk) begin s0_13r <= w0r_13 + w0r_29; s0_13i <= w0i_13 + w0i_29; d0_29r <= w0r_13 - w0r_29; d0_29i <= w0i_13 - w0i_29; end
    wire signed [19:0] o0_13r, o0_13i, o0_29r, o0_29i;
    cfft32_dly #(.W(20), .D(4)) u_s0_13_r (.clk(clk), .x(s0_13r), .y(o0_13r));
    cfft32_dly #(.W(20), .D(4)) u_s0_13_i (.clk(clk), .x(s0_13i), .y(o0_13i));
    cfft32_cmul #(.W(20), .WO(20), .CR(-108982), .CI(72819)) u_cm0_29 (.clk(clk), .xr(d0_29r), .xi(d0_29i), .yr(o0_29r), .yi(o0_29i));
    reg signed [19:0] s0_14r, s0_14i, d0_30r, d0_30i;
    always @(posedge clk) begin s0_14r <= w0r_14 + w0r_30; s0_14i <= w0i_14 + w0i_30; d0_30r <= w0r_14 - w0r_30; d0_30i <= w0i_14 - w0i_30; end
    wire signed [19:0] o0_14r, o0_14i, o0_30r, o0_30i;
    cfft32_dly #(.W(20), .D(4)) u_s0_14_r (.clk(clk), .x(s0_14r), .y(o0_14r));
    cfft32_dly #(.W(20), .D(4)) u_s0_14_i (.clk(clk), .x(s0_14i), .y(o0_14i));
    cfft32_cmul #(.W(20), .WO(20), .CR(-121094), .CI(50159)) u_cm0_30 (.clk(clk), .xr(d0_30r), .xi(d0_30i), .yr(o0_30r), .yi(o0_30i));
    reg signed [19:0] s0_15r, s0_15i, d0_31r, d0_31i;
    always @(posedge clk) begin s0_15r <= w0r_15 + w0r_31; s0_15i <= w0i_15 + w0i_31; d0_31r <= w0r_15 - w0r_31; d0_31i <= w0i_15 - w0i_31; end
    wire signed [19:0] o0_15r, o0_15i, o0_31r, o0_31i;
    cfft32_dly #(.W(20), .D(4)) u_s0_15_r (.clk(clk), .x(s0_15r), .y(o0_15r));
    cfft32_dly #(.W(20), .D(4)) u_s0_15_i (.clk(clk), .x(s0_15i), .y(o0_15i));
    cfft32_cmul #(.W(20), .WO(20), .CR(-128553), .CI(25571)) u_cm0_31 (.clk(clk), .xr(d0_31r), .xi(d0_31i), .yr(o0_31r), .yi(o0_31i));
    // ---- 段 1（span 8、出口 21 bit）
    reg signed [20:0] s1_0r, s1_0i, d1_8r, d1_8i;
    always @(posedge clk) begin s1_0r <= o0_0r + o0_8r; s1_0i <= o0_0i + o0_8i; d1_8r <= o0_0r - o0_8r; d1_8i <= o0_0i - o0_8i; end
    wire signed [20:0] o1_0r, o1_0i, o1_8r, o1_8i;
    cfft32_dly #(.W(21), .D(4)) u_s1_0_r (.clk(clk), .x(s1_0r), .y(o1_0r));
    cfft32_dly #(.W(21), .D(4)) u_s1_0_i (.clk(clk), .x(s1_0i), .y(o1_0i));
    cfft32_dly #(.W(21), .D(4)) u_d1_8_r (.clk(clk), .x(d1_8r), .y(o1_8r));
    cfft32_dly #(.W(21), .D(4)) u_d1_8_i (.clk(clk), .x(d1_8i), .y(o1_8i));
    reg signed [20:0] s1_1r, s1_1i, d1_9r, d1_9i;
    always @(posedge clk) begin s1_1r <= o0_1r + o0_9r; s1_1i <= o0_1i + o0_9i; d1_9r <= o0_1r - o0_9r; d1_9i <= o0_1i - o0_9i; end
    wire signed [20:0] o1_1r, o1_1i, o1_9r, o1_9i;
    cfft32_dly #(.W(21), .D(4)) u_s1_1_r (.clk(clk), .x(s1_1r), .y(o1_1r));
    cfft32_dly #(.W(21), .D(4)) u_s1_1_i (.clk(clk), .x(s1_1i), .y(o1_1i));
    cfft32_cmul #(.W(21), .WO(21), .CR(121094), .CI(50159)) u_cm1_9 (.clk(clk), .xr(d1_9r), .xi(d1_9i), .yr(o1_9r), .yi(o1_9i));
    reg signed [20:0] s1_2r, s1_2i, d1_10r, d1_10i;
    always @(posedge clk) begin s1_2r <= o0_2r + o0_10r; s1_2i <= o0_2i + o0_10i; d1_10r <= o0_2r - o0_10r; d1_10i <= o0_2i - o0_10i; end
    wire signed [20:0] o1_2r, o1_2i, o1_10r, o1_10i;
    cfft32_dly #(.W(21), .D(4)) u_s1_2_r (.clk(clk), .x(s1_2r), .y(o1_2r));
    cfft32_dly #(.W(21), .D(4)) u_s1_2_i (.clk(clk), .x(s1_2i), .y(o1_2i));
    cfft32_cmul #(.W(21), .WO(21), .CR(92681), .CI(92681)) u_cm1_10 (.clk(clk), .xr(d1_10r), .xi(d1_10i), .yr(o1_10r), .yi(o1_10i));
    reg signed [20:0] s1_3r, s1_3i, d1_11r, d1_11i;
    always @(posedge clk) begin s1_3r <= o0_3r + o0_11r; s1_3i <= o0_3i + o0_11i; d1_11r <= o0_3r - o0_11r; d1_11i <= o0_3i - o0_11i; end
    wire signed [20:0] o1_3r, o1_3i, o1_11r, o1_11i;
    cfft32_dly #(.W(21), .D(4)) u_s1_3_r (.clk(clk), .x(s1_3r), .y(o1_3r));
    cfft32_dly #(.W(21), .D(4)) u_s1_3_i (.clk(clk), .x(s1_3i), .y(o1_3i));
    cfft32_cmul #(.W(21), .WO(21), .CR(50159), .CI(121094)) u_cm1_11 (.clk(clk), .xr(d1_11r), .xi(d1_11i), .yr(o1_11r), .yi(o1_11i));
    reg signed [20:0] s1_4r, s1_4i, d1_12r, d1_12i;
    always @(posedge clk) begin s1_4r <= o0_4r + o0_12r; s1_4i <= o0_4i + o0_12i; d1_12r <= o0_4r - o0_12r; d1_12i <= o0_4i - o0_12i; end
    wire signed [20:0] o1_4r, o1_4i, o1_12r, o1_12i;
    cfft32_dly #(.W(21), .D(4)) u_s1_4_r (.clk(clk), .x(s1_4r), .y(o1_4r));
    cfft32_dly #(.W(21), .D(4)) u_s1_4_i (.clk(clk), .x(s1_4i), .y(o1_4i));
    wire signed [20:0] nj1_12 = -d1_12i;
    cfft32_dly #(.W(21), .D(4)) u_d1_12_r (.clk(clk), .x(nj1_12), .y(o1_12r));
    cfft32_dly #(.W(21), .D(4)) u_d1_12_i (.clk(clk), .x(d1_12r), .y(o1_12i));
    reg signed [20:0] s1_5r, s1_5i, d1_13r, d1_13i;
    always @(posedge clk) begin s1_5r <= o0_5r + o0_13r; s1_5i <= o0_5i + o0_13i; d1_13r <= o0_5r - o0_13r; d1_13i <= o0_5i - o0_13i; end
    wire signed [20:0] o1_5r, o1_5i, o1_13r, o1_13i;
    cfft32_dly #(.W(21), .D(4)) u_s1_5_r (.clk(clk), .x(s1_5r), .y(o1_5r));
    cfft32_dly #(.W(21), .D(4)) u_s1_5_i (.clk(clk), .x(s1_5i), .y(o1_5i));
    cfft32_cmul #(.W(21), .WO(21), .CR(-50159), .CI(121094)) u_cm1_13 (.clk(clk), .xr(d1_13r), .xi(d1_13i), .yr(o1_13r), .yi(o1_13i));
    reg signed [20:0] s1_6r, s1_6i, d1_14r, d1_14i;
    always @(posedge clk) begin s1_6r <= o0_6r + o0_14r; s1_6i <= o0_6i + o0_14i; d1_14r <= o0_6r - o0_14r; d1_14i <= o0_6i - o0_14i; end
    wire signed [20:0] o1_6r, o1_6i, o1_14r, o1_14i;
    cfft32_dly #(.W(21), .D(4)) u_s1_6_r (.clk(clk), .x(s1_6r), .y(o1_6r));
    cfft32_dly #(.W(21), .D(4)) u_s1_6_i (.clk(clk), .x(s1_6i), .y(o1_6i));
    cfft32_cmul #(.W(21), .WO(21), .CR(-92681), .CI(92681)) u_cm1_14 (.clk(clk), .xr(d1_14r), .xi(d1_14i), .yr(o1_14r), .yi(o1_14i));
    reg signed [20:0] s1_7r, s1_7i, d1_15r, d1_15i;
    always @(posedge clk) begin s1_7r <= o0_7r + o0_15r; s1_7i <= o0_7i + o0_15i; d1_15r <= o0_7r - o0_15r; d1_15i <= o0_7i - o0_15i; end
    wire signed [20:0] o1_7r, o1_7i, o1_15r, o1_15i;
    cfft32_dly #(.W(21), .D(4)) u_s1_7_r (.clk(clk), .x(s1_7r), .y(o1_7r));
    cfft32_dly #(.W(21), .D(4)) u_s1_7_i (.clk(clk), .x(s1_7i), .y(o1_7i));
    cfft32_cmul #(.W(21), .WO(21), .CR(-121094), .CI(50159)) u_cm1_15 (.clk(clk), .xr(d1_15r), .xi(d1_15i), .yr(o1_15r), .yi(o1_15i));
    reg signed [20:0] s1_16r, s1_16i, d1_24r, d1_24i;
    always @(posedge clk) begin s1_16r <= o0_16r + o0_24r; s1_16i <= o0_16i + o0_24i; d1_24r <= o0_16r - o0_24r; d1_24i <= o0_16i - o0_24i; end
    wire signed [20:0] o1_16r, o1_16i, o1_24r, o1_24i;
    cfft32_dly #(.W(21), .D(4)) u_s1_16_r (.clk(clk), .x(s1_16r), .y(o1_16r));
    cfft32_dly #(.W(21), .D(4)) u_s1_16_i (.clk(clk), .x(s1_16i), .y(o1_16i));
    cfft32_dly #(.W(21), .D(4)) u_d1_24_r (.clk(clk), .x(d1_24r), .y(o1_24r));
    cfft32_dly #(.W(21), .D(4)) u_d1_24_i (.clk(clk), .x(d1_24i), .y(o1_24i));
    reg signed [20:0] s1_17r, s1_17i, d1_25r, d1_25i;
    always @(posedge clk) begin s1_17r <= o0_17r + o0_25r; s1_17i <= o0_17i + o0_25i; d1_25r <= o0_17r - o0_25r; d1_25i <= o0_17i - o0_25i; end
    wire signed [20:0] o1_17r, o1_17i, o1_25r, o1_25i;
    cfft32_dly #(.W(21), .D(4)) u_s1_17_r (.clk(clk), .x(s1_17r), .y(o1_17r));
    cfft32_dly #(.W(21), .D(4)) u_s1_17_i (.clk(clk), .x(s1_17i), .y(o1_17i));
    cfft32_cmul #(.W(21), .WO(21), .CR(121094), .CI(50159)) u_cm1_25 (.clk(clk), .xr(d1_25r), .xi(d1_25i), .yr(o1_25r), .yi(o1_25i));
    reg signed [20:0] s1_18r, s1_18i, d1_26r, d1_26i;
    always @(posedge clk) begin s1_18r <= o0_18r + o0_26r; s1_18i <= o0_18i + o0_26i; d1_26r <= o0_18r - o0_26r; d1_26i <= o0_18i - o0_26i; end
    wire signed [20:0] o1_18r, o1_18i, o1_26r, o1_26i;
    cfft32_dly #(.W(21), .D(4)) u_s1_18_r (.clk(clk), .x(s1_18r), .y(o1_18r));
    cfft32_dly #(.W(21), .D(4)) u_s1_18_i (.clk(clk), .x(s1_18i), .y(o1_18i));
    cfft32_cmul #(.W(21), .WO(21), .CR(92681), .CI(92681)) u_cm1_26 (.clk(clk), .xr(d1_26r), .xi(d1_26i), .yr(o1_26r), .yi(o1_26i));
    reg signed [20:0] s1_19r, s1_19i, d1_27r, d1_27i;
    always @(posedge clk) begin s1_19r <= o0_19r + o0_27r; s1_19i <= o0_19i + o0_27i; d1_27r <= o0_19r - o0_27r; d1_27i <= o0_19i - o0_27i; end
    wire signed [20:0] o1_19r, o1_19i, o1_27r, o1_27i;
    cfft32_dly #(.W(21), .D(4)) u_s1_19_r (.clk(clk), .x(s1_19r), .y(o1_19r));
    cfft32_dly #(.W(21), .D(4)) u_s1_19_i (.clk(clk), .x(s1_19i), .y(o1_19i));
    cfft32_cmul #(.W(21), .WO(21), .CR(50159), .CI(121094)) u_cm1_27 (.clk(clk), .xr(d1_27r), .xi(d1_27i), .yr(o1_27r), .yi(o1_27i));
    reg signed [20:0] s1_20r, s1_20i, d1_28r, d1_28i;
    always @(posedge clk) begin s1_20r <= o0_20r + o0_28r; s1_20i <= o0_20i + o0_28i; d1_28r <= o0_20r - o0_28r; d1_28i <= o0_20i - o0_28i; end
    wire signed [20:0] o1_20r, o1_20i, o1_28r, o1_28i;
    cfft32_dly #(.W(21), .D(4)) u_s1_20_r (.clk(clk), .x(s1_20r), .y(o1_20r));
    cfft32_dly #(.W(21), .D(4)) u_s1_20_i (.clk(clk), .x(s1_20i), .y(o1_20i));
    wire signed [20:0] nj1_28 = -d1_28i;
    cfft32_dly #(.W(21), .D(4)) u_d1_28_r (.clk(clk), .x(nj1_28), .y(o1_28r));
    cfft32_dly #(.W(21), .D(4)) u_d1_28_i (.clk(clk), .x(d1_28r), .y(o1_28i));
    reg signed [20:0] s1_21r, s1_21i, d1_29r, d1_29i;
    always @(posedge clk) begin s1_21r <= o0_21r + o0_29r; s1_21i <= o0_21i + o0_29i; d1_29r <= o0_21r - o0_29r; d1_29i <= o0_21i - o0_29i; end
    wire signed [20:0] o1_21r, o1_21i, o1_29r, o1_29i;
    cfft32_dly #(.W(21), .D(4)) u_s1_21_r (.clk(clk), .x(s1_21r), .y(o1_21r));
    cfft32_dly #(.W(21), .D(4)) u_s1_21_i (.clk(clk), .x(s1_21i), .y(o1_21i));
    cfft32_cmul #(.W(21), .WO(21), .CR(-50159), .CI(121094)) u_cm1_29 (.clk(clk), .xr(d1_29r), .xi(d1_29i), .yr(o1_29r), .yi(o1_29i));
    reg signed [20:0] s1_22r, s1_22i, d1_30r, d1_30i;
    always @(posedge clk) begin s1_22r <= o0_22r + o0_30r; s1_22i <= o0_22i + o0_30i; d1_30r <= o0_22r - o0_30r; d1_30i <= o0_22i - o0_30i; end
    wire signed [20:0] o1_22r, o1_22i, o1_30r, o1_30i;
    cfft32_dly #(.W(21), .D(4)) u_s1_22_r (.clk(clk), .x(s1_22r), .y(o1_22r));
    cfft32_dly #(.W(21), .D(4)) u_s1_22_i (.clk(clk), .x(s1_22i), .y(o1_22i));
    cfft32_cmul #(.W(21), .WO(21), .CR(-92681), .CI(92681)) u_cm1_30 (.clk(clk), .xr(d1_30r), .xi(d1_30i), .yr(o1_30r), .yi(o1_30i));
    reg signed [20:0] s1_23r, s1_23i, d1_31r, d1_31i;
    always @(posedge clk) begin s1_23r <= o0_23r + o0_31r; s1_23i <= o0_23i + o0_31i; d1_31r <= o0_23r - o0_31r; d1_31i <= o0_23i - o0_31i; end
    wire signed [20:0] o1_23r, o1_23i, o1_31r, o1_31i;
    cfft32_dly #(.W(21), .D(4)) u_s1_23_r (.clk(clk), .x(s1_23r), .y(o1_23r));
    cfft32_dly #(.W(21), .D(4)) u_s1_23_i (.clk(clk), .x(s1_23i), .y(o1_23i));
    cfft32_cmul #(.W(21), .WO(21), .CR(-121094), .CI(50159)) u_cm1_31 (.clk(clk), .xr(d1_31r), .xi(d1_31i), .yr(o1_31r), .yi(o1_31i));
    // ---- 段 2（span 4、出口 22 bit）
    reg signed [21:0] s2_0r, s2_0i, d2_4r, d2_4i;
    always @(posedge clk) begin s2_0r <= o1_0r + o1_4r; s2_0i <= o1_0i + o1_4i; d2_4r <= o1_0r - o1_4r; d2_4i <= o1_0i - o1_4i; end
    wire signed [21:0] o2_0r, o2_0i, o2_4r, o2_4i;
    cfft32_dly #(.W(22), .D(4)) u_s2_0_r (.clk(clk), .x(s2_0r), .y(o2_0r));
    cfft32_dly #(.W(22), .D(4)) u_s2_0_i (.clk(clk), .x(s2_0i), .y(o2_0i));
    cfft32_dly #(.W(22), .D(4)) u_d2_4_r (.clk(clk), .x(d2_4r), .y(o2_4r));
    cfft32_dly #(.W(22), .D(4)) u_d2_4_i (.clk(clk), .x(d2_4i), .y(o2_4i));
    reg signed [21:0] s2_1r, s2_1i, d2_5r, d2_5i;
    always @(posedge clk) begin s2_1r <= o1_1r + o1_5r; s2_1i <= o1_1i + o1_5i; d2_5r <= o1_1r - o1_5r; d2_5i <= o1_1i - o1_5i; end
    wire signed [21:0] o2_1r, o2_1i, o2_5r, o2_5i;
    cfft32_dly #(.W(22), .D(4)) u_s2_1_r (.clk(clk), .x(s2_1r), .y(o2_1r));
    cfft32_dly #(.W(22), .D(4)) u_s2_1_i (.clk(clk), .x(s2_1i), .y(o2_1i));
    cfft32_cmul #(.W(22), .WO(22), .CR(92681), .CI(92681)) u_cm2_5 (.clk(clk), .xr(d2_5r), .xi(d2_5i), .yr(o2_5r), .yi(o2_5i));
    reg signed [21:0] s2_2r, s2_2i, d2_6r, d2_6i;
    always @(posedge clk) begin s2_2r <= o1_2r + o1_6r; s2_2i <= o1_2i + o1_6i; d2_6r <= o1_2r - o1_6r; d2_6i <= o1_2i - o1_6i; end
    wire signed [21:0] o2_2r, o2_2i, o2_6r, o2_6i;
    cfft32_dly #(.W(22), .D(4)) u_s2_2_r (.clk(clk), .x(s2_2r), .y(o2_2r));
    cfft32_dly #(.W(22), .D(4)) u_s2_2_i (.clk(clk), .x(s2_2i), .y(o2_2i));
    wire signed [21:0] nj2_6 = -d2_6i;
    cfft32_dly #(.W(22), .D(4)) u_d2_6_r (.clk(clk), .x(nj2_6), .y(o2_6r));
    cfft32_dly #(.W(22), .D(4)) u_d2_6_i (.clk(clk), .x(d2_6r), .y(o2_6i));
    reg signed [21:0] s2_3r, s2_3i, d2_7r, d2_7i;
    always @(posedge clk) begin s2_3r <= o1_3r + o1_7r; s2_3i <= o1_3i + o1_7i; d2_7r <= o1_3r - o1_7r; d2_7i <= o1_3i - o1_7i; end
    wire signed [21:0] o2_3r, o2_3i, o2_7r, o2_7i;
    cfft32_dly #(.W(22), .D(4)) u_s2_3_r (.clk(clk), .x(s2_3r), .y(o2_3r));
    cfft32_dly #(.W(22), .D(4)) u_s2_3_i (.clk(clk), .x(s2_3i), .y(o2_3i));
    cfft32_cmul #(.W(22), .WO(22), .CR(-92681), .CI(92681)) u_cm2_7 (.clk(clk), .xr(d2_7r), .xi(d2_7i), .yr(o2_7r), .yi(o2_7i));
    reg signed [21:0] s2_8r, s2_8i, d2_12r, d2_12i;
    always @(posedge clk) begin s2_8r <= o1_8r + o1_12r; s2_8i <= o1_8i + o1_12i; d2_12r <= o1_8r - o1_12r; d2_12i <= o1_8i - o1_12i; end
    wire signed [21:0] o2_8r, o2_8i, o2_12r, o2_12i;
    cfft32_dly #(.W(22), .D(4)) u_s2_8_r (.clk(clk), .x(s2_8r), .y(o2_8r));
    cfft32_dly #(.W(22), .D(4)) u_s2_8_i (.clk(clk), .x(s2_8i), .y(o2_8i));
    cfft32_dly #(.W(22), .D(4)) u_d2_12_r (.clk(clk), .x(d2_12r), .y(o2_12r));
    cfft32_dly #(.W(22), .D(4)) u_d2_12_i (.clk(clk), .x(d2_12i), .y(o2_12i));
    reg signed [21:0] s2_9r, s2_9i, d2_13r, d2_13i;
    always @(posedge clk) begin s2_9r <= o1_9r + o1_13r; s2_9i <= o1_9i + o1_13i; d2_13r <= o1_9r - o1_13r; d2_13i <= o1_9i - o1_13i; end
    wire signed [21:0] o2_9r, o2_9i, o2_13r, o2_13i;
    cfft32_dly #(.W(22), .D(4)) u_s2_9_r (.clk(clk), .x(s2_9r), .y(o2_9r));
    cfft32_dly #(.W(22), .D(4)) u_s2_9_i (.clk(clk), .x(s2_9i), .y(o2_9i));
    cfft32_cmul #(.W(22), .WO(22), .CR(92681), .CI(92681)) u_cm2_13 (.clk(clk), .xr(d2_13r), .xi(d2_13i), .yr(o2_13r), .yi(o2_13i));
    reg signed [21:0] s2_10r, s2_10i, d2_14r, d2_14i;
    always @(posedge clk) begin s2_10r <= o1_10r + o1_14r; s2_10i <= o1_10i + o1_14i; d2_14r <= o1_10r - o1_14r; d2_14i <= o1_10i - o1_14i; end
    wire signed [21:0] o2_10r, o2_10i, o2_14r, o2_14i;
    cfft32_dly #(.W(22), .D(4)) u_s2_10_r (.clk(clk), .x(s2_10r), .y(o2_10r));
    cfft32_dly #(.W(22), .D(4)) u_s2_10_i (.clk(clk), .x(s2_10i), .y(o2_10i));
    wire signed [21:0] nj2_14 = -d2_14i;
    cfft32_dly #(.W(22), .D(4)) u_d2_14_r (.clk(clk), .x(nj2_14), .y(o2_14r));
    cfft32_dly #(.W(22), .D(4)) u_d2_14_i (.clk(clk), .x(d2_14r), .y(o2_14i));
    reg signed [21:0] s2_11r, s2_11i, d2_15r, d2_15i;
    always @(posedge clk) begin s2_11r <= o1_11r + o1_15r; s2_11i <= o1_11i + o1_15i; d2_15r <= o1_11r - o1_15r; d2_15i <= o1_11i - o1_15i; end
    wire signed [21:0] o2_11r, o2_11i, o2_15r, o2_15i;
    cfft32_dly #(.W(22), .D(4)) u_s2_11_r (.clk(clk), .x(s2_11r), .y(o2_11r));
    cfft32_dly #(.W(22), .D(4)) u_s2_11_i (.clk(clk), .x(s2_11i), .y(o2_11i));
    cfft32_cmul #(.W(22), .WO(22), .CR(-92681), .CI(92681)) u_cm2_15 (.clk(clk), .xr(d2_15r), .xi(d2_15i), .yr(o2_15r), .yi(o2_15i));
    reg signed [21:0] s2_16r, s2_16i, d2_20r, d2_20i;
    always @(posedge clk) begin s2_16r <= o1_16r + o1_20r; s2_16i <= o1_16i + o1_20i; d2_20r <= o1_16r - o1_20r; d2_20i <= o1_16i - o1_20i; end
    wire signed [21:0] o2_16r, o2_16i, o2_20r, o2_20i;
    cfft32_dly #(.W(22), .D(4)) u_s2_16_r (.clk(clk), .x(s2_16r), .y(o2_16r));
    cfft32_dly #(.W(22), .D(4)) u_s2_16_i (.clk(clk), .x(s2_16i), .y(o2_16i));
    cfft32_dly #(.W(22), .D(4)) u_d2_20_r (.clk(clk), .x(d2_20r), .y(o2_20r));
    cfft32_dly #(.W(22), .D(4)) u_d2_20_i (.clk(clk), .x(d2_20i), .y(o2_20i));
    reg signed [21:0] s2_17r, s2_17i, d2_21r, d2_21i;
    always @(posedge clk) begin s2_17r <= o1_17r + o1_21r; s2_17i <= o1_17i + o1_21i; d2_21r <= o1_17r - o1_21r; d2_21i <= o1_17i - o1_21i; end
    wire signed [21:0] o2_17r, o2_17i, o2_21r, o2_21i;
    cfft32_dly #(.W(22), .D(4)) u_s2_17_r (.clk(clk), .x(s2_17r), .y(o2_17r));
    cfft32_dly #(.W(22), .D(4)) u_s2_17_i (.clk(clk), .x(s2_17i), .y(o2_17i));
    cfft32_cmul #(.W(22), .WO(22), .CR(92681), .CI(92681)) u_cm2_21 (.clk(clk), .xr(d2_21r), .xi(d2_21i), .yr(o2_21r), .yi(o2_21i));
    reg signed [21:0] s2_18r, s2_18i, d2_22r, d2_22i;
    always @(posedge clk) begin s2_18r <= o1_18r + o1_22r; s2_18i <= o1_18i + o1_22i; d2_22r <= o1_18r - o1_22r; d2_22i <= o1_18i - o1_22i; end
    wire signed [21:0] o2_18r, o2_18i, o2_22r, o2_22i;
    cfft32_dly #(.W(22), .D(4)) u_s2_18_r (.clk(clk), .x(s2_18r), .y(o2_18r));
    cfft32_dly #(.W(22), .D(4)) u_s2_18_i (.clk(clk), .x(s2_18i), .y(o2_18i));
    wire signed [21:0] nj2_22 = -d2_22i;
    cfft32_dly #(.W(22), .D(4)) u_d2_22_r (.clk(clk), .x(nj2_22), .y(o2_22r));
    cfft32_dly #(.W(22), .D(4)) u_d2_22_i (.clk(clk), .x(d2_22r), .y(o2_22i));
    reg signed [21:0] s2_19r, s2_19i, d2_23r, d2_23i;
    always @(posedge clk) begin s2_19r <= o1_19r + o1_23r; s2_19i <= o1_19i + o1_23i; d2_23r <= o1_19r - o1_23r; d2_23i <= o1_19i - o1_23i; end
    wire signed [21:0] o2_19r, o2_19i, o2_23r, o2_23i;
    cfft32_dly #(.W(22), .D(4)) u_s2_19_r (.clk(clk), .x(s2_19r), .y(o2_19r));
    cfft32_dly #(.W(22), .D(4)) u_s2_19_i (.clk(clk), .x(s2_19i), .y(o2_19i));
    cfft32_cmul #(.W(22), .WO(22), .CR(-92681), .CI(92681)) u_cm2_23 (.clk(clk), .xr(d2_23r), .xi(d2_23i), .yr(o2_23r), .yi(o2_23i));
    reg signed [21:0] s2_24r, s2_24i, d2_28r, d2_28i;
    always @(posedge clk) begin s2_24r <= o1_24r + o1_28r; s2_24i <= o1_24i + o1_28i; d2_28r <= o1_24r - o1_28r; d2_28i <= o1_24i - o1_28i; end
    wire signed [21:0] o2_24r, o2_24i, o2_28r, o2_28i;
    cfft32_dly #(.W(22), .D(4)) u_s2_24_r (.clk(clk), .x(s2_24r), .y(o2_24r));
    cfft32_dly #(.W(22), .D(4)) u_s2_24_i (.clk(clk), .x(s2_24i), .y(o2_24i));
    cfft32_dly #(.W(22), .D(4)) u_d2_28_r (.clk(clk), .x(d2_28r), .y(o2_28r));
    cfft32_dly #(.W(22), .D(4)) u_d2_28_i (.clk(clk), .x(d2_28i), .y(o2_28i));
    reg signed [21:0] s2_25r, s2_25i, d2_29r, d2_29i;
    always @(posedge clk) begin s2_25r <= o1_25r + o1_29r; s2_25i <= o1_25i + o1_29i; d2_29r <= o1_25r - o1_29r; d2_29i <= o1_25i - o1_29i; end
    wire signed [21:0] o2_25r, o2_25i, o2_29r, o2_29i;
    cfft32_dly #(.W(22), .D(4)) u_s2_25_r (.clk(clk), .x(s2_25r), .y(o2_25r));
    cfft32_dly #(.W(22), .D(4)) u_s2_25_i (.clk(clk), .x(s2_25i), .y(o2_25i));
    cfft32_cmul #(.W(22), .WO(22), .CR(92681), .CI(92681)) u_cm2_29 (.clk(clk), .xr(d2_29r), .xi(d2_29i), .yr(o2_29r), .yi(o2_29i));
    reg signed [21:0] s2_26r, s2_26i, d2_30r, d2_30i;
    always @(posedge clk) begin s2_26r <= o1_26r + o1_30r; s2_26i <= o1_26i + o1_30i; d2_30r <= o1_26r - o1_30r; d2_30i <= o1_26i - o1_30i; end
    wire signed [21:0] o2_26r, o2_26i, o2_30r, o2_30i;
    cfft32_dly #(.W(22), .D(4)) u_s2_26_r (.clk(clk), .x(s2_26r), .y(o2_26r));
    cfft32_dly #(.W(22), .D(4)) u_s2_26_i (.clk(clk), .x(s2_26i), .y(o2_26i));
    wire signed [21:0] nj2_30 = -d2_30i;
    cfft32_dly #(.W(22), .D(4)) u_d2_30_r (.clk(clk), .x(nj2_30), .y(o2_30r));
    cfft32_dly #(.W(22), .D(4)) u_d2_30_i (.clk(clk), .x(d2_30r), .y(o2_30i));
    reg signed [21:0] s2_27r, s2_27i, d2_31r, d2_31i;
    always @(posedge clk) begin s2_27r <= o1_27r + o1_31r; s2_27i <= o1_27i + o1_31i; d2_31r <= o1_27r - o1_31r; d2_31i <= o1_27i - o1_31i; end
    wire signed [21:0] o2_27r, o2_27i, o2_31r, o2_31i;
    cfft32_dly #(.W(22), .D(4)) u_s2_27_r (.clk(clk), .x(s2_27r), .y(o2_27r));
    cfft32_dly #(.W(22), .D(4)) u_s2_27_i (.clk(clk), .x(s2_27i), .y(o2_27i));
    cfft32_cmul #(.W(22), .WO(22), .CR(-92681), .CI(92681)) u_cm2_31 (.clk(clk), .xr(d2_31r), .xi(d2_31i), .yr(o2_31r), .yi(o2_31i));
    // ---- 段 3（span 2、出口 23 bit）
    reg signed [22:0] s3_0r, s3_0i, d3_2r, d3_2i;
    always @(posedge clk) begin s3_0r <= o2_0r + o2_2r; s3_0i <= o2_0i + o2_2i; d3_2r <= o2_0r - o2_2r; d3_2i <= o2_0i - o2_2i; end
    wire signed [22:0] o3_0r, o3_0i, o3_2r, o3_2i;
    cfft32_dly #(.W(23), .D(4)) u_s3_0_r (.clk(clk), .x(s3_0r), .y(o3_0r));
    cfft32_dly #(.W(23), .D(4)) u_s3_0_i (.clk(clk), .x(s3_0i), .y(o3_0i));
    cfft32_dly #(.W(23), .D(4)) u_d3_2_r (.clk(clk), .x(d3_2r), .y(o3_2r));
    cfft32_dly #(.W(23), .D(4)) u_d3_2_i (.clk(clk), .x(d3_2i), .y(o3_2i));
    reg signed [22:0] s3_1r, s3_1i, d3_3r, d3_3i;
    always @(posedge clk) begin s3_1r <= o2_1r + o2_3r; s3_1i <= o2_1i + o2_3i; d3_3r <= o2_1r - o2_3r; d3_3i <= o2_1i - o2_3i; end
    wire signed [22:0] o3_1r, o3_1i, o3_3r, o3_3i;
    cfft32_dly #(.W(23), .D(4)) u_s3_1_r (.clk(clk), .x(s3_1r), .y(o3_1r));
    cfft32_dly #(.W(23), .D(4)) u_s3_1_i (.clk(clk), .x(s3_1i), .y(o3_1i));
    wire signed [22:0] nj3_3 = -d3_3i;
    cfft32_dly #(.W(23), .D(4)) u_d3_3_r (.clk(clk), .x(nj3_3), .y(o3_3r));
    cfft32_dly #(.W(23), .D(4)) u_d3_3_i (.clk(clk), .x(d3_3r), .y(o3_3i));
    reg signed [22:0] s3_4r, s3_4i, d3_6r, d3_6i;
    always @(posedge clk) begin s3_4r <= o2_4r + o2_6r; s3_4i <= o2_4i + o2_6i; d3_6r <= o2_4r - o2_6r; d3_6i <= o2_4i - o2_6i; end
    wire signed [22:0] o3_4r, o3_4i, o3_6r, o3_6i;
    cfft32_dly #(.W(23), .D(4)) u_s3_4_r (.clk(clk), .x(s3_4r), .y(o3_4r));
    cfft32_dly #(.W(23), .D(4)) u_s3_4_i (.clk(clk), .x(s3_4i), .y(o3_4i));
    cfft32_dly #(.W(23), .D(4)) u_d3_6_r (.clk(clk), .x(d3_6r), .y(o3_6r));
    cfft32_dly #(.W(23), .D(4)) u_d3_6_i (.clk(clk), .x(d3_6i), .y(o3_6i));
    reg signed [22:0] s3_5r, s3_5i, d3_7r, d3_7i;
    always @(posedge clk) begin s3_5r <= o2_5r + o2_7r; s3_5i <= o2_5i + o2_7i; d3_7r <= o2_5r - o2_7r; d3_7i <= o2_5i - o2_7i; end
    wire signed [22:0] o3_5r, o3_5i, o3_7r, o3_7i;
    cfft32_dly #(.W(23), .D(4)) u_s3_5_r (.clk(clk), .x(s3_5r), .y(o3_5r));
    cfft32_dly #(.W(23), .D(4)) u_s3_5_i (.clk(clk), .x(s3_5i), .y(o3_5i));
    wire signed [22:0] nj3_7 = -d3_7i;
    cfft32_dly #(.W(23), .D(4)) u_d3_7_r (.clk(clk), .x(nj3_7), .y(o3_7r));
    cfft32_dly #(.W(23), .D(4)) u_d3_7_i (.clk(clk), .x(d3_7r), .y(o3_7i));
    reg signed [22:0] s3_8r, s3_8i, d3_10r, d3_10i;
    always @(posedge clk) begin s3_8r <= o2_8r + o2_10r; s3_8i <= o2_8i + o2_10i; d3_10r <= o2_8r - o2_10r; d3_10i <= o2_8i - o2_10i; end
    wire signed [22:0] o3_8r, o3_8i, o3_10r, o3_10i;
    cfft32_dly #(.W(23), .D(4)) u_s3_8_r (.clk(clk), .x(s3_8r), .y(o3_8r));
    cfft32_dly #(.W(23), .D(4)) u_s3_8_i (.clk(clk), .x(s3_8i), .y(o3_8i));
    cfft32_dly #(.W(23), .D(4)) u_d3_10_r (.clk(clk), .x(d3_10r), .y(o3_10r));
    cfft32_dly #(.W(23), .D(4)) u_d3_10_i (.clk(clk), .x(d3_10i), .y(o3_10i));
    reg signed [22:0] s3_9r, s3_9i, d3_11r, d3_11i;
    always @(posedge clk) begin s3_9r <= o2_9r + o2_11r; s3_9i <= o2_9i + o2_11i; d3_11r <= o2_9r - o2_11r; d3_11i <= o2_9i - o2_11i; end
    wire signed [22:0] o3_9r, o3_9i, o3_11r, o3_11i;
    cfft32_dly #(.W(23), .D(4)) u_s3_9_r (.clk(clk), .x(s3_9r), .y(o3_9r));
    cfft32_dly #(.W(23), .D(4)) u_s3_9_i (.clk(clk), .x(s3_9i), .y(o3_9i));
    wire signed [22:0] nj3_11 = -d3_11i;
    cfft32_dly #(.W(23), .D(4)) u_d3_11_r (.clk(clk), .x(nj3_11), .y(o3_11r));
    cfft32_dly #(.W(23), .D(4)) u_d3_11_i (.clk(clk), .x(d3_11r), .y(o3_11i));
    reg signed [22:0] s3_12r, s3_12i, d3_14r, d3_14i;
    always @(posedge clk) begin s3_12r <= o2_12r + o2_14r; s3_12i <= o2_12i + o2_14i; d3_14r <= o2_12r - o2_14r; d3_14i <= o2_12i - o2_14i; end
    wire signed [22:0] o3_12r, o3_12i, o3_14r, o3_14i;
    cfft32_dly #(.W(23), .D(4)) u_s3_12_r (.clk(clk), .x(s3_12r), .y(o3_12r));
    cfft32_dly #(.W(23), .D(4)) u_s3_12_i (.clk(clk), .x(s3_12i), .y(o3_12i));
    cfft32_dly #(.W(23), .D(4)) u_d3_14_r (.clk(clk), .x(d3_14r), .y(o3_14r));
    cfft32_dly #(.W(23), .D(4)) u_d3_14_i (.clk(clk), .x(d3_14i), .y(o3_14i));
    reg signed [22:0] s3_13r, s3_13i, d3_15r, d3_15i;
    always @(posedge clk) begin s3_13r <= o2_13r + o2_15r; s3_13i <= o2_13i + o2_15i; d3_15r <= o2_13r - o2_15r; d3_15i <= o2_13i - o2_15i; end
    wire signed [22:0] o3_13r, o3_13i, o3_15r, o3_15i;
    cfft32_dly #(.W(23), .D(4)) u_s3_13_r (.clk(clk), .x(s3_13r), .y(o3_13r));
    cfft32_dly #(.W(23), .D(4)) u_s3_13_i (.clk(clk), .x(s3_13i), .y(o3_13i));
    wire signed [22:0] nj3_15 = -d3_15i;
    cfft32_dly #(.W(23), .D(4)) u_d3_15_r (.clk(clk), .x(nj3_15), .y(o3_15r));
    cfft32_dly #(.W(23), .D(4)) u_d3_15_i (.clk(clk), .x(d3_15r), .y(o3_15i));
    reg signed [22:0] s3_16r, s3_16i, d3_18r, d3_18i;
    always @(posedge clk) begin s3_16r <= o2_16r + o2_18r; s3_16i <= o2_16i + o2_18i; d3_18r <= o2_16r - o2_18r; d3_18i <= o2_16i - o2_18i; end
    wire signed [22:0] o3_16r, o3_16i, o3_18r, o3_18i;
    cfft32_dly #(.W(23), .D(4)) u_s3_16_r (.clk(clk), .x(s3_16r), .y(o3_16r));
    cfft32_dly #(.W(23), .D(4)) u_s3_16_i (.clk(clk), .x(s3_16i), .y(o3_16i));
    cfft32_dly #(.W(23), .D(4)) u_d3_18_r (.clk(clk), .x(d3_18r), .y(o3_18r));
    cfft32_dly #(.W(23), .D(4)) u_d3_18_i (.clk(clk), .x(d3_18i), .y(o3_18i));
    reg signed [22:0] s3_17r, s3_17i, d3_19r, d3_19i;
    always @(posedge clk) begin s3_17r <= o2_17r + o2_19r; s3_17i <= o2_17i + o2_19i; d3_19r <= o2_17r - o2_19r; d3_19i <= o2_17i - o2_19i; end
    wire signed [22:0] o3_17r, o3_17i, o3_19r, o3_19i;
    cfft32_dly #(.W(23), .D(4)) u_s3_17_r (.clk(clk), .x(s3_17r), .y(o3_17r));
    cfft32_dly #(.W(23), .D(4)) u_s3_17_i (.clk(clk), .x(s3_17i), .y(o3_17i));
    wire signed [22:0] nj3_19 = -d3_19i;
    cfft32_dly #(.W(23), .D(4)) u_d3_19_r (.clk(clk), .x(nj3_19), .y(o3_19r));
    cfft32_dly #(.W(23), .D(4)) u_d3_19_i (.clk(clk), .x(d3_19r), .y(o3_19i));
    reg signed [22:0] s3_20r, s3_20i, d3_22r, d3_22i;
    always @(posedge clk) begin s3_20r <= o2_20r + o2_22r; s3_20i <= o2_20i + o2_22i; d3_22r <= o2_20r - o2_22r; d3_22i <= o2_20i - o2_22i; end
    wire signed [22:0] o3_20r, o3_20i, o3_22r, o3_22i;
    cfft32_dly #(.W(23), .D(4)) u_s3_20_r (.clk(clk), .x(s3_20r), .y(o3_20r));
    cfft32_dly #(.W(23), .D(4)) u_s3_20_i (.clk(clk), .x(s3_20i), .y(o3_20i));
    cfft32_dly #(.W(23), .D(4)) u_d3_22_r (.clk(clk), .x(d3_22r), .y(o3_22r));
    cfft32_dly #(.W(23), .D(4)) u_d3_22_i (.clk(clk), .x(d3_22i), .y(o3_22i));
    reg signed [22:0] s3_21r, s3_21i, d3_23r, d3_23i;
    always @(posedge clk) begin s3_21r <= o2_21r + o2_23r; s3_21i <= o2_21i + o2_23i; d3_23r <= o2_21r - o2_23r; d3_23i <= o2_21i - o2_23i; end
    wire signed [22:0] o3_21r, o3_21i, o3_23r, o3_23i;
    cfft32_dly #(.W(23), .D(4)) u_s3_21_r (.clk(clk), .x(s3_21r), .y(o3_21r));
    cfft32_dly #(.W(23), .D(4)) u_s3_21_i (.clk(clk), .x(s3_21i), .y(o3_21i));
    wire signed [22:0] nj3_23 = -d3_23i;
    cfft32_dly #(.W(23), .D(4)) u_d3_23_r (.clk(clk), .x(nj3_23), .y(o3_23r));
    cfft32_dly #(.W(23), .D(4)) u_d3_23_i (.clk(clk), .x(d3_23r), .y(o3_23i));
    reg signed [22:0] s3_24r, s3_24i, d3_26r, d3_26i;
    always @(posedge clk) begin s3_24r <= o2_24r + o2_26r; s3_24i <= o2_24i + o2_26i; d3_26r <= o2_24r - o2_26r; d3_26i <= o2_24i - o2_26i; end
    wire signed [22:0] o3_24r, o3_24i, o3_26r, o3_26i;
    cfft32_dly #(.W(23), .D(4)) u_s3_24_r (.clk(clk), .x(s3_24r), .y(o3_24r));
    cfft32_dly #(.W(23), .D(4)) u_s3_24_i (.clk(clk), .x(s3_24i), .y(o3_24i));
    cfft32_dly #(.W(23), .D(4)) u_d3_26_r (.clk(clk), .x(d3_26r), .y(o3_26r));
    cfft32_dly #(.W(23), .D(4)) u_d3_26_i (.clk(clk), .x(d3_26i), .y(o3_26i));
    reg signed [22:0] s3_25r, s3_25i, d3_27r, d3_27i;
    always @(posedge clk) begin s3_25r <= o2_25r + o2_27r; s3_25i <= o2_25i + o2_27i; d3_27r <= o2_25r - o2_27r; d3_27i <= o2_25i - o2_27i; end
    wire signed [22:0] o3_25r, o3_25i, o3_27r, o3_27i;
    cfft32_dly #(.W(23), .D(4)) u_s3_25_r (.clk(clk), .x(s3_25r), .y(o3_25r));
    cfft32_dly #(.W(23), .D(4)) u_s3_25_i (.clk(clk), .x(s3_25i), .y(o3_25i));
    wire signed [22:0] nj3_27 = -d3_27i;
    cfft32_dly #(.W(23), .D(4)) u_d3_27_r (.clk(clk), .x(nj3_27), .y(o3_27r));
    cfft32_dly #(.W(23), .D(4)) u_d3_27_i (.clk(clk), .x(d3_27r), .y(o3_27i));
    reg signed [22:0] s3_28r, s3_28i, d3_30r, d3_30i;
    always @(posedge clk) begin s3_28r <= o2_28r + o2_30r; s3_28i <= o2_28i + o2_30i; d3_30r <= o2_28r - o2_30r; d3_30i <= o2_28i - o2_30i; end
    wire signed [22:0] o3_28r, o3_28i, o3_30r, o3_30i;
    cfft32_dly #(.W(23), .D(4)) u_s3_28_r (.clk(clk), .x(s3_28r), .y(o3_28r));
    cfft32_dly #(.W(23), .D(4)) u_s3_28_i (.clk(clk), .x(s3_28i), .y(o3_28i));
    cfft32_dly #(.W(23), .D(4)) u_d3_30_r (.clk(clk), .x(d3_30r), .y(o3_30r));
    cfft32_dly #(.W(23), .D(4)) u_d3_30_i (.clk(clk), .x(d3_30i), .y(o3_30i));
    reg signed [22:0] s3_29r, s3_29i, d3_31r, d3_31i;
    always @(posedge clk) begin s3_29r <= o2_29r + o2_31r; s3_29i <= o2_29i + o2_31i; d3_31r <= o2_29r - o2_31r; d3_31i <= o2_29i - o2_31i; end
    wire signed [22:0] o3_29r, o3_29i, o3_31r, o3_31i;
    cfft32_dly #(.W(23), .D(4)) u_s3_29_r (.clk(clk), .x(s3_29r), .y(o3_29r));
    cfft32_dly #(.W(23), .D(4)) u_s3_29_i (.clk(clk), .x(s3_29i), .y(o3_29i));
    wire signed [22:0] nj3_31 = -d3_31i;
    cfft32_dly #(.W(23), .D(4)) u_d3_31_r (.clk(clk), .x(nj3_31), .y(o3_31r));
    cfft32_dly #(.W(23), .D(4)) u_d3_31_i (.clk(clk), .x(d3_31r), .y(o3_31i));
    // ---- 段 4（span 1、出口 24 bit）
    reg signed [23:0] s4_0r, s4_0i, d4_1r, d4_1i;
    always @(posedge clk) begin s4_0r <= o3_0r + o3_1r; s4_0i <= o3_0i + o3_1i; d4_1r <= o3_0r - o3_1r; d4_1i <= o3_0i - o3_1i; end
    wire signed [23:0] o4_0r, o4_0i, o4_1r, o4_1i;
    cfft32_dly #(.W(24), .D(4)) u_s4_0_r (.clk(clk), .x(s4_0r), .y(o4_0r));
    cfft32_dly #(.W(24), .D(4)) u_s4_0_i (.clk(clk), .x(s4_0i), .y(o4_0i));
    cfft32_dly #(.W(24), .D(4)) u_d4_1_r (.clk(clk), .x(d4_1r), .y(o4_1r));
    cfft32_dly #(.W(24), .D(4)) u_d4_1_i (.clk(clk), .x(d4_1i), .y(o4_1i));
    reg signed [23:0] s4_2r, s4_2i, d4_3r, d4_3i;
    always @(posedge clk) begin s4_2r <= o3_2r + o3_3r; s4_2i <= o3_2i + o3_3i; d4_3r <= o3_2r - o3_3r; d4_3i <= o3_2i - o3_3i; end
    wire signed [23:0] o4_2r, o4_2i, o4_3r, o4_3i;
    cfft32_dly #(.W(24), .D(4)) u_s4_2_r (.clk(clk), .x(s4_2r), .y(o4_2r));
    cfft32_dly #(.W(24), .D(4)) u_s4_2_i (.clk(clk), .x(s4_2i), .y(o4_2i));
    cfft32_dly #(.W(24), .D(4)) u_d4_3_r (.clk(clk), .x(d4_3r), .y(o4_3r));
    cfft32_dly #(.W(24), .D(4)) u_d4_3_i (.clk(clk), .x(d4_3i), .y(o4_3i));
    reg signed [23:0] s4_4r, s4_4i, d4_5r, d4_5i;
    always @(posedge clk) begin s4_4r <= o3_4r + o3_5r; s4_4i <= o3_4i + o3_5i; d4_5r <= o3_4r - o3_5r; d4_5i <= o3_4i - o3_5i; end
    wire signed [23:0] o4_4r, o4_4i, o4_5r, o4_5i;
    cfft32_dly #(.W(24), .D(4)) u_s4_4_r (.clk(clk), .x(s4_4r), .y(o4_4r));
    cfft32_dly #(.W(24), .D(4)) u_s4_4_i (.clk(clk), .x(s4_4i), .y(o4_4i));
    cfft32_dly #(.W(24), .D(4)) u_d4_5_r (.clk(clk), .x(d4_5r), .y(o4_5r));
    cfft32_dly #(.W(24), .D(4)) u_d4_5_i (.clk(clk), .x(d4_5i), .y(o4_5i));
    reg signed [23:0] s4_6r, s4_6i, d4_7r, d4_7i;
    always @(posedge clk) begin s4_6r <= o3_6r + o3_7r; s4_6i <= o3_6i + o3_7i; d4_7r <= o3_6r - o3_7r; d4_7i <= o3_6i - o3_7i; end
    wire signed [23:0] o4_6r, o4_6i, o4_7r, o4_7i;
    cfft32_dly #(.W(24), .D(4)) u_s4_6_r (.clk(clk), .x(s4_6r), .y(o4_6r));
    cfft32_dly #(.W(24), .D(4)) u_s4_6_i (.clk(clk), .x(s4_6i), .y(o4_6i));
    cfft32_dly #(.W(24), .D(4)) u_d4_7_r (.clk(clk), .x(d4_7r), .y(o4_7r));
    cfft32_dly #(.W(24), .D(4)) u_d4_7_i (.clk(clk), .x(d4_7i), .y(o4_7i));
    reg signed [23:0] s4_8r, s4_8i, d4_9r, d4_9i;
    always @(posedge clk) begin s4_8r <= o3_8r + o3_9r; s4_8i <= o3_8i + o3_9i; d4_9r <= o3_8r - o3_9r; d4_9i <= o3_8i - o3_9i; end
    wire signed [23:0] o4_8r, o4_8i, o4_9r, o4_9i;
    cfft32_dly #(.W(24), .D(4)) u_s4_8_r (.clk(clk), .x(s4_8r), .y(o4_8r));
    cfft32_dly #(.W(24), .D(4)) u_s4_8_i (.clk(clk), .x(s4_8i), .y(o4_8i));
    cfft32_dly #(.W(24), .D(4)) u_d4_9_r (.clk(clk), .x(d4_9r), .y(o4_9r));
    cfft32_dly #(.W(24), .D(4)) u_d4_9_i (.clk(clk), .x(d4_9i), .y(o4_9i));
    reg signed [23:0] s4_10r, s4_10i, d4_11r, d4_11i;
    always @(posedge clk) begin s4_10r <= o3_10r + o3_11r; s4_10i <= o3_10i + o3_11i; d4_11r <= o3_10r - o3_11r; d4_11i <= o3_10i - o3_11i; end
    wire signed [23:0] o4_10r, o4_10i, o4_11r, o4_11i;
    cfft32_dly #(.W(24), .D(4)) u_s4_10_r (.clk(clk), .x(s4_10r), .y(o4_10r));
    cfft32_dly #(.W(24), .D(4)) u_s4_10_i (.clk(clk), .x(s4_10i), .y(o4_10i));
    cfft32_dly #(.W(24), .D(4)) u_d4_11_r (.clk(clk), .x(d4_11r), .y(o4_11r));
    cfft32_dly #(.W(24), .D(4)) u_d4_11_i (.clk(clk), .x(d4_11i), .y(o4_11i));
    reg signed [23:0] s4_12r, s4_12i, d4_13r, d4_13i;
    always @(posedge clk) begin s4_12r <= o3_12r + o3_13r; s4_12i <= o3_12i + o3_13i; d4_13r <= o3_12r - o3_13r; d4_13i <= o3_12i - o3_13i; end
    wire signed [23:0] o4_12r, o4_12i, o4_13r, o4_13i;
    cfft32_dly #(.W(24), .D(4)) u_s4_12_r (.clk(clk), .x(s4_12r), .y(o4_12r));
    cfft32_dly #(.W(24), .D(4)) u_s4_12_i (.clk(clk), .x(s4_12i), .y(o4_12i));
    cfft32_dly #(.W(24), .D(4)) u_d4_13_r (.clk(clk), .x(d4_13r), .y(o4_13r));
    cfft32_dly #(.W(24), .D(4)) u_d4_13_i (.clk(clk), .x(d4_13i), .y(o4_13i));
    reg signed [23:0] s4_14r, s4_14i, d4_15r, d4_15i;
    always @(posedge clk) begin s4_14r <= o3_14r + o3_15r; s4_14i <= o3_14i + o3_15i; d4_15r <= o3_14r - o3_15r; d4_15i <= o3_14i - o3_15i; end
    wire signed [23:0] o4_14r, o4_14i, o4_15r, o4_15i;
    cfft32_dly #(.W(24), .D(4)) u_s4_14_r (.clk(clk), .x(s4_14r), .y(o4_14r));
    cfft32_dly #(.W(24), .D(4)) u_s4_14_i (.clk(clk), .x(s4_14i), .y(o4_14i));
    cfft32_dly #(.W(24), .D(4)) u_d4_15_r (.clk(clk), .x(d4_15r), .y(o4_15r));
    cfft32_dly #(.W(24), .D(4)) u_d4_15_i (.clk(clk), .x(d4_15i), .y(o4_15i));
    reg signed [23:0] s4_16r, s4_16i, d4_17r, d4_17i;
    always @(posedge clk) begin s4_16r <= o3_16r + o3_17r; s4_16i <= o3_16i + o3_17i; d4_17r <= o3_16r - o3_17r; d4_17i <= o3_16i - o3_17i; end
    wire signed [23:0] o4_16r, o4_16i, o4_17r, o4_17i;
    cfft32_dly #(.W(24), .D(4)) u_s4_16_r (.clk(clk), .x(s4_16r), .y(o4_16r));
    cfft32_dly #(.W(24), .D(4)) u_s4_16_i (.clk(clk), .x(s4_16i), .y(o4_16i));
    cfft32_dly #(.W(24), .D(4)) u_d4_17_r (.clk(clk), .x(d4_17r), .y(o4_17r));
    cfft32_dly #(.W(24), .D(4)) u_d4_17_i (.clk(clk), .x(d4_17i), .y(o4_17i));
    reg signed [23:0] s4_18r, s4_18i, d4_19r, d4_19i;
    always @(posedge clk) begin s4_18r <= o3_18r + o3_19r; s4_18i <= o3_18i + o3_19i; d4_19r <= o3_18r - o3_19r; d4_19i <= o3_18i - o3_19i; end
    wire signed [23:0] o4_18r, o4_18i, o4_19r, o4_19i;
    cfft32_dly #(.W(24), .D(4)) u_s4_18_r (.clk(clk), .x(s4_18r), .y(o4_18r));
    cfft32_dly #(.W(24), .D(4)) u_s4_18_i (.clk(clk), .x(s4_18i), .y(o4_18i));
    cfft32_dly #(.W(24), .D(4)) u_d4_19_r (.clk(clk), .x(d4_19r), .y(o4_19r));
    cfft32_dly #(.W(24), .D(4)) u_d4_19_i (.clk(clk), .x(d4_19i), .y(o4_19i));
    reg signed [23:0] s4_20r, s4_20i, d4_21r, d4_21i;
    always @(posedge clk) begin s4_20r <= o3_20r + o3_21r; s4_20i <= o3_20i + o3_21i; d4_21r <= o3_20r - o3_21r; d4_21i <= o3_20i - o3_21i; end
    wire signed [23:0] o4_20r, o4_20i, o4_21r, o4_21i;
    cfft32_dly #(.W(24), .D(4)) u_s4_20_r (.clk(clk), .x(s4_20r), .y(o4_20r));
    cfft32_dly #(.W(24), .D(4)) u_s4_20_i (.clk(clk), .x(s4_20i), .y(o4_20i));
    cfft32_dly #(.W(24), .D(4)) u_d4_21_r (.clk(clk), .x(d4_21r), .y(o4_21r));
    cfft32_dly #(.W(24), .D(4)) u_d4_21_i (.clk(clk), .x(d4_21i), .y(o4_21i));
    reg signed [23:0] s4_22r, s4_22i, d4_23r, d4_23i;
    always @(posedge clk) begin s4_22r <= o3_22r + o3_23r; s4_22i <= o3_22i + o3_23i; d4_23r <= o3_22r - o3_23r; d4_23i <= o3_22i - o3_23i; end
    wire signed [23:0] o4_22r, o4_22i, o4_23r, o4_23i;
    cfft32_dly #(.W(24), .D(4)) u_s4_22_r (.clk(clk), .x(s4_22r), .y(o4_22r));
    cfft32_dly #(.W(24), .D(4)) u_s4_22_i (.clk(clk), .x(s4_22i), .y(o4_22i));
    cfft32_dly #(.W(24), .D(4)) u_d4_23_r (.clk(clk), .x(d4_23r), .y(o4_23r));
    cfft32_dly #(.W(24), .D(4)) u_d4_23_i (.clk(clk), .x(d4_23i), .y(o4_23i));
    reg signed [23:0] s4_24r, s4_24i, d4_25r, d4_25i;
    always @(posedge clk) begin s4_24r <= o3_24r + o3_25r; s4_24i <= o3_24i + o3_25i; d4_25r <= o3_24r - o3_25r; d4_25i <= o3_24i - o3_25i; end
    wire signed [23:0] o4_24r, o4_24i, o4_25r, o4_25i;
    cfft32_dly #(.W(24), .D(4)) u_s4_24_r (.clk(clk), .x(s4_24r), .y(o4_24r));
    cfft32_dly #(.W(24), .D(4)) u_s4_24_i (.clk(clk), .x(s4_24i), .y(o4_24i));
    cfft32_dly #(.W(24), .D(4)) u_d4_25_r (.clk(clk), .x(d4_25r), .y(o4_25r));
    cfft32_dly #(.W(24), .D(4)) u_d4_25_i (.clk(clk), .x(d4_25i), .y(o4_25i));
    reg signed [23:0] s4_26r, s4_26i, d4_27r, d4_27i;
    always @(posedge clk) begin s4_26r <= o3_26r + o3_27r; s4_26i <= o3_26i + o3_27i; d4_27r <= o3_26r - o3_27r; d4_27i <= o3_26i - o3_27i; end
    wire signed [23:0] o4_26r, o4_26i, o4_27r, o4_27i;
    cfft32_dly #(.W(24), .D(4)) u_s4_26_r (.clk(clk), .x(s4_26r), .y(o4_26r));
    cfft32_dly #(.W(24), .D(4)) u_s4_26_i (.clk(clk), .x(s4_26i), .y(o4_26i));
    cfft32_dly #(.W(24), .D(4)) u_d4_27_r (.clk(clk), .x(d4_27r), .y(o4_27r));
    cfft32_dly #(.W(24), .D(4)) u_d4_27_i (.clk(clk), .x(d4_27i), .y(o4_27i));
    reg signed [23:0] s4_28r, s4_28i, d4_29r, d4_29i;
    always @(posedge clk) begin s4_28r <= o3_28r + o3_29r; s4_28i <= o3_28i + o3_29i; d4_29r <= o3_28r - o3_29r; d4_29i <= o3_28i - o3_29i; end
    wire signed [23:0] o4_28r, o4_28i, o4_29r, o4_29i;
    cfft32_dly #(.W(24), .D(4)) u_s4_28_r (.clk(clk), .x(s4_28r), .y(o4_28r));
    cfft32_dly #(.W(24), .D(4)) u_s4_28_i (.clk(clk), .x(s4_28i), .y(o4_28i));
    cfft32_dly #(.W(24), .D(4)) u_d4_29_r (.clk(clk), .x(d4_29r), .y(o4_29r));
    cfft32_dly #(.W(24), .D(4)) u_d4_29_i (.clk(clk), .x(d4_29i), .y(o4_29i));
    reg signed [23:0] s4_30r, s4_30i, d4_31r, d4_31i;
    always @(posedge clk) begin s4_30r <= o3_30r + o3_31r; s4_30i <= o3_30i + o3_31i; d4_31r <= o3_30r - o3_31r; d4_31i <= o3_30i - o3_31i; end
    wire signed [23:0] o4_30r, o4_30i, o4_31r, o4_31i;
    cfft32_dly #(.W(24), .D(4)) u_s4_30_r (.clk(clk), .x(s4_30r), .y(o4_30r));
    cfft32_dly #(.W(24), .D(4)) u_s4_30_i (.clk(clk), .x(s4_30i), .y(o4_30i));
    cfft32_dly #(.W(24), .D(4)) u_d4_31_r (.clk(clk), .x(d4_31r), .y(o4_31r));
    cfft32_dly #(.W(24), .D(4)) u_d4_31_i (.clk(clk), .x(d4_31i), .y(o4_31i));
    // cmul の数: 65
    // ---- 出口（bit 反転順 → 自然順は配線）
    assign m_f[0 +: 24] = o4_0r;
    assign m_f[24 +: 24] = o4_0i;
    assign m_f[48 +: 24] = o4_16r;
    assign m_f[72 +: 24] = o4_16i;
    assign m_f[96 +: 24] = o4_8r;
    assign m_f[120 +: 24] = o4_8i;
    assign m_f[144 +: 24] = o4_24r;
    assign m_f[168 +: 24] = o4_24i;
    assign m_f[192 +: 24] = o4_4r;
    assign m_f[216 +: 24] = o4_4i;
    assign m_f[240 +: 24] = o4_20r;
    assign m_f[264 +: 24] = o4_20i;
    assign m_f[288 +: 24] = o4_12r;
    assign m_f[312 +: 24] = o4_12i;
    assign m_f[336 +: 24] = o4_28r;
    assign m_f[360 +: 24] = o4_28i;
    assign m_f[384 +: 24] = o4_2r;
    assign m_f[408 +: 24] = o4_2i;
    assign m_f[432 +: 24] = o4_18r;
    assign m_f[456 +: 24] = o4_18i;
    assign m_f[480 +: 24] = o4_10r;
    assign m_f[504 +: 24] = o4_10i;
    assign m_f[528 +: 24] = o4_26r;
    assign m_f[552 +: 24] = o4_26i;
    assign m_f[576 +: 24] = o4_6r;
    assign m_f[600 +: 24] = o4_6i;
    assign m_f[624 +: 24] = o4_22r;
    assign m_f[648 +: 24] = o4_22i;
    assign m_f[672 +: 24] = o4_14r;
    assign m_f[696 +: 24] = o4_14i;
    assign m_f[720 +: 24] = o4_30r;
    assign m_f[744 +: 24] = o4_30i;
    assign m_f[768 +: 24] = o4_1r;
    assign m_f[792 +: 24] = o4_1i;
    assign m_f[816 +: 24] = o4_17r;
    assign m_f[840 +: 24] = o4_17i;
    assign m_f[864 +: 24] = o4_9r;
    assign m_f[888 +: 24] = o4_9i;
    assign m_f[912 +: 24] = o4_25r;
    assign m_f[936 +: 24] = o4_25i;
    assign m_f[960 +: 24] = o4_5r;
    assign m_f[984 +: 24] = o4_5i;
    assign m_f[1008 +: 24] = o4_21r;
    assign m_f[1032 +: 24] = o4_21i;
    assign m_f[1056 +: 24] = o4_13r;
    assign m_f[1080 +: 24] = o4_13i;
    assign m_f[1104 +: 24] = o4_29r;
    assign m_f[1128 +: 24] = o4_29i;
    assign m_f[1152 +: 24] = o4_3r;
    assign m_f[1176 +: 24] = o4_3i;
    assign m_f[1200 +: 24] = o4_19r;
    assign m_f[1224 +: 24] = o4_19i;
    assign m_f[1248 +: 24] = o4_11r;
    assign m_f[1272 +: 24] = o4_11i;
    assign m_f[1296 +: 24] = o4_27r;
    assign m_f[1320 +: 24] = o4_27i;
    assign m_f[1344 +: 24] = o4_7r;
    assign m_f[1368 +: 24] = o4_7i;
    assign m_f[1392 +: 24] = o4_23r;
    assign m_f[1416 +: 24] = o4_23i;
    assign m_f[1440 +: 24] = o4_15r;
    assign m_f[1464 +: 24] = o4_15i;
    assign m_f[1488 +: 24] = o4_31r;
    assign m_f[1512 +: 24] = o4_31i;
    reg [28:0] vsh = 0;
    always @(posedge clk) vsh <= {vsh[27:0], s_valid};
    assign m_valid = vsh[28];
endmodule
`default_nettype wire
