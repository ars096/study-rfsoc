# SPDX-License-Identifier: BSD-3-Clause
# proj011 — FFT IP（lane_fft と同じ設定）を 1 個ずつ OOC 合成して資源を数える（make survey）
#
# **proj010 の教訓: 資源の予言は自作部分では当たり、既製 IP の中身で外れた**
# （DSP 予言 20〜45 / 個 → 実際 50）。本番のビルド（make、1 回 40 分級）の前に、IP 単体で数える。
#
# 8 通り = throttle {nonrealtime realtime} × 乗算器 {performance resources} × バタフライ {xtremedsp luts}
# 設定は src/fft_cfg.tcl の fft_req（build.tcl と同じもの）。**違うのは throttle / 乗算器 / バタフライだけ。**
#
# **物差しの検証**: nonrealtime / use_mults_performance / use_xtremedsp_slices は proj010 の lane_fft そのもの。
# proj010 の配置配線後の実測は **DSP 50 / 個**（800 / 16）。これと合わなければ、
# OOC 単体と本番とで数え方が違う（階層をまたぐ最適化など）ので、他の 7 通りの数字も本番の予言には使わない。
#
# 出力: build-survey/survey.txt（表）/ build-survey/util_<名前>.rpt（1 通りずつ）
#       build-survey/params_<名前>.rpt（IP の全 CONFIG。要求どおりになったかの証拠）
#
# 資源だけを見る。OOC 合成後のタイミングは配置前の見積もりなので**表に出さない**（数字があると比べたくなる）。

set part   xczu48dr-ffvg1517-2-e
if {[info exists ::env(PART)] && $::env(PART) ne ""} { set part $::env(PART) }
set outdir ./build-survey
set jobs 8
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }

source ./src/fft_cfg.tcl
# build.tcl と同じ値（build.tcl の「分光計」の段と対）
set fft_lane_n 512
set fft_in_w   14
set dsp_mhz    256.000

set variants {}
foreach thr {nonrealtime realtime} {
    foreach cmul {use_mults_performance use_mults_resources} {
        foreach bfly {use_xtremedsp_slices use_luts} {
            lappend variants [list $thr $cmul $bfly]
        }
    }
}
proc vname {thr cmul bfly} {
    return [format "fft_%s_%s_%s" \
        [expr {$thr eq "realtime" ? "rt" : "nrt"}] \
        [string map {use_mults_performance perf use_mults_resources res use_luts lut} $cmul] \
        [string map {use_xtremedsp_slices dsp use_luts lut} $bfly]]
}

puts "PART : $part"
puts "JOBS : $jobs"
create_project survey $outdir/vivado -part $part -force

# ---- IP を 8 個作る。設定は 1 つずつ投げて読み返す（build.tcl と同じ流儀）----
set ng 0
foreach v $variants {
    lassign $v thr cmul bfly
    set name [vname $thr $cmul $bfly]
    create_ip -name xfft -vendor xilinx.com -library ip -module_name $name
    set ip [get_ips $name]
    set req [fft_req $thr $cmul $bfly $fft_lane_n $fft_in_w $dsp_mhz]
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

# ---- OOC 合成を並列で ----
set runs {}
foreach v $variants { lappend runs [get_runs [vname {*}$v]_synth_1] }
launch_runs $runs -jobs $jobs
foreach r $runs { wait_on_run $r }
foreach r $runs {
    if {[get_property PROGRESS $r] ne "100%" || [string match "*ERROR*" [get_property STATUS $r]]} {
        puts "ERROR: $r が完走しなかった（[get_property STATUS $r]）"
        exit 1
    }
}

# ---- 数える ----
# DSP48E2 はプリミティブを直接数える（report_utilization の表の読み違いを避ける）。LUT / FF / BRAM は表から
proc util_field {txt label} {
    if {[regexp -line "^\\|\\s*${label}\\*?\\s*\\|\\s*(\\d+(?:\\.\\d+)?)\\s*\\|" $txt -> n]} { return $n }
    return "?"
}
set rows {}
foreach v $variants {
    lassign $v thr cmul bfly
    set name [vname $thr $cmul $bfly]
    open_run ${name}_synth_1 -name $name
    set rpt [report_utilization -return_string]
    set fh [open $outdir/util_$name.rpt w]; puts $fh $rpt; close $fh
    set dsp [llength [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E2}]]
    lappend rows [list $name $thr $cmul $bfly $dsp \
        [util_field $rpt "CLB LUTs"] [util_field $rpt "CLB Registers"] [util_field $rpt "Block RAM Tile"] \
        [util_field $rpt "CARRY8"]]
    close_design
}

set fh [open $outdir/survey.txt w]
set hdr [format "%-22s %-12s %-22s %-21s %5s %7s %7s %6s %6s" 名前 throttle 乗算器 バタフライ DSP LUT FF BRAM CARRY8]
foreach ch [list stdout $fh] {
    puts $ch ""
    puts $ch "---- FFT IP 1 個（512 点・入力 14 bit・unscaled）の資源。OOC 合成後 ----"
    puts $ch $hdr
    foreach r $rows { puts $ch [format "%-22s %-12s %-22s %-21s %5s %7s %7s %6s %6s" {*}$r] }
}
# 物差しの検証
set base ""
foreach r $rows { if {[lindex $r 0] eq "fft_nrt_perf_dsp"} { set base [lindex $r 4] } }
foreach ch [list stdout $fh] {
    puts $ch ""
    if {$base == 50} {
        puts $ch "物差し: fft_nrt_perf_dsp の DSP = $base（proj010 の実測 50 / 個と一致）→ この表は本番の予言に使える"
    } else {
        puts $ch "**物差し: fft_nrt_perf_dsp の DSP = $base で、proj010 の実測 50 / 個と合わない。**"
        puts $ch "  OOC 単体と本番とで数えているものが違う。他の行の数字を本番の予言に使わないこと"
    }
    puts $ch "16 個ぶん ＋ 自作部分 144（proj010 の実測）が本番の DSP の予言になる"
}
close $fh
puts ""
puts "=== survey 完了: $outdir/survey.txt ==="
