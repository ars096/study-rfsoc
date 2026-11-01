# SPDX-License-Identifier: BSD-3-Clause
# proj007 — 1PPS 入力のピンと非同期宣言
#
# 出典: RFSoC 4x2 Reference Manual Rev A6 / Figure 6 と Appendix A「1PPS Control」
#
#   基板シルクは `PPS Clk`。**1 本の SMA から 2 系統が PL へ出る。**
#     IRIG_TRIG_OUT  AH13   シュミットトリガ側
#     IRIG_COMP_OUT  AJ13   コンパレータ（LMV7235）直結側。**オープンドレイン**
#   同じ回路に ADS7885S（8bit SPI ADC）が居る（SDO = AK13 / SCLK = AH12）が、
#   **proj007 では使わない**（CS_N のピンが RefMan のピン表に出てこない。
#   入力レベルの確認は基板の外でスペアナかオシロで行う方が早く、確実）。
#
# **XDC には制約だけを書く。** if / foreach は
#   CRITICAL WARNING: [Designutils 20-1307] Command 'if' is not supported ...
# で弾かれ、**その行は実行されない**。防御的な書き方をすると防御そのものが動かず、
# 制約が丸ごと無効になる（proj003 で WNS = -4.556 ns のビットストリームを作った原因）。
# **効いたかどうかの検証は build.tcl の open_run 側で行う。**
# proj007 では「ポートが存在すること」「配置が AH13 / AJ13 であること」を
# build.tcl で読み返して確かめている。

set_property -dict {PACKAGE_PIN AH13 IOSTANDARD LVCMOS18} [get_ports pps_trig]
set_property -dict {PACKAGE_PIN AJ13 IOSTANDARD LVCMOS18} [get_ports pps_comp]

# **IRIG_COMP_OUT はオープンドレイン。**基板にプルアップが無ければ PL 側は浮く。
# 実機で trig 側だけが動いて comp 側が動かない / 常に H のままなら、
# **まずここを有効にして焼き直す**（2026-09-17 時点でプルアップの有無は未確認）。
#
# set_property PULLUP true [get_ports pps_comp]

# ---- 非同期入力 ----
# pps_capture 側で 3 段の同期器（ASYNC_REG 付き）に入る。
# **入力遅延を宣言しないと Vivado は「未制約の入力」として扱う。**
# 明示的に解析対象から外して、意図であることを残す。
set_false_path -from [get_ports pps_trig]
set_false_path -from [get_ports pps_comp]
