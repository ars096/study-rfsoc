# 版とハードウェアの固定値

**このファイルには公開してよい情報だけを書く。** ライセンスの Host ID、AMD アカウント、
`.lic` の内容は書かない — git の履歴は消せないため「公開時に消す」は成立しない。
それらはリポジトリ外の作業記録で管理する。

## ツール

| | 値 | 備考 |
|---|---|---|
| Vivado | 2023.2 と 2024.1 を併設 | proj001 は 2023.2、**proj002 以降は 2024.1**（BSP と PYNQ v3.1 が前提とする版）。2026-09-16 に 2024.1 で `get_parts` / `get_board_parts` が通ることを確認 |
| PYNQ image | v3.1.1 (Carlisle) | 2026-09-16 にカードを新規作成し、ボード上で `pynq.__version__` = 3.1.1 を確認。Vivado 2024.1 と整合。**旧 v3.0.1 カードは温存してある** |
| Board files | RealDigitalOrg/RFSoC4x2-BSP `board_files/rfsoc4x2/1.0` | commit **`40e6814a3b62eead76e41a29fdabc43030f89b6c`**（2025-09-24）。proj002 のビルドが実際に使って成功した版。**Vivado のインストールツリーの外に clone し、`board.repoPaths` で指す** |
| Part | `xczu48dr-ffvg1517-2-e` | 根拠: BSP board_files の宣言値 |

### PYNQ イメージの版

2026-09-15 の時点でボードの SD カードは **v3.0.1** だった（それまで VERSIONS.md は
v3.1.1 と記載していたが、これは未確認の想定だった）。翌 2026-09-16 に新しいカードへ
v3.1.1 を焼き、ボード上で `pynq.__version__` = 3.1.1 を確認して解消した。

| | Vivado |
|---|---|
| PYNQ v3.0.1 | 2022.2 で検証済み（PYNQ 開発元の推奨） |
| RFSoC-PYNQ v3.1.1 (Carlisle) | 2024.1。RFSoC 4x2 向けの最新イメージ |

BSP の board files が 2024.1 前提である以上、**イメージ側を v3.1.1 に上げて揃える**のが唯一の解。
逆方向（Vivado を 2022.2 に下げる）は board files とズレるため成立しない。
**既存の v3.0.1 カードは上書きせず温存する**（proj001 の環境を再現できる唯一の実体のため）。

暫定の逃げ道として `Overlay(..., ignore_version=True)` があるが、
版の合わない IP が動かない可能性があるとされており、恒久策にはしない。
特に RF Data Converter は `xrfdc` / `xrfclk` ドライバと IP の版が結合する。

### Part の未確認事項

リファレンスマニュアル Rev A5 の本文には `XCZU48DR-1FFVG1517E`（速度グレード **-1**）と
読める記載があり、board file の `-2` と食い違う。**決着はチップ上面の刻印。**
万一 -1 ならタイミング解析が楽観側に振れるため、分光計本体に入る前に確認する。

JTAG からは判別できない（IDCODE に速度グレードが入っておらず、Hardware Manager は
`xczu48dr` までしか報告しない）。

### 刻印を読まずに済ませる

知りたいのは「タイミング解析が楽観側に振れていないか」だけなので、
**遅い方（`-1`）で解析して閉じれば、どちらであっても安全**と言える。
`-1` で閉じる設計は `-2` でも必ず閉じる。

```bash
make               # 既定の -2 → build/
make timing-check  # -1 で通す → build-1-e/（build/ は無傷）
```

**検証ビルドは合否の判定にのみ使う。`-2` の結果と数字を比較してはいけない。**
`-1` のビルドは `board_part` もボードプリセットも使わない別の設計であり
（理由は下記）、配置配線も別物になる。クロック制約は同じ 10.000 ns / 100 MHz だが、
スラックの差は速度グレードだけに由来しない。

実績: proj002 は `-1` で WNS +6.700961 ns / WHS +0.034556 ns（2026-09-16）。
`-2` の +6.678998 / +0.027402 と近いが、**この 2 つは比較対象ではない**。

### なぜ -1 のビルドが board_part を使えないか

3 つとも 2026-09-16 に実際に試して塞がった。同じ順路を辿らないこと。

| 試した方法 | 結果 |
|---|---|
| `PART` を差し替えて `board_part` はそのまま | `board_part` が part をボード宣言値（-2）に**強制的に戻す**（WARNING: Project 1-153）。警告 1 行だけで、結果は -2 になる |
| プリセット適用後に `board_part` を外して part を変更 | BD 内の IP が locked になり `make_wrapper` が失敗（ERROR: BD 41-1665） |
| `set_speed_grade` で再解析 | **2024.1 で非推奨。機能しない**（"no longer supported"） |

そこで `PART` が既定以外のときは、最初から目的の part でプロジェクトを作り、
`board_part` もボードプリセットも使わない。PS の周辺機器設定（DDR / MIO）は
既定値になるが、**PL 側のタイミング解析には影響しない**。
検証ビルドのビットストリームは実機に使わない。

**`-1` で閉じず `-2` なら閉じる、という状況になって初めて刻印の確認が必要になる。**
その場合もヒートシンクを外す前に、board file が `-2` を宣言している根拠を
ベンダ（RealDigital）に問い合わせる。

## ハードウェア

| | 値 |
|---|---|
| ボード | RealDigital RFSoC 4x2 |
| FPGA | XCZU48DR / FFVG1517 |
| 書き込みポート | **PROG UART**（microUSB） |
| FTDI | `0403:6010` FT2232C/D/H |
| 自走 PL クロック | SYS_CLK_100M 100 MHz LVDS（Si5395 生成）/ P = AM15 |
| ユーザ LED | AR11 / AW10 / AT11 / AU10（LVCMOS18）。2026-09-16 に proj002 で点灯順序を物理的に確認済み |
| 押しボタン | AV12 / AV10 / AW9 / AT12 |
| スライドスイッチ | AN13 / AU12 / AW11 / AV11 |

**`USB DEVICE` ポートに挿すと FTDI が `lsusb` に現れず、JTAG target が 0 個になる。**
シルク印刷を読んで挿す。

### RF フロントエンドとクロック（proj003 以降）

出典は RFSoC 4x2 Reference Manual Rev A6。**実機での裏取りが済んだものは印を付けていく。**

| | 値 | 状態 |
|---|---|---|
| **ADC_B** | RF-ADC **Tile 226 / slice 0**（`adc_tiles[2].blocks[0]`）| **2026-09-16 に実信号で確定** |
| ADC_A | RF-ADC Tile 226 / slice 2（推定）| ADC_B が slice 0 だったことからの推定。未確認 |
| ADC_C / ADC_D | RF-ADC **Tile 224** | RefMan A6 記載。スライスの対応は未確認 |
| DAC_A | RF-DAC Tile 230 | RefMan A6 記載 |
| DAC_B | RF-DAC Tile 228 | RefMan A6 記載 |
| ADC 入力のバラン | **MABA-011118**（10 MHz 〜 10 GHz） | 各 SMA と ADC の間に入る。**DC 結合ではない** |
| RFDC 基準クロック | 491.52 MHz（Tile 224 / 226 / 228 / 230） | LMX2594 が供給 |
| システム REFCLK | 122.88 MHz DIFF | LMK04828 が供給 |
| RF SYSREF | 7.68 MHz DIFF | |
| 外部クロック入力 | **CLK_IN（SMA）** → LMK04828 | 実装済み。**基板改造は不要** |
| 複数ボード同期 | SYNC_IN（SMA） | |

クロック生成は Si5395B（PL 用 100 MHz LVDS をファクトリプログラムで生成）と、
LMK04828（ジッタクリーナ）＋ LMX2594 × 2（RF シンセ）の 2 系統に分かれる。
**proj001 / proj002 が使っていた自走 100 MHz は Si5395 側**で、RFDC のサンプリング
クロックとは別経路である。

### RFDC IP（usp_rf_data_converter）の制約

Vivado 2024.1 で実際に弾かれて判明した値。**GUI を開かずに Tcl で設定するときは
この 3 つを同時に満たす必要がある。**

| | 値 |
|---|---|
| ADC Sampling Rate の有効範囲 | **(1.0, 5.0) GSPS** |
| ADC Refclk Freq の有効値 | **VCO / FeedbackDiv の離散リスト**。fs を先に決めないと選択肢が出ない |
| PLL の VCO | 8.5〜13.2 GHz |
| ADC Outclk Freq の有効値 | fs / 16, /32, /64。**これが出力ピン `clk_adcX` の周波数**。AXIS のクロックではない |
| AXIS のクロック | `Fabric_Freq` = fs / Data_Width（派生値）。**IP からは出ない**ので Clocking Wizard で `clk_adcX` から逓倍して作る |
| Mixer Type | Data Type と Decimation Mode に依存。**Real / デシメーション 1 では 1（Bypassed）のみ** |
| デュアルタイルのスライス番号 | **0 と 2**（1 と 3 は disabled parameter） |

タイル単位のパラメータ（`ADC2_Sampling_Rate` 等）は、そのタイルのスライスが有効に
なるまで disabled parameter 扱いで、`set_property` は `WARNING: [BD 41-721]` の
1 行だけ出して **黙って無視される**。`ADC2_Enable` と `ADC2_Fabric_Freq` は派生値。

したがって設定の順序は
**スライス有効化 → スライスの設定 → PLL 有効化 → Sampling Rate → Refclk → Outclk**。
設定後は必ず読み返して検証する（`proj003/build.tcl`）。

RFSoC4x2 で LMX の 491.52 MHz を使う場合、成立する動作点は
**VCO 9830.4 MHz（FeedbackDiv 20）/ OutDiv 8 → fs 1228.8 MSPS** 付近に限られる。

### PYNQ 側のドライバ

| | |
|---|---|
| `xrfclk` の関数 | **`set_ref_clks(lmk_freq=, lmx_freq=)`**（v3.1.1）。旧版は `set_ref_clk`。版で名前が変わる |
| `xrfdc` | **`Overlay()` より前に `import xrfdc` すること。** PYNQ のドライバは import した時点で VLNV に登録される。忘れると `ol.<rfdc>` が素の `DefaultIP` になり `adc_tiles` が生えない |

ドライバが当たっているかは `isinstance(ol.rfdc, xrfdc.RFdc)` で確かめる。
当たっていなければ `ol.ip_dict['rfdc']['type']`（`.hwh` の VLNV）と
`xrfdc.RFdc.bindto` を見比べる。**版が食い違うと当たらない。**

RFSoC4x2 の `xrfclk` 引数は `lmk_freq=245.76, lmx_freq=491.52`。

**ビットストリームをロードした時点でタイルは起動し、PLL もロックしている。**
`StartUp()` / `DynamicPLLConfig()` を呼ぶ必要はなく、呼べば動いている状態を壊しうる。
状態は `tile.PLLLockStatus`（2 = locked）と `block.BlockStatus` で読む。

| 使える API | |
|---|---|
| `tile` | `ClockSource` `DynamicPLLConfig` `FIFOStatus` `GetFIFOStatusObs` `PLLConfig` `PLLLockStatus` `Reset` `SetupFIFO` `SetupFIFOBoth` `SetupFIFOObs` `ShutDown` `StartUp` `blocks` |
| `block` | `BlockStatus` `CalFreeze` `CalibrationMode` `GetCalCoefficients` `MixerSettings` `NyquistZone` `ResetNCOPhase` `SetCalCoefficients` |

### SMA のラベルとスライス番号は並びが逆

**RefMan の ADC_A / ADC_B の並びと、RFDC のスライス番号の並びは逆。**
Tile 226 の slice 0 だけを有効にしてビットストリームを作り、**ADC_B の SMA に
100.0125 MHz を入れたところ、その slice 0 に −1.7 dBFS で乗った**（2026-09-16）。

「A が slice 0」と素直に読むと逆になる。**SMA のラベルで設計を書かず、
実信号でどのスライスに乗るかを確かめること。** 間違えても
「DMA は完走するのに中身がノイズだけ」になるだけで、原因が遠い。

### ADC のデータ形式

14 bit を 16 bit の **上位に寄せている**（下位 2 bit は常に 0）。
全サンプルが 4 の倍数になるので、値の刻みを見れば判定できる。
フルスケールは ±32768 として dBFS を計算してよい。

**ブロックに `GetIntrStatus` は無い。** ADC の取りこぼし（= 記録の不連続）は
`block.BlockStatus['IsFIFOFlagsAsserted']` で見る。これが唯一の検出手段。

無効にしたタイル / ブロックは `not available in XRFdc_GetBlockStatus` を返す。
**どのタイルが生きているかはこれで確認できる。**

### 外部 10 MHz 基準クロック（proj004 で調べた実態）

**外部基準を挿していなくても LMK04828 の PLL2 はオンボード VCXO で出力を作る。**
したがってクロックは出るし ADC も動く（入出力間の位相関係が不定になるだけ）。
**「動いているように見える」ことは、外部基準が効いている証拠にならない。**

判定は **取得した波形の周波数オフセット（ppm）** で行う。proj003 の実測 +14.92 ppm は
**基板の 48 MHz XO（±15 ppm 品）の確度そのもの**で、これが Si5395 → LMK の 10 MHz →
PLL1 → 160 MHz VCXO → PLL2 → LMX → RFDC と伝わって fs の確度になっている。

| | 値 | 状態 |
|---|---|---|
| 出荷時の PLL1 基準 | **基板の Si5395 が出す 10 MHz** | RefMan A6 / TICS プロジェクト |
| 出荷時に選ばれる入力 | **CLKin1**（`0x0147` = `0x1A`） | 出荷時レジスタから確定 |
| **CLK_IN（SMA）の行き先** | **CLKin0** | **2026-09-17 に proj004 で実測確定** |
| LMK の VCXO | 160 MHz | RefMan A6 |
| PLL1 の位相比較周波数 | 80 kHz（10 MHz / 125）／ PLL1_N = 2000 | 出荷時レジスタ |

**出荷時のレジスタでは CLKin0 と CLKin1 の両方が 10 MHz 前提（R = 125）になっている。**
ケーブル無しで PLL1 がロックする以上、選ばれている CLKin1 が Si5395 側である。

**2026-09-17 に proj004 で実測確定した。** `0x0147` を `0x1A`（CLKin1）→ `0x0A`（CLKin0）に
差し替えるだけで、クロックのずれが **+14.912 ppm → −0.015 ppm** になった。
CLKin1 を明示指定した対照が `stock` と一致（+14.908 / +14.912）しているので、
**変わったのは基準入力だけ**と言い切れる。

| clkin | ppm |
|---|---|
| `stock`（出荷時 = CLKin1） | +14.912 |
| **`0`（CLK_IN の SMA）** | **−0.015** |
| `1`（CLKin1 を明示） | +14.908 |

残差 −0.015 ppm は「ずれが無い」ではなく、**53.3 µs のキャプチャとサブビン補間で
測れる下限**である。また 0 に潰れたことは「SG とボードが同じ基準を見ている」ことしか
言わず、基準そのものの確度はこの測定では分からない（共通のずれは打ち消える）。

#### CASPER のファイルをそのまま置く方式は成立しない

`xrfclk._read_tics_output()` はパッケージのディレクトリの `*.txt` を、
**ファイル名を `_` で 2 分割して** `チップ名_周波数.txt` と解釈する
（`chip, freq = name.split('_')`）。したがって
`rfsoc4x2_lmk_CLKin0_extref_10M_PL_122M88_LMXREF_245M76.txt` のような名前を置くと、
**`set_ref_clks()` が `ValueError: too many values to unpack` で落ちる。**

proj004 は代わりに、**出荷時のファイルをその場で読み、必要なレジスタだけ差し替えて**
`xrfclk._write_LMK_regs()` に渡す方式を採った。触るのは `0x0147`（CLKin の選択）と
`CLKinX_R` だけで、**PLL1_N・VCXO・PLL2 以降は触らない**（位相比較周波数 80 kHz を
保てば基板上のループフィルタがそのまま成立する）。

なお RFSoC 4x2 の PYNQ イメージは `xrfclk` にパッチが当たっており、
`_read_tics_output()` が `set_ref_clks()` のたびに走る（素の Xilinx 版は初回のみ）。

#### ロック状態を見ても基準の正しさは分からない

**`tile.PLLLockStatus` は RFDC タイルの PLL であって、LMK の PLL1 ではない。**
2026-09-17 に、CLK_IN に何も来ていない状態で CLKin0 を選んだところ、

| 見たもの | 値 |
|---|---|
| `tile.PLLLockStatus` | **2（locked）** |
| DMA | 完走。`done` = 1 |
| `IsFIFOFlagsAsserted` | 0 |
| 波形・高調波 | 正常 |
| **ppm** | **+90.68** |

**どの状態レジスタも正常を返しながら、クロックが 90 ppm ずれていた。**
PLL1 が基準を失って DAC が振り切れ、160 MHz VCXO が引っ張られた端の値である。
**外部基準が効いているかを状態レジスタで判定することはできない。ppm を測る。**

#### 書いたレジスタは読み返せない

`xrfclk` は SPI を書くだけで読み出しの口を持たない。LMK04828 の読み返しは 4 線モードで
`CLKin_SEL0` / `CLKin_SEL1` / `RESET` のいずれかのピンに出す方式で、RFSoC 4x2 で
そのピンがどこへ行っているかは未確認。有効にすると `Status_LD1`（PLL1 ロック LED、
`0x015F` = `0x0B`）を潰しかねない。**検証は LED と ppm という外側の証拠で行う。**

#### そのほか

- TI は「10 MHz は方形波でないと PLL1 がロックしないことがある。入力タイプは MOS に」と
  回答している（E2E フォーラム）。観測所の基準は正弦波なので、**ロックしなければ
  レベルか波形を疑う**。CLKin の入力タイプは `0x0146` にあるが**ビット割り当てが
  未確定なので触っていない**
- LMK04828 には**ホールドオーバ**がある。外部基準を抜いても直前の DAC 値を保持して
  VCXO を走らせ続けるので、**抜いた瞬間に ppm が戻るとは限らない**。内部基準との比較は
  必ず設定を書き直して取り直す
- 評価ボードで動く設定ファイルが実装基板では動かない例が報告されている

#### 信号が来ているかを先に測る

2026-09-17、`clkin 0` が +90.68 ppm になった原因は **SG の REF OUT が出ていなかった**
ことだった（AnaPico APSYN420 は既定で出ない。`ROSC:OUTP:STAT ON` が要る）。
スペアナで無出力を確認するまで、LMK の CLKin 入力バッファの型（`0x0146`）を疑っていた。

**レジスタを疑う前に、信号が来ているかを測る。** `0x0146` はビット割り当てが未確定の
ままで、結局触る必要は無かった。

## XDC と Vivado の run について

**XDC では一般の Tcl が使えない。** `if` / `foreach` / `while` / `lsort` / `concat` は

```
CRITICAL WARNING: [Designutils 20-1307] Command 'if' is not supported in the xdc constraint file.
```

で弾かれ、**その行は実行されない**。オブジェクトが取れないときに警告を出すような
防御的な書き方をすると、防御自体が動かず制約が丸ごと無効になる。
**XDC には制約だけを書き、条件分岐や検証は `build.tcl` 側（`open_run` 後）で行う。**

**`launch_runs` は別プロセスなので、run の中の警告は `make` のコンソールに出ない。**
`build/vivado/<proj>.runs/*/runme.log` にしかない。上の 20-1307 はこれと重なると
永久に見えないため、`build.tcl` の末尾で run のログから `CRITICAL WARNING` を
拾い上げること（proj003 で実装）。

2026-09-16 に proj003 で、この 2 つが重なって **WNS = −4.556 ns のビットストリームが
完走した**。クロック内の経路はすべて余裕があり、違反はクロック間だけだった。

### RFSoC4x2 のクロック実名（proj003 のブロックデザイン）

| クロック | 周期 | 中身 |
|---|---|---|
| `clk_pl_0` | 10.000 ns | PS の PL クロック 0 |
| `clk_pl_1` | 5.714 ns | PS の PL クロック 1。**200 MHz を要求して 175 MHz になる** |
| `RFADC<n>_CLK` | — | RFDC の `clk_adc<n>`（= `Outclk_Freq`） |
| `clk_out1_system_<clkwiz>_0` | — | Clocking Wizard の出力（生成クロック） |

**PS の PL クロックは要求値どおりに出るとは限らない。** PLL の刻みで下がり、
警告も出ない。`get_property CONFIG.FREQ_HZ` で読み返して確かめること。

## board files の置き場所

`board.repoPaths` に渡すのは **`board.xml` の 2 階層上**（`rfsoc4x2/` を含むディレクトリ）。

```
<clone>/board_files
  └ rfsoc4x2/1.0/board.xml
```

各 proj の `Makefile` の `BOARD_REPO` で持つ。**Vivado のインストールツリーの中には置かない**
（`<Vivado>/data/boards/board_files` は Vivado が自動で読むため指定が不要になり、
「どこに置いたか」が記録されないまま版を増やすと見失う）。

## board files の版は commit でしか識別できない

**版表記 `1.0` は中身が変わっても据え置かれる。** 実際、RealDigital は `1.0` のまま
`preset.xml` の DDR 設定を修正している。

| commit | 内容 |
|---|---|
| `7981645` Added board files for RFSoC4x2 | `PSU__DDRC__ROW_ADDR_COUNT` = **17** |
| `4b61c2a` Corrected DDR-4 Row Address Count | 同 = **16**（こちらが正） |

したがって `1.0` と書くだけでは実体を特定できない。**必ず commit を記録する。**

これは PL only の設計では表に出ない（`preset.xml` を読まないため）。
PYNQ でも PS は SD の boot イメージで初期化済みなので影響しない。
**効くのはこのブロックデザインから boot ファイル（FSBL / PetaLinux / `boot.bin`）を
生成するとき**で、DDR の行アドレス幅が 1 bit ずれた状態で焼くことになる。

2026-09-16 時点で `/tools/Xilinx/Vivado/2023.2/data/boards/board_files/rfsoc4x2` に
修正**前**（17）のコピーが存在していた。同じ VLNV `realdigital.org:rfsoc4x2:part0:1.0` を
名乗る中身の違う board file が同時に見えている状態は、どちらが採用されるか不定になるため退避した。

## Vivado_init.tcl に注意

`~/.Xilinx/Vivado/Vivado_init.tcl` は **Vivado の全バージョンが起動時に読む**初期化スクリプト。
ここに `board.repoPaths` のような設定を書くと、**GUI とバッチで別の board file を見る**状態に
なりうるし、設定が git に残らないので他のマシンで再現できない。

各 proj の `build.tcl` は `set_param board.repoPaths` を明示的に実行するので、
バッチビルドは `Vivado_init.tcl` の内容に影響されない（set であって append ではないため上書きされる）。
**ただし GUI で開くと `Vivado_init.tcl` 側が効く。** 両者を食い違わせないこと。

環境依存の設定は各 proj の `Makefile`（`XILINX_VIVADO` / `BOARD_REPO`）に持つのが原則。
版が git 履歴に残る。

## ローカル環境（各自の設定。値はここに書かない）

- Vivado の場所は各 proj の `Makefile` の `XILINX_VIVADO` で指定する
- Vivado ML **Enterprise** ライセンスが必要（ZU48DR は無償の Standard では対象外）
- ライセンスの Host ID・所有アカウント・rehost の経緯はリポジトリ外の作業記録で管理する
