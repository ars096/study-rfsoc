# SPDX-License-Identifier: BSD-3-Clause
# proj037 V — 2G-1-Fine の .bit（BIT_KIND 12、STAGE2 ＋ RAW）。README の V-1。
#   YATSUGATAKE 54ce5e3 の hw/bits/2g-1-fast/build.tcl（2G-1-Fast: ADC 4 本のギアボックス・axis_sel4 2 個・time_core と 1PPS・
#   s45_core_0・s45_ring_0・照合）を写し、study-rfsoc proj028 の build_f5.tcl（MIG・ct_wr・ct_rd・smc_ddr・clk_mon）を足した。変えたのは:
#   1. コア s45_core_0 = s2_s45_core（core_cmn ＋ s2_strm（STAGE2、s 0。荒い段・帳簿・fine_core）＋ raw_core（RAW、s 1））。
#      FULL の入力の選び s2_sel は s2_sel（sel = s45_core_0/s2_sel → s_axis_s2）
#   2. FFT IP は lane_fft_f（8192 点・bit 反転順・入力 15 bit・unscaled → 29 bit・realtime。proj028 と同じ）× 16（fine_core の中）。
#      ROM（fine_coef・fine_tw）の hex は src/fine/ を絶対パスで s45_core_0 の CONFIG に
#   3. corner turn はコアの外: s45_core_0/ct_y・ct_mark・ct_valid → ct_wr_0 → smc_ddr → ddr4_0（PL DDR4 4 GiB）← ct_rd_0 → s45_core_0/s_axis_ct。
#      UI クロックの側の rst_ui・clk_mon_0（較正と UI クロックの見張り、pl_clk0）・sys_clk_ddr4（G13）・ddr4_pl（proj028 と同じ）
#   4. smc_ctrl の M: rfdc・s45_core_0・time_core_0・s45_ring_0 に ct_wr_0・ct_rd_0・clk_mon_0 を足して 7
#   5. ID: BIT_KIND 12・BIT_REV 1・PROJ 0x0037_0100。制約は src/board/（timing.xdc・pps.xdc は YATSUGATAKE 54ce5e3 の hw/board の写し、ddr4.xdc・clk_mon.xdc は proj028）
#   6. 照合に足したもの: corner turn のネットの表（ct_nets、張る側と同じ表）・在ってはいけない相手（proj028）・番地（MIG を 0 +4G）・
#      MIG の設定の読み返し・DDR の足 5 本・clk_mon の同期器・自作のセルの OOC 16 個・ROM の BRAM（係数 4・ひねり係数 11.5、proj028）
# 2G-1-Fast の build.tcl の経緯の注（proj010〜proj033）は YATSUGATAKE の版にある。ここには写さない
#
set proj         proj037
# proj015: **既定の part を -1 に**（実機の .bit を -1 で配置配線する。チップの刻印が未確認で、遅い方で閉じたものだけを載せる）。
#   -1 のビルドは board_part を使わず、./src/board/ps_preset.tcl（make ps-preset で書き出したボードプリセットの PS の設定）を当てる。
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
# proj037 Y-4（診断の変種）: ADC1=1 で ADC_A の 1 本だけを立てる（ほかの ADC を立てると ADC_A の形が変わるかを見る）
if {[info exists ::env(ADC1)] && $::env(ADC1) eq "1"} {
    set chans     {{2 2}}
    set ch_labels {ADC_A}
    puts "ADC1       : ADC_A の 1 本だけ（proj037 Y-4 の診断の変種。実機の .bit に置き換えない）"
}
set adc_tiles  {0 2}
if {[llength $chans] == 1} { set adc_tiles {2} }    ;# proj037 Y-4（ADC1）: ADC_A のタイル 226 だけ
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

# ---- 細かい側（fine_core.v と sim/lane_fft_f_model.v と対。proj028）----
# 131072 点 = 16 レーン × 8192 点（固定長・bit 反転順）。荒い ch 1 本の細かい FFT。7/8 を残して 114,688 ch / 荒い ch・3,670,016 ch
set fft_mod     lane_fft_f ;# **名前は RTL（fine_chain.v）と sim/lane_fft_f_model.v と対**
set fft_lane_n  8192
set fft_order   bit_reversed_order
set fft_in_w    15        ;# IP の入力（fine_pfb の出口、15 bit の複素）
set fft_out_w   29        ;# unscaled の出力 = 15 + log2(8192) + 1。RTL は 32 bit の欄を読む
# STAGE2 の大きさ（s2_s45_core の既定と同じ値を明示して読み返す。sim は縮めて回した）
set s2_b_c      20971520  ;# 1 チャンクの荒いブロック（286.72 ms）
set s2_base     73400320  ;# BASE_BEATS = 3.5·B_C
set s2_rec_w    114688    ;# レコードの本体の語の数（語 7 の P = 8·REC_W = 917,504）
set raw_n_acc   143360    ;# RAW の N_ACC の既定（286.72 ms = 512 ビート × 143,360）
# ROM の中身（make gen-fine の生成物。src/fine/）: {CONFIG の名前 ファイル 行数 1 行の桁数}
set fine_hex [list \
    LO_FILE [file normalize ./src/fine/fine_coef_lo.hex] 2048 9 \
    HI_FILE [file normalize ./src/fine/fine_coef_hi.hex] 2048 9 \
    TA_FILE [file normalize ./src/fine/fine_tw_a.hex]    64 144 \
    TB_FILE [file normalize ./src/fine/fine_tw_b.hex]    128 144 ]
# 生成物の形を先に見る。古い・切れた hex をここで止める
foreach {par h nrow ncol} $fine_hex {
    if {![file exists $h]} { puts "ERROR: $h が無い"; exit 1 }
    set fh [open $h r]; set lines [split [string trim [read $fh]] "\n"]; close $fh
    set bad 0
    foreach l $lines { if {[string length $l] != $ncol || ![string is xdigit -strict $l]} { incr bad } }
    if {[llength $lines] != $nrow || $bad != 0} {
        puts "ERROR: $h の形が違う（[llength $lines] 行（期待 $nrow）、うち $ncol 桁の 16 進でない行 $bad）"
        exit 1
    }
}
set ncore 1               ;# コアは 1 個（s45_core_0）。ギアボックスの ch は nch（4）

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
puts "STAGE2    : 荒い 64 ch（8/7）× 細かい 131072 点（16 × $fft_lane_n）→ 3,670,016 ch・558 Hz / B_C $s2_b_c ブロック = BASE $s2_base ビート / REC_W $s2_rec_w"
foreach {par h nrow ncol} $fine_hex { puts "ROM       : $par = $h（$nrow 行 × $ncol 桁）" }

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
# -1 では board_part を使わず、./src/board/ps_preset.tcl の PS の設定を明示して当てる（proj015）
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
    puts "NOTE: board_part は使わない（part $part のまま）。PS には ./src/board/ps_preset.tcl を当てる"
} else {
    puts "NOTE: ./src/board/ps_preset.tcl が無い。PS にプリセットを当てない検証ビルド（実機に使わない）。make ps-preset で作る"
}

# コア（s2_s45_core）とその中身（proj037 U）。荒い段は coarse_stage を通さず s2_strm が coarse_pfb・cfft32・coarse_post を直に持つ
set rtl [list ./src/s2_s45_core.v ./src/s2_strm.v ./src/coarse_pfb.v ./src/cfft32.v ./src/coarse_post.v \
              ./src/fine/fine_core.v ./src/fine/fine_pfb.v ./src/fine/fine_coef.v ./src/fine/fine_tw.v ./src/fine/fine_chain.v \
              ./src/fine/fine_acc.v ./src/fine/fine_rdo.v ./src/fine/cmul.v ./src/fine/dft16f.v \
              ./src/common/core_cmn.v ./src/common/raw_core.v ./src/common/tp_core.v ./src/common/rec_arb.v ./src/common/adc_ev.v \
              ./src/ct_wr.v ./src/ct_buf.v ./src/ct_rd.v ./src/clk_mon.v \
              ./src/common/time_core.v ./src/common/s45_ring.v ./src/common/gb_adc.v ./src/common/gb_gate.v ./src/common/axis_sel4.v]
foreach f $rtl { if {![file exists $f]} { puts "ERROR: $f が無い"; exit 1 } }
add_files -norecurse [lmap f $rtl {file normalize $f}]
# ROM の中身（$readmemh）。プロジェクトにも載せておく（CONFIG には絶対パスを与える。上の g21_hex）
set hex_files [lmap {par h nrow ncol} $fine_hex {set h}]
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
        puts "ERROR: FFT IP のポートが fine_chain.v の前提と $ng 件合わない。entity $fft_mod にあるポート:"
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

# proj024: 入力の選びは 2 個（D-8・D-14）。s2_sel → s45_core_0/s_axis_s2（FULL の流れの SRC）、raw_sel → s45_core_0/s_axis_raw（RAW の流れの SRC）
foreach sname {s2_sel raw_sel} {
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
foreach {k want} [list CONFIG.BUILD_TAG $time_tag CONFIG.BIT_KIND 12 CONFIG.BIT_REV 1 CONFIG.PROJ [expr {0x00370100}]] {   ;# proj024: 2G-1
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

# リング（s45_ring_0）。入口はコアの数（1 本）、書き手 → PS の S_AXI_HP0_FPD
set rcore [create_bd_cell -type module -reference s45_ring s45_ring_0]
foreach {k want} [list CONFIG.NIN $ncore CONFIG.BIT_KIND 12 CONFIG.BIT_REV 1 CONFIG.PROJ [expr {0x00370100}]] {
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

# ---- コア s45_core_0（s2_s45_core）----
#   CORE_PORT = [3:0] ADC の番号（SMA のラベル）/ [11:8] タイル / [15:12] スライス（chans の 0 番 = ADC_A。VERSIONS.md の実測）
set gcore [create_bd_cell -type module -reference s2_s45_core s45_core_0]
set core_tag [expr {$build_tag_base | (1 << 22)}]
lassign [lindex $chans 0] cp_t cp_s
set core_port [expr {0 | ($cp_t << 8) | ($cp_s << 12)}]
set kv [list CONFIG.BUILD_TAG $core_tag CONFIG.GB_K_RST $gb_k_rst CONFIG.CORE_PORT $core_port \
             CONFIG.B_C $s2_b_c CONFIG.BASE_BEATS $s2_base CONFIG.REC_W $s2_rec_w CONFIG.RAW_N_ACC_DEFAULT $raw_n_acc \
             CONFIG.BIT_KIND 12 CONFIG.BIT_REV 1 CONFIG.PROJ [expr {0x00370100}]]
foreach {k want} $kv {
    set_property $k $want $gcore
    if {[get_property $k $gcore] != $want} { puts "ERROR: s45_core_0 の $k が [get_property $k $gcore]（要求 $want）"; exit 1 }
}
# ROM の中身の絶対パス。文字列の CONFIG に引用符が要るかは版で違いうるので、素のままと引用符つきを順に試し、読み返しで判定する（proj023 3b と同じ）。
# **生成されたラッパに .<PAR>("<絶対パス>") が書かれたかは generate_target の後で見る**（下の「ROM のラッパ」）
foreach {par h nrow ncol} $fine_hex {
    set got ""
    foreach v [list $h "\"$h\""] {
        if {[catch {set_property CONFIG.$par $v $gcore}]} continue
        set got [string trim [get_property CONFIG.$par $gcore] {"}]
        if {$got eq $h} break
    }
    if {$got ne $h} { puts "ERROR: s45_core_0 の $par が '$got'（要求 $h）"; exit 1 }
}
puts [format "s45_core_0（%s）: s2_s45_core / BUILD_TAG = 0x%08x / GB_K_RST = %d / CORE_PORT = 0x%04x / STAGE2（s 0）＋ RAW（s 1）" \
        [lindex $ch_labels 0] $core_tag $gb_k_rst $core_port]
set core_axi    [BI s45_core_0 [list "s_axi"  "S_AXI"]  "s45_core_0 の AXI4-Lite"]
set core_axis   [BI s45_core_0 [list "s_axis" "S_AXIS"] "s45_core_0 の AXI4-Stream 入力（コアの ADC）"]
set full_axis   [BI s45_core_0 [list "s_axis_s2" "S_AXIS_S2"] "s45_core_0 の STAGE2 の流れの入力"]
set raw_axis    [BI s45_core_0 [list "s_axis_raw" "S_AXIS_RAW"] "s45_core_0 の RAW の流れの入力"]
set rec_axis(0) [BI s45_core_0 [list "m_axis_rec" "M_AXIS_REC"] "s45_core_0 のレコードの出口"]
set ct_axis     [BI s45_core_0 [list "s_axis_ct" "S_AXIS_CT"] "s45_core_0 の細かい側の入口（ct_rd_0 から）"]

for {set i 0} {$i < $nch} {incr i} {
    # gb_bc_i: ch 0 は 3 本（M00 コア・M01 s2_sel・M02 raw_sel）、ch 1〜3 は 2 本（M00 s2_sel・M01 raw_sel）
    set nmi($i) [expr {$i == 0 ? 3 : 2}]
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
# proj024: ch 1〜3 のギアボックスの制御の定数（コアが無い ch。core_cmn と同じ値: hold 0・adj 0・k = GB_K_RST）
foreach {nm w v} [list gb_tie_hold 1 0 gb_tie_adj 2 0 gb_tie_k 6 $gb_k_rst] {
    set c [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant $nm]
    set_property -dict [list CONFIG.CONST_WIDTH $w CONFIG.CONST_VAL $v] $c
    if {[get_property CONFIG.CONST_WIDTH $c] != $w || [get_property CONFIG.CONST_VAL $c] != $v} { puts "ERROR: $nm の CONST_WIDTH・CONST_VAL が要求と違う"; exit 1 }
}

puts [format "gb_adc_*: DW = %d / gb_gate_*: DW = %d・CW = %d（axis_rd_data_count の幅）" \
        [expr {$spw_adc * 16}] [expr {$gb_mid * 16}] $rdc_w]

# ---- corner turn（ct_wr_0・ct_rd_0）・MIG（ddr4_0）・見張り（clk_mon_0）。proj028 build_f5.tcl と同じ設定 ----
set ctw [create_bd_cell -type module -reference ct_wr ct_wr_0]
set ctr [create_bd_cell -type module -reference ct_rd ct_rd_0]
set cm  [create_bd_cell -type module -reference clk_mon clk_mon_0]
set mig [create_bd_cell -type ip -vlnv xilinx.com:ip:ddr4 ddr4_0]
set mig_req {
    CONFIG.C0.DDR4_MemoryType         Components
    CONFIG.C0.DDR4_DataWidth          64
    CONFIG.C0.DDR4_MemoryPart         MT40A512M16HA-075E
    CONFIG.C0.DDR4_TimePeriod         833
    CONFIG.C0.DDR4_InputClockPeriod   4998
    CONFIG.C0.BANK_GROUP_WIDTH        1
    CONFIG.C0.DDR4_CasLatency         17
    CONFIG.C0.DDR4_CasWriteLatency    12
    CONFIG.System_Clock               No_Buffer
    CONFIG.C0.DDR4_DataMask           DM_NO_DBI
    CONFIG.C0.DDR4_Ecc                false
    CONFIG.C0.DDR4_AxiSelection       true
    CONFIG.C0.DDR4_AxiDataWidth       512
    CONFIG.C0.DDR4_AxiAddressWidth    32
}
set ng 0
foreach {k v} $mig_req { if {[catch {set_property $k $v $mig} m]} { incr ng; puts "  MIG: $k = $v を設定できない: $m" } }
foreach {k v} $mig_req { set got ""; catch {set got [get_property $k $mig]}; if {![string equal -nocase $got $v]} { incr ng; puts "  MIG 違う: $k = $got（要求 $v）" } }
puts "MIG        : 要求 [expr {[llength $mig_req] / 2}] 個のうち違う $ng 個（MT40A512M16HA-075E・4 GiB・AXI 512 bit）"
if {$ng > 0} { puts "ERROR: MIG の設定が要求どおりにならない"; exit 1 }
set p_sys [create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:diff_clock_rtl:1.0 sys_clk_ddr4]
set_property CONFIG.FREQ_HZ 200000000 $p_sys
set ibuf [create_bd_cell -type ip -vlnv xilinx.com:ip:util_ds_buf ibufds_ddr4]
set_property CONFIG.C_BUF_TYPE IBUFDS $ibuf
set bufg [create_bd_cell -type ip -vlnv xilinx.com:ip:util_ds_buf bufg_ddr4]
set_property CONFIG.C_BUF_TYPE BUFG $bufg
foreach {c want} {ibufds_ddr4 IBUFDS bufg_ddr4 BUFG} {
    if {[get_property CONFIG.C_BUF_TYPE [get_bd_cells $c]] ne $want} { puts "ERROR: $c の C_BUF_TYPE が要求と違う"; exit 1 }
}
connect_bd_intf_net $p_sys [get_bd_intf_pins ibufds_ddr4/CLK_IN_D]
set p_ddr [create_bd_intf_port -mode Master -vlnv xilinx.com:interface:ddr4_rtl:1.0 ddr4_pl]
connect_bd_intf_net [get_bd_intf_pins ddr4_0/C0_DDR4] $p_ddr
# rst_ui の dcm_locked は定数 1（proj028 S-2d: calib を待つのは ct_wr・ct_rd を動かす PS の側。clk_mon が calib を見せる）
set one [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant one_ui]
set_property -dict [list CONFIG.CONST_WIDTH 1 CONFIG.CONST_VAL 1] $one
set rst_ui [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_ui]
# smc_ddr: S00 = ct_wr_0、S01 = ct_rd_0（DSP）→ M00 = ddr4_0（UI クロック）
set smc_ddr [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_ddr]
set_property -dict [list CONFIG.NUM_SI 2 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 2] $smc_ddr
foreach {k w} {CONFIG.NUM_SI 2 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 2} {
    if {[get_property $k $smc_ddr] != $w} { puts "ERROR: smc_ddr の $k が [get_property $k $smc_ddr]（要求 $w）"; exit 1 }
}
set ctw_axi [BI ct_wr_0   [list "s_axi" "S_AXI"] "ct_wr_0 の AXI4-Lite"]
set ctr_axi [BI ct_rd_0   [list "s_axi" "S_AXI"] "ct_rd_0 の AXI4-Lite"]
set cm_axi  [BI clk_mon_0 [list "s_axi" "S_AXI"] "clk_mon_0 の AXI4-Lite"]
set ctw_m   [BI ct_wr_0   [list "m_axi" "M_AXI"] "ct_wr_0 の AXI4"]
set ctr_m   [BI ct_rd_0   [list "m_axi" "M_AXI"] "ct_rd_0 の AXI4"]
set ctr_out [BI ct_rd_0   [list "m_axis" "M_AXIS"] "ct_rd_0 の出口"]

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
# M00 = RFDC、M01 = s45_core_0、M02 = time_core_0、M03 = s45_ring_0（proj024: コア 1 個）、M04 = ct_wr_0・M05 = ct_rd_0・M06 = clk_mon_0（proj037）
set smc_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_ctrl]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI [expr {1 + $ncore + 2 + 3}] CONFIG.NUM_CLKS {2}] $smc_ctrl
if {[get_property CONFIG.NUM_MI $smc_ctrl] != 1 + $ncore + 2 + 3} {
    puts "ERROR: smc_ctrl の NUM_MI が [get_property CONFIG.NUM_MI $smc_ctrl]（要求 [expr {1 + $ncore + 2 + 3}]: RFDC ＋ s45_core_0 ＋ time_core_0 ＋ s45_ring_0 ＋ ct_wr_0 ＋ ct_rd_0 ＋ clk_mon_0）"
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
set dsp_shared [list s45_core_0/aclk s2_sel/aclk raw_sel/aclk time_core_0/aclk s45_ring_0/aclk zynq_ultra_ps_e_0/saxihp0_fpd_aclk]
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
# ギアボックスの制御: ch 0 は s45_core_0（core_cmn）、ch 1〜3 は定数 gb_tie_* と rst_dsp（proj024。コアが無い ch）
#   書き込み側（gb_up / gb_fifo）: gb_adc が rst_adc と gb_hold（0）から作る gb_rstn
#   読み出し側（gb_gate / gb_dn）: ch 0 は s45_core_0 の gb_dn_rstn、ch 1〜3 は rst_dsp
#   gb_gate の見張りは s2_sel・raw_sel の i 番の入口へ（ch 0 は s45_core_0 にも）
# **ch ごとの結線はこの表 1 つから張り、下の照合も同じ表を読む**（張る側と照かめる側が別の表だと、両方が同じ誤りを持てない）
proc ch_nets {i} {
    if {$i == 0} {
        return [list \
            rst_dsp/peripheral_aresetn     [list gb_bc_0/aresetn] \
            gb_adc_0/gb_rstn               [list gb_up_0/aresetn gb_fifo_0/s_axis_aresetn] \
            s45_core_0/gb_dn_rstn          [list gb_gate_0/aresetn gb_dn_0/aresetn] \
            s45_core_0/gb_hold             gb_adc_0/hold \
            s45_core_0/gb_adj              gb_adc_0/adj \
            s45_core_0/gb_k                gb_gate_0/k \
            gb_fifo_0/axis_rd_data_count   gb_gate_0/rd_count \
            gb_gate_0/gb_stat              [list s45_core_0/gb_stat s2_sel/gb_stat0 raw_sel/gb_stat0] \
            gb_adc_0/adc_out               gb_gate_0/adc_in \
            gb_gate_0/adc_stat             [list s45_core_0/adc_stat s2_sel/adc_stat0 raw_sel/adc_stat0] \
        ]
    }
    return [list \
        rst_dsp/peripheral_aresetn     [list gb_bc_$i/aresetn gb_gate_$i/aresetn gb_dn_$i/aresetn] \
        gb_adc_$i/gb_rstn              [list gb_up_$i/aresetn gb_fifo_$i/s_axis_aresetn] \
        gb_tie_hold/dout               gb_adc_$i/hold \
        gb_tie_adj/dout                gb_adc_$i/adj \
        gb_tie_k/dout                  gb_gate_$i/k \
        gb_fifo_$i/axis_rd_data_count  gb_gate_$i/rd_count \
        gb_gate_$i/gb_stat             [list s2_sel/gb_stat$i raw_sel/gb_stat$i] \
        gb_adc_$i/adc_out              gb_gate_$i/adc_in \
        gb_gate_$i/adc_stat            [list s2_sel/adc_stat$i raw_sel/adc_stat$i] \
    ]
}
# 共有の駆動元（全 ch が載るのが正しいネット）。照合で「他の ch」を見ない
proc shared_drv {d} { return [expr {[string match rst_* $d] || [string match gb_tie_* $d]}] }
for {set i 0} {$i < $nch} {incr i} {
    foreach {drv loads} [ch_nets $i] { foreach p $loads { nc $drv $p } }
}
proc lseq {n} { set r {}; for {set i 0} {$i < $n} {incr i} { lappend r $i }; return $r }
# 共有のネット（入力の選び・時刻・リング）
proc shared_nets {} {
    return [list \
        rst_dsp/peripheral_aresetn     [list s45_core_0/aresetn s2_sel/aresetn raw_sel/aresetn time_core_0/aresetn s45_ring_0/aresetn] \
        s45_core_0/s2_sel            s2_sel/sel \
        s45_core_0/raw_sel             raw_sel/sel \
        rst_ctrl/peripheral_aresetn    time_core_0/ctrl_aresetn \
        time_core_0/t_out              s45_core_0/t_in \
        time_core_0/go_out             s45_core_0/go_in \
        time_core_0/ev_out             s45_core_0/tev_in \
        s45_core_0/rec_drop            s45_ring_0/rec_drop0 \
    ]
}
foreach {drv loads} [shared_nets] { foreach p $loads { nc $drv $p } }
# proj037: corner turn・MIG・clk_mon（proj028 build_f5.tcl の nets_f5 のうち、この形に残るもの）
proc ct_nets {} {
    return [list \
        zynq_ultra_ps_e_0/pl_clk0      [list clk_mon_0/clk] \
        clk_wiz_adc/clk_out2           [list smc_ddr/aclk ct_wr_0/clk ct_rd_0/clk] \
        ddr4_0/c0_ddr4_ui_clk          [list rst_ui/slowest_sync_clk smc_ddr/aclk1 clk_mon_0/ui_clk] \
        rst_ctrl/peripheral_aresetn    [list clk_mon_0/aresetn] \
        rst_ctrl/peripheral_reset      [list ddr4_0/sys_rst] \
        rst_dsp/peripheral_aresetn     [list ct_wr_0/aresetn ct_rd_0/aresetn] \
        rst_dsp/interconnect_aresetn   [list smc_ddr/aresetn] \
        ddr4_0/c0_ddr4_ui_clk_sync_rst [list rst_ui/ext_reset_in clk_mon_0/ui_rst] \
        one_ui/dout                    [list rst_ui/dcm_locked] \
        rst_ui/peripheral_aresetn      [list ddr4_0/c0_ddr4_aresetn] \
        ibufds_ddr4/IBUF_OUT           [list bufg_ddr4/BUFG_I] \
        bufg_ddr4/BUFG_O               [list ddr4_0/c0_sys_clk_i clk_mon_0/ref_clk] \
        ddr4_0/c0_init_calib_complete  [list clk_mon_0/calib] \
        s45_core_0/ct_valid            [list ct_wr_0/s_valid] \
        s45_core_0/ct_y                [list ct_wr_0/s_y] \
        s45_core_0/ct_mark             [list ct_wr_0/s_mark] \
        ct_wr_0/chunk_done             [list ct_rd_0/chunk_done] \
        ct_wr_0/chunk_idx              [list ct_rd_0/chunk_idx] \
    ]
}
foreach {drv loads} [ct_nets] { foreach p $loads { nc $drv $p } }

# ---- データ経路: RFDC → ギアボックス → gb_bc_i →（ch 0 だけ s45_core_0）・s2_sel・raw_sel ----
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
    if {$i == 0} {
        lappend ch_intf($i) [get_bd_intf_pins gb_bc_0/M00_AXIS] $core_axis \
                            [get_bd_intf_pins gb_bc_0/M01_AXIS] $sel_axis(s2_sel,0) \
                            [get_bd_intf_pins gb_bc_0/M02_AXIS] $sel_axis(raw_sel,0) \
                            [get_bd_intf_pins smc_ctrl/M01_AXI] $core_axi
    } else {
        lappend ch_intf($i) [get_bd_intf_pins gb_bc_$i/M00_AXIS] $sel_axis(s2_sel,$i) \
                            [get_bd_intf_pins gb_bc_$i/M01_AXIS] $sel_axis(raw_sel,$i)
    }
    foreach {a b} $ch_intf($i) { ic $a $b }
    puts [format "  %s = Tile %d slice %d -> gb_adc_%d / gb_up_%d / gb_fifo_%d / gb_gate_%d / gb_dn_%d -> gb_bc_%d -> {%ss2_sel/s%d, raw_sel/s%d}" \
            [lindex $ch_labels $i] [expr {224 + $t}] $s $i $i $i $i $i $i [expr {$i == 0 ? "s45_core_0（smc M01）, " : ""}] $i $i]
    incr i
}

# 制御系 AXI: PS → SmartConnect → RFDC（M00）/ s45_core_0（M01。上の ch_intf で張った）/ time_core_0（M02）/ s45_ring_0（M03）
ic [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_FPD] [get_bd_intf_pins smc_ctrl/S00_AXI]
ic [get_bd_intf_pins smc_ctrl/M00_AXI] [get_bd_intf_pins rfdc/s_axi]
set sh_intf [list $sel_m(s2_sel) $full_axis \
                 $sel_m(raw_sel) $raw_axis \
                 [get_bd_intf_pins smc_ctrl/M[format %02d [expr {1 + $ncore}]]_AXI] $time_axi \
                 [get_bd_intf_pins smc_ctrl/M[format %02d [expr {2 + $ncore}]]_AXI] $ring_axi \
                 $ring_m $hp0 \
                 $rec_axis(0) $ring_in(0) \
                 [get_bd_intf_pins smc_ctrl/M[format %02d [expr {3 + $ncore}]]_AXI] $ctw_axi \
                 [get_bd_intf_pins smc_ctrl/M[format %02d [expr {4 + $ncore}]]_AXI] $ctr_axi \
                 [get_bd_intf_pins smc_ctrl/M[format %02d [expr {5 + $ncore}]]_AXI] $cm_axi \
                 $ctw_m [get_bd_intf_pins smc_ddr/S00_AXI] \
                 $ctr_m [get_bd_intf_pins smc_ddr/S01_AXI] \
                 [get_bd_intf_pins smc_ddr/M00_AXI] [get_bd_intf_pins ddr4_0/C0_DDR4_S_AXI] \
                 $ctr_out $ct_axis]
foreach {a b} $sh_intf { ic $a $b }
puts "  s45_core_0/ct_* -> ct_wr_0 -> smc_ddr -> ddr4_0 <- ct_rd_0 -> s45_core_0/s_axis_ct / ct_wr_0・ct_rd_0・clk_mon_0 は smc_ctrl の M04〜M06"
puts "  s2_sel（STAGE2 の SRC）-> s45_core_0/s_axis_s2 / raw_sel（RAW の SRC）-> s45_core_0/s_axis_raw"
puts [format "  time_core_0（smc M%02d）/ s45_core_0/m_axis_rec -> s45_ring_0/s0_axis（smc M%02d）-> zynq_ultra_ps_e_0/S_AXI_HP0_FPD" [expr {1 + $ncore}] [expr {2 + $ncore}]]

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
# proj037: corner turn・MIG・clk_mon の表（張る側と同じ ct_nets）
foreach {drv loads} [ct_nets] {
    set probs [net_check 0 pin $drv $loads 1]
    set tag [expr {[llength $probs] ? "NG" : "OK"}]
    lappend nc_log [format "ct * %-3s pin  %s -> %s" $tag [norm_pin $drv] $loads]
    foreach pr $probs { lappend nc_log "        $pr"; incr nc_ng }
}
# proj037: 在ってはいけない相手（proj028 build_f5.tcl。ドメインとリセットの取り違え）
foreach {pin mustnot} {
    ct_wr_0/clk          {ddr4_0/c0_ddr4_ui_clk zynq_ultra_ps_e_0/pl_clk0 clk_wiz_adc/clk_out1}
    ct_rd_0/clk          {ddr4_0/c0_ddr4_ui_clk zynq_ultra_ps_e_0/pl_clk0 clk_wiz_adc/clk_out1}
    s45_core_0/aclk      {ddr4_0/c0_ddr4_ui_clk clk_wiz_adc/clk_out1 zynq_ultra_ps_e_0/pl_clk0}
    smc_ddr/aclk1        {clk_wiz_adc/clk_out2 zynq_ultra_ps_e_0/pl_clk0}
    ct_wr_0/aresetn      {rst_ui/peripheral_aresetn rst_ctrl/peripheral_aresetn}
    ct_rd_0/aresetn      {rst_ui/peripheral_aresetn rst_ctrl/peripheral_aresetn}
    rst_ui/dcm_locked    {ddr4_0/c0_init_calib_complete}
    clk_mon_0/clk        {ddr4_0/c0_ddr4_ui_clk clk_wiz_adc/clk_out2}
} {
    set peers [peer_names [get_bd_pins -quiet $pin] pin]
    set bad {}
    foreach m $mustnot { if {[lsearch -exact $peers $m] >= 0} { lappend bad $m } }
    set tag [expr {[llength $peers] >= 2 && [llength $bad] == 0 ? "OK" : "NG"}]
    lappend nc_log [format "ct * %-3s %s のネットに %s が無い（ネットの上 %d 本）" $tag $pin $mustnot [llength $peers]]
    if {$tag eq "NG"} { lappend nc_log "        在ってはいけない: $bad"; incr nc_ng }
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
# proj024: **在ってはいけない側**。コアは s45_core_0 の 1 個だけ・Wide の部品（共有の ROM・spec_core）のセルが無い・中身が s2_s45_core
foreach pat {s45_core_[1-9]* spec_core_* wide_coef_rom_* wide_tw_rom_* full_tie_*} {
    set cs [get_bd_cells -quiet $pat]
    set tag [expr {[llength $cs] == 0 ? "OK" : "NG"}]
    lappend nc_log [format "ch * %-3s セル %s が無い（在るのは: %s）" $tag $pat $cs]
    if {$tag eq "NG"} { incr nc_ng }
}
set v [get_property VLNV [get_bd_cells s45_core_0]]
set tag [expr {[string match "*:module_ref:s2_s45_core:*" $v] ? "OK" : "NG"}]
lappend nc_log [format "ch 0 %-3s s45_core_0 の中身 = %s（期待 s2_s45_core）" $tag $v]
if {$tag eq "NG"} { incr nc_ng }
# proj024: ch 1〜3 のギアボックスの制御はどれも s45_core_0 の gb_* の出口から来ていない（在ってはいけない側。上の ch_nets の (2) でも見ているが、名指しで）
#   **ネットの上に s45_core_0 が居ないこと、ではない**: rst_dsp のネットには s45_core_0/aresetn も正しく載る（2026-10-18 の 1 回目のビルドはこれで止めた）。
#   見るのはコアのギアボックスの制御の出口 4 本（gb_hold・gb_adj・gb_k・gb_dn_rstn）だけ
set core_gb_out {s45_core_0/gb_hold s45_core_0/gb_adj s45_core_0/gb_k s45_core_0/gb_dn_rstn}
proc from_core_gb {p} {
    set peers [peer_names [get_bd_pins -quiet $p] pin]
    set bad {}
    foreach q $::core_gb_out { if {[lsearch -exact $peers $q] >= 0} { lappend bad $q } }
    return [list $peers $bad]
}
for {set i 1} {$i < $nch} {incr i} {
    foreach p [list gb_adc_$i/hold gb_adc_$i/adj gb_gate_$i/k gb_gate_$i/aresetn gb_dn_$i/aresetn] {
        lassign [from_core_gb $p] peers bad
        set tag [expr {[llength $peers] > 0 && [llength $bad] == 0 ? "OK" : "NG"}]
        lappend nc_log [format "ch %d %-3s %s はコアの gb_* の出口に繋がっていない（%s）" $i $tag $p [expr {[llength $bad] ? "繋がっている: $bad" : "ネットの上 [llength $peers] 本"}]]
        if {$tag eq "NG"} { incr nc_ng }
    }
}
# rev2: タイルのリセットが別のネット（別のフロップ）であること。**在ってはいけない側**
proc pin_unconnected {p} { return [expr {[llength [get_bd_pins -quiet $p]] == 1 && [llength [get_bd_nets -quiet -of_objects [get_bd_pins -quiet $p]]] == 0}] }
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
if {$nch >= 2} {
    set pa [net_check 0 pin s45_core_0/gb_hold [list gb_adc_1/hold] 0]
    set pb [net_check 1 pin s45_core_0/gb_hold [list gb_adc_0/hold] 0]
    if {[llength $pa] == 0} { set pc_ok 0; lappend nc_log "陽性対照 (a) が通ってしまった（在るべき相手の照合が壊れている）" }
    if {[llength $pb] == 0} { set pc_ok 0; lappend nc_log "陽性対照 (b) が通ってしまった（他の ch の照合が壊れている）" }
    lappend nc_log "陽性対照: (a) [llength $pa] 件・(b) [llength $pb] 件で落ちた（どちらも 1 件以上が期待）"
} else {
    lappend nc_log "陽性対照: (a)(b) は ch 1 を名指しするので省いた（ADC1 の変種、ch 1 本）"
}
# (c)(d) 時刻のネット / (h) 入力の選びの取り違え（s2_sel の sel に raw_sel を期待する）。どれも落ちるべき
set pcc [net_check 0 pin time_core_0/t_out  [list s45_core_0/go_in] 1]
set pcd [net_check 0 pin time_core_0/go_out [list s45_core_0/t_in] 1]
set pch [net_check 0 pin s45_core_0/s2_sel [list raw_sel/sel] 1]
foreach {nm r} [list c $pcc d $pcd h $pch] {
    if {[llength $r] == 0} { set pc_ok 0; lappend nc_log "陽性対照 ($nm) が通ってしまった（共有のネットの照合が壊れている）" }
}
lappend nc_log "陽性対照: (c) [llength $pcc] 件・(d) [llength $pcd] 件・(h) [llength $pch] 件で落ちた（どれも 1 件以上が期待）"
# (e)(f): 「つながっていない」の照合が、つながっているピン・無いピンに「つながっていない」と言わないこと
set pce [pin_unconnected s45_core_0/s2_sel]
set pcf [pin_unconnected s45_core_0/no_such_pin]
if {$pce} { set pc_ok 0; lappend nc_log "陽性対照 (e) が通ってしまった（つながっているピンを「つながっていない」と言った）" }
if {$pcf} { set pc_ok 0; lappend nc_log "陽性対照 (f) が通ってしまった（無いピンを「つながっていない」と言った）" }
lappend nc_log "陽性対照: (e) [expr {$pce ? "通った（NG）" : "落ちた"}]・(f) [expr {$pcf ? "通った（NG）" : "落ちた"}]（どちらも落ちるのが期待）"
set pcj [net_check 0 pin ct_wr_0/clk [list rst_ui/slowest_sync_clk] 1]
set pck [expr {[lsearch -exact [peer_names [get_bd_pins -quiet ct_wr_0/clk] pin] clk_wiz_adc/clk_out2] >= 0}]
if {[llength $pcj] == 0} { set pc_ok 0; lappend nc_log "陽性対照 (j) が通ってしまった（corner turn の表の照合が壊れている）" }
if {!$pck} { set pc_ok 0; lappend nc_log "陽性対照 (k) が落ちた（ct_wr_0/clk のネットに clk_out2 が見えない: 在ってはいけない側の読みが壊れている）" }
lappend nc_log "陽性対照: (j) [llength $pcj] 件で落ちた（1 件以上が期待）・(k) ct_wr_0/clk の相手に clk_out2 が [expr {$pck ? "見えた" : "見えない（NG）"}]"
# (g) ch 1 のネットを ch 2 として照らす（gb_tie_* を共有と扱わない形で: (2) が gb_adc_1 を「他の ch」と言うべき）
if {$nch >= 3} {
    set pcg [lsearch -all -inline [net_check 2 pin gb_adc_1/gb_rstn [list gb_up_1/aresetn] 0] "*ch 1 のピン*"]
    if {[llength $pcg] == 0} { set pc_ok 0; lappend nc_log "陽性対照 (g) が通ってしまった（ch の照合が壊れている）" }
    lappend nc_log "陽性対照: (g) [llength $pcg] 件で落ちた（1 件以上が期待）"
} else {
    lappend nc_log "陽性対照: (g) は ch 1・2 を名指しするので省いた（ADC1 の変種）"
}
# (i) 上の「コアの gb_* の出口に繋がっていない」を ch 0 に当てる（ch 0 はコアが握るので、繋がっていると言うべき）
set pci 0
foreach p {gb_adc_0/hold gb_gate_0/k gb_gate_0/aresetn} { lassign [from_core_gb $p] peers bad; if {[llength $bad] > 0} { incr pci } }
if {$pci != 3} { set pc_ok 0; lappend nc_log "陽性対照 (i) が通ってしまった（ch 0 の 3 本のうち $pci 本しかコアの gb_* に繋がっていると言わない）" }
lappend nc_log "陽性対照: (i) ch 0 の 3 本のうち $pci 本で「コアの gb_* に繋がっている」と言った（3 が期待）"
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
# proj037: ct_wr_0・ct_rd_0・clk_mon_0 のレジスタ（4 KiB）。corner turn の書き手と読み手は MIG の 4 GiB を 0 から見る
set k 95
foreach cell {ct_wr_0 ct_rd_0 clk_mon_0} {
    set cseg ""
    foreach seg [get_bd_addr_segs -quiet] { if {[string match "*SEG_${cell}*" $seg]} { set cseg $seg } }
    if {$cseg eq ""} { puts "ERROR: $cell のアドレスセグメントが見つからない"; exit 1 }
    if {[get_property RANGE $cseg] < 4096} { set_property RANGE 4096 $cseg }
    puts [format "CT ADDR    : %-10s %s +%s（%s）" $cell [get_property OFFSET $cseg] [get_property RANGE $cseg] $cseg]
    lappend wins [list $k [expr {[get_property OFFSET $cseg]}] [expr {[get_property RANGE $cseg]}]]
    incr k
}
foreach sp {ct_wr_0/m_axi ct_rd_0/m_axi} {
    set segs [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces $sp]]
    if {[llength $segs] != 1 || [get_property OFFSET $segs] != 0 || [get_property RANGE $segs] != 4294967296} {
        puts "ERROR: $sp から MIG が 0 +4G で見えない（$segs）"; exit 1
    }
    puts [format "CT DMA     : %s %s +%s" $segs [get_property OFFSET $segs] [get_property RANGE $segs]]
}
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
            puts "ERROR: 窓 $i1 と $i2 が重なっている（10 + i = s45_core_i、99 = time_core_0、98 = s45_ring_0、95〜97 = ct_wr_0・ct_rd_0・clk_mon_0）"
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
add_files -fileset constrs_1 -norecurse [list ./src/board/ddr4.xdc ./src/board/clk_mon.xdc]   ;# proj028: PL DDR4 の足・clk_mon の false path
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
set vs {}
catch {set vs [split [exec find $projdir -path "*${bd_name}_s45_core_0_0*" -name "*.v"] "\n"]}
foreach {par hex nrow ncol} $fine_hex {
    set hit ""
    foreach f $vs {
        set fh [open $f r]; set t [read $fh]; close $fh
        set hre [regsub -all {[][{}()*+?.\\^$|]} $hex {\\&}]
        if {[regexp "\\.${par}\\s*\\(\\s*\"$hre\"\\s*\\)" $t]} { set hit $f; break }
    }
    if {$hit eq ""} {
        puts "ERROR: s45_core_0 のラッパに .${par}(\"$hex\") が無い。探したファイル:"
        foreach f $vs { puts "  $f" }
        exit 1
    }
    puts "ROM のラッパ: s45_core_0 .$par = \"$hex\"（[file tail $hit]）"
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
# proj023 3b: $readmemh が読めないと ROM が 0 になり、BRAM が消えるだけで合成は通る。**OOC のログで先に止める**（ROM は s45_core_0 の中）
set rm_ng 0
set rm_seen 0
set rm_ok 0
foreach n $ooc_names {
    if {![string match "*s45_core_0*" $n]} continue
    incr rm_seen
    set lf [file join [ooc_dir $n] runme.log]
    set fh [open $lf r]; set t [read $fh]; close $fh
    foreach line [split $t "\n"] {
        if {[regexp -nocase {Synth 8-4445|could not open .*readmem|readmem.*(not found|cannot|could not)} $line]} { puts "  $n: $line"; incr rm_ng }
        foreach {par h nrow ncol} $fine_hex {
            if {[string first [file tail $h] $line] >= 0 && [regexp -nocase {read successfully} $line]} { incr rm_ok }
        }
    }
}
puts "ROM の中身 : s45_core_0 の OOC の run $rm_seen 個のログに \$readmemh の失敗 $rm_ng 行・読めた印 $rm_ok 行（印が無くても止めない。配置後の BRAM の数で止める）"
# proj023 4a: **ドライバの無いネット（Synth 8-3848）で止める**。自作のセル（module reference）の run だけを見る
set nd_ng 0
set nd_seen 0
foreach n $ooc_names {
    if {![regexp {^system_(s45_core|time_core|s45_ring|gb_adc|gb_gate|s2_sel|raw_sel|ct_wr|ct_rd|clk_mon)_} $n]} continue
    incr nd_seen
    set lf [file join [ooc_dir $n] runme.log]
    if {![file exists $lf]} continue
    set fh [open $lf r]; set t [read $fh]; close $fh
    foreach line [split $t "\n"] {
        if {[string match "*Synth 8-3848*" $line]} { puts "  $n: $line"; incr nd_ng }
    }
}
puts "ドライバ   : 自作のセルの OOC の run $nd_seen 個のログに Synth 8-3848（ドライバの無いネット）$nd_ng 行"
# 期待: s45_core_0 1・time_core_0 1・s45_ring_0 1・gb_adc nch・gb_gate nch・s2_sel 1・raw_sel 1・ct_wr_0 1・ct_rd_0 1・clk_mon_0 1 = 8 ＋ 2·nch（4 本で 16）
set nd_want [expr {8 + 2 * $nch}]
if {$nd_seen != $nd_want} { puts "ERROR: 自作のセルの OOC の run が $nd_seen 個（期待 $nd_want。run の名前が変わった？ $ooc_names）"; exit 1 }
if {$nd_ng > 0} { puts "ERROR: ドライバの無いネットがある（RTL の書き漏れ）"; exit 1 }
if {$rm_seen != 1} { puts "ERROR: s45_core_0 の OOC の run が 1 個でない（$rm_seen）。run の名前: $ooc_names"; exit 1 }
if {$rm_ng > 0} { puts "ERROR: ROM の中身（hex）を合成が読めていない"; exit 1 }

# ---- YATSUGATAKE M5b: USR_ACCESS に commit を焼く（Makefile の USR_ACCESS）。write_bitstream の前のフックで設定するだけで、
#      配置・配線には触れない（RTL も変えない）。make が書き出した .bit を sw/pynq/bitinfo.py で読み返して照らす ----
# **expr で受けない**: expr の ? : は 0x… を数として読み、10 進の文字列にして返す（2026-10-15 の 1 回目で、下の形の照合が止めた）
set usr_access ""
if {[info exists ::env(USR_ACCESS)]} { set usr_access $::env(USR_ACCESS) }
if {$usr_access eq ""} { puts "ERROR: USR_ACCESS が来ていない（make から回す。焼かないなら USR_ACCESS=none）"; exit 1 }
if {[string tolower $usr_access] eq "none"} {
    puts "USR_ACCESS (焼く): なし（USR_ACCESS=none。比べのためのビルド）"
} else {
    if {![regexp {^0x[0-9a-fA-F]{8}$} $usr_access]} { puts "ERROR: USR_ACCESS $usr_access が 0x と 16 進 8 桁でない"; exit 1 }
    set hook [file normalize $outdir/usr_access_hook.tcl]
    set fh [open $hook w]
    puts $fh "set_property BITSTREAM.CONFIG.USR_ACCESS $usr_access \[current_design\]"
    puts $fh "puts \"USR_ACCESS: \[get_property BITSTREAM.CONFIG.USR_ACCESS \[current_design\]\]\""
    close $fh
    set_property STEPS.WRITE_BITSTREAM.TCL.PRE $hook [get_runs impl_1]
    if {[get_property STEPS.WRITE_BITSTREAM.TCL.PRE [get_runs impl_1]] ne $hook} {
        puts "ERROR: write_bitstream の前のフックが設定されていない"; exit 1
    }
    puts "USR_ACCESS (焼く): $usr_access（commit [string range $usr_access 2 8]・汚れ [string index $usr_access end]）"
}

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
        puts "ERROR: ポート $pname が存在しない（create_bd_port の名前と ./src/board/pps.xdc の get_ports を突き合わせる）"
        exit 1
    }
    set got [get_property PACKAGE_PIN $prt]
    set io  [get_property IOSTANDARD  $prt]
    puts [format "  %-10s %-6s %s" $pname $got $io]
    if {$got ne $want} { puts "ERROR: $pname の配置が $got。期待 $want（RefMan A6 / Appendix A）"; exit 1 }
}
# ---- proj037: PL DDR4 の足（proj028 S-2f と同じ 5 本）と clk_mon の同期器の false path の相手 ----
puts ""
puts "---- PL DDR4 の足 ----"
foreach {pname want} {sys_clk_ddr4_clk_p G13 ddr4_pl_act_n B14 {ddr4_pl_dq[0]} K17 ddr4_pl_reset_n E14 {ddr4_pl_adr[0]} B13} {
    set prt [get_ports -quiet $pname]
    if {[llength $prt] == 0} { puts "ERROR: ポート $pname が無い（ddr4.xdc と BD の外部ポートの名前を突き合わせる）"; exit 1 }
    set got [get_property PACKAGE_PIN $prt]
    puts [format "  %-20s %s" $pname $got]
    if {$got ne $want} { puts "ERROR: $pname の配置が $got（期待 $want）"; exit 1 }
}
set n_sync [llength [get_cells -quiet -hierarchical -filter {NAME =~ */clk_mon_0/inst/s_ref_reg[0] || NAME =~ */clk_mon_0/inst/s_ui_reg[0] || NAME =~ */clk_mon_0/inst/s_cal_reg[0] || NAME =~ */clk_mon_0/inst/s_rst_reg[0]}]]
puts "clk_mon の同期器の 1 段目: $n_sync 個（期待 4）"
if {$n_sync != 4} { puts "ERROR: clk_mon.xdc の false path の相手が 4 個でない"; exit 1 }
set nfft [llength [get_cells -quiet -hierarchical -filter "REF_NAME == $fft_mod || ORIG_REF_NAME == $fft_mod"]]
puts "$fft_mod: $nfft 個（期待 16）"
if {$nfft != 16} { puts "ERROR: $fft_mod が 16 個でない"; exit 1 }
# ---- proj024: ROM が BRAM として残っているか（合否。**中身が 0 なら ROM は消えて BRAM が 0 になる**）----
# 予言（proj028 F-1・F-2 の OOC と F-5 の実装）: 係数（fine_coef）RAMB36 4・ひねり係数（fine_tw）11.5
puts ""
puts "---- ROM の BRAM（s45_core_0 の中）----"
foreach {cell pred} {s45_core_0/inst/u_s2/u_fine/u_pfb/u_coef 4 s45_core_0/inst/u_s2/u_fine/u_tw 11.5} {
    set n36 0; set n18 0
    foreach x [get_cells -quiet -hierarchical -filter {REF_NAME =~ RAMB36*}] { if {[string first "/$cell/" "/$x"] >= 0} { incr n36 } }
    foreach x [get_cells -quiet -hierarchical -filter {REF_NAME =~ RAMB18*}] { if {[string first "/$cell/" "/$x"] >= 0} { incr n18 } }
    set eq [expr {$n36 + $n18 / 2.0}]
    puts [format "  %-44s RAMB36 %d・RAMB18 %d（RAMB36 換算 %.1f、予言 %s）" $cell $n36 $n18 $eq $pred]
    if {$eq < $pred / 2.0} { puts "ERROR: $cell の BRAM が予言の半分に届かない。ROM の中身（\$readmemh）が効いていないか、階層の名前が違う（utilization_hier.rpt）"; exit 1 }
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
    puts "  **非同期の宣言が見当たらない。./src/board/timing.xdc が効いていない可能性がある**"
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

# ---- lane_fft_g21 1 個ぶん・16 個の合計・段ごと（proj024）----
# **S-1（IP 単体の OOC 合成）の数字と突き合わせる**（1 個 DSP 33・BRAM 21.5）
set ffts [lsort [get_cells -quiet -hierarchical -filter "ORIG_REF_NAME == $fft_mod || REF_NAME == $fft_mod"]]
# **名前に [0] が入るので -filter の =~ は使わない**（glob の文字クラスとして読まれ、何にも当たらない）。名前を一度集め、先頭一致で数える
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
puts "---- FFT IP の資源（$fft_mod）----"
puts "  $fft_mod の個数         = [llength $ffts]（期待 16）"
if {[llength $ffts] > 0} {
    set c0 [lindex $ffts 0]
    report_utilization -cells $c0 -file $outdir/lane_fft_util.rpt
    puts "  DSP48E2 1 個あたり      = [count_under $dsp_names $c0]（$c0。proj028 F-1 の OOC）"
    foreach line [split [exec cat $outdir/lane_fft_util.rpt] \n] {
        if {[regexp {^\|\s*(CLB LUTs|CLB Registers|Block RAM Tile|URAM|DSPs)\s*\|} $line]} { puts "    [string trim $line]" }
    }
}
puts "  DSP48E2 $fft_mod 16 個の合計 = $dsp_fft"
puts "  DSP48E2 全体            = $dsp_all（proj037 V-2 の予言 ≒ 1,850）"
# 段ごと（階層の名前は s2_s45_core.v・g21_core.v・g21_spec.v・core_cmn.v のインスタンス名）
set ram_names [get_property NAME [get_cells -quiet -hierarchical -filter {REF_NAME =~ RAMB* || REF_NAME =~ URAM*}]]
foreach sub {u_s2/u_pfb u_s2/u_fft u_s2/u_post u_s2/u_fine/u_pfb u_s2/u_fine/g_lane u_s2/u_fine/u_tw u_s2/u_fine/u_chain u_s2/u_fine/u_acc u_s2/u_fine/u_rdo u_cmn/g_tp.u_tp u_raw} {
    puts [format "  s45_core_0/%-24s DSP48E2 %4d・RAMB/URAM のセル %4d" $sub [count_in $dsp_names "/s45_core_0/inst/$sub"] [count_in $ram_names "/s45_core_0/inst/$sub"]]
}
foreach {c f what} {s45_core_0/inst/u_raw raw_core_util.rpt "s45_core_0 の RAW（予言 RAMB36 8 前後）" \
                    s45_core_0/inst/u_s2/u_fine/u_acc acc_util.rpt "細かい側の積分器（proj028 F-5: URAM 44）" \
                    s45_core_0/inst/u_s2/u_fine/u_pfb pfb_util.rpt "細かい PFB（履歴 URAM 22 ＋ 係数 RAMB36 4）" \
                    s45_core_0/inst/u_s2/u_pfb cpfb_util.rpt "荒い PFB" \
                    ct_wr_0/inst ctwr_util.rpt "ct_wr（溜め）"} {
    set cc [get_cells -quiet $c]
    if {$cc eq ""} { set cc [get_cells -quiet -hierarchical -filter "NAME =~ *$c"] }
    if {$cc eq ""} { puts "  WARNING: $c のセルが見つからない（utilization_hier.rpt で見る）"; continue }
    report_utilization -cells [lindex $cc 0] -file $outdir/$f
    puts "  $what:"
    foreach line [split [exec cat $outdir/$f] \n] {
        if {[regexp {^\|\s*(CLB LUTs|CLB Registers|Block RAM Tile|URAM|DSPs)\s*\|} $line]} { puts "    [string trim $line]" }
    }
}
# 全体の LUT・FF・URAM・BRAM を utilization.rpt から。README の E-1（PFB あり・URAM 2 列 ＋ BRAM・積）: DSP 19.6 %・BRAM 57.8 %・URAM 70 %・LUT 23.9 %
if {![catch {set fh [open $outdir/utilization.rpt r]; set ut [read $fh]; close $fh}]} {
    foreach line [split $ut "\n"] {
        if {[regexp {^\|\s*(CLB LUTs|CLB Registers|URAM|Block RAM Tile|DSPs)\*?\s*\|} $line]} { puts "  全体: [string trim $line]" }
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
    puts "  クロック対が違っていれば ./src/board/timing.xdc の非同期宣言の漏れ。"
    puts "  **XDC で if / foreach を使うと黙って無効になる**（Designutils 20-1307）"
    exit 1
}

if {!$has_preset} {
    puts ""
    puts "NOTE: これは PS にプリセットを当てていない検証ビルド（$part）。"
    puts "      このビットストリームは実機に使わない。見るのは上の TIMING の値だけ。make ps-preset で ./src/board/ps_preset.tcl を作る"
}

