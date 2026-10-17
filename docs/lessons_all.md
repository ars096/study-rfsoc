# 知見の全部（lessons_all）

[`LESSONS.md`](../LESSONS.md)（要点）に入れなかったものも含め、proj001〜023 の README から拾った知見を**すべて**置く。
LESSONS.md は毎回全部読むもの、ここは**診断のときに語で引く**もの（「tready」「segfault」「CDC」「SHIFT」など）。

- 見出しは LESSONS.md と同じ。1 項目 = 規則 ＋ 理由（踏んだ症状）＋ 出典の proj
- **削除しない。** 後の proj で覆ったものは「← projNNN で覆った」を付けて残し、新しい結論を隣に書く
- 新しい知見はまずここに足す。次の proj でも踏みそうなものだけ LESSONS.md にも載せる。LESSONS.md から外すときは、ここに在ることを確かめてから外す
- 固定値は [`VERSIONS.md`](../VERSIONS.md) が正

## 版・環境

- Vivado 2024.1・board files の固定 commit・PYNQ v3.1.1 の組を崩さない（値は VERSIONS.md）。— RFDC は `xrfdc`・`xrfclk` と IP の版が結合し、ずれると動かないか静かに違う値を読む（proj002・runbook）
- board files は Vivado のインストールツリーの外に clone して commit を記録し、`board.repoPaths` は build.tcl・Makefile で持つ。— 版表記 `1.0` のまま DDR の行アドレス数が修正されている。`Vivado_init.tcl` は GUI とバッチで食い違いうる（VERSIONS.md・runbook）
- `settings64.sh` を `.bashrc` で source しない。Vivado は Makefile の `XILINX_VIVADO` から絶対パスで叩く。— `LD_LIBRARY_PATH` が汚れ、git・ssh・python が壊れる（runbook）
- Makefile でディレクトリ名と同じターゲット名を暗黙に作らない（`build` は `all` の別名として明示）。— `make build` が `'build' is up to date.` で何もせず正常終了した（proj007）
- proj を複製したら、`set proj`・Makefile の DCP の場所・program.tcl の bitname・PS の BITFILE と ID の期待値・`feat_rev()` をその場で直す。— proj014 の program.tcl が proj013 の .bit を探していた。複製で ID が rev1 に戻り、PS が GRST などの古い道に落ちるところだった（proj012・015）

## RFDC・クロック

### RFDC の設定
- RFDC の CONFIG は「スライスを有効化 → スライスの設定 → PLL → Sampling Rate → Refclk → Outclk」の順に 1 つずつ入れ、全部読み返す。失敗した項目と許容値は `rfdc_params.rpt` に書き出す。— 有効化の前のタイル単位の設定は `BD 41-721` の 1 行で無視される（proj003）
- Sampling Rate は (1.0, 5.0) GSPS、Refclk は VCO / FeedbackDiv の離散リスト、VCO は 8.5〜13.2 GHz。3 つを同時に満たす。fs を先に決めないと refclk の選択肢が出ない。— 983.04 MSPS は下限で弾かれた（proj003）
- fs 4096 MSPS はタイル PLL R 1 / N 25 / M 3（LMX 491.52 MHz、VCO 12288 MHz）。M 2 では VCO の下限で fs ≥ 4.25 GSPS になる（proj009）
- タイル内の全スライスの Data_Width は 1 回の `set_property -dict` で揃えて入れる。— 1 本ずつだと IP_Flow 19-3478 で中間状態が弾かれ、4 スライスとも既定の 8 から動けなかった（proj009）
- fs 4096 MSPS・Real・デシメーション 1 で 1 語に出せるサンプル数は 7〜12（16 は不可）。12 サンプル / 341.33 MHz で受け、ギアボックス（gb_up ×4 → 非同期 gb_fifo → gb_dn ÷3）で 16 サンプル / 256 MHz に詰め替える。— 16 を指定すると黙って 8 に戻り、Fabric_Freq 512 MHz を返した（proj009）
- RFDC の AXI4-Stream には TLAST が無い。DMA S2MM へ流すときは自作のゲートで TLAST を作る（proj003）
- RFDC の下流は待機中も `tready = 1`（受けて捨てる）。— backpressure をかけるとサンプルを落とす。取りこぼしの印は `BlockStatus['IsFIFOFlagsAsserted']` だけで、`GetIntrStatus` は無い（proj003）
- ビットストリームのロードでタイルは起動し PLL もロックしている。`StartUp()`・`DynamicPLLConfig()` は呼ばず、状態を読むだけ（proj003）
- IF 2〜4 GHz は `NyquistZone = 2`。スペクトルは反転し、全帯域の ch k は IF 4096 − 0.5·k MHz。ゾーンは読み返して照合する。— BLE の 3 チャネルで向きを実測で裏づけた（proj009・013）

### クロックの源と起動
- AXIS クロック（`Fabric_Freq`）は IP から出ないので、`clk_adcX`（`Outclk_Freq` = fs/16・/32・/64）を MMCM で逓倍して作る。— PS の PL クロックでは fs/8 ちょうどを作れず、FIFO が溢れるか枯れる（proj003）
- 制御系（AXI4-Lite）は `pl_clk0` に置き、MMCM の `locked` を `rst_adc`・`rst_dsp` の `dcm_locked` に入れる。PS の PL クロックは要求どおりとは限らない（200 を要求して 175 MHz）ので `CONFIG.FREQ_HZ` を読み返す。— `clk_adc` はタイル起動後にしか出ないので、制御系を載せるとタイルを起動できない（proj003）
- 全タイルの AXIS クロックは Tile 226 の `clk_adc2` から作る 1 個の MMCM に依る。複数タイルの `ShutDown()`・`StartUp()` はせず Overlay を焼き直す。— `state 14`・`state 3` で落ち、源を先にしても成立しなかった。源のタイルを止めると AXIS クロックの位相も動く（proj008・012）
- `rst_adc` はタイルの数の幅にして、タイルごとに別のフロップ（xlslice）から配る。タイルが 1 つなら切り出さない（xlslice は DIN_WIDTH 1 を受けない）。— 1 個のフロップを 2 タイルの同期段へ配ると CDC-11 が Critical 2 件（proj012・016）

### 外部基準・LMK・LMX
- CLK_IN の SMA は LMK04828 の CLKin0。外部 10 MHz にするには出荷時のファイルの `0x0147` を `0x1A → 0x0A` にするだけで、PLL1_N・VCXO・PLL2 以降は触らない（位相比較 80 kHz のまま）（proj004）
- 外部基準が効いているかは `PLLLockStatus` では分からない（それはタイルの PLL）。ppm（CW のサブビン補間）か PPS の間隔の残差で判定する。— 基準が無いまま locked = 2・DMA 完走で +90.68 ppm ずれていた（proj004・007）
- クロック源を変えたら Overlay を読み直す。内部基準との比較はケーブルを抜かず、出荷時のレジスタを書き直して取る。— タイルはロード時の LMX を掴む。LMK にはホールドオーバがある（proj004）
- ボードの道具は `--clkin 0 --ref 10` を必ず付ける。— 付け忘れると基板の発振器で動き、timebase が −15.4 ppm で止まった。W-1 が 1 ch ずれた（proj014・020）
- LMX2594 の出力は PWR 3（specd `--lmx-pwr` の既定）。書き直しは setup_clocks の後、Overlay() の前。— n × 163.84 MHz の櫛は LMX の出力 491.52 MHz の経路から出ていて、PWR 3 で −5.7 dB。ロック・位相雑音は PWR 0 まで変わらない。VCO が出どころという見立ては外れた（proj019）
- `xrfclk` のディレクトリに `_` を 2 つ以上含む .txt を置かない。v3.1.1 の関数は `set_ref_clks(lmk_freq=…, lmx_freq=…)`。— `_read_tics_output()` が `_` で 2 分割して落ちる。私有関数の名前も版で変わる（proj004）

### 起動の直後
- Overlay の直後（〜5 s）は RF-ADC の背景較正が収束していない。取得の前に `--settle` を置く。— 直後はインタリーブのイメージが −33〜−39 dBc、5 s 後は −53〜−66 dBc（proj009）
- DSP ドメインのコアは `check_tiles` と待ちの後で AXI4-Lite で読む。— MMCM のロックと `rst_dsp` の明けの前に読むと SmartConnect が応答を待ち続け、PS ごと止まった（再起動が要った）（proj021）
- 起動の途切れは守りを重ねる: ギアボックスのしきい値 K = 2・入力が 64 µs 途切れず続くまで口を開けない見張り・FLAGS・自動のやり直し。— K = 0 は Overlay の途切れ 27/80、K = 2 で 0/80（proj011・012・021）← proj011 の既定 K = 0 は proj012 で覆った
- 起動の途切れには 2 つの型がある。早い型は最初の valid から 2・8・20 クロック目（GRST でも起き、gray の遅いビットの模型 3(2^b − 1) に合う）。遅い型は 17036 クロック目ちょうどで Overlay だけ（原因は未解明）。静的解析（`gb-cdc`）では決められない（proj011・012）
- proj015 から GRST は無いので、ギアボックスの起動の試験は Overlay の読み込みを繰り返す（gbboot、50 回）。— K 0 は 50 回中 13 回、ADC_A だけに空振り。どの ADC に出るかは配置で変わる（proj021）

### 時刻の遅れ（M・D）
- ギアボックスや ADC の道の遅れを変えたら、F-2 で ADC → コアの遅れ M を測り直し、timebase.CAL に bit の ID ごとに入れ直す。前の proj の値は持ち込まない。— 1b のスキッドで M が +21〜+26 ns 動いた（予言で足し忘れた）。配置で adc_to_core が数 ns 変わる（proj020・021）
- F-2 の M は Overlay ごとに 4 ADC 共通で ≒ 0.9 ビートずれる。ケーブルを入れ替えた 2 回の平均で取る（proj021）
- PPS → ADC の閉ループの M は全帯域の生サンプルで測る。タイル 226 は 224 より ≒ 1 ビート遅い。— 狭い窓には縁のエネルギーがほとんど来ない（15 回中 2 回）（proj016・017）
- 窓のサンプルの時刻は DUMP_T − D(NS)、窓どうしの区切りの比べではさらに X(NS) を引く。RTL を変えたら `make sim-wdelay` で出し直す（proj016・017）
- WSTART・TP の区切りの格子は ADC ごとの最初の valid が原点で、タイル・Overlay ごとに位相が違う。ADC 間は T（DUMP_T）で比べる（proj017）

## FFT IP（Xilinx xfft、realtime）

- realtime の IP は**流し始めた後に 1 回 tready を下げる**（入力が途切れる幅なら、途切れの後の面の頭ごとにも 1 クロック）。IP の手前の段は tready を守る（溜め・待ち行列で受け、IP が受けたときだけ進める）。— 守らないと受けなかった 1 語ぶん枠がずれ、TLAST 事象が立ち続ける（proj011 FLAGS[3]・proj014 rev2 WS_STALL・proj023 4b）
  - ← proj023 4b の「口を開ける前に tready が続くのを待つ」「設定（config）は口の前だけ」は効かなかった（害は無い。tready が下がるのは流し始めた後）
- realtime の IP は入力の途切れを待たずに進む（`event_data_in_channel_halt`）。以後 TLAST の検査と frame_started の数えが入力とずれたままになる（データの枠はずれない。IP のリセットで戻る）。— 起動の 2〜5 割で TLAST 事象が立ち続け、それでも `--golden` は通った（proj011）
- FLAGS[4] の意味は proj ごとに違う（窓では「待たされた（データは保った）」、TP では振り切れ）。判定とマスクで取り違えない（proj014・017）
- realtime の IP の手前にはフレームの溜め（2 面）を置き、1 フレームを途切れなく流す。nonrealtime にすると CE の大ファンアウトが最悪経路になる（proj010・014）
- IP の入口から出口までの遅れ（出口の k1 の位相）はコアの間で揃う保証が無い。出口の k1 で引く ROM はコアごとに、T だけで引く ROM は共有してよい。— 共有のひねり係数 ROM で、タイル 224（C・D）だけ tw_mis が立ち続けた（proj023 4b 6 回目。差の原因は調査中）← proj022・023 の「ひねり係数も 4 ADC で 1 組」は覆った
- IP の CONFIG は 1 つずつ入れて読み返し、違えば止める。— `number_of_stages_using_block_ram` 7 は IP_Flow 19-3461 の後で 4 に戻った（proj011・022）
- IP のポートの照合は合成 VHDL の entity 宣言の中だけを読む。— component 宣言は設定に依らず全ポートを持ち、照合が「在る」と嘘をついた（proj011）
- 512 点の IP 1 個の DSP 50 = 複素乗算 7 × 4 ＋ バタフライ 22。`use_mults_resources` で −7、`use_luts` で −22。realtime は DSP を減らさない（理由はタイミング）（proj011）
- 窓の FFT は res/lut（30 DSP / 個）。バタフライを DSP にすると +34 / 個（proj014）
- IP の中の LUT の記憶は分散 RAM ではなく全部 SRL。BRAM の段数を増やしても LUT は 1 段で −70 / 個。LUT の大半はバタフライと長さ切り替え（proj022）
- 長さの実行時切り替えは使わない（LUT が 1 個 +713、64 個で 46k）。固定長にして ch の束ねでモードを作る（ch の応答も平ら）（proj023 D-7）← proj014 の長さ切り替えは覆った
- unscaled でも IP は各段の積を入力の LSB で丸め、後段で増幅されて一定の床になる。倍精度の模型と比べる判定は丸めの模型（`ipround_model.py`）で許容を作るか、SHIFT 7 で比べる。— SHIFT 4 では 18 ch が許容を超えた（枠のずれではない）（proj010・015）

## Vivado・build.tcl の見張り

### part と PS
- part は合成の前に要求値と照合する。実機の .bit も `-1` でビルドし、PS は `make ps-preset` の `src/ps_preset.tcl` を当てて読み返す（DDR4-2400 と 533 MHz の組は `-1` で外す）。— board_part は part を `-2` に引き戻す（Project 1-153）。同じ RTL が `-2` +0.007 / `-1` −0.767 ns（proj015）← proj014 までの「`-1` は合否の確かめだけ」は覆った
- `-1` の検証ビルド（`build-1-e*/`）はプリセットを当てていない。実機に載せない。BUILD の指紋（速度グレード・プリセットの有無）を PS で読み、無ければ止める。— scp の glob で 4 つの .bit が同名に上書きされていた（proj009・011）
- 使わない PS の AXI マスタ（`M_AXI_HPM1_FPD` 等）は明示的に 0。— プリセットが有効にし、`BD 41-758` で落ちる（proj002）
- `get_board_parts` の結果は `close_project` の前に使う（後は null）（proj015）

### XDC と run のログ
- XDC には制約だけ（`if`・`foreach`・`lsort`・`concat` はその行ごと実行されない、Designutils 20-1307）。存在しないかもしれないクロックは XDC に書かない。`set_bus_skew` を名前で書かない（proj003・006・016）
- run の CRITICAL WARNING は runme.log から build.tcl の末尾で拾い上げる。— make のコンソールに出ず、WNS −4.556 ns の .bit が完走した（proj003・006）

### BD と結線
- BD に入れる自作の RTL は `add_files` と 1 対 1。— iverilog は直接ファイルを渡すので漏れが sim に出ず、`filemgmt 56-587` で落ちた（proj007）
- 外部ポートは `create_bd_port` で作り、実装後に配置を読み返す。`make_bd_pins_external` はポート名に `_0` を付けて XDC と食い違う（proj007）
- Tcl の `expr` に `"01"` のような文字列を渡さない（`1` に化ける）。文字列の分岐は `if` で。— `vin0_1` になってアナログ入力が見つからなかった（proj006）
- つながない入力ポートは xlconstant で結ぶ。— CRITICAL WARNING BD 41-759（proj021）
- AXI4-Lite の口の番地幅を変えたら、build.tcl の番地の範囲（win_range）も直す（proj021）
- 条件によって作らない IP は、OOC の先回しのリストにも同じ条件でだけ入れる。— `can't read "xfft"` で止まった（proj021）
- ch ごとの点対点の結線は 1 つの表から張り、同じ表で両側（在るべき相手・他の ch のセルが無い）を照合する。陽性対照を build.tcl に常設する（proj012・023）
- 共有の ROM の番地を出さないコアの出口は「どこにもつながっていない」を照合する（在ってはいけない側。「無いピン」に OK と言わない陽性対照も）（proj023）

### 合成ログの見張り
- 自作のセルの OOC のログに Synth 8-3848（ドライバの無いネット）があれば止める（Xilinx の IP の run は対象外）。— wide_s45_core の s_axi_arready の駆動漏れを 4 コアぶん警告していたのに拾わず、PS は別のレジスタを読んでいた（proj023）
- `$readmemh` の hex は絶対パスで CONFIG に渡し、生成されたラッパの `.COEF_FILE("…")`・OOC ログの Synth 8-4445・配置後の ROM の BRAM 数（予言の半分以上）で照合する。— OOC は run のディレクトリで走るので相対名は届かない。読めないと ROM が 0 になり BRAM が消えるだけ（proj023）
- URAM（URAM288）は初期値を持てないので ROM は BRAM に置く（proj023）
- OOC で DSP を数えるときは report_utilization の表から読む。— `ARITHMETIC.DSP.*` は DSP48E2 1 個を 9 個に数えた（proj015）
- 共有の ROM の配りに足した段は `dont_touch` を付け、残った FF の数を build.tcl で数える（0 なら DSP に吸われた）（proj023）

### Vivado が落ちる
- Vivado 2024.1 は OOC・synth_1・impl_1 で終わり際に落ちる（`Abnormal program termination (11)`・tcmalloc abort (6)・Synth 8-7098 Stack limit。毎回違う run）。runme.log の `^ERROR` では見えないので落ちた印を探し、落ちた run と、それに依って始まらなかった run（runme.log が無い）だけを 2 回まで回し直す（JOBS 8）。`wait_on_run` の Tcl のエラーは catch で受ける（proj012〜015・023）
- run は名前の文字列で持ち、その場で `[get_runs $n]` を渡す（proj015）
- 負の経路の塊の集計は build.tcl の中で設計を開いたまま出す。— `make worst-paths` で配置後の dcp を開くと segfault した（proj023）
- dcp は glob でなく `set proj` の名前で 1 個に絞る。ビルドのディレクトリに古い proj の成果物を残さない。— 古い proj020.runs の dcp を読んで取り違えた（proj021）

### 再現性
- 同じ RTL の作り直しは WNS・WHS まで小数 6 桁で再現する。構成替えの確かめは旧 proj との diff（WNS・CDC の分類別件数・資源・CRITICAL WARNING）で行う（proj021）
- RTL の定数（BUILD_TAG など）に commit やビルド時刻を入れない（配置が組み替わる）。版を .bit に焼くなら USR_ACCESSE2 の案がある（未決）（proj011・021）

## タイミングの定石（`-1`・256 MHz）

- 合否は `-1` で閉じること（資料が食い違うので遅い方に合わせた）（proj012・013）
- 既定の戦略で閉じなければ `IMPL=Performance_Explore`。並べるなら `Performance_ExtraTimingOpt`・`Performance_ExplorePostRoutePhysOpt` も（良し悪しは毎回入れ替わる）。PEPRPO は WNS が負でなければ PE と同じ結果。`Performance_NetDelay_high` はかえって悪い（proj015・020・021・023）
- 数 ps なら作り直さず配線後の `phys_opt_design`（`make physopt`: AggressiveExplore → AggressiveFanoutOpt → AlternateReplication → Explore）。— −0.0045 → +0.011 ns（proj021）
- WNS は配置の組み替わり（ID の定数 1 つでも）で ±0.1〜0.2 ns 動く。予言は幅で書く。`-1` の方が `-2` より余裕が出ることもある。余裕が数十 ps の bit は、RTL を少し変えると負に戻る前提で扱う（proj011・013・014・023）
- `-1` で閉じないときは `make worst-paths` で群に分けて段を入れる（選択の後・和を 2 項ずつの木に・BRAM の書き込みを 2 段で受ける・DSP の手前の hist をリセットしない・読み出しの mux を 1 段）（proj015）
- フレームの頭でしか使わない幅のある加算・比較は `pre_*` レジスタに前もって計算する。— spec_core の `cur_k → t_last`（proj011）を、写した wide_spec が再び持ち込んだ（論理 14 段、−0.561 ns）（proj011・023）
- ファブリックの加算の出口をレジスタを挟まずに DSP の A/B に入れない（AREG/BREG = 2・MREG・PREG）。加算木は 1 段ごとにレジスタで区切る（proj012・013）
- 飽和や和の後のレジスタを Vivado に DSP へ取り込ませない（dont_touch）。— 論理が DSP の入口（セットアップ ≒ 0.3 ns）に直に入る形が wspec・u_pfb・dft16 で壁になった（proj021）
- 共有の ROM の配りに足す段は dont_touch。— 無いと DSP の A 入力のレジスタに吸われて消えた。1 段では ROM から遠いコアまでの 1 回の飛び（≒ 3.2 ns）は割れない。割るなら 2 段か ROM の複製（proj023）
- DSP の出口どうしの加算にレジスタを付けると、加算木の最初の段も DSP に載る。見積もりに含める（tp_core 予言 16 → 24 / ch、wspec 窓ごと +2）（proj013・014・015）
- 準静的な高ファンアウト信号（WRST でしか変わらないもの）は `max_fanout` の複製で配る。使わない選択器は置かない。— c_ns（FO 1,830）・axis_sel4 の選択の bit（FO 303）が壁に出た（proj016・017・021）
- リセットはコアの中で 3 段受けてから配る。FFT IP のリセットはレーンごとに 1 段（dont_touch）受ける。— rst_dsp → DSP の CE、rstn_q2 → IP の BRAM の ENBWREN（−0.008 ns）が出た（proj021・023）
- IP の tready を段全体の CE に配らない。段の後の FIFO（深さ 16）と出口のレジスタで受け、読みは貸し借りで出す（proj020）
- CRC-32 は for 文でなく展開した XOR の式で書き、入力を 1 段受ける。— for 文は 13 段の LUT の鎖で −0.7 ns 前後（proj021）
- 規模が効くのは並ぶものではなく、1 か所に集まるもの（1024 bit の FIFO）と大ファンアウト（gb_fifo の書き込み番地 FO 888、gb_up の状態 FO 195）。ギアボックスの出口からの分岐は 1 段挟む（proj009・012・013）
- 群 C（gb_gate の armed → gb_fifo の読み出し許可 FO 780）は gb_gate の入口の 2 語のスキッドバッファで切ってある。ギアボックスの遅れが +2 語（≒ +23 ns）になるので F-2 をやり直す（proj015・020・021）

## 設計の規約

### 時刻・フレーム
- 時刻の物差しは DSP のクロックの数 T（256 MHz・16 並列、64 bit、1 s = 256,000,000 ビート）。12 並列・341 MHz では 1 秒が整数にならない（proj009・016）
- PPS は毎秒のトリガにせず、発火は `T == START_AT`、PPS は原点と残差の監視に使う。— 毎秒叩き直すとジッタがデータの時刻に乗る。水晶のホールドオーバは −111 ppb（proj007）
- 予約発火には `late` を持たせ、一致検出は上位と下位の 2 段に割り、`start_at − 1` で trig を出す（proj007）
- ARM したコアは T = START_AT + 1 で RUN を受ける。ARM_RUN と ARM_WRST を両方かけたら RUN は WRST の明けまで待つ。コアの予約は発火・STOP・取り消しでしか消えないので、PS が time_core とコアの両方を取り消す（DISARM）（proj016・018）
- `epoch` は `ctrl_aclk`（rst_ctrl）側に置き、PS は snapshot の前後で比べる。原点は MMCM ロック後の `rst_adc` の解除（proj007）
- 1PPS の立ち上がりは TRIG（AH13）でスタンプし、COMP（AJ13、オープンドレイン、58.6 ns 遅れ）は監視に。`pps_pol=0` が真の立ち上がり（proj007）
- PPS の同期器はリセットで 1 から始める。— 0 だと解除の瞬間に偽の縁が出た（proj016）
- 時刻のバスの段の食い違いはコアの自己申告（RUN_T・DUMP_T）に出ない。結線の照合と外からの観測で見る（proj017）
- 較正定数は bit の ID（MAGIC・PROJ）と対にして持ち、一致しなければ適用を拒否する。タイルの再起動で整数ビート N が、Overlay で小数部も変わる。符号を 2 回逆に書いた（proj007・008）
- フレームの頭は T の格子に揃える（T ≡ K_F mod 2048、F0 = (⌊fa/M⌋ + 2)·M）。DUMP_T = K_F ＋ 2048·DUMP_F0。— 4 ADC で係数 ROM を共有でき、r = DUMP_T − m·BASE が Overlay ごとに変わらない（proj021 は変わった）（proj023）
- ダンプの区切りは秒に揃えず毎回同じ N フレーム。幅の違う窓は時刻の格子 G = 2.048 ms（START_AT は G の倍数）で揃え、dt は G の倍数。⌈(fin + 2)/M⌉·M にすると M = 1 の窓だけ 1 個先の点に行く（proj016・017）
- 「どのフレームを積んだか」はフレーム番号（fin・fout）と F0 で持つ。スナップショット・TP の区切りも F0 に揃える（proj010・013）
- SHIFT・CFG_ID は RUN の時点で取り込み、RUN の間の書き込みは次の RUN から。再 RUN は STOP の後 1 ダンプ待つ（proj016）
- 1 フレームは 8192 / 4.096 GS/s = 2.000 µs（2.048 ではない）。— `--every 20` が 19.53 ms になっていた（proj019）
- DUMP_T などの時刻を付ける部品は、口の s_axis をそのまま数える（1 段受けると 1 ビート後ろ）（proj021）

### 数え・判定
- 長く走るカウンタの判定は飽和する数えにする。— 32 bit の q が 16.8 s ごとに巻き戻り、12 フレーム ok が落ちていた（proj015）
- 区切りの判定は等号でなく `≥`（proj013）

### 語長・SHIFT・単位
- 丸めて捨てるのは SHIFT の 1 か所だけ。雑音の σ を ≫ 1 LSB に保つ（切り捨ては −0.5 LSB 偏る）（proj010）
- SHIFT は雑音の床が数 LSB²（判定では ≧ 16 LSB²）以上になるように、窓ごと・入力レベルごとに選ぶ。比を取る判定は飽和があれば NG にする。— 窓の FFT の出力は全帯域より 18 dB 大きく、SHIFT 4 では −20 dBm の CW でも窓の山が飽和した（proj014・017）
- FFT の入力の小数 G は NS ≧ 7（4・2 MHz）で 5。電力の予言は 64·4^(G−4)·4^ΔSHIFT（proj015）
- 絶対強度は abs = (Σp/N_ACC − 2/3)·4^SHIFT·4^(4−G)/2³¹（14 bit の LSB²、全 bit 共通）。−2/3 を引き忘れると 0.53 倍のような偽の値（proj019）
- TP は 14 bit の x（ADC の 16 bit >>> 2）の二乗の和、σ_x² = Σx²/(フレーム数·8192)。— /16 と誤って 16 倍に出た（proj019）
- PFB の係数は Σh² で規格化。原型 sinc × Kaiser β 5・bw 1.198・T = 4・18 bit を共通にする（和 / TP 0.9068）。← β 8・bw 1.00 は ch の間の谷で決め直した（proj020）
- PFB の立ち上がりでは r − 3 + t < 0 のタップを 0。重心は 1.5 フレーム前なので D_eff に 1.5·L を入れる（proj020・022・023）
- PFB の出口の最大利得は Σ|c| = 1.405（+2.95 dB）、最悪は ch の間ちょうどの CW（proj020・023）
- SLICE の ch → IF は (S0 + i + (B − 1)/(2B))·fs/N（N = 32768/B）。レコードに log2 B と S0_CUR を載せ、レコードだけで IF が決まるようにする（proj023）

### CDC
- 同期器には `ASYNC_REG` を付ける（無くても動作・タイミングに出ず MTBF だけ落ちる。CDC-2 が唯一の検出）（proj006）
- 自作の CDC を持たない。AXI4-Lite の乗り換えは SmartConnect（NUM_CLKS 2）（proj010）
- CDC は report_cdc の分類で読む（件数でなく launch・destination の名前）。毎クロック変わる組合せ出力は送り側で 1 段受けてから同期器へ。— CDC-10 の 34 件のうち実害は比較器のグリッチ 2 件（proj006・007）
- データ＋ハンドシェイクは PS が「値を書く → 同じ値に arm を足して書く」の順で叩く。その CDC-1 は既知として理由を残す（proj006・007）
- 既知の CDC: ギアボックスの FIFO 1 本で CDC-15 +768・CDC-3 +2、gb_adc の gaps_reg → gb_gate と epoch の gray の CDC-6。SmartConnect の M を 1 本足すと CDC-3 が増える（proj009・012・014・016）

### 多 ch・共有
- 多 ch の生サンプルは `axis_combiner` で 1 本に束ね、ゲートと同期器を 1 個に（CONFIG は `NUM_SI`・`TDATA_NUM_BYTES`）。— 4 レーンに並べると「ときどき 8 サンプルずれる」が起きうる（proj006）
- 生サンプルの取得長は FIFO 深さで上限し、build.tcl の帯域の検査を残す（4ch フルレートは HP0 で流せない）（proj006）
- 共有の ROM は番地も一緒に返し、各コアが自分の番地と照合して粘着の coef_mis・tw_mis を立てる（proj023）
- BUILD_TAG に ch の番号を載せ、PS はセル名と突き合わせる（proj012）

### レコード・リング
- PL → DDR の書き手は自作の AXI4（INCR、バースト ≦ 16 拍、4 KiB の境を越えない）。W はレコードの BRESP が全部 OKAY で返ってから進める（DataMover はやめた）（proj021）
- リングはレコード単位で順番に回し、空きが無ければ丸ごと捨てて DROP_CNT +1。凍ったバンクが読み終える前に上書きされたら tuser = 1 で捨て REC_LATE と DROP_CNT を増やす（DROP_CNT = SEQ の飛びの合計）（proj021）
- SEQ より先に上書きされる記憶（スナップショット）は `snap_ok` を 2 回見る（proj021）
- レコードの出口のリセット（rst_rec）を起動のやり直しのリセットと分ける。— SRST がレコードの途中に来ると rec_arb が tlast を待ち続けた（proj021）

### 構成
- ソースは src/common・src/<bit>・src/board に分ける（境目は「別の bit で中身が変わるか」、迷ったら bit 個別）（proj021）

## sim と模型

- FFT IP の行動模型に実機の振る舞いを入れる: リセットから tready を上げるまでの遅れ（FFT_READY_DELAY）、流し始めの 1 回の tready の下げ（FFT_STALL_AT・周期的な STALL）、入力の途切れ（halt で制御側の数えだけずらす）。模型を別の proj から写すときはこれも引き継ぐ。tready を守らない陽性対照（`-DWSPEC_NOREADY`・`-DIPQ_POSCTL`）を置く。— proj014 で入れた振る舞いが proj023 の模型に無く、同じ不具合が sim を通った（proj011・014・023）
- tb の AXI の手渡しの待ちは `!== 1'b1`。`while (!arready)` は z を「準備よし」と読む（proj023）
- tb で 1 本の `reg` を 2 つの手続きブロックから叩かない（後勝ちで試験が空振りする）（proj007）
- ソフトが依存する RTL の性質（リセット中に読めるもの・返らないもの）は tb で固定する。解析側の判定も実機なしで通す（numpy の `bool_` は `is True` に一致しない）（proj007・008）
- 自作部分は IP の前後で切り、整数の模型と bit 単位で比べる（IP の C モデルには合わせない）（proj023 D-3）
- 区切り（フレームの頭）は振幅の比べでは捕まらない。IP の手前の bit 単位の照合（A1'）と T の位相で見る（proj023）
- 照合の相手は同じ口の経路でなく、記憶の階層参照にする。— rec_fr の読みの遅れを数え違えても AXI4-Lite の照合は通った（proj021）
- tb はビートをコアの中のリセットが明けてから数える。iverilog では日本語をタスクの引数に渡さず `$display` に直に書く（proj021）
- 照合は最後の WRST の印より後だけ。tb は z を書いてから印を書き、待ちは段ごとのレイテンシの積もりを見込む（proj015）
- 刺激に満杯の区間（±最大値を 100 サンプル）を入れる。— 28 bit を 24 bit で宣言した誤りは満杯の区間でしか見えなかった（proj014）
- 確かめたいことを試験台の側で仮定しない。— S-4 が通ったのは試験台が最初の z の時刻を仮定していたため（proj017）
- 固定小数点の線は CW の ch そのものを除いて数える（NCO の定数位相を線と読んだ）（proj014）
- 半帯域の段は（偶, 奇）の組で受けるので、模型も入力を偶数個で切る（proj014）
- 幅を足すときは模型の PFB の通過域が `max(WIDTHS)` から決まることを確かめる。生成物は前の proj と cmp で 1 byte も違わないことを確かめる。係数は生成物としてリポジトリに入れる（proj014・015）
- 16 並列の並び順はトーンの純度（k·fs/16 ± f のスプリアス）で、奇数 m と偶数 m を分けて判定する（proj009）
- 変種と陽性対照は `make sim-…` で並べて回し、成否は各ログの「結果: 全部通過」で読む（proj011 以降）

## PS・PYNQ

### 起動とドライバ
- `import xrfdc` は `Overlay()` より前。`isinstance(ol.rfdc, xrfdc.RFdc)` で当たったかを確かめ、当たらなければ .hwh の VLNV と `RFdc.bindto` を見比べる（proj003）
- ロードは `Overlay()`（JTAG ではない。.hwh が送られずタイルも起動しない）。.bit と .hwh は同じ basename・同じディレクトリ（proj002・004）
- PYNQ の `blocks[]` は有効なスライスを 0 から詰める（slice 0/2 → blocks[0]/[1]）（proj006）
- 起動直後の粘着 FLAGS は消す前に読む（`--keep-startup-flags`、wide.py の起動の見張り）。— PS が起動直後に消していて、FLAGS[3]・[4] がずっと見えていなかった（proj011・023）

### MMIO・速さ
- MMIO は 1 回 ≒ 10 µs（rd64 ≒ 16 µs）。RUN を順に書くと 1 本 5 フレームずれるので帳簿（DUMP_F0）で揃える（proj012）
- AXI4-Lite の読み出しは 20.48 ms のダンプに追いつかない（実効 ≒ 8.9 MB/s）。dt 40.96 ms でも余裕 5 ms。速い dt はリング（DMA）で（proj015・019・020）
- A53 の Python・numpy の速さはボードで 1 呼び出しずつ測る（PC の見積もりの 10 倍遅い）。中央値は `np.partition`（proj021）
- Python の 1 本の取得 ≒ 0.20 ms × レコード数 ＋ 8.8 ms × MB。重い bit は取得を C にするかプロセスを分ける（proj021）

### リング・キャッシュ
- HP0 は coherent でない。キャッシュありのバッファで読み、読む前に [R, W) をまとめて 1 回捨てる（キャッシュなしは 81 MB/s で遅い）（proj021）
- PYNQ 3.1.1 の `invalidate()` は offset・size を使わず全体を同期する（64 MiB で 4.6 ms）。pyxrt の `bo.sync(FROM_DEVICE, size, offset)` を直に呼ぶ（版が変わったら測り直す）（proj021）
- PynqBuffer をレコードごとに切り出さず、素の ndarray の view と `tolist()` で読む（0.37 → 0.09 ms）（proj021）
- CMA は 128 MiB で allocate は 64 MiB まで（proj021）
- リングを閉じるときは REC_CTRL・TP_REC_CTRL を 0 にし、busy が落ちてからバッファを返す（返すと Segmentation fault）（proj021）
- キャッシュの陽性対照（`--no-inval`）では読み終えた先をわざとキャッシュに載せる（`--touch-ahead`）（proj021）

### 記録・サーバ
- 長い記録を Python のリストに溜めない（4 本 1 時間 ≒ 1.7 GB、メモリ 4 GB）。30 分に区切るかディスクへ流す（proj013）
- 取得の環は gc.freeze() → gc.disable()、CPU 固定・SCHED_FIFO。SIGINT・TERM は明示して受ける（proj018）
- ソケットは受け側の ACK まで記録を溜まりに残す（sendall の後に消すと切断で黙って消えた）。ACK 待ちの時間切れで接続を切らない（proj018・021）
- specd の LOAD は spawn で起こす（fork だと新しい版の s45proto が子に持ち込まれる）。LOAD をまたいで通し番号を続ける（1 に戻すと受け側が 122 個捨てた）。STATUS は `r.get(k, "-")`（proj021）
- specd は起動のたびに SET し、GET・STATUS を確かめてから START（tint が前の試験のまま一晩回った）（proj019）

### 時刻と較正
- 時刻は整数 ns（625/768 の整数演算）で扱い、差は整数で引いてから float にする（float64 の UTC ns は 256 ns 刻みで、閉ループ試験が偽通過した）（proj007・008・021）
- timebase の CAL と tp_cal.json は bit の ID を鍵にし、新しい bit は「未較正」で足して F-2 で埋める（proj020・023）

### 実行
- ボードのスクリプトは root で動かす（`sudo` なら `sudo -E $(which python3)`。素の sudo は venv を外れる）（proj004）

## 実機・測定

### 配線と信号源
- SMA のラベルとスライスの対応は逆順（ADC_A = Tile 226 / slice 2 … 値は VERSIONS.md）。ラベルから推測しない（proj003・006）
- Tile 224 と 226 は入力の極性が 180° 反転（周波数に依らない）。相互相関・合成では符号を揃える（proj006・008）
- この E8257D は 3.94 GHz で −10 dBm 以下が unleveled（`:STAT:QUES:POW:COND?` bit 1）。ALC は ON、`:POW?` は設定値を返すので、読み返しでは気づけない。−5 dBm では bit は立たないが出力は 6 dB 低かった。CW が雑音に沈み、H-2 の境目の判定が雑音だけの 2 ch で 0 dB になって OK と出た。sg.py が ON の間に bit を見て止める。低いレベルは 0 dBm 以上で出して固定減衰器で落とす（proj023 H-2）
- CW を使う判定には「CW が見えているか」（ch の電力 / 中央値）の線を必ず置く。比だけの判定は、CW が無くても雑音で通る（proj023 H-2）
- 試験音源は E8257D。APSYN420 は 100 MHz で方形波（H3 −9.3 dBc、広帯域の雑音で床が 1.3〜2.1 dB 上がる）（proj005）
- レベルは ADC 入力換算で、減衰量と構成を毎回記録する（0 dBFS ≒ +5.8〜5.9 dBm）。— 減衰量が残っておらず絶対レベルが 54 dB 合わなくなった proj がある（proj003・005・010）
- ボードと SG は同じ 10 MHz に載せる。SG の宛先の環境変数は root のシェルにも入れる（CW が無いまま測った）。E8257D の下限 −20 dBm 前後より下は固定減衰器（proj014・015）
- 試験台では ADC の前に高域通過フィルタ（2 GHz）。DC・fs/2 から 1 MHz 以内と、ch の端数 |df| > 0.4 の点に基準の CW を置かない（proj014・015）
- 1PPS を ADC に常時入れない（構成 B: PPS Clk だけ、科学 4ch、要求 100 µs）。← proj008 の一時の「PPS 1 本・科学 3ch」は覆った（proj008）
- 1PPS・10 MHz のケーブルは 800 MHz 帯の携帯電話の上りの主な入口（ボード単体の ≒ 7 倍）。終端していない分配器でさらに 2 倍。使わない口は 50 Ω で終端し、RF 分配器を裸で使わない（枝にパッド）（proj008・010・013）
- パワーメーター（E9300A）の前に 20 dB の固定減衰器。アッテネータ（J7211C）の設定値は基準にしない（段の誤差 ±0.15〜0.3 dB）。観測中に段を切り替えると入力が ≒ 3 ms 途切れる。ノイズソースは尖度 2.48 で TP の雑音の基準にしない（proj019・021）
- 揺れ（ラジオメータ式・アラン）は増幅した雑音を入れて測る。パーセバルの照合にはナイキストの ch（X_4096）も含める（proj013）

### レベルとスプリアス
- 入力レベルは HOT/R で −10 dBFS 以下、運転 ≒ −16〜−21 dBFS（−9.3 dBFS で TP が振り切れた）。窓の CW 試験は −20 dBm・SHIFT 11。試験の後は SG の出力を OFF に戻す（proj019・020・021）
- 試験音は fs/64 の倍数を避ける（像が 30〜40 dB 上がる）。狭い窓（≦ 8 MHz）は n × 163.84 MHz と k·fs/8 を避けて置く（proj019）
- 強い線の f ± k·fs/8 に −55 dBc 級のインタリーブの線（起動ごとに 5〜14 dB 揺れる、較正モード・周波数に依らない。仕様）。時間スキュー支配の予言は外れた（proj009・010・012）
- 入力が無くても立つ線: fs/8 の倍数、LMX 491.52 MHz の 5〜12 倍の高調波（値は VERSIONS.md）。無入力の 491.52・245.76・153.6・307.2 MHz は既知のクロックの回り込み（proj003・005・010）
- ADC のインターリーブの線は PFB の折り返し先（fs/8 の倍数）と重なる。窓の折り返しと分けるには全帯域の同じ IF に線があるかを見る（proj014）
- 入力なしの ch の揺れは DC と k·fs/8・fs/2 のインタリーブの線のちらつきに支配される（proj013）
- バラン MABA-011118 は DC 結合ではない（パルスは微分される）（VERSIONS.md）

### 比べ方
- 配線に依る値（窓の和 / TP、SG のレベル、PATT）は絶対値で予言せず、同じ配線のまま旧 bit を LOAD して比べる（予言から −1.7 % 外れ、旧 bit とは 0.06 % 内）（proj021）
- `--golden`（numpy 照合）は振幅の近さだけを見る。区切りのずれは別の判定で見る（proj011・023）

## 公開

- リポジトリは公開。commit の前に公開前のスキャンを全項目行う。コミットメッセージに `Claude-Session:` の行や URL を入れない（`Co-Authored-By` は可）
- リポジトリに書かないもの: ライセンスの Host ID・アカウント・`.lic` の内容・個人名・ホームパス・内部システム名・ホスト名・限定共有の URL

- **（proj023 4e）RAW の生サンプルと全帯域のスペクトルの T の付け方は、入口の段数で 1 ビートずれうる。** raw_core は口のビートに 1 クロック前の T（t_loc）を付け、wide_spec はデータと T を同じ段で受けて口のビートにそのクロックの T を付ける。実機では RAW の入口の axis_sel4 の 1 段が打ち消して D_S = 0。adc_to_core（F-2）は RAW で測るので、ほかの流れの D_S は「RAW と同じサンプルに付ける T の差」を sim で出す（sim-wds。陽性対照は RAW の口の段を外して +1）
