# 版とハードウェアの固定値

**このファイルには公開してよい情報だけを書く。** ライセンスの Host ID、AMD アカウント、
`.lic` の内容は書かない — git の履歴は消せないため「公開時に消す」は成立しない。
それらはリポジトリ外の作業記録で管理する。

## ツール

| | 値 | 備考 |
|---|---|---|
| Vivado | 2023.2 | 2024.1 への移行を検討中（BSP と PYNQ v3.1.1 が前提とする版） |
| PYNQ image | v3.1.1 (Carlisle) | Vivado 2024.1 前提 |
| Board files | RealDigitalOrg/RFSoC4x2-BSP | commit 未固定。clone して `board.repoPaths` に指定 |
| Part | `xczu48dr-ffvg1517-2-e` | 根拠: BSP board_files の宣言値 |

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

## ローカル環境（各自の設定。値はここに書かない）

- Vivado の場所は各 proj の `Makefile` の `XILINX_VIVADO` で指定する
- Vivado ML **Enterprise** ライセンスが必要（ZU48DR は無償の Standard では対象外）
- ライセンスの Host ID・所有アカウント・rehost の経緯はリポジトリ外の作業記録で管理する
