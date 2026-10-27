# E-1: 配置配線後のチェックポイントを開き、部品ごとの資源と記憶の型を出す（ビルドの成果物は変えない）
# vivado -mode batch -nojournal -nolog -source tools/rep_util.tcl -tclargs <routed.dcp> <out_prefix>
set dcp [lindex $argv 0]; set out [lindex $argv 1]
open_checkpoint $dcp
report_utilization -hierarchical -hierarchical_depth 12 -file ${out}_hier.rpt
