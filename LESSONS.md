# 知見の要約（LESSONS）

proj001〜023 で踏んだ穴と、次以降の proj でも従う決まりを 1 か所に集めたもの。
**新しい proj を起こすとき**と、**実機で説明できない症状が出て診断を始める前**に、必ず全部読む。

- 1 項目 = 規則 1 文 ＋ 理由（踏んだ症状）＋ 出典の proj。詳しい経緯は出典の README にある
- ここは**要点**。拾った知見の**全部**は [`docs/lessons_all.md`](docs/lessons_all.md) にあり、診断のときはそちらを語で引く（「tready」「segfault」「CDC」など）
- 固定値（版・SMA の対応・クロックのレジスタ値など）は [`VERSIONS.md`](VERSIONS.md) が正。ここには指し先だけを書く
- **proj を閉じるときに足す・直す。** 新しい知見はまず docs/lessons_all.md に足し、次の proj でも踏みそうなものだけここにも載せる
- **削除しない。** ここが長くなったら（目安 150 行）、使う頻度の下がった項目を docs/lessons_all.md に在ることを確かめてから外す。後の proj で覆ったら両方を書き換え、docs/lessons_all.md には「← projNNN で覆った」を付けて古い結論も残す

## 版・環境

- Vivado 2024.1・board files の固定 commit・PYNQ v3.1.1 の組を崩さない（値は VERSIONS.md）。— RFDC は `xrfdc`・`xrfclk` と IP の版が結合していて、ずれると動かないか、静かに違う値を読む（proj002・runbook）
- `settings64.sh` を `.bashrc` で source しない。Vivado は Makefile の `XILINX_VIVADO` から絶対パスで叩く。— `LD_LIBRARY_PATH` が汚れ、git・ssh・python が壊れる（runbook）
- proj を複製したら、`set proj`・Makefile の DCP の場所・program.tcl の bitname・PS の BITFILE と ID の期待値・`feat_rev()` をその場で直す。— 古い .bit を探す、ID が rev1 に戻って PS が古い道に落ちる、を踏んだ（proj012・015）
- → 全部: docs/lessons_all.md の「版・環境」

## RFDC・クロック

- RFDC の CONFIG は「スライスを有効化 → スライスの設定 → PLL → Sampling Rate → Refclk → Outclk」の順に入れ、全部読み返す。タイル内の全スライスの Data_Width は 1 回の `set_property -dict` で揃えて入れる。— 有効化の前のタイルの設定は警告 1 行で無視され、範囲外の値は黙って直前の値に戻る。1 本ずつ変えると IP_Flow 19-3478 で動けない（proj003・009）
- fs 4096 MSPS では RFDC は 1 語に 16 サンプルを出せない（有効値は 7〜12）。12 サンプル / 341.33 MHz で受け、ギアボックスで 16 サンプル / 256 MHz に詰め替える（proj009）
- RFDC の下流は常に `tready = 1`（backpressure をかけない）。— RFDC がサンプルを落とす。取りこぼしの印は `BlockStatus['IsFIFOFlagsAsserted']` だけ（proj003）
- AXIS のクロックは `clk_adcX` から MMCM で作る。制御系（AXI4-Lite）は `pl_clk0` に置き、MMCM の `locked` を `rst_adc`・`rst_dsp` の `dcm_locked` に入れる。— `clk_adc` はタイルの起動後にしか出ないので、制御系を載せるとタイルを起動できない（proj003）
- 全タイルの AXIS クロックは Tile 226 から作る 1 個の MMCM に依る。PS から `ShutDown()`・`StartUp()`・`DynamicPLLConfig()` を呼ばず、起動は Overlay に任せる。— 複数タイルの ShutDown は順序を直しても成立しなかった（proj003・008）
- SMA のラベルとスライスの対応は逆順で、PYNQ の `blocks[]` は有効なスライスを 0 から詰める。Tile 224 と 226 は入力の極性が 180° 反転している（値は VERSIONS.md）。— ラベルから書くと「DMA は完走するが中身は雑音」になる（proj003・006・008）
- IF 2〜4 GHz は `NyquistZone = 2` で取り、スペクトルは反転する。ゾーンは読み返して照合する（proj009）
- 外部 10 MHz は LMK04828 の CLKin0。出荷時のファイルの `0x0147` を `0x1A → 0x0A` にするだけ。**基準が効いているかは `PLLLockStatus` では分からない**（ppm か PPS の間隔で判定）。— 基準が無いまま locked = 2 で +90 ppm ずれていた（proj004・007）
- ボードの道具は必ず `--clkin 0 --ref 10` を付け、クロックの設定 → `import xrfdc` → `Overlay()` の順に呼ぶ。LMX2594 の出力は PWR 3。— 付け忘れると基板の発振器で動き timebase が −15.4 ppm で止まる。PWR が強いと n × 163.84 MHz の櫛が立つ（proj019・020）
- Overlay の直後は RF-ADC の背景較正が収束していない（〜5 s）。DSP ドメインのコアは `check_tiles` と待ち（`--settle`）の後で読む。— 直後はインタリーブのイメージが 20 dB 高い。MMCM のロック前に AXI4-Lite で読むと SmartConnect が応答を待ち続け、PS ごと止まった（proj009・021）
- 起動の途切れに備え、ギアボックスのしきい値は K = 2。— K = 0 では Overlay の起動の一部で、最初の数語が途切れる（proj011・012・021）
- ギアボックスや ADC の道の遅れを変えたら、F-2 で ADC → コアの遅れ M を測り直し、timebase.CAL に bit の ID ごとに入れ直す。前の proj の値は持ち込まない（proj020・021）
- → 全部: docs/lessons_all.md の「RFDC・クロック」

## FFT IP（Xilinx xfft、realtime）

- realtime の IP は**流し始めた後に 1 回 tready を下げる**（入力が途切れる幅なら、途切れの後の面の頭ごとにも）。**IP の手前の段は必ず tready を守る**（溜め・待ち行列で受け、IP が受けたときだけ進める）。— 守らないと受けなかったビートが消え、IP の枠が 1 つずれたまま TLAST 事象が立ち続ける。「口を開ける前に tready を待つ」だけでは止まらない（proj011 FLAGS[3]・proj014 rev2・proj023 4b）
- realtime の IP は入力の途切れを待たずに進む（`event_data_in_channel_halt`）。IP の入力は途切れなく流す（フレームの溜めを前に置く）。nonrealtime にすると CE の大ファンアウトが最悪経路になる（proj010・011・014）
- **IP の入口から出口までの遅れ（出口の k1 の位相）はコアの間で揃う保証が無い。** IP の出口の k1 で引く ROM はコアごとに置く。T だけで引く ROM は共有してよい。— 共有のひねり係数 ROM で、タイル 224 のコアだけ tw_mis が立ち続けた（proj023 4b 6 回目。差の原因は調査中）
- IP の CONFIG は 1 つずつ入れて読み返し、違えば止める。ポートの照合は合成 VHDL の entity 宣言の中だけを読む。— 範囲外は黙って既定に戻る。component 宣言は全ポートを持つので、照合が「在る」と嘘をついた（proj011・022）
- DSP は乗算器 3 乗算・LUT バタフライで減る（realtime は減らさない）。IP の中の LUT の記憶は SRL。資源は IP を 1 個だけ合成して数えてから予言する（`make survey`）（proj011・022）
- unscaled でも IP は各段の積を丸める。倍精度の模型と比べる判定は、丸めの模型で許容を作るか、SHIFT を大きめ（7）にして比べる（proj010・015）
- 長さの実行時切り替えは使わない（LUT が 1 個 +713）。固定長にして、ch の束ねでモードを作る（proj023 D-7）
- 入力の流れに空きがある（DDR から読む・忙しさ 100 % 未満）ときは、realtime の IP の手前でフレームの枠を途切れなく回し、そろわない枠は空のフレームで埋める。— realtime の IP（とその模型）はフレームの間の途切れも halt として数える（proj028 F-4）
- → 全部: docs/lessons_all.md の「FFT IP（Xilinx xfft、realtime）」

## Vivado・build.tcl の見張り

- part は合成の前に要求値と照合する。実機の .bit も `-1` でビルドし、PS は `make ps-preset` の `src/ps_preset.tcl` を当てて読み返す。— board_part は part を `-2` に引き戻す。同じ RTL が `-2` +0.007 / `-1` −0.767 ns だった（proj015）
- XDC には制約だけを書く（`if`・`foreach` はその行ごと実行されない）。`set_bus_skew` を名前で書かない。run の CRITICAL WARNING は runme.log から build.tcl で拾い上げる（proj003・006・016）
- BD に入れる自作の RTL は `add_files` と 1 対 1。外部ポートは `create_bd_port` で作り、配置を読み返す。Tcl の `expr` に `"01"` のような文字列を渡さない（proj006・007）
- つながない入力ポートは xlconstant で結ぶ。使わない PS の AXI マスタは明示的に 0 にする。— CRITICAL WARNING BD 41-759・BD 41-758 が出る（proj002・021）
- ch ごとの結線は 1 つの表から張り、同じ表で両側（在るべき相手・他の ch のピンが無い）を照合する。陽性対照も build.tcl に置く（proj012・023）
- 自作のセルの OOC のログに Synth 8-3848（ドライバの無いネット）があれば止める。— AXI の arready の駆動漏れを Vivado は警告していたが拾っておらず、PS は別のレジスタを読んでいた（proj023）
- `$readmemh` の hex は絶対パスで渡し、ラッパの文字列・Synth 8-4445 の有無・配置後の BRAM の数で照合する。URAM は初期値を持てないので ROM は BRAM に置く。— 読めないと ROM が 0 になり、BRAM が消えるだけでビルドが通る（proj023）
- Vivado 2024.1 は OOC・synth_1・impl_1 で終わり際に落ちる（segfault・tcmalloc・Stack limit。毎回違う run）。落ちた印のある run と、それに依って始まらなかった run だけを 2 回まで回し直す（proj012〜015・023）。**親の Vivado も `open_run` で落ちる**（run の外）ので、後段だけを回す口（`make post`）を持つ（proj025）
- 取得の 1 周の時間（loop_max）は余裕の物差しにならない。1 BASE の処理 ＋ 寝る 3 ms が BASE を越えると 1 周が 2 BASE を抱え、時間が二値的に倍に跳ぶ。余裕は loops / dumps から 1 BASE の処理時間に直して読む（proj025 4c）
- `ram_style = "ultra"` の溢れは、コアごとの OOC の run の中では見えない（place の前の UTLZ-1 で止まる）。複数コアは URAM・BRAM の総数をビルドの前に足す（proj025）
- run は名前の文字列で持ち、その場で `[get_runs $n]` を渡す。dcp を読むときは `set proj` の名前で 1 個に絞る（glob しない）。— 同じ build/ に残っていた古い proj の dcp を読み、取り違えた（proj015・021）
- 速度グレードの検証用ビルドの .bit を実機に載せない。BUILD_TAG の指紋（速度グレード・プリセットの有無）を PS が読む。指紋に commit やビルド時刻を入れない（配置が組み替わり、同じ RTL の作り直しが WNS まで再現しなくなる）（proj011・021）
- CRITICAL WARNING は runme.log だけでなく vivado.log の本体（BD を組むとき）も拾う。— BD 41-759 を 3 回のビルドで見落とした（proj024 2f）
- → 全部: docs/lessons_all.md の「Vivado・build.tcl の見張り」

## タイミングの定石（`-1`・256 MHz）

- 合否は `-1` で閉じること。既定の戦略で閉じなければ `IMPL=Performance_Explore` を回す（並べて回すなら `Performance_ExtraTimingOpt`・`…PostRoutePhysOpt` も）。数 ps なら配線後の `phys_opt_design`（`make physopt`）（proj015・020・021・023）
- WNS は配置の組み替わりだけで ±0.1〜0.2 ns 動く。予言は幅で書き、余裕が数十 ps の bit は、RTL を少し変えると負に戻る前提で扱う（proj011・023）
- フレームの頭でしか使わない幅のある加算・比較は、前もって `pre_*` レジスタに計算しておく。— spec_core で直した型を、写した wide_spec が再び持ち込んだ（−0.561 ns）（proj011・023）
- ファブリックの加算の出口を、レジスタを挟まずに DSP の入口に入れない。飽和・和の後のレジスタを DSP に吸わせたくないときは `dont_touch`（proj012・021・023）
- 準静的な高ファンアウト信号は `max_fanout` の複製で配る。リセットはコアの中で 3 段受け、FFT IP のリセットはレーンごとに 1 段（dont_touch）受けてから配る。IP の tready を段全体の CE に配らない（proj016・020・021・023）
- CRC は for 文でなく展開した XOR の式で書き、入力を 1 段受ける。— for 文は 13 段の LUT の鎖になった（proj021）
- 1 か所に集まるもの（大きい FIFO・選択器）と大ファンアウトが効く。gb_gate → gb_fifo の読み出し許可はスキッドバッファで切ってある（群 C。遅れが +2 語変わる）（proj012・021）
- DSP の出口どうしの加算にレジスタを付けると、加算木の最初の段も DSP に載る。見積もりに含める（proj013・014）
- → 全部: docs/lessons_all.md の「タイミングの定石（`-1`・256 MHz）」

## 設計の規約

- 時刻の物差しは DSP のクロックの数 T（256 MHz、64 bit、1 s = 256,000,000）。PPS は毎秒のトリガにせず、原点と監視に使う。予約は `T == START_AT` で発火し、`late` を持たせる（proj007・016）
- フレームの頭は T の格子に揃える（T ≡ K_F mod 2048、F0 = (⌊fa/M⌋ + 2)·M、時刻の格子 2.048 ms）。DUMP_T は式で決まる。ダンプの区切りは秒に揃えず、毎回同じ N フレーム（proj016・017・023）
- 長く走るカウンタの判定は飽和する数えにする。区切りの判定は等号でなく `≥`。— 32 bit の数えが 16.8 s ごとに巻き戻り、判定が落ちていた（proj013・015）
- 丸めて捨てるのは SHIFT の 1 か所だけ。雑音の床が数 LSB² 以上になる SHIFT を選ぶ。絶対強度は abs = (Σp/N_ACC − 2/3)·4^SHIFT·4^(4−G)/2³¹（−2/3 は切り捨ての偏り）（proj010・014・019）
- 1 フレームは 8192 / 4.096 GS/s = 2.000 µs（2.048 µs ではない）（proj019）
- 共有の ROM は番地も一緒に返し、各コアが照合して粘着の FLAGS を立てる。— タイル間の位相差はこれで見えた（proj023）
- 同期器には `ASYNC_REG` を付け、自作の CDC は持たない（AXI4-Lite の乗り換えは SmartConnect）。CDC は report_cdc の分類で読み、既知の CDC（ギアボックスの FIFO、PS の書き込み順で守るハンドシェイク）と照らす（proj006・007・010・012）
- PL → DDR の書き手は自作の AXI4（バースト ≦ 16 拍、4 KiB の境を越えない）。リングはレコードを丸ごと捨てて DROP_CNT を数え、出口のリセット（rst_rec）を起動のやり直しのリセットと分ける（proj021）
- ソースは src/common・src/<bit>・src/board に分ける（境目は「別の bit で中身が変わるか」）（proj021）
- 自作の AXI4-Lite の口はリセット中に ready を出さない。PS が最初に読むものは、止まりうるクロック（MIG の UI など）の側に置かない。— ddr_tg がリセット中も arready を出し、較正の前の読みで OS ごと止まった（proj028）
- → 全部: docs/lessons_all.md の「設計の規約」

## sim と模型

- 変種（陽性対照など）を同時に走らせる sim の道具は、入力のファイル名を変種ごとに分ける。— 同じ名前の入力 hex を 3 本が同時に書き直し、書きかけを読んだ本体の sim が不定で落ちた（proj028 F-5a。それまでは偶然通っていた。**陽性対照が「競合で落ちた」可能性もある**ので、直した後に全部回し直した）
- **FFT IP の行動模型に実機の振る舞いを入れる**: リセットから tready を上げるまでの遅れ、流し始めの 1 回の tready の下げ、入力の途切れ（halt）。模型を別の proj から写すときは、この振る舞いも引き継ぐ。— 模型が tready を落とさなかったので、proj014 と proj023 の両方で、同じ不具合が sim を通った（proj014・023）
- tb の AXI の待ちは `!== 1'b1` で書く（`while (!arready)` は z を「準備よし」と読む）（proj023）
- 自作部分は IP の前後で切り、整数の模型と bit 単位で比べる。区切り（フレームの頭）は振幅の比べでは捕まらないので、IP の手前の bit 単位の照合と T の位相で見る（proj023）
- 照合の相手は同じ口の経路でなく、記憶の階層参照にする。tb はビートをコアの中のリセットが明けてから数える。最後の WRST の印より後だけを照合する（proj015・021）
- 刺激に満杯の区間（±最大値）を入れる。確かめたいことを試験台の側で仮定しない（proj014・017）
- 大きな N では、ひねり係数の番地の 1 ずれが浮動小数点との比べ（B 層）でほとんど見えない（2G-1: 雑音の ε 8.7e-6 → 1.2e-4、CW の ch は 0.0000 dB）。番地の誤りは bit 単位の照合（A2）と tw_k1 の見張りで捕まえる（proj024 M-8）
- 変種と陽性対照は `make sim-…` で並べて回し、成否は各ログの「結果: 全部通過」で読む（proj011 以降）
- **別の KIND の部品を写したら、その KIND だけの例外を持ち込んでいないかを INTERFACE と照らす**。tb が 2 つの時機に同じ値を渡すと、取り込む時機の誤りは sim を通る。— 2G-1（FULL）の g21_spec が Wide（SLICE）の「SHIFT は WRST で」を持ち込み、2c の sim は通っていた（proj024 2d）
- → 全部: docs/lessons_all.md の「sim と模型」
- インパルスで遅れを測る sim は、探す窓を足の範囲に限る（広いと前のインパルスの足を拾う）。RAW の SNAP はダンプが閉じてから出るので、それまで待って止める（proj024）
- **sim の入口を間引くと、速さの不足が隠れる**。入口が遅いと空の枠が挟まるのは正しい振る舞いなので、中身の照合は通る。全速の変種（ch の間も空けない）を置き、陽性対照（直す前の形）で落ちることを確かめる。実機では読みのループで数え（チャンク・DONE・DROP）を時刻つきで残して、1 単位の処理時間を測る（proj028 F-5c-0: 1 フレームの溜めで本物と空の枠が交互になり、実時間より 16 % 遅かった）

- **遅れ 0 のメモリの模型は読みの速さの不足を隠す**。速さの判定には実機の遅れを持つ模型を（proj028 F-5e）

## PS・PYNQ

- `import xrfdc` は `Overlay()` より前。当たったかを `isinstance(ol.rfdc, xrfdc.RFdc)` で確かめる。.bit と .hwh は同じ basename（proj003・004）
- `xrfclk` のディレクトリに `_` を 2 つ以上含む .txt を置かない（proj004）
- 起動直後の粘着 FLAGS は消す前に読む（`--keep-startup-flags`・wide.py の起動の見張り）（proj011・023）
- MMIO は 1 回 ≒ 10 µs。RUN を順に書くと 1 本あたり 5 フレームずれるので、帳簿（DUMP_F0）で揃える。速い dt は AXI4-Lite でなくリング（DMA）で読む（proj012・019・021）
- HP0 は coherent でない。キャッシュありのバッファを使い、読む前に [R, W) をまとめて `bo.sync(FROM_DEVICE, size, offset)` で捨てる（PYNQ 3.1.1 の `invalidate()` は全体を同期する）。CMA の allocate は 64 MiB まで（proj021）
- リングを閉じるときは REC_CTRL を 0 にし、busy が落ちてからバッファを返す（返すと Segmentation fault）（proj021）
- 時刻は整数 ns で引き算してから float にする（float64 の UTC ns は 256 ns 刻み）。較正定数は bit の ID と対にして持ち、一致しなければ適用を拒否する（proj007・008・021）
- A53 の Python の速さはボードで 1 呼び出しずつ測る（PC の見積もりの 10 倍遅い）。長い記録をリストに溜めない（proj013・021）
- specd は起動のたびに SET し、GET・STATUS を確かめてから START。LOAD は spawn で起こし、通し番号を続ける（proj019・021）
- 1 MiB 級の numpy の配列を周ごとに作る取得では、glibc の mmap の閾値（既定 128 KiB）を上げる（`s45acq.malloc_tune`、mallopt）。— 周ごとに mmap・munmap とゼロ埋めのページフォルトが起き、400 周に 1 回 57 ms の嵐になった。60 ms 級の跳ねは初めて触るページのある周に出る（proj024 3d）
- PS の量は今の読み口（範囲の invalidate）で測る。— proj021 M-5 の「Python 1 本 ≒ 114 MB/s」はバッファ全体を毎回 invalidate していた疑いで、2G-1 の 1 MiB / 10.24 ms は予言 100〜125 % に対し実測 61〜63 %（proj024 3d）
- 取得の速さは実機の周の段の時間（`--loop-log-ms`）で測る。同じ配列をなめる台は L2 に載って実機の半分に出る。**2 秒の運転は溜まり 256 MiB の一巡の前**で、put ごとにページフォルト（64 / 本）が乗る → `--prefault`、フォルトは `ru_minflt` で数える（proj029 1a〜1d）
- PL のリングの上のレコードを写さずに使うなら、R は使い終えるまで進めない（`Ring.read(lazy)` → `release()`）。使い切れない分は写して CRC を照らしてから進める。PL の CRC は記録を作る同じなめで取る（proj029 2）
- 2G の tint 10.24 ms は `--prefault --fast --fast-ring` で 1 BASE 6.2 ms（61 %）。どれも既定は切ってある。51 MB/s の受けは NIC（≒ 27 MB/s）を越えるので、長い運転の受けはボードの上で先に起こす（proj029）
- 揃わないチャンクを待ち続けると PS のメモリを食い尽くしてボードが固まる。待ちの上限・器の使い回し・RSS の上限を置く。途中保存は fork。s45_ring の SIZE は 2 の冪（proj028 F-6c）
- → 全部: docs/lessons_all.md の「PS・PYNQ」

## 実機・測定

- E8257D は周波数によって −10 dBm 以下で unleveled になる（3.94 GHz で確認）。`:POW?` は設定値を返すので、`:STAT:QUES:POW:COND?` の bit 1 を見る（sg.py が見る）。低いレベルは +0 dBm 以上で出して固定減衰器で落とす（proj023）
- 試験音源は E8257D（APSYN420 は 100 MHz で方形波）。ボードと SG は同じ 10 MHz に載せる。減衰量と構成を毎回記録する（0 dBFS ≒ +5.8〜5.9 dBm）（proj005・014・019）
- 試験音は fs/64 の倍数、k·fs/8、n × 163.84 MHz を避ける。強い線の f ± k·fs/8 には −55 dBc 級のインタリーブの線が立つ（仕様）（proj009・019）
- 1PPS を ADC に常時入れない（構成 B）。1PPS・10 MHz のケーブルと終端していない分配器は 800 MHz 帯の混信の入口。使わない口は 50 Ω で終端する（proj008・010・013）
- 0 のままの定数は式の符号の誤りを隠す。0 から動かす前に、等価な 2 つの書き方で同じ結果になる試験を書く（pps_det_ns の符号、proj026）
- 1PPS・10 MHz の入口に LPF（BLP-10.7+、常設）。M は ≒ 71.5 ns 小さくなる。混信の効きは携帯電話では比べられない（送信の強さ・帯域が通話ごとに違う）→ SG の CW で（proj026）
- 入力レベルは HOT/R で −10 dBFS 以下（運転 ≒ −16〜−21 dBFS）。窓の CW 試験は −20 dBm・SHIFT 11。試験の後は SG の出力を OFF に戻す（proj019・020・021）
- 配線に依る値は絶対値で予言せず、同じ配線のまま旧 bit を載せて比べる（proj021）
- 0.02 dB を判定する掃引は SG（E8257D）を 300 s 温めてから。入れた直後は 95 s で −0.08 dB 漂う。繰り返しの点はモードごとに ch の中心に（proj023 H-1）
- 出荷時の基準の ppm は 1 か月で 2.3 ppm 動いた。周波数を使う測定は外部 10 MHz で（CW は計算どおりの bin、≦ 0.007 ppm）（proj028 F-7）
- RUN で PL が 4 °C 温まり電力が −0.5 %（10 分）。Overlay の読み直しで 0.5 %（ON）・4 %（ADC の床）の段。比べる測定は同じ読み込みの中で、10 分空回ししてから（proj028 F-6）
- ON / OFF は雑音源の電源でなくアッテネータで作り、状態ごとに利得を合わせる（8 bit に一緒に収まらない）。ADC の床は 0.29 s ごとに 0.45 % 揺れる（proj028 F-6e）
- → 全部: docs/lessons_all.md の「実機・測定」
- F-2 の σ ≦ 0.4 は PPS のスタンプの 1 ビートの跳ねに敏感（M の確かさより厳しい）。σ で落ちたら Overlay を載せ直して回し直す、と測る前に決めておく（proj024）
- F-2 の Overlay ごとの 4 ADC 共通のずれは 1 ビートを越えうる（「2 回の差 ≦ 1」がそれだけで落ちる）。ケーブルの差は共通の分を引いた残りで見る（YATSUGATAKE M6）
- CW の応答を 0.02 dB で見る掃引は雑音を切って測る。P_off を引いても CW × 雑音の交差項の揺れが残る（YATSUGATAKE M6 H-1）

## 公開

- リポジトリは公開。commit の前に公開前のスキャンを全項目行う。コミットメッセージに `Claude-Session:` の行や URL を入れない（`Co-Authored-By` は可）
