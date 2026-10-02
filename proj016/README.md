# proj016 — 時刻ラベル（1PPS）・設定番号・健全性フラグを分光計に入れる（ADC 1 本）

日付: 2026-10-02
状態: **進行中**（RTL・sim まで完了。ビルド・実機は未実施）

## 目的

**45m に載せたときに科学観測品質を出すための「細かな機能」を、分光の中身を変えずに足す。**

- **1PPS による時刻ラベル**: 256 MHz（DSP ドメイン）の 64 bit ビートカウンタ（1 s = 256,000,000 ビートちょうど）と PPS のスタンプを置き直し、
  **予約したビートで全部のコア（窓 4・total power・全帯域）を同時に始め**、**ダンプごとに「最初のフレームが入ったビート」を貼る**。
  PS の `timebase.py` で UTC に換算する（要求 100 µs、proj008 で決めた値）
- **設定番号（CFG_ID）**: 設定は RUN の時点で取り込み、RUN の間に書いても次の RUN まで効かない（SHIFT を含む）。ダンプに CFG_ID を貼る
- **健全性フラグ**: ダンプごとに 1 語（PPS の欠落・間隔の異常・グリッチ・原点の喪失・ADC の振り切れ・入力の途切れ・帳簿の食い違い）

proj007 / proj008 の時刻層は fs = 1228.8 MSPS（153.6 MHz・8 サンプル / ビート）のもので、proj009 で fs を 4096 MSPS にしてから載っていない。

土台は proj015（rev3 = ID 0x0015_0300）。`git ls-files proj015` の追跡ファイルを複製した。

## 着手の前に決めたこと（2026-10-02）

| | 決定 | 読み |
|---|---|---|
| 使う ADC | **1 本（ADC_A）**。窓 4・total power・全帯域 1 本は残す | 機能の整備に注力する。足すのはカウンタ・比較・フラグで DSP を使わないので、資源が入るかは窓の構成で決まる。窓の構成は次の proj で変わる（16 窓で「入るか」を確かめてもすぐ古くなる）。**ADC をまたいだ開始の揃いだけは 1 本では測れない**ので、RTL は ADC の数に依らない形で書き、窓の構成の proj で 4 ADC にするときの合否に「4 ADC が同じビートで始まる」を入れる |
| 窓の構成 | proj015 のまま触らない（別の proj） | |
| ダンプの区切り | **秒の格子に揃えない。毎回同じ N フレーム**、各ダンプに厳密な開始のビートを貼る | 1 秒が整数個のフレームになるのは 128 MHz 以上の幅だけ（フレーム 4096/W µs、1 s / 16 µs = 62500 = 2²·5⁶）。格子に揃えると狭い幅でダンプの長さが 1 フレームぶん揺れる（2 MHz・100 ms で最大 2.05 %）。後段の処理を増やさない方を取る。OTF ではどちらでも時刻で補間する |
| 開始 | **予約したビート（START_AT）で、ARM しておいたコアが同じクロックに RUN を受ける** | 今は PS の書き込みの順で 1 本 10 µs ずつずれる。START_AT は PPS のスタンプ ＋ 整数秒に置ける。窓の WRST も同じ発火で予約できる（フレームの格子の位相を秒に揃えたいとき） |
| 設定番号 | **案 1（影のレジスタと CFG_ID）**。観測の途中で設定を変えない運用なので、**設定は RUN の時点で取り込む**（RUN の間の書き込みは次の RUN まで効かない） | 2026-10-02 の相談では「ダンプの境目で入れ替える」と言ったが、途中で変えない運用ならダンプの境目でなく RUN で取り込めば足り、構造が単純になる。周波数を RUN のまま変える作り（案 3）・予約の適用（案 2）は入れない |
| 時刻の物差し | **ビートは「DSP のクロックの数」**（入力の valid の数ではない） | DSP のクロックは clk_adc2（fs/16）から MMCM で作るので 10 MHz の基準に乗る。入力の途切れ（起動の直後だけ）はクロックとサンプルの対応を一度だけずらす。途切れを健全性フラグに出す |

## 着手してから決めること

- 時刻のバスの段数（time_core → 各コア）。**段数のぶんを time_core の側で先に足して出し、コアの中のビートが time_core のビートと一致する**ようにする（sim で確かめる）
- 窓の「最初の z が入ったビート」から ADC のサンプルの時刻への定数 D(NS)（PFB・DDC の群遅延と経路の遅れ）。sim のインパルスで出し、実機で PPS を ADC に入れて確かめる
- PPS の間隔の許容（同期器の量子化で ±1 ビートは正常）

## 判定

（sim）

- S-T1: time_core 単体 — カウンタ・PPS のスタンプ・間隔・グリッチ・欠落・予約発火（`start_at` ちょうど）・遅すぎ / 遠すぎの拒否・原点の喪失
- S-T2: ダンプのスタンプ — ダンプ k の開始のビート = ダンプ 0 の開始 ＋ k·N·L（L = 窓のフレーム長、4096·2^(NS−1) クロック。全帯域 512）。帳簿の食い違い（H_OPEN / H_LOST）0。陽性対照（わざとずらす）で落ちること
- S-T3: 同時開始 — ARM した 4 窓・TP・全帯域が同じクロックに RUN を受ける
- S-T4: 設定番号 — RUN の間に SHIFT・N_ACC・CFG_ID を書き換えても、その RUN のダンプは全部 RUN の時点の値（陽性対照: 取り込みを外すと混ざる）
- 既存の sim（proj015 の sim-all）が全部通過したまま

（実機）

- T-0: ID・ビルドの指紋、PPS の間隔 256,000,000 ± 1 を 120 s
- T-1: 4 窓・TP・全帯域の同時開始と、ダンプの開始のビートの連続（30 分）
- T-2: **閉ループ**: 1PPS を ADC_A にも入れ、PPS の縁が TP の 1 ms の区切り・窓のスナップショットの予言した位置に出ること（proj008 の閉ループの型）。D(NS) を確かめる
- T-3: 健全性フラグの陽性対照: PPS を抜く → 欠落、10 MHz を内蔵の水晶に → 間隔の異常（proj007 の対照）、SG を上げる → 振り切れ、Overlay を読み直す → 原点の喪失
- T-4: 設定番号: RUN の間に SHIFT を書いても、ダンプの値が変わらないこと
- T-5: `-1` で閉じる（WNS ≧ 0）

## やったこと

### RTL（2026-10-02）

| ファイル | 中身 |
|---|---|
| `src/time_core.v`（新） | 64 bit のビートカウンタ T（256 MHz、1 s = 256,000,000）、PPS の 2 系統（TRIG・COMP）のスタンプ・間隔・数・グリッチ・欠落、予約発火（START_AT、遅すぎ / 遠すぎの拒否・取り消し）、ANCHORED、EPOCH（ctrl_aclk 側で数え gray で渡す）、健全性の素 ev_out[3:0]。AXI4-Lite は DSP ドメイン |
| `src/dstamp.v`（新） | ダンプごとの開始のビート（DUMP_T）と健全性の語（DUMP_H）。入力側で区切りを数え（RUN の fin + 2 から N フレームごと）、輪（8 個）に置いて commit で渡す。帳簿の食い違い（H_OPEN・H_LOST）も語に出す |
| `src/adc_ev.v`（新） | 入力の振り切れ（\|x\| ≧ 32764）と途切れ（最初の valid の後の valid = 0） |
| `src/wspec_core.v` | dstamp を置く（フレームの頭 = 最初の z） |
| `src/win_core.v` | t_in・go_in・tev_in を 1 段受ける。窓ごとに ARM_RUN・ARM_WRST・CFG_ID・RUN_CFG・WRST_CFG・DUMP_T・DUMP_H・DUMP_CFG・RUN_T・RUN_SHIFT。**SHIFT を RUN で取り込む**。ADC の共通に TP_ARM・TANCH（ADC のフレームと T の組）・TP_RUN_T・OVR_CNT・GAP_CNT。ID 0x0016_0100 / 0x0016_A100 |
| `src/spec_core.v` | 同じ（ARM_RUN・CFG_ID・DUMP_T・DUMP_H・DUMP_CFG・RUN_T・RUN_SHIFT。SHIFT を RUN で取り込む）。ID 0x0016_01CC |
| `build.tcl` | chans = {{2 2}}（ADC_A）・adc_tiles = {2}、time_core_0 を smc の M03 に、PPS のポート（AH13 / AJ13、`src/pps.xdc`）、時刻のネットを共有のネットとして照合（陽性対照 (c)(d) を足した。ch が 1 本だと ch 間の陽性対照 (a)(b) は回らない）、実装後に PPS のピンを読み返す |

番地の表は各ファイルの冒頭（time_core・win_core・spec_core・dstamp）。

sim が通った後に、別の目（サブエージェント）で RTL と build.tcl の差分を読ませて直したこと:

- 窓に ARM_RUN と ARM_WRST を両方かけると、RUN を受けた次のクロックに WRST が wspec をリセットして RUN が消えていた（RUN_CFG・RUN_SHIFT・RUN_T だけが「走っている」と言う）→ RUN を WRST の明けまで待たせる（`run_defer`。CTRL の読みの [7]）。sim-tsys に 7. を足した
- dstamp の「最後のダンプか」（32 bit の比べ）がフレームの頭のクロックにあり、≒ 800 個の FF の enable に効いていた → レジスタに置いた（k が変わるのはフレームの頭だけなので次の頭に間に合う）
- time_core の間隔の判定で、減算と 2 本の比べが 1 クロックに並んでいた → 1 クロックずつに分けた
- コメントの誤り（ev[0] はリセットから最初の縁まで 1）・timing.xdc の「自作の RTL は乗り換えを持たない」を直した（EPOCH の gray の乗り換えを書いた。set_bus_skew は名前を XDC に書くと黙って外れうるので置かない）
- 見送ったもの: 再 RUN の直前に流れていたダンプが新しい SHIFT・CFG で閉じうる（STOP の後 1 ダンプぶん待ってから RUN する運用で受ける）／WRST で SEQ が 0 に戻ると DUMP_CFG が 1 回書き換わる（読む側は SEQ を見るので無害）

### 時刻の約束

- **ビート**: DSP のクロック 1 個（3.90625 ns = 125/32 ns）。コアの中の t_loc は time_core の T と同じ値になる（time_core が段数ぶん先に足して出す）
- **予約**: START_AT を書いて time_core を ARM。ARM しておいたコアは **T = START_AT + 1** のクロックに RUN（WRST）を受ける（RUN_T）。
  窓に ARM_RUN と ARM_WRST を両方かけたときだけ、**RUN は WRST が明けてから**（同時だと WRST が RUN を消す）
- **コアの側の予約は、発火・STOP・取り消しでしか消えない**。time_core の取り消しや「遅すぎ」では残るので、PS がコアの側も取り消す（`timetest.py` の `arm_tc`）
- **ダンプの時刻**: DUMP_T = そのダンプの最初のフレームの最初のサンプルがコアに入ったビート。全帯域は DUMP_T(k) − DUMP_T(0) = k·N·512 ちょうど、窓は k·N·4096·2^(NS−1)
- **ADC のサンプルの時刻**に直すには、コアの入口までの遅れ（未較正、T-2 で測る）と、窓ではさらに D(NS) を引く（`pynq/timebase.py`）

窓の遅れ D(NS)（`make sim-wdelay`。ADC のインパルスのビート → |z|² の重心が wspec に入るまで、ビート）:

| NS | 幅 | D [ビート] | D [µs] | フレーム長 L [ビート] |
|---|---|---|---|---|
| 1 | 256 MHz | 57.6 | 0.225 | 4096 |
| 2 | 128 MHz | 87.2 | 0.341 | 8192 |
| 3 | 64 MHz | 136.1 | 0.532 | 16384 |
| 4 | 32 MHz | 229.0 | 0.895 | 32768 |
| 5 | 16 MHz | 408.1 | 1.594 | 65536 |
| 6 | 8 MHz | 748.3 | 2.923 | 131072 |
| 7 | 4 MHz | 1427.8 | 5.577 | 262144 |
| 8 | 2 MHz | 2781.1 | 10.864 | 524288 |

要求 100 µs に対して最大 11 µs（2 MHz）。**小さいが 0 ではないので timebase で引く**（`WIN_DELAY_BEATS`）。RTL を変えたら出し直す。

### PS（`pynq/`）

- `timebase.py`（新）: `TimeCore`（レジスタ）と `Timebase`（錨・UTC の整数 ns・答えられないときは例外）。proj008 の型
- `timetest.py`（新）: 実機の T-0〜T-4
- `spectrometer.py`・`window.py`: ID・BITFILE（proj016.bit）・CHANS を ADC_A の 1 本に・窓の既定の ADC を 0 に。**4 ADC を前提にした道具（`win16.py` など）は proj016 では動かない**
- `docs/block_design.svg` は proj015 のまま（time_core が描かれていない）

## 結果

### sim（2026-10-02、クラウドの iverilog 12）

| sim | 中身 | 結果 |
|---|---|---|
| `sim-time`（S-T1） | time_core 単体（1 秒を 2000 クロックに縮めて）: t_loc = T、PPS の間隔・数（2 系統）、許容 ±1 の内 / 外（+1 は BAD にならず +3 は BAD と ev[1]）、グリッチ、欠落（MISS・ev[0]・戻ったら落ちる）、予約発火 3 通り（100・777・5 秒先。**go_loc の立つ T = START_AT ちょうど**、FIRED = START_AT）、遅すぎ・遠すぎ・取り消し、リセットで EPOCH 1 → 2・ANCHORED が 0 に | **通過** |
| `sim-time-p` | 陽性対照: 発火を 1 クロック早く | **落ちた**（6 件）= 見張りは効いている |
| `sim-wstamp`（S-T2） | wspec_core ＋ dstamp。4 変種（N 2・N 1・N 1 で入力が 1/3・N 1 で FFT の遅れ 9000 クロック）、RUN を 2 回。DUMP_T = 頭の z を入れたクロックの T（tb が独立に記録）、DUMP_F0・DUMP_K・RUN_T、健全性 = 区間の ev の OR（ev の入ったダンプと入らないダンプの両方がある）、帳簿 0 | **通過**（4 / 4） |
| `sim-wstamp-p` | 陽性対照: スタンプを 1 ビートずらす | **落ちた**（8 件） |
| `sim-tsys`（S-T3・S-T4） | time_core ＋ win_core（NW 2）＋ spec_core を BD と同じくつなぐ。窓 0・窓 1・TP・全帯域が **T = START_AT + 1 = 8332 の同じクロックに RUN**、RUN_T・TP_RUN_T・FIRED、DUMP_T（全帯域 6 個・窓 0 4 個、全帯域の間隔 k·8·512 ちょうど、**窓 0（NS 1）の間隔の k·2·4096 からのずれ 0**）、RUN の間に SHIFT 7 → 3・CFG_ID 0x1234 → 0x9999 を書いても使う SHIFT は 7 のまま・DUMP_CFG は 0x1234、健全性（[0] = 1・[3] = 0・振り切れを入れたダンプだけ [4]・窓 1 の [6]）、OVR_CNT 1・GAP_CNT 0、TANCH、予約の WRST（窓 1 だけ T = START_AT2 + 1、ARM していないコアは受けない）、7. ARM_RUN ＋ ARM_WRST（WRST は START_AT3 + 1、RUN は明けた後、ダンプ 0 が閉じる） | **通過**（7. は WRST T 90109・RUN T 90175 = 明けた後） |
| `sim-tsys-p` | 陽性対照: SHIFT を RUN で取り込まない | **落ちた**（「RUN の間の SHIFT が RUN の値でない」窓 0 45410・全帯域 45405 クロック） |
| `sim-spec-all`（回帰。下の直しの後に回し直した） | proj015 の spec_core の sim 一式（SHIFT 4・7、途切れ・見張り・TLAST の陽性対照、gb、tp） | **全部通過** |
| `sim-wspec`（回帰。直しの後に回し直した） | proj015 の wspec_core の 5 変種と陽性対照 2 つ | **全部通過** |
| `sim-top`（回帰） | win_core を AXI 越しに端から端まで（NS 1） | **全部通過** |
| `sim-win4`（回帰） | win_core を 1 ADC × 4 窓で AXI 越しに（窓ごとに別の k・NS・WRST の時刻、TP） | **全部通過** |

sim-win-all のうち pfb・ddc・win・hb2s・pfbm は回し直していない（`src/pfb_core.v`・`ddc_core.v`・`hb2*.v`・`pair2.v`・`nco_rom.v`・`dft16f.v`・`cmul.v` は proj015 と同一のファイル。`cmp` で確かめた）。

**sim で踏んだこと**:
- time_core の同期器をリセットで 0 にしていると、**リセットの解除の瞬間に PPS が H なら偽の縁**になり、最初の間隔が短く出て BAD が立った（tb の PPS の位相で見つけた）。同期器を 1 で始めるように直した
- 発火の残りの初期値を最初は diff − 2 にしていて 1 クロック遅れた（diff は 1 クロック前の T に対する値）。diff − 3 に直し、陽性対照（diff − 4）が落ちることを確かめた

### ビルド（2026-10-02、Vivado 2024.1、`-1`、実装の戦略は既定、`make`）

| | proj016 | 予言・比べ |
|---|---|---|
| WNS / WHS | **+0.006 / +0.010 ns**（閉じた。最悪 5 本とも clk_out2 → clk_out2 = DSP ドメインの中） | proj015 rev3 は 4 ADC で 0.000（戦略 PEPRPO）。資源が 1/3 なのに余裕は戻っていない → 最悪経路の群を `make worst-paths` で見る |
| DSP | 1232（28.8 %） | spec_core_0 504（予言 504）・win_core_0 728（予言 720）。**wspec 1 個 32（予言 30）**: 窓ごとに +2、時刻の足しもので DSP に乗ったものがある（dstamp か RUN の取り込み。未確認） |
| BRAM / URAM | 199 タイル（18.4 %）/ 8 | |
| LUT / FF | 26.5 % / 22.7 % | |
| run の CRITICAL WARNING | なし | |
| report_cdc | CDC-3 Info 52 / CDC-6 Warning 2 / CDC-15 Warning 833 | CDC-6（多 bit・ASYNC_REG）は time_core の EPOCH の gray（予言どおりの新顔）。2 件の中身は cdc.rpt で確かめる |
| PPS のピン・結線の照合 | 通過（落ちれば exit 1 で止まる） | |

最悪経路（`make worst-paths`、slack < 0.3 ns の setup 120 本）:

| 群 | 本数 | 最悪 | 型 | 読み |
|---|---|---|---|---|
| win_core_0/u_pfb の中（`g_f[0].g_r[18].u_reg` → dft16f のひねり係数の cmul の DSP の A/B） | 80 | +0.006 | 配線 77 %・段 5・**skew −0.331 ns** | proj015 から居る群（pfb_core は proj015 と同一のファイル）。DSP の列までの配線とクロックの skew。配置で動く |
| full_sel（axis_sel4）の選択 `sr[1]` → 256 bit の出口 | 30 | +0.008 | 配線 94 %・段 1・**ファンアウト 303** | ADC 1 本では選ぶ相手がいないのに 4:1 の選択器が残っていて、その選択の bit が 256 bit に配られている |
| win_core → wspec | 10 | +0.190 | | |

**今回足した時刻の論理（time_core・dstamp・t_loc の配り）は setup の上位 200 本に出ていない**（hold の 1 本 t_loc → ts だけ、+0.010 で他と同じ）。
hold は 200 本とも +0.010〜0.015 で FFT IP の中が主（Vivado の hold の詰めの値。問題にしない）。
余裕が戻らなかったのは、時刻の論理ではなく、proj015 から居る pfb の配線と、ADC 1 本にしたのに残した full_sel のファンアウト。

## 結論・次にやること

- [x] Vivado サーバでビルド → `-1` で WNS +0.006 ns（T-5 は通過。ただし余裕はほぼ 0）
- [x] `make worst-paths` → 時刻の論理は出ない。pfb（proj015 から）と full_sel のファンアウト 303
- [ ] 次に作り直すとき: ADC 1 本なら full_sel を置かず gb_bc_0 → spec_core_0 を直につなぐ（30 本の群が消える）
- [ ] cdc.rpt の CDC-6 の 2 件が EPOCH の gray だけか
- [ ] 実機の T-0〜T-4
- [ ] T-2 の結果で `timebase.CAL` の pps_det_ns・adc_to_core_ns を埋める
- [ ] 窓の構成の proj（4 ADC に戻す）で「4 ADC が同じビートで開始」を合否に入れる

## 再現手順

```bash
make sim-t-all     # time_core（S-T1）・dstamp（S-T2）と陽性対照。数分
make sim-tsys      # time_core ＋ win_core（NW 2）＋ spec_core（S-T3・S-T4）。1 時間級。陽性対照 make sim-tsys-p
make sim-wdelay    # 窓の遅れ D(NS)
make sim-all       # proj015 の sim 一式 ＋ sim-t-all（回帰）
make ps-preset     # -1 の PS のプリセット（proj015 のものを複製済み。Vivado の版を変えたら作り直す）
make IMPL=Performance_ExplorePostRoutePhysOpt JOBS=8   # proj015 rev3 と同じ戦略（既定の戦略で閉じるならそれでよい）
```

実機（PYNQ、root。ボードは 10 MHz と 1PPS を受ける。`build/proj016.bit`・`.hwh` と `pynq/*.py` をボードへ）:

```bash
python3 timetest.py --clkin 0 --ref 10 --t0                  # T-0（120 s）
python3 timetest.py --clkin 0 --ref 10 --t1 --seconds 1800   # T-1（30 分）
python3 timetest.py --clkin 0 --ref 10 --t2                  # T-2（1PPS を ADC_A にも分けて入れる）
python3 timetest.py --clkin 0 --ref 10 --t3 --seconds 300    # T-3（その間に PPS を抜く・基準を替える・SG を上げる）
python3 timetest.py --clkin 0 --ref 10 --t4                  # T-4
```

環境は [`../VERSIONS.md`](../VERSIONS.md)、詰まったときは
[`../proj001/docs/runbook.md`](../proj001/docs/runbook.md)。
