# SPDX-License-Identifier: BSD-3-Clause
# proj009 — JTAG 書き込み
#
# 段階ごとに「見えているもの」を出力する。素の open_hw_target は target が 0 個のとき
# "There is no current hw_target" という原因を示さないエラーになるため。
#
#   make prog   書き込む
#   make id     デバイスを表示するだけ（合成ライセンス不要）

set id_only [expr {[llength $argv] > 0 && [lindex $argv 0] eq "id"}]
set outdir ./build
if {[info exists ::env(OUTDIR)] && $::env(OUTDIR) ne ""} { set outdir ./$::env(OUTDIR) }
set bitfile $outdir/proj009.bit

open_hw_manager
connect_hw_server -url localhost:3121   ;# 別機なら <host>:3121

# ---- JTAG target ----
set targets [get_hw_targets]
if {[llength $targets] == 0} {
    puts "ERROR: JTAG target が 0 個。以下を順に確認する:"
    puts "  1. ボードの電源が入っているか（電源 LED）"
    puts "  2. microUSB が PROG UART に挿さっているか（USB DEVICE では出ない）"
    puts "  3. データ用ケーブルか（充電専用ケーブルでは見えない）"
    puts "  4. lsusb に FTDI 0403:6010 が出るか"
    puts "  5. ケーブルドライバ / udev ルールが入っているか"
    exit 1
}
puts "TARGETS:"
foreach t $targets { puts "  $t" }

current_hw_target [lindex $targets 0]
open_hw_target

# ---- JTAG チェーン上のデバイス ----
set devs [get_hw_devices]
if {[llength $devs] == 0} {
    puts "ERROR: target は見えているがデバイスが居ない（TDO が返っていない）"
    exit 1
}
foreach d $devs { puts "DEVICE: $d  PART: [get_property PART $d]" }
# 注: PART は IDCODE 由来なので速度グレードは含まれない

if {$id_only} {
    close_hw_target
    close_hw_manager
    exit 0
}

# ---- 書き込み ----
set dev [lindex [get_hw_devices xczu48dr*] 0]
current_hw_device $dev
refresh_hw_device -update_hw_probes false $dev

set_property PROGRAM.FILE $bitfile $dev
program_hw_devices $dev
refresh_hw_device $dev
puts "=== programmed: $bitfile ==="
