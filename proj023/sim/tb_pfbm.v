// SPDX-License-Identifier: BSD-3-Clause
// proj015 — pfb_core を 4 窓（NW = 4）で。窓ごとに別の k・別の始まり（w_rst を下ろす時刻）、窓 3 は途中で打ち直す（make sim-pfbm）
//   +GAP=<0|1> +IN=x.hex +NSAMP= +DIR=<出力のディレクトリ>
//   出力: DIR/y_w<w>.txt。区切りの行「# R <その時までに渡した valid なビートの数>」（w_rst を下ろした時）、
//         「# S <q_start>」（その区切りの最初の ok なフレームの前）、フレーム「実部 虚部」（m' の順）
//   -DPFB_QW=<n> で pfb_core のビートの番号を n bit に（巻き戻りの試験）
// 照合は sim/check_pfbm.py（窓ごとに x[8·m_s:] を model/win_fixed.py の pfb_fixed に通したものと bit 単位で）
`timescale 1ns / 1ps
`ifndef PFB_QW
`define PFB_QW 32
`endif
module tb_pfbm;
    localparam integer NW = 4;
    localparam integer QW = `PFB_QW;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [NW-1:0] wrst = {NW{1'b1}};
    reg  [255:0] tdata = 0;
    reg          tvalid = 0;
    wire [5*NW-1:0] kv = {5'd9, 5'd16, 5'd0, 5'd5};      // 窓 0: 5、1: 0、2: 16、3: 9
    wire [24*NW-1:0] y0r, y0i, y1r, y1i;
    wire [NW-1:0] y0ok, y1ok;
    wire yv;
    wire [16*NW-1:0] satc;
    wire [QW*NW-1:0] qst;
    pfb_core #(.NW(NW), .QW(QW)) dut (.clk(clk), .rst(rst), .w_rst(wrst), .s_tdata(tdata), .s_tvalid(tvalid), .k(kv),
        .y0_re(y0r), .y0_im(y0i), .y1_re(y1r), .y1_im(y1i), .y0_ok(y0ok), .y1_ok(y1ok), .y_valid(yv),
        .sat_cnt(satc), .q_start(qst));

    reg [15:0] mem [0:(1<<22)-1];
    integer nsamp, nbeat, b, l, gap, seed, w;
    integer fo [0:NW-1];
    integer nout [0:NW-1];
    reg     seg [0:NW-1];               // 1 = 区切りの最初のフレームを待っている
    reg [8*256-1:0] fin, dir, fname;
    // 窓ごとの予定（valid なビートの数で）: 下ろす / 打ち直す / もう一度下ろす
    //   窓 0: rst と同時（q_s = 5）/ 窓 1: ビート 2（まだ 5 に届かない → q_s = 5）/ 窓 2: ビート 301 / 窓 3: ビート 100 → 700 で打ち直し → 900
    function integer rel_at(input integer ww);
        case (ww) 0: rel_at = 0; 1: rel_at = 2; 2: rel_at = 301; default: rel_at = 100; endcase
    endfunction
    task mark(input integer ww, input integer nb);
        begin $fwrite(fo[ww], "# R %0d\n", nb); seg[ww] = 1; end
    endtask
    initial begin
        if (!$value$plusargs("GAP=%d", gap)) gap = 0;
        if (!$value$plusargs("NSAMP=%d", nsamp)) nsamp = 16 * 4096;
        if (!$value$plusargs("IN=%s", fin)) fin = "x.hex";
        if (!$value$plusargs("DIR=%s", dir)) dir = ".";
        $readmemh(fin, mem, 0, nsamp - 1);
        for (w = 0; w < NW; w = w + 1) begin
            $sformat(fname, "%0s/y_w%0d.txt", dir, w);
            fo[w] = $fopen(fname, "w");
            nout[w] = 0; seg[w] = 0;
        end
        seed = 15;
        nbeat = nsamp / 16;
        repeat (4) @(posedge clk);
        rst <= 0; wrst[0] <= 0; mark(0, 0);
        b = 0;
        while (b < nbeat) begin
            @(posedge clk);
            for (w = 1; w < NW; w = w + 1) if (wrst[w] && b == rel_at(w) && !(w == 3 && b > 600)) begin wrst[w] <= 0; mark(w, b); end
            if (b == 700 && !wrst[3]) begin wrst[3] <= 1; $fwrite(fo[3], "# X %0d\n", b); end
            if (b == 900 && wrst[3]) begin wrst[3] <= 0; mark(3, b); end
            if (gap && (($random(seed) & 7) == 0)) begin
                tvalid <= 0;
                tdata  <= {16{16'hDEAD}};
            end else begin
                for (l = 0; l < 16; l = l + 1) tdata[16*l +: 16] <= mem[16*b + l];
                tvalid <= 1;
                b = b + 1;
            end
        end
        @(posedge clk);
        tvalid <= 0;
        repeat (40) @(posedge clk);
        for (w = 0; w < NW; w = w + 1) begin
            $display("pfbm: 窓 %0d（k %0d）GAP=%0d QW=%0d 出力 %0d フレーム、飽和 %0d、q_start %0d", w, kv[5*w +: 5], gap, QW, nout[w], satc[16*w +: 16], qst[QW*w +: QW]);
            $fclose(fo[w]);
        end
        $finish;
    end
    always @(posedge clk) begin
        if (yv) for (w = 0; w < NW; w = w + 1) begin
            if ((y0ok[w] || y1ok[w]) && seg[w]) begin $fwrite(fo[w], "# S %0d\n", qst[QW*w +: QW]); seg[w] = 0; end
            if (y0ok[w]) begin $fwrite(fo[w], "%0d %0d\n", $signed(y0r[24*w +: 24]), $signed(y0i[24*w +: 24])); nout[w] = nout[w] + 1; end
            if (y1ok[w]) begin $fwrite(fo[w], "%0d %0d\n", $signed(y1r[24*w +: 24]), $signed(y1i[24*w +: 24])); nout[w] = nout[w] + 1; end
        end
    end
endmodule
