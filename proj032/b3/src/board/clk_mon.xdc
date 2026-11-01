# SPDX-License-Identifier: BSD-3-Clause
# proj028 S-2 — clk_mon の同期器の 1 段目（参照クロック・UI クロックの側から pl_clk0 へ）。どれも ASYNC_REG の 2 段の同期器で受ける 1 bit
set_false_path -to [get_cells -hierarchical -filter {NAME =~ */clk_mon_0/inst/s_ref_reg[0] || NAME =~ */clk_mon_0/inst/s_ui_reg[0] || NAME =~ */clk_mon_0/inst/s_cal_reg[0] || NAME =~ */clk_mon_0/inst/s_rst_reg[0]}]
