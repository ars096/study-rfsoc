// SPDX-License-Identifier: BSD-3-Clause
// tb_g24_coef — g24_coef の単体（proj025 手順 1a）。1 フレーム（8192 ビート）＋ 次のフレームの頭 512 ビートを流し、
// 途中に有効の切れ目（3 クロック）を入れる。出口の (m_out, coef) を `OUT/coef.txt に書き、判定は sim/check_g24.py coef。
// tb の中で数えるもの: 出口の順番が入れた順番と同じ・レイテンシがどのビートも同じ（値を表示。RTL の LAT と合うか）
`timescale 1ns / 1ps
module tb_g24_coef;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg  [12:0] addr = 0;
    reg         addr_v = 0;
    wire [1151:0] coef;
    wire [12:0] m_out;
    wire v_out;
    g24_coef #(.LO_FILE(`LO), .HI_FILE(`HI)) u (.clk(clk), .addr(addr), .addr_v(addr_v), .coef(coef), .m_out(m_out), .v_out(v_out));

    localparam integer NB = 8192 + 512;
    reg [12:0] em [0:NB-1];
    integer    ec [0:NB-1];
    integer cyc = 0, nin = 0, nout = 0, bad_ord = 0, bad_lat = 0, fd, lat0 = -1;
    always @(posedge clk) cyc <= cyc + 1;

    always @(posedge clk) if (v_out === 1'b1) begin
        if (nout >= nin || m_out !== em[nout]) bad_ord = bad_ord + 1;
        if (lat0 < 0) lat0 = cyc - ec[nout];
        if (cyc - ec[nout] != lat0) bad_lat = bad_lat + 1;
        $fwrite(fd, "%0d %h\n", m_out, coef);
        nout = nout + 1;
    end

    integer i;
    initial begin
        fd = $fopen({`OUT, "/coef.txt"}, "w");
        repeat (4) @(posedge clk);
        for (i = 0; i < NB; i = i + 1) begin
            if (i == 1000 || i == 6001) begin       // 切れ目: 3 クロック有効を落とす（番地はそのまま）
                @(negedge clk); addr_v = 0;
                repeat (3) @(negedge clk);
            end
            @(negedge clk);
            addr = i[12:0]; addr_v = 1;
            em[nin] = i[12:0]; ec[nin] = cyc + 1; nin = nin + 1;
        end
        @(negedge clk); addr_v = 0;
        repeat (10) @(posedge clk);
        $fclose(fd);
        $display("tb_g24_coef: 入れた %0d・出た %0d・順番の誤り %0d・レイテンシ %0d クロック（揃わない %0d）", nin, nout, bad_ord, lat0, bad_lat);
        if (nin == nout && bad_ord == 0 && bad_lat == 0) $display("tb: 口の振る舞い OK");
        else $display("tb: 口の振る舞い NG");
        $finish;
    end
endmodule
