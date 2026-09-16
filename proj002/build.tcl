# SPDX-License-Identifier: BSD-3-Clause
# proj002 — Zynq MPSoC + AXI GPIO（PYNQ オーバーレイ）
#
# proj001 と違い **project mode** を使う。
#   理由: PYNQ が読む .hwh は block design からしか生成されず、block design は
#         非プロジェクトモードでは作れない（create_bd_design が拒否される）。
#   生成物は build/ に集約し、Vivado のプロジェクトは build/vivado に閉じ込める。
#
# 出力:
#   build/proj002.bit   ビットストリーム
#   build/proj002.hwh   ハードウェアハンドオフ（PYNQ が読む。.bit と同名にする）

set proj         proj002
set part_default xczu48dr-ffvg1517-2-e
set part         $part_default
set bd_name      system
set outdir  ./build

# part と出力先は Makefile から環境変数で受ける。
# 既定以外の part（速度グレードの検証など）は別ディレクトリに出て、build/ を壊さない。
if {[info exists ::env(PART)] && $::env(PART) ne ""} { set part $::env(PART) }
if {[info exists ::env(OUTDIR)] && $::env(OUTDIR) ne ""} { set outdir ./$::env(OUTDIR) }
puts "PART   : $part"
puts "OUTDIR : $outdir"
set projdir $outdir/vivado

set jobs 8
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }

# ---- board files ----
# BSP の置き場所は環境ごとに違うので Makefile から環境変数で受け取る。
if {[info exists ::env(BOARD_REPO)] && $::env(BOARD_REPO) ne ""} {
    set_param board.repoPaths $::env(BOARD_REPO)
} else {
    puts "WARNING: BOARD_REPO が未設定。board part が見つからなければ Makefile を確認する"
}

file mkdir $outdir
create_project $proj $projdir -part $part -force

set board_repo "未設定"
if {[info exists ::env(BOARD_REPO)]} { set board_repo $::env(BOARD_REPO) }

set bp [lindex [get_board_parts -quiet -latest_file_version *rfsoc4x2*] 0]
if {$bp eq ""} {
    puts "ERROR: RFSoC4x2 の board part が見つからない。以下を順に確認する:"
    puts "  1. BOARD_REPO が RFSoC4x2-BSP/board_files を指しているか（= $board_repo）"
    puts "  2. その下に rfsoc4x2/<version>/board.xml があるか"
    puts "  3. BSP が Vivado 2024.1 前提。古い Vivado では読まれないことがある"
    exit 1
}
puts "BOARD PART: $bp"
set_property board_part $bp [current_project]

# ---- block design ----
create_bd_design $bd_name

# Zynq UltraScale+ PS。ボードプリセットを当てる（DDR・MIO・クロックの設定一式）
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e zynq_ultra_ps_e_0]
apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
    -config {apply_board_preset "1"} $ps

# PL クロック 100 MHz と AXI マスタを設定する。
# **使う AXI マスタだけでなく、使わないものも明示的に 0 にする。**
# ボードプリセットは HPM1_FPD も有効にするため、放置すると maxihpm1_fpd_aclk が
# どこにも繋がらず validate_bd_design が
#   ERROR: [BD 41-758] The following clock pins are not connected to a valid clock source
# で落ちる（2026-09-16 に実際に踏んだ）。
#   GP0 = M_AXI_HPM0_FPD（使う） / GP1 = M_AXI_HPM1_FPD / GP2 = M_AXI_HPM0_LPD
set_property -dict [list \
    CONFIG.PSU__FPGA_PL0_ENABLE {1} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ {100} \
    CONFIG.PSU__USE__M_AXI_GP0 {1} \
    CONFIG.PSU__USE__M_AXI_GP1 {0} \
    CONFIG.PSU__USE__M_AXI_GP2 {0} \
] $ps

# AXI GPIO。PYNQ 側からは ip_dict のキー "gpio_led" で引く
set gpio [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio gpio_led]
set_property -dict [list \
    CONFIG.C_GPIO_WIDTH {4} \
    CONFIG.C_ALL_OUTPUTS {1} \
    CONFIG.C_IS_DUAL {0} \
] $gpio

# AXI 接続（SmartConnect とリセットは automation に作らせる）
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config [list \
        Master {/zynq_ultra_ps_e_0/M_AXI_HPM0_FPD} \
        Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} \
        Slave {/gpio_led/S_AXI} \
        intc_ip {New AXI SmartConnect} master_apm {0} \
    ] [get_bd_intf_pins gpio_led/S_AXI]

# 外部ポート。ラッパのポート名が led[3:0] になり、XDC の記述が proj001 と揃う
create_bd_port -dir O -from 3 -to 0 led
connect_bd_net [get_bd_pins gpio_led/gpio_io_o] [get_bd_port led]

assign_bd_address
validate_bd_design
save_bd_design
puts "=== block design ok ==="

# board_part を設定すると、Vivado は project の part をボードの宣言値に強制的に
# 合わせる（WARNING: Project 1-153 "A device change ... is being done"）。
# そのため速度グレードの検証で -1 を指定しても黙って -2 に戻される。
# board_part が要るのはボードプリセットを当てる block design の生成までなので、
# ここで外して part を指定し直す。
if {$part ne $part_default} {
    puts "NOTE: 速度グレード検証のため board_part を外し、part を $part に設定し直す"
    set_property board_part "" [current_project]
    set_property part $part [current_project]
    reset_target    all [get_files ${bd_name}.bd]
    generate_target all [get_files ${bd_name}.bd]
}

# ---- ラッパと制約 ----
set bd_file [get_files ${bd_name}.bd]
make_wrapper -files $bd_file -top

set wrapper [lindex [glob -nocomplain \
    $projdir/$proj.gen/sources_1/bd/$bd_name/hdl/${bd_name}_wrapper.* \
    $projdir/$proj.srcs/sources_1/bd/$bd_name/hdl/${bd_name}_wrapper.*] 0]
if {$wrapper eq ""} { puts "ERROR: ラッパ HDL が見つからない"; exit 1 }
add_files -norecurse $wrapper
set_property top ${bd_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

add_files -fileset constrs_1 -norecurse ./src/led.xdc

# ---- part の検証 ----
# 黙ってすり替わっていないことを合成前に確かめる。
set part_actual [get_property PART [current_project]]
if {$part_actual ne $part} {
    puts "ERROR: 要求した part と実際の part が違う"
    puts "  要求: $part"
    puts "  実際: $part_actual"
    puts "  board_part がボードの宣言値に引き戻している可能性がある（WARNING: Project 1-153）"
    exit 1
}
puts "PART (確定): $part_actual"

# ---- 合成〜実装〜ビットストリーム ----
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    puts "ERROR: impl_1 が完走していない。build/vivado の run ログを見る"
    exit 1
}

open_run impl_1
report_timing_summary -file $outdir/timing.rpt
report_utilization    -file $outdir/utilization.rpt
report_drc            -file $outdir/drc.rpt

set wns [get_property STATS.WNS [get_runs impl_1]]
set whs [get_property STATS.WHS [get_runs impl_1]]
puts "TIMING: WNS = $wns ns / WHS = $whs ns"
if {$wns ne "" && $wns < 0} { puts "WARNING: セットアップ違反あり（WNS < 0）" }

# ---- 成果物を build/ 直下へ。PYNQ は .bit と .hwh が同名同階層であることを要求する ----
set bit [lindex [glob -nocomplain $projdir/$proj.runs/impl_1/${bd_name}_wrapper.bit] 0]
if {$bit eq ""} { puts "ERROR: .bit が見つからない"; exit 1 }
file copy -force $bit $outdir/$proj.bit

set hwh [lindex [glob -nocomplain \
    $projdir/$proj.gen/sources_1/bd/$bd_name/hw_handoff/${bd_name}.hwh \
    $projdir/$proj.srcs/sources_1/bd/$bd_name/hw_handoff/${bd_name}.hwh] 0]
if {$hwh eq ""} { puts "ERROR: .hwh が見つからない"; exit 1 }
file copy -force $hwh $outdir/$proj.hwh

puts "=== wrote $outdir/$proj.bit ==="
puts "=== wrote $outdir/$proj.hwh ==="
