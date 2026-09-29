# SPDX-License-Identifier: BSD-3-Clause
# proj014 — 手順 1（模型）と手順 2（survey）だけの Makefile。
# 手順 3（RTL）で proj013 の追跡ファイルを複製するときに、proj013 の Makefile にこの 3 つのターゲットを足して置き換える。
# **それまで make（ビルド）のターゲットは置かない**（proj013 と同じ名前の .bit を作る道を作らない）。
#
# settings64.sh を .bashrc で source しないこと。bin/vivado を絶対パスで叩く。
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado
PART_DEFAULT  := xczu48dr-ffvg1517-2-e
PART          ?= $(PART_DEFAULT)
JOBS          ?= 8
PYTHON        ?= python3
MODEL_A       ?= 60
IVERILOG      ?= iverilog
VVP           ?= vvp
# sim-pfb の粗い ch（0・8・16 は実数化の後処理が自明になる端、4・12 は 45°）
PFB_KS        ?= 0 1 4 5 8 13 15 16
# SIM_PFB_POSCTL=1: 陽性対照（RTL の分岐の和の丸めを切り捨てに）。一致しなければ「結果: 全部通過」
SIM_PFB_POSCTL ?= 0
PFB_DIR       := build-sim-pfb$(if $(filter 1,$(SIM_PFB_POSCTL)),-posctl)

export PART

.PHONY: model model-posctl model-sweep fixed fixed-posctl coef sim-pfb survey clean

# 仕様の模型（numpy だけ。Vivado もライセンスも要らない）。成否は「結果: 全部通過」の行で読む
model:
	mkdir -p build-model
	$(PYTHON) model/win_model.py --a $(MODEL_A) --json build-model/coeffs.json | tee build-model/model.log

# 陽性対照 4 通り（pfb-short / hb-short / nco-sign / ppfb）。どれも落ちれば「結果: 全部通過」
model-posctl:
	mkdir -p build-model
	$(PYTHON) model/win_model.py --a $(MODEL_A) --posctl all | tee build-model/posctl.log

# 要求の深さを振った設計の比較（情報）
model-sweep:
	$(PYTHON) model/win_model.py --A 50 55 60 65 70

# 固定小数点の模型（語長・丸め・NCO）。同じ入力の浮動小数点と比べる。「結果: 全部通過」で読む
fixed:
	mkdir -p build-model
	$(PYTHON) model/win_fixed.py | tee build-model/fixed.log

# 陽性対照（FFT の入力の小数 G = 0 で N1 が落ちる）
fixed-posctl:
	mkdir -p build-model
	$(PYTHON) model/win_fixed.py --posctl | tee build-model/fixed_posctl.log

# 係数の生成物 src/win_coef.vh（リポジトリに入れる。手で直さない）。設計を変えたら作り直して sim-pfb を回し直す
coef:
	$(PYTHON) tools/gen_coef.py src/win_coef.vh

# pfb_core の単体の sim（iverilog）。model/win_fixed.py の pfb_fixed と bit 単位で照合。k ごと × 入力の途切れ あり / なし
sim-pfb:
	mkdir -p $(PFB_DIR)
	$(PYTHON) sim/check_pfb.py gen $(PFB_DIR)
	$(IVERILOG) -g2005 -Isrc $(if $(filter 1,$(SIM_PFB_POSCTL)),-DPFB_POSCTL) -o $(PFB_DIR)/tb src/cmul.v src/dft16f.v src/pfb_core.v sim/tb_pfb.v
	for k in $(PFB_KS); do for g in 0 1; do \
	  $(VVP) -n $(PFB_DIR)/tb +K=$$k +GAP=$$g +IN=$(PFB_DIR)/x.hex +OUT=$(PFB_DIR)/y_k$${k}_g$${g}.txt +NSAMP=16384 | grep '^pfb:' ; \
	done; done
	SIM_PFB_POSCTL=$(SIM_PFB_POSCTL) $(PYTHON) sim/check_pfb.py check $(PFB_DIR) $(PFB_KS) | tee $(PFB_DIR)/check.log

# FFT IP 単体の資源（ライセンスが要る。並列で 10〜20 分の見込み）。結果は build-survey/survey.txt
survey:
	mkdir -p build-survey
	$(VIVADO) -mode batch -nojournal -log build-survey/vivado.log -source tools/ip_survey.tcl -tclargs $(JOBS)

clean:
	rm -rf build-model build-survey build-sim-pfb build-sim-pfb-posctl .Xil
