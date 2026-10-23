# SPDX-License-Identifier: BSD-3-Clause
# proj027 — 2G-4 の RTL。段階 A: 模型（`make model`）・ROM の中身（`make gen`）・部品の単体の sim（手順 1a〜1d、`make sim-all`）
# proj025 の段階 A の Makefile（fcea4f1）を写し、名前を g24 に・1d の陽性対照 NORND を RND1 に。Vivado のターゲットは段階 B で足す
PYTHON        ?= python3
IVERILOG      ?= iverilog
VVP           ?= vvp

.PHONY: coef-ooc wide-hier model gen sim-all sim-g24c sim-g24t sim-g24p sim-g24ch clean

# 模型（numpy だけ）。M-a〜d。成否は最後の「まとめ」の行で読む（make の成功を信用しない）
model:
	mkdir -p runs
	$(PYTHON) model/g24_model.py | tee runs/model.log

# 2G-2 の ROM の中身（model/g24_fixed.py の定義）を build-gen/ に書き、読み返して模型と照らす。src/g24/ に写したものをコミットする
gen:
	$(PYTHON) tools/gen_g24_tables.py build-gen

# ---- RTL の単体の sim（手順 1。成否は各ログの「結果:」の行で読む）----
SIMDIR := build-sim
# 1a. g24_coef（係数の補間）。ふつうと陽性対照（-DCOEF_FRAC_ERR、落ちるべき）
sim-g24c:
	@for v in normal err; do \
	  o=$(SIMDIR)/g24c_$$v; mkdir -p $$o; d=""; [ $$v = err ] && d="-DCOEF_FRAC_ERR"; \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g24/g24_coef_lo.hex\" -DHI=\"src/g24/g24_coef_hi.hex\" \
	    -o $$o/tb src/g24/g24_coef.v sim/tb_g24_coef.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g24.py coef $$o $$o/tb.log > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g24c_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g24c_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g24c_err/check.log \
	  && echo "sim-g24c: 全部通過（陽性対照は落ちた）" || (echo "sim-g24c: NG"; exit 1)

# 1b. g24_tw（ひねり係数の積）。ふつうと陽性対照（-DTW_HI_ERR、落ちるべき）
sim-g24t:
	@for v in normal err; do \
	  o=$(SIMDIR)/g24t_$$v; mkdir -p $$o; d=""; [ $$v = err ] && d="-DTW_HI_ERR"; \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DTA=\"src/g24/g24_tw_a.hex\" -DTB=\"src/g24/g24_tw_b.hex\" \
	    -o $$o/tb src/common/cmul.v src/g24/g24_tw.v sim/tb_g24_tw.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g24.py tw $$o $$o/tb.log > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g24t_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g24t_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g24t_err/check.log \
	  && echo "sim-g24t: 全部通過（陽性対照は落ちた）" || (echo "sim-g24t: NG"; exit 1)

# 1c. g24_pfb（PFB）。ふつう・陽性対照 2 本（-DPFB_DLY_ERR: 係数が 1 ビートずれる / -DPFB_NOMASK: 起動の直後も履歴を使う。どちらも落ちるべき）
G24P_RTL := src/g24/g24_coef.v src/g24/g24_pfb_core.v src/g24/g24_pfb.v sim/tb_g24_pfb.v
sim-g24p:
	@for v in normal dlyerr nomask; do \
	  o=$(SIMDIR)/g24p_$$v; mkdir -p $$o; d=""; \
	  [ $$v = dlyerr ] && d="-DPFB_DLY_ERR"; [ $$v = nomask ] && d="-DPFB_NOMASK"; \
	  $(PYTHON) sim/check_g24.py pfb-gen $$o > /dev/null && \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g24/g24_coef_lo.hex\" -DHI=\"src/g24/g24_coef_hi.hex\" \
	    -o $$o/tb $(G24P_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g24.py pfb $$o $$o/tb.log > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g24p_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g24p_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g24p_dlyerr/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/g24p_nomask/check.log \
	  && echo "sim-g24p: 全部通過（陽性対照 2 本は落ちた）" || (echo "sim-g24p: NG"; exit 1)

# 1d. g24_tw ＋ g24_chain（鎖）。ふつう（SHIFT 7）・飽和（SHIFT 4）・陽性対照 2 本（-DCHAIN_TW_LAT_ERR・-DCHAIN_RND1、落ちるべき）
G24CH_RTL := src/common/cmul.v src/common/dft16.v src/g24/g24_tw.v src/g24/g24_chain.v sim/tb_g24_chain.v
sim-g24ch:
	@o0=$(SIMDIR)/g24ch_in; mkdir -p $$o0; $(PYTHON) sim/check_g24.py chain-gen $$o0 > /dev/null; \
	for v in normal sat twlat rnd1; do \
	  o=$(SIMDIR)/g24ch_$$v; mkdir -p $$o; cp $$o0/yre.hex $$o0/yim.hex $$o/; d=""; sh=7; \
	  [ $$v = sat ] && sh=4; [ $$v = twlat ] && d="-DCHAIN_TW_LAT_ERR"; [ $$v = rnd1 ] && d="-DCHAIN_RND1"; \
	  $(IVERILOG) -g2005 $$d -DSHIFT=$$sh -DOUT=\"$$o\" -DTA=\"src/g24/g24_tw_a.hex\" -DTB=\"src/g24/g24_tw_b.hex\" \
	    -o $$o/tb $(G24CH_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g24.py chain $$o $$o/tb.log $$sh > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g24ch_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g24ch_normal/check.log && grep -q '結果: 全部通過' $(SIMDIR)/g24ch_sat/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/g24ch_twlat/check.log && grep -q '結果: 不合格' $(SIMDIR)/g24ch_rnd1/check.log \
	  && echo "sim-g24ch: 全部通過（陽性対照 2 本は落ちた）" || (echo "sim-g24ch: NG"; exit 1)

# 1a〜1d をまとめて（iverilog は 1 本 1 コアなので並べて回す）。成否は各ターゲットの最後の行で読む
sim-all:
	@$(MAKE) --no-print-directory -j4 -O sim-g24c sim-g24t sim-g24p sim-g24ch

clean:
	rm -rf build build-* .Xil *.jou *.log runs

# ---- F-2 の測り: g24_coef を 1 個だけ OOC で合成（Vivado。JOBS は最大 8、2026-10-23 西村さん）----
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado
JOBS          ?= 8
RULER_REV     := f706170
coef-ooc:
	mkdir -p build-ooc/ruler
	for f in g22_coef.v g22_coef_lo.hex g22_coef_hi.hex; do git --no-optional-locks show $(RULER_REV):proj025/src/g22/$$f > build-ooc/ruler/$$f; done
	$(VIVADO) -mode batch -nojournal -log build-ooc/vivado.log -source tools/coef_ooc.tcl -tclargs $(JOBS) > /dev/null 2>&1; true
	@tail -n 5 build-ooc/ooc.txt 2>/dev/null || echo "ooc.txt が無い（build-ooc/vivado.log を読む）"

# ---- Wide の束ね・切り出しの LUT: proj023 ビルド 11 の配線済みチェックポイントを読むだけで開き、階層を深くして数える ----
wide-hier:
	mkdir -p build-wide
	$(VIVADO) -mode batch -nojournal -log build-wide/vivado.log -source tools/wide_hier.tcl > /dev/null 2>&1; true
	@grep -E 'CLB LUTs:|NG|結果:' build-wide/vivado.log | grep -v '^#' | tail -n 6
