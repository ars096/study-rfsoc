# SPDX-License-Identifier: BSD-3-Clause
# proj025 — 2G-2 の RTL。段階 A: 模型（`make model`）・ROM の中身（`make gen`）・部品の単体の sim（手順 1a〜1d、`make sim-all`）
# proj024 の Makefile の model・gen・sim-g21* を写し、名前を g22 に。Vivado のターゲットは段階 B で足す
PYTHON        ?= python3
IVERILOG      ?= iverilog
VVP           ?= vvp

.PHONY: model gen sim-all sim-g22c sim-g22t sim-g22p sim-g22ch clean

# 模型（numpy だけ）。M-a〜d。成否は最後の「まとめ」の行で読む（make の成功を信用しない）
model:
	mkdir -p runs
	$(PYTHON) model/g22_model.py | tee runs/model.log

# 2G-2 の ROM の中身（model/g22_fixed.py の定義）を build-gen/ に書き、読み返して模型と照らす。src/g22/ に写したものをコミットする
gen:
	$(PYTHON) tools/gen_g22_tables.py build-gen

# ---- RTL の単体の sim（手順 1。成否は各ログの「結果:」の行で読む）----
SIMDIR := build-sim
# 1a. g22_coef（係数の補間）。ふつうと陽性対照（-DCOEF_FRAC_ERR、落ちるべき）
sim-g22c:
	@for v in normal err; do \
	  o=$(SIMDIR)/g22c_$$v; mkdir -p $$o; d=""; [ $$v = err ] && d="-DCOEF_FRAC_ERR"; \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g22/g22_coef_lo.hex\" -DHI=\"src/g22/g22_coef_hi.hex\" \
	    -o $$o/tb src/g22/g22_coef.v sim/tb_g22_coef.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g22.py coef $$o $$o/tb.log > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g22c_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g22c_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g22c_err/check.log \
	  && echo "sim-g22c: 全部通過（陽性対照は落ちた）" || (echo "sim-g22c: NG"; exit 1)

# 1b. g22_tw（ひねり係数の積）。ふつうと陽性対照（-DTW_HI_ERR、落ちるべき）
sim-g22t:
	@for v in normal err; do \
	  o=$(SIMDIR)/g22t_$$v; mkdir -p $$o; d=""; [ $$v = err ] && d="-DTW_HI_ERR"; \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DTA=\"src/g22/g22_tw_a.hex\" -DTB=\"src/g22/g22_tw_b.hex\" \
	    -o $$o/tb src/common/cmul.v src/g22/g22_tw.v sim/tb_g22_tw.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g22.py tw $$o $$o/tb.log > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g22t_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g22t_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g22t_err/check.log \
	  && echo "sim-g22t: 全部通過（陽性対照は落ちた）" || (echo "sim-g22t: NG"; exit 1)

# 1c. g22_pfb（PFB）。ふつう・陽性対照 2 本（-DPFB_DLY_ERR: 係数が 1 ビートずれる / -DPFB_NOMASK: 起動の直後も履歴を使う。どちらも落ちるべき）
G22P_RTL := src/g22/g22_coef.v src/g22/g22_pfb_core.v src/g22/g22_pfb.v sim/tb_g22_pfb.v
sim-g22p:
	@for v in normal dlyerr nomask; do \
	  o=$(SIMDIR)/g22p_$$v; mkdir -p $$o; d=""; \
	  [ $$v = dlyerr ] && d="-DPFB_DLY_ERR"; [ $$v = nomask ] && d="-DPFB_NOMASK"; \
	  $(PYTHON) sim/check_g22.py pfb-gen $$o > /dev/null && \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g22/g22_coef_lo.hex\" -DHI=\"src/g22/g22_coef_hi.hex\" \
	    -o $$o/tb $(G22P_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g22.py pfb $$o $$o/tb.log > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g22p_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g22p_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g22p_dlyerr/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/g22p_nomask/check.log \
	  && echo "sim-g22p: 全部通過（陽性対照 2 本は落ちた）" || (echo "sim-g22p: NG"; exit 1)

# 1d. g22_tw ＋ g22_chain（鎖）。ふつう（SHIFT 7）・飽和（SHIFT 4）・陽性対照 2 本（-DCHAIN_TW_LAT_ERR・-DCHAIN_NORND、落ちるべき）
G22CH_RTL := src/common/cmul.v src/common/dft16.v src/g22/g22_tw.v src/g22/g22_chain.v sim/tb_g22_chain.v
sim-g22ch:
	@o0=$(SIMDIR)/g22ch_in; mkdir -p $$o0; $(PYTHON) sim/check_g22.py chain-gen $$o0 > /dev/null; \
	for v in normal sat twlat nornd; do \
	  o=$(SIMDIR)/g22ch_$$v; mkdir -p $$o; cp $$o0/yre.hex $$o0/yim.hex $$o/; d=""; sh=7; \
	  [ $$v = sat ] && sh=4; [ $$v = twlat ] && d="-DCHAIN_TW_LAT_ERR"; [ $$v = nornd ] && d="-DCHAIN_NORND"; \
	  $(IVERILOG) -g2005 $$d -DSHIFT=$$sh -DOUT=\"$$o\" -DTA=\"src/g22/g22_tw_a.hex\" -DTB=\"src/g22/g22_tw_b.hex\" \
	    -o $$o/tb $(G22CH_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g22.py chain $$o $$o/tb.log $$sh > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g22ch_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g22ch_normal/check.log && grep -q '結果: 全部通過' $(SIMDIR)/g22ch_sat/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/g22ch_twlat/check.log && grep -q '結果: 不合格' $(SIMDIR)/g22ch_nornd/check.log \
	  && echo "sim-g22ch: 全部通過（陽性対照 2 本は落ちた）" || (echo "sim-g22ch: NG"; exit 1)

# 1a〜1d をまとめて（iverilog は 1 本 1 コアなので並べて回す）。成否は各ターゲットの最後の行で読む
sim-all:
	@$(MAKE) --no-print-directory -j4 -O sim-g22c sim-g22t sim-g22p sim-g22ch

clean:
	rm -rf build build-* .Xil *.jou *.log runs
