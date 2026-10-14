# SPDX-License-Identifier: BSD-3-Clause
#
# gb_cdc.tcl — 配置配線後の dcp から、gb_fifo の書き込みポインタ（gray）の乗り換えをビットごとに測る（proj011 rev6）
#
#   vivado -mode batch -nojournal -nolog -source tools/gb_cdc.tcl -tclargs <routed.dcp> [出力.txt]
#   make gb-cdc DCP=build/vivado/proj011.runs/impl_1/system_wrapper_routed.dcp
#
# **何を見るか**（README の rev6 の節・sim/tb_gearbox.v）:
#   書き込み（341.33 MHz）と読み出し（256 MHz）は同じ VCO（1024 MHz）の 3 分周・4 分周で、語の周期はどちらも 12 VCO。
#   gray の各ビット b が読み出し側の最初の同期段に着く時刻（読み出しのクロックの縁から測る）を
#       A(b) = 書き込み側のクロックの到着（src の C）＋ データ経路（src の C → dest の D）− 読み出し側のクロックの到着（dest の C）
#   とすると、起動の直後に途切れが起きるのは「bit 0 より後に初めて動くビットのどれかが、bit 0 と別の縁で捕まる」とき。
#   gb_up が語をまとめ始める位相（4 通り、VCO 1 周期 = 0.977 ns 刻み）が起動ごとにばらつくので、起動のうち途切れる割合は
#       P ≒ D / 0.977 ns（0〜1 に切る）、D = max_{b≥1} A(b) − A(0)
#   D ≦ 0（bit 0 が一番遅い）なら、どの位相でも途切れない。
#
# **限界**: クロックの到着は setup の報告から読むので、書き込み側は早い側（DCD）、読み出し側は遅い側（SCD）の値になる。
#   ビット間の差（D）を見るぶんには共通の偏りは消えるが、ビットごとの時刻の絶対値は信用しない。
#   温度・電圧で数十 ps 動くので、D が 0 の近くなら率は日によって変わりうる。

if {[llength $argv] < 1} {
    puts "使い方: vivado -mode batch -source tools/gb_cdc.tcl -tclargs <routed.dcp> \[出力.txt\]"
    exit 2
}
set dcp [lindex $argv 0]
set out [expr {[llength $argv] > 1 ? [lindex $argv 1] : ""}]
open_checkpoint $dcp

set lines {}
proc say {s} { global lines; puts $s; lappend lines $s }

# ---- 同期段（読み出し側の最初の段）と、その D を駆動する gray のレジスタを探す ----
set fifo [get_cells -hier -filter {NAME =~ *gb_fifo_0* && IS_PRIMITIVE == 0} -quiet]
if {[llength $fifo] == 0} { puts "ERROR: gb_fifo_0 が見つからない"; exit 1 }
# xpm_cdc_gray: dest_graysync_ff_reg[0][b] が最初の段。書き込みポインタは wr_pntr_cdc_inst（読み出しポインタの逆向きは rd_pntr_cdc_inst）
# **フィルタの [0] は glob の文字クラスになる**（proj011 で踏んだ）ので、広く取ってから Tcl で文字列として選ぶ。
# データ数の乗り換え（wr_pntr_cdc_dc_inst）は別物なので除く
set dst {}
foreach c [get_cells -hier -quiet -filter {IS_PRIMITIVE && NAME =~ *gb_fifo_0*wr_pntr_cdc_inst*dest_graysync_ff_reg*}] {
    if {[string first {dest_graysync_ff_reg[0][} $c] >= 0} { lappend dst $c }
}
if {[llength $dst] == 0} {
    say "ERROR: wr_pntr_cdc の最初の同期段が見つからない。gb_fifo_0 の中の ASYNC_REG のセル:"
    foreach c [get_cells -hier -quiet -filter {IS_PRIMITIVE && ASYNC_REG && NAME =~ *gb_fifo_0*}] { say "  $c" }
    exit 1
}
proc bitno {c} { if {[regexp {\[(\d+)\]$} $c -> b]} { return $b } ; return -1 }
set dst [lsort -command {apply {{a b} {expr {[bitno $a] - [bitno $b]}}}} $dst]

# セルの名前に [ ] が入るので、get_pins $cell/D は glob に化ける。セルのオブジェクトから引く
proc pin {cell name} { return [get_pins -of_objects $cell -filter "REF_PIN_NAME == $name"] }

proc rt_val {rpt key} {
    # report_timing の要約の行（"Data Path Delay:  0.812ns" など）から ns を読む
    foreach l [split $rpt "\n"] {
        if {[string first $key $l] >= 0 && [regexp {(-?[0-9]+\.[0-9]+)ns} $l -> v]} { return $v }
    }
    return ""
}

say [format "dcp: %s" $dcp]
say [format "同期段: %d ビット（%s …）" [llength $dst] [lindex $dst 0]]
say ""
say [format "%-4s %9s %9s %9s %9s %9s   %s" bit "書込CLK" "経路" "読出CLK" "A" "A−A(0)" "src → dest"]
set A {}
foreach d $dst {
    set b [bitno $d]
    set dpin [pin $d D]
    set drv [get_cells -quiet -of [get_pins -quiet -leaf -of [get_nets -of $dpin] -filter {DIRECTION == OUT}]]
    if {[llength $drv] != 1} { say "ERROR: bit $b の D の駆動元が 1 つでない（$drv）"; exit 1 }
    # 書き込み側のクロックの到着: src に入る経路（同じ ADC ドメイン）の DCD
    set r1 [report_timing -quiet -to [pin $drv D] -delay_type max -return_string]
    set tsrc [rt_val $r1 "Destination Clock Delay"]
    # データ経路（乗り換え。非同期の宣言で解析の外なので slack は inf、経路の遅延だけが出る）
    set r2 [report_timing -quiet -from [pin $drv C] -to $dpin -delay_type max -return_string]
    set dp [rt_val $r2 "Data Path Delay"]
    if {$dp eq ""} {
        # 予備: 時間の経路のオブジェクトから読む
        set tp [get_timing_paths -quiet -from [pin $drv C] -to $dpin -delay_type max]
        if {[llength $tp] > 0} { set dp [get_property DATAPATH_DELAY $tp] }
    }
    # 読み出し側のクロックの到着: dest から次の段への経路（同じ DSP ドメイン）の SCD
    set r3 [report_timing -quiet -from [pin $d C] -delay_type max -return_string]
    set tdst [rt_val $r3 "Source Clock Delay"]
    if {$tsrc eq "" || $dp eq "" || $tdst eq ""} {
        say "ERROR: bit $b の値が読めない（書込 '$tsrc' / 経路 '$dp' / 読出 '$tdst'）"
        exit 1
    }
    set a [expr {$tsrc + $dp - $tdst}]
    dict set A $b $a
    say [format "%-4d %9.3f %9.3f %9.3f %9.3f %9s   %s → %s" $b $tsrc $dp $tdst $a "" [file tail $drv] [file tail $d]]
}
set a0 [dict get $A 0]
set dmax -1e9; set bmax -1
dict for {b a} $A { if {$b >= 1 && $a - $a0 > $dmax} { set dmax [expr {$a - $a0}]; set bmax $b } }
say ""
dict for {b a} $A { say [format "  A(%d) − A(0) = %+.3f ns" $b [expr {$a - $a0}]] }
# 位相は 4 通り（VCO 1 周期 = 0.977 ns 刻み）で、境目は A ≡ 0（mod 0.977 ns）に並ぶ。bit 0 と後のビットの間に境目が入る位相だけが途切れる。
# **境目の絶対位置は読めない**（クロックの到着を setup の報告の早い側・遅い側から取るので、±0.2 ns 程度ずれる）ので、
# 言えるのは「途切れうる位相の数の上限」= D を 0.977 で割って切り上げた数（D ≦ 0 なら 0）。2026-09-28、rev5 の 0/40 で
# 旧式の P ≒ D / 0.977（位相を連続とみなした平均）が外れて改めた
set nph [expr {$dmax <= 0 ? 0 : min(4, int(ceil($dmax / 0.9766)))}]
say ""
say [format "D = max A(b≥1) − A(0) = %+.3f ns（bit %d）→ 途切れうる位相は 4 通りのうち最大 %d（率は 0 か %d/4 以下。境目の位置しだい）" \
        $dmax $bmax $nph $nph]
set cand {}
dict for {b a} $A { if {$b >= 1 && $a > $a0} { lappend cand [format "bit %d → 語 %d（RAW_FIRST ≒ %d クロック前後）" $b [expr {(1 << $b) - 1}] [expr {3 * ((1 << $b) - 1)}]] } }
if {[llength $cand] > 0} {
    say "途切れるなら、その位置は bit 0 より遅いビットのうち、その起動で別の縁に入った最も若いビットが初めて動く語:"
    foreach c $cand { say "  $c" }
} else {
    say "bit 0 が一番遅い（D ≦ 0）。見立てどおりなら、このビット列は起動で途切れない"
}
if {$out ne ""} {
    set f [open $out w]; puts $f [join $lines "\n"]; close $f
    puts "書いた: $out"
}
