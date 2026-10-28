# pwr_cal — 実測のある routed dcp に report_power をかけ、VCCINT の見積もりと実測の比を取る（proj032 の電力の物差し）
#   vivado -mode batch -source tools/pwr_cal.tcl -tclargs <routed.dcp> <out.rpt>
set dcp [lindex $argv 0]
set out [lindex $argv 1]
open_checkpoint $dcp
report_power -file $out
report_utilization -file [file rootname $out]_util.rpt
