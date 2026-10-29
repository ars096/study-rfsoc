# SPDX-License-Identifier: BSD-3-Clause
# proj033 — routed のチェックポイントから report_power（ベクタなし）を取り、VCCINT の電流と全体の電力を 1 行で出す（proj027 4c-b・proj030 と同じ数え方）
#   vivado -mode batch -source tools/power_rpt.tcl -tclargs <routed.dcp> <出力の .rpt>
lassign $argv dcp out
open_checkpoint $dcp
report_power -file $out
set fh [open $out r]; set txt [read $fh]; close $fh
set tot "?"; set vi "?"
regexp -line {\|\s*Total On-Chip Power \(W\)\s*\|\s*([0-9.]+)} $txt -> tot
regexp -line {\|\s*Vccint\s*\|\s*[0-9.]+\s*\|\s*([0-9.]+)} $txt -> vi
puts "POWER $dcp: 全体 $tot W・VCCINT $vi A"
