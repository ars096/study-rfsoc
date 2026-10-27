// SPDX-License-Identifier: BSD-3-Clause
// cu_src — sim だけの係数の源（proj031 P-2）。中身は g24_cu そのもの。
// コアの tb ごとに AXI で 4096 行を書いて VERIFY すると 30 万拍 ＋ 86,016 拍かかり、tb の入力（12 フレーム ≒ 49,000 拍）が先に尽きる。
// そこで URAM に裏口で中身を入れ（`WORDS、sim/check_cu.py gen の hex = PS が書くのと同じ値）、リセットが明けたら OK を立てる（u.ok に書く）。
// AXI の書き → VERIFY → OK の道そのものは sim-cu で確かめる。
// -DTB_CU_NOOK: OK を立てない（陽性対照。コアの口が開かず、ダンプが出ずに落ちるべき）
// -DTB_CU_DROP=<拍>: リセットが明けてからその拍で OK を落とす（陽性対照。flags[0] = coef_mis が立つべき）
// -DTB_CU_BACK=<拍>: 落としてからその拍で OK を戻す（proj031 rev 2: PS が書き直して VERIFY が通った形。flags_clr で coef_mis が消えるべき）
`timescale 1ns / 1ps
module cu_src (
    input  wire          clk,
    input  wire          rst,
    input  wire [11:0]   addr,
    input  wire          addr_v,
    output wire [1151:0] coef,
    output wire [11:0]   m_out,
    output wire          v_out,
    output wire          ok_out
);
    g24_cu u (.aclk(clk), .aresetn(~rst), .addr(addr), .addr_v(addr_v), .coef(coef), .m_out(m_out), .v_out(v_out), .ok_out(ok_out),
        .s_axi_awaddr(10'd0), .s_axi_awvalid(1'b0), .s_axi_awready(), .s_axi_wdata(32'd0), .s_axi_wvalid(1'b0), .s_axi_wready(),
        .s_axi_bresp(), .s_axi_bvalid(), .s_axi_bready(1'b1),
        .s_axi_araddr(10'd0), .s_axi_arvalid(1'b0), .s_axi_arready(), .s_axi_rdata(), .s_axi_rresp(), .s_axi_rvalid(), .s_axi_rready(1'b1));

    initial begin
        #1 $readmemh(`WORDS, u.u_ram.mem);
`ifndef TB_CU_NOOK
        @(negedge u.rst);                   // g24_cu の中の 3 段の後
        @(posedge clk); #0.1 u.ok = 1'b1;
`ifdef TB_CU_DROP
        repeat (`TB_CU_DROP) @(posedge clk);
        #0.1 u.ok = 1'b0;
`ifdef TB_CU_BACK
        repeat (`TB_CU_BACK) @(posedge clk);
        #0.1 u.ok = 1'b1;
`endif
`endif
`endif
    end
endmodule
