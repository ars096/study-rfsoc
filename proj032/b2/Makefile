# SPDX-License-Identifier: BSD-3-Clause
# proj032 P-8 — b1 に PL の DDR（MIG）を足した .bit（b2）。Vivado は絶対パスで叩く（settings64.sh を .bashrc で source しない。d3/Makefile の注）
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado
BOARD_REPO ?= $(HOME)/src/RFSoC4x2-BSP/board_files
# 実機と同じ -1 だけを作る（PS は ../src/board/ps_preset.tcl を当てる）
PART ?= xczu48dr-ffvg1517-1-e
OUTDIR := build
JOBS ?= 8
# 実装の戦略（impl_1 の strategy）。空なら既定。例: make IMPL=Performance_Explore → build-PE/（proj031 と同じ）
IMPL ?=
ifneq ($(IMPL),)
  OUTDIR := $(OUTDIR)-$(shell echo $(IMPL) | tr -cd 'A-Z')
endif

export BOARD_REPO PART OUTDIR IMPL

.PHONY: all build post clean

# 成果物は build/proj032b2.bit・.hwh。成否は make の終了状態でなく build/vivado.log の「TIMING (確定)」「CRITICAL WARNING: n 件」「=== wrote」で読む
build:
	mkdir -p $(OUTDIR)
	VIVADO_LOG=$(OUTDIR)/vivado.log $(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado.log -source build.tcl -tclargs $(JOBS)

all: build

clean:
	rm -rf build build-* .Xil *.jou *.log

# impl_1 の後で親の Vivado が落ちたとき、後段（build_post.tcl）だけを回す
post:
	VIVADO_LOG=$(OUTDIR)/vivado_post.log RESUME=1 $(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado_post.log -source build_post.tcl
