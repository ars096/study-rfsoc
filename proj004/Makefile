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

JOBS ?= 8
PROJ ?= proj004

export BOARD_REPO PART OUTDIR

.PHONY: all sim prog id timing-check clean

all: $(OUTDIR)
	$(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado.log -source build.tcl -tclargs $(JOBS)

# capture_gate のテストベンチ。**Vivado もライセンスも要らない**ので、
# RTL を触ったらまずこれを通す。Mac 上でも走る。
IVERILOG ?= iverilog
sim: | $(OUTDIR)
	$(IVERILOG) -g2012 -o $(OUTDIR)/tb_capture_gate src/capture_gate.v sim/tb_capture_gate.v
	$(OUTDIR)/tb_capture_gate

prog:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl

# JTAG チェーンのデバイスを表示するだけ（合成ライセンス不要）
id:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl -tclargs id

# 速度グレード -1 で通るかを確かめる。成果物は build-1-e/ に出るので build/ は無傷。
timing-check:
	$(MAKE) PART=xczu48dr-ffvg1517-1-e

$(OUTDIR):
	mkdir -p $(OUTDIR)

clean:
	rm -rf build build-* .Xil *.jou *.log
