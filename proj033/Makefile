# SPDX-License-Identifier: BSD-3-Clause
# proj033 — 2G-1-Fast にレーン FFT の 2-for-1（README）。模型（M-1・M-2）と部品の単体の sim（P-1〜）。P-4 で proj024-m0 の Makefile を写して後ろに足す
PYTHON   ?= python3
IVERILOG ?= iverilog
VVP      ?= vvp
SIMDIR   := build-sim

.PHONY: model sim-sep sim-all2

# M-1・M-2: 2-for-1 の式・鎖の全体・溜めの深さ・(B) の鎖と均しの待ち行列。成否は最後の「まとめ」の行で読む
model:
	@mkdir -p runs
	$(PYTHON) model/s2_model.py | tee runs/model.txt

# ---- P-1 s2_sep の単体の sim（成否は各ログの「結果:」の行で読む）----
# normal・gap は通るべき、addr・swap・pos（陽性対照）は落ちるべき。入力の hex は変種ごとのディレクトリに書く（proj028 F-5a）
sim-sep:
	@for v in normal gap addr swap pos; do \
	  o=$(SIMDIR)/sep_$$v; mkdir -p $$o; d=""; \
	  [ $$v = gap ] && d="-DTB_GAP"; [ $$v = addr ] && d="-DSEP_ADDR_ERR"; [ $$v = swap ] && d="-DSEP_SWAP_ERR"; [ $$v = pos ] && d="-DTB_SKIP"; \
	  ( $(PYTHON) sim/check_s2.py gen $$o > /dev/null && \
	    $(IVERILOG) -g2005 -Wall $$d -DOUT=\"$$o\" -o $$o/tb src/s2_sep.v sim/tb_s2_sep.v > $$o/iverilog.log 2>&1 && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_s2.py check $$o $$o/tb.log > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in normal gap addr swap pos; do printf '%-12s %s\n' "sep_$$v" "$$(grep '結果:' $(SIMDIR)/sep_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/sep_normal/check.log && grep -q '結果: 全部通過' $(SIMDIR)/sep_gap/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/sep_addr/check.log && grep -q '結果: 不合格' $(SIMDIR)/sep_swap/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/sep_pos/check.log \
	  && echo "sim-sep: 全部通過（陽性対照 3 本は落ちた）" || (echo "sim-sep: NG"; exit 1)

# ---- P-2・P-3 s2_sep → s2_chain（＋ g21_tw）→ s2_q をつないだ sim（6 フレーム、積分器の口を模型と bit 単位で）----
# normal（SHIFT 7）・sat（SHIFT 4、q の飽和あり）・gap は通るべき、d2（-DCHAIN_D2）・nornd（-DCHAIN_NORND）・bubble（-DQ_BUBBLE）は落ちるべき
ALL2_RTL := src/s2_sep.v src/common/cmul.v src/common/dft16f.v src/g21/g21_tw.v src/s2_chain.v src/s2_q.v sim/tb_s2_all.v
ALL2_V   := normal sat gap d2 nornd bubble
sim-all2:
	@for v in $(ALL2_V); do \
	  o=$(SIMDIR)/all2_$$v; mkdir -p $$o; d=""; sh=7; \
	  [ $$v = sat ] && sh=4; [ $$v = gap ] && d="-DTB_GAP"; [ $$v = d2 ] && d="-DCHAIN_D2"; [ $$v = nornd ] && d="-DCHAIN_NORND"; [ $$v = bubble ] && d="-DQ_BUBBLE"; \
	  ( $(PYTHON) sim/check_s2.py gen $$o > /dev/null && \
	    $(IVERILOG) -g2005 -Wall $$d -DSHIFT=$$sh -DOUT=\"$$o\" -DTA=\"src/g21/g21_tw_a.hex\" -DTB=\"src/g21/g21_tw_b.hex\" \
	      -o $$o/tb $(ALL2_RTL) > $$o/iverilog.log 2>&1 && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_s2.py all $$o $$o/tb.log $$sh $$v > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in $(ALL2_V); do printf '%-12s %s\n' "all2_$$v" "$$(grep '結果:' $(SIMDIR)/all2_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/all2_normal/check.log && grep -q '結果: 全部通過' $(SIMDIR)/all2_sat/check.log \
	  && grep -q '結果: 全部通過' $(SIMDIR)/all2_gap/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/all2_d2/check.log && grep -q '結果: 不合格' $(SIMDIR)/all2_nornd/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/all2_bubble/check.log \
	  && echo "sim-all2: 全部通過（陽性対照 3 本は落ちた）" || (echo "sim-all2: NG"; exit 1)
