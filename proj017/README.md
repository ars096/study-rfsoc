# proj017 — SAM45-Fine: 4 ADC × 2 窓（256〜8 MHz・4096 点・40.96 ms）＋ ADC ごとの total power 1.024 ms ＋ 時刻の格子 ＋ proj016 の時刻の機能

日付: 2026-10-02
状態: **sim 通過・ビルド待ち**（2026-10-03。時刻の格子 2.048 ms・dt 40.96 ms・TP 1.024 ms を取り込んだ。ビルド・実機は未）

## 目的

**最終の 9 本の bit（[`../BITS.md`](../BITS.md)）の最初の 1 本、SAM45-Fine を本番の形で作る。**

- 分光: **4 ADC × 2 窓**、幅 256 / 128 / 64 / 32 / 16 / 8 MHz（窓ごとにレジスタで）、複素 4096 点、**積分 40.96 ms**（= 20 × 2.048 ms）
- **時刻の格子 G = 2.048 ms**: 幅の違う窓のダンプの区切りを、サンプルの時刻で全窓一致させる（wspec_core の F0 を格子に寄せる）
- **total power: 4 ADC それぞれを 1.024 ms の区切り（TP_N = 512）で出す**。区切りごとに時刻を貼り、PS が読み落としなく全部を取る（全部の bit に共通の要求。最初は 1 kHz と決め、格子に合わせて 1.024 ms に）
- proj016 の時刻ラベル・設定番号・健全性の語を 4 ADC に戻す。**「4 ADC が同じビートで始まる」と「ADC ごとの M」を測る**（proj016 の持ち越し）
- 読み出しは AXI4-Lite のまま（DMA は後の proj）。40.96 ms ごとに 8 窓のスペクトルと 4 ADC の total power を **30 分読み落としなく**取れること
- `-1` で閉じる

土台は proj016（rev1 = ID 0x0016_0100）。`git ls-files proj016` の追跡ファイルを複製した。
分光の中身（pfb・ddc・wspec）は proj015 rev3 で 4 ADC × 4 窓の実機が通った RTL の部分集合（窓 4 → 2、幅 8 通り → 6 通り）。

## 着手の前に決めたこと（2026-10-02、西村さんの確認済み。dt・格子・TP の区切りは同じ日の別の会話で決め直した）

| | 決定 | 読み |
|---|---|---|
| 窓の数 | **win_core の NW = 2 × 4 ADC**（win_core は proj016 のまま、build.tcl の CONFIG.NW と chans だけ） | NW = 2 は proj016 の sim-tsys で通っている |
| 幅 | **RTL は NS 1..8 のまま触らない**。合否は仕様の NS 1..6（256〜8 MHz）で取る | 4・2 MHz（NS 7・8）を外すと light 2 段ぶん軽くなるが、ddc は時分割なので DSP はほぼ変わらない見当。実機の通った RTL を変えないほうを取る。外すかは資源と WNS を見てから |
| 積分（dt） | **40.96 ms**（SAM45-Wide・SAM45-Fine・Fine。ほかの 6 本は 10.24 ms。BITS.md）。**N_ACC = 40.96 ms / L**（L = 16·2^(NS−1) µs）: NS 1..6 → **2560・1280・640・320・160・80**（NS 7・8 → 40・20） | 最初は 40 ms（N = round(40 ms / L)、32〜8 MHz で 39.94 ms）と決めた。**同じ観測で幅の違う窓を取るとき、全窓のダンプの区切りをサンプルの時刻で一致させる**ため決め直した: 40 ms は NS ≧ 5 の L（128・256・512 µs）で割り切れず、40.96 ms = 20 × 2.048 ms は NS 1..8 すべてで割り切れる（10.24 ms の 4 倍） |
| **時刻の格子** | **T の絶対の格子 G = 524,288 ビート（2.048 ms）**。WRST・RUN・TP_ARM の START_AT は G の倍数に置く（PS） | 窓の WSTART を全窓・全 ADC で同じ格子に乗せる。途中で 1 窓だけ WRST しても揃ったまま。**WSTART（0x8C）の照合は ADC の中で全窓同じ**まで（WSTART は pfb の valid なビートの数で、原点が ADC ごとの最初の valid なビートなので ADC の間では比べられない）。ADC の間の揃いは F-4 で DUMP_T − D(NS)（T の物差し）を 8 窓で比べて見る |
| **F0 を格子に（RTL）** | **wspec_core: F0 = (⌊fin / M⌋ + 2)·M**（M = G / L = 2^(8−NS) フレーム、フレームの番号は WRST から）。従来の F0 = fin + 2 は M = 1 の場合 | dt を共通にしただけでは揃わない: RUN が各窓のフレームのどの位相に来るかは窓ごとに違い、最初のフレームの頭が窓ごとに 1〜2·L ずれる（8 MHz で最大 ≒ 1 ms）。引き継ぎのメモは「F0 を M の倍数に切り上げる」だったが、⌈(fin + 2) / M⌉·M では格子の点の近くで RUN を受けたとき（WRST と RUN を同じ発火にかけた場合など）M = 1 の窓だけ 1 個先の点に行くので、⌊fin / M⌋ + 2 にした（`src/wspec_core.v` の冒頭）。DSP は増えない見当 |
| 秒との関係・外部の状態 | 格子は秒に揃えない（1 s は 2.048 ms の倍数でない）。Overlay をまたいだ格子の一致も求めない。外部の状態入力（ON/OFF/HOT）は入れない | 時刻は DUMP_T で厳密に貼り、アンテナ・観測モードの時系列とはマージで関連付ける（BITS.md） |
| total power | **tp_core（ADC ごと、win_core の中）を TP_N = 512（1.024 ms、既定値 TPN_DEFAULT も 512）で、4 ADC を同じ格子の予約で TP_ARM**。区切りの時刻は TANCH から ANCH_T + (f − ANCH_F)·512（間隔 262,144 ビート） | 最初は TP_N = 500（1 ms）と決めた。分光の区切りと時刻を揃え比べやすくするため 1.024 ms に（40.96 ms = 40 区切り、10.24 ms = 10 区切り）。1 ms の TP の仕組みは proj013 から在り、RTL は既定値だけ |
| total power の区切りと窓・秒 | **TP の区切りは窓の区切りから一定の小さなずれ**（TP は ADC のフレーム 2 µs の頭でしか切れず F0 = TFIN + 2。数 µs 以下、ADC ごと・Overlay ごとに一定）。TANCH から計算して記録に出す。秒の縁にも揃えない | ビート単位で厳密に揃える（tp_core の区切りをフレームから切り離す）のは要るとき別に |
| total power の語に健全性 | **リングの語 3 の FLAGS の空き [4] に「その区切りに ADC の振り切れ」を足す**（adc_ev と同じ式） | 1.024 ms の TP は RFI・振り切れを見る用途に効く。PPS 系の健全性はダンプの語に既にある |
| 全帯域 1 本（spec_core_0） | **試験用に残す**（4 ADC から選ぶ。閉ループの M を ADC ごとに測るのに要る） | proj016 で閉ループは全帯域の生サンプルでしか測れないと分かった。DSP 504 |
| full_sel | **axis_sel4 の選択の bit を複製**（max_fanout。proj016 の最悪経路の群 2: 選択の bit がファンアウト 303）。段は足さない（M を変えない） | |
| 読み出し | **PS の読み出しの環を 1 本に**: 8 窓の SEQ を見て閉じたダンプを読み、4 ADC の TP_WP までのリングを読む | proj016 で 5 コアの SEQ を 20 ms おきに読んで 30 分に 1〜2 個落とした。読み出しの量は 65536 語 / 40.96 ms ≒ 17 ms（proj015 の実測から）で、面が 2 つあるので 40.96 ms の中に収まる見当。TP のリング 512 個 = 0.524 s |
| ID | win_core 0x0017_0100 / 0x0017_A100、spec_core 0x0017_01CC | |

### 資源の見当（予言。ビルドの前に書く）

| | DSP | 根拠 |
|---|---|---|
| win_core × 4 | **520 × 4 = 2080** | pfb 288 ＋ (ddc 72 ＋ wspec 32) × 2 ＋ tp 24（proj015・016 の実測） |
| spec_core_0 | **504** | proj016 と同一 |
| 合計 | **≒ 2584（60 %）** | proj015 rev3 は 3416（80 %）。**F0 を格子に寄せる分（窓ごとに 8 bit の減算 2 つと 48 bit の加算 1 つ、RUN の次のクロックだけ）と TP の既定値は DSP を使わない見当**（wspec 32 のまま） |

BRAM は窓 8 個ぶん（溜め 8・FFT 15・NCO 4 = 27 × 8 = 216）＋ スナップショット 8 × 4 ＋ tp 2 × 4 ＋ spec_core_0 ≒ 80 で **≒ 340 前後**（proj015 より ≒ 220 少ない）。
WNS `-1`: 窓が半分になり混み方は proj015 より軽い。**予言は 0〜+0.2 ns**（±0.2 ns の幅で書く教訓）。F0 の格子の 48 bit の加算は run_f0 → run_f0 の 1 クロックの経路で、最悪経路に出ない見当。

## 判定

（sim）

- S-1: 既存の sim 一式（proj016 の sim-all・sim-t-all）が通ったまま
- S-2: 4 ADC ぶんの win_core（NW 2）が time_core 1 個の予約で **同じクロックに RUN・TP_RUN** を受ける（`make sim-t4adc`）。陽性対照: ADC 3 の t_in の段を 1 つずらすと落ちる（`make sim-t4adc-p`）
- S-3: TP の FLAGS[4] が振り切れを入れた区切りだけに立つ（`make sim-tp`、陽性対照 `SIM_TP_POSCTL=2`）。**TP_N の既定 512 で**（区切りの個数 A がこの既定に依る）
- S-4: **F0 の格子**: NS 1..6 の窓に、フレームの位相をばらばらにして RUN を入れ、WSTART + F0·L が全窓で一致し、ダンプ 0・1 の DUMP_T − D(NS) が全窓で一致（`make sim-wgrid`、格子を 2^17 ビートに縮める）。陽性対照: 格子に寄せない（`make sim-wgrid-p`）と落ちる

（実機）

- F-0: ID・ビルドの指紋、4 ADC の PLL のロック、T-0（PPS の間隔 120 s）
- F-1: **4 ADC × 2 窓・TP 4・全帯域の 13 コアが RUN_T = START_AT + 1 で揃う**
- F-2: **ADC ごとの M**（T-2 の閉ループを全帯域で ADC_A〜D の 4 回。1PPS を 4 分配）。タイルの間（224 / 226）の差を読む
- F-3: 窓の回帰: 8 窓で W-0・W-1・W-6（proj015 の型）、6 幅を 1 窓ずつ
- F-4: **40.96 ms で 44,000 ダンプ（≒ 30.0 分）**: 8 窓の SEQ・DUMP_T（k·N·L からのずれ ±16）、4 ADC の TP の区切り ≒ 1,760,000 個ずつが**番号の飛びなし**、健全性なし。
  **8 窓の DUMP_T − D(NS) が全ダンプで一致（±16 ビート）、TP の区切り = 窓の区切り ＋ 一定**（30 分の TP の区切りは 1,757,812.5 で整数にならないので、ダンプの回数で区切る）。
  陽性対照: 1 窓だけ WRST を格子から外して予約すると一致しない（`fine.py --offgrid`）
- F-5: TP の TP-0（パーセバル: 全帯域と TP の比、ADC ごと）と FLAGS[4] の陽性対照（SG を上げる）
- F-6: `-1` で閉じる（WNS ≧ 0）

## やったこと

### RTL・build.tcl（2026-10-02）

| ファイル | 中身 |
|---|---|
| `build.tcl` | chans を 4 本（ADC_A..D）・adc_tiles = {0 2} に戻し、WIN_NW = 2。資源の予言の表示を proj017 の値に（合計 ≒ 2584、win_core 520 = 288 ＋ 104 × 2 ＋ 24） |
| `src/tp_core.v` | **FLAGS[4] = 区切りの中に振り切れ（\|x16\| ≧ 32764、adc_ev と同じ式）**。s1 でレーンごとに比べ、s2 で OR、制御の遅延と並べて区切りに OR。TP_PARAM の版 1 → 2。陽性対照 `TP_OVR_POSCTL`（≧ を > に） |
| `src/axis_sel4.v` | 選択の bit に `max_fanout = 32`（proj016 の `-1` の最悪経路の群 2、ファンアウト 303）。**段は足さない**（全帯域の入口の遅れ = M を変えない） |
| ID | win_core 0x0017_0100 / 0x0017_A100、spec_core 0x0017_01xx、time_core 0x0017_7101（中身は proj016 と同一。timebase の CAL を bit ごとに持つため） |
| `src/wspec_core.v`（時刻の格子） | **F0 = (⌊fin / M⌋ + 2)·M**（M = 2^max(0, G_L2 − 11 − NS)、parameter G_L2 = 19）。RUN のクロックは従来どおり fin + 2、次のクロック（run_q）に 2M − 2 − (fin mod M)（≦ 254）を run_f0・sn_next・dstamp の f0lo に足す。入力 w_ns（win_core の c_ns）。陽性対照 `WSPEC_NOGRID` |
| `src/dstamp.v` | f0_adj_v・f0_adj（RUN の次のクロックに F0 の下位 8 bit に足す。spec_core は 0）。F0 − fin ≦ 256 なので下位 8 bit の比べのまま |
| `src/win_core.v`・`spec_core.v` | parameter G_L2 = 19 を wspec_core へ。**TPN_DEFAULT 500 → 512**（1.024 ms） |
| 古い試験台 | tb_tsys・tb_top・tb_win4・tb_t4adc は win_core の G_L2 = 12、tb_wspec・tb_wstamp は wspec_core の G_L2 = 12・w_ns = 1（どれも M = 1 = 従来の F0 = fin + 2。短い入力のままの試験の形を保つ） |

### sim（2026-10-02）

- `sim/check_tp.py`: 入力の乱数を \|x16\| ≦ 32760 に収め、しきい値ちょうど（+32764、立つ）と 1 つ手前（+32760、立たない）を混ぜた。判定 D に「窓の中に [4] の立つ区切りと立たない区切りの両方」「しきい値ちょうどのビートがある」を足した。`make sim-tp SIM_TP_POSCTL=2` が陽性対照（`sim-spec-all` に入れた）
- `sim/tb_wgrid.v`（新、`make sim-wgrid` / `sim-wgrid-p`）: **S-4**。wspec_core × 6（NS 1..6、G_L2 = 17 で M = 32 … 1）に同じ WSTART から z を窓のレートで流し、窓の遅れ D(NS) ぶんずらす。RUN を 3 回（格子の点の 70 ビート前 = 実機の形、格子の真ん中、任意の位相）。RUN_F0 = (⌊fin / M⌋ + 2)·M、RUN_F0·L が 6 窓で同じ、ダンプ 0・1 の DUMP_T − D − S0 = (g0 + k)·G。陽性対照は格子に寄せない
- `sim/check_tp.py`: TP_N の既定を 512 に（最初の自走を 1030 フレームに伸ばし、区切りの個数 A が既定に依るように）
- `sim/tb_t4adc.v`（新、`make sim-t4adc` / `sim-t4adc-p`）: S-2。time_core 1 個 ＋ win_core（NW 2）× 4 を BD と同じくつなぎ、ADC ごとに入力の始まりを 37·i クロックずらす。8 窓・TP 4 本が T = START_AT + 1 に RUN、RUN_T・TP_RUN_T、2 回目の予約は ARM したコアだけ。陽性対照は ADC 3 の時刻のバスを 1 段遅らせる

別の目（サブエージェント）で proj016 との差分を読ませて直したこと:

- `fine.py` の窓の FLAGS の判定のマスクが **[4] を含んでいた**（窓の FLAGS[4] は「FFT IP に待たされた」で rev2 から正常。TP の FLAGS[4] = 振り切れと取り違えた）→ window.py と同じく外し、[10]（ddc の追い越し）を足して 0x7EF に。実機で全窓が毎回 NG になるところだった
- `fine.py` の窓の DUMP_T のずれを 0 ちょうどで判定していた → T-1 と同じ ±16（proj016 の実機は 30 分で 0）
- `fine.py` の TP の時刻の間隔の判定が、区切りの番号の連続と同じ内容で何も足していなかった → 始めと終わりの TANCH の組が 512 ビート / フレームで結ばれること・GAP_CNT が増えていないことに置き換えた（錨の式の前提そのもの）
- `check_tp.py` に負の側のしきい値ちょうど（−32764）が無く、RTL の負の側を `<` にしても通った → −32764 と −32760 を入れ、「+32764 だけ」「−32764 だけ」で立った区切りがリングの窓の中に在ることを D に
- `tb_t4adc.v` の判定 3 が ARM していないコアの一部しか見ていなかった → 11 コアとも。`sim-t4adc`・`-p` を `sim-t-all` に入れた

sim で分かったこと:

- **陽性対照（ADC 3 の時刻のバスを 1 段遅らせる）で、コアの RUN_T のレジスタは START_AT + 1 のまま**だった（外から見た RUN は +1 遅れて NG）。コアの中の時計も同じだけ遅れるので、遅れた RUN を遅れた時計で読む。**時刻のバスの段の食い違いはコアの自己申告（RUN_T・DUMP_T）では見えない**。見るのは build.tcl の結線の照合（直に繋がっていること）と、sim の外からの観測、実機では閉ループ（F-2）だけ

### PS（`pynq/`）

- `spectrometer.py`・`window.py`: 4 ADC・proj017.bit・ID・TP_PARAM の版 2
- `timebase.py`: **adc_to_core_ns を ADC ごとに**（`sample_utc_ns(beat, ns, adc)`）。proj017 は 4 本とも未較正（F-2 で入れる）。proj016 の ADC_A の 121.2 ns は持ち込まない
- `timetest.py`: 4 ADC × NW 窓（`--ns` は ADC の順・窓の順に 8 個、既定 1,2,3,4,5,6,1,6）、TP 4 本を同じ予約で ARM、RUN_T を 13 コアで照合（F-1）、`--t2-adc 0,1,2,3` で閉ループを ADC ごとに（F-2。FULL_SEL を切り替えて SRST）
- `fine.py`（新）: **F-4**（40.96 ms・44,000 ダンプ ≒ 30 分、8 窓のスペクトルと 4 ADC の TP を全部読む。窓は SEQ・DUMP_K・DUMP_T のずれ ±16・健全性・FLAGS（[4] 待たされた を除く）、TP は区切りの番号が 512 ずつ・読み落とし 0・FLAGS は [4] 以外 0・始めと終わりの TANCH の組と GAP_CNT、**8 窓の DUMP_T − D(NS) の一致・TP の区切りとの一定のずれ**、1 周の読み出しの時間。陽性対照 `--offgrid`）と **F-5**（ADC ごとの TP と、同じ ADC につないだ全帯域の TP の 1 フレームあたりの比）
- `timetest.py`: **格子の START_AT**（`start_at_grid`）と、**格子の START_AT での一斉の WRST**（`wrst_on_grid`: 窓の設定を書いて ARM_WRST、WSTART が ADC の中で全窓同じことを照合）。T-1 の RUN も格子に。`--tint` の既定 40.96 ms

## 結果

### sim（2026-10-02、クラウドの iverilog 12）

| sim | 中身 | 結果 |
|---|---|---|
| `sim-tp`（S-3） | tp_core 単体。FLAGS[4] を含めリングの 512 個が模型と bit 単位で一致。窓の 512 個のうち 280 個に [4]、+32764 だけで立った区切り 81・−32764 だけで 98。**時刻の格子の後に TP_N の既定 512 で回し直した**（TP_WP 537 が模型と一致） | **通過** |
| `sim-tp SIM_TP_POSCTL=2` | 陽性対照: しきい値の ≧ を > に | **落ちた**（B の食い違い 156 個）= 見張りは効いている |
| `sim-tp SIM_TP_POSCTL=1` | proj013 からの陽性対照（F0 の素朴な判定） | **落ちた** |
| `sim-wgrid`（S-4、時刻の格子の後） | wspec_core × 6（NS 1..6、G = 2^17）。RUN 3 回（格子の点の 70 ビート前・格子の真ん中・任意の位相）で RUN_F0 = 96 48 24 12 6 3 / 224 … 7 / 384 … 12、**F0·L が 6 窓とも同じ格子の点（3G・7G・12G）**、ダンプ 0・1 の DUMP_T − D(NS) − S0 が 6 窓とも (g0 + k)·G ちょうど | **通過** |
| `sim-wgrid-p` | 陽性対照: 格子に寄せない（F0 = fin + 2） | **落ちた**（NG 67 件。F0·L が 2 2 2 2 2 3 G など窓ごとにばらばら、DUMP_T − D の差 4096〜409600 ビート） |
| `sim-t4adc`（S-2） | time_core ＋ win_core（NW 2）× 4、入力の始まりを ADC ごとに 37·i クロックずらす。**8 窓・TP 4 本が T = START_AT + 1 = 3085 の同じクロックに RUN**（ずれ 0 × 12）、RUN_T・TP_RUN_T・FIRED、2 回目の予約は ARM した ADC 1 の窓 1 だけ。TP の F0 は ADC 0 がフレーム 8・他は 7（ADC ごとのフレームの格子） | **通過** |
| `sim-t4adc-p` | 陽性対照: ADC 3 の時刻のバスを 1 段遅らせる | **落ちた**（ADC 3 の 3 コアが T 3086）。**RUN_T のレジスタは落ちない**（上の「sim で分かったこと」） |
| `sim-spec-all`（回帰） | spec_core 一式（SHIFT 7・4、TLAST の陽性対照、起動の途切れ・見張りなしの陰性対照、gb、tp 3 通り）。ID 0x0017_0100・TP_PARAM 版 2 | **全部通過** |
| `sim-t-all`（回帰） | time_core（S-T1、ID 0x0017_7101）・dstamp（S-T2 の 4 変種）と陽性対照 2 つ | **通過**・陽性対照は落ちた（6 件・8 件。proj016 と同じ） |
| `sim-top`（回帰） | win_core を AXI 越しに端から端まで（ID 0x0017_0100、tp_core 版 2 を含む） | **全部通過** |
| `sim-tsys`（回帰） | time_core ＋ win_core（NW 2）＋ spec_core（S-T3・S-T4） | **全部通過**（4 コアとも T 8332 に RUN、窓 0 のダンプの間隔のずれ 0） |

**時刻の格子（wspec_core の F0・dstamp・TPN_DEFAULT）の後に回し直したもの**（2026-10-03）: sim-tp 3 通り・sim-wspec（5 変種と陽性対照 2 つ）・sim-wstamp（4 変種、陽性対照は落ちた）・sim-t4adc・sim-wgrid・sim-spec-all・sim-top・sim-tsys がすべて通過（古い試験台は G_L2 = 12 で従来の F0 = fin + 2 の形）。sim-win4 は回し直していない（win_core を G_L2 = 12 で使うので wspec_core の振る舞いは従来と同じ。1 時間級）。

sim-win-all のうち wspec 以外（pfb・ddc・win・hb2s・pfbm）は回し直していない: 使う RTL（`pfb_core.v`・`ddc_core.v`・`hb2*.v`・`pair2.v`・`nco_rom.v`・`dft16f.v`・`cmul.v`・`win_coef.vh`）は proj016 と同一（`cmp`）。

### ビルド・実機

（未）

## 結論・次にやること

（未）
