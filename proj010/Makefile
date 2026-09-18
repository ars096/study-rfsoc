# SPDX-License-Identifier: BSD-3-Clause
# Vivado のインストール先をここで持つ。
# settings64.sh を .bashrc で source しないこと（Xilinx 同梱の古い共有ライブラリが
# LD_LIBRARY_PATH の先頭に入り、git / ssh / python が壊れる）。
# bin/vivado は起動スクリプト自身が環境を組み立てるので、絶対パスで叩けば動く。
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado

# RealDigitalOrg/RFSoC4x2-BSP を clone した先の board_files ディレクトリ。
# Vivado のインストールツリーの中には置かない（VERSIONS.md 参照）。
BOARD_REPO ?= $(HOME)/src/RFSoC4x2-BSP/board_files

# part。**-1 で閉じる設計は -2 でも必ず閉じる**ので `make timing-check` で -1 でも通す。
PART_DEFAULT := xczu48dr-ffvg1517-2-e
PART         ?= $(PART_DEFAULT)

# 既定以外の part は別ディレクトリに出し、検証済みの成果物を上書きしない。
ifeq ($(PART),$(PART_DEFAULT))
  OUTDIR := build
else
  OUTDIR := build-$(patsubst xczu48dr-ffvg1517-%,%,$(PART))
endif

# 同時に走らせる run の数（launch_runs -jobs）。効くのは IP の OOC 合成だけ。
# proj010 は lane_fft（FFT IP）の OOC 合成が 1 本増える。ビルドサーバの nproc = 32 に合わせてある。
# コア数やメモリの少ない機械では `make JOBS=8` に下げること。
JOBS ?= 30

export BOARD_REPO PART OUTDIR

# ---- シミュレーション（Vivado もライセンスも要らない。RTL を触ったらまずこれ）----
# FFT IP の代わりに sim/lane_fft_model.v を使う。判定は sim/check.py（bit 単位・numpy・帳簿の 3 層）。
# 所要 8〜10 分（ほとんどが AXI4-Lite での 4096 ch × 2 語の読み出し 3 回ぶん）。
IVERILOG  ?= iverilog
VVP       ?= vvp
PYTHON    ?= python3
SIM_SHIFT ?= 7
SIMDIR    := build-sim-s$(SIM_SHIFT)
RTL       := src/spec_core.v src/cmul.v src/dft16.v src/tw_rom.v

.PHONY: all sim twiddle prog id timing-check clean

all: $(OUTDIR)
	$(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado.log -source build.tcl -tclargs $(JOBS)

# SIM_SHIFT=7: 飽和しない（numpy との照合を全 ch で行う）/ SIM_SHIFT=4: 強い線が飽和する（飽和の数え方を確かめる）
sim:
	mkdir -p $(SIMDIR)
	$(PYTHON) sim/check.py gen $(SIMDIR)
	$(IVERILOG) -g2005 -DOUT=\"$(SIMDIR)\" -DSHIFT=$(SIM_SHIFT) -o $(SIMDIR)/tb $(RTL) sim/lane_fft_model.v sim/tb_spec_core.v
	$(VVP) -n $(SIMDIR)/tb
	$(PYTHON) sim/check.py check $(SIMDIR) $(SIM_SHIFT)

# ひねり係数の ROM を作り直す（生成物もコミットする。差分が出たら理由を README に書く）
twiddle:
	$(PYTHON) tools/gen_tw_rom.py > src/tw_rom.v
	git diff --stat -- src/tw_rom.v

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
