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
# SIM_DDC_POSCTL=1: 陽性対照（RTL の NCO の番地を 1 つずらす）
SIM_DDC_POSCTL ?= 0
DDC_DIR       := build-sim-ddc$(if $(filter 1,$(SIM_DDC_POSCTL)),-posctl)
DDC_RTL       := src/nco_rom.v src/hb2.v src/pair2.v src/ddc_core.v
# SIM_WSPEC_POSCTL=1: 陽性対照（RTL の積分で初回のフレームでも読み値に足す）
SIM_WSPEC_POSCTL ?= 0
WSPEC_DIR     := build-sim-wspec$(if $(filter 1,$(SIM_WSPEC_POSCTL)),-posctl)
# 変種: 名前:NACC:NDUMP:SHIFT:GAP（GAP 0 = 途切れなし = 256 MHz 窓 / 3 / 32 = 8 MHz 窓の速さ）
WSPEC_VARS    ?= g0:4:4:4:0 g3:2:4:7:3 g32:1:3:4:32

export PART

.PHONY: model model-posctl model-sweep fixed fixed-posctl coef sim-pfb sim-ddc sim-win sim-all sim-pfb-p sim-ddc-p sim-wspec sim-wspec-p survey clean

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

# ddc_core の単体の sim（NCO → 半帯域 × NS）。入力は pfb_fixed の y。NS 1..6 × d 2 通り × 途切れ あり / なし
sim-ddc:
	mkdir -p $(DDC_DIR)
	$(PYTHON) sim/check_ddc.py gen $(DDC_DIR)
	$(IVERILOG) -g2005 -Isrc $(if $(filter 1,$(SIM_DDC_POSCTL)),-DDDC_POSCTL) -o $(DDC_DIR)/tb $(DDC_RTL) sim/tb_ddc.v
	NB=$$(wc -l < $(DDC_DIR)/y.txt); $(PYTHON) sim/check_ddc.py cases | while read ns dp; do for g in 0 1; do \
	  $(VVP) -n $(DDC_DIR)/tb +NS=$$ns +DPHI=$$dp +GAP=$$g +NBEAT=$$NB +IN=$(DDC_DIR)/y.txt +OUT=$(DDC_DIR)/z_ns$${ns}_d$${dp}_g$${g}.txt | grep '^ddc:' ; \
	done; done
	SIM_DDC_POSCTL=$(SIM_DDC_POSCTL) $(PYTHON) sim/check_ddc.py check $(DDC_DIR) | tee $(DDC_DIR)/check.log

# pfb_core → ddc_core をつないだ sim（つなぎ目の試験。6 通りの幅、1 本 1 分級）
sim-win:
	mkdir -p build-sim-win
	$(PYTHON) sim/check_win.py gen build-sim-win
	$(IVERILOG) -g2005 -Isrc -o build-sim-win/tb src/cmul.v src/dft16f.v src/pfb_core.v $(DDC_RTL) sim/tb_win.v
	$(PYTHON) sim/check_win.py cases | while read k ns dp; do \
	  $(VVP) -n build-sim-win/tb +K=$$k +NS=$$ns +DPHI=$$dp +GAP=1 +NSAMP=65536 +IN=build-sim-win/x.hex +OUT=build-sim-win/z_k$${k}_ns$${ns}.txt | grep '^win:' ; \
	done
	$(PYTHON) sim/check_win.py check build-sim-win | tee build-sim-win/check.log

# wspec_core の単体の sim（溜め → FFT のモデル → 電力 → 積分・スナップショット・帳簿）。4 層の判定（sim/check_wspec.py）
sim-wspec:
	mkdir -p $(WSPEC_DIR)
	$(PYTHON) sim/check_wspec.py gen $(WSPEC_DIR)
	$(IVERILOG) -g2005 -Isrc $(if $(filter 1,$(SIM_WSPEC_POSCTL)),-DWSPEC_POSCTL) -o $(WSPEC_DIR)/tb src/wspec_core.v sim/win_fft_model.v sim/tb_wspec.v
	rm -f $(WSPEC_DIR)/check.log
	for v in $(WSPEC_VARS); do \
	  nm=$${v%%:*}; r=$${v#*:}; na=$${r%%:*}; r=$${r#*:}; nd=$${r%%:*}; r=$${r#*:}; sh=$${r%%:*}; gp=$${r#*:}; \
	  mkdir -p $(WSPEC_DIR)/$$nm; \
	  $(VVP) -n $(WSPEC_DIR)/tb +NACC=$$na +NDUMP=$$nd +SHIFT=$$sh +GAP=$$gp +IN=$(WSPEC_DIR)/z.txt +DIR=$(WSPEC_DIR)/$$nm | grep '^wspec:' ; \
	  echo "== $$nm" >> $(WSPEC_DIR)/check.log; \
	  SIM_WSPEC_POSCTL=$(SIM_WSPEC_POSCTL) $(PYTHON) sim/check_wspec.py check $(WSPEC_DIR)/$$nm $$na $$nd $$sh >> $(WSPEC_DIR)/check.log; \
	done
	@cat $(WSPEC_DIR)/check.log | grep -v "  OK"
sim-wspec-p:
	$(MAKE) --no-print-directory sim-wspec SIM_WSPEC_POSCTL=1 WSPEC_VARS=g0:4:4:4:0

# sim を全部並べる（iverilog は 1 本 1 コア）。成否は各 check.log の「結果: 全部通過」で読む（make の成功を信用しない）
sim-all:
	$(MAKE) --no-print-directory -j7 sim-pfb sim-ddc sim-win sim-wspec sim-pfb-p sim-ddc-p sim-wspec-p
	@grep -H "結果" build-sim-*/check.log
sim-pfb-p:
	$(MAKE) --no-print-directory sim-pfb SIM_PFB_POSCTL=1
sim-ddc-p:
	$(MAKE) --no-print-directory sim-ddc SIM_DDC_POSCTL=1

# FFT IP 単体の資源（ライセンスが要る。並列で 10〜20 分の見込み）。結果は build-survey/survey.txt
survey:
	mkdir -p build-survey
	$(VIVADO) -mode batch -nojournal -log build-survey/vivado.log -source tools/ip_survey.tcl -tclargs $(JOBS)

clean:
	rm -rf build-model build-survey build-sim-* .Xil
