# SPDX-License-Identifier: BSD-3-Clause
# proj003 — クロックドメイン間の扱い
#
# XDC は Tcl として評価される。オブジェクトが取れなかったときに黙って
# 制約が抜けるのが一番まずいので、取れなければ CRITICAL WARNING を出す。
#
# **ここが抜けると、タイミング解析は PS の PL クロックと RFDC の出力クロックを
# 関係のあるクロックとして扱い、実際には存在しない経路で巨大な違反を報告する。**
# WNS が説明できない値になったら、まずこのファイルが効いているかを疑う。

# ---- PS の PL クロックと ADC 側クロックは非同期 ----
set c_ps  [get_clocks -quiet clk_pl_*]
set c_adc [get_clocks -quiet -of_objects \
             [get_pins -quiet -hier -filter {NAME =~ *rfdc*clk_adc2}]]

if {[llength $c_ps] > 0 && [llength $c_adc] > 0} {
    set_clock_groups -asynchronous -group $c_ps -group $c_adc
    puts "XDC: 非同期クロックグループを設定した"
    puts "XDC:   PS  = $c_ps"
    puts "XDC:   ADC = $c_adc"
} else {
    puts "CRITICAL WARNING: 非同期クロックグループを設定できなかった。"
    puts "  clk_pl_*      = $c_ps"
    puts "  rfdc/clk_adc2 = $c_adc"
    puts "  クロック名が版で変わった可能性がある。report_clocks で実名を確認すること"
}

# ---- capture_gate の乗り換え点 ----
# ctrl（pl_clk0 → aclk）と status（aclk → pl_clk0）。いずれも 2FF 同期の
# 初段レジスタが終点なので、経路そのものは解析しない。
foreach patt {*arm_sync_reg[0]* *busy_sync_reg[0]* *done_sync_reg[0]* *remain_reg*} {
    set cells [get_cells -quiet -hier -filter "NAME =~ $patt"]
    if {[llength $cells] > 0} {
        set_false_path -to $cells
    } else {
        puts "CRITICAL WARNING: false path の終点が見つからない（$patt）"
    }
}
