# SPDX-License-Identifier: BSD-3-Clause
# proj015 — ddc_core を 1 個だけ OOC 合成して資源を数える（make ooc-ddc）。時分割あり（TS = 1）となし（TS = 0）を並べる
#
# 予言（手順 2、2026-09-30）: TS = 0 は NCO 8 ＋ light 7 段 × 10 ＋ final 36 = 114、TS = 1 は 8 ＋ (10 ＋ 6 ＋ 4 ＋ 2 × 4) ＋ 36 = 72 DSP。
# **合成は DSP の出口どうしの加算にレジスタが付いた形を DSP に載せる**（proj013 の教訓）ので、加算の分だけ上に外れうる
# 出力: build-ooc-ddc/ooc.txt（表）/ util_ts<N>.rpt / util_ts<N>_hier.rpt

set part   xczu48dr-ffvg1517-2-e
if {[info exists ::env(PART)] && $::env(PART) ne ""} { set part $::env(PART) }
set outdir ./build-ooc-ddc
file mkdir $outdir
set rows {}
foreach ts {0 1} {
    create_project -in_memory -part $part
    set_property include_dirs [list [file normalize ./src]] [current_fileset]
    read_verilog [list src/nco_rom.v src/hb2.v src/hb2s.v src/pair2.v src/ddc_core.v]
    synth_design -top ddc_core -part $part -mode out_of_context -generic TS=$ts
    create_clock -name clk -period 3.906 [get_ports clk]
    report_utilization -file $outdir/util_ts$ts.rpt
    report_utilization -hierarchical -file $outdir/util_ts${ts}_hier.rpt
    set dsp  [llength [get_cells -hier -filter {PRIMITIVE_TYPE =~ ARITHMETIC.DSP.*}]]
    set lut  [llength [get_cells -hier -filter {PRIMITIVE_GROUP == LUT}]]
    set ff   [llength [get_cells -hier -filter {PRIMITIVE_GROUP == FLOP_LATCH}]]
    set bram [llength [get_cells -hier -filter {PRIMITIVE_TYPE =~ BLOCKRAM.*}]]
    lappend rows [list $ts $dsp $lut $ff $bram]
    close_project
}
set fp [open $outdir/ooc.txt w]
puts $fp "TS | DSP | LUT | FF | BRAM（セル数。RAMB36 と RAMB18 を区別しない）"
foreach r $rows { puts $fp [join $r " | "] }
close $fp
puts [exec cat $outdir/ooc.txt]
