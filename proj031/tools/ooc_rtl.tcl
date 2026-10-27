# SPDX-License-Identifier: BSD-3-Clause
# proj030 — 自作の RTL（proj028 の tools/ooc_rtl.tcl の写し） を 1 個 OOC で合成して資源・合成の WNS・ドライバの無いネット（Synth 8-3848）を見る
#   vivado -mode batch -source tools/ooc_rtl.tcl -tclargs <top> <周期 ns> <クロックのポート> <ファイル...>
#   generic: OOC_GENERIC="LO_FILE=/abs/a.hex;HI_FILE=/abs/b.hex"
set part xczu48dr-ffvg1517-1-e
lassign $argv top period clkport
set files [lrange $argv 3 end]
set outdir ./build-ooc
file mkdir $outdir
foreach f $files { read_verilog $f }
# generic は環境変数 OOC_GENERIC（「名前=値」を ; で区切る）。$readmemh の hex は絶対パスで渡す（LESSONS: 読めないと ROM が 0 になり BRAM が消えるだけで通る）
set gens {}
if {[info exists ::env(OOC_GENERIC)] && $::env(OOC_GENERIC) ne ""} {
    foreach kv [split $::env(OOC_GENERIC) ";"] {
        lassign [split $kv "="] k v
        lappend gens -generic "$k=\"$v\""
    }
}
synth_design -top $top -part $part -mode out_of_context {*}$gens
create_clock -name $clkport -period $period [get_ports $clkport]
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set rpt [report_utilization -return_string]
set fh [open $outdir/util_$top.rpt w]; puts $fh $rpt; close $fh
report_timing -max_paths 5 -file $outdir/timing_$top.rpt
set dsp [llength [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E2}]]
proc uf {txt label} { if {[regexp -line "^\\|\\s*${label}\\*?\\s*\\|\\s*(\\d+(?:\\.\\d+)?)\\s*\\|" $txt -> n]} { return $n }; return "?" }
puts "OOC $top: DSP $dsp・LUT [uf $rpt {CLB LUTs}]・FF [uf $rpt {CLB Registers}]・BRAM [uf $rpt {Block RAM Tile}]・URAM [uf $rpt URAM]・WNS $wns（$period ns）"
