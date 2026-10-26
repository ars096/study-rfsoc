# SPDX-License-Identifier: BSD-3-Clause
# proj028 F-5 — 2 段分光の全体の .bit（make f5、この PC の Vivado）。S-2 の build.tcl（MIG）と proj024 の build.tcl（RFDC・ギアボックス・リング）を写してつないだ
#
#   ADC_A（Tile 226 / slice 2、4.096 GS/s、実数）→ rfdc → gb_adc_0 → gb_up_0（12 → 48）→ gb_fifo_0（341.33 → 256 MHz）→ gb_gate_0 → gb_dn_0（48 → 16）
#     → coarse_stage_0（荒い PFB・32 点 FFT・利得・8 bit）→ ct_wr_0 ─┐
#                                                                   ├→ smc_ddr（SmartConnect、256 MHz → MIG の UI クロック）→ ddr4_0（PL DDR4 4 GiB）
#     fine_top_0（細かい PFB・FFT・積分・読み出し）← ct_rd_0 ────────┘
#     fine_top_0 → s45_ring_0（proj024。PS の DDR のリング）→ zynq_ultra_ps_e_0/S_AXI_HP0_FPD
#   制御: PS の M_AXI_HPM0_FPD（pl_clk0 100 MHz）→ smc_ctrl（NUM_CLKS 2: pl_clk0 / DSP 256 MHz）→ rfdc・clk_mon_0・coarse_stage_0・ct_wr_0・ct_rd_0・fine_top_0・s45_ring_0
#   ギアボックスの制御は定数（proj024 の ch 1〜3 と同じ: hold 0・adj 0・k = GB_K_RST 2）。時刻（time_core・1PPS）・core_cmn は載せない
#
# 見張り（LESSONS）: part・PS のプリセット・RFDC・Clocking Wizard・ギアボックス・MIG・FFT IP の設定の読み返し・FFT IP のポート（在るべき・在ってはいけない）・
#   ROM の hex のラッパ・結線の照合（在るべき相手と在ってはいけない相手、陽性対照つき）・番地の重なり・ドライバの無いネット・
#   落ちた印のある run だけ回し直す・足の配置・ROM が BRAM で残ったか・CRITICAL WARNING・WNS/WHS
# 出力: build-f5/proj028.bit・.hwh（同名同階層）・timing.rpt・utilization.rpt・address_map.rpt
set proj    proj028
set bd_name system
set part    xczu48dr-ffvg1517-1-e
set outdir  ./build-f5
set jobs    8
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }
set projdir $outdir/vivado
puts "PART   : $part"
puts "OUTDIR : $outdir"
puts "JOBS   : $jobs"
file mkdir $outdir

# ---- 設計パラメータ ----
# **SMA のラベルとの対応は VERSIONS.md が正**: ADC_A = Tile 226 / slice 2 = {2 2}
set chans      {{2 2}}
set ch_labels  {ADC_A}
set adc_tiles  {2}
set fs_gsps    4.096
set refclk_mhz 491.520
set spw_adc    12
set spw        16
set gb_mid     48
set outclk_mhz [format %.3f [expr {$fs_gsps * 1000.0 / 16}]]
set fabric_mhz [format %.3f [expr {$fs_gsps * 1000.0 / $spw_adc}]]
set dsp_mhz    [format %.3f [expr {$fs_gsps * 1000.0 / $spw}]]
set ctrl_mhz   100
set gb_k_rst   2
set proj_id    [expr {0x00280500}]    ;# s45_ring の PROJ（proj028 F-5）
# 細かい側の ROM（make gen-fine の生成物）: {CONFIG の名前 ファイル 行数 1 行の桁数}
set fine_hex [list \
    LO_FILE [file normalize ./src/fine/fine_coef_lo.hex] 2048 9 \
    HI_FILE [file normalize ./src/fine/fine_coef_hi.hex] 2048 9 \
    TA_FILE [file normalize ./src/fine/fine_tw_a.hex]    64 144 \
    TB_FILE [file normalize ./src/fine/fine_tw_b.hex]    128 144 ]

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

# 生成物の形を先に見る（行数・桁）。古い・切れた hex をここで止める
foreach {par h nrow ncol} $fine_hex {
    if {![file exists $h]} { puts "ERROR: $h が無い"; exit 1 }
    set fh [open $h r]; set lines [split [string trim [read $fh]] "\n"]; close $fh
    set bad 0
    foreach l $lines { if {![string is xdigit -strict $l]} { incr bad } }
    set w [string length [lindex $lines 0]]
    puts [format "ROM       : %s = %s（%d 行 × %d 桁、16 進でない行 %d）" $par [file tail $h] [llength $lines] $w $bad]
    if {[llength $lines] != $nrow || $bad != 0} { puts "ERROR: $h の行数が違う（期待 $nrow）か 16 進でない行がある"; exit 1 }
}

# ------------------------------------------------------------------ helper（proj024 と同じ）
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
    foreach q [get_bd_intf_pins -quiet $cell/*] { puts "    $q" }
    exit 1
}
proc nc {a b} { connect_bd_net  [BP $a] [BP $b] }
proc ic {a b} { connect_bd_intf_net $a $b }
set ::cfg_fail {}
proc cfg_apply {cell cfg {fatal 1}} {
    set obj   [get_bd_cells $cell]
    set known [list_property $obj]
    foreach {k v} $cfg {
        if {[lsearch -exact $known $k] < 0} { lappend ::cfg_fail [list $k $v "この IP に存在しない名前" $fatal]; continue }
        if {[catch {set_property $k $v $obj} msg]} {
            set why [string map {"\n" " "} $msg]
            if {[regexp {Valid values are - (.*)$} $why -> vals]} { set why "有効値: $vals" }
            lappend ::cfg_fail [list $k $v $why $fatal]
        }
    }
}
proc cfg_report {stage} {
    if {[llength $::cfg_fail] == 0} { return }
    puts "---- CONFIG の設定に失敗した項目（$stage）----"
    set hard 0
    foreach f $::cfg_fail {
        lassign $f k v why isfatal
        puts "  $k = $v[expr {$isfatal ? "" : "   （任意）"}]"
        puts "      $why"
        if {$isfatal} { incr hard }
    }
    set ::cfg_fail {}
    if {$hard > 0} { exit 1 }
}
proc dump_ip_params {obj path} {
    set fh [open $path w]
    foreach k [lsort [list_property $obj]] {
        if {![string match CONFIG.* $k]} continue
        set v ""; catch {set v [get_property $k $obj]}
        puts $fh "$k = $v"
    }
    close $fh
}

# ------------------------------------------------------------------ project
create_project $proj $projdir -part $part -force
set part_actual [get_property PART [current_project]]
if {$part_actual ne $part} { puts "ERROR: part が違う（要求 $part・実際 $part_actual）"; exit 1 }

set rtl [list \
    ./src/coarse_stage.v ./src/coarse_pfb.v ./src/cfft32.v ./src/coarse_post.v \
    ./src/ct_wr.v ./src/ct_buf.v ./src/ct_rd.v ./src/clk_mon.v ./src/gb_tap.v \
    ./src/fine/fine_top.v ./src/fine/fine_core.v ./src/fine/fine_pfb.v ./src/fine/fine_coef.v ./src/fine/fine_tw.v \
    ./src/fine/fine_chain.v ./src/fine/fine_acc.v ./src/fine/fine_rdo.v ./src/fine/cmul.v ./src/fine/dft16f.v \
    ./src/common/gb_adc.v ./src/common/gb_gate.v ./src/common/s45_ring.v ./src/common/rec_arb.v]
foreach f $rtl { if {![file exists $f]} { puts "ERROR: $f が無い"; exit 1 } }
add_files -norecurse [lmap f $rtl {file normalize $f}]
set hex_files [lmap {par h nrow ncol} $fine_hex {set h}]
add_files -norecurse $hex_files
set_property file_type {Memory File} [get_files $hex_files]
add_files -fileset constrs_1 -norecurse [list [file normalize ./src/board/ddr4.xdc] [file normalize ./src/board/clk_mon.xdc] [file normalize ./src/board/timing_f5.xdc]]
set_property USED_IN_SYNTHESIS false [get_files timing_f5.xdc]

# ---- FFT IP（lane_fft_f。fine_core.v と sim/lane_fft_f_model.v と対。設定は tools/f5_ooc.tcl と同じ）----
set fft_mod lane_fft_f
create_ip -name xfft -vendor xilinx.com -library ip -module_name $fft_mod
set xfft [get_ips $fft_mod]
set xfft_req [fft_req 8192 15 bit_reversed_order $dsp_mhz]
set ng 0
foreach {k v fatal} $xfft_req { if {[catch {set_property $k $v $xfft} msg]} { puts "  FFT: $k = $v を設定できない: $msg"; if {$fatal} { incr ng } } }
foreach {k v fatal} $xfft_req {
    set got ""; catch {set got [get_property $k $xfft]}
    if {![string equal -nocase $got $v] && $fatal} { puts "  FFT: $k = $got（要求 $v）"; incr ng }
}
dump_ip_params $xfft $outdir/xfft_params.rpt
if {$ng > 0} { puts "ERROR: FFT IP の設定が $ng 件、要求どおりにならない"; exit 1 }
generate_target {instantiation_template synthesis} $xfft
# ポート: entity の宣言の中だけを読む（component 宣言は全部のポートを持つ。proj011 で踏んだ）
set want_ports [dict create aclk 1 aresetn 1 s_axis_config_tdata 8 s_axis_config_tvalid 1 s_axis_config_tready 1 \
    s_axis_data_tdata 32 s_axis_data_tvalid 1 s_axis_data_tready 1 s_axis_data_tlast 1 \
    m_axis_data_tdata 64 m_axis_data_tuser 16 m_axis_data_tvalid 1 m_axis_data_tlast 1 \
    event_frame_started 1 event_tlast_unexpected 1 event_tlast_missing 1 event_data_in_channel_halt 1]
set top ""
foreach f [get_files -quiet -of_objects [get_files ${fft_mod}.xci]] { if {[string match "*/synth/${fft_mod}.vhd" $f]} { set top $f } }
if {$top eq ""} { puts "ERROR: FFT IP のトップ（synth/${fft_mod}.vhd）が無い"; exit 1 }
set fh [open $top r]; set txt [read $fh]; close $fh
if {![regexp -nocase -indices "\\mentity\\s+${fft_mod}\\s+is\\M" $txt ent_a]} { puts "ERROR: entity $fft_mod が無い"; exit 1 }
set a0 [lindex $ent_a 1]
if {![regexp -nocase -indices -start $a0 "\\mend\\s+(entity\\s+)?${fft_mod}\\s*;" $txt ent_b]} { puts "ERROR: entity の終わりが無い"; exit 1 }
set ent_txt [string range $txt $a0 [lindex $ent_b 0]]
set have [dict create]
foreach {all name dir hi} [regexp -all -inline -nocase {\m(\w+)\s*:\s*(in|out)\s+std_logic(?:_vector\s*\(\s*(\d+)\s+downto\s+0\s*\))?} $ent_txt] {
    set w [expr {$hi eq "" ? 1 : $hi + 1}]
    if {![dict exists $have [string tolower $name]]} { dict set have [string tolower $name] $w }
}
set ng 0
dict for {n w} $want_ports {
    if {![dict exists $have $n]} { puts "  FFT のポート $n が無い"; incr ng } \
    elseif {[dict get $have $n] != $w} { puts "  FFT のポート $n の幅 [dict get $have $n]（RTL は $w）"; incr ng }
}
if {[dict exists $have m_axis_data_tready]} { puts "  FFT のポート m_axis_data_tready が在る（realtime なら無い）"; incr ng }
puts "FFT IP    : $fft_mod 8192 点・bit 反転順・入力 15 bit・unscaled・realtime。ポート [dict size $have] 本、違う $ng 件"
if {$ng > 0} { exit 1 }
update_compile_order -fileset sources_1

# ------------------------------------------------------------------ block design
create_bd_design $bd_name

# ---- PS ----
source [file normalize ./src/board/ps_preset.tcl]
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e zynq_ultra_ps_e_0]
if {[get_property VLNV $ps] ne $ps_preset_vlnv} { puts "ERROR: PS の VLNV [get_property VLNV $ps] が ps_preset.tcl の $ps_preset_vlnv と違う"; exit 1 }
set_property -dict $ps_preset $ps
set ng 0
foreach {k v} $ps_preset { if {[get_property $k $ps] ne $v} { incr ng; puts "  PS PRESET 違う: $k = [get_property $k $ps]（要求 $v）" } }
set nd 0
foreach {k v} $ps_preset_derived { set got ""; catch {set got [get_property $k $ps]}; if {$got ne $v} { incr nd } }
puts [format "PS PRESET : 当てた %d 個のうち違う %d 個 / 導出 %d 個のうち違う %d 個" [expr {[llength $ps_preset] / 2}] $ng [expr {[llength $ps_preset_derived] / 2}] $nd]
if {$ng > 0} { puts "ERROR: PS にプリセットが当たっていない"; exit 1 }
# 使う AXI は HPM0_FPD（制御）と HP0_FPD（リング、128 bit）。**使わないものも明示的に 0 にする**（proj002 の BD 41-758）
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
foreach {k want} {CONFIG.PSU__USE__S_AXI_GP2 1 CONFIG.PSU__SAXIGP2__DATA_WIDTH 128 CONFIG.PSU__USE__S_AXI_GP0 0 CONFIG.PSU__USE__S_AXI_GP3 0} {
    if {[get_property $k $ps] != $want} { puts "ERROR: PS の $k が [get_property $k $ps]（要求 $want）"; exit 1 }
}

# ---- RFDC（proj024 と同じ順序: スライスを有効 → 使わないものを落とす → スライス → PLL・fs・Refclk・Outclk → 残り。最後に読み返す）----
set rfdc [create_bd_cell -type ip -vlnv xilinx.com:ip:usp_rf_data_converter rfdc]
set on {}
foreach ch $chans { lassign $ch t s; lappend on CONFIG.ADC_Slice${t}${s}_Enable {true} }
cfg_apply rfdc $on 0
set off {}
foreach t {0 1 2 3} {
    foreach sl {0 2} {
        if {[lsearch -exact $chans [list $t $sl]] < 0} { lappend off CONFIG.ADC_Slice${t}${sl}_Enable {false} }
        lappend off CONFIG.DAC_Slice${t}${sl}_Enable {false}
    }
}
cfg_apply rfdc $off 0
foreach t $adc_tiles {
    set d {}
    foreach ch $chans {
        lassign $ch tt s
        if {$tt != $t} continue
        set S "${t}${s}"
        lappend d CONFIG.ADC_Data_Type${S} {0} CONFIG.ADC_Data_Width${S} $spw_adc CONFIG.ADC_Decimation_Mode${S} {1} CONFIG.ADC_Mixer_Type${S} {1}
    }
    if {[catch {set_property -dict $d $rfdc} msg]} { lappend ::cfg_fail [list "Tile [expr {224 + $t}] のスライス設定" $d [string map {"\n" " "} $msg] 0] }
}
foreach t $adc_tiles {
    cfg_apply rfdc [list CONFIG.ADC${t}_PLL_Enable    {true}]      0
    cfg_apply rfdc [list CONFIG.ADC${t}_Sampling_Rate $fs_gsps]    0
    cfg_apply rfdc [list CONFIG.ADC${t}_Refclk_Freq   $refclk_mhz] 0
    cfg_apply rfdc [list CONFIG.ADC${t}_Outclk_Freq   $outclk_mhz] 0
    cfg_apply rfdc [list CONFIG.ADC${t}_Clock_Source $t CONFIG.ADC${t}_Clock_Dist {0} CONFIG.ADC${t}_Multi_Tile_Sync {false}] 0
}
foreach ch $chans {
    lassign $ch t s
    cfg_apply rfdc [list CONFIG.ADC_Mixer_Mode${t}${s} {2} CONFIG.ADC_NCO_Freq${t}${s} {0} CONFIG.ADC_OBS${t}${s} {false}] 0
}
cfg_report "RFDC の設定（読み返しで検証するので、ここでは止めない）"
dump_ip_params $rfdc $outdir/rfdc_params.rpt
set ng 0
set want {}
foreach t $adc_tiles {
    lappend want CONFIG.ADC${t}_Sampling_Rate $fs_gsps num CONFIG.ADC${t}_Refclk_Freq $refclk_mhz num \
                 CONFIG.ADC${t}_Outclk_Freq $outclk_mhz num CONFIG.ADC${t}_Fabric_Freq $fabric_mhz num
}
foreach ch $chans {
    lassign $ch t s
    lappend want CONFIG.ADC_Data_Type${t}${s} 0 int CONFIG.ADC_Data_Width${t}${s} $spw_adc int \
                 CONFIG.ADC_Decimation_Mode${t}${s} 1 int CONFIG.ADC_Mixer_Type${t}${s} 1 int
}
foreach {k w kind} $want {
    set got ""; catch {set got [get_property $k $rfdc]}
    set ok 0
    if {$kind eq "num"} { if {![catch {expr {abs($got - $w) < 1e-6}} r] && $r} { set ok 1 } } else { if {$got eq $w} { set ok 1 } }
    puts [format "  %-34s = %-12s %s" $k $got [expr {$ok ? "OK" : "違う（要求 $w）"}]]
    if {!$ok} { incr ng }
}
if {$ng > 0} { puts "ERROR: RFDC の設定が $ng 件反映されていない（$outdir/rfdc_params.rpt）"; exit 1 }
set want_hz [expr {double($outclk_mhz) * 1e6}]
foreach t $adc_tiles {
    set hz ""; catch {set hz [get_property CONFIG.FREQ_HZ [BP rfdc/clk_adc${t}]]}
    if {$hz eq "" || abs($hz - $want_hz) > 1.0} { puts "ERROR: clk_adc${t} = '$hz' Hz（要求 $want_hz）"; exit 1 }
    puts "clk_adc${t} = $hz Hz"
}

# ---- Clocking Wizard（clk_out1 = 341.333 MHz ADC ドメイン、clk_out2 = 256 MHz DSP ドメイン）----
set clkw [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz clk_wiz_adc]
cfg_apply clk_wiz_adc [list CONFIG.PRIM_SOURCE {No_buffer} CONFIG.PRIM_IN_FREQ $outclk_mhz \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $fabric_mhz CONFIG.CLKOUT2_USED {true} CONFIG.CLKOUT2_REQUESTED_OUT_FREQ $dsp_mhz \
    CONFIG.USE_LOCKED {true} CONFIG.USE_RESET {true} CONFIG.RESET_TYPE {ACTIVE_LOW} CONFIG.RESET_PORT {resetn}] 0
cfg_report "Clocking Wizard"
foreach {k w} [list CONFIG.PRIM_IN_FREQ $outclk_mhz CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $fabric_mhz CONFIG.CLKOUT2_REQUESTED_OUT_FREQ $dsp_mhz] {
    set got [get_property $k $clkw]
    if {abs($got - $w) > 1e-6} { puts "ERROR: Clocking Wizard: $k 要求 $w / 実際 $got"; exit 1 }
}
proc wiz_actual_check {clkw pairs stage} {
    foreach {n want} $pairs {
        set act ""; catch {set act [get_property CONFIG.CLKOUT${n}_ACTUAL_FREQ $clkw]}
        puts [format "  clk_out%d  要求 %s MHz → 実際 %s MHz（%s）" $n $want [expr {$act eq "" ? "未確定" : $act}] $stage]
        if {$act ne "" && abs($act - $want) > 1e-3} { puts "ERROR: Clocking Wizard の clk_out$n が要求と違う"; exit 1 }
    }
}
set wiz_pairs [list 1 $fabric_mhz 2 $dsp_mhz]
wiz_actual_check $clkw $wiz_pairs "設定直後"

# ---- ギアボックス（proj024 と同じ形。ch は 1 本）----
create_bd_cell -type ip -vlnv xilinx.com:ip:axis_dwidth_converter gb_up_0
cfg_apply gb_up_0 [list CONFIG.S_TDATA_NUM_BYTES [expr {$spw_adc * 2}] CONFIG.M_TDATA_NUM_BYTES [expr {$gb_mid * 2}] CONFIG.HAS_TLAST {0} CONFIG.HAS_TKEEP {0} CONFIG.HAS_TSTRB {0}] 0
create_bd_cell -type ip -vlnv xilinx.com:ip:axis_data_fifo gb_fifo_0
cfg_apply gb_fifo_0 [list CONFIG.TDATA_NUM_BYTES [expr {$gb_mid * 2}] CONFIG.FIFO_DEPTH {32} CONFIG.IS_ACLK_ASYNC {1} CONFIG.HAS_TLAST {0} CONFIG.HAS_TKEEP {0} CONFIG.HAS_TSTRB {0}] 0
cfg_apply gb_fifo_0 [list CONFIG.HAS_RD_DATA_COUNT {1}] 1
create_bd_cell -type ip -vlnv xilinx.com:ip:axis_dwidth_converter gb_dn_0
cfg_apply gb_dn_0 [list CONFIG.S_TDATA_NUM_BYTES [expr {$gb_mid * 2}] CONFIG.M_TDATA_NUM_BYTES [expr {$spw * 2}] CONFIG.HAS_TLAST {0} CONFIG.HAS_TKEEP {0} CONFIG.HAS_TSTRB {0}] 0
cfg_report "ギアボックス"
foreach {k want} {CONFIG.IS_ACLK_ASYNC 1 CONFIG.HAS_RD_DATA_COUNT 1 CONFIG.FIFO_DEPTH 32} {
    if {[get_property $k [get_bd_cells gb_fifo_0]] != $want} { puts "ERROR: gb_fifo_0 の $k が [get_property $k [get_bd_cells gb_fifo_0]]"; exit 1 }
}
foreach {cell pin want} [list gb_up_0 M_AXIS [expr {$gb_mid * 2}] gb_fifo_0 M_AXIS [expr {$gb_mid * 2}] gb_dn_0 M_AXIS [expr {$spw * 2}]] {
    set nb ""; catch {set nb [get_property CONFIG.TDATA_NUM_BYTES [get_bd_intf_pins $cell/$pin]]}
    puts [format "GEARBOX   : %-10s %s = %s B（期待 %s）" $cell $pin $nb $want]
    if {$nb eq "" || $nb != $want} { puts "ERROR: ギアボックスの語幅が違う（$cell）"; exit 1 }
}
set rdc [get_bd_pins -quiet gb_fifo_0/axis_rd_data_count]
if {[llength $rdc] == 0} { puts "ERROR: gb_fifo_0/axis_rd_data_count が無い"; exit 1 }
set rdc_w [expr {[get_property LEFT $rdc] - [get_property RIGHT $rdc] + 1}]
set gba [create_bd_cell -type module -reference gb_adc gb_adc_0]
set_property CONFIG.DW [expr {$spw_adc * 16}] $gba
set gbg [create_bd_cell -type module -reference gb_gate gb_gate_0]
set_property CONFIG.DW [expr {$gb_mid * 16}] $gbg
set_property CONFIG.CW $rdc_w $gbg
if {[get_property CONFIG.DW $gba] != $spw_adc * 16 || [get_property CONFIG.DW $gbg] != $gb_mid * 16 || [get_property CONFIG.CW $gbg] != $rdc_w} {
    puts "ERROR: gb_adc_0 / gb_gate_0 の DW・CW が要求と違う"; exit 1
}
foreach {nm w v} [list gb_tie_hold 1 0 gb_tie_adj 2 0 gb_tie_k 6 $gb_k_rst] {
    set c [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant $nm]
    set_property -dict [list CONFIG.CONST_WIDTH $w CONFIG.CONST_VAL $v] $c
    if {[get_property CONFIG.CONST_WIDTH $c] != $w || [get_property CONFIG.CONST_VAL $c] != $v} { puts "ERROR: $nm の値が要求と違う"; exit 1 }
}

# ---- 自作のセル ----
set tap [create_bd_cell -type module -reference gb_tap gb_tap_0]
set_property CONFIG.DW [expr {$spw * 16}] $tap
if {[get_property CONFIG.DW $tap] != $spw * 16} { puts "ERROR: gb_tap_0 の DW が要求と違う"; exit 1 }
set cs  [create_bd_cell -type module -reference coarse_stage coarse_stage_0]
set ctw [create_bd_cell -type module -reference ct_wr ct_wr_0]
set ctr [create_bd_cell -type module -reference ct_rd ct_rd_0]
set ft  [create_bd_cell -type module -reference fine_top fine_top_0]
foreach {par h nrow ncol} $fine_hex {
    set got ""
    foreach v [list $h "\"$h\""] {
        if {[catch {set_property CONFIG.$par $v $ft}]} continue
        set got [string trim [get_property CONFIG.$par $ft] {"}]
        if {$got eq $h} break
    }
    if {$got ne $h} { puts "ERROR: fine_top_0 の $par が '$got'（要求 $h）"; exit 1 }
}
set rcore [create_bd_cell -type module -reference s45_ring s45_ring_0]
foreach {k want} [list CONFIG.NIN 1 CONFIG.BIT_KIND 28 CONFIG.BIT_REV 1 CONFIG.PROJ $proj_id] {
    set_property $k $want $rcore
    if {[get_property $k $rcore] != $want} { puts "ERROR: s45_ring_0 の $k が [get_property $k $rcore]（要求 $want）"; exit 1 }
}
set cm [create_bd_cell -type module -reference clk_mon clk_mon_0]
# リングの使わない入口（s1〜s3 の tvalid・rec_drop0〜3）は定数 0 を明示してつなぐ（つながないと BD 41-759 の CRITICAL WARNING。1 回目のビルドで出た）
foreach {nm w} {ring_tie0 1 ring_tie00 2} {
    set c [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant $nm]
    set_property -dict [list CONFIG.CONST_WIDTH $w CONFIG.CONST_VAL 0] $c
}

# ---- MIG（S-2f と同じ。実物の部品 MT40A512M16HA-075E・4 GiB）----
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
puts "MIG       : 要求 [expr {[llength $mig_req] / 2}] 個のうち違う $ng 個"
if {$ng > 0} { puts "ERROR: MIG の設定が要求どおりにならない"; exit 1 }
set p_sys [create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:diff_clock_rtl:1.0 sys_clk_ddr4]
set_property CONFIG.FREQ_HZ 200000000 $p_sys
set ibuf [create_bd_cell -type ip -vlnv xilinx.com:ip:util_ds_buf ibufds_ddr4]
set_property CONFIG.C_BUF_TYPE IBUFDS $ibuf
set bufg [create_bd_cell -type ip -vlnv xilinx.com:ip:util_ds_buf bufg_ddr4]
set_property CONFIG.C_BUF_TYPE BUFG $bufg
connect_bd_intf_net $p_sys [get_bd_intf_pins ibufds_ddr4/CLK_IN_D]
nc ibufds_ddr4/IBUF_OUT bufg_ddr4/BUFG_I
nc bufg_ddr4/BUFG_O ddr4_0/c0_sys_clk_i
set p_ddr [create_bd_intf_port -mode Master -vlnv xilinx.com:interface:ddr4_rtl:1.0 ddr4_pl]
connect_bd_intf_net [get_bd_intf_pins ddr4_0/C0_DDR4] $p_ddr
set one [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant one_ui]
set_property -dict [list CONFIG.CONST_WIDTH 1 CONFIG.CONST_VAL 1] $one

# ---- 相互接続 ----
# smc_ctrl: S00 = PS、M00 rfdc・M01 clk_mon_0（pl_clk0）・M02 coarse_stage_0・M03 ct_wr_0・M04 ct_rd_0・M05 fine_top_0・M06 s45_ring_0（DSP）
set smc_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_ctrl]
set_property -dict [list CONFIG.NUM_SI 1 CONFIG.NUM_MI 7 CONFIG.NUM_CLKS 2] $smc_ctrl
# smc_ddr: S00 = ct_wr_0、S01 = ct_rd_0（DSP）→ M00 = ddr4_0（UI クロック）
set smc_ddr [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_ddr]
set_property -dict [list CONFIG.NUM_SI 2 CONFIG.NUM_MI 1 CONFIG.NUM_CLKS 2] $smc_ddr
foreach {c k w} {smc_ctrl CONFIG.NUM_MI 7 smc_ctrl CONFIG.NUM_CLKS 2 smc_ddr CONFIG.NUM_SI 2 smc_ddr CONFIG.NUM_CLKS 2} {
    if {[get_property $k [get_bd_cells $c]] != $w} { puts "ERROR: $c の $k が [get_property $k [get_bd_cells $c]]（要求 $w）"; exit 1 }
}

# ---- リセット ----
set rst_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_ctrl]
set rst_adc  [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_adc]
set rst_dsp  [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_dsp]
set rst_ui   [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_ui]

# ------------------------------------------------------------------ 配線
set ps_clk0 zynq_ultra_ps_e_0/pl_clk0
set ps_rstn zynq_ultra_ps_e_0/pl_resetn0
set adc_fab clk_wiz_adc/clk_out1
set dsp_fab clk_wiz_adc/clk_out2
set ui_clk  ddr4_0/c0_ddr4_ui_clk
nc rfdc/clk_adc2 clk_wiz_adc/clk_in1
nc $ps_rstn clk_wiz_adc/resetn

# **ネットはこの表 1 つから張り、下の照合も同じ表を読む**（proj024 の ch_nets と同じ考え）。{駆動元 {負荷 …}}
proc nets_f5 {} {
    return [list \
        zynq_ultra_ps_e_0/pl_clk0     {rst_ctrl/slowest_sync_clk smc_ctrl/aclk rfdc/s_axi_aclk zynq_ultra_ps_e_0/maxihpm0_fpd_aclk clk_mon_0/clk} \
        clk_wiz_adc/clk_out1          {rst_adc/slowest_sync_clk rfdc/m2_axis_aclk gb_up_0/aclk gb_fifo_0/s_axis_aclk gb_adc_0/aclk} \
        clk_wiz_adc/clk_out2          {rst_dsp/slowest_sync_clk smc_ctrl/aclk1 smc_ddr/aclk gb_fifo_0/m_axis_aclk gb_gate_0/aclk gb_dn_0/aclk
                                       gb_tap_0/aclk coarse_stage_0/clk ct_wr_0/clk ct_rd_0/clk fine_top_0/aclk s45_ring_0/aclk zynq_ultra_ps_e_0/saxihp0_fpd_aclk} \
        ddr4_0/c0_ddr4_ui_clk         {rst_ui/slowest_sync_clk smc_ddr/aclk1 clk_mon_0/ui_clk} \
        clk_wiz_adc/locked            {rst_adc/dcm_locked rst_dsp/dcm_locked} \
        zynq_ultra_ps_e_0/pl_resetn0  {rst_ctrl/ext_reset_in rst_adc/ext_reset_in rst_dsp/ext_reset_in} \
        rst_ctrl/peripheral_aresetn   {smc_ctrl/aresetn rfdc/s_axi_aresetn clk_mon_0/aresetn} \
        rst_ctrl/peripheral_reset     {ddr4_0/sys_rst} \
        rst_adc/peripheral_aresetn    {rfdc/m2_axis_aresetn gb_adc_0/aresetn} \
        rst_dsp/peripheral_aresetn    {gb_gate_0/aresetn gb_dn_0/aresetn coarse_stage_0/aresetn ct_wr_0/aresetn ct_rd_0/aresetn fine_top_0/aresetn s45_ring_0/aresetn} \
        rst_dsp/interconnect_aresetn  {smc_ddr/aresetn} \
        ddr4_0/c0_ddr4_ui_clk_sync_rst {rst_ui/ext_reset_in clk_mon_0/ui_rst} \
        one_ui/dout                   {rst_ui/dcm_locked} \
        rst_ui/peripheral_aresetn     {ddr4_0/c0_ddr4_aresetn} \
        bufg_ddr4/BUFG_O              {clk_mon_0/ref_clk} \
        ddr4_0/c0_init_calib_complete {clk_mon_0/calib} \
        gb_adc_0/gb_rstn              {gb_up_0/aresetn gb_fifo_0/s_axis_aresetn} \
        gb_tie_hold/dout              {gb_adc_0/hold} \
        gb_tie_adj/dout               {gb_adc_0/adj} \
        gb_tie_k/dout                 {gb_gate_0/k} \
        gb_fifo_0/axis_rd_data_count  {gb_gate_0/rd_count} \
        gb_adc_0/adc_out              {gb_gate_0/adc_in} \
        gb_gate_0/gb_stat             {fine_top_0/gb_stat} \
        gb_gate_0/adc_stat            {fine_top_0/adc_stat} \
        gb_tap_0/m_data               {coarse_stage_0/s_data} \
        gb_tap_0/m_valid              {coarse_stage_0/s_valid} \
        coarse_stage_0/m_valid        {ct_wr_0/s_valid} \
        coarse_stage_0/m_y            {ct_wr_0/s_y} \
        ct_wr_0/chunk_done            {ct_rd_0/chunk_done} \
        ct_wr_0/chunk_idx             {ct_rd_0/chunk_idx} \
        ring_tie0/dout                {s45_ring_0/s1_axis_tvalid s45_ring_0/s2_axis_tvalid s45_ring_0/s3_axis_tvalid} \
        ring_tie00/dout               {s45_ring_0/rec_drop0 s45_ring_0/rec_drop1 s45_ring_0/rec_drop2 s45_ring_0/rec_drop3} \
    ]
}
foreach {drv loads} [nets_f5] { foreach p $loads { nc $drv $p } }

# インタフェース
ic [BI rfdc {m22_axis} "RFDC の AXI4-Stream 出力（tile 2 slice 2）"] [BI gb_adc_0 {s_axis S_AXIS} "gb_adc_0 の入力"]
ic [BI gb_adc_0 {m_axis M_AXIS} "gb_adc_0 の出力"] [get_bd_intf_pins gb_up_0/S_AXIS]
ic [get_bd_intf_pins gb_up_0/M_AXIS]   [get_bd_intf_pins gb_fifo_0/S_AXIS]
ic [get_bd_intf_pins gb_fifo_0/M_AXIS] [BI gb_gate_0 {s_axis S_AXIS} "gb_gate_0 の入力"]
ic [BI gb_gate_0 {m_axis M_AXIS} "gb_gate_0 の出力"] [get_bd_intf_pins gb_dn_0/S_AXIS]
ic [get_bd_intf_pins gb_dn_0/M_AXIS] [BI gb_tap_0 {s_axis S_AXIS} "gb_tap_0 の入口"]
ic [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_FPD] [get_bd_intf_pins smc_ctrl/S00_AXI]
set mi 0
foreach {cell what} {rfdc s_axi clk_mon_0 s_axi coarse_stage_0 s_axi ct_wr_0 s_axi ct_rd_0 s_axi fine_top_0 s_axi s45_ring_0 s_axi} {
    ic [get_bd_intf_pins smc_ctrl/M[format %02d $mi]_AXI] [BI $cell [list $what [string toupper $what]] "$cell の AXI4-Lite"]
    incr mi
}
ic [BI ct_wr_0 {m_axi M_AXI} "ct_wr_0 の AXI4"] [get_bd_intf_pins smc_ddr/S00_AXI]
ic [BI ct_rd_0 {m_axi M_AXI} "ct_rd_0 の AXI4"] [get_bd_intf_pins smc_ddr/S01_AXI]
ic [get_bd_intf_pins smc_ddr/M00_AXI] [get_bd_intf_pins ddr4_0/C0_DDR4_S_AXI]
ic [BI ct_rd_0 {m_axis M_AXIS} "ct_rd_0 の出口"] [BI fine_top_0 {s_axis S_AXIS} "fine_top_0 の入口"]
ic [BI fine_top_0 {m_axis M_AXIS} "fine_top_0 の出口"] [BI s45_ring_0 {s0_axis S0_AXIS} "s45_ring_0 の入口 0"]
ic [BI s45_ring_0 {m_axi M_AXI} "s45_ring_0 の書き手"] [get_bd_intf_pins zynq_ultra_ps_e_0/S_AXI_HP0_FPD]

# 外部ポート（RF のアナログ入力・タイルのクロック・SYSREF。専用ピンなので XDC は要らない）
foreach ch $chans {
    lassign $ch t s
    if {$s < 2} { set pair "01" } else { set pair "23" }
    make_bd_intf_pins_external [BI rfdc [list "vin${t}_${pair}" "vin${t}${s}"] "ADC アナログ入力 (tile $t slice $s)"]
}
foreach t $adc_tiles { make_bd_intf_pins_external [BI rfdc [list "adc${t}_clk"] "ADC タイル $t のクロック入力"] }
make_bd_intf_pins_external [BI rfdc {sysref_in} "SYSREF 入力"]

# ------------------------------------------------------------------ 番地
# 自作のセルは先に決めた番地に置き（PS の道具は .hwh の名前で引くが、重ならないことを先に決める）、残り（rfdc・DDR）は assign_bd_address に任せる
set ps_data [get_bd_addr_spaces zynq_ultra_ps_e_0/Data]
set off 0xA0100000
foreach cell {clk_mon_0 coarse_stage_0 ct_wr_0 ct_rd_0 fine_top_0 s45_ring_0} {
    set seg [get_bd_addr_segs -quiet -of_objects [get_bd_intf_pins $cell/s_axi]]
    if {[llength $seg] != 1} { puts "ERROR: $cell/s_axi の番地の区画が 1 個でない（$seg）"; exit 1 }
    assign_bd_address -offset [format 0x%08X $off] -range 4K -target_address_space $ps_data $seg
    set off [expr {$off + 0x1000}]
}
assign_bd_address
set fh [open $outdir/address_map.rpt w]
set wins {}
foreach seg [get_bd_addr_segs -quiet -of_objects $ps_data] {
    set o [get_property OFFSET $seg]; set r [get_property RANGE $seg]
    puts $fh [format "%-64s %s +%s" $seg $o $r]
    puts [format "番地      : %-56s %s +%s" $seg $o $r]
    lappend wins [list $seg [expr {$o}] [expr {$r}]]
}
foreach sp {ct_wr_0/m_axi ct_rd_0/m_axi s45_ring_0/m_axi} {
    foreach seg [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces $sp]] {
        puts $fh [format "%-64s %s +%s" $seg [get_property OFFSET $seg] [get_property RANGE $seg]]
        puts [format "番地      : %-56s %s +%s" $seg [get_property OFFSET $seg] [get_property RANGE $seg]]
    }
}
close $fh
foreach w1 $wins {
    foreach w2 $wins {
        lassign $w1 n1 o1 r1; lassign $w2 n2 o2 r2
        if {$n1 ne $n2 && $o1 < $o2 + $r2 && $o2 < $o1 + $r1} { puts "ERROR: 番地が重なる: $n1 と $n2"; exit 1 }
    }
}
# corner turn の 2 本は MIG の 4 GiB を 0 から見る。リングは PS の DDR（DDR_LOW）を見る
foreach sp {ct_wr_0/m_axi ct_rd_0/m_axi} {
    set seg [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces $sp]]
    if {[llength $seg] != 1 || [get_property OFFSET $seg] != 0 || [get_property RANGE $seg] != 4294967296} {
        puts "ERROR: $sp から MIG が 0 +4G で見えない（$seg）"; exit 1
    }
}
set rddr 0
foreach seg [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces s45_ring_0/m_axi]] { if {[string match "*DDR_LOW*" $seg]} { incr rddr } }
if {$rddr != 1} { puts "ERROR: s45_ring_0/m_axi から PS の DDR_LOW が見えない"; exit 1 }

validate_bd_design
save_bd_design
puts "---- Clocking Wizard の実出力（validate 後）----"
wiz_actual_check $clkw $wiz_pairs "validate 後"
set hz [get_property CONFIG.FREQ_HZ [BP $ps_clk0]]
puts "pl_clk0 = $hz Hz（要求 $ctrl_mhz MHz）"
if {abs($hz - $ctrl_mhz * 1e6) > 1e3} { puts "ERROR: pl_clk0 が要求と違う"; exit 1 }
foreach {cell want} {rst_ui 1 rst_ctrl 0 rst_dsp 0 rst_adc 0} {
    set got [get_property CONFIG.C_EXT_RESET_HIGH [get_bd_cells $cell]]
    puts "リセット  : $cell の ext_reset_in は [expr {$got ? {高} : {低}}] で効く（C_EXT_RESET_HIGH $got）"
    if {$got ne $want} { puts "ERROR: $cell の ext_reset_in の極性が違う（期待 $want）"; exit 1 }
}

# ---- 結線の照合（表 nets_f5 の全部 ＋ 在ってはいけない相手）----
proc net_pins {pin} {
    set n [get_bd_nets -quiet -of_objects [get_bd_pins $pin]]
    if {$n eq ""} { return {} }
    return [lsort [get_bd_pins -quiet -of_objects $n]]
}
set ng 0
set nchk 0
foreach {drv loads} [nets_f5] {
    set got [net_pins $drv]
    foreach p $loads { incr nchk; if {[lsearch -exact $got /$p] < 0} { incr ng; puts "  結線: $drv のネットに $p が無い" } }
}
# 在ってはいけない: ドメインの取り違え・リセットの取り違え
foreach {pin mustnot} {
    ct_wr_0/clk          {/ddr4_0/c0_ddr4_ui_clk /zynq_ultra_ps_e_0/pl_clk0 /clk_wiz_adc/clk_out1}
    ct_rd_0/clk          {/ddr4_0/c0_ddr4_ui_clk /zynq_ultra_ps_e_0/pl_clk0}
    fine_top_0/aclk      {/ddr4_0/c0_ddr4_ui_clk /clk_wiz_adc/clk_out1}
    coarse_stage_0/clk   {/clk_wiz_adc/clk_out1 /zynq_ultra_ps_e_0/pl_clk0}
    smc_ddr/aclk1        {/clk_wiz_adc/clk_out2}
    ct_wr_0/aresetn      {/rst_ui/peripheral_aresetn /rst_ctrl/peripheral_aresetn}
    fine_top_0/aresetn   {/rst_ui/peripheral_aresetn /rst_ctrl/peripheral_aresetn}
    rst_ui/dcm_locked    {/ddr4_0/c0_init_calib_complete}
    clk_mon_0/clk        {/ddr4_0/c0_ddr4_ui_clk /clk_wiz_adc/clk_out2}
    gb_dn_0/aresetn      {/rst_adc/peripheral_aresetn}
} {
    set got [net_pins $pin]
    incr nchk
    if {[llength $got] < 2} { incr ng; puts "  結線: $pin のネットが読めない（$got）" }
    foreach m $mustnot { if {[lsearch -exact $got $m] >= 0} { incr ng; puts "  結線: $pin のネットに $m が在ってはいけない" } }
}
# 陽性対照: 照合の手続きが「無い」と「在ってはいけない」を見つけられること
set pc 0
set got [net_pins ct_wr_0/clk]
if {[lsearch -exact $got /ddr4_0/c0_ddr4_ui_clk] < 0} { incr pc }          ;# 在ってはいけない相手は無い → 数える
if {[lsearch -exact $got /clk_wiz_adc/clk_out2] >= 0} { incr pc }          ;# 在るべき相手は在る → 数える
if {[lsearch -exact [net_pins fine_top_0/aclk] /nonexistent/pin] < 0} { incr pc }
puts "結線の照合: $nchk 項目・違う $ng 個（陽性対照 $pc / 3）"
if {$ng > 0 || $pc != 3} { puts "ERROR: 結線の照合で落ちた"; exit 1 }

# ------------------------------------------------------------------ ラッパ・OOC の run
set bd_file [get_files ${bd_name}.bd]
make_wrapper -files $bd_file -top
add_files -norecurse [glob $projdir/$proj.gen/sources_1/bd/$bd_name/hdl/${bd_name}_wrapper.v]
set_property top ${bd_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

proc run_dir {n} { return [file join $::projdir $::proj.runs $n] }
proc run_crashed {n} {
    set lf [file join [run_dir $n] runme.log]
    if {![file exists $lf]} { return 0 }
    set fh [open $lf r]; set t [read $fh]; close $fh
    return [regexp {Abnormal program termination|segfault in } $t]
}
proc run_state {n} {
    set d [run_dir $n]
    if {[file exists $d/.vivado.error.rst]} { return bad }
    if {[file exists $d/.vivado.end.rst]}   { return done }
    return bad
}
generate_target all $bd_file
create_ip_run $bd_file
# fine_top_0 のラッパに ROM の hex の絶対パスが書かれたか（**在るべき側**）
set vs {}
catch {set vs [split [exec find $projdir -path "*${bd_name}_fine_top_0_0*" -name "*.v"] "\n"]}
foreach {par hex nrow ncol} $fine_hex {
    set hit ""
    set hre [regsub -all {[][{}()*+?.\\^$|]} $hex {\\&}]
    foreach f $vs {
        set fh [open $f r]; set t [read $fh]; close $fh
        if {[regexp "\\.${par}\\s*\\(\\s*\"$hre\"\\s*\\)" $t]} { set hit $f; break }
    }
    if {$hit eq ""} { puts "ERROR: fine_top_0 のラッパに .${par}(\"$hex\") が無い（$vs）"; exit 1 }
    puts "ROM のラッパ: fine_top_0 .$par = \"$hex\""
}
set xf [get_files -quiet [get_property IP_FILE $xfft]]
if {$xf ne "" && [llength [get_runs -quiet ${xfft}_synth_1]] == 0} { create_ip_run $xf }
set ooc [lsort [lmap r [get_runs -quiet -filter {IS_SYNTHESIS && NAME != synth_1}] {string cat $r}]]
puts "OOC 合成  : [llength $ooc] 個を先に回す"
launch_runs [get_runs -filter {IS_SYNTHESIS && NAME != synth_1}] -jobs $jobs
foreach n $ooc { catch {wait_on_run [get_runs $n]} }
for {set try 1} {$try <= 2} {incr try} {
    set bad [lmap n $ooc { expr {[run_state $n] eq "bad" ? $n : [continue]} }]
    if {[llength $bad] == 0} break
    foreach n $bad {
        if {![run_crashed $n] && [file exists [file join [run_dir $n] runme.log]]} { puts "ERROR: OOC の合成 $n が失敗（落ちた印が無い）"; exit 1 }
    }
    puts "NOTE: 回し直す（$try 回目）: $bad"
    foreach n $bad { reset_run [get_runs $n] }
    launch_runs [get_runs $bad] -jobs [expr {min($jobs, 4)}]
    foreach n $bad { catch {wait_on_run [get_runs $n]} }
}
set bad [lmap n $ooc { expr {[run_state $n] eq "bad" ? $n : [continue]} }]
if {[llength $bad] > 0} { puts "ERROR: OOC の合成が通らない: $bad"; exit 1 }
# 自作のセルの run: ドライバの無いネット（Synth 8-3848）・$readmemh の失敗で止める
set nd 0; set seen 0; set rm 0
foreach n $ooc {
    if {![regexp {^system_(coarse_stage|ct_wr|ct_rd|fine_top|s45_ring|clk_mon|gb_adc|gb_gate|gb_tap)_} $n]} continue
    incr seen
    set fh [open [file join [run_dir $n] runme.log] r]; set t [read $fh]; close $fh
    foreach line [split $t "\n"] {
        if {[string match "*Synth 8-3848*" $line]} { puts "  $n: $line"; incr nd }
        if {[regexp -nocase {Synth 8-4445|could not open .*readmem|readmem.*(not found|cannot|could not)} $line]} { puts "  $n: $line"; incr rm }
    }
}
puts "自作のセル: OOC の run $seen 個（期待 9）・Synth 8-3848 $nd 行・\$readmemh の失敗 $rm 行"
if {$seen != 9 || $nd > 0 || $rm > 0} { puts "ERROR: 自作のセルの合成で止める"; exit 1 }

# ------------------------------------------------------------------ 合成〜ビットストリーム
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
catch {wait_on_run impl_1}
for {set try 1} {$try <= 2 && [get_property PROGRESS [get_runs impl_1]] ne "100%"} {incr try} {
    set redo ""
    foreach n {synth_1 impl_1} { if {[run_crashed $n]} { set redo $n; break } }
    if {$redo eq ""} { break }
    puts "NOTE: $redo で Vivado が落ちた。回し直す（$try 回目）"
    reset_run [get_runs $redo]
    launch_runs impl_1 -to_step write_bitstream -jobs $jobs
    catch {wait_on_run impl_1}
}
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} { puts "ERROR: impl_1 が完走していない（$projdir の run のログ）"; exit 1 }
open_run impl_1

# ---- 足の配置（S-2f と同じ 5 本）----
set ng 0
foreach {pname want} {sys_clk_ddr4_clk_p G13 ddr4_pl_act_n B14 {ddr4_pl_dq[0]} K17 ddr4_pl_reset_n E14 {ddr4_pl_adr[0]} B13} {
    set prt [get_ports -quiet $pname]
    if {[llength $prt] == 0} { incr ng; puts "  足: ポート $pname が無い"; continue }
    set got [get_property PACKAGE_PIN $prt]
    if {$got ne $want} { incr ng; puts "  足: $pname が $got（期待 $want）" }
}
if {$ng > 0} { puts "ERROR: 足の配置が違う"; exit 1 }
# ---- clk_mon の同期器の false path の相手（S-2 と同じ）----
set n_sync [llength [get_cells -quiet -hierarchical -filter {NAME =~ */clk_mon_0/inst/s_ref_reg[0] || NAME =~ */clk_mon_0/inst/s_ui_reg[0] || NAME =~ */clk_mon_0/inst/s_cal_reg[0] || NAME =~ */clk_mon_0/inst/s_rst_reg[0]}]]
puts "clk_mon の同期器の 1 段目: $n_sync 個（期待 4）"
if {$n_sync != 4} { puts "ERROR: clk_mon.xdc の false path の相手が 4 個でない"; exit 1 }
# ---- ROM が BRAM で残ったか（中身が 0 なら ROM は消える）。予言: 係数 4・ひねり係数 11.5（F-1・F-2 の OOC）----
foreach {cell pred} {fine_top_0/inst/u_core/u_pfb/u_coef 4 fine_top_0/inst/u_core/u_tw 11.5} {
    set n36 0; set n18 0
    foreach x [get_cells -quiet -hierarchical -filter {REF_NAME =~ RAMB36*}] { if {[string first "/$cell/" "/$x"] >= 0} { incr n36 } }
    foreach x [get_cells -quiet -hierarchical -filter {REF_NAME =~ RAMB18*}] { if {[string first "/$cell/" "/$x"] >= 0} { incr n18 } }
    set eq [expr {$n36 + $n18 / 2.0}]
    puts [format "ROM の BRAM: %-40s RAMB36 換算 %.1f（予言 %s）" $cell $eq $pred]
    if {$eq < $pred / 2.0} { puts "ERROR: $cell の BRAM が予言の半分に届かない"; exit 1 }
}
set nfft [llength [get_cells -quiet -hierarchical -filter {REF_NAME == lane_fft_f || ORIG_REF_NAME == lane_fft_f}]]
puts "lane_fft_f: $nfft 個（期待 16）"
if {$nfft != 16} { puts "ERROR: lane_fft_f が 16 個でない"; exit 1 }

report_timing_summary -file $outdir/timing.rpt
report_utilization    -file $outdir/utilization.rpt
report_utilization -hierarchical -hierarchical_depth 4 -file $outdir/utilization_hier.rpt
report_clocks         -file $outdir/clocks.rpt
report_drc            -file $outdir/drc.rpt
catch {report_cdc -details -file $outdir/cdc.rpt}

set seen 0
foreach lf [lsort [glob -nocomplain $projdir/$proj.runs/*/runme.log]] {
    set fh [open $lf r]
    foreach line [split [read $fh] \n] { if {[string match "CRITICAL WARNING*" $line]} { puts "  [file tail [file dirname $lf]]: $line"; incr seen } }
    close $fh
}
if {[info exists ::env(VIVADO_LOG)] && [file exists $::env(VIVADO_LOG)]} {
    set fh [open $::env(VIVADO_LOG) r]
    foreach line [split [read $fh] \n] { if {[string match "CRITICAL WARNING*" $line]} { puts "  vivado.log: $line"; incr seen } }
    close $fh
}
puts "CRITICAL WARNING: $seen 件"
set u [report_utilization -return_string]
proc uf {txt label} { if {[regexp -line "^\\|\\s*${label}\\*?\\s*\\|\\s*(\\d+(?:\\.\\d+)?)\\s*\\|\\s*\\d+\\s*\\|\\s*\\d+\\s*\\|\\s*\\d+\\s*\\|\\s*([\\d.]+)" $txt -> n p]} { return "$n（$p %）" }; return "?" }
puts "資源      : DSP [uf $u DSPs]・LUT [uf $u {CLB LUTs}]・FF [uf $u {CLB Registers}]・BRAM [uf $u {Block RAM Tile}]・URAM [uf $u URAM]"
set wns [get_property STATS.WNS [get_runs impl_1]]
set whs [get_property STATS.WHS [get_runs impl_1]]
puts "TIMING (確定): WNS $wns ns・WHS $whs ns"
if {$wns < 0 || $whs < 0} { puts "ERROR: タイミングが閉じていない（.bit は $projdir に在るが build-f5/ には写さない）"; exit 1 }

set bit [lindex [glob -nocomplain $projdir/$proj.runs/impl_1/${bd_name}_wrapper.bit] 0]
if {$bit eq ""} { puts "ERROR: .bit が無い"; exit 1 }
file copy -force $bit $outdir/$proj.bit
set hwh [lindex [glob -nocomplain $projdir/$proj.gen/sources_1/bd/$bd_name/hw_handoff/${bd_name}.hwh] 0]
if {$hwh eq ""} { puts "ERROR: .hwh が無い"; exit 1 }
file copy -force $hwh $outdir/$proj.hwh
puts "=== wrote $outdir/$proj.bit・$outdir/$proj.hwh ==="
