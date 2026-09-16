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
# 環境ごとに違うので Makefile では固定せず、ここを書き換えるか環境変数で渡す。
BOARD_REPO ?= $(HOME)/src/RFSoC4x2-BSP/board_files

JOBS ?= 8
PROJ ?= proj002

export BOARD_REPO

.PHONY: all prog id clean

all: build
	$(VIVADO) -mode batch -nojournal -log build/vivado.log -source build.tcl -tclargs $(JOBS)

prog:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl

# JTAG チェーンのデバイスを表示するだけ（合成ライセンス不要）
id:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl -tclargs id

build:
	mkdir -p build

clean:
	rm -rf build .Xil *.jou *.log
