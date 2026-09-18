# SPDX-License-Identifier: BSD-3-Clause
# proj010 — クロックドメイン間の扱い
#
# **XDC では一般の Tcl が使えない。**if / foreach などは CRITICAL WARNING
# [Designutils 20-1307] で弾かれ、**その行は実行されない**（2026-09-16 に踏んだ）。
# XDC には制約だけを書き、効いたかどうかは build.tcl の open_run 後で見る。
#
# クロック（名前は proj009 のビルドで確認済み）:
#   clk_pl_0                       10.000 ns   PS の PL クロック 0（制御系・SmartConnect の aclk）
#   RFADC2_CLK                      3.906 ns   clk_adc2 = fs/16 = 256 MHz（MMCM の入力だけ）
#   clk_out1_system_clk_wiz_adc_0   2.930 ns   341.333 MHz  ADC ドメイン（RFDC の AXIS・ギアボックス入口）
#   clk_out2_system_clk_wiz_adc_0   3.906 ns   256.000 MHz  DSP ドメイン（ギアボックス出口・spec_core・SmartConnect の aclk1）
#
# **proj009 から clk_pl_1 が消える**（DMA と HP ポートを外した）。
# 残っていると get_clocks が空を返して set_clock_groups が落ちるので、グループから外した。
#
# 乗り換えは 2 か所だけ:
#   clk_out1 → clk_out2   ギアボックスの非同期 FIFO（gb_fifo_0。proj009 と同じ）
#   clk_pl_0 ↔ clk_out2   SmartConnect の内部の乗り換え（spec_core の AXI4-Lite）
# どちらも既製 IP の中に閉じており、自作の RTL は乗り換えを持たない。

set_clock_groups -asynchronous \
    -group [get_clocks -include_generated_clocks clk_pl_0] \
    -group [get_clocks {RFADC2_CLK clk_out1_system_clk_wiz_adc_0}] \
    -group [get_clocks clk_out2_system_clk_wiz_adc_0]
