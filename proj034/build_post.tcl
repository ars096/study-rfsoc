# SPDX-License-Identifier: BSD-3-Clause
# proj025 build.tcl の後段（open_run impl_1 から最後まで）。build.tcl から source する。単独では回さない
# 2f ビルド 2 で build.tcl から切り出した（中身は一字も変えていない）。親の Vivado が open_run で落ちたとき、
# `make post`（RESUME=1）で合成・実装をやり直さずにここだけを回すため。
# 前段から引き継ぐ変数: proj・part・outdir・projdir・bd_name・fft_mod・ncore・has_preset

open_run impl_1

# ---- proj016: 1PPS のポートが意図した足に出ているか（proj007 と同じ。合否判定なので catch の外）----
puts ""
puts "---- 1PPS の入力ポート ----"
foreach {pname want} {pps_trig AH13 pps_comp AJ13} {
    set prt [get_ports -quiet $pname]
    if {[llength $prt] == 0} {
        puts "ERROR: ポート $pname が存在しない（create_bd_port の名前と src/board/pps.xdc の get_ports を突き合わせる）"
        exit 1
    }
    set got [get_property PACKAGE_PIN $prt]
    set io  [get_property IOSTANDARD  $prt]
    puts [format "  %-10s %-6s %s" $pname $got $io]
    if {$got ne $want} { puts "ERROR: $pname の配置が $got。期待 $want（RefMan A6 / Appendix A）"; exit 1 }
}
# ---- proj024: ROM が BRAM として残っているか（合否。**中身が 0 なら ROM は消えて BRAM が 0 になる**）----
# 予言（proj025、コアごと）: 係数（g22_coef）2048 × 36 bit × 2 表・2 ポート → RAMB36 4（M-a）。
#       ひねり係数（g22_tw）64 行・128 行 × 576 bit → 幅で決まり RAMB36（512 × 72）× 8 × 2 = 16（A は 64 行なので RAMB18 に落ちて 12 前後までありうる。
#       レーン 0 の定数の列が削られて少し減りうる）。合否は「予言の半分に届くか」（中身が 0 なら ROM が消えて 0 になる）
puts ""
puts "---- ROM の BRAM（s45_core_0・1 の中）----"
foreach {cell pred} {s45_core_0/inst/u_full/u_spec/u_pfb/u_coef 4 s45_core_0/inst/u_full/u_spec/u_tw 12 \
                     s45_core_1/inst/u_full/u_spec/u_pfb/u_coef 4 s45_core_1/inst/u_full/u_spec/u_tw 12} {
    set n36 0; set n18 0
    foreach x [get_cells -quiet -hierarchical -filter {REF_NAME =~ RAMB36*}] { if {[string first "/$cell/" "/$x"] >= 0} { incr n36 } }
    foreach x [get_cells -quiet -hierarchical -filter {REF_NAME =~ RAMB18*}] { if {[string first "/$cell/" "/$x"] >= 0} { incr n18 } }
    set eq [expr {$n36 + $n18 / 2.0}]
    puts [format "  %-44s RAMB36 %d・RAMB18 %d（RAMB36 換算 %.1f、予言 %d）" $cell $n36 $n18 $eq $pred]
    if {$eq < $pred / 2.0} { puts "ERROR: $cell の BRAM が予言の半分に届かない。ROM の中身（\$readmemh）が効いていないか、階層の名前が違う（utilization_hier.rpt）"; exit 1 }
}
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
    puts "  **非同期の宣言が見当たらない。src/board/timing.xdc が効いていない可能性がある**"
}

# ---- BRAM と DSP の使用量 ----
# README の予言（BRAM36 と DSP の見積もり）と突き合わせる。proj023 の見込み: DSP 2,656・BRAM ≒ 784・URAM ≒ 40・LUT ≒ 252k・FF ≒ 489k（README の見積もり ＋ 2b の ROM の移し替え）
puts ""
puts "---- ブロック RAM / DSP ----"
foreach line [split [exec cat $outdir/utilization.rpt] \n] {
    if {[string match "*Block RAM Tile*" $line] || [string match "*RAMB36*" $line] \
        || [string match "*RAMB18*" $line] || [string match "*URAM*" $line] \
        || [string match "| DSPs*" $line] || [string match "*DSP48E2*" $line]} {
        puts "  [string trim $line]"
    }
}
# 階層ごと（lane_fft 16 個・spec_core の残り）に分けて残す
report_utilization -hierarchical -hierarchical_depth 4 -file $outdir/utilization_hier.rpt

# ---- lane_fft_g22 1 個ぶん・16 個の合計・段ごと（proj024）----
# **S-1（IP 単体の OOC 合成）の数字と突き合わせる**（1 個 DSP 33・BRAM 21.5）
set ffts [lsort [get_cells -quiet -hierarchical -filter "ORIG_REF_NAME == $fft_mod || REF_NAME == $fft_mod"]]
# **名前に [0] が入るので -filter の =~ は使わない**（glob の文字クラスとして読まれ、何にも当たらない）。名前を一度集め、先頭一致で数える
set dsp_names [get_property NAME [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E2}]]
set dsp_all [llength $dsp_names]
proc count_under {names c} {
    set n 0
    foreach x $names { if {[string first "$c/" $x] == 0} { incr n } }
    return $n
}
proc count_in {names pat} {
    set n 0
    foreach x $names { if {[string first $pat "/$x"] >= 0} { incr n } }
    return $n
}
set dsp_fft 0
foreach c $ffts { incr dsp_fft [count_under $dsp_names $c] }
puts ""
puts "---- FFT IP の資源（$fft_mod）----"
puts "  $fft_mod の個数         = [llength $ffts]（期待 16 = 8 × 2 コア。proj034 の 2-for-1）"
if {[llength $ffts] > 0} {
    set c0 [lindex $ffts 0]
    report_utilization -cells $c0 -file $outdir/lane_fft_util.rpt
    puts "  DSP48E2 1 個あたり      = [count_under $dsp_names $c0]（$c0。S-1 は 33）"
    puts "    S-1（OOC 合成）: DSP 33・BRAM 21.5"
    foreach line [split [exec cat $outdir/lane_fft_util.rpt] \n] {
        if {[regexp {^\|\s*(CLB LUTs|CLB Registers|Block RAM Tile|URAM|DSPs)\s*\|} $line]} { puts "    [string trim $line]" }
    }
}
puts "  DSP48E2 $fft_mod 16 個の合計 = $dsp_fft（proj025 の 1 個 33 から 16 × 33 = 528）"
puts "  DSP48E2 全体            = $dsp_all（proj034 の E-1 は 1,256）"
# 段ごと（階層の名前は g22_s45_core.v・g22_core.v・g22_spec.v・core_cmn.v のインスタンス名）
set ram_names [get_property NAME [get_cells -quiet -hierarchical -filter {REF_NAME =~ RAMB* || REF_NAME =~ URAM*}]]
for {set c 0} {$c < $ncore} {incr c} {
foreach sub {u_full/u_spec/u_pfb u_full/u_spec/g_lane u_full/u_spec/u_tw u_full/u_spec/u_sep u_full/u_spec/u_chain u_full/u_spec/u_q u_full/u_spec/u_acc u_full/u_tp u_full/u_rec u_cmn/g_tp.u_tp g_raw.u_raw} {
    puts [format "  s45_core_%d/%-24s DSP48E2 %4d・RAMB/URAM のセル %4d" $c $sub [count_in $dsp_names "/s45_core_$c/inst/$sub"] [count_in $ram_names "/s45_core_$c/inst/$sub"]]
}
}
foreach {c f what} {s45_core_0/inst/g_raw.u_raw raw_core_util.rpt "s45_core_0 の RAW（予言 RAMB36 8 前後）" \
                    s45_core_0/inst/u_full/u_spec/u_acc acc_util.rpt "コア 0 の積分器（予言 URAM 24）" \
                    s45_core_1/inst/u_full/u_spec/u_acc acc1_util.rpt "コア 1 の積分器（予言 URAM 24）" \
                    s45_core_0/inst/u_full/u_spec/u_pfb pfb_util.rpt "コア 0 の PFB（履歴 ＋ 係数 RAMB36 4）"} {
    set cc [get_cells -quiet $c]
    if {$cc eq ""} { set cc [get_cells -quiet -hierarchical -filter "NAME =~ *$c"] }
    if {$cc eq ""} { puts "  WARNING: $c のセルが見つからない（utilization_hier.rpt で見る）"; continue }
    report_utilization -cells [lindex $cc 0] -file $outdir/$f
    puts "  $what:"
    foreach line [split [exec cat $outdir/$f] \n] {
        if {[regexp {^\|\s*(CLB LUTs|CLB Registers|Block RAM Tile|URAM|DSPs)\s*\|} $line]} { puts "    [string trim $line]" }
    }
}
# 全体の LUT・FF・URAM・BRAM を utilization.rpt から。README の E-1（PFB あり・URAM 2 列 ＋ BRAM・積）: DSP 19.6 %・BRAM 57.8 %・URAM 70 %・LUT 23.9 %
if {![catch {set fh [open $outdir/utilization.rpt r]; set ut [read $fh]; close $fh}]} {
    foreach line [split $ut "\n"] {
        if {[regexp {^\|\s*(CLB LUTs|CLB Registers|URAM|Block RAM Tile|DSPs)\*?\s*\|} $line]} { puts "  全体: [string trim $line]" }
    }
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

# ---- proj023 3b: 負の setup 経路の塊（始点 → 終点のセルの階層）----
# 1 回目のビルドは 2,251 本が負だったが、診断は最悪 5 本しか出さず、配置後の dcp を開き直す worst_paths は Vivado が落ちた。
# **開いている設計のまま**、負の経路を始点・終点の階層（コアの番号と添字を * に）で束ねて数える
if {[get_property STATS.WNS [get_runs impl_1]] < 0} {
    proc hier_key {pin} {
        set parts [split [string trimleft $pin /] /]
        set h [join [lrange $parts 0 end-2] /]
        regsub -all {s45_core_\d+} $h {s45_core_*} h
        regsub -all {\[\d+\]} $h {[*]} h
        return $h
    }
    set grp [dict create]
    set nneg 0
    foreach pth [get_timing_paths -quiet -max_paths 5000 -nworst 1 -setup -slack_lesser_than 0] {
        incr nneg
        set k "[hier_key [get_property STARTPOINT_PIN $pth]] → [hier_key [get_property ENDPOINT_PIN $pth]]"
        set sl [get_property SLACK $pth]
        if {[dict exists $grp $k]} {
            lassign [dict get $grp $k] n w
            dict set grp $k [list [expr {$n + 1}] [expr {min($w, $sl)}]]
        } else { dict set grp $k [list 1 $sl] }
    }
    puts ""
    puts "---- 負の setup 経路の塊（$nneg 本、上限 5000。始点 → 終点の階層、本数の多い順に 20）----"
    set rows {}
    dict for {k v} $grp { lappend rows [list $k {*}$v] }
    set fh [open $outdir/neg_paths_groups.rpt w]
    set i 0
    foreach r [lsort -integer -decreasing -index 1 $rows] {
        lassign $r k n w
        set line [format "  %5d 本  最悪 %7.3f  %s" $n $w $k]
        puts $fh $line
        if {[incr i] <= 20} { puts $line }
    }
    close $fh
    puts "  全部: $outdir/neg_paths_groups.rpt（[dict size $grp] 塊）"
    report_timing -max_paths 20 -nworst 1 -slack_lesser_than 0 -file $outdir/neg_paths_top20.rpt
}

# ---- 宣言していないクロックに経路が残っていないか ----
# timing.xdc が非同期と宣言しているのは clk_pl_0 / RFADC2_CLK 系 / clk_out2 の 3 群だけ。
# proj006 以降 **clk_adc0 をどこにも繋いでいない**ので、RFADC0_CLK には
# ファブリックの経路が無いはずである。使っていないタイル / DAC の
# ダミークロックも同じ。**前提を数えて確かめる。**
# ここに経路が出たら、timing.xdc にその群を足すか、配線を見直す。
# ---- 乗り換えの分類は Vivado 自身に出させる ----
#
# **自作の経路数えは偽陽性を出した**（2026-09-17）。
# `get_timing_paths -from <clock>` は **slack を持たない経路（= 解析対象外）も返す。**
# RFADC0/1/3 と RFDAC0..3 に 8 本ずつ出たので制約漏れかと思ったが、
# **timing.xdc で宣言済みの RFADC2_CLK も全く同じ 8 本を返した。**
# 終点はいずれも `rfdc/inst/IP2Bus_Data_reg[*]/D` — RFDC IP の内部で、
# タイルのステータスが AXI4-Lite の読み出しレジスタへ渡る経路であり、
# **IP が自前の制約で処理済み**である（だから slack が空）。
#
# **対照（宣言済みのクロック）を並べていたから偽陽性と分かった。**
# 片方しか見ない診断は、診断自体が嘘をつく。
#
# 以後は 2 段構えにする:
#   1. report_cdc — 乗り換えを Vivado が分類する専用コマンド。**これを正とする**
#   2. 自作の数えは **slack を持つ経路だけ**に絞る（対照も残す）
if {![catch {report_cdc -details -file $outdir/cdc.rpt} cdc_err]} {
    set fh [open $outdir/cdc.rpt r]; set txt [read $fh]; close $fh
    puts ""
    puts "---- 乗り換え（report_cdc）----"
    set shown 0
    foreach line [split $txt \n] {
        # 要約表は罫線なしの固定幅（2026-09-17 に | で拾おうとして空振りした）:
        #   CDC-1   Critical     26  1-bit unknown CDC circuitry
        if {[regexp {^\s*CDC-\d+\s+(Critical|Warning|Info)\s+\d+} $line]} {
            puts "  [string trim $line]"
            incr shown
        }
    }
    if {$shown == 0} { puts "  （要約表を拾えなかった。中身を直接見る）" }
    puts "  詳細: $outdir/cdc.rpt"
} else {
    puts ""
    puts "WARNING: report_cdc が使えない: $cdc_err"
}

puts ""
puts "---- タイルのクロックから出る経路（**解析対象のものだけ**）----"
puts "  対象外 = slack を持たない = IP の制約か clock group で既に除かれている"
foreach cn {RFADC0_CLK RFADC1_CLK RFADC2_CLK RFADC3_CLK \
            RFDAC0_CLK RFDAC1_CLK RFDAC2_CLK RFDAC3_CLK} {
    set c [get_clocks -quiet $cn]
    if {[llength $c] == 0} { continue }
    set mark [expr {$cn eq "RFADC2_CLK" ? " (宣言済み・対照)" : ""}]
    set timed 0
    set untimed 0
    set worst ""
    set worst_ec ""
    foreach pth [get_timing_paths -quiet -from $c -max_paths 40 -nworst 1 -setup] {
        set sl [get_property SLACK $pth]
        if {$sl eq ""} { incr untimed; continue }
        incr timed
        if {$worst eq "" || $sl < $worst} {
            set worst $sl
            set worst_ec [get_property ENDPOINT_CLOCK $pth]
        }
    }
    set detail ""
    if {$timed > 0} {
        set detail [format "  最悪 %+.3f → %s   **解析対象の経路がある。timing.xdc を見直す**" \
                    $worst $worst_ec]
    }
    puts [format "  %-12s%-18s 解析対象 %2d 本 / 対象外 %2d 本%s" \
          $cn $mark $timed $untimed $detail]
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
    puts "  クロック対が違っていれば src/board/timing.xdc の非同期宣言の漏れ。"
    puts "  **XDC で if / foreach を使うと黙って無効になる**（Designutils 20-1307）"
    exit 1
}

if {!$has_preset} {
    puts ""
    puts "NOTE: これは PS にプリセットを当てていない検証ビルド（$part）。"
    puts "      このビットストリームは実機に使わない。見るのは上の TIMING の値だけ。make ps-preset で src/board/ps_preset.tcl を作る"
}

