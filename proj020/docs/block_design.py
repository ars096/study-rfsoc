# SPDX-License-Identifier: BSD-3-Clause
# proj020 のブロックデザインの図 docs/block_design.svg を作る（proj017 の図から、wspec の PFB・ID・M・資源を描き直した）。`cd docs && python3 block_design.py`。build.tcl の配線を変えたらここも直す
# 土台は proj015（4 ADC の行）と proj016（time_core_0・PPS・時刻のバス）の docs/block_design.py。proj017: 4 ADC × win_core_i（NW 2）、
#   smc の M00 rfdc・M01〜M04 win_core_0〜3・M05 spec_core_0・M06 time_core_0。時刻のバスは time_core_0 → win_core_0〜3・spec_core_0
W, H = 1870, 1560
o = []
def a(s): o.append(s)
def box(x, y, w, h, cls="blk", style=""):
    a(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}"' + (f' style="{style}"' if style else '') + '/>')
def t(x, y, s, cls="s", anchor=None, style=""):
    an = f' text-anchor="{anchor}"' if anchor else ''
    st = f' style="{style}"' if style else ''
    s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    a(f'<text x="{x}" y="{y}" class="{cls}"{an}{st}>{s}</text>')
def path(d, cls):
    a(f'<path class="{cls}" d="{d}"/>')

a(f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"
     font-family="'Hiragino Sans','Noto Sans CJK JP','Yu Gothic',sans-serif">
  <!-- SPDX-License-Identifier: BSD-3-Clause -->
  <!-- proj020 のブロックデザイン（build.tcl が組む配線。配線は proj017 と同じ）。docs/block_design.py で描いた。build.tcl を変えたらここも直す -->
  <defs>
    <marker id="aB" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#2f6fb5"/></marker>
    <marker id="aO" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#d9822b"/></marker>
    <marker id="aG" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#2e8b57"/></marker>
    <marker id="aK" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#555"/></marker>
    <marker id="aP" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#8a4fb0"/></marker>
    <marker id="aR" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#c0392b"/></marker>
    <marker id="aT" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#0f7c8c"/></marker>
    <style>
      .blk  {{ fill:#f8f8f8; stroke:#333; stroke-width:1.5; }}
      .sub  {{ fill:#ffffff; stroke:#2e8b57; stroke-width:1.2; }}
      .win  {{ fill:#fdf1f0; stroke:#c0392b; stroke-width:2.2; }}
      .wsub {{ fill:#ffffff; stroke:#c0392b; stroke-width:1.2; }}
      .tim  {{ fill:#eef8f9; stroke:#0f7c8c; stroke-width:2.2; }}
      .tsub {{ fill:#ffffff; stroke:#0f7c8c; stroke-width:1.2; }}
      .ext  {{ fill:#eeeeee; stroke:#777; stroke-width:1.2; stroke-dasharray:4 3; }}
      .note {{ fill:#fbf7ec; stroke:#b39a5a; stroke-width:1.2; }}
      .t    {{ font-size:14px; font-weight:bold; fill:#111; }}
      .tm   {{ font-size:12.5px; font-weight:bold; fill:#111; }}
      .s    {{ font-size:11.5px; fill:#333; }}
      .xs   {{ font-size:10.5px; fill:#555; }}
      .xt   {{ font-size:10.5px; fill:#0b5d69; }}
      .wB   {{ stroke:#2f6fb5; stroke-width:2.0; fill:none; marker-end:url(#aB); }}
      .wO   {{ stroke:#d9822b; stroke-width:2.6; fill:none; marker-end:url(#aO); }}
      .wG   {{ stroke:#2e8b57; stroke-width:2.6; fill:none; marker-end:url(#aG); }}
      .wR   {{ stroke:#c0392b; stroke-width:2.6; fill:none; marker-end:url(#aR); }}
      .wK   {{ stroke:#555; stroke-width:1.6; fill:none; marker-end:url(#aK); }}
      .wP   {{ stroke:#8a4fb0; stroke-width:1.1; fill:none; stroke-dasharray:4 3; marker-end:url(#aP); }}
      .wT   {{ stroke:#0f7c8c; stroke-width:2.4; fill:none; marker-end:url(#aT); }}
      .lb   {{ font-size:11px; fill:#333; }}
      .lbB  {{ font-size:11px; fill:#2f6fb5; }}
      .lbO  {{ font-size:11px; fill:#b8661a; }}
      .lbG  {{ font-size:11px; fill:#236b43; }}
      .lbR  {{ font-size:11px; fill:#a93226; }}
      .lbP  {{ font-size:10.5px; fill:#6d3a8e; }}
      .lbT  {{ font-size:11px; fill:#0b5d69; }}
    </style>
  </defs>
  <rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>''')


t(20, 28, "proj020 ブロックデザイン（build.tcl の配線、SAM45-Fine rev2、ID 0x0020_0100）: 4 ADC × 窓 2 ＋ total power × 4 ＋ 全帯域 1 本 ＋ 時刻（time_core・1PPS）", style="font-size:17px;font-weight:bold;fill:#111")
t(20, 48, "配線は proj017 と同じ。proj020 で変えたもの: wspec の溜めと FFT の間に PFB（T = 4、sinc × Kaiser β 5・bw 1.198）・溜めを 5 面のリング（URAM）・FLAGS[5]・ID 0x0020。`-1` は Performance_Explore で WNS +0.047 ns（DSP 2600・BRAM 305・URAM 56）")

# ---------------- PS / SmartConnect ----------------
box(40, 70, 250, 125, style="stroke:#2f6fb5")
t(52, 92, "zynq_ultra_ps_e_0", "t"); t(52, 110, "PS（PYNQ / Linux）・-1 ＋ ps_preset.tcl")
t(52, 128, "fine.py（F-4）・timetest.py・timebase.py・specd.py", "xs")
t(52, 143, "window.py（win_core_i）・s45resp.py・s45lin.py", "xs")
t(282, 165, "M_AXI_HPM0_FPD ▶", "xs", "end"); t(282, 185, "pl_clk0 100 MHz / pl_resetn0 ▶", "xs", "end")
box(420, 70, 240, 125, style="stroke:#2f6fb5")
t(432, 92, "smc_ctrl", "t"); t(432, 110, "SmartConnect（NUM_MI 7）")
t(432, 127, "NUM_CLKS 2", "xs")
t(432, 142, "aclk = pl_clk0 / aclk1 = 256 MHz", "xs")
t(436, 186, "◀ S00", "xs")
for k in range(7):
    t(654, 92 + 14 * k, f"M0{k} ▶", "xs", "end")
path("M290,161 L418,161", "wB"); t(302, 155, "AXI（制御）", "lbB")

# ---------------- time_core_0 ----------------
TX, TY, TW, TH = 1010, 66, 710, 160
box(TX, TY, TW, TH, "tim")
t(TX + 12, TY + 20, "time_core_0　DSP ドメイン 256 MHz・BUILD_TAG 0x50900000・ID 0x0020_7101（中身は proj017 と同じ）", "tm")
t(TX + TW - 8, TY + TH - 6, "s_axi ◀ M06", "xs", "end")
cols = [("T（64 bit）", ["1 ビート = 3.906 ns", "1 s = 256,000,000", "aresetn でだけ 0 に", "t_out = T ＋ 1 を出す", "（コアで 1 段 → T）"]),
        ("PPS（TRIG・COMP）", ["同期器 3 段", "スタンプ・間隔・数", "グリッチ（< 0.5 s）", "欠落（1.5 s）", "BAD（|間隔 − 1 s| > TOL）"]),
        ("予約発火", ["START_AT = G の倍数", "（G = 524,288 ビート）", "go_loc は T = START_AT", "コアは START_AT + 1 に", "RUN・WRST・TP_RUN"]),
        ("原点", ["ANCHORED（PS が 1 に）", "リセットで 0", "EPOCH: ctrl_aclk 側で", "数え gray で渡す", "（CDC-6 の 1 件）"])]
cx = TX + 10
for nm, lines in cols:
    box(cx, TY + 30, 165, 112, "tsub")
    t(cx + 8, TY + 46, nm, "tm")
    for k, ln in enumerate(lines):
        t(cx + 8, TY + 62 + 15 * k, ln, "xt")
    cx += 175
box(760, 84, 200, 40, "ext"); t(770, 100, "pps_trig（AH13）"); t(770, 116, "IRIG_TRIG_OUT・シュミット", "xs")
box(760, 134, 200, 40, "ext"); t(770, 150, "pps_comp（AJ13）"); t(770, 166, "IRIG_COMP_OUT・オープンドレイン", "xs")
path(f"M960,104 L{TX-2},104", "wK"); path(f"M960,154 L{TX-2},154", "wK")
box(760, 184, 200, 34, "ext"); t(770, 205, "PPS Clk（SMA）← 45m の 1PPS", "xs")
path("M860,184 L860,176", "wK")

# ---------------- 行 ----------------
labels = ["ADC_A", "ADC_B", "ADC_C", "ADC_D"]
tiles  = [(226, 2, "m22_axis", "vin2_23"), (226, 0, "m20_axis", "vin2_01"),
          (224, 2, "m02_axis", "vin0_23"), (224, 0, "m00_axis", "vin0_01")]
Mns = ["124.7", "124.9", "122.1", "121.9"]
LH = 190
tops = [330 + LH * i for i in range(4)]
RX, RW = 200, 170
blocks = [("gb_adc", 396, 98, "O", ["出口の見張り", "書き込み側の再起動"]),
          ("gb_up", 506, 98, "O", ["幅の変換", "12 → 48 smp（×4）"]),
          ("gb_fifo", 616, 108, "F", ["非同期 FIFO", "768 bit × 32"]),
          ("gb_gate", 736, 98, "G", ["しきい値 K", "見張り（既定 K = 2）"]),
          ("gb_dn", 846, 98, "G", ["幅の変換", "48 → 16 smp（÷3）"])]
BCX, BCW = 956, 106
WX, WW = 1110, 610
XS0 = BCX + BCW + 8

rtop, rbot = tops[0] - 40, tops[3] + 160
box(RX, rtop, RW, rbot - rtop)
t(RX + 12, rtop + 22, "rfdc", "t"); t(RX + 12, rtop + 40, "RF Data Converter")
t(RX + 12, rtop + 58, "fs 4096 MSPS・ゾーン 2", "xs")
t(RX + 12, rtop + 73, "Real・Data_Width 12", "xs")
ymid = tops[2] - 12
a(f'<line x1="{RX}" y1="{ymid}" x2="{RX+RW}" y2="{ymid}" stroke="#999" stroke-dasharray="5 3"/>')
t(RX + 12, tops[0] + 120, "Tile 226", "tm"); t(RX + 12, ymid + 26, "Tile 224", "tm")
t(RX + 12, tops[0] + 136, "M ≒ 32.0 ビート", "xt"); t(RX + 12, ymid + 42, "M ≒ 31.2 ビート", "xt")
t(RX + 12, ymid - 8, "clk_adc2 → MMCM（源）", "xs")

# AXI: M00 → rfdc、M01〜M04 → win_core_i、M05 → spec_core_0、M06 → time_core_0（time_core の箱を避けて下を通す）
path(f"M660,92 L680,92 L680,262 L{RX+85},262 L{RX+85},{rtop-2}", "wB")
t(RX + 92, 256, "M00 → rfdc/s_axi（pl_clk0）", "lbB")
XV0 = WX + WW + 20
for i in range(4):
    y = 106 + 14 * i
    xa = 690 + 8 * i
    yh = 236 + 8 * i
    xv = XV0 + 10 * i
    path(f"M660,{y} L{xa},{y} L{xa},{yh} L{xv},{yh} L{xv},{tops[i]+20} L{WX+WW+2},{tops[i]+20}", "wB")
t(990, 290, "M01〜M04 → win_core_0〜3（1 MiB × 4）／ M05 → spec_core_0（64 KiB）／ M06 → time_core_0（4 KiB）", "lbB")
path(f"M660,176 L746,176 L746,{TY+TH+18} L{TX+40},{TY+TH+18} L{TX+40},{TY+TH+2}", "wB")

# 時刻のバス（t_out・go_out・ev_out）: time_core の右辺から右端の縦線へ降り、win_core_0〜3・spec_core_0 の右辺へ
xtb = 1835
t(1100, 316, "時刻のバス t_out（64）・go_out・ev_out（4）→ 右端の縦線から win_core_0〜3・spec_core_0 へ（各コアで 1 段、t_loc = T）", "lbT")
t(396, 316, "語幅: 192 bit・341 MHz → 768 bit → 256 bit・256 MHz", "xs")

for i in range(4):
    top = tops[i]
    ry = top + 58
    tl, sl, mport, vin = tiles[i]
    box(20, ry - 22, 150, 44, "ext")
    t(30, ry - 4, f"{labels[i]}（SMA）"); t(30, ry + 13, "IF 2048〜4096 MHz", "xs")
    path(f"M170,{ry} L{RX-2},{ry}", "wK")
    t(RX + RW - 6, ry - 6, f"{mport} ▶", "xs", "end")
    t(RX + RW - 6, ry + 10, f"slice {sl}", "xs", "end")
    t(396, top + 14, f"ch {i} = {labels[i]}：Tile {tl} / slice {sl}　M = {Mns[i]} ns", "tm")
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
    yc = by + bh + 14
    path(f"M{WX},{yc} L{blocks[0][1]+48},{yc} L{blocks[0][1]+48},{by+bh+2}", "wP")
    for x in (blocks[3][1] + 48, blocks[4][1] + 48):
        path(f"M{x},{yc} L{x},{by+bh+2}", "wP")
    if i == 0:
        t(blocks[0][1] + 56, yc + 13, "gb_hold・gb_adj／gb_k・gb_dn_rstn ← win_core_i ／ gb_stat・adc_stat → win_core_i と full_sel", "lbP")

    # ---- win_core_i（NW 2）----
    wy, wh = top + 2, LH - 14
    box(WX, wy, WW, wh, "win")
    t(WX + 10, wy + 17, f"win_core_{i}（{labels[i]}）　NW 2・BUILD_TAG 0x50C0000{i}・DSP 524・URAM 14", "tm")
    t(WX + WW - 6, wy + 17, "s_axi ◀", "xs", "end")
    path(f"M{xtb},{wy+42} L{WX+WW+2},{wy+42}", "wT")
    py = wy + 28
    box(WX + 10, py, 128, wh - 38, "wsub")
    t(WX + 16, py + 15, "pfb_core（共有）", "tm")
    for k, ln in enumerate(["粗い PFB・M 32", "128 MHz 間隔・4 倍", "窓ごとに ch k を", "選んで 2 本へ", "DSP 272", "（256 ＋ 8 × NW）"]):
        t(WX + 16, py + 31 + 14 * k, ln, "xs")
    path(f"M{WX+2},{ry} L{WX+8},{ry}", "wR")
    wx2, ww2, rh = WX + 150, 290, 62
    for w in range(2):
        yy = py + w * (rh + 8)
        box(wx2, yy, ww2, rh, "wsub")
        t(wx2 + 6, yy + 13, f"窓 {w}: ddc（NS 1..8）→ PFB T = 4 → wspec（4096 点）", "xs")
        t(wx2 + 6, yy + 26, "72 ＋ 42 DSP・溜め 5 面（URAM）・FIFO 16", "xs")
        box(wx2 + 6, yy + 32, ww2 - 12, 26, "tsub")
        t(wx2 + 10, yy + 44, "F0 = (⌊fin / M⌋ + 2)·M・N_ACC = 40.96 ms / L", "xt")
        t(wx2 + 10, yy + 55, "dstamp（DUMP_T・H）・ARM・CFG_ID・FLAGS[5]", "xt")
        path(f"M{WX+138},{py+(wh-38)//2} L{WX+144},{py+(wh-38)//2} L{WX+144},{yy+rh//2} L{wx2-2},{yy+rh//2}", "wR")
    rx2 = wx2 + ww2 + 10
    rw2 = WX + WW - 10 - rx2
    box(rx2, py, rw2, 56, "sub")
    t(rx2 + 6, py + 14, "tp_core（total power）", "xs")
    t(rx2 + 6, py + 28, "Σx²・512 フレーム = 1.024 ms", "xs")
    t(rx2 + 6, py + 42, "FLAGS[4] 振り切れ", "xt")
    box(rx2, py + 62, rw2, 46, "tsub")
    t(rx2 + 6, py + 76, "adc_ev: 振り切れ・途切れ", "xt")
    t(rx2 + 6, py + 90, "TANCH（ADC のフレーム, T）", "xt")
    t(rx2 + 6, py + 104, "スナップショット 1 つ（PFB の出口）", "xs")
    t(rx2, py + 124, "窓 w 0x20000·w／共通 0x80000", "xs")

# ---------------- full_sel → spec_core_0 ----------------
fy = tops[3] + LH + 40
fx0, fw = XS0 - 30, 150
box(fx0, fy, fw, 90, style="stroke:#2e8b57;stroke-width:1.8")
t(XS0 - 6, fy - 10, "gb_bc_0〜3 の M01 →", "xs", "end")
t(fx0 + 8, fy + 18, "full_sel", "tm"); t(fx0 + 8, fy + 34, "axis_sel4（4 → 1）", "xs")
t(fx0 + 8, fy + 49, "sel ← win_core_0", "xs"); t(fx0 + 8, fy + 64, "（FULL_SEL）", "xs")
t(fx0 + 8, fy + 79, "選択 bit を複製", "xt")
SPX, SPW = fx0 + fw + 40, WX + WW - (fx0 + fw + 40)
path(f"M{fx0+fw},{fy+45} L{SPX-2},{fy+45}", "wG")
box(SPX, fy, SPW, 160, style="stroke:#2e8b57;stroke-width:2.2")
t(SPX + 12, fy + 20, "spec_core_0（全帯域 1 本・試験用）DSP 504", "t")
t(SPX + 12, fy + 38, "8192 点 FFT（lane_fft × 16）→ 電力 → 積分：4096 ch × 0.5 MHz・40.96 ms = 20480 フレーム", "xs")
box(SPX + 10, fy + 48, 200, 40, "sub")
t(SPX + 18, fy + 64, "tp_core（u_tp）", "tm"); t(SPX + 18, fy + 80, "Σx²・1.024 ms・FLAGS[4]", "xs")
box(SPX + 220, fy + 48, SPW - 230, 40, "tsub")
t(SPX + 228, fy + 64, "dstamp・adc_ev・ARM_RUN・CFG_ID", "xt")
t(SPX + 228, fy + 80, "F0 = fin + 2（格子に寄せない）・k·N·512", "xt")
t(SPX + 12, fy + 108, "用途: F-2 の閉ループ（ADC ごとの M）・W-6・W-1b・F-5 の基準。FULL_SEL で ADC を選び SRST", "xs")
t(SPX + SPW - 8, fy + 150, "ID 0x0020_01CC・BUILD_TAG 0x50A00000・s_axi ◀ M05", "xs", "end")
xv5 = XV0 + 40
path(f"M660,162 L722,162 L722,276 L{xv5},276 L{xv5},{fy+146} L{SPX+SPW+2},{fy+146}", "wB")
# 時刻のバスの縦線（右端）と spec_core_0 への枝
path(f"M{TX+TW},{TY+60} L{xtb},{TY+60} L{xtb},{fy+128} L{SPX+SPW+2},{fy+128}", "wT")
t(SPX + SPW - 8, fy + 124, "t_in・go_in・tev_in ◀", "xt", "end")

# ---------------- クロックとリセット ----------------
cy = fy + 195
path(f"M{RX+85},{rbot} L{RX+85},{cy-2}", "wK")
t(RX + 92, rbot + 24, "clk_adc2 256 MHz（fs/16）", "lb")
box(RX, cy, 230, 120)
t(RX + 12, cy + 22, "clk_wiz_adc（MMCM・共有）", "t")
t(RX + 12, cy + 40, "入力 256 MHz（clk_adc2）", "xs")
t(RX + 12, cy + 60, "clk_out1 341.333 MHz → ADC ドメイン", "lbO")
t(RX + 12, cy + 77, "clk_out2 256.000 MHz → DSP ドメイン", "lbG")
t(RX + 12, cy + 95, "time_core の T はこのクロックを数える", "xt")
t(RX + 12, cy + 110, "（10 MHz に乗っていれば 1 s = 256e6）", "xt")
rx0 = RX + 250
box(rx0, cy, 150, 56, style="stroke:#2f6fb5")
t(rx0 + 10, cy + 22, "rst_ctrl", "t"); t(rx0 + 10, cy + 42, "smc・rfdc・time の ctrl", "xs")
box(rx0 + 160, cy, 170, 56, style="stroke:#d9822b")
t(rx0 + 170, cy + 22, "rst_adc", "t"); t(rx0 + 170, cy + 42, "→ rst_adc_t2 / t0（タイル）", "xs")
box(rx0 + 340, cy, 320, 56, style="stroke:#2e8b57")
t(rx0 + 350, cy + 22, "rst_dsp", "t"); t(rx0 + 350, cy + 42, "win_core_0〜3・gb_bc・full_sel・spec_core_0・time_core_0", "xs")
t(rx0, cy + 78, "3 つとも ext_reset_in = pl_resetn0。ADC・DSP 側は MMCM の locked まで保持。", "xs")
t(rx0, cy + 94, "WSTART（窓の始まり）は ADC ごとの最初の valid なビートから数えるので、タイルで値が分かれる（区切りの揃いには効かない）。", "xt")
t(rx0, cy + 110, "窓は格子の START_AT の ARM_WRST で一斉に WRST、ARM_RUN で次の格子の点から RUN。", "xt")
box(20, cy, 150, 44, "ext"); t(30, cy + 18, "LMX2594"); t(30, cy + 35, "491.52 MHz（両タイル）", "xs")
box(20, cy + 56, 150, 44, "ext"); t(30, cy + 74, "SYSREF（LMK04828）"); t(30, cy + 91, "→ sysref_in", "xs")
box(20, cy + 112, 150, 44, "ext"); t(30, cy + 130, "10 MHz（CLKin0）"); t(30, cy + 147, "メーザー由来（--clkin 0）", "xs")
path(f"M170,{cy+22} L184,{cy+22} L184,{rbot-40} L{RX-2},{rbot-40}", "wK")
path(f"M170,{cy+78} L192,{cy+78} L192,{rbot-24} L{RX-2},{rbot-24}", "wK")

nx0 = rx0 + 680
box(nx0, cy, WX + WW - nx0, 170, "note")
t(nx0 + 12, cy + 20, "資源とタイミング（build/・-1 ＋ PS のプリセット・既定の戦略）", "tm")
t(nx0 + 12, cy + 40, "DSP 2520（59.0 %）= win_core 504 × 4 ＋ spec_core_0 504", "xs")
t(nx0 + 12, cy + 55, "　win_core 1 つ = pfb 272 ＋ (ddc 72 ＋ ws 32) × 2 ＋ tp 24", "xs")
t(nx0 + 12, cy + 70, "BRAM 337 タイル（31.2 %）・URAM 16・LUT 47.3 %・FF 37.6 %", "xs")
t(nx0 + 12, cy + 88, "WNS +0.038 ns / WHS +0.010 ns", "xs")
t(nx0 + 12, cy + 103, "CDC-6 5 件: gb_adc の gaps × 4・EPOCH の gray × 1", "xs")
t(nx0 + 12, cy + 118, "結線の照合 105 行・問題 0・陽性対照 (a)〜(d) が落ちる", "xs")
t(nx0 + 12, cy + 136, "実機: 40.96 ms × 44,000 回で読み落とし 0、8 窓の区切りは", "xt")
t(nx0 + 12, cy + 151, "　X(NS) を除いて ±1 ビート（4 ADC・2 タイルをまたいで）", "xt")

ly = H - 18
t(20, ly, "凡例", "tm")
for k, (cls, lab, lc) in enumerate([("wB", "PS 側（pl_clk0）・AXI", "lbB"), ("wO", "ADC ドメイン 341 MHz", "lbO"),
                                    ("wG", "DSP ドメイン 256 MHz", "lbG"), ("wR", "窓の流れ", "lbR"),
                                    ("wT", "時刻（DSP ドメイン）", "lbT"), ("wP", "見張り・再起動", "lbP"), ("wK", "アナログ・クロック・PPS", "lb")]):
    x = 70 + k * 245
    path(f"M{x},{ly-4} L{x+40},{ly-4}", cls)
    t(x + 48, ly, lab, lc)

a("</svg>")
open("block_design.svg", "w", encoding="utf-8").write("\n".join(o) + "\n")
print("ok")
