# SPDX-License-Identifier: BSD-3-Clause
# proj016 のブロックデザインの図 docs/block_design.svg を作る。`cd docs && python3 block_design.py`。build.tcl の配線を変えたらここも直す
# 土台は proj015 の docs/block_design.py。proj016: ADC_A の 1 本だけ（gb_bc_0 → {win_core_0（NW 4）, full_sel} → spec_core_0）、
#   time_core_0 を足した（smc の M03、PPS の 2 本、t_out・go_out・ev_out → win_core_0・spec_core_0）。smc の M00 rfdc・M01 win_core_0・M02 spec_core_0
W, H = 1820, 1010
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
  <!-- proj016 のブロックデザイン（build.tcl が組む配線）。docs/block_design.py で描いた。build.tcl を変えたらここも直す -->
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

t(20, 28, "proj016 ブロックデザイン（build.tcl の配線、ID 0x0016_0100）: ADC_A 1 本 × 窓 4 ＋ total power ＋ 全帯域 1 本 ＋ 時刻（time_core・1PPS）", style="font-size:17px;font-weight:bold;fill:#111")
t(20, 48, "proj015 の分光の中身は同じ（pfb・ddc・FFT は同一のファイル）。足したのは time_core_0 と、窓・全帯域ごとの dstamp（ダンプの開始のビートと健全性）・adc_ev（振り切れ・途切れ）・予約の受け口（ARM）。"
          "新しいものは青緑")

# ---------------- PS / SmartConnect ----------------
box(40, 70, 250, 125, style="stroke:#2f6fb5")
t(52, 92, "zynq_ultra_ps_e_0", "t"); t(52, 110, "PS（PYNQ / Linux）・-1 ＋ ps_preset.tcl")
t(52, 128, "timetest.py・timebase.py（時刻）", "xs")
t(52, 143, "window.py（win_core_0）・spectrometer.py", "xs")
t(282, 165, "M_AXI_HPM0_FPD ▶", "xs", "end"); t(282, 185, "pl_clk0 100 MHz / pl_resetn0 ▶", "xs", "end")

box(420, 70, 240, 125, style="stroke:#2f6fb5")
t(432, 92, "smc_ctrl", "t"); t(432, 110, "SmartConnect（NUM_MI 4）")
t(432, 127, "NUM_CLKS 2", "xs")
t(432, 142, "aclk = pl_clk0 / aclk1 = 256 MHz", "xs")
t(432, 157, "乗り換えを内部に持つ", "xs")
t(436, 186, "◀ S00", "xs")
for k, nm in enumerate(["M00 ▶", "M01 ▶", "M02 ▶", "M03 ▶"]):
    t(654, 104 + 15 * k, nm, "xs", "end")
path("M290,161 L418,161", "wB"); t(302, 155, "AXI（制御）", "lbB")

# ---------------- time_core_0（新）----------------
TX, TY, TW, TH = 1010, 66, 710, 160
box(TX, TY, TW, TH, "tim")
t(TX + 12, TY + 20, "time_core_0（新）　DSP ドメイン 256 MHz・BUILD_TAG [20]・ID 0x0016_7101", "tm")
t(TX + 28, TY + TH - 6, "▲ s_axi（M03）", "xs")
box(TX + 10, TY + 30, 160, 112, "tsub")
t(TX + 18, TY + 46, "T（64 bit）", "tm")
for k, ln in enumerate(["1 ビート = 3.906 ns", "1 s = 256,000,000", "aresetn でだけ 0 に", "t_out = T ＋ 1 を出す", "（コアで 1 段 → T）"]):
    t(TX + 18, TY + 62 + 15 * k, ln, "xt")
box(TX + 180, TY + 30, 175, 112, "tsub")
t(TX + 188, TY + 46, "PPS（TRIG・COMP）", "tm")
for k, ln in enumerate(["同期器 3 段（1 で始める）", "スタンプ・間隔・数", "グリッチ（< 0.5 s）", "欠落（1.5 s）", "BAD（|間隔 − 1 s| > TOL）"]):
    t(TX + 188, TY + 62 + 15 * k, ln, "xt")
box(TX + 365, TY + 30, 165, 112, "tsub")
t(TX + 373, TY + 46, "予約発火", "tm")
for k, ln in enumerate(["START_AT（64 bit）", "rem を下へ数える", "遅すぎ < 16・遠すぎ ≧ 2^40", "go_loc は T = START_AT", "FIRED = START_AT"]):
    t(TX + 373, TY + 62 + 15 * k, ln, "xt")
box(TX + 540, TY + 30, 160, 112, "tsub")
t(TX + 548, TY + 46, "原点", "tm")
for k, ln in enumerate(["ANCHORED（PS が 1 に）", "リセットで 0", "EPOCH: ctrl_aclk 側で", "aresetn の解除を数え", "gray で渡す（CDC-6）"]):
    t(TX + 548, TY + 62 + 15 * k, ln, "xt")
# PPS の外部ポート
box(760, 84, 200, 40, "ext"); t(770, 100, "pps_trig（AH13）"); t(770, 116, "IRIG_TRIG_OUT・シュミット", "xs")
box(760, 134, 200, 40, "ext"); t(770, 150, "pps_comp（AJ13）"); t(770, 166, "IRIG_COMP_OUT・オープンドレイン", "xs")
path(f"M960,104 L{TX-2},104", "wK"); path(f"M960,154 L{TX-2},154", "wK")
box(760, 184, 200, 34, "ext"); t(770, 205, "PPS Clk（SMA）← 45m の 1PPS", "xs")
path("M860,184 L860,176", "wK")

# ---------------- ADC_A の行 ----------------
top = 280
RX, RW = 200, 170
blocks = [("gb_adc", 396, 98, "O", ["出口の見張り", "書き込み側の再起動"]),
          ("gb_up", 506, 98, "O", ["幅の変換", "12 → 48 smp（×4）"]),
          ("gb_fifo", 616, 108, "F", ["非同期 FIFO", "768 bit × 32"]),
          ("gb_gate", 736, 98, "G", ["しきい値 K", "見張り（既定 K = 2）"]),
          ("gb_dn", 846, 98, "G", ["幅の変換", "48 → 16 smp（÷3）"])]
BCX, BCW = 956, 106
WX, WW = 1110, 610
ry = top + 58
rtop, rbot = top - 10, top + 160
box(RX, rtop, RW, rbot - rtop)
t(RX + 12, rtop + 22, "rfdc", "t"); t(RX + 12, rtop + 40, "RF Data Converter")
t(RX + 12, rtop + 92, "fs 4096 MSPS・ゾーン 2", "xs")
t(RX + 12, rtop + 107, "Real・Data_Width 12", "xs")
t(RX + 12, rtop + 125, "Tile 226 だけ", "tm")
t(RX + 12, rtop + 142, "（Tile 224 は無効）", "xs")
path(f"M660,100 L690,100 L690,250 L{RX+85},250 L{RX+85},{rtop-2}", "wB")
t(300, 245, "M00 → rfdc/s_axi（pl_clk0）", "lbB")

box(20, ry - 22, 150, 44, "ext")
t(30, ry - 4, "ADC_A（SMA）"); t(30, ry + 13, "IF 2048〜4096 MHz", "xs")
path(f"M170,{ry} L{RX-2},{ry}", "wK")
t(RX + RW - 6, ry - 6, "m22_axis ▶", "xs", "end"); t(RX + RW - 6, ry + 10, "slice 2", "xs", "end")
t(396, top + 14, "ch 0 = ADC_A：Tile 226 / slice 2", "tm")
t(640, top + 14, "語幅: 192 bit・341 MHz → 768 bit → 256 bit・256 MHz（tready = 1）", "xs")
path(f"M{RX+RW},{ry} L{blocks[0][1]-2},{ry}", "wO")
by, bh = top + 30, 56
for j, (nm, x, w, dom, lines) in enumerate(blocks):
    col = {"O": "#d9822b", "G": "#2e8b57", "F": "#333"}[dom]
    box(x, by, w, bh, style=f"stroke:{col}")
    if dom == "F":
        a(f'<line x1="{x}" y1="{by}" x2="{x}" y2="{by+bh}" stroke="#d9822b" stroke-width="5"/>')
        a(f'<line x1="{x+w}" y1="{by}" x2="{x+w}" y2="{by+bh}" stroke="#2e8b57" stroke-width="5"/>')
    t(x + 8, by + 18, f"{nm}_0", "tm")
    t(x + 8, by + 33, lines[0], "xs"); t(x + 8, by + 47, lines[1], "xs")
    if j + 1 < len(blocks):
        path(f"M{x+w},{ry} L{blocks[j+1][1]-2},{ry}", "wO" if dom == "O" else "wG")
last = blocks[-1]
path(f"M{last[1]+last[2]},{ry} L{BCX-2},{ry}", "wG")
box(BCX, by, BCW, bh, style="stroke:#c0392b;stroke-width:1.8")
t(BCX + 8, by + 18, "gb_bc_0", "tm")
t(BCX + 8, by + 33, "axis_broadcaster", "xs"); t(BCX + 8, by + 47, "M00 窓・M01 全帯域", "xs")
path(f"M{BCX+BCW},{ry} L{WX-2},{ry}", "wR")
XS0 = BCX + BCW + 14
yc = by + bh + 14
path(f"M{WX},{yc} L{blocks[0][1]+48},{yc} L{blocks[0][1]+48},{by+bh+2}", "wP")
for x in (blocks[3][1] + 48, blocks[4][1] + 48):
    path(f"M{x},{yc} L{x},{by+bh+2}", "wP")
t(blocks[0][1] + 56, yc + 13, "gb_hold・gb_adj／gb_k・gb_dn_rstn ← win_core_0 ／ gb_stat・adc_stat → win_core_0 と full_sel", "lbP")

# ---- win_core_0 ----
wy, wh = top + 2, 300
box(WX, wy, WW, wh, "win")
t(WX + 10, wy + 17, "win_core_0（ADC_A）　NW 4・ID 0x0016_0100・DSP 728", "tm")
t(WX + WW - 6, wy + 17, "s_axi ◀ M01", "xs", "end")
py = wy + 28
box(WX + 10, py, 128, 170, "wsub")
t(WX + 16, py + 15, "pfb_core（共有）", "tm")
for k, ln in enumerate(["粗い PFB・M 32", "128 MHz 間隔・4 倍", "96 タップ・実 DFT", "窓ごとに ch k を", "選んで 4 本へ・288", "（proj015 と同一）"]):
    t(WX + 16, py + 31 + 14 * k, ln, "xs")
path(f"M{WX+2},{ry} L{WX+8},{ry}", "wR")
wx2, ww2, rh = WX + 150, 290, 38
for w in range(4):
    yy = py + w * (rh + 6)
    box(wx2, yy, ww2, rh, "wsub")
    t(wx2 + 6, yy + 12, f"窓 {w}: ddc → wspec（4096 点 FFT・電力・積分）", "xs")
    box(wx2 + 6, yy + 17, ww2 - 12, 17, "tsub")
    t(wx2 + 10, yy + 29, "dstamp（DUMP_T・DUMP_H）・ARM・CFG_ID", "xt")
    path(f"M{WX+138},{py+85} L{WX+144},{py+85} L{WX+144},{yy+rh//2} L{wx2-2},{yy+rh//2}", "wR")
rx2 = wx2 + ww2 + 10
rw2 = WX + WW - 10 - rx2
box(rx2, py, rw2, 44, "sub")
t(rx2 + 6, py + 15, "tp_core（total power）", "xs"); t(rx2 + 6, py + 29, "Σx²・1 ms・リング・TP_ARM", "xs")
box(rx2, py + 50, rw2, 32, "wsub")
t(rx2 + 6, py + 63, "スナップショット 1 つ", "xs"); t(rx2 + 6, py + 76, "SNAP_SEL の窓が書く", "xs")
box(rx2, py + 88, rw2, 46, "tsub")
t(rx2 + 6, py + 101, "adc_ev: 振り切れ・途切れ", "xt"); t(rx2 + 6, py + 114, "TANCH:（ADC のフレーム, T）", "xt")
t(rx2 + 6, py + 127, "OVR_CNT・GAP_CNT", "xt")
t(rx2, py + 150, "窓 w: 0x20000·w", "xs"); t(rx2, py + 164, "共通: 0x80000〜", "xs")
t(WX + 10, wy + 214, "SHIFT・CFG_ID は RUN の時点で取り込む（RUN の間の書き込みは次の RUN から）", "xs")
t(WX + 10, wy + 228, "ARM_RUN ＋ ARM_WRST が同じ発火なら、RUN は WRST が明けた後", "xs")
t(WX + 10, wy + 244, "DUMP_H: [0] PPS 来ていない [1] 間隔 [2] グリッチ [3] 原点なし [4] 振り切れ", "xt")
t(WX + 10, wy + 258, "　　　　[5] 途切れ [6] CFG 不一致 [14][15] 帳簿", "xt")
t(WX + 10, wy + 274, "窓の遅れ D(NS)（ADC → z）: 0.23 µs（256 MHz）〜 10.9 µs（2 MHz）＝ WIN_DELAY_BEATS", "xt")
t(WX + 10, wy + 288, "DUMP_T(k) − DUMP_T(0) = k·N·4096·2^(NS−1)（sim の NS 1 でずれ 0）", "xt")

# 時刻のバス: time_core → win_core_0（上から）・spec_core_0（右を回って）
xtb = 1400
path(f"M{xtb},{TY+TH} L{xtb},{wy-2}", "wT")
t(xtb + 8, TY + TH + 18, "t_out（64）・go_out・ev_out（4）→ 各コアで 1 段（t_loc = T）", "lbT")

# ---------------- full_sel → spec_core_0 ----------------
fy = wy + wh + 40
fx0, fw = XS0 - 30, 150
path(f"M{BCX+BCW},{ry+14} L{XS0},{ry+14} L{XS0},{fy-2}", "wG")
box(fx0, fy, fw, 90, style="stroke:#2e8b57;stroke-width:1.8")
t(fx0 + 8, fy + 18, "full_sel", "tm"); t(fx0 + 8, fy + 34, "axis_sel4（s0 だけ）", "xs")
t(fx0 + 8, fy + 49, "sel ← win_core_0", "xs"); t(fx0 + 8, fy + 64, "sel のファンアウト 303", "xs")
t(fx0 + 8, fy + 79, "（最悪経路の群。次で外す）", "xs")
SPX, SPW = fx0 + fw + 40, WX + WW - (fx0 + fw + 40)
path(f"M{fx0+fw},{fy+45} L{SPX-2},{fy+45}", "wG")
box(SPX, fy, SPW, 160, style="stroke:#2e8b57;stroke-width:2.2")
t(SPX + 12, fy + 20, "spec_core_0（全帯域 1 本）　DSP 504", "t")
t(SPX + SPW - 8, fy + 20, "ID 0x0016_01CC・s_axi ◀ M02", "xs", "end")
t(SPX + 12, fy + 38, "8192 点 FFT（lane_fft × 16）→ 電力 → 積分：4096 ch × 0.5 MHz", "xs")
box(SPX + 10, fy + 48, 180, 40, "sub")
t(SPX + 18, fy + 64, "tp_core（u_tp）", "tm"); t(SPX + 18, fy + 80, "Σx²・1 ms", "xs")
box(SPX + 200, fy + 48, SPW - 210, 40, "tsub")
t(SPX + 208, fy + 64, "dstamp・adc_ev・ARM_RUN・CFG_ID（新）", "xt")
t(SPX + 208, fy + 80, "DUMP_T の間隔 = k·N·512 ちょうど", "xt")
t(SPX + 12, fy + 108, "SHIFT・CFG_ID は RUN で取り込む。gb_* の出口は未接続（ギアボックスは win_core_0 が握る）", "xs")
# AXI M01 / M02（右端）
XV0 = WX + WW + 22
path(f"M660,119 L700,119 L700,258 L{XV0},258 L{XV0},{wy+12} L{WX+WW+2},{wy+12}", "wB")
path(f"M660,134 L710,134 L710,266 L{XV0+12},266 L{XV0+12},{fy+150} L{SPX+SPW+2},{fy+150}", "wB")
path(f"M660,149 L720,149 L720,236 L{TX+20},236 L{TX+20},{TY+TH+2}", "wB")
t(728, 231, "M03 → time_core_0（4 KiB）", "lbB")
t(760, 252, "M01 → win_core_0（1 MiB）・M02 → spec_core_0（64 KiB）", "lbB")
# 時刻のバスを spec_core_0 へ
xtr = XV0 + 30
path(f"M{TX+TW},{TY+TH-20} L{xtr},{TY+TH-20} L{xtr},{fy+130} L{SPX+SPW+2},{fy+130}", "wT")
t(SPX + SPW - 8, fy + 126, "t_in・go_in・tev_in ◀", "xt", "end")

# ---------------- クロックとリセット ----------------
cy = fy + 195
path(f"M{RX+85},{rbot} L{RX+85},{cy-2}", "wK")
t(RX + 92, rbot + 24, "clk_adc2 256 MHz（fs/16）", "lb")
box(RX, cy, 230, 120)
t(RX + 12, cy + 22, "clk_wiz_adc（MMCM）", "t")
t(RX + 12, cy + 40, "入力 256 MHz（clk_adc2）", "xs")
t(RX + 12, cy + 60, "clk_out1 341.333 MHz → ADC ドメイン", "lbO")
t(RX + 12, cy + 77, "clk_out2 256.000 MHz → DSP ドメイン", "lbG")
t(RX + 12, cy + 95, "time_core の T はこのクロックを数える", "xt")
t(RX + 12, cy + 110, "（10 MHz に乗っていれば 1 s = 256e6）", "xt")
rx0 = RX + 250
box(rx0, cy, 170, 56, style="stroke:#2f6fb5")
t(rx0 + 10, cy + 22, "rst_ctrl", "t"); t(rx0 + 10, cy + 42, "smc・rfdc・time_core の ctrl", "xs")
box(rx0 + 180, cy, 170, 56, style="stroke:#d9822b")
t(rx0 + 190, cy + 22, "rst_adc", "t"); t(rx0 + 190, cy + 42, "1 タイルなので切り出さない", "xs")
box(rx0 + 360, cy, 300, 56, style="stroke:#2e8b57")
t(rx0 + 370, cy + 22, "rst_dsp", "t"); t(rx0 + 370, cy + 42, "win_core_0・spec_core_0・time_core_0 ほか", "xs")
t(rx0, cy + 78, "3 つとも ext_reset_in = pl_resetn0。ADC・DSP 側は MMCM の locked まで保持。", "xs")
t(rx0, cy + 94, "MMCM のロックが外れると rst_dsp → T が 0 に戻り ANCHORED = 0（ダンプの [3]）。EPOCH は rst_ctrl 側で数える。", "xt")
t(rx0, cy + 110, "time_core の ctrl_aclk = pl_clk0（エポックを数える側）。それ以外の時刻はすべて DSP ドメイン。", "xt")
box(20, cy, 150, 44, "ext"); t(30, cy + 18, "LMX2594"); t(30, cy + 35, "491.52 MHz", "xs")
box(20, cy + 56, 150, 44, "ext"); t(30, cy + 74, "SYSREF（LMK04828）"); t(30, cy + 91, "→ sysref_in", "xs")
box(20, cy + 112, 150, 44, "ext"); t(30, cy + 130, "10 MHz（CLKin0）"); t(30, cy + 147, "メーザー由来（--clkin 0）", "xs")
path(f"M170,{cy+22} L184,{cy+22} L184,{rbot-40} L{RX-2},{rbot-40}", "wK")
path(f"M170,{cy+78} L192,{cy+78} L192,{rbot-24} L{RX-2},{rbot-24}", "wK")

nx0 = rx0 + 680
box(nx0, cy, WX + WW - nx0, 156, "note")
t(nx0 + 12, cy + 20, "資源とタイミング（build/・-1 ＋ PS のプリセット・既定の戦略）", "tm")
t(nx0 + 12, cy + 40, "DSP 1232（28.8 %）= win_core_0 728 ＋ spec_core_0 504", "xs")
t(nx0 + 12, cy + 55, "　wspec 1 個 32（予言 30。+2 の場所は未確認）", "xs")
t(nx0 + 12, cy + 70, "BRAM 199 タイル（18.4 %）・URAM 8・LUT 26.5 %・FF 22.7 %", "xs")
t(nx0 + 12, cy + 88, "WNS +0.006 ns / WHS +0.010 ns。最悪経路は pfb（proj015 から）と", "xs")
t(nx0 + 12, cy + 103, "　full_sel のファンアウト。時刻の論理は上位 200 本に出ない", "xs")
t(nx0 + 12, cy + 121, "CDC-6: ADC_STAT（既存）と EPOCH の gray（新）の 2 件", "xs")
t(nx0 + 12, cy + 136, "実機: T-0 通過（間隔 256,000,000 ちょうど）・T-1 通過（30 分でずれ 0・健全性なし）", "xs")

ly = H - 18
t(20, ly, "凡例", "tm")
for k, (cls, lab, lc) in enumerate([("wB", "PS 側（pl_clk0）・AXI", "lbB"), ("wO", "ADC ドメイン 341 MHz", "lbO"),
                                    ("wG", "DSP ドメイン 256 MHz", "lbG"), ("wR", "窓の流れ", "lbR"),
                                    ("wT", "時刻（新・DSP ドメイン）", "lbT"), ("wP", "見張り・再起動", "lbP"), ("wK", "アナログ・クロック・PPS", "lb")]):
    x = 70 + k * 245
    path(f"M{x},{ly-4} L{x+40},{ly-4}", cls)
    t(x + 48, ly, lab, lc)

a("</svg>")
open("block_design.svg", "w", encoding="utf-8").write("\n".join(o) + "\n")
print("ok")
