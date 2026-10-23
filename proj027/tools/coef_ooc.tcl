# SPDX-License-Identifier: BSD-3-Clause
# proj027 — F-2 の測り: 係数の補間（g24_coef）を 1 個だけ OOC で合成して資源を数える（make coef-ooc）
#
# **既製 IP・自作部品の資源は、1 個だけ合成して数えてから決める**（LESSONS）。F-2（PFB の係数 ROM をコアごとか 4 コアで共有か）の材料。
# 数えるもの（名前・トップ・HEX の置き場所）:
#   ruler_g22    物差し: proj025 の g22_coef（f706170 から git show で build-ooc/ruler/ に出す）。proj025 の実ビルドの u_pfb（LUT 494・DSP 144・RAMB36 153）を越えないこと
#   g24          2G-4 の g24_coef（src/g24）
#   pc_nohex     陽性対照: g24_coef に在らない HEX を渡す。ROM が空で畳まれ RAMB36 0 になるはず（ならなければ $readmemh の照合が効いていない）
# 照合（違えば exit 1）: 合成が完走 / ruler_g22・g24 の RAMB36 が予言どおり（4・2）/ pc_nohex の RAMB36 が 0
# DSP は REF_NAME == DSP48E2 で数える（`DSP*` だと DSP48E2 の中の部品セル 9 個ずつを拾い、64 個が 576 に見えた。1 回目 2026-10-23）
# 出力: build-ooc/ooc.txt（表）/ util_<名前>.rpt / synth_<名前>.log の抜き書きは vivado.log

set part   xczu48dr-ffvg1517-1-e
if {[info exists ::env(PART)] && $::env(PART) ne ""} { set part $::env(PART) }
set outdir ./build-ooc
set jobs 8
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }
set_param general.maxThreads [expr {$jobs > 8 ? 8 : $jobs}]
set period 3.906

# {名前  トップ  RTL  LO  HI  RAMB36 の期待}
set variants [list \
    [list ruler_g22 g22_coef $outdir/ruler/g22_coef.v $outdir/ruler/g22_coef_lo.hex $outdir/ruler/g22_coef_hi.hex 4] \
    [list g24       g24_coef ./src/g24/g24_coef.v     ./src/g24/g24_coef_lo.hex     ./src/g24/g24_coef_hi.hex     2] \
    [list pc_nohex  g24_coef ./src/g24/g24_coef.v     $outdir/no_such_lo.hex        $outdir/no_such_hi.hex        0] \
]

puts "PART : $part"
puts "JOBS : $jobs"
set ng 0
set rows {}
foreach v $variants {
    lassign $v name top rtl lo hi exp_b
    puts "==== $name ===="
    close_project -quiet
    create_project -in_memory -part $part
    read_verilog $rtl
    if {[catch {synth_design -top $top -mode out_of_context -part $part \
                  -generic LO_FILE=\"[file normalize $lo]\" -generic HI_FILE=\"[file normalize $hi]\"} msg]} {
        puts "  $name: 合成に失敗: $msg"; incr ng; continue
    }
    create_clock -period $period [get_ports clk]
    report_utilization -file $outdir/util_$name.rpt
    set lut  [llength [get_cells -hier -filter {PRIMITIVE_GROUP == CLB && PRIMITIVE_SUBGROUP == LUT}]]
    set srl  [llength [get_cells -hier -filter {PRIMITIVE_SUBGROUP == SRL}]]
    set ff   [llength [get_cells -hier -filter {PRIMITIVE_GROUP == REGISTER}]]
    set dsp  [llength [get_cells -hier -filter {REF_NAME == DSP48E2}]]
    set b36  [llength [get_cells -hier -filter {REF_NAME == RAMB36E2}]]
    set b18  [llength [get_cells -hier -filter {REF_NAME == RAMB18E2}]]
    set carry [llength [get_cells -hier -filter {REF_NAME == CARRY8}]]
    set ok [expr {$b36 == $exp_b ? "OK" : "NG"}]
    if {$ok ne "OK"} { incr ng }
    lappend rows [format "%-10s LUT %6d  SRL %5d  FF %6d  CARRY8 %4d  DSP %4d  RAMB36 %3d  RAMB18 %3d  (RAMB36 の期待 %d: %s)" \
                    $name $lut $srl $ff $carry $dsp $b36 $b18 $exp_b $ok]
    puts [lindex $rows end]
}
set f [open $outdir/ooc.txt w]
puts $f "PART $part  周期 $period ns  OOC 合成のみ"
foreach r $rows { puts $f $r }
puts $f [expr {$ng == 0 ? "結果: 全部通過" : "結果: 不合格 ($ng)"}]
close $f
foreach r $rows { puts $r }
if {$ng} { puts "結果: 不合格 ($ng)"; exit 1 }
puts "結果: 全部通過"
