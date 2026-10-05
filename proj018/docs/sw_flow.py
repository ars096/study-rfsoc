# SPDX-License-Identifier: BSD-3-Clause
# proj018 のソフトウェアの制御とデータの流れの図 docs/sw_flow.svg を作る。`cd docs && python3 sw_flow.py`。
# specd.py・s45acq.py・s45ring.py・s45proto.py の形を変えたらここも直す。描き方（箱・線・色）は proj017 の docs/block_design.py に合わせた
W, H = 1880, 1060
DX = 90           # PS・PL を右へずらす（PC との間に線の名札を置く）
o = []
def a(s): o.append(s)
def box(x, y, w, h, cls="blk", style=""):
    a(f'<rect class="{cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="4"' + (f' style="{style}"' if style else '') + '/>')
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
  <!-- proj018 のソフトウェアの制御とデータの流れ。docs/sw_flow.py で描いた -->
  <defs>
    <marker id="aB" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#2f6fb5"/></marker>
    <marker id="aO" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#d9822b"/></marker>
    <marker id="aG" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#2e8b57"/></marker>
    <marker id="aK" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#555"/></marker>
    <marker id="aP" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#8a4fb0"/></marker>
    <marker id="aT" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#0f7c8c"/></marker>
    <style>
      .blk  {{ fill:#f8f8f8; stroke:#333; stroke-width:1.5; }}
      .ps   {{ fill:#f4f8fd; stroke:#2f6fb5; stroke-width:2.2; }}
      .par  {{ fill:#ffffff; stroke:#2f6fb5; stroke-width:1.6; }}
      .chd  {{ fill:#fff8f0; stroke:#d9822b; stroke-width:1.8; }}
      .sub  {{ fill:#ffffff; stroke:#999; stroke-width:1.0; }}
      .ring {{ fill:#f1f9f4; stroke:#2e8b57; stroke-width:2.0; }}
      .pl   {{ fill:#fdf1f0; stroke:#c0392b; stroke-width:2.2; }}
      .plsub {{ fill:#ffffff; stroke:#c0392b; stroke-width:1.1; }}
      .tim  {{ fill:#eef8f9; stroke:#0f7c8c; stroke-width:1.4; }}
      .ext  {{ fill:#eeeeee; stroke:#777; stroke-width:1.2; stroke-dasharray:4 3; }}
      .note {{ fill:#fbf7ec; stroke:#b39a5a; stroke-width:1.2; }}
      .t    {{ font-size:14px; font-weight:bold; fill:#111; }}
      .tm   {{ font-size:12.5px; font-weight:bold; fill:#111; }}
      .s    {{ font-size:11.5px; fill:#333; }}
      .xs   {{ font-size:10.5px; fill:#555; }}
      .wB   {{ stroke:#2f6fb5; stroke-width:2.0; fill:none; marker-end:url(#aB); }}
      .wBd  {{ stroke:#2f6fb5; stroke-width:1.3; fill:none; stroke-dasharray:5 3; marker-end:url(#aB); }}
      .wO   {{ stroke:#d9822b; stroke-width:2.8; fill:none; marker-end:url(#aO); }}
      .wG   {{ stroke:#2e8b57; stroke-width:1.8; fill:none; stroke-dasharray:6 3; marker-end:url(#aG); }}
      .wK   {{ stroke:#555; stroke-width:1.5; fill:none; marker-end:url(#aK); }}
      .wP   {{ stroke:#8a4fb0; stroke-width:1.3; fill:none; stroke-dasharray:4 3; marker-end:url(#aP); }}
      .wT   {{ stroke:#0f7c8c; stroke-width:2.0; fill:none; marker-end:url(#aT); }}
      .lbB  {{ font-size:11px; fill:#2f6fb5; }}
      .lbO  {{ font-size:11px; fill:#b8661a; }}
      .lbG  {{ font-size:11px; fill:#236b43; }}
      .lbP  {{ font-size:10.5px; fill:#6d3a8e; }}
      .lbT  {{ font-size:11px; fill:#0b5d69; }}
      .lbK  {{ font-size:11px; fill:#444; }}
    </style>
  </defs>
  <rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>''')

t(20, 30, "proj018 データ取得サーバー（PS）の制御とデータの流れ: specd.py（通信）＋ s45acq.py（取得）＋ s45ring.py（溜まり）、PL は proj017.bit（SAM45-Fine）",
  style="font-size:17px;font-weight:bold;fill:#111")
t(20, 51, "青 = 制御（命令・応答）、橙 = データ（記録）、緑の破線 = ACK（受け取った記録を溜まりから消す）、紫の破線 = EVENT・DROP、青緑 = 時刻。"
          "取得と通信は別のプロセス（GIL を取り合わない）")

# ---------------- 外の PC ----------------
box(30, 120, 270, 175, "ext")
t(44, 143, "制御 PC", "t")
t(44, 163, "specctl.py（1 命令 1 行・--wait-idle）")
t(44, 181, "または s45client.py の S45（Jupyter）")
t(44, 203, "ID・STATUS・GET・SET・ANCHOR", "xs")
t(44, 219, "START [at= n= force=]・STOP", "xs")
t(44, 235, "SEND ON [from=]・SEND OFF・CLEAR", "xs")
t(44, 251, "SHUTDOWN confirm=1・BYE", "xs")
t(44, 275, "nc <board> 51000 でも打てる", "xs")

box(30, 395, 270, 205, "ext")
t(44, 418, "ダウンロード PC", "t")
t(44, 438, "specrecv.py（受けて書く・照合・ACK）")
t(44, 456, "または s45client.py（裏のスレッドで受ける）")
t(44, 478, "照合: 記録ごとの CRC-32", "xs")
t(44, 494, "seq の欠け ＝ DROP / SKIP の範囲（説明のない欠け 0）", "xs")
t(44, 510, "(ADC, 窓) ごとの DUMP_K ＋1・DUMP_T ＋N_ACC·L", "xs")
t(44, 526, "TP の区切り ＋262,144 ビート", "xs")
t(44, 542, "送り直された記録（seq ≦ 最後）は捨てる（重複を除く）", "xs")
t(44, 566, "書く: 受けた記録をそのまま続けた .s45", "xs")
t(44, 582, "（specrecv.py --file で読み直せる）", "xs")

# ---------------- PS ----------------
a(f'<g transform="translate({DX},0)">')
box(340, 75, 935, 830, "ps")
t(354, 97, "ボードの PS（PYNQ / Linux、A53 × 4）", "t")

# 親: specd
box(360, 112, 420, 590, "par")
t(374, 134, "specd.py（親のプロセス・通信）", "tm")
t(374, 150, "PYNQ を import しない。起動時に PID を出す", "xs")
box(375, 162, 390, 128, "sub")
t(387, 181, "制御の口（スレッド）TCP 51000・同時に 1 接続", "s", style="font-weight:bold")
t(387, 198, "1 行の命令 → 解釈 → 応答 1 行 OK key=val / ERR 符号", "xs")
t(387, 214, "2 つ目の接続は ERR BUSY で切る", "xs")
t(387, 230, "SEND・CLEAR はここで（溜まりの読み手の側）", "xs")
t(387, 246, "SET・START・STOP・STATUS などは取得へ渡す", "xs")
t(387, 262, "STATUS = 取得の数 ＋ 溜まり・送信の数", "xs")
t(387, 278, "制御 PC が切れても取得は止めない", "xs")
box(375, 305, 390, 145, "sub")
t(387, 324, "送り（スレッド）＋ データの口 TCP 51001・1 接続", "s", style="font-weight:bold")
t(387, 341, "SEND ON の間: 溜まりの送る位置 s の次の記録を", "xs")
t(387, 357, "  sendall（memoryview のまま、コピーしない）→ s を進める", "xs")
t(387, 373, "送ったが ACK の無い記録 (seq, 終わり) を控える", "xs")
t(387, 389, "切れたら s を r に戻す（次の接続で送り直す）", "xs")
t(387, 405, "from=now・CLEAR: 溜まりを捨て、SKIP（seq 0）を先に送る", "xs")
t(387, 421, "送れないまま 10 s（--send-timeout）→ 切る", "xs")
t(387, 437, "2 つ目の受け側には BUSY の EVENT を送って切る", "xs")
box(375, 465, 390, 75, "sub")
t(387, 484, "ACK の受け（スレッド）", "s", style="font-weight:bold")
t(387, 501, "受け側から <Q（最後の seq）だけが来る", "xs")
t(387, 517, "その seq までの控えを外し、溜まりの r を進める", "xs")
t(387, 533, "0 バイト（切断）→ 送りの控えを捨て、s を r に", "xs")
box(375, 555, 390, 132, "sub")
t(387, 574, "止める（主のスレッド）", "s", style="font-weight:bold")
t(387, 591, "Ctrl-C・TERM（明示して受ける）・SHUTDOWN confirm=1", "xs")
t(387, 607, "→ 取得に quit（RUN なら STOP してから抜ける）", "xs")
t(387, 623, "→ 来なければ terminate → kill", "xs")
t(387, 639, "→ 共有メモリを片付けて os._exit", "xs")
t(387, 655, "取得のプロセスは SIGINT を無視（親だけが受ける）", "xs")
t(387, 671, "起動: fork（PYNQ を読む前）→ 準備完了を待つ", "xs")

# 子: s45acq
box(850, 112, 405, 590, "chd")
t(864, 134, "s45acq.py（子のプロセス・取得）", "tm")
t(864, 150, "CPU 3 に固定・SCHED_FIFO 10・gc.freeze ＋ gc.disable", "xs")
box(865, 162, 375, 110, "sub")
t(877, 181, "命令の処理（読み出しの環の合間に、パイプを覗く）", "s", style="font-weight:bold")
t(877, 198, "SET: 全部確かめてから一度に（IDLE だけ）", "xs")
t(877, 214, "START: 格子の点で一斉に WRST → N_ACC・SHIFT・TP_N", "xs")
t(877, 230, "  → 窓 8・TP 4 本を格子の START_AT で同時に ARM", "xs")
t(877, 246, "STOP: RUN なら止める、ARMED なら DISARM ＋ 取り消し", "xs")
t(877, 262, "状態: IDLE → ARMED（発火待ち）→ RUN → IDLE / ERROR", "xs")
box(865, 287, 375, 114, "sub")
t(877, 306, "HwBackend（PYNQ）", "s", style="font-weight:bold")
t(877, 323, "setup_clocks（10 MHz）→ import xrfdc → Overlay", "xs")
t(877, 339, "ID の照合（窓・ADC の共通・time_core・TP_PARAM）", "xs")
t(877, 355, "timebase の錨（1PPS と UTC の秒）", "xs")
t(877, 371, "MMIO（AXI4-Lite）で読み書き", "xs")
t(877, 387, "（--fake: FakeBackend が同じ間隔・同じ形の記録を作る）", "xs")

box(865, 416, 375, 128, "sub")
t(877, 435, "読み出しの環（RUN の間、1 周の後に 3 ms 寝る）", "s", style="font-weight:bold")
t(877, 452, "窓 × 8: SEQ が進んだら seqlock で読む", "xs")
t(877, 468, "  （SEQ → メタ・DUMP_SAT・FLAGS・4096 ch → SEQ）", "xs")
t(877, 484, "TP × 4: リングを TP_WP まで（落としは数える）", "xs")
t(877, 500, "時刻: 錨の式で UTC。PPS の照合は 1 秒に 1 回", "xs")
t(877, 516, "数: miss・kgap・tp_lost・健全性の OR・飽和・1 周の時間", "xs")
t(877, 532, "（リストに溜めない。1 周の時間は固定の度数分布）", "xs")
box(865, 559, 375, 128, "sub")
t(877, 578, "記録にする（s45proto）", "s", style="font-weight:bold")
t(877, 595, "SPEC: メタ ＋ 4096 ch の uint64（IF の昇順に並べ替え）", "xs")
t(877, 611, "TP: ADC ごとに 40 区切り（40.96 ms）をまとめる", "xs")
t(877, 627, "EVENT: START（設定の全部）・STOP・DROP・ERROR", "xs")
t(877, 643, "頭に 中身の CRC-32（PL から読んだ値で）・通し番号 seq", "xs")
t(877, 659, "溜まりに入らない → 捨てて数え、空きが 1/4 に", "xs")
t(877, 675, "  戻ったら DROP（捨てた seq の範囲）を置いて再開", "xs")

# パイプ
box(785, 175, 60, 70, "note")
t(815, 196, "パイプ", "s", "middle", style="font-weight:bold")
t(815, 212, "辞書", "xs", "middle"); t(815, 226, "命令 → ", "xs", "middle"); t(815, 240, "← 応答", "xs", "middle")
path("M765,195 L785,195", "wB"); path("M845,195 L863,195", "wB")
path("M863,232 L845,232", "wBd"); path("M785,232 L767,232", "wBd")

# 溜まり
box(360, 725, 895, 160, "ring")
t(374, 747, "s45ring.py: 共有メモリの溜まり（既定 256 MiB ≒ 38 秒、--buf-mb）— 書き手 1 つ（取得）・読み手 1 つ（送り）", "tm")
t(374, 766, "記録（頭 24 B ＋ 中身）をバイトの環にそのまま連続に置く（端に入らなければ PAD で埋めて頭へ）。位置は単調に増えるバイト数", "xs")
# 位置の帯
X0, X1, Y = 400, 1210, 800
a(f'<rect x="{X0}" y="{Y}" width="{X1 - X0}" height="26" fill="#ffffff" stroke="#2e8b57" stroke-width="1"/>')
xr, xs_, xw = 520, 760, 1060
a(f'<rect x="{xr}" y="{Y}" width="{xs_ - xr}" height="26" fill="#dff0e5"/>')
a(f'<rect x="{xs_}" y="{Y}" width="{xw - xs_}" height="26" fill="#fde9d4"/>')
t((xr + xs_) / 2, Y + 17, "送った・ACK 待ち", "xs", "middle")
t((xs_ + xw) / 2, Y + 17, "まだ送っていない", "xs", "middle")
t((X0 + xr) / 2, Y + 17, "空き", "xs", "middle"); t((xw + X1) / 2, Y + 17, "空き", "xs", "middle")
for x, lb in ((xr, "r（ACK まで）"), (xs_, "s（送った）"), (xw, "w（書いた）")):
    a(f'<line x1="{x}" y1="{Y - 4}" x2="{x}" y2="{Y + 30}" stroke="#333" stroke-width="1.6"/>')
    t(x, Y + 44, lb, "lbK", "middle")
t(374, 862, "書き手は 空き = 容量 − (w − r) が足りなければ書かない（呼び手が捨てて数える）。w・r の更新は Lock の中（aarch64 のメモリの順序の壁）", "xs")
t(374, 877, "言語に依らない形（固定の頭 ＋ バイトの環）にしてあり、取得の環だけを C に替えられる", "xs")

# ---------------- PL ----------------
box(1320, 75, 300, 830, "pl")
t(1334, 97, "PL: proj017.bit（SAM45-Fine）", "t")
t(1334, 114, "ID 0x0017_0100。RTL は proj018 で変えていない", "xs")
box(1335, 128, 270, 90, "tim")
t(1347, 147, "time_core_0", "tm")
t(1347, 164, "64 bit のビート T（256 MHz）", "xs")
t(1347, 180, "1PPS のスタンプ・錨（ANCHORED / EPOCH）", "xs")
t(1347, 196, "START_AT の予約の発火 → 全コアが +1 で RUN", "xs")
t(1347, 212, "時刻の格子 G = 2.048 ms", "xs")
for i, lbl in enumerate("ABCD"):
    y = 235 + i * 125
    box(1335, y, 270, 110, "plsub")
    t(1347, y + 19, f"win_core_{i}（ADC_{lbl}）", "tm")
    t(1347, y + 36, "窓 0・窓 1（256〜8 MHz、4096 点）", "xs")
    t(1347, y + 52, "  SEQ・DUMP_K・DUMP_T・DUMP_H・CFG_ID", "xs")
    t(1347, y + 68, "  RUN_SHIFT・DUMP_SAT・FLAGS・二面の溜め", "xs")
    t(1347, y + 84, "tp_core: Σx² を 1.024 ms ごと", "xs")
    t(1347, y + 100, "  512 個のリング・TP_WP・TANCH", "xs")
box(1335, 740, 270, 70, "plsub", style="stroke-dasharray:4 3")
t(1347, 759, "spec_core_0（全帯域、試験用）", "tm")
t(1347, 776, "specd は使わない（START で DISARM だけ）", "xs")
t(1347, 792, "閉ループの M を測るときに timetest.py で", "xs")
t(1335, 838, "AXI4-Lite（smc_ctrl）で PS とつながる", "xs")
t(1335, 854, "読み出しは DMA なし（40.96 ms に 8 窓 × 8192 語）", "xs")

# 外の入力
for i, (lb, y) in enumerate((("ADC_A〜D", 470), ("1PPS", 160), ("10 MHz（基準）", 195))):
    t(1700, y - 6, lb, "xs", "middle")
    path(f"M1765,{y} L1622,{y}", "wT" if i else "wK")
t(1700, 488, "IF 2048〜4096 MHz", "xs", "middle")

# ---------------- 線 ----------------
# 制御 PC ⇄ 制御の口（PC は group の外: x = 300 − DX = 210）
path("M210,190 L373,190", "wB"); t(218, 182, "TCP 51000: 命令 1 行", "lbB")
path("M373,222 L212,222", "wBd"); t(218, 240, "応答 1 行", "lbB")
# 送り → ダウンロード PC、ACK
path("M373,440 L212,440", "wO"); t(218, 422, "TCP 51001: 記録", "lbO"); t(218, 436, "（頭に CRC-32・seq）", "lbO")
path("M210,505 L373,505", "wG"); t(218, 522, "ACK（<Q 最後の seq）", "lbG"); t(218, 536, "0.2 s ごと", "lbG")
# 溜まり → 送り（パイプの下の隙間を上る）
path("M828,723 L828,385 L767,385", "wO"); t(834, 716, "next_record", "lbO")
# ACK の受け → 溜まりの r
path("M767,512 L800,512 L800,723", "wG"); t(796, 712, "ack_to（r を進める）", "lbG", "end")
# 取得の中: 命令 → HwBackend → 読み出しの環 → 記録 → 溜まり
path("M950,272 L950,285", "wB")
path("M1052,401 L1052,414", "wO")
path("M1052,544 L1052,557", "wO")
path("M1052,687 L1052,723", "wO"); t(1060, 712, "put（記録）", "lbO")
path("M1200,687 L1200,723", "wP"); t(1206, 712, "DROP", "lbP")
# HwBackend ⇄ PL
path("M1240,322 L1333,322", "wB"); t(1246, 314, "書く", "lbB")
path("M1333,372 L1242,372", "wO"); t(1246, 390, "読む", "lbO")
path("M1622,160 L1607,160", "wT")
a("</g>")

# 凡例・数
box(30, 930, W - 60, 112, "note")
t(44, 952, "数（実機、2026-10-05）", "tm")
t(44, 972, "送る量: 8 窓 × 32,848 B / 40.96 ms ＋ TP ≒ 6.5 MB/s。P-1（1 時間）: 87,890 ダンプ × 8 窓・TP 4 本で読み落とし 0・欠け 0・CRC 不一致 0、"
           "取得の 1 周の最大 29.13 ms・99 % 点 24.9 ms（8 窓のダンプは格子で同時に閉じ、その 1 周で 8 窓を読む）")
t(44, 992, "P-4: 溜まり 8 MiB で 6 秒送らない → DROP 3,108 個 = 受け側の欠け（読み出しは落とさない）。P-5: 受け側を 2 回に分けても欠け 0（ACK の無い記録は送り直す）")
t(44, 1012, "最初の版は sendall が返ったら溜まりから消していた → 受け側を切ると送りかけの記録が黙って消えた（PL なしの試験で発見）。今は受け側の ACK まで溜まりに残す")
t(44, 1032, "道具: s45fcheck.py（中身の確かめ C-1〜C-5）・test_fake.sh（PL なし。CRC の反転・黙った欠け・読み出しの停止の陽性対照）", "xs")

a("</svg>")
open("sw_flow.svg", "w").write("\n".join(o))
print("sw_flow.svg を書いた")
