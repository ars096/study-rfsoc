# SPDX-License-Identifier: BSD-3-Clause
#
# postroute_physopt.tcl — 配置配線の済んだ dcp に配線後の物理最適化（phys_opt_design）を掛け、閉じたら bit を書く（proj021 2-2b、2026-10-10）
#
#   vivado -mode batch -source tools/postroute_physopt.tcl -tclargs <routed.dcp> <出力ディレクトリ>
#   make physopt OUTDIR=build-PE                → build-PE-po/（proj021.bit・proj021.hwh（元のコピー）・timing.rpt・routed_physopt.dcp）
#
# **使うのは、負けている終点が少なく WNS が数十 ps 以内のとき**（2-2b の PE: −0.004 ns・1 終点）。配置は変えず、
# 経路の上の論理の複製・置き換え・配線の組み直しだけ。設計（RTL・BD・制約）は元のビルドと同じなので、.hwh は元のものをそのまま使う。
# 指示を順に試し、WNS ≥ 0 かつ WHS ≥ 0 になったところで止める。最後まで負けなら bit は書かずに 1 で終わる
if {[llength $argv] < 2} { puts "使い方: -tclargs <routed.dcp> <出力ディレクトリ>"; exit 2 }
set dcp [lindex $argv 0]
set out [lindex $argv 1]
file mkdir $out
open_checkpoint $dcp
proc wns {} { set p [get_timing_paths -setup -max_paths 1 -nworst 1]; return [expr {[llength $p] ? [get_property SLACK $p] : 0}] }
proc whs {} { set p [get_timing_paths -hold  -max_paths 1 -nworst 1]; return [expr {[llength $p] ? [get_property SLACK $p] : 0}] }
puts [format "前: WNS %.4f ns / WHS %.4f ns（%s）" [wns] [whs] $dcp]
foreach d {AggressiveExplore AggressiveFanoutOpt AlternateReplication Explore} {
    if {[wns] >= 0 && [whs] >= 0} break
    if {[catch {phys_opt_design -directive $d} msg]} { puts "phys_opt_design -directive $d: 失敗（$msg）"; continue }
    puts [format "phys_opt_design -directive %-22s → WNS %.4f ns / WHS %.4f ns" $d [wns] [whs]]
}
report_timing_summary -file $out/timing.rpt
set w [wns]; set h [whs]
puts "TIMING (確定): WNS = $w ns / WHS = $h ns"
if {$w < 0 || $h < 0} { puts "ERROR: 閉じなかった。bit は書かない"; exit 1 }
write_checkpoint -force $out/routed_physopt.dcp
write_bitstream -force $out/proj021.bit
puts "bit: $out/proj021.bit"
exit 0
