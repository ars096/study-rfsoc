# SPDX-License-Identifier: BSD-3-Clause
# proj022 — SAM45-Wide の模型と資源の見積もり。RTL はまだ無いので build.tcl は無い（RTL は proj021 の後の proj で）
#
# Vivado のインストール先（survey だけが使う）。settings64.sh を .bashrc で source しないこと（VERSIONS.md）
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado
PYTHON        ?= python3
# survey の OOC 合成を同時に走らせる数（6 個しかないので 6 で足りる）
JOBS ?= 6

.PHONY: model estimate survey survey-s2 clean

# 模型（numpy だけ）。M-1〜M-6。成否は最後の「まとめ」の行で読む（make の成功を信用しない）
model:
	mkdir -p runs
	$(PYTHON) model/wide_model.py all | tee runs/model.log

# 資源の見積もり（E-1）。レーン FFT の数字は既定が proj014 の survey、S-1 の後は引数で置き換える
estimate:
	mkdir -p runs
	$(PYTHON) tools/estimate.py $(EST_ARGS) | tee runs/estimate.log

# Vivado サーバ: レーン FFT の OOC 合成（S-1）。ライセンスが要る。10〜20 分の見込み。結果は build-survey/survey.txt
survey:
	mkdir -p build-survey
	$(VIVADO) -mode batch -nojournal -log build-survey/vivado.log -source tools/ip_survey.tcl -tclargs $(JOBS)

# S-2: レーン FFT の中の記憶を LUT から BRAM へ移す段数を振る（入力 15 bit）。結果は build-survey-s2/survey.txt（S-1 は上書きしない）
survey-s2:
	mkdir -p build-survey-s2
	SURVEY=s2 $(VIVADO) -mode batch -nojournal -log build-survey-s2/vivado.log -source tools/ip_survey.tcl -tclargs $(JOBS)

clean:
	rm -rf build-survey build-survey-s2 .Xil *.jou *.log
