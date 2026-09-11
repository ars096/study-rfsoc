# SPDX-License-Identifier: BSD-3-Clause
# ---- 自走 100 MHz システムクロック（Si5395 生成・LVDS）----
set_property -dict {PACKAGE_PIN AM15 IOSTANDARD LVDS} [get_ports sys_clk_p]
set_property -dict {PACKAGE_PIN AM16 IOSTANDARD LVDS} [get_ports sys_clk_n]
create_clock -name sys_clk -period 10.000 [get_ports sys_clk_p]

# HP バンクでは内部 100 ohm 終端を使うのが基本。
# 基板側に外部終端がある場合は二重終端になるので BSP の XDC を優先する。
set_property DIFF_TERM_ADV TERM_100 [get_ports sys_clk_p]

# ---- ユーザ LED ----
set_property -dict {PACKAGE_PIN AR11 IOSTANDARD LVCMOS18} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN AW10 IOSTANDARD LVCMOS18} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN AT11 IOSTANDARD LVCMOS18} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN AU10 IOSTANDARD LVCMOS18} [get_ports {led[3]}]

# ---- ビットストリーム設定 ----
set_property BITSTREAM.GENERAL.COMPRESS TRUE [current_design]
set_property BITSTREAM.CONFIG.OVERTEMPSHUTDOWN ENABLE [current_design]
