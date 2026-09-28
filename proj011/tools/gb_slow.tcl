# SPDX-License-Identifier: BSD-3-Clause
#
# gb_slow.tcl — 配置の前に、gb_fifo の書き込みポインタ（gray）の同期段の 1 ビットだけを遠くの SLICE に固定する（proj011 rev6 の検証ビルド）
#
# **目的**: 起動の途切れの見立て（README の rev6 の節）の実機の陽性対照。遅いビットを「わざと」作り、
#   - GRST で ADJ（書き込み側の語の位相）を振ると、特定の位相でだけ途切れる
#   - 途切れの位置は語 2^b − 1（RAW_FIRST ≒ 3 (2^b − 1) クロック）
#   - しきい値 K ≧ 2 で消える
# を確かめる。**本番のビルドには使わない**（spec_core の BUILD[27] が立ち、PS が表示する）。
#
# build.tcl が impl_1 の STEPS.PLACE_DESIGN.TCL.PRE に登録する（gb_slow_bit / gb_slow_site を先に set した包みから source される）。
# 同期段（dest_graysync_ff_reg[k][b]、k = 0..段数−1）の全段に LOC = gb_slow_site を付ける（BEL は配置器に任せる）。
# 書き込み側（src_gray_ff）は gb_fifo の近くに置かれたままなので、最初の段までの配線だけが長くなる（量は make gb-cdc で測る）。
#
# 経緯（2026-09-28）: 初版は配置の後に place_cell で SITE/BEL を指定して動かしたが、2 段目で
# 「[Vivado 12-1409] ... the bel and site locations are in disagreement」が 60 か所すべてで出て止まった。配置の前の LOC に改めた。
# 既定の場所 SLICE_X46Y109 は、rev6 の配置での元の場所 SLICE_X106Y109 から X で 60 離したもの

puts "---- gb_slow: 書き込みポインタの bit $gb_slow_bit の同期段を $gb_slow_site に固定する ----"
set objs {}
set cells {}
foreach c [get_cells -hier -quiet -filter {IS_PRIMITIVE && NAME =~ *gb_fifo_0*wr_pntr_cdc_inst*dest_graysync_ff_reg*}] {
    if {[regexp {\[(\d+)\]\[(\d+)\]$} $c -> k b] && $b == $gb_slow_bit} { lappend cells [list $k $c] }
}
foreach kc [lsort -integer -index 0 $cells] { lappend objs [lindex $kc 1] }
if {[llength $objs] == 0} { error "gb_slow: bit $gb_slow_bit の同期段が見つからない" }
set s [get_sites -quiet $gb_slow_site]
if {[llength $s] == 0 || ![string match SLICE* [get_property SITE_TYPE $s]]} {
    error "gb_slow: $gb_slow_site が SLICE でない（[get_property -quiet SITE_TYPE $s]）"
}
set_property LOC $s $objs
puts "gb_slow: [llength $objs] 段に LOC = $s（[get_property SITE_TYPE $s]、クロック領域 [get_property CLOCK_REGION $s]）"
foreach o $objs { puts "  $o" }
