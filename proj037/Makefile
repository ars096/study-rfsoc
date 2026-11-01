# SPDX-License-Identifier: BSD-3-Clause
# proj037 — 2G-1-Fine の RTL の sim（U）と .bit（V、`make`）。build の部分は YATSUGATAKE 54ce5e3 の hw/bits/2g-1-fast/Makefile を写した
#
# Vivado のインストール先。settings64.sh を .bashrc で source しないこと（VERSIONS.md）
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado
# RealDigitalOrg/RFSoC4x2-BSP を clone した先の board_files（-2 のビルドだけが使う）
BOARD_REPO ?= $(HOME)/src/RFSoC4x2-BSP/board_files
# part。既定は -1（実機の .bit。PS には src/board/ps_preset.tcl を当てる）。-2 は PART=xczu48dr-ffvg1517-2-e → build-2-e/
PART_DEFAULT := xczu48dr-ffvg1517-1-e
PART         ?= $(PART_DEFAULT)
# gb_gate のしきい値の既定（core_cmn の GB_K_RST）
GB_K_DEFAULT := 2
GB_K ?= $(GB_K_DEFAULT)
# 実装の戦略（impl_1 の strategy）。空なら既定。例: make IMPL=Performance_Explore → build-PE/
IMPL ?=
ifeq ($(PART),$(PART_DEFAULT))
  OUTDIR := build
else
  OUTDIR := build-$(patsubst xczu48dr-ffvg1517-%,%,$(PART))
endif
ifneq ($(GB_K),$(GB_K_DEFAULT))
  OUTDIR := $(OUTDIR)-k$(GB_K)
endif
ifneq ($(IMPL),)
  OUTDIR := $(OUTDIR)-$(shell echo $(IMPL) | tr -cd 'A-Z')
endif
# launch_runs -jobs（効くのは OOC 合成だけ）
BUILD_JOBS ?= 16
# .bit の USR_ACCESS に焼く値（YATSUGATAKE の M5b と同じ形。ここでは study-rfsoc の commit）: [31:4] commit の短いハッシュ 7 桁・[3:1] 0・
#   [0] proj037 の追跡しているファイルに未コミットの変更がある（rfsoc の他の proj の変更は見ない）。make を始めた時点で 1 回だけ決める。USR_ACCESS=none で焼かない
ifeq ($(origin USR_ACCESS),undefined)
  USR_ACCESS := $(shell h=$$(git rev-parse --short=7 HEAD 2>/dev/null | cut -c1-7); \
                  [ $${#h} = 7 ] && printf '0x%s%s' $$h $$(git status --porcelain --untracked-files=no -- . | grep -q . && echo 1 || echo 0))
endif
export BOARD_REPO PART OUTDIR GB_K IMPL USR_ACCESS
PROJ ?= proj037
PYTHON ?= python3
SIM_J  ?= 16

.PHONY: all build prog id clean sim-all sim-u sim-reg

all: build

# 合成〜ビットストリーム（1 時間を越える）。成果物は $(OUTDIR)/proj037.bit・.hwh。成否は make の終了状態でなくログの ERROR・TIMING (確定) で読む
build:
	@test -n "$(USR_ACCESS)" || { echo "USR_ACCESS を git から作れない（git の作業ツリーの中で make する。焼かないなら USR_ACCESS=none）"; exit 1; }
	@echo "USR_ACCESS: $(USR_ACCESS)"
	mkdir -p $(OUTDIR)
	$(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado.log -source build.tcl -tclargs $(BUILD_JOBS)
	@# 書き出した .bit を読み返し、焼くはずの値と照らす（在るかと、値が合うかの両側。none なら「無いこと」）
	@$(PYTHON) tools/bitinfo.py $(OUTDIR)/$(PROJ).bit --expect $(USR_ACCESS) > $(OUTDIR)/bitinfo.txt; s=$$?; cat $(OUTDIR)/bitinfo.txt; exit $$s

prog:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl

# JTAG チェーンのデバイスを表示するだけ（合成ライセンス不要）
id:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl -tclargs id

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
