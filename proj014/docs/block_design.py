# SPDX-License-Identifier: BSD-3-Clause
# proj014 のブロックデザインの図 docs/block_design.svg を作る。`cd docs && python3 block_design.py`。build.tcl の配線を変えたらここも直す
# 土台は proj013 の docs/block_design.py。足したもの: ADC_B の gb_bc_1（axis_broadcaster）と、その下の win_core_0 の帯、smc の M05
W, H = 1620, 1335
o = []
def a(s): o.append(s)
def box(x, y, w, h, cls="blk", style=""):
    a(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}"' + (f' style="{style}"' if style else '') + '/>')
def t(x, y, s, cls="s", anchor=None, style=""):
    an = f' text-anchor="{anchor}"' if anchor else ''
    st = f' style="{style}"' if style else ''
    a(f'<text x="{x}" y="{y}" class="{cls}"{an}{st}>{s}</text>')
def path(d, cls):
    a(f'<path class="{cls}" d="{d}"/>')

a(f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     font-family="'Hiragino Sans','Noto Sans CJK JP','Yu Gothic',sans-serif">
  <!-- SPDX-License-Identifier: BSD-3-Clause -->
  <!-- proj014 のブロックデザイン（build.tcl が組む配線）。docs/block_design.py で描いた。build.tcl を変えたらここも直す -->
  <defs>
    <marker id="aB" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#2f6fb5"/></marker>
    <marker id="aO" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#d9822b"/></marker>
    <marker id="aG" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#2e8b57"/></marker>
    <marker id="aK" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#555"/></marker>
    <marker id="aP" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#8a4fb0"/></marker>
    <marker id="aR" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#c0392b"/></marker>
    <style>
      .blk  {{ fill:#f8f8f8; stroke:#333; stroke-width:1.5; }}
      .sub  {{ fill:#ffffff; stroke:#2e8b57; stroke-width:1.2; }}
      .win  {{ fill:#fdf1f0; stroke:#c0392b; stroke-width:2.2; }}
      .wsub {{ fill:#ffffff; stroke:#c0392b; stroke-width:1.2; }}
      .ext  {{ fill:#eeeeee; stroke:#777; stroke-width:1.2; stroke-dasharray:4 3; }}
      .note {{ fill:#fbf7ec; stroke:#b39a5a; stroke-width:1.2; }}
      .t    {{ font-size:14px; font-weight:bold; fill:#111; }}
      .tm   {{ font-size:12.5px; font-weight:bold; fill:#111; }}
      .s    {{ font-size:11.5px; fill:#333; }}
      .xs   {{ font-size:10.5px; fill:#555; }}
      .wB   {{ stroke:#2f6fb5; stroke-width:2.0; fill:none; marker-end:url(#aB); }}
      .wO   {{ stroke:#d9822b; stroke-width:2.6; fill:none; marker-end:url(#aO); }}
      .wG   {{ stroke:#2e8b57; stroke-width:2.6; fill:none; marker-end:url(#aG); }}
      .wR   {{ stroke:#c0392b; stroke-width:2.6; fill:none; marker-end:url(#aR); }}
      .wK   {{ stroke:#555; stroke-width:1.6; fill:none; marker-end:url(#aK); }}
      .wP   {{ stroke:#8a4fb0; stroke-width:1.1; fill:none; stroke-dasharray:4 3; marker-end:url(#aP); }}
      .lb   {{ font-size:11px; fill:#333; }}
      .lbB  {{ font-size:11px; fill:#2f6fb5; }}
      .lbO  {{ font-size:11px; fill:#b8661a; }}
      .lbG  {{ font-size:11px; fill:#236b43; }}
      .lbR  {{ font-size:11px; fill:#a93226; }}
      .lbP  {{ font-size:10.5px; fill:#6d3a8e; }}
    </style>
  </defs>
  <rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>''')

t(20, 28, "proj014 ブロックデザイン（build.tcl の配線。proj013 rev1 の 4 本に、ADC_B の窓 1 つの分光計 win_core_0 を足したもの）", style="font-size:17px;font-weight:bold;fill:#111")
t(20, 48, "ADC_A〜D の 4 本 → ch ごとのギアボックス → ch ごとの spec_core（全帯域 4096 ch、中に tp_core）→ AXI4-Lite → PS。"
          "ADC_B だけ gb_dn_1 の出口を gb_bc_1 で 2 本に分け、同じ流れを win_core_0（窓）にも入れる。セルの番号 i = 0..3 = ADC_A..D")

# ---------------- PS / SmartConnect ----------------
box(40, 70, 230, 125, style="stroke:#2f6fb5")
t(52, 92, "zynq_ultra_ps_e_0", "t"); t(52, 110, "PS（PYNQ / Linux）")
t(52, 128, "spectrometer.py（spec_core × 4）", "xs")
t(52, 143, "window.py（win_core_0 ＋ spec_core_1）", "xs")
t(262, 165, "M_AXI_HPM0_FPD ▶", "xs", "end"); t(262, 185, "pl_clk0 100 MHz / pl_resetn0 ▶", "xs", "end")

box(400, 70, 230, 125, style="stroke:#2f6fb5")
t(412, 92, "smc_ctrl", "t"); t(412, 110, "SmartConnect（NUM_MI 6）")
t(412, 127, "NUM_CLKS 2", "xs")
t(412, 142, "aclk = pl_clk0 / aclk1 = 256 MHz", "xs")
t(412, 157, "乗り換えを内部に持つ", "xs")
t(416, 186, "◀ S00", "xs")
t(624, 104, "M00 ▶", "xs", "end")
for k in range(5):
    t(624, 119 + 15 * k, f"M0{k+1} ▶", "xs", "end")
path("M270,161 L398,161", "wB"); t(282, 155, "AXI（制御）", "lbB")

# ---------------- 行の位置 ----------------
labels = ["ADC_A", "ADC_B", "ADC_C", "ADC_D"]
tiles  = [(226, 2, "m22_axis", "vin2_23"), (226, 0, "m20_axis", "vin2_01"),
          (224, 2, "m02_axis", "vin0_23"), (224, 0, "m00_axis", "vin0_01")]
LH = 150
WB_T, WB_H = 612, 196                      # win_core_0 の帯（ADC_B の行のすぐ下）
tops = [310, 460, WB_T + WB_H + 12, WB_T + WB_H + 12 + LH]
RX, RW = 200, 170          # rfdc
blocks = [("gb_adc", 400, 110, "O", ["出口の見張り", "書き込み側の再起動"]),
          ("gb_up", 532, 110, "O", ["幅の変換", "12 → 48 smp（×4）"]),
          ("gb_fifo", 664, 120, "F", ["非同期 FIFO", "768 bit × 32"]),
          ("gb_gate", 806, 110, "G", ["しきい値 K", "見張り（既定 K = 2）"]),
          ("gb_dn", 938, 110, "G", ["幅の変換", "48 → 16 smp（÷3）"])]
BCX, BCW = 1080, 118       # gb_bc_1
SX, SW = 1236, 280         # spec_core

# rfdc の箱
rtop, rbot = tops[0] - 78, tops[3] + 120
box(RX, rtop, RW, rbot - rtop)
t(RX + 12, rtop + 22, "rfdc", "t"); t(RX + 12, rtop + 40, "RF Data Converter")
t(RX + 12, rtop + 58, "fs 4096 MSPS・ゾーン 2", "xs")
t(RX + 12, rtop + 73, "Real・デシメーション 1", "xs")
t(RX + 12, rtop + 88, "Data_Width 12", "xs")
ymid = tops[2] - 15
a(f'<line x1="{RX}" y1="{ymid}" x2="{RX+RW}" y2="{ymid}" stroke="#999" stroke-dasharray="5 3"/>')
t(RX + 12, tops[0] + 30, "Tile 226", "tm"); t(RX + 12, ymid + 26, "Tile 224", "tm")
t(RX + 12, ymid - 8, "clk_adc2 → MMCM（源）", "xs")
t(RX + 12, rbot - 10, "clk_adc0 は未接続", "xs")

# M00 → rfdc
path(f"M630,100 L660,100 L660,222 L{RX+85},222 L{RX+85},{rtop-2}", "wB")
t(668, 212, "M00 → rfdc/s_axi（pl_clk0）", "lbB")

# 右端の AXI の縦線（M01..M04 → spec_core_i、M05 → win_core_0）
XV0 = SX + SW + 26
for i in range(4):
    y = 115 + 15 * i
    xv = XV0 + 12 * i
    top = tops[i]
    path(f"M630,{y} L{xv},{y} L{xv},{top+22} L{SX+SW+2},{top+22}", "wB")
yw = 115 + 15 * 4
xvw = XV0 + 12 * 4
t(700, 111, "M01〜M04 → spec_core_0〜3/s_axi：AXI4-Lite・64 KiB × 4 ／ M05 → win_core_0/s_axi：128 KiB（重なりと揃いを build.tcl が照合）・aclk1 = 256 MHz", "lbB")

for i in range(4):
    top = tops[i]
    ry = top + 58
    tl, sl, mport, vin = tiles[i]
    box(20, ry - 22, 150, 44, "ext")
    t(30, ry - 4, f"{labels[i]}（SMA）"); t(30, ry + 13, "IF 2048〜4096 MHz", "xs")
    path(f"M170,{ry} L{RX-2},{ry}", "wK")
    t(RX + 8, ry + 26, f"{vin}", "xs")
    t(RX + RW - 6, ry - 6, f"{mport} ▶", "xs", "end")
    t(RX + RW - 6, ry + 10, f"slice {sl}", "xs", "end")
    t(400, top + 14, f"ch {i} = {labels[i]}：Tile {tl} / slice {sl}" + ("（窓の ch）" if i == 1 else ""), "tm")
    path(f"M{RX+RW},{ry} L{blocks[0][1]-2},{ry}", "wO")
    by = top + 30
    bh = 56
    for j, (nm, x, w, dom, lines) in enumerate(blocks):
        col = {"O": "#d9822b", "G": "#2e8b57", "F": "#333"}[dom]
        box(x, by, w, bh, style=f"stroke:{col}")
        if dom == "F":
            a(f'<line x1="{x}" y1="{by}" x2="{x}" y2="{by+bh}" stroke="#d9822b" stroke-width="5"/>')
            a(f'<line x1="{x+w}" y1="{by}" x2="{x+w}" y2="{by+bh}" stroke="#2e8b57" stroke-width="5"/>')
        t(x + 8, by + 18, f"{nm}_{i}", "tm")
        t(x + 8, by + 33, lines[0], "xs"); t(x + 8, by + 47, lines[1], "xs")
        if j + 1 < len(blocks):
            nx = blocks[j + 1][1]
            cls = "wO" if dom == "O" else "wG"
            path(f"M{x+w},{ry} L{nx-2},{ry}", cls)
    last = blocks[-1]
    if i == 1:
        # gb_dn_1 → gb_bc_1 → {spec_core_1, win_core_0}
        path(f"M{last[1]+last[2]},{ry} L{BCX-2},{ry}", "wG")
        box(BCX, by, BCW, bh, style="stroke:#c0392b;stroke-width:1.8")
        t(BCX + 8, by + 18, "gb_bc_1", "tm")
        t(BCX + 8, by + 33, "axis_broadcaster", "xs"); t(BCX + 8, by + 47, "NUM_MI 2・256 bit", "xs")
        path(f"M{BCX+BCW},{ry} L{SX-2},{ry}", "wG")
        t(BCX + BCW + 4, ry - 6, "M00", "xs")
        path(f"M{BCX+60},{by+bh} L{BCX+60},{WB_T-2}", "wR")
        t(BCX + 54, by + bh + 34, "M01 → win_core_0/s_axis", "lbR", "end")
    else:
        path(f"M{last[1]+last[2]},{ry} L{SX-2},{ry}", "wG")
    if i == 0:
        t(640, top + 14, "語幅: RFDC 192 bit・341 MHz → gb_up 768 bit → gb_dn 256 bit・256 MHz（tready = 1）", "xs")
    yc = by + bh + 14
    path(f"M{SX},{yc} L{blocks[0][1]+48},{yc} L{blocks[0][1]+48},{by+bh+2}", "wP")
    for x in (blocks[3][1] + 48, blocks[4][1] + 48):
        path(f"M{x},{yc} L{x},{by+bh+2}", "wP")
    fx = blocks[2][1] + blocks[2][2]
    path(f"M{fx-20},{by+bh} L{fx-20},{by+bh+6} L{blocks[3][1]+14},{by+bh+6} L{blocks[3][1]+14},{by+bh+2}", "wP")
    if i == 0:
        t(blocks[0][1] + 56, yc + 13, "gb_hold・gb_adj（書き込み側の GRST）", "lbP")
        t(blocks[3][1] - 10, yc + 13, "gb_k・gb_dn_rstn / 状態は gb_stat・adc_stat で戻る", "lbP")
        t(blocks[2][1] + 4, by + bh + 20, "rd_count", "lbP")
    if i == 1:
        t(blocks[0][1] + 56, yc + 13, "ADC_B のギアボックスの制御も spec_core_1 のまま（win_core_0 は流れを受けるだけ）", "lbP")
    box(SX, top + 4, SW, 140, style="stroke:#2e8b57;stroke-width:2.2")
    t(SX + 12, top + 22, f"spec_core_{i}（{labels[i]}）", "t")
    t(SX + 12, top + 39, "8192 点 FFT（lane_fft × 16）→ 電力 → 積分", "s")
    t(SX + 12, top + 54, "4096 ch × 0.5 MHz・既定 100 ms・二面", "xs")
    t(SX + 12, top + 68, "起動の見張り・FLAGS・GRST・自動のやり直し", "xs")
    t(SX + 12, top + 82, f"BUILD_TAG 0x6080000{i}・ID 0x0014_01CC（4 個同じ）", "xs")
    path(f"M{SX+5},{ry} L{SX+5},{top+104} L{SX+9},{top+104}", "wG")
    box(SX + 10, top + 88, SW - 18, 52, "sub")
    t(SX + 18, top + 103, "tp_core（u_tp）total power", "tm")
    t(SX + 18, top + 118, "Σx²（x = ADC >>> 2）・500 フレーム = 1 ms・F0 揃え", "xs")
    t(SX + 18, top + 132, "リング 512 × 16 B（0x2000〜）・reg 0x100〜0x118", "xs")
    t(SX + SW - 6, top + 26, "s_axi ◀", "xs", "end")

# ---------------- win_core_0 の帯 ----------------
WX0, WX1 = 392, SX + SW
box(WX0, WB_T, WX1 - WX0, WB_H, "win")
path(f"M{xvw},{yw} L{xvw},{WB_T+22} L{WX1+2},{WB_T+22}", "wB")
t(WX1 - 6, WB_T + 26, "s_axi ◀", "xs", "end")
# 入口: gb_bc_1 の M01 を帯の上辺の内側に沿って左へ回し、pfb_core の左に入れる
yin = WB_T + 14
path(f"M{BCX+60},{WB_T} L{BCX+60},{yin} L{WX0+14},{yin} L{WX0+14},{WB_T+100} L{WX0+24},{WB_T+100}", "wR")
t(WX0 + 24, WB_T + 34, "win_core_0（窓 1 つの分光計・bit ③ の最初の形）　ID 0x0014_0200（rev2）・BUILD_TAG 0x60C00001（[22] 窓・ch 1）・DSP 390", "t")
t(WX0 + 24, WB_T + 52, "窓の設定 WK・WDPHI・WNS は CTRL[12] = WRST で取り込み、pfb・ddc・wspec を最初から。全部 DSP ドメイン 256 MHz", "xs")

sy, sh = WB_T + 64, 112
subs = [("pfb_core（u_pfb）", 420, 250, ["粗い PFB の 1 ch（k = WK、0..16）", "128 MHz 間隔・M 32・4 倍オーバーサンプリング",
                                           "96 タップ（等リプル・18 bit）・32 点 実 DFT", "出力 y 複素 24 bit・512 MSPS / ch", "DSP 264"]),
        ("ddc_core（u_ddc）", 706, 250, ["NCO: 位相 32 bit・表 2^14（1/4 波 × 18 bit）", "窓の中心へ（d = c − 128·WK）",
                                           "半帯域 ÷2 × WNS 段（軽い 15 タップ × (WNS−1)", "＋ 最後の 67 タップ）→ 幅 W = 512 / 2^WNS", "出力 z 複素 18 bit・W MSPS・DSP 94"]),
        ("wspec_core（u_ws）", 992, 300, ["溜め 2 面 × 4096（rev2: IP の tready を守る）", "→ win_fft（複素 4096 点・realtime・unscaled）",
                                            "→ 電力 sat18(Y >>> SHIFT)² → 64 bit 積分（二面・URAM）", "スナップショット 4096 語・SEQ（seqlock）", "FLAGS・WS_STALL 0x80・WS_RDY0 0x84・DSP 30"])]
for j, (nm, x, w, lines) in enumerate(subs):
    box(x, sy, w, sh, "wsub")
    t(x + 8, sy + 17, nm, "tm")
    for k, ln in enumerate(lines):
        t(x + 8, sy + 34 + 15 * k, ln, "xs")
    if j + 1 < len(subs):
        path(f"M{x+w},{sy+sh//2} L{subs[j+1][1]-2},{sy+sh//2}", "wR")
t(subs[0][1] + subs[0][2] + 2, sy + sh // 2 - 6, "y", "lbR")
t(subs[1][1] + subs[1][2] + 2, sy + sh // 2 - 6, "z", "lbR")
t(1300, sy + 17, "AXI 128 KiB:", "tm")
t(1300, sy + 34, "0x00000 レジスタ", "xs")
t(1300, sy + 49, "0x08000 スナップショット", "xs")
t(1300, sy + 64, "0x10000 スペクトル（4096 ch × 64 bit）", "xs")
t(1300, sy + 84, "ch b ↔ ν = b·W/4096（b ≧ 2048 は負）", "xs")
t(1300, sy + 99, "IF = 4096 − c − ν（並べ替えは PS）", "xs")

# ---------------- クロックとリセット ----------------
cy = rbot + 40
path(f"M{RX+85},{rbot} L{RX+85},{cy-2}", "wK")
t(RX + 92, rbot + 24, "clk_adc2 256 MHz（fs/16）", "lb")
box(RX, cy, 230, 120)
t(RX + 12, cy + 22, "clk_wiz_adc（MMCM・1 個を共有）", "t")
t(RX + 12, cy + 40, "入力 256 MHz（clk_adc2）", "xs")
t(RX + 12, cy + 60, "clk_out1 341.333 MHz → ADC ドメイン", "lbO")
t(RX + 12, cy + 77, "clk_out2 256.000 MHz → DSP ドメイン", "lbG")
t(RX + 12, cy + 95, "両タイルの m*_axis_aclk に clk_out1", "xs")
t(RX + 12, cy + 110, "4 : 3 は同じ MMCM から出るので厳密", "xs")

rx0 = RX + 260
box(rx0, cy, 150, 56, style="stroke:#2f6fb5")
t(rx0 + 10, cy + 22, "rst_ctrl", "t"); t(rx0 + 10, cy + 42, "pl_clk0：smc・rfdc 制御", "xs")
box(rx0 + 165, cy, 180, 56, style="stroke:#d9822b")
t(rx0 + 175, cy + 22, "rst_adc", "t"); t(rx0 + 175, cy + 42, "タイルごとのビット", "xs")
box(rx0 + 360, cy, 260, 56, style="stroke:#2e8b57")
t(rx0 + 370, cy + 22, "rst_dsp", "t"); t(rx0 + 370, cy + 42, "spec_core_0〜3・win_core_0・gb_bc_1・smc", "xs")
t(rx0, cy + 78, "3 つとも ext_reset_in = pl_resetn0。ADC・DSP 側は MMCM の locked まで保持。", "xs")
t(rx0, cy + 94, "ギアボックスは ch ごとに spec_core_i の GRST でも落ちる（ch i の GRST は ch i だけ）。", "xs")
t(rx0, cy + 110, "rst_adc の出口はタイルごとの別ビット（t2 → Tile 226、t0 → Tile 224）。", "xs")

box(20, cy, 150, 44, "ext"); t(30, cy + 18, "LMX2594"); t(30, cy + 35, "491.52 MHz（両タイル）", "xs")
box(20, cy + 56, 150, 44, "ext"); t(30, cy + 74, "SYSREF（LMK04828）"); t(30, cy + 91, "7.68 MHz → sysref_in", "xs")
box(20, cy + 112, 150, 44, "ext"); t(30, cy + 130, "10 MHz（CLKin0）"); t(30, cy + 147, "LMK の PLL1 へ（--clkin 0）", "xs")
path(f"M170,{cy+22} L184,{cy+22} L184,{rbot-40} L{RX-2},{rbot-40}", "wK")
path(f"M170,{cy+78} L192,{cy+78} L192,{rbot-24} L{RX-2},{rbot-24}", "wK")

nx0 = 1100
box(nx0, cy, 480, 140, "note")
t(nx0 + 12, cy + 20, "結線の照合と資源（build.tcl → build/net_check.rpt・vivado.log）", "tm")
t(nx0 + 12, cy + 40, "ch ごとの線は 1 つの表（ch_nets / ch_intf）から張り、照合も同じ表を読む", "xs")
t(nx0 + 12, cy + 56, "(1) 在るべき相手が同じネットにいる (2) 他の ch のセルがいない", "xs")
t(nx0 + 12, cy + 71, "ch 1 は gb_dn_1 → gb_bc_1 → {spec_core_1, win_core_0} の 3 本（82 行・問題 0）", "xs")
t(nx0 + 12, cy + 91, "rev1 の結果（-2）: DSP 2406（spec_core 504 × 4 ＋ win_core 390）", "xs")
t(nx0 + 12, cy + 106, "BRAM 359 ＋ URAM 2（積分）・LUT 198,726・FF 373,229", "xs")
t(nx0 + 12, cy + 121, "WNS +0.065 ns（-2）/ +0.086 ns（-1）。rev2 は wspec_core の握手と見張りだけ", "xs")

ly = H - 22
t(20, ly, "凡例", "tm")
for k, (cls, lab, lc) in enumerate([("wB", "PS 側（pl_clk0）・AXI", "lbB"), ("wO", "ADC ドメイン 341.333 MHz", "lbO"),
                                    ("wG", "DSP ドメイン 256 MHz", "lbG"), ("wR", "窓の流れ（DSP ドメイン）", "lbR"),
                                    ("wP", "見張り・再起動（ch ごとに閉じる）", "lbP"), ("wK", "アナログ・クロック", "lb")]):
    x = 70 + k * 250
    path(f"M{x},{ly-4} L{x+40},{ly-4}", cls)
    t(x + 48, ly, lab, lc)

a("</svg>")
open("block_design.svg", "w", encoding="utf-8").write("\n".join(o) + "\n")
print("ok")
