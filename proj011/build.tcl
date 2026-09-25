# SPDX-License-Identifier: BSD-3-Clause
# proj011 — proj010 の分光計（RFDC → ギアボックス → spec_core → AXI4-Lite → PS）の FFT IP を
#           **realtime・資源優先**に設定し直し、1ch のまま資源と速度グレード -1 の余裕を測り直す
#
# 出力:
#   build/proj011.bit      ビットストリーム（FFT_OPT=perf なら build-perf/）
#   build/proj011.hwh      ハードウェアハンドオフ（PYNQ が読む。.bit と同名にする）
#   build/rfdc_params.rpt  RFDC IP が実際に持つ CONFIG 一覧
#   build/xfft_params.rpt  FFT IP（lane_fft）が実際に持つ CONFIG 一覧
#   build/lane_fft_util.rpt  lane_fft 1 個ぶんの資源（g_lane[0]）。make survey の数字と突き合わせる
#
# ---- proj010 からの変更点（これ以外は proj010 と同一）----
#
#   1. **FFT IP の設定を src/fft_cfg.tcl に移し、FFT_OPT（res / perf）で選ぶ。**
#      tools/ip_survey.tcl（make survey）も同じファイルを読むので、IP 単体の調査と本番が同じ設定を数える
#   2. **throttle_scheme = realtime。**nonrealtime の CE（proj010 の -2 の最悪経路）を無くす。
#      realtime の IP には m_axis_data_tready が無い（PG109）ので、spec_core.v の接続も外した。
#      **ポートの照合で「在ってはいけない」側も見る**（在れば IP が realtime になっていない）
#   3. 乗算器・バタフライ・throttle の CONFIG を fatal にした（調べる対象なので黙って戻られると困る）
#   4. spec_core の ID の下位 8 bit に FFT の設定の符号を載せる（CONFIG.FFT_CFG）。
#      res と perf は同名の proj011.bit になるので、**PS から載っている変種を読めるようにする**
#   5. lane_fft 1 個ぶんの資源を別に出す（予言の突き合わせ用）
#   6. （rev4）spec_core にビルドの指紋 BUILD_TAG（プリセットの有無・速度グレード）を与える
#
# RFDC・Clocking Wizard・ギアボックス・spec_core の本体は proj010 と同一。
# ナイキストゾーン（2）は実行時に PYNQ から設定する（pynq/spectrometer.py）。

set proj         proj011
set part_default xczu48dr-ffvg1517-2-e
set part         $part_default
set bd_name      system
set outdir       ./build

if {[info exists ::env(PART)]   && $::env(PART)   ne ""} { set part   $::env(PART) }
if {[info exists ::env(OUTDIR)] && $::env(OUTDIR) ne ""} { set outdir ./$::env(OUTDIR) }
set fft_opt res
if {[info exists ::env(FFT_OPT)] && $::env(FFT_OPT) ne ""} { set fft_opt $::env(FFT_OPT) }
source ./src/fft_cfg.tcl
lassign [fft_opt_map $fft_opt] fft_throttle fft_cmul fft_bfly
set fft_code [fft_cfg_code $fft_throttle $fft_cmul $fft_bfly]

# ---- 設計パラメータ ----
# **SMA のラベル（ADC_A/B/C/D）との対応は VERSIONS.md が正。ラベルから推測しないこと。**
#   ADC_B = Tile 226 / slice 0 = {2 0}
set chans      {{2 0}}
set adc_tiles  {2}
set nch        [llength $chans]

set fs_gsps    4.096      ;# サンプリング周波数 [GSPS]
set refclk_mhz 491.520    ;# LMX2594 → RFDC タイル
# 1 語あたりのサンプル数（proj009 で確定）
#   spw_adc: RFDC の出力。12 → 341.333 MHz（ADC ドメイン。ギアボックスの入口だけ）
#   spw    : ギアボックスの後。16 → 256 MHz（DSP ドメイン。spec_core はここ）
set spw_adc    12
set spw        16
set beat_bits  [expr {$nch * $spw * 16}]   ;# 256 bit
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

# ---- 分光計（spec_core.v と対）----
# 8192 点 = 16 レーン × 512 点。出力 4096 ch・0.5 MHz、1 フレーム 2.000 µs
set fft_lane_n  512
set fft_in_w    14        ;# IP の入力（ADC の有効 14 bit）
set fft_out_w   24        ;# unscaled の出力 = 14 + log2(512) + 1。**spec_core.v の YW と一致すること**
set spec_range  65536     ;# spec_core の AXI4-Lite の窓（16 bit 番地）

puts "PART      : $part"
puts "OUTDIR    : $outdir"
puts "FFT_OPT   : $fft_opt（$fft_throttle / $fft_cmul / $fft_bfly、符号 [format 0x%02x $fft_code]）"
foreach ch $chans {
    lassign $ch t s
    puts "ADC       : Tile [expr {224 + $t}] / slice $s"
}
puts "fs        : $fs_mhz MSPS （RFDC $fabric_mhz MHz × $spw_adc → DSP $dsp_mhz MHz × $spw sample/word）"
puts "GEARBOX   : $spw_adc → $gb_mid → $spw サンプル（×$gb_up / ÷$gb_dn）"
puts "SPEC      : 8192 点 = 16 × $fft_lane_n / 4096 ch × [expr {$fs_gsps * 1000.0 / 8192}] MHz / 1 フレーム [expr {8192 / $fs_gsps / 1000.0}] us"

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
# 速度グレードの検証ビルド（-1）では board_part もボードプリセットも使わない。
set use_board [expr {$part eq $part_default}]

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
} else {
    puts "NOTE: 速度グレード検証ビルド。board_part とボードプリセットは使わない"
}

add_files -norecurse [list ./src/spec_core.v ./src/cmul.v ./src/dft16.v ./src/tw_rom.v]

# ------------------------------------------------------------------ FFT IP（lane_fft）
# spec_core.v がレーンごとに 1 個（計 16 個）使う。**名前 lane_fft は RTL と対**。
# 設定の意味（spec_core.v / sim/lane_fft_model.v の冒頭と対）:
#   512 点・pipelined streaming・固定小数点・入力 14 bit・**unscaled**（出力 24 bit、飽和も丸めの
#   スケーリングも起きない。|Y| ≦ 2^22 の上限は spec_core.v の冒頭）
#   **自然順で出力し XK_INDEX を載せる**（k1 でひねり係数と積分の番地を引くため）
#   **realtime**（proj011。入力が途切れても IP は待たない。途切れは spec_core の FLAGS[4] / [6] が捕まえる。
#   出力側の tready は IP に無い）
#   乗算器・バタフライは FFT_OPT で選ぶ（src/fft_cfg.tcl）
# CONFIG の名前は版で変わりうるので、1 つずつ投げて **読み返しで判定する**（proj003 の流儀）。
create_ip -name xfft -vendor xilinx.com -library ip -module_name lane_fft
set xfft [get_ips lane_fft]
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
    m_axis_data_tdata 48 m_axis_data_tuser 16 m_axis_data_tvalid 1 m_axis_data_tlast 1 \
    event_frame_started 1 event_tlast_unexpected 1 event_tlast_missing 1 event_data_in_channel_halt 1 ]
set top ""
foreach f [get_files -quiet -of_objects [get_files lane_fft.xci]] {
    if {[string match "*/synth/lane_fft.vhd" $f]} { set top $f }
}
if {$top eq ""} {
    puts "WARNING: IP のトップ（synth/lane_fft.vhd）が見つからない。ポートの照合を飛ばす"
} else {
    set fh [open $top r]; set txt [read $fh]; close $fh
    # **entity の宣言の中だけを読む。**lane_fft.vhd には IP コア（xfft_v9_1_x）の component 宣言も入っていて、
    # そちらは設定に依らず**全部のポート**（aclken・m_axis_data_tready・m_axis_status_* …）を持つ。
    # ファイル全体を読むと「在るか」は component 側で必ず通り、「在ってはいけないか」は必ず落ちる
    # （2026-09-24、proj011 の初回ビルドで realtime の IP に m_axis_data_tready が「在る」と誤判定した）。
    if {![regexp -nocase -indices {\mentity\s+lane_fft\s+is\M} $txt ent_a]} {
        puts "ERROR: $top に entity lane_fft の宣言が見つからない"
        exit 1
    }
    set a0 [lindex $ent_a 1]
    if {![regexp -nocase -indices -start $a0 {\mend\s+(entity\s+)?lane_fft\s*;} $txt ent_b]} {
        puts "ERROR: $top の entity lane_fft の終わりが見つからない"
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
    puts "---- FFT IP のポート（entity lane_fft の宣言から [dict size $have] 本）----"
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
        puts "ERROR: FFT IP のポートが spec_core.v の前提と $ng 件合わない。entity lane_fft にあるポート:"
        dict for {n w} $have { puts "    $n ($w)" }
        exit 1
    }
}
update_compile_order -fileset sources_1

# ------------------------------------------------------------------ block design
create_bd_design $bd_name

# ---- PS ----
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e zynq_ultra_ps_e_0]
if {$use_board} {
    apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
        -config {apply_board_preset "1"} $ps
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
    CONFIG.PSU__USE__S_AXI_GP2 {0} \
    CONFIG.PSU__USE__S_AXI_GP3 {0} \
    CONFIG.PSU__USE__S_AXI_GP4 {0} \
    CONFIG.PSU__USE__S_AXI_GP5 {0} \
    CONFIG.PSU__USE__S_AXI_GP6 {0} \
    CONFIG.PSU__USE__IRQ0 {0} \
    CONFIG.PSU__USE__IRQ1 {0} \
] $ps

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
        create_bd_cell -type ip -vlnv xilinx.com:ip:axis_dwidth_converter gb_dn_$i
        cfg_apply gb_dn_$i [list \
            CONFIG.S_TDATA_NUM_BYTES [expr {$gb_mid * 2}] \
            CONFIG.M_TDATA_NUM_BYTES [expr {$spw * 2}] \
            CONFIG.HAS_TLAST {0} CONFIG.HAS_TKEEP {0} CONFIG.HAS_TSTRB {0} \
        ] 0
        incr i
    }
    cfg_report "ギアボックスの設定（読み返しで検証するので、ここでは止めない）"
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

# ---- 分光計コア（spec_core.v。中で lane_fft を 16 個使う）----
# PYNQ から ol.spec_core_0 で引く。AXI4-Lite（s_axi）と AXI4-Stream（s_axis）は
# ポート名の接頭辞から推論される。**推論されなかったらここで止める。**
set spec [create_bd_cell -type module -reference spec_core spec_core_0]
# FFT の設定の符号を ID の下位 8 bit に載せる（src/fft_cfg.tcl の fft_cfg_code）。**読み返して確かめる**
set_property CONFIG.FFT_CFG $fft_code $spec
set got_code [get_property CONFIG.FFT_CFG $spec]
if {$got_code != $fft_code} {
    puts "ERROR: spec_core_0 の FFT_CFG が $got_code（要求 $fft_code）"
    exit 1
}
puts [format "spec_core_0: FFT_CFG = 0x%02x（ID の下位 8 bit）" $fft_code]
# ビルドの指紋（rev4）: [30] ボードのプリセットあり / [29:28] 速度グレード。**ID では build/ と build-1-e/ を区別できない**
# （同じ RTL・同じ FFT_OPT）ので、PS がこれを読んで、プリセットの無い検証ビルドを実機に載せたら止める。
# ビルド時刻は入れない（定数が変わると配置が組み替わり、作り直しが WNS まで再現しなくなる）
set grade [string index [lindex [split $part -] 2] 0]
if {![string is integer -strict $grade] || $grade < 1 || $grade > 3} {
    puts "ERROR: part '$part' から速度グレードが読めない"
    exit 1
}
set build_tag [expr {($use_board << 30) | (($grade & 3) << 28)}]
set_property CONFIG.BUILD_TAG $build_tag $spec
set got_tag [get_property CONFIG.BUILD_TAG $spec]
if {$got_tag != $build_tag} {
    puts "ERROR: spec_core_0 の BUILD_TAG が $got_tag（要求 $build_tag）"
    exit 1
}
puts [format "spec_core_0: BUILD_TAG = 0x%08x（プリセット %s / 速度グレード -%s）" $build_tag [expr {$use_board ? "あり" : "なし"}] $grade]
set spec_axi  [BI spec_core_0 [list "s_axi"  "S_AXI"]  "spec_core の AXI4-Lite"]
set spec_axis [BI spec_core_0 [list "s_axis" "S_AXIS"] "spec_core の AXI4-Stream 入力"]

# ---- リセット生成（3 ドメイン）----
set rst_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_ctrl]
set rst_adc  [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_adc]
set rst_dsp  [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_dsp]

# ---- 相互接続 ----
# **NUM_CLKS = 2**: aclk = pl_clk0（PS と RFDC）/ aclk1 = DSP ドメイン（spec_core）。
# SmartConnect は相手の IP のクロックから、どのポートがどのクロックかを判断し、
# 乗り換えを内部に持つ。**spec_core を 256 MHz に置いたまま自作の CDC を書かずに済む。**
set smc_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_ctrl]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {2} CONFIG.NUM_CLKS {2}] $smc_ctrl

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

# クロック
foreach p [list rst_ctrl/slowest_sync_clk smc_ctrl/aclk rfdc/s_axi_aclk \
                zynq_ultra_ps_e_0/maxihpm0_fpd_aclk] {
    nc $ps_clk0 $p
}
set adc_dom [list rst_adc/slowest_sync_clk]
foreach t $adc_tiles { lappend adc_dom rfdc/m${t}_axis_aclk }
lappend adc_dom gb_up_0/aclk gb_fifo_0/s_axis_aclk
set dsp_dom [list rst_dsp/slowest_sync_clk gb_fifo_0/m_axis_aclk gb_dn_0/aclk \
                  spec_core_0/aclk smc_ctrl/aclk1]
foreach p $adc_dom { nc $adc_fabric $p }
foreach p $dsp_dom { nc $dsp_fabric $p }

# MMCM がロックするまで ADC / DSP ドメインをリセットに保つ。
# **clk_adcN はタイルが起動して初めて出る**ので、ロックも起動後になる。
nc clk_wiz_adc/locked rst_adc/dcm_locked
nc clk_wiz_adc/locked rst_dsp/dcm_locked

# リセット
foreach r {rst_ctrl rst_adc rst_dsp} { nc $ps_rstn $r/ext_reset_in }
foreach p [list smc_ctrl/aresetn rfdc/s_axi_aresetn] { nc rst_ctrl/peripheral_aresetn $p }
set adc_rst {}
foreach t $adc_tiles { lappend adc_rst rfdc/m${t}_axis_aresetn }
lappend adc_rst gb_up_0/aresetn gb_fifo_0/s_axis_aresetn
foreach p $adc_rst { nc rst_adc/peripheral_aresetn $p }
foreach p [list gb_dn_0/aresetn spec_core_0/aresetn] { nc rst_dsp/peripheral_aresetn $p }

# ---- データ経路: RFDC → ギアボックス → spec_core ----
lassign [lindex $chans 0] t s
set src [BI rfdc [list "m${t}${s}_axis"] "RFDC の AXI4-Stream 出力 (tile $t slice $s)"]
if {![catch {set nb [get_property CONFIG.TDATA_NUM_BYTES $src]}] && $nb ne ""} {
    if {$nb != $spw_adc * 2} {
        puts "ERROR: m${t}${s}_axis の語幅が $nb B。期待 [expr {$spw_adc * 2}] B。"
        puts "  Real のつもりが I/Q になっている可能性がある"
        exit 1
    }
}
ic $src [get_bd_intf_pins gb_up_0/S_AXIS]
ic [get_bd_intf_pins gb_up_0/M_AXIS]   [get_bd_intf_pins gb_fifo_0/S_AXIS]
ic [get_bd_intf_pins gb_fifo_0/M_AXIS] [get_bd_intf_pins gb_dn_0/S_AXIS]
ic [get_bd_intf_pins gb_dn_0/M_AXIS]   $spec_axis
puts [format "  Tile %d slice %d -> gb_up_0 / gb_fifo_0 / gb_dn_0 -> spec_core_0" [expr {224 + $t}] $s]

# 制御系 AXI: PS → SmartConnect → RFDC / spec_core
ic [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_FPD] [get_bd_intf_pins smc_ctrl/S00_AXI]
ic [get_bd_intf_pins smc_ctrl/M00_AXI] [get_bd_intf_pins rfdc/s_axi]
ic [get_bd_intf_pins smc_ctrl/M01_AXI] $spec_axi

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

# ---- spec_core の窓は 64 KiB ----
# スペクトル（0x8000–）まで届かないと、上位の ch だけ読めない（DECERR）。
# assign_bd_address が既定で何を割り当てたかに依存しないよう、明示して読み返す。
set spec_seg ""
foreach seg [get_bd_addr_segs -quiet] {
    if {[string match "*spec_core_0*" $seg] && [string match "*SEG_*" $seg]} { set spec_seg $seg }
}
if {$spec_seg eq ""} {
    puts "ERROR: spec_core_0 のアドレスセグメントが見つからない。一覧:"
    foreach seg [get_bd_addr_segs -quiet] { puts "    $seg" }
    exit 1
}
if {[get_property RANGE $spec_seg] < $spec_range} {
    set_property RANGE $spec_range $spec_seg
}
puts [format "SPEC ADDR  : %s +%s（%s）" [get_property OFFSET $spec_seg] \
      [get_property RANGE $spec_seg] $spec_seg]
if {[get_property RANGE $spec_seg] < $spec_range} {
    puts "ERROR: spec_core の窓が $spec_range B に届かない"
    exit 1
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

add_files -fileset constrs_1 -norecurse ./src/timing.xdc
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

# ---- 合成〜実装〜ビットストリーム ----
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    puts "ERROR: impl_1 が完走していない。$projdir の run ログを見る"
    exit 1
}

open_run impl_1
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
    puts "  **非同期の宣言が見当たらない。src/timing.xdc が効いていない可能性がある**"
}

# ---- BRAM と DSP の使用量 ----
# README の予言（BRAM36 と DSP の見積もり）と突き合わせる。**4ch に広げるときの基準になる。**
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

# ---- lane_fft 1 個ぶん・16 個の合計・それ以外 ----
# **make survey（IP 単体の OOC 合成）の数字と突き合わせる。**配置配線後なので、
# 単体の値と違えば最適化が階層をまたいだということ（それ自体が記録に値する）
set ffts [lsort [get_cells -quiet -hierarchical -filter {ORIG_REF_NAME == lane_fft || REF_NAME == lane_fft}]]
# **名前に [0] が入るので -filter の =~ は使わない**（glob の文字クラスとして読まれ、何にも当たらない）。
# DSP の名前を一度集め、先頭一致で数える
set dsp_names [get_property NAME [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E2}]]
set dsp_all [llength $dsp_names]
proc count_under {names c} {
    set n 0
    foreach x $names { if {[string first "$c/" $x] == 0} { incr n } }
    return $n
}
set dsp_fft 0
foreach c $ffts { incr dsp_fft [count_under $dsp_names $c] }
puts ""
puts "---- FFT IP の資源（FFT_OPT = $fft_opt）----"
puts "  lane_fft の個数         = [llength $ffts]（期待 16）"
if {[llength $ffts] > 0} {
    set c0 [lindex $ffts 0]
    report_utilization -cells $c0 -file $outdir/lane_fft_util.rpt
    puts "  DSP48E2 1 個あたり      = [count_under $dsp_names $c0]（$c0）"
    foreach line [split [exec cat $outdir/lane_fft_util.rpt] \n] {
        if {[regexp {^\|\s*(CLB LUTs|CLB Registers|Block RAM Tile|DSPs)\s*\|} $line]} { puts "    [string trim $line]" }
    }
}
puts "  DSP48E2 FFT 16 個の合計 = $dsp_fft"
puts "  DSP48E2 それ以外        = [expr {$dsp_all - $dsp_fft}]（proj010 では 144 = cmul 32 × 4 ＋ 電力 16）"
puts "  DSP48E2 全体            = $dsp_all（proj010 は 944）"

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
    puts "  クロック対が違っていれば src/timing.xdc の非同期宣言の漏れ。"
    puts "  **XDC で if / foreach を使うと黙って無効になる**（Designutils 20-1307）"
    exit 1
}

if {!$use_board} {
    puts ""
    puts "NOTE: これは速度グレード検証ビルド（$part）。"
    puts "      ボードプリセットを当てていないので、このビットストリームは実機に使わない。"
    puts "      見るのは上の TIMING の値だけ。"
}

