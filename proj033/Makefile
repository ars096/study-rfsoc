# SPDX-License-Identifier: BSD-3-Clause
# proj033 — 2G-1-Fast にレーン FFT の 2-for-1（README）。proj024-m0 の Makefile を写し（proj024 の model は model-g21 に）、proj033 の段を後ろに足した
# 以下は proj024 の注: 2G の模型と資源の見積もり、2G-1 の RTL の単体の sim（手順 1a〜2e）、2G-1 の .bit（2f、`make build`、Vivado サーバ）
#
# Vivado のインストール先（survey・s2・build が使う）。settings64.sh を .bashrc で source しないこと（VERSIONS.md）
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado

# ---- 2f: 2G-1 の .bit（Vivado サーバ。`make build`。proj023 の Makefile の build の部分を写した）----
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
# launch_runs -jobs（効くのは OOC 合成だけ）。ビルドサーバの nproc = 32 に合わせてある
BUILD_JOBS ?= 30
export BOARD_REPO PART OUTDIR GB_K IMPL
PYTHON        ?= python3
IVERILOG      ?= iverilog
VVP           ?= vvp
# survey の OOC 合成を同時に走らせる数（9 個）
JOBS ?= 9

.PHONY: model model-g21 estimate survey s2 gen build sim-g21ds sim-g21c sim-g21t sim-g21p sim-g21ch sim-lane sim-g21a sim-g21s sim-recfr sim-g21core sim-g21s45 clean

# proj024 の模型（numpy だけ）。M-1〜M-8。成否は最後の「まとめ」の行で読む（make の成功を信用しない）。proj033 の model は下
model-g21:
	mkdir -p runs
	$(PYTHON) model/g2_model.py all | tee runs/model-g21.log

# 資源の見積もり（E-1）。レーン FFT の数字は既定が外挿の仮の値。S-1 の後は EST_ARGS="--fft '4096,rev,…' …" で置き換える
estimate:
	mkdir -p runs
	$(PYTHON) tools/estimate.py $(EST_ARGS) | tee runs/estimate.log

# Vivado サーバ: レーン FFT 1 個の OOC の配置配線（S-2）。-1・256 MHz で閉じるか。結果は build-s2/s2.txt（数十分〜1 時間）
# proj023 のビルドと重ならないときに回す
s2:
	mkdir -p build-s2
	$(VIVADO) -mode batch -nojournal -log build-s2/vivado.log -source tools/ip_impl.tcl -tclargs 4

# Vivado サーバ: 2G-1-Fast の .bit（B-1。合成〜ビットストリーム、1 時間前後）。成果物は $(OUTDIR)/proj033.bit・.hwh。
# **ビルドの後、今のディレクトリで今の RTL が焼けたかを確かめる**（grep BUILD_TAG $(OUTDIR)/vivado.log）。成否は make の終了状態でなくログの ERROR・TIMING (確定) で読む
build:
	mkdir -p $(OUTDIR)
	$(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado.log -source build.tcl -tclargs $(BUILD_JOBS)

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

# 1d. g21_tw ＋ g21_chain（鎖）。ふつう（SHIFT 7）・飽和（SHIFT 4）・陽性対照 2 本（-DCHAIN_TW_LAT_ERR・-DCHAIN_NORND、落ちるべき）
G21CH_RTL := src/common/cmul.v src/common/dft16.v src/g21/g21_tw.v src/g21/g21_chain.v sim/tb_g21_chain.v
sim-g21ch:
	@o0=$(SIMDIR)/g21ch_in; mkdir -p $$o0; $(PYTHON) sim/check_g21.py chain-gen $$o0 > /dev/null; \
	for v in normal sat twlat nornd; do \
	  o=$(SIMDIR)/g21ch_$$v; mkdir -p $$o; cp $$o0/yre.hex $$o0/yim.hex $$o/; d=""; sh=7; \
	  [ $$v = sat ] && sh=4; [ $$v = twlat ] && d="-DCHAIN_TW_LAT_ERR"; [ $$v = nornd ] && d="-DCHAIN_NORND"; \
	  $(IVERILOG) -g2005 $$d -DSHIFT=$$sh -DOUT=\"$$o\" -DTA=\"src/g21/g21_tw_a.hex\" -DTB=\"src/g21/g21_tw_b.hex\" \
	    -o $$o/tb $(G21CH_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g21.py chain $$o $$o/tb.log $$sh > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g21ch_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g21ch_normal/check.log && grep -q '結果: 全部通過' $(SIMDIR)/g21ch_sat/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/g21ch_twlat/check.log && grep -q '結果: 不合格' $(SIMDIR)/g21ch_nornd/check.log \
	  && echo "sim-g21ch: 全部通過（陽性対照 2 本は落ちた）" || (echo "sim-g21ch: NG"; exit 1)

# 2a. レーン FFT 16384 点の行動模型（sim/lane_fft_g21_model.v）の単体。tready の下げなし・あり（-DFFT_STALL_AT=3）
sim-lane:
	@for v in plain stall; do \
	  o=$(SIMDIR)/lane_$$v; mkdir -p $$o; d=""; st=0; [ $$v = stall ] && d="-DFFT_STALL_AT=3" && st=1; \
	  $(PYTHON) sim/check_g21.py lane-gen $$o && \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -o $$o/tb sim/lane_fft_g21_model.v sim/tb_lane_g21.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g21.py lane $$o $$o/tb.log $$st > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "lane_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/lane_plain/check.log && grep -q '結果: 全部通過' $(SIMDIR)/lane_stall/check.log \
	  && echo "sim-lane: 全部通過" || (echo "sim-lane: NG"; exit 1)

# 2b. g21_acc（FULL の積分器）。ふつうと陽性対照（-DACC_FIRST_ERR: ダンプの最初で消さない。面 0 の 2 回目のダンプ C が落ちるべき）
sim-g21a:
	@for v in normal err; do \
	  o=$(SIMDIR)/g21a_$$v; mkdir -p $$o; d=""; [ $$v = err ] && d="-DACC_FIRST_ERR"; \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -o $$o/tb src/g21/g21_acc.v sim/tb_g21_acc.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g21.py acc $$o > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g21a_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g21a_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g21a_err/check.log \
	  && echo "sim-g21a: 全部通過（陽性対照は落ちた）" || (echo "sim-g21a: NG"; exit 1)

# 2c. g21_spec（分光の本体。proj033: IP 8 個 → s2_sep → s2_chain → s2_q）。ふつう（流し始めの tready の下げあり）と陽性対照（-DIPQ_POSCTL: 待ち行列なし。落ちるべき）
G21S_RTL := src/common/cmul.v src/common/dft16f.v src/g21/g21_coef.v src/g21/g21_pfb_core.v src/g21/g21_pfb.v \
            src/g21/g21_tw.v src/s2_sep.v src/s2_chain.v src/s2_q.v src/g21/g21_acc.v src/g21/g21_spec.v sim/lane_fft_g21_model.v sim/tb_g21_spec.v
sim-g21s:
	@o0=$(SIMDIR)/g21s_in; mkdir -p $$o0; $(PYTHON) sim/check_g21.py spec-gen $$o0; \
	for v in normal ipq; do \
	  o=$(SIMDIR)/g21s_$$v; mkdir -p $$o; ln -sf ../g21s_in/x.hex $$o/x.hex; d="-DFFT_STALL_AT=3"; \
	  [ $$v = ipq ] && d="$$d -DIPQ_POSCTL"; \
	  $(IVERILOG) -g2005 $$d -DSHIFT=4 -DOUT=\"$$o\" -DLO=\"src/g21/g21_coef_lo.hex\" -DHI=\"src/g21/g21_coef_hi.hex\" \
	    -DTA=\"src/g21/g21_tw_a.hex\" -DTB=\"src/g21/g21_tw_b.hex\" -o $$o/tb $(G21S_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g21.py spec $$o $$o/tb.log 4 > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g21s_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g21s_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g21s_ipq/check.log \
	  && echo "sim-g21s: 全部通過（陽性対照は落ちた）" || (echo "sim-g21s: NG"; exit 1)

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

# 2d. g21_core（FULL の流れのブロック・SPEC のレコード 1 MiB・FULL の TP・SRC）。入力は 2c と同じ x.hex（sim-g21s の g21s_in を作る）。
#     ふつう・陽性対照 2 本（-DG21C_POSCTL: 積分器の読みの口に 1 段多い / -DG21C_TP_POSCTL: TP の F0 の × 32 を忘れる）。
#     G21CORE_V で回す変種を選べる（コア 2 個の環境で 3 本を同時に回して 20 分前後。1 MiB のレコードを出す 13 万クロックが長い）
G21CORE_RTL := src/common/cmul.v src/common/dft16f.v src/s2_sep.v src/s2_chain.v src/s2_q.v src/common/adc_ev.v src/common/tp_core.v src/common/rec_fr.v src/common/rec_arb.v \
               src/g21/g21_coef.v src/g21/g21_pfb_core.v src/g21/g21_pfb.v src/g21/g21_tw.v src/g21/g21_acc.v \
               src/g21/g21_spec.v src/g21/g21_core.v sim/lane_fft_g21_model.v sim/tb_g21_core.v
G21CORE_V ?= normal posctl tp
sim-g21core:
	@o0=$(SIMDIR)/g21s_in; mkdir -p $$o0; [ -f $$o0/x.hex ] || $(PYTHON) sim/check_g21.py spec-gen $$o0; \
	for v in $(G21CORE_V); do \
	  o=$(SIMDIR)/g21core_$$v; mkdir -p $$o; ln -sf ../g21s_in/x.hex $$o/x.hex; d="-DFFT_STALL_AT=3"; \
	  [ $$v = posctl ] && d="$$d -DG21C_POSCTL"; [ $$v = tp ] && d="$$d -DG21C_TP_POSCTL"; \
	  ( $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g21/g21_coef_lo.hex\" -DHI=\"src/g21/g21_coef_hi.hex\" \
	      -DTA=\"src/g21/g21_tw_a.hex\" -DTB=\"src/g21/g21_tw_b.hex\" -o $$o/tb $(G21CORE_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_g21.py core $$o $$o/tb.log > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in $(G21CORE_V); do printf '%-14s %s\n' "g21core_$$v" "$$(grep '結果:' $(SIMDIR)/g21core_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/g21core_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g21core_posctl/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/g21core_tp/check.log \
	  && echo "sim-g21core: 全部通過（陽性対照 2 本は落ちた）" || (echo "sim-g21core: NG"; exit 1)

# 2e. g21_s45_core（コアの共通・FULL（s 0）・RAW（s 1）・axis_sel4 × 2 は tb がブロックデザインと同じく外に置く）。
#     ふつうと陽性対照（-DDROP_POSCTL: FULL の TP の drop を数え忘れる。rec_drop の和と LATE の和が合わなくなるべき）。2 本を同時に
G21S45_RTL := $(filter-out sim/tb_g21_core.v,$(G21CORE_RTL)) src/common/core_cmn.v src/common/raw_core.v src/common/axis_sel4.v \
              src/g21/g21_s45_core.v sim/tb_g21_s45.v
G21S45_V ?= normal drop
sim-g21s45:
	@o0=$(SIMDIR)/g21s_in; mkdir -p $$o0; [ -f $$o0/x.hex ] || $(PYTHON) sim/check_g21.py spec-gen $$o0; \
	for v in $(G21S45_V); do \
	  o=$(SIMDIR)/g21s45_$$v; mkdir -p $$o; ln -sf ../g21s_in/x.hex $$o/x.hex; d="-DFFT_STALL_AT=3"; \
	  [ $$v = drop ] && d="$$d -DDROP_POSCTL"; \
	  ( $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g21/g21_coef_lo.hex\" -DHI=\"src/g21/g21_coef_hi.hex\" \
	      -DTA=\"src/g21/g21_tw_a.hex\" -DTB=\"src/g21/g21_tw_b.hex\" -o $$o/tb $(G21S45_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_g21.py s45 $$o $$o/tb.log > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in $(G21S45_V); do printf '%-14s %s\n' "g21s45_$$v" "$$(grep '結果:' $(SIMDIR)/g21s45_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/g21s45_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g21s45_drop/check.log \
	  && echo "sim-g21s45: 全部通過（陽性対照は落ちた）" || (echo "sim-g21s45: NG"; exit 1)

# 4d-2. FULL の流れの遅れ D_eff = D_S ＋ 1.5·L（tb_g21_ds、proj023 の sim-wds の形）。ADC 4 本・axis_sel4 × 2 はブロックデザインと同じく外に、
#       FULL・RAW とも SRC 2。インパルスを (i) RAW のダンプの頭・(ii) フレームの境目に G21DS_NIMP 個（組の数 × 2）。
#       ふつうと陽性対照（-DDS_POSCTL: FULL の口に axis_sel4 の段が無い → D_S が 0 に動き、+1 の判定だけが落ちるべき）の 2 本を同時に
G21DS_RTL  := $(filter-out sim/tb_g21_s45.v,$(G21S45_RTL)) sim/tb_g21_ds.v
G21DS_NIMP ?= 8
G21DS_V    ?= normal posctl
.PHONY: sim-g21ds
sim-g21ds:
	@for v in $(G21DS_V); do \
	  o=$(SIMDIR)/g21ds_$$v; mkdir -p $$o; d="-DFFT_STALL_AT=3 -DNIMP=$(G21DS_NIMP)"; pc=""; \
	  [ $$v = posctl ] && d="$$d -DDS_POSCTL" && pc=posctl; \
	  ( $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g21/g21_coef_lo.hex\" -DHI=\"src/g21/g21_coef_hi.hex\" \
	      -DTA=\"src/g21/g21_tw_a.hex\" -DTB=\"src/g21/g21_tw_b.hex\" -o $$o/tb $(G21DS_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_g21.py ds $$o $$pc > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in $(G21DS_V); do printf '%-14s %s\n' "g21ds_$$v" "$$(grep '結果:' $(SIMDIR)/g21ds_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/g21ds_normal/check.log && grep -q '結果: 全部通過（陽性対照' $(SIMDIR)/g21ds_posctl/check.log \
	  && echo "sim-g21ds: 全部通過（陽性対照は落ちた）" || (echo "sim-g21ds: NG"; exit 1)

# ==== proj033 の段（M-1・M-2 模型、P-1〜P-3 部品、S の OOC）====
.PHONY: sim-sep sim-all2 ooc-sep ooc-chain ooc-q ooc-ref ooc-all

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

# ---- S 部品の OOC（`-1`・256 MHz、合成まで）。結果は build-ooc/ooc-<名前>.txt。Synth 8-3848（ドライバの無いネット）があれば NG ----
# ooc-ref は比べる相手の今の鎖 g21_chain（proj024-m0 の src/g21/g21_chain.v。電力まで含む）。4 本は出力先が別なので並べてよい（ooc-all）
OOC_sep   := s2_sep    src/s2_sep.v
OOC_chain := s2_chain  src/common/cmul.v src/common/dft16f.v src/s2_chain.v
OOC_q     := s2_q      src/s2_q.v
OOC_ref   := g21_chain src/common/cmul.v src/common/dft16.v src/g21/g21_chain.v
ooc-sep ooc-chain ooc-q ooc-ref:
	@n=$(@:ooc-%=%); set -- $(OOC_$(@:ooc-%=%)); top=$$1; shift; o=build-ooc/$$n; mkdir -p $$o; \
	cd $$o && $(VIVADO) -mode batch -nojournal -log vivado.log -source ../../tools/ooc_rtl.tcl -tclargs $$top 3.906 clk $$(for x in "$$@"; do echo ../../$$x; done) > /dev/null 2>&1; \
	  grep '^OOC ' vivado.log | tee ../ooc-$$n.txt; m=$$(grep -c 'Synth 8-3848' vivado.log); echo "Synth 8-3848: $$m" | tee -a ../ooc-$$n.txt; \
	  grep -c 'CRITICAL WARNING' vivado.log | sed 's/^/CRITICAL WARNING: /' | tee -a ../ooc-$$n.txt; [ $$m -eq 0 ]
ooc-all:
	$(MAKE) -j4 ooc-sep ooc-chain ooc-q ooc-ref

clean:
	rm -rf build build-* .Xil *.jou *.log
