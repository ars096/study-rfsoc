# SPDX-License-Identifier: BSD-3-Clause
# proj001 — 非プロジェクトモードでの合成〜ビットストリーム生成
set proj   proj001
set part   xczu48dr-ffvg1517-2-e
set outdir ./build

file mkdir $outdir

read_verilog ./src/blink.v
read_xdc     ./src/blink.xdc

synth_design -top blink -part $part
opt_design
place_design
route_design

report_timing_summary -file $outdir/timing.rpt
report_utilization    -file $outdir/utilization.rpt
report_drc            -file $outdir/drc.rpt

write_bitstream -force $outdir/$proj.bit
puts "=== wrote $outdir/$proj.bit ==="
