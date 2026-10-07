# SPDX-License-Identifier: BSD-3-Clause
# proj011 — FFT IP（lane_fft）の設定。build.tcl と tools/ip_survey.tcl の両方が source する。
#
# **設定を 1 か所に置く理由**: IP 単体の調査（make survey）と本番のビルド（make）で
# 違う設定を数えてしまうと、調査の数字が本番の予言に使えない。
#
# fft_req {throttle cmul bfly} … {CONFIG 名  値  fatal} の並びを返す。
#   throttle: realtime | nonrealtime
#   cmul    : use_mults_resources（3 乗算） | use_mults_performance（4 乗算。proj010） | use_luts
#   bfly    : use_luts | use_xtremedsp_slices（proj010）
# proj011 では **乗算器・バタフライ・throttle を fatal にした**（proj010 では任意 = 0）。
# これが調べる対象なので、黙って既定値に戻られると測定そのものが無効になる。
#
# FFT_OPT（Makefile）の名前と中身:
#   res  = realtime + use_mults_resources  + use_luts             ← proj011 の本命（既定）
#   perf = realtime + use_mults_performance + use_xtremedsp_slices ← proj010 と乗算器が同じ。realtime の効きだけを分ける

proc fft_opt_map {opt} {
    switch -- $opt {
        res  { return [list realtime use_mults_resources  use_luts] }
        perf { return [list realtime use_mults_performance use_xtremedsp_slices] }
        default {
            puts "ERROR: FFT_OPT = '$opt' は知らない（res / perf）"
            exit 1
        }
    }
}

# spec_core の ID の下位 8 bit に載せる符号。PS から「どの変種の .bit が載っているか」を読むため
#   [0] realtime  [1] 乗算器が use_mults_resources  [2] バタフライが use_luts  [3] 乗算器が use_luts
proc fft_cfg_code {throttle cmul bfly} {
    set c 0
    if {$throttle eq "realtime"}            { incr c 1 }
    if {$cmul     eq "use_mults_resources"} { incr c 2 }
    if {$bfly     eq "use_luts"}            { incr c 4 }
    if {$cmul     eq "use_luts"}            { incr c 8 }
    return $c
}

proc fft_req {throttle cmul bfly lane_n in_w clk_mhz} {
    return [list \
        CONFIG.transform_length                       $lane_n                1 \
        CONFIG.implementation_options                 pipelined_streaming_io 1 \
        CONFIG.data_format                            fixed_point            1 \
        CONFIG.input_width                            $in_w                  1 \
        CONFIG.scaling_options                        unscaled               1 \
        CONFIG.output_ordering                        natural_order          1 \
        CONFIG.xk_index                               true                   1 \
        CONFIG.throttle_scheme                        $throttle              1 \
        CONFIG.aresetn                                true                   1 \
        CONFIG.run_time_configurable_transform_length false                  1 \
        CONFIG.cyclic_prefix_insertion                false                  1 \
        CONFIG.channels                               1                      1 \
        CONFIG.complex_mult_type                      $cmul                  1 \
        CONFIG.butterfly_type                         $bfly                  1 \
        CONFIG.target_clock_frequency                 [expr {int($clk_mhz)}] 0 \
        CONFIG.phase_factor_width                     18                     0 \
        CONFIG.rounding_modes                         convergent_rounding    0 \
        CONFIG.ovflo                                  false                  0 \
    ]
}
