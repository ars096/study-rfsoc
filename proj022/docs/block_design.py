# SPDX-License-Identifier: BSD-3-Clause
# proj022 のブロックデザインの図 docs/block_design.svg を作る。`cd docs && python3 block_design.py`
# **予定の図**（RTL 前。build.tcl はまだ無い）。README の「結論」の表と E-1 の案 A（係数・ひねり係数を 4 ADC で共有、
# 履歴 URAM、積分器は切り出しだけ・BRAM）を描いた。描き方は proj021 の docs/block_design.py の型。
# v2 の共通部（s45_core の殻・レコード・リング・time_core）は proj021 が確定させるので、ここでは箱だけ置く。
# RTL の proj で build.tcl ができたら、そちらの配線から描き直す
W, H = 1870, 1380
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
  <!-- proj022 の予定のブロックデザイン（RTL 前）。docs/block_design.py で描いた -->
  <defs>
    <marker id="aB" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#2f6fb5"/></marker>
    <marker id="aO" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#d9822b"/></marker>
    <marker id="aG" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#2e8b57"/></marker>
    <marker id="aK" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#555"/></marker>
    <marker id="aR" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#c0392b"/></marker>
    <marker id="aT" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#0f7c8c"/></marker>
    <marker id="aC" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#8e5b1f"/></marker>
    <style>
      .blk  {{ fill:#f8f8f8; stroke:#333; stroke-width:1.5; }}
      .sub  {{ fill:#ffffff; stroke:#2e8b57; stroke-width:1.2; }}
      .new  {{ fill:#fff7ea; stroke:#d9822b; stroke-width:1.6; }}
      .core {{ fill:#f2f8f3; stroke:#2e8b57; stroke-width:2.2; }}
      .tim  {{ fill:#eef8f9; stroke:#0f7c8c; stroke-width:2.0; }}
      .tsub {{ fill:#ffffff; stroke:#0f7c8c; stroke-width:1.2; }}
      .shr  {{ fill:#fbf3e8; stroke:#8e5b1f; stroke-width:2.0; }}
      .v2   {{ fill:#f4f4f8; stroke:#6a6a8a; stroke-width:1.6; stroke-dasharray:6 4; }}
      .ext  {{ fill:#eeeeee; stroke:#777; stroke-width:1.2; stroke-dasharray:4 3; }}
      .note {{ fill:#fbf7ec; stroke:#b39a5a; stroke-width:1.2; }}
      .t    {{ font-size:14px; font-weight:bold; fill:#111; }}
      .tm   {{ font-size:12.5px; font-weight:bold; fill:#111; }}
      .s    {{ font-size:11.5px; fill:#333; }}
      .xs   {{ font-size:10.5px; fill:#555; }}
      .xt   {{ font-size:10.5px; fill:#0b5d69; }}
      .xc   {{ font-size:10.5px; fill:#7a4a14; }}
      .xn   {{ font-size:10.5px; fill:#a8571a; }}
      .wB   {{ stroke:#2f6fb5; stroke-width:2.0; fill:none; marker-end:url(#aB); }}
      .wO   {{ stroke:#d9822b; stroke-width:2.6; fill:none; marker-end:url(#aO); }}
      .wG   {{ stroke:#2e8b57; stroke-width:2.6; fill:none; marker-end:url(#aG); }}
      .wR   {{ stroke:#c0392b; stroke-width:2.6; fill:none; marker-end:url(#aR); }}
      .wK   {{ stroke:#555; stroke-width:1.6; fill:none; marker-end:url(#aK); }}
      .wT   {{ stroke:#0f7c8c; stroke-width:2.2; fill:none; marker-end:url(#aT); }}
      .wC   {{ stroke:#8e5b1f; stroke-width:2.4; fill:none; marker-end:url(#aC); }}
      .lC   {{ stroke:#8e5b1f; stroke-width:2.4; fill:none; }}
      .lb   {{ font-size:11px; fill:#333; }}
      .lbB  {{ font-size:11px; fill:#2f6fb5; }}
      .lbO  {{ font-size:11px; fill:#b8661a; }}
      .lbG  {{ font-size:11px; fill:#236b43; }}
      .lbR  {{ font-size:11px; fill:#a93226; }}
      .lbT  {{ font-size:11px; fill:#0b5d69; }}
      .lbC  {{ font-size:11px; fill:#7a4a14; }}
    </style>
  </defs>
  <rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>''')

t(20, 28, "proj022 ブロックデザイン（予定・RTL 前）: SAM45-Wide = 4 ADC × PFB（T = 4）＋ 全帯域 FFT 8192 / 16384 / 32768 点 ＋ 切り出し 4096 ch × 2", style="font-size:17px;font-weight:bold;fill:#111")
t(20, 48, "build.tcl はまだ無い。README の「結論」と E-1 の案 A（係数・ひねり係数を 4 ADC で 1 組・履歴 URAM・積分器は切り出しだけ）を描いた。橙の枠 = SAM45-Fine（proj021）から新しく作るもの、点線の枠 = v2 の共通部（proj021 が確定させる）")

# ---------------- PS / SmartConnect / time_core ----------------
box(40, 70, 250, 120, style="stroke:#2f6fb5")
t(52, 92, "zynq_ultra_ps_e_0", "t"); t(52, 110, "PS（PYNQ / Linux）・-1 ＋ ps_preset.tcl")
t(52, 128, "specd v2: 束ね・float32・s45proto v2", "xs")
t(52, 143, "モード（N）・SHIFT・開始 ch は RUN の前に", "xs")
t(282, 165, "M_AXI_HPM0_FPD ▶", "xs", "end"); t(282, 182, "◀ S_AXI_HP0（リング）", "xs", "end")
box(330, 70, 220, 120, style="stroke:#2f6fb5")
t(342, 92, "smc_ctrl", "t"); t(342, 110, "SmartConnect")
t(342, 127, "aclk = pl_clk0 / aclk1 = 256 MHz", "xs")
t(342, 142, "M00 rfdc・M01〜M04 s45_core_0〜3", "xs")
t(342, 157, "・time_core・s45_ring（v2 の番地）", "xs")
path("M290,150 L328,150", "wB")

TX, TY, TW, TH = 590, 70, 520, 120
box(TX, TY, TW, TH, "tim")
t(TX + 12, TY + 20, "time_core_0（proj021 のまま）DSP ドメイン 256 MHz", "tm")
for k, ln in enumerate(["T（64 bit、1 ビート = 3.906 ns）・1PPS のスタンプ・欠落・BAD",
                        "予約発火: START_AT は時刻の格子（2.048 ms = 524,288 ビート）の倍数",
                        "格子 2.048 ms = 1024 / 512 / 256 フレーム（N = 8192 / 16384 / 32768。整数）",
                        "→ WRST・RUN を 4 コアに同じビートで（フレームの頭を T に揃えれば係数の遅延 0）"]):
    t(TX + 12, TY + 42 + 17 * k, ln, "xt")

V2X, V2Y, V2W, V2H = 1150, 70, 700, 165
box(V2X, V2Y, V2W, V2H, "v2")
t(V2X + 12, V2Y + 20, "v2 の共通部（proj021 が作っている。ここでは箱だけ）", "tm")
for k, ln in enumerate(["rec_fr・rec_arb: ダンプごとのレコード（頭に DUMP_T・CFG・健全性）を組み、流れと TP を束ねる",
                        "s45_ring: PL が書くリング・尾の CRC-32・HP0 128 bit → DDR（PS は範囲を絞った invalidate で読む）",
                        "流れのブロック（1 KiB）: SID・KIND・NCH・SRC・CFG_ID・DUMP_* ・RUN_* …",
                        "**SLICE に要るもの（proj021 へ返す）: 開始 ch s・全帯域の点数 N**（ch → IF = (s + i)·fs / N）",
                        "量: 4 ADC × 2 × 4096 ch / 40.96 ms（SAM45-Fine と同じ。float32 で 6.4 MB/s）"]):
    t(V2X + 12, V2Y + 42 + 18 * k, ln.replace("**", ""), "xs" if k != 3 else "xn")
path(f"M{V2X},{V2Y+150} L300,{V2Y+150} L300,182 L292,182", "wR")
t(V2X - 8, V2Y + 145, "◀ DDR へ（HP0）", "lbR", "end")

# ---------------- 行 ----------------
labels = ["ADC_A", "ADC_B", "ADC_C", "ADC_D"]
tiles = [(226, 2), (226, 0), (224, 2), (224, 0)]
LH = 205
tops = [285 + LH * i for i in range(4)]
RX, RW = 190, 120
GX, GW = 335, 215
CX, CW = 610, 1150
XCOEF, XTW = 572, 588
XAXI, XREC, XTIM = 1775, 1805, 1840

rtop, rbot = tops[0] - 10, tops[3] + 175
box(RX, rtop, RW, rbot - rtop)
t(RX + 10, rtop + 22, "rfdc", "t"); t(RX + 10, rtop + 40, "fs 4096 MSPS", "xs")
t(RX + 10, rtop + 55, "ゾーン 2・Real", "xs"); t(RX + 10, rtop + 70, "（proj021 のまま）", "xs")
ymid = tops[2] - 12
a(f'<line x1="{RX}" y1="{ymid}" x2="{RX+RW}" y2="{ymid}" stroke="#999" stroke-dasharray="5 3"/>')
t(RX + 10, tops[0] + 130, "Tile 226", "tm"); t(RX + 10, ymid + 26, "Tile 224", "tm")

# AXI（smc → コア）・時刻のバス・レコード
path(f"M550,120 L566,120 L566,262 L{XAXI},262 L{XAXI},{tops[0]-4}", "wB")
t(1300, 275, "M01〜M04 → s45_core_0〜3（AXI4-Lite、v2 の番地）", "lbB")
path(f"M{TX+TW//2},{TY+TH} L{TX+TW//2},252 L{XTIM},252 L{XTIM},{tops[0]-4}", "wT")
t(TX + TW // 2 + 8, 248, "時刻のバス t・go・ev → 各コア", "lbT")

for i in range(4):
    top = tops[i]
    ry = top + 72
    tl, sl = tiles[i]
    box(20, ry - 22, 150, 44, "ext")
    t(30, ry - 4, f"{labels[i]}（SMA）"); t(30, ry + 13, "IF 2048〜4096 MHz", "xs")
    path(f"M170,{ry} L{RX-2},{ry}", "wK")
    path(f"M{RX+RW},{ry} L{GX-2},{ry}", "wO")
    box(GX, ry - 34, GW, 68, style="stroke:#2e8b57")
    t(GX + 8, ry - 16, f"ギアボックス {i}（proj021 のまま）", "tm")
    t(GX + 8, ry, "gb_adc → gb_up → gb_fifo → gb_gate", "xs")
    t(GX + 8, ry + 14, "→ gb_dn: 16 サンプル / ビート・256 MHz", "xs")
    t(GX + 8, ry + 28, f"Tile {tl} / slice {sl}", "xs")
    path(f"M{GX+GW},{ry} L{CX-2},{ry}", "wG")

    # ---- s45_core_i（SAM45-Wide）----
    cy0, ch0 = top, LH - 15
    box(CX, cy0, CW, ch0, "core")
    t(CX + 12, cy0 + 18, f"s45_core_{i}（{labels[i]}）SAM45-Wide　見当: DSP 664（レーン FFT 432・PFB 64・残り 168）・BRAM 130 ＋ 積分器 32・URAM 10", "tm")
    t(CX + CW - 8, cy0 + 18, "s_axi ◀", "xs", "end")
    py, ph = cy0 + 28, 96
    stages = [
        ("pfb_w（PFB T = 4）", 150, "new", ["16 レーン × 4 タップ", "x 14 → y 16 bit（小数 1）", "履歴 URAM 10", "（672 bit × 2048 行）", "DSP 64"]),
        ("lane_fft × 16", 150, "sub", ["FFT IP・実行時の長さ", "512 / 1024 / 2048 点", "入力 16 → Y 27 bit", "unscaled・自然順", "DSP 27 × 16（S-1 待ち）"]),
        ("ひねり係数 × 15", 122, "new", ["cmul（>> 18）", "W_N^(p·k1)", "表 1 本を 1·2·4 個おき", "→ V 25 bit"]),
        ("dft16", 104, "sub", ["今のまま", "k2 = 0..7", "U 27・Z 29 bit"]),
        ("SHIFT・電力", 116, "sub", [">> SHIFT → 18 bit", "飽和を数える", "re² ＋ im² × 8", "（37 bit）"]),
        ("振り分け", 124, "new", ["c = k1 ＋ M·k2", "→ 銀行 ⌊(c − s)/M⌋", "番地 (c − s) mod M", "8 → 8（37 bit）"]),
        ("積分器（切り出しだけ）", 168, "new", ["8 銀行 × 1024 × 64 bit", "× 2 面 = BRAM 32", "N_ACC 20480 / 10240 / 5120", "（どれも 40.96 ms）", "RMW 1 銀行 1 クロック 1 回"]),
        ("流れ（KIND SLICE）", 136, "new", ["s0: 4096 ch（開始 s₀）", "s1: 4096 ch（開始 s₁）", "全帯域は s0 だけ・s₀ 0", "dstamp・CFG_ID", "→ レコード"]),
    ]
    x = CX + 12
    pos = {}
    for k, (nm, w, cls, lines) in enumerate(stages):
        box(x, py, w, ph, cls)
        t(x + 7, py + 16, nm, "tm")
        for j, ln in enumerate(lines):
            t(x + 7, py + 32 + 14 * j, ln, "xs")
        pos[k] = (x, w)
        if k + 1 < len(stages):
            path(f"M{x+w},{py+ph//2} L{x+w+10},{py+ph//2}", "wG")
        x += w + 12
    path(f"M{CX+2},{ry} L{CX+10},{ry}", "wG") if ry < py + ph else None
    # 下の段
    sy, sh = py + ph + 14, 40
    box(CX + 12, sy, 262, sh, "new")
    t(CX + 18, sy + 15, "SRL の遅延（ADC ごとの一定のずれ k ビート）", "xc")
    t(CX + 18, sy + 31, "係数 64 × 18 bit・ひねり係数 15 × 36 bit", "xc")
    sub2 = [("tp_core: Σx²・1.024 ms・FLAGS[4]", 215), ("スナップショット（ADC の生 8192）", 200),
            ("adc_ev・dstamp・健全性・帳簿", 200), ("モード N・SHIFT・s₀・s₁|RUN の時点で取り込む", 0)]
    xx = CX + 12 + 262 + 12
    for nm, w in sub2:
        if w == 0:
            w = CX + CW - 12 - xx
        box(xx, sy, w, sh, "tsub" if "dstamp" in nm else "sub")
        if "|" in nm:
            l1, l2 = nm.split("|")
            t(xx + 6, sy + 16, l1, "xs"); t(xx + 6, sy + 31, l2, "xs")
        else:
            t(xx + 6, sy + 25, nm, "xs" if "dstamp" not in nm else "xt")
        xx += w + 12
    # 係数・ひねり係数のバス: 縦線 → SRL → pfb・cmul
    path(f"M{XCOEF},{sy+12} L{CX+10},{sy+12}", "wC")
    path(f"M{XTW},{sy+28} L{CX+10},{sy+28}", "wC")
    px, pw = pos[0]
    path(f"M{px+60},{sy} L{px+60},{py+ph+2}", "wC")
    tx_, tw_ = pos[2]
    path(f"M{CX+200},{sy} L{CX+200},{sy-6} L{tx_+tw_//2},{sy-6} L{tx_+tw_//2},{py+ph+2}", "wC")
    # 出口 → レコード（右の縦線）・AXI・時刻
    ex, ew = pos[7]
    path(f"M{ex+ew},{py+ph//2} L{XREC},{py+ph//2} L{XREC},{V2Y+V2H+2}", "wR") if i == 0 else \
        path(f"M{ex+ew},{py+ph//2} L{XREC},{py+ph//2}", "wR")
    path(f"M{XAXI},{cy0+10} L{XAXI},{cy0+22} L{CX+CW+2},{cy0+22}", "wB")
    path(f"M{XTIM},{cy0+10} L{XTIM},{cy0+40} L{CX+CW+2},{cy0+40}", "wT")
# 縦線（レコード・AXI・時刻）を下の行までつなぐ
a(f'<line x1="{XREC}" y1="{tops[3]+28+48}" x2="{XREC}" y2="{tops[0]+28+48}" stroke="#c0392b" stroke-width="2.6"/>')
a(f'<line x1="{XAXI}" y1="{tops[0]-4}" x2="{XAXI}" y2="{tops[3]+22}" stroke="#2f6fb5" stroke-width="2.0"/>')
a(f'<line x1="{XTIM}" y1="{tops[0]-4}" x2="{XTIM}" y2="{tops[3]+40}" stroke="#0f7c8c" stroke-width="2.2"/>')
t(XREC + 6, tops[1] - 8, "レコード", "lbR")

# ---------------- 共有の ROM（4 ADC で 1 組）----------------
SY = tops[3] + LH + 10
box(GX - 10, SY, 255, 112, "shr")
t(GX, SY + 20, "pfb_coef_rom（4 ADC で 1 組）", "tm")
for k, ln in enumerate(["URAM 16（レーンごとに 1 個）", "1 語 72 bit = 4 タップ × 18 bit", "行 2048 ＋ 1024 ＋ 512（長さごとの表）",
                        "番地 = フレームの中のビート m", "sinc × Kaiser β 5・bw 1.198・Σh² = N"]):
    t(GX, SY + 38 + 15 * k, ln, "xc")
box(GX - 10, SY + 124, 255, 82, "shr")
t(GX, SY + 144, "tw_rom（4 ADC で 1 組）", "tm")
for k, ln in enumerate(["BRAM 30（15 レーン × 2048 × 36 bit）", "W_32768^(p·k1·32768/N)（厳密）", "番地 = レーン FFT の出口の k1"]):
    t(GX, SY + 162 + 15 * k, ln, "xc")
path(f"M{GX+245},{SY+50} L{XCOEF},{SY+50} L{XCOEF},{tops[0]+150}", "lC")
path(f"M{GX+245},{SY+165} L{XTW},{SY+165} L{XTW},{tops[0]+166}", "lC")

# ---------------- モードの表・資源 ----------------
MX, MY = 610, SY
box(MX, MY, 590, 206, "note")
t(MX + 12, MY + 20, "モード（レジスタで切り替え。Overlay ではない）・dt 40.96 ms", "tm")
rows = [("", "N（レーン）", "ch 幅", "流れ", "フレーム", "40.96 ms"),
        ("全帯域", "8192（512）", "500 kHz", "1", "2 µs", "20480"),
        ("1 GHz", "16384（1024）", "250 kHz", "2", "4 µs", "10240"),
        ("512 MHz", "32768（2048）", "125 kHz", "2", "8 µs", "5120")]
cols = [0, 80, 200, 290, 340, 420]
for r, row in enumerate(rows):
    for c, v in enumerate(row):
        t(MX + 14 + cols[c], MY + 42 + 17 * r, v, "tm" if r == 0 or c == 0 else "xs")
for k, ln in enumerate(["ch の応答は 3 つの長さとも proj020 と同じ（0.5 ch −3.00 dB・≧ 1 ch −53.7 dB・ENBW 1.010）",
                        "PFB の重心は矩形より 1.5 フレーム前（3 / 6 / 12 µs）。立ち上がり 3 フレームは r − 3 + t < 0 のタップを 0",
                        "1 本の流れは 1 クロックに 4096 / M 個の bin を受ける（開始 ch に依らない）→ 切り出しだけを積める",
                        "SHIFT の目安: −17 dBFS の雑音で 2〜3、−1 dBFS の CW で 7〜9（0〜15 で足りる）"]):
    t(MX + 12, MY + 124 + 18 * k, ln, "xs")

NX = MX + 600
box(NX, MY, CX + CW - NX, 206, "note")
t(NX + 12, MY + 20, "資源の見積もり（E-1 の案 A、レーン FFT は proj014 の survey の値）", "tm")
for k, ln in enumerate(["DSP 2,656（62 %）= (432 ＋ 64 ＋ 168) × 4",
                        "BRAM 688（64 %）= (120 ＋ 10 ＋ 32) × 4 ＋ ひねり係数 30 ＋ 共通 10",
                        "URAM 56（70 %）= 履歴 10 × 4 ＋ 係数 16",
                        "LUT 290k（68 %）・FF 540k（64 %）",
                        "何も共有しないと BRAM 938（87 %）で入らない",
                        "未確定: S-1（レーン FFT の入力 16 bit）・v2 の共通部（proj021）",
                        "`-1` の危うさ: LUT（Fine は 48.6 %）。長さ切り替えの代償 46k"]):
    t(NX + 12, MY + 42 + 20 * k, ln, "xs" if k not in (4, 6) else "xn")

# ---------------- クロック ----------------
KY = SY
box(20, KY, 150, 44, "ext"); t(30, KY + 18, "LMX2594"); t(30, KY + 35, "491.52 MHz（両タイル）", "xs")
box(20, KY + 56, 150, 44, "ext"); t(30, KY + 74, "10 MHz（CLKin0）"); t(30, KY + 91, "観測所の基準", "xs")
box(20, KY + 112, 150, 94); t(30, KY + 132, "clk_wiz_adc", "tm")
t(30, KY + 150, "341.333 MHz → ADC", "lbO"); t(30, KY + 167, "256.000 MHz → DSP", "lbG")
t(30, KY + 186, "（proj021 のまま）", "xs")
path(f"M170,{KY+22} L180,{KY+22} L180,{rbot-30} L{RX-2},{rbot-30}", "wK")

ly = H - 18
t(20, ly, "凡例", "tm")
for k, (cls, lab, lc) in enumerate([("wB", "PS 側・AXI", "lbB"), ("wO", "ADC ドメイン 341 MHz", "lbO"),
                                    ("wG", "DSP ドメイン 256 MHz", "lbG"), ("wR", "レコード（v2）", "lbR"),
                                    ("wT", "時刻", "lbT"), ("wC", "共有の係数・ひねり係数", "lbC"), ("wK", "アナログ・クロック", "lb")]):
    x = 70 + k * 250
    path(f"M{x},{ly-4} L{x+40},{ly-4}", cls)
    t(x + 48, ly, lab, lc)

a("</svg>")
open("block_design.svg", "w", encoding="utf-8").write("\n".join(o) + "\n")
print("ok")
