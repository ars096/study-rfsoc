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
| ADC_A / ADC_B | RF-ADC **Tile 226** | RefMan A6 記載。ブロック番号の付き方は `xrfdc` で未確認 |
| ADC_C / ADC_D | RF-ADC **Tile 224** | 同上 |
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

### 外部 10 MHz 基準クロックの罠

**外部基準を挿していなくても LMK04828 の PLL2 はオンボード VCXO で出力を作る。**
したがってクロックは出るし ADC も動く（入出力間の位相関係が不定になるだけ）。
**「動いているように見える」ことは、外部基準が効いている証拠にならない。**

判定するには PLL1 のロック状態を読むか、取得した波形の周波数オフセットを測る。
また `xrfclk` が書き込む LMK04828 のレジスタ設定ファイルを、外部 10 MHz を CLKin0 から
取る版に差し替える必要がある。TICS Pro で自作する前に、CASPER が持つ RFSoC4x2 向けの
検証済みファイルを当たること（`rfsoc4x2_lmk_CLKin0_extref_10M_PL_122M88_LMXREF_245M76.txt`）。

評価ボードで動く設定ファイルが実装基板では動かない例が報告されている。

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
