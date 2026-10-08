# SPDX-License-Identifier: BSD-3-Clause
#
# worst_paths.tcl — 配置配線後の dcp から、setup / hold の最悪経路の中身を読む（proj012 rev3、2026-09-28）
#
#   vivado -mode batch -nojournal -nolog -source tools/worst_paths.tcl -tclargs <routed.dcp> <出力ディレクトリ> [N] [しきい値 ns]
#   make worst-paths PART=xczu48dr-ffvg1517-1-e        # -1 の dcp（build-1-e/）
#   make worst-paths                                    # -2 の dcp（build/）
#
# **何を知りたいか**: `-1` の余裕は 70 ps（1.8 %）で、配置の組み替わりだけで ±0.1 ns 動く。total power や窓を足して
#   負になったとき「どこを直すか」を先に決めておく。そのために次の 3 つを数える:
#   1. どのブロックが際どいか — しきい値より悪い経路を、始点・終点のセルの階層（深さ D）で束ねた件数と最悪値
#   2. 際どさの型 — 論理の段数・論理遅延と配線遅延の比・クロックスキュー・経路上の最大ファンアウト・通るプリミティブ（DSP/BRAM/URAM）
#        論理が支配（段数が多い）→ 段を切る／配線が支配 → 配置（距離・混雑・ファンアウト）／スキューが支配 → クロックの張り方
#   3. 1 本だけ例外なのか、壁なのか — しきい値以下の件数の分布（数本なら例外、数百本なら構造）
#
# **照合**（在るか／在ってはいけないか）:
#   - get_timing_paths の最悪 slack が report_timing_summary の WNS と一致すること（読む対象を間違えていないか）
#   - clk_out2 が在ること（ブロックデザインのクロック名が変わると、ドメイン別の集計が黙って空になる）
#   - しきい値以下の経路が 0 本なら、しきい値の置き方を疑う旨を出す（空の集計を「問題なし」と読まない）
#
# 出力（<出力ディレクトリ>/）:
#   worst_paths.txt          要約（下の 1〜3。コンソールにも出す）
#   worst_setup_detail.rpt   setup 上位 10 本の report_timing（ピンごと）
#   worst_hold_detail.rpt    hold 上位 10 本
#   design_analysis.rpt      report_design_analysis（経路の特徴・段数の分布・混雑）

if {[llength $argv] < 2} {
    puts "使い方: vivado -mode batch -source tools/worst_paths.tcl -tclargs <routed.dcp> <出力ディレクトリ> \[N=200\] \[しきい値=0.30\]"
    exit 2
}
set dcp    [lindex $argv 0]
set outdir [lindex $argv 1]
set N      [expr {[llength $argv] > 2 ? [lindex $argv 2] : 200}]
set THR    [expr {[llength $argv] > 3 ? [lindex $argv 3] : 0.30}]
set DEPTH  5    ;# 階層の束ね方の深さ（system_i/s45_core_0/inst/u_win/u_xxx まで。proj021 手順 2-1 で 4 → 5: s45_core の中に u_win・g_full.u_full が 1 段増えた）
file mkdir $outdir
open_checkpoint $dcp

set lines {}
proc say {s} { global lines; puts $s; lappend lines $s }
set nerr 0
proc fail {s} { global nerr; incr nerr; say "NG: $s" }

say "dcp      : $dcp"
say "part     : [get_property PART [current_design]]"
say "上位      : $N 本 / しきい値 slack < $THR ns"
say ""

# ---- 照合 1: クロック ----
set clks [get_clocks -quiet -filter {NAME =~ *clk_out2*}]
if {[llength $clks] == 0} {
    fail "clk_out2 のクロックが見つからない。在るクロック:"
    foreach c [get_clocks -quiet] { say "  $c  [get_property PERIOD $c] ns" }
} else {
    foreach c $clks { say "DSP ドメイン: $c（周期 [get_property PERIOD $c] ns）" }
}

# ---- 照合 2: WNS の一致 ----
set p1 [get_timing_paths -setup -max_paths 1 -nworst 1 -quiet]
set wns_path [get_property SLACK $p1]
set wns_sum ""
set tsum [report_timing_summary -no_detailed_paths -return_string -quiet]
foreach l [split $tsum "\n"] {
    # Design Timing Summary の表の値の行（WNS(ns) TNS(ns) ... の次のデータ行）の先頭の数
    if {[regexp {^\s+(-?[0-9]+\.[0-9]+)\s+(-?[0-9]+\.[0-9]+)\s+[0-9]+\s+[0-9]+\s+(-?[0-9]+\.[0-9]+)} $l -> w t h]} { set wns_sum $w; set whs_sum $h; break }
}
say [format "WNS: 経路 %s ns / 要約 %s ns" $wns_path $wns_sum]
if {$wns_sum eq ""} {
    fail "report_timing_summary から WNS を読めなかった（表の書式が変わった？）"
} elseif {abs($wns_path - $wns_sum) > 0.0015} {
    fail "最悪経路の slack と要約の WNS が合わない。読む対象が違う"
}
say ""

# ---- 経路ごとの特徴 ----
proc hier {name depth} {
    set parts [split $name /]
    return [join [lrange $parts 0 [expr {min($depth, [llength $parts] - 1) - 1}]] /]
}
proc path_info {p} {
    set d  [get_property DATAPATH_DELAY $p]
    set dl [get_property DATAPATH_LOGIC_DELAY $p]
    set dn [get_property DATAPATH_NET_DELAY $p]
    set lv [get_property LOGIC_LEVELS $p]
    set sk [get_property SKEW $p]
    set sp [get_property STARTPOINT_PIN $p]
    set ep [get_property ENDPOINT_PIN $p]
    set sc [get_cells -quiet -of_objects $sp]
    set ec [get_cells -quiet -of_objects $ep]
    # 経路上の最大ファンアウト（FLAT_PIN_COUNT − 1）とプリミティブの型
    set fo 0; set fonet ""
    foreach n [get_nets -quiet -of_objects $p] {
        set f [expr {[get_property FLAT_PIN_COUNT $n] - 1}]
        if {$f > $fo} { set fo $f; set fonet $n }
    }
    set kinds {}
    foreach c [get_cells -quiet -of_objects $p] {
        set r [get_property REF_NAME $c]
        if {[regexp {^(DSP48E2|RAMB36E2|RAMB18E2|URAM288|SRL16E|SRLC32E|CARRY8)$} $r]} {
            if {[lsearch $kinds $r] < 0} { lappend kinds $r }
        }
    }
    set sclk [get_property STARTPOINT_CLOCK $p]
    set eclk [get_property ENDPOINT_CLOCK $p]
    return [dict create slack [get_property SLACK $p] d $d dl $dl dn $dn lv $lv sk $sk \
            sc $sc ec $ec fo $fo fonet $fonet kinds $kinds sclk $sclk eclk $eclk]
}
proc kind_of {i} {
    # 際どさの型: 配線 ≧ 70 % → 配線／段数 ≧ 8 → 段数／|スキュー| ≧ 0.15 ns → スキュー／それ以外 → 混在
    set dn [dict get $i dn]; set d [dict get $i d]
    if {$d > 0 && $dn / $d >= 0.70} { return "配線" }
    if {[dict get $i lv] >= 8} { return "段数" }
    if {abs([dict get $i sk]) >= 0.15} { return "スキュー" }
    return "混在"
}

foreach mode {setup hold} {
    set paths [get_timing_paths -$mode -max_paths $N -nworst 1 -unique_pins -quiet]
    say "==== $mode: 上位 [llength $paths] 本 ===="
    say [format "%-3s %7s %3s %6s %5s %6s %5s %-4s %-8s %s" # slack 段 遅延 配線% skew FO 型 DSP等 "始点 → 終点（セル）"]
    set k 0
    set grp [dict create]; set typ [dict create]; set nthr 0
    foreach p $paths {
        set i [path_info $p]
        set s [dict get $i slack]
        set ty [kind_of $i]
        incr k
        if {$k <= 20} {
            say [format "%-3d %+7.3f %3d %6.3f %4.0f%% %+6.3f %5d %-4s %-8s %s → %s" $k $s [dict get $i lv] [dict get $i d] \
                [expr {[dict get $i d] > 0 ? 100.0 * [dict get $i dn] / [dict get $i d] : 0}] [dict get $i sk] [dict get $i fo] \
                $ty [join [dict get $i kinds] ,] [dict get $i sc] [dict get $i ec]]
            if {$k <= 5 && [dict get $i fo] >= 32} { say "      最大ファンアウトのネット: [dict get $i fonet]（[dict get $i fo]）" }
            if {$k <= 5 && [dict get $i sclk] ne [dict get $i eclk]} { say "      クロックの乗り換え: [dict get $i sclk] → [dict get $i eclk]" }
        }
        if {$s < $THR} {
            incr nthr
            set key "[hier [dict get $i sc] $::DEPTH]  →  [hier [dict get $i ec] $::DEPTH]"
            if {![dict exists $grp $key]} { dict set grp $key [list 0 1e9] }
            lassign [dict get $grp $key] n m
            dict set grp $key [list [incr n] [expr {min($m, $s)}]]
            dict incr typ $ty
        }
    }
    say ""
    say "slack < $THR ns: $nthr 本（上位 $N 本のうち。$N 本とも下回るなら N を増やして数え直す）"
    if {$nthr == 0} {
        say "  （0 本。しきい値が低すぎるか、読む対象が違う。空の集計を問題なしと読まない）"
    } else {
        set typs {}
        dict for {t n} $typ { lappend typs "$t $n" }
        say "  型の内訳: [join $typs ／]"
        say "  階層（深さ $::DEPTH）ごと（件数・最悪 slack）:"
        set rows {}
        dict for {key v} $grp { lappend rows [list [lindex $v 0] [lindex $v 1] $key] }
        foreach r [lsort -index 1 -real $rows] {
            say [format "    %4d  %+7.3f  %s" [lindex $r 0] [lindex $r 1] [lindex $r 2]]
        }
    }
    if {$nthr >= $N} { say "  NOTE: 上位 $N 本すべてがしきい値を下回った。件数は下限" }
    say ""
    report_timing -$mode -max_paths 10 -nworst 1 -unique_pins -input_pins -sort_by slack \
        -file $outdir/worst_${mode}_detail.rpt
}

if {[catch {
    report_design_analysis -timing -max_paths 50 -setup -file $outdir/design_analysis.rpt
    report_design_analysis -logic_level_distribution -logic_level_dist_paths 1000 -append -file $outdir/design_analysis.rpt
    report_design_analysis -congestion -append -file $outdir/design_analysis.rpt
} err]} { say "NOTE: report_design_analysis の一部が失敗: $err" }

say "照合の問題: $nerr 件"
set f [open $outdir/worst_paths.txt w]; puts $f [join $lines "\n"]; close $f
puts "書いた: $outdir/worst_paths.txt / worst_setup_detail.rpt / worst_hold_detail.rpt / design_analysis.rpt"
exit [expr {$nerr > 0 ? 1 : 0}]
