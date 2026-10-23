# SPDX-License-Identifier: BSD-3-Clause
# proj028 S-2 — PL DDR4 の帯域と容量を測る .bit（make build）。RFDC は載せない
#
#   PS（-1 では src/board/ps_preset.tcl を当てて読み返す。proj015 から）
#     M_AXI_HPM0_FPD（pl_clk0 100 MHz）→ smc_ctrl（SmartConnect、NUM_CLKS 2: pl_clk0 / MIG の UI クロック）→ ddr_tg_0/s_axi
#   sys_clk_ddr4（200 MHz、G13/G12）→ IBUFDS → BUFG → ddr4_0/c0_sys_clk_i（System_Clock No_Buffer。PYNQ の base overlay と同じ）
#   ddr4_0（MIG、PYNQ の base overlay と同じ設定。README の S-1）→ C0_DDR4 = 外部の ddr4_pl（足は src/board/ddr4.xdc）
#   ddr_tg_0（src/ddr_tg.v、module reference）: clk = c0_ddr4_ui_clk、m_axi → ddr4_0/C0_DDR4_S_AXI、calib = c0_init_calib_complete
#   リセット: rst_ctrl（pl_clk0、pl_resetn0）→ ddr4_0/sys_rst（peripheral_reset、高で効く）
#             rst_ui（UI クロック、ext_reset_in = c0_ddr4_ui_clk_sync_rst（高）・dcm_locked = c0_init_calib_complete）→ ddr_tg_0・ddr4_0 の aresetn
#
# 見張り（LESSONS）: part の照合・PS のプリセットの読み返し・MIG の設定の読み返し・結線の照合（在るべき相手と、在ってはいけない相手）・
#   足の配置の読み返し・run と vivado.log の CRITICAL WARNING・落ちた印のある run だけ回し直す・WNS < 0 で止める
# 出力: $outdir/proj028.bit・.hwh（同名同階層。PYNQ が要る）・timing.rpt・utilization.rpt
set proj    proj028
set bd_name system
set part    xczu48dr-ffvg1517-1-e
set outdir  ./build
set jobs    8
if {[info exists ::env(PART)]   && $::env(PART)   ne ""} { set part   $::env(PART) }
if {[info exists ::env(OUTDIR)] && $::env(OUTDIR) ne ""} { set outdir ./$::env(OUTDIR) }
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }
set projdir $outdir/vivado
set ctrl_mhz 100
puts "PART   : $part"
puts "OUTDIR : $outdir"
puts "JOBS   : $jobs"
file mkdir $outdir

if {$part ne "xczu48dr-ffvg1517-1-e"} {
    puts "ERROR: proj028 S-2 は -1 だけを作る（PS のプリセットの当て方が -1 の形）。PART=$part"
    exit 1
}
create_project $proj $projdir -part $part -force
set part_actual [get_property PART [current_project]]
if {$part_actual ne $part} { puts "ERROR: part が違う（要求 $part・実際 $part_actual）"; exit 1 }

# ---- RTL ----
add_files [file normalize ./src/ddr_tg.v]
add_files [file normalize ./src/clk_mon.v]
add_files -fileset constrs_1 [file normalize ./src/board/ddr4.xdc]
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
# 使う AXI は HPM0_FPD だけ。**使わないものも明示的に 0 にする**（proj002 の BD 41-758）
set_property -dict [list \
    CONFIG.PSU__FPGA_PL0_ENABLE {1} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ $ctrl_mhz \
    CONFIG.PSU__FPGA_PL1_ENABLE {0} \
    CONFIG.PSU__USE__M_AXI_GP0 {1} \
    CONFIG.PSU__USE__M_AXI_GP1 {0} \
    CONFIG.PSU__USE__M_AXI_GP2 {0} \
    CONFIG.PSU__USE__S_AXI_GP0 {0} \
    CONFIG.PSU__USE__S_AXI_GP1 {0} \
    CONFIG.PSU__USE__S_AXI_GP2 {0} \
    CONFIG.PSU__USE__S_AXI_GP3 {0} \
    CONFIG.PSU__USE__S_AXI_GP4 {0} \
    CONFIG.PSU__USE__S_AXI_GP5 {0} \
    CONFIG.PSU__USE__S_AXI_GP6 {0} \
    CONFIG.PSU__USE__IRQ0 {0} \
    CONFIG.PSU__USE__IRQ1 {0} \
] $ps

# ---- MIG（README の S-1 の実機の設定。読み返して照らす）----
set mig [create_bd_cell -type ip -vlnv xilinx.com:ip:ddr4 ddr4_0]
set mig_req {
    CONFIG.C0.DDR4_MemoryType         Components
    CONFIG.C0.DDR4_DataWidth          64
    CONFIG.C0.DDR4_MemoryPart         MT40A1G16RC-062E
    CONFIG.C0.DDR4_TimePeriod         833
    CONFIG.C0.DDR4_InputClockPeriod   4998
    CONFIG.C0.BANK_GROUP_WIDTH        1
    CONFIG.C0.DDR4_CasLatency         17
    CONFIG.C0.DDR4_CasWriteLatency    12
    CONFIG.System_Clock               No_Buffer
    CONFIG.C0.DDR4_DataMask           DM_NO_DBI
    CONFIG.C0.DDR4_Ecc                false
    CONFIG.C0.DDR4_AxiSelection       true
    CONFIG.C0.DDR4_AxiDataWidth       512
    CONFIG.C0.DDR4_AxiAddressWidth    33
}
set ng 0
foreach {k v} $mig_req { if {[catch {set_property $k $v $mig} m]} { incr ng; puts "  MIG: $k = $v を設定できない: $m" } }
foreach {k v} $mig_req { set got ""; catch {set got [get_property $k $mig]}; if {![string equal -nocase $got $v]} { incr ng; puts "  MIG 違う: $k = $got（要求 $v）" } }
set mig_idw [get_property CONFIG.C0.DDR4_AxiIDWidth $mig]
puts "MIG     : 要求 [expr {[llength $mig_req] / 2}] 個のうち違う $ng 個・AXI ID $mig_idw bit"
if {$ng > 0} { puts "ERROR: MIG の設定が要求どおりにならない"; exit 1 }

# ---- 参照クロック ----
set p_sys [create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:diff_clock_rtl:1.0 sys_clk_ddr4]
set_property CONFIG.FREQ_HZ 200000000 $p_sys
set ibuf [create_bd_cell -type ip -vlnv xilinx.com:ip:util_ds_buf ibufds_ddr4]
set_property CONFIG.C_BUF_TYPE IBUFDS $ibuf
set bufg [create_bd_cell -type ip -vlnv xilinx.com:ip:util_ds_buf bufg_ddr4]
set_property CONFIG.C_BUF_TYPE BUFG $bufg
connect_bd_intf_net $p_sys [get_bd_intf_pins ibufds_ddr4/CLK_IN_D]
connect_bd_net [get_bd_pins ibufds_ddr4/IBUF_OUT] [get_bd_pins bufg_ddr4/BUFG_I]
connect_bd_net [get_bd_pins bufg_ddr4/BUFG_O] [get_bd_pins ddr4_0/c0_sys_clk_i]

# ---- DDR4 の外部ポート ----
set p_ddr [create_bd_intf_port -mode Master -vlnv xilinx.com:interface:ddr4_rtl:1.0 ddr4_pl]
connect_bd_intf_net [get_bd_intf_pins ddr4_0/C0_DDR4] $p_ddr

# ---- リセット ----
set rst_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_ctrl]
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] [get_bd_pins rst_ctrl/slowest_sync_clk]
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_resetn0] [get_bd_pins rst_ctrl/ext_reset_in]
connect_bd_net [get_bd_pins rst_ctrl/peripheral_reset] [get_bd_pins ddr4_0/sys_rst]
set rst_ui [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_ui]
# ext_reset_in の極性（C_EXT_RESET_HIGH）はつないだピンの極性から伝わる read-only の値。設定せず、validate の後で 1 を読み返す
#   （1 回目のビルドは設定しようとして CRITICAL WARNING BD 41-737 を出した。値は 1 で正しかった）
connect_bd_net [get_bd_pins ddr4_0/c0_ddr4_ui_clk] [get_bd_pins rst_ui/slowest_sync_clk]
connect_bd_net [get_bd_pins ddr4_0/c0_ddr4_ui_clk_sync_rst] [get_bd_pins rst_ui/ext_reset_in]
# dcm_locked は定数 1: ddr_tg の制御の口は UI クロックのリセットが明けたら受ける（較正の終わりまで待たせない）。
#   DDR への読み書きは ddr_tg の中で calib が立つまで出さない。
#   （1 回目の実機: dcm_locked = calib で、較正の前の読みが応答を返さず PS ごと止まった。2026-10-23）
set one [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant one_ui]
set_property -dict [list CONFIG.CONST_WIDTH 1 CONFIG.CONST_VAL 1] $one
connect_bd_net [get_bd_pins one_ui/dout] [get_bd_pins rst_ui/dcm_locked]

# ---- ddr_tg ----
set tg [create_bd_cell -type module -reference ddr_tg ddr_tg_0]
set_property CONFIG.IDW $mig_idw $tg
connect_bd_net [get_bd_pins ddr4_0/c0_ddr4_ui_clk] [get_bd_pins ddr_tg_0/clk]
connect_bd_net [get_bd_pins rst_ui/peripheral_aresetn] [get_bd_pins ddr_tg_0/aresetn] [get_bd_pins ddr4_0/c0_ddr4_aresetn]
connect_bd_net [get_bd_pins ddr4_0/c0_init_calib_complete] [get_bd_pins ddr_tg_0/calib]
connect_bd_intf_net [get_bd_intf_pins ddr_tg_0/m_axi] [get_bd_intf_pins ddr4_0/C0_DDR4_S_AXI]

# ---- 制御（SmartConnect が乗り換えを持つ。自作の CDC は書かない）----
set smc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_ctrl]
set_property -dict [list CONFIG.NUM_SI 1 CONFIG.NUM_MI 2 CONFIG.NUM_CLKS 2] $smc
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] [get_bd_pins smc_ctrl/aclk] [get_bd_pins zynq_ultra_ps_e_0/maxihpm0_fpd_aclk]
connect_bd_net [get_bd_pins ddr4_0/c0_ddr4_ui_clk] [get_bd_pins smc_ctrl/aclk1]
connect_bd_net [get_bd_pins rst_ctrl/interconnect_aresetn] [get_bd_pins smc_ctrl/aresetn]
connect_bd_intf_net [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_FPD] [get_bd_intf_pins smc_ctrl/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins smc_ctrl/M00_AXI] [get_bd_intf_pins ddr_tg_0/s_axi]

# ---- clk_mon（pl_clk0 の側。MIG のクロックに依らずに読める見張り。PS は ddr_tg より先にここを読む）----
set cm [create_bd_cell -type module -reference clk_mon clk_mon_0]
connect_bd_net [get_bd_pins zynq_ultra_ps_e_0/pl_clk0] [get_bd_pins clk_mon_0/clk]
connect_bd_net [get_bd_pins rst_ctrl/peripheral_aresetn] [get_bd_pins clk_mon_0/aresetn]
connect_bd_net [get_bd_pins bufg_ddr4/BUFG_O] [get_bd_pins clk_mon_0/ref_clk]
connect_bd_net [get_bd_pins ddr4_0/c0_ddr4_ui_clk] [get_bd_pins clk_mon_0/ui_clk]
connect_bd_net [get_bd_pins ddr4_0/c0_init_calib_complete] [get_bd_pins clk_mon_0/calib]
connect_bd_net [get_bd_pins ddr4_0/c0_ddr4_ui_clk_sync_rst] [get_bd_pins clk_mon_0/ui_rst]
connect_bd_intf_net [get_bd_intf_pins smc_ctrl/M01_AXI] [get_bd_intf_pins clk_mon_0/s_axi]

# ---- 番地 ----
assign_bd_address
# assign_bd_address がどちらを 0xA000_0000 に置くかは決まっていないので、先に clk_mon を空いた番地へ動かしてから ddr_tg を置く
#   （1 回目の作り直しで clk_mon が 0xA000_0000 に置かれ、ddr_tg と重なって BD 41-70 で止まった）
set seg_tg [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces zynq_ultra_ps_e_0/Data] -filter {NAME =~ *ddr_tg_0*}]
if {[llength $seg_tg] != 1} { puts "ERROR: ddr_tg_0 の番地の区画が 1 個でない（$seg_tg）"; exit 1 }
set seg_cm [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces zynq_ultra_ps_e_0/Data] -filter {NAME =~ *clk_mon_0*}]
if {[llength $seg_cm] != 1} { puts "ERROR: clk_mon_0 の番地の区画が 1 個でない（$seg_cm）"; exit 1 }
set_property range 4K $seg_cm
set_property offset 0xA0010000 $seg_cm
set_property range 4K $seg_tg
set_property offset 0xA0000000 $seg_tg
set_property offset 0xA0001000 $seg_cm
set seg_ddr [get_bd_addr_segs -quiet -of_objects [get_bd_addr_spaces ddr_tg_0/m_axi] ]
puts "番地    : ddr_tg_0 = [get_property offset $seg_tg]（[get_property range $seg_tg]）・clk_mon_0 = [get_property offset $seg_cm]・ddr_tg の m_axi → [get_property range [lindex $seg_ddr 0]]"

validate_bd_design
save_bd_design
foreach {cell want} {rst_ui 1 rst_ctrl 0} {
    set got [get_property CONFIG.C_EXT_RESET_HIGH [get_bd_cells $cell]]
    puts "リセット: $cell の ext_reset_in は [expr {$got ? {高} : {低}}] で効く（C_EXT_RESET_HIGH $got）"
    if {$got ne $want} { puts "ERROR: $cell の ext_reset_in の極性が違う（期待 $want）。ddr_tg がリセットされたまま・されないままになる"; exit 1 }
}

# ---- 結線の照合（在るべき相手と、在ってはいけない相手）----
proc net_pins {pin} {
    set n [get_bd_nets -quiet -of_objects [get_bd_pins $pin]]
    if {$n eq ""} { return {} }
    return [lsort [get_bd_pins -quiet -of_objects $n]]
}
set ng 0
foreach {pin must mustnot} {
    ddr_tg_0/clk     {/ddr4_0/c0_ddr4_ui_clk /smc_ctrl/aclk1 /rst_ui/slowest_sync_clk} {/zynq_ultra_ps_e_0/pl_clk0}
    ddr_tg_0/aresetn {/rst_ui/peripheral_aresetn /ddr4_0/c0_ddr4_aresetn}                {/rst_ctrl/peripheral_aresetn /rst_ctrl/interconnect_aresetn}
    ddr_tg_0/calib   {/ddr4_0/c0_init_calib_complete /clk_mon_0/calib}                   {/rst_ui/dcm_locked}
    rst_ui/dcm_locked {/one_ui/dout}                                                     {/ddr4_0/c0_init_calib_complete}
    clk_mon_0/clk    {/zynq_ultra_ps_e_0/pl_clk0}                                        {/ddr4_0/c0_ddr4_ui_clk}
    clk_mon_0/aresetn {/rst_ctrl/peripheral_aresetn}                                     {/rst_ui/peripheral_aresetn}
    clk_mon_0/ref_clk {/bufg_ddr4/BUFG_O /ddr4_0/c0_sys_clk_i}                           {}
    clk_mon_0/ui_rst {/ddr4_0/c0_ddr4_ui_clk_sync_rst /rst_ui/ext_reset_in}              {}
    smc_ctrl/aclk    {/zynq_ultra_ps_e_0/pl_clk0}                                        {/ddr4_0/c0_ddr4_ui_clk}
    ddr4_0/sys_rst   {/rst_ctrl/peripheral_reset}                                        {/rst_ui/peripheral_reset}
} {
    set got [net_pins $pin]
    foreach m $must    { if {[lsearch -exact $got $m] < 0} { incr ng; puts "  結線: $pin のネットに $m が無い（$got）" } }
    foreach m $mustnot { if {[lsearch -exact $got $m] >= 0} { incr ng; puts "  結線: $pin のネットに $m が在ってはいけない" } }
}
# 陽性対照: 照合の手続きが「無い」を見つけられること（在るはずの無い相手を must に置く）
set got [net_pins ddr_tg_0/clk]
if {[lsearch -exact $got /zynq_ultra_ps_e_0/pl_clk0] >= 0} { incr ng; puts "  陽性対照: pl_clk0 が ddr_tg の clk に在る（照合が壊れている）" }
if {[llength $got] < 3} { incr ng; puts "  陽性対照: ddr_tg_0/clk のネットのピンが読めていない（$got）" }
puts "結線の照合: 違う $ng 個"
if {$ng > 0} { puts "ERROR: 結線の照合で落ちた"; exit 1 }

make_wrapper -files [get_files $projdir/$proj.srcs/sources_1/bd/$bd_name/$bd_name.bd] -top
add_files -norecurse [glob $projdir/$proj.gen/sources_1/bd/$bd_name/hdl/${bd_name}_wrapper.v]
set_property top ${bd_name}_wrapper [current_fileset]
update_compile_order -fileset sources_1

# ---- run（落ちた印のある run だけ 2 回まで回し直す。proj012〜025）----
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

# ---- clk_mon の同期器の false path が効く相手が在るか（XDC の get_cells が空だと、制約は黙って効かない）----
set n_sync [llength [get_cells -quiet -hierarchical -filter {NAME =~ */clk_mon_0/inst/s_ref_reg[0] || NAME =~ */clk_mon_0/inst/s_ui_reg[0] || NAME =~ */clk_mon_0/inst/s_cal_reg[0] || NAME =~ */clk_mon_0/inst/s_rst_reg[0]}]]
puts "clk_mon の同期器の 1 段目: $n_sync 個（期待 4）"
if {$n_sync != 4} { puts "ERROR: clk_mon.xdc の false path の相手が 4 個でない（セルの名前が変わった？）"; exit 1 }

# ---- 足の配置の読み返し（PYNQ の base.xdc と BSP の 4x2_PL_DDR4.xdc で 115 本とも一致を確かめた足から 5 本）----
set ng 0
foreach {pname want} {sys_clk_ddr4_clk_p G13 ddr4_pl_act_n B14 {ddr4_pl_dq[0]} K17 ddr4_pl_reset_n E14 {ddr4_pl_adr[0]} B13} {
    set prt [get_ports -quiet $pname]
    if {[llength $prt] == 0} { incr ng; puts "  足: ポート $pname が無い"; continue }
    set got [get_property PACKAGE_PIN $prt]
    puts [format "  足: %-20s %-5s %s" $pname $got [get_property IOSTANDARD $prt]]
    if {$got ne $want} { incr ng; puts "  足: $pname が $got（期待 $want）" }
}
if {$ng > 0} { puts "ERROR: 足の配置が違う"; exit 1 }

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
