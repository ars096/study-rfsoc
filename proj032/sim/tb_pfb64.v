// tb_pfb64 — pfb64_core の値を仕様の式（浮動小数点）と比べるための台（E-2 の確かめ。bit 単位の照合は P の段で）
//   入力: x_in.hex（1 行 = 1 ビート 16 サンプル × 16 bit、lane 0 が下位）。出力: y_out.txt（valid なビートごとに頭 16 本の re im）
`timescale 1ns / 1ps
module tb_pfb64;
    localparam integer NH = 16, YW = 24, NBEAT = 400;
    reg clk = 0; always #1.953 clk = ~clk;
    reg rst = 1;
    reg [255:0] mem [0:NBEAT-1];
    reg [255:0] d; reg v;
    // 頭の ch（端・中央・偶奇・mod 4 の全部）
`ifdef PSPLIT
    // 頭 0..7 は偶の k、8..15 は奇の k（check_pfb64.py の K_PS と同じ並び）
    wire [6*NH-1:0] k = {6'd31, 6'd29, 6'd21, 6'd17, 6'd13, 6'd5, 6'd3, 6'd1, 6'd4, 6'd32, 6'd30, 6'd24, 6'd16, 6'd8, 6'd2, 6'd0};
    localparam integer PS = 1;
`else
    wire [6*NH-1:0] k = {6'd30, 6'd24, 6'd7, 6'd32, 6'd31, 6'd29, 6'd21, 6'd17, 6'd16, 6'd13, 6'd8, 6'd5, 6'd3, 6'd2, 6'd1, 6'd0};
    localparam integer PS = 0;
`endif
    wire [YW*NH-1:0] yr, yi; wire yv;
    pfb64_core #(.NH(NH), .PSPLIT(PS)) dut (.clk(clk), .rst(rst), .s_tdata(d), .s_tvalid(v), .k(k), .y_re(yr), .y_im(yi), .y_valid(yv));
    integer q, h, fo;
    initial begin
        $readmemh(`XIN, mem);
        fo = $fopen(`YOUT, "w");
        d = 0; v = 0;
        repeat (5) @(posedge clk);
        rst <= 0;
        for (q = 0; q < NBEAT; q = q + 1) begin
            @(posedge clk); d <= mem[q]; v <= 1;
            if (q % 7 == 3) begin @(posedge clk); v <= 0; end    // 途切れも入れる
        end
        @(posedge clk); v <= 0;
        repeat (60) @(posedge clk);
        $fclose(fo);
        $finish;
    end
    always @(posedge clk) if (yv) begin
        for (h = 0; h < NH; h = h + 1) $fwrite(fo, "%0d %0d ", $signed(yr[YW*h +: YW]), $signed(yi[YW*h +: YW]));
        $fwrite(fo, "\n");
    end
endmodule
