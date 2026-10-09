# SPDX-License-Identifier: BSD-3-Clause
#
# floorplan.tcl — 配置配線後の dcp から、配置されたセルの位置を階層ごとに書き出す（proj021、2026-10-09）
#
#   vivado -mode batch -nojournal -nolog -source tools/floorplan.tcl -tclargs <routed.dcp> <出力ディレクトリ> [深さ=5] [経路の本数=50]
#   make floorplan                     # build/ の dcp → build/floorplan/
#   make floorplan DCP=build-PE/vivado/proj021.runs/impl_1/system_wrapper_routed.dcp FP_OUT=build-PE/floorplan
#
# 描くのは tools/floorplan.py（numpy・matplotlib。Vivado は要らない）。ここは数えて書き出すだけ。
#
# 出力（<出力ディレクトリ>/）:
#   cells.csv      group,site,site_type,x,y,n   — 階層（深さ D で束ねた名前）× サイトごとのプリミティブの数。x・y は RPM_X・RPM_Y
#                                                （SLICE・DSP・BRAM・URAM が同じ物差しに乗る座標）
#   sites.csv      kind,x,y                     — デバイスの全サイト（SLICE・DSP・BRAM・URAM・RFDC など。背景に描く）
#   regions.csv    name,x0,y0,x1,y1             — クロック領域の外枠（その領域のサイトの RPM の最小・最大）
#   paths.csv      rank,slack,sx,sy,ex,ey,start,end — setup の上位の経路の始点・終点のセルの位置
#   clock_util.rpt report_clock_utilization
#   floorplan.txt  要約（照合の結果・グループごとの件数）
#
# **照合**（数え漏れを黙って描かない）:
#   - 置かれたプリミティブの数 = report_utilization の LUT ＋ FF ＋ DSP ＋ BRAM ＋ URAM の合計の近く（CARRY・MUXF なども数えるので多めに出る）
#   - 位置の分からないサイト（RPM が読めない）が 0 であること
#   - グループが 1 つしかない・s45_core_* が無い → 束ねる深さか階層の名前を疑う

if {[llength $argv] < 2} {
    puts "使い方: vivado -mode batch -source tools/floorplan.tcl -tclargs <routed.dcp> <出力ディレクトリ> \[深さ=5\] \[経路の本数=50\]"
    exit 2
}
set dcp    [lindex $argv 0]
set outdir [lindex $argv 1]
set DEPTH  [expr {[llength $argv] > 2 ? [lindex $argv 2] : 5}]
set NPATH  [expr {[llength $argv] > 3 ? [lindex $argv 3] : 50}]
file mkdir $outdir
open_checkpoint $dcp

set lines {}
proc say {s} { global lines; puts $s; lappend lines $s }
set nerr 0
proc fail {s} { global nerr; incr nerr; say "NG: $s" }

proc hier {name depth} {
    set parts [split $name /]
    set n [expr {min($depth, [llength $parts] - 1)}]
    if {$n < 1} { return "(top)" }
    return [join [lrange $parts 0 [expr {$n - 1}]] /]
}

say "dcp   : $dcp"
say "part  : [get_property PART [current_design]]"
say "深さ  : $DEPTH"

# ---- サイトの座標（RPM）を、使うサイトの名前から一度に引く ----
array set rx {}; array set ry {}; array set rt {}
proc load_sites {sites} {
    global rx ry rt
    if {[llength $sites] == 0} { return }
    set xs [get_property RPM_X $sites]
    set ys [get_property RPM_Y $sites]
    set ts [get_property SITE_TYPE $sites]
    foreach s $sites x $xs y $ys t $ts { set rx($s) $x; set ry($s) $y; set rt($s) $t }
}

# ---- 背景: デバイスの全サイト ----
set fh [open $outdir/sites.csv w]
puts $fh "kind,x,y"
set nsite 0
foreach {kind pat} {SLICE {SLICE*} DSP {DSP48E2*} BRAM {RAMB36*} URAM {URAM288*} RFADC {*ADC*} RFDAC {*DAC*} IO {*IOB*} PS {PS8*}} {
    set ss [get_sites -quiet -filter "SITE_TYPE =~ $pat"]
    if {[llength $ss] == 0} { continue }
    set xs [get_property RPM_X $ss]
    set ys [get_property RPM_Y $ss]
    foreach x $xs y $ys { puts $fh "$kind,$x,$y"; incr nsite }
    say [format "  背景のサイト %-6s %7d 個" $kind [llength $ss]]
}
close $fh

# ---- 置かれたプリミティブ ----
set cells [get_cells -hierarchical -quiet -filter {IS_PRIMITIVE && STATUS != UNPLACED && PRIMITIVE_LEVEL != INTERNAL}]
set names [get_property NAME $cells]
set locs  [get_property LOC $cells]
say "置かれたプリミティブ: [llength $cells] 個"
array set cnt {}
array set used {}
set noloc 0
foreach nm $names lc $locs {
    if {$lc eq ""} { incr noloc; continue }
    set used($lc) 1
    set k "[hier $nm $DEPTH]|$lc"
    if {[info exists cnt($k)]} { incr cnt($k) } else { set cnt($k) 1 }
}
if {$noloc} { say "  LOC の無いプリミティブ $noloc 個（数えない）" }
load_sites [get_sites [array names used]]
set fh [open $outdir/cells.csv w]
puts $fh "group,site,site_type,x,y,n"
array set gsum {}
set nbad 0
foreach k [array names cnt] {
    lassign [split $k |] g s
    if {![info exists rx($s)] || $rx($s) eq ""} { incr nbad; continue }
    puts $fh "\"$g\",$s,$rt($s),$rx($s),$ry($s),$cnt($k)"
    if {[info exists gsum($g)]} { incr gsum($g) $cnt($k) } else { set gsum($g) $cnt($k) }
}
close $fh
if {$nbad} { fail "RPM の読めないサイトが $nbad 個" }
set groups [lsort [array names gsum]]
say "グループ（深さ $DEPTH）: [llength $groups] 個"
if {[llength $groups] < 2} { fail "グループが [llength $groups] 個。深さか階層の名前を疑う" }
if {[llength [lsearch -all -glob $groups *s45_core_*]] == 0} {
    # proj021 1b までの dcp は win_core_i・spec_core_0（floorplan.py はどちらも描ける）。どちらも無ければ階層の名前を疑う
    if {[llength [lsearch -all -glob $groups *win_core_*]] == 0} { fail "s45_core_*・win_core_* のグループが無い（階層の名前が違う）" } else { say "  NOTE: s45_core_* が無く win_core_* がある（proj021 1b までの dcp）" }
}

# report_utilization の合計と比べる（多めに出るのは CARRY8・MUXF・SRL など）
set ut [report_utilization -return_string]
set tot 0
foreach pat {{CLB LUTs} {CLB Registers} {DSPs} {Block RAM Tile} {URAM}} {
    if {[regexp "\\|\\s*${pat}\\*?\\s*\\|\\s*(\[0-9.\]+)\\s*\\|" $ut -> v]} { set tot [expr {$tot + $v}]; say "  report_utilization: $pat = $v" }
}
say "  置かれたプリミティブ [llength $cells] ／ LUT ＋ FF ＋ DSP ＋ BRAM ＋ URAM $tot"
if {$tot > 0 && [llength $cells] < 0.9 * $tot} { fail "置かれたプリミティブが report_utilization の合計より少ない（数え漏れ）" }

# ---- クロック領域の外枠 ----
set fh [open $outdir/regions.csv w]
puts $fh "name,x0,y0,x1,y1"
foreach cr [get_clock_regions -quiet] {
    set ss [get_sites -quiet -of_objects $cr -filter {SITE_TYPE =~ SLICE*}]
    if {[llength $ss] == 0} { continue }
    set xs [lsort -integer [get_property RPM_X $ss]]
    set ys [lsort -integer [get_property RPM_Y $ss]]
    puts $fh "$cr,[lindex $xs 0],[lindex $ys 0],[lindex $xs end],[lindex $ys end]"
}
close $fh

# ---- setup の上位の経路の両端 ----
set fh [open $outdir/paths.csv w]
puts $fh "rank,slack,sx,sy,ex,ey,start,end"
set r 0
foreach p [get_timing_paths -setup -max_paths $NPATH -nworst 1 -quiet] {
    incr r
    set sc [get_cells -quiet -of_objects [get_property STARTPOINT_PIN $p]]
    set ec [get_cells -quiet -of_objects [get_property ENDPOINT_PIN $p]]
    if {$sc eq "" || $ec eq ""} { continue }
    set ss [get_sites -quiet -of_objects $sc]
    set es [get_sites -quiet -of_objects $ec]
    if {$ss eq "" || $es eq ""} { continue }
    puts $fh "$r,[get_property SLACK $p],[get_property RPM_X $ss],[get_property RPM_Y $ss],[get_property RPM_X $es],[get_property RPM_Y $es],\"[hier $sc $DEPTH]\",\"[hier $ec $DEPTH]\""
}
close $fh
say "経路: setup の上位 $r 本"

report_clock_utilization -file $outdir/clock_util.rpt

say ""
say "グループごとのプリミティブの数（多い順）:"
foreach g [lsort -command {apply {{a b} {global gsum; expr {$gsum($b) - $gsum($a)}}}} $groups] {
    say [format "  %8d  %s" $gsum($g) $g]
}
say ""
say [expr {$nerr ? "結果: NG $nerr 件" : "結果: 照合は通過"}]
set fh [open $outdir/floorplan.txt w]
foreach l $lines { puts $fh $l }
close $fh
exit [expr {$nerr ? 1 : 0}]
