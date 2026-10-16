# SPDX-License-Identifier: BSD-3-Clause
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

set proj         proj023
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
set fft_opt res
if {[info exists ::env(FFT_OPT)] && $::env(FFT_OPT) ne ""} { set fft_opt $::env(FFT_OPT) }
set gb_k_rst 2          ;# rev3: 既定値 2（Makefile の GB_K_DEFAULT と対。README の rev3）
# rev6 の検証ビルド: GB_SLOW = b なら、gb_fifo の書き込みポインタの bit b の同期段を配置の前に遠くの SLICE（GB_SLOW_SITE）に固定する
# （tools/gb_slow.tcl）。既定の SLICE_X46Y109 は rev6 の配置での元の場所 SLICE_X106Y109 から X で 60 離したもの
set gb_slow ""
set gb_slow_site SLICE_X46Y109
if {[info exists ::env(GB_SLOW)] && $::env(GB_SLOW) ne ""} { set gb_slow $::env(GB_SLOW) }
if {[info exists ::env(GB_SLOW_SITE)] && $::env(GB_SLOW_SITE) ne ""} { set gb_slow_site $::env(GB_SLOW_SITE) }
if {$gb_slow ne "" && (![string is integer -strict $gb_slow] || $gb_slow < 0 || $gb_slow > 4)} {
    puts "ERROR: GB_SLOW = '$gb_slow'（0〜4。深さ 32 の gray は 5 ビット）"
    exit 1
}
if {[info exists ::env(GB_K)] && $::env(GB_K) ne ""} { set gb_k_rst $::env(GB_K) }
if {![string is integer -strict $gb_k_rst] || $gb_k_rst < 0 || $gb_k_rst > 24} {
    puts "ERROR: GB_K = '$gb_k_rst'（0〜24。gb_fifo の深さ 32 に余裕を残す）"
    exit 1
}
source ./src/sam45fine/fft_cfg.tcl
lassign [fft_opt_map $fft_opt] fft_throttle fft_cmul fft_bfly
set fft_code [fft_cfg_code $fft_throttle $fft_cmul $fft_bfly]

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

# ---- 分光計（wide_spec.v と対。proj023）----
# 32768 点 = 16 レーン × 2048 点（固定長、D-7）。細かい ch 0.125 MHz、1 フレーム 8.000 µs（2048 ビート）。束ね B = 1 / 2 / 4 は電力の後
set fft_mod     lane_fft_w ;# **名前は RTL（wide_spec.v）と sim/lane_fft_w_model.v と対**
set fft_lane_n  2048
set fft_in_w    15        ;# IP の入力（wide_pfb の出口 y、15 bit）
set fft_out_w   27        ;# unscaled の出力 = 15 + log2(2048) + 1。RTL は 32 bit の欄の下位 26 bit を読む（|Y| < 2^25、README 2c）
# フレームの頭（D-2）と起動の見張り。**RTL の既定と同じ値を明示して読み返す**（sim は GF_L2 2 で回している）
set wide_kf     0         ;# T ≡ K_F（mod 2048）がフレームの頭
set wide_st_n   16384     ;# 起動の見張り（ビート）
set wide_gf_l2  8         ;# F0 の格子 = 2^8 フレーム（M = G / 2048 = 256）
set wide_coef_hex [file normalize ./src/sam45wide/wide_coef.hex]
set wide_tw_hex   [file normalize ./src/sam45wide/wide_tw.hex]
# 生成物の形を先に見る（行数 2048・1 行の桁数 = 1152 / 4・576 / 4）。古い・切れた hex をここで止める
foreach {h ncol} [list $wide_coef_hex 288 $wide_tw_hex 144] {
    if {![file exists $h]} { puts "ERROR: $h が無い（make wide-coef / make wide-tw で作る）"; exit 1 }
    set fh [open $h r]; set lines [split [string trim [read $fh]] "\n"]; close $fh
    set bad 0
    foreach l $lines { if {[string length $l] != $ncol || ![string is xdigit -strict $l]} { incr bad } }   ;# Tcl の正規表現の {n} は 255 まで
    if {[llength $lines] != 2048 || $bad != 0} {
        puts "ERROR: $h の形が違う（[llength $lines] 行、うち $ncol 桁の 16 進でない行 $bad）"
        exit 1
    }
}

puts "PART      : $part"
puts "OUTDIR    : $outdir"
puts "FFT_OPT   : $fft_opt（$fft_throttle / $fft_cmul / $fft_bfly、符号 [format 0x%02x $fft_code]）"
set i 0
foreach ch $chans {
    lassign $ch t s
    puts "ADC $i     : [lindex $ch_labels $i] = Tile [expr {224 + $t}] / slice $s"
    incr i
}
puts "fs        : $fs_mhz MSPS （RFDC $fabric_mhz MHz × $spw_adc → DSP $dsp_mhz MHz × $spw sample/word）"
puts "GEARBOX   : $spw_adc → $gb_mid → $spw サンプル（×$gb_up / ÷$gb_dn）"
puts "SPEC      : 32768 点 = 16 × $fft_lane_n / 細かい ch [expr {$fs_gsps * 1000.0 / 32768}] MHz / 1 フレーム [expr {32768 / $fs_gsps / 1000.0}] us / SLICE 4096 ch × 2 / コア（束ね B 1・2・4）"
puts "WIDE      : K_F = $wide_kf / ST_N = $wide_st_n / GF_L2 = $wide_gf_l2"

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

file mkdir $outdir
create_project $proj $projdir -part $part -force

# board_part は part をボードの宣言値（-2）へ強制的に戻す（WARNING: Project 1-153）。
# -1 では board_part を使わず、src/board/ps_preset.tcl の PS の設定を明示して当てる（proj015）
set use_board [expr {$part eq $board_part_part}]
set ps_preset_file [file normalize ./src/board/ps_preset.tcl]
set use_preset_file [expr {!$use_board && [file exists $ps_preset_file]}]
set has_preset [expr {$use_board || $use_preset_file}]
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

# proj023 3b: コア（wide_s45_core）とその中身。窓（win_core 一式）・spec_core は足さない。FULL の位置は RAW（コア 0）だけ
add_files -norecurse [list ./src/common/wide_s45_core.v ./src/common/core_cmn.v ./src/common/wide_core.v ./src/common/wide_spec.v \
                           ./src/common/wide_pfb.v ./src/common/wide_chain.v ./src/common/wide_acc.v ./src/common/cmul.v ./src/common/dft16.v \
                           ./src/common/wide_coef_rom.v ./src/common/wide_tw_rom.v ./src/common/raw_core.v ./src/common/tp_core.v \
                           ./src/common/rec_fr.v ./src/common/rec_arb.v ./src/common/adc_ev.v]
# proj016〜: 時刻・リング・ギアボックスの見張り・RAW の入力の選び
add_files -norecurse [list ./src/common/time_core.v ./src/common/s45_ring.v ./src/common/gb_adc.v ./src/common/gb_gate.v ./src/common/axis_sel4.v]
# ROM の中身（$readmemh）。プロジェクトにも載せておく（CONFIG には絶対パスを与える。上の wide_coef_hex）
add_files -norecurse [list $wide_coef_hex $wide_tw_hex]
set_property file_type {Memory File} [get_files [list $wide_coef_hex $wide_tw_hex]]
set win_range 65536       ;# s45_core_i の AXI4-Lite の窓（16 bit 番地 = 64 KiB。INTERFACE 3.）

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
set xfft_req [fft_req $fft_throttle $fft_cmul $fft_bfly $fft_lane_n $fft_in_w $dsp_mhz]
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
        puts "ERROR: FFT IP のポートが wide_spec.v の前提と $ng 件合わない。entity $fft_mod にあるポート:"
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
if {$gb_slow ne ""} { set build_tag_base [expr {$build_tag_base | (1 << 27) | (($gb_slow & 7) << 24)}] }

# gb_fifo の axis_rd_data_count の幅は版で変わりうるので、ピンの幅を読んで与える（4 個とも同じ設定なので gb_fifo_0 で読む）
set rdc [get_bd_pins -quiet gb_fifo_0/axis_rd_data_count]
if {[llength $rdc] == 0} {
    puts "ERROR: gb_fifo_0/axis_rd_data_count が無い（HAS_RD_DATA_COUNT が効いていない）。gb_fifo_0 のピン:"
    foreach p [get_bd_pins gb_fifo_0/*] { puts "  $p" }
    exit 1
}
set rdc_w [expr {[get_property LEFT $rdc] - [get_property RIGHT $rdc] + 1}]

# proj015: 全帯域は 1 本だけ（axis_sel4 で 4 ADC から選ぶ）。proj021 手順 2-1: spec_core_0 のセルは無くし、
#   s45_core_0 の中の FULL の流れ（CONFIG.FULL = 1、src/common/s45_core.v）にした。入力は s45_core_0 の s_axis_full、選ぶのはその流れの SRC
set fsel [create_bd_cell -type module -reference axis_sel4 full_sel]
set_property CONFIG.DW $beat_bits $fsel
if {[get_property CONFIG.DW $fsel] != $beat_bits} { puts "ERROR: full_sel の DW が要求と違う"; exit 1 }
for {set i 0} {$i < $nch} {incr i} {
    set sel_axis($i) [BI full_sel [list "s${i}_axis" "S${i}_AXIS"] "full_sel の入力 $i"]
}
set sel_m [BI full_sel [list "m_axis" "M_AXIS"] "full_sel の出力"]

# proj016: 時刻（time_core_0）。BUILD_TAG = 土台 ＋ [20] 時刻のコア
set tcore [create_bd_cell -type module -reference time_core time_core_0]
set time_tag [expr {$build_tag_base | (1 << 20)}]
foreach {k want} [list CONFIG.BUILD_TAG $time_tag CONFIG.BIT_KIND 1 CONFIG.BIT_REV 1 CONFIG.PROJ [expr {0x00230100}]] {   ;# proj023: D-5
    set_property $k $want $tcore
    if {[get_property $k $tcore] != $want} { puts "ERROR: time_core_0 の $k が [get_property $k $tcore]（要求 $want）"; exit 1 }
}
foreach {k want} {CONFIG.BEATS_PER_SEC 256000000 CONFIG.BLANK_BEATS 128000000 CONFIG.MISS_BEATS 384000000} {
    if {[get_property $k $tcore] != $want} { puts "ERROR: time_core_0 の $k が [get_property $k $tcore]（期待 $want）"; exit 1 }
}
# **1 秒のビート数は DSP のクロック（fs / spw）と一致していなければならない**
if {abs([get_property CONFIG.BEATS_PER_SEC $tcore] - $dsp_mhz * 1e6) > 0.5} {
    puts "ERROR: time_core_0 の BEATS_PER_SEC（[get_property CONFIG.BEATS_PER_SEC $tcore]）が DSP のクロック $dsp_mhz MHz と合わない"
    exit 1
}
set time_axi [BI time_core_0 [list "s_axi" "S_AXI"] "time_core_0 の AXI4-Lite"]
puts [format "time_core_0: BUILD_TAG = 0x%08x / 1 秒 = %d ビート" $time_tag [get_property CONFIG.BEATS_PER_SEC $tcore]]

# proj021 手順 2-2a: リング（s45_ring_0、src/common/s45_ring.v）。入口 i = s45_core_i/m_axis_rec、書き手 → PS の S_AXI_HP0_FPD
set rcore [create_bd_cell -type module -reference s45_ring s45_ring_0]
foreach {k want} [list CONFIG.NIN $nch CONFIG.BIT_KIND 1 CONFIG.BIT_REV 1 CONFIG.PROJ [expr {0x00230100}]] {   ;# proj023: D-5
    set_property $k $want $rcore
    if {[get_property $k $rcore] != $want} { puts "ERROR: s45_ring_0 の $k が [get_property $k $rcore]（要求 $want）"; exit 1 }
}
if {$nch > 4} { puts "ERROR: s45_ring_0 の入口は 4 本まで（nch = $nch）"; exit 1 }
set ring_axi [BI s45_ring_0 [list "s_axi" "S_AXI"] "s45_ring_0 の AXI4-Lite"]
set ring_m   [BI s45_ring_0 [list "m_axi" "M_AXI"] "s45_ring_0 の AXI4 の書き手"]
set hp0      [get_bd_intf_pins -quiet zynq_ultra_ps_e_0/S_AXI_HP0_FPD]
if {$hp0 eq ""} { puts "ERROR: PS の S_AXI_HP0_FPD が無い"; exit 1 }
for {set i 0} {$i < $nch} {incr i} {
    set ring_in($i) [BI s45_ring_0 [list "s${i}_axis" "S${i}_AXIS"] "s45_ring_0 の入口 $i"]
}
puts "s45_ring_0: NIN = $nch / 書き手 → zynq_ultra_ps_e_0/S_AXI_HP0_FPD（128 bit）"

for {set i 0} {$i < $nch} {incr i} {
    set lbl  [lindex $ch_labels $i]
    # proj015: 窓のコア（ch ごと、NW = 4）
    # proj021 手順 2-1: コア s45_core_i（src/common/s45_core.v = win_core ＋ i = 0 だけ FULL の流れ）。**PS はこの名前でコアを見つける**
    #   CORE_PORT = [3:0] ADC の番号（SMA のラベル）/ [11:8] タイル / [15:12] スライス（chans。VERSIONS.md の実測）
    # proj023 3b: 中身は wide_s45_core（core_cmn ＋ wide_core ＋ コア 0 だけ RAW）。**セルの名前は s45_core_i のまま**
    set wcore [create_bd_cell -type module -reference wide_s45_core s45_core_$i]
    set win_tag [expr {$build_tag_base | (1 << 22) | $i}]
    lassign [lindex $chans $i] cp_t cp_s
    set core_port [expr {$i | ($cp_t << 8) | ($cp_s << 12)}]
    set f_raw [expr {$i == 0 ? 1 : 0}]                      ;# RAW の流れ（s = 2）を置くか（コア 0 だけ）
    set kv [list CONFIG.BUILD_TAG $win_tag CONFIG.GB_K_RST $gb_k_rst CONFIG.CORE_PORT $core_port CONFIG.RAW $f_raw \
                 CONFIG.K_F $wide_kf CONFIG.ST_N $wide_st_n CONFIG.GF_L2 $wide_gf_l2 \
                 CONFIG.BIT_KIND 1 CONFIG.BIT_REV 1 CONFIG.PROJ [expr {0x00230100}]]
    foreach {k want} $kv {
        set_property $k $want $wcore
        if {[get_property $k $wcore] != $want} { puts "ERROR: s45_core_$i の $k が [get_property $k $wcore]（要求 $want）"; exit 1 }
    }
    puts [format "s45_core_%d（%s）: wide_s45_core / BUILD_TAG = 0x%08x / GB_K_RST = %d / CORE_PORT = 0x%04x / RAW = %d" $i $lbl $win_tag $gb_k_rst $core_port $f_raw]
    if {$f_raw} {
        puts "  RAW の流れ（s = 2）: 生サンプル / ダンプ（raw_core）。入力は full_sel（4 ADC から選ぶ）"
        set full_axis [BI s45_core_0 [list "s_axis_full" "S_AXIS_FULL"] "s45_core_0 の RAW の流れの入力"]
    }
    set win_axi($i)  [BI s45_core_$i [list "s_axi"  "S_AXI"]  "s45_core_$i の AXI4-Lite"]
    set win_axis($i) [BI s45_core_$i [list "s_axis" "S_AXIS"] "s45_core_$i の AXI4-Stream 入力"]
    set rec_axis($i) [BI s45_core_$i [list "m_axis_rec" "M_AXIS_REC"] "s45_core_$i のレコードの出口（proj021 2-2a）"]
    set gbc [create_bd_cell -type ip -vlnv xilinx.com:ip:axis_broadcaster gb_bc_$i]
    cfg_apply $gbc [list CONFIG.NUM_MI 2 CONFIG.S_TDATA_NUM_BYTES [expr {$spw * 2}] CONFIG.M_TDATA_NUM_BYTES [expr {$spw * 2}]]
    foreach {k want} [list CONFIG.NUM_MI 2 CONFIG.S_TDATA_NUM_BYTES [expr {$spw * 2}] CONFIG.M_TDATA_NUM_BYTES [expr {$spw * 2}]] {
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

# proj023 3b: 共有の係数 ROM（D-6）。番地は s45_core_0、出口は 4 コアへ（下の shared_nets）
# proj023 4b: ひねり係数 ROM はコアごと（wide_tw_rom_i。下の ch_nets）
set rom_list [list wide_coef_rom_0 wide_coef_rom CONFIG.COEF_FILE $wide_coef_hex]
for {set i 0} {$i < $nch} {incr i} { lappend rom_list wide_tw_rom_$i wide_tw_rom CONFIG.TW_FILE $wide_tw_hex }
foreach {cell mod par hex} $rom_list {
    set c [create_bd_cell -type module -reference $mod $cell]
    # 文字列の CONFIG に引用符が要るかは版で違いうるので、素のままと引用符つきを順に試し、読み返しで判定する。
    # **生成されたラッパに .$par("<絶対パス>") が書かれたかは generate_target の後で見る**（下の「ROM のラッパ」）
    set got ""
    foreach v [list $hex "\"$hex\""] {
        if {[catch {set_property $par $v $c}]} continue
        set got [string trim [get_property $par $c] {"}]
        if {$got eq $hex} break
    }
    if {$got ne $hex} { puts "ERROR: $cell の $par が '$got'（要求 $hex）"; exit 1 }
    puts "ROM        : $cell（$mod）$par = $hex"
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
# **NUM_CLKS = 2**: aclk = pl_clk0（PS と RFDC）/ aclk1 = DSP ドメイン（spec_core）。
# SmartConnect は相手の IP のクロックから、どのポートがどのクロックかを判断し、
# 乗り換えを内部に持つ。**spec_core を 256 MHz に置いたまま自作の CDC を書かずに済む。**
# M00 = RFDC、M0(1+i) = s45_core_i（proj015）、M0(1+nch) = time_core_0（proj016。proj021 手順 2-1 で spec_core_0 の M が無くなった）
set smc_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_ctrl]
# proj021 手順 2-2a: M0(2+nch) = s45_ring_0
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI [expr {1 + $nch + 2}] CONFIG.NUM_CLKS {2}] $smc_ctrl
if {[get_property CONFIG.NUM_MI $smc_ctrl] != 1 + $nch + 2} {
    puts "ERROR: smc_ctrl の NUM_MI が [get_property CONFIG.NUM_MI $smc_ctrl]（要求 [expr {1 + $nch + 2}]。proj021: RFDC ＋ s45_core × nch ＋ time_core_0 ＋ s45_ring_0）"
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
    lappend dsp_dom gb_fifo_$i/m_axis_aclk gb_dn_$i/aclk gb_gate_$i/aclk s45_core_$i/aclk gb_bc_$i/aclk wide_tw_rom_$i/clk
}
lappend dsp_dom full_sel/aclk time_core_0/aclk s45_ring_0/aclk zynq_ultra_ps_e_0/saxihp0_fpd_aclk wide_coef_rom_0/clk
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
# proj015: ギアボックスの制御は s45_core_i（spec_core_0 の gb_* はどこにもつながない）。**ch ごとに閉じている**
#   書き込み側（gb_up / gb_fifo）: gb_adc が rst_adc と win_core の gb_hold（0）から作る gb_rstn
#   読み出し側（gb_gate / gb_dn）: win_core の gb_dn_rstn（= aresetn を 1 段）
#   gb_gate の見張りは s45_core_i と full_sel（axis_sel4）の i 番の入口へ
# **ch ごとの結線はこの表 1 つから張り、下の照合も同じ表を読む**（張る側と照かめる側が別の表だと、両方が同じ誤りを持てない）
proc ch_nets {i} {
    return [list \
        rst_dsp/peripheral_aresetn     [list s45_core_$i/aresetn gb_bc_$i/aresetn] \
        gb_adc_$i/gb_rstn              [list gb_up_$i/aresetn gb_fifo_$i/s_axis_aresetn] \
        s45_core_$i/gb_dn_rstn         [list gb_gate_$i/aresetn gb_dn_$i/aresetn] \
        s45_core_$i/gb_hold            gb_adc_$i/hold \
        s45_core_$i/gb_adj             gb_adc_$i/adj \
        s45_core_$i/gb_k               gb_gate_$i/k \
        gb_fifo_$i/axis_rd_data_count  gb_gate_$i/rd_count \
        gb_gate_$i/gb_stat             [list s45_core_$i/gb_stat full_sel/gb_stat$i] \
        gb_adc_$i/adc_out              gb_gate_$i/adc_in \
        gb_gate_$i/adc_stat            [list s45_core_$i/adc_stat full_sel/adc_stat$i] \
        s45_core_$i/tw_addr            wide_tw_rom_$i/addr \
        wide_tw_rom_$i/tw              s45_core_$i/tw_in \
        wide_tw_rom_$i/k1_out          s45_core_$i/tw_k1 \
    ]
}
for {set i 0} {$i < $nch} {incr i} {
    foreach {drv loads} [ch_nets $i] { foreach p $loads { nc $drv $p } }
}
# proj021 手順 2-2a: FULL = 0 のコア（s45_core_1〜）の FULL の入口を定数 0 で縛る（CRITICAL WARNING BD 41-759 を消す。RTL では使っていない入口）
#   幅ごとに 1 個の xlconstant を全部のコアで共有する。照合は下の shared_nets の表で一緒に見る
foreach {nm w} {full_tie_1b 1 full_tie_256b 256} {   ;# proj023: 32 bit（full_gb_stat・full_adc_stat）は wide_s45_core に無い
    set c [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant $nm]
    set_property -dict [list CONFIG.CONST_WIDTH $w CONFIG.CONST_VAL 0] $c
    if {[get_property CONFIG.CONST_WIDTH $c] != $w || [get_property CONFIG.CONST_VAL $c] != 0} { puts "ERROR: $nm の CONST_WIDTH・CONST_VAL が要求と違う"; exit 1 }
}
proc tie_list {pin} { set r {}; for {set i 1} {$i < $::nch} {incr i} { lappend r s45_core_${i}/$pin }; return $r }
# proj015: 全帯域の分光 1 本とその選び（共有のネット。下の照合で見る）
proc shared_nets {} {
    return [list \
        full_tie_1b/dout               [tie_list s_axis_full_tvalid] \
        full_tie_256b/dout             [tie_list s_axis_full_tdata] \
        rst_dsp/peripheral_aresetn     full_sel/aresetn \
        s45_core_0/full_sel            full_sel/sel \
        rst_dsp/peripheral_aresetn     time_core_0/aresetn \
        rst_dsp/peripheral_aresetn     s45_ring_0/aresetn \
        rst_ctrl/peripheral_aresetn    time_core_0/ctrl_aresetn \
        time_core_0/t_out              [lmap i [lseq $::nch] {list s45_core_${i}/t_in}] \
        time_core_0/go_out             [lmap i [lseq $::nch] {list s45_core_${i}/go_in}] \
        time_core_0/ev_out             [lmap i [lseq $::nch] {list s45_core_${i}/tev_in}] \
        {*}[concat {*}[lmap i [lseq $::nch] {list s45_core_${i}/rec_drop [list s45_ring_0/rec_drop${i}]}]] \
        s45_core_0/coef_addr           wide_coef_rom_0/addr \
        s45_core_0/coef_addr_v         wide_coef_rom_0/addr_v \
        wide_coef_rom_0/coef           [lmap i [lseq $::nch] {list s45_core_${i}/coef_in}] \
        wide_coef_rom_0/m_out          [lmap i [lseq $::nch] {list s45_core_${i}/coef_m}] \
    ]
}
proc lseq {n} { set r {}; for {set i 0} {$i < $n} {incr i} { lappend r $i }; return $r }
foreach {drv loads} [shared_nets] { foreach p $loads { nc $drv $p } }

# ---- データ経路: RFDC → ギアボックス → spec_core（ch ごと）----
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
        [get_bd_intf_pins gb_bc_$i/M00_AXIS] $win_axis($i) \
        [get_bd_intf_pins gb_bc_$i/M01_AXIS] $sel_axis($i) \
        [get_bd_intf_pins smc_ctrl/M[format %02d [expr {1 + $i}]]_AXI] $win_axi($i) \
    ]
    foreach {a b} $ch_intf($i) { ic $a $b }
    puts [format "  %s = Tile %d slice %d -> gb_adc_%d / gb_up_%d / gb_fifo_%d / gb_gate_%d / gb_dn_%d -> gb_bc_%d -> {s45_core_%d（smc M%02d）, full_sel/s%d}" \
            [lindex $ch_labels $i] [expr {224 + $t}] $s $i $i $i $i $i $i $i [expr {1 + $i}] $i]
    incr i
}

# 制御系 AXI: PS → SmartConnect → RFDC（M00）/ s45_core_i（M0(1+i)。上の ch_intf で張った）/ time_core_0（M0(1+nch)）
ic [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_FPD] [get_bd_intf_pins smc_ctrl/S00_AXI]
ic [get_bd_intf_pins smc_ctrl/M00_AXI] [get_bd_intf_pins rfdc/s_axi]
set sh_intf [list $sel_m $full_axis \
                 [get_bd_intf_pins smc_ctrl/M[format %02d [expr {1 + $nch}]]_AXI] $time_axi \
                 [get_bd_intf_pins smc_ctrl/M[format %02d [expr {2 + $nch}]]_AXI] $ring_axi \
                 $ring_m $hp0]
# proj021 手順 2-2a: レコードの道 s45_core_i/m_axis_rec → s45_ring_0/s{i}_axis
for {set i 0} {$i < $nch} {incr i} { lappend sh_intf $rec_axis($i) $ring_in($i) }
foreach {a b} $sh_intf { ic $a $b }
puts [format "  full_sel（s45_core_0 の FULL の流れの SRC で選ぶ）-> s45_core_0/s_axis_full / time_core_0（smc M%02d）" [expr {1 + $nch}]]
puts [format "  s45_core_i/m_axis_rec -> s45_ring_0/s{i}_axis（smc M%02d）-> zynq_ultra_ps_e_0/S_AXI_HP0_FPD" [expr {2 + $nch}]]

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
    # ch ごとの点対点のネット（張ったのと同じ表）。rst_dsp だけは共有
    foreach {drv loads} [ch_nets $i] {
        lappend rows pin $drv $loads [string match rst_* $drv]
    }
    # クロックと ADC 側のリセット（共有。載っているべきネットに載っているか）
    lappend rows pin $adc_fabric [list gb_up_$i/aclk gb_fifo_$i/s_axis_aclk gb_adc_$i/aclk] 1
    lappend rows pin $dsp_fabric [list gb_fifo_$i/m_axis_aclk gb_dn_$i/aclk gb_gate_$i/aclk s45_core_$i/aclk gb_bc_$i/aclk wide_tw_rom_$i/clk] 1
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
# proj015: 共有のネット（全帯域の選び）。在るべき相手と、**spec_core_0 の gb_* の出口がどこにもつながっていない**こと
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
set probs [net_check 0 pin $dsp_fabric [list full_sel/aclk time_core_0/aclk s45_ring_0/aclk zynq_ultra_ps_e_0/saxihp0_fpd_aclk wide_coef_rom_0/clk] 1]
lappend nc_log [format "ch * %-3s pin  %s -> full_sel/aclk time_core_0/aclk s45_ring_0/aclk zynq_ultra_ps_e_0/saxihp0_fpd_aclk wide_coef_rom_0/clk" [expr {[llength $probs] ? "NG" : "OK"}] [norm_pin $dsp_fabric]]
foreach pr $probs { lappend nc_log "        $pr"; incr nc_ng }
# proj021 手順 2-1: spec_core_0 のセルは無い（FULL の流れは s45_core_0 の中。ギアボックスの gb_* は s45_core_i が握る）
set tag [expr {[llength [get_bd_cells -quiet spec_core_*]] == 0 ? "OK" : "NG"}]
lappend nc_log [format "ch * %-3s spec_core_* のセルが無い" $tag]
if {$tag eq "NG"} { incr nc_ng }
# proj023 3b: 共有の ROM の番地は s45_core_0 だけが出す。**s45_core_1〜 の番地の出口はどこにもつながっていない**（在ってはいけない側）
proc pin_unconnected {p} { return [expr {[llength [get_bd_pins -quiet $p]] == 1 && [llength [get_bd_nets -quiet -of_objects [get_bd_pins -quiet $p]]] == 0}] }
for {set i 1} {$i < $nch} {incr i} {
    foreach pn {coef_addr coef_addr_v} {
        set tag [expr {[pin_unconnected s45_core_$i/$pn] ? "OK" : "NG"}]
        lappend nc_log [format "ch %d %-3s s45_core_%d/%s がどこにもつながっていない（係数 ROM の番地はコア 0 だけ）" $i $tag $i $pn]
        if {$tag eq "NG"} { incr nc_ng }
    }
}
# 4 個のセルの中身が wide_s45_core であること（窓の s45_core が残っていない）
for {set i 0} {$i < $nch} {incr i} {
    set v [get_property VLNV [get_bd_cells s45_core_$i]]
    set tag [expr {[string match "*:module_ref:wide_s45_core:*" $v] ? "OK" : "NG"}]
    lappend nc_log [format "ch %d %-3s s45_core_%d の中身 = %s（期待 wide_s45_core）" $i $tag $i $v]
    if {$tag eq "NG"} { incr nc_ng }
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
        # proj016: 1 タイルなら直に繋がっているべき（在るべき側の照合）
        lappend nc_log "tile $t NG  rfdc/m${t}_axis_aresetn が rst_adc/peripheral_aresetn に繋がっていない（1 タイルは直に配る）"
        incr nc_ng
    } else {
        lappend nc_log [format "tile %d OK  rfdc/m%d_axis_aresetn の源（%s）" $t $t [expr {$direct ? "rst_adc に直" : "切り出し"}]]
    }
}
# 陽性対照: (a) 在るべき相手を他の ch にする（(1) が落ちるべき）/ (b) 正しいネットを他の ch の番号で照らす（(2) が落ちるべき）
set pc_ok 1
if {$nch > 1} {
    set pa [net_check 0 pin s45_core_0/gb_hold [list gb_adc_1/hold] 0]
    set pb [net_check 1 pin s45_core_0/gb_hold [list gb_adc_0/hold] 0]
    if {[llength $pa] == 0} { set pc_ok 0; lappend nc_log "陽性対照 (a) が通ってしまった（在るべき相手の照合が壊れている）" }
    if {[llength $pb] == 0} { set pc_ok 0; lappend nc_log "陽性対照 (b) が通ってしまった（他の ch の照合が壊れている）" }
    lappend nc_log "陽性対照: (a) [llength $pa] 件・(b) [llength $pb] 件で落ちた（どちらも 1 件以上が期待）"
}
# proj016: 時刻のネットの陽性対照（ch が 1 本でも回る）。(c) t_out の相手に go_in を期待する / (d) go_out の相手に t_in を期待する。どちらも落ちるべき
set pcc [net_check 0 pin time_core_0/t_out  [list s45_core_0/go_in] 1]
set pcd [net_check 0 pin time_core_0/go_out [list s45_core_0/t_in] 1]
if {[llength $pcc] == 0} { set pc_ok 0; lappend nc_log "陽性対照 (c) が通ってしまった（時刻のネットの照合が壊れている）" }
if {[llength $pcd] == 0} { set pc_ok 0; lappend nc_log "陽性対照 (d) が通ってしまった（時刻のネットの照合が壊れている）" }
lappend nc_log "陽性対照: (c) [llength $pcc] 件・(d) [llength $pcd] 件で落ちた（どちらも 1 件以上が期待）"
# proj023 3b: 「つながっていない」の照合の陽性対照 (e): つながっている s45_core_0/coef_addr に当てると「つながっていない」と言わないこと。
#   (f): 在りもしないピンにも「つながっていない」と言わないこと（名前を間違えた照合が黙って通らない）
set pce [pin_unconnected s45_core_0/coef_addr]
set pcf [pin_unconnected s45_core_1/coef_addr_no_such_pin]
if {$pce} { set pc_ok 0; lappend nc_log "陽性対照 (e) が通ってしまった（つながっているピンを「つながっていない」と言った）" }
if {$pcf} { set pc_ok 0; lappend nc_log "陽性対照 (f) が通ってしまった（無いピンを「つながっていない」と言った）" }
lappend nc_log "陽性対照: (e) [expr {$pce ? "通った（NG）" : "落ちた"}]・(f) [expr {$pcf ? "通った（NG）" : "落ちた"}]（どちらも落ちるのが期待）"
# proj023 4b: (g) コア 0 のひねり係数 ROM のネットを ch 1 として照らす（(2) が wide_tw_rom_0 と s45_core_0 を「他の ch」と言うべき。
#   照合の正規表現に wide_tw_rom が入っていないと黙って通る）
if {$nch > 1} {
    set pcg [lsearch -all -inline [net_check 1 pin s45_core_0/tw_addr [list wide_tw_rom_0/addr] 0] "*ch 0 のピン wide_tw_rom_0/*"]
    if {[llength $pcg] == 0} { set pc_ok 0; lappend nc_log "陽性対照 (g) が通ってしまった（ひねり係数 ROM の ch の照合が壊れている）" }
    lappend nc_log "陽性対照: (g) [llength $pcg] 件で落ちた（1 件以上が期待）"
}
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
# proj015: s45_core_i の窓（win_range の境界に揃える）。proj021 2-2d から 64 KiB（2-2c までは仮の読み窓のため 1 MiB）
for {set i 0} {$i < $nch} {incr i} {
    set win_seg ""
    foreach seg [get_bd_addr_segs -quiet] {
        if {[string match "*s45_core_${i}*" $seg] && [string match "*SEG_*" $seg]} { set win_seg $seg }
    }
    if {$win_seg eq ""} { puts "ERROR: s45_core_$i のアドレスセグメントが見つからない"; exit 1 }
    if {[get_property RANGE $win_seg] < $win_range} { set_property RANGE $win_range $win_seg }
    set woff [get_property OFFSET $win_seg]
    set wrng [get_property RANGE $win_seg]
    if {($woff % $win_range) != 0} {
        # 揃っていなければ、win_range 境界の空きへ動かす（重なりは下で見る）
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
            puts "ERROR: 窓 $i1 と $i2 が重なっている（10 + i = s45_core_i、99 = time_core_0、98 = s45_ring_0）"
            exit 1
        }
    }
}

validate_bd_design
save_bd_design

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

# ---- rev6 の検証ビルド: 配置の後に遅いビットを作る ----
if {$gb_slow ne ""} {
    set hook [file normalize $outdir/gb_slow_hook.tcl]
    set fh [open $hook w]
    puts $fh "set gb_slow_bit $gb_slow"
    puts $fh "set gb_slow_site $gb_slow_site"
    puts $fh "source [file normalize ./tools/gb_slow.tcl]"
    close $fh
    set_property STEPS.PLACE_DESIGN.TCL.PRE $hook [get_runs impl_1]
    puts "NOTE: 遅いビットの検証ビルド（bit $gb_slow → $gb_slow_site）。**本番には使わない**"
}

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
# proj023 3b: 共有の ROM のラッパに hex の絶対パスが文字列として書かれたか（**在るべき側**。引用符が抜けると合成で落ちるか、別の名前を探して 0 の ROM になる）
set wrap_list [list wide_coef_rom_0 COEF_FILE $wide_coef_hex]
for {set i 0} {$i < $nch} {incr i} { lappend wrap_list wide_tw_rom_$i TW_FILE $wide_tw_hex }
foreach {inst par hex} $wrap_list {
    set vs {}
    catch {set vs [split [exec find $projdir -path "*${bd_name}_${inst}_0*" -name "*.v"] "\n"]}
    set hit ""
    foreach f $vs {
        set fh [open $f r]; set t [read $fh]; close $fh
        set hre [regsub -all {[][{}()*+?.\\^$|]} $hex {\\&}]
        if {[regexp "\\.${par}\\s*\\(\\s*\"$hre\"\\s*\\)" $t]} { set hit $f; break }
    }
    if {$hit eq ""} {
        puts "ERROR: $inst のラッパに .${par}(\"$hex\") が無い。探したファイル:"
        foreach f $vs { puts "  $f" }
        exit 1
    }
    puts "ROM のラッパ: $inst .$par = \"$hex\"（[file tail $hit]）"
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
# proj023 3b: $readmemh が読めないと ROM が 0 になり、BRAM が消えるだけで合成は通る。**OOC のログで先に止める**
set rm_ng 0
set rm_seen 0
foreach n $ooc_names {
    if {![string match "*wide_coef_rom*" $n] && ![string match "*wide_tw_rom*" $n]} continue
    incr rm_seen
    set lf [file join [ooc_dir $n] runme.log]
    set fh [open $lf r]; set t [read $fh]; close $fh
    foreach line [split $t "\n"] {
        if {[regexp -nocase {Synth 8-4445|could not open .*readmem|readmem.*(not found|cannot|could not)} $line]} { puts "  $n: $line"; incr rm_ng }
    }
}
puts "ROM の中身 : OOC の run [expr {$rm_seen}] 個のログに \$readmemh の失敗 $rm_ng 行"
# proj023 4a: **ドライバの無いネット（Synth 8-3848）で止める**。ビルド 5 回目の .bit は wide_s45_core の s_axi_arready が
#   どこからも駆動されず（RTL の書き漏れ）、実機で NSTREAM が IF_ID の値に読めた。Vivado は OOC のログで警告していたが、
#   iverilog の tb は arready の z を「準備よし」と読んで通っていた。自作のセル（module reference）の run だけを見る
set nd_ng 0
#   （Xilinx の IP の run は対象外: ビルド 5 回目で rfdc 24・PS 5・smartconnect 1 行が出ていて、どれも IP の中の使わない口）
set nd_seen 0
foreach n $ooc_names {
    if {![regexp {^system_(s45_core|wide_coef_rom|wide_tw_rom|time_core|s45_ring|gb_adc|gb_gate|full_sel)_} $n]} continue
    incr nd_seen
    set lf [file join [ooc_dir $n] runme.log]
    if {![file exists $lf]} continue
    set fh [open $lf r]; set t [read $fh]; close $fh
    foreach line [split $t "\n"] {
        if {[string match "*Synth 8-3848*" $line]} { puts "  $n: $line"; incr nd_ng }
    }
}
puts "ドライバ   : 自作のセルの OOC の run $nd_seen 個のログに Synth 8-3848（ドライバの無いネット）$nd_ng 行"
if {$nd_seen < 4 + 1 + $nch + 1 + 1 + 4 + 4 + 1} { puts "ERROR: 自作のセルの OOC の run が $nd_seen 個（期待 [expr {16 + $nch}]。run の名前が変わった？ $ooc_names）"; exit 1 }
if {$nd_ng > 0} { puts "ERROR: ドライバの無いネットがある（RTL の書き漏れ）"; exit 1 }
if {$rm_seen != 1 + $nch} { puts "ERROR: wide_coef_rom・wide_tw_rom_* の OOC の run が [expr {1 + $nch}] 個でない（$rm_seen）。run の名前: $ooc_names"; exit 1 }
if {$rm_ng > 0} { puts "ERROR: ROM の中身（hex）を合成が読めていない"; exit 1 }

# ---- 合成〜実装〜ビットストリーム ----
# proj023 4b: synth_1・impl_1 でも Vivado が落ちる（2026-10-15 のビルド 6 回目: impl_1 が始まってすぐ segfault、
#   Abnormal program termination (11)）。**落ちた印のある run だけ**を 2 回まで回し直す（OOC と同じ方針。印の無い失敗は止める）。
#   wait_on_run は失敗した run で Tcl のエラーを投げてスクリプトごと止まるので、catch で受ける
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
catch {wait_on_run impl_1}
for {set try 1} {$try <= 2 && [get_property PROGRESS [get_runs impl_1]] ne "100%"} {incr try} {
    set redo ""
    foreach n {synth_1 impl_1} {
        if {[ooc_crashed $n]} { set redo $n; break }
    }
    if {$redo eq ""} { break }
    puts "NOTE: $redo で Vivado が落ちた。回し直す（$try 回目）"
    reset_run [get_runs $redo]
    launch_runs impl_1 -to_step write_bitstream -jobs $jobs
    catch {wait_on_run impl_1}
}
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    puts "ERROR: impl_1 が完走していない。$projdir の run ログを見る"
    exit 1
}

open_run impl_1

# ---- proj016: 1PPS のポートが意図した足に出ているか（proj007 と同じ。合否判定なので catch の外）----
puts ""
puts "---- 1PPS の入力ポート ----"
foreach {pname want} {pps_trig AH13 pps_comp AJ13} {
    set prt [get_ports -quiet $pname]
    if {[llength $prt] == 0} {
        puts "ERROR: ポート $pname が存在しない（create_bd_port の名前と src/board/pps.xdc の get_ports を突き合わせる）"
        exit 1
    }
    set got [get_property PACKAGE_PIN $prt]
    set io  [get_property IOSTANDARD  $prt]
    puts [format "  %-10s %-6s %s" $pname $got $io]
    if {$got ne $want} { puts "ERROR: $pname の配置が $got。期待 $want（RefMan A6 / Appendix A）"; exit 1 }
}
# ---- proj023 3b: 共有の ROM が BRAM として残っているか（合否。**中身が 0 なら ROM は消えて BRAM が 0 になる**）----
# 予言: 係数 2048 × 1152 bit → RAMB36（512 × 72）× 64、ひねり係数 2048 × 576 bit → × 32（レーン 0 の定数の列が削られて少し減りうる）
puts ""
puts "---- ROM の BRAM（係数は共有・ひねり係数はコアごと）----"
set bram_list [list wide_coef_rom_0 64]
for {set i 0} {$i < $nch} {incr i} { lappend bram_list wide_tw_rom_$i 32 }
foreach {cell pred} $bram_list {
    set n36 0; set n18 0
    foreach x [get_cells -quiet -hierarchical -filter {REF_NAME =~ RAMB36*}] { if {[string first "/$cell/" "/$x"] >= 0} { incr n36 } }
    foreach x [get_cells -quiet -hierarchical -filter {REF_NAME =~ RAMB18*}] { if {[string first "/$cell/" "/$x"] >= 0} { incr n18 } }
    set eq [expr {$n36 + $n18 / 2.0}]
    puts [format "  %-16s RAMB36 %d・RAMB18 %d（RAMB36 換算 %.1f、予言 %d）" $cell $n36 $n18 $eq $pred]
    if {$eq < $pred / 2.0} { puts "ERROR: $cell の BRAM が予言の半分に届かない。ROM の中身（\$readmemh）が効いていない疑い"; exit 1 }
}
report_timing_summary -file $outdir/timing.rpt
report_utilization    -file $outdir/utilization.rpt
report_drc            -file $outdir/drc.rpt
report_clocks         -file $outdir/clocks.rpt

# ---- ここから診断。**診断の失敗でビルドを壊さない。** ----
# 2026-09-16、存在しないコマンド（get_clock_groups）を診断に書いたために、
# write_bitstream まで成功していたのに成果物のコピーに到達しなかった。
# 調べるためのコードが、調べたい対象を壊してはいけない。
if {[catch {

# ---- run のログから CRITICAL WARNING を拾い上げる ----
# **launch_runs は別プロセスなので、run の中の警告はこのコンソールに出ない。**
puts ""
puts "---- run の CRITICAL WARNING ----"
set seen 0
foreach lf [lsort [glob -nocomplain $projdir/$proj.runs/*/runme.log]] {
    set fh [open $lf r]
    foreach line [split [read $fh] \n] {
        if {[string match "CRITICAL WARNING*" $line]} {
            puts "  [file tail [file dirname $lf]]: $line"
            incr seen
        }
    }
    close $fh
}
if {$seen == 0} { puts "  （なし）" }

# ---- クロックと非同期グループ ----
puts ""
puts "---- クロック ----"
foreach c [get_clocks -quiet] {
    puts [format "  %-34s %8.3f ns  (%7.3f MHz)" $c \
          [get_property PERIOD $c] [expr {1000.0/[get_property PERIOD $c]}]]
}
# **get_clock_groups というコマンドは存在しない**（2026-09-16 に書いて落とした）。
report_clock_interaction -delay_type min_max -significant_digits 3 \
    -file $outdir/clock_interaction.rpt
set fh [open $outdir/clock_interaction.rpt r]
set ci [read $fh]
close $fh
set n_async [regexp -all -nocase {asynchronous} $ci]
puts ""
puts "クロック間の制約: $outdir/clock_interaction.rpt"
puts "  asynchronous を含む箇所 = $n_async"
if {$n_async == 0} {
    puts "  **非同期の宣言が見当たらない。src/board/timing.xdc が効いていない可能性がある**"
}

# ---- BRAM と DSP の使用量 ----
# README の予言（BRAM36 と DSP の見積もり）と突き合わせる。proj023 の見込み: DSP 2,656・BRAM ≒ 784・URAM ≒ 40・LUT ≒ 252k・FF ≒ 489k（README の見積もり ＋ 2b の ROM の移し替え）
puts ""
puts "---- ブロック RAM / DSP ----"
foreach line [split [exec cat $outdir/utilization.rpt] \n] {
    if {[string match "*Block RAM Tile*" $line] || [string match "*RAMB36*" $line] \
        || [string match "*RAMB18*" $line] || [string match "*URAM*" $line] \
        || [string match "| DSPs*" $line] || [string match "*DSP48E2*" $line]} {
        puts "  [string trim $line]"
    }
}
# 階層ごと（lane_fft 16 個・spec_core の残り）に分けて残す
report_utilization -hierarchical -hierarchical_depth 4 -file $outdir/utilization_hier.rpt

# ---- lane_fft_w 1 個ぶん・64 個の合計・コアごと・段ごと（proj023 3b）----
# **make survey（IP 単体の OOC 合成）の数字と突き合わせる。**固定長・入力 15 bit は survey していないので、ここが初めての実測
set ffts [lsort [get_cells -quiet -hierarchical -filter "ORIG_REF_NAME == $fft_mod || REF_NAME == $fft_mod"]]
# **名前に [0] が入るので -filter の =~ は使わない**（glob の文字クラスとして読まれ、何にも当たらない）。
# DSP の名前を一度集め、先頭一致で数える
set dsp_names [get_property NAME [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E2}]]
set dsp_all [llength $dsp_names]
proc count_under {names c} {
    set n 0
    foreach x $names { if {[string first "$c/" $x] == 0} { incr n } }
    return $n
}
proc count_in {names pat} {
    set n 0
    foreach x $names { if {[string first $pat "/$x"] >= 0} { incr n } }
    return $n
}
set dsp_fft 0
foreach c $ffts { incr dsp_fft [count_under $dsp_names $c] }
puts ""
puts "---- FFT IP の資源（$fft_mod、FFT_OPT = $fft_opt）----"
puts "  $fft_mod の個数         = [llength $ffts]（期待 [expr {16 * $nch}] = 16 レーン × $nch コア）"
if {[llength $ffts] > 0} {
    set c0 [lindex $ffts 0]
    report_utilization -cells $c0 -file $outdir/lane_fft_util.rpt
    puts "  DSP48E2 1 個あたり      = [count_under $dsp_names $c0]（$c0。予言 27）"
    puts "    予言（proj022 の S-1 から固定長の差を引いた見込み）: LUT ≒ 3,190・BRAM 8"
    foreach line [split [exec cat $outdir/lane_fft_util.rpt] \n] {
        if {[regexp {^\|\s*(CLB LUTs|CLB Registers|Block RAM Tile|DSPs)\s*\|} $line]} { puts "    [string trim $line]" }
    }
}
puts "  DSP48E2 $fft_mod [llength $ffts] 個の合計 = $dsp_fft（予言 [expr {16 * $nch}] × 27 = [expr {16 * $nch * 27}]）"
puts "  DSP48E2 全体            = $dsp_all（予言 2656 = 664 × 4: レーン FFT 432 ＋ PFB 64 ＋ 鎖 144 ＋ TP 24）"
# コアごと。4 個が同じでなければ、どこかのコアだけ最適化が違う（コア 0 は RAW を持つが RAW は DSP を使わない）
for {set i 0} {$i < $nch} {incr i} {
    puts [format "  DSP48E2 s45_core_%d（%s） = %d（予言 664）" $i [lindex $ch_labels $i] [count_in $dsp_names "/s45_core_${i}/inst/"]]
}
# コア 0 の段ごと（階層の名前は wide_s45_core.v・wide_core.v・wide_spec.v・core_cmn.v の generate / インスタンス名）
foreach {sub pred} {u_wide/u_spec/u_pfb 64 u_wide/u_spec/g_lane 432 u_wide/u_spec/u_chain 144 u_wide/u_spec/u_acc 0 u_cmn/g_tp.u_tp 24 g_raw.u_raw 0} {
    set n [count_in $dsp_names "/s45_core_0/inst/$sub"]
    puts [format "  DSP48E2 s45_core_0/%-24s = %d（予言 %d）" $sub $n $pred]
}
# コア 0 の RAW（raw_core）と共有の ROM の資源
foreach {c f what} {s45_core_0/inst/g_raw.u_raw raw_core_util.rpt "s45_core_0 の RAW（予言 RAMB36 8 前後・LUT 1,000〜3,000）" \
                    wide_coef_rom_0 coef_rom_util.rpt "係数 ROM（予言 RAMB36 64）" wide_tw_rom_0 tw_rom_util.rpt "ひねり係数 ROM（予言 RAMB36 32）"} {
    set cc [get_cells -quiet $c]
    if {$cc eq ""} { set cc [get_cells -quiet -hierarchical -filter "NAME =~ *$c"] }
    if {$cc eq ""} { puts "  WARNING: $c のセルが見つからない（utilization_hier.rpt で見る）"; continue }
    report_utilization -cells [lindex $cc 0] -file $outdir/$f
    puts "  $what:"
    foreach line [split [exec cat $outdir/$f] \n] {
        if {[regexp {^\|\s*(CLB LUTs|CLB Registers|Block RAM Tile|DSPs)\s*\|} $line]} { puts "    [string trim $line]" }
    }
}
# proj023 3b: 共有の ROM の配りの 1 段（wide_spec の coef_q・tw_q）がファブリックの FF として残っているか（DSP の A レジスタに吸われると 0）
set ff_names [get_property NAME [get_cells -quiet -hierarchical -filter {REF_NAME =~ FD*}]]
foreach {nm pred} {coef_q_reg 1152 tw_q_reg 576} {
    for {set i 0} {$i < $nch} {incr i} {
        set n [count_in $ff_names "/s45_core_${i}/inst/u_wide/u_spec/$nm"]
        puts [format "  FF s45_core_%d の %-10s = %d（予言 %d、0 なら DSP に吸われた）" $i $nm $n $pred]
    }
}
# 全体の LUT・FF・URAM を utilization.rpt から（vivado.log の上の表は BRAM・DSP だけなので）
if {![catch {set fh [open $outdir/utilization.rpt r]; set ut [read $fh]; close $fh}]} {
    foreach line [split $ut "\n"] {
        if {[regexp {^\|\s*(CLB LUTs|CLB Registers|URAM|Block RAM Tile)\*?\s*\|} $line]} { puts "  全体: [string trim $line]" }
    }
}

# ---- 一番きつい経路のクロック対を **必ず** 出す ----
# **WNS が正でも出す。**通ったかどうかだけ見ていると、
# 「宣言し忘れた乗り換えが、たまたま間に合っていただけ」を見逃す。
# 起点と終点のクロックが違うのに残っていたら、timing.xdc の非同期宣言の漏れを疑う。
# 同じなら単に設計が重い（語幅を広げた、段数が増えた）。
foreach {kind label} {setup "setup（周期）" hold "hold（保持）"} {
    puts ""
    puts "---- 一番きつい経路 上位 5  $label ----"
    set n 0
    foreach pth [get_timing_paths -quiet -max_paths 5 -nworst 1 -$kind] {
        set sc [get_property STARTPOINT_CLOCK $pth]
        set ec [get_property ENDPOINT_CLOCK $pth]
        puts [format "  slack %9.3f  %-30s → %-30s%s" \
              [get_property SLACK $pth] $sc $ec \
              [expr {$sc eq $ec ? "" : "   ← 乗り換え"}]]
        incr n
    }
    if {$n == 0} { puts "  （経路なし）" }
}

# ---- proj023 3b: 負の setup 経路の塊（始点 → 終点のセルの階層）----
# 1 回目のビルドは 2,251 本が負だったが、診断は最悪 5 本しか出さず、配置後の dcp を開き直す worst_paths は Vivado が落ちた。
# **開いている設計のまま**、負の経路を始点・終点の階層（コアの番号と添字を * に）で束ねて数える
if {[get_property STATS.WNS [get_runs impl_1]] < 0} {
    proc hier_key {pin} {
        set parts [split [string trimleft $pin /] /]
        set h [join [lrange $parts 0 end-2] /]
        regsub -all {s45_core_\d+} $h {s45_core_*} h
        regsub -all {\[\d+\]} $h {[*]} h
        return $h
    }
    set grp [dict create]
    set nneg 0
    foreach pth [get_timing_paths -quiet -max_paths 5000 -nworst 1 -setup -slack_lesser_than 0] {
        incr nneg
        set k "[hier_key [get_property STARTPOINT_PIN $pth]] → [hier_key [get_property ENDPOINT_PIN $pth]]"
        set sl [get_property SLACK $pth]
        if {[dict exists $grp $k]} {
            lassign [dict get $grp $k] n w
            dict set grp $k [list [expr {$n + 1}] [expr {min($w, $sl)}]]
        } else { dict set grp $k [list 1 $sl] }
    }
    puts ""
    puts "---- 負の setup 経路の塊（$nneg 本、上限 5000。始点 → 終点の階層、本数の多い順に 20）----"
    set rows {}
    dict for {k v} $grp { lappend rows [list $k {*}$v] }
    set fh [open $outdir/neg_paths_groups.rpt w]
    set i 0
    foreach r [lsort -integer -decreasing -index 1 $rows] {
        lassign $r k n w
        set line [format "  %5d 本  最悪 %7.3f  %s" $n $w $k]
        puts $fh $line
        if {[incr i] <= 20} { puts $line }
    }
    close $fh
    puts "  全部: $outdir/neg_paths_groups.rpt（[dict size $grp] 塊）"
    report_timing -max_paths 20 -nworst 1 -slack_lesser_than 0 -file $outdir/neg_paths_top20.rpt
}

# ---- 宣言していないクロックに経路が残っていないか ----
# timing.xdc が非同期と宣言しているのは clk_pl_0 / RFADC2_CLK 系 / clk_out2 の 3 群だけ。
# proj006 以降 **clk_adc0 をどこにも繋いでいない**ので、RFADC0_CLK には
# ファブリックの経路が無いはずである。使っていないタイル / DAC の
# ダミークロックも同じ。**前提を数えて確かめる。**
# ここに経路が出たら、timing.xdc にその群を足すか、配線を見直す。
# ---- 乗り換えの分類は Vivado 自身に出させる ----
#
# **自作の経路数えは偽陽性を出した**（2026-09-17）。
# `get_timing_paths -from <clock>` は **slack を持たない経路（= 解析対象外）も返す。**
# RFADC0/1/3 と RFDAC0..3 に 8 本ずつ出たので制約漏れかと思ったが、
# **timing.xdc で宣言済みの RFADC2_CLK も全く同じ 8 本を返した。**
# 終点はいずれも `rfdc/inst/IP2Bus_Data_reg[*]/D` — RFDC IP の内部で、
# タイルのステータスが AXI4-Lite の読み出しレジスタへ渡る経路であり、
# **IP が自前の制約で処理済み**である（だから slack が空）。
#
# **対照（宣言済みのクロック）を並べていたから偽陽性と分かった。**
# 片方しか見ない診断は、診断自体が嘘をつく。
#
# 以後は 2 段構えにする:
#   1. report_cdc — 乗り換えを Vivado が分類する専用コマンド。**これを正とする**
#   2. 自作の数えは **slack を持つ経路だけ**に絞る（対照も残す）
if {![catch {report_cdc -details -file $outdir/cdc.rpt} cdc_err]} {
    set fh [open $outdir/cdc.rpt r]; set txt [read $fh]; close $fh
    puts ""
    puts "---- 乗り換え（report_cdc）----"
    set shown 0
    foreach line [split $txt \n] {
        # 要約表は罫線なしの固定幅（2026-09-17 に | で拾おうとして空振りした）:
        #   CDC-1   Critical     26  1-bit unknown CDC circuitry
        if {[regexp {^\s*CDC-\d+\s+(Critical|Warning|Info)\s+\d+} $line]} {
            puts "  [string trim $line]"
            incr shown
        }
    }
    if {$shown == 0} { puts "  （要約表を拾えなかった。中身を直接見る）" }
    puts "  詳細: $outdir/cdc.rpt"
} else {
    puts ""
    puts "WARNING: report_cdc が使えない: $cdc_err"
}

puts ""
puts "---- タイルのクロックから出る経路（**解析対象のものだけ**）----"
puts "  対象外 = slack を持たない = IP の制約か clock group で既に除かれている"
foreach cn {RFADC0_CLK RFADC1_CLK RFADC2_CLK RFADC3_CLK \
            RFDAC0_CLK RFDAC1_CLK RFDAC2_CLK RFDAC3_CLK} {
    set c [get_clocks -quiet $cn]
    if {[llength $c] == 0} { continue }
    set mark [expr {$cn eq "RFADC2_CLK" ? " (宣言済み・対照)" : ""}]
    set timed 0
    set untimed 0
    set worst ""
    set worst_ec ""
    foreach pth [get_timing_paths -quiet -from $c -max_paths 40 -nworst 1 -setup] {
        set sl [get_property SLACK $pth]
        if {$sl eq ""} { incr untimed; continue }
        incr timed
        if {$worst eq "" || $sl < $worst} {
            set worst $sl
            set worst_ec [get_property ENDPOINT_CLOCK $pth]
        }
    }
    set detail ""
    if {$timed > 0} {
        set detail [format "  最悪 %+.3f → %s   **解析対象の経路がある。timing.xdc を見直す**" \
                    $worst $worst_ec]
    }
    puts [format "  %-12s%-18s 解析対象 %2d 本 / 対象外 %2d 本%s" \
          $cn $mark $timed $untimed $detail]
}

set wns [get_property STATS.WNS [get_runs impl_1]]

} diag_err]} {
    puts ""
    puts "WARNING: 診断の途中で失敗した（ビルドは続行する）: $diag_err"
}

# 診断が途中で落ちても、WNS の判定だけは必ず行う
set wns [get_property STATS.WNS [get_runs impl_1]]
set whs [get_property STATS.WHS [get_runs impl_1]]
puts ""
puts "TIMING (確定): WNS = $wns ns / WHS = $whs ns"
if {$wns ne "" && $wns < 0} { set timing_failed 1 }

# ---- 成果物を build/ 直下へ。PYNQ は .bit と .hwh が同名同階層であることを要求する ----
set bit [lindex [glob -nocomplain $projdir/$proj.runs/impl_1/${bd_name}_wrapper.bit] 0]
if {$bit eq ""} { puts "ERROR: .bit が見つからない"; exit 1 }
file copy -force $bit $outdir/$proj.bit

set hwh [lindex [glob -nocomplain \
    $projdir/$proj.gen/sources_1/bd/$bd_name/hw_handoff/${bd_name}.hwh \
    $projdir/$proj.srcs/sources_1/bd/$bd_name/hw_handoff/${bd_name}.hwh] 0]
if {$hwh eq ""} { puts "ERROR: .hwh が見つからない"; exit 1 }
file copy -force $hwh $outdir/$proj.hwh

puts "=== wrote $outdir/$proj.bit ==="
puts "=== wrote $outdir/$proj.hwh ==="

# **タイミングが閉じていないビルドは失敗として扱う。**
if {[info exists timing_failed]} {
    puts ""
    puts "ERROR: タイミングが閉じていない。成果物は調査用に残したが実機に使わないこと。"
    puts "  上の「違反している経路」でクロック対を見る。"
    puts "  クロック対が違っていれば src/board/timing.xdc の非同期宣言の漏れ。"
    puts "  **XDC で if / foreach を使うと黙って無効になる**（Designutils 20-1307）"
    exit 1
}

if {!$has_preset} {
    puts ""
    puts "NOTE: これは PS にプリセットを当てていない検証ビルド（$part）。"
    puts "      このビットストリームは実機に使わない。見るのは上の TIMING の値だけ。make ps-preset で src/board/ps_preset.tcl を作る"
}

