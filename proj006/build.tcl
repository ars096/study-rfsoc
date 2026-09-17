# SPDX-License-Identifier: BSD-3-Clause
# proj006 — RFDC 4ch → axis_combiner → capture_gate → AXI4-Stream Data FIFO → AXI DMA → PS
#
# 出力:
#   build/proj006.bit      ビットストリーム
#   build/proj006.hwh      ハードウェアハンドオフ（PYNQ が読む。.bit と同名にする）
#   build/rfdc_params.rpt  RFDC IP が実際に持つ CONFIG 一覧（版がズレたときの突き合わせ用）
#   build/comb_params.rpt  axis_combiner の CONFIG 一覧（同上）
#
# ---- proj005 からの変更点は 3 つだけ ----
#
#   1. **2 タイル × 2 スライス = 4ch** を有効にする（ADC_A/B = Tile 226、ADC_C/D = Tile 224）
#   2. **4 本の AXI4-Stream を axis_combiner で 512 bit の 1 本に束ねる。**
#      1 本のストリームの同じビートに 4ch が乗るので、「4 つのゲートを同時に起動する」
#      という問題そのものが消える。capture_gate は DATA_W を 512 にするだけで改修不要
#   3. **取得長を FIFO の深さで上限する。**4ch フルレートは 9.8304 GB/s で、
#      HP ポート（128 bit 止まり）では受けきれない。`n_beats <= FIFO 深さ` を守れば
#      FIFO が溢れないことを原理的に保証できる。proj005 の帯域チェックは
#      **消さずにこの検査へ差し替える**（消すと、次に取得長を伸ばしたとき黙って壊れる）
#
# ---- サンプリング周波数の根拠（proj003〜005 から変更なし）----
# LMX2594 が RFDC タイルへ 491.52 MHz を渡す（ボード既定）。これは動かせない。
#
#   VCO = 9830.4 MHz (FeedbackDiv=20) / OutDiv = 8 → **fs = 1228.8 MSPS**
#     AXIS = 1228.8 / 8 sample = 153.6 MHz
#     4ch ぶんのデータレート = 1228.8 MSPS × 2 B × 4 = **9.8304 GB/s**
#
# **RefMan: ADC 用と DAC 用に LMX2594 が 1 個ずつ。**つまり Tile 224 と Tile 226 は
# 同じ 1 個の LMX2594 から 491.52 MHz をもらう。サンプリングクロックは同一で位相も固定。
# それでもタイル間でサンプルの番号が揃う保証はない（RFDC の内部 FIFO）。
# **その素性を測るのが proj006 の本題**で、この設計はそのための道具である。

set proj         proj006
set part_default xczu48dr-ffvg1517-2-e
set part         $part_default
set bd_name      system
set outdir       ./build

if {[info exists ::env(PART)]   && $::env(PART)   ne ""} { set part   $::env(PART) }
if {[info exists ::env(OUTDIR)] && $::env(OUTDIR) ne ""} { set outdir ./$::env(OUTDIR) }

# ---- 設計パラメータ ----
# チャネルの並び。**axis_combiner の S00 が 512 bit 語の最下位**に来る。
#   ch0 = S00_AXIS = Tile 224 slice 0
#   ch1 = S01_AXIS = Tile 224 slice 2
#   ch2 = S02_AXIS = Tile 226 slice 0
#   ch3 = S03_AXIS = Tile 226 slice 2
# **SMA のラベル（ADC_A/B/C/D）との対応はここに書かない。**
# proj003 で「SMA のラベルとスライス番号の並びが逆」を踏んでいる。
# 対応は実機で 1 本ずつ入れて確定する（pynq/slice_map.py）。
set chans      {{0 0} {0 2} {2 0} {2 2}}
set adc_tiles  {0 2}
set nch        [llength $chans]

set fs_gsps    1.2288     ;# サンプリング周波数 [GSPS]。IP の有効範囲は (1.0, 5.0)
set refclk_mhz 491.520    ;# LMX2594 → RFDC タイル
set spw        8          ;# 1ch あたり AXI4-Stream 1 語のサンプル数
set beat_bits  [expr {$nch * $spw * 16}]   ;# 束ねた後の語幅 = 512 bit
set beat_bytes [expr {$beat_bits / 8}]     ;# = 64 B

# **FIFO の深さが取得長の上限を決める。**ここを増やすと BRAM を食う。
#   512 bit × 8192 語 = 512 KiB = BRAM36 で 128 個（ZU48DR は 1080 個）
#   → 1ch あたり 8192 × 8 = 65536 サンプル（proj003 / proj005 と同じ長さ）
# 伸ばしたくなったら FIFO_MEMORY_TYPE を ultra にして URAM へ逃がす道がある。
set fifo_depth 8192

# RFDC の出力クロック。**AXIS のクロックではない。**有効値は fs/16, fs/32, fs/64。
# 最大（fs/16）を選ぶと Clocking Wizard の逓倍比が小さく済む。
set outclk_mhz 76.800     ;# = 1228.8 / 16
# **Clocking Wizard は 1 個。**この 1 個の出力を両タイルの AXIS クロックに配る。
# 2 個置くと MMCM 2 個ぶんの位相不定を持ち込むことになる。同じ 491.52 MHz 起源で
# 周波数は同一なので 1 個で足りる。
set wiz_src_tile 2        ;# clk_adc2 を Clocking Wizard の入力にする

set ctrl_mhz   100        ;# pl_clk0: AXI4-Lite 制御系
set data_mhz   200        ;# pl_clk1: DMA の MM 側と HP ポート

set fabric_mhz [format %.3f [expr {$fs_gsps * 1000.0 / $spw}]]
set fs_mhz     [format %.3f [expr {$fs_gsps * 1000.0}]]

puts "PART      : $part"
puts "OUTDIR    : $outdir"
puts "CH        : $nch ch"
foreach ch $chans {
    lassign $ch t s
    puts "            Tile [expr {224 + $t}] / slice $s"
}
puts "fs        : $fs_mhz MSPS （AXIS $fabric_mhz MHz × $spw sample/word/ch）"
puts "BEAT      : $beat_bits bit = $beat_bytes B"

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
#
# **版によって CONFIG の名前が変わる IP では、候補を並べて全部投げる。**
# 存在しない名前は「この IP に存在しない名前」として控えられるだけで害はない。
# 効いたかどうかは **読み返しで判定する**（axis_combiner がこれ）。
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
        puts "  IP が実際に持つ CONFIG と許容値は $::outdir の *_params.rpt にある"
        exit 1
    }
}

# IP の CONFIG と、列挙なら許される値を書き出す。版がズレたときの唯一の手がかり。
proc dump_ip_params {obj path} {
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
# ADCn_Enable と ADCn_Fabric_Freq は派生パラメータなので触らない（読むだけ）。
#
# 全段を「失敗しても止めない」で流し、**最後に読み返しで検証する**。

# 1) 使うスライスを有効にする
set on {}
foreach ch $chans {
    lassign $ch t s
    lappend on CONFIG.ADC_Slice${t}${s}_Enable {true}
}
cfg_apply rfdc $on 0
dump_ip_params $rfdc $outdir/rfdc_params.rpt

# 2) 使わないタイル / スライスを明示的に落とす。
#    **デュアルタイルのスライスは 0 と 2 のみ**（1 と 3 は disabled parameter になる。
#    2026-09-16 の警告で確定した）。
#    既定で ADC0 が有効なので、放置すると使わない外部ポートが .hwh に残る。
set off {}
foreach t {0 1 2 3} {
    foreach sl {0 2} {
        if {[lsearch -exact $chans [list $t $sl]] < 0} {
            lappend off CONFIG.ADC_Slice${t}${sl}_Enable {false}
        }
        lappend off CONFIG.DAC_Slice${t}${sl}_Enable {false}
    }
}
cfg_apply rfdc $off 0

# 3) スライスの設定
#    Data_Type       0 = Real
#    Decimation_Mode 1 = 1x（デシメーションなし）
#    Mixer_Type      1 = Bypassed。**有効値は Data_Type と Decimation_Mode に依存して
#                    絞られ、Real / 1x では 1 しか許されない**
foreach ch $chans {
    lassign $ch t s
    set S "${t}${s}"
    cfg_apply rfdc [list \
        CONFIG.ADC_Data_Type${S}        {0} \
        CONFIG.ADC_Data_Width${S}       $spw \
        CONFIG.ADC_Decimation_Mode${S}  {1} \
        CONFIG.ADC_Mixer_Type${S}       {1} \
    ] 0
}

# 4) タイルの設定。**この順序を崩さないこと**
#    Clock_Source を自タイルにする = クロック転送（Clock_Dist）を使わない。
#    RefMan では ADC 用 LMX2594 が両タイルへ 491.52 MHz を配るので、
#    **各タイルが自前のクロック入力を持つ**前提である。
#    もし adcN_clk のインタフェースが片方しか出てこなければこの前提が誤りで、
#    Clock_Dist によるクロック転送に切り替える必要がある（下の外部ポートで分かる）。
foreach t $adc_tiles {
    cfg_apply rfdc [list CONFIG.ADC${t}_PLL_Enable    {true}]      0
    cfg_apply rfdc [list CONFIG.ADC${t}_Sampling_Rate $fs_gsps]    0
    cfg_apply rfdc [list CONFIG.ADC${t}_Refclk_Freq   $refclk_mhz] 0
    cfg_apply rfdc [list CONFIG.ADC${t}_Outclk_Freq   $outclk_mhz] 0
}

# 5) 残り。ミキサをバイパスすると派生値になりうる
foreach t $adc_tiles {
    cfg_apply rfdc [list \
        CONFIG.ADC${t}_Clock_Source    $t \
        CONFIG.ADC${t}_Clock_Dist      {0} \
        CONFIG.ADC${t}_Multi_Tile_Sync {false} \
    ] 0
}
foreach ch $chans {
    lassign $ch t s
    set S "${t}${s}"
    cfg_apply rfdc [list \
        CONFIG.ADC_Mixer_Mode${S} {2} \
        CONFIG.ADC_NCO_Freq${S}   {0} \
        CONFIG.ADC_OBS${S}        {false} \
    ] 0
}

cfg_report "RFDC の設定（読み返しで検証するので、ここでは止めない）"
dump_ip_params $rfdc $outdir/rfdc_params.rpt

# ---- 読み返しによる検証 ----
# BD 41-721 は警告 1 行しか出さず、set_property のエラーも
# 「前の正しい設定に戻した」とだけ言って進む。**結果を読み返す以外に
# 「設定したつもりで効いていない」状態を検出する手段がない。**
puts ""
puts "---- RFDC の確定値 ----"
set ng 0
set want {}
foreach t $adc_tiles {
    lappend want CONFIG.ADC${t}_Sampling_Rate $fs_gsps    num
    lappend want CONFIG.ADC${t}_Refclk_Freq   $refclk_mhz num
    lappend want CONFIG.ADC${t}_Outclk_Freq   $outclk_mhz num
    # **両タイルの Fabric_Freq が同じであることが、MMCM 1 個で足りる根拠。**
    lappend want CONFIG.ADC${t}_Fabric_Freq   $fabric_mhz num
}
foreach ch $chans {
    lassign $ch t s
    set S "${t}${s}"
    lappend want CONFIG.ADC_Data_Type${S}       0    int
    lappend want CONFIG.ADC_Data_Width${S}      $spw int
    lappend want CONFIG.ADC_Decimation_Mode${S} 1    int
    lappend want CONFIG.ADC_Mixer_Type${S}      1    int
}
foreach {k w kind} $want {
    set got ""
    catch {set got [get_property $k $rfdc]}
    set ok 0
    if {$kind eq "num"} {
        if {![catch {expr {abs($got - $w) < 1e-6}} r] && $r} { set ok 1 }
    } else {
        if {$got eq $w} { set ok 1 }
    }
    puts [format "  %-34s = %-12s %s" $k $got [expr {$ok ? "OK" : "違う（要求 $w）"}]]
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
puts "RFDC (確定): fs = $fs_mhz MSPS / refclk = $refclk_mhz MHz / AXIS = $fabric_mhz MHz × $nch ch"

# ---- クロックピンの実周波数を読む ----
# **両タイルの clk_adcN が同じ 76.8 MHz であること**を確かめる。
# ここが違うと「MMCM 1 個を両タイルで共有する」という設計の前提が崩れる。
puts ""
puts "---- RFDC のクロックピン ----"
foreach pin [lsort [get_bd_pins -quiet rfdc/*]] {
    set hz ""
    catch {set hz [get_property CONFIG.FREQ_HZ $pin]}
    if {$hz ne ""} { puts [format "  %-28s %s Hz" [file tail $pin] $hz] }
}

set want_hz [expr {double($outclk_mhz) * 1e6}]
foreach t $adc_tiles {
    set hz ""
    catch {set hz [get_property CONFIG.FREQ_HZ [BP rfdc/clk_adc${t}]]}
    if {$hz eq ""} {
        puts "CRITICAL WARNING: clk_adc${t} の FREQ_HZ が読めない。合成後に clocks.rpt で確認すること"
    } elseif {abs($hz - $want_hz) > 1.0} {
        puts ""
        puts "ERROR: clk_adc${t} = $hz Hz で、Outclk_Freq の要求 $want_hz Hz と違う。"
        puts "  Clocking Wizard の入力周波数の前提が崩れる。上の一覧を見て判断すること"
        exit 1
    } else {
        puts "clk_adc${t} = $hz Hz"
    }
}
puts ""

# ---- AXIS クロックを作る Clocking Wizard（1 個）----
# RFDC は AXIS の 153.6 MHz を出さない（clk_adcN は fs/16 = 76.8 MHz）。
# **PS の PL クロックでは代用できない。**AXIS クロックは fs / 8 きっかりである必要が
# あり、わずかでもずれると FIFO が溢れるか枯れる。
#
# **1 個だけ置いて、両タイルの m*_axis_aclk に配る。**両タイルは同じ LMX2594 の
# 491.52 MHz から同じ fs を作っているので、Fabric_Freq は上の読み返しで同一を確認済み。
# 2 個置くと MMCM 2 個ぶんの位相不定が入るだけで、得るものがない。
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

foreach {k w} [list \
        CONFIG.PRIM_IN_FREQ               $outclk_mhz \
        CONFIG.CLKOUT1_REQUESTED_OUT_FREQ $fabric_mhz] {
    set got [get_property $k $clkw]
    if {abs($got - $w) > 1e-6} {
        puts "ERROR: Clocking Wizard が設定を丸めた: $k  要求 $w / 実際 $got"
        exit 1
    }
}
set act ""
catch {set act [get_property CONFIG.CLKOUT1_ACTUAL_FREQ $clkw]}
# CLKOUT1_ACTUAL_FREQ はこの時点では空のことがある（validate 後に確定する）。
puts "CLK WIZ    : $outclk_mhz MHz → $fabric_mhz MHz[expr {$act eq "" ? "" : " （実際 $act）"}]"
if {$act ne "" && abs($act - $fabric_mhz) > 1e-3} {
    puts "ERROR: Clocking Wizard の実出力が要求と違う（$act MHz）。"
    puts "  AXIS クロックは fs / 8 きっかりでなければならない"
    exit 1
}
puts ""

# ---- 4ch を 1 本に束ねる ----
# axis_combiner は **全ての SI が valid のときだけ**出力を出す。
# デシメーション 1 / Real では RFDC のストリームは常時 valid なので詰まらないが、
# どれかのタイルが起動していなければ 1 ビートも出ない。
# **気づける失敗の仕方**になっており、これは意図した挙動である。
#
# CONFIG の名前は版で変わる。**Vivado 2024.1 では NUM_SI と TDATA_NUM_BYTES**
# （2026-09-17 のビルドで確定。C_NUM_SI_SLOTS / C_AXIS_TDATA_WIDTH は存在しない）。
# 名前が変わっても気づけるよう、**効いたかどうかは M_AXIS の語幅を読み返して判定する。**
set comb [create_bd_cell -type ip -vlnv xilinx.com:ip:axis_combiner axis_comb]
cfg_apply axis_comb [list \
    CONFIG.NUM_SI              $nch \
    CONFIG.TDATA_NUM_BYTES     [expr {$spw * 2}] \
    CONFIG.HAS_TLAST           {0} \
    CONFIG.HAS_TKEEP           {0} \
    CONFIG.HAS_TSTRB           {0} \
] 0
cfg_report "axis_combiner の設定（読み返しで検証するので、ここでは止めない）"
dump_ip_params $comb $outdir/comb_params.rpt

# **読み返しで判定する。**出力が 64 B でなければ、CONFIG の名前が版で変わっている。
set comb_m [BI axis_comb [list "M_AXIS" "M00_AXIS"] "axis_combiner の出力"]
set comb_nb ""
catch {set comb_nb [get_property CONFIG.TDATA_NUM_BYTES $comb_m]}
puts "COMBINER   : M_AXIS TDATA_NUM_BYTES = $comb_nb （期待 $beat_bytes）"
if {$comb_nb eq "" || $comb_nb != $beat_bytes} {
    puts ""
    puts "ERROR: axis_combiner の出力語幅が $beat_bytes B になっていない。"
    puts "  CONFIG の名前が Vivado の版で変わっている可能性が高い。"
    puts "  実際に持つ CONFIG の一覧は $outdir/comb_params.rpt。"
    puts "  そこから「SI の本数」と「1 本あたりの語幅」に当たる名前を拾って上の list を直す"
    exit 1
}

# ---- キャプチャゲート（proj005 から改修なし。DATA_W を 512 にして使う）----
set gate [create_bd_cell -type module -reference capture_gate capture_gate_0]
set_property CONFIG.DATA_W $beat_bits $gate

# ---- 非同期 FIFO（clk_adc → pl_clk1 の乗り換えをここに閉じ込める）----
# **proj005 と役割が変わっている。**proj005 では「瞬間的な詰まりの保険」だったが、
# proj006 では **取得長そのものを決める貯め込み用**である。
# n_beats <= FIFO_DEPTH を守る限り、下流が何をしていても FIFO は溢れない。
set fifo [create_bd_cell -type ip -vlnv xilinx.com:ip:axis_data_fifo axis_fifo]
set_property -dict [list \
    CONFIG.TDATA_NUM_BYTES   $beat_bytes \
    CONFIG.FIFO_DEPTH        $fifo_depth \
    CONFIG.FIFO_MEMORY_TYPE  {block} \
    CONFIG.IS_ACLK_ASYNC     {1} \
    CONFIG.HAS_TLAST         {1} \
    CONFIG.HAS_TKEEP         {0} \
    CONFIG.HAS_TSTRB         {0} \
] $fifo

# ---- DMA（S2MM のみ・Simple mode）----
# c_s2mm_burst_size は **1 バーストが 4 KiB を越えないよう**語幅に合わせて決める。
#   proj005: 128 bit(16 B) × 256 = 4096 B
#   proj006: 512 bit(64 B) ×  64 = 4096 B
set burst [expr {4096 / $beat_bytes}]
set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma dma_adc]
set_property -dict [list \
    CONFIG.c_include_sg               {0} \
    CONFIG.c_include_mm2s             {0} \
    CONFIG.c_include_s2mm             {1} \
    CONFIG.c_include_s2mm_dre         {0} \
    CONFIG.c_sg_length_width          {26} \
    CONFIG.c_m_axi_s2mm_data_width    $beat_bits \
    CONFIG.c_s_axis_s2mm_tdata_width  $beat_bits \
    CONFIG.c_s2mm_burst_size          $burst \
    CONFIG.c_addr_width               {40} \
] $dma
# **c_prmry_is_aclk_async は設定しない。**読み出し専用で、
# CRITICAL WARNING: [BD 41-737] が出るだけ（2026-09-17 に確認。proj005 も出していた）。
# 非同期かどうかは、接続されたクロックから Vivado が導出する。
# ここでは S_AXIS_S2MM が pl_clk1、M_AXI_S2MM も pl_clk1 で、
# 乗り換えは上流の axis_data_fifo に閉じ込めてある。

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
# **512 bit → 128 bit の変換は SmartConnect にやらせる。**HP ポートは 128 bit 止まり。
set smc_data [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect smc_data]
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1} CONFIG.NUM_CLKS {1}] $smc_data

# ------------------------------------------------------------------ 配線
set ps_clk0  zynq_ultra_ps_e_0/pl_clk0
set ps_clk1  zynq_ultra_ps_e_0/pl_clk1
set ps_rstn  zynq_ultra_ps_e_0/pl_resetn0

set adc_outclk rfdc/clk_adc${wiz_src_tile}  ;# 76.8 MHz。Clocking Wizard の入力
set adc_fabric clk_wiz_adc/clk_out1         ;# 153.6 MHz。AXIS ドメイン
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
# **AXIS ドメインは 1 個の MMCM 出力で統一する。**両タイルの m*_axis_aclk を含む。
set adc_dom [list rst_adc/slowest_sync_clk capture_gate_0/aclk \
                  axis_comb/aclk axis_fifo/s_axis_aclk]
foreach t $adc_tiles { lappend adc_dom rfdc/m${t}_axis_aclk }
foreach p $adc_dom { nc $adc_fabric $p }

# MMCM がロックするまで ADC ドメインをリセットに保つ。
# **clk_adcN はタイルが起動して初めて出る**ので、ロックも起動後になる。
nc clk_wiz_adc/locked rst_adc/dcm_locked

# リセット
foreach r {rst_ctrl rst_data rst_adc} { nc $ps_rstn $r/ext_reset_in }
foreach p [list smc_ctrl/aresetn rfdc/s_axi_aresetn \
                dma_adc/axi_resetn gpio_capture/s_axi_aresetn] {
    nc rst_ctrl/peripheral_aresetn $p
}
nc rst_data/peripheral_aresetn smc_data/aresetn
set adc_rst [list capture_gate_0/aresetn axis_comb/aresetn axis_fifo/s_axis_aresetn]
foreach t $adc_tiles { lappend adc_rst rfdc/m${t}_axis_aresetn }
foreach p $adc_rst { nc rst_adc/peripheral_aresetn $p }

# キャプチャ制御
nc gpio_capture/gpio_io_o  capture_gate_0/ctrl
nc capture_gate_0/status   gpio_capture/gpio2_io_i

# ---- データ経路: RFDC ×4 → combiner → gate → FIFO → DMA ----
# **並びを固定する。**chans の順に S00, S01, ... へ入れ、
# S00 が 512 bit 語の最下位になる（PYNQ 側の deinterleave がこれに依存する）。
set i 0
foreach ch $chans {
    lassign $ch t s
    set src [BI rfdc [list "m${t}${s}_axis"] "RFDC の AXI4-Stream 出力 (tile $t slice $s)"]
    # **語幅で Real / I/Q を判定する。** ミキサの設定が通っていても、出力が I/Q に
    # なっていれば 1 語あたりのバイト数が変わる。実機に持ち込む前にここで気づける。
    if {![catch {set nb [get_property CONFIG.TDATA_NUM_BYTES $src]}] && $nb ne ""} {
        if {$nb != $spw * 2} {
            puts "ERROR: m${t}${s}_axis の語幅が $nb B。期待 [expr {$spw * 2}] B。"
            puts "  Real のつもりが I/Q になっている可能性がある"
            exit 1
        }
    }
    set dst [BI axis_comb [list [format "S%02d_AXIS" $i]] \
                "axis_combiner の入力 $i"]
    ic $src $dst
    puts [format "  ch%d  <- Tile %d slice %d  (%s -> %s)" \
          $i [expr {224 + $t}] $s [file tail $src] [file tail $dst]]
    incr i
}
ic $comb_m [get_bd_intf_pins capture_gate_0/s_axis]
ic [get_bd_intf_pins capture_gate_0/m_axis] [get_bd_intf_pins axis_fifo/S_AXIS]
ic [get_bd_intf_pins axis_fifo/M_AXIS]      [get_bd_intf_pins dma_adc/S_AXIS_S2MM]

# 制御系 AXI: PS → SmartConnect → RFDC / DMA / GPIO
ic [get_bd_intf_pins zynq_ultra_ps_e_0/M_AXI_HPM0_FPD] [get_bd_intf_pins smc_ctrl/S00_AXI]
ic [get_bd_intf_pins smc_ctrl/M00_AXI] [get_bd_intf_pins rfdc/s_axi]
ic [get_bd_intf_pins smc_ctrl/M01_AXI] [get_bd_intf_pins dma_adc/S_AXI_LITE]
ic [get_bd_intf_pins smc_ctrl/M02_AXI] [get_bd_intf_pins gpio_capture/S_AXI]

# データ系 AXI: DMA → SmartConnect（512→128 変換）→ PS の HP0
ic [get_bd_intf_pins dma_adc/M_AXI_S2MM] [get_bd_intf_pins smc_data/S00_AXI]
ic [get_bd_intf_pins smc_data/M00_AXI]   [get_bd_intf_pins zynq_ultra_ps_e_0/S_AXI_HP0_FPD]

# ---- 外部ポート（RF のアナログ入力・タイルのクロック・SYSREF）----
# いずれも専用ピンなので XDC での配置制約は要らない。IP のタイル選択で決まる。
# **アナログ入力はスライスの対（01 / 23）でまとまっている。**
set ext_done {}
foreach ch $chans {
    lassign $ch t s
    # **expr に "01" を渡さないこと。**数値として評価され 1 になり、
    # パターンが vin0_1 に化けて「見つからない」で止まる（2026-09-17 に踏んだ）。
    # 文字列の分岐は if で書く。
    if {$s < 2} { set pair "01" } else { set pair "23" }
    set pin [BI rfdc [list "vin${t}_${pair}" "vin${t}${s}"] \
                "ADC アナログ入力 (tile $t slice $s)"]
    if {[lsearch -exact $ext_done $pin] >= 0} continue
    lappend ext_done $pin
    make_bd_intf_pins_external $pin
    puts "EXTERNAL: $pin （ADC アナログ入力 tile $t slice $s）"
}
foreach t $adc_tiles {
    set pin [BI rfdc [list "adc${t}_clk"] "ADC タイル $t のクロック入力"]
    make_bd_intf_pins_external $pin
    puts "EXTERNAL: $pin （ADC タイル $t のクロック入力）"
}
set pin [BI rfdc [list "sysref_in"] "SYSREF 入力"]
make_bd_intf_pins_external $pin
puts "EXTERNAL: $pin （SYSREF 入力）"

# ------------------------------------------------------------------ まとめ
assign_bd_address
validate_bd_design
save_bd_design

# ---- PS の PL クロックの実周波数を確かめる ----
# **要求した値がそのまま出るとは限らない。**PS の PLL の刻みで下がる
# （2026-09-16: 200 MHz を要求して 175 MHz になった）。
puts ""
puts "---- PS の PL クロック ----"
set hz_data 0
foreach {pin w} [list \
        zynq_ultra_ps_e_0/pl_clk0 $ctrl_mhz \
        zynq_ultra_ps_e_0/pl_clk1 $data_mhz] {
    set hz ""
    catch {set hz [get_property CONFIG.FREQ_HZ [BP $pin]]}
    set mhz [expr {$hz eq "" ? 0 : $hz / 1e6}]
    puts [format "  %-12s 要求 %6s MHz → 実際 %8.3f MHz" [file tail $pin] $w $mhz]
    if {[file tail $pin] eq "pl_clk1"} { set hz_data $hz }
}

# ---- 取得長の上限（proj005 の帯域チェックの差し替え）----
#
# **proj005 では「MM 側の帯域 > ストリームの帯域」を成立条件にしていた。**
# 4ch ではこれが成り立たない。9.8304 GB/s を HP ポート 1 本（128 bit）で
# 受けることはできず、4 本に分けても PS の DDR4 が Linux と共用である以上持たない。
#
# **成立条件を「FIFO が溢れないこと」に置き換える。**
# capture_gate は n_beats ビートだけ下流へ流す。n_beats <= FIFO_DEPTH なら、
# DMA が 1 ビートも吸わなくても FIFO に収まる。
# **下流の速度に依存しない保証**になっており、見積もりが要らない。
puts ""
puts "---- 取得長の上限 ----"
set in_bps    [expr {$fs_gsps * 1e9 * 2 * $nch}]
set out_bps   [expr {$hz_data * 16}]          ;# HP0 は 128 bit = 16 B
set fifo_kib  [expr {$fifo_depth * $beat_bytes / 1024}]
set max_samp  [expr {$fifo_depth * $spw}]
puts [format "  流入 %.4f GB/s（%d ch）/ HP0 の流出 %.4f GB/s" \
      [expr {$in_bps/1e9}] $nch [expr {$out_bps/1e9}]]
puts "  → 連続ストリームは成立しない。**FIFO 深さで取得長を上限する方式**"
puts [format "  FIFO  %d 語 × %d B = %d KiB" $fifo_depth $beat_bytes $fifo_kib]
puts [format "  最大  n_beats = %d → 1ch あたり %d サンプル（%.1f us）" \
      $fifo_depth $max_samp [expr {$max_samp / ($fs_gsps * 1e9) * 1e6}]]
puts "  **pynq 側は n_beats <= $fifo_depth を守ること。**破ると記録が不連続になる"

# capture_gate の n_beats は 24 bit。FIFO 深さがそれを越えていないか。
if {$fifo_depth >= (1 << 24)} {
    puts "ERROR: FIFO 深さが capture_gate の n_beats（24 bit）を越えている"
    exit 1
}
# FIFO が 1 ビートも吸われないまま埋まる最悪の場合を、そのまま設計条件にしている。
# ここが崩れるのは fifo_depth を下げたときだけなので、定数の突き合わせで足りる。
if {$fifo_depth < 1024} {
    puts "ERROR: FIFO が浅すぎる（$fifo_depth 語）。取得長が実用にならない"
    exit 1
}

set fh [open $outdir/address_map.rpt w]
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
# クロックは実装の段階で出そろう。合成時に get_clocks が空を返すと
# set_clock_groups がエラーになるので、実装でのみ使う。
set_property USED_IN_SYNTHESIS false [get_files timing.xdc]

# ---- part の検証 ----
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

# ---- ここから診断。**診断の失敗でビルドを壊さない。** ----
# 2026-09-16、存在しないコマンド（get_clock_groups）を診断に書いたために、
# write_bitstream まで成功していたのに成果物のコピーに到達しなかった。
# 調べるためのコードが、調べたい対象を壊してはいけない。
if {[catch {

# ---- run のログから CRITICAL WARNING を拾い上げる ----
# **launch_runs は別プロセスなので、run の中の警告はこのコンソールに出ない。**
puts ""
puts "---- run の CRITICAL WARNING ----"
set seen 0
foreach lf [lsort [glob -nocomplain $projdir/$proj.runs/*/runme.log]] {
    set fh [open $lf r]
    foreach line [split [read $fh] \n] {
        if {[string match "CRITICAL WARNING*" $line]} {
            puts "  [file tail [file dirname $lf]]: $line"
            incr seen
        }
    }
    close $fh
}
if {$seen == 0} { puts "  （なし）" }

# ---- クロックと非同期グループ ----
puts ""
puts "---- クロック ----"
foreach c [get_clocks -quiet] {
    puts [format "  %-34s %8.3f ns  (%7.3f MHz)" $c \
          [get_property PERIOD $c] [expr {1000.0/[get_property PERIOD $c]}]]
}
# **get_clock_groups というコマンドは存在しない**（2026-09-16 に書いて落とした）。
report_clock_interaction -delay_type min_max -significant_digits 3 \
    -file $outdir/clock_interaction.rpt
set fh [open $outdir/clock_interaction.rpt r]
set ci [read $fh]
close $fh
set n_async [regexp -all -nocase {asynchronous} $ci]
puts ""
puts "クロック間の制約: $outdir/clock_interaction.rpt"
puts "  asynchronous を含む箇所 = $n_async"
if {$n_async == 0} {
    puts "  **非同期の宣言が見当たらない。src/timing.xdc が効いていない可能性がある**"
}

# ---- BRAM の使用量 ----
# FIFO を深くしたときに、どこで頭を打つのかを数字で残す。
puts ""
puts "---- ブロック RAM ----"
foreach line [split [exec cat $outdir/utilization.rpt] \n] {
    if {[string match "*Block RAM Tile*" $line] || [string match "*RAMB36*" $line] \
        || [string match "*URAM*" $line]} { puts "  [string trim $line]" }
}

# ---- 一番きつい経路のクロック対を **必ず** 出す ----
# **WNS が正でも出す。**通ったかどうかだけ見ていると、
# 「宣言し忘れた乗り換えが、たまたま間に合っていただけ」を見逃す。
# 起点と終点のクロックが違うのに残っていたら、timing.xdc の非同期宣言の漏れを疑う。
# 同じなら単に設計が重い（語幅を広げた、段数が増えた）。
foreach {kind label} {setup "setup（周期）" hold "hold（保持）"} {
    puts ""
    puts "---- 一番きつい経路 上位 5  $label ----"
    set n 0
    foreach pth [get_timing_paths -quiet -max_paths 5 -nworst 1 -$kind] {
        set sc [get_property STARTPOINT_CLOCK $pth]
        set ec [get_property ENDPOINT_CLOCK $pth]
        puts [format "  slack %9.3f  %-30s → %-30s%s" \
              [get_property SLACK $pth] $sc $ec \
              [expr {$sc eq $ec ? "" : "   ← 乗り換え"}]]
        incr n
    }
    if {$n == 0} { puts "  （経路なし）" }
}

# ---- 宣言していないクロックに経路が残っていないか ----
# timing.xdc が非同期と宣言しているのは clk_pl_0 / clk_pl_1 / RFADC2_CLK の 3 群だけ。
# proj006 は **clk_adc0 をどこにも繋いでいない**ので、RFADC0_CLK には
# ファブリックの経路が無いはずである。使っていないタイル / DAC の
# ダミークロックも同じ。**前提を数えて確かめる。**
# ここに経路が出たら、timing.xdc にその群を足すか、配線を見直す。
# 2026-09-17 の 1 回目: RFADC0/1/3 と RFDAC0..3 に **起点 8 / 終点 0** が出た。
# **proj006 で生じたものではない。**使わないタイルのダミークロック（10 ns）は
# proj003 以降ずっとあり、proj005 でも同じ経路が解析されていたはずである。
# 対処を決める前に **何の経路で、どれだけ余裕があるのか**を見る。
# RFADC2_CLK は timing.xdc で宣言済みなので、**対照**として並べる
# （宣言が効いていれば、乗り換えの経路は解析から外れて出てこない）。
puts ""
puts "---- タイルのクロックから出る経路 ----"
foreach cn {RFADC0_CLK RFADC1_CLK RFADC2_CLK RFADC3_CLK \
            RFDAC0_CLK RFDAC1_CLK RFDAC2_CLK RFDAC3_CLK} {
    set c [get_clocks -quiet $cn]
    if {[llength $c] == 0} { continue }
    set mark [expr {$cn eq "RFADC2_CLK" ? "  (timing.xdc で宣言済み)" : ""}]
    set paths [get_timing_paths -quiet -from $c -max_paths 40 -nworst 1 -setup]
    if {[llength $paths] == 0} {
        puts [format "  %-12s%s  経路なし" $cn $mark]
        continue
    }
    # 終点のクロックごとに、本数と最悪 slack をまとめる
    unset -nocomplain agg
    set example ""
    foreach pth $paths {
        set ec [get_property ENDPOINT_CLOCK $pth]
        if {$ec eq ""} { set ec "(制約なし)" }
        set sl [get_property SLACK $pth]
        if {![info exists agg($ec)]} { set agg($ec) [list 0 $sl] }
        lassign $agg($ec) n w
        incr n
        if {$sl ne "" && ($w eq "" || $sl < $w)} { set w $sl }
        set agg($ec) [list $n $w]
        if {$example eq ""} { catch {set example [get_property ENDPOINT_PIN $pth]} }
    }
    puts [format "  %-12s%s" $cn $mark]
    foreach ec [lsort [array names agg]] {
        lassign $agg($ec) n w
        puts [format "      → %-30s %3d 本  最悪 slack %s%s" $ec $n $w \
              [expr {$ec eq $cn ? "" : "   ← 乗り換え"}]]
    }
    if {$example ne ""} { puts "      終点の例: $example" }
}

set wns [get_property STATS.WNS [get_runs impl_1]]

} diag_err]} {
    puts ""
    puts "WARNING: 診断の途中で失敗した（ビルドは続行する）: $diag_err"
}

# 診断が途中で落ちても、WNS の判定だけは必ず行う
set wns [get_property STATS.WNS [get_runs impl_1]]
set whs [get_property STATS.WHS [get_runs impl_1]]
puts ""
puts "TIMING (確定): WNS = $wns ns / WHS = $whs ns"
if {$wns ne "" && $wns < 0} { set timing_failed 1 }

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

# **タイミングが閉じていないビルドは失敗として扱う。**
if {[info exists timing_failed]} {
    puts ""
    puts "ERROR: タイミングが閉じていない。成果物は調査用に残したが実機に使わないこと。"
    puts "  上の「違反している経路」でクロック対を見る。"
    puts "  クロック対が違っていれば src/timing.xdc の非同期宣言の漏れ。"
    puts "  **XDC で if / foreach を使うと黙って無効になる**（Designutils 20-1307）"
    exit 1
}

if {!$use_board} {
    puts ""
    puts "NOTE: これは速度グレード検証ビルド（$part）。"
    puts "      ボードプリセットを当てていないので、このビットストリームは実機に使わない。"
    puts "      見るのは上の TIMING の値だけ。"
}
