# SPDX-License-Identifier: BSD-3-Clause
# proj028 F-5a — 細かい側の全体（fine_top = AXI4-Lite ＋ fine_core）を、本物のレーン FFT（xfft 8192 点 × 16）込みで OOC の合成・配置配線（`-1`・256 MHz）
#   vivado -mode batch -source tools/f5_ooc.tcl -tclargs <jobs>
# IP の設定は proj024 の tools/ip_impl.tcl の fft_req を写した（固定長・realtime・unscaled・入力 15 bit・bit 反転順）。モジュール名は RTL と sim の模型と対の lane_fft_f
# 照合（違えば exit 1）: IP の設定が要求どおり / IP のポートが RTL と合う / IP が 16 個・出口 64 本 / 合成が完走 / 時間を見た経路がある /
#   陽性対照: 配線の後にクロックを 1.5 ns に作り直すと WNS が負
# 出力: build-f5ooc/f5ooc.txt・util_*.rpt・timing_*.rpt・params_lane_fft_f.rpt
set part xczu48dr-ffvg1517-1-e
set outdir ./build-f5ooc
set jobs 8
if {[llength $argv] > 0} { set jobs [lindex $argv 0] }
set per 3.906
file mkdir $outdir
create_project f5ooc $outdir/vivado -part $part -force

proc fft_req {n in_w order clk_mhz} {
    return [list \
        CONFIG.transform_length                       $n                     1 \
        CONFIG.implementation_options                 pipelined_streaming_io 1 \
        CONFIG.data_format                            fixed_point            1 \
        CONFIG.input_width                            $in_w                  1 \
        CONFIG.scaling_options                        unscaled               1 \
        CONFIG.output_ordering                        $order                 1 \
        CONFIG.xk_index                               true                   1 \
        CONFIG.throttle_scheme                        realtime               1 \
        CONFIG.aresetn                                true                   1 \
        CONFIG.run_time_configurable_transform_length false                  1 \
        CONFIG.cyclic_prefix_insertion                false                  1 \
        CONFIG.channels                               1                      1 \
        CONFIG.complex_mult_type                      use_mults_resources    1 \
        CONFIG.butterfly_type                         use_luts               1 \
        CONFIG.target_clock_frequency                 $clk_mhz               0 \
        CONFIG.phase_factor_width                     18                     0 \
        CONFIG.rounding_modes                         convergent_rounding    0 \
        CONFIG.ovflo                                  false                  0 \
    ]
}

# ---- IP ----
set ng 0
create_ip -name xfft -vendor xilinx.com -library ip -module_name lane_fft_f
set ip [get_ips lane_fft_f]
set req [fft_req 8192 15 bit_reversed_order 256]
foreach {k val fatal} $req { if {[catch {set_property $k $val $ip} msg]} { puts "  $k = $val を設定できない: $msg"; if {$fatal} { incr ng } } }
foreach {k val fatal} $req {
    set got ""; catch {set got [get_property $k $ip]}
    if {![string equal -nocase $got $val] && $fatal} { puts "  $k = $got（要求 $val）"; incr ng }
}
set fh [open $outdir/params_lane_fft_f.rpt w]
foreach k [lsort [list_property $ip CONFIG.*]] { puts $fh [format "%-50s %s" $k [get_property $k $ip]] }
close $fh
if {$ng > 0} { puts "ERROR: FFT IP の設定が $ng 件、要求どおりにならない"; exit 1 }
generate_target {instantiation_template synthesis} $ip

# ---- IP のポートの幅（fine_core.v の結線と同じ。模型 sim/lane_fft_f_model.v とも同じ）----
set vt [lindex [get_files -quiet -of_objects $ip *.veo] 0]
if {$vt eq ""} { puts "ERROR: lane_fft_f の .veo が無い"; exit 1 }
set fh [open $vt r]; set veo [read $fh]; close $fh
set ng 0
foreach {pn w} {s_axis_data_tdata 32 m_axis_data_tdata 64 m_axis_data_tuser 16 s_axis_config_tdata 8} {
    if {![regexp "\\.${pn}\\(" $veo]} { incr ng; puts "  IP のポート $pn が無い"; continue }
}
# 幅は合成後のセルのピンで照らす（下）
foreach pn {event_frame_started event_tlast_unexpected event_tlast_missing event_data_in_channel_halt} {
    if {![regexp "\\.${pn}\\(" $veo]} { incr ng; puts "  IP のポート $pn が無い" }
}
# 在ってはいけない: 出力の halt（realtime では無いはず。在れば設定が non-realtime）
if {[regexp {\.event_data_out_channel_halt\(} $veo]} { incr ng; puts "  event_data_out_channel_halt が在る（realtime になっていない）" }
if {$ng > 0} { puts "ERROR: IP のポートが RTL と合わない"; exit 1 }

# ---- RTL ----
set src [file normalize ./src/fine]
foreach f {fine_top.v fine_core.v fine_pfb.v fine_coef.v fine_tw.v fine_chain.v fine_acc.v fine_rdo.v cmul.v dft16f.v} { add_files $src/$f }
set_property top fine_top [current_fileset]
set gens {}
foreach {par f} {LO_FILE fine_coef_lo.hex HI_FILE fine_coef_hi.hex TA_FILE fine_tw_a.hex TB_FILE fine_tw_b.hex} {
    if {![file exists $src/$f]} { puts "ERROR: $src/$f が無い（make gen-fine）"; exit 1 }
    lappend gens "$par=\"$src/$f\""
}
set_property generic $gens [current_fileset]
set xdc $outdir/clk.xdc
set fh [open $xdc w]; puts $fh "create_clock -name aclk -period $per \[get_ports aclk\]"; close $fh
add_files -fileset constrs_1 [file normalize $xdc]
set_property -name {STEPS.SYNTH_DESIGN.ARGS.MORE OPTIONS} -value {-mode out_of_context} -objects [get_runs synth_1]
update_compile_order -fileset sources_1

# Vivado が合成の終わり際に落ちる型（Abnormal program termination。proj012〜、2026-10-26 の 1 回目もこれ）は、落ちた印のある run だけ 2 回まで回し直す
proc run_crashed {n} {
    set lf [file join $::outdir vivado f5ooc.runs $n runme.log]
    if {![file exists $lf]} { return 0 }
    set fh [open $lf r]; set t [read $fh]; close $fh
    return [regexp {Abnormal program termination|segfault in } $t]
}
launch_runs synth_1 -jobs $jobs
catch {wait_on_run synth_1}
for {set try 1} {$try <= 2 && [get_property PROGRESS [get_runs synth_1]] ne "100%"} {incr try} {
    set redo ""
    foreach n {lane_fft_f_synth_1 synth_1} { if {[run_crashed $n]} { set redo $n; break } }
    if {$redo eq ""} break
    puts "NOTE: $redo で Vivado が落ちた。回し直す（$try 回目）"
    reset_run [get_runs $redo]
    launch_runs synth_1 -jobs $jobs
    catch {wait_on_run synth_1}
}
if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} { puts "ERROR: synth_1 が完走しなかった（[get_property STATUS [get_runs synth_1]]）"; exit 1 }
open_run synth_1

proc uf {txt label} { if {[regexp -line "^\\|\\s*${label}\\*?\\s*\\|\\s*(\\d+(?:\\.\\d+)?)\\s*\\|" $txt -> n]} { return $n }; return "?" }
proc row {stage} {
    set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
    set whs [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -hold]]
    set rpt [report_utilization -return_string]
    set fh [open $::outdir/util_$stage.rpt w]; puts $fh $rpt; close $fh
    report_timing -max_paths 10 -nworst 1 -setup -file $::outdir/timing_$stage.rpt
    set dsp [llength [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E2}]]
    return [list $stage $dsp [uf $rpt {CLB LUTs}] [uf $rpt {CLB Registers}] [uf $rpt {Block RAM Tile}] [uf $rpt URAM] $wns $whs]
}

# 合成後の照合: IP は 16 個・ROM が残った・Synth 8-3848（ドライバの無いネット）が無い
set nip [llength [get_cells -quiet -hierarchical -filter {REF_NAME == lane_fft_f || ORIG_REF_NAME == lane_fft_f}]]
puts "lane_fft_f のセル: $nip 個（期待 16）"
if {$nip != 16} { puts "ERROR: lane_fft_f が 16 個でない"; exit 1 }
set p [get_pins -quiet -of_objects [lindex [get_cells -hierarchical -filter {REF_NAME == lane_fft_f || ORIG_REF_NAME == lane_fft_f}] 0] -filter {NAME =~ *m_axis_data_tdata*}]
puts "IP の m_axis_data_tdata: [llength $p] 本（期待 64）"
if {[llength $p] != 64} { puts "ERROR: IP の出口の幅が 64 でない"; exit 1 }
set sl [glob -nocomplain $outdir/vivado/f5ooc.runs/synth_1/runme.log]
set fh [open $sl r]; set t [read $fh]; close $fh
set n3848 [regexp -all {Synth 8-3848} $t]
set ncw   [regexp -all -line {^CRITICAL WARNING} $t]
puts "合成のログ: Synth 8-3848 $n3848 件・CRITICAL WARNING $ncw 件"
foreach m [regexp -all -inline -line {^CRITICAL WARNING.*$} $t] { puts "  $m" }
set rows [list [row synth]]

opt_design
place_design
phys_opt_design
route_design
set nseq [llength [get_cells -quiet -hierarchical -filter {IS_SEQUENTIAL}]]
if {$nseq == 0} { puts "ERROR: 順序回路が無い"; exit 1 }
lappend rows [row route]
write_checkpoint -force $outdir/route.dcp

# 陽性対照: 周期 1.5 ns にすると負（解析が経路を見ていること）
create_clock -name aclk -period 1.5 [get_ports aclk]
set pc [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]

set fh [open $outdir/f5ooc.txt w]
set fmt "%-6s %5s %7s %7s %6s %5s %8s %8s"
foreach ch [list stdout $fh] {
    puts $ch ""
    puts $ch "---- fine_top（fine_core ＋ lane_fft_f × 16）OOC（$part、$per ns）----"
    puts $ch [format $fmt 段 DSP LUT FF BRAM URAM WNS WHS]
    foreach r $rows { puts $ch [format $fmt {*}$r] }
    puts $ch "陽性対照（配線の後に 1.5 ns）: WNS $pc（負であること）"
}
close $fh
if {$pc >= 0} { puts "ERROR: 陽性対照が負にならない。解析が効いていない疑い"; exit 1 }
puts "\n=== F-5a 完了: $outdir/f5ooc.txt ==="
