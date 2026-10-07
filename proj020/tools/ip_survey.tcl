# SPDX-License-Identifier: BSD-3-Clause
# proj014 — 窓の切り出しで使う FFT IP を 1 個ずつ OOC 合成して資源を数える（make survey）
#
# proj011 の ip_survey.tcl の型。**既製 IP の資源は、IP を 1 個だけ合成して数えてから予言する**
# （proj010: 自作部分の見積もりは当たり、IP の中身で外れた）。
#
# 数えるもの:
#   win4096_*   ③ 狭帯域の窓ごとの FFT（複素 4096 点、W = 256 MHz なら 1 サンプル / クロック）。乗算器とバタフライを 3 通り
#   lane2048_*  ② 広帯域のレーン FFT（16 レーン × 2048 点 = 32768 点）。固定長と、実行時の長さ切り替え（512〜2048）の 2 通り
#   ruler_*     物差し: proj011〜013 の lane_fft（512 点・入力 14 bit・realtime・use_mults_resources・use_luts）
#
# **物差しの検証**: ruler の DSP が proj012/013 の本番の 21 / 個（FFT 64 個で 1344）と合わなければ、
# OOC 単体と本番とで数えているものが違うので、他の行の数字を本番の予言に使わない。
#
# 出力: build-survey/survey.txt（表）/ util_<名前>.rpt / params_<名前>.rpt（IP の全 CONFIG。要求どおりになった証拠）
# 資源だけを見る。OOC 合成後のタイミングは配置前の見積もりなので表に出さない。

set part   xczu48dr-ffvg1517-2-e
if {[info exists ::env(PART)] && $::env(PART) ne ""} { set part $::env(PART) }
set outdir ./build-survey
set jobs 8
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }
set dsp_mhz 256

# {名前  点数  入力 bit  乗算器  バタフライ  実行時の長さ切り替え}
set variants {
    {ruler_lane512_res_lut     512 14 use_mults_resources   use_luts             false}
    {win4096_res_lut          4096 18 use_mults_resources   use_luts             false}
    {win4096_res_dsp          4096 18 use_mults_resources   use_xtremedsp_slices false}
    {win4096_perf_dsp         4096 18 use_mults_performance use_xtremedsp_slices false}
    {lane2048_res_lut         2048 14 use_mults_resources   use_luts             false}
    {lane2048rtc_res_lut      2048 14 use_mults_resources   use_luts             true}
}

proc fft_req {n in_w cmul bfly rtc clk_mhz} {
    return [list \
        CONFIG.transform_length                       $n                     1 \
        CONFIG.implementation_options                 pipelined_streaming_io 1 \
        CONFIG.data_format                            fixed_point            1 \
        CONFIG.input_width                            $in_w                  1 \
        CONFIG.scaling_options                        unscaled               1 \
        CONFIG.output_ordering                        natural_order          1 \
        CONFIG.xk_index                               true                   1 \
        CONFIG.throttle_scheme                        realtime               1 \
        CONFIG.aresetn                                true                   1 \
        CONFIG.run_time_configurable_transform_length $rtc                   1 \
        CONFIG.cyclic_prefix_insertion                false                  1 \
        CONFIG.channels                               1                      1 \
        CONFIG.complex_mult_type                      $cmul                  1 \
        CONFIG.butterfly_type                         $bfly                  1 \
        CONFIG.target_clock_frequency                 $clk_mhz               0 \
        CONFIG.phase_factor_width                     18                     0 \
        CONFIG.rounding_modes                         convergent_rounding    0 \
        CONFIG.ovflo                                  false                  0 \
    ]
}

puts "PART : $part"
puts "JOBS : $jobs"
create_project survey $outdir/vivado -part $part -force

set ng 0
foreach v $variants {
    lassign $v name n in_w cmul bfly rtc
    create_ip -name xfft -vendor xilinx.com -library ip -module_name $name
    set ip [get_ips $name]
    set req [fft_req $n $in_w $cmul $bfly $rtc $dsp_mhz]
    set known [list_property $ip]
    foreach {k val fatal} $req {
        if {[lsearch -exact $known $k] < 0} {
            puts "  $name: $k はこの IP に無い"; if {$fatal} { incr ng }; continue
        }
        if {[catch {set_property $k $val $ip} msg]} {
            puts "  $name: $k = $val を設定できない: $msg"; if {$fatal} { incr ng }
        }
    }
    foreach {k val fatal} $req {
        set got ""; catch {set got [get_property $k $ip]}
        if {![string equal -nocase $got $val] && $fatal} {
            puts "  $name: $k = $got（要求 $val）"; incr ng
        }
    }
    set fh [open $outdir/params_$name.rpt w]
    foreach k [lsort [list_property $ip CONFIG.*]] { puts $fh [format "%-50s %s" $k [get_property $k $ip]] }
    close $fh
    generate_target {instantiation_template synthesis} $ip
    create_ip_run $ip
}
if {$ng > 0} {
    puts "ERROR: FFT IP の設定が $ng 件、要求どおりにならない（build-survey/params_*.rpt を見る）"
    exit 1
}

set runs {}
foreach v $variants { lappend runs [get_runs [lindex $v 0]_synth_1] }
launch_runs $runs -jobs $jobs
foreach r $runs { wait_on_run $r }
foreach r $runs {
    if {[get_property PROGRESS $r] ne "100%" || [string match "*ERROR*" [get_property STATUS $r]]} {
        puts "ERROR: $r が完走しなかった（[get_property STATUS $r]）"
        puts "  proj012/013 で、OOC の合成が 0 errors で終わった後に Vivado が segfault する落ち方が 2 回あった。"
        puts "  $outdir/vivado/survey.runs/*/runme.log の末尾が Abnormal program termination なら、もう一度 make survey"
        exit 1
    }
}

proc util_field {txt label} {
    if {[regexp -line "^\\|\\s*${label}\\*?\\s*\\|\\s*(\\d+(?:\\.\\d+)?)\\s*\\|" $txt -> n]} { return $n }
    return "?"
}
set rows {}
foreach v $variants {
    lassign $v name n in_w cmul bfly rtc
    open_run ${name}_synth_1 -name $name
    set rpt [report_utilization -return_string]
    set fh [open $outdir/util_$name.rpt w]; puts $fh $rpt; close $fh
    set dsp [llength [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E2}]]
    lappend rows [list $name $n $in_w $rtc $dsp \
        [util_field $rpt "CLB LUTs"] [util_field $rpt "CLB Registers"] \
        [util_field $rpt "Block RAM Tile"] [util_field $rpt "URAM"]]
    close_design
}

set fh [open $outdir/survey.txt w]
set fmt "%-22s %5s %4s %5s %5s %7s %7s %6s %5s"
foreach ch [list stdout $fh] {
    puts $ch ""
    puts $ch "---- FFT IP 1 個の資源（realtime・unscaled・natural order）。OOC 合成後 ----"
    puts $ch [format $fmt 名前 点数 入力 RTC DSP LUT FF BRAM URAM]
    foreach r $rows { puts $ch [format $fmt {*}$r] }
}
set base ""
foreach r $rows { if {[lindex $r 0] eq "ruler_lane512_res_lut"} { set base [lindex $r 4] } }
foreach ch [list stdout $fh] {
    puts $ch ""
    if {$base == 21} {
        puts $ch "物差し: ruler の DSP = $base（proj012/013 の本番の 21 / 個と一致）→ この表は本番の予言に使える"
    } else {
        puts $ch "**物差し: ruler の DSP = $base で、proj012/013 の本番の 21 / 個と合わない。**"
        puts $ch "  OOC 単体と本番とで数えているものが違う。他の行の数字を本番の予言に使わないこと"
    }
    puts $ch "③: win4096 × 16（4 ADC × 4 窓）＋ 自作部分（make model の「資源の見当」と PFB の 32 点 FFT）"
    puts $ch "②: lane2048 × 64（4 ADC × 16 レーン）＋ proj013 の自作部分（ひねり係数・16 点 DFT・電力・積分は ch を選ぶぶん増える）"
}
close $fh
puts ""
puts "=== survey 完了: $outdir/survey.txt ==="
