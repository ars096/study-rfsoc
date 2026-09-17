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

# part。速度グレードは BSP board_files の宣言値が -2、RefMan A5 は -1 と読める記載で
# 未決着（VERSIONS.md 参照）。**-1 で閉じる設計は -2 でも必ず閉じる**ので、
# タイミングが効く設計は `make timing-check` で -1 でも通しておく。
PART_DEFAULT := xczu48dr-ffvg1517-2-e
PART         ?= $(PART_DEFAULT)

# 既定以外の part は別ディレクトリに出し、検証済みの成果物を上書きしない。
ifeq ($(PART),$(PART_DEFAULT))
  OUTDIR := build
else
  OUTDIR := build-$(patsubst xczu48dr-ffvg1517-%,%,$(PART))
endif

# 同時に走らせる run の数（launch_runs -jobs）。
# **効くのは IP の OOC 合成だけ。**impl_1 は単一の run なので、いくつにしても 1 つしか走らない。
# 2026-09-17 の proj006 の実測: IP 合成 + synth = 3分43秒 / impl = 5分44秒。
# つまり **-jobs が効くのは全体の 4 割**で、残りは general.maxThreads（既定 8）の領域。
#
# ビルドサーバの nproc = 32 に合わせてある。
# **コア数やメモリの少ない機械では下げること** — run 1 個が独立した Vivado プロセスで
# 数 GB 食うので、8 コアの機械で 30 にするとメモリを食い潰して逆に遅くなる。
# `make JOBS=8` で上書きできる。
JOBS ?= 30
PROJ ?= proj007

export BOARD_REPO PART OUTDIR

.PHONY: all build sim sim-gate sim-pps prog id timing-check clean

all:
	@mkdir -p $(OUTDIR)
	$(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado.log -source build.tcl -tclargs $(JOBS)

# **`make build` を無効打にしない。**
# 以前は `build` にマッチするのが下の `$(OUTDIR): mkdir -p` だけだったので、
# ディレクトリが既にあると make は "'build' is up to date." と言って黙って終わった。
# **成功と区別がつかない失敗**なので、明示的に all の別名にしてある。
build: all

# テストベンチ。**Vivado もライセンスも要らない**ので、
# RTL を触ったらまずこれを通す。Mac 上でも走る。
#
#   sim-gate  capture_gate 単体（proj006 と同じ内容。即時モードの回帰）
#   sim-pps   pps_capture + capture_gate の結合。**予約発火で
#             t_start == start_at になることが本題**
#
# tb_pps_capture は失敗すると $fatal で **非ゼロ終了する**ので、make が止まる。
IVERILOG ?= iverilog
sim: sim-gate sim-pps

sim-gate:
	@mkdir -p $(OUTDIR)
	$(IVERILOG) -g2012 -o $(OUTDIR)/tb_capture_gate src/capture_gate.v sim/tb_capture_gate.v
	$(OUTDIR)/tb_capture_gate

sim-pps:
	@mkdir -p $(OUTDIR)
	$(IVERILOG) -g2012 -o $(OUTDIR)/tb_pps_capture \
	    src/pps_capture.v src/capture_gate.v sim/tb_pps_capture.v
	$(OUTDIR)/tb_pps_capture

prog:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl

# JTAG チェーンのデバイスを表示するだけ（合成ライセンス不要）
id:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl -tclargs id

# 速度グレード -1 で通るかを確かめる。成果物は build-1-e/ に出るので build/ は無傷。
timing-check:
	$(MAKE) PART=xczu48dr-ffvg1517-1-e

clean:
	rm -rf build build-* .Xil *.jou *.log
