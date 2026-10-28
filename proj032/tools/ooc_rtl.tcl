# SPDX-License-Identifier: BSD-3-Clause
# proj032 — 自作の RTL（proj030 の tools/ooc_rtl.tcl の写し。`include の場所を OOC_INC で） を 1 個 OOC で合成して資源・合成の WNS・ドライバの無いネット（Synth 8-3848）を見る
#   vivado -mode batch -source tools/ooc_rtl.tcl -tclargs <top> <周期 ns> <クロックのポート> <ファイル...>
#   generic: OOC_GENERIC="LO_FILE=/abs/a.hex;HI_FILE=/abs/b.hex"
set part xczu48dr-ffvg1517-1-e
lassign $argv top period clkport
set files [lrange $argv 3 end]
set tag $top
if {[info exists ::env(OOC_TAG)] && $::env(OOC_TAG) ne ""} { set tag $::env(OOC_TAG) }
set outdir ./build-ooc/$tag
file mkdir $outdir
# OOC_FFT=1: FFT IP win_fft（複素 4096 点・入力 18 bit・unscaled・realtime・use_mults_resources・use_luts。proj021 の build.tcl と同じ設定）を作って一緒に合成する（E-4 の機関）
if {[info exists ::env(OOC_FFT)] && $::env(OOC_FFT) eq "1"} {
    create_project -in_memory -part $part
    create_ip -name xfft -vendor xilinx.com -library ip -module_name win_fft -dir $outdir
    set wfft [get_ips win_fft]
    set req [list CONFIG.transform_length 4096 CONFIG.implementation_options pipelined_streaming_io CONFIG.data_format fixed_point \
                  CONFIG.input_width 18 CONFIG.scaling_options unscaled CONFIG.output_ordering natural_order CONFIG.xk_index true \
                  CONFIG.throttle_scheme realtime CONFIG.aresetn true CONFIG.run_time_configurable_transform_length false \
                  CONFIG.cyclic_prefix_insertion false CONFIG.channels 1 CONFIG.complex_mult_type use_mults_resources CONFIG.butterfly_type use_luts]
    set_property -dict [concat $req [list CONFIG.target_clock_frequency 256 CONFIG.phase_factor_width 18 CONFIG.rounding_modes convergent_rounding CONFIG.ovflo false]] $wfft
    set ng 0
    foreach {k v} $req { if {![string equal -nocase [get_property $k $wfft] $v]} { puts "ERROR: win_fft $k = [get_property $k $wfft]（要求 $v）"; incr ng } }
    set ow ""; catch {set ow [get_property CONFIG.output_width $wfft]}
    if {$ow ne "" && $ow != 31} { puts "ERROR: win_fft の出力の幅 [get_property CONFIG.output_width $wfft]（期待 31）"; incr ng }
    if {$ng} { exit 1 }
    generate_target all $wfft
    synth_ip $wfft
}
foreach f $files { read_verilog $f }
# generic は環境変数 OOC_GENERIC（「名前=値」を ; で区切る）。$readmemh の hex は絶対パスで渡す（LESSONS: 読めないと ROM が 0 になり BRAM が消えるだけで通る）
set gens {}
if {[info exists ::env(OOC_GENERIC)] && $::env(OOC_GENERIC) ne ""} {
    foreach kv [split $::env(OOC_GENERIC) ";"] {
        lassign [split $kv "="] k v
        if {[string is integer -strict $v]} { lappend gens -generic "$k=$v" } else { lappend gens -generic "$k=\"$v\"" }
    }
}
set incs {}
if {[info exists ::env(OOC_INC)] && $::env(OOC_INC) ne ""} { set incs [list -include_dirs $::env(OOC_INC)] }
synth_design -top $top -part $part -mode out_of_context {*}$gens {*}$incs
create_clock -name $clkport -period $period [get_ports $clkport]
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set rpt [report_utilization -return_string]
set fh [open $outdir/util_$top.rpt w]; puts $fh $rpt; close $fh
report_timing -max_paths 5 -file $outdir/timing_$top.rpt
set dsp [llength [get_cells -quiet -hierarchical -filter {REF_NAME == DSP48E2}]]
proc uf {txt label} { if {[regexp -line "^\\|\\s*${label}\\*?\\s*\\|\\s*(\\d+(?:\\.\\d+)?)\\s*\\|" $txt -> n]} { return $n }; return "?" }
puts "OOC $top: DSP $dsp・LUT [uf $rpt {CLB LUTs}]・FF [uf $rpt {CLB Registers}]・BRAM [uf $rpt {Block RAM Tile}]・URAM [uf $rpt URAM]・WNS $wns（$period ns）"
# OOC_PLACE=1: opt_design・place_design まで進めて数え直す（合成の LUT は LUT の詰め合わせ前の数。LUTRAM の 2 出力の詰めなど）
if {[info exists ::env(OOC_PLACE)] && $::env(OOC_PLACE) eq "1"} {
    opt_design
    place_design
    set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
    set rpt [report_utilization -return_string]
    set fh [open $outdir/util_${top}_placed.rpt w]; puts $fh $rpt; close $fh
    report_utilization -hierarchical -hierarchical_depth 3 -file $outdir/util_${top}_placed_hier.rpt
    report_timing -max_paths 5 -file $outdir/timing_${top}_placed.rpt
    puts "OOC placed $top: DSP $dsp・LUT [uf $rpt {CLB LUTs}]・FF [uf $rpt {CLB Registers}]・BRAM [uf $rpt {Block RAM Tile}]・URAM [uf $rpt URAM]・WNS $wns（$period ns）"
}
