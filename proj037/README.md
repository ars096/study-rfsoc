# proj037 — 2G-1-Fine を製品の形にする study（丸めの線・荒い ch ごとのレコード・1PPS と DUMP_T）

日付: 2026-10-30
状態: 進行中（ボードを使わない段から）

着手の前に [`../LESSONS.md`](../LESSONS.md) を全部読む（知見の全部は [`../docs/lessons_all.md`](../docs/lessons_all.md)）。

## 目的

ADR 0022（YATSUGATAKE）が「2G-1-Fine を移すまでに決める」とした 3 つを、ボードを使わない段で決める。

1. **R: 荒い段の丸めの線**（f ± k·fs/56、proj028 F-8）を下げるか。運転の入力（雑音が支配）で線がどの高さになり、観測に効くかを模型で見積もる
2. **S: 流れの形**。レコードを荒い ch ごと（114,688 ch × 8 B = 0.92 MB）に分け、INTERFACE 4.4 の頭と 4.6 の尾を付ける形を決める
3. **T: 1PPS と DUMP_T を載せる**。時刻の格子 G（2.048 ms）・ダンプの区切り・DUMP_T が指す点・D_eff を決める

## 出発点

- 土台: study-rfsoc proj028（commit 684b630。模型は `model/` に写した: m1_coarse・m3_coarse_fixed・coarse_pfb_ref・cfft32_ref・coarse_post_ref・m8_cw_long・m4_stitch（細かい PFB の原型 design()）。中身は変えていない）
- 仕様: YATSUGATAKE main 1e11a9b（`docs/spec/interface.md`・ADR 0009・0022）。仕様を変える案はこの README の「変更案」に書き、採るときに YATSUGATAKE の PR で `docs/spec/` に入れる
- 並行の作業との重なり（2026-10-30）: YATSUGATAKE の PR #74（`hw/common/` の core_cmn・rec_fr・tp_core の一本化）がマージ前。**S・T の RTL は #74 の後の `hw/common/` の上で作る**。この proj の R と、S・T の設計（式・頭の語・模型）は #74 と重ならない
- ボードは使わない（2G-1-Fast・2G-2 の移植と取り合わないように）

## R 荒い段の丸めの線を下げるか

### R-1 運転の入力での線の高さ — 予言（走らせる前に書く、2026-10-30）

proj028 F-8 は**雑音源を切った**入力（σ_x 5.2〜8.7 LSB）で、荒い段の丸め（z の SH 18、cfft32 の中の丸め）がトーンと相関して f ± k·fs/56 に固定の高さの線を作ることを示した。
運転では ADC に雑音（雑音源・空、−16〜−21 dBFS、σ_x ≒ 1031 LSB）が来るので、z の σ は ≒ 3800 LSB、8 bit の σ は 12 LSB で、どの丸めも雑音でディザされている。

作り（`model/r1_lines.py`）:
- 荒い段と 8 bit の再量子化の bit 単位の模型を numpy でベクトルにした（`model/fast_coarse.py`）。ref（coarse_pfb_ref・cfft32_ref・coarse_post_ref）と bit 単位で一致することを先に確かめる
- 同じ入力を、**丸めない同じ式**（同じ量子化した係数・同じ詰め替え・浮動小数点）にも通し、差 e = 固定小数点 − 浮動小数点を取る。丸めの作る線は e の中にあり、e の床は入力の雑音より ≒ 30 dB 低いので、入力の雑音に埋もれずに見える
- 入力: σ_x 1031（−18 dBFS）の白色雑音 ＋ CW（1151.999442 MHz、F-8 と同じ）。CW の強さは細かい ch（558 Hz）の雑音に対して CNR 0・+20・+40・+58 dB（+58 は 8 bit の S 12 の余裕の上限）。対照に F-8a の条件（A 47.2・σ 5.2）
- 荒い ch ごとの e と出口の y の長い FFT（131,072 ブロック、刻み 558 Hz、Blackman-Harris、±4 bin の和）で f ± k·fs/56（k = ±1〜±8、±7 を除く）の高さを読む
- 観測に効くかの物差し: 細かい ch の雑音に対する線の比。1 時間の積分で雑音の揺れは 1/√(df·τ) = 7.0e-4（−31.5 dB）、100 時間で −41.5 dB。**線がこれより下なら観測に効かない**

予言:
- (a) 模型の速い版は ref と bit 単位で一致（違い 0）。陽性対照（cfft32 の丸めの加え 2^16 を抜く）で違う
- (b) 対照（F-8a の条件）で、e の中の線が F-8 の値（k = ±1〜±8 で −65〜−77 dBc）を再現する（±3 dB）
- (c) **運転の入力では、丸めの線（e の中）は CNR によらず細かい ch の雑音より 50 dB 以上低い**（雑音のディザで丸めの誤差がトーンと相関しない。線は e の床に沈む）。
  見える深さ: z と cfft32 の丸め（e_Y、8 bit の前）は床が雑音の ≒ −70 dB なので −60 dB まで読める。8 bit の丸め（e_8）は床そのものが雑音の −32 dB（損失 5.8e-4）で、1 本の FFT では ≒ −22 dB までしか読めない。
  e_8 は「−22 dB より上に線が無い」までを確かめ、その下は σ 12 LSB のガウスのディザの理屈（丸めの誤差と入力の相関は exp(−2π²σ²) で 0）に頼る
- (d) 出口の y の線は、丸めではなく係数（荒い PFB の阻止域）の比例の漏れが支配: k = ±1 が ≒ −78 dBc（F-8c の強いトーン）。これは CW とともに上がるので、CNR +58 dB で細かい ch の雑音の ≒ −20 dB。**丸めを直しても消えない**
- 決め（予言どおりなら）: 丸めの位置・語長・ディザは**変えない**。f ± fs/56 の比例の漏れ（阻止域）は「強い線の周り ±73 MHz に CW の −78 dBc の像」として仕様の既知の性質に書く

### R-1 の結果（2026-10-30、`runs/r1.txt`・`runs/r1_leak.txt`、1 条件 ≒ 50 s）

| | 予言 | 結果 |
|---|---|---|
| (a) 速い版と ref | 違い 0・陽性対照は落ちる | **z・F・y とも違い 0**（300 ブロック、満杯の区間を含む）。陽性対照（cfft32 の丸めの加えを抜く）は F が 17,032 値違う ○ |
| (b) 対照（F-8a の条件） | e の線が −65〜−77 dBc | **e_Y −68.7〜−80.2 dBc**（床の上 +8〜+21 dB）・y −65.7〜−76.7 dBc。F-8 の模型と実機の値を再現 ○ |
| (c) 運転の入力（σ_x 1031）の丸めの線 | 雑音の −50 dB より下 | **どの CNR（+2〜+50 dB）でも、e_Y・e_8・y のどこにも線は無い**（床の上は最大 +6.4 dB。同じ ch のほかの 400 か所の 99 % 点は +5.9 dB で、64 か所を読んで 1 か所が越えるのは偶然の範囲）。読めた深さ: e_Y の線 ≦ 雑音の −54 dB、e_8 の線 ≦ −26 dB ○ |
| (d) 係数の像 | k = ±1 が ≒ −78 dBc | 雑音なし・丸めなしの実数の CW で直に測った（下）。**sl の位置で k = ±1 が −78.7 dBc**（F-8c の −78 と一致）。ch の中の位置で **−69〜−86 dBc**、\|k\| ≥ 2 は −84 dBc より下 ○（幅は予言より広い） |

- 予言の誤り（測る前に見つけて直した）: 1 回目は dBc を 8 bit の y の目盛りで取っていた。8 bit の利得は ch ごとに違う（F-8a の条件では CW の ch 17 が 1682、雑音だけの ch が 57,197）ので、CW の無い ch の線が +30 dB 持ち上がり、(b) が −35〜−49 dBc に出た。
  全部を Y（利得の前）の目盛りで比べ、CNR は ch 17 自身の雑音で取るように直した。名目の CNR（+58 dB）と実際（+50.2 dB）の差は、CW が荒い ch の端（sl）にあって ch 17 の利得が下がったため
- 係数の像（`--leak`、5 つの周波数）: k = ±1 は −69.3（300.29 MHz、ch の中の 0.69）・−72.3・−76.0・−78.3・−78.7 dBc。像は f + k·fs/56 に立ち、CW の強さに比例する（丸めではないので丸めを直しても変わらない）
- 読み: **丸めの線は、ADC の雑音だけ（雑音源を切った試験）のときにしか立たない**。運転の入力（−16〜−21 dBFS）では z の σ ≒ 3800 LSB・8 bit の σ 12 LSB のガウスの雑音が丸めをディザしており、丸めの誤差はトーンと相関しない

#### R の決め（2026-10-30、開発者が決定）

- **荒い段の丸めの位置（SH 18）・語長（z 18 bit・8 bit）は変えない。ディザも入れない。** 運転の入力では丸めの線が雑音の −54 dB より下で、1 時間の積分の揺れ（−31.5 dB）より 20 dB 以上低い
- 残るのは**係数の像**（荒い PFB の阻止域が作る、f ± k·fs/56 の CW に比例した像。−69〜−86 dBc）。これは ADC の交互の誤差の線（f ± k·fs/8 の −55 dBc 級、仕様、LESSONS）より低いので、作りは変えず**既知の性質として仕様に書く**（変更案の V-1）。
  観測に効く目安: 細かい ch の雑音に対する CW の比が CNR のとき、像は CNR − 69 dB。1 時間の積分（−31.5 dB）で見えるのは CNR ≧ +37 dB の線（強いメーザー・RFI）の ±73.14 MHz
- 試験の注意（LESSONS に既にある「弱い CW では荒い段の丸めが固定の高さの線を作る」）: 雑音源を切って CW を測る試験では f ± k·fs/56 に −65〜−80 dBc の線が見える。判定に使う線の高さは雑音源 ON か模型と並べて読む

## S 流れの形（荒い ch ごとのレコード）— 設計（2026-10-30）

前提（proj028 から）: 細かい側は荒い ch を k = 0..31 の順に 1 本ずつ積み終え、`fine_rdo` が 1 本ぶん（114,688 ch、つないだ順 = 周波数の昇順）を出す。
ダンプ（チャンク、286.72 ms）全体は 3,670,016 × 8 B = 29.4 MB で、CMA の 64 MiB に 2 つしか入らない。荒い ch ごとなら 0.92 MB（2G-1-Fast の 1 MiB と同じ大きさ）。

### S-1 決めること（2026-10-30、開発者が表の案どおりに決定）

| | 案 | 理由 |
|---|---|---|
| レコードの単位 | **荒い ch 1 本 × 1 チャンク = 1 レコード**（中身 114,688 × u64 = 917,504 B）。1 ダンプ = 32 レコード | 細かい側の出方そのまま（溜めが要らない）。リングと PS の 1 回の量が 2G-1-Fast と同じ |
| 流れの KIND | **新しい KIND 5「STAGE2」**（2 段）。NCH = 3,670,016。PARAM[7:0] = log2 N_f（17） | 1 本の流れの ch → IF は f = (S0 + i)·fs / (56·N_f)。2^n 点の FFT ではないので FULL（f = i·fs/N）にも SLICE にも入らない（式が違う KIND は分けるのが 2.1 の約束） |
| SEQ | **レコードごとに +1**（= 32·ダンプ ＋ k）。流れのブロックの SEQ（0x1C）は閉じたレコードの通し番号 | リングと PS の「SEQ の飛び = 欠け」の見張りが KIND に依らず今のまま使える |
| DUMP_K | そのレコードの**チャンクの番号**（RUN から 0, 1, …。32 レコードで同じ） | 束ね（5.1）が「同じダンプの 32 本」を集める鍵 |
| 語 7 の上位（KIND に固有） | **S0 = k·114,688**（そのレコードの最初の ch。SLICE の S0_CUR と同じ意味） | レコードだけで ch → IF が決まる（4.4 の約束）。k = S0 / 114,688 |
| 語 4 | log2 NFFT = 17（N_f）・NS = 6（log2 M、荒い段の分け方）・SHIFT・G・fmt 0・src・DUMP_H | ch → IF の式に要る N_f をレコードに持つ |
| DUMP_F0 | チャンクの最初の**荒いブロック**の番号（RUN から、ブロック = 56 サンプル） | SNAP（type 4）と組にする鍵。ブロックの格子は T に固定（T-2）なので式で検算できる |
| DUMP_T | チャンクの最初のブロックの最初のサンプルがコアに入ったビート（**= RUN_T ＋ DUMP_K·BASE_BEATS**、T-1） | 2.5 の「指す点は KIND ごと」。FULL と同じ「入口のビート」 |
| DUMP_N | 積んだ細かいフレームの数（ふつう 160。RUN の最初のチャンクは履歴が無く 157） | 5.1 の 4. の「DUMP_N がどれも BASE / L」で、最初のダンプは PS が束ねずに捨てる（下） |
| DUMP_SAT | **荒い ch k の 8 bit の飽和の数**（そのチャンクの間） | coarse_post の数えを ch ごと・チャンクの区切りで持てば、レコードごとに意味がある |
| 尾 | 4.6 のまま（s45_ring が CRC-32 を付ける） | 変えない |

- **最初のダンプ**（チャンク 0）: 細かい PFB の履歴（前のチャンクの末尾 3 フレーム）が無いので 157 フレームしか積めない。案は「PL は DUMP_N = 157 のまま出し、PS は 5.1 の 4. で捨てる」。
  見送る案: (a) RUN の 3 フレーム前から書き始める（DUMP_T が G の格子から 2.625 G ずれる）、(b) PL がチャンク 0 を出さない（SEQ・DUMP_K が 1 から始まり、帳簿の約束が KIND で変わる）
- **PS の束ね（5.1 の読み替え）**: 基本のダンプ m = round(DUMP_T / BASE_BEATS) は 32 レコードで同じ。**ダンプ m が揃う = S0 が 0, 114,688, … の 32 本が SEQ の連続で並ぶ**。束 j は n_sum 個のダンプ × 32 本。一つでも欠けたら束ごと捨てる（今の約束のまま）。
  束ねは荒い ch ごとに足せる（k ごとに n_sum 本の和）ので、PS が 29 MB を一度に抱える必要はない
- 量: PS の読みは 32 × 0.92 MB / 286.72 ms = 102 MB/s（2G-1-Fast と同じ）。ネットワークは 4.5 の表のとおり tint ≧ 573.44 ms

### S-2 RTL でやること（#74 のマージ後の `hw/common/` の上で）

- `fine_rdo` の頭を 4.4 の形に（今は proj028 の仮の頭: w0 = {ID, 114688}・w1 = {k, c}・w2 = 積んだ数・w3 = s_k・w7 = 本体のバイト数）。頭の値（DUMP_T・DUMP_H・DUMP_SAT）は**チャンクごとの帳簿**（下の T-3）から引く
- 流れのブロック（2.5）・core_cmn（コアの共通部）を付ける。どこまで rec_fr を使い回すかは #74 の後の rec_fr の口を見て決める（rec_fr は 4096 ch の凍ったバンクを口で読む形で、細かい側は 1 本ずつ流して出すので、頭の組み立てだけを共通にするのが自然）
- 判定（sim）: 1 チャンク ＝ 32 レコードの頭が式（DUMP_T = RUN_T ＋ c·BASE_BEATS・S0 = k·114,688・SEQ の連続）と一致、中身は proj028 の F-4 の照合のまま、尾の CRC を zlib で照合。陽性対照: S0 を 1 本ずらす

## T 1PPS と DUMP_T — 設計（2026-10-30）

### T-1 時刻の格子とブロックの位相

- 荒いブロックは 56 サンプル = 3.5 ビート。**ブロックの対（7 ビート）の頭は T の 7 の倍数に置く**（T-2）。G（2^19 ビート）は 7 の倍数ではないので、ブロックの頭と G の倍数が重なるのは 7G = 14.336 ms ごと（dt が 14.336 ms の倍数である理由と同じ）
- BASE（286.72 ms）= 73,400,320 ビート = 140 G = 20·7G。specd は START_AT を **T の tint の倍数**に置く（5.1）ので、**START_AT はいつもブロックの頭**
- したがって **DUMP_T = RUN_T ＋ DUMP_K·BASE_BEATS が式で決まる**（SLICE と同じ「DUMP_T は式で決まる」）。5.1 の残り r = DUMP_T − m·BASE_BEATS は 0（RUN が START_AT ＋ 1 で発火するなら 1 ビートなど、作りで決まる定数。RTL で決める）
- 見張り（式に頼らない側）: ct_wr がチャンクの最初のブロックを受けた拍の T を実際に押し（スタンプ）、式と違えば粘着の FLAGS。sim に陽性対照（ブロックの位相を 1 拍ずらす）

### T-2 ブロックの位相を T に固定する

- proj028 の coarse_pfb は「履歴に入った拍の数え」（7 拍の周期）で位相 A・B を決めている。数えの原点は入力の valid が初めて立った拍なので、**ブロックの格子と T の関係は Overlay ごとに違う**
- 案: 拍の数えを T mod 7 に合わせる（time_core の T がコアに届く拍で、mod 7 の数えを同じリセットから回す。ギアボックスの出口は起動の後は毎拍 valid なので、valid の欠けは GB の FLAGS で別に見る）。
  RUN の印（tuser）は START_AT の拍の入力に付けて荒い段を一緒に通し、ct_wr はその印のブロックからチャンク 0 を始める（遅れの定数を持たない）

### T-3 チャンクごとの帳簿

- ct_wr がチャンク c を閉じるときに {DUMP_T のスタンプ・DUMP_H（チャンクの間の ev の OR）・荒い ch ごとの飽和の数え 32 個} を、c mod 3 の帳簿に置く（DDR の面と同じ 3 面）。fine_rdo はチャンク c の ch k を出すときに引く
- 1PPS・time_core は共通部のまま（2.3 の `time_core_0`）。2G-1-Fine の bit に足すのは build.tcl の PPS のピンと LPF の常設（ADR の前提）だけ

### T-4 D_eff — 予言（走らせる前に書く、2026-10-30）

5.2 の utc_ns = beat_utc(DUMP_T) − adc_to_core[src] − D_eff。D_eff は、ダンプの矩形（DUMP_T から BASE）の中心と、入力のサンプルがダンプの電力に効く重み（係数の 2 乗）の重心との差。

- 細かい PFB（T = 4、対称の窓）: フレーム f の窓はブロック [(f − 3)·N_f, (f + 1)·N_f) で、重心は矩形のフレームの中心より **1.5·N_f ブロック前**（SLICE の 1.5·L と同じ）
- 荒い PFB（1728 タップ、対称）: ブロック m は最も新しいサンプル 56m ＋ 55 から 1728 個を窓にかけるので、重心は 56m ＋ 55 − 863.5 = 56m − 808.5。ブロックが覆うサンプル [56m, 56m + 55] の中心（56m ＋ 27.5）より **836 サンプル前**
- **予言: D_eff = 1.5·N_f·56 ＋ 836 サンプル = 11,010,884 サンプル = 688,180.25 ビート（2.688204 ms）**。N_f に依らない形（1.5·N_f·56 ＋ 836）なので、N_f 256 に縮めた模型で確かめる（22,340 サンプル）
- RTL の遅れ（D_S にあたるもの）は、RUN の印がデータと一緒に流れる作り（T-2）なら 0。これは RTL の sim で孤立したサンプルを入れて確かめる（proj023 の sim-wds と同じ型。RTL の段）
- 作り（`model/t4_deff.py`）: 荒い段の 18 bit の係数（gtable）と細かい窓（m4_stitch.design）で、サンプル t の重み w(t) = Σ_m g²[56m + 55 − t]·Σ_f h_f²[…] を直に足し、重心を数える。チャンク K = 6 フレーム、前に履歴 3 フレーム。
  陽性対照: 細かい窓を対称でない窓（前半だけ 2 倍）にすると予言から外れる

**T-4 の結果（2026-10-30、`runs/t4.txt`）: 予言どおり**
- N_f 256: −22,340.0000 サンプル（予言 −22,340、差 −4e-12）・N_f 1024: −86,852.0000（予言 −86,852、差 +3e-11）。陽性対照は +1,910・+7,643 サンプル外れて落ちる ○
- **2G-1-Fine の D_eff = 688,180.25 ビート = 2,688,204.1 ns**（RTL の遅れ D_S = 0 の前提。D_S は RTL の sim で出す）。
  サンプルの瞬間を区間 [t − ½, t + ½) と読むかどうかの ½ サンプル（0.12 ns）は入れていない（SLICE の 1.5·L も同じ読み）

## U RTL — 作り（2026-11-01。S-2・T-2・T-3 を製品の形に）

出発点: study-rfsoc proj028（commit 684b630）の `src/`・`sim/`・`tb/`・`tools/` と、YATSUGATAKE main 54ce5e3 の `hw/common/`（core_cmn・time_core・tp_core・raw_core・rec_arb・s45_ring・adc_ev・axis_sel4・gb_*）。
写した部品はこの proj の中に置く（`src/` は proj028 の並び、`src/common/` に hw/common の写し）。2G-1-Fast（YATSUGATAKE `hw/bits/2g-1-fast/`、g21_s45_core・g21_core）を流れのブロックの手本にする。

### U-1 決めたこと（2026-11-01、開発者）

- **流れは 2 本**: s = 0 STAGE2・s = 1 RAW（2G-1-Fast の FULL ＋ RAW と同じ形。F-2・specd の SNAP は RAW の道具のまま）。NSTREAM 2
- RTL と実機は proj037 の続きでやり、移植元のタグも proj037 で打つ

### U-2 コアの形（案）

```
ADC ─ gb ─┬─ s2_s45_core（module reference、セルの名前 s45_core_0）──────────────────────────┐
          │    core_cmn（BIT_KIND 12・NSTREAM 2・BASE_BEATS 73,400,320）                     │
          │    s2_strm（流れ 0、KIND 5）: 流れのブロック・ARM_RUN・帳簿・荒い段（coarse_stage） │
          │       └ m_axis_ct（512 bit ＋ tuser の印）→ ct_wr ─ MIG ─ ct_rd ─ s_axis_ct ┐      │
          │       fine_core（fine_rdo の頭を 4.4 に）← ─────────────────────────────── ┘      │
          │    raw_core（流れ 1、KIND 4）                                                    │
          │    rec_arb（コアの TP・STAGE2・RAW）→ m_axis_rec ─────────────────────────────── s45_ring
          └─ axis_sel4（RAW の SRC）
```

- **荒い段はコアの中、corner turn（ct_wr・ct_rd）はコアの外**（MIG への AXI4 の主は BD のセルのまま。設定のレジスタ BASE・CHSTRIDE・… は Overlay を載せたときに PS が書く。約束の外）
- **荒い段の設定は流れのブロックの種類に固有の場所へ**: 0x100 + 4k GAIN[k]（k = 0..31）・0x200 + 8k POW[k]・0x300 + 4k CLIP[k]・0x380 NACC・0x384 POW の SEQ（今の coarse_post の 0x100・0x200・0x400・0x004・0x008 を移す）。GAIN は specd が書く（運転の設定）、POW・CLIP は診断
- 流れのブロックの 0x000〜0x0FF は g21_core と同じ並び。STAGE2 の読み方: SID {2, 5, 0, 0}・PARAM {0, 64, 0, 17}・NCH 3,670,016・FRAME_BEATS 458,752（細かいフレーム = 131,072 ブロック × 3.5 ビート = 458,752 ビート）・N_ACC 160（固定。書けるが効かない）・NFFT_MIN_MAX {0, 0, 17, 17}・SHIFT は細かい側の SHIFT（RUN で取り込む）

### U-3 ブロックの位相（T-2）

- coarse_pfb の 7 拍の数え b7 を、**受けた拍の T mod 7** から作る（今は「valid が初めて立った拍から」）。T mod 7 は 8 ≡ 1 (mod 7) なので 64 bit の 8 進の桁の和で、段に分けて出す。
  数えの規則は今の coarse_pfb のまま（b7 = 3 で対の 1 つ目のブロック、b7 = 6 で 2 つ目）で、**b7 = (T_beat − PH) mod 7**、PH は「T ≡ 0 (mod 7) の拍がブロックの対の頭」になる定数（v1 の段の分、sim で決める）
- 見張り: 数え（ふつうに +1 で回す）と T mod 7 から出した値を毎拍比べ、違えば粘着の FLAGS（TFIN の書き換えなどで T が飛んだとき）。違ったら数えを T に合わせ直す
- **RUN の印**: go（START_AT の拍）で RUN を受け、その拍が頭のブロックの対の、**最初のブロックの番号 n_run** を覚える（荒い段の入口で数えたブロックの番号）。荒い段の出口（順序は変わらず欠けない）で同じ番号を数え、n_run のブロックに tuser[0] = 1（印）を付ける。
  以後 N_DUMP チャンクぶん（0 なら止めるまで）のブロックだけ m_axis_ct に valid を出す。ct_wr は印のブロックで数えを 0 にしてチャンク 0 を始める（今の CTRL の RUN 0 → 1 と同じ消し方）
- START_AT が 7 の倍数でない（specd の誤り）: RUN は受けず、FLAGS の [?] を立てる（DUMP_T の式が崩れるので黙って始めない）

### U-4 チャンクごとの帳簿（T-3）

- **入口の側**（荒い段の入口で、T の区間 [RUN_T ＋ c·BASE, RUN_T ＋ (c+1)·BASE) ごと）: DUMP_T のスタンプ（チャンクの頭のブロックの最初のサンプルが入った拍の T）・DUMP_H（ev の OR、g21_core と同じ 6 bit ＋ [15] H_OPEN）
- **出口の側**（荒い段の出口で、ブロックの番号 [c·B_C, (c+1)·B_C) ごと、B_C = 20,971,520 ブロック）: 荒い ch k ごとの 8 bit の飽和の数え（re・im の成分ごと、coarse_post の CLIP と同じ数え方）
- 帳簿は **4 面**（c mod 4。DDR は 3 面だが、チャンク c の最後のレコード（k = 31）が出るのはチャンク c + 2 の頭に近い。余裕に 1 面）。面に c を書き、fine_rdo が引くときに c が違えば粘着の FLAGS と、そのレコードを tuser = 1（捨てる）
- fine_rdo の頭（4.4）: w0 {s 0, core, type 1, rec_ver 1, "S45R"}・w1 {DUMP_K = c, SEQ}・w2 DUMP_F0 = c·B_C・w3 DUMP_T（帳簿のスタンプ）・w4 {DUMP_H, src, fmt 0, G, SHIFT, NS 6, 17}・w5 {DUMP_SAT[k], DUMP_N（積んだフレーム）}・w6 {FLAGS, DUMP_CFG}・w7 {S0 = k·114,688, 917,504}
- **SEQ**: レコードを始めるたびに +1（RUN をまたいで続く、g21 と同じ）。fine_rdo が捨てたレコード（busy 中の start）も SEQ は進める（欠け = SEQ の飛び）。流れのブロックの 0x1C は最後に始めたレコードの SEQ、DUMP_K・DUMP_* は最後のレコードの値
- REC_CTRL: ALL = 全部・ONE = 次のチャンクの 32 本を出したら 0 に。出さないレコードは fine_rdo の読みを回して中身を捨てる（fine_acc の面を空けるため）。REC_LATE は fine_rdo の n_drop
- **DUMP_T の見張り**: スタンプと式（RUN_T ＋ c·BASE_BEATS）が違えば粘着の FLAGS

### U-5 判定（sim、予言は走らせる前に）

本物の大きさ（1 チャンク = 7,340 万ビート）は iverilog で回らないので、**大きさの引数を縮めて**回す（ブロック数 B_C・群 GPD・細かい側の N_f はそのまま回せないので、fine_core は proj028 の sim-fcore の大きさのまま、帳簿と頭は fine_rdo を単体で）:

| | 中身 | 予言 |
|---|---|---|
| U-a ブロックの位相 | coarse_pfb を T を付けて回し、T の始まりを 7 通りに変える。対の頭が T ≡ 0 (mod 7) | 7 通りとも、b7 = 3 のブロックの最初のサンプルの T が 7 の倍数。模型（coarse_pfb_ref）と bit 単位で同じ。陽性対照（PH ＋ 1）は 7 通りとも外れる |
| U-b RUN の印と F0 | s2_strm を B_C 縮めて（例 2048 ブロック）、START_AT を 3 通り。印のブロック・チャンクの区切り・DUMP_T のスタンプ | 印のブロックの最初のサンプルの T = START_AT。スタンプ = RUN_T ＋ c·BASE（B_C に合わせて縮めた BASE）。START_AT ＋ 1（7 の倍数でない）は RUN を受けず FLAGS |
| U-c 頭と帳簿 | fine_rdo ＋ 帳簿を単体で、3 チャンク × 32 本 | 32·3 本の頭が式（SEQ 連続・DUMP_K・S0 = k·114,688・DUMP_F0 = c·B_C・DUMP_SAT が帳簿の値）と一致。中身は proj028 の sim-facc の照合のまま。陽性対照: S0 を 1 本ずらす（k ＋ 1）で落ちる |
| U-d 尾 | s45_ring まで通し、尾の CRC を zlib で | 一致 |
| U-e D_S | 孤立したサンプル（1 拍だけ大きい値）を START_AT の後に入れ、荒い段の出口でそのサンプルが効くブロックの番号と DUMP_F0 の式から、入口の拍と DUMP_T の差 | D_S = 0（印がデータと一緒に流れるので、遅れの定数が無い）。陽性対照: 印を 1 ブロック遅らせると D_S = 3.5 ビート |

### U-5 の結果（2026-11-01、`build-sim/`）

| | 予言 | 結果 |
|---|---|---|
| U-a ブロックの位相（`sim_cpfb_ph.py`） | 7 通りとも対の頭が T ≡ 0 (mod 7)・z は模型と同じ。陽性対照は 7 通りとも外れる | **7 通りとも位相の外れ 0・z の違うブロック 0 / 69〜70・lock 1・err 0** ○。陽性対照（-DCPFB_PH_ERR）は 7 通りとも 47〜48 ブロック外れる ○。足した見張り: 本物の T で valid を落とす（--gapt）と ph_err が立つ ○ |
| U-b RUN の印と区切り（`sim_s2_strm.py ub`） | 印のブロックの T = START_AT・スタンプ = 式。7 の倍数でない START_AT は受けず FLAGS | **START_AT 2800・2807・3059 とも出口 192 ブロック（3 チャンク × 64）・印 1（最初のブロック）・RUN_T = START_AT・FLAGS 0（スタンプが式どおり）** ○。START_AT ＋ 1 の 3 通りは出口 0・FLAGS[1] ○ |
| U-e D_S（`sim_s2_strm.py ue`） | D_S = 0。陽性対照（印を 1 ブロック遅らせる）で 3.5 ビート | **D_S = 0 サンプル**（孤立したサンプルが効く 31 ブロックの z が全部、DUMP_T と印から数えた位置 s = 805 の g[56m + 55 − s] と合い、合う s は 1 つ）○。陽性対照は s = 749（**+56 サンプル = 3.5 ビート**）○ |
| U-c 頭と帳簿（`sim_s2_strm.py uc`） | 頭が式と一致・S0 を 1 本ずらす陽性対照で落ちる | **(c, k) = (0, 0)・(1, 1)・(2, 31) の 3 本とも頭 8 語が式と一致**（SEQ 0・1・2 の連続・DUMP_K・DUMP_F0 = c·B_C・DUMP_T = START_AT ＋ c·BASE・語 4・DUMP_SAT が出口で数え直した値（127・118・123）・DUMP_N・DUMP_CFG・S0 = k·114,688）○。帳簿に無いチャンク（c 5）は tuser 1・FLAGS[3]・REC_LATE 1 ○。陽性対照（-DS2_S0_ERR）は落ちる ○。**fine_core は口だけ同じスタブ**（`tb/fine_core_stub.v`）: 本物は荒い段といっしょだと iverilog で ≒ 86 拍/秒、レコード 4 本に 1.5 時間を越える。中身の道は sim-fcore・sim-facc（頭を外から渡す形）が見る |
| ct_wr の印（`sim_ct_wr.py --mark`、U-3 で足した） | ごみ（群の半分 ＋ 3 ブロック）の後の印から、印の無いときと同じ中身 | QB 4・QB 64 とも中身の違い 0・chunk_done 0..6 ○。陽性対照（印を見ない ct_wr）は 36,863 / 36,864 値違う ○。proj028 の 4 本（ふつう・QB 64・陽性対照・STALL）も今までどおり |
| proj028 の回帰 | 写した部品の口を変えても今までどおり | sim-cpfb 3 本・sim-cstage 2 本・sim-facc 3 本・**sim-fcore 4 本**（ふつう・陽性対照・速さ・速さの陽性対照。頭は外から渡す形に、照合は 4.4 の w0 に直した。4 本並べて ≒ 50 分）が今までどおり ○ |

| U-d リングの尾（`sim_s2_ring.py`） | リング = コアの出口の tuser 0 のレコード・尾の CRC = zlib・DROP_CNT 1・REC_CNT 5。陽性対照は CRC の外れ 1・語の違い 1 | **5 本（RAW 2・STAGE2 3）とも頭と本体が語ごとに同じ・尾 w0 = {SEQ, "S45E"}・w1 = zlib.crc32・残り 0**・REC_CNT 5・ERR 0・記憶の見張りの NG 0（バースト 137）・STAGE2 の語 7 = {k·114,688, 32} ○。**1 回目は DROP_CNT 2 で外れた**（下）。直した後は DROP_CNT 1 ○。陽性対照（-DRING_FLIP）は CRC の外れ 1・語の違い 1 で落ちる ○。1 本 ≒ 3 分 |

- **U-d の 1 回目の外れ: 帳簿に無いレコード（c 5）が DROP_CNT で 2 と数えられた**。s2_strm が、そのレコードを tuser 1 で出し（リングが DROP_CNT +1）、同時に rec_drop も立てていた（リングがもう +1）。
  interface.md 4.2 の DROP_CNT は「捨てたレコードの数」で、rec_drop は「読み始めなかったダンプ」（g21_core の rec_fr と同じ）。rec_drop を fine_rdo の n_drop（読み始めなかったレコード）だけにし、REC_LATE は両方を数えるままにした。
  U-c はリングを通さず、REC_LATE だけを見ていたので出なかった。U を全部回し直した（`make sim-u` 14 本、3 分 11 秒、全部予言どおり）
- U-d は本体を縮めるため、s2_strm に REC_W（語 7 の P = 8·REC_W だけに効く。既定 114,688）を足した。リングを読むのは終わりの 1 回だけ（リングの巻き戻りと PAD は proj021 の sim-ringu が見ている）
- LBL_FIX（ラベルの補正）は 0 のままで D_S = 0 だった（axis_sel4 の 1 段と s2_strm の受けの 1 段が「t_loc − 1」で合っている）
- U-c の 1 回目で、捨てたレコード（帳簿に無い c）の頭の値が流れのブロックの DUMP_*（0x3C など）に残った（DUMP_K 0xFFFF0005）。捨てなかったレコードの値だけを残すように直し、U を全部回し直した（`make sim-u` 12 本、2 分 21 秒）

### U-d の作りと予言（走らせる前に書く、2026-11-01）

- 作り（`tb/tb_s2_ring.v`・`tools/sim_s2_ring.py`）: s2_s45_core（fine_core はスタブ）→ s45_ring（NIN 1）→ 止まりをランダムに入れる記憶（proj021 の tb_ring_u の HP0 の代わり。SIZE 64 KiB、終わりに 1 回だけ読む）。
  B_C 64・BASE 224・N_DUMP 3 は U-c と同じ。STAGE2 は ARM_RUN、RAW（N_ACC 1・N_DUMP 2・ALL）も同じ go で ARM_RUN。
  細かい側には U-c と同じ (c, k) = (0, 0)・(1, 1)・(2, 31)・(5, 3) を流す（(5, 3) は帳簿に無い → tuser 1）
- **本体の大きさの引数 REC_W を s2_strm に足す**（既定 114,688 語、語 7 の P = 8·REC_W だけに効く。S0 = k·114,688 は変えない）。スタブの本体は 4 語なので tb は REC_W 4。
  s45_ring は P でレコードの長さを決めるので、P と本体の語の数が食い違うと尾の位置がずれる（本物の大きさは 1 レコード 114,696 語で、荒い段と回すと 20 分を越える）
- 予言:
  1. リングのレコード = コアの出口（m_axis_rec）の tuser 0 のレコード（STAGE2 3 本・RAW 2 本）、順もそのまま、頭と本体が語ごとに同じ。TP のレコードは出ない（TP_RUN を書かない）
  2. 尾 8 語が w0 = {SEQ（頭の w1 の下位 32 bit）, "S45E"}・w1 = zlib.crc32（頭 ＋ 本体の little endian のバイト）・残り 0
  3. DROP_CNT 1（(5, 3) の 1 本）・REC_CNT 5・ERR 0・記憶の見張りの NG 0。STAGE2 の語 7 = {k·114,688, 32}
  4. 陽性対照（-DRING_FLIP）: 記憶に書かれた最初のレコードの本体の 1 語を 1 bit 反転 → CRC の外れ 1 本・語の違い 1 で落ちる

## V .bit（2026-11-01。`make`、この PC の Vivado 2024.1）

### V-1 作り

出発点: YATSUGATAKE 54ce5e3 の `hw/bits/2g-1-fast/build.tcl`（2G-1-Fast の製品の形: ADC 4 本のギアボックス・axis_sel4 2 個・time_core と 1PPS・s45_core_0・s45_ring_0・照合）を写し、
study-rfsoc proj028 の `build_f5.tcl`（MIG・ct_wr・ct_rd・smc_ddr・clk_mon）を足した。

```
ADC_A..D ─ gb_* ─ gb_bc_i ─┬─ s45_core_0/s_axis（ch 0 だけ、コアの TP）
                           ├─ s2_sel（axis_sel4、sel = s45_core_0/s2_sel）─ s45_core_0/s_axis_s2
                           └─ raw_sel（axis_sel4、sel = s45_core_0/raw_sel）─ s45_core_0/s_axis_raw
s45_core_0（s2_s45_core）/ct_y・ct_mark・ct_valid → ct_wr_0 ─┐
                                                           ├─ smc_ddr（256 MHz → UI）─ ddr4_0（PL DDR4 4 GiB）
s45_core_0/s_axis_ct ← ct_rd_0 ─────────────────────────────┘   （chunk_done・chunk_idx: ct_wr_0 → ct_rd_0）
s45_core_0/m_axis_rec → s45_ring_0 → PS の S_AXI_HP0_FPD
time_core_0（1PPS: pps_trig・pps_comp）→ s45_core_0/t_in・go_in・tev_in
smc_ctrl（pl_clk0 / DSP）: M00 rfdc・M01 s45_core_0・M02 time_core_0・M03 s45_ring_0・M04 ct_wr_0・M05 ct_rd_0・M06 clk_mon_0（pl_clk0）
```

- ID: BIT_KIND 12・BIT_REV 1・PROJ 0x0037_0100（s45_core_0・time_core_0・s45_ring_0）。part は -1（2G-1-Fast と同じ。PS には `src/board/ps_preset.tcl`）
- コアの荒い段の出口は tready が無いので AXIS にせず、素のピン（ct_y・ct_mark・ct_valid）にした（BD が口を推論すると ct_wr の s_y・s_mark・s_valid につなげない）
- 制約: `src/board/timing.xdc`・`pps.xdc`（YATSUGATAKE 54ce5e3 の hw/board、写し）・`ddr4.xdc`・`clk_mon.xdc`（proj028）。UI クロックは群に入れない（proj028 と同じ。乗り換えは smc_ddr と clk_mon の中）
- corner turn の設定（BASE・CHSTRIDE・PLANE_STRIDE・GPD 10240・NPLANE 3・HB）は Overlay を載せたときに PS が書く（proj028 の f5.py と同じ）

### V-2 予言（走らせる前に書く）

- 照合（設定の読み返し・結線・番地・ROM のラッパ・ROM の BRAM・足・自作のセルの OOC）は全部通る。初回は書き換えの Tcl の誤りで 1〜2 回止まる見込み
- 資源: proj028 F-5e（BRAM 440・DSP 1,835・URAM 66・LUT 16.3 万）に、ギアボックス 3 本・axis_sel4 2・time_core・raw_core（記憶 2 面 = RAMB36 8）・core_cmn の TP・s2_strm の帳簿を足して
  **DSP ≒ 1,850・BRAM ≒ 455〜465・URAM 66・LUT ≒ 17.5〜18 万**
- タイミング: proj028 の F-5 は WNS +0.007〜+0.022 ns でぎりぎり。足した部品は 2G-1-Fast で閉じた形なので経路は増えないが、混みで配置が動き、**既定の戦略で閉じない確率は半分くらい**。閉じなければ Performance_Explore を並べる（proj028 と同じ手順）
- CDC: 自作の乗り換えは time_core の EPOCH（2G-1-Fast と同じ）と clk_mon だけ

### V-3 結果

**1 回目（既定の戦略、`build/`、USR_ACCESS 0xf752b041 = f752b04 ＋ 未コミットの変更あり）: タイミングが閉じない（WNS −1.903 ns・WHS +0.007 ns）。実機に使わない**

- 照合は全部通った（PS のプリセット・MIG の 14 項目・FFT のポート・結線 126 行と陽性対照・番地・ROM のラッパ 4 本・自作のセルの OOC 16 個・DDR の足 5 本・clk_mon の同期器 4 個・lane_fft_f 16 個）
- ROM の BRAM: u_coef RAMB36 換算 4.0（予言 4）・u_tw 11.5（予言 11.5）
- 資源: LUT 177,021・FF 294,024・BRAM 449.5・URAM 66・DSP 1,862。予言（LUT 17.5〜18 万・BRAM 455〜465・URAM 66・DSP ≒ 1,850）のうち BRAM だけ 6 少ない側に外れた
- 違反: 最悪の 20 本は全部 MIG の UI クロック（mmcm_clkout0、3.333 ns）。遅れの 87〜98 % が配線（論理 0 段で 4.8 ns の経路もある）。群の数えでは MIG の中（cal・ui・axi）と smc_ddr の m00 側が大半で、ほかに s45_core_0 の u_s2/u_post（最悪 −1.0 ns）と u_s2 → ct_wr_0（−0.77 ns）
- 混み: 配線の前の見積もりで Global・Short とも level 5（32×32）。最も混んだ所は INT X56〜71・Y284〜327
- CRITICAL WARNING: BD 41-759 × 3（リングの使わない口、2G-1-Fast と同じ）と Timing 38-282（閉じない）だけ
- 読み: 予言の「半分くらいで閉じない」の側。MIG の論理が混んだ所を通って引き伸ばされた形で、proj028（同じ MIG で +0.007 ns）より細かい段のぶんだけ混んだ
- 次: Performance_Explore（`build-PE/`）と Congestion_SpreadLogic_high（`build-CSL/`）を並べて回す（2026-11-02 03:20 開始）

**2 回目（Performance_Explore、`build-PE/`）: WNS −0.183 ns・WHS +0.007 ns。閉じない**

**3 回目（Congestion_SpreadLogic_high、`build-CSL/`）: WNS +0.046 ns・WHS +0.007 ns。閉じた → 実機（W）はこれを使う**

- 照合は 1 回目と同じく全部通った（結線 126 行と陽性対照・ROM の BRAM 4.0 / 11.5・clk_mon 4・lane_fft_f 16）。資源は LUT 177,310・BRAM 449.5・URAM 66（1 回目とほぼ同じ）
- bitinfo: USR_ACCESS f752b041（f752b04 ＋ 未コミットの変更あり）、照合 通過。CRITICAL WARNING は BD 41-759 × 3 だけ
- 読み: 混みをほぐす戦略で閉じたので、外れの原因は MIG の論理が混んだ所で引き伸ばされたこと、という見立てと合う。余裕は +0.046 ns と薄く、RTL を変えて作り直すと再び外れうる

## W 実機（2026-11-01〜。`pynq/s2run.py`、ボードを使う試験はこの会話にまとめる）

### W-1 作りと予言（走らせる前に書く）

道具: `pynq/s2run.py`（proj028 の `pynq/f5.py` を写し、荒い段・細かい側の口を流れのブロック 0 に、始めを ARM_RUN と time_core の START_AT に、照合を INTERFACE 4.4 の頭にした）。
配線と状態: ADC_A（いつもの配線）・ノイズソース ON（15.0 V）・ATT 13 dB（2026-11-01 22:25 に読んだ。回す前と後に毎回読む）・出荷時のクロック。

| | 中身 | 予言 |
|---|---|---|
| W-1a 流れ | `--chunks 12`（≒ 3.4 s）、RAW も同じ go | STAGE2 のレコード 384 / 384・CRC と尾の外れ 0・SEQ 0〜383 が (c, k) の順・語 0・DUMP_F0 = c·B_C・**RUN_T = START_AT・DUMP_T = RUN_T ＋ c·BASE**・語 4 {SHIFT 7, 6, 17}・DUMP_N 157（c 0）/ 160・FLAGS 0（細かい PFB の飽和だけ許す）・REC_LATE 0・DROP 0・ct_wr の溢れ 0・印 1・チャンク 12・ct_rd の捨て 0。RAW: SNAP 12 本・DUMP_T の進み = 143,360 × 512 = BASE |
| W-1b 陽性対照 | `--start-off 1`（START_AT を 7 の倍数から 1 ずらす） | STAGE2 のレコード 0・流れ 0 の FLAGS[1]・ct_wr の印 0（RAW は出る: 下の注） |
| W-1c proj028 と並べる | proj028 F-5 の .bit（`build-f5/`、`f5.py`）と proj037 を交互に 2 回ずつ（A B A B）。利得はどちらも同じ手順で σ 12 LSB に合わせる。比べは `tools/cmp_spec.py` | 1024 bin の中央値の比 proj037 / proj028: **水準**（荒い ch ごとの比の中央値）1 ± 0.03（利得の合わせの差。Overlay の読み直しの揺れ ≒ 1.6 %、proj028 F-5h）・**形**（荒い ch ごとに割った残りの 1〜99 % 点）1 ± 0.01。同じ .bit の 2 回も同じ幅に入る。陽性対照（`--posctl`、荒い ch を 1 つずらす）は形で落ちる |

- W-1b の注: time_core の go は流れ 0・1 の両方に配られる。RAW は START_AT の 7 の倍数を見ないので、W-1b で RAW の SNAP は出るのが正しい（道具は STAGE2 だけを 0 本と判定し、RAW は数えるだけ）

### W-1 結果（2026-11-02。.bit は `build-CSL/`、md5 9c0330e8…、USR_ACCESS 0xf752b041。ATT は毎回の前後とも +13 dB、ノイズソース ON 14.998 V）

| | 結果 |
|---|---|
| W-1a | **全部通過**（予言どおり）。384 / 384・CRC 外れ 0・SEQ 0〜383・RUN_T = START_AT・DUMP_T 外れ 0・DUMP_N 157 / 160・FLAGS 0・REC_LATE 0・DROP 0・ct_wr の溢れ 0・印 1。RAW: SNAP 12・DUMP_T の進み 73,400,320 = BASE。RAW の DUMP_T[0] − RUN_T = 631 ビート |
| W-1b | **陽性対照として正しく RUN を受けなかった**。STAGE2 0 本・FLAGS 0x2・ct_wr の印 0。RAW の SNAP 5（リングの REC_CNT は 7。差の 2 本は止めた後に読んだ RAW の SNAP（meta の other、late）で確かめた） |
| W-1c | **不合格**（予言の外れ）。B / A の水準 0.939〜1.088（予言 ±0.03）・形 0.762〜1.295（予言 ±0.01）。同じ .bit の 2 回は揃う（A2 / A1 の形 0.9945〜1.0089、B2 / B1 0.9966〜1.0032。B2 / B1 の水準 0.9575 は B2 の利得の合わせで σ が 12.35 まで出た 1 ch）。陽性対照は正しく落ちた（形 0.33〜3.6） |

W-1c の外れの中身（診断、`runs/w1c.png`。判定の条件は変えない）:

- B / A は荒い ch ごとののこぎり形。ch の中で 1 から外れ、端で 0.7〜1.4。入力の形が急な ch 0〜5 では A と B はよく重なる（一様なずれではない）
- 荒い ch の中の形（512 bin ごと）を B_k ≈ a·A_k ＋ b·reverse(A_k) で当てると、残りの平均が 0.094（A だけ）→ 0.037 に下がる（半 ch ずらした写しを足す当て方は 0.054、ch 32−k の反転を混ぜる当て方は合わない）。b は ch ごとにばらつき（ch 0〜6 で ≒ 0、ch 7・9・23 で 0.7〜0.9、ch 14〜29 で 0.3〜0.5、負になる ch もある）
- 読み: 荒い ch の複素の時系列で、f と −f が ch ごとに違う割合で混ざっている（I/Q の像の形）。A（proj028）と B（proj037）のどちらに像があるかは、この比べだけでは決まらない
- RAW の SNAP（荒い段を通らない、36 本、2 MHz）と ch の中の形を突き合わせたが、A も B も残りが 0.1〜1.1 と大きく、周波数の当て方（ch の中心と細かい bin の対応）がまだ合っていない。決め手にならなかった
- s2run に RAW の SNAP の中身を `<out>_raw.npy` に残す口を足した
- **周波数の当て方を INTERFACE の式（IF = (S0 ＋ i)·fs / (56·2^17)、全体の bin j = k·114,688 ＋ i が IF = j × 558 Hz）に直して RAW と突き合わせた**（`w1d_*`。B を 11 回、RAW の SNAP 132 本を 2,048 点・Hann で 2 MHz に。ch ごとの水準は割り、両端 2 格子を除く）:

  | | RAW との残り（rms） | RAW の床（半分どうしの比から、0.042）を引いた残り |
  |---|---|---|
  | B（proj037） | 0.0425 | **0.005**（RAW と区別できない） |
  | A（proj028 F-5） | 0.102 | **0.093** |

  道具は `tools/raw_shape.py`。陽性対照（`--posctl`、荒い ch の中を反転）では A・B とも残り ≒ 0.60 に上がる（形を見ている）。B のほうが RAW に近い ch は 32 中 30。**荒い ch の中の形が狂っているのは proj028 F-5 の側で、proj037 は正しい形**。W-1c の予言は「proj028 と同じ形」を前提にしていて、その前提の側が壊れていた（判定は不合格のまま。比べの相手を誤った予言として残す）
- proj028 F-5 の像の原因は突き止めていない。荒い段の模型で見ると、ブロックの位相の起点のずれは全ブロックの一様な時間のずれで、像は作らないはず。proj028 と proj037 の違い（位相の起点・ct_wr の印・fine_core の帳簿・PS の組み立て）のどれかは未確定
- W-1c の見張りの穴: 「2 つの .bit を並べて比べる」は、相手が正しいことを確かめてからでないと判定にならない。荒い段を通らない参照（RAW の SNAP）を初めから比べに入れるべきだった

## 変更案（YATSUGATAKE の `docs/spec/` に入れる候補）

- **V-2（S から）**: interface.md 2.1 の KIND の表に **5 STAGE2** を足す（ch → IF は (S0 + i)·fs / (56·2^PARAM[7:0])、S0 は語 7 の上位）。2.5・4.4 に「STAGE2 は荒い ch ごとに 1 レコード、SEQ はレコードごと、DUMP_K はチャンク、DUMP_SAT は荒い ch の 8 bit の飽和」。5.1 に「STAGE2 のダンプ m は 32 本で揃う」
- **V-3（T から）**: 5.2 の D_eff の表に STAGE2 = 1.5·N_f·56 ＋ 836 サンプル（N_f 131072 で 688,180.25 ビート）＋ D_S（RTL の sim で出す）。timing.md に同じ値
- **V-1（R から）**: bits.md の 2G-1-Fine に「強い狭帯域の線 f に対して、f ± k·fs/56（k = ±1: −69〜−86 dBc、\|k\| ≥ 2: −84 dBc 以下）に荒い PFB の像が立つ。ADC の交互の誤差の線（−55 dBc 級）より低い」を足す

## やったこと

- 2026-10-30: 番号を確保し（INDEX）、proj028 の模型を写した。目的と R-1 の予言を書いた
- 2026-10-30: R-1 を走らせた（`model/fast_coarse.py`・`model/r1_lines.py`）。丸めと語長は変えない案にした
- 2026-10-30: S（レコードの形）と T（ブロックの位相・DUMP_T・帳簿）の設計を書いた。T-4 の D_eff を模型（`model/t4_deff.py`）で確かめた
- 2026-10-30: 開発者が R・S を案どおりに決めた。YATSUGATAKE PR #75（ADR 0027）
- 2026-11-01: U（RTL）。流れは STAGE2 ＋ RAW の 2 本、RTL と実機は proj037 の続き（開発者）。proj028 の `src/`・`sim/`・`tb/`・`tools/`（684b630）と YATSUGATAKE の `hw/common/`（54ce5e3）の要るものを写した（proj028 の BD の包み `fine_top.v` は写さない: 細かい側は s2_strm の中）。
  coarse_pfb（の生成器）にブロックの位相を T に固定する照らし、coarse_post に飽和の口、ct_wr に印、fine_rdo の頭を 4.4 に、fine_core に帳簿の口。
  新しく `src/s2_strm.v`（STAGE2 の流れ）・`src/s2_s45_core.v`（コアの包み、g21_s45_core から）。sim は `make sim-all`
- 2026-11-01: U-d（`tb/tb_s2_ring.v`・`tools/sim_s2_ring.py`）。s2_strm の rec_drop の二重の数えを直し、REC_W を足した

## 結果

- R-1: 運転の入力（雑音が支配）では、荒い段の丸めの線は雑音の −54 dB より下（e_Y）で、どの CNR でも線は見えない。F-8 の線は雑音源を切った試験だけのもの。残る係数の像は −69〜−86 dBc（k = ±1）で、ADC の交互の誤差の線（−55 dBc 級）より低い
- S: レコード = 荒い ch 1 本 × 1 チャンク（917,504 B）、新しい KIND 5 STAGE2、SEQ はレコードごと・DUMP_K はチャンク・語 7 の上位 = S0 の案
- T: ブロックの対の頭を T の 7 の倍数に固定すれば、START_AT（tint の倍数）がいつもブロックの頭になり、DUMP_T = RUN_T ＋ DUMP_K·BASE_BEATS が式で決まる。D_eff = 688,180.25 ビート（模型で一致）

## 結論・次にやること

- 2026-10-30: R の決め・S-1 の表は開発者が案どおりに決めた。V-1〜V-3 は YATSUGATAKE の ADR 0027 と `docs/spec/` の変更にして PR #75（ブランチ `2g-1-fine/spec-records-time`、docs だけ）に出した
- RTL（S-2・T-2・T-3）は YATSUGATAKE の PR #74 のマージの後、その `hw/common/` の上で。sim の判定と陽性対照は S-2・T-1 に書いた
- 2026-11-01: U の RTL を書き、U-a・U-b・U-e・ct_wr の印が予言どおり（U-5 の結果）。**D_S = 0**（STAGE2 の D_eff は 688,180.25 ビートのまま）。
- 2026-11-01: U-c・U-d も予言どおり（U-d の 1 回目で DROP_CNT の二重の数えを見つけて直した）。sim の段（U-5）はこれで全部。
  次にやること:
  1. build.tcl: proj028 の build_f5.tcl（MIG・ct_wr・ct_rd・SmartConnect）と YATSUGATAKE 2G-1-Fast の build.tcl（time_core・1PPS の口と LPF・axis_sel4 2 個・s45_core_0・s45_ring_0・照合）を合わせる。
     ct_wr・ct_rd の設定（BASE・CHSTRIDE・PLANE_STRIDE・GPD 10240・NPLANE 3・HB）は Overlay を載せたときに PS が書く
  2. 実機（ボードを使う試験は 1 つの会話に）: specd の STAGE2 の束ね（32 本 × n_sum）・RAW の F-2、DUMP_T = RUN_T ＋ c·BASE の見張り、proj028 の F-5c の照合（384/384・CRC・尾・捨て 0）
- 2026-11-02: V の .bit は Congestion_SpreadLogic_high で閉じた（WNS +0.046）。W-1a 通過・W-1b 陽性対照 OK。W-1c は不合格だが、RAW の SNAP と比べて**狂っているのは proj028 F-5 の側**と確かめた（proj037 は RAW と区別できない）。
  **1PPS は開発の段階では ADC に入れない（開発者の方針、2026-11-02）**。そのため、RAW の F-2（ADC に入れた 1PPS の縁で D を測る）は開発の段階ではやらない。
  次にやること:
  1. 実機: specd の STAGE2 の束ね（32 本 × n_sum）、長い運転（取りこぼし 0）、DUMP_T = RUN_T ＋ c·BASE の見張り。DUMP_T の照合は time_core の T（1PPS は time_core の口だけ）で行う
  2. proj028 F-5 の像の原因（未確定。ct_wr の印・fine_core の帳簿・PS の組み立て・位相の起点のどれか）。proj028 の F-5 の結論のうち、ch の中の形に頼るものの見直し
  3. 知見を LESSONS に足す（「2 つの .bit を並べるだけでは相手の正しさが分からない。荒い段を通らない参照を比べに入れる」「DROP_CNT の二重の数え」）
- 知見: 次の proj でも踏みそうなものを `../docs/lessons_all.md` に足した（要点なら `../LESSONS.md` にも）

## 再現手順

```bash
python3 model/r1_lines.py --check     # 速い版と ref の照合
python3 model/r1_lines.py             # R-1（5 条件、≒ 4 分）
python3 model/r1_lines.py --leak      # R-1 の係数の像
python3 model/t4_deff.py              # T-4 の D_eff
```

環境は [`../VERSIONS.md`](../VERSIONS.md)。
