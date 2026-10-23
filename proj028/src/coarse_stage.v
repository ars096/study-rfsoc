// SPDX-License-Identifier: BSD-3-Clause
// proj028 C-2 — 荒い段: coarse_pfb（荒い PFB）→ cfft32（32 点の複素 FFT）→ coarse_post（Y・利得・8 bit・電力）
//   入力: ADC の 1 拍 16 サンプル（256 MHz）。出口: 1 ブロック（56 サンプル）に 1 語 512 bit = 32 ch × {im 8, re 8}
//   出口の回転 e^{−j2π(k+½)mD/M} は掛けない（細かい FFT の出口の bin の巡回で済む、M-1d）
`default_nettype none
module coarse_stage (
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF s_axi, ASSOCIATED_RESET aresetn" *)
    input  wire          clk,
    input  wire          aresetn,
    input  wire          s_valid,
    input  wire [255:0]  s_data,
    output wire          m_valid,
    output wire [511:0]  m_y,
    input  wire [11:0]   s_axi_awaddr,
    input  wire          s_axi_awvalid,
    output wire          s_axi_awready,
    input  wire [31:0]   s_axi_wdata,
    input  wire          s_axi_wvalid,
    output wire          s_axi_wready,
    output wire          s_axi_bvalid,
    output wire [1:0]    s_axi_bresp,
    input  wire          s_axi_bready,
    input  wire [11:0]   s_axi_araddr,
    input  wire          s_axi_arvalid,
    output wire          s_axi_arready,
    output wire [31:0]   s_axi_rdata,
    output wire          s_axi_rvalid,
    output wire [1:0]    s_axi_rresp,
    input  wire          s_axi_rready
);
    reg rst_q;
    always @(posedge clk) rst_q <= ~aresetn;
    wire zv, fv;
    wire [64*18-1:0] z;
    wire [32*2*24-1:0] f;
    coarse_pfb u_pfb (.clk(clk), .rst(rst_q), .s_valid(s_valid), .s_data(s_data), .m_valid(zv), .m_z(z));
    cfft32 u_fft (.clk(clk), .s_valid(zv), .s_z(z), .m_valid(fv), .m_f(f));
    coarse_post u_post (.clk(clk), .aresetn(aresetn), .s_valid(fv), .s_f(f), .m_valid(m_valid), .m_y(m_y),
        .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata), .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),
        .s_axi_bvalid(s_axi_bvalid), .s_axi_bresp(s_axi_bresp), .s_axi_bready(s_axi_bready),
        .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready),
        .s_axi_rdata(s_axi_rdata), .s_axi_rvalid(s_axi_rvalid), .s_axi_rresp(s_axi_rresp), .s_axi_rready(s_axi_rready));
endmodule
`default_nettype wire
