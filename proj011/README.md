# proj011 — FFT IP を realtime・資源優先に設定し直し、1ch のまま資源と `-1` の余裕を測り直す

日付: 2026-09-24
状態: 進行中（`make sim` SHIFT 7 通過・`make survey` 完了。ビルドはポートの照合の誤りで 1 回止まり、照合を直した。実機は未実施）

## 目的

**4ch に広げる前と、窓の切り出しの方式を選ぶ前に、「FFT 1 本にどれだけ資源を使うか」を実測で押さえる。**

proj010 は 1ch で動いたが、次の 2 つが 4ch への拡張と窓の切り出しの両方を塞いでいる:

- **DSP**: 944（22.1 %）のうち **FFT IP が 800（1 個 50 × 16）**。そのまま 4ch にすると 3776（88 %）。
  最終仕様（IF 4 本 × 1 IF あたり 2〜8 窓）で窓ごとに FFT を持つなら、さらに足りない
- **`-1` の余裕**: WNS +0.081 ns（周期 3.906 ns の 2 %）。`-2` の最悪経路は **nonrealtime を選んだために
  IP の中に生えるクロックイネーブル（CE）の大ファンアウト**（配線 97 %）だった

どちらも **IP の設定だけで手が打てる**（RTL はほぼ変えない）。この proj ではそれを試し、
FFT 1 本あたりの DSP・LUT・BRAM と、`-1` の WNS を実測で出す。その数字を持って、proj012 以降で
窓の切り出しの方式（ソフト DDC か粗い PFB か）を選ぶ。

**機能は proj010 と同じ**（ADC_B 1 本・8192 点・4096 ch × 0.5 MHz・100 ms 積分）。
proj010 の判定の道具（`make sim`・`--probe`・`--golden`・`--tone`・`--radiometer`・`--tick`）を回帰試験に使う。

## proj010 から変えるもの・変えないもの

| | proj010 | proj011 |
|---|---|---|
| `throttle_scheme` | nonrealtime | **realtime**（出力側の `m_axis_data_tready` が IP から消える） |
| `complex_mult_type` | use_mults_performance（4 乗算） | **FFT_OPT で選ぶ**（下の表） |
| `butterfly_type` | use_xtremedsp_slices | **FFT_OPT で選ぶ** |
| 上の 3 つの CONFIG | 任意（読み返しが違っても通す） | **fatal**（調べる対象なので、黙って既定値に戻られると測定が無効になる） |
| FFT IP の設定の置き場 | build.tcl の中 | **`src/fft_cfg.tcl`**（build.tcl と `tools/ip_survey.tcl` が同じものを読む） |
| spec_core の ID | 0x0010_0001 | **0x0011_01CC**（CC = FFT の設定の符号。res と perf は同名の `.bit` になるので、載っている変種を PS から読む） |
| RFDC・ギアボックス・spec_core の本体・XDC・PS 側のソフト | — | **同一** |

### 変種（`make FFT_OPT=...`）

| FFT_OPT | throttle | 乗算器 | バタフライ | ID の下位 | 出力先（-2 / -1） | 何を見るか |
|---|---|---|---|---|---|---|
| **res**（既定） | realtime | use_mults_resources（3 乗算） | use_luts | 0x07 | `build/` / `build-1-e/` | 本命。資源と `-1` の両方 |
| perf | realtime | use_mults_performance（4 乗算） | use_xtremedsp_slices | 0x01 | `build-perf/` / `build-1-e-perf/` | 乗算器が proj010 と同じ。**realtime だけの効き**を分ける |

nonrealtime の本番ビルドは proj010 そのものなので作らない。資源だけなら `make survey` が 8 通りすべてを数える。

## 手順

1. **`make sim`**（Vivado 不要）— spec_core の接続を 1 本外したので、proj010 と同じ 3 層（bit 単位・numpy・帳簿）で通ることを確かめる。
   モデル（`sim/lane_fft_model.v`）も出力側の tready を外した。**途切れたときの realtime の IP の振る舞いはモデルしていない**
2. **`make survey`**（新設）— FFT IP を 1 個ずつ OOC 合成し、8 通り（throttle × 乗算器 × バタフライ）の資源を
   `build-survey/survey.txt` に出す。**nonrealtime / performance / xtremedsp（= proj010）が DSP 50 になることを物差しの検証にする**
3. survey の数字で「本番」の予言（下の表の空欄）を書く — **ビルドの前に**
4. `make` と `make FFT_OPT=perf`（`-2`）、`make timing-check` と `make timing-check FFT_OPT=perf`（`-1`）
5. 実機: res の `.bit` で回帰試験（下の「実機」）

## 予言（測る前に書く）

### 段階 1: IP 単体（`make survey`。survey の前に書く）

FFT IP 1 個（512 点・pipelined streaming・入力 14 bit・unscaled・位相係数 18 bit）。

| 変種 | DSP / 個 | LUT | 根拠 |
|---|---|---|---|
| nrt / perf / dsp（= proj010） | **50**（実測） | — | 物差し。合わなければ survey を使わない |
| rt / perf / dsp（= perf） | **50**（変わらない） | nrt より少し減る（0〜10 %） | realtime は制御（CE）を消すだけで、演算器は変わらない |
| nrt・rt / res / dsp | 40〜46 | ほぼ同じ | 複素乗算 1 個 4 → 3 DSP。50 のうち乗算器が 16〜32 と見て 1/4 が減る |
| nrt・rt / perf / lut | 20〜35 | +1,000〜3,000 | バタフライの加減算が DSP から CARRY8 に移る |
| **rt / res / lut（= res）** | **15〜30** | **+1,000〜3,000** | 上の 2 つの和。**proj010 README の見込み「50 → 30 台」より下を予言する** |

- 読み: DSP 50 の内訳（乗算器とバタフライの比）は survey の 4 通りの差から分かる。予言が外れたら、内訳の見積もりのどちらが外れたかを書く
- BRAM（RAMB18 6 / 個）はメモリの設定を触らないので **8 通りとも同じ**と予言する

### 段階 2: 本番（`make`。survey の後・ビルドの前に書いた。2026-09-24）

survey の物差し（nrt / perf / dsp = DSP 50）が proj010 の配置配線後の実測と一致したので、survey の数字をそのまま 16 倍する。

| | proj010 実測 | res の予言 | perf の予言 | 根拠 |
|---|---|---|---|---|
| DSP48E2 | 944 | **16 × 21 ＋ 144 = 480**（11.2 %） | **16 × 50 ＋ 144 = 944**（proj010 と同じ） | 自作部分 144 は変えない。物差しが 1 個単位で一致したので**ちょうどこの数**と予言する |
| DSP（4ch 換算） | 3776（88 %） | **1920（45 %）** | 3776 | × 4 |
| lane_fft 16 個の LUT | 16 × 1695 = 27,120（survey） | **+10,300**（16 × 641） | **−2,700**（16 × −166） | survey の差。配置配線後の値は OOC と数 % 違ってよい |
| lane_fft 16 個の FF | 16 × 3640 = 58,240（survey） | **+17,200**（16 × 1075） | **−1,900**（16 × −119） | 同上 |
| BRAM | RAMB36 23 ＋ RAMB18 112 | **同じ** | **同じ** | survey で 8 通りとも 3 タイル / 個 |
| CDC（report_cdc） | Critical 0 / CDC-3 20 / CDC-15 833 | **同じ** | **同じ** | 変えたのは 256 MHz ドメインの内側だけ。**構造の指紋**（proj008 の規約） |

**4ch の DSP は res で 45 %。**残り 55 % が窓の切り出し（PFB の FIR か DDC の NCO・乗算器）に使える予算になる。
LUT・FF の増分（4ch で +41k / +69k）は XCZU48DR（LUT 425k / FF 850k）に対して 10 % 未満。

### 段階 2: タイミング（ビルドの前に書く。今書ける）

| | proj010 実測 | perf（realtime だけ）の予言 | res の予言 |
|---|---|---|---|
| WNS `-2` | +0.474 ns（最悪経路は FFT IP の nonrealtime の CE） | **+0.45〜+0.50**。最悪経路は FFT IP の CE から離れ、**ギアボックス（341 MHz 側、proj010 で +0.483）か spec_core の自作部分**に移る | perf 以下（LUT の加算器は DSP より遅い）。ただし正 |
| WNS `-1` | **+0.081 ns** | **+0.15〜+0.30** | perf より小さいが **+0.081 より大きい** |
| 最悪経路（`-1`） | —（記録なし） | FFT IP の外 | FFT IP の中なら LUT のバタフライ（CARRY8 の連鎖） |

- 外れ方の読み: perf の WNS が proj010 と変わらず、最悪経路が FFT IP の中に残る → realtime でも CE（か同等の大ファンアウト）が残っている。
  `aclken` を有効にしていないことと、IP の中の該当の網を確かめる
- `-1` のビルドは board_part を使わない別の配置配線なので、`-2` と差を取って意味づけしない（VERSIONS.md）。**比べるのは `-1` どうし**（proj010 +0.081）

### 実機（res の `.bit`）

| 判定 | 内容 | 予言 |
|---|---|---|
| 0 `--probe` | ID・フレームの速さ・FIN − FOUT | ID = **0x0011_0107**（res）。500,000 フレーム/s、FIN − FOUT の区間が一定、FLAGS 0 — **proj010 と同じ** |
| 2 `--golden` | 同じフレームを numpy と照合 | SNAP_F = DUMP_F0。差の平均 **9.5 ± 1 LSB**（proj010 は 9.55）。3 乗算でも丸めの位置は同じと見る。**大きく変われば IP 内部の丸めが変わった**ので `tools/ipround_model.py` を直す |
| 1 `--tone` | 3000.0 MHz → ch 2192 | proj010 と 0.01 dB 以内で同じ振幅 |
| 3 `--radiometer` | 10 ms・100 ms | 共通の利得を除いた比が 1 ± 0.05（proj010: 0.984 / 1.011） |
| realtime の危険 | 入力に隙間があるとフレームの境界がずれる | **起動直後を含めて FLAGS[4]（隙間）・[6]（data_in_channel_halt）が立たない。**`--ndump` の帳簿で DUMP_F0 の間隔 = DUMP_K × N_ACC。1 時間の `--record` で flags_or = 0 |

**realtime の危険には陽性対照が無い**（入力に隙間を作る手段を RTL に持っていない）。FLAGS[4] は proj010 から在るが、
実機で一度も立ったことがないので、**見張りが動くことは sim でしか確かめていない**。立たないことは「隙間が無い」と
「見張りが壊れている」を区別しない。必要になったら、隙間を注入するテスト用の入力（CTRL の 1 bit で valid を 1 クロック落とす）を足す。

## やったこと

- proj010 の追跡されているファイルを複製（`git ls-files proj010`）。`proj010` の名前を proj011 に置き換え
- `src/fft_cfg.tcl`（新設）: FFT IP の設定・変種の対応（res / perf）・ID の符号
- `build.tcl`: FFT IP の設定を `fft_cfg.tcl` から取る。`m_axis_data_tready` を want_ports から外し、**在ってはいけないポートとして照合**。
  spec_core に `CONFIG.FFT_CFG` を与えて読み返す。配置配線後に lane_fft 1 個ぶん・16 個の合計・それ以外の DSP を出す（`lane_fft_util.rpt`）
- `src/spec_core.v`: `m_axis_data_tready` の接続を外した。parameter `FFT_CFG`、ID = {16'h0011, 8'h01, FFT_CFG}
- `sim/lane_fft_model.v`: 出力側の tready を外した / `sim/check.py`: ID の期待値
- `tools/ip_survey.tcl`（新設）・`make survey`
- `Makefile`: `FFT_OPT`（res / perf）と出力先の振り分け
- `pynq/spectrometer.py`: BITFILE・ID の照合（上位 24 bit）・載っている変種の表示と `--record` の info.json への記録

## 結果

### IP 単体（`make survey`、2026-09-24、`-2`、OOC 合成後）

| 名前 | throttle | 乗算器 | バタフライ | DSP | LUT | FF | BRAM | CARRY8 |
|---|---|---|---|---|---|---|---|---|
| nrt_perf_dsp（= proj010） | nonrealtime | performance | xtremedsp | **50** | 1695 | 3640 | 3 | 86 |
| nrt_perf_lut | nonrealtime | performance | luts | 28 | 2246 | 3997 | 3 | 184 |
| nrt_res_dsp | nonrealtime | resources | xtremedsp | 43 | 1950 | 4477 | 3 | 113 |
| nrt_res_lut | nonrealtime | resources | luts | 21 | 2501 | 4834 | 3 | 211 |
| rt_perf_dsp（= perf） | realtime | performance | xtremedsp | **50** | 1529 | 3521 | 3 | 86 |
| rt_perf_lut | realtime | performance | luts | 28 | 2081 | 3878 | 3 | 184 |
| rt_res_dsp | realtime | resources | xtremedsp | 43 | 1784 | 4358 | 3 | 113 |
| **rt_res_lut（= res）** | realtime | resources | luts | **21** | 2336 | 4715 | 3 | 211 |

**物差しは通った**（nrt_perf_dsp = 50 = proj010 の配置配線後の実測）。

| 段階 1 の予言 | 結果 | |
|---|---|---|
| realtime で DSP は変わらない | 50 → 50（4 組とも同じ） | **当たり** |
| realtime で LUT が 0〜10 % 減る | −166（−9.8 %）、FF −119（−3 %）。4 組とも同じ差 | **当たり**（範囲の端） |
| 3 乗算で DSP 40〜46 | 43 | **当たり** |
| 3 乗算で LUT ほぼ同じ | **LUT +255（+15 %）・FF +837（+23 %）・CARRY8 +27** | **外れ**（3 乗算の前置加算器の段と遅延合わせのレジスタを見ていなかった） |
| LUT バタフライで DSP 20〜35 | 28 | **当たり** |
| LUT バタフライで LUT +1,000〜3,000 | **+551**、FF +357、CARRY8 +98 | **外れ（小さく）** |
| res で DSP 15〜30 | **21** | **当たり** |
| BRAM は 8 通りとも同じ | 3 タイル（RAMB18 6） | **当たり** |

- **DSP 50 の内訳が分かった: 複素乗算 7 個 × 4 = 28 ＋ バタフライ 22。**3 乗算で 7 減り（7 個 × 1）、LUT バタフライで 22 減る。
  2 つの効きは**ちょうど足し算**（50 − 7 − 22 = 21）で、throttle とも独立（realtime の差は 4 組とも LUT −166 / FF −119）
- 512 点 = 9 段で複素乗算が 7 個なのは、最後の 2 段の係数が自明（±1・±j）で乗算器が要らないためと読む
- 外れた 2 つはどちらも LUT・FF の見積もりで、DSP は全部当たった。**資源の予言は「消える側」は当たり、「増える側」を外す**

### ビルド（1 回目、2026-09-24）— ポートの照合の誤りで止まった

`build.tcl` の「在ってはいけないポート」の照合が、realtime の IP に `m_axis_data_tready` が**在る**と判定して止まった。

- **IP は realtime になっていた。**照合が読み違えていた: `synth/lane_fft.vhd` には entity の宣言のほかに、
  IP コア（xfft_v9_1_x）の **component 宣言**が入っていて、そちらは設定に依らず全部のポート
  （`aclken`・`m_axis_data_tready`・`m_axis_status_*`・`event_*_channel_halt` …）を持つ。照合はファイル全体を読んでいた
- 裏づけ: エラーに出た一覧は RTL の 17 本が先に並び（entity）、その後に上の 8 本が component の宣言順で続いた。
  throttle_scheme の読み返しは realtime で通っていた
- **proj010 から在る「在るか」の照合にも同じ穴があった。**entity に無いポートでも component 側で通ってしまう。
  「在ってはいけない」側を足して初めて、照合そのものが嘘をついていたと分かった（**外れた予言が道具の誤りを出した**）
- 修正: entity lane_fft の宣言の中だけを読む。見出しに「entity の宣言から N 本」を出す（17 本が期待値）

### シミュレーション（2026-09-24、SHIFT 7）

**全部通過。数字は proj010 と同じ**: t1 の B は差/許容の最大 0.66・平均の差 0.476 LSB、A は 3 試験とも不一致 0 ch、ID = 0x0011_0100（sim の既定 FFT_CFG = 0）。
spec_core の変更は IP との接続 1 本と ID だけなので、同じ数字が出るのが予言どおり。SHIFT 4 は未実施。

survey・ビルド・実機は未実施。

## 結論・次にやること

- [x] `make sim` SHIFT 7（proj010 と同じ数字で通過）
- [ ] `make sim SIM_SHIFT=4`
- [x] `make survey` → 段階 1 の予言と突き合わせ（DSP は全部当たり、LUT・FF の 2 つが外れ）、段階 2 の空欄を埋めた
- [x] ビルド 1 回目: ポートの照合の誤り（component 宣言を読んでいた）で停止 → entity だけを読むよう修正
- [ ] `make` / `make FFT_OPT=perf` / `make timing-check` / `make timing-check FFT_OPT=perf`
- [ ] 実機 判定 0・2・1・3、realtime の危険
- [ ] 4ch・窓の切り出しの資源の見積もりを、この proj の数字で書き直す

## 再現手順

```bash
make sim                              # Vivado 不要。SIM_SHIFT=4 で飽和の数え方も見る
make survey                           # FFT IP 単体 × 8 通りの資源 → build-survey/survey.txt
make                                  # res（既定）: build/proj011.bit / .hwh
make FFT_OPT=perf                     # perf: build-perf/
make timing-check                     # res の -1: build-1-e/
make timing-check FFT_OPT=perf        # perf の -1: build-1-e-perf/
make prog                             # JTAG（OUTDIR=build-perf で perf を書く）
```

ボード（`pynq/` と `proj011.bit` / `.hwh` を同じディレクトリに置く）: 使い方は proj010 と同じ。起動時に
`spec_core: ID = 00110107 / FFT_CFG 0x07 = res（…）` と出るので、**どちらの変種が載っているかを毎回ここで確かめる。**

```bash
sudo python3 spectrometer.py --clkin 0 --probe
sudo python3 spectrometer.py --clkin 0 --golden
sudo python3 spectrometer.py --clkin 0 --tone 3000.0 --sg-dbm -20 --atten-db 0
sudo python3 spectrometer.py --clkin 0 --radiometer --nacc 5000,50000 --ndump 30
```

`pynq/extref.py`・`clocks/`・`tools/`（survey 以外）は proj010 からそのまま持ってきた（自己完結のため）。

環境は [`../VERSIONS.md`](../VERSIONS.md)、詰まったときは
[`../proj001/docs/runbook.md`](../proj001/docs/runbook.md)。
