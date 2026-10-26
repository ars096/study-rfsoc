# proj030 — レーン FFT の 2-for-1（実のレーン 2 本を複素の IP 1 個に）。段階 M: 模型（`make model`）
PYTHON ?= python3
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado

.PHONY: model sim-sep ooc-sep

# M-1 の模型。成否は最後の「まとめ」の行で読む
model:
	@mkdir -p runs
	$(PYTHON) model/s2_model.py | tee runs/model.txt

# ---- P-1 s2_sep の単体の sim（成否は各ログの「結果:」の行で読む）----
IVERILOG ?= iverilog
VVP      ?= vvp
SIMDIR   := build-sim
# normal・gap は通るべき、addr・swap・pos（陽性対照）は落ちるべき。入力の hex は変種ごとのディレクトリに書く（proj028 F-5a）
sim-sep:
	@for v in normal gap addr swap pos; do \
	  o=$(SIMDIR)/sep_$$v; mkdir -p $$o; d=""; \
	  [ $$v = gap ] && d="-DTB_GAP"; [ $$v = addr ] && d="-DSEP_ADDR_ERR"; [ $$v = swap ] && d="-DSEP_SWAP_ERR"; [ $$v = pos ] && d="-DTB_SKIP"; \
	  ( $(PYTHON) sim/check_s2.py gen $$o > /dev/null && \
	    $(IVERILOG) -g2005 -Wall $$d -DOUT=\"$$o\" -o $$o/tb src/s2_sep.v sim/tb_s2_sep.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_s2.py check $$o $$o/tb.log > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in normal gap addr swap pos; do printf '%-12s %s\n' "sep_$$v" "$$(grep '結果:' $(SIMDIR)/sep_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/sep_normal/check.log && grep -q '結果: 全部通過' $(SIMDIR)/sep_gap/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/sep_addr/check.log && grep -q '結果: 不合格' $(SIMDIR)/sep_swap/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/sep_pos/check.log \
	  && echo "sim-sep: 全部通過（陽性対照 3 本は落ちた）" || (echo "sim-sep: NG"; exit 1)

# ---- S-1 s2_sep を 1 個 OOC で合成（`-1`・256 MHz）。結果は build-ooc/ooc-sep.txt。Synth 8-3848（ドライバの無いネット）があれば NG ----
ooc-sep:
	@mkdir -p build-ooc
	$(VIVADO) -mode batch -nojournal -log build-ooc/vivado.log -source tools/ooc_rtl.tcl -tclargs s2_sep 3.906 clk src/s2_sep.v > /dev/null 2>&1; \
	  cd build-ooc && grep '^OOC ' vivado.log | tee ooc-sep.txt; n=$$(grep -c 'Synth 8-3848' vivado.log); echo "Synth 8-3848: $$n" | tee -a ooc-sep.txt; \
	  grep -c 'CRITICAL WARNING' vivado.log | sed 's/^/CRITICAL WARNING: /' | tee -a ooc-sep.txt; [ $$n -eq 0 ]
