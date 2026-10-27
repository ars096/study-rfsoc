# SPDX-License-Identifier: BSD-3-Clause
# proj031 — proj030 の build.tcl（7acee6c）を写し、PFB の係数を共有の URAM（g24_cu_0、4 コアで 1 組、README の P-1・P-2）にした 2G-4 の .bit。変えたのは:
#   set proj proj031・PROJ 0x0031_0100・add_files（g24_coef → g24_cu・crc32_d32.vh。sources_1 の include_dirs に src/g24）・
#   コアの CONFIG から LO_FILE・HI_FILE を外した（係数の hex は PS が読む）・g24_cu_0 のセル（smc_ctrl の M07。COEF_CRC_HI・LO は環境変数 COEF_CRC から。
#   Makefile が make model-cu の最後の行を渡す）・結線（shared_nets に g24_cu_0 のリセット・番地（s45_core_0 から）・出口 3 本（4 コアへ）、DSP のクロック）・
#   在ってはいけない側（コア 1〜3 の coef_addr は空き・g24_cu_0/addr のネットにはコア 0 だけ）と陽性対照 (m)(n)・番地の窓・URAM の数（build_post.tcl）。
#   rev 2（README の B-2）: PROJ 0x0031_0200 だけ（RTL の直しは g24_pfb_core の coef_mis を flags_clr でも消す）。以下は proj030 の注:
# proj030 P-4 — proj027 の build.tcl（fe49b9d）を写し、レーン FFT を 2-for-1 にした 2G-4 の .bit。変えたのは: set proj proj030・PROJ 0x0030_0100・
#   add_files（g24_chain・dft16 → s2_sep・s2_chain・s2_q・dft16f）・IP は 8 × 4 コア（設定は同じ。入力が複素になるだけ）。以下は proj027 の注:
# proj027 手順 2f — 2G-4（4 ADC × 65536 点、32768 ch × 4、BIT_KIND 3）の .bit。proj025-m0 の build.tcl（2G-2、2 コア）を写して直した:
#   1. コアは **s45_core_0〜3 の 4 個**（F-1: Wide の形。module reference の g24_s45_core）。**RAW は 4 コアとも 1**（F-5）。
#      CORE_PORT はコア c = ADC c（ch c = ADC_A〜D）。ギアボックスの制御はコア c が ch c を握る（4 ch ともコアがあるので gb_tie_* は無い）
#   2. **axis_sel4 を 8 個**: full_sel_c（sel = s45_core_c/full_sel → s45_core_c/s_axis_full）・raw_sel_c（sel = s45_core_c/raw_sel →
#      s45_core_c/s_axis_raw）、c = 0〜3（F-4・F-5）。gb_bc_i は 9 本（M00 コア i・M01〜M04 full_sel_0〜3・M05〜M08 raw_sel_0〜3）
#   3. FFT IP は lane_fft_g24（**4096 点**・bit 反転順・入力 15 bit・unscaled → 出力 28 bit・realtime。proj024 S-1 の 4096 点・rev の設定）× 16 × 4 コア
#   4. 係数・ひねり係数の ROM はコアの中なので**コアごとに 1 組**（F-2・F-3）。中身は src/g24/*.hex（係数 1024 行・A 32 行）を絶対パスで 4 コアの CONFIG に
#   5. ID: BIT_KIND 3・BIT_REV 1・PROJ 0x0027_0100。s45_ring_0 の入口は 4 本で全部使う。**使わない入口が無いので tie_*・gb_tie_* は作らない**
#      （在ってはいけない側の照合で、そのセルが無いことを見る）
#   6. SmartConnect の M は 1 ＋ 4 ＋ 2 = 7（RFDC・s45_core_0〜3・time_core_0・s45_ring_0）
#
# （以下は proj025 の build.tcl の記録）
# proj025 手順 2f — 2G-2（2 ADC × 131072 点、65536 ch × 2、BIT_KIND 10）の .bit。proj024-m0 の build.tcl（2G-1）を写して直した:
#   1. コアは **s45_core_0・s45_core_1 の 2 個**（E-1: Wide の形。module reference の g24_s45_core。コア 0 は RAW = 1、コア 1 は RAW = 0、E-5）。
#      CORE_PORT はコア c = ADC c（ch 0 = ADC_A・ch 1 = ADC_B）。ギアボックスの制御はコア c が ch c を握り、ch 2・3 は定数（gb_tie_*）と rst_dsp
#   2. **axis_sel4 を 3 個**: full_sel_0（sel = s45_core_0/full_sel → s45_core_0/s_axis_full）・full_sel_1（コア 1）・raw_sel（コア 0 の RAW）（E-4）。
#      gb_bc_0・gb_bc_1 は 4 本（自分のコア・full_sel_0・full_sel_1・raw_sel）、gb_bc_2・3 は 3 本
#   3. FFT IP は lane_fft_g24（**8192 点**・bit 反転順・入力 15 bit・unscaled → 出力 29 bit・realtime。proj024 S-1・S-2 の 8192 点の設定）× 16 × 2 コア
#   4. 係数・ひねり係数の ROM はコアの中なので**コアごとに 1 組**（E-2・E-3）。中身は src/g24/*.hex を絶対パスで両方のコアの CONFIG に
#   5. ID: BIT_KIND 10・BIT_REV 1・PROJ 0x0025_0100。s45_ring_0 の入口は 2 本。**使わない入口（s45_core_1 の s_axis_raw、s45_ring_0 の s2・s3）は
#      xlconstant で縛る**（proj024 2f の BD 41-759 を、Wide の full_tie_* と同じ形で）
#   6. **BD を組んだ後に vivado.log の本体の CRITICAL WARNING を拾って止める**（LESSONS、proj024 2f。runme.log だけでは BD 41-759 が見えなかった）
#
# （以下は proj024 の build.tcl の記録）
# proj024 手順 2f — 2G-1（1 ADC × 262144 点、131072 ch、BIT_KIND 11）の .bit。proj023 の build.tcl（ビルド 11、567fda2 の頃）を写して直した:
#   1. コアは **s45_core_0 の 1 個だけ**（module reference の g24_s45_core = core_cmn ＋ g24_core（FULL、s 0）＋ raw_core（RAW、s 1））。
#      セルの名前は今までどおり s45_core_0（PS はこの名前でコアを見つける）。CORE_PORT は ADC_A（ch 0）
#   2. ギアボックスは 4 ADC とも残す（FULL と RAW は SRC で 4 本から選ぶ。D-8・D-14）。ch 1〜3 のギアボックスの制御（gb_hold・gb_adj・gb_k）は
#      定数（gb_tie_*）、読み出し側のリセット（gb_dn_rstn）は rst_dsp。ch 0 は s45_core_0 が握る（Wide と同じ）
#   3. **axis_sel4 を 2 個**: full_sel（sel = s45_core_0/full_sel → s_axis_full）・raw_sel（sel = s45_core_0/raw_sel → s_axis_raw）。
#      gb_bc_0 は 3 本（コア・full_sel・raw_sel）、gb_bc_1〜3 は 2 本（full_sel・raw_sel）
#   4. FFT IP は lane_fft_g24（16384 点・bit 反転順・入力 15 bit・unscaled → 出力 30 bit・realtime。S-1・S-2 と同じ設定、tools/ip_impl.tcl の fft_req）× 16
#   5. 係数・ひねり係数の ROM はコアの中（g24_coef・g24_tw）。中身は src/g24/*.hex を **絶対パスで** s45_core_0 の CONFIG（LO_FILE・HI_FILE・TA_FILE・TB_FILE）に。
#      $readmemh が読めないと ROM は 0 になり、BRAM が消えるだけでビルドは通る → ラッパの文字列・合成のログ・配置後の BRAM の数で止める（proj023 3b と同じ）
#   6. ID: BIT_KIND 11・BIT_REV 1・PROJ 0x0024_0100（s45_core_0・time_core_0・s45_ring_0）。s45_ring_0 の入口は 1 本
#   7. 遅いビットの検証ビルド（GB_SLOW）と FFT_OPT は外した（2G-1 の IP は 1 通り）
#   8. 資源の数え: lane_fft_g24 16 個・段ごと（u_pfb・g_lane・u_chain・u_tw・u_acc・TP）・ROM の BRAM・URAM
#
# （以下は proj023 の build.tcl の記録）
# proj023 手順 3b — SAM45-Wide（proj023/README の手順 3b・D-1〜D-7）:
#   1. コアのセル s45_core_i を module reference の wide_s45_core に（core_cmn ＋ wide_core（SLICE × 2）＋ コア 0 だけ RAW）。
#      **窓（win_core・pfb_core・ddc_core・wspec_core …）と win_fft は外した**。セルの名前は今までどおり（PS はこの名前でコアを見つける）
#   2. FFT IP は lane_fft_w（2048 点固定・入力 15 bit・unscaled → 出力 27 bit）× 16 / コア。設定は src/sam45fine/fft_cfg.tcl の fft_req（FFT_OPT）
#   3. 共有の係数 ROM（D-6）: wide_coef_rom_0（PFB の係数）。**番地は s45_core_0 が出し、出口を 4 コアへ配る**。
#      s45_core_1〜3 の係数の番地の出口はどこにもつながない（照合の「在ってはいけない」側で見る）。
#      ひねり係数 ROM は **コアごと**（wide_tw_rom_i、番地は s45_core_i の tw_addr）。proj023 4b 実機 6 回目: 共有の ROM はコア 0 の
#      IP の出口の k1 で引くが、タイル 224 のコア（C・D）は IP の出口の k1 の位相がコア 0 と違い、tw_mis が立ち続けた。
#      IP の出口の位相はコアの間で揃う保証が無い（係数は T で引くので共有のまま）
#      中身は src/sam45wide/*.hex を **絶対パスで** CONFIG に与える（OOC の合成は run のディレクトリで走るので相対パスは届かない）。
#      $readmemh が読めないと ROM は 0 になり、BRAM が消えるだけでビルドは通る → 合成のログと配置後の BRAM の数で止める
#   4. ID は D-5: BIT_KIND 1・BIT_REV 1・PROJ 0x0023_0100（s45_core_i・time_core_0・s45_ring_0）
#   5. full_sel（axis_sel4）は RAW の入力の選びとして残す。wide_s45_core に full_gb_stat・full_adc_stat は無い（raw_core は使わない）ので縛りも外した
#   6. 資源の数え: lane_fft_w 64 個・コアごと・段ごと（u_pfb・鎖・TP）・共有の ROM
#
# （以下は proj021 の記録）
# proj021 手順 2-1 — インターフェース v2 の流れのブロックと自己記述（INTERFACE.md の 2.〜3.、proj021/README の手順 2-1）
# proj021 手順 2-5 — SAM45-Fine の FULL（spec_core）を生サンプルの流れ（raw_core、KIND 4 RAW）に替える（README 手順 2-5）:
#   1. s45_core_0 を CONFIG.FULL 0・CONFIG.RAW 1 に（full_kind = raw）。lane_fft（FFT IP）は作らず、spec_core.v・dft16.v・tw_rom.v も足さない
#   2. BIT_REV 2 → 3（s45_core_i・time_core_0・s45_ring_0）。資源の数えの FULL の行は RAW の行（g_raw.u_raw）に
#   （full_kind = fft にすると 2-2d〜2-4 の形の FULL に戻る。BIT_REV は 3 のまま。PS は流れの KIND で見分ける）
#
#   1. コアのセルを s45_core_i（src/common/s45_core.v = win_core ＋ i = 0 だけ FULL の流れの spec_core）に。**spec_core_0 のセルは無い**。
#      axis_sel4（full_sel）の出口 → s45_core_0/s_axis_full、選ぶのは s45_core_0 の full_sel（FULL の流れの SRC）
#   2. CORE_PORT（ADC・タイル・スライス）を chans から、BIT_KIND 2・BIT_REV 2（2-2d。2-1〜2-2c は 1）・PROJ 0x0021_0200 を s45_core_i と time_core_0 に
#   3. SmartConnect の M は 1 + nch + 1（spec_core_0 の M が無くなった）。コアの窓は 1 MiB のまま（仮の読み窓）。**2-2d で 64 KiB に**
#   4. 資源の数え: FULL は s45_core_0/inst/g_full.u_full、窓は s45_core_i/inst/u_win の下
# proj021 手順 2-2a（proj021/README の手順 2-2a）
#   1. s45_core_1〜 の FULL の入口（s_axis_full_tdata・tvalid・full_gb_stat・full_adc_stat）を xlconstant の 0 で縛る（BD 41-759）
#   2. リング s45_ring_0（src/common/s45_ring.v、CORE_KIND 3）: 入口 = s45_core_i/m_axis_rec（rec_fr のレコード）と rec_drop、
#      書き手 → PS の S_AXI_HP0_FPD（GP2、128 bit、saxihp0_fpd_aclk = DSP のクロック）、レジスタ = smc_ctrl の M0(2+nch)
#
# （以下は proj020 の記録）
# proj020 — SAM45-Fine rev2: proj017 の wspec_core の溜めと FFT の間に PFB（T = 4）を入れる
#
# ---- proj017 からの変更点 ----
#   1. src/sam45fine/pfb4_rom.v（PFB の係数 ROM、model/pfb4.py gen の生成物）を足す。wspec_core の溜めは 5 面のリング（URAM）
#   2. ID: win_core 0x0020_0100 / 0x0020_A100、spec_core 0x0020_01xx、time_core 0x0020_7101（spec_core・time_core は中身は同じ）
#   3. 資源の予言: wspec 32 → 40（PFB の積 8）、win_core 504 → 520、全体 2520 → 2584。URAM 16 → 56（窓ごとに 5）、BRAM36 −4 / 窓
#
# （以下は proj017 の記録）
# proj017 — SAM45-Fine（BITS.md）: proj016 を **4 ADC × 2 窓**（win_core × 4、NW = 2）に。全帯域 1 本（spec_core_0）・time_core_0 は proj016 のまま
#
# ---- proj016 からの変更点 ----
#   1. chans を 4 本（ADC_A..D）・adc_tiles = {0 2} に戻す（proj015 と同じ並び）。WIN_NW = 2
#   2. tp_core に FLAGS[4]（区切りの中の振り切れ）。ID: win_core 0x0017_0100 / 0x0017_A100、spec_core 0x0017_01xx、time_core 0x0017_7101
#   3. axis_sel4 の選択の bit を複製（max_fanout。proj016 の `-1` の最悪経路の群 2: sr[1] のファンアウト 303）
#
# （以下は proj016 の記録）
# proj016 — proj015 rev3 の分光計を **ADC 1 本（ADC_A）** にし、時刻（time_core・1PPS）・設定番号・健全性フラグを足す
#
# ---- proj015 からの変更点 ----
#   1. chans を {{2 2}}（ADC_A = Tile 226 / slice 2）の 1 本に。adc_tiles = {2}（Clocking Wizard の源 clk_adc2 と同じタイル）。
#      窓 4（win_core_0、NW = 4）・total power・全帯域 1 本（spec_core_0）は残す。full_sel（axis_sel4）は s0 だけつなぐ
#   2. **time_core_0**（src/common/time_core.v）を module reference で置く。DSP ドメイン（256 MHz）、AXI4-Lite は smc_ctrl の M(2 + nch)。
#      ctrl_aclk / ctrl_aresetn は pl_clk0 / rst_ctrl（エポックを MMCM に依らない側で数える。proj007 rev2 と同じ）。
#      PPS の外部ポート pps_trig（AH13）/ pps_comp（AJ13）を create_bd_port で作り、src/board/pps.xdc で置く（実装後に読み返す）
#   3. time_core_0 の t_out・go_out・ev_out を win_core_i と spec_core_0 の t_in・go_in・tev_in へ（共有のネットとして照合する。
#      ch が 1 本だと ch 間の陽性対照が回らないので、時刻のネットで陽性対照を置く）
#   4. src/common/dstamp.v・src/common/adc_ev.v（win_core・spec_core の中で使う）
#
# （以下は proj015 の記録）
# proj015 — bit ③（狭帯域の窓）の最終の形: **4 ADC × 4 窓**（win_core × 4、NW = 4）＋ 全帯域の分光 1 本（spec_core_0、4 ADC から選ぶ）
#
# ---- proj014 からの変更点 ----
#   1. win_core を ch ごとに 1 個（win_core_i、CONFIG.NW = 4）。中で粗い PFB を 4 窓で共有し、窓ごとに ddc（NS 1..8）・wspec、
#      ADC の total power（tp_core）とスナップショット 1 つを持つ。AXI4-Lite の窓は **1 MiB**（20 bit 番地。窓 w = 0x20000·w、ADC の共通 = 0x80000）
#   2. spec_core は **spec_core_0 の 1 本だけ**（RTL は proj013 rev1 と同一で ID だけ）。入力は axis_sel4（src/common/axis_sel4.v）で
#      4 本の gb_dn の出口から選ぶ。選ぶのは win_core_0 の FULL_SEL（0x80020）。ch ごとに gb_bc_i（axis_broadcaster）で
#      win_core_i と axis_sel4 に分ける
#   3. **ギアボックスの制御は win_core_i**（gb_hold = 0・gb_adj = 0・gb_dn_rstn = aresetn・gb_k = GB_K）。spec_core の GRST は
#      ギアボックスに届かない（spec_core_0 の gb_* の出口はどこにもつながない）。窓の経路は valid なビートだけで進むので起動の途切れに強い。
#      gb_gate の見張り（gb_stat・adc_stat）は win_core_i と axis_sel4 に配り、axis_sel4 が選んだ ch のものを spec_core_0 に渡す
#   4. SmartConnect の M は 1 + 4 + 1 本（M00 RFDC・M0(1+i) win_core_i・M05 spec_core_0）
#   5. win_core の BUILD_TAG = 土台 ＋ [22] 窓のコア ＋ [1:0] ch の番号。spec_core_0 は 土台 ＋ [21] 選べる全帯域
#   6. 結線の照合を win_core_i・gb_bc_i に広げ、axis_sel4 の共有のネットも見る
#
# （以下は proj014 の記録）
# proj014 — proj013 rev1（全帯域 4 IF ＋ total power）に、**窓 1 つの分光計 win_core を ADC_B に 1 個足す**（bit ③ の最初の形）
#
# ---- proj013 からの変更点（これ以外は proj013 rev1 と同一）----
#   1. win_core（src/common/win_core.v。pfb_core → ddc_core → wspec_core。中で FFT IP win_fft を 1 個使う）を module reference で置く。
#      入力は ADC_B（ch i = WIN_CH = 1）の gb_dn の出口を axis_broadcaster（gb_bc）で 2 本に分けたもの。**spec_core_1 と同じ流れ**なので、
#      同じ入力で全帯域と窓を比べられる（判定 W-6）。ギアボックスの制御（gb_hold・GB_K・見張り）は spec_core_1 のまま
#   2. FFT IP win_fft（複素 4096 点・入力 18 bit・unscaled・realtime・use_mults_resources・use_luts。tools/ip_survey.tcl の win4096_res_lut）
#   3. SmartConnect の M を 1 + 4 + 1 本に。win_core の窓は **128 KiB**（17 bit 番地）。重なりも見る
#   4. win_core の BUILD_TAG = spec_core と同じ土台 ＋ [22] 窓のコア ＋ [1:0] ch の番号
#   5. spec_core の ID を 0x0014_01CC に（**RTL は proj013 rev1 と同一で、定数だけ**。載っている .bit を PS が見分けるため）
#   6. src/common/win_coef.vh を include するので、sources_1 の include_dirs に ./src
#
# proj012 — proj011 rev6 の分光計（RFDC → ギアボックス → spec_core → AXI4-Lite → PS）を
#           **ADC_A〜D の 4 本に広げる**（全帯域 4096 ch × 0.5 MHz × 4 IF）
#
# ---- proj011 からの変更点（これ以外は proj011 rev6 と同一）----
#
#   1. chans を 4 本に。**並びは SMA のラベル順（ADC_A, B, C, D）**にし、BD のセルの番号 i = 0..3 を
#      A..D に対応させる（gb_*_i・spec_core_i）。対応の実測は VERSIONS.md。proj009 の 4ch の並び
#      （{0 0} {0 2} {2 0} {2 2}）は 512 bit 語に束ねる都合だった。**束ねないので、ラベル順にできる**
#   2. ギアボックス（gb_adc / gb_up / gb_fifo / gb_gate / gb_dn）と spec_core を **ch ごとに 1 組**。
#      Clocking Wizard は 1 個を共有（proj009 の 4ch と同じ。clk_adc2 が源）
#   3. SmartConnect の M を 1 + 4 本に。spec_core の窓 64 KiB × 4 を読み返す（重なりも見る）
#   4. spec_core の BUILD_TAG に [23] 4ch のビルド / [1:0] ch の番号（0..3 = ADC_A..D）を載せる。
#      **PS はセル名と BUILD の ch の番号を突き合わせてから動く**（spec_core.v の RTL は同一）
#   5. **ch 間の結線の照合**（下の「結線の照合」）。4 組並べると、ch をまたいだ取り違え
#      （spec_core_1 の gb_hold が gb_adc_2 に行く、など）がビルドも実機も通る形で起きうる。
#      組ごとに「在るべき相手と繋がっている」と「他の ch のセルと繋がっていない」の両側を見る
#   6. （rev2）rst_adc の peripheral_aresetn をタイルの数の幅にし、xlslice でタイルごとに別のビット（別の DFF）から
#      m*_axis_aresetn と、その タイルの ch の gb_adc_i へ配る。rev1 の CDC-11（1 個のフロップ → 2 タイルの同期段）を消す
#   7. （rev3）gb_gate のしきい値 GB_K_RST の既定を 0 → 2（Overlay の起動にも効く）。RTL は ID の定数だけ
#
# 出力:
#   build/proj012.bit      ビットストリーム（FFT_OPT=perf なら build-perf/）
#   build/proj012.hwh      ハードウェアハンドオフ（PYNQ が読む。.bit と同名にする）
#   build/rfdc_params.rpt  RFDC IP が実際に持つ CONFIG 一覧
#   build/xfft_params.rpt  FFT IP（lane_fft）が実際に持つ CONFIG 一覧
#   build/lane_fft_util.rpt  lane_fft 1 個ぶんの資源（g_lane[0]）。make survey の数字と突き合わせる
#   build/net_check.rpt    ch 間の結線の照合の全行
#
# ---- （履歴）proj011 の proj010 からの変更点 ----
#
#   1. **FFT IP の設定を src/sam45fine/fft_cfg.tcl に移し、FFT_OPT（res / perf）で選ぶ。**
#      tools/ip_survey.tcl（make survey）も同じファイルを読むので、IP 単体の調査と本番が同じ設定を数える
#   2. **throttle_scheme = realtime。**nonrealtime の CE（proj010 の -2 の最悪経路）を無くす。
#      realtime の IP には m_axis_data_tready が無い（PG109）ので、spec_core.v の接続も外した。
#      **ポートの照合で「在ってはいけない」側も見る**（在れば IP が realtime になっていない）
#   3. 乗算器・バタフライ・throttle の CONFIG を fatal にした（調べる対象なので黙って戻られると困る）
#   4. spec_core の ID の下位 8 bit に FFT の設定の符号を載せる（CONFIG.FFT_CFG）。
#      res と perf は同名の proj011.bit になるので、**PS から載っている変種を読めるようにする**
#   5. lane_fft 1 個ぶんの資源を別に出す（予言の突き合わせ用）
#   6. （rev4）spec_core にビルドの指紋 BUILD_TAG（プリセットの有無・速度グレード）を与える
#   7. （rev6）ギアボックスの入口に gb_adc（再起動のリセット・RFDC の見張り）、gb_fifo の出口に gb_gate
#      （読み出しの開始のしきい値 K・見張り）を挟む。gb_fifo に axis_rd_data_count を出させる。
#      GB_K（環境変数、既定 0）を spec_core の GB_K_RST に与える（ハードのリセットの起動に効くしきい値）
#
# RFDC・Clocking Wizard・ギアボックス・spec_core の本体は proj010 と同一。
# ナイキストゾーン（2）は実行時に PYNQ から設定する（pynq/spectrometer.py）。

set proj         proj031
# proj015: **既定の part を -1 に**（実機の .bit を -1 で配置配線する。チップの刻印が未確認で、遅い方で閉じたものだけを載せる）。
#   -1 のビルドは board_part を使わず、src/board/ps_preset.tcl（make ps-preset で書き出したボードプリセットの PS の設定）を当てる。
#   -2（board_part の宣言値）は PART=xczu48dr-ffvg1517-2-e で build-2-e/ に（board_part ＋ プリセット。proj014 までの build/ と同じ作り）
set part_default xczu48dr-ffvg1517-1-e
set board_part_part xczu48dr-ffvg1517-2-e
set part         $part_default
set bd_name      system
set outdir       ./build

if {[info exists ::env(PART)]   && $::env(PART)   ne ""} { set part   $::env(PART) }
if {[info exists ::env(OUTDIR)] && $::env(OUTDIR) ne ""} { set outdir ./$::env(OUTDIR) }
set gb_k_rst 2          ;# rev3: 既定値 2（Makefile の GB_K_DEFAULT と対。README の rev3）
if {[info exists ::env(GB_K)] && $::env(GB_K) ne ""} { set gb_k_rst $::env(GB_K) }
if {![string is integer -strict $gb_k_rst] || $gb_k_rst < 0 || $gb_k_rst > 24} {
    puts "ERROR: GB_K = '$gb_k_rst'（0〜24。gb_fifo の深さ 32 に余裕を残す）"
    exit 1
}
# proj024: FFT IP の設定は tools/ip_impl.tcl（S-2）の fft_req と同じ（S-1・S-2 で数えたものをそのまま本番に）。{CONFIG 値 fatal}
proc fft_req {n in_w order clk_mhz} {
    return [list \
        CONFIG.transform_length                       $n                     1 \
        CONFIG.implementation_options                 pipelined_streaming_io 1 \
        CONFIG.data_format                            fixed_point            1 \
        CONFIG.input_width                            $in_w                  1 \
        CONFIG.scaling_options                        unscaled               1 \
        CONFIG.output_ordering                        $order                 1 \
        CONFIG.xk_index                               true                   1 \
        CONFIG.throttle_scheme                        realtime               1 \
        CONFIG.aresetn                                true                   1 \
        CONFIG.run_time_configurable_transform_length false                  1 \
        CONFIG.cyclic_prefix_insertion                false                  1 \
        CONFIG.channels                               1                      1 \
        CONFIG.complex_mult_type                      use_mults_resources    1 \
        CONFIG.butterfly_type                         use_luts               1 \
        CONFIG.target_clock_frequency                 $clk_mhz               0 \
        CONFIG.phase_factor_width                     18                     0 \
        CONFIG.rounding_modes                         convergent_rounding    0 \
        CONFIG.ovflo                                  false                  0 \
    ]
}

# ---- 設計パラメータ ----
# **SMA のラベル（ADC_A/B/C/D）との対応は VERSIONS.md が正。ラベルから推測しないこと。**
#   ADC_A = Tile 226 / slice 2 = {2 2}   ADC_B = Tile 226 / slice 0 = {2 0}
#   ADC_C = Tile 224 / slice 2 = {0 2}   ADC_D = Tile 224 / slice 0 = {0 0}
# **i 番目の ch = chans の i 番目 = セル gb_*_i / spec_core_i = ch_labels の i 番目。**
# proj017: 4 本に戻す（proj016 は ADC_A の 1 本だけ）
set chans      {{2 2} {2 0} {0 2} {0 0}}
set ch_labels  {ADC_A ADC_B ADC_C ADC_D}
set adc_tiles  {0 2}
set nch        [llength $chans]
if {$nch != [llength $ch_labels] || $nch > 4} {
    puts "ERROR: chans（$nch 本）と ch_labels（[llength $ch_labels] 本）が合わない。BUILD_TAG の ch の番号は 2 bit"
    exit 1
}

set fs_gsps    4.096      ;# サンプリング周波数 [GSPS]
set refclk_mhz 491.520    ;# LMX2594 → RFDC タイル
# 1 語あたりのサンプル数（proj009 で確定）
#   spw_adc: RFDC の出力。12 → 341.333 MHz（ADC ドメイン。ギアボックスの入口だけ）
#   spw    : ギアボックスの後。16 → 256 MHz（DSP ドメイン。spec_core はここ）
set spw_adc    12
set spw        16
set beat_bits  [expr {$spw * 16}]          ;# 256 bit（ch ごと。束ねない）
set beat_bytes [expr {$beat_bits / 8}]

proc gcd {a b} { while {$b} { set t $b; set b [expr {$a % $b}]; set a $t }; return $a }
set gb_mid [expr {$spw_adc * $spw / [gcd $spw_adc $spw]}]
set gb_up  [expr {$gb_mid / $spw_adc}]
set gb_dn  [expr {$gb_mid / $spw}]
set use_gb [expr {$spw_adc != $spw}]

set outclk_mhz [format %.3f [expr {$fs_gsps * 1000.0 / 16}]]
set wiz_src_tile 2        ;# clk_adc2 を Clocking Wizard の入力にする（timing.xdc の RFADC2_CLK）

set ctrl_mhz   100        ;# pl_clk0: AXI4-Lite 制御系（PS 側）

set fabric_mhz [format %.3f [expr {$fs_gsps * 1000.0 / $spw_adc}]]
set dsp_mhz    [format %.3f [expr {$fs_gsps * 1000.0 / $spw}]]
set fs_mhz     [format %.3f [expr {$fs_gsps * 1000.0}]]

# ---- 分光計（g24_spec.v と対。proj024）----
# proj027: 65536 点 = 16 レーン × 4096 点（固定長・bit 反転順）。ch 62.5 kHz、1 フレーム 16 µs（4096 ビート）。FULL 32768 ch × 4 コア
set fft_mod     lane_fft_g24 ;# **名前は RTL（g24_spec.v）と sim/lane_fft_g24_model.v と対**
set fft_lane_n  4096
set fft_order   bit_reversed_order
set fft_in_w    15        ;# IP の入力（g24_pfb の出口 y、15 bit）
set fft_out_w   28        ;# unscaled の出力 = 15 + log2(4096) + 1。proj030: 入力は複素（2-for-1）。RTL（g24_spec）は 32 bit の欄の下位 28 bit を読む
# フレームの頭と起動の見張り。**RTL の既定と同じ値を明示して読み返す**（sim は GF_L2 1 で回している）
set g24_kf      0         ;# T ≡ K_F（mod 4096）がフレームの頭
set g24_st_n    16384     ;# 起動の見張り（ビート）
set g24_gf_l2   7         ;# F0 の格子 = 2^7 フレーム（2.048 ms。2G-4 のフレームは 16 µs）
# ROM の中身（make gen の生成物。src/g24/）: {CONFIG の名前 ファイル 行数 1 行の桁数}
set g24_hex [list \
    TA_FILE [file normalize ./src/g24/g24_tw_a.hex]    32 144 \
    TB_FILE [file normalize ./src/g24/g24_tw_b.hex]    128 144 ]
# 生成物の形を先に見る。古い・切れた hex をここで止める
foreach {par h nrow ncol} $g24_hex {
    if {![file exists $h]} { puts "ERROR: $h が無い（make gen で作る）"; exit 1 }
    set fh [open $h r]; set lines [split [string trim [read $fh]] "\n"]; close $fh
    set bad 0
    foreach l $lines { if {[string length $l] != $ncol || ![string is xdigit -strict $l]} { incr bad } }
    if {[llength $lines] != $nrow || $bad != 0} {
        puts "ERROR: $h の形が違う（[llength $lines] 行（期待 $nrow）、うち $ncol 桁の 16 進でない行 $bad）"
        exit 1
    }
}
set ncore 4               ;# proj027: コアは 4 個（s45_core_0〜3、F-1）= ギアボックスの ch の数 nch
set g24_kind 3            ;# BIT_KIND（2G-4）
set g24_proj [expr {0x00310200}]   ;# proj031 rev 2（rev 1 は 0x0031_0100。proj030 は 0x0030_0100、proj027 は 0x0027_0100）
if {$ncore != $nch} { puts "ERROR: ncore（$ncore）が nch（$nch）と違う（2G-4 はコア c = ch c）"; exit 1 }

puts "PART      : $part"
puts "OUTDIR    : $outdir"
puts "FFT       : $fft_mod = $fft_lane_n 点・$fft_order・入力 $fft_in_w bit・unscaled（出力 $fft_out_w bit）・realtime"
set i 0
foreach ch $chans {
    lassign $ch t s
    puts "ADC $i     : [lindex $ch_labels $i] = Tile [expr {224 + $t}] / slice $s"
    incr i
}
puts "fs        : $fs_mhz MSPS （RFDC $fabric_mhz MHz × $spw_adc → DSP $dsp_mhz MHz × $spw sample/word）"
puts "GEARBOX   : $spw_adc → $gb_mid → $spw サンプル（×$gb_up / ÷$gb_dn）"
puts "SPEC      : 65536 点 = 16 × $fft_lane_n / ch [expr {$fs_gsps * 1e6 / 65536}] kHz / 1 フレーム [expr {65536 / $fs_gsps / 1000.0}] us / FULL 32768 ch / コア 4 個（s45_core_0〜3）"
puts "G24       : K_F = $g24_kf / ST_N = $g24_st_n / GF_L2 = $g24_gf_l2"
foreach {par h nrow ncol} $g24_hex { puts "ROM       : $par = $h（$nrow 行 × $ncol 桁）" }

set projdir $outdir/vivado
set jobs 8
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }

# ------------------------------------------------------------------ helper
# 見つからなかったときに「何があるのか」を出す。素の get_bd_pins は空を返すだけで、
# connect_bd_net の側で意味の分からないエラーになる。
proc BP {path} {
    set p [get_bd_pins -quiet $path]
    if {[llength $p] == 0} {
        puts "ERROR: BD ピンが見つからない: $path"
        foreach q [get_bd_pins -quiet "[file dirname $path]/*"] { puts "    $q" }
        exit 1
    }
    return [lindex $p 0]
}
proc BI {cell patterns what} {
    foreach pat $patterns {
        set p [get_bd_intf_pins -quiet $cell/$pat]
        if {[llength $p] > 0} { return [lindex $p 0] }
    }
    puts "ERROR: $what が見つからない（$cell で試したパターン: $patterns）"
    puts "  $cell のインタフェースピン一覧:"
    foreach q [get_bd_intf_pins -quiet $cell/*] { puts "    $q" }
    exit 1
}
proc nc {a b} { connect_bd_net  [BP $a] [BP $b] }
proc ic {a b} { connect_bd_intf_net $a $b }

# CONFIG を **1 つずつ** 設定する。まとめて set_property すると最初の 1 つで止まり、
# 残りが正しいのかどうか分からないまま往復することになる。
# 失敗したものは「要求値」と「許される値」を控えて先へ進み、後でまとめて報告する。
# fatal = 0 の組は「設定できればよい」項目で、失敗しても止めない。
#
# **版によって CONFIG の名前が変わる IP では、候補を並べて全部投げる。**
# 存在しない名前は「この IP に存在しない名前」として控えられるだけで害はない。
# 効いたかどうかは **読み返しで判定する**（axis_combiner がこれ）。
set ::cfg_fail {}

proc cfg_apply {cell cfg {fatal 1}} {
    set obj   [get_bd_cells $cell]
    set known [list_property $obj]
    foreach {k v} $cfg {
        if {[lsearch -exact $known $k] < 0} {
            lappend ::cfg_fail [list $k $v "この IP に存在しない名前" $fatal]
            continue
        }
        if {[catch {set_property $k $v $obj} msg]} {
            # list_property_value は BD セルの CONFIG では空を返す。
            # **有効値は Vivado のエラーメッセージ本文にしか出ない**ので、それを残す。
            set why [string map {"\n" " "} $msg]
            if {[regexp {Valid values are - (.*)$} $why -> vals]} {
                set why "有効値: $vals"
            } elseif {[regexp {is out of the range \(([^)]*)\)} $why -> rng]} {
                set why "有効範囲: ($rng)"
            }
            lappend ::cfg_fail [list $k $v $why $fatal]
        }
    }
}

proc cfg_report {stage} {
    if {[llength $::cfg_fail] == 0} { return }
    puts ""
    puts "---- CONFIG の設定に失敗した項目（$stage）----"
    set hard 0
    foreach f $::cfg_fail {
        lassign $f k v why isfatal
        puts "  $k = $v[expr {$isfatal ? "" : "   （任意）"}]"
        puts "      $why"
        if {$isfatal} { incr hard }
    }
    set ::cfg_fail {}
    puts ""
    if {$hard > 0} {
        puts "  IP が実際に持つ CONFIG と許容値は $::outdir の *_params.rpt にある"
        exit 1
    }
}

# IP の CONFIG と、列挙なら許される値を書き出す。版がズレたときの唯一の手がかり。
proc dump_ip_params {obj path} {
    set fh [open $path w]
    # **BD のセルは VLNV、プロジェクトの IP（create_ip）は IPDEF に版を持つ。**
    # 片方しか無いので、在る方を読む（2026-09-18、IP に VLNV を聞いて落ちた）
    set props [list_property $obj]
    set vlnv "?"
    foreach k {VLNV IPDEF} {
        if {[lsearch -exact $props $k] >= 0} { set vlnv [get_property $k $obj]; break }
    }
    puts $fh "# $vlnv"
    foreach k [lsort [list_property $obj]] {
        if {![string match CONFIG.* $k]} continue
        set v ""       ; catch {set v [get_property $k $obj]}
        set allowed "" ; catch {set allowed [list_property_value $k $obj]}
        if {[llength $allowed] > 1} {
            puts $fh "$k = $v      \[$allowed\]"
        } else {
            puts $fh "$k = $v"
        }
    }
    close $fh
    puts "=== wrote $path ==="
}

# ------------------------------------------------------------------ project
if {[info exists ::env(BOARD_REPO)] && $::env(BOARD_REPO) ne ""} {
    set_param board.repoPaths $::env(BOARD_REPO)
    set board_repo $::env(BOARD_REPO)
} else {
    set board_repo "未設定"
    puts "WARNING: BOARD_REPO が未設定。board part が見つからなければ Makefile を確認する"
}

# has_preset は後段（build_post.tcl）も使う。プロジェクトに依らないので create_project の前で決める（proj025 2f、再開のため）
set use_board [expr {$part eq $board_part_part}]
set ps_preset_file [file normalize ./src/board/ps_preset.tcl]
set use_preset_file [expr {!$use_board && [file exists $ps_preset_file]}]
set has_preset [expr {$use_board || $use_preset_file}]

# ---- 再開（RESUME=1、`make post`）: 完走した impl_1 を開き、open_run から後（build_post.tcl）だけを回す ----
# proj025 2f ビルド 2: impl_1 は write_bitstream まで完走したのに、親の Vivado が open_run impl_1 で落ちた
#   （hs_err: HANENetlist::copyAttrsToAttrMap、signal 11）。run の外の落ち方なので、下の「落ちた run の回し直し」では拾えない。
#   **create_project -force を通らない**（通るとプロジェクトごと消える）。合成・実装はやり直さない
set resume [expr {[info exists ::env(RESUME)] && $::env(RESUME) eq "1"}]
if {$resume} {
    set xpr $projdir/$proj.xpr
    if {![file exists $xpr]} { puts "ERROR: 再開するプロジェクトが無い（$xpr）。make build から"; exit 1 }
    open_project $xpr
    set got_part [get_property PART [current_project]]
    if {$got_part ne $part} { puts "ERROR: プロジェクトの part が $got_part（期待 $part）"; exit 1 }
    foreach r {synth_1 impl_1} {
        if {[get_property PROGRESS [get_runs $r]] ne "100%"} { puts "ERROR: $r が完走していない。make build から"; exit 1 }
        if {[get_property NEEDS_REFRESH [get_runs $r]]} { puts "ERROR: $r が古い（Vivado がソースの変更を見ている）。make build から"; exit 1 }
    }
    set bit0 [lindex [glob -nocomplain $projdir/$proj.runs/impl_1/${bd_name}_wrapper.bit] 0]
    if {$bit0 eq ""} { puts "ERROR: impl_1 の .bit が無い。make build から"; exit 1 }
    # 「在ってはいけない」側: .bit より新しいソース（RTL・XDC・hex・ps_preset）があれば、その .bit は今の RTL ではない
    set t_bit [file mtime $bit0]
    set newer {}
    foreach f [split [exec find ./src -type f] "\n"] { if {$f ne "" && [file mtime $f] > $t_bit} { lappend newer $f } }
    if {[llength $newer] > 0} { puts "ERROR: .bit より新しいソースがある: $newer。make build から"; exit 1 }
    puts "RESUME    : $xpr の impl_1 から後段だけ（.bit [clock format $t_bit -format {%Y-%m-%d %H:%M:%S}]、sha256 [lindex [exec sha256sum $bit0] 0]）"
    source ./build_post.tcl
    exit 0
}

file mkdir $outdir
create_project $proj $projdir -part $part -force

# board_part は part をボードの宣言値（-2）へ強制的に戻す（WARNING: Project 1-153）。
# -1 では board_part を使わず、src/board/ps_preset.tcl の PS の設定を明示して当てる（proj015）
if {$use_preset_file} {
    source $ps_preset_file
    if {![info exists ps_preset_excluded]} { set ps_preset_excluded {} }
    puts "PS PRESET : $ps_preset_file（board part $ps_preset_board_part、当てる [expr {[llength $ps_preset] / 2}] 個・照らす [expr {[llength $ps_preset_derived] / 2}] 個・-1 で当てない [expr {[llength $ps_preset_excluded] / 2}] 個）"
}

if {$use_board} {
    set bp [lindex [get_board_parts -quiet -latest_file_version *rfsoc4x2*] 0]
    if {$bp eq ""} {
        puts "ERROR: RFSoC4x2 の board part が見つからない。以下を順に確認する:"
        puts "  1. BOARD_REPO が RFSoC4x2-BSP/board_files を指しているか（= $board_repo）"
        puts "  2. その下に rfsoc4x2/<version>/board.xml があるか"
        puts "  3. BSP が Vivado 2024.1 前提。古い Vivado では読まれないことがある"
        exit 1
    }
    puts "BOARD PART: $bp"
    set_property board_part $bp [current_project]
} elseif {$use_preset_file} {
    puts "NOTE: board_part は使わない（part $part のまま）。PS には src/board/ps_preset.tcl を当てる"
} else {
    puts "NOTE: src/board/ps_preset.tcl が無い。PS にプリセットを当てない検証ビルド（実機に使わない）。make ps-preset で作る"
}

# proj024: コア（g24_s45_core）とその中身。Wide の wide_* と共有の ROM は足さない
add_files -norecurse [list ./src/g24/g24_s45_core.v ./src/g24/g24_core.v ./src/g24/g24_spec.v ./src/g24/g24_pfb.v ./src/g24/g24_pfb_core.v \
                           ./src/g24/g24_cu.v ./src/g24/g24_tw.v ./src/g24/g24_acc.v \
                           ./src/s2_sep.v ./src/s2_chain.v ./src/s2_q.v \
                           ./src/common/core_cmn.v ./src/common/raw_core.v ./src/common/cmul.v ./src/common/dft16f.v ./src/common/tp_core.v \
                           ./src/common/rec_fr.v ./src/common/rec_arb.v ./src/common/adc_ev.v]
# proj031: g24_cu が include する CRC の式（tools/gen_crc32.py の生成物）
add_files -norecurse [list ./src/g24/crc32_d32.vh]
set_property file_type {Verilog Header} [get_files crc32_d32.vh]
set_property include_dirs [list [file normalize ./src/g24]] [get_filesets sources_1]
# proj016〜: 時刻・リング・ギアボックスの見張り・入力の選び
add_files -norecurse [list ./src/common/time_core.v ./src/common/s45_ring.v ./src/common/gb_adc.v ./src/common/gb_gate.v ./src/common/axis_sel4.v]
# ROM の中身（$readmemh）。プロジェクトにも載せておく（CONFIG には絶対パスを与える。上の g24_hex）
set hex_files [lmap {par h nrow ncol} $g24_hex {set h}]
add_files -norecurse $hex_files
set_property file_type {Memory File} [get_files $hex_files]
set win_range 65536       ;# s45_core_0 の AXI4-Lite の窓（16 bit 番地 = 64 KiB。INTERFACE 3.）

# ------------------------------------------------------------------ FFT IP（lane_fft_w。proj023）
# wide_spec.v がレーンごとに 1 個（コアごと 16 個、計 64 個）使う。2048 点固定・入力 15 bit・unscaled（出力 27 bit）。
# 以下の説明の「lane_fft・512 点・入力 14 bit・spec_core.v」は proj011〜021 のもの。照合の形はそのまま、名前と幅を $fft_mod に替えた
# spec_core.v がレーンごとに 1 個（計 16 個）使う。**名前 lane_fft は RTL と対**。
# 設定の意味（spec_core.v / sim/lane_fft_model.v の冒頭と対）:
#   512 点・pipelined streaming・固定小数点・入力 14 bit・**unscaled**（出力 24 bit、飽和も丸めの
#   スケーリングも起きない。|Y| ≦ 2^22 の上限は spec_core.v の冒頭）
#   **自然順で出力し XK_INDEX を載せる**（k1 でひねり係数と積分の番地を引くため）
#   **realtime**（proj011。入力が途切れても IP は待たない。途切れは spec_core の FLAGS[4] / [6] が捕まえる。
#   出力側の tready は IP に無い）
#   乗算器・バタフライは FFT_OPT で選ぶ（src/sam45fine/fft_cfg.tcl）
# CONFIG の名前は版で変わりうるので、1 つずつ投げて **読み返しで判定する**（proj003 の流儀）。
create_ip -name xfft -vendor xilinx.com -library ip -module_name $fft_mod
set xfft [get_ips $fft_mod]
set xfft_req [fft_req $fft_lane_n $fft_in_w $fft_order $dsp_mhz]
set known [list_property $xfft]
foreach {k v fatal} $xfft_req {
    if {[lsearch -exact $known $k] < 0} {
        lappend ::cfg_fail [list $k $v "この IP に存在しない名前" $fatal]
        continue
    }
    if {[catch {set_property $k $v $xfft} msg]} {
        lappend ::cfg_fail [list $k $v [string map {"\n" " "} $msg] $fatal]
    }
}
dump_ip_params $xfft $outdir/xfft_params.rpt
cfg_report "FFT IP の設定（xfft_params.rpt に全 CONFIG）"

puts ""
puts "---- FFT IP の確定値 ----"
set ng 0
foreach {k v fatal} $xfft_req {
    set got ""
    catch {set got [get_property $k $xfft]}
    set ok [expr {[string equal -nocase $got $v]}]
    puts [format "  %-44s = %-24s %s" $k $got [expr {$ok ? "OK" : ($fatal ? "違う（要求 $v）" : "（任意）要求 $v")}]]
    if {!$ok && $fatal} { incr ng }
}
# 出力語幅は派生値。**spec_core.v の YW = 24 はこれを前提にしている**
set ow ""
catch {set ow [get_property CONFIG.output_width $xfft]}
puts [format "  %-44s = %s（期待 %d）" CONFIG.output_width $ow $fft_out_w]
if {$ow ne "" && $ow != $fft_out_w} { incr ng }
if {$ow eq ""} { puts "  NOTE: output_width を読めない。下のポート幅の照合で代える" }
if {$ng > 0} {
    puts "ERROR: FFT IP の設定が $ng 件、要求どおりになっていない（xfft_params.rpt を見る）"
    exit 1
}

generate_target {instantiation_template synthesis simulation} $xfft

# ---- RTL が使うポートが IP に在るか・幅が合うか ----
# spec_core.v は名前付きで繋いでいる。IP 側に無い名前は合成エラーになるが、
# **合成まで 10 分待たずに、ここで原因を言って止める。**幅は RTL が固定値で書いている。
# IP のトップ（VHDL）のポート宣言を読む。
set want_ports [dict create \
    aclk 1 aresetn 1 \
    s_axis_config_tdata 8 s_axis_config_tvalid 1 s_axis_config_tready 1 \
    s_axis_data_tdata 32 s_axis_data_tvalid 1 s_axis_data_tready 1 s_axis_data_tlast 1 \
    m_axis_data_tdata 64 m_axis_data_tuser 16 m_axis_data_tvalid 1 m_axis_data_tlast 1 \
    event_frame_started 1 event_tlast_unexpected 1 event_tlast_missing 1 event_data_in_channel_halt 1 ]
set top ""
foreach f [get_files -quiet -of_objects [get_files ${fft_mod}.xci]] {
    if {[string match "*/synth/${fft_mod}.vhd" $f]} { set top $f }
}
if {$top eq ""} {
    puts "WARNING: IP のトップ（synth/lane_fft.vhd）が見つからない。ポートの照合を飛ばす"
} else {
    set fh [open $top r]; set txt [read $fh]; close $fh
    # **entity の宣言の中だけを読む。**lane_fft.vhd には IP コア（xfft_v9_1_x）の component 宣言も入っていて、
    # そちらは設定に依らず**全部のポート**（aclken・m_axis_data_tready・m_axis_status_* …）を持つ。
    # ファイル全体を読むと「在るか」は component 側で必ず通り、「在ってはいけないか」は必ず落ちる
    # （2026-09-24、proj011 の初回ビルドで realtime の IP に m_axis_data_tready が「在る」と誤判定した）。
    if {![regexp -nocase -indices "\\mentity\\s+${fft_mod}\\s+is\\M" $txt ent_a]} {
        puts "ERROR: $top に entity $fft_mod の宣言が見つからない"
        exit 1
    }
    set a0 [lindex $ent_a 1]
    if {![regexp -nocase -indices -start $a0 "\\mend\\s+(entity\\s+)?${fft_mod}\\s*;" $txt ent_b]} {
        puts "ERROR: $top の entity $fft_mod の終わりが見つからない"
        exit 1
    }
    set ent_txt [string range $txt $a0 [lindex $ent_b 0]]
    set have [dict create]
    foreach {all name dir hi} [regexp -all -inline -nocase \
            {\m(\w+)\s*:\s*(in|out)\s+std_logic(?:_vector\s*\(\s*(\d+)\s+downto\s+0\s*\))?} $ent_txt] {
        set w [expr {$hi eq "" ? 1 : $hi + 1}]
        if {![dict exists $have [string tolower $name]]} { dict set have [string tolower $name] $w }
    }
    set ng 0
    puts ""
    puts "---- FFT IP のポート（entity $fft_mod の宣言から [dict size $have] 本）----"
    dict for {n w} $want_ports {
        if {![dict exists $have $n]} {
            puts [format "  %-30s 無い" $n]; incr ng
        } elseif {[dict get $have $n] != $w} {
            puts [format "  %-30s 幅 %d（RTL は %d）" $n [dict get $have $n] $w]; incr ng
        } else {
            puts [format "  %-30s %2d OK" $n $w]
        }
    }
    # **在ってはいけないポート。**realtime の IP には出力側の tready が無い（PG109）。
    # 在れば、throttle_scheme の読み返しが通っていても IP は nonrealtime で生成されている
    foreach n {m_axis_data_tready} {
        if {[dict exists $have $n]} {
            puts [format "  %-30s 在る（realtime なら無いはず）" $n]; incr ng
        } else {
            puts [format "  %-30s 無い OK（realtime）" $n]
        }
    }
    if {$ng > 0} {
        puts "ERROR: FFT IP のポートが g24_spec.v の前提と $ng 件合わない。entity $fft_mod にあるポート:"
        dict for {n w} $have { puts "    $n ($w)" }
        exit 1
    }
}

# proj023 3b: win_fft（窓の FFT）は外した（D-4）
update_compile_order -fileset sources_1

# ------------------------------------------------------------------ block design
create_bd_design $bd_name

# ---- PS ----
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e zynq_ultra_ps_e_0]
if {$use_board} {
    apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
        -config {apply_board_preset "1"} $ps
} elseif {$use_preset_file} {
    # proj015: ボードプリセットの PS の設定を明示して当て、**読み返して照らす**（当てる設定は全部一致が必要・導出されるものは数えて出す）
    if {[get_property VLNV $ps] ne $ps_preset_vlnv} {
        puts "ERROR: PS の VLNV [get_property VLNV $ps] が ps_preset.tcl の $ps_preset_vlnv と違う（Vivado の版が変わった？ make ps-preset で作り直す）"
        exit 1
    }
    set_property -dict $ps_preset $ps
    set ng 0
    foreach {k v} $ps_preset {
        set got [get_property $k $ps]
        if {$got ne $v} { incr ng; puts "  PS PRESET 違う: $k = $got（要求 $v）" }
    }
    set nd 0
    foreach {k v} $ps_preset_derived {
        set got ""
        catch {set got [get_property $k $ps]}
        if {$got ne $v} { incr nd; puts "  PS PRESET（導出）違う: $k = $got（プリセット $v）" }
    }
    puts [format "PS PRESET : 当てた %d 個のうち違う %d 個 / 導出される %d 個のうち違う %d 個" \
            [expr {[llength $ps_preset] / 2}] $ng [expr {[llength $ps_preset_derived] / 2}] $nd]
    if {$ng > 0} { puts "ERROR: PS にプリセットの設定が当たっていない"; exit 1 }
}

# 使う AXI ポートだけでなく、**使わないものも明示的に 0 にする**。
# ボードプリセットが何を有効にするかに設計が依存しないようにするため
# （proj002 で HPM1_FPD の未接続クロックにより BD 41-758 を踏んだ）。
#   M_AXI: GP0 = HPM0_FPD / GP1 = HPM1_FPD / GP2 = HPM0_LPD
#   S_AXI: GP0 = HPC0_FPD / GP1 = HPC1_FPD / GP2 = HP0_FPD / GP3..5 = HP1..3_FPD / GP6 = LPD
set_property -dict [list \
    CONFIG.PSU__FPGA_PL0_ENABLE {1} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ $ctrl_mhz \
    CONFIG.PSU__FPGA_PL1_ENABLE {0} \
    CONFIG.PSU__USE__M_AXI_GP0 {1} \
    CONFIG.PSU__USE__M_AXI_GP1 {0} \
    CONFIG.PSU__USE__M_AXI_GP2 {0} \
    CONFIG.PSU__USE__S_AXI_GP0 {0} \
    CONFIG.PSU__USE__S_AXI_GP1 {0} \
    CONFIG.PSU__USE__S_AXI_GP2 {1} \
    CONFIG.PSU__SAXIGP2__DATA_WIDTH {128} \
    CONFIG.PSU__USE__S_AXI_GP3 {0} \
    CONFIG.PSU__USE__S_AXI_GP4 {0} \
    CONFIG.PSU__USE__S_AXI_GP5 {0} \
    CONFIG.PSU__USE__S_AXI_GP6 {0} \
    CONFIG.PSU__USE__IRQ0 {0} \
    CONFIG.PSU__USE__IRQ1 {0} \
] $ps
# proj021 手順 2-2a: S_AXI_HP0_FPD（GP2）をリング（s45_ring_0）の書き手に。128 bit・DSP のクロック
foreach {k want} {CONFIG.PSU__USE__S_AXI_GP2 1 CONFIG.PSU__SAXIGP2__DATA_WIDTH 128 CONFIG.PSU__USE__S_AXI_GP0 0 CONFIG.PSU__USE__S_AXI_GP3 0} {
    if {[get_property $k $ps] != $want} { puts "ERROR: PS の $k が [get_property $k $ps]（要求 $want）"; exit 1 }
}

# ---- RFDC ----
# PYNQ 側から ol.rfdc で引けるよう、セル名を rfdc にする
set rfdc [create_bd_cell -type ip -vlnv xilinx.com:ip:usp_rf_data_converter rfdc]

# **設定の順序が全て。** 2026-09-16 に順に踏んだ内容を順序として固定してある。
#
#   1. スライスを有効にする。これをしないとタイルのパラメータは disabled parameter で、
#      set_property が WARNING: [BD 41-721] の 1 行だけ出して **黙って無視される**
#   2. スライスの設定（Data_Width 等）。Fabric_Freq の計算に効く
#   3. PLL を有効化 → **Sampling Rate** → **Refclk Freq** → Outclk Freq。
#      Refclk の有効値は VCO / FeedbackDiv の離散リストで、VCO は Sampling Rate から
#      決まる。**fs を先に入れないと 491.52 が選択肢に現れない**
#   4. 残り（派生値になりうるもの）
#
# ADCn_Enable と ADCn_Fabric_Freq は派生パラメータなので触らない（読むだけ）。
#
# 全段を「失敗しても止めない」で流し、**最後に読み返しで検証する**。

# 1) 使うスライスを有効にする
set on {}
foreach ch $chans {
    lassign $ch t s
    lappend on CONFIG.ADC_Slice${t}${s}_Enable {true}
}
cfg_apply rfdc $on 0
dump_ip_params $rfdc $outdir/rfdc_params.rpt

# 2) 使わないタイル / スライスを明示的に落とす。
#    **デュアルタイルのスライスは 0 と 2 のみ**（1 と 3 は disabled parameter になる。
#    2026-09-16 の警告で確定した）。
#    既定で ADC0 が有効なので、放置すると使わない外部ポートが .hwh に残る。
set off {}
foreach t {0 1 2 3} {
    foreach sl {0 2} {
        if {[lsearch -exact $chans [list $t $sl]] < 0} {
            lappend off CONFIG.ADC_Slice${t}${sl}_Enable {false}
        }
        lappend off CONFIG.DAC_Slice${t}${sl}_Enable {false}
    }
}
cfg_apply rfdc $off 0

# 3) スライスの設定
#    Data_Type       0 = Real
#    Decimation_Mode 1 = 1x（デシメーションなし）
#    Mixer_Type      1 = Bypassed。**有効値は Data_Type と Decimation_Mode に依存して
#                    絞られ、Real / 1x では 1 しか許されない**
#
#    **Data_Width は同じタイルのスライスどうしで揃っていなければならない。**
#    1 つずつ変えると「片方だけ 12・もう片方は 8」の中間状態が不正になって弾かれ、
#    どちらも既定の 8 から動けない（2026-09-18、4ch 版で 4 スライスとも 8 のまま止まった。
#    1ch 版はタイルにスライスが 1 本なので表に出なかった。proj006 は spw = 8 = 既定値で、変える必要がなかった）。
#    **タイルごとに全スライスをまとめて 1 回の set_property で設定する。**
foreach t $adc_tiles {
    set d {}
    foreach ch $chans {
        lassign $ch tt s
        if {$tt != $t} continue
        set S "${t}${s}"
        lappend d CONFIG.ADC_Data_Type${S}       {0} \
                  CONFIG.ADC_Data_Width${S}      $spw_adc \
                  CONFIG.ADC_Decimation_Mode${S} {1} \
                  CONFIG.ADC_Mixer_Type${S}      {1}
    }
    if {[catch {set_property -dict $d $rfdc} msg]} {
        # 失敗しても止めない。下の読み返しで判定する（有効値はログの IP_Flow 19-3461 の行）
        lappend ::cfg_fail [list "Tile [expr {224 + $t}] のスライス設定（まとめて）" $d \
                                 [string map {"\n" " "} $msg] 0]
    }
}

# 4) タイルの設定。**この順序を崩さないこと**
#    Clock_Source を自タイルにする = クロック転送（Clock_Dist）を使わない。
#    RefMan では ADC 用 LMX2594 が両タイルへ 491.52 MHz を配るので、
#    **各タイルが自前のクロック入力を持つ**前提である。
#    もし adcN_clk のインタフェースが片方しか出てこなければこの前提が誤りで、
#    Clock_Dist によるクロック転送に切り替える必要がある（下の外部ポートで分かる）。
foreach t $adc_tiles {
    cfg_apply rfdc [list CONFIG.ADC${t}_PLL_Enable    {true}]      0
    cfg_apply rfdc [list CONFIG.ADC${t}_Sampling_Rate $fs_gsps]    0
    cfg_apply rfdc [list CONFIG.ADC${t}_Refclk_Freq   $refclk_mhz] 0
    cfg_apply rfdc [list CONFIG.ADC${t}_Outclk_Freq   $outclk_mhz] 0
}

# 5) 残り。ミキサをバイパスすると派生値になりうる
foreach t $adc_tiles {
    cfg_apply rfdc [list \
        CONFIG.ADC${t}_Clock_Source    $t \
        CONFIG.ADC${t}_Clock_Dist      {0} \
        CONFIG.ADC${t}_Multi_Tile_Sync {false} \
    ] 0
}
foreach ch $chans {
    lassign $ch t s
    set S "${t}${s}"
    cfg_apply rfdc [list \
        CONFIG.ADC_Mixer_Mode${S} {2} \
        CONFIG.ADC_NCO_Freq${S}   {0} \
        CONFIG.ADC_OBS${S}        {false} \
    ] 0
}

cfg_report "RFDC の設定（読み返しで検証するので、ここでは止めない）"
dump_ip_params $rfdc $outdir/rfdc_params.rpt

# ---- 読み返しによる検証 ----
# BD 41-721 は警告 1 行しか出さず、set_property のエラーも
# 「前の正しい設定に戻した」とだけ言って進む。**結果を読み返す以外に
# 「設定したつもりで効いていない」状態を検出する手段がない。**
puts ""
puts "---- RFDC の確定値 ----"
set ng 0
set want {}
foreach t $adc_tiles {
    lappend want CONFIG.ADC${t}_Sampling_Rate $fs_gsps    num
    lappend want CONFIG.ADC${t}_Refclk_Freq   $refclk_mhz num
    lappend want CONFIG.ADC${t}_Outclk_Freq   $outclk_mhz num
    # **両タイルの Fabric_Freq が同じであることが、MMCM 1 個で足りる根拠。**
    lappend want CONFIG.ADC${t}_Fabric_Freq   $fabric_mhz num
}
foreach ch $chans {
    lassign $ch t s
    set S "${t}${s}"
    lappend want CONFIG.ADC_Data_Type${S}       0    int
    lappend want CONFIG.ADC_Data_Width${S}      $spw_adc int
    lappend want CONFIG.ADC_Decimation_Mode${S} 1    int
    lappend want CONFIG.ADC_Mixer_Type${S}      1    int
}
foreach {k w kind} $want {
    set got ""
    catch {set got [get_property $k $rfdc]}
    set ok 0
    if {$kind eq "num"} {
        if {![catch {expr {abs($got - $w) < 1e-6}} r] && $r} { set ok 1 }
    } else {
        if {$got eq $w} { set ok 1 }
    }
    puts [format "  %-34s = %-12s %s" $k $got [expr {$ok ? "OK" : "違う（要求 $w）"}]]
    if {!$ok} { incr ng }
}
if {$ng > 0} {
    puts ""
    puts "ERROR: RFDC の設定が $ng 件反映されていない。"
    puts "  理由と有効値はログの ERROR: [IP_Flow 19-34xx] の行にある（catch で拾えるのは"
    puts "  「Common 17-39 failed due to earlier errors」だけ）。"
    puts "  全 CONFIG と現在値は $outdir/rfdc_params.rpt。"
    puts "  fs / refclk / VCO の関係は build.tcl 冒頭の計算を見直すこと"
    exit 1
}
puts "RFDC (確定): fs = $fs_mhz MSPS / refclk = $refclk_mhz MHz / AXIS = $fabric_mhz MHz × $nch ch"

# ---- クロックピンの実周波数を読む ----
# **clk_adcN が Outclk_Freq（fs/16 = 256 MHz）であること**を確かめる。
# ここが違うと「MMCM 1 個を両タイルで共有する」という設計の前提が崩れる。
puts ""
puts "---- RFDC のクロックピン ----"
foreach pin [lsort [get_bd_pins -quiet rfdc/*]] {
    set hz ""
    catch {set hz [get_property CONFIG.FREQ_HZ $pin]}
    if {$hz ne ""} { puts [format "  %-28s %s Hz" [file tail $pin] $hz] }
}

set want_hz [expr {double($outclk_mhz) * 1e6}]
foreach t $adc_tiles {
    set hz ""
    catch {set hz [get_property CONFIG.FREQ_HZ [BP rfdc/clk_adc${t}]]}
    if {$hz eq ""} {
        puts "CRITICAL WARNING: clk_adc${t} の FREQ_HZ が読めない。合成後に clocks.rpt で確認すること"
    } elseif {abs($hz - $want_hz) > 1.0} {
        puts ""
        puts "ERROR: clk_adc${t} = $hz Hz で、Outclk_Freq の要求 $want_hz Hz と違う。"
        puts "  Clocking Wizard の入力周波数の前提が崩れる。上の一覧を見て判断すること"
        exit 1
    } else {
        puts "clk_adc${t} = $hz Hz"
    }
}
puts ""

# ---- AXIS クロックを作る Clocking Wizard（1 個）----
# RFDC は AXIS クロックを出さない（clk_adcN は Outclk_Freq = fs/16）。spw = 16 なら 1:1。
# **PS の PL クロックでは代用できない。**AXIS クロックは fs / spw きっかりである必要が
# あり、わずかでもずれると FIFO が溢れるか枯れる。
#
# **1 個だけ置いて、両タイルの m*_axis_aclk に配る。**両タイルは同じ LMX2594 の
# 491.52 MHz から同じ fs を作っているので、Fabric_Freq は上の読み返しで同一を確認済み。
# 2 個置くと MMCM 2 個ぶんの位相不定が入るだけで、得るものがない。
# **出力は 2 本。**同じ MMCM から出すので周波数比 4:3 は厳密に保たれる。
#   clk_out1 = fs / spw_adc = 341.333 MHz  RFDC の AXIS とギアボックスの入口（ADC ドメイン）
#   clk_out2 = fs / spw     = 256.000 MHz  ギアボックスの出口以降（DSP ドメイン）
# 入力 256 MHz から VCO 1024 MHz（×4）を作れば、÷3 と ÷4 で両方がちょうど出る。
set clkw [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz clk_wiz_adc]
set wiz_cfg [list \
    CONFIG.PRIM_SOURCE                  {No_buffer} \
    CONFIG.PRIM_IN_FREQ                 $outclk_mhz \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ   $fabric_mhz \
    CONFIG.USE_LOCKED                   {true} \
    CONFIG.USE_RESET                    {true} \
    CONFIG.RESET_TYPE                   {ACTIVE_LOW} \
    CONFIG.RESET_PORT                   {resetn} \
]
if {$use_gb} {
    lappend wiz_cfg CONFIG.CLKOUT2_USED {true} CONFIG.CLKOUT2_REQUESTED_OUT_FREQ $dsp_mhz
}
cfg_apply clk_wiz_adc $wiz_cfg 0
cfg_report "Clocking Wizard の設定"

set wiz_want [list CONFIG.PRIM_IN_FREQ $outclk_mhz CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $fabric_mhz]
if {$use_gb} { lappend wiz_want CONFIG.CLKOUT2_REQUESTED_OUT_FREQ $dsp_mhz }
foreach {k w} $wiz_want {
    set got [get_property $k $clkw]
    if {abs($got - $w) > 1e-6} {
        puts "ERROR: Clocking Wizard が設定を丸めた: $k  要求 $w / 実際 $got"
        exit 1
    }
}
# CLKOUTn_ACTUAL_FREQ はこの時点では空のことがある（validate 後に確定する）。
# **validate 後にもう一度読む**（下の「Clocking Wizard の実出力」）。
proc wiz_actual_check {clkw pairs stage} {
    foreach {n want} $pairs {
        set act ""
        catch {set act [get_property CONFIG.CLKOUT${n}_ACTUAL_FREQ $clkw]}
        puts [format "  clk_out%d  要求 %s MHz → 実際 %s MHz（%s）" $n $want \
              [expr {$act eq "" ? "未確定" : $act}] $stage]
        if {$act ne "" && abs($act - $want) > 1e-3} {
            puts "ERROR: Clocking Wizard の clk_out$n が要求と違う（$act MHz）。"
            puts "  AXIS クロックは fs / spw きっかりでなければならない。ずれると FIFO が溢れるか枯れる"
            exit 1
        }
    }
}
set wiz_pairs [list 1 $fabric_mhz]
if {$use_gb} { lappend wiz_pairs 2 $dsp_mhz }
puts "CLK WIZ    : 入力 $outclk_mhz MHz"
wiz_actual_check $clkw $wiz_pairs "設定直後"
puts ""

# ---- ギアボックス（ch ごと。spw_adc → spw の詰め替え）----
# RFDC ─(spw_adc×16 bit @ fabric)─▶ gb_up（×gb_up）─▶ gb_fifo（非同期）─▶ gb_dn（÷gb_dn）─(spw×16 bit @ dsp)─▶
#
# **サンプルの順序は保たれる。**axis_dwidth_converter は、まとめるときは先に来た語を
# 下位に置き、割るときは下位から先に出す。RFDC の語も下位が先のサンプルなので、
# 12 → 48 → 16 のどの段でも「下位ほど古い」が崩れない（proj009 の lane_check で実機確認済み）。
# spec_core はこの並びを前提にレーン p = サンプル 16m + p と読む。
#
# **上流に backpressure をかけてはいけない**（RFDC がサンプルを落とす）。流入と流出の
# 速度は厳密に等しく、下流（spec_core）は常に受け取る（tready = 1）ので、gb_fifo は浅くてよい。
if {$use_gb} {
    set i 0
    foreach ch $chans {
        create_bd_cell -type ip -vlnv xilinx.com:ip:axis_dwidth_converter gb_up_$i
        cfg_apply gb_up_$i [list \
            CONFIG.S_TDATA_NUM_BYTES [expr {$spw_adc * 2}] \
            CONFIG.M_TDATA_NUM_BYTES [expr {$gb_mid * 2}] \
            CONFIG.HAS_TLAST {0} CONFIG.HAS_TKEEP {0} CONFIG.HAS_TSTRB {0} \
        ] 0
        create_bd_cell -type ip -vlnv xilinx.com:ip:axis_data_fifo gb_fifo_$i
        cfg_apply gb_fifo_$i [list \
            CONFIG.TDATA_NUM_BYTES  [expr {$gb_mid * 2}] \
            CONFIG.FIFO_DEPTH       {32} \
            CONFIG.IS_ACLK_ASYNC    {1} \
            CONFIG.HAS_TLAST {0} CONFIG.HAS_TKEEP {0} CONFIG.HAS_TSTRB {0} \
        ] 0
        # rev6: 読み出し側の残量（gb_gate がしきい値 K と見張りに使う）。**無いと gb_gate が働かない**ので fatal
        cfg_apply gb_fifo_$i [list CONFIG.HAS_RD_DATA_COUNT {1}] 1
        create_bd_cell -type ip -vlnv xilinx.com:ip:axis_dwidth_converter gb_dn_$i
        cfg_apply gb_dn_$i [list \
            CONFIG.S_TDATA_NUM_BYTES [expr {$gb_mid * 2}] \
            CONFIG.M_TDATA_NUM_BYTES [expr {$spw * 2}] \
            CONFIG.HAS_TLAST {0} CONFIG.HAS_TKEEP {0} CONFIG.HAS_TSTRB {0} \
        ] 0
        incr i
    }
    cfg_report "ギアボックスの設定（読み返しで検証するので、ここでは止めない）"
    for {set i 0} {$i < $nch} {incr i} {
        foreach {k want} {CONFIG.IS_ACLK_ASYNC 1 CONFIG.HAS_RD_DATA_COUNT 1 CONFIG.FIFO_DEPTH 32} {
            set got [get_property $k [get_bd_cells gb_fifo_$i]]
            puts [format "GEARBOX    : gb_fifo_%d %s = %s（期待 %s）" $i $k $got $want]
            if {$got != $want} { puts "ERROR: gb_fifo_$i の $k が $got"; exit 1 }
        }
    }
    # **読み返しで判定する。**語幅が 1 段でも違えば、サンプルの並びが崩れる。
    set i 0
    foreach ch $chans {
        foreach {cell pin want} [list \
                gb_up_$i   M_AXIS [expr {$gb_mid * 2}] \
                gb_fifo_$i M_AXIS [expr {$gb_mid * 2}] \
                gb_dn_$i   M_AXIS [expr {$spw * 2}]] {
            set nb ""
            catch {set nb [get_property CONFIG.TDATA_NUM_BYTES [get_bd_intf_pins $cell/$pin]]}
            puts [format "GEARBOX    : %-10s %s = %s B（期待 %s）" $cell $pin $nb $want]
            if {$nb eq "" || $nb != $want} {
                puts "ERROR: ギアボックスの語幅が期待と違う（$cell）。CONFIG の名前が版で変わっている可能性"
                exit 1
            }
        }
        incr i
    }
}

# ---- 分光計コア（spec_core.v。中で lane_fft を 16 個使う）と、ギアボックスの見張り（rev6）を ch ごとに ----
# PYNQ から ol.spec_core_<i> で引く（i = 0..3 = ADC_A..D）。AXI4-Lite（s_axi）と AXI4-Stream（s_axis）は
# ポート名の接頭辞から推論される。**推論されなかったらここで止める。**
#
# ビルドの指紋（rev4）: [30] ボードのプリセットあり / [29:28] 速度グレード。**ID では build/ と build-1-e/ を区別できない**
# （同じ RTL・同じ FFT_OPT）ので、PS がこれを読んで、プリセットの無い検証ビルドを実機に載せたら止める。
# rev6: [27] 遅いビットの検証ビルド（GB_SLOW）/ [26:24] そのビット（gb_fifo_0 = ADC_A だけに効く）
# proj012: [23] 4ch のビルド / [1:0] ch の番号 i。**同じ RTL の 4 個を PS から見分ける唯一の手がかり**
# ビルド時刻は入れない（定数が変わると配置が組み替わり、作り直しが WNS まで再現しなくなる）
set grade [string index [lindex [split $part -] 2] 0]
if {![string is integer -strict $grade] || $grade < 1 || $grade > 3} {
    puts "ERROR: part '$part' から速度グレードが読めない"
    exit 1
}
set build_tag_base [expr {($has_preset << 30) | (($grade & 3) << 28) | (1 << 23)}]   ;# [30] = PS にプリセット（board_part か ps_preset.tcl）

# gb_fifo の axis_rd_data_count の幅は版で変わりうるので、ピンの幅を読んで与える（4 個とも同じ設定なので gb_fifo_0 で読む）
set rdc [get_bd_pins -quiet gb_fifo_0/axis_rd_data_count]
if {[llength $rdc] == 0} {
    puts "ERROR: gb_fifo_0/axis_rd_data_count が無い（HAS_RD_DATA_COUNT が効いていない）。gb_fifo_0 のピン:"
    foreach p [get_bd_pins gb_fifo_0/*] { puts "  $p" }
    exit 1
}
set rdc_w [expr {[get_property LEFT $rdc] - [get_property RIGHT $rdc] + 1}]

# proj024: 入力の選びは 2 個（D-8・D-14）。full_sel → s45_core_0/s_axis_full（FULL の流れの SRC）、raw_sel → s45_core_0/s_axis_raw（RAW の流れの SRC）
# proj025: FULL の選びはコアごと（full_sel_0・full_sel_1、E-4）＋ raw_sel（コア 0）の 3 個
# proj027: FULL も RAW もコアごと（full_sel_0〜3・raw_sel_0〜3、F-4・F-5）の 8 個。**この並びが gb_bc_i の M01〜M08 の順**
set sel_names {}
foreach kind {full_sel raw_sel} { for {set c 0} {$c < $ncore} {incr c} { lappend sel_names ${kind}_$c } }
foreach sname $sel_names {
    set c [create_bd_cell -type module -reference axis_sel4 $sname]
    set_property CONFIG.DW $beat_bits $c
    if {[get_property CONFIG.DW $c] != $beat_bits} { puts "ERROR: $sname の DW が要求と違う"; exit 1 }
    for {set i 0} {$i < $nch} {incr i} {
        set sel_axis($sname,$i) [BI $sname [list "s${i}_axis" "S${i}_AXIS"] "$sname の入力 $i"]
    }
    set sel_m($sname) [BI $sname [list "m_axis" "M_AXIS"] "$sname の出力"]
}

# proj016: 時刻（time_core_0）。BUILD_TAG = 土台 ＋ [20] 時刻のコア
set tcore [create_bd_cell -type module -reference time_core time_core_0]
set time_tag [expr {$build_tag_base | (1 << 20)}]
foreach {k want} [list CONFIG.BUILD_TAG $time_tag CONFIG.BIT_KIND $g24_kind CONFIG.BIT_REV 1 CONFIG.PROJ $g24_proj] {   ;# proj027: 2G-4
    set_property $k $want $tcore
    if {[get_property $k $tcore] != $want} { puts "ERROR: time_core_0 の $k が [get_property $k $tcore]（要求 $want）"; exit 1 }
}
foreach {k want} {CONFIG.BEATS_PER_SEC 256000000 CONFIG.BLANK_BEATS 128000000 CONFIG.MISS_BEATS 384000000} {
    if {[get_property $k $tcore] != $want} { puts "ERROR: time_core_0 の $k が [get_property $k $tcore]（期待 $want）"; exit 1 }
}
if {abs([get_property CONFIG.BEATS_PER_SEC $tcore] - $dsp_mhz * 1e6) > 0.5} {
    puts "ERROR: time_core_0 の BEATS_PER_SEC（[get_property CONFIG.BEATS_PER_SEC $tcore]）が DSP のクロック $dsp_mhz MHz と合わない"
    exit 1
}
set time_axi [BI time_core_0 [list "s_axi" "S_AXI"] "time_core_0 の AXI4-Lite"]
puts [format "time_core_0: BUILD_TAG = 0x%08x / 1 秒 = %d ビート" $time_tag [get_property CONFIG.BEATS_PER_SEC $tcore]]

# リング（s45_ring_0）。入口はコアの数（4 本、全部使う）、書き手 → PS の S_AXI_HP0_FPD
set rcore [create_bd_cell -type module -reference s45_ring s45_ring_0]
foreach {k want} [list CONFIG.NIN $ncore CONFIG.BIT_KIND $g24_kind CONFIG.BIT_REV 1 CONFIG.PROJ $g24_proj] {
    set_property $k $want $rcore
    if {[get_property $k $rcore] != $want} { puts "ERROR: s45_ring_0 の $k が [get_property $k $rcore]（要求 $want）"; exit 1 }
}
set ring_axi [BI s45_ring_0 [list "s_axi" "S_AXI"] "s45_ring_0 の AXI4-Lite"]
set ring_m   [BI s45_ring_0 [list "m_axi" "M_AXI"] "s45_ring_0 の AXI4 の書き手"]
set hp0      [get_bd_intf_pins -quiet zynq_ultra_ps_e_0/S_AXI_HP0_FPD]
if {$hp0 eq ""} { puts "ERROR: PS の S_AXI_HP0_FPD が無い"; exit 1 }
for {set i 0} {$i < $ncore} {incr i} {
    set ring_in($i) [BI s45_ring_0 [list "s${i}_axis" "S${i}_AXIS"] "s45_ring_0 の入口 $i"]
}
puts "s45_ring_0: NIN = $ncore / 書き手 → zynq_ultra_ps_e_0/S_AXI_HP0_FPD（128 bit）"

# ---- コア s45_core_0〜3（g24_s45_core。proj027: 4 個、F-1）----
#   CORE_PORT = [3:0] ADC の番号（SMA のラベル）/ [11:8] タイル / [15:12] スライス（chans の c 番 = コア c の ADC。VERSIONS.md の実測）
#   RAW: 4 コアとも 1（RAW の流れ s 1 を持つ、F-5）。BUILD_TAG の [1:0] はコアの番号（Wide と同じ。同じ RTL の 4 個を PS が見分ける）
set core_raw 1
for {set c 0} {$c < $ncore} {incr c} {
    set gcore($c) [create_bd_cell -type module -reference g24_s45_core s45_core_$c]
    set core_tag($c) [expr {$build_tag_base | (1 << 22) | $c}]
    lassign [lindex $chans $c] cp_t cp_s
    set core_port($c) [expr {$c | ($cp_t << 8) | ($cp_s << 12)}]
    set kv [list CONFIG.BUILD_TAG $core_tag($c) CONFIG.GB_K_RST $gb_k_rst CONFIG.CORE_PORT $core_port($c) \
                 CONFIG.K_F $g24_kf CONFIG.ST_N $g24_st_n CONFIG.GF_L2 $g24_gf_l2 CONFIG.RAW $core_raw \
                 CONFIG.BIT_KIND $g24_kind CONFIG.BIT_REV 1 CONFIG.PROJ $g24_proj]
    foreach {k want} $kv {
        set_property $k $want $gcore($c)
        if {[get_property $k $gcore($c)] != $want} { puts "ERROR: s45_core_$c の $k が [get_property $k $gcore($c)]（要求 $want）"; exit 1 }
    }
    # ROM の中身の絶対パス。文字列の CONFIG に引用符が要るかは版で違いうるので、素のままと引用符つきを順に試し、読み返しで判定する（proj023 3b と同じ）。
    # **生成されたラッパに .<PAR>("<絶対パス>") が書かれたかは generate_target の後で見る**（下の「ROM のラッパ」。コアごと）
    foreach {par h nrow ncol} $g24_hex {
        set got ""
        foreach v [list $h "\"$h\""] {
            if {[catch {set_property CONFIG.$par $v $gcore($c)}]} continue
            set got [string trim [get_property CONFIG.$par $gcore($c)] {"}]
            if {$got eq $h} break
        }
        if {$got ne $h} { puts "ERROR: s45_core_$c の $par が '$got'（要求 $h）"; exit 1 }
    }
    puts [format "s45_core_%d（%s）: g24_s45_core / BUILD_TAG = 0x%08x / GB_K_RST = %d / CORE_PORT = 0x%04x / RAW = %d" \
            $c [lindex $ch_labels $c] $core_tag($c) $gb_k_rst $core_port($c) [get_property CONFIG.RAW $gcore($c)]]
    set core_axi($c)  [BI s45_core_$c [list "s_axi"  "S_AXI"]  "s45_core_$c の AXI4-Lite"]
    set core_axis($c) [BI s45_core_$c [list "s_axis" "S_AXIS"] "s45_core_$c の AXI4-Stream 入力（コアの ADC）"]
    set full_axis($c) [BI s45_core_$c [list "s_axis_full" "S_AXIS_FULL"] "s45_core_$c の FULL の流れの入力"]
    set rec_axis($c)  [BI s45_core_$c [list "m_axis_rec" "M_AXIS_REC"] "s45_core_$c のレコードの出口"]
    set raw_axis($c)  [BI s45_core_$c [list "s_axis_raw" "S_AXIS_RAW"] "s45_core_$c の RAW の流れの入力"]
}
# ---- proj031: 共有の係数 URAM（g24_cu_0。4 コアで 1 組。番地は s45_core_0、出口は 4 コアへ）----
#   COEF_CRC は make model-cu の値（環境変数、0x で 8 桁）。CONFIG は integer の 10 進で入れる（32'h は読み返しで形が変わる、time_core の注）ので 16 bit ずつ 2 つに
if {![info exists ::env(COEF_CRC)] || ![regexp {^0x[0-9A-Fa-f]{8}$} $::env(COEF_CRC)]} {
    puts "ERROR: 環境変数 COEF_CRC が無いか形が違う（'[expr {[info exists ::env(COEF_CRC)] ? $::env(COEF_CRC) : ""}]'。make build が make model-cu の最後の行から渡す）"
    exit 1
}
set coef_crc [expr {$::env(COEF_CRC)}]
set coef_crc_hi [expr {($coef_crc >> 16) & 0xFFFF}]
set coef_crc_lo [expr {$coef_crc & 0xFFFF}]
set gcu [create_bd_cell -type module -reference g24_cu g24_cu_0]
foreach {k want} [list CONFIG.COEF_CRC_HI $coef_crc_hi CONFIG.COEF_CRC_LO $coef_crc_lo CONFIG.PROJ $g24_proj] {
    set_property $k $want $gcu
    if {[get_property $k $gcu] != $want} { puts "ERROR: g24_cu_0 の $k が [get_property $k $gcu]（要求 $want）"; exit 1 }
}
puts [format "g24_cu_0         : g24_cu / COEF_CRC = 0x%04X%04X / PROJ = 0x%08x" $coef_crc_hi $coef_crc_lo $g24_proj]
set cu_axi [BI g24_cu_0 [list "s_axi" "S_AXI"] "g24_cu_0 の AXI4-Lite"]

for {set i 0} {$i < $nch} {incr i} {
    # proj027: gb_bc_i は 9 本（M00 コア i・M01〜M04 full_sel_0〜3・M05〜M08 raw_sel_0〜3）。4 ch ともコアがある
    set nmi($i) [expr {($i < $ncore ? 1 : 0) + [llength $sel_names]}]
    set gbc [create_bd_cell -type ip -vlnv xilinx.com:ip:axis_broadcaster gb_bc_$i]
    set want_bc [list CONFIG.NUM_MI $nmi($i) CONFIG.S_TDATA_NUM_BYTES [expr {$spw * 2}] CONFIG.M_TDATA_NUM_BYTES [expr {$spw * 2}]]
    cfg_apply $gbc $want_bc
    foreach {k want} $want_bc {
        if {[get_property $k $gbc] != $want} { puts "ERROR: gb_bc_$i の $k が [get_property $k $gbc]（要求 $want）"; exit 1 }
    }
    # gb_adc: RFDC → gb_up の間（ADC ドメイン、素通し）。gb_gate: gb_fifo → gb_dn の間（DSP ドメイン）
    set gba [create_bd_cell -type module -reference gb_adc gb_adc_$i]
    set_property CONFIG.DW [expr {$spw_adc * 16}] $gba
    set gbg [create_bd_cell -type module -reference gb_gate gb_gate_$i]
    set_property CONFIG.DW [expr {$gb_mid * 16}] $gbg
    set_property CONFIG.CW $rdc_w $gbg
    if {[get_property CONFIG.DW $gba] != $spw_adc * 16 || [get_property CONFIG.DW $gbg] != $gb_mid * 16 \
            || [get_property CONFIG.CW $gbg] != $rdc_w} {
        puts "ERROR: gb_adc_$i / gb_gate_$i の DW・CW が要求と違う"
        exit 1
    }
}
cfg_report "gb_bc_*（axis_broadcaster）"
# proj024: ch 1〜3 のギアボックスの制御の定数（コアが無い ch。core_cmn と同じ値: hold 0・adj 0・k = GB_K_RST）。proj025: ch 2・3
# proj027: 4 ch ともコアが握るので作らない（gb_tie_* が無いことは照合の「在ってはいけない」側で見る）
if {$ncore < $nch} {
foreach {nm w v} [list gb_tie_hold 1 0 gb_tie_adj 2 0 gb_tie_k 6 $gb_k_rst] {
    set c [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant $nm]
    set_property -dict [list CONFIG.CONST_WIDTH $w CONFIG.CONST_VAL $v] $c
    if {[get_property CONFIG.CONST_WIDTH $c] != $w || [get_property CONFIG.CONST_VAL $c] != $v} { puts "ERROR: $nm の CONST_WIDTH・CONST_VAL が要求と違う"; exit 1 }
}
}

puts [format "gb_adc_*: DW = %d / gb_gate_*: DW = %d・CW = %d（axis_rd_data_count の幅）" \
        [expr {$spw_adc * 16}] [expr {$gb_mid * 16}] $rdc_w]

# ---- リセット生成（3 ドメイン）----
set rst_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_ctrl]
set rst_adc  [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_adc]
set rst_dsp  [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_dsp]
# rev2: **rst_adc の peripheral_aresetn をタイルの数だけの幅にし、タイルごとに別のフロップから配る。**
#   rev1 では 1 個のフロップ（ACTIVE_LOW_PR_OUT_DFF[0]）が両タイルの m*_axis_aresetn に配られ、RFDC の IP の中の
#   タイルごとの同期段（cdc_adc{0,2}_clk_valid_i）へ枝分かれして CDC-11（Critical）が 2 件出た。
#   ビットごとに別の DFF（ACTIVE_LOW_PR_OUT_DFF[k]）になり、同じ順序回路から同じクロックで解かれるので、解除の時刻は揃ったまま。
#   ch i の gb_adc_i は、その ch のタイルのビットを受ける
set n_tiles [llength $adc_tiles]
set_property CONFIG.C_NUM_PERP_ARESETN $n_tiles $rst_adc
if {[get_property CONFIG.C_NUM_PERP_ARESETN $rst_adc] != $n_tiles} {
    puts "ERROR: rst_adc の C_NUM_PERP_ARESETN が [get_property CONFIG.C_NUM_PERP_ARESETN $rst_adc]（要求 $n_tiles）"
    exit 1
}
# 1 ビットを切り出すセル。**版で IP が変わる**（2024.2 以降は xlslice が非推奨で inline_hdl の ilslice）ので、作れた方を使い、
# ピンは向きで探す（名前 Din / Dout に依存しない）。切り出したビットは読み返す
proc mk_slice {name width bit} {
    set c ""
    foreach vlnv {xilinx.com:ip:xlslice xilinx.com:inline_hdl:ilslice} {
        if {![catch {set c [create_bd_cell -type ip -vlnv $vlnv $name]}] && $c ne ""} { break }
        set c ""
    }
    if {$c eq ""} { puts "ERROR: $name: xlslice も ilslice も作れない"; exit 1 }
    set_property -dict [list CONFIG.DIN_WIDTH $width CONFIG.DIN_FROM $bit CONFIG.DIN_TO $bit] $c
    foreach {k w} [list CONFIG.DIN_WIDTH $width CONFIG.DIN_FROM $bit CONFIG.DIN_TO $bit] {
        if {[get_property $k $c] != $w} { puts "ERROR: $name の $k が [get_property $k $c]（要求 $w）"; exit 1 }
    }
    set pi [get_bd_pins -quiet -of_objects $c -filter {DIR == I}]
    set po [get_bd_pins -quiet -of_objects $c -filter {DIR == O}]
    if {[llength $pi] != 1 || [llength $po] != 1} {
        puts "ERROR: $name のピンが 入力 1 本・出力 1 本 でない（[get_bd_pins -quiet -of_objects $c]）"
        exit 1
    }
    puts [format "RST SLICE  : %s（%s）= peripheral_aresetn\[%d\]" $name [get_property VLNV $c] $bit]
    return [list [norm_pin_s $pi] [norm_pin_s $po]]
}
proc norm_pin_s {p} { return [string trimleft $p /] }
# proj016: タイルが 1 個なら切り出さない（xlslice の DIN_WIDTH は 2 以上しか受けない: IP_Flow 19-3458。2026-10-02 に踏んだ）。
#   peripheral_aresetn は 1 bit で、フロップは 1 個 → 1 タイル。rev2 の CDC-11（1 個のフロップ → 2 タイル）の形は起きない
set k 0
foreach t $adc_tiles {
    if {$n_tiles == 1} {
        set rst_in($t)  ""
        set rst_out($t) rst_adc/peripheral_aresetn
        puts "RST SLICE  : タイル 1 個なので切り出さない（rst_adc/peripheral_aresetn を直に配る）"
    } else {
        lassign [mk_slice rst_adc_t$t $n_tiles $k] rst_in($t) rst_out($t)
    }
    incr k
}

# ---- 相互接続 ----
# **NUM_CLKS = 2**: aclk = pl_clk0（PS と RFDC）/ aclk1 = DSP ドメイン。SmartConnect が乗り換えを内部に持つ（自作の CDC は書かない）
# M00 = RFDC、M01〜M04 = s45_core_0〜3、M05 = time_core_0、M06 = s45_ring_0（proj027: コア 4 個）
set smc_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_ctrl]
# proj031: M07 = g24_cu_0
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI [expr {1 + $ncore + 3}] CONFIG.NUM_CLKS {2}] $smc_ctrl
if {[get_property CONFIG.NUM_MI $smc_ctrl] != 1 + $ncore + 3} {
    puts "ERROR: smc_ctrl の NUM_MI が [get_property CONFIG.NUM_MI $smc_ctrl]（要求 [expr {1 + $ncore + 3}]: RFDC ＋ s45_core_0〜3 ＋ time_core_0 ＋ s45_ring_0 ＋ g24_cu_0）"
    exit 1
}

# ------------------------------------------------------------------ 配線
set ps_clk0  zynq_ultra_ps_e_0/pl_clk0
set ps_rstn  zynq_ultra_ps_e_0/pl_resetn0

set adc_outclk rfdc/clk_adc${wiz_src_tile}  ;# fs/16 = 256 MHz。Clocking Wizard の入力
set adc_fabric clk_wiz_adc/clk_out1         ;# fs/spw_adc = 341.333 MHz。ADC ドメイン
set dsp_fabric clk_wiz_adc/clk_out2         ;# fs/spw = 256 MHz。DSP ドメイン
BP $adc_outclk
BP $adc_fabric
BP $dsp_fabric
nc $adc_outclk clk_wiz_adc/clk_in1
nc $ps_rstn    clk_wiz_adc/resetn

# クロック。**両タイルの m*_axis_aclk に clk_out1 を配る。clk_adc0 はどこにも繋がない**（proj009 の 4ch と同じ。timing.xdc）
foreach p [list rst_ctrl/slowest_sync_clk smc_ctrl/aclk rfdc/s_axi_aclk \
                zynq_ultra_ps_e_0/maxihpm0_fpd_aclk] {
    nc $ps_clk0 $p
}
set adc_dom [list rst_adc/slowest_sync_clk]
foreach t $adc_tiles { lappend adc_dom rfdc/m${t}_axis_aclk }
set dsp_dom [list rst_dsp/slowest_sync_clk smc_ctrl/aclk1]
for {set i 0} {$i < $nch} {incr i} {
    lappend adc_dom gb_up_$i/aclk gb_fifo_$i/s_axis_aclk gb_adc_$i/aclk
    lappend dsp_dom gb_fifo_$i/m_axis_aclk gb_dn_$i/aclk gb_gate_$i/aclk gb_bc_$i/aclk
}
set dsp_shared {}
for {set c 0} {$c < $ncore} {incr c} { lappend dsp_shared s45_core_$c/aclk }
foreach sname $sel_names { lappend dsp_shared $sname/aclk }
lappend dsp_shared time_core_0/aclk s45_ring_0/aclk zynq_ultra_ps_e_0/saxihp0_fpd_aclk g24_cu_0/aclk
lappend dsp_dom {*}$dsp_shared
nc $ps_clk0 time_core_0/ctrl_aclk
foreach p $adc_dom { nc $adc_fabric $p }
foreach p $dsp_dom { nc $dsp_fabric $p }

# MMCM がロックするまで ADC / DSP ドメインをリセットに保つ。
# **clk_adcN はタイルが起動して初めて出る**ので、ロックも起動後になる。
nc clk_wiz_adc/locked rst_adc/dcm_locked
nc clk_wiz_adc/locked rst_dsp/dcm_locked

# リセット
foreach r {rst_ctrl rst_adc rst_dsp} { nc $ps_rstn $r/ext_reset_in }
foreach p [list smc_ctrl/aresetn rfdc/s_axi_aresetn] { nc rst_ctrl/peripheral_aresetn $p }
# rev2: タイルごとのビット（上の rst_adc_t*）。ch i の gb_adc_i は ch i のタイルのビット
foreach t $adc_tiles {
    if {$rst_in($t) ne ""} { nc rst_adc/peripheral_aresetn $rst_in($t) }
    nc $rst_out($t) rfdc/m${t}_axis_aresetn
}
for {set i 0} {$i < $nch} {incr i} {
    set ch_tile($i) [lindex [lindex $chans $i] 0]
    nc $rst_out($ch_tile($i)) gb_adc_$i/aresetn
}
# ギアボックスの制御: ch c（c < ncore）はコア s45_core_c（core_cmn）、コアが無い ch は定数 gb_tie_* と rst_dsp（proj025 の ch 2・3。proj027 では無い）
#   書き込み側（gb_up / gb_fifo）: gb_adc が rst_adc と gb_hold（0）から作る gb_rstn
#   読み出し側（gb_gate / gb_dn）: コアのある ch はそのコアの gb_dn_rstn、ほかは rst_dsp
#   gb_gate の見張りは 8 個の axis_sel4（full_sel_0〜3・raw_sel_0〜3）の i 番の入口へ（コアのある ch はそのコアにも）
# **ch ごとの結線はこの表 1 つから張り、下の照合も同じ表を読む**（張る側と照かめる側が別の表だと、両方が同じ誤りを持てない）
proc ch_nets {i} {
    set sels [lmap s $::sel_names {string cat $s/gb_stat$i}]
    set sela [lmap s $::sel_names {string cat $s/adc_stat$i}]
    if {$i < $::ncore} {
        return [list \
            rst_dsp/peripheral_aresetn     [list gb_bc_$i/aresetn] \
            gb_adc_$i/gb_rstn              [list gb_up_$i/aresetn gb_fifo_$i/s_axis_aresetn] \
            s45_core_$i/gb_dn_rstn         [list gb_gate_$i/aresetn gb_dn_$i/aresetn] \
            s45_core_$i/gb_hold            gb_adc_$i/hold \
            s45_core_$i/gb_adj             gb_adc_$i/adj \
            s45_core_$i/gb_k               gb_gate_$i/k \
            gb_fifo_$i/axis_rd_data_count  gb_gate_$i/rd_count \
            gb_gate_$i/gb_stat             [concat [list s45_core_$i/gb_stat] $sels] \
            gb_adc_$i/adc_out              gb_gate_$i/adc_in \
            gb_gate_$i/adc_stat            [concat [list s45_core_$i/adc_stat] $sela] \
        ]
    }
    return [list \
        rst_dsp/peripheral_aresetn     [list gb_bc_$i/aresetn gb_gate_$i/aresetn gb_dn_$i/aresetn] \
        gb_adc_$i/gb_rstn              [list gb_up_$i/aresetn gb_fifo_$i/s_axis_aresetn] \
        gb_tie_hold/dout               gb_adc_$i/hold \
        gb_tie_adj/dout                gb_adc_$i/adj \
        gb_tie_k/dout                  gb_gate_$i/k \
        gb_fifo_$i/axis_rd_data_count  gb_gate_$i/rd_count \
        gb_gate_$i/gb_stat             $sels \
        gb_adc_$i/adc_out              gb_gate_$i/adc_in \
        gb_gate_$i/adc_stat            $sela \
    ]
}
# 共有の駆動元（全 ch が載るのが正しいネット）。照合で「他の ch」を見ない
proc shared_drv {d} { return [expr {[string match rst_* $d] || [string match gb_tie_* $d]}] }
for {set i 0} {$i < $nch} {incr i} {
    foreach {drv loads} [ch_nets $i] { foreach p $loads { nc $drv $p } }
}
proc lseq {n} { set r {}; for {set i 0} {$i < $n} {incr i} { lappend r $i }; return $r }
# proj025: 使わない入口の縛り（BD 41-759 を出さない。proj024 2f は s45_ring_0 の空いた入口を Vivado が黙って 0 に縛っていた）。
#   s45_core_1（RAW = 0）の s_axis_raw の tdata・tvalid、s45_ring_0 の s2・s3（tdata・tvalid・tlast・tuser）・rec_drop2・3。幅ごとに xlconstant 1 個を共有
# proj027: 4 コアとも RAW を持ち、s45_ring_0 の入口 4 本も全部使うので、縛る入口が無い。**tie_* は作らない**
#   （空いた入口が残っていれば BD 41-759 が出て、下の vivado.log の見張りで止まる。tie_* が無いことは照合の「在ってはいけない」側で見る）
# 共有のネット（入力の選び・時刻・リング）
proc shared_nets {} {
    set rl [list]
    for {set c 0} {$c < $::ncore} {incr c} { lappend rl s45_core_$c/aresetn }
    foreach s $::sel_names { lappend rl $s/aresetn }
    lappend rl time_core_0/aresetn s45_ring_0/aresetn g24_cu_0/aresetn
    set r [list rst_dsp/peripheral_aresetn $rl rst_ctrl/peripheral_aresetn time_core_0/ctrl_aresetn]
    foreach {drv pin} {t_out t_in go_out go_in ev_out tev_in} {
        lappend r time_core_0/$drv [lmap c [lseq $::ncore] {string cat s45_core_$c/$pin}]
    }
    for {set c 0} {$c < $::ncore} {incr c} {
        lappend r s45_core_$c/full_sel full_sel_$c/sel \
                  s45_core_$c/raw_sel  raw_sel_$c/sel \
                  s45_core_$c/rec_drop s45_ring_0/rec_drop$c
    }
    # proj031: 共有の係数。番地はコア 0 から、出口 3 本は 4 コアへ（在ってはいけない側は下の「g24_cu_0 の番地」）
    lappend r s45_core_0/coef_addr   [list g24_cu_0/addr] \
              s45_core_0/coef_addr_v [list g24_cu_0/addr_v]
    foreach {drv pin} {coef coef_in m_out coef_m_in ok_out coef_ok_in} {
        lappend r g24_cu_0/$drv [lmap c [lseq $::ncore] {string cat s45_core_$c/$pin}]
    }
    return $r
}
foreach {drv loads} [shared_nets] { foreach p $loads { nc $drv $p } }

# ---- データ経路: RFDC → ギアボックス → gb_bc_i → s45_core_i・full_sel_0〜3・raw_sel_0〜3（proj027）----
set i 0
foreach ch $chans {
    lassign $ch t s
    set src [BI rfdc [list "m${t}${s}_axis"] "RFDC の AXI4-Stream 出力 (tile $t slice $s)"]
    if {![catch {set nb [get_property CONFIG.TDATA_NUM_BYTES $src]}] && $nb ne ""} {
        if {$nb != $spw_adc * 2} {
            puts "ERROR: m${t}${s}_axis の語幅が $nb B。期待 [expr {$spw_adc * 2}] B。"
            puts "  Real のつもりが I/Q になっている可能性がある"
            exit 1
        }
    }
    set ch_src($i) $src
    set ch_intf($i) [list \
        $src                                                    [BI gb_adc_$i  [list "s_axis" "S_AXIS"] "gb_adc_$i の入力"] \
        [BI gb_adc_$i  [list "m_axis" "M_AXIS"] "gb_adc_$i の出力"] [get_bd_intf_pins gb_up_$i/S_AXIS] \
        [get_bd_intf_pins gb_up_$i/M_AXIS]                      [get_bd_intf_pins gb_fifo_$i/S_AXIS] \
        [get_bd_intf_pins gb_fifo_$i/M_AXIS]                    [BI gb_gate_$i [list "s_axis" "S_AXIS"] "gb_gate_$i の入力"] \
        [BI gb_gate_$i [list "m_axis" "M_AXIS"] "gb_gate_$i の出力"] [get_bd_intf_pins gb_dn_$i/S_AXIS] \
        [get_bd_intf_pins gb_dn_$i/M_AXIS]   [get_bd_intf_pins gb_bc_$i/S_AXIS] \
    ]
    # proj025: コアのある ch（i < ncore）は M00 がそのコア、その後に full_sel_0・full_sel_1・raw_sel。コアの AXI4-Lite は smc の M(1 + i)
    # proj027: その後は sel_names の順（full_sel_0〜3・raw_sel_0〜3）
    set m 0
    if {$i < $ncore} {
        lappend ch_intf($i) [get_bd_intf_pins gb_bc_$i/M[format %02d $m]_AXIS] $core_axis($i) \
                            [get_bd_intf_pins smc_ctrl/M[format %02d [expr {1 + $i}]]_AXI] $core_axi($i)
        incr m
    }
    foreach sname $sel_names {
        lappend ch_intf($i) [get_bd_intf_pins gb_bc_$i/M[format %02d $m]_AXIS] $sel_axis($sname,$i)
        incr m
    }
    foreach {a b} $ch_intf($i) { ic $a $b }
    puts [format "  %s = Tile %d slice %d -> gb_adc_%d / gb_up_%d / gb_fifo_%d / gb_gate_%d / gb_dn_%d -> gb_bc_%d -> {%sfull_sel_0〜3/s%d, raw_sel_0〜3/s%d}" \
            [lindex $ch_labels $i] [expr {224 + $t}] $s $i $i $i $i $i $i [expr {$i < $ncore ? "s45_core_$i（smc M0[expr {1 + $i}]）, " : ""}] $i $i]
    incr i
}

# 制御系 AXI: PS → SmartConnect → RFDC（M00）/ s45_core_0〜3（M01〜M04。上の ch_intf で張った）/ time_core_0（M05）/ s45_ring_0（M06）
ic [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_FPD] [get_bd_intf_pins smc_ctrl/S00_AXI]
ic [get_bd_intf_pins smc_ctrl/M00_AXI] [get_bd_intf_pins rfdc/s_axi]
set sh_intf [list [get_bd_intf_pins smc_ctrl/M[format %02d [expr {1 + $ncore}]]_AXI] $time_axi \
                  [get_bd_intf_pins smc_ctrl/M[format %02d [expr {2 + $ncore}]]_AXI] $ring_axi \
                  $ring_m $hp0 \
                  [get_bd_intf_pins smc_ctrl/M[format %02d [expr {3 + $ncore}]]_AXI] $cu_axi]
for {set c 0} {$c < $ncore} {incr c} {
    lappend sh_intf $sel_m(full_sel_$c) $full_axis($c) \
                    $sel_m(raw_sel_$c)  $raw_axis($c) \
                    $rec_axis($c)       $ring_in($c)
}
foreach {a b} $sh_intf { ic $a $b }
puts "  full_sel_c（コア c の FULL の SRC）-> s45_core_c/s_axis_full / raw_sel_c（コア c の RAW の SRC）-> s45_core_c/s_axis_raw"
puts [format "  time_core_0（smc M%02d）/ s45_core_c/m_axis_rec -> s45_ring_0/s{c}_axis（smc M%02d）-> zynq_ultra_ps_e_0/S_AXI_HP0_FPD" [expr {1 + $ncore}] [expr {2 + $ncore}]]

# ---- 1PPS の外部ポート（proj007 と同じ。create_bd_port で作る: make_bd_pins_external は `_0` を足し XDC と食い違う）----
foreach {pname ppin what} [list \
        pps_trig pps_trig_i "IRIG_TRIG_OUT (AH13) シュミットトリガ側" \
        pps_comp pps_comp_i "IRIG_COMP_OUT (AJ13) コンパレータ側"] {
    create_bd_port -dir I $pname
    connect_bd_net [get_bd_ports $pname] [BP time_core_0/$ppin]
    puts "EXTERNAL: $pname （$what）"
}

# ---- 結線の照合（proj012）----
# **両側を見る**: (1) 在るべき相手が同じネットにいる (2) 同じネットに **他の ch の** セル（gb_*_j・spec_core_j、j ≠ i）がいない。
# 片側だけだと、読む範囲を間違えていても通る（proj011 のポートの照合で踏んだ）。
# 共有のネット（クロック・rst_adc / rst_dsp）は (2) を見ない（全 ch が載るのが正しい）。
# 照合器そのものの陽性対照: 最後に、わざと誤った期待を 2 通り与え、**両方とも落ちること**を確かめる。
proc norm_pin {p} { return [string trimleft $p /] }
proc peer_names {obj kind} {
    if {$kind eq "intf"} {
        set n [get_bd_intf_nets -quiet -of_objects $obj]
        if {[llength $n] == 0} { return {} }
        set ps [get_bd_intf_pins -quiet -of_objects $n]
    } else {
        set n [get_bd_nets -quiet -of_objects $obj]
        if {[llength $n] == 0} { return {} }
        set ps [get_bd_pins -quiet -of_objects $n]
    }
    set out {}
    foreach p $ps { lappend out [norm_pin $p] }
    return $out
}
# 戻り値は問題の文字列のリスト（空なら通過）。shared = 1 なら (2) を見ない
proc net_check {i kind a expects shared} {
    set probs {}
    set obj [expr {$kind eq "intf" ? $a : [get_bd_pins -quiet $a]}]
    if {[llength $obj] == 0} { return [list "$a が無い"] }
    set peers [peer_names $obj $kind]
    if {[llength $peers] == 0} { return [list "[norm_pin $obj] がどこにも繋がっていない"] }
    foreach e $expects {
        if {[lsearch -exact $peers [norm_pin $e]] < 0} {
            lappend probs "[norm_pin $obj] と [norm_pin $e] が同じネットにない（ネットの上: $peers）"
        }
    }
    if {!$shared} {
        foreach p $peers {
            if {[regexp {^(gb_adc|gb_up|gb_fifo|gb_gate|gb_dn|gb_bc|s45_core|wide_tw_rom)_(\d+)/} $p -> cell j] && $j != $i} {
                lappend probs "ch $i のネットに ch $j のピン $p が載っている（[norm_pin $obj] のネット）"
            }
        }
    }
    return $probs
}
set nc_log {}
set nc_ng 0
for {set i 0} {$i < $nch} {incr i} {
    set rows {}
    # ch ごとの点対点のネット（張ったのと同じ表）。rst_*・gb_tie_* は共有
    foreach {drv loads} [ch_nets $i] {
        lappend rows pin $drv $loads [shared_drv $drv]
    }
    # クロックと ADC 側のリセット（共有。載っているべきネットに載っているか）
    lappend rows pin $adc_fabric [list gb_up_$i/aclk gb_fifo_$i/s_axis_aclk gb_adc_$i/aclk] 1
    lappend rows pin $dsp_fabric [list gb_fifo_$i/m_axis_aclk gb_dn_$i/aclk gb_gate_$i/aclk gb_bc_$i/aclk] 1
    # rev2: ADC 側のリセットは ch のタイルのビットから（そのタイルの m*_axis_aresetn と同じネット）
    lappend rows pin $rst_out($ch_tile($i)) [list gb_adc_$i/aresetn rfdc/m$ch_tile($i)_axis_aresetn] 1
    # データ経路と AXI（インタフェースのネット）
    foreach {a b} $ch_intf($i) { lappend rows intf $a [list $b] 0 }
    foreach {kind a expects shared} $rows {
        set probs [net_check $i $kind $a $expects $shared]
        set tag [expr {[llength $probs] ? "NG" : "OK"}]
        lappend nc_log [format "ch %d %-3s %-4s %s -> %s" $i $tag $kind [norm_pin $a] [lmap e $expects {norm_pin $e}]]
        foreach pr $probs { lappend nc_log "        $pr"; incr nc_ng }
    }
}
# 共有のネット（入力の選び・時刻・リング）
foreach {drv loads} [shared_nets] {
    set probs [net_check 0 pin $drv $loads 1]
    set tag [expr {[llength $probs] ? "NG" : "OK"}]
    lappend nc_log [format "ch * %-3s pin  %s -> %s" $tag [norm_pin $drv] $loads]
    foreach pr $probs { lappend nc_log "        $pr"; incr nc_ng }
}
foreach {a b} $sh_intf {
    set probs [net_check 0 intf $a [list $b] 1]
    set tag [expr {[llength $probs] ? "NG" : "OK"}]
    lappend nc_log [format "ch * %-3s intf %s -> %s" $tag [norm_pin $a] [norm_pin $b]]
    foreach pr $probs { lappend nc_log "        $pr"; incr nc_ng }
}
set probs [net_check 0 pin $dsp_fabric $dsp_shared 1]
lappend nc_log [format "ch * %-3s pin  %s -> %s" [expr {[llength $probs] ? "NG" : "OK"}] [norm_pin $dsp_fabric] $dsp_shared]
foreach pr $probs { lappend nc_log "        $pr"; incr nc_ng }
# proj025: **在ってはいけない側**。コアは s45_core_0・1 の 2 個だけ・Wide の部品（共有の ROM・spec_core）や 2G-1 の名前（full_sel）のセルが無い・
#   中身がどちらも g24_s45_core・RAW はコア 0 だけ
# proj027: コアは s45_core_0〜3 の 4 個だけ・2G-1・2G-2 の名前（full_sel・raw_sel）と縛り（tie_*・gb_tie_*）のセルが無い・中身が 4 個とも g24_s45_core・RAW 1
foreach pat {s45_core_[4-9]* s45_core_??* spec_core_* wide_coef_rom_* wide_tw_rom_* full_tie_* full_sel raw_sel tie_* gb_tie_* full_sel_[4-9]* raw_sel_[4-9]* g24_cu_[1-9]* g24_cu_0?*} {
    set cs [get_bd_cells -quiet $pat]
    set tag [expr {[llength $cs] == 0 ? "OK" : "NG"}]
    lappend nc_log [format "ch * %-3s セル %s が無い（在るのは: %s）" $tag $pat $cs]
    if {$tag eq "NG"} { incr nc_ng }
}
# 在るべき側の数: axis_sel4 は 8 個（sel_names）、gb_bc_i は NUM_MI 9
set ns [llength [get_bd_cells -quiet -filter {VLNV =~ "*:module_ref:axis_sel4:*"}]]
set tag [expr {$ns == [llength $sel_names] && $ns == 2 * $ncore ? "OK" : "NG"}]
lappend nc_log [format "ch * %-3s axis_sel4 のセル %d 個（期待 %d = full_sel・raw_sel × %d コア）" $tag $ns [expr {2 * $ncore}] $ncore]
if {$tag eq "NG"} { incr nc_ng }
for {set i 0} {$i < $nch} {incr i} {
    set got [get_property CONFIG.NUM_MI [get_bd_cells gb_bc_$i]]
    set tag [expr {$got == 1 + 2 * $ncore ? "OK" : "NG"}]
    lappend nc_log [format "ch %d %-3s gb_bc_%d の NUM_MI = %s（期待 %d）" $i $tag $i $got [expr {1 + 2 * $ncore}]]
    if {$tag eq "NG"} { incr nc_ng }
}
for {set c 0} {$c < $ncore} {incr c} {
    set v [get_property VLNV [get_bd_cells s45_core_$c]]
    set r [get_property CONFIG.RAW [get_bd_cells s45_core_$c]]
    set tag [expr {[string match "*:module_ref:g24_s45_core:*" $v] && $r == $core_raw ? "OK" : "NG"}]
    lappend nc_log [format "ch %d %-3s s45_core_%d の中身 = %s・RAW = %s（期待 g24_s45_core・RAW %d）" $c $tag $c $v $r $core_raw]
    if {$tag eq "NG"} { incr nc_ng }
}
proc pin_unconnected {p} { return [expr {[llength [get_bd_pins -quiet $p]] == 1 && [llength [get_bd_nets -quiet -of_objects [get_bd_pins -quiet $p]]] == 0}] }
# proj031: g24_cu_0 の番地（在ってはいけない側）。コア 1〜3 の coef_addr・coef_addr_v はどこにもつながない。
#   g24_cu_0/addr・addr_v のネットに載るのはコア 0 の口と g24_cu_0 だけ（shared_nets は「在るか」だけ）
proc cu_addr_probs {} {
    set probs {}
    for {set c 1} {$c < $::ncore} {incr c} {
        foreach pin {coef_addr coef_addr_v} {
            if {![pin_unconnected s45_core_$c/$pin]} { lappend probs "s45_core_$c/$pin がつながっている（使うのはコア 0 だけ）" }
        }
    }
    foreach {cu core} {addr coef_addr addr_v coef_addr_v} {
        set want [lsort [list g24_cu_0/$cu s45_core_0/$core]]
        set got [lsort [peer_names [get_bd_pins -quiet g24_cu_0/$cu] pin]]
        if {$got ne $want} { lappend probs "g24_cu_0/$cu のネットが {$got}（期待 {$want}）" }
    }
    return $probs
}
set probs [cu_addr_probs]
lappend nc_log [format "ch * %-3s g24_cu_0 の番地はコア 0 だけ・コア 1〜3 の coef_addr は空き（%d 件）" [expr {[llength $probs] ? "NG" : "OK"}] [llength $probs]]
foreach pr $probs { lappend nc_log "        $pr"; incr nc_ng }
set ncu [llength [get_bd_cells -quiet -filter {VLNV =~ "*:module_ref:g24_cu:*"}]]
set tag [expr {$ncu == 1 ? "OK" : "NG"}]
lappend nc_log [format "ch * %-3s g24_cu のセル %d 個（期待 1）" $tag $ncu]
if {$tag eq "NG"} { incr nc_ng }
# proj027: コア c の選び（full_sel・raw_sel）のネットに、**ほかのコアの axis_sel4・もう一方の種類の axis_sel4 の sel が載っていない**（在ってはいけない側）。
#   shared_nets の照合は「在るか」だけを見る（共有扱い）ので、取り違えの片側（余計に載っている）はここで見る
proc sel_other {c kind} { return [sel_other_as $c $kind s45_core_$c/$kind] }
proc sel_other_as {c kind pin} {
    set bad {}
    foreach q [peer_names [get_bd_pins -quiet $pin] pin] {
        if {[regexp {^(full_sel|raw_sel)_(\d+)/} $q -> k j] && ($k ne $kind || $j != $c)} { lappend bad $q }
        if {[regexp {^s45_core_(\d+)/} $q -> j] && $j != $c} { lappend bad $q }
    }
    return $bad
}
for {set c 0} {$c < $ncore} {incr c} {
    foreach kind {full_sel raw_sel} {
        set bad [sel_other $c $kind]
        set tag [expr {[llength $bad] == 0 && ![pin_unconnected s45_core_$c/$kind] ? "OK" : "NG"}]
        lappend nc_log [format "ch %d %-3s s45_core_%d/%s のネットにほかのコア・種類の sel が無い（%s）" $c $tag $c $kind [expr {[llength $bad] ? "載っている: $bad" : "なし"}]]
        if {$tag eq "NG"} { incr nc_ng }
    }
}
# proj024: コアの無い ch のギアボックスの制御はどれもコアの gb_* の出口から来ていない（在ってはいけない側。上の ch_nets の (2) でも見ているが、名指しで）
#   **ネットの上にコアが居ないこと、ではない**: rst_dsp のネットには s45_core_*/aresetn も正しく載る（2026-10-18 の 1 回目のビルドはこれで止めた）。
#   見るのはコアのギアボックスの制御の出口 4 本（gb_hold・gb_adj・gb_k・gb_dn_rstn）だけ
#   proj027: コアの無い ch は無い（下のループは 0 回）。代わりに陽性対照 (i) を 4 ch 全部に当てる
set core_gb_out {}
for {set c 0} {$c < $ncore} {incr c} { foreach q {gb_hold gb_adj gb_k gb_dn_rstn} { lappend core_gb_out s45_core_$c/$q } }
proc from_core_gb {p} {
    set peers [peer_names [get_bd_pins -quiet $p] pin]
    set bad {}
    foreach q $::core_gb_out { if {[lsearch -exact $peers $q] >= 0} { lappend bad $q } }
    return [list $peers $bad]
}
for {set i $ncore} {$i < $nch} {incr i} {
    foreach p [list gb_adc_$i/hold gb_adc_$i/adj gb_gate_$i/k gb_gate_$i/aresetn gb_dn_$i/aresetn] {
        lassign [from_core_gb $p] peers bad
        set tag [expr {[llength $peers] > 0 && [llength $bad] == 0 ? "OK" : "NG"}]
        lappend nc_log [format "ch %d %-3s %s はコアの gb_* の出口に繋がっていない（%s）" $i $tag $p [expr {[llength $bad] ? "繋がっている: $bad" : "ネットの上 [llength $peers] 本"}]]
        if {$tag eq "NG"} { incr nc_ng }
    }
}
# rev2: タイルのリセットが別のネット（別のフロップ）であること。**在ってはいけない側**
foreach t $adc_tiles {
    set peers [peer_names [get_bd_pins -quiet rfdc/m${t}_axis_aresetn] pin]
    foreach u $adc_tiles {
        if {$u == $t} continue
        set tag [expr {[lsearch -exact $peers rfdc/m${u}_axis_aresetn] >= 0 ? "NG" : "OK"}]
        lappend nc_log [format "tile %d %-3s rfdc/m%d_axis_aresetn と rfdc/m%d_axis_aresetn が別のネット" $t $tag $t $u]
        if {$tag eq "NG"} { lappend nc_log "        タイル $t と $u のリセットが同じネット（rev1 の CDC-11 の形）"; incr nc_ng }
    }
    set direct [expr {[lsearch -exact $peers rst_adc/peripheral_aresetn] >= 0}]
    if {$n_tiles > 1 && $direct} {
        lappend nc_log "tile $t NG  rfdc/m${t}_axis_aresetn が rst_adc/peripheral_aresetn に直に繋がっている（切り出しを通っていない）"
        incr nc_ng
    } elseif {$n_tiles == 1 && !$direct} {
        lappend nc_log "tile $t NG  rfdc/m${t}_axis_aresetn が rst_adc/peripheral_aresetn に繋がっていない（1 タイルは直に配る）"
        incr nc_ng
    } else {
        lappend nc_log [format "tile %d OK  rfdc/m%d_axis_aresetn の源（%s）" $t $t [expr {$direct ? "rst_adc に直" : "切り出し"}]]
    }
}
# 陽性対照: (a) 在るべき相手を他の ch にする（(1) が落ちるべき）/ (b) 正しいネットを他の ch の番号で照らす（(2) が落ちるべき）
set pc_ok 1
set pa [net_check 0 pin s45_core_0/gb_hold [list gb_adc_1/hold] 0]
set pb [net_check 1 pin s45_core_0/gb_hold [list gb_adc_0/hold] 0]
if {[llength $pa] == 0} { set pc_ok 0; lappend nc_log "陽性対照 (a) が通ってしまった（在るべき相手の照合が壊れている）" }
if {[llength $pb] == 0} { set pc_ok 0; lappend nc_log "陽性対照 (b) が通ってしまった（他の ch の照合が壊れている）" }
lappend nc_log "陽性対照: (a) [llength $pa] 件・(b) [llength $pb] 件で落ちた（どちらも 1 件以上が期待）"
# (c)(d) 時刻のネット / (h) 入力の選びの取り違え（full_sel の sel に raw_sel を期待する）。どれも落ちるべき
set pcc [net_check 0 pin time_core_0/t_out  [list s45_core_0/go_in] 1]
set pcd [net_check 0 pin time_core_0/go_out [list s45_core_0/t_in] 1]
set pch [net_check 0 pin s45_core_0/full_sel [list raw_sel_0/sel] 1]
# proj025 (j): コア 1 の FULL の選びにコア 0 の選びを期待する（full_sel_0 と full_sel_1 の取り違え。落ちるべき）
set pcj [net_check 1 pin s45_core_1/full_sel [list full_sel_0/sel] 1]
# proj027 (j2): コア 3 の RAW の選びにコア 2 の選びを期待する（raw_sel_2 と raw_sel_3 の取り違え。落ちるべき）
set pcj2 [net_check 3 pin s45_core_3/raw_sel [list raw_sel_2/sel] 1]
# proj027 (l): 上の sel_other（ほかのコア・種類の sel が載っていない）を、コア 0 の正しいネットにコア 1 として当てる（full_sel_0 を「ほかのコア」と言うべき）
set pcl [sel_other_as 1 full_sel s45_core_0/full_sel]
# proj031 (m): g24_cu_0 の番地にコア 1 の口を期待する（落ちるべき）
set pcm [net_check 0 pin g24_cu_0/addr [list s45_core_1/coef_addr] 1]
foreach {nm r} [list c $pcc d $pcd h $pch j $pcj j2 $pcj2 l $pcl m $pcm] {
    if {[llength $r] == 0} { set pc_ok 0; lappend nc_log "陽性対照 ($nm) が通ってしまった（共有のネットの照合が壊れている）" }
}
lappend nc_log "陽性対照: (c) [llength $pcc] 件・(d) [llength $pcd] 件・(h) [llength $pch] 件・(j) [llength $pcj] 件・(j2) [llength $pcj2] 件・(l) [llength $pcl] 件・(m) [llength $pcm] 件で落ちた（どれも 1 件以上が期待）"
# proj031 (n): 「空き」の照合が、つながっているコア 0 の coef_addr を「空き」と言わないこと
set pcn [pin_unconnected s45_core_0/coef_addr]
if {$pcn} { set pc_ok 0; lappend nc_log "陽性対照 (n) が通ってしまった（つながっている coef_addr を「空き」と言った）" }
lappend nc_log "陽性対照: (n) [expr {$pcn ? "通った（NG）" : "落ちた"}]（落ちるのが期待）"
# (e)(f): 「つながっていない」の照合が、つながっているピン・無いピンに「つながっていない」と言わないこと
set pce [pin_unconnected s45_core_0/full_sel]
set pcf [pin_unconnected s45_core_0/no_such_pin]
if {$pce} { set pc_ok 0; lappend nc_log "陽性対照 (e) が通ってしまった（つながっているピンを「つながっていない」と言った）" }
if {$pcf} { set pc_ok 0; lappend nc_log "陽性対照 (f) が通ってしまった（無いピンを「つながっていない」と言った）" }
lappend nc_log "陽性対照: (e) [expr {$pce ? "通った（NG）" : "落ちた"}]・(f) [expr {$pcf ? "通った（NG）" : "落ちた"}]（どちらも落ちるのが期待）"
# (g) ch 2 のネットを ch 3 として照らす（(2) が gb_adc_2 を「他の ch」と言うべき）
set pcg [lsearch -all -inline [net_check 3 pin gb_adc_2/gb_rstn [list gb_up_2/aresetn] 0] "*ch 2 のピン*"]
if {[llength $pcg] == 0} { set pc_ok 0; lappend nc_log "陽性対照 (g) が通ってしまった（ch の照合が壊れている）" }
lappend nc_log "陽性対照: (g) [llength $pcg] 件で落ちた（1 件以上が期待）"
# (i) 上の「コアの gb_* の出口に繋がっていない」を 4 ch に当てる（コアが握るので、繋がっていると言うべき）。proj027: ch 0〜3 の 12 本
set pci 0
set pci_n 0
for {set i 0} {$i < $ncore} {incr i} {
    foreach p [list gb_adc_$i/hold gb_gate_$i/k gb_gate_$i/aresetn] { incr pci_n; lassign [from_core_gb $p] peers bad; if {[llength $bad] > 0} { incr pci } }
}
if {$pci != $pci_n || $pci_n != 12} { set pc_ok 0; lappend nc_log "陽性対照 (i) が通ってしまった（$pci_n 本のうち $pci 本しかコアの gb_* に繋がっていると言わない）" }
lappend nc_log "陽性対照: (i) ch 0〜3 の $pci_n 本のうち $pci 本で「コアの gb_* に繋がっている」と言った（12 が期待）"
# (k) 「繋がっていない」の照合を、繋がっている s45_core_3/raw_sel に当てる（繋がっていない、と言わないべき。proj025 はコア 0）
set pck [pin_unconnected s45_core_3/raw_sel]
if {$pck} { set pc_ok 0; lappend nc_log "陽性対照 (k) が通ってしまった（s45_core_3/raw_sel を「繋がっていない」と言った）" }
lappend nc_log "陽性対照: (k) [expr {$pck ? "通った（NG）" : "落ちた"}]（落ちるのが期待）"
set fh [open $outdir/net_check.rpt w]
foreach l $nc_log { puts $fh $l }
close $fh
puts ""
puts "---- 結線の照合（ch ごと。$outdir/net_check.rpt）----"
puts "  照合した行 [llength [lsearch -all -regexp $nc_log {^ch [\d*] (OK|NG)}]] / 問題 $nc_ng 件 / 陽性対照 [expr {$pc_ok ? "OK" : "**NG**"}]"
if {$nc_ng > 0 || !$pc_ok} {
    foreach l $nc_log { if {![string match "* OK *" $l]} { puts "  $l" } }
    puts "ERROR: ch 間の結線の照合に失敗した"
    exit 1
}

# ---- 外部ポート（RF のアナログ入力・タイルのクロック・SYSREF）----
# いずれも専用ピンなので XDC での配置制約は要らない。IP のタイル選択で決まる。
# **アナログ入力はスライスの対（01 / 23）でまとまっている。**
set ext_done {}
foreach ch $chans {
    lassign $ch t s
    # **expr に "01" を渡さないこと。**数値として評価され 1 になり、
    # パターンが vin0_1 に化けて「見つからない」で止まる（2026-09-17 に踏んだ）。
    # 文字列の分岐は if で書く。
    if {$s < 2} { set pair "01" } else { set pair "23" }
    set pin [BI rfdc [list "vin${t}_${pair}" "vin${t}${s}"] \
                "ADC アナログ入力 (tile $t slice $s)"]
    if {[lsearch -exact $ext_done $pin] >= 0} continue
    lappend ext_done $pin
    make_bd_intf_pins_external $pin
    puts "EXTERNAL: $pin （ADC アナログ入力 tile $t slice $s）"
}
foreach t $adc_tiles {
    set pin [BI rfdc [list "adc${t}_clk"] "ADC タイル $t のクロック入力"]
    make_bd_intf_pins_external $pin
    puts "EXTERNAL: $pin （ADC タイル $t のクロック入力）"
}
set pin [BI rfdc [list "sysref_in"] "SYSREF 入力"]
make_bd_intf_pins_external $pin
puts "EXTERNAL: $pin （SYSREF 入力）"

# ------------------------------------------------------------------ まとめ
assign_bd_address

# proj021 手順 2-1: spec_core_0 のセルは無い（全帯域は s45_core_0 の中の FULL の流れ）。**重なっていないことは下で見る**
set wins {}
for {set i 0} {$i < $ncore} {incr i} {
    set win_seg ""
    foreach seg [get_bd_addr_segs -quiet] {
        if {[string match "*s45_core_${i}*" $seg] && [string match "*SEG_*" $seg]} { set win_seg $seg }
    }
    if {$win_seg eq ""} { puts "ERROR: s45_core_$i のアドレスセグメントが見つからない"; exit 1 }
    if {[get_property RANGE $win_seg] < $win_range} { set_property RANGE $win_range $win_seg }
    set woff [get_property OFFSET $win_seg]
    set wrng [get_property RANGE $win_seg]
    if {($woff % $win_range) != 0} {
        set_property OFFSET [expr {0xA0000000 + $win_range * (16 + $i)}] $win_seg
        set woff [get_property OFFSET $win_seg]
    }
    puts [format "WIN ADDR   : s45_core_%d（%s）%s +%s（%s）" $i [lindex $ch_labels $i] $woff $wrng $win_seg]
    if {$wrng < $win_range || ($woff % $win_range) != 0} { puts "ERROR: s45_core_$i の窓が $win_range B に届かない / 揃っていない"; exit 1 }
    lappend wins [list [expr {10 + $i}] [expr {$woff}] [expr {$wrng}]]
}
# proj016: time_core_0 の窓（読み返して重なりを見る）
set tseg ""
foreach seg [get_bd_addr_segs -quiet] {
    if {[string match "*time_core_0*" $seg] && [string match "*SEG_*" $seg]} { set tseg $seg }
}
if {$tseg eq ""} { puts "ERROR: time_core_0 のアドレスセグメントが見つからない"; exit 1 }
if {[get_property RANGE $tseg] < 256} { set_property RANGE 4096 $tseg }
puts [format "TIME ADDR  : time_core_0 %s +%s（%s）" [get_property OFFSET $tseg] [get_property RANGE $tseg] $tseg]
lappend wins [list 99 [expr {[get_property OFFSET $tseg]}] [expr {[get_property RANGE $tseg]}]]
# proj031: g24_cu_0 の窓（4 KiB。読み返して重なりを見る）
set cseg ""
foreach seg [get_bd_addr_segs -quiet] {
    if {[string match "*SEG_g24_cu_0*" $seg]} { set cseg $seg }
}
if {$cseg eq ""} { puts "ERROR: g24_cu_0 のアドレスセグメントが見つからない"; exit 1 }
if {[get_property RANGE $cseg] < 4096} { set_property RANGE 4096 $cseg }
puts [format "CU ADDR    : g24_cu_0 %s +%s（%s）" [get_property OFFSET $cseg] [get_property RANGE $cseg] $cseg]
lappend wins [list 97 [expr {[get_property OFFSET $cseg]}] [expr {[get_property RANGE $cseg]}]]
# proj021 手順 2-2a: s45_ring_0 のレジスタ（4 KiB）と、書き手から PS の DDR が見えること
set rseg ""
set ddr_seg ""
foreach seg [get_bd_addr_segs -quiet] {
    if {[string match "*SEG_s45_ring_0*" $seg]} { set rseg $seg }
    if {[string match "*s45_ring_0/m_axi*DDR_LOW*" $seg]} { set ddr_seg $seg }
}
if {$rseg eq ""} { puts "ERROR: s45_ring_0 のアドレスセグメントが見つからない"; exit 1 }
if {[get_property RANGE $rseg] < 4096} { set_property RANGE 4096 $rseg }
puts [format "RING ADDR  : s45_ring_0 %s +%s（%s）" [get_property OFFSET $rseg] [get_property RANGE $rseg] $rseg]
lappend wins [list 98 [expr {[get_property OFFSET $rseg]}] [expr {[get_property RANGE $rseg]}]]
if {$ddr_seg eq ""} {
    puts "ERROR: s45_ring_0/m_axi から PS の DDR（HP0_DDR_LOW）が見えない。見えるもの:"
    foreach seg [get_bd_addr_segs -quiet] { if {[string match "*s45_ring_0/m_axi*" $seg]} { puts "  $seg" } }
    exit 1
}
puts [format "RING DMA   : %s %s +%s" $ddr_seg [get_property OFFSET $ddr_seg] [get_property RANGE $ddr_seg]]
foreach w1 $wins {
    foreach w2 $wins {
        lassign $w1 i1 o1 r1
        lassign $w2 i2 o2 r2
        if {$i1 < $i2 && $o1 < $o2 + $r2 && $o2 < $o1 + $r1} {
            puts "ERROR: 窓 $i1 と $i2 が重なっている（10 + i = s45_core_i、99 = time_core_0、98 = s45_ring_0、97 = g24_cu_0）"
            exit 1
        }
    }
}

validate_bd_design
save_bd_design

# ---- proj025: vivado.log の本体の CRITICAL WARNING（BD を組むときのもの）を拾って止める ----
# proj024 2f: BD 41-759（s45_ring_0 の空いた入口を 0 に縛った）は vivado.log の本体にだけ出て、runme.log を読む見張りに 3 回のビルドで見落とされた（LESSONS）。
# 陽性対照: 目印の CRITICAL WARNING を 1 件わざと出し、**それを拾えなかったら止める**（ログが読めない・書き出しが遅れている、を「異常なし」と読まない）
set cw_mark "PROJ027-CW-POSCTL"
if {[catch {send_msg_id PROJ027-1 {CRITICAL WARNING} "$cw_mark: vivado.log の見張りの陽性対照（このビルドの正常な印）"} msg]} {
    puts "ERROR: 陽性対照の CRITICAL WARNING を出せない（send_msg_id: $msg）"; exit 1
}
set vlog [file join $outdir vivado.log]
set cw_hits {}
set cw_pc 0
if {[catch {set fh [open $vlog r]; set vt [read $fh]; close $fh} msg]} { puts "ERROR: $vlog を読めない（$msg）"; exit 1 }
foreach line [split $vt "\n"] {
    if {![regexp {^CRITICAL WARNING:} $line]} continue
    if {[string first $cw_mark $line] >= 0} { incr cw_pc; continue }
    lappend cw_hits $line
}
puts ""
puts "---- vivado.log の CRITICAL WARNING（BD を組み終えたところまで）----"
puts "  陽性対照の目印 $cw_pc 件（1 が期待）・ほか [llength $cw_hits] 件（0 が期待）"
foreach l $cw_hits { puts "  $l" }
if {$cw_pc != 1} { puts "ERROR: vivado.log の見張りが陽性対照を拾えない（$vlog が読めていないか、書き出しが遅れている）"; exit 1 }
if {[llength $cw_hits] > 0} { puts "ERROR: BD を組む段階で CRITICAL WARNING が出た（上）"; exit 1 }

puts ""
puts "---- Clocking Wizard の実出力（validate 後）----"
wiz_actual_check $clkw $wiz_pairs "validate 後"

# ---- PS の PL クロックの実周波数を確かめる ----
# **要求した値がそのまま出るとは限らない。**PS の PLL の刻みで下がる
# （2026-09-16: 200 MHz を要求して 175 MHz になった）。
puts ""
puts "---- PS の PL クロック ----"
foreach {pin w} [list zynq_ultra_ps_e_0/pl_clk0 $ctrl_mhz] {
    set hz ""
    catch {set hz [get_property CONFIG.FREQ_HZ [BP $pin]]}
    set mhz [expr {$hz eq "" ? 0 : $hz / 1e6}]
    puts [format "  %-12s 要求 %6s MHz → 実際 %8.3f MHz" [file tail $pin] $w $mhz]
}

set fh [open $outdir/address_map.rpt w]
foreach seg [get_bd_addr_segs -quiet] {
    puts $fh [format "%-56s %s +%s" $seg \
        [get_property OFFSET $seg] [get_property RANGE $seg]]
}
close $fh
puts "=== block design ok （アドレスマップ: $outdir/address_map.rpt）==="

# ---- ラッパと制約 ----
set bd_file [get_files ${bd_name}.bd]
make_wrapper -files $bd_file -top

set wrapper [lindex [glob -nocomplain \
    $projdir/$proj.gen/sources_1/bd/$bd_name/hdl/${bd_name}_wrapper.* \
    $projdir/$proj.srcs/sources_1/bd/$bd_name/hdl/${bd_name}_wrapper.*] 0]
if {$wrapper eq ""} { puts "ERROR: ラッパ HDL が見つからない"; exit 1 }
add_files -norecurse $wrapper
set_property top ${bd_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

add_files -fileset constrs_1 -norecurse ./src/board/timing.xdc
add_files -fileset constrs_1 -norecurse ./src/board/pps.xdc      ;# proj016: 1PPS のピン（実装後に読み返す）
# クロックは実装の段階で出そろう。合成時に get_clocks が空を返すと
# set_clock_groups がエラーになるので、実装でのみ使う。
set_property USED_IN_SYNTHESIS false [get_files timing.xdc]

# ---- part の検証 ----
set part_actual [get_property PART [current_project]]
if {$part_actual ne $part} {
    puts "ERROR: 要求した part と実際の part が違う"
    puts "  要求: $part"
    puts "  実際: $part_actual"
    puts "  board_part がボードの宣言値に引き戻している可能性がある（WARNING: Project 1-153）"
    exit 1
}
puts "PART (確定): $part_actual"


# ---- proj015 rev2: 実装の戦略（環境変数 IMPL。Makefile の IMPL）。**読み返して確かめる** ----
if {[info exists ::env(IMPL)] && $::env(IMPL) ne ""} {
    set impl_req $::env(IMPL)
    if {[catch {set_property strategy $impl_req [get_runs impl_1]} msg]} {
        puts "ERROR: impl_1 の strategy を $impl_req にできない: $msg"
        exit 1
    }
    set impl_got [get_property strategy [get_runs impl_1]]
    puts "IMPL       : impl_1 の strategy = $impl_got（要求 $impl_req）"
    if {$impl_got ne $impl_req} { puts "ERROR: impl_1 の strategy が要求と違う"; exit 1 }
} else {
    puts "IMPL       : impl_1 の strategy = [get_property strategy [get_runs impl_1]]（既定）"
}

# ---- proj015: OOC の合成を先に回し、Vivado 自体が落ちた run だけを回し直す ----
# 2026-10-01: 同じ RTL の run が、合成を終えた後に segfault で落ちた（Abnormal program termination (11)）。
#   1 回目は s45_core_1、2 回目は gb_fifo_2・rst_dsp_0 と、落ちる run は毎回違う（-jobs 30 で並べたとき）。
#   回し直すのは「落ちた印（Abnormal program termination / segfault）が在る」run だけ。印の無い失敗は回し直さずに止める
# **run のオブジェクトを Tcl の変数・リスト・proc の引数に通さない。**
#   e64fa7c・5381546 とも、get_runs が返した OOC の run を lmap / foreach で取り出して get_property に渡すと
#   「Invalid option value 'system_zynq_ultra_ps_e_0_0_synth_1' specified for 'object'」で止まった
#   （取り出した要素は名前の文字列になる）。run は名前で持ち、Vivado に渡すときは毎回 [get_runs $n] をその場で書く。
#   状態は get_property を使わず、run のディレクトリの印のファイルで読む（ISEWrap が書く
#   .vivado.end.rst = 正常終了、.vivado.error.rst = 異常終了）
proc ooc_dir {n} { return [file join $::projdir $::proj.runs $n] }
proc ooc_state {n} {
    set d [ooc_dir $n]
    if {[file exists $d/.vivado.error.rst]} { return bad }
    if {[file exists $d/.vivado.end.rst]}   { return done }
    return bad
}
proc ooc_crashed {n} {
    set log [file join [ooc_dir $n] runme.log]
    if {![file exists $log]} { return 0 }
    set fh [open $log r]; set t [read $fh]; close $fh
    # 落ちた印があれば、ERROR の行があっても落ちたと数える（2026-10-01: 並列合成の task_worker が先に落ち、
    #   親が「Synth 8-787 cannot access rtd files in ./.Xil/...」の ERROR を出してから落ちた）。
    #   本当の RTL の誤りなら回し直しても同じ ERROR で失敗し、2 回で止まる
    return [regexp {Abnormal program termination|segfault in } $t]
}
proc ooc_unstarted {n} { return [expr {![file exists [file join [ooc_dir $n] runme.log]]}] }
proc ooc_bad {names} { lmap n $names { expr {[ooc_state $n] eq "bad" ? $n : [continue]} } }
proc ooc_wait {names} { foreach n $names { catch {wait_on_run [get_runs $n]} } }

# OOC の run は launch_runs synth_1 のときに作られる。先に回すため、ここで作っておく（f2d8de4 では作っていなかったので空のまま素通りした）
generate_target all [get_files $bd_file]
create_ip_run [get_files $bd_file]
# proj024: s45_core_0 のラッパに ROM の hex の絶対パスが文字列として書かれたか（**在るべき側**。引用符が抜けると合成で落ちるか、別の名前を探して 0 の ROM になる）
# proj025: コアごとに（ROM はコアごとに 1 組、E-2・E-3）。proj027: 4 コア（F-2・F-3）
for {set c 0} {$c < $ncore} {incr c} {
set vs {}
catch {set vs [split [exec find $projdir -path "*${bd_name}_s45_core_${c}_0*" -name "*.v"] "\n"]}
foreach {par hex nrow ncol} $g24_hex {
    set hit ""
    foreach f $vs {
        set fh [open $f r]; set t [read $fh]; close $fh
        set hre [regsub -all {[][{}()*+?.\\^$|]} $hex {\\&}]
        if {[regexp "\\.${par}\\s*\\(\\s*\"$hre\"\\s*\\)" $t]} { set hit $f; break }
    }
    if {$hit eq ""} {
        puts "ERROR: s45_core_$c のラッパに .${par}(\"$hex\") が無い。探したファイル:"
        foreach f $vs { puts "  $f" }
        exit 1
    }
    puts "ROM のラッパ: s45_core_$c .$par = \"$hex\"（[file tail $hit]）"
}
}
# FFT の IP（xfft・win_fft）も OOC で合成されるので、同じく先に回す
# proj023 3b: FFT の IP は lane_fft_w（$xfft）だけ
foreach ip [list $xfft] {
    if {[catch {
        set xf [get_files -quiet [get_property IP_FILE $ip]]
        if {$xf ne "" && [llength [get_runs -quiet ${ip}_synth_1]] == 0} { create_ip_run $xf }
    } msg]} { puts "NOTE: $ip の OOC の run を先に作れない（impl_1 のときに作られる）: $msg" }
}
set ooc_names [lsort [lmap r [get_runs -quiet -filter {IS_SYNTHESIS && NAME != synth_1}] {string cat $r}]]
puts "OOC 合成   : [llength $ooc_names] 個を先に回す"
if {[llength $ooc_names] == 0} { puts "ERROR: OOC の run が 0 個（create_ip_run が効いていない）"; exit 1 }
launch_runs [get_runs -filter {IS_SYNTHESIS && NAME != synth_1}] -jobs $jobs
ooc_wait $ooc_names
for {set try 1} {$try <= 2} {incr try} {
    set bad [ooc_bad $ooc_names]
    if {[llength $bad] == 0} break
    foreach n $bad {
        # proj023 3b: 落ちた run に依る run（lane_fft_w → s45_core_i）は始まらず、runme.log が無い。これも回し直す
        #   （2026-10-14: lane_fft_w が合成を終えて dcp を書いた後、終わり際に tcmalloc の abort（Abnormal program termination (6)）で落ち、
        #   s45_core_0〜3 が始まらないまま「落ちた印が無い」で止まった）
        if {![ooc_crashed $n] && ![ooc_unstarted $n]} {
            puts "ERROR: OOC の合成 $n が失敗（Vivado が落ちた印が無い。[ooc_dir $n]/runme.log を見る）"
            exit 1
        }
        puts "  $n: [expr {[ooc_crashed $n] ? "Vivado が落ちた" : "始まっていない（依る run が落ちた）"}]"
    }
    if {[llength [lmap n $bad {expr {[ooc_crashed $n] ? $n : [continue]}}]] == 0} {
        puts "ERROR: 始まっていない run だけが残った（落ちた run が無いのに始まらない）: $bad"
        exit 1
    }
    puts "NOTE: OOC の合成で Vivado が落ちた run を回し直す（$try 回目）: $bad"
    foreach n $bad { reset_run [get_runs $n] }
    launch_runs [get_runs $bad] -jobs [expr {min($jobs, 4)}]
    ooc_wait $bad
}
set bad [ooc_bad $ooc_names]
if {[llength $bad] > 0} { puts "ERROR: 回し直しても OOC の合成が通らない: $bad"; exit 1 }
puts "OOC 合成   : [llength $ooc_names] 個すべて完了"
# proj023 3b: $readmemh が読めないと ROM が 0 になり、BRAM が消えるだけで合成は通る。**OOC のログで先に止める**（ROM は s45_core_0〜3 の中）
set rm_ng 0
set rm_seen 0
set rm_ok 0
foreach n $ooc_names {
    if {![string match "*s45_core_*" $n]} continue
    incr rm_seen
    set lf [file join [ooc_dir $n] runme.log]
    set fh [open $lf r]; set t [read $fh]; close $fh
    foreach line [split $t "\n"] {
        if {[regexp -nocase {Synth 8-4445|could not open .*readmem|readmem.*(not found|cannot|could not)} $line]} { puts "  $n: $line"; incr rm_ng }
        foreach {par h nrow ncol} $g24_hex {
            if {[string first [file tail $h] $line] >= 0 && [regexp -nocase {read successfully} $line]} { incr rm_ok }
        }
    }
}
puts "ROM の中身 : s45_core_* の OOC の run $rm_seen 個のログに \$readmemh の失敗 $rm_ng 行・読めた印 $rm_ok 行（印が無くても止めない。配置後の BRAM の数で止める）"
# proj031: g24_cu の URAM の推論が落ちた印（Synth 8-5792「ram_style = "ultra" ... is ignored」。WARNING 1 行で BRAM 64 に落ちる、README の S）で止める
set cu_seen 0
set cu_ng 0
foreach n $ooc_names {
    if {![string match "system_g24_cu_*" $n]} continue
    incr cu_seen
    set fh [open [file join [ooc_dir $n] runme.log] r]; set t [read $fh]; close $fh
    foreach line [split $t "\n"] { if {[string match "*Synth 8-5792*" $line]} { puts "  $n: $line"; incr cu_ng } }
}
puts "URAM の推論: g24_cu の OOC の run $cu_seen 個・Synth 8-5792 $cu_ng 行"
if {$cu_seen != 1 || $cu_ng != 0} { puts "ERROR: g24_cu の OOC の run が 1 個でないか、URAM の指定が無視された（README の S）"; exit 1 }
# proj023 4a: **ドライバの無いネット（Synth 8-3848）で止める**。自作のセル（module reference）の run だけを見る
set nd_ng 0
set nd_seen 0
foreach n $ooc_names {
    if {![regexp {^system_(s45_core|time_core|s45_ring|gb_adc|gb_gate|full_sel|raw_sel|g24_cu)_} $n]} continue
    incr nd_seen
    set lf [file join [ooc_dir $n] runme.log]
    if {![file exists $lf]} continue
    set fh [open $lf r]; set t [read $fh]; close $fh
    foreach line [split $t "\n"] {
        if {[string match "*Synth 8-3848*" $line]} { puts "  $n: $line"; incr nd_ng }
    }
}
puts "ドライバ   : 自作のセルの OOC の run $nd_seen 個のログに Synth 8-3848（ドライバの無いネット）$nd_ng 行"
# 期待（proj027）: s45_core 4・time_core_0 1・s45_ring_0 1・gb_adc 4・gb_gate 4・full_sel_0〜3 4・raw_sel_0〜3 4 = 22（proj025 は 15）
# proj031: ＋ g24_cu_0 1 = 23（1 回目のビルドは 22 のままで、ここで止まった）
set nd_want [expr {$ncore + 1 + 1 + $nch + $nch + [llength $sel_names] + 1}]
if {$nd_seen != $nd_want} { puts "ERROR: 自作のセルの OOC の run が $nd_seen 個（期待 $nd_want。run の名前が変わった？ $ooc_names）"; exit 1 }
if {$nd_ng > 0} { puts "ERROR: ドライバの無いネットがある（RTL の書き漏れ）"; exit 1 }
if {$rm_seen != $ncore} { puts "ERROR: s45_core_* の OOC の run が $ncore 個でない（$rm_seen）。run の名前: $ooc_names"; exit 1 }
if {$rm_ng > 0} { puts "ERROR: ROM の中身（hex）を合成が読めていない"; exit 1 }

# ---- 合成〜実装〜ビットストリーム ----
# proj023 4b: synth_1・impl_1 でも Vivado が落ちる（2026-10-15 のビルド 6 回目: impl_1 が始まってすぐ segfault、
#   Abnormal program termination (11)）。**落ちた印のある run だけ**を 2 回まで回し直す（OOC と同じ方針。印の無い失敗は止める）。
#   wait_on_run は失敗した run で Tcl のエラーを投げてスクリプトごと止まるので、catch で受ける
# proj027 2f: impl_1 を回し直すときは、落ちた段（CURRENT_STEP）から後だけを reset する（reset_runs -from_step）。
#   ビルド 1 の build/ は write_bitstream の前の DRC で落ち、reset_run が丸ごと消したので配線済みの結果（routed.dcp）を失い、
#   その後の 2 回も link_design から回して落ちた。小さな設計で write_bitstream の頭で SIGSEGV を起こして確かめた
#   （2026-10-26）: -from_step write_bitstream の後の launch_runs -to_step write_bitstream は open_checkpoint routed.dcp から
#   write_bitstream だけを回し、routed.dcp は同じ中身のまま。init_design（link_design）で落ちたときは失うものが無いので丸ごと reset する。
#   **-from_step の reset の直後は PROGRESS が 100% になる**（STATUS は「route_design Complete!」）ので、完走の判定は
#   PROGRESS でなく STATUS と .bit で見る
proc impl_done {} {
    return [expr {[get_property STATUS [get_runs impl_1]] eq "write_bitstream Complete!"
                  && [llength [glob -nocomplain [file join [ooc_dir impl_1] *.bit]]] == 1}]
}
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
catch {wait_on_run impl_1}
for {set try 1} {$try <= 2 && ![impl_done]} {incr try} {
    set redo ""
    foreach n {synth_1 impl_1} {
        if {[ooc_crashed $n]} { set redo $n; break }
    }
    if {$redo eq ""} { break }
    set step [expr {$redo eq "impl_1" ? [get_property CURRENT_STEP [get_runs impl_1]] : ""}]
    if {$step in {"" init_design}} {
        puts "NOTE: $redo で Vivado が落ちた（段 [expr {$step eq "" ? "-" : $step}]）。丸ごと回し直す（$try 回目）"
        reset_run [get_runs $redo]
    } else {
        puts "NOTE: impl_1 の $step で Vivado が落ちた。$step から後だけを回し直す（$try 回目）"
        if {[catch {reset_runs [get_runs impl_1] -from_step $step} msg]} {
            # 丸ごとの reset に逃げない（それをすると配線済みの結果を消す）
            puts "ERROR: impl_1 を $step から reset できない: $msg"
            exit 1
        }
    }
    launch_runs impl_1 -to_step write_bitstream -jobs $jobs
    catch {wait_on_run impl_1}
}
if {![impl_done]} {
    puts "ERROR: impl_1 が完走していない（STATUS [get_property STATUS [get_runs impl_1]]）。$projdir の run ログを見る"
    exit 1
}

source ./build_post.tcl
