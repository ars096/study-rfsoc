# proj003 — RF Data Converter（ADC_A の生データを PYNQ で読む）

日付: 2026-09-16 〜
状態: **進行中**（実装済み・Vivado 未通し）

## 目的

**ADC_A の生サンプルを PS へ吸い上げ、既知の CW トーンで数値が正しいことを確認する。**

proj002 までで PS ↔ PL の疎通と PYNQ オーバーレイの流儀は通った。ここから先は
PL の中身を疑う作業になるが、**中身を疑うには中身を覗く手段が要る**。proj003 の
本当の成果物はビットストリームではなく、以降の proj が使う「測定器」である。

確かめたいのは 3 点。

1. board preset で RFDC のタイルが当たり、タイル PLL がロックすること
2. ADC の AXI4-Stream が PS の DRAM まで届くこと（DMA が完走する）
3. **取れた数字が物理的に正しいこと** — 既知周波数の CW が、期待するビンに、
   期待する dBFS で立つ

3 が本命。1 と 2 だけなら「何かのデータ」は取れてしまう。

## 設計

```
                  ┌──── clk_wiz_adc/clk_out1 153.6 MHz ─────────┐
                  │                                              │
 ADC_A ─balun─▶ rfdc ──m20_axis──▶ capture_gate_0 ──▶ axis_fifo ─┼─▶ dma_adc
  (SMA)        Tile 226 / ADC_A     TLAST 生成        非同期      │   S2MM のみ
               Real / Mixer 1       記録の連続性      4096 word   │      │
               デシメーション 1          ▲                        │      │ M_AXI_S2MM
               fs = 1228.8 MSPS          │ ctrl/status           │      ▼
                  ▲                 gpio_capture                 │   smc_data
                  │ s_axi                ▲ S_AXI                 │      │
                  │                      │              pl_clk1 200 MHz │
 zynq_ultra_ps_e ─┴── M_AXI_HPM0_FPD ─▶ smc_ctrl                 │      │
      │  pl_clk0 100 MHz（制御系）                                │      │
      └── S_AXI_HP0_FPD (128bit) ◀──────────────────────────────────────┘
```

| セル | 役割 |
|---|---|
| `rfdc` | RF Data Converter。PYNQ から `ol.rfdc` で引く |
| `capture_gate_0` | 自作。TLAST の生成と記録の連続性（下記） |
| `clk_wiz_adc` | `rfdc/clk_adc2`（fs/16 = 76.8 MHz）を AXIS の fs/8 = 153.6 MHz に逓倍する |
| `axis_fifo` | 非同期 FIFO。AXIS ドメイン → `pl_clk1` の乗り換えをここに閉じ込める |
| `dma_adc` | AXI DMA（S2MM のみ・Simple mode）。`ol.dma_adc` |
| `gpio_capture` | キャプチャの arm と状態読み。`ol.gpio_capture` |

### クロックドメインは 3 つに分かれる

| ドメイン | 周波数 | 何が載るか |
|---|---|---|
| `pl_clk0` | 100 MHz | AXI4-Lite 制御系（RFDC・DMA・GPIO のレジスタ） |
| `clk_wiz_adc/clk_out1` | 153.6 MHz | RFDC の AXIS 出力・`capture_gate`・FIFO の書き込み側 |
| `pl_clk1` | 200 MHz | FIFO の読み出し側・DMA の MM 側・HP ポート |

### サンプリング周波数の選び方

LMX2594 が RFDC タイルへ 491.52 MHz を渡す（ボード既定）。これは動かせない。
**制約は 3 つあり、どれか 1 つを忘れると IP に弾かれる**（2026-09-16 に全部踏んだ）。

| | 制約 |
|---|---|
| (a) | IP の Sampling Rate の有効範囲は **(1.0, 5.0) GSPS** |
| (b) | Refclk Freq の有効値は **VCO / FeedbackDiv の離散リスト**。つまり **fs を先に決めないと refclk の選択肢が決まらない** |
| (c) | VCO は 8.5〜13.2 GHz |

`491.52 = VCO / N` を満たす VCO は N = 18..26 で 8847.36〜12779.52 MHz。そのうち
`fs = VCO / OutDiv` が (1.0, 5.0) に入り、AXIS とデータレートが現実的なのは 1 つだけ。

```
VCO = 9830.4 MHz (FeedbackDiv = 20) / OutDiv = 8 → fs = 1228.8 MSPS

他の候補:
  OutDiv = 6 → 1638.4 MSPS   3.28 GB/s で MM 側（3.2 GB/s）が足りない
  OutDiv = 4 → 2457.6 MSPS   AXIS が 307 MHz で重い
  OutDiv =10 →  983.04 MSPS  (a) の下限 1.0 GSPS を割る
```

| | 値 | 効いてくるところ |
|---|---|---|
| fs | 1228.8 MSPS | 第 1 ナイキストゾーン = DC 〜 614.4 MHz |
| AXIS 語 | 8 sample × 16 bit = 128 bit | |
| AXIS クロック | 1228.8 / 8 = **153.6 MHz** | `Fabric_Freq`。**IP からは出ないので Clocking Wizard で作る** |
| `clk_adc2` | 1228.8 / 16 = **76.8 MHz** | `Outclk_Freq`。IP が出す唯一のクロック。Clocking Wizard の入力 |
| データレート | 1228.8 MSPS × 2 B = **2.4576 GB/s** | `pl_clk1` 200 MHz の 3.2 GB/s に対し 30% の余裕 |
| FIFO | 4096 語 = 64 KiB | 記録の半分を吸える。**溢れると記録が不連続になる** |
| キャプチャ長 | 2^16 = 65536 サンプル（128 KiB） | 53.3 µs 分 = 8192 ビート |
| FFT 分解能 | 1228.8 MHz / 65536 = **ちょうど 18.75 kHz** | 試験トーンをビン中心に置ける |

`build.tcl` は設定後に **IP から値を読み返して**、反映されていることを確認する。
`WARNING: [BD 41-721]` も `set_property` のエラーも「前の正しい設定に戻した」としか
言わずに進むので、**読み返す以外に「設定したつもりで効いていない」状態を検出する
手段がない**。

なお 2.4576 GB/s の負荷は **proj003 固有**である。積分器が入れば読み出しは
積分周期ごとのスペクトルだけになり、桁で軽くなる。

## 決めたこと

- **決定**: 「自作 RTL ゼロ」の方針は撤回し、`capture_gate` だけ書く
  **理由**: 既製 IP で代用できない役割が 2 つある。
  (1) **TLAST を作る。** RFDC の AXI4-Stream には TLAST が無い。AXI DMA の S2MM は
  パケットの終端を TLAST で認識するため、長さだけに頼ると完了条件が DMA の実装依存になる。
  (2) **記録の連続性を保証する。** 待機中も下流の FIFO へ流し続けると、次のキャプチャの
  先頭が前回の残りで埋まり、記録の途中に位相の飛びが入る。FFT では見かけ上の
  ノイズフロアの上昇として現れ、**「ADC が悪いのか経路が悪いのか」が切り分けられなくなる**。
  待機中は上流を受け取って捨て、下流を常に空にしておく
  **見送った案**: 長さだけで DMA を止める案。動くかもしれないが、動かなかったときに
  設計の意図として「ここで終わるはず」と言えない
  **重要**: 待機中も `s_axis_tready` は 1 に保つ。上流に backpressure をかけると
  RFDC 側がサンプルを落とす

- **決定**: 動いているタイルには触らない（既定は検証のみ）
  **理由**: ビットストリームをロードした時点でタイルは起動し、PLL もロックしている
  （2026-09-16 に確認: `PLLLockStatus` = 2 / `SamplingFreq` = 1.2288 / `ClockSource` = 1）。
  そこへ `DynamicPLLConfig` や `StartUp` をかけるのは、**動いている状態をわざわざ
  壊しにいく**ことになる。`adc_capture.py` は状態を読んで検証するだけで、
  作り直しは `--pll-config` / `--restart` を明示したときにしか行わない

- **決定**: XDC には制約だけを書き、検証は `build.tcl` 側で行う
  **理由**: **XDC では一般の Tcl が使えない。** `if` / `foreach` / `lsort` / `concat`
  は `CRITICAL WARNING: [Designutils 20-1307]` で弾かれ、**その行は実行されない**。
  2026-09-16、「オブジェクトが取れなかったら警告を出す」という防御的な書き方をして
  これを踏んだ。**防御そのものが動かない構文だったため制約が丸ごと無効になり、
  WNS = −4.556 ns のビットストリームが完走した**
  **付随**: `launch_runs` は別プロセスなので、run の中の警告は `make` のコンソールに
  出ない。`build.tcl` は実装後に run のログから `CRITICAL WARNING` を拾い上げる。
  これが無いと 20-1307 は永久に見えない
  **付随**: クロックは実装の段階で出そろうので、`timing.xdc` は
  `USED_IN_SYNTHESIS false` にしてある

- **決定**: タイミングが閉じていないビルドは `make` を失敗させる
  **理由**: 「できたように見えるが使ってはいけない `.bit`」を黙って置いていくと、
  あとで必ず取り違える。成果物は調査のために残すが、終了コードは非ゼロにする

- **決定**: AXIS クロックは `rfdc/clk_adc2` から Clocking Wizard で作る
  **理由**: RFDC は AXIS の 153.6 MHz を出さない。IP の出力ピン `clk_adc2` は
  `Outclk_Freq`（fs/16, fs/32, fs/64 から選ぶ）で、AXIS が必要とする `Fabric_Freq`
  （fs / `Data_Width`）とは別物だった。**両者を同じものだと思って `Outclk_Freq` に
  153.6 を入れ、弾かれて初めて分かった**（2026-09-16）
  **見送った案**: PS の PL クロックで AXIS を駆動する案。**AXIS クロックは fs/8
  きっかりでなければならず**、わずかでもずれれば FIFO が溢れるか枯れる。PS の PLL は
  153.6 MHz を正確に作れないので成立しない
  **付随**: 逓倍比を小さくするため `Outclk_Freq` は有効値のうち最大の 76.8 MHz を選ぶ。
  MMCM のロックは **タイルが起動して `clk_adc2` が出てから**なので、`locked` を
  `rst_adc/dcm_locked` へ入れて ADC ドメインをそれまでリセットに保つ

- **決定**: AXI4-Lite の制御系は `pl_clk0`、ADC のデータ経路は AXIS クロックに置き、
  AXI DMA は Asynchronous Clocks を有効にする
  **理由**: `clk_adc2` は **タイルが起動して初めて出る**。制御系をその系統に
  載せると、タイルを起動するためのレジスタアクセス自体がクロック待ちになり、
  永久に起動できない（鶏と卵）
  **見送った案**: PL 全体を ADC 系の単一ドメインにする案。配線は簡単になるが
  上記で詰む。`maxihpm0_fpd_aclk` まで含めると症状が「PS がハングする」
  になって原因が遠くなる

- **決定**: Real モード・NCO なし・デシメーション 1 で、生サンプルをそのまま取る
  **理由**: DDC を入れると出力が I/Q になり、語の並びとナイキストゾーンの解釈が
  同時に変わる。生サンプルなら FFT の結果を素直に読める。**proj003 の目的は
  「数字が正しいと言い切れる状態」を作ることなので、解釈の自由度を減らす**
  **見送った案**: 4915.2 MSPS のままデシメーション ×8。最終仕様には近いが、
  設定項目が増え、詰まったときに RFDC の設定と経路のどちらが悪いか分からない

- **決定**: サンプリング周波数を 1228.8 MSPS にする（ボード既定の 4915.2 MSPS を使わない）
  **理由**: AXIS クロックが 153.6 MHz に収まり、PL のタイミングが論点にならない。
  4915.2 MSPS をデシメーションなしで取ると AXIS が 300〜600 MHz 級になり、
  最初の一回としては重い。**上げるのは後からできる**
  **経緯**: 当初 983.04 MSPS（= 491.52 × 2）を選んだが、**IP の Sampling Rate の
  有効範囲が (1.0, 5.0) GSPS** で弾かれた。ADC の下限を 0.5 GSPS と見積もっていたのが
  誤り。491.52 MHz の refclk と両立する範囲で最も軽いのが 1228.8 MSPS になる

- **決定**: 読み出しは AXI DMA（S2MM のみ・Simple mode・Buffer Length Register 26bit）
  **理由**: 単発の有限長キャプチャに Scatter-Gather は不要。26bit にすると 64 MiB まで
  一発で取れる。積分器が入った後の読み出しにもそのまま使い回せる
  **見送った案**: BRAM スナップショット。挙動は決定的だが深さが固定され、後段で使えない

- **決定**: RFDC の CONFIG は **1 つずつ設定し、失敗は集めてまとめて報告する**
  **理由**: RFDC の CONFIG 名と許容値は Vivado の版と他のパラメータに依存して変わる。
  まとめて `set_property` すると最初の 1 つで止まり、残りが正しいのか分からないまま
  往復することになる。`build.tcl` は失敗した項目の「要求値」と「許される値」を
  控えて先へ進み、最後にまとめて報告したうえで、**IP が実際に持つ CONFIG と
  その許容値を `build/rfdc_params.rpt` に書き出す**

- **決定**: RFDC は「スライスを有効にする → タイルの設定 → スライスの設定」の順で設定する
  **理由**: タイル単位のパラメータ（`ADC2_Sampling_Rate` 等）は、そのタイルの
  スライスが有効になるまで disabled parameter 扱いで、**`WARNING: [BD 41-721]`
  の 1 行だけを出して黙って無視される**（2026-09-16 に実際に踏んだ）。
  `ADC2_Enable` は派生パラメータなので触らない。無視されていないことは
  **設定後に IP から読み返して**確かめる

- **決定**: ADC のキャリブレーションは既定のまま（背景校正を切らない）
  **理由**: 最初から変数を増やさない。分光計として問題になるかどうかは、
  積分後のスペクトルで初めて判断できる（Phase 4 以降）

- **決定**: 外部 10 MHz 基準クロックは proj003 に含めず proj004 に分ける
  **理由**: 外部基準が来ていなくても LMK04828 の PLL2 はオンボード VCXO で出力を作る。
  つまり **外部基準を挿していなくても「動いているように見える」**（入出力間の位相関係が
  不定になるだけ）。効いているかどうかを判定するには PLL1 のロックを読むか、
  **取れた波形の周波数オフセットを測る**しかない。その測定手段が proj003 の成果物なので、
  順序は proj003 → proj004 で固定される

## キャプチャ制御のビット割り当て

`gpio_capture` と `capture_gate` の取り決め。**ソフトと RTL の両方を直すこと。**

| | 向き | 内容 |
|---|---|---|
| ch1 `gpio_io_o` | 出力 32bit | `[23:0]` n_beats（ビート数）/ `[31]` arm（**立ち上がり**で起動） |
| ch2 `gpio2_io_i` | 入力 32bit | `[0]` busy / `[1]` done（arm でクリア） |

1 ビート = 8 サンプル。65536 サンプルなら n_beats = 8192。

**手順の順序が重要**: 先に DMA を張り、それから arm する。逆にするとゲートが先に
流し始め、DMA が受ける前に FIFO が溢れて記録の先頭が欠ける。

## 段取り

proj003 の中を 3 段に切る。詰まったときに容疑者が分かれる。

1. **RFDC を置いてビルドだけ通す。** `--probe` でタイルが列挙され、PLL がロックする
2. **FIFO と DMA を足す。** N サンプルの転送が完走する（タイムアウトしない）
3. **CW を入れる。** FFT のピークが期待どおりの位置と高さに立つ

`capture_gate` は Vivado を通す前に `make sim` で検証済み（下記）。

## 成功条件

| # | 条件 | 期待値 |
|---|---|---|
| 1 | `xrfdc` がタイルを列挙し、PLL がロックする | `PLLLockStatus` = 2 |
| 2 | DMA が完走する | 65536 サンプルの転送がタイムアウトしない。`done` が立つ |
| 3 | **CW のピーク周波数が一致する** | 100.0125 MHz（= 18.75 kHz × 5334）を入れて bin 5334 に立つ。これが **fs の裏取りそのもの**。**2026-09-16 に達成** |
| 4 | 裾の非対称が説明できる | **信号発生器とボードのクロックは独立**なので、ピークはビン中心に乗らない。サブビン補間でずれを Hz / ppm で出す（2026-09-16 の実測は約 +15 ppm）。**proj004 で減るべき量** |
| 5 | 折返しが説明できる | 800 MHz を入れると 1228.8 − 800 = **428.8 MHz** に見える |
| 6 | 振幅が dBFS で整合する | SG の設定値と、バラン + ADC のフルスケールから予想される値が一致する。**高調波が −40 dBc より大きければ入力過大**（2026-09-16 は −1.7 dBFS で H3 が −11 dBc） |
| 7 | 無入力時のノイズフロアが妥当 | 全 0 でも飽和でもない。**配線ミスはこの 2 つに振れる** |

## ファイル

| | |
|---|---|
| `build.tcl` | ブロックデザインの生成から `.bit` / `.hwh` まで |
| `src/capture_gate.v` | AXI4-Stream の有限長スナップショット（自作 RTL はこれだけ） |
| `src/timing.xdc` | 非同期クロックグループと CDC の false path |
| `sim/tb_capture_gate.v` | `capture_gate` のテストベンチ（icarus verilog） |
| `build/rfdc_params.rpt` | RFDC IP の全 CONFIG と許容値（生成物。版のズレを追う唯一の手がかり） |
| `pynq/adc_capture.py` | ボード上での取得と FFT 検証 |
| `tools/apsyn.py` | 試験トーンの供給。AnaPico APSYN420 を USBTMC で叩く（**Vivado サーバ**に USB 接続。標準ライブラリのみ） |
| `program.tcl` | JTAG 書き込み（PYNQ 経由で使うので通常は不要） |

## 再現手順

```bash
# 手元（Vivado もライセンスも要らない）
cd proj003
make sim           # capture_gate のテストベンチ。RTL を触ったらまずこれ

# Vivado サーバ
make               # 合成〜実装〜ビットストリーム
make timing-check  # 速度グレード -1 でも閉じるか（build-1-e/ に出る）
```

```bash
# Vivado サーバ — 試験トーンの供給（APSYN420 を USB-B で繋ぐ）
cd proj003
python3 tools/apsyn.py --probe          # まずこれ。*IDN? と現在の設定
python3 tools/apsyn.py --preset bin     # 100.005 MHz / -10 dBm / 出力 ON
python3 tools/apsyn.py --preset leak    # 100.000 MHz（ビン中心から外す）
python3 tools/apsyn.py --preset fold    # 600 MHz（第 2 ナイキストゾーン）
python3 tools/apsyn.py --off            # 終わったら切る
```

**出力は -10 dBm を既定にしてある。** ADC 入力のフルスケールは +1 dBm 級しかなく、
0 dBm を超える設定には `--force` が要る。

```bash
# ボード（PYNQ v3.1.1）
scp build/proj003.bit build/proj003.hwh pynq/adc_capture.py xilinx@<board>:~/proj003/
ssh xilinx@<board>
cd ~/proj003
sudo python3 adc_capture.py --probe             # まずこれ。タイル / ブロックの確定
sudo python3 adc_capture.py --tone 100.0125     # ビン中心の CW
sudo python3 adc_capture.py --tone 100.0        # ビン中心から外す
sudo python3 adc_capture.py --tone 800.0 --zone 2   # 第 2 ナイキストゾーン
```

環境の固定値は [`../VERSIONS.md`](../VERSIONS.md)、詰まったときは
[`../proj001/docs/runbook.md`](../proj001/docs/runbook.md)。

## 範囲外（送り先）

| 項目 | 送り先 |
|---|---|
| 外部 10 MHz 基準クロック | **proj004** |
| 4ch 同時取得・タイル間同期（MTS） | proj005 |
| PFB / FFT・積分 | Phase 4（proj006 以降） |
| 連続転送（サイクリック DMA・リングバッファ） | 積分器が入る段階 |
| DAC・ループバック | 必要になったら |

## 着手前に裏取りが要ること

- ~~**ADC_A の tile / block**~~ → **確定済み（2026-09-16）。ただし A と B が逆だった。**
  有効にしたのは Tile 226 slice 0（PYNQ 側は `rfdc.adc_tiles[2].blocks[0]`）だが、
  **実信号が乗ったのは `ADC_B` の SMA**。RefMan の A/B の並びとスライス番号の
  並びは逆である。**SMA のラベルで設計を書かず、実信号で確かめること。**
  他のタイル・ブロックは `not available in XRFdc_GetBlockStatus` を返すので、
  無効化が効いていることも同時に確認できた
- ~~14 bit のビット寄せ~~ → **確定済み**。16 bit の **上位に寄せている**
  （全サンプルが 4 の倍数）。フルスケールは ±32768
- 14 bit サンプルを 16 bit 語に収める際のビットの寄せ方。`--probe` の後の
  取得で `max|x|` を見る（±32768 級なら MSB 揃え、±8192 級なら LSB 揃え）
- 試験トーンの周波数。ADC 入力は **MABA-011118 バラン（10 MHz 〜 10 GHz）** で
  AC 結合されている。100 MHz 級なら問題ない

## 想定される詰まりどころ

| 症状 | 見るところ |
|---|---|
| `set_property` が RFDC の CONFIG で落ちる | 版のズレ。失敗した項目と**許される値**が一覧で出る。`build/rfdc_params.rpt` に全 CONFIG と許容値 |
| `WARNING: [BD 41-721] ... disabled parameter` が出る | タイルのパラメータをスライス有効化より前に設定している。**警告 1 行で黙って無視される** |
| `IP_Flow 19-3461 Value ... is out of the range` | 許容値が他のパラメータに依存して絞られている（例: Real / デシメーション 1 では `ADC_Mixer_Type` は 1 = Bypassed のみ） |
| `ADC2_Outclk_Freq` に AXIS の周波数を入れて弾かれる | **Outclk は AXIS のクロックではなく `clk_adcX` の周波数**（fs/16, /32, /64）。AXIS は `Fabric_Freq` = fs / `Data_Width` で派生し、IP からは出ない |
| `clk_adc2` の周波数が `Outclk_Freq` と違う | Clocking Wizard の入力周波数の前提が崩れる。`---- RFDC のクロックピン ----` の一覧を見る |
| BUFG の段数に関する DRC が出る | `clk_wiz_adc` の `PRIM_SOURCE`。`No_buffer` を前提にしているので `Global_buffer` に変えてみる |
| MMCM がロックしない | `clk_adc2` はタイルが起動して初めて出る。`xrfdc` でタイルを起動する前は `locked` が 0 で正常 |
| RFDC が設定を丸めた、と言って止まる | タイル PLL の VCO 範囲（8.5〜13.2 GHz）。上の計算をやり直す |
| **WNS が説明できない値になる** | 非同期クロックグループが効いているか。`---- クロック ----` と `GROUP:` の出力を見る。クロック内は余裕があるのに WNS が大きく負なら、乗り換えの宣言漏れ |
| XDC を書いたのに効いていない | **XDC では `if` / `foreach` / `lsort` / `concat` が使えない**（`Designutils 20-1307`）。弾かれた行は実行されない。`---- run の CRITICAL WARNING ----` に出る |
| DRC に `27 net(s) have no routable loads` | 無効にした ADC/DAC タイルの `*_done_i` など。**正常**（使っていないタイルの信号） |
| `ol.rfdc` が `DefaultIP` のまま（`adc_tiles` が無い） | **`import xrfdc` を `Overlay()` より前に書いたか。** PYNQ のドライバは import した時点で VLNV に登録される。書き忘れるとドライバが当たらない |
| ドライバが当たらない（import はしている） | `.hwh` の VLNV と `xrfdc.RFdc.bindto` を見比べる。**版が食い違うと当たらない** |
| `xrfclk` に `set_ref_clk` が無い | v3.1.1 は `set_ref_clks`。版で名前が変わる |
| `xrfdc` がタイルを見つけない | `.hwh` に RFDC が入っているか。**ボードに持ち込む前に確認できる** |
| タイル PLL がロックしない | `xrfclk.set_ref_clk()` を先に呼んだか。LMX が 491.52 MHz を出しているか |
| DMA が完了しない / `done`=0 かつ `busy`=0 | ゲートが一度も起動していない。GPIO の配線か arm のビット割り当て |
| DMA が完了しない / `busy`=1 のまま | RFDC から `tvalid` が出ていない。タイルの起動と、MMCM がロックしているか |
| ピークの裾が非対称（`-6.02 / -12.04 / -12.04` にならない） | 正常。SG とボードのクロックが独立なので、ビン中心には乗らない。ずれ量は ppm で報告される |
| 高調波が大きい（H3 が −40 dBc より上） | **入力レベルが高すぎて ADC が圧縮している**。10 dB 下げて高調波が 20〜30 dB 下がれば圧縮が原因 |
| `IsFIFOFlagsAsserted` が 0 以外になる | **RFDC がサンプルを落としている = 記録が不連続**。下流の帯域（FIFO / DMA / HP ポート）。ブロックに `GetIntrStatus` は無く、これが唯一の検出手段 |
| 取れたデータが全部 0 | **ADC_A の tile / slice の取り違え**。`--probe` |
| ピーク周波数が合わない | fs の思い込み。`adc_capture.py` が実測 fs を出すのでそれを見る |
| 振幅が 1/4 になる | 14 bit のビット寄せ |
| ピークが 2 本立つ・位置が違う | ナイキストゾーンの折返し。`--zone` |
| ノイズフロアが妙に高い | 記録が不連続になっている疑い。`make sim` と RFDC のオーバーフロー状態 |
| `/dev/usbtmc*` が無い / 開けない | SG 側。`lsusb` と `dmesg \| tail`、udev ルール（`tools/apsyn.py` の docstring） |
| board part / part がすり替わる | proj002 で入れた **part 一致検証**。RFDC はボード依存設定が多いのでここで効く |
