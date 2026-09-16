# proj002 — Zynq MPSoC + AXI GPIO（PYNQ から LED を叩く）

日付: 2026-09-15
状態: **進行中**

## 目的

制御系の疎通を取り戻す。proj001 は PL だけで閉じていたので、**PS ↔ PL の経路と
PYNQ オーバーレイの流儀**が未検証のまま残っている。分光計本体（RFDC → PFB/FFT →
積分 → 読み出し）は最後が必ずこの経路になるので、ここを最小構成で通しておく。

確かめたいのは 3 点。

1. Zynq MPSoC のボードプリセットが BSP の board file から当たること
2. block design から `.hwh` が出て、**PYNQ v3.1.1 が `.bit` と一緒に読めること**
3. PS から AXI 経由で PL のレジスタを叩けること（AXI GPIO → LED）

## 設計

```
zynq_ultra_ps_e ──M_AXI_HPM0_FPD──▶ AXI SmartConnect ──▶ axi_gpio (gpio_led)
       │                                                        │
       └── pl_clk0 100 MHz / pl_resetn0 ──────────────────┘   gpio_io_o[3:0] ──▶ LED
```

- AXI GPIO は 4bit・全出力・シングルチャネル
- IP 名を `gpio_led` にしてある。PYNQ 側から `ol.ip_dict["gpio_led"]` で引くため
- 外部ポート名を `led` にしてラッパのポートを `led[3:0]` にし、XDC の記述を proj001 と揃えた

## 決めたこと

- **決定**: proj002 から **project mode** に切り替える
  **理由**: PYNQ が読む `.hwh` は block design からしか生成されず、block design は
  非プロジェクトモードでは作れない（`create_bd_design` が拒否される）。
  Vivado プロジェクトは `build/vivado` に閉じ込め、`build/` ごと `.gitignore` 対象に
  してあるので、リポジトリに入る生成物は増えない
  **見送った案**: 非プロジェクトモードのまま `create_ip` で PS と AXI GPIO を置く案。
  `.hwh` が出ないため PYNQ から使えない

- **決定**: Vivado を **2024.1** に上げる（proj001 は 2023.2 のまま据え置き）
  **理由**: BSP と PYNQ v3.1.1 がいずれも 2024.1 を前提としており、board file と
  ボードプリセットを実際に使い始めるのがこの proj だから。RFDC に入ってから版を
  跨ぐ方が高くつく。`projNNN` が自己完結なので併設で困らない
  **見送った案**: 2023.2 のまま GPIO まで進める案。不整合が出たときに設計の問題と
  切り分けられない

- **決定**: PL クロックは PS の `pl_clk0` 100 MHz を使う
  **理由**: proj001 が自走 100 MHz を選んだのは「PS が構成されないと LED が動かず
  配線ミスと区別できない」ためだったが、**今回は PS が動いていること自体が確認対象**
  なので前提が逆になる。PYNQ では PS は SD ブート済みで、オーバーレイは PL だけを
  差し替える

- **決定**: `build/proj002.bit` と `build/proj002.hwh` を同名同階層に並べて出す
  **理由**: PYNQ の `Overlay()` は `.bit` と同じベース名の `.hwh` を探す。
  Vivado の出力は `system_wrapper.bit` と `system.hwh` で名前も階層も揃わないため、
  `build.tcl` の末尾でコピーして揃えている

## やったこと

- （未実施）

## 結果

- （未記入）

## 結論・次にやること

- （未記入）
- 次の proj の候補: RF Data Converter を置いて ADC の生データを PS 側へ吸い上げる

## 再現手順

```bash
# Vivado サーバ
cd proj002
make            # 合成〜実装〜ビットストリーム（build/proj002.bit, build/proj002.hwh）
```

`Makefile` 先頭の 2 つを自分の環境に合わせる。

| 変数 | 意味 |
|---|---|
| `XILINX_VIVADO` | Vivado のインストール先。proj002 は **2024.1** |
| `BOARD_REPO` | `RFSoC4x2-BSP/board_files` の場所。ここが違うと board part が見つからない |

**ボードの SD カードは v3.0.1 なので、先に v3.1.1 へ更新する**（[`../VERSIONS.md`](../VERSIONS.md)）。
急ぐ場合の暫定策として `Overlay(BIT, ignore_version=True)` で 3.0.1 のまま試すこともできるが、
恒久策にはしない。

```bash
# ボード（PYNQ v3.1.1）
scp build/proj002.bit build/proj002.hwh xilinx@<board>:~/proj002/
ssh xilinx@<board>
cd ~/proj002 && sudo python3 led_test.py
```

`make prog` で JTAG 書き込みもできるが、**それだけでは LED は光らない**。
PL のレジスタを叩くのは PS 側のソフトなので、確認は PYNQ 経由で行う。

環境の固定値は [`../VERSIONS.md`](../VERSIONS.md)、詰まったときは
[`../proj001/docs/runbook.md`](../proj001/docs/runbook.md)。

## 想定される詰まりどころ

| 症状 | 見るところ |
|---|---|
| board part が見つからない | `BOARD_REPO` のパス。`<repo>/rfsoc4x2/<version>/board.xml` が居るか |
| `apply_bd_automation` がプリセットを当てられない | BSP が 2024.1 前提。Vivado の版 |
| `Overlay()` が `.hwh` を見つけられない | `.bit` と `.hwh` が同名で同じディレクトリに居るか |
| `ip_dict` に `gpio_led` が無い | block design の IP 名。`assign_bd_address` が走ったか |
| LED が光らない・順序が違う | `src/led.xdc` のピン割り当て（proj001 で確認済みの値） |
