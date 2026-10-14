# proj023 — SAM45-Wide の RTL（PFB T = 4 ＋ 16 レーンの全帯域 FFT 8192 / 16384 / 32768 点 ＋ SLICE、インターフェース v2 の上で）

日付: 2026-10-14（起こし）
状態: 進行中（手順 0・1 済み、次は手順 2）

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

## 決めたこと（手順 1、2026-10-14）

| # | 件 | 決定 | 理由・見送った案 |
|---|---|---|---|
| D-1 | spec_core の作り替え | **`src/common/wide_core.v` を新しく作る**（spec_core.v を複製して作り替える。spec_core.v は残し、sim-spec-all を回帰に残す）。段: 入口（ギアボックスの出口 16 サンプル / ビート）→ **PFB（新規 `wide_pfb.v`、T = 4、履歴は URAM）** → レーン FFT × 16（IP、入力 15 bit・unscaled・**実行時の長さ 512 / 1024 / 2048**、XK_INDEX = k1）→ ひねり係数（1 本の 32768 点の表を 1・2・4 個おき）＋ cmul → dft16（今のまま、k2 = 0..7）→ SHIFT・飽和 → 電力 → **積分器は切り出しだけ**（8 銀行 × 1024 × 64 bit × 2 面、流れ 2 本ぶん）。帳簿（F0・DUMP_T・SEQ・REC）は spec_core の形を流れ 2 本に。TP は spec_core と同じく入口の Σx² | spec_core の sim（手順 0）が今の形で通った。spec_core を直接書き換えると、proj011 以来の sim の回帰を失う |
| D-2 | フレームの頭（INTERFACE 8. の 8） | **(a) 揃える。フレームの頭 = WRST_T（＋ RTL で決まる一定の遅れ）**。WRST は FULL のような「取り込むだけ」ではなく、**PFB と 16 個の IP を作り直し、入力の口を WRST_T ＋ K_OPEN のビートで開ける**（K_OPEN は IP が受けられるようになるまでの一定の数）。specd は WRST を T の tint の倍数で 4 コア一斉に置くので（INTERFACE 5.1、s45acq の start）、フレームの頭は **T ≡ 一定（mod 2048 ビート）** に乗る。F0 は wspec_core と同じく格子に寄せる: M = G / FB（FB = 512・1024・2048 ビート → M = 1024・512・256）、F0 = (⌊fin / M⌋ + 2)·M。残り r は RTL の定数になり、sim で出して PS の表（(BIT_KIND, BIT_REV) ごと）に置く。**ハードのリセット後、最初の WRST までのフレームは位相が決まらない**（RUN は受けるが FLAGS に「WRST 前」を立てる） | (b) ずれを読んで吸う案は、PS の表が Overlay ごとの実測になり、proj021 の V2-f の r（742・517・948）と同じ不定さが残る。モードの切り替え（FFT_N）も「次の WRST で効く」（INTERFACE 2.4）ので、作り直しは WRST に 1 つにまとまる |
| D-3 | sim の golden | **今の 3 層のまま、IP の前後で bit 単位**: (A1) PFB の出口（= IP の入口）を記録し、`wide_model.py` の PFB の整数模型と bit 単位 / (A2) IP の出口（行動模型 `lane_fft_model.v` を長さ切り替えに広げる）を記録し、ひねり係数・dft16・丸め・電力・積分・切り出しの整数模型と bit 単位 / (B) 刺激（stim）から numpy の浮動小数点の PFB ＋ rfft と振幅の許容 / (C) 帳簿。**IP の C モデルには合わせない** | IP の中身は自作でないので、IP の前後で切れば自作部分は全部 bit 単位で見られる（spec_core の A 層の流儀）。IP 自身の丸めは実機（H-1・`--golden` の振幅）で見る。B の刺激は 4N サンプル要るので、スナップショットではなく stim から作る |
| D-4 | コアの中身 | **SLICE × 2（s = 0, 1）＋ RAW（s = 2）。DDC の窓（win_core・ddc_core・wspec_core・pfb_core）は外す** | 2026-10-14 に西村さんと確認。BITS.md の Wide は窓を持たない。RAW は DSP を使わず、F-2 の較正をそのまま使える |
| D-5 | ID | **BIT_KIND 1・BIT_REV 1・PROJ 0x0023_0100**。手順 2 で RTL を替えるときに、`s45_core`・`time_core`・`s45_ring` の既定値・build.tcl・sim の期待値・timebase の CAL の鍵を一度に | 半端に変えると sim と PS の照合が食い違う |
| **D-6** | **モードの切り替えの単位**（手順 1 で出た件） | **ADC ごとに独立**（2026-10-14 に西村さんが決めた）。FFT_N はコアごと（INTERFACE 2.4 のまま、変更なし）。**係数とひねり係数は 2 組を置き、1 組を 2 ポートで 2 ADC に配る**（組 0 = ADC_A・B、組 1 = ADC_C・D。URAM・BRAM の A / B ポートに ADC を 1 つずつ。番地は ADC ごとに独立） | 4 ADC で 1 組（proj022 の推し A）は、同じ番地を 4 ADC が同時に読めるときだけ成り立つ。モードが ADC ごとなら番地が ADC ごとに違う。2 ポートで 2 ADC に配れば ADC ごとに 1 組（URAM 64・BRAM +90）より軽い |

### D-6 で見積もりがどう動くか（proj022 の E-1 の推し A から）

| | 4 ADC で 1 組（推し A） | **2 組 × 2 ポート（D-6）** | ADC ごとに 1 組 |
|---|---|---|---|
| PFB の係数（URAM、レーンごと 1 個 = 3 つの長さ × 4 タップ） | 16 | **32** | 64 |
| ひねり係数（BRAM、15 × 2） | 30 | **60** | 120 |
| PFB の履歴（URAM、10 / ADC） | 40 | 40 | 40 |
| **URAM 合計** | 56（70 %） | **72（90 %）** | 104（130 %、入らない） |
| **BRAM 合計** | 688（64 %） | **718（66 %）** | 778（72 %） |
| ずれを吸う遅延（LUT） | 要らない（D-2） | 要らない（ポートごとに番地を作る） | 要らない |

- **URAM 90 % は目安（≦ 90 %）の縁**。逃げ道: ADC 1 つぶんの PFB の履歴を BRAM に置けば URAM 62（78 %）・BRAM 758（70 %）。どちらにするかは手順 3 のビルドで配置を見て決める（今は URAM のまま）
- LUT は proj022 の 70.1 %（S-1 の実測で引き直した値）から大きくは動かない見込み（番地の生成が 2 → 4 本）

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

手順 2（RTL と単体の sim）の予言（2026-10-14、書く前）:
- **wide_pfb**: `wide_model.py` の PFB の整数模型と bit 単位で一致する（proj020 の pfb_core が win_fixed.py と bit 単位で一致した型）。最初の 3 フレーム（WRST の直後、履歴が埋まる前）は模型と同じ「0 の履歴」で一致する
- **長さ切り替え**: IP の設定の口に FFT_N を WRST のときだけ書けば、切り替えの直後の最初のフレームから正しい長さで出る（WRST で IP を作り直すので、走っている途中の設定の切り替えは使わない）
- **ひねり係数の 1・2・4 個おき**: W_N'^(pk1) = W_32768^(pk1·32768/N') は厳密なので、表を長さごとに作った場合と **bit 単位で同じ**（量子化した値の部分集合）
- **フレームの頭**: WRST_T からフレームの頭までの遅れ（K_OPEN ＋ 段の深さ）は 3 つの長さで同じで、r = DUMP_T − m·BASE は長さに依らない 1 つの定数になる（PFB の重心のずれ 1.5·L は 5.2 の D_eff に入れる）
- **一番危ないところ**: 2 組 × 2 ポートの共有で、ポート A / B の読みの遅れが食い違い、ADC_B・D だけ係数が 1 ビートずれる。sim で 4 ADC を同時に回し、4 本とも模型と bit 単位で比べる（陽性対照: ポート B の番地を 1 ずらす）

## 手順

0. 複製と名前の付け替え。spec_core の sim が土台で通るか（2026-10-14 済み、全部通過）
1. D-1〜D-6 を決める（2026-10-14 済み、上の「決めたこと」）
2. wide_core の RTL と単体の sim（S-W1〜S-W3）。ID を D-5 に ← **次はここ**。中の順:
   2a. `model/wide_model.py` から sim の模型（PFB の整数模型・鎖の整数模型・stim）を切り出す（`sim/check_wide.py`）
   2b. `wide_pfb.v`（PFB、係数は 2 組 × 2 ポートの外の ROM から）＋ 単体の sim（A1）
   2c. `lane_fft_model.v` を長さ切り替えに広げ、`wide_core.v`（ひねり係数・dft16・切り出しの積分器・帳簿）＋ 単体の sim（A2・B・C）
   2d. フレームの頭（D-2）と WRST での作り直し・4 ADC の共有（S-W3、陽性対照つき）
3. build.tcl（窓を外し、wide_core × 4 ＋ RAW）・S-W4・ビルド（B-1）
4. 実機（H-1〜H-4）

## やったこと

- 2026-10-14: `git archive proj021-m0 proj021` から複製した。持ち込まなかったもの: proj021 の README・`docs/` の図（`block_design.py` だけ残した。手順 3 で描き直す）・`runs/`・`pynq/` の測定の結果（png・npz・jsonl・`lin_*`・`resp_*`・`r2*`・`rb*`・`v2*`・`ps2` の json）。足したもの: proj022 の `model/wide_model.py`・`tools/estimate.py`
- 2026-10-14: 手順 1。spec_core（フレームの頭は入力の口が開いた時点で決まる）・wspec_core（F0 を格子に寄せる、proj017）・specd の始まり（WRST を格子で一斉）を読み、D-1〜D-5 を決めた。モードを ADC ごとにすると係数の共有が崩れることが分かり、D-6 を西村さんに確認した（ADC ごとに独立 → 2 組 × 2 ポート）
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

- [x] 手順 1: D-1〜D-6（上）
- [ ] 手順 2a: sim の模型を `wide_model.py` から切り出す

## 公開について

study-rfsoc は公開リポジトリ。commit・push の前に、公開前のスキャン（リポジトリ外の手順書）の全項目を機械的に行う。
**コミットメッセージに `Claude-Session:` の行や URL を入れない**（`Co-Authored-By` の行は可）。

## 再現手順

```bash
make sim-spec-all   # 手順 0: spec_core の sim（変種を同時に）。成否は build-sim-logs/*.log の「結果: 全部通過」
```

環境は [`../VERSIONS.md`](../VERSIONS.md)、詰まったときは [`../proj001/docs/runbook.md`](../proj001/docs/runbook.md)。
