# SPDX-License-Identifier: BSD-3-Clause
# projNNN — 非プロジェクトモードでの合成〜ビットストリーム生成
set proj   projNNN
set part   xczu48dr-ffvg1517-2-e
set outdir ./build

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
