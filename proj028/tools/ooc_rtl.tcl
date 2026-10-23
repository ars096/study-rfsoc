# SPDX-License-Identifier: BSD-3-Clause
# proj028 — 自作の RTL を 1 個 OOC で合成して資源・合成の WNS・ドライバの無いネット（Synth 8-3848）を見る
#   vivado -mode batch -source tools/ooc_rtl.tcl -tclargs <top> <周期 ns> <クロックのポート> <ファイル...>
set part xczu48dr-ffvg1517-1-e
lassign $argv top period clkport
set files [lrange $argv 3 end]
set outdir ./build-ooc
file mkdir $outdir
foreach f $files { read_verilog $f }
synth_design -top $top -part $part -mode out_of_context
create_clock -name $clkport -period $period [get_ports $clkport]
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set rpt [report_utilization -return_string]
set fh [open $outdir/util_$top.rpt w]; puts $fh $rpt; close $fh
report_timing -max_paths 5 -file $outdir/timing_$top.rpt
set dsp [llength [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E2}]]
proc uf {txt label} { if {[regexp -line "^\\|\\s*${label}\\*?\\s*\\|\\s*(\\d+(?:\\.\\d+)?)\\s*\\|" $txt -> n]} { return $n }; return "?" }
puts "OOC $top: DSP $dsp・LUT [uf $rpt {CLB LUTs}]・FF [uf $rpt {CLB Registers}]・BRAM [uf $rpt {Block RAM Tile}]・WNS $wns（$period ns）"
