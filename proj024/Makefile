# SPDX-License-Identifier: BSD-3-Clause
# proj024 — 2G の模型と資源の見積もり。RTL は無いので build.tcl は無い（RTL は SAM45-Wide を YATSUGATAKE に入れた後の proj で）
#
# Vivado のインストール先（survey だけが使う）。settings64.sh を .bashrc で source しないこと（VERSIONS.md）
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado
PYTHON        ?= python3
IVERILOG      ?= iverilog
VVP           ?= vvp
# survey の OOC 合成を同時に走らせる数（9 個）
JOBS ?= 9

.PHONY: model estimate survey s2 gen sim-g21c sim-g21t sim-g21p clean

# 模型（numpy だけ）。M-1〜M-6。成否は最後の「まとめ」の行で読む（make の成功を信用しない）
model:
	mkdir -p runs
	$(PYTHON) model/g2_model.py all | tee runs/model.log

# 資源の見積もり（E-1）。レーン FFT の数字は既定が外挿の仮の値。S-1 の後は EST_ARGS="--fft '4096,rev,…' …" で置き換える
estimate:
	mkdir -p runs
	$(PYTHON) tools/estimate.py $(EST_ARGS) | tee runs/estimate.log

# Vivado サーバ: レーン FFT 1 個の OOC の配置配線（S-2）。-1・256 MHz で閉じるか。結果は build-s2/s2.txt（数十分〜1 時間）
# proj023 のビルドと重ならないときに回す
s2:
	mkdir -p build-s2
	$(VIVADO) -mode batch -nojournal -log build-s2/vivado.log -source tools/ip_impl.tcl -tclargs 4

# 2G-1 の ROM の中身（model/g21_fixed.py の定義）を build-gen/ に書き、読み返して模型と照らす（M-8 の続き）
gen:
	$(PYTHON) tools/gen_g21_tables.py build-gen

# Vivado サーバ: レーン FFT の OOC 合成（S-1）。ライセンスが要る。結果は build-survey/survey.txt
# proj023 のビルドと重ならないときに回す（同じサーバ。壊れはしないが互いに遅くなる）
survey:
	mkdir -p build-survey
	$(VIVADO) -mode batch -nojournal -log build-survey/vivado.log -source tools/ip_survey.tcl -tclargs $(JOBS)

# ---- RTL の単体の sim（手順 1。成否は各ログの「結果:」の行で読む）----
SIMDIR := build-sim
# 1a. g21_coef（係数の補間）。ふつうと陽性対照（-DCOEF_FRAC_ERR、落ちるべき）
sim-g21c:
	@for v in normal err; do \
	  o=$(SIMDIR)/g21c_$$v; mkdir -p $$o; d=""; [ $$v = err ] && d="-DCOEF_FRAC_ERR"; \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g21/g21_coef_lo.hex\" -DHI=\"src/g21/g21_coef_hi.hex\" \
	    -o $$o/tb src/g21/g21_coef.v sim/tb_g21_coef.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g21.py coef $$o $$o/tb.log > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g21c_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g21c_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g21c_err/check.log \
	  && echo "sim-g21c: 全部通過（陽性対照は落ちた）" || (echo "sim-g21c: NG"; exit 1)

# 1b. g21_tw（ひねり係数の積）。ふつうと陽性対照（-DTW_HI_ERR、落ちるべき）
sim-g21t:
	@for v in normal err; do \
	  o=$(SIMDIR)/g21t_$$v; mkdir -p $$o; d=""; [ $$v = err ] && d="-DTW_HI_ERR"; \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DTA=\"src/g21/g21_tw_a.hex\" -DTB=\"src/g21/g21_tw_b.hex\" \
	    -o $$o/tb src/common/cmul.v src/g21/g21_tw.v sim/tb_g21_tw.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g21.py tw $$o $$o/tb.log > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g21t_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g21t_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g21t_err/check.log \
	  && echo "sim-g21t: 全部通過（陽性対照は落ちた）" || (echo "sim-g21t: NG"; exit 1)

# 1c. g21_pfb（PFB）。ふつう・陽性対照 2 本（-DPFB_DLY_ERR: 係数が 1 ビートずれる / -DPFB_NOMASK: 起動の直後も履歴を使う。どちらも落ちるべき）
G21P_RTL := src/g21/g21_coef.v src/g21/g21_pfb_core.v src/g21/g21_pfb.v sim/tb_g21_pfb.v
sim-g21p:
	@for v in normal dlyerr nomask; do \
	  o=$(SIMDIR)/g21p_$$v; mkdir -p $$o; d=""; \
	  [ $$v = dlyerr ] && d="-DPFB_DLY_ERR"; [ $$v = nomask ] && d="-DPFB_NOMASK"; \
	  $(PYTHON) sim/check_g21.py pfb-gen $$o > /dev/null && \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g21/g21_coef_lo.hex\" -DHI=\"src/g21/g21_coef_hi.hex\" \
	    -o $$o/tb $(G21P_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g21.py pfb $$o $$o/tb.log > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g21p_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g21p_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g21p_dlyerr/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/g21p_nomask/check.log \
	  && echo "sim-g21p: 全部通過（陽性対照 2 本は落ちた）" || (echo "sim-g21p: NG"; exit 1)

clean:
	rm -rf build-survey build-s2 build-gen build-sim .Xil *.jou *.log
