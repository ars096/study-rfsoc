# SPDX-License-Identifier: BSD-3-Clause
# proj032 P-7 — SpW のコアを 1 個（ADC_A）載せた最初の実機の .bit（make build）。成果物は build/proj032b1.bit・.hwh
#
#   ADC_A（Tile 226 / slice 2）→ RFDC → ギアボックス（gb_adc → gb_up → gb_fifo → gb_gate → gb_dn）→ s45_core_0（spw_s45_core: spw_core のラッパ）
#     → m_axis_rec（128 bit）→ s45_ring_0（ring128）→ PS の S_AXI_HP0_FPD（128 bit）。時刻は time_core_0（1PPS）
#   **PL の DDR（MIG）は載せない**（P-7）: 窓の履歴の枠はチップ内（WSL < S = 6）だけ。DDR の口はラッパの中で 0 に縛る
#   proj031 の build.tcl（12681f1）から写したところ: 補助の手続き・RFDC・Clocking Wizard・ギアボックス・リセット・外部ポート・vivado.log の見張り（中身は変えず、chans を ADC_A の 1 本に）
#   書いたところ: FFT IP（win_fft、tools/ooc_rtl.tcl と同じ設定）・コア・time_core・リング・相互接続・番地・結線の照合
#   PS は -1 のプリセット（src/board/ps_preset.tcl）を当てる（D-3 と同じ）
#   ID: BIT_KIND 7（SpW8）・BIT_REV 2（1 は 1 回目の build_r1）・PROJ 0x0032_0300（s45_core_0・time_core_0・s45_ring_0）
#   成否は make の終了状態でなく build/vivado.log の「TIMING (確定)」「CRITICAL WARNING: n 件」「=== wrote」で読む
set proj    proj032b1
set bd_name system
set part    xczu48dr-ffvg1517-1-e
set outdir  ./build
if {[info exists ::env(PART)]   && $::env(PART)   ne ""} { set part   $::env(PART) }
if {[info exists ::env(OUTDIR)] && $::env(OUTDIR) ne ""} { set outdir ./$::env(OUTDIR) }
set jobs 8
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }
set projdir $outdir/vivado
if {$part ne "xczu48dr-ffvg1517-1-e"} { puts "ERROR: proj032 b1 は -1 だけを作る（PS のプリセットの当て方が -1 の形）。PART=$part"; exit 1 }

# ---- 設計パラメータ ----
# **SMA のラベルとの対応は VERSIONS.md が正**（ADC_A = Tile 226 / slice 2 = {2 2}）
set chans      {{2 2}}
set ch_labels  {ADC_A}
set adc_tiles  {2}
set nch        1
set fs_gsps    4.096
set refclk_mhz 491.520
set spw_adc    12
set spw        16
set beat_bits  256
proc gcd {a b} { while {$b} { set t $b; set b [expr {$a % $b}]; set a $t }; return $a }
set gb_mid [expr {$spw_adc * $spw / [gcd $spw_adc $spw]}]
set gb_up  [expr {$gb_mid / $spw_adc}]
set gb_dn  [expr {$gb_mid / $spw}]
set use_gb 1
set outclk_mhz [format %.3f [expr {$fs_gsps * 1000.0 / 16}]]
set wiz_src_tile 2
set ctrl_mhz   100
set fabric_mhz [format %.3f [expr {$fs_gsps * 1000.0 / $spw_adc}]]
set dsp_mhz    [format %.3f [expr {$fs_gsps * 1000.0 / $spw}]]
set fs_mhz     [format %.3f [expr {$fs_gsps * 1000.0}]]
set gb_k_rst   2
# SpW のコア（spw_core と対）
set spw_h 14; set spw_e 3; set spw_s 6; set spw_nk 8; set spw_gl2 19
set spw_kind 7
set spw_rev 2                  ;# P-7: 1 = 1 回目（build_r1、eng が tready を見ない）・2 = IP の手前に溜め（eng の u_ipq）
set spw_proj [expr {0x00320300}]
set win_range 65536
puts "PART      : $part / OUTDIR : $outdir / JOBS : $jobs"
puts "ADC       : ADC_A = Tile 226 / slice 2 → s45_core_0（SpW、H $spw_h・E $spw_e・S $spw_s・G_L2 $spw_gl2、PL の DDR なし）"
puts "fs        : $fs_mhz MSPS （RFDC $fabric_mhz MHz × $spw_adc → DSP $dsp_mhz MHz × $spw）"

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
file mkdir $outdir
create_project $proj $projdir -part $part -force
set part_actual [get_property PART [current_project]]
if {$part_actual ne $part} { puts "ERROR: part が違う（要求 $part・実際 $part_actual）"; exit 1 }
set ps_preset_file [file normalize ../src/board/ps_preset.tcl]
source $ps_preset_file
set has_preset 1

set S [file normalize ../src]
add_files -norecurse [list $S/spw/spw_s45_core.v $S/spw/spw_core.v $S/spw/spw_regs.v $S/spw/spw_front.v $S/spw/pfb64_core.v $S/spw/head_core.v \
    $S/spw/ddcb.v $S/spw/hbmc.v $S/spw/sfifo.v $S/spw/wsb.v $S/spw/eng.v $S/spw/pfb4_rom.v $S/spw/ddrr.v $S/spw/ddrw.v $S/spw/dsink.v \
    $S/spw/f32cv.v $S/spw/rmux128.v $S/spw/ring128.v \
    $S/common/cmul.v $S/common/dft16f.v $S/common/hb2.v $S/common/hb2s.v $S/common/nco_rom.v \
    $S/common/core_cmn.v $S/common/tp_core.v $S/common/adc_ev.v $S/common/time_core.v $S/common/gb_adc.v $S/common/gb_gate.v]
add_files -norecurse [list $S/spw/pfb64_coef.vh $S/spw/hb_coef.vh]
set_property file_type {Verilog Header} [get_files [list pfb64_coef.vh hb_coef.vh]]
set_property include_dirs [list $S/spw] [get_filesets sources_1]

# ------------------------------------------------------------------ FFT IP（win_fft。eng.v が機関ごとに 1 個。tools/ooc_rtl.tcl と同じ設定）
create_ip -name xfft -vendor xilinx.com -library ip -module_name win_fft
set wfft [get_ips win_fft]
set req [list CONFIG.transform_length 4096 CONFIG.implementation_options pipelined_streaming_io CONFIG.data_format fixed_point \
              CONFIG.input_width 18 CONFIG.scaling_options unscaled CONFIG.output_ordering natural_order CONFIG.xk_index true \
              CONFIG.throttle_scheme realtime CONFIG.aresetn true CONFIG.run_time_configurable_transform_length false \
              CONFIG.cyclic_prefix_insertion false CONFIG.channels 1 CONFIG.complex_mult_type use_mults_resources CONFIG.butterfly_type use_luts]
set_property -dict [concat $req [list CONFIG.target_clock_frequency 256 CONFIG.phase_factor_width 18 CONFIG.rounding_modes convergent_rounding CONFIG.ovflo false]] $wfft
set ng 0
foreach {k v} $req { if {![string equal -nocase [get_property $k $wfft] $v]} { puts "ERROR: win_fft $k = [get_property $k $wfft]（要求 $v）"; incr ng } }
if {$ng} { exit 1 }
generate_target {instantiation_template synthesis simulation} $wfft
update_compile_order -fileset sources_1

# ------------------------------------------------------------------ block design
create_bd_design $bd_name

# ---- PS（-1 のプリセットを当てて読み返す。D-3 と同じ）----
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e zynq_ultra_ps_e_0]
if {[get_property VLNV $ps] ne $ps_preset_vlnv} { puts "ERROR: PS の VLNV [get_property VLNV $ps] が ps_preset.tcl の $ps_preset_vlnv と違う"; exit 1 }
set_property -dict $ps_preset $ps
set ng 0
foreach {k v} $ps_preset { if {[get_property $k $ps] ne $v} { incr ng; puts "  PS PRESET 違う: $k = [get_property $k $ps]（要求 $v）" } }
if {$ng > 0} { puts "ERROR: PS にプリセットが当たっていない"; exit 1 }
# 使う AXI は HPM0_FPD と HP0_FPD（S_AXI_GP2、128 bit）。**使わないものも明示的に 0 にする**（proj002 の BD 41-758）
set ps_req [list \
    CONFIG.PSU__FPGA_PL0_ENABLE {1} CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ $ctrl_mhz CONFIG.PSU__FPGA_PL1_ENABLE {0} \
    CONFIG.PSU__USE__M_AXI_GP0 {1} CONFIG.PSU__USE__M_AXI_GP1 {0} CONFIG.PSU__USE__M_AXI_GP2 {0} \
    CONFIG.PSU__USE__S_AXI_GP0 {0} CONFIG.PSU__USE__S_AXI_GP1 {0} CONFIG.PSU__USE__S_AXI_GP2 {1} CONFIG.PSU__SAXIGP2__DATA_WIDTH {128} \
    CONFIG.PSU__USE__S_AXI_GP3 {0} CONFIG.PSU__USE__S_AXI_GP4 {0} CONFIG.PSU__USE__S_AXI_GP5 {0} CONFIG.PSU__USE__S_AXI_GP6 {0} \
    CONFIG.PSU__USE__IRQ0 {0} CONFIG.PSU__USE__IRQ1 {0} ]
set_property -dict $ps_req $ps
set ng 0
foreach {k v} $ps_req { if {[get_property $k $ps] ne $v} { incr ng; puts "  PS 違う: $k = [get_property $k $ps]（要求 $v）" } }
if {$ng > 0} { puts "ERROR: PS の口の設定が要求どおりにならない"; exit 1 }

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


# ---- コア・時刻・リング（P-7）----
set grade [string index [lindex [split $part -] 2] 0]
set build_tag_base [expr {($has_preset << 30) | (($grade & 3) << 28)}]     ;# [30] PS にプリセット / [29:28] 速度グレード（proj031 と同じ形。[23] 4ch は立てない）
set rdc [get_bd_pins -quiet gb_fifo_0/axis_rd_data_count]
if {[llength $rdc] == 0} { puts "ERROR: gb_fifo_0/axis_rd_data_count が無い"; exit 1 }
set rdc_w [expr {[get_property LEFT $rdc] - [get_property RIGHT $rdc] + 1}]
set gba [create_bd_cell -type module -reference gb_adc gb_adc_0]
set_property CONFIG.DW [expr {$spw_adc * 16}] $gba
set gbg [create_bd_cell -type module -reference gb_gate gb_gate_0]
set_property -dict [list CONFIG.DW [expr {$gb_mid * 16}] CONFIG.CW $rdc_w] $gbg
if {[get_property CONFIG.DW $gba] != $spw_adc * 16 || [get_property CONFIG.DW $gbg] != $gb_mid * 16 || [get_property CONFIG.CW $gbg] != $rdc_w} {
    puts "ERROR: gb_adc_0 / gb_gate_0 の DW・CW が要求と違う"; exit 1
}

set tcore [create_bd_cell -type module -reference time_core time_core_0]
set time_tag [expr {$build_tag_base | (1 << 20)}]
foreach {k want} [list CONFIG.BUILD_TAG $time_tag CONFIG.BIT_KIND $spw_kind CONFIG.BIT_REV $spw_rev CONFIG.PROJ $spw_proj] {
    set_property $k $want $tcore
    if {[get_property $k $tcore] != $want} { puts "ERROR: time_core_0 の $k が [get_property $k $tcore]（要求 $want）"; exit 1 }
}
if {abs([get_property CONFIG.BEATS_PER_SEC $tcore] - $dsp_mhz * 1e6) > 0.5} { puts "ERROR: time_core_0 の BEATS_PER_SEC が DSP のクロックと合わない"; exit 1 }

set rcore [create_bd_cell -type module -reference ring128 s45_ring_0]
foreach {k want} [list CONFIG.NX [expr {$spw_e + 1}] CONFIG.BIT_KIND $spw_kind CONFIG.BIT_REV $spw_rev CONFIG.PROJ $spw_proj] {
    set_property $k $want $rcore
    if {[get_property $k $rcore] != $want} { puts "ERROR: s45_ring_0 の $k が [get_property $k $rcore]（要求 $want）"; exit 1 }
}

set gcore [create_bd_cell -type module -reference spw_s45_core s45_core_0]
set core_tag [expr {$build_tag_base | (1 << 22)}]
lassign [lindex $chans 0] cp_t cp_s
set core_port [expr {0 | ($cp_t << 8) | ($cp_s << 12)}]
foreach {k want} [list CONFIG.BUILD_TAG $core_tag CONFIG.GB_K_RST $gb_k_rst CONFIG.ADC $core_port CONFIG.H $spw_h CONFIG.E $spw_e \
                       CONFIG.S $spw_s CONFIG.NK $spw_nk CONFIG.G_L2 $spw_gl2 CONFIG.BIT_KIND $spw_kind CONFIG.BIT_REV $spw_rev CONFIG.PROJ $spw_proj] {
    set_property $k $want $gcore
    if {[get_property $k $gcore] != $want} { puts "ERROR: s45_core_0 の $k が [get_property $k $gcore]（要求 $want）"; exit 1 }
}
puts [format "s45_core_0（ADC_A）: spw_s45_core / BUILD_TAG = 0x%08x / CORE_PORT = 0x%04x / time_core_0 BUILD_TAG = 0x%08x" $core_tag $core_port $time_tag]
set core_axi  [BI s45_core_0 [list s_axi S_AXI] "s45_core_0 の AXI4-Lite"]
set core_axis [BI s45_core_0 [list s_axis S_AXIS] "s45_core_0 の入力"]
set rec_axis  [BI s45_core_0 [list m_axis_rec M_AXIS_REC] "s45_core_0 のレコードの出口"]
set time_axi  [BI time_core_0 [list s_axi S_AXI] "time_core_0 の AXI4-Lite"]
set ring_axi  [BI s45_ring_0 [list s_axi S_AXI] "s45_ring_0 の AXI4-Lite"]
set ring_m    [BI s45_ring_0 [list m_axi M_AXI] "s45_ring_0 の書き手"]
set ring_in   [BI s45_ring_0 [list s_axis S_AXIS] "s45_ring_0 の入口"]
set hp0 [get_bd_intf_pins -quiet zynq_ultra_ps_e_0/S_AXI_HP0_FPD]
if {$hp0 eq ""} { puts "ERROR: PS の S_AXI_HP0_FPD が無い"; exit 1 }
foreach {p w} {s45_core_0/rec_drop 4 s45_ring_0/ext_drop 4 s45_core_0/m_axis_rec_tdata 128} {
    set q [BP $p]
    set got [expr {[get_property LEFT $q] - [get_property RIGHT $q] + 1}]
    if {$got != $w} { puts "ERROR: $p の幅 $got（期待 $w）"; exit 1 }
}


# ---- 相互接続（M00 RFDC・M01 s45_core_0・M02 time_core_0・M03 s45_ring_0。aclk = pl_clk0 / aclk1 = DSP）----
set smc_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_ctrl]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {4} CONFIG.NUM_CLKS {2}] $smc_ctrl
if {[get_property CONFIG.NUM_MI $smc_ctrl] != 4} { puts "ERROR: smc_ctrl の NUM_MI"; exit 1 }

# ------------------------------------------------------------------ 配線（proj031 と同じ形。ch は 1 本）
set ps_clk0  zynq_ultra_ps_e_0/pl_clk0
set ps_rstn  zynq_ultra_ps_e_0/pl_resetn0
set adc_outclk rfdc/clk_adc${wiz_src_tile}
set adc_fabric clk_wiz_adc/clk_out1
set dsp_fabric clk_wiz_adc/clk_out2
nc $adc_outclk clk_wiz_adc/clk_in1
nc $ps_rstn    clk_wiz_adc/resetn
foreach p [list rst_ctrl/slowest_sync_clk smc_ctrl/aclk rfdc/s_axi_aclk zynq_ultra_ps_e_0/maxihpm0_fpd_aclk time_core_0/ctrl_aclk] { nc $ps_clk0 $p }
set adc_dom [list rst_adc/slowest_sync_clk gb_up_0/aclk gb_fifo_0/s_axis_aclk gb_adc_0/aclk]
foreach t $adc_tiles { lappend adc_dom rfdc/m${t}_axis_aclk }
set dsp_dom [list rst_dsp/slowest_sync_clk smc_ctrl/aclk1 gb_fifo_0/m_axis_aclk gb_dn_0/aclk gb_gate_0/aclk \
                  s45_core_0/aclk time_core_0/aclk s45_ring_0/aclk zynq_ultra_ps_e_0/saxihp0_fpd_aclk]
foreach p $adc_dom { nc $adc_fabric $p }
foreach p $dsp_dom { nc $dsp_fabric $p }
nc clk_wiz_adc/locked rst_adc/dcm_locked
nc clk_wiz_adc/locked rst_dsp/dcm_locked
foreach r {rst_ctrl rst_adc rst_dsp} { nc $ps_rstn $r/ext_reset_in }
foreach p [list smc_ctrl/aresetn rfdc/s_axi_aresetn time_core_0/ctrl_aresetn] { nc rst_ctrl/peripheral_aresetn $p }
nc $rst_out(2) rfdc/m2_axis_aresetn
# **結線はこの表 1 つから張り、下の照合も同じ表を読む**（proj031 の ch_nets と同じ考え）
set nets [list \
    $rst_out(2)                    [list gb_adc_0/aresetn] \
    rst_dsp/peripheral_aresetn     [list s45_core_0/aresetn time_core_0/aresetn s45_ring_0/aresetn] \
    gb_adc_0/gb_rstn               [list gb_up_0/aresetn gb_fifo_0/s_axis_aresetn] \
    s45_core_0/gb_dn_rstn          [list gb_gate_0/aresetn gb_dn_0/aresetn] \
    s45_core_0/gb_hold             [list gb_adc_0/hold] \
    s45_core_0/gb_adj              [list gb_adc_0/adj] \
    s45_core_0/gb_k                [list gb_gate_0/k] \
    gb_fifo_0/axis_rd_data_count   [list gb_gate_0/rd_count] \
    gb_gate_0/gb_stat              [list s45_core_0/gb_stat] \
    gb_adc_0/adc_out               [list gb_gate_0/adc_in] \
    gb_gate_0/adc_stat             [list s45_core_0/adc_stat] \
    time_core_0/t_out              [list s45_core_0/t_in] \
    time_core_0/go_out             [list s45_core_0/go_in] \
    s45_core_0/rec_drop            [list s45_ring_0/ext_drop] ]
foreach {drv loads} $nets { foreach p $loads { nc $drv $p } }

# データの道: RFDC → gb_adc → gb_up → gb_fifo → gb_gate → gb_dn → s45_core_0 → s45_ring_0 → HP0
set src [BI rfdc [list m22_axis] "RFDC の AXI4-Stream 出力 (tile 2 slice 2)"]
if {![catch {set nb [get_property CONFIG.TDATA_NUM_BYTES $src]}] && $nb ne "" && $nb != $spw_adc * 2} { puts "ERROR: m22_axis の語幅が $nb B"; exit 1 }
set intf [list \
    $src [BI gb_adc_0 [list s_axis S_AXIS] "gb_adc_0 の入力"] \
    [BI gb_adc_0 [list m_axis M_AXIS] "gb_adc_0 の出力"] [get_bd_intf_pins gb_up_0/S_AXIS] \
    [get_bd_intf_pins gb_up_0/M_AXIS] [get_bd_intf_pins gb_fifo_0/S_AXIS] \
    [get_bd_intf_pins gb_fifo_0/M_AXIS] [BI gb_gate_0 [list s_axis S_AXIS] "gb_gate_0 の入力"] \
    [BI gb_gate_0 [list m_axis M_AXIS] "gb_gate_0 の出力"] [get_bd_intf_pins gb_dn_0/S_AXIS] \
    [get_bd_intf_pins gb_dn_0/M_AXIS] $core_axis \
    $rec_axis $ring_in \
    $ring_m $hp0 \
    [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_FPD] [get_bd_intf_pins smc_ctrl/S00_AXI] \
    [get_bd_intf_pins smc_ctrl/M00_AXI] [get_bd_intf_pins rfdc/s_axi] \
    [get_bd_intf_pins smc_ctrl/M01_AXI] $core_axi \
    [get_bd_intf_pins smc_ctrl/M02_AXI] $time_axi \
    [get_bd_intf_pins smc_ctrl/M03_AXI] $ring_axi ]
foreach {a b} $intf { ic $a $b }

# ---- 1PPS の外部ポート（proj031 と同じ）----
foreach {pname ppin} {pps_trig pps_trig_i pps_comp pps_comp_i} {
    create_bd_port -dir I $pname
    connect_bd_net [get_bd_ports $pname] [BP time_core_0/$ppin]
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

# ------------------------------------------------------------------ 番地
assign_bd_address
set data [get_bd_addr_spaces zynq_ultra_ps_e_0/Data]
set wins {}
foreach {c rng off} [list s45_core_0 $win_range 0xA0100000 time_core_0 4096 0xA0110000 s45_ring_0 4096 0xA0111000] {
    set seg [get_bd_addr_segs -quiet -of_objects $data -filter "NAME =~ *${c}*"]
    if {[llength $seg] != 1} { puts "ERROR: $c の番地の区画が 1 個でない（$seg）"; exit 1 }
    set_property range $rng $seg
    set_property offset $off $seg
    if {[get_property range $seg] != $rng || [get_property offset $seg] != $off} { puts "ERROR: $c の番地が要求と違う"; exit 1 }
    puts [format "番地      : %-12s %s +%s" $c [get_property offset $seg] [get_property range $seg]]
    lappend wins [list $c [expr {$off}] $rng]
}
set rseg [get_bd_addr_segs -quiet -of_objects $data -filter "NAME =~ *rfdc*"]
lappend wins [list rfdc [expr {[get_property offset $rseg]}] [expr {[get_property range $rseg]}]]
foreach w1 $wins { foreach w2 $wins {
    lassign $w1 c1 o1 r1; lassign $w2 c2 o2 r2
    if {$c1 < $c2 && $o1 < $o2 + $r2 && $o2 < $o1 + $r1} { puts "ERROR: $c1 と $c2 の番地が重なっている"; exit 1 }
} }
set low ""
foreach s [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces s45_ring_0/m_axi]] { if {[string match "*DDR_LOW*" $s]} { set low $s } }
if {$low eq ""} { puts "ERROR: s45_ring_0/m_axi から PS の DDR_LOW が見えない"; exit 1 }
puts [format "RING DMA  : %s %s +%s" $low [get_property offset $low] [get_property range $low]]

validate_bd_design
save_bd_design

# ---- vivado.log の本体の CRITICAL WARNING（BD を組むときのもの）。陽性対照の目印つき（proj031 と同じ）----
set cw_mark "PROJ032-CW-POSCTL"
if {[catch {send_msg_id PROJ032-1 {CRITICAL WARNING} "$cw_mark: vivado.log の見張りの陽性対照（このビルドの正常な印）"} msg]} { puts "ERROR: 陽性対照の CRITICAL WARNING を出せない（$msg）"; exit 1 }
set vlog [file join $outdir vivado.log]
set cw_hits {}; set cw_pc 0
if {[catch {set fh [open $vlog r]; set vt [read $fh]; close $fh} msg]} { puts "ERROR: $vlog を読めない（$msg）"; exit 1 }
foreach line [split $vt "\n"] {
    if {![regexp {^CRITICAL WARNING:} $line]} continue
    if {[string first $cw_mark $line] >= 0} { incr cw_pc; continue }
    lappend cw_hits $line
}
puts "vivado.log の CRITICAL WARNING（BD まで）: 陽性対照 $cw_pc 件（1 が期待）・ほか [llength $cw_hits] 件（0 が期待）"
foreach l $cw_hits { puts "  $l" }
if {$cw_pc != 1} { puts "ERROR: vivado.log の見張りが陽性対照を拾えない"; exit 1 }
if {[llength $cw_hits] > 0} { puts "ERROR: BD を組む段階で CRITICAL WARNING が出た（上）"; exit 1 }
wiz_actual_check $clkw $wiz_pairs "validate 後"
foreach {cell want} {rst_dsp 0 rst_ctrl 0 rst_adc 0} {
    if {[get_property CONFIG.C_EXT_RESET_HIGH [get_bd_cells $cell]] ne $want} { puts "ERROR: $cell の ext_reset_in の極性が違う"; exit 1 }
}

# ---- 結線の照合（在るべき相手と、在ってはいけない相手。陽性対照つき）----
proc net_pins {pin} {
    set n [get_bd_nets -quiet -of_objects [get_bd_pins $pin]]
    if {$n eq ""} { return {} }
    return [lsort [get_bd_pins -quiet -of_objects $n]]
}
set ng 0
set chk {}
foreach {drv loads} $nets { foreach p $loads { lappend chk $p [list /$drv] {} } }
foreach p $dsp_dom { lappend chk $p [list /$dsp_fabric] [list /$adc_fabric /$ps_clk0] }
foreach p $adc_dom { lappend chk $p [list /$adc_fabric] [list /$dsp_fabric /$ps_clk0] }
lappend chk time_core_0/ctrl_aclk [list /$ps_clk0] [list /$dsp_fabric]
lappend chk s45_core_0/aresetn [list /rst_dsp/peripheral_aresetn] [list /rst_ctrl/peripheral_aresetn /rst_adc/peripheral_aresetn]
foreach {pin must mustnot} $chk {
    set got [net_pins $pin]
    foreach m $must    { if {[lsearch -exact $got $m] < 0} { incr ng; puts "  結線: $pin のネットに $m が無い（$got）" } }
    foreach m $mustnot { if {[lsearch -exact $got $m] >= 0} { incr ng; puts "  結線: $pin のネットに $m が在ってはいけない" } }
}
set got [net_pins s45_core_0/aclk]
if {[lsearch -exact $got /$ps_clk0] >= 0 || [lsearch -exact $got /$dsp_fabric] < 0 || [llength $got] < 5} { incr ng; puts "  陽性対照: s45_core_0/aclk のネットが読めていない（$got）" }
if {[lsearch -exact [net_pins gb_gate_0/k] /s45_core_0/gb_hold] >= 0} { incr ng; puts "  陽性対照: 照合が壊れている" }
puts "結線の照合: 照らした [expr {[llength $chk] / 3}] 本・違う $ng 個"
if {$ng > 0} { puts "ERROR: 結線の照合で落ちた"; exit 1 }

set fh [open $outdir/address_map.rpt w]
foreach seg [get_bd_addr_segs -quiet] { puts $fh [format "%-56s %s +%s" $seg [get_property OFFSET $seg] [get_property RANGE $seg]] }
close $fh

# ---- ラッパと制約 ----
make_wrapper -files [get_files ${bd_name}.bd] -top
set wrapper [lindex [glob -nocomplain $projdir/$proj.gen/sources_1/bd/$bd_name/hdl/${bd_name}_wrapper.v] 0]
if {$wrapper eq ""} { puts "ERROR: ラッパ HDL が見つからない"; exit 1 }
add_files -norecurse $wrapper
set_property top ${bd_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1
add_files -fileset constrs_1 -norecurse [file normalize ../src/board/timing.xdc]
add_files -fileset constrs_1 -norecurse [file normalize ../src/board/pps.xdc]
set_property USED_IN_SYNTHESIS false [get_files timing.xdc]

# ---- 実装の戦略（環境変数 IMPL。Makefile の IMPL）。**読み返して確かめる**（proj031 と同じ）----
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

# ---- run（落ちた印のある run だけ 2 回まで回し直す。D-3 と同じ）----
proc run_dir {n} { return [file join $::projdir $::proj.runs $n] }
proc run_crashed {n} {
    set lf [file join [run_dir $n] runme.log]
    if {![file exists $lf]} { return 0 }
    set fh [open $lf r]; set t [read $fh]; close $fh
    return [regexp {Abnormal program termination|segfault in } $t]
}
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
catch {wait_on_run impl_1}
for {set try 1} {$try <= 2 && [get_property PROGRESS [get_runs impl_1]] ne "100%"} {incr try} {
    set redo ""
    foreach r [get_runs] { if {[run_crashed [get_property NAME $r]]} { set redo [get_property NAME $r]; break } }
    if {$redo eq ""} { break }
    puts "NOTE: $redo で Vivado が落ちた。回し直す（$try 回目）"
    reset_run [get_runs $redo]
    launch_runs impl_1 -to_step write_bitstream -jobs $jobs
    catch {wait_on_run impl_1}
}
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} { puts "ERROR: impl_1 が完走していない（$projdir の run のログ）"; exit 1 }

# 後段（open_run から後）は build_post.tcl。impl_1 の後に親の Vivado が落ちたら `make post` で後段だけ回し直す（proj025 2f と同じ）
source ./build_post.tcl
