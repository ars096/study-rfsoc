// proj032 D-3 — hp_tg の sim。AXI4 の書きの口の模型（awready・wready を P_RDY % で、B は wlast から 20〜80 クロック後）
//   T1 速い口（P_RDY 100）・RATE 0.5・連続: 全拍の番地とデータが式どおり、拍の数 ≒ RATE × CYC、溜めの最大は小さい（≦ 2 バースト ＋ 余り）
//   T2 ダンプの山の形（ON 4096・PERIOD 16384・RATE 0.75）・口は P_RDY 50（≒ 0.5 拍 / クロック）: 溜めの最大 ≒ ON·(0.75 − 0.5) ＝ 1024 拍（± 25 %）
//   T3 天井（RATE 65536・ON 0）・P_RDY 50: 拍 / CYC ≒ 0.5、FLAGS[2] は立たない（溜めは 2^30 に届かない長さ）
//   陽性対照（-DPOSCTL）: 模型が 1 拍ごとにデータの 1 bit を化けさせる → 照合の不一致が数えられる
`timescale 1ns / 1ps
`default_nettype none
module tb_hp_tg;
    reg clk = 0, aresetn = 0;
    always #2 clk = ~clk;
    reg  [7:0]  awaddr, araddr;
    reg         awvalid = 0, wvalid = 0, arvalid = 0, bready = 1, rready = 1;
    reg  [31:0] wdata;
    wire        awready, wready, bvalid, arready, rvalid;
    wire [1:0]  bresp, rresp;
    wire [31:0] rdata;
    wire [5:0]  m_awid, m_arid;
    wire [48:0] m_awaddr, m_araddr;
    wire [7:0]  m_awlen, m_arlen;
    wire [2:0]  m_awsize, m_arsize, m_awprot, m_arprot;
    wire [1:0]  m_awburst, m_arburst;
    wire        m_awlock, m_arlock, m_awvalid, m_wlast, m_wvalid, m_bready, m_arvalid, m_rready;
    wire [3:0]  m_awcache, m_arcache, m_awqos, m_arqos;
    wire [127:0] m_wdata;
    wire [15:0] m_wstrb;
    reg         m_awready = 0, m_wready = 0, m_bvalid = 0;
    hp_tg dut (.clk(clk), .aresetn(aresetn),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready), .s_axi_wdata(wdata), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bvalid(bvalid), .s_axi_bresp(bresp), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready), .s_axi_rdata(rdata), .s_axi_rvalid(rvalid), .s_axi_rresp(rresp), .s_axi_rready(rready),
        .m_axi_awid(m_awid), .m_axi_awaddr(m_awaddr), .m_axi_awlen(m_awlen), .m_axi_awsize(m_awsize), .m_axi_awburst(m_awburst), .m_axi_awlock(m_awlock),
        .m_axi_awcache(m_awcache), .m_axi_awprot(m_awprot), .m_axi_awqos(m_awqos), .m_axi_awvalid(m_awvalid), .m_axi_awready(m_awready),
        .m_axi_wdata(m_wdata), .m_axi_wstrb(m_wstrb), .m_axi_wlast(m_wlast), .m_axi_wvalid(m_wvalid), .m_axi_wready(m_wready),
        .m_axi_bid(6'd0), .m_axi_bresp(2'b00), .m_axi_bvalid(m_bvalid), .m_axi_bready(m_bready),
        .m_axi_arid(m_arid), .m_axi_araddr(m_araddr), .m_axi_arlen(m_arlen), .m_axi_arsize(m_arsize), .m_axi_arburst(m_arburst), .m_axi_arlock(m_arlock),
        .m_axi_arcache(m_arcache), .m_axi_arprot(m_arprot), .m_axi_arqos(m_arqos), .m_axi_arvalid(m_arvalid), .m_axi_arready(1'b1),
        .m_axi_rid(6'd0), .m_axi_rdata(128'd0), .m_axi_rresp(2'b00), .m_axi_rlast(1'b0), .m_axi_rvalid(1'b0), .m_axi_rready(m_rready));

    task wr(input [7:0] a, input [31:0] d);
        begin
            @(negedge clk); awaddr = a; wdata = d; awvalid = 1; wvalid = 1;
            @(posedge clk); while (awready !== 1'b1) @(posedge clk);
            @(negedge clk); awvalid = 0; wvalid = 0;
            while (bvalid !== 1'b1) @(posedge clk);
            @(posedge clk);
        end
    endtask
    reg [31:0] rd_v;
    task rd(input [7:0] a);
        begin
            @(negedge clk); araddr = a; arvalid = 1;
            @(posedge clk); while (arready !== 1'b1) @(posedge clk);
            @(negedge clk); arvalid = 0;
            while (rvalid !== 1'b1) @(posedge clk);
            rd_v = rdata;
            @(posedge clk);
        end
    endtask

    // ---- 口の模型 ----
    integer p_rdy = 100;
    reg [48:0] awq [0:255];
    integer awn = 0, awh = 0, wc = 0, nbeat = 0, nbad = 0, nadr = 0;
    reg [48:0] exp_aw;
    integer bq [0:63];
    integer bn = 0, j;
    reg [31:0] x;
    reg [127:0] e;
    reg [48:0] base = 49'h0_1234_5000;
    reg [31:0] size = 32'h0002_0000, seed = 32'hA5C3_0F1E;
    always @(posedge clk) begin
        m_awready <= (({$random} % 100) < p_rdy);
        m_wready  <= (({$random} % 100) < p_rdy);
        if (m_awvalid && m_awready) begin
            if (m_awaddr != exp_aw) begin nadr = nadr + 1; if (nadr < 4) $display("AW の番地 %h（期待 %h）", m_awaddr, exp_aw); end
            if (m_awlen != dut.r_bl || m_awsize != 3'd4 || m_awburst != 2'b01) nadr = nadr + 1;
            if ((m_awaddr[11:0] + (m_awlen + 1) * 16) > 4096) nadr = nadr + 1;     // 4 KiB を越えない
            awq[awn % 256] = m_awaddr; awn = awn + 1;
            exp_aw = (exp_aw + (m_awlen + 1) * 16 >= base + size) ? base : exp_aw + (m_awlen + 1) * 16;
        end
        if (m_wvalid && m_wready) begin
            x = (awq[awh % 256][35:4] + wc) ^ seed;
            e = {~(x ^ 32'h0303_0303), x ^ 32'h0202_0202, x ^ 32'h0101_0101, x};
`ifdef POSCTL
            e[nbeat % 128] = ~e[nbeat % 128];
`endif
            if (m_wdata !== e || m_wstrb !== 16'hFFFF) begin nbad = nbad + 1; if (nbad < 4) $display("W の不一致: 拍 %0d", nbeat); end
            if (m_wlast !== (wc == m_awlen)) nbad = nbad + 1;
            nbeat = nbeat + 1;
            if (m_wlast) begin wc = 0; awh = awh + 1; bq[bn] = 20 + {$random} % 61; bn = bn + 1; end
            else wc = wc + 1;
        end
        m_bvalid <= 0;
        if (bn > 0) begin
            if (bq[0] <= 0) begin m_bvalid <= 1; for (j = 0; j < 63; j = j + 1) bq[j] = bq[j + 1]; bn = bn - 1; end
            for (j = 0; j < bn; j = j + 1) bq[j] = bq[j] - 1;
        end
    end

    integer fails = 0;
    reg [63:0] cyc, wb;
    reg [31:0] blm, fl, lat;
    task run(input [31:0] bl, input [31:0] rate, input [31:0] dur, input [31:0] on, input [31:0] per);
        begin
            wr(8'h08, bl); wr(8'h0C, rate); wr(8'h10, base[31:0]); wr(8'h14, {15'd0, base[48:32]}); wr(8'h18, size);
            wr(8'h1C, seed); wr(8'h20, dur); wr(8'h24, on); wr(8'h28, per); wr(8'h2C, 8);
            exp_aw = base;
            wr(8'h04, 1);
            rd(8'h40); while (!rd_v[3]) rd(8'h40);
            rd(8'h48); cyc[31:0] = rd_v; rd(8'h4C); cyc[63:32] = rd_v;
            rd(8'h50); wb[31:0] = rd_v;  rd(8'h54); wb[63:32] = rd_v;
            rd(8'h68); blm = rd_v; rd(8'h44); fl = rd_v; rd(8'h70); lat = rd_v;
            wr(8'h04, 0);
            repeat (200) @(posedge clk);
        end
    endtask

    initial begin
        repeat (10) @(posedge clk); aresetn = 1; repeat (10) @(posedge clk);
        rd(8'h00);
        if (rd_v != 32'h0320_0D31) begin fails = fails + 1; $display("ID %h", rd_v); end
        // T1
        p_rdy = 100;
        run(15, 32768, 60000, 0, 0);
        $display("T1: CYC %0d・拍 %0d（%.3f / クロック）・溜めの最大 %0d 拍・B の待ち最大 %0d・FLAGS %0d", cyc, wb, wb * 1.0 / cyc, blm, lat, fl);
        if (wb * 1.0 / cyc < 0.49 || wb * 1.0 / cyc > 0.51 || blm > 40 || fl != 0) begin fails = fails + 1; $display("  T1 ×"); end
        // T2
        p_rdy = 50;
        run(15, 49152, 120000, 4096, 16384);
        $display("T2: CYC %0d・拍 %0d・溜めの最大 %0d 拍（予言 ≒ 1024）・FLAGS %0d", cyc, wb, blm, fl);
        if (blm < 768 || blm > 1280 || fl != 0) begin fails = fails + 1; $display("  T2 ×"); end
        // T3
        run(63, 65536, 40000, 0, 0);
        $display("T3: CYC %0d・拍 %0d（%.3f / クロック）・FLAGS %0d", cyc, wb, wb * 1.0 / cyc, fl);
        if (wb * 1.0 / cyc < 0.45 || wb * 1.0 / cyc > 0.55 || fl[1]) begin fails = fails + 1; $display("  T3 ×"); end
        $display("拍の照合: 拍 %0d・データの不一致 %0d・AW の不一致 %0d", nbeat, nbad, nadr);
        if (nbad != 0 || nadr != 0) fails = fails + 1;
`ifdef POSCTL
        if (nbad > 0) $display("結果: 陽性対照は落ちた（期待どおり）");
        else $display("結果: 陽性対照が落ちなかった ×");
`else
        if (fails == 0) $display("結果: 全部通過");
        else $display("結果: 不合格");
`endif
        $finish;
    end
endmodule
`default_nettype wire
