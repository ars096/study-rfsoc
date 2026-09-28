# SPDX-License-Identifier: BSD-3-Clause
# proj012 のブロックデザインの図 docs/block_design.svg を作る。`cd docs && python3 block_design.py`。build.tcl の配線を変えたらここも直す
W, H = 1440, 1110
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
  <!-- proj012 のブロックデザイン（build.tcl が組む配線）。手描き（生成スクリプトで描いた）。build.tcl を変えたらここも直す -->
  <defs>
    <marker id="aB" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#2f6fb5"/></marker>
    <marker id="aO" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#d9822b"/></marker>
    <marker id="aG" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#2e8b57"/></marker>
    <marker id="aK" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#555"/></marker>
    <marker id="aP" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#8a4fb0"/></marker>
    <style>
      .blk  {{ fill:#f8f8f8; stroke:#333; stroke-width:1.5; }}
      .sub  {{ fill:#ffffff; stroke:#2e8b57; stroke-width:1.2; }}
      .ext  {{ fill:#eeeeee; stroke:#777; stroke-width:1.2; stroke-dasharray:4 3; }}
      .note {{ fill:#fbf7ec; stroke:#b39a5a; stroke-width:1.2; }}
      .t    {{ font-size:14px; font-weight:bold; fill:#111; }}
      .tm   {{ font-size:12.5px; font-weight:bold; fill:#111; }}
      .s    {{ font-size:11.5px; fill:#333; }}
      .xs   {{ font-size:10.5px; fill:#555; }}
      .wB   {{ stroke:#2f6fb5; stroke-width:2.0; fill:none; marker-end:url(#aB); }}
      .wO   {{ stroke:#d9822b; stroke-width:2.6; fill:none; marker-end:url(#aO); }}
      .wG   {{ stroke:#2e8b57; stroke-width:2.6; fill:none; marker-end:url(#aG); }}
      .wK   {{ stroke:#555; stroke-width:1.6; fill:none; marker-end:url(#aK); }}
      .wP   {{ stroke:#8a4fb0; stroke-width:1.1; fill:none; stroke-dasharray:4 3; marker-end:url(#aP); }}
      .lb   {{ font-size:11px; fill:#333; }}
      .lbB  {{ font-size:11px; fill:#2f6fb5; }}
      .lbO  {{ font-size:11px; fill:#b8661a; }}
      .lbG  {{ font-size:11px; fill:#236b43; }}
      .lbP  {{ font-size:10.5px; fill:#6d3a8e; }}
    </style>
  </defs>
  <rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>''')

t(20, 28, "proj012 ブロックデザイン（build.tcl の配線。1 本ずつは proj011 rev6 と同一）", style="font-size:17px;font-weight:bold;fill:#111")
t(20, 48, "ADC_A〜D の 4 本 → ch ごとのギアボックス（gb_adc・gb_up・gb_fifo・gb_gate・gb_dn）→ ch ごとの spec_core（8192 点 FFT → 電力 → 積分）→ AXI4-Lite → PS。"
          "セルの番号 i = 0..3 = ADC_A..D")

# ---------------- PS / SmartConnect ----------------
box(40, 70, 230, 120, style="stroke:#2f6fb5")
t(52, 92, "zynq_ultra_ps_e_0", "t"); t(52, 110, "PS（PYNQ / Linux）")
t(52, 128, "RUN は spec_core ごとに 4 回書く", "xs")
t(52, 143, "（開始のずれは DUMP_F0 に残る）", "xs")
t(262, 160, "M_AXI_HPM0_FPD ▶", "xs", "end"); t(262, 180, "pl_clk0 100 MHz / pl_resetn0 ▶", "xs", "end")

box(400, 70, 230, 120, style="stroke:#2f6fb5")
t(412, 92, "smc_ctrl", "t"); t(412, 110, "SmartConnect（NUM_MI 5）")
t(412, 127, "NUM_CLKS 2", "xs")
t(412, 142, "aclk = pl_clk0 / aclk1 = 256 MHz", "xs")
t(412, 157, "乗り換えを内部に持つ", "xs")
t(416, 180, "◀ S00", "xs")
t(624, 108, "M00 ▶", "xs", "end")
for k in range(4):
    t(624, 124 + 15 * k, f"M0{k+1} ▶", "xs", "end")
path("M270,156 L398,156", "wB"); t(282, 150, "AXI（制御）", "lbB")

# ---------------- lanes ----------------
labels = ["ADC_A", "ADC_B", "ADC_C", "ADC_D"]
tiles  = [(226, 2, "m22_axis", "vin2_23"), (226, 0, "m20_axis", "vin2_01"),
          (224, 2, "m02_axis", "vin0_23"), (224, 0, "m00_axis", "vin0_01")]
LT, LH = 310, 150          # 1 本目の上端・1 本あたりの高さ
RX, RW = 200, 170          # rfdc
blocks = [("gb_adc", 400, 110, "O", ["出口の見張り", "書き込み側の再起動"]),
          ("gb_up", 532, 110, "O", ["幅の変換", "12 → 48 smp（×4）"]),
          ("gb_fifo", 664, 120, "F", ["非同期 FIFO", "768 bit × 32"]),
          ("gb_gate", 806, 110, "G", ["しきい値 K", "見張り（既定 K = 0）"]),
          ("gb_dn", 938, 110, "G", ["幅の変換", "48 → 16 smp（÷3）"])]
SX, SW = 1090, 280         # spec_core

# rfdc の箱
rtop, rbot = LT - 78, LT + 3 * LH + 120
box(RX, rtop, RW, rbot - rtop)
t(RX + 12, rtop + 22, "rfdc", "t"); t(RX + 12, rtop + 40, "RF Data Converter")
t(RX + 12, rtop + 58, "fs 4096 MSPS・ゾーン 2", "xs")
t(RX + 12, rtop + 73, "Real・デシメーション 1", "xs")
t(RX + 12, rtop + 88, "Data_Width 12", "xs")
# タイルの区切り
ymid = LT + 2 * LH - 15
a(f'<line x1="{RX}" y1="{ymid}" x2="{RX+RW}" y2="{ymid}" stroke="#999" stroke-dasharray="5 3"/>')
t(RX + 12, LT + 30, "Tile 226", "tm"); t(RX + 12, ymid + 26, "Tile 224", "tm")
t(RX + 12, ymid - 8, "clk_adc2 → MMCM（源）", "xs")
t(RX + 12, rbot - 10, "clk_adc0 は未接続", "xs")

# M00 → rfdc
path(f"M630,104 L660,104 L660,222 L{RX+85},222 L{RX+85},{rtop-2}", "wB")
t(668, 200, "M00 → rfdc/s_axi（pl_clk0）", "lbB")

# 右端の AXI の縦線（M01..M04 → spec_core_i）
for i in range(4):
    y = 120 + 15 * i
    xv = 1392 + 12 * i
    top = LT + i * LH
    path(f"M630,{y} L{xv},{y} L{xv},{top+22} L{SX+SW+2},{top+22}", "wB")
t(700, 116, "M01〜M04 → spec_core_0〜3/s_axi：AXI4-Lite・64 KiB × 4（重なりを build.tcl が照合）・aclk1 = 256 MHz", "lbB")

for i in range(4):
    top = LT + i * LH
    ry = top + 58            # データ線の高さ
    tl, sl, mport, vin = tiles[i]
    # 外部ポート
    box(20, ry - 22, 150, 44, "ext")
    t(30, ry - 4, f"{labels[i]}（SMA）"); t(30, ry + 13, "IF 2048〜4096 MHz", "xs")
    path(f"M170,{ry} L{RX-2},{ry}", "wK")
    t(RX + 8, ry + 26, f"{vin}", "xs")
    t(RX + RW - 6, ry - 6, f"{mport} ▶", "xs", "end")
    t(RX + RW - 6, ry + 10, f"slice {sl}", "xs", "end")
    # 行の見出し
    t(400, top + 14, f"ch {i} = {labels[i]}：Tile {tl} / slice {sl}", "tm")
    # rfdc → gb_adc
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
    # gb_dn → spec_core
    last = blocks[-1]
    path(f"M{last[1]+last[2]},{ry} L{SX-2},{ry}", "wG")
    if i == 0:
        t(640, top + 14, "語幅: RFDC 192 bit・341 MHz → gb_up 768 bit → gb_dn 256 bit・256 MHz（tready = 1）", "xs")
    # 見張りと再起動の線（ch_nets）: spec_core → gb_adc / gb_gate / gb_dn、状態は逆向き
    yc = by + bh + 14
    path(f"M{SX},{yc} L{blocks[0][1]+48},{yc} L{blocks[0][1]+48},{by+bh+2}", "wP")
    for x in (blocks[3][1] + 48, blocks[4][1] + 48):
        path(f"M{x},{yc} L{x},{by+bh+2}", "wP")
    # gb_fifo の残量 → gb_gate
    fx = blocks[2][1] + blocks[2][2]
    path(f"M{fx-20},{by+bh} L{fx-20},{by+bh+6} L{blocks[3][1]+14},{by+bh+6} L{blocks[3][1]+14},{by+bh+2}", "wP")
    if i == 0:
        t(blocks[0][1] + 56, yc + 13, "gb_hold・gb_adj（書き込み側の GRST）", "lbP")
        t(blocks[3][1] - 10, yc + 13, "gb_k・gb_dn_rstn / 状態は gb_stat・adc_stat で戻る", "lbP")
        t(blocks[2][1] + 4, by + bh + 20, "rd_count", "lbP")
    # spec_core
    box(SX, top + 6, SW, 110, style="stroke:#2e8b57;stroke-width:2.2")
    t(SX + 12, top + 26, f"spec_core_{i}（{labels[i]}）", "t")
    t(SX + 12, top + 44, "8192 点 FFT（lane_fft × 16）→ 電力 → 積分", "s")
    t(SX + 12, top + 60, "4096 ch × 0.5 MHz・既定 100 ms・二面", "xs")
    t(SX + 12, top + 75, "起動の見張り・FLAGS・GRST・自動のやり直し", "xs")
    t(SX + 12, top + 90, f"BUILD_TAG 0x6080000{i}（[23] 4ch・[1:0] ch = {i}）", "xs")
    t(SX + 12, top + 105, "ID 0x0012_02CC（4 個とも同じ。rev2）", "xs")
    t(SX + SW - 6, top + 26, "s_axi ◀", "xs", "end")

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
t(rx0 + 175, cy + 22, "rst_adc", "t"); t(rx0 + 175, cy + 42, "タイルごとのビット（rev2）", "xs")
box(rx0 + 360, cy, 180, 56, style="stroke:#2e8b57")
t(rx0 + 370, cy + 22, "rst_dsp", "t"); t(rx0 + 370, cy + 42, "spec_core_0〜3・smc aclk1", "xs")
t(rx0, cy + 78, "3 つとも ext_reset_in = pl_resetn0。ADC・DSP 側は MMCM の locked まで保持。", "xs")
t(rx0, cy + 110, "rev2: rst_adc の出口をタイルごとの別ビットから配る（t2 → Tile 226、t0 → Tile 224）。", "xs")
t(rx0, cy + 94, "ギアボックスは ch ごとに spec_core_i の GRST でも落ちる（ch i の GRST は ch i だけ）。", "xs")

# 外部のクロック
box(20, cy, 150, 44, "ext"); t(30, cy + 18, "LMX2594"); t(30, cy + 35, "491.52 MHz（両タイル）", "xs")
box(20, cy + 56, 150, 44, "ext"); t(30, cy + 74, "SYSREF（LMK04828）"); t(30, cy + 91, "7.68 MHz → sysref_in", "xs")
path(f"M170,{cy+22} L184,{cy+22} L184,{rbot-40} L{RX-2},{rbot-40}", "wK")
path(f"M170,{cy+78} L192,{cy+78} L192,{rbot-24} L{RX-2},{rbot-24}", "wK")

# 結線の照合
nx0 = 1012
box(nx0, cy, 408, 120, "note")
t(nx0 + 12, cy + 20, "結線の照合（build.tcl → build/net_check.rpt）", "tm")
t(nx0 + 12, cy + 40, "ch ごとの線は 1 つの表（ch_nets / ch_intf）から張り、照合も同じ表を読む", "xs")
t(nx0 + 12, cy + 56, "(1) 在るべき相手が同じネットにいる", "xs")
t(nx0 + 12, cy + 71, "(2) 同じネットに他の ch のセル（gb_*_j・spec_core_j）がいない", "xs")
t(nx0 + 12, cy + 86, "照合器の陽性対照 2 通り（わざと誤った期待で落ちること）を毎回確かめる", "xs")
t(nx0 + 12, cy + 106, "予言: DSP 1920（480 × 4）・BRAM 316 タイル・lane_fft 64 個", "xs")

# 凡例
ly = H - 22
t(20, ly, "凡例", "tm")
for k, (cls, lab, lc) in enumerate([("wB", "PS 側（pl_clk0）・AXI", "lbB"), ("wO", "ADC ドメイン 341.333 MHz", "lbO"),
                                    ("wG", "DSP ドメイン 256 MHz", "lbG"), ("wP", "見張り・再起動（ch ごとに閉じる）", "lbP"),
                                    ("wK", "アナログ・クロック", "lb")]):
    x = 70 + k * 260
    path(f"M{x},{ly-4} L{x+40},{ly-4}", cls)
    t(x + 48, ly, lab, lc)

a("</svg>")
open("block_design.svg", "w", encoding="utf-8").write("\n".join(o) + "\n")
print("ok")
