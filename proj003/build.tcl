# SPDX-License-Identifier: BSD-3-Clause
# proj003 — RFDC → capture_gate → AXI4-Stream Data FIFO → AXI DMA → PS
#
# 出力:
#   build/proj003.bit   ビットストリーム
#   build/proj003.hwh   ハードウェアハンドオフ（PYNQ が読む。.bit と同名にする）
#   build/rfdc_params.rpt  RFDC IP が実際に持つ CONFIG 一覧（版がズレたときの突き合わせ用）
#
# ---- サンプリング周波数の根拠 ----
# LMX2594 が RFDC タイルへ 491.52 MHz を渡す（ボード既定）。タイル PLL で 983.04 MSPS。
#   VCO = fs × OutDiv。RFDC の PLL は VCO 8.5〜13.2 GHz。
#   OutDiv = 10 → VCO = 9.8304 GHz（範囲内） / FeedbackDiv = 9830.4/491.52 = 20
#   OutDiv = 8 なら 7.86 GHz、16 なら 15.7 GHz で **どちらも範囲外**。10 以外に選択肢はない。
# XRFdc のドライバは OutDiv として 1, 3 と 2〜32 の偶数を探索するので 10 は選ばれる。
#
# fs を変えるときはこの計算をやり直すこと。VCO が範囲外だと IP が黙って別の値に
# 丸める可能性があるため、下で **設定値を読み返して検証している**。
#
# ---- 版がズレたときの直し方 ----
# RFDC の CONFIG 名は Vivado の版で変わる。未知の名前があれば build は止まり、
# build/rfdc_params.rpt に実際の一覧が出る。それを見て cfg_rfdc のリストを直す。

set proj         proj003
set part_default xczu48dr-ffvg1517-2-e
set part         $part_default
set bd_name      system
set outdir       ./build

if {[info exists ::env(PART)]   && $::env(PART)   ne ""} { set part   $::env(PART) }
if {[info exists ::env(OUTDIR)] && $::env(OUTDIR) ne ""} { set outdir ./$::env(OUTDIR) }

# ---- 設計パラメータ ----
set adc_tile    2          ;# RF-ADC Tile 226 = IP 上の ADC2（RefMan A6: ADC_A / ADC_B が 226）
set adc_slice   0          ;# ADC_A。デュアルタイルのスライス番号は実機で裏を取ること
set fs_gsps     0.98304    ;# サンプリング周波数 [GSPS]
set refclk_mhz  491.520    ;# LMX2594 → RFDC タイル
set spw         8          ;# AXI4-Stream 1 語あたりのサンプル数
set ctrl_mhz    100        ;# pl_clk0: AXI4-Lite 制御系
set data_mhz    200        ;# pl_clk1: DMA の MM 側と HP ポート

set fabric_mhz  [format %.3f [expr {$fs_gsps * 1000.0 / $spw}]]
set fs_mhz      [format %.3f [expr {$fs_gsps * 1000.0}]]

puts "PART      : $part"
puts "OUTDIR    : $outdir"
puts "ADC       : Tile [expr {224 + 2*$adc_tile}] / slice $adc_slice"
puts "fs        : $fs_mhz MSPS （AXIS $fabric_mhz MHz × $spw sample/word）"

set projdir $outdir/vivado
set jobs 8
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }

# ------------------------------------------------------------------ helper
# 見つからなかったときに「何があるのか」を出す。素の get_bd_pins は空を返すだけで、
# connect_bd_net の側で意味の分からないエラーになる。
proc BP {path} {
    set p [get_bd_pins -quiet $path]
    if {[llength $p] == 0} {
        puts "ERROR: BD ピンが見つからない: $path"
        foreach q [get_bd_pins -quiet "[file dirname $path]/*"] { puts "    $q" }
        exit 1
    }
    return [lindex $p 0]
}
proc BI {cell patterns what} {
    foreach pat $patterns {
        set p [get_bd_intf_pins -quiet $cell/$pat]
        if {[llength $p] > 0} { return [lindex $p 0] }
    }
    puts "ERROR: $what が見つからない（$cell で試したパターン: $patterns）"
    puts "  $cell のインタフェースピン一覧:"
    foreach q [get_bd_intf_pins -quiet $cell/*] { puts "    $q" }
    exit 1
}
proc nc {a b} { connect_bd_net  [BP $a] [BP $b] }
proc ic {a b} { connect_bd_intf_net $a $b }

# CONFIG 名の存在を確かめてから設定する。知らない名前は集めて後でまとめて報告する。
proc cfg_apply {cell cfg} {
    set obj   [get_bd_cells $cell]
    set known [list_property $obj]
    set bad {}
    foreach {k v} $cfg {
        if {[lsearch -exact $known $k] < 0} {
            lappend bad $k
        } else {
            set_property $k $v $obj
        }
    }
    return $bad
}

# ------------------------------------------------------------------ project
if {[info exists ::env(BOARD_REPO)] && $::env(BOARD_REPO) ne ""} {
    set_param board.repoPaths $::env(BOARD_REPO)
    set board_repo $::env(BOARD_REPO)
} else {
    set board_repo "未設定"
    puts "WARNING: BOARD_REPO が未設定。board part が見つからなければ Makefile を確認する"
}

file mkdir $outdir
create_project $proj $projdir -part $part -force

# board_part は part をボードの宣言値（-2）へ強制的に戻す（WARNING: Project 1-153）。
# 速度グレードの検証ビルド（-1）では board_part もボードプリセットも使わない。
set use_board [expr {$part eq $part_default}]

if {$use_board} {
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
} else {
    puts "NOTE: 速度グレード検証ビルド。board_part とボードプリセットは使わない"
}

add_files -norecurse ./src/capture_gate.v
update_compile_order -fileset sources_1

# ------------------------------------------------------------------ block design
create_bd_design $bd_name

# ---- PS ----
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e zynq_ultra_ps_e_0]
if {$use_board} {
    apply_bd_automation -rule xilinx.com:bd_rule:zynq_ultra_ps_e \
        -config {apply_board_preset "1"} $ps
}

# 使う AXI ポートだけでなく、**使わないものも明示的に 0 にする**。
# ボードプリセットが何を有効にするかに設計が依存しないようにするため
# （proj002 で HPM1_FPD の未接続クロックにより BD 41-758 を踏んだ）。
#   M_AXI: GP0 = HPM0_FPD / GP1 = HPM1_FPD / GP2 = HPM0_LPD
#   S_AXI: GP0 = HPC0_FPD / GP1 = HPC1_FPD / GP2 = HP0_FPD / GP3..5 = HP1..3_FPD / GP6 = LPD
set_property -dict [list \
    CONFIG.PSU__FPGA_PL0_ENABLE {1} \
    CONFIG.PSU__CRL_APB__PL0_REF_CTRL__FREQMHZ $ctrl_mhz \
    CONFIG.PSU__FPGA_PL1_ENABLE {1} \
    CONFIG.PSU__CRL_APB__PL1_REF_CTRL__FREQMHZ $data_mhz \
    CONFIG.PSU__USE__M_AXI_GP0 {1} \
    CONFIG.PSU__USE__M_AXI_GP1 {0} \
    CONFIG.PSU__USE__M_AXI_GP2 {0} \
    CONFIG.PSU__USE__S_AXI_GP0 {0} \
    CONFIG.PSU__USE__S_AXI_GP1 {0} \
    CONFIG.PSU__USE__S_AXI_GP2 {1} \
    CONFIG.PSU__SAXIGP2__DATA_WIDTH {128} \
    CONFIG.PSU__USE__S_AXI_GP3 {0} \
    CONFIG.PSU__USE__S_AXI_GP4 {0} \
    CONFIG.PSU__USE__S_AXI_GP5 {0} \
    CONFIG.PSU__USE__S_AXI_GP6 {0} \
    CONFIG.PSU__USE__IRQ0 {0} \
    CONFIG.PSU__USE__IRQ1 {0} \
] $ps

# ---- RFDC ----
# PYNQ 側から ol.rfdc で引けるよう、セル名を rfdc にする
set rfdc [create_bd_cell -type ip -vlnv xilinx.com:ip:usp_rf_data_converter rfdc]

# 実際に持っている CONFIG を先に書き出す。版がズレたときはこれが唯一の手がかりになる
set fh [open $outdir/rfdc_params.rpt w]
puts $fh "# [get_property VLNV $rfdc]"
foreach k [lsort [list_property $rfdc]] {
    if {[string match CONFIG.* $k]} { puts $fh "$k = [get_property $k $rfdc]" }
}
close $fh
puts "=== wrote $outdir/rfdc_params.rpt ==="

set T $adc_tile
set S "${adc_tile}${adc_slice}"
set cfg_rfdc [list \
    CONFIG.ADC${T}_Enable            {1} \
    CONFIG.ADC${T}_PLL_Enable        {true} \
    CONFIG.ADC${T}_Refclk_Freq       $refclk_mhz \
    CONFIG.ADC${T}_Sampling_Rate     $fs_gsps \
    CONFIG.ADC${T}_Outclk_Freq       $fabric_mhz \
    CONFIG.ADC${T}_Fabric_Freq       $fabric_mhz \
    CONFIG.ADC${T}_Clock_Source      $T \
    CONFIG.ADC${T}_Clock_Dist        {0} \
    CONFIG.ADC${T}_Multi_Tile_Sync   {false} \
    CONFIG.ADC_Slice${S}_Enable      {true} \
    CONFIG.ADC_Data_Type${S}         {0} \
    CONFIG.ADC_Data_Width${S}        $spw \
    CONFIG.ADC_Decimation_Mode${S}   {1} \
    CONFIG.ADC_Mixer_Type${S}        {3} \
    CONFIG.ADC_Mixer_Mode${S}        {2} \
    CONFIG.ADC_NCO_Freq${S}          {0} \
    CONFIG.ADC_OBS${S}               {false} \
]
# 値の意味: Data_Type 0 = Real / Decimation_Mode 1 = 1x（デシメーションなし）
#           Mixer_Type 3 = Bypassed / Mixer_Mode 2 = Real→Real
# 版によって列挙の番号が動く可能性がある。疑うときは rfdc_params.rpt の既定値を見る。

set bad [cfg_apply rfdc $cfg_rfdc]
if {[llength $bad] > 0} {
    puts "ERROR: RFDC の CONFIG 名が Vivado の版と食い違っている:"
    foreach k $bad { puts "  未知: $k" }
    puts "  実際の一覧: $outdir/rfdc_params.rpt"
    exit 1
}

# **設定値を読み返す。** IP が要求を黙って丸める可能性があるため。
# part の検証（proj002）と同じ考え方で、要求と実際が違ったらここで止める。
foreach {k want} [list \
        CONFIG.ADC${T}_Sampling_Rate $fs_gsps \
        CONFIG.ADC${T}_Fabric_Freq   $fabric_mhz] {
    set got [get_property $k $rfdc]
    if {abs($got - $want) > 1e-6} {
        puts "ERROR: RFDC が設定を丸めた: $k  要求 $want / 実際 $got"
        puts "  PLL の VCO 範囲（8.5〜13.2 GHz）を外している可能性がある。"
        puts "  build.tcl 冒頭の計算をやり直すこと"
        exit 1
    }
}
puts "RFDC (確定): fs = [get_property CONFIG.ADC${T}_Sampling_Rate $rfdc] GSPS / fabric = [get_property CONFIG.ADC${T}_Fabric_Freq $rfdc] MHz"

# ---- キャプチャゲート（自作。TLAST の生成と記録の連続性を担う）----
set gate [create_bd_cell -type module -reference capture_gate capture_gate_0]
set_property CONFIG.DATA_W [expr {$spw * 16}] $gate

# ---- 非同期 FIFO（clk_adc → pl_clk1 の乗り換えをここに閉じ込める）----
set fifo [create_bd_cell -type ip -vlnv xilinx.com:ip:axis_data_fifo axis_fifo]
set_property -dict [list \
    CONFIG.TDATA_NUM_BYTES   [expr {$spw * 2}] \
    CONFIG.FIFO_DEPTH        {2048} \
    CONFIG.FIFO_MEMORY_TYPE  {block} \
    CONFIG.IS_ACLK_ASYNC     {1} \
    CONFIG.HAS_TLAST         {1} \
    CONFIG.HAS_TKEEP         {0} \
    CONFIG.HAS_TSTRB         {0} \
] $fifo

# ---- DMA（S2MM のみ・Simple mode）----
set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma dma_adc]
set_property -dict [list \
    CONFIG.c_include_sg               {0} \
    CONFIG.c_include_mm2s             {0} \
    CONFIG.c_include_s2mm             {1} \
    CONFIG.c_include_s2mm_dre         {0} \
    CONFIG.c_sg_length_width          {26} \
    CONFIG.c_m_axi_s2mm_data_width    [expr {$spw * 16}] \
    CONFIG.c_s_axis_s2mm_tdata_width  [expr {$spw * 16}] \
    CONFIG.c_s2mm_burst_size          {256} \
    CONFIG.c_addr_width               {40} \
    CONFIG.c_prmry_is_aclk_async      {1} \
] $dma

# ---- キャプチャ制御の GPIO ----
#   ch1 出力 32bit: [23:0] n_beats / [31] arm
#   ch2 入力 32bit: [0] busy / [1] done
set gpio [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio gpio_capture]
set_property -dict [list \
    CONFIG.C_GPIO_WIDTH   {32} \
    CONFIG.C_ALL_OUTPUTS  {1} \
    CONFIG.C_IS_DUAL      {1} \
    CONFIG.C_GPIO2_WIDTH  {32} \
    CONFIG.C_ALL_INPUTS_2 {1} \
] $gpio

# ---- リセット生成（3 ドメインぶん）----
set rst_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_ctrl]
set rst_data [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_data]
set rst_adc  [create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset rst_adc]

# ---- 相互接続 ----
set smc_ctrl [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_ctrl]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {3} CONFIG.NUM_CLKS {1}] $smc_ctrl
set smc_data [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_data]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1} CONFIG.NUM_CLKS {1}] $smc_data

# ------------------------------------------------------------------ 配線
set ps_clk0  zynq_ultra_ps_e_0/pl_clk0
set ps_clk1  zynq_ultra_ps_e_0/pl_clk1
set ps_rstn  zynq_ultra_ps_e_0/pl_resetn0

# RFDC の出力クロックとストリーム。ピン名は版で変わりうるので拾って確かめる
set adc_outclk rfdc/clk_adc${T}
BP $adc_outclk

# クロック
foreach p [list \
        rst_ctrl/slowest_sync_clk  smc_ctrl/aclk \
        rfdc/s_axi_aclk            dma_adc/s_axi_lite_aclk \
        gpio_capture/s_axi_aclk    capture_gate_0/ctrl_aclk \
        zynq_ultra_ps_e_0/maxihpm0_fpd_aclk] {
    nc $ps_clk0 $p
}
foreach p [list \
        rst_data/slowest_sync_clk  smc_data/aclk \
        dma_adc/m_axi_s2mm_aclk    axis_fifo/m_axis_aclk \
        zynq_ultra_ps_e_0/saxihp0_fpd_aclk] {
    nc $ps_clk1 $p
}
foreach p [list \
        rst_adc/slowest_sync_clk   rfdc/m${T}_axis_aclk \
        capture_gate_0/aclk        axis_fifo/s_axis_aclk] {
    nc $adc_outclk $p
}

# リセット
foreach r {rst_ctrl rst_data rst_adc} { nc $ps_rstn $r/ext_reset_in }
foreach p [list smc_ctrl/aresetn rfdc/s_axi_aresetn \
                dma_adc/axi_resetn gpio_capture/s_axi_aresetn] {
    nc rst_ctrl/peripheral_aresetn $p
}
nc rst_data/peripheral_aresetn smc_data/aresetn
foreach p [list rfdc/m${T}_axis_aresetn capture_gate_0/aresetn axis_fifo/s_axis_aresetn] {
    nc rst_adc/peripheral_aresetn $p
}

# キャプチャ制御
nc gpio_capture/gpio_io_o  capture_gate_0/ctrl
nc capture_gate_0/status   gpio_capture/gpio2_io_i

# データ経路
set rfdc_axis [BI rfdc [list "m${T}${adc_slice}_axis" "m${T}*_axis"] "RFDC の AXI4-Stream 出力"]
ic $rfdc_axis [get_bd_intf_pins capture_gate_0/s_axis]
ic [get_bd_intf_pins capture_gate_0/m_axis] [get_bd_intf_pins axis_fifo/S_AXIS]
ic [get_bd_intf_pins axis_fifo/M_AXIS]      [get_bd_intf_pins dma_adc/S_AXIS_S2MM]

# 制御系 AXI: PS → SmartConnect → RFDC / DMA / GPIO
ic [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_FPD] [get_bd_intf_pins smc_ctrl/S00_AXI]
ic [get_bd_intf_pins smc_ctrl/M00_AXI] [get_bd_intf_pins rfdc/s_axi]
ic [get_bd_intf_pins smc_ctrl/M01_AXI] [get_bd_intf_pins dma_adc/S_AXI_LITE]
ic [get_bd_intf_pins smc_ctrl/M02_AXI] [get_bd_intf_pins gpio_capture/S_AXI]

# データ系 AXI: DMA → SmartConnect → PS の HP0
ic [get_bd_intf_pins dma_adc/M_AXI_S2MM] [get_bd_intf_pins smc_data/S00_AXI]
ic [get_bd_intf_pins smc_data/M00_AXI]   [get_bd_intf_pins zynq_ultra_ps_e_0/S_AXI_HP0_FPD]

# ---- 外部ポート（RF のアナログ入力・タイルのクロック・SYSREF）----
# いずれも専用ピンなので XDC での配置制約は要らない。IP のタイル選択で決まる。
foreach {pats what} [list \
        [list "vin${T}_01" "vin${T}${adc_slice}" "vin${T}*"] "ADC アナログ入力" \
        [list "adc${T}_clk"]                                 "ADC タイルのクロック入力" \
        [list "sysref_in"]                                   "SYSREF 入力"] {
    set pin [BI rfdc $pats $what]
    make_bd_intf_pins_external $pin
    puts "EXTERNAL: $pin （$what）"
}

# ------------------------------------------------------------------ まとめ
assign_bd_address
validate_bd_design
save_bd_design

set fh [open $outdir/address_map.rpt w]
foreach seg [get_bd_addr_segs -excluded -quiet] { puts $fh "EXCLUDED $seg" }
foreach seg [get_bd_addr_segs -quiet] {
    puts $fh [format "%-56s %s +%s" $seg \
        [get_property OFFSET $seg] [get_property RANGE $seg]]
}
close $fh
puts "=== block design ok （アドレスマップ: $outdir/address_map.rpt）==="

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

add_files -fileset constrs_1 -norecurse ./src/timing.xdc

# ---- part の検証 ----
# board_part による part のすり替えは WARNING 1 行でしか通知されない。
# RFDC はボード依存の設定が多いので、ここで止めておく価値が proj002 より大きい。
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
    puts "ERROR: impl_1 が完走していない。$projdir の run ログを見る"
    exit 1
}

open_run impl_1
report_timing_summary -file $outdir/timing.rpt
report_utilization    -file $outdir/utilization.rpt
report_drc            -file $outdir/drc.rpt
report_clocks         -file $outdir/clocks.rpt

set wns [get_property STATS.WNS [get_runs impl_1]]
set whs [get_property STATS.WHS [get_runs impl_1]]
puts "TIMING: WNS = $wns ns / WHS = $whs ns"
if {$wns ne "" && $wns < 0} {
    puts "WARNING: セットアップ違反あり（WNS < 0）"
    puts "  まず src/timing.xdc の非同期クロックグループが効いているかを $outdir/clocks.rpt で確認する"
}

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

if {!$use_board} {
    puts ""
    puts "NOTE: これは速度グレード検証ビルド（$part）。"
    puts "      ボードプリセットを当てていないので、このビットストリームは実機に使わない。"
    puts "      見るのは上の TIMING の値だけ。"
}
