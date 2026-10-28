// axi_mem_model — DDR の振る舞いの模型（sim 専用、proj032 D-2）。書き 1 口（64 bit）・読み NR 口（128 bit）、記憶は 1 MiB
//   AR は口ごとに待ち行列。各 AR は着いてから LAT_MIN〜LAT_MAX クロック後に 128 拍を出し、拍はときどき途切れる（rvalid を GAP_PCT % で下げる）
//   書きは awready・wready をときどき下げ、最後の拍から 20〜80 クロック後に B を返す。+MEM_SLOW で遅延を大きく（陽性対照: 読み手の flags[0]）
`timescale 1ns / 1ps
module axi_mem_model #(
    parameter integer NR = 3
)(
    input  wire              clk,
    input  wire              rst,
    input  wire [31:0]       awaddr,
    input  wire              awvalid,
    output reg               awready,
    input  wire [63:0]       wdata,
    input  wire              wvalid,
    output reg               wready,
    input  wire              wlast,
    output reg               bvalid,
    input  wire [NR*32-1:0]  araddr,
    input  wire [NR-1:0]     arvalid,
    output reg  [NR-1:0]     arready,
    output reg  [NR*128-1:0] rdata,
    output reg  [NR-1:0]     rvalid,
    output reg  [NR-1:0]     rlast
);
    reg [7:0] mem [0:(1<<20)-1];
    integer lat_min, lat_max, gap;
    initial begin
        lat_min = 20; lat_max = 300; gap = 10;
        if ($test$plusargs("MEM_SLOW")) begin lat_min = 1500; lat_max = 2500; end
    end
    integer i, j, r;
    // ---- 書き ----
    reg [31:0] wa;
    reg        wbusy;
    integer    bcnt [0:63];
    integer    bn;
    always @(posedge clk) begin
        if (rst) begin awready <= 0; wready <= 0; bvalid <= 0; wbusy = 0; bn = 0; end
        else begin
            bvalid <= 0;
            awready <= !wbusy && (($random & 3) != 0);
            if (awvalid && awready) begin wa = awaddr; wbusy = 1; end
            wready <= wbusy && (($random & 7) != 0);
            if (wvalid && wready) begin
                for (j = 0; j < 8; j = j + 1) mem[(wa + j) & 20'hFFFFF] = wdata[j*8 +: 8];
                wa = wa + 8;
                if (wlast) begin wbusy = 0; bcnt[bn] = 20 + ($random & 63); bn = bn + 1; end
            end
            // B: 一番古いものから順に
            if (bn > 0) begin
                if (bcnt[0] == 0) begin
                    bvalid <= 1;
                    for (j = 0; j < 63; j = j + 1) bcnt[j] = bcnt[j+1];
                    bn = bn - 1;
                end else bcnt[0] = bcnt[0] - 1;
                for (j = 1; j < bn; j = j + 1) if (bcnt[j] > 0) bcnt[j] = bcnt[j] - 1;
            end
        end
    end
    // ---- 読み（口ごと）----
    genvar g;
    generate for (g = 0; g < NR; g = g + 1) begin : rp
        reg [31:0] qa [0:15];
        integer    qt [0:15];
        integer    qn, beat, k;
        reg [31:0] ra;
        always @(posedge clk) begin
            if (rst) begin arready[g] <= 0; rvalid[g] <= 0; rlast[g] <= 0; qn = 0; beat = 0; end
            else begin
                arready[g] <= (qn < 15);
                if (arvalid[g] && arready[g]) begin
                    qa[qn] = araddr[g*32 +: 32];
                    qt[qn] = lat_min + ({$random} % (lat_max - lat_min + 1));
                    qn = qn + 1;
                end
                for (k = 0; k < qn; k = k + 1) if (qt[k] > 0) qt[k] = qt[k] - 1;
                rvalid[g] <= 0; rlast[g] <= 0;
                if (qn > 0 && qt[0] == 0 && (({$random} % 100) >= gap)) begin
                    ra = qa[0] + beat * 16;
                    for (k = 0; k < 16; k = k + 1) rdata[g*128 + k*8 +: 8] <= mem[(ra + k) & 20'hFFFFF];
                    rvalid[g] <= 1;
                    rlast[g] <= (beat == 127);
                    beat = beat + 1;
                    if (beat == 128) begin
                        beat = 0;
                        for (k = 0; k < 15; k = k + 1) begin qa[k] = qa[k+1]; qt[k] = qt[k+1]; end
                        qn = qn - 1;
                    end
                end
            end
        end
    end endgenerate
endmodule
