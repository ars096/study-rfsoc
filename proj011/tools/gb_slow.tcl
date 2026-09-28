# SPDX-License-Identifier: BSD-3-Clause
#
# gb_slow.tcl — 配置の後に、gb_fifo の書き込みポインタ（gray）の同期段の 1 ビットだけを遠くに置き直す（proj011 rev6 の検証ビルド）
#
# **目的**: 起動の途切れの見立て（README の rev6 の節）の実機の陽性対照。遅いビットを「わざと」作り、
#   - GRST で ADJ（書き込み側の語の位相）を振ると、特定の位相でだけ途切れる
#   - 途切れの位置は語 2^b − 1（RAW_FIRST ≒ 3 (2^b − 1) クロック）
#   - しきい値 K ≧ 2 で消える
# を確かめる。**本番のビルドには使わない**（spec_core の BUILD[27] が立ち、PS が表示する）。
#
# build.tcl が impl_1 の STEPS.PLACE_DESIGN.TCL.POST に登録する（gb_slow_bit / gb_slow_dx を先に set した包みから source される）。
# 同期段（dest_graysync_ff_reg[k][b]、k = 0..段数−1）をまとめて、元の場所から SLICE の X で gb_slow_dx だけ離れた空きの SLICE に置き直す。
# 最初の段までの配線が長くなり、そのビットだけ到着が遅れる（量は make gb-cdc で測る）

puts "---- gb_slow: 書き込みポインタの bit $gb_slow_bit の同期段を X で $gb_slow_dx 離す ----"
set cells {}
foreach c [get_cells -hier -quiet -filter {IS_PRIMITIVE && NAME =~ *gb_fifo_0*wr_pntr_cdc_inst*dest_graysync_ff_reg*}] {
    if {[regexp {\[(\d+)\]\[(\d+)\]$} $c -> k b] && $b == $gb_slow_bit} { lappend cells [list $k $c] }
}
set cells [lsort -integer -index 0 $cells]
if {[llength $cells] == 0} { error "gb_slow: bit $gb_slow_bit の同期段が見つからない" }
set objs {}
foreach kc $cells { lappend objs [lindex $kc 1] }
set site0 [get_sites -of_objects [lindex $objs 0]]
if {![regexp {^SLICE_X(\d+)Y(\d+)$} $site0 -> x0 y0]} { error "gb_slow: 元の場所 '$site0' が SLICE でない" }
puts "gb_slow: 元の場所 $site0（[llength $objs] 段）"

set bels {AFF BFF CFF DFF}
# 元の BEL を控える（置けなかったら戻す）。place_cell は置いてあるセルをそのまま動かせる
set orig {}
foreach o $objs { lappend orig $o [get_property LOC $o]/[lindex [split [get_property BEL $o] .] end] }
set done 0
foreach dir {1 -1} {
    set tx [expr {$x0 + $dir * $gb_slow_dx}]
    for {set dy 0} {$dy <= 30 && !$done} {incr dy} {
        foreach ty [list [expr {$y0 + $dy}] [expr {$y0 - $dy}]] {
            set s [get_sites -quiet SLICE_X${tx}Y${ty}]
            if {[llength $s] == 0 || [get_property IS_USED $s]} { continue }
            set args {}
            set i 0
            foreach o $objs { lappend args $o "$s/[lindex $bels $i]"; incr i }
            if {[catch {place_cell {*}$args} msg]} {
                puts "gb_slow: $s に置けない（$msg）。元に戻す"
                catch {place_cell {*}$orig}
                continue
            }
            set_property IS_LOC_FIXED 1 $objs
            set_property IS_BEL_FIXED 1 $objs
            puts "gb_slow: $site0 → $s（X で [expr {$tx - $x0}]、Y で [expr {$ty - $y0}]）"
            set done 1
            break
        }
    }
    if {$done} { break }
}
if {!$done} { error "gb_slow: 置き直す先が見つからない" }
