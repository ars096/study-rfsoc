# SPDX-License-Identifier: BSD-3-Clause
# proj032 P-7 — b1 の後段: 完走した impl_1 を開いて、報告・1PPS の足・資源・CRITICAL WARNING・WNS を見て、.bit と .hwh を build/ へ
#   build.tcl の最後から source する。RESUME=1（make post）なら単独で: プロジェクトを開き、impl_1 が完走していることを確かめてから
#   report_drc は外した（1 回目のビルドで open_run の後の report_drc で親の Vivado が落ちた（segfault）。DRC は write_bitstream の中で走っている）
if {[info exists ::env(RESUME)] && $::env(RESUME) eq "1"} {
    set proj proj032b1; set bd_name system; set outdir ./build
    if {[info exists ::env(OUTDIR)] && $::env(OUTDIR) ne ""} { set outdir ./$::env(OUTDIR) }
    set projdir $outdir/vivado
    open_project $projdir/$proj.xpr
    foreach r {synth_1 impl_1} {
        if {[get_property PROGRESS [get_runs $r]] ne "100%"} { puts "ERROR: $r が完走していない。make build から"; exit 1 }
        if {[get_property NEEDS_REFRESH [get_runs $r]]} { puts "ERROR: $r が古い（ソースが変わった）。make build から"; exit 1 }
    }
}
open_run impl_1
report_timing_summary -file $outdir/timing.rpt
report_utilization    -file $outdir/utilization.rpt
report_utilization -hierarchical -hierarchical_depth 4 -file $outdir/utilization_hier.rpt
report_clocks         -file $outdir/clocks.rpt
report_clock_interaction -file $outdir/clock_interaction.rpt

# 1PPS の足（proj031 の build_post.tcl と同じ）
foreach {pname want} {pps_trig AH13 pps_comp AJ13} {
    set got [get_property PACKAGE_PIN [get_ports $pname]]
    if {$got ne $want} { puts "ERROR: $pname の配置が $got（期待 $want）"; exit 1 }
}
# 資源（OOC の P-6 と比べる: DSP 838・BRAM 224.5・URAM 20 ＋ ギアボックス・リング・時刻）
set ur [report_utilization -return_string]
foreach {name pat} {DSP {DSPs\s*\|\s*([0-9.]+)} BRAM {Block RAM Tile\s*\|\s*([0-9.]+)} URAM {URAM\s*\|\s*([0-9.]+)} LUT {CLB LUTs\*?\s*\|\s*([0-9.]+)}} {
    set v "?"; regexp $pat $ur -> v; puts "資源      : $name $v"
}

# ---- CRITICAL WARNING（run の runme.log と vivado.log）----
set seen 0
foreach lf [lsort [glob -nocomplain $projdir/$proj.runs/*/runme.log]] {
    set fh [open $lf r]
    foreach line [split [read $fh] \n] { if {[string match "CRITICAL WARNING*" $line]} { puts "  [file tail [file dirname $lf]]: $line"; incr seen } }
    close $fh
}
puts "CRITICAL WARNING: $seen 件"

set wns [get_property STATS.WNS [get_runs impl_1]]
set whs [get_property STATS.WHS [get_runs impl_1]]
puts "TIMING (確定): WNS $wns ns・WHS $whs ns"
if {$wns < 0 || $whs < 0} { puts "ERROR: タイミングが閉じていない"; exit 1 }

set bit [lindex [glob -nocomplain $projdir/$proj.runs/impl_1/${bd_name}_wrapper.bit] 0]
if {$bit eq ""} { puts "ERROR: .bit が無い"; exit 1 }
file copy -force $bit $outdir/$proj.bit
set hwh [lindex [glob -nocomplain $projdir/$proj.gen/sources_1/bd/$bd_name/hw_handoff/${bd_name}.hwh] 0]
if {$hwh eq ""} { puts "ERROR: .hwh が無い"; exit 1 }
file copy -force $hwh $outdir/$proj.hwh
puts "sha256 $outdir/$proj.bit: [lindex [exec sha256sum $outdir/$proj.bit] 0]"
puts "=== wrote $outdir/$proj.bit・$outdir/$proj.hwh ==="
