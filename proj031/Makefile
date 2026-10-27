# SPDX-License-Identifier: BSD-3-Clause
# proj030 — レーン FFT の 2-for-1。proj027（2G-4）の Makefile（commit fe49b9d）を写し、proj030 の段（模型・P-1〜P-3 の sim・OOC）を後ろに足した。
# proj027 の `model`（g24_model.py の M-a〜d）は `model-g24` に名前を替えた。2G-4 の .bit は `make build`（2-for-1 を組んだ g24_spec）
PYTHON        ?= python3
IVERILOG      ?= iverilog
VVP           ?= vvp

.PHONY: build post coef-ooc wide-hier model-g24 gen sim-all sim-g24c sim-g24t sim-g24p sim-g24ch sim-lane sim-g24a sim-g24s sim-recfr sim-g24core sim-g24s45 clean

# 模型（numpy だけ）。M-a〜d。成否は最後の「まとめ」の行で読む（make の成功を信用しない）
model-g24:
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

# ---- 段階 B: 2a〜2e・4d-2 の sim（proj025-m0 の Makefile から写した。名前は g24 に。2e-2 は 4 コア版 sim-g24x4 を作った）----
# 2a. レーン FFT 4096 点の行動模型（sim/lane_fft_g24_model.v）の単体。tready の下げなし・あり（-DFFT_STALL_AT=3）
sim-lane:
	@for v in plain stall; do \
	  o=$(SIMDIR)/lane_$$v; mkdir -p $$o; d=""; st=0; [ $$v = stall ] && d="-DFFT_STALL_AT=3" && st=1; \
	  $(PYTHON) sim/check_g24.py lane-gen $$o && \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -o $$o/tb sim/lane_fft_g24_model.v sim/tb_lane_g24.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g24.py lane $$o $$o/tb.log $$st > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "lane_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/lane_plain/check.log && grep -q '結果: 全部通過' $(SIMDIR)/lane_stall/check.log \
	  && echo "sim-lane: 全部通過" || (echo "sim-lane: NG"; exit 1)

# 2b. g24_acc（FULL の積分器）。ふつうと陽性対照（-DACC_FIRST_ERR: ダンプの最初で消さない。面 0 の 2 回目のダンプ C が落ちるべき）
sim-g24a:
	@for v in normal err; do \
	  o=$(SIMDIR)/g24a_$$v; mkdir -p $$o; d=""; [ $$v = err ] && d="-DACC_FIRST_ERR"; \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -o $$o/tb src/g24/g24_acc.v sim/tb_g24_acc.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g24.py acc $$o > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g24a_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g24a_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g24a_err/check.log \
	  && echo "sim-g24a: 全部通過（陽性対照は落ちた）" || (echo "sim-g24a: NG"; exit 1)

# 2c. g24_spec（分光の本体）。x.hex は無ければ作る（proj027: 毎回作り直すと、make -j で並べた 2d・2e が書きかけの x.hex を読んで X が混ざった）。ふつう（流し始めの tready の下げあり）と陽性対照（-DIPQ_POSCTL: 待ち行列なし。落ちるべき）
G24S_RTL := src/common/cmul.v src/common/dft16f.v src/g24/g24_coef.v src/g24/g24_pfb_core.v src/g24/g24_pfb.v \
            src/g24/g24_tw.v src/s2_sep.v src/s2_chain.v src/s2_q.v src/g24/g24_acc.v src/g24/g24_spec.v sim/lane_fft_g24_model.v sim/tb_g24_spec.v
sim-g24s:
	@o0=$(SIMDIR)/g24s_in; mkdir -p $$o0; [ -f $$o0/x.hex ] || $(PYTHON) sim/check_g24.py spec-gen $$o0; \
	for v in normal ipq; do \
	  o=$(SIMDIR)/g24s_$$v; mkdir -p $$o; ln -sf ../g24s_in/x.hex $$o/x.hex; d="-DFFT_STALL_AT=3"; \
	  [ $$v = ipq ] && d="$$d -DIPQ_POSCTL"; \
	  $(IVERILOG) -g2005 $$d -DSHIFT=4 -DOUT=\"$$o\" -DLO=\"src/g24/g24_coef_lo.hex\" -DHI=\"src/g24/g24_coef_hi.hex\" \
	    -DTA=\"src/g24/g24_tw_a.hex\" -DTB=\"src/g24/g24_tw_b.hex\" -o $$o/tb $(G24S_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g24.py spec $$o $$o/tb.log 4 > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g24s_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g24s_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g24s_ipq/check.log \
	  && echo "sim-g24s: 全部通過（陽性対照は落ちた）" || (echo "sim-g24s: NG"; exit 1)

# 2d. rec_fr に NCH を足した版が NCH 4096 で 567fda2 の版（sim/rec_fr_ref.v）と同じ振る舞いか（全部の出口をクロックごとに比べる）。
#     陽性対照（-DEQ_POSCTL: 新しい版を NCH 2048 に。違いが出るべき）。2 本を同時に回す
sim-recfr:
	@for v in normal posctl; do \
	  o=$(SIMDIR)/recfr_$$v; mkdir -p $$o; d=""; [ $$v = posctl ] && d="-DEQ_POSCTL"; \
	  ( $(IVERILOG) -g2005 $$d -o $$o/tb sim/rec_fr_ref.v src/common/rec_fr.v sim/tb_recfr_eq.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1 ) & \
	done; wait; \
	for v in normal posctl; do printf '%-14s %s\n' "recfr_$$v" "$$(grep '結果:' $(SIMDIR)/recfr_$$v/tb.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/recfr_normal/tb.log && grep -q '結果: 不合格' $(SIMDIR)/recfr_posctl/tb.log \
	  && echo "sim-recfr: 全部通過（陽性対照は落ちた）" || (echo "sim-recfr: NG"; exit 1)

# 2d. g24_core（FULL の流れのブロック・SPEC のレコード 256 KiB・FULL の TP・SRC）。入力は 2c と同じ x.hex（sim-g24s の g24s_in を作る）。
#     ふつう・陽性対照 2 本（-DG24C_POSCTL: 積分器の読みの口に 1 段多い / -DG24C_TP_POSCTL: TP の F0 の × 8 を忘れる）。
#     G24CORE_V で回す変種を選べる（proj025 では 3 本を同時に 20 分前後。2G-4 のレコードは 256 KiB で半分）
G24CORE_RTL := src/common/cmul.v src/common/dft16f.v src/s2_sep.v src/s2_chain.v src/s2_q.v src/common/adc_ev.v src/common/tp_core.v src/common/rec_fr.v src/common/rec_arb.v \
               src/g24/g24_coef.v src/g24/g24_pfb_core.v src/g24/g24_pfb.v src/g24/g24_tw.v src/g24/g24_acc.v \
               src/g24/g24_spec.v src/g24/g24_core.v sim/lane_fft_g24_model.v sim/tb_g24_core.v
G24CORE_V ?= normal posctl tp
sim-g24core:
	@o0=$(SIMDIR)/g24s_in; mkdir -p $$o0; [ -f $$o0/x.hex ] || $(PYTHON) sim/check_g24.py spec-gen $$o0; \
	for v in $(G24CORE_V); do \
	  o=$(SIMDIR)/g24core_$$v; mkdir -p $$o; ln -sf ../g24s_in/x.hex $$o/x.hex; d="-DFFT_STALL_AT=3"; \
	  [ $$v = posctl ] && d="$$d -DG24C_POSCTL"; [ $$v = tp ] && d="$$d -DG24C_TP_POSCTL"; \
	  ( $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g24/g24_coef_lo.hex\" -DHI=\"src/g24/g24_coef_hi.hex\" \
	      -DTA=\"src/g24/g24_tw_a.hex\" -DTB=\"src/g24/g24_tw_b.hex\" -o $$o/tb $(G24CORE_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_g24.py core $$o $$o/tb.log > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in $(G24CORE_V); do printf '%-14s %s\n' "g24core_$$v" "$$(grep '結果:' $(SIMDIR)/g24core_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/g24core_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g24core_posctl/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/g24core_tp/check.log \
	  && echo "sim-g24core: 全部通過（陽性対照 2 本は落ちた）" || (echo "sim-g24core: NG"; exit 1)

# 2e. g24_s45_core（コアの共通・FULL（s 0）・RAW（s 1）・axis_sel4 × 2 は tb がブロックデザインと同じく外に置く）。
#     ふつうと陽性対照（-DDROP_POSCTL: FULL の TP の drop を数え忘れる。rec_drop の和と LATE の和が合わなくなるべき）。2 本を同時に
G24S45_RTL := $(filter-out sim/tb_g24_core.v,$(G24CORE_RTL)) src/common/core_cmn.v src/common/raw_core.v src/common/axis_sel4.v \
              src/g24/g24_s45_core.v sim/tb_g24_s45.v
G24S45_V ?= normal drop
sim-g24s45:
	@o0=$(SIMDIR)/g24s_in; mkdir -p $$o0; [ -f $$o0/x.hex ] || $(PYTHON) sim/check_g24.py spec-gen $$o0; \
	for v in $(G24S45_V); do \
	  o=$(SIMDIR)/g24s45_$$v; mkdir -p $$o; ln -sf ../g24s_in/x.hex $$o/x.hex; d="-DFFT_STALL_AT=3"; \
	  [ $$v = drop ] && d="$$d -DDROP_POSCTL"; \
	  ( $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g24/g24_coef_lo.hex\" -DHI=\"src/g24/g24_coef_hi.hex\" \
	      -DTA=\"src/g24/g24_tw_a.hex\" -DTB=\"src/g24/g24_tw_b.hex\" -o $$o/tb $(G24S45_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_g24.py s45 $$o $$o/tb.log > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in $(G24S45_V); do printf '%-14s %s\n' "g24s45_$$v" "$$(grep '結果:' $(SIMDIR)/g24s45_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/g24s45_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g24s45_drop/check.log \
	  && echo "sim-g24s45: 全部通過（陽性対照は落ちた）" || (echo "sim-g24s45: NG"; exit 1)

# 2e-2. コア 4 個（s45_core_0〜3、4 個とも RAW = 1、F-5）に同じ ADC（SRC 2）を入れ、ダンプがコア 0 と bit 単位で同じか（F-4 の sim 版）・
#       RAW の SRC がコアごとに効くか。proj025 の sim-g22x2（2 コア）を 4 コアに。
#       ふつうと陽性対照（-DX4_DLY: コア 3 の FULL の口に 1 段多い。コア 3 だけ違うべき）の 2 本を同時に。判定は tb の中（「結果:」の行）
G24X4_RTL := $(filter-out sim/tb_g24_s45.v,$(G24S45_RTL)) sim/tb_g24_x4.v
G24X4_V ?= normal dly
.PHONY: sim-g24x4
sim-g24x4:
	@o0=$(SIMDIR)/g24s_in; mkdir -p $$o0; [ -f $$o0/x.hex ] || $(PYTHON) sim/check_g24.py spec-gen $$o0; \
	for v in $(G24X4_V); do \
	  o=$(SIMDIR)/g24x4_$$v; mkdir -p $$o; ln -sf ../g24s_in/x.hex $$o/x.hex; d="-DFFT_STALL_AT=3"; \
	  [ $$v = dly ] && d="$$d -DX4_DLY"; \
	  ( $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g24/g24_coef_lo.hex\" -DHI=\"src/g24/g24_coef_hi.hex\" \
	      -DTA=\"src/g24/g24_tw_a.hex\" -DTB=\"src/g24/g24_tw_b.hex\" -o $$o/tb $(G24X4_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1 ) & \
	done; wait; \
	for v in $(G24X4_V); do printf '%-14s %s\n' "g24x4_$$v" "$$(grep '結果:' $(SIMDIR)/g24x4_$$v/tb.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/g24x4_normal/tb.log && grep -q '結果: 不合格' $(SIMDIR)/g24x4_dly/tb.log \
	  && echo "sim-g24x4: 全部通過（陽性対照は落ちた）" || (echo "sim-g24x4: NG"; exit 1)

# 4d-2. FULL の流れの遅れ D_eff = D_S ＋ 1.5·L（tb_g24_ds、proj023 の sim-wds の形）。ADC 4 本・axis_sel4 × 2 はブロックデザインと同じく外に、
#       FULL・RAW とも SRC 2。インパルスを (i) RAW のダンプの頭・(ii) フレームの境目に G24DS_NIMP 個（組の数 × 2）。
#       ふつうと陽性対照（-DDS_POSCTL: FULL の口に axis_sel4 の段が無い → D_S が 0 に動き、+1 の判定だけが落ちるべき）の 2 本を同時に
G24DS_RTL  := $(filter-out sim/tb_g24_s45.v,$(G24S45_RTL)) sim/tb_g24_ds.v
G24DS_NIMP ?= 8
G24DS_V    ?= normal posctl
.PHONY: sim-g24ds
sim-g24ds:
	@for v in $(G24DS_V); do \
	  o=$(SIMDIR)/g24ds_$$v; mkdir -p $$o; d="-DFFT_STALL_AT=3 -DNIMP=$(G24DS_NIMP)"; pc=""; \
	  [ $$v = posctl ] && d="$$d -DDS_POSCTL" && pc=posctl; \
	  ( $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g24/g24_coef_lo.hex\" -DHI=\"src/g24/g24_coef_hi.hex\" \
	      -DTA=\"src/g24/g24_tw_a.hex\" -DTB=\"src/g24/g24_tw_b.hex\" -o $$o/tb $(G24DS_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_g24.py ds $$o $$pc > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in $(G24DS_V); do printf '%-14s %s\n' "g24ds_$$v" "$$(grep '結果:' $(SIMDIR)/g24ds_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/g24ds_normal/check.log && grep -q '結果: 全部通過（陽性対照' $(SIMDIR)/g24ds_posctl/check.log \
	  && echo "sim-g24ds: 全部通過（陽性対照は落ちた）" || (echo "sim-g24ds: NG"; exit 1)


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

# ---- 2f: 2G-4 の .bit（Vivado サーバ。`make build`。proj025-m0 の Makefile から写した）----
# RealDigitalOrg/RFSoC4x2-BSP を clone した先の board_files（Vivado のインストールツリーの中には置かない。VERSIONS.md）
BOARD_REPO ?= $(HOME)/src/RFSoC4x2-BSP/board_files
# part。既定は -1（実機の .bit。PS には src/board/ps_preset.tcl を当てる）。-2 は PART=xczu48dr-ffvg1517-2-e → build-2-e/
PART_DEFAULT := xczu48dr-ffvg1517-1-e
PART         ?= $(PART_DEFAULT)
# gb_gate のしきい値の既定（core_cmn の GB_K_RST）。proj012 rev3 から 2
GB_K_DEFAULT := 2
GB_K ?= $(GB_K_DEFAULT)
# 実装の戦略（impl_1 の strategy）。空なら既定。例: make build IMPL=Performance_Explore → build-PE/
IMPL ?=
ifeq ($(PART),$(PART_DEFAULT))
  OUTDIR := build
else
  OUTDIR := build-$(patsubst xczu48dr-ffvg1517-%,%,$(PART))
endif
ifneq ($(GB_K),$(GB_K_DEFAULT))
  OUTDIR := $(OUTDIR)-k$(GB_K)
endif
ifneq ($(IMPL),)
  OUTDIR := $(OUTDIR)-$(shell echo $(IMPL) | tr -cd 'A-Z')
endif
# launch_runs -jobs（効くのは OOC 合成だけ）。proj027: Vivado は並行で使うので上限 8（2026-10-23、西村さん。proj025 は 30）
BUILD_JOBS ?= 8
export BOARD_REPO PART OUTDIR GB_K IMPL

# 2G-4 の .bit（2f。合成〜ビットストリーム）。成果物は $(OUTDIR)/proj030.bit・.hwh。
# **ビルドの後、今のディレクトリで今の RTL が焼けたかを確かめる**（grep BUILD_TAG $(OUTDIR)/vivado.log）。成否は make の終了状態でなくログの ERROR・TIMING (確定) で読む
build:
	mkdir -p $(OUTDIR)
	$(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado.log -source build.tcl -tclargs $(BUILD_JOBS)

# impl_1 は完走したのに、後段（open_run 〜 照合・CDC・build/ への写し）で親の Vivado が落ちたときの再開（proj025 2f ビルド 2）。
# 合成・実装はやり直さない（build.tcl の RESUME=1 → build_post.tcl）。.bit より新しいソースがあれば止まる。ログは別名（元の vivado.log を残す）
post:
	RESUME=1 $(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado_post.log -source build.tcl -tclargs $(BUILD_JOBS)

# ================================================================ proj030
.PHONY: model sim-sep sim-all2 ooc-sep ooc-chain ooc-q ooc-ref

# M-1 の模型。成否は最後の「まとめ」の行で読む
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

# ---- P-2・P-3 の OOC（`-1`・256 MHz）。結果は build-ooc/ooc-<名前>.txt ----
OOC_CHAIN := src/common/cmul.v src/common/dft16f.v src/s2_chain.v
OOC_Q     := src/s2_q.v
ooc-chain ooc-q:
	@n=$(@:ooc-%=%); top=s2_$$n; f="$(if $(filter ooc-chain,$@),$(OOC_CHAIN),$(OOC_Q))"; o=build-ooc/$$n; mkdir -p $$o; \
	cd $$o && $(VIVADO) -mode batch -nojournal -log vivado.log -source ../../tools/ooc_rtl.tcl -tclargs $$top 3.906 clk $$(for x in $$f; do echo ../../$$x; done) > /dev/null 2>&1; \
	  grep '^OOC ' vivado.log | tee ../ooc-$$n.txt; m=$$(grep -c 'Synth 8-3848' vivado.log); echo "Synth 8-3848: $$m" | tee -a ../ooc-$$n.txt; \
	  grep -c 'CRITICAL WARNING' vivado.log | sed 's/^/CRITICAL WARNING: /' | tee -a ../ooc-$$n.txt; [ $$m -eq 0 ]

# 比べる相手: 今の鎖 g24_chain（proj027 の HEAD から ref/ に写した。電力まで含む）
ooc-ref:
	@o=build-ooc/ref; mkdir -p $$o; \
	cd $$o && $(VIVADO) -mode batch -nojournal -log vivado.log -source ../../tools/ooc_rtl.tcl -tclargs g24_chain 3.906 clk ../../src/common/cmul.v ../../ref/dft16.v ../../ref/g24_chain.v > /dev/null 2>&1; \
	  grep '^OOC ' vivado.log | tee ../ooc-ref.txt
