# SPDX-License-Identifier: BSD-3-Clause
# Vivado のインストール先をここで持つ。
# settings64.sh を .bashrc で source しないこと（Xilinx 同梱の古い共有ライブラリが
# LD_LIBRARY_PATH の先頭に入り、git / ssh / python が壊れる）。
# bin/vivado は起動スクリプト自身が環境を組み立てるので、絶対パスで叩けば動く。
#
# proj001 は 2023.2。proj002 から 2024.1 に上げる（BSP と PYNQ v3.1.1 が前提とする版）。
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado

# RealDigitalOrg/RFSoC4x2-BSP を clone した先の board_files ディレクトリ。
# Vivado のインストールツリーの中には置かない（VERSIONS.md 参照）。
BOARD_REPO ?= $(HOME)/src/RFSoC4x2-BSP/board_files

# part。S-2 の .bit は実機と同じ -1 だけを作る（PS は src/board/ps_preset.tcl を当てる。proj015 から）
PART ?= xczu48dr-ffvg1517-1-e
OUTDIR := build

# 同時に走らせる run の数（launch_runs -jobs）。
# **効くのは IP の OOC 合成だけ。**impl_1 は単一の run なので、いくつにしても 1 つしか走らない。
# 2026-09-17 の proj006 の実測: IP 合成 + synth = 3分43秒 / impl = 5分44秒。
# つまり **-jobs が効くのは全体の 4 割**で、残りは general.maxThreads（既定 8）の領域。
#
# ビルドサーバの nproc = 32 に合わせてある。
# **コア数やメモリの少ない機械では下げること** — run 1 個が独立した Vivado プロセスで
# 数 GB 食うので、8 コアの機械で 30 にするとメモリを食い潰して逆に遅くなる。
# `make JOBS=8` で上書きできる。
JOBS ?= 8
PROJ ?= proj032d1

export BOARD_REPO PART OUTDIR

PYTHON ?= python3

.PHONY: all build prog id timing-check clean sim-ddrtg

# S-2: PL DDR4 の帯域と容量を測る .bit（PS ＋ MIG ＋ ddr_tg。この PC の Vivado、1 時間前後）。成果物は build/proj032d1.bit・.hwh（proj032 D-1。proj028 S-2f の写しに ddr_tg の流れの番地を足した）。
# 成否は make の終了状態でなく build/vivado.log の「TIMING (確定)」「CRITICAL WARNING: n 件」「=== wrote」で読む
build:
	mkdir -p $(OUTDIR)
	VIVADO_LOG=$(OUTDIR)/vivado.log $(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado.log -source build.tcl -tclargs $(JOBS)

# S-2: 負荷発生器 ddr_tg の単体の sim（AXI4 のメモリの模型）。ふつうと陽性対照（-DALIAS: 4 GB で番地が折り返す模型）を並べて回す。成否は各ログの「結果:」
sim-ddrtg:
	mkdir -p build-sim
	iverilog -g2012 -o build-sim/tb_ddr_tg.vvp tb/tb_ddr_tg.v src/ddr_tg.v
	iverilog -g2012 -DALIAS -o build-sim/tb_ddr_tg_alias.vvp tb/tb_ddr_tg.v src/ddr_tg.v
	iverilog -g2012 -DAW33 -o build-sim/tb_ddr_tg_aw33.vvp tb/tb_ddr_tg.v src/ddr_tg.v
	vvp -n build-sim/tb_ddr_tg.vvp > build-sim/sim_ddrtg.log & vvp -n build-sim/tb_ddr_tg_alias.vvp > build-sim/sim_ddrtg_alias.log & vvp -n build-sim/tb_ddr_tg_aw33.vvp > build-sim/sim_ddrtg_aw33.log & wait
	iverilog -g2012 -o build-sim/tb_clk_mon.vvp tb/tb_clk_mon.v src/clk_mon.v
	iverilog -g2012 -DNO_UI -o build-sim/tb_clk_mon_noui.vvp tb/tb_clk_mon.v src/clk_mon.v
	vvp -n build-sim/tb_clk_mon.vvp > build-sim/sim_clkmon.log & vvp -n build-sim/tb_clk_mon_noui.vvp > build-sim/sim_clkmon_noui.log & wait
	@grep "結果:" build-sim/sim_ddrtg.log build-sim/sim_ddrtg_alias.log build-sim/sim_ddrtg_aw33.log build-sim/sim_clkmon.log build-sim/sim_clkmon_noui.log


all: build

prog:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl

# JTAG チェーンのデバイスを表示するだけ（合成ライセンス不要）
id:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl -tclargs id

# 速度グレード -1 で通るかを確かめる。成果物は build-1-e/ に出るので build/ は無傷。
# D-1 は -1 だけを作るので、build がそのまま -1 の確かめ
timing-check: build


clean:
	rm -rf build build-* .Xil *.jou *.log
