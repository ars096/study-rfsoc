# SPDX-License-Identifier: BSD-3-Clause
# proj025 — 2G-2 の RTL。段階 A: 模型（`make model`）・ROM の中身（`make gen`）・部品の単体の sim（手順 1a〜1d、`make sim-all`）
# 段階 B: 2a〜2e の sim（sim-lane 〜 sim-g22ds）・2G-2 の .bit（2f、`make build`、Vivado サーバ）
# proj024 の Makefile の model・gen・sim-g21* を写し（段階 A）、sim-lane 以降・build・s2・survey を proj024-m0 から写した（段階 B）。名前は g22 に
#
# Vivado のインストール先（survey・s2・build が使う）。settings64.sh を .bashrc で source しないこと（VERSIONS.md）
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado

# ---- 2f: 2G-2 の .bit（Vivado サーバ。`make build`。proj024-m0 の Makefile から写した）----
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

PYTHON        ?= python3
IVERILOG      ?= iverilog
VVP           ?= vvp
# survey の OOC 合成を同時に走らせる数
JOBS ?= 9

.PHONY: model model-g22 gen s2 survey build post sim-all sim-g22c sim-g22t sim-g22p sim-g22ch sim-lane sim-g22a sim-g22s sim-recfr sim-g22core sim-g22s45 clean

# proj025 の模型（numpy だけ）。M-a〜d。成否は最後の「まとめ」の行で読む（make の成功を信用しない）。proj034 で model から名前を替えた
model-g22:
	mkdir -p runs
	$(PYTHON) model/g22_model.py | tee runs/model.log

# 2G-2 の ROM の中身（model/g22_fixed.py の定義）を build-gen/ に書き、読み返して模型と照らす。src/g22/ に写したものをコミットする
gen:
	$(PYTHON) tools/gen_g22_tables.py build-gen

# Vivado サーバ: レーン FFT 1 個の OOC の配置配線（S-2）。-1・256 MHz で閉じるか。結果は build-s2/s2.txt（数十分〜1 時間）
# proj023 のビルドと重ならないときに回す
s2:
	mkdir -p build-s2
	$(VIVADO) -mode batch -nojournal -log build-s2/vivado.log -source tools/ip_impl.tcl -tclargs 4

# Vivado サーバ: 2G-2 の .bit（2f。合成〜ビットストリーム、1 時間前後）。成果物は $(OUTDIR)/proj025.bit・.hwh。
# **ビルドの後、今のディレクトリで今の RTL が焼けたかを確かめる**（grep BUILD_TAG $(OUTDIR)/vivado.log）。成否は make の終了状態でなくログの ERROR・TIMING (確定) で読む
build:
	mkdir -p $(OUTDIR)
	$(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado.log -source build.tcl -tclargs $(BUILD_JOBS)

# 2f ビルド 2 で足した: impl_1 は完走したのに、後段（open_run 〜 照合・CDC・build/ への写し）で親の Vivado が落ちたときの再開。
# 合成・実装はやり直さない（build.tcl の RESUME=1 → build_post.tcl）。.bit より新しいソースがあれば止まる。ログは別名（元の vivado.log を残す）
post:
	RESUME=1 $(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado_post.log -source build.tcl -tclargs $(BUILD_JOBS)

# Vivado サーバ: レーン FFT の OOC 合成（S-1）。ライセンスが要る。結果は build-survey/survey.txt
# proj023 のビルドと重ならないときに回す（同じサーバ。壊れはしないが互いに遅くなる）
survey:
	mkdir -p build-survey
	$(VIVADO) -mode batch -nojournal -log build-survey/vivado.log -source tools/ip_survey.tcl -tclargs $(JOBS)

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

# 2a. レーン FFT 8192 点の行動模型（sim/lane_fft_g22_model.v）の単体。tready の下げなし・あり（-DFFT_STALL_AT=3）
sim-lane:
	@for v in plain stall; do \
	  o=$(SIMDIR)/lane_$$v; mkdir -p $$o; d=""; st=0; [ $$v = stall ] && d="-DFFT_STALL_AT=3" && st=1; \
	  $(PYTHON) sim/check_g22.py lane-gen $$o && \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -o $$o/tb sim/lane_fft_g22_model.v sim/tb_lane_g22.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g22.py lane $$o $$o/tb.log $$st > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "lane_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/lane_plain/check.log && grep -q '結果: 全部通過' $(SIMDIR)/lane_stall/check.log \
	  && echo "sim-lane: 全部通過" || (echo "sim-lane: NG"; exit 1)

# 2b. g22_acc（FULL の積分器）。ふつうと陽性対照（-DACC_FIRST_ERR: ダンプの最初で消さない。面 0 の 2 回目のダンプ C が落ちるべき）
sim-g22a:
	@for v in normal err; do \
	  o=$(SIMDIR)/g22a_$$v; mkdir -p $$o; d=""; [ $$v = err ] && d="-DACC_FIRST_ERR"; \
	  $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -o $$o/tb src/g22/g22_acc.v sim/tb_g22_acc.v && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g22.py acc $$o > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g22a_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g22a_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g22a_err/check.log \
	  && echo "sim-g22a: 全部通過（陽性対照は落ちた）" || (echo "sim-g22a: NG"; exit 1)

# 2c. g22_spec（分光の本体）。ふつう（流し始めの tready の下げあり）と陽性対照（-DIPQ_POSCTL: 待ち行列なし。落ちるべき）
G22S_RTL := src/common/cmul.v src/common/dft16f.v src/g22/g22_coef.v src/g22/g22_pfb_core.v src/g22/g22_pfb.v \
            src/g22/g22_tw.v src/s2_sep.v src/s2_chain.v src/s2_q.v src/g22/g22_acc.v src/g22/g22_spec.v sim/lane_fft_g22_model.v sim/tb_g22_spec.v
sim-g22s:
	@o0=$(SIMDIR)/g22s_in; mkdir -p $$o0; $(PYTHON) sim/check_g22.py spec-gen $$o0; \
	for v in normal ipq; do \
	  o=$(SIMDIR)/g22s_$$v; mkdir -p $$o; ln -sf ../g22s_in/x.hex $$o/x.hex; d="-DFFT_STALL_AT=3"; \
	  [ $$v = ipq ] && d="$$d -DIPQ_POSCTL"; \
	  $(IVERILOG) -g2005 $$d -DSHIFT=4 -DOUT=\"$$o\" -DLO=\"src/g22/g22_coef_lo.hex\" -DHI=\"src/g22/g22_coef_hi.hex\" \
	    -DTA=\"src/g22/g22_tw_a.hex\" -DTB=\"src/g22/g22_tw_b.hex\" -o $$o/tb $(G22S_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	  $(PYTHON) sim/check_g22.py spec $$o $$o/tb.log 4 > $$o/check.log 2>&1; \
	  printf '%-14s %s\n' "g22s_$$v" "$$(grep '結果:' $$o/check.log || echo '結果の行が無い')"; \
	done
	@grep -q '結果: 全部通過' $(SIMDIR)/g22s_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g22s_ipq/check.log \
	  && echo "sim-g22s: 全部通過（陽性対照は落ちた）" || (echo "sim-g22s: NG"; exit 1)

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

# 2d. g22_core（FULL の流れのブロック・SPEC のレコード 512 KiB・FULL の TP・SRC）。入力は 2c と同じ x.hex（sim-g22s の g22s_in を作る）。
#     ふつう・陽性対照 2 本（-DG22C_POSCTL: 積分器の読みの口に 1 段多い / -DG22C_TP_POSCTL: TP の F0 の × 32 を忘れる）。
#     G22CORE_V で回す変種を選べる（コア 2 個の環境で 3 本を同時に回して 20 分前後。512 KiB のレコードを出す 13 万クロックが長い）
G22CORE_RTL := src/common/cmul.v src/common/dft16f.v src/s2_sep.v src/s2_chain.v src/s2_q.v src/common/adc_ev.v src/common/tp_core.v src/common/rec_fr.v src/common/rec_arb.v \
               src/g22/g22_coef.v src/g22/g22_pfb_core.v src/g22/g22_pfb.v src/g22/g22_tw.v src/g22/g22_acc.v \
               src/g22/g22_spec.v src/g22/g22_core.v sim/lane_fft_g22_model.v sim/tb_g22_core.v
G22CORE_V ?= normal posctl tp
sim-g22core:
	@o0=$(SIMDIR)/g22s_in; mkdir -p $$o0; [ -f $$o0/x.hex ] || $(PYTHON) sim/check_g22.py spec-gen $$o0; \
	for v in $(G22CORE_V); do \
	  o=$(SIMDIR)/g22core_$$v; mkdir -p $$o; ln -sf ../g22s_in/x.hex $$o/x.hex; d="-DFFT_STALL_AT=3"; \
	  [ $$v = posctl ] && d="$$d -DG22C_POSCTL"; [ $$v = tp ] && d="$$d -DG22C_TP_POSCTL"; \
	  ( $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g22/g22_coef_lo.hex\" -DHI=\"src/g22/g22_coef_hi.hex\" \
	      -DTA=\"src/g22/g22_tw_a.hex\" -DTB=\"src/g22/g22_tw_b.hex\" -o $$o/tb $(G22CORE_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_g22.py core $$o $$o/tb.log > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in $(G22CORE_V); do printf '%-14s %s\n' "g22core_$$v" "$$(grep '結果:' $(SIMDIR)/g22core_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/g22core_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g22core_posctl/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/g22core_tp/check.log \
	  && echo "sim-g22core: 全部通過（陽性対照 2 本は落ちた）" || (echo "sim-g22core: NG"; exit 1)

# 2e. g22_s45_core（コアの共通・FULL（s 0）・RAW（s 1）・axis_sel4 × 2 は tb がブロックデザインと同じく外に置く）。
#     ふつうと陽性対照（-DDROP_POSCTL: FULL の TP の drop を数え忘れる。rec_drop の和と LATE の和が合わなくなるべき）。2 本を同時に
G22S45_RTL := $(filter-out sim/tb_g22_core.v,$(G22CORE_RTL)) src/common/core_cmn.v src/common/raw_core.v src/common/axis_sel4.v \
              src/g22/g22_s45_core.v sim/tb_g22_s45.v
G22S45_V ?= normal drop
sim-g22s45:
	@o0=$(SIMDIR)/g22s_in; mkdir -p $$o0; [ -f $$o0/x.hex ] || $(PYTHON) sim/check_g22.py spec-gen $$o0; \
	for v in $(G22S45_V); do \
	  o=$(SIMDIR)/g22s45_$$v; mkdir -p $$o; ln -sf ../g22s_in/x.hex $$o/x.hex; d="-DFFT_STALL_AT=3"; \
	  [ $$v = drop ] && d="$$d -DDROP_POSCTL"; \
	  ( $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g22/g22_coef_lo.hex\" -DHI=\"src/g22/g22_coef_hi.hex\" \
	      -DTA=\"src/g22/g22_tw_a.hex\" -DTB=\"src/g22/g22_tw_b.hex\" -o $$o/tb $(G22S45_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_g22.py s45 $$o $$o/tb.log > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in $(G22S45_V); do printf '%-14s %s\n' "g22s45_$$v" "$$(grep '結果:' $(SIMDIR)/g22s45_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/g22s45_normal/check.log && grep -q '結果: 不合格' $(SIMDIR)/g22s45_drop/check.log \
	  && echo "sim-g22s45: 全部通過（陽性対照は落ちた）" || (echo "sim-g22s45: NG"; exit 1)

# 2e-2. コア 2 個（s45_core_0 RAW = 1・s45_core_1 RAW = 0）に同じ ADC（SRC 2）を入れ、ダンプが bit 単位で同じか（E-4 の sim 版）・RAW = 0 のコアの形。
#       ふつうと陽性対照（-DX2_DLY: コア 1 の FULL の口に 1 段多い。違うべき）の 2 本を同時に。判定は tb の中（「結果:」の行）
G22X2_RTL := $(filter-out sim/tb_g22_s45.v,$(G22S45_RTL)) sim/tb_g22_x2.v
G22X2_V ?= normal dly
.PHONY: sim-g22x2
sim-g22x2:
	@o0=$(SIMDIR)/g22s_in; mkdir -p $$o0; [ -f $$o0/x.hex ] || $(PYTHON) sim/check_g22.py spec-gen $$o0; \
	for v in $(G22X2_V); do \
	  o=$(SIMDIR)/g22x2_$$v; mkdir -p $$o; ln -sf ../g22s_in/x.hex $$o/x.hex; d="-DFFT_STALL_AT=3"; \
	  [ $$v = dly ] && d="$$d -DX2_DLY"; \
	  ( $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g22/g22_coef_lo.hex\" -DHI=\"src/g22/g22_coef_hi.hex\" \
	      -DTA=\"src/g22/g22_tw_a.hex\" -DTB=\"src/g22/g22_tw_b.hex\" -o $$o/tb $(G22X2_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1 ) & \
	done; wait; \
	for v in $(G22X2_V); do printf '%-14s %s\n' "g22x2_$$v" "$$(grep '結果:' $(SIMDIR)/g22x2_$$v/tb.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/g22x2_normal/tb.log && grep -q '結果: 不合格' $(SIMDIR)/g22x2_dly/tb.log \
	  && echo "sim-g22x2: 全部通過（陽性対照は落ちた）" || (echo "sim-g22x2: NG"; exit 1)

# 4d-2. FULL の流れの遅れ D_eff = D_S ＋ 1.5·L（tb_g22_ds、proj023 の sim-wds の形）。ADC 4 本・axis_sel4 × 2 はブロックデザインと同じく外に、
#       FULL・RAW とも SRC 2。インパルスを (i) RAW のダンプの頭・(ii) フレームの境目に G22DS_NIMP 個（組の数 × 2）。
#       ふつうと陽性対照（-DDS_POSCTL: FULL の口に axis_sel4 の段が無い → D_S が 0 に動き、+1 の判定だけが落ちるべき）の 2 本を同時に
G22DS_RTL  := $(filter-out sim/tb_g22_s45.v,$(G22S45_RTL)) sim/tb_g22_ds.v
G22DS_NIMP ?= 8
G22DS_V    ?= normal posctl
.PHONY: sim-g22ds
sim-g22ds:
	@for v in $(G22DS_V); do \
	  o=$(SIMDIR)/g22ds_$$v; mkdir -p $$o; d="-DFFT_STALL_AT=3 -DNIMP=$(G22DS_NIMP)"; pc=""; \
	  [ $$v = posctl ] && d="$$d -DDS_POSCTL" && pc=posctl; \
	  ( $(IVERILOG) -g2005 $$d -DOUT=\"$$o\" -DLO=\"src/g22/g22_coef_lo.hex\" -DHI=\"src/g22/g22_coef_hi.hex\" \
	      -DTA=\"src/g22/g22_tw_a.hex\" -DTB=\"src/g22/g22_tw_b.hex\" -o $$o/tb $(G22DS_RTL) && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_g22.py ds $$o $$pc > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in $(G22DS_V); do printf '%-14s %s\n' "g22ds_$$v" "$$(grep '結果:' $(SIMDIR)/g22ds_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/g22ds_normal/check.log && grep -q '結果: 全部通過（陽性対照' $(SIMDIR)/g22ds_posctl/check.log \
	  && echo "sim-g22ds: 全部通過（陽性対照は落ちた）" || (echo "sim-g22ds: NG"; exit 1)

# 1a〜1d をまとめて（iverilog は 1 本 1 コアなので並べて回す）。成否は各ターゲットの最後の行で読む
sim-all:
	@$(MAKE) --no-print-directory -j4 -O sim-g22c sim-g22t sim-g22p sim-g22ch

# ==== proj034 の段（M-1・M-2 模型、P-1〜P-3 部品、S の OOC。proj033 の段を 2G-2 に）====
.PHONY: sim-sep sim-all2 ooc-sep ooc-chain ooc-q ooc-ref ooc-all

# M-1・M-2（proj034）: 2-for-1 の式・鎖の全体・溜めの深さ・(B) の鎖と均しの待ち行列。成否は最後の「まとめ」の行で読む
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

# ---- P-2・P-3 s2_sep → s2_chain（＋ g22_tw）→ s2_q をつないだ sim（6 フレーム、積分器の口を模型と bit 単位で）----
# normal（SHIFT 7）・sat（SHIFT 4、q の飽和あり）・gap は通るべき、d1（-DCHAIN_D1）・nornd（-DCHAIN_NORND）・bubble（-DQ_BUBBLE）は落ちるべき
ALL2_RTL := src/s2_sep.v src/common/cmul.v src/common/dft16f.v src/g22/g22_tw.v src/s2_chain.v src/s2_q.v sim/tb_s2_all.v
ALL2_V   := normal sat gap d1 nornd bubble
sim-all2:
	@for v in $(ALL2_V); do \
	  o=$(SIMDIR)/all2_$$v; mkdir -p $$o; d=""; sh=7; \
	  [ $$v = sat ] && sh=4; [ $$v = gap ] && d="-DTB_GAP"; [ $$v = d1 ] && d="-DCHAIN_D1"; [ $$v = nornd ] && d="-DCHAIN_NORND"; [ $$v = bubble ] && d="-DQ_BUBBLE"; \
	  ( $(PYTHON) sim/check_s2.py gen $$o > /dev/null && \
	    $(IVERILOG) -g2005 -Wall $$d -DSHIFT=$$sh -DOUT=\"$$o\" -DTA=\"src/g22/g22_tw_a.hex\" -DTB=\"src/g22/g22_tw_b.hex\" \
	      -o $$o/tb $(ALL2_RTL) > $$o/iverilog.log 2>&1 && $(VVP) -n $$o/tb > $$o/tb.log 2>&1; \
	    $(PYTHON) sim/check_s2.py all $$o $$o/tb.log $$sh $$v > $$o/check.log 2>&1 ) & \
	done; wait; \
	for v in $(ALL2_V); do printf '%-12s %s\n' "all2_$$v" "$$(grep '結果:' $(SIMDIR)/all2_$$v/check.log || echo '結果の行が無い')"; done
	@grep -q '結果: 全部通過' $(SIMDIR)/all2_normal/check.log && grep -q '結果: 全部通過' $(SIMDIR)/all2_sat/check.log \
	  && grep -q '結果: 全部通過' $(SIMDIR)/all2_gap/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/all2_d1/check.log && grep -q '結果: 不合格' $(SIMDIR)/all2_nornd/check.log \
	  && grep -q '結果: 不合格' $(SIMDIR)/all2_bubble/check.log \
	  && echo "sim-all2: 全部通過（陽性対照 3 本は落ちた）" || (echo "sim-all2: NG"; exit 1)

# ---- S 部品の OOC（`-1`・256 MHz、合成まで）。結果は build-ooc/ooc-<名前>.txt。Synth 8-3848（ドライバの無いネット）があれば NG ----
# ooc-ref は比べる相手の今の鎖 g22_chain（proj025-m0 の src/g22/g22_chain.v。電力まで含む）。4 本は出力先が別なので並べてよい（ooc-all）
OOC_sep   := s2_sep    src/s2_sep.v
OOC_chain := s2_chain  src/common/cmul.v src/common/dft16f.v src/s2_chain.v
OOC_q     := s2_q      src/s2_q.v
OOC_ref   := g22_chain src/common/cmul.v src/common/dft16.v src/g22/g22_chain.v
ooc-sep ooc-chain ooc-q ooc-ref:
	@n=$(@:ooc-%=%); set -- $(OOC_$(@:ooc-%=%)); top=$$1; shift; o=build-ooc/$$n; mkdir -p $$o; \
	cd $$o && $(VIVADO) -mode batch -nojournal -log vivado.log -source ../../tools/ooc_rtl.tcl -tclargs $$top 3.906 clk $$(for x in "$$@"; do echo ../../$$x; done) > /dev/null 2>&1; \
	  grep '^OOC ' vivado.log | tee ../ooc-$$n.txt; m=$$(grep -c 'Synth 8-3848' vivado.log); echo "Synth 8-3848: $$m" | tee -a ../ooc-$$n.txt; \
	  grep -c 'CRITICAL WARNING' vivado.log | sed 's/^/CRITICAL WARNING: /' | tee -a ../ooc-$$n.txt; [ $$m -eq 0 ]
ooc-all:
	$(MAKE) -j4 ooc-sep ooc-chain ooc-q ooc-ref

clean:
	rm -rf build build-* .Xil *.jou *.log runs
