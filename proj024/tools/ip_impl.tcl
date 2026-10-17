# SPDX-License-Identifier: BSD-3-Clause
# proj024 — レーン FFT を 1 個ずつ OOC で配置配線し、`-1`・256 MHz で閉じるかを見る（make s2 = S-2）
#
# S-1（ip_survey.tcl）は合成だけで、タイミングは見ていない。2G-1 の 16384 点の IP が `-1` で閉じるかは、RTL を書く前に知りたい唯一の不確かさ。
# IP の設定は S-1 と同じ（fft_req を写した。固定長・realtime・unscaled・入力 15 bit）。part は実機の .bit と同じ -1（VERSIONS.md、proj015 以降）。
#
# 数えるもの（名前・点数・出力順・クロックの周期 ns）:
#   ruler2048_nat     物差し: proj023 の lane_fft_w。ビルド 11 では本番の中で閉じている（WNS +0.001 ns は IP の外の経路）
#   lane8192_rev      2G-2
#   lane16384_rev     2G-1
#   pc16384_400       陽性対照: 16384 点を 2.5 ns（400 MHz）で。**負になるはず**（ならなければクロックが効いていない）
# 戦略: Default と Explore（opt・place・phys_opt・route の -directive Explore）。OOC なので入出力の口の経路は数えない（内部のレジスタ間だけ）
#
# 照合（違えば exit 1）: 設定が要求どおり / 合成が完走 / aclk のクロックが 1 本で周期が要求どおり / 時間を見た経路がある / 陽性対照が負
# 出力: build-s2/s2.txt（表）/ timing_<名前>_<戦略>.rpt（上位 10 経路）/ params_<名前>.rpt

set part   xczu48dr-ffvg1517-1-e
if {[info exists ::env(PART)] && $::env(PART) ne ""} { set part $::env(PART) }
set outdir ./build-s2
set jobs 4
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }

# {名前  点数  出力順  周期 ns}
set variants {
    {ruler2048_nat   2048 natural_order      3.906}
    {lane8192_rev    8192 bit_reversed_order 3.906}
    {lane16384_rev  16384 bit_reversed_order 3.906}
    {pc16384_400    16384 bit_reversed_order 2.500}
}
set strategies {Default Explore}

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
puts "S-2  : → $outdir"
file mkdir $outdir
create_project s2 $outdir/vivado -part $part -force

set ng 0
foreach v $variants {
    lassign $v name n order per
    # IP の設定は全部 256 MHz（本番と同じ）。陽性対照も同じ IP で、配置配線のクロックだけを速くする
    create_ip -name xfft -vendor xilinx.com -library ip -module_name $name
    set ip [get_ips $name]
    set req [fft_req $n 15 $order 256]
    foreach {k val fatal} $req {
        if {[catch {set_property $k $val $ip} msg]} { puts "  $name: $k = $val を設定できない: $msg"; if {$fatal} { incr ng } }
    }
    foreach {k val fatal} $req {
        set got ""; catch {set got [get_property $k $ip]}
        if {![string equal -nocase $got $val] && $fatal} { puts "  $name: $k = $got（要求 $val）"; incr ng }
    }
    set fh [open $outdir/params_$name.rpt w]
    foreach k [lsort [list_property $ip CONFIG.*]] { puts $fh [format "%-50s %s" $k [get_property $k $ip]] }
    close $fh
    generate_target {instantiation_template synthesis} $ip
    create_ip_run $ip
}
if {$ng > 0} { puts "ERROR: FFT IP の設定が $ng 件、要求どおりにならない"; exit 1 }

set runs {}
foreach v $variants { lappend runs [get_runs [lindex $v 0]_synth_1] }
launch_runs $runs -jobs $jobs
foreach r $runs { wait_on_run $r }
foreach r $runs {
    if {[get_property PROGRESS $r] ne "100%" || [string match "*ERROR*" [get_property STATUS $r]]} {
        puts "ERROR: $r が完走しなかった（[get_property STATUS $r]）。runme.log の末尾が Abnormal program termination なら、もう一度 make s2"
        exit 1
    }
}

set rows {}
foreach v $variants {
    lassign $v name n order per
    set dcp [glob -nocomplain $outdir/vivado/s2.runs/${name}_synth_1/${name}.dcp]
    if {$dcp eq ""} { puts "ERROR: $name の合成の dcp が無い"; exit 1 }
    foreach st $strategies {
        open_checkpoint $dcp
        # ---- クロック: IP の OOC の制約が作ったものを見る。無ければ作る。周期が違えば上書きせず止める ----
        set port [get_ports -quiet aclk]
        if {$port eq ""} { puts "ERROR: $name に aclk の口が無い"; exit 1 }
        set clks [get_clocks -quiet -of_objects $port]
        if {$clks eq ""} {
            create_clock -name aclk -period $per $port
        } elseif {abs([get_property PERIOD $clks] - $per) > 0.001} {
            # IP の OOC の制約の周期と違う（陽性対照、または IP の既定）→ 作り直す。記録に残す
            puts "NOTE: $name の aclk の周期 [get_property PERIOD $clks] ns を $per ns に作り直す"
            create_clock -name aclk -period $per $port
        }
        set clks [get_clocks -of_objects $port]
        if {[llength $clks] != 1 || abs([get_property PERIOD $clks] - $per) > 0.001} {
            puts "ERROR: $name の aclk のクロックが [llength $clks] 本・周期 [get_property PERIOD [lindex $clks 0]] ns（要求 $per）"; exit 1
        }
        if {$st eq "Default"} {
            opt_design; place_design; phys_opt_design; route_design
        } else {
            opt_design -directive Explore; place_design -directive Explore
            phys_opt_design -directive Explore; route_design -directive Explore
        }
        set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
        set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
        set nfail [llength [get_timing_paths -quiet -max_paths 100000 -slack_lesser_than 0 -setup]]
        set nseq [llength [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL}]]
        if {$wns eq "" || $nseq == 0} { puts "ERROR: $name $st で時間を見た経路が無い（WNS '$wns'、順序回路 $nseq 個）"; exit 1 }
        set wp [get_timing_paths -max_paths 1 -nworst 1 -setup]
        set from [get_property REF_NAME [get_cells -quiet -of_objects [get_property STARTPOINT_PIN $wp]]]
        set to   [get_property REF_NAME [get_cells -quiet -of_objects [get_property ENDPOINT_PIN $wp]]]
        set lvl  [get_property LOGIC_LEVELS $wp]
        set ndel [format %.3f [get_property DATAPATH_DELAY $wp]]
        report_timing -max_paths 10 -nworst 1 -setup -file $outdir/timing_${name}_${st}.rpt
        set u [report_utilization -return_string]
        set lut "?"; regexp {\|\s*CLB LUTs\*?\s*\|\s*(\d+)} $u -> lut
        lappend rows [list $name $n $per $st [format %+.3f $wns] [format %+.3f $whs] $nfail "$from→$to" $lvl $ndel $lut]
        close_design
    }
}

set fh [open $outdir/s2.txt w]
set fmt "%-15s %6s %6s %-8s %8s %8s %6s %-26s %4s %7s %6s"
foreach ch [list stdout $fh] {
    puts $ch ""
    puts $ch "---- FFT IP 1 個の OOC 配置配線（part $part）。内部のレジスタ間だけ ----"
    puts $ch [format $fmt 名前 点数 周期ns 戦略 WNS WHS 負の数 最悪経路（始→終） 段 遅延ns LUT]
    foreach r $rows { puts $ch [format $fmt {*}$r] }
}
# 陽性対照は負であること
set pc_ok 1
foreach r $rows { if {[string match pc* [lindex $r 0]] && [lindex $r 4] >= 0} { set pc_ok 0 } }
foreach ch [list stdout $fh] {
    puts $ch ""
    if {$pc_ok} { puts $ch "陽性対照（400 MHz）は負 → クロックは効いている。上の 256 MHz の行は読んでよい" } \
    else        { puts $ch "**陽性対照（400 MHz）が負にならない。クロックか解析が効いていない疑い。256 MHz の行を信用しない**" }
}
close $fh
puts "\n=== S-2 完了: $outdir/s2.txt ==="
if {!$pc_ok} { exit 1 }
