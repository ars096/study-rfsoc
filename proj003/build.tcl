# SPDX-License-Identifier: BSD-3-Clause
# proj003 — RFDC → capture_gate → AXI4-Stream Data FIFO → AXI DMA → PS
#
# 出力:
#   build/proj003.bit   ビットストリーム
#   build/proj003.hwh   ハードウェアハンドオフ（PYNQ が読む。.bit と同名にする）
#   build/rfdc_params.rpt  RFDC IP が実際に持つ CONFIG 一覧（版がズレたときの突き合わせ用）
#
# ---- サンプリング周波数の根拠 ----
# LMX2594 が RFDC タイルへ 491.52 MHz を渡す（ボード既定）。これは動かせない。
# 制約は 3 つ。**どれか 1 つを忘れると IP に弾かれる**（2026-09-16 に全部踏んだ）。
#
#   (a) IP の Sampling Rate の有効範囲は **(1.0, 5.0) GSPS**
#   (b) Refclk Freq の有効値は **VCO / FeedbackDiv の離散リスト**。
#       つまり **fs を先に決めないと refclk の選択肢が決まらない**
#   (c) VCO は 8.5〜13.2 GHz
#
# 491.52 = VCO / N を満たす VCO は N = 18..26 で 8847.36〜12779.52 MHz。
# そのうち fs = VCO / OutDiv が (1.0, 5.0) に入り、かつ AXIS とデータレートが
# 現実的なのは:
#
#   VCO = 9830.4 MHz (N=20, FeedbackDiv=20) / OutDiv = 8 → **fs = 1228.8 MSPS**
#     AXIS = 1228.8 / 8 sample = 153.6 MHz
#     データレート = 1228.8 MSPS × 2 B = 2.4576 GB/s（pl_clk1 200 MHz の 3.2 GB/s 以内）
#
# 他の候補: OutDiv = 6 → 1638.4 MSPS は 3.28 GB/s で MM 側が足りない。
#           OutDiv = 4 → 2457.6 MSPS は AXIS が 307 MHz で重い。
#
# fs を変えるときはこの計算をやり直すこと。下で **設定値を読み返して検証している**。
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
set fs_gsps     1.2288     ;# サンプリング周波数 [GSPS]。IP の有効範囲は (1.0, 5.0)
set refclk_mhz  491.520    ;# LMX2594 → RFDC タイル
set spw         8          ;# AXI4-Stream 1 語あたりのサンプル数
# RFDC の出力クロック。**AXIS のクロックではない。**有効値は fs/16, fs/32, fs/64。
# 最大（fs/16）を選ぶと Clocking Wizard の逓倍比が小さく済む。
set outclk_mhz  76.800     ;# = 1228.8 / 16
set ctrl_mhz    100        ;# pl_clk0: AXI4-Lite 制御系
set data_mhz    200        ;# pl_clk1: DMA の MM 側と HP ポート

set fabric_mhz  [format %.3f [expr {$fs_gsps * 1000.0 / $spw}]]
set fs_mhz      [format %.3f [expr {$fs_gsps * 1000.0}]]

puts "PART      : $part"
puts "OUTDIR    : $outdir"
puts "ADC       : Tile [expr {224 + $adc_tile}] / slice $adc_slice"
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

# CONFIG を **1 つずつ** 設定する。まとめて set_property すると最初の 1 つで止まり、
# 残りが正しいのかどうか分からないまま往復することになる。
# 失敗したものは「要求値」と「許される値」を控えて先へ進み、後でまとめて報告する。
# fatal = 0 の組は「設定できればよい」項目で、失敗しても止めない。
set ::cfg_fail {}

proc cfg_apply {cell cfg {fatal 1}} {
    set obj   [get_bd_cells $cell]
    set known [list_property $obj]
    foreach {k v} $cfg {
        if {[lsearch -exact $known $k] < 0} {
            lappend ::cfg_fail [list $k $v "この IP に存在しない名前" $fatal]
            continue
        }
        if {[catch {set_property $k $v $obj} msg]} {
            # list_property_value は BD セルの CONFIG では空を返す。
            # **有効値は Vivado のエラーメッセージ本文にしか出ない**ので、それを残す。
            set why [string map {"\n" " "} $msg]
            if {[regexp {Valid values are - (.*)$} $why -> vals]} {
                set why "有効値: $vals"
            } elseif {[regexp {is out of the range \(([^)]*)\)} $why -> rng]} {
                set why "有効範囲: ($rng)"
            }
            lappend ::cfg_fail [list $k $v $why $fatal]
        }
    }
}

proc cfg_report {stage} {
    if {[llength $::cfg_fail] == 0} { return }
    puts ""
    puts "---- CONFIG の設定に失敗した項目（$stage）----"
    set hard 0
    foreach f $::cfg_fail {
        lassign $f k v why isfatal
        puts "  $k = $v[expr {$isfatal ? "" : "   （任意）"}]"
        puts "      $why"
        if {$isfatal} { incr hard }
    }
    set ::cfg_fail {}
    puts ""
    if {$hard > 0} {
        puts "  IP が実際に持つ CONFIG と許容値は build/rfdc_params.rpt にある"
        exit 1
    }
}

# IP の CONFIG と、列挙なら許される値を書き出す。版がズレたときの唯一の手がかり。
proc dump_rfdc_params {obj path} {
    set fh [open $path w]
    puts $fh "# [get_property VLNV $obj]"
    foreach k [lsort [list_property $obj]] {
        if {![string match CONFIG.* $k]} continue
        set v ""       ; catch {set v [get_property $k $obj]}
        set allowed "" ; catch {set allowed [list_property_value $k $obj]}
        if {[llength $allowed] > 1} {
            puts $fh "$k = $v      \[$allowed\]"
        } else {
            puts $fh "$k = $v"
        }
    }
    close $fh
    puts "=== wrote $path ==="
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

set T $adc_tile
set S "${adc_tile}${adc_slice}"

# **設定の順序が全て。** 2026-09-16 に順に踏んだ内容を順序として固定してある。
#
#   1. スライスを有効にする。これをしないとタイルのパラメータは disabled parameter で、
#      set_property が WARNING: [BD 41-721] の 1 行だけ出して **黙って無視される**
#   2. スライスの設定（Data_Width 等）。Fabric_Freq の計算に効く
#   3. PLL を有効化 → **Sampling Rate** → **Refclk Freq** → Outclk Freq。
#      Refclk の有効値は VCO / FeedbackDiv の離散リストで、VCO は Sampling Rate から
#      決まる。**fs を先に入れないと 491.52 が選択肢に現れない**
#   4. 残り（派生値になりうるもの）
#
# ADC2_Enable と ADC2_Fabric_Freq は派生パラメータなので触らない（読むだけ）。
#
# 全段を「失敗しても止めない」で流し、**最後に読み返しで検証する**。
# 途中で止めると、その先の項目が正しいかどうか分からないまま次の 20 分を使うことになる。

# 1) 使うスライスを有効にする
cfg_apply rfdc [list CONFIG.ADC_Slice${S}_Enable {true}] 0
dump_rfdc_params $rfdc $outdir/rfdc_params.rpt

# 2) 使わないタイル / スライスを明示的に落とす。
#    **デュアルタイルのスライスは 0 と 2 のみ**（1 と 3 は disabled parameter になる。
#    2026-09-16 の警告で確定した）。したがって ADC_A = Tile 226 slice 0 /
#    ADC_B = Tile 226 slice 2。
#    既定で ADC0 が有効なので、放置すると使わない外部ポートが .hwh に残る。
set off {}
foreach t {0 1 2 3} {
    foreach sl {0 2} {
        if {"$t$sl" eq $S} continue
        lappend off CONFIG.ADC_Slice${t}${sl}_Enable {false}
        lappend off CONFIG.DAC_Slice${t}${sl}_Enable {false}
    }
}
cfg_apply rfdc $off 0

# 3) スライスの設定
#    Data_Type       0 = Real
#    Decimation_Mode 1 = 1x（デシメーションなし）
#    Mixer_Type      1 = Bypassed。**有効値は Data_Type と Decimation_Mode に依存して
#                    絞られ、Real / 1x では 1 しか許されない**
cfg_apply rfdc [list \
    CONFIG.ADC_Data_Type${S}        {0} \
    CONFIG.ADC_Data_Width${S}       $spw \
    CONFIG.ADC_Decimation_Mode${S}  {1} \
    CONFIG.ADC_Mixer_Type${S}       {1} \
] 0

# 4) タイルの設定。**この順序を崩さないこと**
cfg_apply rfdc [list CONFIG.ADC${T}_PLL_Enable    {true}]        0
cfg_apply rfdc [list CONFIG.ADC${T}_Sampling_Rate $fs_gsps]      0
cfg_apply rfdc [list CONFIG.ADC${T}_Refclk_Freq   $refclk_mhz]   0
# ADC2_Outclk_Freq は **AXIS のクロックではない**。有効値は fs/16, fs/32, fs/64 で、
# IP の出力ピン clk_adc2 の周波数そのもの（2026-09-16 に FREQ_HZ を読んで確定）。
# AXIS のクロックは ADC2_Fabric_Freq（fs / Data_Width = 153.6 MHz）で、IP からは出ない。
# したがって clk_adc2 を Clocking Wizard で逓倍して AXIS クロックを作る。
# 逓倍比を小さくするため、有効値のうち最大の fs/16 = 76.8 MHz を選ぶ。
cfg_apply rfdc [list CONFIG.ADC${T}_Outclk_Freq   $outclk_mhz]   0

# 5) 残り。ミキサをバイパスすると派生値になりうる
cfg_apply rfdc [list \
    CONFIG.ADC${T}_Clock_Source    $T \
    CONFIG.ADC${T}_Clock_Dist      {0} \
    CONFIG.ADC${T}_Multi_Tile_Sync {false} \
    CONFIG.ADC_Mixer_Mode${S}      {2} \
    CONFIG.ADC_NCO_Freq${S}        {0} \
    CONFIG.ADC_OBS${S}             {false} \
] 0

cfg_report "RFDC の設定（読み返しで検証するので、ここでは止めない）"
dump_rfdc_params $rfdc $outdir/rfdc_params.rpt

# ---- 読み返しによる検証 ----
# BD 41-721 は警告 1 行しか出さず、set_property のエラーも
# 「前の正しい設定に戻した」とだけ言って進む。**結果を読み返す以外に
# 「設定したつもりで効いていない」状態を検出する手段がない。**
puts ""
puts "---- RFDC の確定値 ----"
set ng 0
foreach {k want kind} [list \
        CONFIG.ADC${T}_Sampling_Rate   $fs_gsps     num \
        CONFIG.ADC${T}_Refclk_Freq     $refclk_mhz  num \
        CONFIG.ADC${T}_Outclk_Freq     $outclk_mhz  num \
        CONFIG.ADC${T}_Fabric_Freq     $fabric_mhz  num \
        CONFIG.ADC_Data_Type${S}       0            int \
        CONFIG.ADC_Data_Width${S}      $spw         int \
        CONFIG.ADC_Decimation_Mode${S} 1            int \
        CONFIG.ADC_Mixer_Type${S}      1            int] {
    set got ""
    catch {set got [get_property $k $rfdc]}
    set ok 0
    if {$kind eq "num"} {
        if {![catch {expr {abs($got - $want) < 1e-6}} r] && $r} { set ok 1 }
    } else {
        if {$got eq $want} { set ok 1 }
    }
    puts [format "  %-34s = %-12s %s" $k $got [expr {$ok ? "OK" : "違う（要求 $want）"}]]
    if {!$ok} { incr ng }
}
if {$ng > 0} {
    puts ""
    puts "ERROR: RFDC の設定が $ng 件反映されていない。"
    puts "  上の「CONFIG の設定に失敗した項目」に有効値が出ている。"
    puts "  全 CONFIG と現在値は $outdir/rfdc_params.rpt。"
    puts "  fs / refclk / VCO の関係は build.tcl 冒頭の計算を見直すこと"
    exit 1
}
puts "RFDC (確定): fs = $fs_mhz MSPS / refclk = $refclk_mhz MHz / AXIS = $fabric_mhz MHz"

# ---- クロックピンの実周波数を読む ----
# **clk_adc2 が Fabric_Freq なのか Outclk_Freq なのかで設計が変わる。**
# この設計は clk_adc2 を m2_axis_aclk / capture_gate / FIFO 書き込み側に直結している
# ので、153.6 MHz でなければ前提が崩れる。推測せずにピンの FREQ_HZ を読む。
puts ""
puts "---- RFDC のクロックピン ----"
foreach pin [lsort [get_bd_pins -quiet rfdc/*]] {
    set hz ""
    catch {set hz [get_property CONFIG.FREQ_HZ $pin]}
    if {$hz ne ""} { puts [format "  %-28s %s Hz" [file tail $pin] $hz] }
}
foreach ipin [lsort [get_bd_intf_pins -quiet rfdc/*]] {
    set hz ""
    catch {set hz [get_property CONFIG.FREQ_HZ $ipin]}
    if {$hz ne ""} { puts [format "  %-28s %s Hz  (intf)" [file tail $ipin] $hz] }
}

set want_hz [expr {double($outclk_mhz) * 1e6}]
set outclk_hz ""
catch {set outclk_hz [get_property CONFIG.FREQ_HZ [BP rfdc/clk_adc${T}]]}
if {$outclk_hz eq ""} {
    puts "CRITICAL WARNING: clk_adc${T} の FREQ_HZ が読めない。合成後に clocks.rpt で確認すること"
} elseif {abs($outclk_hz - $want_hz) > 1.0} {
    puts ""
    puts "ERROR: clk_adc${T} = $outclk_hz Hz で、Outclk_Freq の要求 $want_hz Hz と違う。"
    puts "  Clocking Wizard の入力周波数の前提が崩れる。上の一覧を見て判断すること"
    exit 1
}
puts "clk_adc${T} = $outclk_hz Hz （Clocking Wizard の入力）"
puts ""

# ---- AXIS クロックを作る Clocking Wizard ----
# RFDC は AXIS の 153.6 MHz を出さない（clk_adc2 は fs/16 = 76.8 MHz）。
# **PS の PL クロックでは代用できない。**AXIS クロックは fs / 8 きっかりである必要が
# あり、わずかでもずれると FIFO が溢れるか枯れる。PS の PLL では 153.6 MHz を
# 正確に作れないので、ADC の出力クロックから逓倍する以外にない。
#
# PRIM_SOURCE は No_buffer。clk_adc2 は IP 内でバッファ済みの前提。
# もし BUFG 段数の DRC が出たら Global_buffer に変える。
set clkw [create_bd_cell -type ip -vlnv xilinx.com:ip:clk_wiz clk_wiz_adc]
cfg_apply clk_wiz_adc [list \
    CONFIG.PRIM_SOURCE                  {No_buffer} \
    CONFIG.PRIM_IN_FREQ                 $outclk_mhz \
    CONFIG.CLKOUT1_REQUESTED_OUT_FREQ   $fabric_mhz \
    CONFIG.USE_LOCKED                   {true} \
    CONFIG.USE_RESET                    {true} \
    CONFIG.RESET_TYPE                   {ACTIVE_LOW} \
    CONFIG.RESET_PORT                   {resetn} \
] 0
cfg_report "Clocking Wizard の設定"

set got_out ""
catch {set got_out [get_property CONFIG.CLKOUT1_JITTER $clkw]}
foreach {k want} [list \
        CONFIG.PRIM_IN_FREQ               $outclk_mhz \
        CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $fabric_mhz] {
    set got [get_property $k $clkw]
    if {abs($got - $want) > 1e-6} {
        puts "ERROR: Clocking Wizard が設定を丸めた: $k  要求 $want / 実際 $got"
        exit 1
    }
}
set act ""
catch {set act [get_property CONFIG.CLKOUT1_ACTUAL_FREQ $clkw]}
puts "CLK WIZ    : $outclk_mhz MHz → $fabric_mhz MHz （実際 $act / ジッタ $got_out ps）"
if {$act ne "" && abs($act - $fabric_mhz) > 1e-3} {
    puts "ERROR: Clocking Wizard の実出力が要求と違う（$act MHz）。"
    puts "  AXIS クロックは fs / 8 きっかりでなければならない"
    exit 1
}
puts ""

# ---- キャプチャゲート（自作。TLAST の生成と記録の連続性を担う）----
set gate [create_bd_cell -type module -reference capture_gate capture_gate_0]
set_property CONFIG.DATA_W [expr {$spw * 16}] $gate

# ---- 非同期 FIFO（clk_adc → pl_clk1 の乗り換えをここに閉じ込める）----
# 深さ 4096 語 = 64 KiB で、65536 サンプル（128 KiB）の記録の半分を吸える。
# 平均では MM 側（3.2 GB/s）がストリーム側（2.4576 GB/s）を上回るので詰まらないが、
# DDR のリフレッシュ等で瞬間的に止まったときの保険。**ここが溢れると capture_gate が
# 上流を止め、RFDC がサンプルを落として記録が不連続になる。**
set fifo [create_bd_cell -type ip -vlnv xilinx.com:ip:axis_data_fifo axis_fifo]
set_property -dict [list \
    CONFIG.TDATA_NUM_BYTES   [expr {$spw * 2}] \
    CONFIG.FIFO_DEPTH        {4096} \
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

# ADC 側のクロック。IP の出力（fs/16）を Clocking Wizard で AXIS の fs/8 にする。
set adc_outclk rfdc/clk_adc${T}     ;# 76.8 MHz。Clocking Wizard の入力
set adc_fabric clk_wiz_adc/clk_out1 ;# 153.6 MHz。AXIS ドメイン
BP $adc_outclk
BP $adc_fabric
nc $adc_outclk clk_wiz_adc/clk_in1
nc zynq_ultra_ps_e_0/pl_resetn0 clk_wiz_adc/resetn

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
    nc $adc_fabric $p
}
# MMCM がロックするまで ADC ドメインをリセットに保つ。
# **clk_adc2 はタイルが起動して初めて出る**ので、ロックも起動後になる。
nc clk_wiz_adc/locked rst_adc/dcm_locked

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

# **語幅で Real / I/Q を判定する。** ミキサの設定が通っていても、出力が I/Q に
# なっていれば 1 語あたりのバイト数が変わる。実機に持ち込む前にここで気づける。
if {![catch {set nb [get_property CONFIG.TDATA_NUM_BYTES $rfdc_axis]}] && $nb ne ""} {
    puts "RFDC AXIS  : TDATA_NUM_BYTES = $nb （期待 [expr {$spw * 2}]）"
    if {$nb != $spw * 2} {
        puts "ERROR: AXIS の語幅が期待と違う。Real のつもりが I/Q になっている可能性がある"
        exit 1
    }
}
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
