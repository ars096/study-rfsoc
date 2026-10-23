# SPDX-License-Identifier: BSD-3-Clause
# proj028 S-1 — 仮の値を OOC 合成で置き換える（make s1）。part は実機と同じ -1
#   1. RTL（非プロジェクト）: cfft32（荒い FFT、256 MHz）・ct_buf（corner turn の溜め、256 / 300 MHz）
#   2. DDR4 IP（プロジェクト）: 設定を要求し、読み返して照合（違えば exit 1）。全 CONFIG を params_ddr4_pl.rpt に
# 出力: build-s1/s1.txt（表）/ util_<名前>.rpt
set part   xczu48dr-ffvg1517-1-e
set outdir ./build-s1
set jobs 4
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }
file mkdir $outdir

proc util_field {txt label} {
    if {[regexp -line "^\\|\\s*${label}\\*?\\s*\\|\\s*(\\d+(?:\\.\\d+)?)\\s*\\|" $txt -> n]} { return $n }
    return "?"
}
proc count_row {name outdir} {
    set rpt [report_utilization -return_string]
    set fh [open $outdir/util_$name.rpt w]; puts $fh $rpt; close $fh
    set dsp [llength [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E2}]]
    return [list $name $dsp [util_field $rpt "CLB LUTs"] [util_field $rpt "CLB Registers"] \
        [util_field $rpt "Block RAM Tile"] [util_field $rpt "URAM"]]
}
set rows {}

# ---- 1. RTL
foreach {top files clocks} {
    cfft32 {src/cfft32.v} {clk 3.906}
    ct_buf {src/ct_buf.v} {wclk 3.906 rclk 3.333}
} {
    foreach f $files { read_verilog $f }
    synth_design -top $top -part $part -mode out_of_context
    foreach {c p} $clocks { create_clock -name $c -period $p [get_ports $c] }
    set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
    set r [count_row $top $outdir]
    lappend r $wns
    lappend rows $r
    close_design
}

# ---- 2. DDR4 IP
create_project s1 $outdir/vivado -part $part -force
create_ip -name ddr4 -vendor xilinx.com -library ip -module_name ddr4_pl
set ip [get_ips ddr4_pl]
# 実機の設定: PYNQ の RFSoC4x2 base overlay（Xilinx/RFSoC-PYNQ 2a6beba の boards/RFSoC4x2/base/base.tcl・base.xdc）と同じ。
#   参照クロック 200 MHz（G13/G12、IBUFDS → BUFG → No_Buffer）。1 回目（2026-10-23 午前）は仮に MT40A512M16HA-075E・3332 ps・AXI 32 bit で数えた
set req {
    CONFIG.C0.DDR4_MemoryType         Components
    CONFIG.C0.DDR4_DataWidth          64
    CONFIG.C0.DDR4_MemoryPart         MT40A1G16RC-062E
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
    CONFIG.C0.DDR4_AxiAddressWidth    33
}
set ng 0
foreach {k v} $req {
    if {[catch {set_property $k $v $ip} m]} { puts "ddr4_pl: $k = $v を設定できない: $m"; incr ng }
}
foreach {k v} $req {
    set got ""; catch {set got [get_property $k $ip]}
    if {![string equal -nocase $got $v]} { puts "ddr4_pl: $k = $got（要求 $v）"; incr ng }
}
set fh [open $outdir/params_ddr4_pl.rpt w]
foreach k [lsort [list_property $ip CONFIG.*]] { puts $fh [format "%-50s %s" $k [get_property $k $ip]] }
close $fh
if {$ng > 0} { puts "ERROR: DDR4 IP の設定が $ng 件、要求どおりにならない"; exit 1 }
generate_target {instantiation_template synthesis} $ip
create_ip_run $ip
set run [get_runs ddr4_pl_synth_1]
launch_runs $run -jobs $jobs
wait_on_run $run
if {[get_property PROGRESS $run] ne "100%" || [string match "*ERROR*" [get_property STATUS $run]]} {
    puts "ERROR: ddr4_pl_synth_1 が完走しなかった（[get_property STATUS $run]）。runme.log の末尾が Abnormal program termination なら make s1 をもう一度"
    exit 1
}
open_run ddr4_pl_synth_1 -name ddr4_pl
set r [count_row ddr4_pl $outdir]
lappend r -
lappend rows $r
close_design

set fh [open $outdir/s1.txt w]
set fmt "%-10s %5s %7s %7s %6s %5s %8s"
foreach ch [list stdout $fh] {
    puts $ch ""
    puts $ch "---- S-1: OOC 合成後（part $part）。WNS は合成の見積もり ----"
    puts $ch [format $fmt 名前 DSP LUT FF BRAM URAM WNS]
    foreach r $rows { puts $ch [format $fmt {*}$r] }
}
close $fh
puts "=== s1 完了: $outdir/s1.txt ==="
