# proj023 — SAM45-Wide の RTL（PFB T = 4 ＋ 16 レーンの全帯域 FFT 8192 / 16384 / 32768 点 ＋ SLICE、インターフェース v2 の上で）

日付: 2026-10-14（起こし）
状態: 進行中（手順 0 済み、次は手順 1）

## 目的

**SAM45-Wide（[BITS.md](../BITS.md) の 1 本目の行、BIT_KIND 1）の bit を作る。**
proj022 で模型と資源の見積もりまで設計し切ったものを RTL にし、proj021 で確定したインターフェース v2（流れとコア・レコードのリング・specd）の上に載せる。

- 4 ADC × 1 コア。コアごとに全帯域の FFT（PFB T = 4 → 16 レーン × レーン FFT 512 / 1024 / 2048 点 → ひねり係数 → 16 点 DFT）を 1 本
- 流れは SLICE × 2（s = 0, 1）。全帯域 2048 MHz は 8192 点の s0 = 0 の 4096 ch（流れ 1 は空）、1 GHz・512 MHz は 16384 / 32768 点の連続した 4096 ch を 2 本（INTERFACE.md 2.1・2.5）
- モードは bit の中のレジスタ（コアの FFT_N、次の WRST で効く）。dt = 40.96 ms（PL のダンプは 10.24 ms、specd で束ねる）
- **`-1` で閉じること**（proj022 の見積もりは LUT 70.1 % が律速）

土台: study-rfsoc のタグ **`proj021-m0`**（proj021 の最終形、SAM45-Fine BIT_REV 3）の `proj021/` の追跡ファイル。proj022 の `model/wide_model.py`（sim の golden の元）と `tools/estimate.py` を足した。

経緯: 2026-10-14 の相談（proj022 を閉じ、proj021 と並行して起こした）。設計の出発点は [proj022 の結論](../proj022/README.md#結論次にやること) と「RTL の proj への申し送り」。

## proj021・proj022 との関係

| | 扱い |
|---|---|
| v2 の共通部（s45_core・s45_ring・time_core・rec_fr・rec_arb・specd・s45proto） | `proj021-m0` のまま使う。**変えるときは理由を README に書く**（製品リポジトリへの移植の土台と同じものなので） |
| INTERFACE.md の SLICE の番地（FFT_N 0x80・2.5 の SLICE の設定・レコードの語 7） | 案のまま入っている。**この proj の RTL で確定させる**。変えるなら INTERFACE.md を直す（proj021 の会話が閉じていればこの会話で） |
| INTERFACE 8. の 8（フレームの頭を時刻の格子に揃える） | **この proj の仕事**（proj021 2-5 で Fine から FULL が外れ、Wide の側に戻った） |
| proj021 の残り（B3・C・D3） | proj021 の会話。ボード・Vivado サーバの取り合いは小さい |

## 最初に決めること（手順 1。RTL を書く前）

| # | 件 | 案 | 決め手 |
|---|---|---|---|
| D-1 | spec_core をどう作り替えるか | `src/common/spec_core.v`（proj021-m0 に残っている、8192 点・矩形の窓・FULL）を土台に、前に PFB、レーン FFT を実行時の長さ切り替えに、積分器を SLICE（切り出しだけ）に。名前は `wide_core.v` にして spec_core は残す | 手順 0 で spec_core の sim が今の形で通ること |
| D-2 | フレームの頭の揃え方（INTERFACE 8. の 8） | (a) F0 とフレームの頭のビートを 4 ADC で同じ T に揃える（係数とひねり係数の 4 ADC 共有に遅延が要らない）/ (b) 揃えず、ADC ごとのずれ（ビート）をレジスタで読み遅延で吸う | proj021 V2-f の r が Overlay・SRST ごとに変わる（742・517・948）の原因。(a) が取れるなら (a) |
| D-3 | sim の golden | (a) FFT IP の出口の丸めを IP の C モデルに合わせ、`wide_model.py` の `fixed_chain` と bit 単位 / (b) 許容の幅で比べる | 今の spec_core の sim（lane_fft_model.v と check.py）の流儀。bit 単位が取れるなら (a) |
| D-4 | コアの中身の流れ | SLICE × 2（s = 0, 1）＋ **RAW（s = 2）を残す**（F-2 の較正と SNAP の道に使う）。DDC の窓（win_core・ddc_core・wspec_core）は外す | BITS.md の Wide は窓を持たない。RAW は proj021 2-5 で DSP 0・F-2 に要る |
| D-5 | ID | BIT_KIND 1・BIT_REV 1・PROJ 0x0023_0100（`s45_core`・`time_core`・`s45_ring` の既定値・build.tcl・sim の期待値・timebase の CAL の鍵を一度に） | **手順 0 では proj021-m0 の値（BIT_KIND 2・BIT_REV 3・PROJ 0x0021_0200）のまま**。RTL を替える手順 2 で一度に変える（半端に変えると sim と PS の照合が食い違う） |

## 判定（案）

| | 中身 | 合格 |
|---|---|---|
| **S-W1 鎖** | wide_core の単体の sim。3 つの長さ × SHIFT（飽和あり・なし）で、模型（D-3）と比べる | D-3 で決めた基準。陽性対照（例: ひねり係数の番地を 1 ずらす）で落ちる |
| **S-W2 SLICE** | 開始 ch s0 を端（0・N/2 − 4096）と途中で、全 ch の模型の部分と一致。FFT_N の切り替えが WRST で効き、コアの SLICE の流れが全部 WRST される | 一致・陽性対照 |
| **S-W3 時刻** | フレームの頭と F0 が D-2 の約束どおり（4 ADC・3 つの長さ）。格子 2.048 ms がフレームの整数倍 | 約束どおり・陽性対照 |
| **S-W4 v2 の回帰** | proj021 の sim（regmap・ring・t4adc・tsys の該当分）が D-5 の ID で通る | 全部通過 |
| **B-1 ビルド** | `-1` で WNS ≧ 0（戦略は既定 → Performance_Explore → 配線後の phys_opt の順）。資源を E-1 と並べる | 閉じる。外れた行は理由を書く |
| **H-1 ch の応答** | 実機で 3 つの長さの半 ch・−3 dB 幅・ENBW（proj020 の P-5 の型、s45resp） | proj022 M-2 の値（半 ch −3.00 dB・ENBW 1.010）と ±0.02 dB |
| **H-2 ch → IF** | SG の絶対周波数で、3 モードの (s0 + i)·fs / N が合う | ±0.5 ch 以内 |
| **H-3 v2 の判定** | INTERFACE 9. の V2-a・V2-b（40.96 ms）・V2-c・V2-e・V2-f を Wide で | proj021 と同じ基準 |
| **H-4 モードの切り替え** | 運転中に FFT_N を 3 つの間で往復。レコードだけで ch → IF が決まり、欠け・kgap が出ない | 欠け 0 |

## 予言（走らせる前に書く）

- 手順 0: spec_core の sim（`make sim-spec-all`）は proj021-m0 のまま通る（2-5 で bit から外れたが、ファイルと試験台は変わっていない）→ **当たった**

（手順 1 で D-1〜D-5 を決めたら、ここに手順 2 以降の予言を足す）

## 手順

0. 複製と名前の付け替え。spec_core の sim が土台で通るか（2026-10-14 済み、全部通過）
1. D-1〜D-5 を決める（README） ← **次はここ**
2. wide_core の RTL と単体の sim（S-W1〜S-W3）。ID を D-5 に
3. build.tcl（窓を外し、wide_core × 4 ＋ RAW）・S-W4・ビルド（B-1）
4. 実機（H-1〜H-4）

## やったこと

- 2026-10-14: `git archive proj021-m0 proj021` から複製した。持ち込まなかったもの: proj021 の README・`docs/` の図（`block_design.py` だけ残した。手順 3 で描き直す）・`runs/`・`pynq/` の測定の結果（png・npz・jsonl・`lin_*`・`resp_*`・`r2*`・`rb*`・`v2*`・`ps2` の json）。足したもの: proj022 の `model/wide_model.py`・`tools/estimate.py`
- 2026-10-14: 名前の付け替えは「動く名前」だけ: build.tcl の `set proj`・Makefile の配線後の phys_opt の hwh のコピー・`tools/postroute_physopt.tcl` の bit の名前・`pynq/plring.py` と `pynq/spectrometer.py` の既定の bit。コメントの proj021 は経緯なので残した。ID（PROJ・BIT_KIND・BIT_REV）は D-5 のとおり手順 2 で

## 結果

### 手順 0: spec_core の sim（`make sim-spec-all`、2026-10-14）

**全部通過（予言どおり）**。9 本とも「結果: 全部通過」、陽性対照（7-5-0 の TLAST の検査ずらし・7-0-2 の見張りなし・tp の posctl / ovrpc）は落ちるべきところで落ちた。

| 変種 | 結果 |
|---|---|
| 7-0-0（SHIFT 7、飽和なし） | 通過。A: 模型とダンプが **bit 単位で一致**（不一致 0 / 4096 ch）・B: numpy の 8192 点 FFT と振幅で一致（差/許容の最大 0.69）・TP のパーセバル 1.000005 |
| 4-0-0（強い線が飽和）・7-0-1（起動の直後の途切れ） | 通過 |
| 7-5-0・7-0-2（陽性・陰性対照） | 通過（落ちるべきところで落ちた） |
| gb・tp・tp-posctl・tp-ovrpc | 通過 |

- 走らせた場所: **Vivado サーバではなく、作業用のクラウドの環境**（Icarus Verilog 12.0・numpy 2.5.3・2 コアで 9 本並べて ≒ 17 分）。Vivado サーバの版で回し直す必要は、RTL を変える手順 2 で `make sim-all` を回すときに兼ねる
- D-3 の材料: 今の spec_core の sim は、FFT IP の代わりの `sim/lane_fft_model.v` で **模型と bit 単位**（A）、numpy の浮動小数点とは振幅の許容（B）の 2 層で比べている。長さ切り替えの付いたレーン FFT でも同じ 2 層が取れるかが D-3 の中身

## 結論・次にやること

- [ ] 手順 1: D-1〜D-5

## 公開について

study-rfsoc は公開リポジトリ。commit・push の前に、公開前のスキャン（リポジトリ外の手順書）の全項目を機械的に行う。
**コミットメッセージに `Claude-Session:` の行や URL を入れない**（`Co-Authored-By` の行は可）。

## 再現手順

```bash
make sim-spec-all   # 手順 0: spec_core の sim（変種を同時に）。成否は build-sim-logs/*.log の「結果: 全部通過」
```

環境は [`../VERSIONS.md`](../VERSIONS.md)、詰まったときは [`../proj001/docs/runbook.md`](../proj001/docs/runbook.md)。
