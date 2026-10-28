# SPDX-License-Identifier: BSD-3-Clause
# proj032 D-3 — PL から PS の DDR へ、HP の口 4 本（ADC ごと）で同時に書く .bit（make build）。RFDC・MIG は載せない
#   （D-1 の build.tcl の形。PS のプリセット・結線の照合・CRITICAL WARNING の拾い上げ・WNS で止めるのは同じ）
#
#   PS（-1 では src/board/ps_preset.tcl を当てて読み返す）
#     M_AXI_HPM0_FPD（pl_clk0 100 MHz）→ smc_ctrl（SmartConnect、NUM_CLKS 2: pl_clk0 / clk_dsp）→ hp_tg_0..3/s_axi・clk_mon_0/s_axi
#   clk_wiz_dsp: pl_clk0 100 MHz → clk_dsp 256 MHz（本番の DSP のクロックと同じ速さ。100 / 5 × 64 / 5）
#   hp_tg_i（src/hp_tg.v、module reference）: clk = clk_dsp、m_axi → S_AXI_HPi_FPD（GP 2 + i、128 bit、saxihpi_fpd_aclk = clk_dsp）
#   clk_mon_0（pl_clk0 の側）: ref_clk・ui_clk = clk_dsp、calib = clk_wiz の locked、ui_rst = rst_dsp の peripheral_reset
#     PS は hp_tg に触る前にここを読む（clk_dsp が回らないまま hp_tg を読むと、応答が返らず PS ごと止まる: D-1 の 2026-10-23）
#   リセット: rst_ctrl（pl_clk0、pl_resetn0）/ rst_dsp（clk_dsp、ext = pl_resetn0・dcm_locked = clk_wiz の locked）
# 出力: $outdir/proj032d3.bit・.hwh・timing.rpt・utilization.rpt
set proj    proj032d3
set bd_name system
set part    xczu48dr-ffvg1517-1-e
set outdir  ./build
set jobs    8
set nhp     4
if {[info exists ::env(PART)]   && $::env(PART)   ne ""} { set part   $::env(PART) }
if {[info exists ::env(OUTDIR)] && $::env(OUTDIR) ne ""} { set outdir ./$::env(OUTDIR) }
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }
set projdir $outdir/vivado
set ctrl_mhz 100
set dsp_mhz  256
puts "PART   : $part"
puts "OUTDIR : $outdir"
puts "JOBS   : $jobs"
file mkdir $outdir

if {$part ne "xczu48dr-ffvg1517-1-e"} {
    puts "ERROR: proj032 D-3 は -1 だけを作る（PS のプリセットの当て方が -1 の形）。PART=$part"
    exit 1
}
create_project $proj $projdir -part $part -force
set part_actual [get_property PART [current_project]]
if {$part_actual ne $part} { puts "ERROR: part が違う（要求 $part・実際 $part_actual）"; exit 1 }

# ---- RTL ----
add_files [file normalize ./src/hp_tg.v]
add_files [file normalize ./src/clk_mon.v]
add_files -fileset constrs_1 [file normalize ./src/board/clk_mon.xdc]
update_compile_order -fileset sources_1

create_bd_design $bd_name

# ---- PS ----
source [file normalize ./src/board/ps_preset.tcl]
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e zynq_ultra_ps_e_0]
if {[get_property VLNV $ps] ne $ps_preset_vlnv} {
    puts "ERROR: PS の VLNV [get_property VLNV $ps] が ps_preset.tcl の $ps_preset_vlnv と違う"; exit 1
}
set_property -dict $ps_preset $ps
set ng 0
foreach {k v} $ps_preset { if {[get_property $k $ps] ne $v} { incr ng; puts "  PS PRESET 違う: $k = [get_property $k $ps]（要求 $v）" } }
set nd 0
foreach {k v} $ps_preset_derived { set got ""; catch {set got [get_property $k $ps]}; if {$got ne $v} { incr nd } }
puts [format "PS PRESET : 当てた %d 個のうち違う %d 個 / 導出 %d 個のうち違う %d 個" [expr {[llength $ps_preset] / 2}] $ng [expr {[llength $ps_preset_derived] / 2}] $nd]
if {$ng > 0} { puts "ERROR: PS にプリセットが当たっていない"; exit 1 }
# 使う AXI は HPM0_FPD と HP0..3_FPD（S_AXI_GP2..5、128 bit）。**使わないものも明示的に 0 にする**（proj002 の BD 41-758）
#   S_AXI: GP0 = HPC0_FPD / GP1 = HPC1_FPD / GP2 = HP0_FPD / GP3..5 = HP1..3_FPD / GP6 = LPD（proj030）
set ps_req [list \
    CONFIG.PSU__FPGA_PL0_ENABLE {1} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ $ctrl_mhz \
    CONFIG.PSU__FPGA_PL1_ENABLE {0} \
    CONFIG.PSU__USE__M_AXI_GP0 {1} \
    CONFIG.PSU__USE__M_AXI_GP1 {0} \
    CONFIG.PSU__USE__M_AXI_GP2 {0} \
    CONFIG.PSU__USE__S_AXI_GP0 {0} \
    CONFIG.PSU__USE__S_AXI_GP1 {0} \
    CONFIG.PSU__USE__S_AXI_GP2 {1} \
    CONFIG.PSU__USE__S_AXI_GP3 {1} \
    CONFIG.PSU__USE__S_AXI_GP4 {1} \
    CONFIG.PSU__USE__S_AXI_GP5 {1} \
    CONFIG.PSU__SAXIGP2__DATA_WIDTH {128} \
    CONFIG.PSU__SAXIGP3__DATA_WIDTH {128} \
    CONFIG.PSU__SAXIGP4__DATA_WIDTH {128} \
    CONFIG.PSU__SAXIGP5__DATA_WIDTH {128} \
    CONFIG.PSU__USE__S_AXI_GP6 {0} \
    CONFIG.PSU__USE__IRQ0 {0} \
    CONFIG.PSU__USE__IRQ1 {0} \
]
set_property -dict $ps_req $ps
set ng 0
foreach {k v} $ps_req { if {[get_property $k $ps] ne $v} { incr ng; puts "  PS 違う: $k = [get_property $k $ps]（要求 $v）" } }
if {$ng > 0} { puts "ERROR: PS の口の設定が要求どおりにならない"; exit 1 }
puts "PS      : HP0..3_FPD を 128 bit で（DDR の速さ [get_property CONFIG.PSU__DDRC__SPEED_BIN $ps]・幅 [get_property CONFIG.PSU__DDRC__BUS_WIDTH $ps]）"

# ---- clk_dsp ----
# 入口の速さは pl_clk0 から伝わる値（99.999985 MHz）に任せる。100 と書くと BD 41-238（FREQ_HZ の食い違い）で validate が落ちる
set clkw [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz clk_wiz_dsp]
set_property -dict [list \
    CONFIG.PRIM_SOURCE                  {No_buffer} \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ   $dsp_mhz \
    CONFIG.USE_LOCKED                   {true} \
    CONFIG.USE_RESET                    {true} \
    CONFIG.RESET_TYPE                   {ACTIVE_LOW} \
    CONFIG.RESET_PORT                   {resetn} \
] $clkw
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] [get_bd_pins clk_wiz_dsp/clk_in1]
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_resetn0] [get_bd_pins clk_wiz_dsp/resetn]

# ---- リセット ----
set rst_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_ctrl]
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] [get_bd_pins rst_ctrl/slowest_sync_clk]
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_resetn0] [get_bd_pins rst_ctrl/ext_reset_in]
set rst_dsp [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_dsp]
connect_bd_net [get_bd_pins clk_wiz_dsp/clk_out1] [get_bd_pins rst_dsp/slowest_sync_clk]
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_resetn0] [get_bd_pins rst_dsp/ext_reset_in]
connect_bd_net [get_bd_pins clk_wiz_dsp/locked] [get_bd_pins rst_dsp/dcm_locked]

# ---- 制御（SmartConnect が乗り換えを持つ。自作の CDC は書かない）----
set smc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_ctrl]
set_property -dict [list CONFIG.NUM_SI 1 CONFIG.NUM_MI [expr {$nhp + 1}] CONFIG.NUM_CLKS 2] $smc
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] [get_bd_pins smc_ctrl/aclk] [get_bd_pins zynq_ultra_ps_e_0/maxihpm0_fpd_aclk]
connect_bd_net [get_bd_pins clk_wiz_dsp/clk_out1] [get_bd_pins smc_ctrl/aclk1]
connect_bd_net [get_bd_pins rst_ctrl/interconnect_aresetn] [get_bd_pins smc_ctrl/aresetn]
connect_bd_intf_net [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_FPD] [get_bd_intf_pins smc_ctrl/S00_AXI]

# ---- hp_tg × 4 ----
for {set i 0} {$i < $nhp} {incr i} {
    set tg [create_bd_cell -type module -reference hp_tg hp_tg_$i]
    connect_bd_net [get_bd_pins clk_wiz_dsp/clk_out1] [get_bd_pins hp_tg_$i/clk] [get_bd_pins zynq_ultra_ps_e_0/saxihp${i}_fpd_aclk]
    connect_bd_net [get_bd_pins rst_dsp/peripheral_aresetn] [get_bd_pins hp_tg_$i/aresetn]
    connect_bd_intf_net [get_bd_intf_pins hp_tg_$i/m_axi] [get_bd_intf_pins zynq_ultra_ps_e_0/S_AXI_HP${i}_FPD]
    connect_bd_intf_net [get_bd_intf_pins smc_ctrl/M0${i}_AXI] [get_bd_intf_pins hp_tg_$i/s_axi]
}

# ---- clk_mon（pl_clk0 の側）----
set cm [create_bd_cell -type module -reference clk_mon clk_mon_0]
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] [get_bd_pins clk_mon_0/clk]
connect_bd_net [get_bd_pins rst_ctrl/peripheral_aresetn] [get_bd_pins clk_mon_0/aresetn]
connect_bd_net [get_bd_pins clk_wiz_dsp/clk_out1] [get_bd_pins clk_mon_0/ref_clk] [get_bd_pins clk_mon_0/ui_clk]
connect_bd_net [get_bd_pins clk_wiz_dsp/locked] [get_bd_pins clk_mon_0/calib]
connect_bd_net [get_bd_pins rst_dsp/peripheral_reset] [get_bd_pins clk_mon_0/ui_rst]
connect_bd_intf_net [get_bd_intf_pins smc_ctrl/M0${nhp}_AXI] [get_bd_intf_pins clk_mon_0/s_axi]

# ---- 番地 ----
assign_bd_address
set data [get_bd_addr_spaces zynq_ultra_ps_e_0/Data]
set cells {}
for {set i 0} {$i < $nhp} {incr i} { lappend cells hp_tg_$i }
lappend cells clk_mon_0
set k 0
foreach c $cells {
    set seg [get_bd_addr_segs -quiet -of_objects $data -filter "NAME =~ *${c}*"]
    if {[llength $seg] != 1} { puts "ERROR: $c の番地の区画が 1 個でない（$seg）"; exit 1 }
    set_property range 4K $seg
    set_property offset [expr {0xA0100000 + 0x1000 * $k}] $seg
    incr k
}
# 先に空いた所へ動かしてから 0xA000_0000 に並べる（D-1: assign_bd_address の置き場所と重なって BD 41-70）
set k 0
foreach c $cells {
    set seg [get_bd_addr_segs -quiet -of_objects $data -filter "NAME =~ *${c}*"]
    set_property offset [expr {0xA0000000 + 0x1000 * $k}] $seg
    puts [format "番地    : %-10s %s" $c [get_property offset $seg]]
    incr k
}
# 書き手から PS の DDR（DDR_LOW）が見えること
for {set i 0} {$i < $nhp} {incr i} {
    set segs [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces hp_tg_$i/m_axi]]
    set low ""
    foreach s $segs { if {[string match "*DDR_LOW*" $s]} { set low $s } }
    if {$low eq ""} { puts "ERROR: hp_tg_$i/m_axi から PS の DDR_LOW が見えない（$segs）"; exit 1 }
    puts [format "DMA     : hp_tg_%d → %s %s +%s" $i $low [get_property offset $low] [get_property range $low]]
}

validate_bd_design
save_bd_design
foreach {cell want} {rst_dsp 0 rst_ctrl 0} {
    set got [get_property CONFIG.C_EXT_RESET_HIGH [get_bd_cells $cell]]
    puts "リセット: $cell の ext_reset_in は [expr {$got ? {高} : {低}}] で効く（C_EXT_RESET_HIGH $got）"
    if {$got ne $want} { puts "ERROR: $cell の ext_reset_in の極性が違う（期待 $want）"; exit 1 }
}
# CLKOUT1_ACTUAL_FREQ は空のことがある（2 回目のビルド）。MMCM の分周から計算する: 入口 × M / (D × O)
set fin [get_property CONFIG.PRIM_IN_FREQ $clkw]
set mm  [get_property CONFIG.MMCM_CLKFBOUT_MULT_F $clkw]
set dd  [get_property CONFIG.MMCM_DIVCLK_DIVIDE $clkw]
set oo  [get_property CONFIG.MMCM_CLKOUT0_DIVIDE_F $clkw]
set act [expr {$fin * $mm / ($dd * $oo)}]
puts "clk_dsp : 要求 $dsp_mhz MHz → $fin × $mm / ($dd × $oo) = $act MHz"
puts "clk_dsp の入口: [get_property CONFIG.PRIM_IN_FREQ $clkw] MHz"
if {abs($act - $dsp_mhz) > 1e-3} { puts "ERROR: clk_dsp が $dsp_mhz MHz にならない"; exit 1 }

# ---- 結線の照合（在るべき相手と、在ってはいけない相手）----
proc net_pins {pin} {
    set n [get_bd_nets -quiet -of_objects [get_bd_pins $pin]]
    if {$n eq ""} { return {} }
    return [lsort [get_bd_pins -quiet -of_objects $n]]
}
set ng 0
set chk {
    clk_mon_0/clk      {/zynq_ultra_ps_e_0/pl_clk0}                       {/clk_wiz_dsp/clk_out1}
    clk_mon_0/ref_clk  {/clk_wiz_dsp/clk_out1}                            {/zynq_ultra_ps_e_0/pl_clk0}
    clk_mon_0/aresetn  {/rst_ctrl/peripheral_aresetn}                     {/rst_dsp/peripheral_aresetn}
    clk_mon_0/calib    {/clk_wiz_dsp/locked /rst_dsp/dcm_locked}          {}
    smc_ctrl/aclk      {/zynq_ultra_ps_e_0/pl_clk0}                       {/clk_wiz_dsp/clk_out1}
    smc_ctrl/aclk1     {/clk_wiz_dsp/clk_out1}                            {/zynq_ultra_ps_e_0/pl_clk0}
}
for {set i 0} {$i < $nhp} {incr i} {
    lappend chk hp_tg_$i/clk [list /clk_wiz_dsp/clk_out1 /zynq_ultra_ps_e_0/saxihp${i}_fpd_aclk /rst_dsp/slowest_sync_clk] [list /zynq_ultra_ps_e_0/pl_clk0]
    lappend chk hp_tg_$i/aresetn [list /rst_dsp/peripheral_aresetn] [list /rst_ctrl/peripheral_aresetn /rst_ctrl/interconnect_aresetn]
}
foreach {pin must mustnot} $chk {
    set got [net_pins $pin]
    foreach m $must    { if {[lsearch -exact $got $m] < 0} { incr ng; puts "  結線: $pin のネットに $m が無い（$got）" } }
    foreach m $mustnot { if {[lsearch -exact $got $m] >= 0} { incr ng; puts "  結線: $pin のネットに $m が在ってはいけない" } }
}
# 陽性対照: 照合の手続きが「無い」を見つけられること
set got [net_pins hp_tg_0/clk]
if {[lsearch -exact $got /zynq_ultra_ps_e_0/pl_clk0] >= 0} { incr ng; puts "  陽性対照: pl_clk0 が hp_tg の clk に在る（照合が壊れている）" }
if {[llength $got] < 3} { incr ng; puts "  陽性対照: hp_tg_0/clk のネットのピンが読めていない（$got）" }
puts "結線の照合: 違う $ng 個"
if {$ng > 0} { puts "ERROR: 結線の照合で落ちた"; exit 1 }

make_wrapper -files [get_files $projdir/$proj.srcs/sources_1/bd/$bd_name/$bd_name.bd] -top
add_files -norecurse [glob $projdir/$proj.gen/sources_1/bd/$bd_name/hdl/${bd_name}_wrapper.v]
set_property top ${bd_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

# ---- run（落ちた印のある run だけ 2 回まで回し直す）----
proc run_dir {n} { return [file join $::projdir $::proj.runs $n] }
proc run_crashed {n} {
    set lf [file join [run_dir $n] runme.log]
    if {![file exists $lf]} { return 0 }
    set fh [open $lf r]; set t [read $fh]; close $fh
    return [regexp {Abnormal program termination|segfault in } $t]
}
launch_runs impl_1 -to_step write_bitstream -jobs $jobs
catch {wait_on_run impl_1}
for {set try 1} {$try <= 2 && [get_property PROGRESS [get_runs impl_1]] ne "100%"} {incr try} {
    set redo ""
    foreach r [get_runs] { if {[run_crashed [get_property NAME $r]]} { set redo [get_property NAME $r]; break } }
    if {$redo eq ""} { break }
    puts "NOTE: $redo で Vivado が落ちた。回し直す（$try 回目）"
    reset_run [get_runs $redo]
    launch_runs impl_1 -to_step write_bitstream -jobs $jobs
    catch {wait_on_run impl_1}
}
if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} { puts "ERROR: impl_1 が完走していない（$projdir の run のログ）"; exit 1 }

open_run impl_1

# ---- clk_mon の同期器の false path が効く相手が在るか ----
set n_sync [llength [get_cells -quiet -hierarchical -filter {NAME =~ */clk_mon_0/inst/s_ref_reg[0] || NAME =~ */clk_mon_0/inst/s_ui_reg[0] || NAME =~ */clk_mon_0/inst/s_cal_reg[0] || NAME =~ */clk_mon_0/inst/s_rst_reg[0]}]]
puts "clk_mon の同期器の 1 段目: $n_sync 個（期待 4）"
if {$n_sync != 4} { puts "ERROR: clk_mon.xdc の false path の相手が 4 個でない（セルの名前が変わった？）"; exit 1 }

report_timing_summary -file $outdir/timing.rpt
report_utilization    -file $outdir/utilization.rpt
report_clocks         -file $outdir/clocks.rpt
report_drc            -file $outdir/drc.rpt

# ---- CRITICAL WARNING（run の runme.log と、BD を組んだときの vivado.log）----
set seen 0
foreach lf [lsort [glob -nocomplain $projdir/$proj.runs/*/runme.log]] {
    set fh [open $lf r]
    foreach line [split [read $fh] \n] { if {[string match "CRITICAL WARNING*" $line]} { puts "  [file tail [file dirname $lf]]: $line"; incr seen } }
    close $fh
}
if {[info exists ::env(VIVADO_LOG)] && [file exists $::env(VIVADO_LOG)]} {
    set fh [open $::env(VIVADO_LOG) r]
    foreach line [split [read $fh] \n] { if {[string match "CRITICAL WARNING*" $line]} { puts "  vivado.log: $line"; incr seen } }
    close $fh
}
puts "CRITICAL WARNING: $seen 件"

set wns [get_property STATS.WNS [get_runs impl_1]]
set whs [get_property STATS.WHS [get_runs impl_1]]
puts "TIMING (確定): WNS $wns ns・WHS $whs ns"
if {$wns < 0 || $whs < 0} { puts "ERROR: タイミングが閉じていない"; exit 1 }

# ---- 成果物（.bit と .hwh を同名同階層に）----
set bit [lindex [glob -nocomplain $projdir/$proj.runs/impl_1/${bd_name}_wrapper.bit] 0]
if {$bit eq ""} { puts "ERROR: .bit が無い"; exit 1 }
file copy -force $bit $outdir/$proj.bit
set hwh [lindex [glob -nocomplain $projdir/$proj.gen/sources_1/bd/$bd_name/hw_handoff/${bd_name}.hwh] 0]
if {$hwh eq ""} { puts "ERROR: .hwh が無い"; exit 1 }
file copy -force $hwh $outdir/$proj.hwh
puts "=== wrote $outdir/$proj.bit・$outdir/$proj.hwh ==="
