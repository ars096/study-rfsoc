// SPDX-License-Identifier: BSD-3-Clause
// proj028 F-3 — fine_acc ＋ fine_rdo の試験台。ch A を積み、A の読み出しと同時に ch B を別の面に積み、最後に B を読み出す
//   入力の 1 行 = {plane, first, act, k1 13 bit, 16 × p 37 bit}。出口の 64 bit を書く（下流の tready はランダム）
`timescale 1ns/1ps
`default_nettype none
module tb_fine_acc;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [16*37+15:0] mem [0:`NBEAT-1];
    reg [16*37-1:0] p = 0; reg p_v = 0; reg [12:0] p_k1 = 0; reg t_act = 0, t_first = 0, t_plane = 0;
    wire [16:0] rd_c; wire rd_plane; wire [63:0] rd_d;
    reg start = 0, st_plane = 0; reg [4:0] st_k = 0; reg [31:0] st_c = 0; reg [15:0] st_nfr = 0;
    wire [63:0] tdata; wire tlast, tvalid, busy, f_drop; wire [15:0] n_drop; reg tready = 0;
    fine_acc u_acc (.clk(clk), .rst(rst), .p(p), .p_v(p_v), .p_k1(p_k1), .t_act(t_act), .t_first(t_first), .t_plane(t_plane),
        .rd_c(rd_c), .rd_plane(rd_plane), .rd_d(rd_d));
    fine_rdo u_rdo (.clk(clk), .rst(rst), .start(start), .st_plane(st_plane), .st_k(st_k), .st_c(st_c), .st_nfr(st_nfr),
        .rd_c(rd_c), .rd_plane(rd_plane), .rd_d(rd_d), .m_axis_tdata(tdata), .m_axis_tlast(tlast), .m_axis_tvalid(tvalid),
        .m_axis_tready(tready), .busy(busy), .n_drop(n_drop), .f_drop(f_drop));
    integer seed = 6, fo, nw = 0, i;
    always @(posedge clk) tready <= ($random(seed) % 4 != 0);
    always @(posedge clk) if (tvalid && tready) begin $fwrite(fo, "%0d %h\n", tlast, tdata); nw = nw + 1; end
    task frames(input integer b0, input integer b1); integer b; begin
        for (b = b0; b < b1; b = b + 1) begin
            @(negedge clk);
            p_v = 1; p = mem[b][16*37-1:0]; p_k1 = mem[b][16*37 +: 13]; t_act = mem[b][16*37+13]; t_first = mem[b][16*37+14]; t_plane = mem[b][16*37+15];
        end
        @(negedge clk); p_v = 0;
        repeat (8) @(posedge clk);
    end endtask
    task go(input pl, input [4:0] k, input [31:0] c, input [15:0] n); begin
        @(negedge clk); start = 1; st_plane = pl; st_k = k; st_c = c; st_nfr = n; @(negedge clk); start = 0;
    end endtask
    initial begin
        $readmemh(`IN_HEX, mem);
        fo = $fopen(`OUT_TXT, "w");
        repeat (4) @(posedge clk); @(negedge clk); rst = 0;
        frames(0, `NA);
        go(0, `KA, 7, 3);
        frames(`NA, `NBEAT);                       // A の読み出しと同時に B を面 1 に
        wait (!busy); repeat (3) @(posedge clk);
        go(1, `KB, 8, 3);
        @(posedge clk); wait (!busy);
        repeat (20) @(posedge clk);
        $display("words %0d drop %0d", nw, n_drop);
        $fclose(fo);
        $finish;
    end
endmodule
`default_nettype wire
