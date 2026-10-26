# SPDX-License-Identifier: BSD-3-Clause
# proj024 — 2G のレーン FFT を 1 個ずつ OOC 合成して資源を数える（make survey = S-1）
#
# proj022 の tools/ip_survey.tcl の型（設定の要求・読み返しの照合・物差し・表）をそのまま使い、数える行だけを替えた。
# **既製 IP の資源は、IP を 1 個だけ合成して数えてから予言する**（proj010・022）。estimate.py の FFT_IP の表はこの結果で置き換える。
#
# 数えるもの（どれも固定長・realtime・unscaled・入力 15 bit・use_mults_resources・use_luts。proj023 の lane_fft_w と同じ設定で、長さと出力順だけ違う）:
#   ruler_lane2048_nat     物差し: proj023 の lane_fft_w そのもの（ビルド 11 で 1 個あたり DSP 27・BRAM 8）。DSP と BRAM が合うこと
#   lane2048_rev           出力順だけを bit 反転順に（出口の並べ替えの記憶がどれだけかを、実測のある長さで見る）
#   lane4096/8192/16384_nat・_rev   2G-4・2G-2・2G-1 のレーン FFT（estimate.py の仮の値を置き換える）
#   lane4096_rev_in17      案 R の前段の後（|a| ≦ 4·max|y| → 17 bit）をそのまま入れる場合
#
# 出力: build-survey/survey.txt（表）/ util_<名前>.rpt / params_<名前>.rpt（IP の全 CONFIG。要求どおりになった証拠）

set part   xczu48dr-ffvg1517-2-e
if {[info exists ::env(PART)] && $::env(PART) ne ""} { set part $::env(PART) }
set which s1
set outdir ./build-survey
set jobs 8
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }
set dsp_mhz 256

# {名前  点数  入力 bit  出力順}
set variants {
    {ruler_lane2048_nat    2048 15 natural_order}
    {lane2048_rev          2048 15 bit_reversed_order}
    {lane4096_nat          4096 15 natural_order}
    {lane4096_rev          4096 15 bit_reversed_order}
    {lane8192_nat          8192 15 natural_order}
    {lane8192_rev          8192 15 bit_reversed_order}
    {lane16384_nat        16384 15 natural_order}
    {lane16384_rev        16384 15 bit_reversed_order}
    {lane4096_rev_in17     4096 17 bit_reversed_order}
}

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

puts "PART : $part"
puts "SURVEY: $which → $outdir"
puts "JOBS : $jobs"
create_project survey $outdir/vivado -part $part -force

set ng 0
foreach v $variants {
    lassign $v name n in_w order
    create_ip -name xfft -vendor xilinx.com -library ip -module_name $name
    set ip [get_ips $name]
    set req [fft_req $n $in_w $order $dsp_mhz]
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
    puts "ERROR: FFT IP の設定が $ng 件、要求どおりにならない（$outdir/params_*.rpt を見る）"
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
    lassign $v name n in_w order
    open_run ${name}_synth_1 -name $name
    set rpt [report_utilization -return_string]
    set fh [open $outdir/util_$name.rpt w]; puts $fh $rpt; close $fh
    set dsp [llength [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E2}]]
    lappend rows [list $name $n $in_w [expr {$order eq "natural_order" ? "nat" : "rev"}] $dsp \
        [util_field $rpt "CLB LUTs"] [util_field $rpt "CLB Registers"] \
        [util_field $rpt "Block RAM Tile"] [util_field $rpt "URAM"]]
    close_design
}

set fh [open $outdir/survey.txt w]
set fmt "%-22s %6s %4s %4s %5s %7s %7s %6s %5s"
foreach ch [list stdout $fh] {
    puts $ch ""
    puts $ch "---- FFT IP 1 個の資源（固定長・realtime・unscaled）。OOC 合成後 ----"
    puts $ch [format $fmt 名前 点数 入力 順 DSP LUT FF BRAM URAM]
    foreach r $rows { puts $ch [format $fmt {*}$r] }
}
set ruler ""
foreach r $rows { if {[lindex $r 0] eq "ruler_lane2048_nat"} { set ruler [list [lindex $r 4] [lindex $r 7]] } }
foreach ch [list stdout $fh] {
    puts $ch ""
    if {$ruler eq [list 27 8]} {
        puts $ch "物差し: ruler_lane2048_nat = DSP 27・BRAM 8（proj023 の lane_fft_w のビルド 11 と同じ）→ この表は本番の予言に使える"
    } else {
        puts $ch "**物差し: ruler_lane2048_nat = DSP・BRAM $ruler で、proj023 の lane_fft_w（27・8）と合わない。**"
        puts $ch "  OOC 単体と本番とで数えているものが違うか、版・設定が違う。他の行を予言に使わないこと"
    }
    puts $ch "E-1 へ: python3 tools/estimate.py --fft '点数,nat|rev,DSP,LUT,FF,BRAM' を行ごとに（何回でも）"
}
close $fh
puts ""
puts "=== survey 完了: $outdir/survey.txt ==="
