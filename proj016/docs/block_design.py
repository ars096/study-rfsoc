# SPDX-License-Identifier: BSD-3-Clause
# proj015 のブロックデザインの図 docs/block_design.svg を作る。`cd docs && python3 block_design.py`。build.tcl の配線を変えたらここも直す
# 土台は proj014 の docs/block_design.py。proj015: 4 ADC とも gb_bc_i → {win_core_i（NW 4）, full_sel} → spec_core_0 1 本、smc の M01〜M04 = win_core、M05 = spec_core_0
W, H = 1800, 1400
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
  <!-- proj015 のブロックデザイン（build.tcl が組む配線）。docs/block_design.py で描いた。build.tcl を変えたらここも直す -->
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

t(20, 28, "proj015 ブロックデザイン（build.tcl の配線、rev3 = ID 0x0015_0300）: 4 ADC × 4 窓（8 通りの幅 256〜2 MHz）＋ total power × 4 ＋ 全帯域 1 本（4 ADC から選ぶ）", style="font-size:17px;font-weight:bold;fill:#111")
t(20, 48, "ADC_A〜D の 4 本 → ch ごとのギアボックス → gb_bc_i で 2 本に分け、win_core_i（窓 4 つ・粗い PFB は共有・total power・スナップショット）と full_sel へ。"
          "full_sel が 1 本を選んで spec_core_0（全帯域 4096 ch）へ。セルの番号 i = 0..3 = ADC_A..D")

# ---------------- PS / SmartConnect ----------------
box(40, 70, 250, 125, style="stroke:#2f6fb5")
t(52, 92, "zynq_ultra_ps_e_0", "t"); t(52, 110, "PS（PYNQ / Linux）・-1 ＋ ps_preset.tcl")
t(52, 128, "window.py・win16.py・winsweep.py（win_core_i）", "xs")
t(52, 143, "spectrometer.py（spec_core_0 ＋ FULL_SEL）", "xs")
t(282, 165, "M_AXI_HPM0_FPD ▶", "xs", "end"); t(282, 185, "pl_clk0 100 MHz / pl_resetn0 ▶", "xs", "end")

box(420, 70, 240, 125, style="stroke:#2f6fb5")
t(432, 92, "smc_ctrl", "t"); t(432, 110, "SmartConnect（NUM_MI 6）")
t(432, 127, "NUM_CLKS 2", "xs")
t(432, 142, "aclk = pl_clk0 / aclk1 = 256 MHz", "xs")
t(432, 157, "乗り換えを内部に持つ", "xs")
t(436, 186, "◀ S00", "xs")
t(654, 104, "M00 ▶", "xs", "end")
for k in range(5):
    t(654, 119 + 15 * k, f"M0{k+1} ▶", "xs", "end")
path("M290,161 L418,161", "wB"); t(302, 155, "AXI（制御）", "lbB")

# ---------------- 行の位置 ----------------
labels = ["ADC_A", "ADC_B", "ADC_C", "ADC_D"]
tiles  = [(226, 2, "m22_axis", "vin2_23"), (226, 0, "m20_axis", "vin2_01"),
          (224, 2, "m02_axis", "vin0_23"), (224, 0, "m00_axis", "vin0_01")]
LH = 178
tops = [262 + LH * i for i in range(4)]
RX, RW = 200, 170          # rfdc
blocks = [("gb_adc", 396, 98, "O", ["出口の見張り", "書き込み側の再起動"]),
          ("gb_up", 506, 98, "O", ["幅の変換", "12 → 48 smp（×4）"]),
          ("gb_fifo", 616, 108, "F", ["非同期 FIFO", "768 bit × 32"]),
          ("gb_gate", 736, 98, "G", ["しきい値 K", "見張り（既定 K = 2）"]),
          ("gb_dn", 846, 98, "G", ["幅の変換", "48 → 16 smp（÷3）"])]
BCX, BCW = 956, 106        # gb_bc_i
WX, WW = 1110, 610         # win_core_i
XS0 = BCX + BCW + 8        # full_sel へ降りる縦線（ch ごとに 7 px ずらす）

# rfdc の箱
rtop, rbot = tops[0] - 40, tops[3] + 150
box(RX, rtop, RW, rbot - rtop)
t(RX + 12, rtop + 22, "rfdc", "t"); t(RX + 12, rtop + 40, "RF Data Converter")
t(RX + 12, rtop + 58, "fs 4096 MSPS・ゾーン 2", "xs")
t(RX + 12, rtop + 73, "Real・デシメーション 1", "xs")
t(RX + 12, rtop + 88, "Data_Width 12", "xs")
ymid = tops[2] - 12
a(f'<line x1="{RX}" y1="{ymid}" x2="{RX+RW}" y2="{ymid}" stroke="#999" stroke-dasharray="5 3"/>')
t(RX + 12, tops[0] + 112, "Tile 226", "tm"); t(RX + 12, ymid + 26, "Tile 224", "tm")
t(RX + 12, ymid - 8, "clk_adc2 → MMCM（源）", "xs")
t(RX + 12, rbot - 10, "clk_adc0 は未接続", "xs")

# M00 → rfdc
path(f"M660,100 L690,100 L690,222 L{RX+85},222 L{RX+85},{rtop-2}", "wB")
t(698, 212, "M00 → rfdc/s_axi（pl_clk0）", "lbB")

# 右端の AXI の縦線（M01..M04 → win_core_i、M05 → spec_core_0）
XV0 = WX + WW + 20
for i in range(4):
    y = 115 + 15 * i
    xv = XV0 + 10 * i
    path(f"M660,{y} L{xv},{y} L{xv},{tops[i]+20} L{WX+WW+2},{tops[i]+20}", "wB")
t(730, 111, "M01〜M04 → win_core_0〜3/s_axi：1 MiB × 4（20 bit 番地）／ M05 → spec_core_0/s_axi：64 KiB。重なりと揃いを build.tcl が照合・aclk1 = 256 MHz", "lbB")

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
    t(396, top + 14, f"ch {i} = {labels[i]}：Tile {tl} / slice {sl}", "tm")
    path(f"M{RX+RW},{ry} L{blocks[0][1]-2},{ry}", "wO")
    by, bh = top + 30, 56
    for j, (nm, x, w, dom, lines) in enumerate(blocks):
        col = {"O": "#d9822b", "G": "#2e8b57", "F": "#333"}[dom]
        box(x, by, w, bh, style=f"stroke:{col}")
        if dom == "F":
            a(f'<line x1="{x}" y1="{by}" x2="{x}" y2="{by+bh}" stroke="#d9822b" stroke-width="5"/>')
            a(f'<line x1="{x+w}" y1="{by}" x2="{x+w}" y2="{by+bh}" stroke="#2e8b57" stroke-width="5"/>')
        t(x + 8, by + 18, f"{nm}_{i}", "tm")
        t(x + 8, by + 33, lines[0], "xs"); t(x + 8, by + 47, lines[1], "xs")
        if j + 1 < len(blocks):
            path(f"M{x+w},{ry} L{blocks[j+1][1]-2},{ry}", "wO" if dom == "O" else "wG")
    last = blocks[-1]
    path(f"M{last[1]+last[2]},{ry} L{BCX-2},{ry}", "wG")
    box(BCX, by, BCW, bh, style="stroke:#c0392b;stroke-width:1.8")
    t(BCX + 8, by + 18, f"gb_bc_{i}", "tm")
    t(BCX + 8, by + 33, "axis_broadcaster", "xs"); t(BCX + 8, by + 47, "M00 窓・M01 選択", "xs")
    path(f"M{BCX+BCW},{ry} L{WX-2},{ry}", "wR")
    xs = XS0 + 7 * i
    path(f"M{BCX+BCW},{ry+14} L{xs},{ry+14} L{xs},{tops[3]+LH+38}", "wG")
    if i == 0:
        t(640, top + 14, "語幅: RFDC 192 bit・341 MHz → gb_up 768 bit → gb_dn 256 bit・256 MHz（tready = 1）", "xs")
    # 見張り（win_core_i が握る）
    yc = by + bh + 14
    path(f"M{WX},{yc} L{blocks[0][1]+48},{yc} L{blocks[0][1]+48},{by+bh+2}", "wP")
    for x in (blocks[3][1] + 48, blocks[4][1] + 48):
        path(f"M{x},{yc} L{x},{by+bh+2}", "wP")
    fx = blocks[2][1] + blocks[2][2]
    path(f"M{fx-20},{by+bh} L{fx-20},{by+bh+6} L{blocks[3][1]+14},{by+bh+6} L{blocks[3][1]+14},{by+bh+2}", "wP")
    if i == 0:
        t(blocks[0][1] + 56, yc + 13, "gb_hold・gb_adj（書き込み側）／ gb_k・gb_dn_rstn ← win_core_i ／ rd_count → gb_gate", "lbP")
        t(blocks[0][1] + 56, yc + 27, "gb_stat・adc_stat → win_core_i と full_sel（ギアボックスの制御は ch ごとに win_core_i）", "lbP")

    # ---- win_core_i ----
    wy, wh = top + 2, LH - 14
    box(WX, wy, WW, wh, "win")
    t(WX + 10, wy + 17, f"win_core_{i}（{labels[i]}）　NW 4・BUILD_TAG 0x50C0000{i}・DSP 728", "tm")
    t(WX + WW - 6, wy + 22, "s_axi ◀", "xs", "end")
    py = wy + 28
    box(WX + 10, py, 128, wh - 38, "wsub")
    t(WX + 16, py + 15, "pfb_core（共有）", "tm")
    for k, ln in enumerate(["粗い PFB・M 32", "128 MHz 間隔・4 倍", "96 タップ・実 DFT", "窓ごとに ch k を", "選んで 4 本へ・288"]):
        t(WX + 16, py + 31 + 14 * k, ln, "xs")
    path(f"M{WX+2},{ry} L{WX+8},{ry}", "wR")
    # 窓 4 つ
    wx2, ww2, rh = WX + 150, 270, 25
    for w in range(4):
        yy = py + w * (rh + 4)
        box(wx2, yy, ww2, rh, "wsub")
        t(wx2 + 6, yy + 11, f"窓 {w}: ddc（NCO・light ≦ 7 段・final）→ wspec", "xs")
        t(wx2 + 6, yy + 22, "4096 点 FFT → 電力 → 64 bit 積分（二面）　72 ＋ 32", "xs")
        path(f"M{WX+138},{py+(wh-38)//2} L{WX+146},{py+(wh-38)//2} L{WX+146},{yy+rh//2} L{wx2-2},{yy+rh//2}", "wR")
    # 右: total power・スナップショット・制御
    rx2 = wx2 + ww2 + 12
    box(rx2, py, WX + WW - 10 - rx2, 50, "sub")
    t(rx2 + 6, py + 15, "tp_core（total power）", "xs")
    t(rx2 + 6, py + 29, "Σx²・1 ms・リング", "xs")
    t(rx2 + 6, py + 43, "DSP 24", "xs")
    box(rx2, py + 56, WX + WW - 10 - rx2, 34, "wsub")
    t(rx2 + 6, py + 71, "スナップショット 1 つ", "xs"); t(rx2 + 6, py + 85, "SNAP_SEL の窓が書く", "xs")
    t(rx2, py + 104, "窓 w: 0x20000·w", "xs")
    t(rx2, py + 118, "共通: 0x80000〜", "xs")
    t(rx2, py + 132, "（GB_K・FULL_SEL・TP）", "xs")

# ---------------- full_sel → spec_core_0 ----------------
fy = tops[3] + LH + 40
fx0, fw = XS0 - 30, 150
box(fx0, fy, fw, 90, style="stroke:#2e8b57;stroke-width:1.8")
t(XS0 - 6, fy - 10, "gb_bc_0〜3 の M01 →", "xs", "end")
t(fx0 + 8, fy + 18, "full_sel", "tm"); t(fx0 + 8, fy + 34, "axis_sel4（4 → 1）", "xs")
t(fx0 + 8, fy + 49, "sel ← win_core_0", "xs"); t(fx0 + 8, fy + 64, "（FULL_SEL）・stat も", "xs")
t(fx0 + 8, fy + 79, "出口にレジスタ 1 段", "xs")
SPX, SPW = fx0 + fw + 40, WX + WW - (fx0 + fw + 40)
path(f"M{fx0+fw},{fy+45} L{SPX-2},{fy+45}", "wG")
box(SPX, fy, SPW, 150, style="stroke:#2e8b57;stroke-width:2.2")
t(SPX + 12, fy + 20, "spec_core_0（全帯域 1 本）　DSP 504", "t")
t(SPX + SPW - 8, fy + 20, "ID 0x0015_01CC・BUILD_TAG 0x50A00000", "xs", "end")
t(SPX + 12, fy + 38, "8192 点 FFT（lane_fft × 16）→ 電力 → 積分：4096 ch × 0.5 MHz・100 ms", "xs")
t(SPX + 12, fy + 53, "RTL は proj013 と同じ（ID の定数だけ）。gb_* の出口は未接続", "xs")
box(SPX + 10, fy + 64, SPW - 20, 40, "sub")
t(SPX + 18, fy + 80, "tp_core（u_tp）total power（中に 1 つ、DSP 24）", "tm")
t(SPX + 18, fy + 96, "Σx²（x = ADC >>> 2）・500 フレーム = 1 ms", "xs")
t(SPX + 12, fy + 122, "W-6・W-1b の基準: 窓と同じ ADC を FULL_SEL で選ぶ", "xs")
t(SPX + SPW - 8, fy + 140, "s_axi ◀ M05", "xs", "end")
xv5 = XV0 + 40
path(f"M660,{115+15*4} L{xv5},{115+15*4} L{xv5},{fy+136} L{SPX+SPW+2},{fy+136}", "wB")

# ---------------- クロックとリセット ----------------
cy = fy + 175
path(f"M{RX+85},{rbot} L{RX+85},{cy-2}", "wK")
t(RX + 92, rbot + 24, "clk_adc2 256 MHz（fs/16）", "lb")
box(RX, cy, 230, 120)
t(RX + 12, cy + 22, "clk_wiz_adc（MMCM・共有）", "t")
t(RX + 12, cy + 40, "入力 256 MHz（clk_adc2）", "xs")
t(RX + 12, cy + 60, "clk_out1 341.333 MHz → ADC ドメイン", "lbO")
t(RX + 12, cy + 77, "clk_out2 256.000 MHz → DSP ドメイン", "lbG")
t(RX + 12, cy + 95, "両タイルの m*_axis_aclk に clk_out1", "xs")
t(RX + 12, cy + 110, "4 : 3 は同じ MMCM から出るので厳密", "xs")
rx0 = RX + 250
box(rx0, cy, 140, 56, style="stroke:#2f6fb5")
t(rx0 + 10, cy + 22, "rst_ctrl", "t"); t(rx0 + 10, cy + 42, "pl_clk0：smc・rfdc", "xs")
box(rx0 + 150, cy, 170, 56, style="stroke:#d9822b")
t(rx0 + 160, cy + 22, "rst_adc", "t"); t(rx0 + 160, cy + 42, "→ rst_adc_t2 / t0（タイル）", "xs")
box(rx0 + 330, cy, 330, 56, style="stroke:#2e8b57")
t(rx0 + 340, cy + 22, "rst_dsp", "t"); t(rx0 + 340, cy + 42, "win_core_0〜3・gb_bc_0〜3・full_sel・spec_core_0・smc", "xs")
t(rx0, cy + 78, "3 つとも ext_reset_in = pl_resetn0。ADC・DSP 側は MMCM の locked まで保持。", "xs")
t(rx0, cy + 94, "ギアボックスの読み出し側は win_core_i の gb_dn_rstn（ch i だけ）。書き込み側は gb_adc_i の gb_rstn。", "xs")
t(rx0, cy + 110, "窓は CTRL[12] = WRST で窓ごとに最初から（粗い PFB の窓ごとの出口だけ打ち直す）。", "xs")
box(20, cy, 150, 44, "ext"); t(30, cy + 18, "LMX2594"); t(30, cy + 35, "491.52 MHz（両タイル）", "xs")
box(20, cy + 56, 150, 44, "ext"); t(30, cy + 74, "SYSREF（LMK04828）"); t(30, cy + 91, "7.68 MHz → sysref_in", "xs")
box(20, cy + 112, 150, 44, "ext"); t(30, cy + 130, "10 MHz（CLKin0）"); t(30, cy + 147, "メーザー由来（--clkin 0）", "xs")
path(f"M170,{cy+22} L184,{cy+22} L184,{rbot-40} L{RX-2},{rbot-40}", "wK")
path(f"M170,{cy+78} L192,{cy+78} L192,{rbot-24} L{RX-2},{rbot-24}", "wK")

nx0 = rx0 + 680
box(nx0, cy, WX + WW - nx0, 156, "note")
t(nx0 + 12, cy + 20, "資源とタイミング（rev3・build-PEPRPO/・-1 ＋ PS のプリセット）", "tm")
t(nx0 + 12, cy + 40, "DSP 3416（80.0 %）= win_core 728 × 4 ＋ spec_core_0 504", "xs")
t(nx0 + 12, cy + 55, "　win_core 1 つ = pfb 288 ＋ (ddc 72 ＋ ws 32) × 4 ＋ tp 24", "xs")
t(nx0 + 12, cy + 70, "BRAM 553（51.2 %）・URAM 32・LUT 69.0 %・FF 55.8 %", "xs")
t(nx0 + 12, cy + 88, "WNS 0.000 ns / WHS 0.000 ns（Performance_ExplorePostRoutePhysOpt）", "xs")
t(nx0 + 12, cy + 103, "　rev1 −0.767 → rev2 −0.199 → 戦略 −0.041 → rev3 0.000", "xs")
t(nx0 + 12, cy + 121, "結線の照合: ch ごとの表（ch_nets / ch_intf）と共有の表（shared_nets）", "xs")
t(nx0 + 12, cy + 136, "から張って同じ表で両側を照らす。spec_core_0 の gb_* は未接続を照合", "xs")

ly = H - 18
t(20, ly, "凡例", "tm")
for k, (cls, lab, lc) in enumerate([("wB", "PS 側（pl_clk0）・AXI", "lbB"), ("wO", "ADC ドメイン 341.333 MHz", "lbO"),
                                    ("wG", "DSP ドメイン 256 MHz", "lbG"), ("wR", "窓の流れ（DSP ドメイン）", "lbR"),
                                    ("wP", "見張り・再起動（ch ごとに閉じる）", "lbP"), ("wK", "アナログ・クロック", "lb")]):
    x = 70 + k * 260
    path(f"M{x},{ly-4} L{x+40},{ly-4}", cls)
    t(x + 48, ly, lab, lc)

a("</svg>")
open("block_design.svg", "w", encoding="utf-8").write("\n".join(o) + "\n")
print("ok")
