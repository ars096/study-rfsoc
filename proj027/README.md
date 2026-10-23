# proj027 — 2G-4 の RTL（4 ADC × 32768 ch、FFT 65536 点 = 16 レーン × 4096 点 × 4 コア）

日付: 2026-10-23（起こし）
土台: study-rfsoc の commit **f706170**（proj025 の 2G-2 が 3. PS を終え、4. 実機に入る前）。
写したもの（2026-10-23、追跡しているファイルだけを `git show` で。名前 g22 → g24・G22 → G24 だけを置き換え、長さ・表・丸めはまだ 2G-2 のまま。M・1a〜1d で直す）:
- f706170 の proj025 から: `model/g2_model.py`（そのまま）・`model/g22_fixed.py` → `g24_fixed.py`・`model/g22_model.py` → `g24_model.py`・`tools/gen_g22_tables.py` → `gen_g24_tables.py`・
  `src/common/cmul.v`・`dft16.v`（そのまま）・`src/g22/g22_{coef,tw,pfb,pfb_core,chain}.v` → `src/g24/g24_*.v`・`sim/tb_g22_{coef,tw,pfb,chain}.v` → `tb_g24_*.v`
  （段階 A の後に変わったのは g22_pfb_core の履歴を BRAM に置く指定だけ（96605ab、proj025 2f ビルド 1）。**これも引き継いだ**）
- fcea4f1（proj025 の段階 A の commit）の proj025 から: `sim/check_g22.py` → `check_g24.py`・`Makefile`（段階 A の 1a〜1d の分だけの版）
- 写していないもの: 表の `.hex`（`make gen` で 2G-4 の長さで作り直す）・コア（g22_acc・spec・core・s45_core）・build.tcl・`pynq/`（段階 B）

状態: 進行中（段階 A を始めた）

着手の前に [`../LESSONS.md`](../LESSONS.md) を全部読む（知見の全部は [`../docs/lessons_all.md`](../docs/lessons_all.md)）。

## 目的

**2G-4（YATSUGATAKE `docs/spec/bits.md` の 2G の行、BIT_KIND 3）の RTL を作る。** 4 本の ADC をそれぞれ 65536 点の FFT（32768 ch、df 62.5 kHz）で、dt 10.24 ms。
作る順 2G-1 → 2G-2 → 2G-4（proj024 D-1）の最後。2G-1（proj024）は閉じ、2G-2（proj025）は実機の前。proj025 の実機と並行して、**実機に左右されない部分（模型・部品・単体の sim）から始める**（proj025 の段階 A と同じ型）。

## 範囲と線引き（進行中の会話とぶつからないように、2026-10-23 の状態で）

並行しているもの: **proj025**（2G-2、次は 4. 実機）・**proj026**（LPF、次は SG 830 MHz の CW で実機）・**YATSUGATAKE-wide の sam45-wide/m5**（SAM45-Wide の移植 M5、USR_ACCESS のビルド）。

| もの | proj027 で | 理由 |
|---|---|---|
| `proj027/` の模型・部品・単体の sim | **扱う** | ファイルは proj027 の中だけ |
| 4 コアのコア・build.tcl・`pynq/` | **まだ写さない**（段階 B） | 写し元は 2G-2 の実機を通った後の proj025 のタグ（`proj025-m0` の案）。2G-2 の実機で直る可能性がある（proj025 の E-6 と同じ理由） |
| `proj023/`〜`proj026/` | **読むだけ** | それぞれの会話が持ち主 |
| study-rfsoc の INTERFACE.md・BITS.md・YATSUGATAKE の `docs/spec/` | **触らない** | 2G-4 の分（BIT_KIND 3・KIND 1 FULL・NCH 32768・FRAME_BEATS 4096）は入っている。変えたいことは下の「決めること」に書いて持ち越す |
| YATSUGATAKE・YATSUGATAKE-wide の作業ツリー | **触らない** | Wide の M5 が `src/common` と `sw/pynq` を動かしている |
| INDEX.md・LESSONS.md・docs/lessons_all.md | 足すだけ（自分の行だけ） | 同じ行を同時に書き換えない |
| コミット | **`git commit -- proj027/ INDEX.md` でパスを指定する** | 同じ作業ツリーに複数の会話がコミットする |
| Vivado サーバ・ボード | 段階 A では**使わない** | proj025 の実機・proj026・Wide の M5 が使う。IP の survey（4096 点のレーン FFT）も含め、最初に Vivado を使う前に西村さんと順番を決める |

## 2G-4 の仕様（bits.md・proj024 から。段階 A で確かめる）

| | 2G-4 | 2G-2（参考、proj025） |
|---|---|---|
| ADC | 4 本 | 2 本（4 本から SRC で選ぶ） |
| 1 本の FFT | 65536 点 = 16 レーン × **4096 点** | 131072 点 = 16 × 8192 |
| ch / ADC・df | 32768・62.5 kHz | 65536・31.25 kHz |
| フレーム | 4096 ビート = 16 µs（10.24 ms に 640、格子 2.048 ms に 128） | 8192 ビート = 32 µs |
| PFB | T 4、L = 262,144 タップ、履歴 3 フレーム × 65536 × 14 bit = 2.75 Mbit / ADC（4 本で 11 Mbit） | 524,288 タップ・5.5 Mbit / ADC |
| 語長（proj024 D-7・M-4） | **Y の丸めなし**（4096 点は今の cmul のまま入る） | Y の下 1 bit を丸める |
| 積分器 | コアごとに 8 銀行 × 4096 × 48 bit × 2 面 = 3.1 Mbit（4 コアで 12.6） | 6.3 Mbit × 2 |
| 流れ | KIND 1 FULL × 4、NCH 32768・FRAME_BEATS 4096、レコード 256 KiB × 4 / 10.24 ms | 512 KiB × 2 |
| PFB の重心のずれ 1.5·L | 24 µs | 48 µs |
| 資源の見積もり（proj024 S-1） | **LUT 64〜67 %（PFB なし）、65〜68 %（PFB あり）**。目安 65 % の境。Wide のビルド 11 は 59.8 % で `-1` の余裕 +0.001 ns | LUT ≒ 35〜41 % |

**2G-2 から変わる大きなこと**: コアが 4 個（Wide と同じ数）・LUT が目安の境（proj024 で「2G-4 を作るときに PFB を残すかを決める」とした）・Y の丸めが無くなる。

## 手順（段階 A: 2G-2 の実機に左右されない部分）

各手順は 予言 → 結果 → 当たり・外れ → INDEX → コミット。

- 0. 写す（済み、上の「写したもの」）
- M. 模型 `model/g24_fixed.py`（長さを 2G-4 に、D1 = 0）と `make model`・表の生成 `make gen`
  - **先に見ておく論点（M-a）**: N が 2G-2 の半分なので、係数の補間の傾き S は 1 タップあたり 2 倍で、同じ D 64・G 5 なら **S 14 bit・V ＋ S = 37 bit で RAMB36 の幅（36）を 1 bit 越える見込み**（表は 2048 行に減る）。候補: G 4（35 bit）/ D 32（S 13・36 bit・4096 行、coef_beat の形が変わる）/ 72 bit 幅の ROM。予言は模型を直してから書く
- 1a〜1d. 部品 `g24_coef`・`g24_tw`・`g24_pfb`・`g24_chain` の単体の sim（模型と bit 単位、陽性対照つき）
- 4 コアの論点と PFB の扱いを並べ、西村さんに決めてもらう（下の「決めること」）

段階 B（proj025 の 2G-2 の実機の最初の確かめの後）: proj025 のタグからコア・build.tcl・`pynq/` を写し、4 コアに組む → ビルド → 実機。

## 決めること（段階 A の終わりまでに並べる）

- PFB を残すか（LUT の目安の境。proj024 の 209 行・214 行）。残さないなら係数・履歴の部品が要らなくなるので、M・1a〜1c の前に決めたほうが安い
- 係数の ROM をコアで共有するか（4 コア。proj025 E-2 は 2 コアでコアごとにした。Wide は共有で `-1` の余裕が 25 ps になった）
- コアの組み方（Wide の形の s45_core × 4 か）・SRC・RAW・TP（proj025 E-1・E-4・E-5 の 4 コア版）
- リングの大きさ（INTERFACE 11.。2G-4 は 256 KiB × 4 / 10.24 ms）

## 結論・次にやること

- [x] 0. 写す（2026-10-23）
- [ ] PFB を残すかを決める（M の前）
- [ ] M. 模型・表
- [ ] 1a〜1d. 部品の単体の sim
- [ ] 4 コアの論点を並べる
