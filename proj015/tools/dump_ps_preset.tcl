# SPDX-License-Identifier: BSD-3-Clause
# proj015 — RFSoC4x2 のボードプリセットが Zynq UltraScale+ の PS に当てる設定を書き出す（make ps-preset）
#
# **なぜ**: board_part を当てると part がボードの宣言値（-2）へ引き戻される（WARNING: Project 1-153）。
#   proj015 から実機の .bit は `-1` でビルドする（チップの刻印が未確認で、遅い方で閉じたものだけを載せる。README）。
#   そのため `-1` のビルドは board_part を使わず、ここで書き出した PS の設定を build.tcl が明示して当てる。
#
# **何を書くか**: 2 つの PS を作って CONFIG.* を比べ、違うものだけを書く
#   (1) board_part の在るプロジェクト（-2）で、apply_board_preset した PS
#   (2) board_part の無いプロジェクト（-1）で、作っただけの PS（build.tcl の -1 のビルドの出発点と同じ）
#   さらに (2) に違いを**まとめて 1 回で**当てて（build.tcl と同じ当て方）、読み返しが一致したものを「当てる設定」にする。
#   一致しないもの（導出される・無効にされた・読み出し専用）は別に数えて出す（build.tcl は当てずに、読み返しの照合だけに使う）
#   1 回目（2026-10-01）は 1 個ずつ当てていて、DDR の周波数・タイミング・MIO の割り当てのように**互いに依存する設定**が、
#   途中の組み合わせで検証に落ちて 88 個「当てられない」になった（DDR 1200 MHz が既定の速度ビンの範囲外、SD0 と I2C0 の MIO の衝突など）
#
# 出力: src/ps_preset.tcl（リポジトリに入れる。生成物だが、**版を git に残す**ため）/ build-ps-preset/ps_preset.log
#   プロジェクトは build-ps-preset/ の下に作る（1 回目は -in_memory で、BD がカレントの .srcs/ に書かれた）
#   書き直したら git diff で中身の変わり方を見る（BSP・Vivado の版で変わりうる）

set board_part_part xczu48dr-ffvg1517-2-e
set part_m1         xczu48dr-ffvg1517-1-e
set out_tcl         ./src/ps_preset.tcl
set logdir          ./build-ps-preset
file mkdir $logdir
if {[info exists ::env(BOARD_REPO)] && $::env(BOARD_REPO) ne ""} { set_param board.repoPaths $::env(BOARD_REPO) }

proc ps_cfg {cell} {
    set d [dict create]
    foreach k [list_property $cell CONFIG.*] { dict set d $k [get_property $k $cell] }
    return $d
}

# ---- (1) プリセットを当てた PS ----
create_project pre $logdir/pre -part $board_part_part -force
set bp [lindex [get_board_parts -quiet -latest_file_version *rfsoc4x2*] 0]
if {$bp eq ""} { puts "ERROR: RFSoC4x2 の board part が見つからない（BOARD_REPO を確かめる）"; exit 1 }
set_property board_part $bp [current_project]
create_bd_design pre
set ps1 [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e ps]
apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e -config {apply_board_preset "1"} $ps1
set vlnv [get_property VLNV $ps1]
set cfg1 [ps_cfg $ps1]
close_project

# ---- (2) board_part の無い -1 の PS ----
create_project base $logdir/base -part $part_m1 -force
create_bd_design base
set ps2 [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e ps]
if {[get_property VLNV $ps2] ne $vlnv} { puts "ERROR: PS の VLNV が (1) $vlnv と (2) [get_property VLNV $ps2] で違う"; exit 1 }
set cfg2 [ps_cfg $ps2]

set diff [dict create]
set skip {CONFIG.Component_Name}
dict for {k v} $cfg1 {
    if {[lsearch -exact $skip $k] >= 0} continue
    if {![dict exists $cfg2 $k]} { puts "WARNING: $k は board_part の無い PS に無い（飛ばす）"; continue }
    if {[dict get $cfg2 $k] ne $v} { dict set diff $k $v }
}
puts "違う CONFIG: [dict size $diff] 個（全 [dict size $cfg1] 個のうち）"

# ---- (2) にまとめて当てて読み返す（build.tcl と同じ: set_property -dict を 1 回）----
set settable [dict create]
set derived  [dict create]
set fh_log [open $logdir/ps_preset.log w]
if {[catch {set_property -dict $diff $ps2} msg]} {
    puts "ERROR: まとめて当てると検証に落ちる: $msg"
    puts $fh_log "まとめて当てて落ちた: $msg"
    close $fh_log
    exit 1
}
dict for {k v} $diff {
    set got [get_property $k $ps2]
    if {$got eq $v} { dict set settable $k $v } else {
        dict set derived $k $v
        puts $fh_log "読み返しが違う: $k = $got（プリセット $v）"
    }
}
close $fh_log
# 読み返しが違うものをコンソールにも（中身を見て、本当に導出されるだけかを判断する）
dict for {k v} $derived { puts "  読み返しが違う: $k = [get_property $k $ps2]（プリセット $v）" }
puts "当てる設定: [dict size $settable] 個 / 当てられない・導出される: [dict size $derived] 個（$logdir/ps_preset.log）"
if {[dict size $settable] == 0} { puts "ERROR: 当てる設定が 0 個（board part のプリセットが効いていない？）"; exit 1 }

set fh [open $out_tcl w]
puts $fh "# SPDX-License-Identifier: BSD-3-Clause"
puts $fh "# 生成物（tools/dump_ps_preset.tcl、make ps-preset）。**手で直さない。** build.tcl が -1 のビルドで PS に当てる"
puts $fh "# board part: $bp / PS: $vlnv / Vivado [version -short]"
puts $fh "# 当てる設定 [dict size $settable] 個（ps_preset）、読み返しだけ照らす [dict size $derived] 個（ps_preset_derived）"
puts $fh "set ps_preset_board_part {$bp}"
puts $fh "set ps_preset_vlnv {$vlnv}"
puts $fh "set ps_preset \[list \\"
foreach k [lsort [dict keys $settable]] { puts $fh "    $k {[dict get $settable $k]} \\" }
puts $fh "\]"
puts $fh "set ps_preset_derived \[list \\"
foreach k [lsort [dict keys $derived]] { puts $fh "    $k {[dict get $derived $k]} \\" }
puts $fh "\]"
close $fh
puts "=== wrote $out_tcl ==="
close_project
