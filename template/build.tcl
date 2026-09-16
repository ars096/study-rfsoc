# SPDX-License-Identifier: BSD-3-Clause
# projNNN — 非プロジェクトモードでの合成〜ビットストリーム生成
set proj   projNNN
set part   xczu48dr-ffvg1517-2-e
set outdir ./build

# part と出力先は Makefile から環境変数で受ける。
# 既定以外の part（速度グレードの検証など）は別ディレクトリに出て、build/ を壊さない。
if {[info exists ::env(PART)] && $::env(PART) ne ""} { set part $::env(PART) }
if {[info exists ::env(OUTDIR)] && $::env(OUTDIR) ne ""} { set outdir ./$::env(OUTDIR) }
puts "PART   : $part"
puts "OUTDIR : $outdir"

file mkdir $outdir

read_verilog ./src/top.v
read_xdc     ./src/top.xdc

synth_design -top top -part $part
opt_design
place_design
route_design

report_timing_summary -file $outdir/timing.rpt
report_utilization    -file $outdir/utilization.rpt
report_drc            -file $outdir/drc.rpt

write_bitstream -force $outdir/$proj.bit
puts "=== wrote $outdir/$proj.bit ==="
