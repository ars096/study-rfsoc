# SPDX-License-Identifier: BSD-3-Clause
# proj024 — 2G の模型と資源の見積もり。RTL は無いので build.tcl は無い（RTL は SAM45-Wide を YATSUGATAKE に入れた後の proj で）
#
# Vivado のインストール先（survey だけが使う）。settings64.sh を .bashrc で source しないこと（VERSIONS.md）
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado
PYTHON        ?= python3
# survey の OOC 合成を同時に走らせる数（9 個）
JOBS ?= 9

.PHONY: model estimate survey clean

# 模型（numpy だけ）。M-1〜M-6。成否は最後の「まとめ」の行で読む（make の成功を信用しない）
model:
	mkdir -p runs
	$(PYTHON) model/g2_model.py all | tee runs/model.log

# 資源の見積もり（E-1）。レーン FFT の数字は既定が外挿の仮の値。S-1 の後は EST_ARGS="--fft '4096,rev,…' …" で置き換える
estimate:
	mkdir -p runs
	$(PYTHON) tools/estimate.py $(EST_ARGS) | tee runs/estimate.log

# Vivado サーバ: レーン FFT の OOC 合成（S-1）。ライセンスが要る。結果は build-survey/survey.txt
# proj023 のビルドと重ならないときに回す（同じサーバ。壊れはしないが互いに遅くなる）
survey:
	mkdir -p build-survey
	$(VIVADO) -mode batch -nojournal -log build-survey/vivado.log -source tools/ip_survey.tcl -tclargs $(JOBS)

clean:
	rm -rf build-survey .Xil *.jou *.log
