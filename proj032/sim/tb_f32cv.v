// proj032 K-2 — f32cv の照合。入力は sim/f32cv_in.txt（16 進の u64、1 行 1 個）、出力を f32cv_out.txt に（check_f32cv.py が numpy と照らす）
`timescale 1ns / 1ps
module tb_f32cv;
    reg clk = 0;
    always #2 clk = ~clk;
    reg         v = 0;
    reg  [63:0] u = 0;
    wire        ov;
    wire [31:0] of;
    f32cv dut (.clk(clk), .in_v(v), .in_u(u), .out_v(ov), .out_f(of));
    reg  [63:0] mem [0:65535];
    integer n, fo, k;
    initial begin
        for (k = 0; k < 65536; k = k + 1) mem[k] = 64'hx;
        $readmemh(`IN_FILE, mem);
        n = 0;
        while (n < 65536 && mem[n] !== 64'hx) n = n + 1;
        fo = $fopen(`OUT_FILE, "w");
        for (k = 0; k < n; k = k + 1) begin
            @(negedge clk); v = 1; u = mem[k];
`ifdef POSCTL
            if (k == 3) u = u ^ 64'd1;                   // 陽性対照: 1 個だけ入力を変える（3 → 2。大きな値の最下位は丸めで消えて落ちない: 1 回目は k 100 で落ちなかった）
`endif
        end
        @(negedge clk); v = 0;
        repeat (8) @(posedge clk);
        $fclose(fo);
        $display("tb_f32cv: %0d 個", n);
        $finish;
    end
    always @(posedge clk) if (ov) $fwrite(fo, "%08x\n", of);
endmodule
