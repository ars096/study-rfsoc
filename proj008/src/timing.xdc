# SPDX-License-Identifier: BSD-3-Clause
# proj007 — クロックドメイン間の扱い（proj006 から制約そのものは変えていない）
#
# **XDC では一般の Tcl が使えない。**
#   CRITICAL WARNING: [Designutils 20-1307] Command 'if' is not supported in the
#   xdc constraint file.
# if / foreach / lsort / concat などは弾かれ、**その行は実行されない**。
# 2026-09-16、オブジェクトが取れなかったときに警告を出す「防御的な」書き方をして
# これを踏んだ。防御そのものが XDC で動かない構文だったため制約が丸ごと無効になり、
# WNS = -4.556 ns のビットストリームができた。
#
# したがって **XDC には制約だけを書く。** 効いたかどうかの検証は build.tcl 側
# （open_run 後、full Tcl が使えるところ）で行う。
#
# クロックの実名は 2026-09-16 のビルド（proj003）で確認した値。
#
#   clk_pl_0                       10.000 ns   PS の PL クロック 0（制御系）
#   clk_pl_1                        5.714 ns   PS の PL クロック 1（データ系 MM 側）
#   RFADC2_CLK                     13.021 ns   RFDC の clk_adc2（76.8 MHz）
#   clk_out1_system_clk_wiz_adc_0   6.510 ns   MMCM 出力（153.6 MHz、AXIS）
#
# clk_out1_... は RFADC2_CLK から派生した生成クロックなので
# -include_generated_clocks で一緒に入る。
#
# ---- proj007 で増えるもの: 無い ----
# 1PPS の入力（pps_trig / pps_comp）は **クロックではない**。pps_capture の中で
# 3 段の同期器（ASYNC_REG 付き）に入るだけなので、ここに足すものは無い。
# ピンの配置と set_false_path は src/pps.xdc に分けてある
# （物理制約とクロック制約を 1 つのファイルに混ぜない）。
# **pps_capture は AXIS ドメイン（clk_out1_...）と clk_pl_0 の 2 つしか使わない**ので、
# 下の 3 群の宣言がそのまま効く。
#
# ---- proj006 で増えたもの ----
# Tile 224 を使うので **RFADC0_CLK（76.8 MHz）が現れる**。ただし proj006 では
# clk_adc0 を **どこにも繋いでいない**（AXIS クロックは MMCM 1 個から両タイルへ配る）。
# したがって RFADC0_CLK からファブリックへ出る経路は無く、グループに足す必要もない。
# **足すと get_clocks が空を返したときに set_clock_groups が落ちる**ので、
# 「無いかもしれないもの」を XDC に書かない。
#
# 効いたかどうかは build.tcl の open_run 側で見る:
#   - 「---- クロック ----」に RFADC0_CLK が出るか
#   - build/clock_interaction.rpt に RFADC0_CLK 絡みの未制約の組が出ていないか
# **ここに RFADC0_CLK 絡みの違反が出たら、前提（繋いでいない）が崩れている。**

# ---- 3 系統は互いに非同期 ----
# **これが抜けると乗り換えが同期経路として解析され、実在しない違反が出る。**
# capture_gate の ctrl / status の乗り換えも、この宣言だけで解析対象から外れるので、
# 個別の set_false_path は要らない。
#
# なお ctrl[23:0]（n_beats）は 2FF 同期を通していないが、ソフトが arm の
# 立ち上がりより前に書き終えており、arm_rise の時点では十分に静定している
# （データ＋ハンドシェイク）。厳密には set_max_delay -datapath_only を張る方が
# よいが、ここでは静定の保証をもって足りているとする。
#
# **proj006 では capture_gate が 1 個のままである**ことが効いている。
# 4ch を 4 レーン並列にしていたら、同期器が 4 個になって「同じ arm を受けたのに
# 個体ごとに 1 クロックずれる」が起きえた。512 bit に束ねたのでその問題は無い。

set_clock_groups -asynchronous \
    -group [get_clocks -include_generated_clocks clk_pl_0] \
    -group [get_clocks -include_generated_clocks clk_pl_1] \
    -group [get_clocks -include_generated_clocks RFADC2_CLK]
