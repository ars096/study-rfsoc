# proj027 — 2G-4 の RTL（4 ADC × 32768 ch、FFT 65536 点 = 16 レーン × 4096 点 × 4 コア）

日付: 2026-10-23（起こし）
土台: study-rfsoc の commit **f706170**（proj025 の 2G-2 が 3. PS を終え、4. 実機に入る前）。
写したもの（2026-10-23、追跡しているファイルだけを `git show` で。名前 g22 → g24・G22 → G24 だけを置き換え、長さ・表・丸めはまだ 2G-2 のまま。M・1a〜1d で直す）:
- f706170 の proj025 から: `model/g2_model.py`（そのまま）・`model/g22_fixed.py` → `g24_fixed.py`・`model/g22_model.py` → `g24_model.py`・`tools/gen_g22_tables.py` → `gen_g24_tables.py`・
  `src/common/cmul.v`・`dft16.v`（そのまま）・`src/g22/g22_{coef,tw,pfb,pfb_core,chain}.v` → `src/g24/g24_*.v`・`sim/tb_g22_{coef,tw,pfb,chain}.v` → `tb_g24_*.v`
  （段階 A の後に変わったのは g22_pfb_core の履歴を BRAM に置く指定だけ（96605ab、proj025 2f ビルド 1）。**これも引き継いだ**）
- fcea4f1（proj025 の段階 A の commit）の proj025 から: `sim/check_g22.py` → `check_g24.py`・`Makefile`（段階 A の 1a〜1d の分だけの版）
- 写していないもの: 表の `.hex`（`make gen` で 2G-4 の長さで作り直す）・コア（g22_acc・spec・core・s45_core）・build.tcl・`pynq/`（段階 B）

状態: 進行中（段階 B。段階 A は済み: PFB あり・模型 M・部品 1a〜1d の単体の sim は全部通過・4 コアの論点 F-1〜F-6 は決めた（F-2 は g24_coef の OOC で測って コアごと）。W: Wide の束ね・切り出しは差し引き 730 LUT / コアで、2G-4 の LUT は約 64.0 % の見込み。段階 B を 2026-10-23 にタグ proj025-m0 から始めた: B0 写し済み・2a〜2e・2e-2（4 コア）・4d-2 の sim は全部通過・2f のビルドは Performance_Explore で閉じた（WNS +0.032 ns、LUT 64.6 %）。次は 3. PS）

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

## M. 2G-4 の部品を bit 単位で決める（`model/g24_fixed.py`、`make model`）— 予言（走らせる前に書く、2026-10-23）

PFB あり（2026-10-23、西村さん。2G-1・2G-2 と同じ T 4）。proj025 の M と同じ 4 項目を 2G-4 の長さで。変えるのは N 65536・M 4096・KB 12・L 262,144・**D1 0**（Y の丸めなし、proj024 D-7）・表の行数だけ。D 64・S_TW 128（hi 32 行・lo 128 行）は変えない。

- **a 係数の補間**（D 64、片側 2048 区間）: V の幅は N に依らず 23 bit（G 5）、傾き S は 1 タップあたり 2G-2 の 2 倍で **G 5 なら S 14 bit・計 37 bit で 36 を越え、M-a は落ちる**。
  **G 4 にする**: V 22・S 13 = **35 bit**。差 ≦ 1 LSB、h に対する rms の比は 2G-2（1.0005）より大きいが **≦ 1.005**（補間の誤差は 1/N² で 4 倍、G を 1 減らした節の丸め 2^−4 / √12 ≒ 0.018 LSB は 0.29 LSB に二乗で足して 0.2 % ほど）。
  表は 2048 × 35 bit = 72 kbit、前半・後半を 1024 行の 2 ポートの ROM（1K × 36）にして **RAMB36 2 個**（2G-2 は 4）。ビートの式（m >> 2・16·(m & 3) + p）は D 64 のままなので形は同じで、全部の i で折り返しの式と一致、陽性対照は一致しない。応答の差 ≦ 0.05 dB。
  外れたとき（G 4 で比が 1.01 を越える）は D 32（S 13・G 5 で 36 bit・4096 行、ビートの式が m >> 1 に変わる）に回る
- **b ひねり係数の積**（hi 32 行・lo 128 行）: 直の表との差 最大 2 LSB、rms の比 ≒ 1.7、成分は 18 bit に入る。陽性対照（hi·127 + lo）は差 > 100 LSB
- **c 鎖の全体**（CW 1000 LSB @ ch 20000 ＋ 雑音 σ 100、Y の丸めなし・cmul SH 18）: 雑音の ch の ε は y の整数への丸めで決まり（proj025 M の外れの理由）、**8e-6〜9e-6**。CW の差 < 0.01 dB、y の飽和 0。
  各段の最大: **Y ≒ 2.0M**（2G-2 の半分、2^27 より十分小さい）、Yd = Y、**V・U・Z は 2G-2 と同じ程度**（V ≒ 0.51M・U ≒ 2.0M・Z ≒ 8.2M。Z の目盛り X / 4 と X の大きさ ∝ N が打ち消す）。
  陽性対照（k1 を 1 ずらす）: ε は k1 = M − 1 の 1 列（W_16^p が入る）が決め、列の割合が 2G-2 の 2 倍なので **≒ 3e-4**（2G-2 は 1.6e-4）で線 2e-5 を越えて落ちる
- **d 積分器の番地**: 12 bit の bit 反転順の k1 は 1 フレームで 4096 の番地を 1 回ずつ、戻るまで 4096 ビート
- 外れるとしたら: 2G-2 の長さの取り残し（8192・13・4096 の意味が変わる所。NSEG は 2G-2 で 4096 だったので、`4096` を grep すると「区間の数」と「M」が混ざる）

**結果（`make model`、2026-10-23、2 秒）: 全部通過**（1 回目で。線は走らせる前のまま）

| | 結果 | 予言 |
|---|---|---|
| a 補間 | G 5 は V 23・S 14 = **37 bit で入らない**。**G 4**: 差 ≦ 1 LSB・h に対する rms 0.2882 LSB（全部の表 0.2873、**比 1.0031**）・**V 22・S 13 = 35 bit**。ビートの式は全部の i で一致、陽性対照は 65,984 個違う。応答の差 0.000 dB。表 2048 × 35 bit = 72 kbit → **RAMB36 2 個** | 当たり（G 5 は 37 bit・G 4 で 35 bit・比 ≦ 1.005・RAMB36 2） |
| b 積 | hi 32 行・lo 128 行。直の表との差 最大 2 LSB・rms 0.664 LSB（直の表 0.397、比 1.67）・成分の最大 65,537。陽性対照は差 8,087 LSB | 当たり |
| c 鎖 | 雑音の ch の ε **8.4e-6**・CW の ch 0.0000 dB・y の飽和 0。各段の最大 Y 2.04M（< 2^27）・Yd = Y・V 0.51M・U 2.04M・Z 8.15M | 当たり（ε 8e-6〜9e-6・Y ≒ 2.0M・V・U・Z は 2G-2 と同じ） |
| c 陽性対照（k1 を 1 ずらす） | ε **5.75e-4**（線 2e-5 を越えて落ちる） | 落ちるのは当たり、**大きさ「≒ 3e-4」は外れ**（1.9 倍） |
| d 番地 | 12 bit の bit 反転順は 1 フレームで 4096 の番地を 1 回ずつ、戻るまで 4096 ビート | 当たり |

G の掃引（M-a の表）: 比は G 3 で 1.0080、G 4 で 1.0031、G 5 以上は 1.002 で頭打ち（補間の誤差が残る）。G 4 は 36 bit に入る最大で、G 5 との差は比で 0.001。

外れた 1 つの理由（結果の後に調べた。部品は直していない）:
- **陽性対照の ε は、k1 = M − 1 の列（W_16^p の代わりに 1 が入る）の 8 ch が決める**: 列の寄与 5.56e-4、列を除いた ε 1.88e-5。列の ch の |誤差|² / |X|² は、期待値が |1 − W_16^p|² の p の平均 = **2** で、8 ch × 2 フレーム = 16 標本の雑音の比なのでばらつきが大きい（今回 2.3、proj025 の 2G-2 は 1.2）。
  予言は 2G-2 の 1 回の実現値（1.2）を定数とみなし、列の割合 8 / 32,761 の 2 倍だけを掛けていた。期待値で書けば 2 × 2.44e-4 ＋ 1.9e-5 ≒ 5.1e-4 で、実測はその内側
- 列を除いた ε 1.88e-5 = y の丸め 8.4e-6 ＋ 1 ずれの位相 2π·p / N の寄与（2G-2 の 2.6e-6 の 4 倍 ≒ 1.0e-5）で、こちらは計算どおり。**2G-4 では端の列を除いても 1 ずれが線 2e-5 のすぐ内側まで来る**（2G-2 は 1.1e-5）。番地の誤りを捕まえるのは bit 単位の照合（sim）と tw_k1 の見張り、という申し送りは変わらない

生成の道具 `tools/gen_g24_tables.py`（`make gen`）: `build-gen/` に `g24_coef_lo.hex`・`g24_coef_hi.hex`（各 1024 行 × 35 bit）・`g24_tw_a.hex`（32 行）・`g24_tw_b.hex`（128 行、各 576 bit）を書き、読み返して模型と照らした（係数 262,144 タップ・ひねり係数 16 × 4096 とも一致）。`src/g24/` に写した。
RTL（`src/g24/`）は 1a〜1d で 2G-4 の長さ・幅に直した（下）

## 1a〜1d. 部品の単体の sim（`make sim-all`）— 予言（走らせる前に書く、2026-10-23）

proj025 の 1a〜1d の部品・tb・判定を写し、長さ（m・k1 を 12 bit、フレーム 4096 ビート）・表（係数 1024 行 × 35 bit・V 22・G 4、A 32 行・hi 5 bit）・Y の幅（27 bit）と丸め（**なし**）だけを変える。段の数は変えない（LAT は 1a 5・1b 6・1c 10・1d 21 のまま）。
sim は作業用のクラウドの環境の Icarus Verilog（oss-cad-suite 2024-10-18、proj025 と同じ）で回す。

- **1a g24_coef**: 1 フレーム ＋ 512 ビート（4,608 行、切れ目 2 か所。2G-2 の 6001 は 4096 を越えるので 3001 に）の全部の (m, t, p) が模型の coef_beat と一致、m の種類 4096、tb の数えのレイテンシ 4（= LAT 5）。陽性対照（-DCOEF_FRAC_ERR）は全部の行（4,608）が違う
- **1b g24_tw**: 4096 ＋ 256 ビートの全部が tw_prod と一致、k1_out の並びは入れたとおり（種類 4096）、LAT 6。陽性対照（-DTW_HI_ERR）は全部の行が違う
- **1c g24_pfb**: 5 フレーム（20,480 ビート）が pfb_int と一致、sat_cnt 0・coef_mis 0、フレームの途中から入れた 384 ビート（m 3700〜4083。2G-2 の 7800 は 4096 を越える）は捨てる。
  陽性対照 2 本: DLY_ERR は coef_mis 1 で、違うビートは 2G-2（17,043 / 40,960 = 42 %）と同じ割合の **≒ 8,500**（係数が隣のビートの値になるのは、同じ区間の中の 4 ビートの 3 つと区間の境で、割合は長さに依らない）。NOMASK は起動の直後に初期化していない履歴（x）を拾って落ちる
- **1d g24_tw ＋ g24_chain**: 3 フレーム（12,288 ビート）が chain_Y ＋ power と一致（SHIFT 7・4）、tw_mis 0。
  飽和を含むビートは **2G-2 と同じ 1・2**（Yd の大きさが 2G-2 と同じ: 2G-2 は Y が 2 倍で 1 bit 丸め、2G-4 は丸めなし。最悪のフレームの |Yd| は どちらも 11507·4096）。
  陽性対照 2 本: TW_LAT_ERR は tw_mis 1 で落ちる。**NORND（丸めを切り捨てに）は 2G-4 では丸めが無いので意味がない → -DCHAIN_RND1（2G-2 の 1 bit の丸めを残したまま）に替える**: Yd が半分になり、0 でないビートはほぼ全部（≒ 12,288）が違う
- 外れるとしたら: 13 → 12 bit の取り残し（`[12:0]` と `13'd`・`brev` の 13 は機械的に直すが、**数として書いた 8191・8192・2047・6001・7800** と、M（4096）と区間の数（2G-2 は NSEG 4096・2G-4 は 2048、半分の表は 2048 → 1024）の取り違え）。Y の幅を 28 → 27 に縮めた所（tb のレジスタの幅 448 → 432・hex の桁 112 → 108）

**結果（`make sim-all`、2026-10-23、35 秒）: 全部通過・陽性対照 6 本は全部落ちた**（1 回目で）

| | ふつう | 陽性対照（落ちた理由） |
|---|---|---|
| 1a g24_coef | 4,608 行・m の種類 4096 / 4096・**模型と違う行 0**・レイテンシはどのビートも同じ（tb の数えで 4 = RTL の LAT 5） | COEF_FRAC_ERR: 4,608 行が違う |
| 1b g24_tw | 4,364 行・**違う行 0**・k1_out の並びは入れたとおり（1 フレームの k1 の種類 4096）・LAT 6 | TW_HI_ERR: 全部の行が違う |
| 1c g24_pfb | 20,480 ビート（途中から入れた 384 は捨てた）・並び OK・**違うビート 0**・sat_cnt 0・coef_mis 0 | DLY_ERR: **12,650 ビート違い**・coef_mis 1 / NOMASK: 起動の直後に初期化していない履歴（x）を拾う（12,288 ビート） |
| 1d g24_tw ＋ g24_chain | SHIFT 7・4 とも 12,288 ビート・k1 の並び OK・**違うビート 0**・tw_mis 0（飽和を含むビートは模型と同じ 1・2） | TW_LAT_ERR: 8,192 ビート違い・tw_mis 1 / RND1: **8,192 ビート違い** |

当たり・外れ:
- 1a・1b・1c のふつう・1d のふつうと飽和の数（1・2、2G-2 と同じ）・NOMASK・TW_LAT_ERR は予言どおり。「外れるとしたら」の取り残し（8191・6001・7800 など）は、置き換えの後に grep して残りを直してから回した（残っていたのは tb_g24_tw の `k1_out == 13'd0` だけ。幅が 1 bit 多いだけで振る舞いは同じ）
- **外れ 1: 1c の DLY_ERR の違うビートは ≒ 8,500 ではなく 12,650（62 %、2G-2 は 42 %）**。模型で係数を 1 ビートずらすと **12,650 がそのまま出る**（−1 ビートなら 12,672）ので、RTL の誤りではない。
  予言の「割合は長さに依らない」が誤りで、**隣のビートの係数の差は N に反比例する**（窓の形は L で決まり、1 ビートぶんの位置の差は窓の中で 2 倍の距離になる）。隣のビートの係数の差の平均は 2G-4 11.5 LSB・2G-2 5.8 LSB、差が 0 のタップは 10.0 %・15.2 %。差が大きいほど y の丸めを越えるビートが増える
- **外れ 2: 1d の RND1 の違うビートは ≒ 12,288 ではなく 8,192**。理由（予言の数え違い）: 3 つ目のフレーム（y がすべて +11507 の最悪の同相）は **k1 = 0 の 1 ビートしか 0 でなく**、その 1 ビートは SHIFT 7 で飽和して、丸めがあってもなくても同じ値になる。0 でないビートの数を 3 フレーム全部と数えていた。「0 でないビートはほぼ全部が違う」の中身は当たり（フレーム 0・1 の 8,192 ビートは全部違う）
- 陽性対照はどれも「違うビートの数が 0 でない」で落ちていて、コンパイルや sim の失敗で落ちたものは無い（tb のログに入れた・出たビートの数が出ている）

段階 B（proj025 の 2G-2 の実機の最初の確かめの後）: proj025 のタグからコア・build.tcl・`pynq/` を写し、4 コアに組む → ビルド → 実機。

## W. Wide の束ね・切り出しの LUT（`make wide-hier`、`tools/wide_hier.tcl`）— 予言（走らせる前に書く、2026-10-23）

proj024 の残り「2G-4 の前に、Wide のビルドで階層を深くして測る」。**新しいビルドはしない**: SAM45-Wide の凍結版（proj023 ビルド 11、`build-PE/`）の配線済みチェックポイントを読むだけで開き、`u_wide` の下を深さ 8 まで数える（proj023 には書かない。YATSUGATAKE-wide にも触らない）。
照合: 全体の CLB LUTs が `proj023/build-PE/utilization.rpt` と同じ 255,211、4 コアの `u_wide` が揃って在る。

- proj024 の見積もり（`tools/estimate.py`）の CORE_REST の LUT 12,400 / コアは、束ね・切り出しを含む
- 予言: **束ね・切り出しは 1 コアあたり LUT 1,000〜3,000**（4 コアで 4,000〜12,000 = デバイスの 0.9〜2.8 %）。2G-4 の見積もり 65〜68 %（PFB あり）は **62〜67 %** に下がる。目安 65 % を確実に切れるとまでは言えない見込み

**結果（2026-10-23、チェックポイントを開いて 4 分 40 秒）: 照合は通過**（全体の CLB LUTs 255,211 が build-PE と一致、4 コアの `u_wide` が在る）

Wide のコア 0（`build-wide/wide_hier_c0.rpt`、配置後）の LUT:

| 段 | LUT | 中身 |
|---|---|---|
| s45_core_0 全体 | 61,004 | |
| レーン FFT 16 個 | 47,801（1 個 2,988） | |
| **レーン FFT 以外** | **13,203** | |
| u_chain | 5,656 | dft16 2,323・ひねり係数の cmul 16 個 約 1,650・残り（SHIFT・電力・**束ね**）1,709 |
| u_acc（wide_acc = **切り出し**の積分器） | 1,432 | |
| u_spec の残り | 1,670 | |
| u_pfb | 348 | |
| u_wide の残り・adc_ev・rec_fr | 1,184 | |
| u_wide の外（TP・RAW など） | 2,959 | |

束ね・切り出しは**外して終わりではなく、2G の部品に置き換わる**（束ねなしの鎖・全部の ch を積む積分器）。なので、比べるのは 2G-2 の実ビルド（proj025 `build/`）の同じ数:

- proj025 のコア 0 のレーン FFT 以外: 71,833 − 16 × 3,710 = **12,473**（RAW を持つコア。RAW の無いコア 1 は 11,201）。g22_acc 1,151（wide_acc は 1,432）
- **Wide → 2G で浮く分は差し引き 730 / コア**（13,203 − 12,473）。4 コアで 2,900 = 0.7 %
- **外れ**: 予言の 1,000〜3,000 / コアより小さい。予言は束ね・切り出しを「外すだけ」と数え、置き換わる 2G の部品の分を引いていなかった

**同じ表から出た、こちらのほうが大きい外れ**: レーン FFT の LUT は **OOC の数より配置後のほうが 6 % 小さい**（2048 点・自然順 3,157 → 2,988 で 0.946、8192 点・bit 反転順 3,957 → 3,710 で 0.938）。proj024 の見積もり（`estimate.py`）は S-1 の OOC の数をそのまま 64 個に掛けていた。

2G-4 の LUT を実測の部品から引き直す（PFB あり・係数はコアごと・RAW も TP もコアごと = F-1〜F-6 の形）:
- レーン FFT 4096 点・bit 反転順: OOC 3,434 × 0.938 ≒ 3,220 / 個
- コアのレーン FFT 以外: proj025 のコア 0（RAW 込み）の 12,473 をそのまま（Wide の束ね・切り出しは無く、PFB の係数もコアごと。幅が細くなる分は数えない）
- 共通部: proj025 の 15,571 ＋ full_sel 2 個 516
- **計 約 272,000 = 64.0 %**（proj024 の数え方だと 66.6 %）。**目安 65 % の下に入る見込み**。ただし余裕は 1 % で、レーン FFT の OOC と配置後の比（0.94）とコアの残りの見積もりの誤差と同じ大きさ。段階 B の最初のビルドで確かめる

## 段階 B（2026-10-23 から。写し元はタグ **proj025-m0** = b1207af）

写し元: study-rfsoc のタグ `proj025-m0`（2G-2 を閉じた commit b1207af。ビルドに効くファイルは 96605ab と同じ）。
段階 A の部品の写し元 f706170 から proj025-m0 までに、proj025 の `src/`・`sim/`・`model/`・`tools/`・`Makefile`・`build.tcl` は変わっていない（`git diff --stat f706170 proj025-m0` が pynq と文書だけ）ので、**段階 A の部品はそのまま使う**。

### B0. 写す（2026-10-23）

写したもの（proj025-m0 の proj025 から。追跡しているファイルだけを `git show` で。計 115 個）:
- **そのまま**（101 個）: `src/common/`（cmul.v・dft16.v は段階 A で写したものと同じ中身（cmp で確かめた）なので上書きしていない）・`src/board/`・`pynq/`・`tools/ip_impl.tcl`・`ip_survey.tcl`・`sim/rec_fr_ref.v`・`tb_recfr_eq.v`
- **名前（g22 → g24、G22 → G24）だけを置き換えた**（14 個）: `src/g22/g22_{acc,spec,core,s45_core}.v` → `src/g24/g24_*.v`、`sim/{lane_fft_g22_model,tb_g22_{acc,spec,core,s45,ds,x2},tb_lane_g22}.v` → `*g24*`、`build.tcl`・`build_post.tcl`。長さ・ID・コアの数はまだ 2G-2 のまま（2a〜2f で直す）
- `sim/check_g24.py`: proj025-m0 の check_g22.py を名前だけ置き換え、段階 A で入れた 2G-4 の直し（chain-gen の Y 27 bit・|Y| の上限）をパッチで当て直した（頭の docstring だけ手で）。**写した後に `make sim-all`（1a〜1d）は全部通過・陽性対照 6 本は落ちた**

写していないもの: `model/g22_*.py`（2G-4 は段階 A の `g24_*.py`）・`tools/gen_g22_tables.py`・`src/g22/*.hex`・`runs/`。Makefile は 2a で proj025-m0 の目標を足す

### 段階 B の手順（proj025 の 2a〜4d と同じ並び。各手順は 予言 → 結果 → 当たり・外れ → INDEX → コミット）

| | もの | 2G-2 から変わること |
|---|---|---|
| 2a | `sim/lane_fft_g24_model.v`（レーン FFT 4096 点・bit 反転順の行動模型。tready の下げ・halt を引き継ぐ） | 長さ 4096（k1 12 bit）、出口 Y 27 bit |
| 2b | `g24_acc`（FULL の積分器、8 銀行 × 4096 × 48 bit × 2 面） | 行 4096、ch c = k1 + 4096·k2 |
| 2c | `g24_spec`（PFB → レーン FFT × 16 → 鎖 → 積分器） | フレーム 4096 ビート、bit 反転の幅 12、Y の丸めなし |
| 2d | `g24_core`（FULL の流れ 1 本、SPEC のレコード 256 KiB・FULL の TP） | NCH 32768・FRAME_BEATS 4096・log2 N 16、DUMP_T = K_F ＋ 4096·DUMP_F0、N_ACC 640、GF_L2 7（128 フレーム = 2.048 ms）、TP の F0 × 8 |
| 2e | `g24_s45_core`（コア 1 個ぶん: core_cmn ＋ g24_core ＋ RAW ＋ rec_arb） | BIT_KIND 3・PROJ 0x0027_0100。**RAW は 4 コアとも**（F-5） |
| 2f | `build.tcl`（**s45_core_0〜3** の 4 セル、axis_sel4 はコアごと（F-4）、係数・ひねり係数の ROM はコアごと（F-2・F-3）、結線の照合を 4 コアに） | Wide（proj023）の 4 コアの形（F-1）。**URAM・BRAM の総数を事前に足す**（LESSONS、proj025 2f）。戦略は既定と Explore を並べる（LUT 約 64 %） |
| 3 | PS（`G24Backend`、FULL 4 本 × 256 KiB / 10.24 ms） | 流れが 4 本 |
| 4 | 実機 4a 立ち上げ・4b ch → IF・4c 30 分・4d F-2・D_eff。**4 コアに同じ ADC の陽性対照**（F-4） | 4 コアの同等 |

### 2a〜2e・4d-2 の sim — 予言（走らせる前に書く、2026-10-23）

直したもの（B0 の写しから。**ふるまいは変えず、長さ・幅・ID だけ**。proj024-m0 → proj025-m0 の差分（2G-1 → 2G-2）と同じ場所を、もう一段縮めた）:
- 12 bit（k1・m）・4096 ビートのフレーム・Y 27 bit・rd_c 15 bit（32768 ch）・積分器 4096 行（URAM 6 / 面）・GF_L2 7（128 フレーム = 2.048 ms）・N_ACC 640・FULL の TP の F0 × 8（4096 / 512）
- **log2 N の 17 → 16**（g24_core の PARAM[7:0]・NFFT_MIN_MAX・SPEC のレコードの語 4 の下 8 bit。proj025 で取り残しかけた所）・NCH 32768・FRAME_BEATS 4096・語 7 = 262,144（256 KiB）
- dbg_ip_ph の詰めを {4'b0, 入口 12 bit, 4'b0, 出口 12 bit} に
- g24_s45_core: BIT_KIND 3・PROJ 0x0027_0100。引数 RAW は残す（2G-4 は 4 コアとも 1、F-5）
- tb: フレームの数は 2G-2 と同じ（2c〜2e は 10 フレーム）、tb_g24_ds の RAW の N_ACC は 193 → 97（12.13 FULL フレーム）・境目の的を 4095・0・4094・1 に。tb_g24_core の TP_N 16 小フレームは 2 フレームになる
- 判定（check_g24.py）: 期待の NCH・FRAME_BEATS・PARAM・NFFT・IF_ID 0x0203_0101・PROJ・語 4・|Y| の上限を 2G-4 に。**2c の B の式 2^(D1+2) は D1 = 0 で 4**（proj025 で式にしてあるので直さない）
- Makefile: proj025-m0 の sim-lane 〜 sim-g24ds を写した。**2e-2（tb_g22_x2、2 コア）は写していない**（B0 で写した sim/tb_g24_x2.v は 4 コア版 tb_g24_x4.v を作った後に消した）: 2G-4 は 4 コアなので、4 コアに同じ ADC の版を 2e の後に作る

予言（proj025 の結果を長さで読み替えたもの。sim の時間は 2G-2 のおよそ半分。この機械（32 コア）で全部を同時に回す）:
- **2a** `make sim-lane`: 出口 12,288 行・XK_INDEX は bit 反転順（0, 2048, 1024, …）・floor(DFT + 0.5) と全部一致・|RTL − DFT| の最大 ≦ 0.5・|Y| の最大 ≒ 3M（< 2^26）。stall は流し始めた後の待ち 1
- **2b** `make sim-g24a`: ダンプ A・B・C とも 32,768 ch・違う 0。陽性対照（ACC_FIRST_ERR）は全 ch 違う
- **2c** `make sim-g24s`: A1（PFB の出口）が模型と一致・A2 の 2 ダンプとも違う ch 0・B の CW の ch < 0.05 dB・床の比 1 ± 0.02・flags 0。陽性対照（IPQ_POSCTL）は flags で落ちる
- **2d** `make sim-recfr`（中身は proj024・025 と同じ。通るはず）・`make sim-g24core`: SPEC のレコード 8 ＋ 32,768 語・頭の 8 語が期待どおり（語 4 の下 8 bit 16・語 7 = 262,144）・TP が SPEC のダンプと同じ T から・レジスタ 26 個が期待どおり。陽性対照 2 本（積分器の読みの 1 段: 32,767 ch 違う・TP の × 8 を忘れる）は落ちる
- **2e** `make sim-g24s45`（コア 0）: IF_ID 0x0203_0101・PROJ 0x0027_0100・NSTREAM 2、SPEC の中身は模型と一致、TP のずれは FULL −1・コア +1（2G-1・2G-2 と同じ）、SNAP 2 個。陽性対照（DROP_POSCTL）は落ちる
- **2e-2** `make sim-g24x4`（新しく作った 4 コアの tb。proj025 の tb_g22_x2 を 4 コアに）: 4 コアとも IF_ID・PROJ・NSTREAM 2・SID1 0x0204_0100（RAW あり）・CORE_PORT c。**4 コアに同じ ADC（SRC 2）でダンプがコア 0 と bit 単位で同じ（違う行 0 / 4,096 × 3）**・DUMP_F0 が 4 コアで同じ・raw_sel がコア c で c（RAW の SRC がコアごと）・FLAGS 0。陽性対照（X4_DLY: コア 3 の FULL の口に 1 段）はコア 3 だけ 4,096 行とも違い、コア 1・2 は 0
- **4d-2** `make sim-g24ds`: **D_S = +1 ビート**・**D_eff = 1 ＋ 1.5·4096 = 6,145 ビート（24.004 µs）**。陽性対照は D_S 0 で落ちる
- 外れるとしたら: 幅を縮めた所の取り残し（grep の語に掛からない数。proj025 では log2 N と 2c の式の定数）。TP_N 16 小フレームが 2 フレームになるので、2d の TP の数え（「2 フレームに 1 レコード」）が 2G-2 と違う形になるかもしれない

**結果（2026-10-23）: 全部通過・陽性対照は全部落ちた**（RTL のふるまいは直していない。直したのは RTL の ID の値 1 つと、tb・判定・Makefile の取り残し 3 つ。下に）

sim の環境: この機械（Vivado サーバ、32 コア）の iverilog（/usr/bin）。並べて回した。

| | ふつう | 陽性対照 | 時間 |
|---|---|---|---|
| 2a sim-lane | 通過（12,288 行・bit 反転順・floor と全部一致）。stall も通過 | — | （2a〜2c・recfr を並べて 8 分） |
| 2b sim-g24a | A・B・C とも 32,768 ch・違う 0 | ACC_FIRST_ERR: 落ちる | |
| 2c sim-g24s | A1 36,864 ビート 違う 0・A2 の 2 ダンプとも違う ch 0 / 32,768・B の CW −0.000 / +0.000 dB・床の比 1.0006 / 1.0003・flags 0 | IPQ_POSCTL: 落ちる | 1 本 4 分 |
| 2d sim-recfr | 通過 | EQ_POSCTL: 落ちる | 1 分 |
| 2d sim-g24core | SPEC 32,776 語・頭の 8 語とも期待どおり・中身の違う ch 0・TP がダンプと同じ T（F0 32 小フレーム = T 16,384）から・レジスタ 26 個とも期待どおり | POSCTL: 32,767 ch 違う / TP_POSCTL: TP_F0 4（期待 32）で落ちる | 3 本並べて 11 分 |
| 2e sim-g24s45 | IF_ID 0x0203_0101・PROJ 0x0027_0100 などレジスタ 15 個・SPEC の中身 違う 0・TP のずれ FULL −1・コア +1・SNAP 2 個とも ADC 1 と一致・捨てた数の帳尻 2 = 2 | DROP_POSCTL: rec_drop 1 ≠ LATE 2 で落ちる | 2 本並べて 10 分 |
| **2e-2 sim-g24x4**（4 コア、新しく作った） | 4 コアとも IF_ID・PROJ・NSTREAM 2・SID1（RAW あり）・CORE_PORT c。**4 コアに同じ ADC（SRC 2）でダンプがコア 0 と bit 単位で同じ（違う行 0 / 4,096 × 3）**・DUMP_F0 4 × 4・raw_sel 0・1・2・3・FLAGS 0 | X4_DLY（コア 3 の口に 1 段）: コア 3 だけ 4,096 行とも違い、コア 1・2 は 0 | 2 本並べて 12 分 |
| **4d-2 sim-g24ds** | インパルス 8 個・FULL の 4 タップが模型と一致・境目 m = 4095・0 を通った・**D_S = +1**・重心 6,144.000 → **D_eff = 6,145 ビート（24.004 µs）** | DS_POSCTL: D_S +0 で落ちる | 2 本並べて 14 分 |

- 予言はどれも当たった（数の上では）。予言の「外れるとしたら」の取り残しは、log2 N などの RTL の数ではなく、**tb の「クロックの数で書いた長さ」と判定の「溢れを起こすための長さ」**に出た（2・4）
- 直したもの（直した後に、その sim を回し直した）:
  1. **g24_s45_core の PROJ の 10 進の値**: 0x0027_0100 のつもりで 2,555,904（= 0x0027_0000、0x0100 を足し忘れ）と書いていた。**2e-2 のレジスタの照合で落ちた**（ダンプの同等は 1 回目から通っていた）。2,556,160 に。
     4d-2 は直す前の RTL で回した（PROJ は D_S・D_eff に関わらない。ほかの sim は g24_s45_core を使わないか、直した後に回した）
  2. **tb の入力の長さ 10 → 12 フレーム**（tb_g24_spec・core・s45 と check の SPEC_NB）: 2c の 1 回目は、2 個目のダンプの後の読み出しの確かめ（4,200 クロック）の間に入力が尽き、**「入力が途切れた」の見張り（flags[2]）が正しく立って**落ちた（中身は 1 回目から bit 単位で一致）。2G-2 の 10 フレームは 8,192 ビートのフレームで余っていた
  3. **Makefile の競争**: sim-g24s が x.hex を毎回作り直していたので、make -j で並べた 2d・2e が書きかけの x.hex を読んで X が混ざり、判定が止まった。「無ければ作る」に
  4. **2e の「捨てた数」の見張りが立たなかった**（帳尻 0 = 0 で、判定の「TP_REC_LATE0 ≧ 1」で落ちた）: 2G-2 の tb は TP の 1 個を 16 小フレーム = 1 フレームにし、512 KiB の SPEC が出口を塞ぐ間に TP の溜め 2 面を溢れさせていた。
     2G-4 では 16 小フレームが 2 フレームで、SPEC は 256 KiB で塞ぐ時間も半分なので溢れない。tb_g24_s45 の TP_N を 8（= 1 フレーム、2G-2 と同じ比）に、判定に S45_TPN を足した。**見張りが立たない sim は見張りが壊れているのと区別がつかない**ので、溢れを起こす側を直した
- 2e-2 は F-4 の「複数のコアに同じ ADC = 同等の陽性対照」の sim 版。RUN は AXI でコア 0 → 3 の順に書いたが、同じ格子の中なので F0 は 4 コアで同じになった

### 2f. build.tcl を 4 コアに — 予言（ビルドの前に書く、2026-10-23）

`build.tcl`（B0 で写した proj025-m0 の 2G-2 を直した。冒頭の 1.〜6.）:
- `set proj proj027`（proj025 2f で取り残した所。最初に直した）・レーン FFT 4096 点・出力 28 bit（RTL は下 27 bit）・K_F の注 mod 4096・**GF_L2 7**（RTL の既定と同じ。proj025 の 6 のままだと読み返しの照合は通るが 4.096 ms の格子になる）・表の行数（係数 1024・A 32）・BIT_KIND 3・PROJ 0x0027_0100
- **s45_core_0〜3、RAW は 4 コアとも 1**（F-5）。CORE_PORT はコア c = ADC c（A・B は Tile 226、C・D は Tile 224）。ギアボックスの制御は 4 ch ともコアが握る
- **axis_sel4 × 8**（full_sel_0〜3・raw_sel_0〜3、F-4・F-5）。gb_bc_i は 9 本（M00 コア・M01〜M04 full_sel・M05〜M08 raw_sel）。SmartConnect の M は 7。s45_ring_0 の NIN 4
- **縛り（tie_*・gb_tie_*）は作らない**: 4 コアとも RAW を持ち、ring の入口も 4 本全部使うので、縛る入口が無い。空いた入口が残れば BD 41-759 が vivado.log の見張りで止める
- 結線の照合: ch_nets・shared_nets を 4 コアの表から作る（張る側と照らす側が同じ表）。在ってはいけない側に「セル s45_core_[4-9]*・full_sel・raw_sel（2G-1・2G-2 の名前）・tie_*・gb_tie_* が無い」「axis_sel4 が 8 個・gb_bc の NUM_MI 9」「コア c の full_sel・raw_sel のネットにほかのコア・もう一方の種類の sel が載っていない（新しく sel_other）」。
  陽性対照は (a)〜(k) を 4 コアに（(h) は raw_sel_0、(i) は 4 ch × 3 本 = 12、(k) はコア 3）、足したもの: **(j2) コア 3 の raw_sel に raw_sel_2 を期待する・(l) sel_other をコア 0 の正しいネットにコア 1 として当てる**
- OOC の自作の run は 22（proj025 の 15 から s45_core +2・full_sel +2・raw_sel +3）。ROM のラッパ・$readmemh・配置後の ROM の BRAM はコアごとに 4 個
- build_post.tcl: ROM の BRAM の予言（係数 2・ひねり係数 12）・lane_fft_g24 64 個・積分器・PFB・RAW の報告を 4 コアに
- Makefile: proj025-m0 の build・post を写した。**BUILD_JOBS の既定 30 → 8**（Vivado は並行で使う、上限 8）
- Tcl の括弧の完結は tclsh で確かめた（Vivado ではまだ回していない）

**資源の総数を先に足す**（LESSONS、proj025 2f の URAM の溢れ。部品ごとの実測から）:

| | 1 コア | 4 コア ＋ 共通 | デバイス | 内訳の出どころ |
|---|---|---|---|---|
| URAM | 12（積分器 8 銀行 × 48 bit = 384 bit → 6 個 / 面 × 2 面） | **48** | 80（60 %） | proj025 は 65536 ch で 24 / コア |
| BRAM タイル | レーン FFT 16 × 7 = 112・PFB の履歴 ≒ 75（4096 × 672 bit、4K × 9 の詰めで 74.7）＋ 係数 2・ひねり係数 11.5・TP 2・RAW 7.5 = **≒ 210** | **≒ 842**（＋ ring 2） | 1080（**78 %**） | S-1 の 4096 点・rev 7（proj025 の 8192 点は OOC 13 = 配置後 13）・proj025 の PFB 153.5（8192 × 672 bit）の半分 ＋ 係数の差・proj025 の tw・TP・RAW の実測 |
| DSP | レーン FFT 16 × 27 = 432・PFB 144・鎖 144・ひねり係数 60・TP 24 × 2 = **828** | **3,312** | 4272（**77.5 %**） | proj025 の 1 コア 924（内訳まで実測）− レーン FFT の差 6 × 16 |

- PFB の履歴を URAM に回す余地は無い（4 コアで ≒ 40 個要り、空きは 32）。proj025 と同じ `ram_style = "block"` のまま
- LUT: W の見込み 64.0 % に、axis_sel4 が 3 個多い分（proj025 の実測 258 × 3 = 774）と SmartConnect の M +2 を足して **63.5〜65.5 %**。FF ≒ 58〜62 %

予言（`make build`、`-1`）:
- BD の段階: vivado.log の CRITICAL WARNING は陽性対照の目印 1 件だけ（BD 41-759 は出ない）・結線の照合 問題 0・陽性対照 (a)〜(l) が全部落ちる。ROM のラッパは 4 コアとも 4 本・$readmemh の失敗 0（読めた印 16）・Synth 8-3848 0（自作の run 22 個）
- 資源: lane_fft_g24 64 個・1 個 DSP 27・DSP 3,312・BRAM ≒ 842（78 %、±10）・URAM 48・LUT 63.5〜65.5 %。ROM の BRAM は 4 コアとも係数 2・ひねり係数 11〜12
- CDC: CDC-3 Info 105・CDC-6 Warning 5（45 ＋ 15 × コア・1 ＋ コア、proj023 の 4 コアと同じ）・CDC-15 は RFDC の中で ≒ 3,137
- **タイミング: 既定の戦略では閉じない見込み（WNS −0.25〜−0.02 ns）**。Wide（4 コア、LUT 60 %）は Explore で +0.001 ns、2G-4 は LUT・DSP・BRAM のどれも Wide より混む。Performance_Explore は −0.10〜+0.05 ns で五分。負の経路の塊は PFB の履歴の BRAM のカスケード・積分器の URAM・コアをまたぐ axis_sel4 の出口（256 bit × 8 本が 4 ADC から集まる）
- 外れるとしたら: BD の組み方（sel_names から作った表・ring の 4 本）・axis_sel4 の VLNV の数え（`module_ref:axis_sel4` の filter）・BRAM の PFB の詰め（4K × 9 で詰まらなければ 76〜80 / コアで +16）

**ビルド 1（2026-10-23 17:00〜、西村さんの決め: 既定 `build/` と Performance_Explore `build-PE/` を BUILD_JOBS 4 ずつで並べる。計 8）**

途中まで（BD 〜 OOC。2 本とも同じ）:
- BD の段階は予言どおり: **結線の照合 178 行・問題 0・陽性対照 (a)〜(l) が全部落ちた**（(i) は 12 / 12、(l) 2 件、(j2) 1 件）・vivado.log の CRITICAL WARNING は目印 1 件だけ（BD 41-759 は出ない）。output_width を読めない ERROR 2 行は catch の中で、proj025 のビルドにも同じ 1 組がある（ポートの幅の照合 m_axis_data_tdata 64 は OK）
- ROM のラッパ 4 コア × 4 本・OOC 46 個・$readmemh の失敗 0（**読めた印 16**）・Synth 8-3848 0（**自作の run 22**）。予言どおり
- **Vivado が落ちた回数が多い**（2 本を並べた日）: build/ の OOC で gb_bc_2（`librdi_synth.so is corrupt` の Abnormal program termination (6)。同じ時刻にほかの run は同じ .so を読んで通っている）・rst_ctrl（segfault）・s45_core_3（下）。
  build-PE/ の impl_1 は link_design の DCP の継ぎ合わせで 2 回（signal 7 `HATAttrValueMap::~HATAttrValueMap`・signal 11 `HANEBuilderDbImpl::setInstMaster`。proj025 2f の open_run の落ち方 `HANENetlist::copyAttrsToAttrMap` と同じ辺り）、回し直しの 2 回目（上限）で通った
- **新しい型: 合成の並列の子（task_worker）が segfault すると、親の Vivado は終わらずに待ち続ける**（s45_core_3、17:09 に子が落ち、親は CPU 2 % のまま 1 時間）。run に終わりの印（.vivado.end.rst / .error.rst）が出ないので、build.tcl の `wait_on_run` も止まり、「落ちた run の回し直し」が働かない。
  親（その run の vivado だけ）を kill すると .error.rst が出て、runme.log の「segfault in」を build.tcl が拾い、3 個とも 1 回目の回し直しで通った。見張りに「終わりの印の無い run のログが 40 分書かれない」を足した

**build-PE/（Performance_Explore、`-1`）: 完走し、閉じた — WNS +0.032 ns / WHS +0.010 ns**（19:10 に .bit、後段の照合は全部通過）

| | 結果 | 予言 | |
|---|---|---|---|
| タイミング | **WNS +0.032222 ns / WHS +0.009505 ns**（上位 5 本はどれも clk_out2（256 MHz）の中）。配置の後の見込みは +0.277 | Explore −0.10〜+0.05 | 当たり（上のほう） |
| URAM | 48（60.00 %、積分器 12 × 4） | 48 | 当たり |
| BRAM | **842 タイル（77.96 %。RAMB36 390・RAMB18 904）**。1 コア: レーン FFT 16 × 7・PFB 77（履歴 75 ＋ 係数 2）・ひねり係数 11.5・TP 2・RAW 7.5 | ≒ 842 | 当たり（部品ごとに一致） |
| DSP | **3,312（77.53 %）**: 1 コア 828 = レーン FFT 432（27 × 16）・PFB 144・鎖 144・ひねり係数 60・TP 24 × 2 | 3,312 | 当たり |
| LUT | **274,731（64.60 %）**。1 コア ≒ 64,400（レーン FFT 1 個 3,250 = OOC 3,434 の 0.946）・axis_sel4 1 個 258・smc_ctrl 1,388 | 63.5〜65.5 % | 当たり。目安 65 % まで 0.4 % |
| FF | 505,719（59.46 %） | 58〜62 % | 当たり |
| ROM の BRAM | 4 コアとも係数 2.0・ひねり係数 11.5 | 2・11〜12 | 当たり |
| CDC | CDC-3 Info 105・CDC-6 Warning 5・CDC-15 Warning 3,137（ほかの分類 0） | 105・5・≒ 3,137 | 当たり（proj023 の 4 コアと同じ） |
| run の CRITICAL WARNING | なし | | |
| 1PPS | pps_trig AH13・pps_comp AJ13（LVCMOS18） | | 照合を通った |

- 指紋: BUILD_TAG s45_core_c 0x50c0000c（c = 0〜3）・time_core_0 0x50900000。CORE_PORT 0x2200・0x0201・0x2002・0x0003（ADC_A〜D）・RAW 4 コアとも 1
- sha256: proj027.bit `8b35ecd411fb100bf3190169cbc46bcfb6ff22ae788aa6ddfa26b4fdf3eed511`（34,437,476 B）/ proj027.hwh `6678f34ea24cc44261ae1903777e9fe5b43b4252ebb426404ca0473535830ae5`
- 予言の外れ: タイミングは「既定では閉じない・Explore は五分」と書き、Explore は閉じた（既定は下）。資源は全部当たり。Vivado の落ち方（並列の子の segfault で親が止まる）は予言に無かった

**build/（既定の戦略、`-1`）: 配線までは閉じたが、.bit は残らなかった**
- 配置の後の見込み WNS −0.256 ns → 配線の後の phys_opt で **WNS +0.008 ns / WHS +0.010 ns**（runme.log の Post Physical Optimization Timing Summary。routed.dcp も書いた）。**予言の「既定では閉じない（−0.25〜−0.02）」は外れ**（配置の後の見込みは予言の幅の中だった）
- その後 **write_bitstream の前の DRC で segfault**（20:23、`HDPLPlaceDBImpl::clear`）。build.tcl の回し直しは `reset_run impl_1` から始めるので、**配線済みの結果（routed.dcp）を消して最初からやり直し**、2 回とも link_design で落ちて（20:26・20:30）上限で止まった（`ERROR: impl_1 が完走していない`）
- **回し直しの欠け**: 落ちた段が write_bitstream でも合成からやり直す。impl の後ろの段で落ちたときは、reset せずに残っている段から（`launch_runs impl_1 -next_step` か routed.dcp を開いて write_bitstream）回すべき。build.tcl は直していない（直すなら次のビルドの前に）
- 既定は回し直さない: 閉じた .bit は build-PE/ にあり、余裕も Explore のほうが大きい（+0.032 > +0.008）

**回し直しの直し（2026-10-26、ビルドは回していない）**
- `build.tcl` の impl_1 の回し直しを、**落ちた段（`CURRENT_STEP`）から後だけを reset する**形にした（`reset_runs impl_1 -from_step <段>` → `launch_runs impl_1 -to_step write_bitstream`）。init_design（link_design）で落ちたとき・synth_1 が落ちたときは、失うものが無いので今までどおり丸ごと reset する。`-from_step` の reset ができなければ丸ごとの reset に逃げずに `exit 1`
- 完走の判定を PROGRESS から **STATUS が「write_bitstream Complete!」かつ impl_1 に .bit が 1 個**に変えた。`-from_step write_bitstream` の reset の直後は、PROGRESS が 100%（STATUS は「route_design Complete!」）になるため。PROGRESS だけで見ると、.bit が無いのに「完走した」と読む
- 確かめ方（小さな設計、xczu48dr、scratchpad で。リポジトリには置いていない）: write_bitstream の TCL.PRE で自分に SIGSEGV を送り、ビルド 1 の build/ と同じ印（`Abnormal program termination (11)`、`.vivado.error.rst`、routed.dcp あり、CURRENT_STEP は write_bitstream）を作った。build.tcl から切り出した proc と回し直しの塊をそのまま回すと、`NOTE: impl_1 の write_bitstream で Vivado が落ちた。write_bitstream から後だけを回し直す（1 回目）` → `open_checkpoint top_routed.dcp` → `write_bitstream` だけを回して完走した（routed.dcp は reset の前後で md5 が同じ）
- 確かめていないこと: write_bitstream 以外の段（place_design・route_design など）で落ちたときの `-from_step`。2G-4 の本番のビルドでも、まだ通していない（次のビルドが初めて）

**知見の候補（LESSONS.md・lessons_all.md には、まだ足さない。2026-10-26、西村さん「まずは README だけで様子を見る」）**
- 並列の task_worker が segfault すると、親の Vivado は終わらずに待ち続ける。終わりの印が出ないので wait_on_run も止まり、回し直しが働かない（上の s45_core_3）
- impl の回し直しで `reset_run impl_1` をすると、後ろの段で落ちたときに配線済みの結果を消す。`-from_step` で落ちた段から。その reset の直後は PROGRESS が 100% になるので、完走の判定に PROGRESS を使わない

**2f の結論: 実機に載せるのは build-PE/ の proj027.bit・.hwh**（Performance_Explore、WNS +0.032 ns。sha256 は上）。LUT 64.6 % は目安 65 % の内側。既定の戦略でも配線までは閉じた（+0.008）ので、2G-4 は戦略に依らず閉じる線にいる

### 3. PS — 土台と手順（2026-10-26 から）

**土台: proj029 の閉じた commit 5164a02 の `pynq/`**（＋ `tools/loopsum.py`）。proj029 の `pynq/` は proj025-m0 の `pynq/`（B0 で写したもの、proj025 の今の版とも同じ）に C の道を足したもので、
差は全部「足した」側（変えた既存の行は 5 ファイルで計 16 行）・新しい選択（`--fast`・`--fast-ring`・`--prefault`）は既定で切ってある・C の道（`s45fast.c`・`plring.LazyRec`）は ch の数にも 2G-2 にも縛られていない。
→ 2G-4 の tint 10.24 ms も、この道で回せる見込みがある（下の 3d）。**写したのは追跡しているファイルだけ**（`git show 5164a02:proj029/…` で 11 個: 足した 6・差し替えた 5。`libs45fast.so` は `.gitignore`）。
**写した後に `test_fake.sh all` は 23 試験とも通過**（2026-10-26、この PC）

作り（2G-2 の道を広げる。2G-1・2G-2 の道は残し、test_fake の g21・g22 の 7 試験が回し直しの対照になる）:
- 2G-2 の定数を **形（geometry）の表**にまとめ、`G2_*` の名前は 2G-2 の値のまま残す（`test_ring_fast.py` が使う）。2G-4 の形: **コア 4・NCH 32768・FRAME 4096・PL_NACC 640・D_S +1**（4d-2 の sim の D_eff 6,145 = 1 ＋ 1.5·4096）・
  **df 62.5 kHz**（fs / N、N = 65536）・IF(c) = 4096 − c·df・**if_mhz = 送る 2047 番目 = ch 30720 = 2176 MHz**・窓 **A0・B0・C0・D0 = コア 0〜3 の FULL（s 0）**（窓 j = 2·コア ＋ s を崩さない）
- `G22Backend`・`FakeG22Backend` の中の `G2_*` を形の表から読む形にし、**`G24Backend`・`FakeG24Backend` は形だけを替えた子**。違いは RAW: 2G-2 は「コア 0 だけに 1 本・コア 1 は NSTREAM 1」、
  **2G-4 は 4 コアとも RAW 1 本（NSTREAM 2）**（F-5）。SNAP は 2G-2 と同じく**コア 0 の RAW**（SRC で ADC を選ぶ。コア 1〜3 の RAW は PS からはまだ使わない）。`snap_stream` は「RAW が 1 本」を前提にしているので、G24 はコア 0 の RAW を直に持つ
- 3a. ID: `s45core` に PROJ_G24 0x0027_0100・BIT_KIND_G24 3（BIT_KINDS[3] = 2G-4 は既に在る）・`TimeCore.IDS` に **0x0203_0102**・
  CAL[0x0027_0100] は **pps_det_ns 71.5（LPF の分、形 (b)）・adc_to_core_ns None**（未較正。4 の F-2 で測る。proj025 の値は別の Overlay なので持ち込まない）・VERSION proj027-0.1
- 3c. specd に `--g24`（bits.json の `"kind": "g24"`）。SET のキーは tint・fmt・cfg・**A0〜D0.src・A0〜D0.shift**・all.shift・shift。既定 src = (A, B, C, D)・shift 7。4 コアに同じ ADC も許す（4 の陽性対照）。
  `src` だけ（窓なし）・A1・E0 など流れの無い窓は ERR。START・begin は 2G-2 と同じ手順を 4 本に（**4 本の RUN_F0 が同じ**・FULL の TP の F0 = RUN_F0 × 8・RUN_T = START_AT ＋ 1）
- **TP の欄の割り付け**は 2G-2 の決めを 4 コアに: FULL の TP（コア c → 欄 src[c]、空いていれば）を先に、次にコアの TP（コア c → 欄 c、空いていれば）。既定（A, B, C, D）は FULL の TP 4 本だけ、
  (B, B, B, B) は コア 0 の FULL → B ＋ コア 0・2・3 のコアの TP → A・C・D の 4 本
- SPEC v2: kind 1・ns 0・nch 32768・中身は IF の昇順（送る i ↔ ch c = 32767 − i）・nacc = n_sum × 640・bit_kind 3。DUMP_T の進みは nacc × 4096（tint 40.96 ms で 2560 × 4096 = 10,485,760、2G-2 と同じ）。
  受け側の溜め: keep_of(500, 32768) = **62 ダンプ / 窓**

3a・3c の予言（PL なし。test_fake に g24・g24same・g24p・g24cli を足す。2026-10-26、走らせる前に書く）:
- 既存の 23 試験（g21・g22 の 7 本を含む）は全部 OK（判定に使う数は土台と同じ）
- **g24**: `SET tint=0.04096 A0.src=D B0.src=C C0.src=B D0.src=A shift=7 fmt=both`・START n=30 → **SPEC 240**（30 × 4 窓 × u64・f32）・組 120・不一致 0・照合 通過。f32 の記録 120 個は
  窓ごとに 30 個（A0〜D0 = core 0〜3・src 3・2・1・0）、どれも kind 1・s 0・ns 0・nch 32768・nacc 2560・df 62500・bit_kind 3、軸は 4096 − (32767 − i)·df と一致し昇順。
  **TP の ADC は ABCD**（FULL の 4 本）。同じ試験の中の陽性対照: 1 ch ずらした軸（32768 − i）で 120 個全部 NG
- **g24same**: `A0.src=B B0.src=B C0.src=B D0.src=B` → 4 窓とも src 1・**TP の ADC は ABCD**（B は FULL 1 本、A・C・D はコアの TP）
- **g24p**（陽性対照）: `A0.src=E`・`shift=16`・`A1.shift=7`・`E0.src=A`・`src=B`（窓なし）・`tint=0.03` は全部 ERR。`A0.src=B D0.src=B C0.shift=3` は通り、GET に A0.src=B・D0.src=B・C0.shift=3・D0.shift=7
- **g24cli**: s45client で acquire(80)（62 の上限が効く数）→ A0〜D0 とも手元 **62 ダンプ × 32768 ch**・軸 32768 個の昇順・説明のない欠け 0・CRC 0（4 窓を数えて時間切れにならない）
- **C の道でも同じ**: `FAST="--fast --fast-ring --prefault" bash test_fake.sh all` が 27 試験とも通過。`test_s45fast.py` に n 32768 を足して照合が OK（今の 22 項目は 65536・131072）、`test_ring_fast.py` 24 項目は OK（2G-2 の形のまま）
- `_spec_record_full` を時計の偽物で直に呼ぶと、2G-4 の cfg で utc の引き算は **D_eff 6,145 ビート = 24,003.9 ns**（2G-2 は 48,003.9）
- 外れるとしたら: 2G-2 の 65536・8192・2 を直に書いている所の取り残し（G22Backend の中の `[1, 0]`・`check_tiles`・ログの文言、FakeG22 の `bit_kind = 10`）。偽物は束ねないので nacc の欄は cfg の値そのまま
- 実機の道（G24Backend）は PL が無いと通らない。4 で初めて走る（ここでは import と、偽物と共有する関数の試験だけ）

**3a・3c 結果（2026-10-26）: 全部 OK・予言は全部当たり**（この PC。`test_fake.sh all` は 23 ＋ 4 = 27 試験を、今の道と `FAST="--fast --fast-ring --prefault"` の両方で）
| 試験 | 結果 |
|---|---|
| 3a の import | BIT_KINDS[3] = 2G-4・PROJ_G24 0x0027_0100・BIT_KIND_G24 3・IDS に 0x0203_0102・CAL[0x0027_0100] は pps_det_ns 71.5・adc_to_core_ns None・VERSION proj027-0.1。形: PL_NACC 640・df 62500・if_mhz 2176.0・鍵 A0〜D0 |
| g24 | SPEC 240・組 120・不一致 0・照合 通過。f32 の 120 個は窓ごとに 30（A0〜D0 = core 0〜3・src 3・2・1・0）、どれも kind 1・s 0・ns 0・nch 32768・nacc 2560・df 62500・bit_kind 3、軸は 4096 − (32767 − i)·df と一致し昇順。**TP の ADC は ABCD**。GET に A0.src=D・D0.src=A・D0.shift=7 |
| g24 の中の陽性対照 | 1 ch ずらした軸（32768 − i）では 120 個全部が NG |
| g24same | 4 窓とも src 1（20 × 4）・**TP の ADC は ABCD**（B は FULL、A・C・D はコアの TP） |
| g24p（陽性対照） | A0.src=E・shift=16・A1.shift・E0.src・src（窓なし）・tint=0.03 の 6 個とも ERR。A0.src=B D0.src=B C0.shift=3 は通り、GET に D0.shift=7 |
| g24cli | acquire(80) で A0〜D0 とも手元 62 ダンプ × 32768 ch・軸 32768 個の昇順・説明のない欠け 0・CRC 0 |
| 既存の 23 試験（g21・g22 の 7 本を含む） | 両方の道で全部 OK（判定に使う数は土台と同じ。2G-2 の道を形の表に広げた後も g22 の 4 本が通った） |
| C の道 | `test_s45fast.py` は n 32768 を足して 34 項目とも OK（NG 0）、`test_ring_fast.py` 24 項目 OK。FAST の回の specd のログに「SPEC の記録（FULL）は C」。**偽物はリングを通らないので `--fast-ring` は働いていない**（実機だけ） |

- utc の引き算: `_spec_record_full` を遅れ 0 の時計で直に呼んで、2G-4 の cfg で **24,003 ns**（予言 24,003.9 の整数への切り捨て。式は `(D_S ＋ 1.5·L)·125 // 32`）・bit_kind 3・nch 32768・nacc 640・if_mhz 2176・df 62500。2G-2 の cfg で 48,003 ns（土台と同じ）
- 予言の「外れるとしたら」に書いた取り残しは、全部を形の表に移した（G22Backend・FakeG22Backend の中に `G2_*` は残っていない。`check_tiles(…, 2)` はナイキストゾーンで、bit に依らない）
- 足したもの: `s45acq.py` に `G2Geom`（G2_GEOM・G4_GEOM）・**G24Backend・FakeG24Backend**（G だけを替えた子）、`check_g22`・`g22_cfgs` は形を引数に（既定は 2G-2）・`g22_tp_slots` はコアの数を len(src) から・
  RAW の照合はコアごとの本数と NSTREAM を形から・SNAP の流れはコア 0 の RAW を直に（`snap_stream` を使わない）・Acq に `g24`・`g2`（形）・`_set1_g22` の鍵を形から。
  `specd.py` に `--g24`・`"kind": "g24"`・GET の A0〜D0、`s45core.py` に PROJ_G24・BIT_KIND_G24、`timebase.py` に IDS・CAL、`test_fake.sh` に g24・g24same・g24p・g24cli、`test_s45fast.py` に n 32768
- **実機の道（G24Backend）はまだ一度も走っていない**。4 で最初に確かめること: discover の CORE_PORT [0, 1, 2, 3]・4 コアとも NSTREAM 2（RAW 1 本）・4 本の WRST の後の SRC = 0x8000_000s・
  **4 本の RUN_F0 が同じ**・FULL の TP の F0 = RUN_F0 × 8・RUN_T = START_AT ＋ 1・ch → IF = 4096 − c·df（SG の CW で、4 窓とも）・D_S = +1（F-2 の RAW と並べて）・1 BASE の時間（下の 3d）

3d の見込み（tint 10.24 ms、4 の実機で測る。予言は 4 の前に書き直す）: 1 BASE に SPEC の記録が 4 本 × 32768 ch = 2G-2 の 2 本 × 65536 ch と同じ ch の数・同じバイト数（1 MiB）。
C の道（`--fast --fast-ring --prefault`）で 2G-2 は 6.2 ms（61 %）。2G-4 は記録の本数が倍なので、1 本ごとに掛かる分（put 0.21・poll 0.1 ms ほど）が ≒ 0.6 ms 増え、**≒ 6.8 ms（66 %）**の見込み

### 4. 実機 — 手順と予言（2026-10-26、走らせる前に書く）

載せるもの: **build-PE/ の proj027.bit・.hwh**（2f ビルド 1、Performance_Explore。sha256 `8b35ecd4…eed511`・`6678f34e…830ae5`、上の 2f と同じ）と pynq/（*.py・*.sh・s45fast.c）・tools/loopsum.py。
ボードの `~/proj027/` に送り、ボードで sha256 を照らしてから使う。**ボードの作業はこの会話から ssh で**（2026-10-26 から。鍵はこの機械の専用の鍵、root は鍵で。命令は `bash -lc` で pynq-venv を読む）。
受けはこの PC（specrecv `--host $B`）。**命令を先に、受けを後に**（proj025 4a の手順の誤りの改め）。tint 10.24 ms の測りだけは受けもボードの上（送り出し 51 MB/s は NIC を越える、proj029）
判定の道具は `pynq/g24cw.py`（g22cw の 4 窓版）。PL なしの確かめ（この PC、2026-10-26）: 偽物の記録（g24、src D・C・B・A）で頭の欄・DUMP_T の進み 10,485,760・4 窓の DUMP_T の揃いが通る。
窓ごとに中身が違う偽物（g24same）では `--same` が 3 窓とも 0 / 20 組で落ちる。B0〜D0 を同じ DUMP_T の A0 に書き換えた合成の記録では 20 / 20 組で通り、陽性対照 `--posctl-same` は落ちる
（ただし偽物の中身はダンプの間でほとんど変わらないので、ずらしても 13 / 19 組は同じ。陽性対照が本当に効くのは雑音がダンプごとに変わる実機）。
`widef2.py` は 2G-4 に直した（discover(bit_kind=3, ncore=4)・4 コアとも RAW 1 本を照らす・`--raw-core`（既定 0）のコアの RAW を直に取る・CAL の鍵 0x0027_0100・既定の .bit proj027.bit）

**順番（今の配線 P から。2026-10-26、西村さん）**: 配線に依らない照合を配線 P のうちに済ませる → **4a-P 立ち上げ（＋ 4 コアの同等）→ 4c-P tint 10.24 ms の 1 BASE → 4d F-2** →（配線を変えて）4a の床・4b ch → IF・4c 30 分

**4a-P 立ち上げ（配線 P: 1PPS を分配して PPS Clk と ADC_A〜D に。LPF は PPS Clk の枝だけ。入力は 1 秒に 1 回の縁と ADC の床）**
- ボード: `specd.py --g24 --bitfile proj027.bit --clkin 0 --ref 10` → この PC: `specctl`: ID・STATUS → SET → `START n=200` → `specrecv.py --host $B --out runs/…`
  - 4a-P1: `A0.src=A B0.src=B C0.src=C D0.src=D shift=7`（既定の割り当て）・**今の道（Python）** → `runs/g24_4a1.s45`
  - 4a-P2: `A0.src=D B0.src=C C0.src=B D0.src=A`（SRC の道を 4 本とも入れ替える）・**C の道（`--fast --fast-ring --prefault` で specd を起こし直す）** → `runs/g24_4a2.s45`
  - **4a-P3（F-4、4 コアの同等）**: `A0.src=C B0.src=C C0.src=C D0.src=C fmt=both`・`START n=50`・C の道 → `runs/g24_4a3.s45`
- 予言:
  - 起動: ID の adc = **02030101**・time **02030102**・proj **00270100**・win は 4 本の SID を「/」でつないだもの・ログに「リング … SIZE 67108864（2G-4: FULL 4 本・256 KiB のレコード × 4）」と mallopt
  - **START が通る**（= G24Backend の照合が全部通る: discover の CORE_PORT [0, 1, 2, 3]・**4 コアとも RAW 1 本・NSTREAM 2**・4 本の WRST の後の SRC 0x8000_000s・NCH 32768・FRAME_BEATS 4096・RUN_SHIFT 7・
    **4 本の RUN_F0 が同じ**・FULL の TP の F0 = RUN_F0 × 8）。RUN_T の WARN なし
  - 記録（g24cw）: 4a-P1・P2 とも 4 窓 × 200・CRC 0・説明のない欠け 0・照合 通過・頭の欄が期待どおり（core 0〜3・nacc 2560・df 62500・bit_kind 3）・DUMP_T の進み 10,485,760・DUMP_K 1 ずつ・**4 窓の DUMP_T が揃う**。
    TP の ADC は P1・P2 とも {A, B, C, D}（FULL の TP 4 本）
  - 床（1 フレームあたりの中央値）は記録するだけで判定しない（配線 P の入力はノイズソースでない。床の予言は配線を変えた後の 4a で書く）
  - **4a-P3: 同じ DUMP_T の B0・C0・D0 が A0 と u64 で bit 単位で同じ（3 窓とも 50 / 50 組）**（2e-2 の sim の実機版。proj025 4a-3 は 2 コアで 50 / 50）。陽性対照 `--posctl-same` は 3 窓とも 0 / 49 組。
    TP の ADC は {A, B, C, D}（コア 0 の FULL → C・コア 0・1・3 のコアの TP → A・B・D）
  - STATUS（STOP の後）: miss・kgap・r_bad・**loop_slow 0**・drop・ring の drop・tp_lost・tp_bad 0。bdrop は 4 以下（止めたときの束ねの途中の分、4 窓 × 1）。
    4a-P1（Python の道、tint 40.96 ms）の 1 BASE の処理（周の間隔から割り戻す、proj025 4c の読み方）は **≒ 9〜10 ms**（2G-2 の TP 4 本の形 8.7 ms ＋ 記録の本数が倍の分）。**自信は低い**: 10.24 ms を越えると遅れが溜まり続ける
  - 自信が低い所: 4a-P3 の bit 単位の一致（4 コアの配置が別。違えば違う ch の数と場所を見る）

**4a-P の結果（2026-10-26 02:25〜02:31 UTC、配線 P、ボードの `~/proj027/`、この会話から ssh）: 全部通過・予言どおり**
- 起動: ID adc 02030101・time 02030102・proj 00270100・win 02010000 × 4・「リング … SIZE 67108864（2G-4: FULL 4 本・256 KiB のレコード × 4）」・mallopt OK・錨 EPOCH 1（予言どおり）。
  **START が通った**（G24Backend の照合: CORE_PORT [0, 1, 2, 3]・4 コアとも RAW 1 本・NSTREAM 2・4 本の SRC の読み返し・NCH・FRAME_BEATS・RUN_SHIFT・**4 本の RUN_F0 が同じ**・FULL の TP の F0 = RUN_F0 × 8）。RUN_T の WARN なし。
  TP の較正（tp_cal.json）は bit の ID が違うので使わない（予言に無いが正しい振る舞い）

| | 道 | 記録・受け | g24cw | 床の中央値（A0〜D0） | TP の ADC | STATUS（STOP の後） |
|---|---|---|---|---|---|---|
| 4a-P1（src A・B・C・D） | Python | 4 窓 × 200・CRC 0・照合 通過 | 全部通過（DUMP_T の進み 10,485,760・4 窓が揃う） | 6.05・7.26・7.77・7.99 | **ABCD** | miss・kgap・drop・pl_drop・loop_slow・tp_lost・r_bad 0、bdrop 4。loops 264・loop_max 40.76・p99 37.9 ms |
| 4a-P2（src D・C・B・A） | C | 同上 | 全部通過 | 7.98・7.70・7.24・5.99 | **ABCD** | 同上（bdrop 4・pl_mat 0）。loops 405・loop_max 23.3 ms |
| 4a-P3（src C × 4、fmt both） | C | 4 窓 × 50 | 全部通過・**B0・C0・D0 が A0 と u64 で bit 単位で同じ 50 / 50 組 × 3**。陽性対照（1 ダンプずらし）は 3 窓とも 0 / 49 組（違う ch 32,737〜32,755） | — | **ABCD** | 同上（bdrop 0）。loops 73・loop_max 33.3 ms |

- **床は入力の ADC について動く**（P1 の D0 = 7.99 と P2 の A0（src D）= 7.98、P1 の A0 = 6.05 と P2 の D0（src A）= 5.99）。SRC の道がコアごとに効いていることの、別の確かめ。床の高さ自体は配線 P（ノイズソースでない）なので判定しない
- **F-4 は実機でも bit 単位**: 4 コアの配置は別でも、同じ ADC・同じ RUN_F0 で 32,768 ch × 50 ダンプ × 3 窓が全部同じ（4 コアの係数・ひねり係数の ROM・FFT IP の振る舞いが同じ）
- 1 周の重さ（4a-P1、Python の道、tint 40.96 ms）: 264 周 / 200 ダンプで 1 周 ≒ 3 BASE、周の間隔 31.0 ms = 3 × t ＋ 3 → **1 BASE ≒ 9.3 ms（予言 9〜10 ms の内）**。loop_max 40.76 ms は tint のすぐ手前で、**Python の道の余裕は ≒ 9 %**。2G-4 の運転は C の道（`--fast --fast-ring --prefault`）を使う

**4c-P tint 10.24 ms（n_sum 1）の 1 BASE**（proj029 4 と同じ測り。配線に依らない）
- ボード: `specd.py --g24 --bitfile proj027.bit --clkin 0 --ref 10 --prefault --fast --fast-ring --loop-log-ms 0.1`・`SET tint=0.01024 fmt=f32`（src は既定）・`START n=200`（≒ 2 秒）・受けはボードの上（`specrecv.py --host 127.0.0.1`、`--out` なし）。
  1 BASE の段の時間は `python3 ../tools/loopsum.py <specd のログ>`
- 予言: **1 BASE の処理 ≒ 6.8 ms（6.0〜7.6 ms、10.24 ms の 66 %）**（上の 3d）。取得の取りこぼし（miss・drop・pl_drop・loop_slow）0・受けの CRC 0・照合 通過。
  外れるとしたら、記録 1 本ごとに掛かる分（put・poll・LazyRec の扱い）が 2G-2 の見積もりより大きい側

**4c-P の結果（2026-10-26 02:31 UTC、`runs/g24_4c.specd.log` はボードに置き追跡しない）: 取りこぼしは 0・1 BASE は予言より重い（外れ）**
- 受け（ボードの上、`--out` なし）: SPEC 800（4 窓 × 200）・CRC 0・欠け 0・説明のない欠け 0・照合 通過。STATUS: miss・kgap・drop・pl_drop・pl_crc・pl_err・r_bad・tp_lost・pl_mat 0・bdrop 0・pl_peak 5.0 MB
- **1 BASE の処理 7.80 ms（76 %）**（`loopsum.py --nwin 4`。**既定の --nwin 2 は 2G-2 の数え方で、BASE を倍に数えて 3.90 ms と出る**）: リングの読み 0.64・振り分け 1.45・**窓の記録 4.75**・TP 0.96 ms。
  記録 1 本あたり poll 0.090・束ね 0.054・記録 0.808・put 0.195 ms。予言 6.8 ms（6.0〜7.6）を越えた
- 外れ方: 32,768 ch の記録 1 本 0.81 ms は 2G-2 の 65,536 ch（1.17 ms）の半分にならない（1 本ごとに決まって掛かる分が大きい）。本数が倍なので、窓の記録は 2G-2 の ≒ 1.5 倍。予言は「記録の時間 ∝ ch の数」と読んでいた
- loop_slow 96 / 143 周は「1 周が tint 10.24 ms を越えた周」の数で、1 周が ≒ 1.4 BASE を抱える形（周の間隔 14.3 ms ≒ 1.4 × 7.8 ＋ 3）。リングの溜まりは最大 5 MB で追いついている。**余裕は ≒ 24 %**（2G-2 の C の道は 39 %）。30 分で確かめるのは 4c

**4d F-2（adc_to_core）**: 手順と合格の線は proj025 4d と同じ。specd を止めて、ボードで root:
`widef2.py --clkin 0 --ref 10 --adc 0,1,2,3 --out f2_27a` → **（西村さん）ADC のケーブルを A↔D・B↔C に入れ替える** → `--out f2_27b` → `--combine f2_27a.f2.json f2_27b.f2.json`。
加えて **4d-x**: 1 回目と同じ配線で `--raw-core 3 --out f2_27a3`（コア 3 の RAW で同じ 4 ADC を測る。2G-4 で初めてできる比べ）
- 予言:
  - 起動: 照合が通る（BIT_KIND 3・コア 4 個・4 コアとも RAW 1 本）。RAW の SRC の読み返しが書いた ADC
  - (a) 4 ADC × 5 試行とも縁が見える（最大 / σ ≧ 20）・1 回の中の σ ≦ 0.4 ビート・2 回の差 ≦ 1 ビート。(p) 4 ADC × 5 試行とも縁が見えない
  - **M ≒ 69 ns（64〜75 ns）**: ギアボックス・axis_sel4・RAW の RTL は proj025 と同じ（M = 69.0〜69.8 ns）。別の Overlay・配置なので ±5 ns
  - **4d-x: コア 3 の RAW の値はコア 0 の RAW と ADC ごとに ±0.1 ビート以内**（同じ Overlay の中で、RAW の道の段の数は同じ RTL。違えば raw_sel の段の数か、コアごとの T の付け方の違い）
  - **改め（2026-10-26、f2_27a の後・4d-x を測る前に書く）**: widef2 は起動のたびに Overlay を載せ直し、proj025 4d では載せ直しだけで 4 ADC がそろって ≒ 1 ビート動いた。
    同じ Overlay の中の比べにはならないので、判定を **「差（コア 3 − コア 0）の 4 ADC に共通の分は問わない（≦ 1.5 ビート）・共通の分を除いた ADC ごとの差の幅（最大 − 最小）≦ 0.2 ビート」** に改める
  - **4d-x の結果（2026-10-26）: 判定できない**。コア 3 の 1 回目（f2_27a3）は A・C・D の σ 0.44・0.46・0.43 で NG（試行の値が ≒ 0.9 ビート離れた 2 つに分かれる、proj024・025 と同じ跳ね）。
    決めたとおり Overlay を載せ直して回し直し（f2_27a3b）、通過（A 17.81・B 17.96・C 18.32・D 18.26、σ 0.38・0.06・0.06・0.03）。
    コア 0 の f2_27a（A 18.36・B 18.41・C 18.73・D 17.73）との差は −0.55・−0.45・−0.41・+0.53 で、共通の分を除いた幅 1.08 > 0.2。
    **ただし D だけが逆向きに ≒ 1 ビート動いた形で、Overlay の載せ直しごとに ADC ごとに ≒ 1 ビート跳ねる分（proj025 の載せ直しでも幅 0.6）と区別できない**。
    線は動かさず「判定できない」とし、比べ方を次の 4d-y に替える
- **4d-y: 1 つの Overlay の中でコア 0 とコア 3 の RAW を交互に**（`pynq/f2pair.py`、widef2 の open_board・open_raw・measure をそのまま使う。2026-10-26、測る前に書く）:
  ADC ごとに、コア 0 → コア 3 → コア 0 →… を 3 巡（巡ごとに先のコアを入れ替える）、1 回 5 試行の (a) だけ。1 回の値は 5 試行の**中央値**（跳ねで 2 つの山に分かれても多数派を取る）
  - 予言: **ADC ごとに、同じ巡の (コア 3 − コア 0) の差の中央値が |差| ≦ 0.1 ビート**（同じ Overlay・同じギアボックス・RAW の道の段の数は同じ RTL）。巡の間で値が 1 ビート跳ねることはあってよい（両方のコアが同じように跳ねるなら差は 0）
  - 外れたら: 差が 4 ADC そろって同じなら raw_sel_3 か RAW の T の付け方がコアで違う（RTL の問い）。ADC ごとにばらばらなら、跳ねがコアごとに独立（PPS のスタンプでなく、RAW の取り込みの側の跳ね）
  - 自信が低い所: σ が 0.4 を越える（proj024・025 で 1 回ずつ）。**越えたら Overlay を載せ直して回し直し、そのことを書く**（測る前に決めておく）
- **1 回目 f2_27a（コア 0 の RAW、2026-10-26）: 通過**。A +18.36（σ 0.03）・B +18.41（0.03）・C +18.73（0.03）・D +17.73（0.05）ビート、(a) 4 ADC × 5/5 で縁（最大 / σ 170〜186）、(p) 全部見えない（3.4〜4.7）
- **4d-y の結果（`runs/f2_27pair.log`・`f2_27pair.pair.json` はボード）: 全部通過・予言どおり**。巡ごとの差（コア 3 − コア 0）の中央値は A +0.00・B −0.06・C +0.00・D +0.00 ビート（線 0.1）。
  **1 つの Overlay の中では、コア 0 とコア 3 の RAW の T は同じ**（raw_sel・RAW の T の付け方はコアで同じ）。この Overlay の値は 4 ADC とも 17.56〜17.75 ビートで、f2_27a（17.73〜18.73）とは ADC ごとに 0〜1.1 ビート違う
  → **Overlay の載せ直しごとの跳ねは ADC ごとに独立に ≒ 1 ビート**（proj025 は 4 ADC そろって −1.0〜−1.6 と読んだが、幅 0.6 あった）。F-2 の M は 1 つの Overlay の値なので、確かさは ±0.5 ビート（±2 ns）と読む（proj025 と同じ）
- 結果は (b) の形で: CAL[0x0027_0100] の pps_det_ns 71.5（LPF の分）のまま、adc_to_core_ns = M ＋ 71.5 を入れ、「未較正」を外す
- **4d の結果（2026-10-26、2 回目 f2_27b は A↔D・B↔C）: 通過・予言どおり**

| | 1 回目 f2_27a | 2 回目 f2_27b | M | 2 回の差 |
|---|---|---|---|---|
| A | +18.36（σ 0.03） | +18.48（σ 0.03） | 18.42 ビート = **71.9 ns** | 0.11 |
| B | +18.41（σ 0.03） | +18.44（σ 0.06） | 18.43 = **72.0 ns** | 0.02 |
| C | +18.73（σ 0.03） | +18.06（σ 0.34） | 18.39 = **71.9 ns** | 0.66 |
| D | +17.73（σ 0.05） | +18.09（σ 0.36） | 17.91 = **69.9 ns** | 0.36 |

  - (a) 2 回とも 4 ADC × 5/5 で縁、(p) は全部見えない。**M = 69.9〜72.0 ns は予言の ≒ 69 ns（64〜75 ns）の内**（proj025 の 69.0〜69.8 ns より 0〜3 ns 大きい。Overlay ごとの ±2 ns の内）
  - 2 回目の C・D は 5 試行のうち 1 回が 1 ビート跳ねた（18.25 の中に 17.38）。道具は算術平均なので M はそれに引かれる。多数派の山で取ると C +0.10・D +0.09 ビート（≦ 0.4 ns）で、Overlay ごとの ±2 ns より小さいので、proj024・025 と同じ数え方の値を使う
  - `timebase.py` の CAL[0x0027_0100] を (b) の形で埋めた: **pps_det_ns 71.5・adc_to_core_ns = M ＋ 71.5 = {A 143.4・B 143.5・C 143.4・D 141.4}**（「未較正」を外した）

**配線 N/S・ノイズソース ON（2026-10-26 02:5x、西村さん）のレベル**: 短い運転 2 回（src A〜D・n 25）で TP −31.29〜−31.52 dBFS・sat 0（proj025 4a・4c の −31.17〜−31.32 と同じ程度）。
**CW は見えない**（どのコアも最大が床の +3 dB、場所は 2666〜2671 MHz を漂う = 雑音の帯域の形）→ SG の出力は入っていない見込み。
床の中央値（1 フレームあたり）A0 6.33e3・B0 6.13e3・C0 6.15e3・D0 6.33e3。
- **床は予言として数えない**: 式（2G-2 の 3.6e3 × 2 = **7.2e3 × 10^((TP + 30.9) / 10)**。雑音の |Y|² は N が半分で 1/2、Y の丸め 1 bit が無いので × 4、1d の注）は測る前に出したが、
  書く前にこの値を見た。式の値 6.4e3（TP −31.4）に対して −0.05〜−0.2 dB で合う。配線 P の ADC の床（4a-P1）も 2G-2 4b の床の 1.6〜1.8 倍で、同じ向き

**4c tint 10.24 ms（n_sum 1）で 30 分 — 予言（2026-10-26、走らせる前に書く）**
- 構成: 配線 N/S・ノイズソース ON（上のレベル）、src A・B・C・D・SHIFT 7・fmt f32・C の道（`--prefault --fast --fast-ring`）・`START n=0`・**30 分**。
  受けはボードの上（51 MB/s は NIC を越える、proj029）で、**受けを先に起こす**（`--seconds` を運転より長く。proj029 4 で受けが 29 秒遅れて溜まりで 6947 件を捨てた改め）。`--out` なし。STATUS を 1 分ごと
- 予言（取りこぼし）: 30 分を通して **miss・kgap・drop・pl_drop・pl_crc・pl_err・r_bad・tp_lost・tp_rec_lost 0**、受けの欠け・CRC 0・照合 通過。SPEC は 4 窓 × ≒ 175,781（30 分 / 10.24 ms）
- 予言（1 周）: 4c-P の 1 BASE 7.80 ms（76 %）のまま。リングの溜まりの最大（pl_peak）は 64 MiB に届かない（≦ 16 MB）。loop_slow は数えるが判定しない（1 周が 1 BASE を越えて抱える形で、取りこぼしではない）
- 自信が低い所: 76 % で 30 分。受けの送り出し（別のプロセス、ボードの CPU）と重なる周・TP の吐き出しの周が重なると、遅れが溜まり始めるかもしれない（proj029 の 30 分は 61 % で、遅い周 44 回）。
  溜まり始めたら pl_peak が分ごとに増える形で見える

**4c の結果（2026-10-26 03:32:44 UTC 開始）: 判定できない — 11 分の時点でボードが電源投入のリセットで落ちた**
- 落ちるまでは予言どおり: 11 分（03:43:47 の STATUS）で dumps 64,728・miss・kgap・drop・pl_drop・pl_crc・pl_err・r_bad・tp_lost・tp_rec_lost とも 0・pl_peak 4.2 MB（5 分・10 分と同じ）・
  loop_p99 13.2 ms・loop_max 22.19 ms・TP −31.31〜−31.52 dBFS・sat 0。受け（660 s）は SPEC 256,413・欠け・CRC・説明のない欠け 0。**30 分を通してではないので、予言の判定はしない**
- 落ち方: STATUS の最後の書き 03:43:47 → 次の起動 03:44:11（`uptime -s`）。前の起動の journal は 03:43:07 の ssh の出入りで終わり、**warning 以上は 03:30 以降 0 件・kernel の panic・oops の行なし**。
  **CRL_APB の RESET_REASON（0xFF5E0220）= 0x1 = 外からの POR**（電源の入り直し。ソフトの再起動・watchdog・PMU のリセットではない）。ボードは DHCP で別の番地を取り直した（見張りは「No route to host」でこれを見た）
- 起動の後に読んだ PL の温度（AMS、別の会話の specd が動いている状態）は 66〜70 ℃。落ちた時の温度は残っていない
- 読み方（未検証）: 外からの POR は、電源（AC アダプタ・電源の監視の IC）か、ボードの電源の保護（過電流・過熱）の側。**4 コア × 4 ADC ＋ C の道で 11 分の負荷**と重なったが、1 回の観測から負荷が原因とは言えない。
  切り分け: 同じ運転を温度（AMS の in_temp*）と負荷を 10 秒ごとに残しながら回し直す（落ちる直前の値が残るように、ログは都度 fsync）。比べに、同じ時間の 2G-2（proj029 の 30 分は落ちていない）か、PL を載せただけの待機を並べる
- 見張りの穴（この会話）: 1 分ごとの STATUS の見張りが ssh の失敗を読み飛ばす作りで、落ちたことを知らせなかった。次からは ssh が続けて 2 回失敗したら知らせる

**4c のやり直し（4c-b）— 予言（2026-10-26 08:1x UTC、走らせる前に書く）**
- 構成は 4c と同じ（配線 N/S・ノイズ ON・src A〜D・SHIFT 7・fmt f32・C の道・`START n=0`・30 分・受けはボードの上で先に起こす）。足すのは `tools/amslog.py`（AMS の温度 3 つ・電圧 28 本と load を **10 秒ごと、行ごとに fsync**）。
  運転の前に 2 分、待機の値を取る。ボードは起動から 4.5 時間・別の会話の specd を止めた直後で、待機の温度は temp20 68.6・temp7 64.5・temp8 67.7 ℃（08:16）
- **中止の条件（決めておく）**: 温度のどれかが **95 ℃** を越えたら STOP（XCZU48DR の拡張温度の上限 100 ℃ の手前）。1 分ごとの見張りで、ssh が続けて 2 回失敗したら知らせる
- 予言（取りこぼし）: 4c と同じ（30 分を通して 0・pl_peak ≦ 16 MB）
- 予言（温度）: 運転を始めると上がり、10 分ほどで平らになる。平らの値は待機 ＋ 5〜15 ℃（**自信は低い**。負荷の前後の温度をこのボードで測ったことがない）
- 落ちるかどうかは予言しない（1 回の観測から率は言えない）。読み方を先に決める:
  (i) 落ちる直前まで温度が上がり続けている、または 4c と同じ程度の時刻で落ちる → 過熱・負荷の側を疑い、比べ（PL を載せただけの待機を同じ時間）を足す。
  (ii) 温度が平らのまま落ちる → 電源の側（アダプタ・保護）を疑う。電圧の行の直前の値を見る。
  (iii) 30 分を通る → 4c の判定はこの回で行い、4c の落ちは「1 回きり・原因未検証」として残す（直ったとは読まない）

**4c-b の結果: 取得を始める前に、ボードがまた外からの POR で落ちた（2 回目）**
- 08:17:35 specd 起動（ID の照合は通過、proj027.bit を載せた）→ 08:18:27 run4c30b.sh → **08:19:05 の AMS の行が最後・08:19:27 に起き直した**。RESET_REASON 0x1・前の起動の journal に kernel の行なし（1 回目と同じ形）。
  run4c30b.sh は `cd ~/proj027` が root では /root に向いて外れ、受け・SET・START は走っていない（amslog だけが呼び出し元の場所で走った）→ **落ちたのは specd が待機している（取得していない）間**
- 落ちる前 40 秒の AMS: 温度 temp20 70.2〜71.5・temp7 66.3〜66.7・temp8 67.6〜69.5 ℃ で平ら、0.85 V の系（≒ 850〜870 mV の行）も平ら → 読み方 (ii)（温度は平ら）。10 秒ごとの AMS では瞬間の落ち込みは見えない
- **この日の 3 つの bit の並び**（journal の sudo の行から）: proj027（02:24〜03:43、うち 02:52 からノイズ ON）→ 03:43 落ち → 別の会話の SAM45-Wide v1.0.0（≒ 4 時間、落ちていない）→ proj027（08:17 起動）→ 08:19 落ち。
  **proj027 を載せていた ≒ 1.4 時間に 2 回、Wide の ≒ 4 時間に 0 回**（回数が少なく、率の比べにはまだならない）
- Vivado の見積もり（routed の report_power、ベクタなし）: **proj027 VCCINT 43.5 A・全体 41.0 W**、Wide（proj023）38.0 A・36.2 W、2G-2（proj025）24.8 A・24.8 W。proj027 がこれまでで一番重い
- ボードに **INA220 が 9 個**（hwmon0〜8、i2c 0x40〜0x48）。0x40 は ≒ 0.876 V・シャント 1 mΩ で VCCINT と見る（起き直した後、bit を載せる前で 5.86 A）。**PL の電流を直に測れる**
- 見立て（未検証）: PL の電流（VCCINT か 12 V の入口）がボードの電源の保護の閾値に近く、ノイズの入力でトグルが増えると越える。待機でも PL の FFT は ADC の入力を処理し続けているので、取得の有無に依らない形と合う
- 電源は AC アダプタ 12 V・9 A（108 W、西村さん）。見積もり 41 W に対して入口は余裕がある → 疑うのはボードの上の VCCINT の電源の側

**4e 電流の測り — 予言（2026-10-26 08:27 UTC）**
- **書いた時刻の注**: README への書き込みが外れたまま 08:25 に記録を始め、08:26:31 に proj027 を載せた。予言はその後に書いた。
  書く前に見たのは温度（temp20 43 → 63 ℃ を 30 秒で上がり続け）と 0x41〜0x45 の系だけで、**VCCINT（0x40）の列は読んでいない**
- 構成: 配線 N/S・**ノイズソース OFF**（西村さんが切った）→ 数分の後に ON。`tools/amslog.py` に INA220 9 個の curr1_input を足し、**1 秒ごと**に残す（`runs/g24_4e.ams.log`）。
  bit を載せる前に 60 秒 → specd（proj027.bit、取得はしない）→ ノイズ OFF で数分 → ノイズ ON。bit なしの VCCINT（0x40）は 5.8 A
- 予言（自信は低い。このボードで PL の電流を測ったのは初めて）: proj027 を載せた VCCINT は **30〜45 A**（見積もり 43.5 A はベクタなしのトグル率）。
  **ノイズ ON で OFF より 2 A 以上増える**（入力の振れが大きくなり、FFT の前段のトグルが増える）。増えなければ、入力のトグルで閾値を越えるという見立ては外れ
- 落ちたら: 落ちる直前の 1 秒ごとの VCCINT の値を読む。ノイズ OFF のうちに落ちれば、ノイズは必要条件ではない

**4e の結果: ノイズ OFF のまま、載せて 2 分 15 秒で 3 回目の外からの POR。VCCINT は 43.0 A で平らだった**
- VCCINT（0x40）: bit なし 5.8 A → **08:26:31 に proj027 を載せて 41.5 A**（温度 43 ℃）→ 温度とともに漏れ電流で上がり、08:27:54 に 42.9 A（71 ℃）→ **最後の 25 秒は 42.97〜43.09 A・PL 70〜73 ℃ で平ら** → 08:28:45 の行が最後・08:28:59 に起き直した（RESET_REASON 0x1）。
  他の 8 個（0x41〜0x48）も最後まで平ら。**1 秒ごとの値に、落ちる前触れ（電流の跳ね・温度の上がり続け）は無い**
- 予言の判定: VCCINT 30〜45 A は**当たり**（41.5〜43.1 A。見積もり 43.5 A とほぼ同じ）。ノイズ ON で増えるかは**測れなかった**（OFF のうちに落ちた）。**ノイズは落ちる必要条件ではない**（見立ての「入力のトグルで越える」は外れ）
- 落ちるまでの時間: 1 回目 ≒ 80 分（02:24 に載せた。その前は Wide などで負荷は軽い）、2 回目 1.5 分（Wide 38 A を 4 時間の後）、3 回目 2.3 分（2 回目の 7 分後）。
  **前に重い負荷が続いた後ほど早く落ちる**形 → 見立て（未検証）: VCCINT のレギュレータの側の熱か過電流の保護の閾値に、43 A が届いている（PL の温度でも VCCINT の値でもない所で決まる）
- **proj027 はこのボードでは今のままで連続運転できない**。これ以上 proj027 を載せない（落ちるたびに電源が入り直す）。
  2G-4 を使うには PL の電流を減らす（proj030 の DSP の節約: レーン FFT の 2-for-1 で DSP −216・LUT ≒ −22,000 / コア）か、レギュレータを冷やす（風）か。Wide の 38 A は 4 時間通っているので、目安は **38 A 以下**

**4f ファンの配置を変えて流量を増やした後（西村さん）— 予言（2026-10-26、bit を載せる前に書く）**
- 構成: 配線 N/S・ノイズソース OFF（4e のまま）。`amslog.py` 1 秒ごと（`runs/g24_4f.ams.log`）を先に起こして 60 秒 → specd（proj027.bit）で待機 5 分 →
  4c と同じ 30 分の取得（`run4c30b.sh` を R=runs/g24_4f で。src A〜D・C の道・受けはボードの上）。ボードは 3 回目の落ち（08:28）から bit なしで休ませた
- 予言（落ち）: 見立て（レギュレータの熱）が正しく、風がレギュレータに届いていれば、**4e の 2.3 分を越え、35 分を通る**。
  自信は低い（風が当たる所・レギュレータの場所を確かめていない）。2〜3 分で落ちれば、風は効いていない か 見立てが外れ（過電流の閾値そのもの）
- 予言（電流・温度）: VCCINT は温度で決まるので、PL の温度が 4e（70〜73 ℃）より下がれば VCCINT も 43.0 A より少し下がる（漏れの分、≒ 0.3 A / 10 ℃）
- 予言（取りこぼし）: 4c と同じ（30 分を通して 0・pl_peak ≦ 16 MB）。ノイズ OFF なので TP は 4c より低い（判定しない）
- 中止の条件: 4c-b と同じ（温度 95 ℃）

**4f の結果（08:37:50 に載せ、取得 08:42:50〜09:13:09）: 落ちずに通った。取りこぼしは 30 分を通して 0**
- 落ち: **載せてから 35 分（取得 30 分 ＋ 待機 5 分）落ちず**、起動時刻は 08:28:59 のまま → 予言の「35 分を通る」は**当たり**。
  ただし 1 回目の落ちは載せてから ≒ 80 分だったので、**35 分を通ったことは「直った」の証拠にならない**（風が効いた、と読むには 80 分より長い運転と、同じ長さの風なしの比べが要る）
- 電流・温度: PL 67〜71 ℃（4e の 70〜73 ℃ より ≒ 3 ℃ 低い）・**VCCINT 42.65〜43.35 A**（4e の最後 42.97〜43.09 A と同じ）→ 「VCCINT も少し下がる」は**外れ**（下がらなかった。3 ℃ の違いでは 1 秒ごとの揺れ ±0.2 A に埋もれる）。
  **落ちた 4e と通った 4f で VCCINT は同じ** → VCCINT の電流の値だけで閾値を越える、という形ではない。風で変わる何か（レギュレータの温度など、測っていない所）と合う
- 取りこぼし（予言どおり、当たり）: STOP の後 dumps 176,695（4 窓とも）・miss・kgap・drop・forced・skip・pl_drop・pl_crc・pl_err・bdrop・r_bad・tp_lost・tp_rec_lost・sat とも 0・**pl_peak 5.25 MB**（≦ 16 MB）・loop_p99 13.1 ms・loop_max 22.56 ms・loop_slow 33,285。
  受け: SPEC 706,780・CRC・欠け・説明のない欠け 0・**照合 通過**（88.6 GB）。TP −58.7〜−61.5 dBFS（ノイズ OFF）
- 4c（30 分）の判定は**この回で通過**とする（構成のうちノイズだけ OFF。取りこぼしの判定はノイズの有無に依らない）。1 回目（03:32）の落ちは原因未検証のまま残す

**4g 2 時間の取得（4f に続けて、bit は載せたまま）— 予言（2026-10-26 09:2x UTC、走らせる前に書く）**
- 構成: 4f と同じ（ノイズ OFF・src A〜D・C の道・受けはボードの上）で取得 **120 分**（`MIN=120 R=runs/g24_4g`）。`amslog.py` 1 秒ごと。bit は 08:37:50 から載せたままで、取得の終わりは載せてから ≒ 2 時間 50 分
- 予言（落ち）: 風が効いているなら**落ちない**（1 回目の 80 分を越える）。自信は中（4f の 35 分の 1 回だけ）。落ちたら、落ちるまでの載せてからの時間と、直前の VCCINT・PL の温度を 4e・1 回目と並べる
- 予言（取りこぼし）: 120 分を通して 0、SPEC 4 窓 × ≒ 703,000（120 分 / 10.24 ms）、pl_peak ≦ 16 MB
- 予言（電流・温度）: 4f と同じ（VCCINT 42.6〜43.4 A・PL 66〜72 ℃）。外れて上がり続けるなら、ボードの熱が溜まり続けている
- 中止の条件: 4c-b と同じ（温度 95 ℃）
- 実際の開始: 西村さんの返事を待つ間に 2 時間が過ぎ、取得の開始は **11:17:02**（予言はその前に書いた）。**4f の STOP（09:13）から 11:17 まで、bit を載せたまま specd の待機で 2 時間落ちていない**（起動時刻 08:28:59 のまま。この間の amslog は 09:22 で切れていて、電流・温度の記録はない）。取得の終わりは載せてから ≒ 4 時間 40 分

**4g の結果（取得 11:17:02〜13:17、受けの終わり 13:19:29）: 落ちず、取りこぼしは 120 分を通して 0 — 予言はすべて当たり**
- 落ち: 起動時刻は 08:28:59 のまま。**proj027 を載せてから 4 時間 41 分（08:37:50〜13:19）落ちていない**（1 回目の 80 分・4e の 2.3 分を大きく越える）
- 取りこぼし: STOP の後 dumps 706,813（4 窓とも、予言 ≒ 703,000）・miss・kgap・drop・forced・skip・pl_drop・pl_crc・pl_err・bdrop・r_bad・tp_lost・tp_rec_lost・sat とも 0・**pl_peak 5.25 MB**・loop_p99 13.1 ms・loop_max 21.64 ms。
  受け: SPEC 2,827,252・CRC・欠け・説明のない欠け 0・**照合 通過**（354.6 GB）
- 電流・温度（1 秒ごと 7,229 行）: **VCCINT 42.52〜43.34 A・PL 65.0〜70.2 ℃**、2 時間を通して平ら（熱は溜まり続けていない）
- 読み方: ファンの配置を変える前は 3 回落ち（80 分・1.5 分・2.3 分）、変えた後は 4 時間 41 分で 0 回。VCCINT は前後で同じ。**風が効いた、という読みと合う**が、風なしの同じ長さの比べはしていない（ボードを落とす試験になるので、しない）。
  **2G-4 の運用の条件として「今のファンの配置」を残す**。PL の電流を減らす（proj030）ことは余裕のために引き続き価値がある

**4b ch → IF（SG の CW）— 予言（2026-10-26、走らせる前に書く）**
- 構成: 配線 N/S（proj025 4b と同じ: SG → 2 分配器 A → PATT 0 dB → 2 分配器 B → ATT 3 dB → 4 分配器 → ADC）・**ノイズソース OFF**・SG E8257D（基準 EXT = ボードと同じ 10 MHz）**+9 dBm**。
  SG はこの PC から `sg.py`（宛先は RFSOC_SG、リポジトリに書かない）。specd は 4g から続けて C の道で待機（bit は載せたまま）。
  `SET A0.src=A B0.src=B C0.src=C D0.src=D shift=7 tint=0.04096 fmt=f32`・`START n=50` → 受けはこの PC（`--out runs/g24_4b{1,2}.s45`）→ `g24cw.py --src ABCD --sg-mhz F`、陽性対照 `--posctl`。終わったら SG の出力を OFF に戻す
- 2 点: **3000.25 MHz**（ch c = (4096 − 3000.25) / 0.0625 = **17532** → 送る i = 32767 − c = **15235**）・**2500.5 MHz**（c **25528** → i **7239**）。どちらも ch の中心（62.5 kHz の整数倍）
- 予言: 2 点 × 4 窓とも CW が見えている・**ピークの番号が期待と一致・軸と SG の差 0 Hz**。
  **ピーク / 中央値 ≒ 79 dB**（2G-2 の 82 dB − 3 dB: N が半分で CW の電力 N² は 1/4、雑音 N は 1/2）。隣の ch −52 dB 前後・±2 ch −59〜−61・±3 ch −65〜−66 dB（PFB は同じ T 4）。
  TP は 4 本とも ≒ −26 dBFS（proj025 4b と同じ配線・レベル）・sat 0。陽性対照 `--posctl` は軸の向きで落ちる

**4b の結果（2026-10-26 13:23〜13:24 UTC）: ch → IF は 2 点 × 4 窓とも通過・陽性対照は落ちた。レベル（TP・ピーク / 中央値）は ≒ 13 dB 低く、予言は外れ**

| | 送る番号（期待） | 軸と SG の差 | ピーク / 中央値（A0 / B0 / C0 / D0） | 隣の ch・±2・±3 ch | TP（A〜D） |
|---|---|---|---|---|---|
| 3000.25 MHz | 15235（15235） | 0.0 Hz | 66.9 / 66.5 / 67.4 / 66.7 dB | −52.5〜−53.8・−59.9〜−61.6・−63.7〜−65.3 dB | −39.16・−39.01・−38.47・−38.76 dBFS |
| 2500.5 MHz | 7239（7239） | 0.0 Hz | 66.6 / 66.1 / 66.4 / 65.8 dB | −53.1〜−54.2・−60.9〜−61.9・−64.2〜−65.4 dB | −39.43・−39.39・−39.43・−39.55 dBFS |

- 各 4 窓 × 50・CRC 0・sat 0・miss 0・受けの照合 通過・4 窓の DUMP_T が揃う。陽性対照 `--posctl` は軸 1351.75 / 1851.5 MHz で 4 窓とも落ちた。
  床（ノイズ OFF、1 フレームあたりの中央値）A0 6.75〜6.77・B0 7.64〜7.67・C0 7.00〜7.11・D0 7.69〜7.88
- **当たり**: ピークの番号・軸の差 0 Hz（2 点 × 4 窓）、隣の ch −53 dB 前後・±2 ch −60〜−62・±3 ch −64〜−65 dB（PFB は同じ T 4。2G-2 と同じ形）
- **外れ**: TP −38.5〜−39.6 dBFS（予言 ≒ −26）、ピーク / 中央値 65.8〜67.4 dB（予言 ≒ 79）。**どちらも ≒ 12〜13 dB 低い**。
  ピーク / 中央値は CW の電力に比例するので、TP の差（≒ 13 dB）でそのまま説明がつく（79 − 13 ≒ 66）。**入口のレベルが proj025 4b（2026-10-23）と違う**と読む。
  何が違うか（PATT の値・ノイズソースを足した後の合成器など）は確かめていない（予言の「同じ配線・レベル」が前提の誤り）。比べの条件は dBFS で書く規約どおり、レベルの判定は配線を確かめてから
  （西村さんにも心当たりはない、2026-10-26。次に配線 N/S を使う前に、SG から ADC までの各段のレベルを測り直す）
- 終わった後: specd を SHUTDOWN し、ボードを再起動して PL を空にした（13:26:55 起動、VCCINT 2.4 A。proj027 を載せたままだと待機でも ≒ 43 A 流れる）
- 走らせ方の誤り（判定に使っていない）: 1 回目（`runs/g24_4b1_sgoff.s45`）は SG を設定した直後に `SG.close()` を呼び、**close が開いた時の状態（OFF）に出力を戻す作り**で、取得の間 SG が切れていた（TP −58〜−62 dBFS・ピークは端の ch 32767）。SG を開いたまま取得する形に直して取り直した。終わった後の SG は出力 OFF


## 決めること（段階 A の終わりまでに並べる）

- ~~PFB を残すか~~ → **残す**（2026-10-23、西村さん。PFB を外しても LUT は 1 % ほどしか減らず、目安 65 % は切れない（proj024 S-1: なし 64〜67 %・あり 65〜68 %）。LUT の余裕はコアの残り（Wide の束ね・切り出しの分が 2G-4 では要らない）で詰める）
4 コアの論点 F-1〜F-6（2026-10-23、西村さん）:

| | 論点 | 決め |
|---|---|---|
| F-1 | コアの組み方 | **Wide の形の s45_core × 4**。Wide の束ね・切り出しは 2G-4 では要らないので外す（その LUT が余裕の詰めどころ） |
| F-2 | PFB の係数 ROM をコアごとか 4 コアで共有か | **コアごと**（OOC で測ってから決めた。補間の掛け算は LUT ではなく DSP に入り、1 個 LUT 16・DSP 64・RAMB36 2。コアごとの代価は DSP 192（4.5 %）で、律速の LUT には効かない。共有は出口 1152 bit を 4 コアへ配るのでタイミングが心配（Wide は 25 ps）。下の F-2 の測り） |
| F-3 | ひねり係数 ROM | **コアごと**（proj025 E-2 と同じ。Wide は共有で `-1` の余裕が 25 ps） |
| F-4 | SRC | **コアごとに 4 本の ADC から選ぶ**（2 コア以上に同じ ADC を入れて bit 単位の同等を陽性対照にできる。proj025 E-4 の 4 コア版） |
| F-5 | RAW・TP | **RAW も TP もコアごと**（勧めは「RAW はコア 0 だけ」だったが、コアごとに決めた。LUT・BRAM の増分は F-2 と一緒に数える） |
| F-6 | 段階 B の写し元 | **proj025 の実機の後のタグ**（`proj025-m0` の案）。2G-2 の実機で直るところを引き継ぐ |

- Vivado: proj025・proj026・Wide の M5 と**並行して使ってよい。JOBS は最大 8**（2026-10-23、西村さん）

### F-2 の測り（`make coef-ooc`、`tools/coef_ooc.tcl`）— 予言（走らせる前に書く、2026-10-23）

g24_coef を 1 個だけ OOC で合成する（part `-1`・3.906 ns・合成だけ）。物差しは proj025 の g22_coef（f706170 から `git show`）、陽性対照は在らない HEX（ROM が空で畳まれる）。

走らせる前に分かったこと: **proj025 の実ビルドの u_pfb（g22_coef 込み、コア 1 個）は LUT 494・DSP 144・RAMB36 153**（`proj025/build/pfb_util.rpt`）。PFB 本体の掛け算は 64 個（g22_pfb_core の `ca * xa`）なので、**残りの DSP 約 80 は補間の S·f（64 個）に回っているとしか読めない**。「補間の掛け算は LUT で組まれる」（RTL の注「13 × 6 bit、LUT」）は前提として怪しい。

| | LUT | DSP | RAMB36 |
|---|---|---|---|
| ruler_g22 | ≦ 494（u_pfb 全体の上限） | 64〜80 | 4（2048 × 36 の 2 ポート ROM × 2） |
| g24 | 300 以下（ruler とほぼ同じ） | 64〜80（ruler と同じ数） | 2（1024 × 35 × 2） |
| pc_nohex | ほぼ 0 | 0 | **0**（0 でなければ照合が効いていない） |

予言が当たったときの F-2 の読み: コアごとに置く代価は **LUT ではなく DSP**（3 コア分で約 190〜240、デバイスの 4.5〜5.6 %）と RAMB36 6。LUT は 4 倍でも 0.3 % 以下で、目安 65 % には効かない。

**結果（2026-10-23、`build-ooc/ooc.txt`、合成 3 本で 70 s）: 全部通過**

| | LUT | SRL | FF | CARRY8 | DSP48E2 | RAMB36 |
|---|---|---|---|---|---|---|
| ruler_g22 | 17 | 12 | 123 | 12 | 64 | 4 |
| g24 | **16** | 11 | 182 | 12 | **64** | **2** |
| pc_nohex | 2 | 11 | 32 | 0 | 64 | 0 |

- 当たり: RAMB36 4・2・0、DSP 64（S·f が 1 個ずつ DSP）。$readmemh は g22・g24 とも「read successfully」、陽性対照だけ CRITICAL WARNING Synth 8-4445（開けない）
- **外れ: LUT は予言の 300 以下どころか 16**。V·64 ＋ 丸めと和（段 3・4）も DSP の中の加算器に入る。RTL の注の「LUT」は誤りだった（g22 から引き継いだ注。直すのは段階 B で写すとき）
- 外れ（数え方）: 1 回目は tcl が `REF_NAME =~ DSP*` で数えていて、DSP48E2 の中の部品セル 9 個ずつを拾い 576 と出た。report_utilization の表（64）と食い違って気づいた。`REF_NAME == DSP48E2` に直して 2 回目
- 陽性対照の DSP 64 は残る（ROM が空でも、合成の段では 0 を掛ける DSP を畳まない）。この対照は ROM の照合のためで、DSP の数の対照にはならない
- proj025 の u_pfb の DSP 144 のうち、係数 64・PFB 本体の掛け算 64 で、残り 16 は PFB 本体の側（係数の側ではない）

**F-2 の材料**: コアごとに置く代価は **DSP 64 ＋ RAMB36 2 ／ コア**（4 コアで共有にすると DSP 192・RAMB36 6 が浮く）。**LUT は 1 コアあたり 20 足らずで、LUT の律速（目安 65 %）には効かない**。
2G-4 の DSP の概算: proj025 のコア 924（係数込み）からレーン FFT の差（33 → 27）× 16 を引いて 828 / コア、4 コアで **約 3,300（77 %）・共有で約 3,120（73 %）**。共有の代価はタイミング（Wide は共有で `-1` の余裕が 25 ps、出口 1152 bit を 4 コアへ配る）。
- リングの大きさ（INTERFACE 11.。2G-4 は 256 KiB × 4 / 10.24 ms）— 段階 B で

## 結論・次にやること

- [x] 0. 写す（2026-10-23）
- [x] PFB を残す（2026-10-23、西村さん。2G-1・2G-2 と同じ T 4）
- [x] M. 模型・表（2026-10-23、全部通過。係数の補間は G 4・35 bit・RAMB36 2）
- [x] 1a〜1d. 部品の単体の sim（2026-10-23、全部通過・陽性対照 6 本は落ちた。外れ 2 つは予言の数え方）
- [x] 4 コアの論点 F-1〜F-6（2026-10-23、西村さん。F-5 は勧めと違い RAW も TP もコアごと）
- [x] F-2 の測り: g24_coef の OOC（2026-10-23、LUT 16・DSP 64・RAMB36 2）→ 係数 ROM はコアごと
- [x] W. Wide の束ね・切り出しの LUT（2026-10-23、proj023 ビルド 11 のチェックポイントを読むだけで。差し引き 730 / コア・0.7 %。レーン FFT は配置後が OOC より 6 % 小さく、2G-4 は約 64.0 % の見込み）
- [x] 段階 B の B0: proj025-m0 から写した（2026-10-23。写した後も 1a〜1d は全部通過）
- [x] 段階 B の 2a〜2e・2e-2（4 コア）・4d-2 の sim（2026-10-23、全部通過・陽性対照は全部落ちた。D_eff 6,145 ビート）
- [x] g24_coef の注の「LUT」を DSP に直した（2026-10-23、注だけ）
- [x] 2f の build.tcl を 4 コアに・ビルド（2026-10-23。**build-PE/（Performance_Explore）が閉じた: WNS +0.032 ns・LUT 64.6 %・BRAM 842・URAM 48・DSP 3,312**。既定は配線まで +0.008 で閉じたが write_bitstream の前に Vivado が落ち、回し直しが配線済みを消した）
- [x] build.tcl の回し直しを、落ちた段から後だけを reset する形に（2026-10-26。小さな設計で write_bitstream の落ちを作って確かめた。本番のビルドではまだ）
- [x] 3. PS（2026-10-26。**土台は proj029 の 5164a02**（C の道を含む）。2G-2 の道を形の表に広げ、G24Backend・FakeG24Backend は形だけを替えた子。test_fake 27 試験が今の道・C の道とも全部通過、予言は全部当たり。実機の道は 4 で初めて走る）
- [x] 4. 実機（4a 立ち上げ・4b ch → IF・4c 30 分・4d F-2・D_eff、4 コアに同じ ADC の陽性対照）。予言は走らせる前に書く（4b のレベルの外れは配線の確かめが残り。運用の条件: ファンの配置）
