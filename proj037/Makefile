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
PROJ ?= proj037

export BOARD_REPO PART OUTDIR

PYTHON ?= python3
SIM_J  ?= 16

.PHONY: all prog id timing-check clean sim-all sim-u sim-reg

all: $(OUTDIR)
	$(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado.log -source build.tcl -tclargs $(JOBS)

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

# ---- sim（U の判定と、proj028 から写した部品の回帰）。成否は make の終了状態でなく各ログの「結果:」で読む ----
# U: ブロックの位相（U-a）・RUN の印と区切り（U-b）・D_S（U-e）・頭と帳簿（U-c）・リングの尾（U-d、≒ 3 分）・ct_wr の印
SIM_U   := cpfbph:"tools/sim_cpfb_ph.py" cpfbph_bad:"tools/sim_cpfb_ph.py --bad" cpfbph_gapt:"tools/sim_cpfb_ph.py --gapt" \
           s2_ub:"tools/sim_s2_strm.py ub" s2_ub_bad:"tools/sim_s2_strm.py ub --bad" s2_ue:"tools/sim_s2_strm.py ue" \
           s2_ue_bad:"tools/sim_s2_strm.py ue --bad" s2_uc:"tools/sim_s2_strm.py uc" s2_uc_bad:"tools/sim_s2_strm.py uc --bad" \
           s2_ud:"tools/sim_s2_ring.py" s2_ud_bad:"tools/sim_s2_ring.py --bad" \
           ctwr_mark:"tools/sim_ct_wr.py --mark" ctwr_mark64:"tools/sim_ct_wr.py --mark --qb 64" ctwr_markbad:"tools/sim_ct_wr.py --mark-bad"
# proj028 の回帰（口を変えた部品の照合を 4.4 の頭に直したもの）
SIM_REG := cpfb:"tools/sim_coarse_pfb.py" cpfb_gap:"tools/sim_coarse_pfb.py --gap" cpfb_bad:"tools/sim_coarse_pfb.py --bad" \
           cstage:"tools/sim_coarse_stage.py" cstage_bad:"tools/sim_coarse_stage.py --bad" \
           ctwr:"tools/sim_ct_wr.py" ctwr64:"tools/sim_ct_wr.py --qb 64" ctwr_bad:"tools/sim_ct_wr.py --bad" ctwr_stall:"tools/sim_ct_wr.py --stall" \
           ctrd:"tools/sim_ct_rd.py" ctrd_bad:"tools/sim_ct_rd.py --bad" ctrd_nout1:"tools/sim_ct_rd.py --nout1" \
           facc:"tools/sim_fine_acc.py" facc_first:"tools/sim_fine_acc.py --first-err" facc_k2:"tools/sim_fine_acc.py --k2-err" \
           fcore:"tools/sim_fine_core.py" fcore_act:"tools/sim_fine_core.py --act-err" fcore_rate:"tools/sim_fine_core.py --rate" \
           fcore_rate_old:"tools/sim_fine_core.py --rate-old"

define run_sims
	mkdir -p build-sim build-sim-logs
	@printf '%s\n' $(1) | xargs -P $(SIM_J) -I{} sh -c 'n=$${1%%:*}; c=$${1#*:}; c=$${c#\"}; c=$${c%\"}; $(PYTHON) $$c > build-sim-logs/$$n.log 2>&1' _ {}
	@grep -H "結果:" build-sim-logs/*.log || true
endef

sim-u:
	$(call run_sims,$(SIM_U))

sim-reg:
	$(call run_sims,$(SIM_REG))

sim-all:
	$(call run_sims,$(SIM_U) $(SIM_REG))
	@n=$$(ls build-sim-logs/*.log | wc -l); g=$$(grep -l "結果: 全部通過\|結果: 不合格（陽性対照として正しく落ちた）\|結果: 陽性対照（STALL）\|結果: 全部通過（" build-sim-logs/*.log | wc -l); \
	  echo "sim-all: $$g / $$n が予言どおり"
