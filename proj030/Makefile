# proj030 — レーン FFT の 2-for-1（実のレーン 2 本を複素の IP 1 個に）。段階 M: 模型（`make model`）
PYTHON ?= python3
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado

.PHONY: model sim-sep sim-all2 ooc-sep

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

# ---- P-2・P-3 s2_sep → s2_chain（＋ g24_tw）→ s2_q をつないだ sim（6 フレーム、積分器の口を模型と bit 単位で）----
# normal（SHIFT 7）・sat（SHIFT 4、q の飽和あり）・gap は通るべき、sh18（-DCHAIN_SH18）・bubble（-DQ_BUBBLE）は落ちるべき
ALL2_RTL := src/s2_sep.v src/common/cmul.v src/common/dft16f.v src/g24/g24_tw.v src/s2_chain.v src/s2_q.v sim/tb_s2_all.v
sim-all2:
	@for v in normal sat gap sh18 bubble; do \
	  o=$(SIMDIR)/all2_$$v; mkdir -p $$o; d=""; sh=7; \
	  [ $$v = sat ] && sh=4; [ $$v = gap ] && d="-DTB_GAP"; [ $$v = sh18 ] && d="-DCHAIN_SH18"; [ $$v = bubble ] && d="-DQ_BUBBLE"; \
	  ( $(PYTHON) sim/check_s2.py gen $$o > /dev/null && \
	    $(IVERILOG) -g2005 -Wall $$d -DSHIFT=$$sh -DOUT=\"$$o\" -DTA=\"src/g24/g24_tw_a.hex\" -DTB=\"src/g24/g24_tw_b.hex\" \
	      -o $$o/tb $(ALL2_RTL) > $$o/iverilog.log 2>&1 && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_s2.py all $$o $$o/tb.log $$sh $$v > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in normal sat gap sh18 bubble; do printf '%-12s %s\n' "all2_$$v" "$$(grep '結果:' $(SIMDIR)/all2_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/all2_normal/check.log && grep -q '結果: 全部通過' $(SIMDIR)/all2_sat/check.log \
	  && grep -q '結果: 全部通過' $(SIMDIR)/all2_gap/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/all2_sh18/check.log && grep -q '結果: 不合格' $(SIMDIR)/all2_bubble/check.log \
	  && echo "sim-all2: 全部通過（陽性対照 2 本は落ちた）" || (echo "sim-all2: NG"; exit 1)
