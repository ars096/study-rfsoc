// SPDX-License-Identifier: BSD-3-Clause
// proj028 F-3 — 
// OOC 用の包み（tools/ooc_rtl.tcl の top に。sim では使わない）（fine_acc ＋ fine_rdo をつなぐだけ）
module f3_top (input wire clk, input wire rst, input wire [16*37-1:0] p, input wire p_v, input wire [12:0] p_k1,
    input wire t_act, input wire t_first, input wire t_plane, input wire start, input wire st_plane, input wire [4:0] st_k,
    input wire [31:0] st_c, input wire [15:0] st_nfr, output wire [63:0] tdata, output wire tlast, output wire tvalid, input wire tready,
    output wire busy);
    wire [16:0] rd_c; wire rd_plane; wire [63:0] rd_d; wire [15:0] nd; wire fdp;
    fine_acc u_acc (.clk(clk), .rst(rst), .p(p), .p_v(p_v), .p_k1(p_k1), .t_act(t_act), .t_first(t_first), .t_plane(t_plane),
        .rd_c(rd_c), .rd_plane(rd_plane), .rd_d(rd_d));
    fine_rdo u_rdo (.clk(clk), .rst(rst), .start(start), .st_plane(st_plane), .st_k(st_k), .st_c(st_c), .st_nfr(st_nfr),
        .rd_c(rd_c), .rd_plane(rd_plane), .rd_d(rd_d), .m_axis_tdata(tdata), .m_axis_tlast(tlast), .m_axis_tvalid(tvalid),
        .m_axis_tready(tready), .busy(busy), .n_drop(nd), .f_drop(fdp));
endmodule
