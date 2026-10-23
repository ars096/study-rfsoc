# SPDX-License-Identifier: BSD-3-Clause
# proj027 — Wide の束ね・切り出しの LUT を測る（make wide-hier）
#
# proj024 の残り「2G-4 の前に、Wide のビルドで階層を深くして測る」。新しいビルドはしない:
# SAM45-Wide の凍結版（proj023 ビルド 11、build-PE/）の配線済みチェックポイントを**読むだけ**で開き、
# s45_core_0 の u_wide の下を深さ 8 まで report_utilization -hierarchical で出す。proj023 のファイルには書かない（出力は proj027/build-wide/）。
# 照合（違えば exit 1）: 全体の CLB LUTs が build-PE/utilization.rpt と同じ（255,211）/ u_wide の LUT が utilization_hier.rpt と同じ
# 出力: build-wide/wide_hier_c0.rpt（コア 0 の階層）/ build-wide/top.txt

set dcp ../proj023/build-PE/vivado/proj023.runs/impl_1/system_wrapper_routed.dcp
set outdir ./build-wide
set want_total 255211
set_param general.maxThreads 8
open_checkpoint $dcp
set ng 0
report_utilization -file $outdir/top.txt
set fh [open $outdir/top.txt r]; set txt [read $fh]; close $fh
if {![regexp {\| CLB LUTs\s+\|\s+(\d+)} $txt -> got]} { set got -1 }
puts "CLB LUTs: $got（期待 $want_total）"
if {$got != $want_total} { puts "NG: 全体の LUT が build-PE と違う"; incr ng }
foreach c {0 1 2 3} {
    set cell system_i/s45_core_$c/inst/u_wide
    if {[llength [get_cells -quiet $cell]] == 0} { puts "NG: $cell が無い"; incr ng; continue }
    report_utilization -hierarchical -hierarchical_depth 8 -cells [get_cells $cell] -file $outdir/wide_hier_c$c.rpt
}
if {$ng} { puts "結果: 不合格 ($ng)"; exit 1 }
puts "結果: 全部通過"
