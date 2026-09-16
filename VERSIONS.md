# 版とハードウェアの固定値

**このファイルには公開してよい情報だけを書く。** ライセンスの Host ID、AMD アカウント、
`.lic` の内容は書かない — git の履歴は消せないため「公開時に消す」は成立しない。
それらはリポジトリ外の作業記録で管理する。

## ツール

| | 値 | 備考 |
|---|---|---|
| Vivado | 2023.2 と 2024.1 を併設 | proj001 は 2023.2、**proj002 以降は 2024.1**（BSP と PYNQ v3.1 が前提とする版）。2026-09-16 に 2024.1 で `get_parts` / `get_board_parts` が通ることを確認 |
| PYNQ image | v3.1.1 (Carlisle) へ更新する | **ボードの SD カードは 2026-09-15 時点で v3.0.1**（Vivado 2022.2 相当）。2024.1 で作ったオーバーレイとは版が合わない。下記参照 |
| Board files | RealDigitalOrg/RFSoC4x2-BSP `board_files/rfsoc4x2/1.0` | **Vivado のインストールツリーの外に clone し、`board.repoPaths` で指す。** ツリー内（`<Vivado>/data/boards/board_files`）に置くと版を増やすたびにコピーが要り、入れ直しで消える。commit は未固定 |
| Part | `xczu48dr-ffvg1517-2-e` | 根拠: BSP board_files の宣言値 |

### PYNQ イメージの版

**ボードの SD カードは v3.0.1 だった**（2026-09-15 に実機で確認。それまで VERSIONS.md は
v3.1.1 と記載していたが、これは未確認の想定だった）。

| | Vivado |
|---|---|
| PYNQ v3.0.1 | 2022.2 で検証済み（PYNQ 開発元の推奨） |
| RFSoC-PYNQ v3.1.1 (Carlisle) | 2024.1。RFSoC 4x2 向けの最新イメージ |

BSP の board files が 2024.1 前提である以上、**イメージ側を v3.1.1 に上げて揃える**。
既存の v3.0.1 カードは上書きせず温存する（proj001 の環境を再現できる唯一の手段のため）。

暫定の逃げ道として `Overlay(..., ignore_version=True)` があるが、
版の合わない IP が動かない可能性があるとされており、恒久策にはしない。
特に RF Data Converter は `xrfdc` / `xrfclk` ドライバと IP の版が結合するので、
Phase 3 に入る前に必ず揃える。

### Part の未確認事項

リファレンスマニュアル Rev A5 の本文には `XCZU48DR-1FFVG1517E`（速度グレード **-1**）と
読める記載があり、board file の `-2` と食い違う。**決着はチップ上面の刻印。**
万一 -1 ならタイミング解析が楽観側に振れるため、分光計本体に入る前に確認する。

JTAG からは判別できない（IDCODE に速度グレードが入っておらず、Hardware Manager は
`xczu48dr` までしか報告しない）。

## ハードウェア

| | 値 |
|---|---|
| ボード | RealDigital RFSoC 4x2 |
| FPGA | XCZU48DR / FFVG1517 |
| 書き込みポート | **PROG UART**（microUSB） |
| FTDI | `0403:6010` FT2232C/D/H |
| 自走 PL クロック | SYS_CLK_100M 100 MHz LVDS（Si5395 生成）/ P = AM15 |
| ユーザ LED | AR11 / AW10 / AT11 / AU10（LVCMOS18） |
| 押しボタン | AV12 / AV10 / AW9 / AT12 |
| スライドスイッチ | AN13 / AU12 / AW11 / AV11 |

**`USB DEVICE` ポートに挿すと FTDI が `lsusb` に現れず、JTAG target が 0 個になる。**
シルク印刷を読んで挿す。

## board files の置き場所

`board.repoPaths` に渡すのは **`board.xml` の 2 階層上**（`rfsoc4x2/` を含むディレクトリ）。

```
<clone>/board_files
  └ rfsoc4x2/1.0/board.xml
```

各 proj の `Makefile` の `BOARD_REPO` で持つ。**Vivado のインストールツリーの中には置かない**
（`<Vivado>/data/boards/board_files` は Vivado が自動で読むため指定が不要になり、
「どこに置いたか」が記録されないまま版を増やすと見失う）。

## ローカル環境（各自の設定。値はここに書かない）

- Vivado の場所は各 proj の `Makefile` の `XILINX_VIVADO` で指定する
- Vivado ML **Enterprise** ライセンスが必要（ZU48DR は無償の Standard では対象外）
- ライセンスの Host ID・所有アカウント・rehost の経緯はリポジトリ外の作業記録で管理する
