# SPDX-License-Identifier: BSD-3-Clause
# Vivado のインストール先をここで持つ。
# settings64.sh を .bashrc で source しないこと（Xilinx 同梱の古い共有ライブラリが
# LD_LIBRARY_PATH の先頭に入り、git / ssh / python が壊れる）。
# bin/vivado は起動スクリプト自身が環境を組み立てるので、絶対パスで叩けば動く。
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2023.2
VIVADO        := $(XILINX_VIVADO)/bin/vivado

PROJ ?= proj001

.PHONY: all prog id clean

all: build
	$(VIVADO) -mode batch -nojournal -log build/vivado.log -source build.tcl

prog:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl

# JTAG チェーンのデバイスを表示するだけ（合成ライセンス不要）
id:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl -tclargs id

build:
	mkdir -p build

clean:
	rm -rf build .Xil *.jou *.log
