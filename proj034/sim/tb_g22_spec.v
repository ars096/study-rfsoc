// SPDX-License-Identifier: BSD-3-Clause
// tb_g22_spec — g22_spec の単体（proj025 手順 2c。proj024 の tb_g21_spec を 8192 ビートのフレームに）。入力は `OUT/x.hex（sim/check_g22.py spec-gen。1 行 = 1 ビート = T のビート）。
// T は 0 から 1 クロックに 1。s_tdata = x[T]（T と同じクロック）。設定: WRST → PFB が始まったら RUN（SHIFT `SHIFT・N_ACC 2・N_DUMP 2）。
// （2d から SHIFT は RUN で効く。w_shift はずっと `SHIFT なので、2c のときと同じ値で積む）
// 記録: PFB の出口（`OUT/y.txt）・IP の出口（`OUT/ip.txt）・ダンプ（commit の瞬間に凍った面の記憶をそのまま写す `OUT/dump<seq>.txt）。
// 読み出しの口（rd_c → rd_d）は各ダンプの頭 4096 ch だけ口からも読んで、写しと比べる（全部は 2b で確かめた）
`timescale 1ns / 1ps
module tb_g22_spec;
    localparam integer NB = 10 * 8192;
    reg clk = 0;
    always #1.953 clk = ~clk;
    reg rst = 1;
    reg [63:0] t = 0;
    reg [255:0] d = 0;
    reg v = 0;
    reg wrst = 0, run = 0, stop = 0, fclr = 0;
    reg [15:0] rc = 0;
    wire [63:0] rd;
    wire [3:0] c_shift;
    wire go, st_sched, st_acc, commit, rd_plane, have_first;
    wire [47:0] fa_now, fo, df0;
    wire [7:0] flags;
    wire [31:0] seq, dk, dn, dsat, ip_ph;
    wire [15:0] pfb_sat, ipq, ip_st;
    wire [1023:0] ip_td;
    wire [12:0] ip_k1;
    wire ip_v;
    g22_spec #(.ST_N(256), .GF_L2(1), .SHIFT_DEFAULT(7),
               .LO_FILE(`LO), .HI_FILE(`HI), .TA_FILE(`TA), .TB_FILE(`TB)) u (
        .clk(clk), .rst(rst), .s_tdata(d), .s_tvalid(v), .t_in(t),
        .cmd_wrst(wrst), .w_shift(4'd`SHIFT), .cmd_run(run), .cmd_stop(stop), .r_nacc(32'd2), .r_ndump(32'd2), .flags_clr(fclr),
        .c_shift(c_shift), .go(go), .fa_now(fa_now), .fo(fo), .flags(flags), .st_sched(st_sched), .st_acc(st_acc),
        .commit(commit), .seq(seq), .dk(dk), .df0(df0), .dn(dn), .dsat(dsat), .rd_plane(rd_plane),
        .rd_c(rc), .rd_d(rd),
        .dbg_pfb_sat(pfb_sat), .dbg_have_first(have_first), .dbg_ipq(ipq), .dbg_ip_ph(ip_ph), .dbg_ip_st(ip_st),
        .dbg_ip_tdata(ip_td), .dbg_ip_k1(ip_k1), .dbg_ip_v(ip_v));

    reg [255:0] xm [0:NB-1];
    integer fy, fi, fdmp, k, nrd_bad = 0, ndump = 0;
    reg [383:0] snap [0:8191];
    // 入力: T のビートに x[T]
    always @(posedge clk) t <= t + 1;
    always @(negedge clk) begin d <= (t < NB) ? xm[t] : 256'd0; v <= !rst && (t < NB); end
    // 記録
    always @(posedge clk) begin
        if (u.y_v) $fwrite(fy, "%0d %h\n", u.y_m, u.y);
        if (ip_v)  $fwrite(fi, "%0d %h\n", ip_k1, ip_td);
    end
    // ダンプ: commit の次のクロックで dump_* と rd_plane が変わっている
    always @(posedge clk) if (commit) begin
        #0.1;
        for (k = 0; k < 8192; k = k + 1) snap[k] = rd_plane ? u.u_acc.g_pl[1].mem[k] : u.u_acc.g_pl[0].mem[k];
        case (seq)
            1: fdmp = $fopen({`OUT, "/dump1.txt"}, "w");
            2: fdmp = $fopen({`OUT, "/dump2.txt"}, "w");
            default: fdmp = $fopen({`OUT, "/dump_x.txt"}, "w");
        endcase
        $fwrite(fdmp, "# seq %0d dk %0d df0 %0d dn %0d dsat %0d plane %0d f_first %0d\n", seq, dk, df0, dn, dsat, rd_plane, u.f_first);
        for (k = 0; k < 8192; k = k + 1) $fwrite(fdmp, "%h\n", snap[k]);
        $fclose(fdmp);
        ndump = ndump + 1;
        rd_check;
    end
    task rd_check;
        integer c;
        reg [47:0] e;
        begin
            for (c = 0; c < 4096 + 4; c = c + 1) begin
                @(negedge clk); rc = c[15:0];
                if (c >= 4) begin
                    e = snap[(c - 4) & 8191][48 * ((c - 4) >> 13) +: 48];
                    if (rd !== {16'd0, e}) nrd_bad = nrd_bad + 1;
                end
            end
        end
    endtask
    initial begin
        $readmemh({`OUT, "/x.hex"}, xm);
        fy = $fopen({`OUT, "/y.txt"}, "w");
        fi = $fopen({`OUT, "/ip.txt"}, "w");
        repeat (6) @(posedge clk);
        @(negedge clk); rst = 0;
        @(negedge clk); wrst = 1;
        @(negedge clk); wrst = 0;
        wait (have_first);
        @(negedge clk); run = 1;
        @(negedge clk); run = 0;
        wait (ndump == 2);
        repeat (4200) @(posedge clk);
        $fclose(fy); $fclose(fi);
        $display("tb_g22_spec: ダンプ %0d・flags %h・SHIFT %0d・ipq %h（待たされた %0d）・f_first %0d・rd の不一致 %0d・pfb_sat %0d",
                 ndump, flags, c_shift, ipq, ipq[15:8], u.f_first, nrd_bad, pfb_sat);
        $finish;
    end
    initial begin #(3.906 * 13 * 8192); $display("tb_g22_spec: 時間切れ（ダンプ %0d・flags %h）", ndump, flags); $finish; end
endmodule
