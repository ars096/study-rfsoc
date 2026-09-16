# SPDX-License-Identifier: BSD-3-Clause
# proj002 — ユーザ LED のみ
#
# クロックとリセットは PS（pl_clk0 / pl_resetn0）から供給されるので、proj001 と違い
# sys_clk の制約は要らない。create_clock も不要（PS の IP が自分で宣言する）。

# ---- ユーザ LED ----
set_property -dict {PACKAGE_PIN AR11 IOSTANDARD LVCMOS18} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN AW10 IOSTANDARD LVCMOS18} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN AT11 IOSTANDARD LVCMOS18} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN AU10 IOSTANDARD LVCMOS18} [get_ports {led[3]}]

# ---- ビットストリーム設定 ----
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
set_property BITSTREAM.CONFIG.OVERTEMPSHUTDOWN ENABLE [current_design]
