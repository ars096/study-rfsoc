# SPDX-License-Identifier: BSD-3-Clause
# INTERFACE.md（v2）の図を docs/ に描く。`cd docs && python3 interface_figs.py`。INTERFACE.md の約束を変えたらここも直す
#   interface_overview.svg  全体の構成（PL ↔ PS ↔ 制御 PC。2.・4.・5.）
#   interface_addrmap.svg   アドレスの割り付け（コア 64 KiB・流れのブロック 1 KiB。2.4・2.5・3.・4.2）
#   interface_ring.svg      PL が書くリングとレコードの形（4.1・4.4・4.6）
#   interface_timing.svg    束ねの区切りと時刻の補正（5.1・5.2）
# 書き方は proj020/docs/block_design.py と同じ（SVG を文字列で組む。外部のライブラリは使わない）

FONT = "'Hiragino Sans','Noto Sans CJK JP','Yu Gothic',sans-serif"

STYLE = """
      .blk  { fill:#f8f8f8; stroke:#333; stroke-width:1.5; }
      .pl   { fill:#fbfbfb; stroke:#333; stroke-width:1.8; }
      .ps   { fill:#f6f9fd; stroke:#2f6fb5; stroke-width:1.8; }
      .pc   { fill:#f4faf6; stroke:#2e8b57; stroke-width:1.8; }
      .sub  { fill:#ffffff; stroke:#555; stroke-width:1.1; }
      .ddc  { fill:#fdf1f0; stroke:#c0392b; stroke-width:1.4; }
      .full { fill:#fff6ea; stroke:#d9822b; stroke-width:1.4; }
      .tim  { fill:#eef8f9; stroke:#0f7c8c; stroke-width:1.6; }
      .ring { fill:#fff8ef; stroke:#d9822b; stroke-width:1.8; }
      .note { fill:#fbf7ec; stroke:#b39a5a; stroke-width:1.2; }
      .diag { fill:#eeeeee; stroke:#777; stroke-width:1.2; stroke-dasharray:4 3; }
      .prom { fill:#eef5ff; stroke:#2f6fb5; stroke-width:1.4; }
      .kind { fill:#fdf1f0; stroke:#c0392b; stroke-width:1.2; }
      .rsv  { fill:#ffffff; stroke:#aaa; stroke-width:1.0; }
      .pad  { fill:#e6e6e6; stroke:#888; stroke-width:1.0; }
      .bad  { fill:#f3d3cf; stroke:#c0392b; stroke-width:1.4; stroke-dasharray:5 3; }
      .t    { font-size:15px; font-weight:bold; fill:#111; }
      .tm   { font-size:13px; font-weight:bold; fill:#111; }
      .s    { font-size:12px; fill:#333; }
      .xs   { font-size:11px; fill:#555; }
      .mono { font-size:11.5px; fill:#333; font-family:'Menlo','DejaVu Sans Mono',monospace; }
      .monob{ font-size:12px; fill:#111; font-weight:bold; font-family:'Menlo','DejaVu Sans Mono',monospace; }
      .ttl  { font-size:19px; font-weight:bold; fill:#111; }
      .wB   { stroke:#2f6fb5; stroke-width:2.0; fill:none; marker-end:url(#aB); }
      .wO   { stroke:#d9822b; stroke-width:3.0; fill:none; marker-end:url(#aO); }
      .wG   { stroke:#2e8b57; stroke-width:2.6; fill:none; marker-end:url(#aG); }
      .wR   { stroke:#c0392b; stroke-width:2.4; fill:none; marker-end:url(#aR); }
      .wT   { stroke:#0f7c8c; stroke-width:2.0; fill:none; marker-end:url(#aT); }
      .wK   { stroke:#555; stroke-width:1.4; fill:none; marker-end:url(#aK); }
      .wP   { stroke:#8a4fb0; stroke-width:1.4; fill:none; stroke-dasharray:4 3; marker-end:url(#aP); }
      .ln   { stroke:#888; stroke-width:1.0; fill:none; stroke-dasharray:3 3; }
      .lnK  { stroke:#333; stroke-width:1.2; fill:none; }
      .lnT  { stroke:#0f7c8c; stroke-width:2.0; fill:none; }
      .lbB  { font-size:11.5px; fill:#2f6fb5; }
      .lbO  { font-size:11.5px; fill:#b8661a; }
      .lbG  { font-size:11.5px; fill:#236b43; }
      .lbR  { font-size:11.5px; fill:#a93226; }
      .lbT  { font-size:11.5px; fill:#0b5d69; }
      .lbP  { font-size:11px; fill:#6d3a8e; }
"""

MARKERS = "".join(
    f'<marker id="a{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
    f'<path d="M0,0 L10,5 L0,10 z" fill="{c}"/></marker>'
    for k, c in dict(B="#2f6fb5", O="#d9822b", G="#2e8b57", R="#c0392b", T="#0f7c8c", K="#555", P="#8a4fb0").items())


class Svg:
    def __init__(self, w, h, title, note):
        self.w, self.h, self.o = w, h, []
        self.a(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" font-family="{FONT}">')
        self.a('  <!-- SPDX-License-Identifier: BSD-3-Clause -->')
        self.a(f'  <!-- {note}。docs/interface_figs.py で描いた。INTERFACE.md を変えたらここも直す -->')
        self.a(f'  <defs>{MARKERS}<style>{STYLE}</style></defs>')
        self.a(f'  <rect x="0" y="0" width="{w}" height="{h}" fill="#ffffff"/>')
        self.t(20, 32, title, "ttl")

    def a(self, s):
        self.o.append(s)

    def box(self, x, y, w, h, cls="blk", rx=4):
        self.a(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}"/>')

    def t(self, x, y, s, cls="s", anchor=None):
        an = f' text-anchor="{anchor}"' if anchor else ''
        s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        self.a(f'<text x="{x}" y="{y}" class="{cls}"{an}>{s}</text>')

    def tl(self, x, y, lines, cls="s", dy=16, anchor=None):
        for i, s in enumerate(lines):
            self.t(x, y + i * dy, s, cls, anchor)

    def p(self, d, cls):
        self.a(f'<path class="{cls}" d="{d}"/>')

    def save(self, fn):
        self.a('</svg>')
        with open(fn, "w", encoding="utf-8") as f:
            f.write("\n".join(self.o) + "\n")


# ===================================================================== 1. 全体
def overview():
    g = Svg(1520, 960, "INTERFACE v2 — 全体の構成（PL ↔ PS ↔ 制御 PC）", "INTERFACE.md の 2.・4.・5. の全体図")
    # ---- PL
    g.box(20, 50, 790, 830, "pl", 8)
    g.t(36, 74, "PL（ファブリック）", "t")
    g.box(40, 88, 560, 52, "tim")
    g.t(52, 108, "time_core_0", "tm")
    g.t(52, 128, "T（256 MHz のビート）・1PPS の錨・ARM / START_AT。全コアが同じビートで RUN・WRST・TP_ARM（1.）", "xs")
    ys = [168, 348, 490, 632]
    hs = [168, 128, 128, 128]
    labels = ["ADC_A", "ADC_B", "ADC_C", "ADC_D"]
    for i, (y, h) in enumerate(zip(ys, hs)):
        g.box(40, y, 520, h, "blk")
        g.t(52, y + 20, f"s45_core_{i}（{labels[i]}、64 KiB）", "tm")
        g.box(52, y + 32, 170, h - 44, "sub")
        g.tl(62, y + 52, ["前段", "ギアボックス・錨（TANCH）", "TP（1.024 ms の区切り）", "CORE_PORT = SMA のラベル"], "xs", 16)
        g.box(250, y + 32, 296, 36, "ddc")
        g.t(260, y + 55, "s = 0　DDC（窓）　PFB T = 4 ＋ FFT", "s")
        g.box(250, y + 74, 296, 36, "ddc")
        g.t(260, y + 97, "s = 1　DDC（窓）", "s")
        g.p(f"M222,{y + 50} L248,{y + 50}", "wK")
        g.p(f"M222,{y + 92} L248,{y + 92}", "wK")
        # 時刻のバス（左の縁）
        g.p(f"M30,{y + 10} L38,{y + 10}", "wT")
    g.box(250, ys[0] + 116, 296, 36, "full")
    g.t(260, ys[0] + 139, "s = 2　FULL（全帯域）　入力は SRC で選ぶ", "s")
    g.p(f"M40,114 L30,114 L30,{ys[3] + 10}", "lnT")
    g.p(f"M232,{ys[3] + 70} C236,{ys[3] - 120} 236,{ys[0] + 300} 248,{ys[0] + 140}", "wP")
    g.t(34, 160, "時刻のバス", "lbT")
    # 切り替え器
    g.box(620, 168, 50, 592, "sub")
    for k, s in enumerate("レコードの切り替え器"):
        g.t(645, 330 + k * 18, s, "s", "middle")
    g.t(645, 560, "tlast", "xs", "middle")
    g.t(645, 576, "で区切る", "xs", "middle")
    for i, (y, h) in enumerate(zip(ys, hs)):
        yy = [y + 50, y + 92] + ([y + 134] if i == 0 else [])
        for v in yy:
            g.p(f"M546,{v} L618,{v}", "wR")
        g.p(f"M137,{y + h - 12} L137,{y + h - 6} L618,{y + h - 6}", "wT")
    # リングの書き手
    g.box(690, 330, 108, 250, "ring")
    g.tl(744, 352, ["s45_ring_0", "（4.2）"], "tm", 16, "middle")
    g.tl(744, 400, ["司令", "空きの判定", "足りなければ", "丸ごと捨てる", "PAD・W の更新", "", "DataMover", "S2MM", "", "尾の CRC-32"], "xs", 15, "middle")
    g.p("M670,455 L688,455", "wR")
    # AXI4-Lite
    g.box(40, 790, 758, 72, "prom")
    g.t(52, 812, "AXI4-Lite（M_AXI_HPM0）— 制御と状態だけ（3.）", "tm")
    g.tl(52, 832, ["設定（WRST・RUN・CFG_ID・REC_CTRL）・seqlock の帳簿（試験と移行）・自己記述（IF_ID・NSTREAM・CAPS・BASE_BEATS）",
                   "s45_ring_0 の BASE・SIZE・EN・W（読む）・R（書く）・DROP_CNT・PEAK。スペクトルとスナップショットの記憶は出さない"], "xs", 16)
    for x in (300, 560, 744):
        g.p(f"M{x},790 L{x},{760 if x != 744 else 582}", "wB")
    # ---- PS
    g.box(840, 50, 400, 830, "ps", 8)
    g.t(856, 74, "PS（A53・PYNQ）", "t")
    g.box(860, 320, 360, 122, "ring")
    g.t(872, 340, "DDR のリング（PYNQ の allocate、SIZE = 2 の冪）", "tm")
    # 小さなリング
    x0, x1, yb = 872, 1208, 350
    g.box(x0, yb, x1 - x0, 22, "rsv", 2)
    g.box(x0 + 60, yb, 150, 22, "full", 2)
    g.box(x0 + 300, yb, 36, 22, "pad", 2)
    g.t(x0 + 135, yb + 16, "まだ読んでいないレコード", "xs", "middle")
    g.t(x0 + 318, yb + 16, "PAD", "xs", "middle")
    g.t(x0 + 60, yb + 36, "R", "monob", "middle")
    g.t(x0 + 210, yb + 36, "W", "monob", "middle")
    g.t(x0, yb + 56, "使用 = (W − R) mod 2³²　空き = SIZE − 使用", "xs")
    g.t(x0, yb + 76, "PL → S_AXI_HP0（HPC0 かは測って決める）。W は BRESP の後", "lbO")
    g.p("M798,380 L858,380", "wO")
    g.box(860, 452, 360, 240, "sub")
    g.t(872, 474, "specd — 取得のプロセス", "tm")
    g.tl(872, 498, ["① W を読む（ポーリング。割り込みは使わない）",
                    "② [R, W) の古いキャッシュを捨てて読む（PS の責任）",
                    "③ 頭と尾の SEQ・magic・CRC-32 を確かめる",
                    "④ 束ねる: u64 の和、n_sum = tint / 10.24 ms（5.1）",
                    "　 欠け・設定の混ざった束は丸ごと捨てて DROP",
                    "⑤ utc_ns = 実効の区間の始まり（5.2）",
                    "⑥ float32 に丸める（4.5）",
                    "⑦ R を書き戻す",
                    "TP は束ねずに 1.024 ms の区切りのまま",
                    "bits.json・較正の表（BIT_KIND・BIT_REV ごと）"], "xs", 18)
    g.p("M1040,442 L1040,451", "wO")
    g.p("M860,600 C820,600 830,826 800,826", "wB")
    g.t(806, 700, "R・設定", "lbB", "end")
    g.box(860, 712, 170, 52, "sub")
    g.tl(872, 732, ["s45ring（共有メモリ）", "proj018 と同じ"], "xs", 16)
    g.box(1050, 712, 170, 52, "sub")
    g.tl(1062, 732, ["specd — 通信のプロセス", "命令の口・送り出し"], "xs", 16)
    g.p("M945,692 L945,710", "wG")
    g.p("M1030,738 L1048,738", "wG")
    g.box(860, 90, 360, 210, "note")
    g.t(872, 112, "PS がコアを見つける（2.3）", "tm")
    g.tl(872, 134, [".hwh の IP の名前: s45_core_0〜3・time_core_0・s45_ring_0",
                    "IF_ID（IF_VER・BIT_KIND・BIT_REV）を読んで照合",
                    "IF_VER が知らない版なら止まる（7.）",
                    "NSTREAM・各流れの SID（KIND）・NCH・FRAME_BEATS",
                    "　 を読んで、bit の種類に依らずに動く",
                    "",
                    "LOAD bit=<名前>: bits.json にある bit だけ",
                    "（取得のプロセスを起動し直し、錨を打ち直す）"], "xs", 18)
    # ---- 制御 PC・受け側
    g.box(1270, 50, 230, 830, "pc", 8)
    g.t(1286, 74, "制御 PC・ダウンロード PC", "t")
    g.box(1288, 120, 196, 170, "sub")
    g.t(1300, 142, "制御 PC（命令）", "tm")
    g.tl(1300, 166, ["SET（A0.if・A0.bw・A0.ns・", "　 A0.shift・A2.src・tint）", "START・STOP・SEND",
                     "BITS・LOAD bit=…", "GET CAPS・STATUS", "SNAP（REC_CTRL の", "　 ONE | SNAP）"], "xs", 17)
    g.box(1288, 560, 196, 230, "sub")
    g.t(1300, 582, "ダウンロード PC（受け側）", "tm")
    g.tl(1300, 606, ["s45proto v2（6.）", "SPEC: float32（fmt 1）", "　 core・s・src・nch・df", "　 n_sum・dump_t・utc_ns",
                     "TP: 1.024 ms の区切り", "SNAP・EVENT（DROP・LOAD）", "", "ver 1 と 2 の両方を読む", "u64（fmt 0）は試験の照合だけ"], "xs", 17)
    g.p("M1286,210 C1250,210 1250,740 1222,740", "wB")
    g.t(1255, 236, "命令", "lbB", "middle")
    g.p("M1220,752 C1250,752 1260,680 1286,680", "wG")
    g.t(1290, 548, "1 GbE（予算 = 実測の 70 %）", "lbG")
    # 凡例
    g.box(20, 896, 1480, 50, "rsv")
    lx = 40
    for cls, lab in [("wR", "SPEC・SNAP のレコード"), ("wT", "TP のレコード・時刻のバス"), ("wO", "DDR のリング（W・R）"),
                     ("wG", "specd の中・ネットワーク"), ("wB", "AXI4-Lite の制御・命令"), ("wP", "SRC（全帯域の入力の選択）")]:
        g.p(f"M{lx},921 L{lx + 40},921", cls)
        g.t(lx + 48, 925, lab, "s")
        lx += 245
    g.save("interface_overview.svg")


# ===================================================================== 2. 番地
def bitfield(g, x, y, w, fields, title):
    """32 bit の語を [31:24][23:16][15:8][7:0] に割った図"""
    g.t(x, y - 6, title, "xs")
    cw = w / 4
    for k, (rng, name) in enumerate(fields):
        g.box(x + k * cw, y, cw, 34, "sub", 0)
        g.t(x + k * cw + cw / 2, y + 14, rng, "xs", "middle")
        g.t(x + k * cw + cw / 2, y + 29, name, "s", "middle")


def addrmap():
    g = Svg(1500, 900, "INTERFACE v2 — アドレスの割り付け（AXI4-Lite、制御と状態だけ）", "INTERFACE.md の 2.4・2.5・3.・4.2 の図")
    # ---- コア 64 KiB（縮尺ではない）
    X, Wc = 120, 250
    g.t(X, 68, "s45_core_i（64 KiB。縮尺ではない）", "tm")
    segs = [("0x0000", "コアの共通（2.4）", 56, "prom"),
            ("0x0100", "total power のレジスタ", 36, "prom"),
            ("0x0200", "（予約）", 36, "rsv"),
            ("0x2000", "TP のリング（移行用。4.6）", 46, "diag"),
            ("0x4000", "流れ s = 0（DDC）", 50, "ddc"),
            ("0x4400", "流れ s = 1（DDC）", 50, "ddc"),
            ("0x4800", "流れ s = 2（FULL、コア 0 だけ）", 50, "full"),
            ("0x4C00", "…（1 KiB ずつ）", 60, "rsv"),
            ("0xFC00", "流れ s = 47（最大）", 40, "rsv")]
    y = 82
    pos = {}
    for adr, name, h, cls in segs:
        g.box(X, y, Wc, h, cls, 0)
        g.t(X - 8, y + 14, adr, "mono", "end")
        g.t(X + 12, y + h / 2 + 5, name, "s")
        pos[adr] = (y, h)
        y += h
    g.t(X - 8, y + 4, "0xFFFF", "mono", "end")
    g.tl(X - 80, y + 36, ["流れのブロックは 0x4000 + 0x400·s（s = 0..47）。",
                          "SpW20 の 1 ADC に 20 窓も入る。",
                          "1 つのコアの中では DDC が s = 0 から、",
                          "FULL・SLICE はその後ろ。",
                          "",
                          "SAM45-Fine（proj021）:",
                          "　コア 0〜3 に DDC × 2（s = 0, 1）",
                          "　コア 0 に FULL × 1（s = 2、SRC で入力を選ぶ）",
                          "",
                          ".hwh の IP の名前で見つける（2.3）:",
                          "　s45_core_0〜3・time_core_0・s45_ring_0"], "xs", 17)

    # ---- 流れのブロック 1 KiB
    MX, MW = 470, 430
    y0 = 82
    g.t(MX, 68, "流れのブロック（1 KiB）", "tm")
    sy, sh = pos["0x4000"]
    g.p(f"M{X + Wc},{sy} L{MX},{y0}", "ln")
    g.p(f"M{X + Wc},{sy + sh} L{MX},{y0 + 760}", "ln")
    # 約束
    g.box(MX, y0, MW, 470, "prom", 0)
    g.t(MX + 10, y0 + 20, "0x000–0x0FF　約束（KIND に依らない。IF_VER で守る）", "tm")
    c1 = ["0x00 SID", "0x04 PARAM", "0x08 CTRL", "0x0C N_ACC", "0x10 N_DUMP", "0x14 SHIFT", "0x18 FLAGS",
          "0x1C SEQ", "0x20 NCH", "0x24 FRAME_BEATS", "0x28 SRC", "0x2C CFG_ID", "0x30 RUN_CFG", "0x34 WRST_CFG",
          "0x38 RUN_SHIFT", "0x3C DUMP_K"]
    c2 = ["0x40 DUMP_F0_LO/HI", "0x48 DUMP_N", "0x4C DUMP_SAT", "0x50 DUMP_T_LO/HI", "0x58 DUMP_H", "0x5C DUMP_CFG",
          "0x60 RUN_T_LO/HI", "0x68 RUN_F0_LO/HI", "0x70 FIN_LO/HI", "0x78 FOUT_LO/HI", "0x80 NFFT_MIN_MAX",
          "0x84 REC_CTRL", "0x88 REC_LATE", "0x8C– 予約"]
    g.tl(MX + 14, y0 + 46, c1, "mono", 21)
    g.tl(MX + 220, y0 + 46, c2, "mono", 21)
    g.tl(MX + 14, y0 + 400, ["DUMP_* は SEQ と同じ commit で切り替わる（seqlock: SEQ → 中身 → SEQ）。",
                             "REC_CTRL: [0] ALL（全部のダンプをレコードに）/ [1] ONE（次の 1 個だけ）/",
                             "　　　　　[2] SNAP（ONE のダンプにスナップショットを付ける）。4.6",
                             "0x8C– は時刻の補正の定数などを足す場所（足すだけなら IF_VER は上げない）"], "xs", 16)
    # 種類に固有
    g.box(MX, y0 + 470, MW, 130, "kind", 0)
    g.t(MX + 10, y0 + 490, "0x100–0x1FF　種類に固有の設定", "tm")
    g.tl(MX + 14, y0 + 514, ["DDC:  WK・WDPHI・WNS・WCUR・WCUR_DPHI・WSTART・",
                             "　　　NS_MIN_MAX・WRST_T（次の WRST で効く）",
                             "SLICE: 点数・切り出しの最初の ch",
                             "FULL:  なし"], "s", 20)
    # 診断
    g.box(MX, y0 + 600, MW, 160, "diag", 0)
    g.t(MX + 10, y0 + 620, "0x200–0x3FF　診断（約束の外）", "tm")
    g.tl(MX + 14, y0 + 644, ["中身を変えても IF_VER を上げない。specd の約束の道は読まない",
                             "（試験の道具だけが KIND と PROJ を見て読む）",
                             "DDC:  PFB_SAT・DDC_SAT・WS_STALL・WS_RDY0・DDC_OVR・WRST_CNT",
                             "FULL: DIAG_*・SRST・GRST・INJ・RAW_*・ST_*",
                             "消したもの: SNAP_F・BANK・窓ごとの ID・WIDX・NW・SNAP_SEL・FULL_SEL"], "xs", 19)

    # ---- 右: コアの共通・リング・ID
    RX, RW = 950, 520
    g.box(RX, 82, RW, 236, "prom", 0)
    g.t(RX + 10, 102, "コアの共通（s45_core_i の 0x0000–0x00FF）", "tm")
    g.tl(RX + 14, 126, ["0x00 IF_ID", "0x04 PROJ", "0x08 NSTREAM", "0x0C CAPS", "0x10 BASE_BEATS", "0x14 BUILD", "0x18 CORE_PORT", "0x20– 今の表 A"], "mono", 21)
    g.tl(RX + 170, 126, ["下の図", "作った proj と rev（照合には使わない）", "このコアの流れの数",
                         "[0] DMA のレコード / [1] TP をレコードで / [2] SNAP …", "基本の単位 10.24 ms = 2,621,440 ビート",
                         "ビルドの指紋", "[3:0] ADC（SMA のラベル）/ タイル / スライス",
                         "TP_RUN・TANCH・TFIN・GB_*・ANCH_*・OVR_CNT…"], "xs", 21)
    bitfield(g, RX + 10, 352, 500, [("[31:24]", "IF_VER = 2"), ("[23:16]", "BIT_KIND"), ("[15:8]", "BIT_REV"), ("[7:0]", "CORE_KIND")],
             "IF_ID（コア・time_core・リングの 0x00）。CORE_KIND: 1 ADC のコア / 2 time_core / 3 リング")
    bitfield(g, RX + 10, 418, 500, [("[31:24]", "IF_VER"), ("[23:16]", "KIND"), ("[15:8]", "s"), ("[7:0]", "0")],
             "SID（流れのブロックの 0x00）。KIND: 1 FULL / 2 SLICE / 3 DDC")
    g.box(RX, 470, RW, 76, "note", 0)
    g.t(RX + 10, 490, "BIT_KIND（BITS.md の 9 本。proj の番号とは別の固定の番号）", "tm")
    g.tl(RX + 14, 512, ["1 SAM45-Wide　2 SAM45-Fine　3 2G　4 512M　5 256M",
                        "6 SpW6　7 SpW8　8 SpW20　9 Fine"], "s", 18)
    # リング
    g.box(RX, 566, RW, 276, "ring", 0)
    g.t(RX + 10, 586, "s45_ring_0（4 KiB、CORE_KIND = 3。4.2）", "tm")
    g.tl(RX + 14, 610, ["0x00 IF_ID", "0x04 CTRL", "0x08 BASE_LO/HI", "0x10 SIZE", "0x14 W", "0x18 R", "0x1C DROP_CNT",
                        "0x20 REC_CNT", "0x24 PEAK", "0x28 ERR_STAT"], "mono", 21)
    g.tl(RX + 170, 610, ["", "W: [0] EN / [1] RST。R: [0] EN / [1] 書いている / [2] ERR",
                         "64 バイト境界。EN = 0 のときだけ書ける", "バイト、2 の冪（≦ 1 GiB）",
                         "R: 書き終えた位置（バイト、下位 32 bit）", "RW: PS が読み終えた位置を書く",
                         "捨てたレコード（空きなし ＋ 出し切れず）", "書いたレコード（PAD を除く）",
                         "使用の最大（余裕を測るため）", "最初の誤りの BRESP と位置"], "xs", 21)
    g.save("interface_addrmap.svg")


# ===================================================================== 3. リングとレコード
def words(g, x, y, cw, rows, title):
    """u64 の語を 8 バイトの升に割って描く。rows = [(語の番号, [(バイト数, 名前, cls), ...]), ...]"""
    g.t(x, y - 24, title, "tm")
    for b in range(8):
        g.t(x + 40 + b * cw + cw / 2, y - 6, str(b), "xs", "middle")
    for r, (wn, fields) in enumerate(rows):
        yy = y + r * 30
        g.t(x + 30, yy + 20, wn, "mono", "end")
        bx = x + 40
        for nb, name, cls in fields:
            g.box(bx, yy, nb * cw, 30, cls, 0)
            g.t(bx + nb * cw / 2, yy + 20, name, "s", "middle")
            bx += nb * cw


def ring():
    g = Svg(1500, 860, "INTERFACE v2 — PL が書くリングとレコードの形", "INTERFACE.md の 4.1・4.4・4.6 の図")
    # ---- リング
    g.t(20, 66, "DDR のリング（4.1）— 書き手は PL（s45_ring_0）1 つ、読み手は specd の取得のプロセス 1 つ。proj018 の s45ring と同じ約束", "tm")
    y, h = 140, 52
    segs = [(80, 250, "full", "SPEC c2 s1"), (250, 600, "rsv", "空き（PL がここに書く。読み終えた所も空きになる）"),
            (600, 760, "full", "SPEC c0 s0"), (760, 920, "full", "SPEC c0 s1"), (920, 990, "tim", "TP c1"),
            (990, 1150, "full", "SPEC c0 s2"), (1150, 1210, "pad", "PAD")]
    for x0, x1, cls, lab in segs:
        g.box(x0, y, x1 - x0, h, cls, 0)
        g.t((x0 + x1) / 2, y + h / 2 + 5, lab, "s", "middle")
    g.t(80, y - 8, "BASE", "mono")
    g.t(1210, y - 8, "BASE + SIZE", "mono", "end")
    g.p(f"M1210,{y + h + 4} C1240,{y + h + 70} 60,{y + h + 70} 80,{y + h + 6}", "wK")
    g.t(645, y + h + 76, "端に入らないときは PAD（type 0）で埋めて頭に戻る（SIZE は 2 の冪・長さは 64 バイトの倍数なので、端までは必ず 64 バイト以上）", "xs", "middle")
    # W と R
    g.p(f"M250,{y - 34} L250,{y - 2}", "wO")
    g.t(250, y - 40, "W（書き終えた位置）", "lbO", "middle")
    g.p(f"M600,{y - 34} L600,{y - 2}", "wB")
    g.t(600, y - 40, "R（PS が読み終えた位置）", "lbB", "middle")
    g.tl(80, 300, ["橙 = まだ読まれていないレコード（R から W まで。端で頭に戻る）。使用 = (W − R) mod 2³²　空き = SIZE − 使用　番地 = BASE + (位置 mod SIZE)",
                   "W・R は単調に増えるバイト数の下位 32 bit（1 回の読みで済む）"], "s", 18)
    g.box(1240, 84, 240, 250, "note")
    g.t(1252, 104, "約束（4.1）", "tm")
    g.tl(1252, 126, ["① W はレコードの BRESP を全部", "　 受けてから進む",
                     "② 書く前に 空き ≧ 長さ。足りなけ", "　 れば丸ごと捨てて DROP_CNT++",
                     "③ 流れの中は SEQ の順。流れの", "　 間の順は約束しない",
                     "④ 次のダンプが閉じる前に出し切る", "　 （だめなら捨てて REC_LATE++）",
                     "⑤ PS: W を読む → キャッシュを捨て", "　 る → 確かめる → 束ねる → R"], "xs", 20)

    # ---- レコード
    Y = 380
    g.t(20, Y, "レコード（4.4・4.6）— 長さは 64 バイトの倍数。リトルエンディアン", "tm")
    yb = Y + 46
    g.box(80, yb, 260, 44, "prom", 0)
    g.t(210, yb + 27, "頭 64 バイト", "tm", "middle")
    g.box(340, yb, 820, 44, "full", 0)
    g.t(750, yb + 19, "中身（64 バイトの倍数に詰める）", "tm", "middle")
    g.t(750, yb + 36, "SPEC: NCH × u64（FFT の ch の順、生の積分値）　TP: 16 バイト × DUMP_N　SNAP: FULL 8192 × i16 / DDC NFFT × (re, im) i32", "xs", "middle")
    g.box(1160, yb, 300, 44, "tim", 0)
    g.t(1310, yb + 27, "尾 64 バイト", "tm", "middle")
    g.p(f"M80,{yb - 8} L80,{yb - 16} L1160,{yb - 16} L1160,{yb - 8}", "lnK")
    g.t(620, yb - 22, "CRC-32（zlib.crc32 と同じ式）の範囲 = 頭 ＋ 中身", "s", "middle")
    cw = 66
    hx, hy = 80, yb + 116
    words(g, hx, hy, cw, [
        ("0", [(4, 'magic "S45R"', "prom"), (1, "rec_ver", "sub"), (1, "type", "sub"), (1, "core", "sub"), (1, "s", "sub")]),
        ("1", [(4, "SEQ", "sub"), (4, "DUMP_K", "sub")]),
        ("2", [(8, "DUMP_F0", "sub")]),
        ("3", [(8, "DUMP_T（ビート）", "sub")]),
        ("4", [(1, "log2 NFFT", "sub"), (1, "NS", "sub"), (1, "SHIFT", "sub"), (1, "G", "sub"), (1, "fmt", "sub"), (1, "src", "sub"), (2, "DUMP_H", "sub")]),
        ("5", [(4, "DUMP_N", "sub"), (4, "DUMP_SAT", "sub")]),
        ("6", [(4, "DUMP_CFG", "sub"), (4, "FLAGS", "sub")]),
        ("7", [(4, "中身のバイト数", "sub"), (4, "予約", "rsv")]),
    ], "頭（語 0〜7、上の数字はバイト）")
    g.p(f"M80,{yb + 44} L{hx + 40},{hy - 40}", "ln")
    g.p(f"M340,{yb + 44} L{hx + 40 + 8 * cw},{hy - 40}", "ln")
    tx = 880
    words(g, tx, hy, cw, [
        ("0", [(4, 'magic "S45E"', "tim"), (4, "SEQ の写し", "sub")]),
        ("1", [(4, "CRC-32", "sub"), (4, "予約", "rsv")]),
        ("2–7", [(8, "0", "rsv")]),
    ], "尾（語 0〜7）")
    g.p(f"M1160,{yb + 44} L{tx + 40},{hy - 40}", "ln")
    g.p(f"M1460,{yb + 44} L{tx + 40 + 8 * cw},{hy - 40}", "ln")
    g.tl(tx, hy + 120, ["PS は頭と尾の SEQ・magic・CRC を確かめてから束ねる。",
                        "合わなければそのレコードを捨て、ERROR の EVENT（黙って使わない）。",
                        "拾うもの: 古いキャッシュの行・書きかけ・DMA の誤り。",
                        "全部のレコードで確かめられるかは proj021 で測る",
                        "（間に合わない bit は間引き、どれだけ確かめたかを STATUS に）。",
                        "",
                        "ネットワークへは specd が float32 にした中身で",
                        "新しい CRC を付ける（s45proto の頭、今と同じ）。"], "xs", 17)
    g.tl(hx, hy + 262, ["type: 0 PAD（語 7 = 端までのバイト数）・1 SPEC・2 TP（s = 0xFF、ADC ごとに区切り 10 個）・4 SNAP（SPEC の直後に同じ SEQ）",
                        "頭の項目は今の DUMP_* と同じ値（1 つのレコードの中で揃っていることを PL が保証する。seqlock の代わり）。",
                        "fmt はリングの中では常に 0（u64 の生）。src = そのダンプの入力の ADC。欠け = SEQ の飛び"], "xs", 17)
    g.save("interface_ring.svg")


# ===================================================================== 4. 束ねと時刻
def timing():
    g = Svg(1500, 900, "INTERFACE v2 — 束ねの区切りと時刻の補正", "INTERFACE.md の 5.1・5.2 の図")
    g.t(20, 66, "束ねの区切り（5.1）— 例: tint = 40.96 ms・n_sum = 4（BASE = 10.24 ms = 5G）", "tm")
    X0, B = 170, 110            # START_AT の位置・BASE 1 個の幅
    n = 11
    xe = X0 + n * B
    # 軸
    ya = 108
    g.p(f"M{X0 - 30},{ya} L{xe + 50},{ya}", "wK")
    for k in range(n * 5 + 1):
        x = X0 + k * B / 5
        g.p(f"M{x},{ya - 4} L{x},{ya + 4}", "lnK")
    for j in range(3):
        x = X0 + j * 4 * B
        g.p(f"M{x},{ya - 14} L{x},{ya + 330}", "ln")
        g.t(x, ya - 18, ["START_AT = T の tint の倍数", "T = (j0 + 1)·tint", "T = (j0 + 2)·tint"][j], "xs", "middle")
    g.t(xe + 54, ya + 4, "T", "monob")
    g.t(X0 + B / 10, ya + 20, "G", "xs", "middle")
    g.t(20, ya + 4, "T（ビート）", "s")
    # 流れ
    rows = [("DDC s = 0（NS 1）", 150, 5, None), ("FULL s = 2", 206, 11, 6)]
    for name, yy, off, miss in rows:
        g.t(20, yy + 22, name, "s")
        for k in range(n):
            x = X0 + k * B + off
            cls = "bad" if k == miss else ("ddc" if off == 5 else "full")
            g.box(x, yy, B - 4, 34, cls, 2)
            g.t(x + (B - 4) / 2, yy + 22, "欠け" if k == miss else (f"m0+{k}" if k else "m0"), "s", "middle")
    g.p(f"M{X0},{150 - 6} L{X0 + 5},{150 - 6}", "lnK")
    g.t(X0 + 8, 150 - 8, "r（KIND・NS ごとに一定。大きく描いた）", "xs")
    # 束
    for name, yy, cls, bad in [("束 DDC", 264, "ddc", None), ("束 FULL", 312, "full", 1)]:
        g.t(20, yy + 24, name, "s")
        for j in range(3):
            x0 = X0 + j * 4 * B + 2
            w = 4 * B - 8 if j < 2 else 3 * B - 8
            c = "bad" if (j == bad or j == 2) else cls
            g.box(x0, yy, w, 38, c, 3)
            lab = f"j0{'+' + str(j) if j else ''}"
            if j == 2:
                lab += "：STOP の前の半端な束 → 捨てる"
            elif j == bad:
                lab += "：欠けがある → 束ごと捨てて DROP の EVENT"
            else:
                lab += "：4 個そろった → u64 の和 → float32"
            g.t(x0 + w / 2, yy + 24, lab, "s", "middle")
    xs = X0 + 11 * B + 14
    g.p(f"M{xs},{140} L{xs},{356}", "lnK")
    g.t(xs + 6, 370, "STOP", "monob")
    g.box(20, 384, 1460, 112, "note")
    g.tl(34, 406, ["① m = round(DUMP_T / BASE_BEATS)（T の原点から。KIND・NS ごとのずれ r ≦ 5,344 ビートは BASE の半分より十分小さい）",
                   "② 見張り: r = DUMP_T − m·BASE_BEATS が 1 回の RUN の中で一定（±1 ビート）、表があれば F(KIND, NS) と ±1 ビート。合わなければ ERROR、その流れは束ねない",
                   "③ 束 j = floor(m / n_sum)。tint は 1 回の取得で全体に 1 つ。specd は RUN・WRST・TP_ARM の START_AT を T の tint の倍数に置く（G の格子にも乗る）",
                   "④ そろう条件: n_sum 個すべて（SEQ の飛びなし）・DUMP_CFG・SRC・NFFT・NS・SHIFT が同じ・DUMP_N = BASE / L。一つでも欠けたら束ごと捨てる",
                   "⑤ 束ね方: 中身は u64 の和 → float32、DUMP_SAT は和、FLAGS・DUMP_H は OR、dump_t は最初のダンプ、単位の式の N_ACC は ΣDUMP_N"], "xs", 20)

    # ---- 時刻の補正
    Y = 530
    g.t(20, Y, "時刻の補正（5.2）— utc_ns = 実効の区間の始まり（区間の重心 = utc_ns + tint/2）", "tm")
    # 遅れの鎖
    cy = Y + 40
    boxes = [(20, "ADC のサンプル", "（求めたい時刻）"), (330, "コアの入口", "ギアボックスの出口"), (640, "wspec に入る", "DUMP_T のビート（DDC）")]
    for x, a1, a2 in boxes:
        g.box(x, cy, 200, 52, "sub")
        g.t(x + 100, cy + 22, a1, "tm", "middle")
        g.t(x + 100, cy + 40, a2, "xs", "middle")
    g.p(f"M222,{cy + 26} L328,{cy + 26}", "wT")
    g.tl(275, cy - 6, ["adc_to_core[src]"], "lbT", 14, "middle")
    g.t(275, cy + 70, "122〜125 ns（F-2 の実測）", "xs", "middle")
    g.p(f"M532,{cy + 26} L638,{cy + 26}", "wT")
    g.t(585, cy - 6, "D(NS)", "lbT", "middle")
    g.t(585, cy + 70, "PFB・DDC の遅れ（sim）", "xs", "middle")
    g.t(430, cy + 92, "FULL は DUMP_T = コアの入口のビート（D = 0）", "xs", "middle")
    # 式
    g.box(20, cy + 110, 820, 150, "prom")
    g.t(34, cy + 136, "utc_ns = beat_utc(dump_t) − adc_to_core[src] − D_eff(KIND, NS)", "monob")
    g.tl(34, cy + 162, ["D_eff:  FULL = 0　/　DDC（PFB T = 4）= D(NS) ＋ 1.5·L(NS)　/　SLICE = 作るときに決める",
                        "1.5·L: NS 1 で 24 µs・NS 6 で 768 µs・NS 8 で 3.07 ms（10.24 ms の 30 %）",
                        "定数は PS の表に (BIT_KIND, BIT_REV) ごと（bits.json が指す較正ファイル）。無ければ「未較正」と明示",
                        "生の dump_t（ビート）も s45proto v2 に残す。幅の違う窓の差 X(NS) ≦ 10 µs は受け入れ済み（10/3）"], "xs", 20)
    # PFB の重心
    PX, PY, F = 900, Y + 40, 50   # フレーム 1 個の幅
    N = 8
    g.t(PX, PY - 6, "ダンプ 1 個（N フレーム）の入力の重み", "tm")
    base = PY + 190
    g.p(f"M{PX},{base} L{PX + (N + 4) * F + 10},{base}", "wK")
    fx0 = PX + 3 * F
    for k in range(-3, N + 1):
        x = fx0 + k * F
        g.p(f"M{x},{base - 3} L{x},{base + 3}", "lnK")
    g.t(fx0, base + 18, "F0", "mono", "middle")
    g.t(fx0 - 3 * F, base + 18, "F0 − 3", "mono", "middle")
    g.t(fx0 + N * F, base + 18, "F0 + N", "mono", "middle")
    g.t(PX + (N + 4) * F + 14, base + 4, "入力のフレーム", "xs")
    top = base - 120
    # 矩形
    g.a(f'<rect x="{fx0}" y="{top}" width="{N * F}" height="120" fill="none" stroke="#555" stroke-width="1.4" stroke-dasharray="5 3"/>')
    # PFB（台形）
    pts = f"{fx0 - 3 * F},{base} {fx0},{top} {fx0 + (N - 3) * F},{top} {fx0 + N * F},{base}"
    g.a(f'<polygon points="{pts}" fill="#c0392b" fill-opacity="0.18" stroke="#c0392b" stroke-width="1.6"/>')
    cr = fx0 + N * F / 2
    cp = cr - 1.5 * F
    g.p(f"M{cr},{top - 26} L{cr},{base}", "lnK")
    g.p(f"M{cp},{top - 26} L{cp},{base}", "wR")
    g.t(cr + 4, top - 30, "矩形の重心", "xs")
    g.t(cp - 4, top - 30, "PFB の重心", "lbR", "end")
    g.p(f"M{cr},{top - 12} L{cp + 2},{top - 12}", "wR")
    g.t((cr + cp) / 2, top - 16 + 30, "1.5·L", "lbR", "middle")
    g.tl(PX, base + 44, ["PFB の出口 k は入力 k − 3 … k に重みを持つので、ダンプの入力は F0 − 3 から始まり、",
                         "重心は矩形より 1.5·L 前に来る。utc_ns はこのずれも引いた「実効の区間の始まり」で、",
                         "受け側は KIND を知らなくても「utc_ns ＋ tint/2 = 中心」でアンテナの時系列と結べる"], "xs", 17)
    g.save("interface_timing.svg")


if __name__ == "__main__":
    import sys
    which = sys.argv[1:] or ["overview", "addrmap", "ring", "timing"]
    for name in which:
        globals()[name]()
