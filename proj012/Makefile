# SPDX-License-Identifier: BSD-3-Clause
# Vivado のインストール先をここで持つ。
# settings64.sh を .bashrc で source しないこと（Xilinx 同梱の古い共有ライブラリが
# LD_LIBRARY_PATH の先頭に入り、git / ssh / python が壊れる）。
# bin/vivado は起動スクリプト自身が環境を組み立てるので、絶対パスで叩けば動く。
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado

# RealDigitalOrg/RFSoC4x2-BSP を clone した先の board_files ディレクトリ。
# Vivado のインストールツリーの中には置かない（VERSIONS.md 参照）。
BOARD_REPO ?= $(HOME)/src/RFSoC4x2-BSP/board_files

# part。**-1 で閉じる設計は -2 でも必ず閉じる**ので `make timing-check` で -1 でも通す。
PART_DEFAULT := xczu48dr-ffvg1517-2-e
PART         ?= $(PART_DEFAULT)

# FFT IP の変種（src/fft_cfg.tcl）。proj011 はこれを振って測る。
#   res  = realtime + 乗算器 use_mults_resources  + バタフライ use_luts            （本命・既定）
#   perf = realtime + 乗算器 use_mults_performance + バタフライ use_xtremedsp_slices（proj010 と乗算器が同じ。realtime の効きだけを見る）
FFT_OPT ?= res

# rev6: gb_gate のしきい値のハードのリセットでの既定値（spec_core の GB_K_RST）。0 = 素通し（rev5 までと同じ起動）。
# proj012 rev3: 既定値を 2 にした。rev2 のビット列の GRST で、K = 0 は 55 / 150 回途切れ、K = 1・2・4 は 450 回とも 0（README の rev3）。
# 既定以外は別ディレクトリ（build-k0/ など）に出す
GB_K_DEFAULT := 2
GB_K ?= $(GB_K_DEFAULT)

# 既定以外の part・変種は別ディレクトリに出し、検証済みの成果物を上書きしない。
#   build/            -2・res        build-perf/      -2・perf
#   build-1-e/        -1・res        build-1-e-perf/  -1・perf
ifeq ($(PART),$(PART_DEFAULT))
  OUTDIR := build
else
  OUTDIR := build-$(patsubst xczu48dr-ffvg1517-%,%,$(PART))
endif
ifneq ($(FFT_OPT),res)
  ifeq ($(OUTDIR),build)
    OUTDIR := build-$(FFT_OPT)
  else
    OUTDIR := $(OUTDIR)-$(FFT_OPT)
  endif
endif
ifneq ($(GB_K),$(GB_K_DEFAULT))
  OUTDIR := $(OUTDIR)-k$(GB_K)
endif
# rev6 の検証ビルド: GB_SLOW=b で gb_fifo の gray の bit b の同期段を GB_SLOW_SITE に固定して、わざと遅らせる（tools/gb_slow.tcl）。build-slow1/ など
GB_SLOW    ?=
GB_SLOW_SITE ?= SLICE_X46Y109
ifneq ($(GB_SLOW),)
  OUTDIR := $(OUTDIR)-slow$(GB_SLOW)
endif

# 同時に走らせる run の数（launch_runs -jobs）。効くのは IP の OOC 合成だけ。
# proj010 から lane_fft（FFT IP）の OOC 合成が 1 本増えている（proj011 も同じ）。ビルドサーバの nproc = 32 に合わせてある。
# コア数やメモリの少ない機械では `make JOBS=8` に下げること。
JOBS ?= 30

export BOARD_REPO PART OUTDIR FFT_OPT GB_K GB_SLOW GB_SLOW_SITE

# ---- シミュレーション（Vivado もライセンスも要らない。RTL を触ったらまずこれ）----
# FFT IP の代わりに sim/lane_fft_model.v を使う。判定は sim/check.py（bit 単位・numpy・帳簿の 3 層）。
# 所要 8〜10 分（ほとんどが AXI4-Lite での 4096 ch × 2 語の読み出し 3 回ぶん）。
IVERILOG  ?= iverilog
VVP       ?= vvp
PYTHON    ?= python3
SIM_SHIFT ?= 7
# SIM_SKEW: モデルの TLAST の検査だけを SIM_SKEW サンプルずらす（rev3 の診断の陽性対照）。0 = ずらさない
SIM_SKEW  ?= 0
# SIM_START: 起動の直後の入力の途切れ（rev5）。0 = 途切れなし / 1 = 途切れ・起動の見張りあり / 2 = 途切れ・見張りなし（陰性対照）
SIM_START ?= 0
SIM_DEFS  := $(if $(filter 1 2,$(SIM_START)),-DSTART_GAPS) $(if $(filter 2,$(SIM_START)),-DNO_GUARD)
SIMDIR    := build-sim-s$(SIM_SHIFT)$(if $(filter-out 0,$(SIM_SKEW)),-k$(SIM_SKEW))$(if $(filter-out 0,$(SIM_START)),-g$(SIM_START))
RTL       := src/spec_core.v src/cmul.v src/dft16.v src/tw_rom.v

.PHONY: all sim sim-gb sim-all gb-cdc worst-paths survey twiddle prog id timing-check clean

all: $(OUTDIR)
	$(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado.log -source build.tcl -tclargs $(JOBS)

# SIM_SHIFT=7: 飽和しない（numpy との照合を全 ch で行う）/ SIM_SHIFT=4: 強い線が飽和する（飽和の数え方を確かめる）
sim:
	mkdir -p $(SIMDIR)
	$(PYTHON) sim/check.py gen $(SIMDIR)
	$(IVERILOG) -g2005 -DOUT=\"$(SIMDIR)\" -DSHIFT=$(SIM_SHIFT) -DTLAST_SKEW=$(SIM_SKEW) $(SIM_DEFS) -o $(SIMDIR)/tb $(RTL) sim/lane_fft_model.v sim/tb_spec_core.v
	$(VVP) -n $(SIMDIR)/tb
	$(PYTHON) sim/check.py check $(SIMDIR) $(SIM_SHIFT) $(SIM_SKEW) $(SIM_START)

# ---- ギアボックスの起動の途切れの模型（rev6。数秒）----
# 3 : 4 のクロックの非同期 FIFO で、gray ポインタのビットごとの遅延が起動の途切れを作ること・gb_gate のしきい値 K が
# それを消すことを確かめる（sim/tb_gearbox.v の冒頭）。gb_gate.v / gb_adc.v の試験も兼ねる
sim-gb:
	mkdir -p build-sim-gb
	$(IVERILOG) -g2005 -o build-sim-gb/tb sim/tb_gearbox.v src/gb_gate.v src/gb_adc.v
	$(VVP) -n build-sim-gb/tb

# ---- 配置配線後の dcp で gb_fifo の gray ポインタの乗り換えをビットごとに測る（rev6。ビルド不要、数分）----
# DCP を指定しなければ build/ の dcp。結果は dcp と同じ場所の gb_cdc.txt
DCP ?= $(firstword $(wildcard $(OUTDIR)/vivado/proj012.runs/impl_1/*_routed.dcp))
gb-cdc:
	@test -n "$(DCP)" || { echo "DCP が無い（make gb-cdc DCP=...）"; exit 1; }
	$(VIVADO) -mode batch -nojournal -nolog -source tools/gb_cdc.tcl -tclargs $(DCP) $(dir $(DCP))gb_cdc.txt

# ---- 配置配線後の dcp で setup / hold の最悪経路の中身を読む（rev3。ビルド不要、数分）----
# DCP は gb-cdc と同じ既定（$(OUTDIR) の dcp）。`make worst-paths PART=xczu48dr-ffvg1517-1-e` で -1 の dcp。
# 結果は dcp の run と同じ階層の $(OUTDIR)/worst_paths/。WP_N = 上位の本数、WP_THR = 束ねるしきい値（ns）
WP_N   ?= 200
WP_THR ?= 0.30
worst-paths:
	@test -n "$(DCP)" || { echo "DCP が無い（make worst-paths DCP=...）"; exit 1; }
	$(VIVADO) -mode batch -nojournal -nolog -source tools/worst_paths.tcl -tclargs $(DCP) $(OUTDIR)/worst_paths $(WP_N) $(WP_THR)

# ---- FFT IP を 1 個だけ OOC 合成して資源を数える（proj010 の教訓: IP の資源は数えてから予言する）----
# throttle 2 × 乗算器 2 × バタフライ 2 = 8 通り。設定は src/fft_cfg.tcl（本番の build.tcl と同じ）。
# 結果は build-survey/survey.txt。**nonrealtime / use_mults_performance / use_xtremedsp_slices（= proj010）が
# DSP 50 にならなければ、この調査は本番と違うものを数えている**ので、その先の数字を使わない。
# ライセンスは合成と同じものが要る。所要は並列で 10〜20 分の見込み。
survey:
	mkdir -p build-survey
	$(VIVADO) -mode batch -nojournal -log build-survey/vivado.log -source tools/ip_survey.tcl -tclargs $(JOBS)

# ---- sim の変種を同時に回す（Vivado サーバ向け。iverilog は 1 本 1 コアなので、変種の数だけ並べても時間は 1 本ぶん）----
# SHIFT 7（飽和なし）/ SHIFT 4（強い線が飽和）/ SKEW 5（TLAST の検査だけをずらす陽性対照）。
# **成否は make の終了状態ではなく各ログの「結果: 全部通過」で判定する**（make の成功を信用しない）。ログは build-sim-logs/
# `make sim-all &` で `make`（ビルド）と並べて走らせてよい（出力先が別）
# 変種は SHIFT-SKEW-START。7-0-1 は起動の直後の途切れを見張りが吸収すること、7-0-2 は見張りがないと崩れること（陰性対照）
SIM_VARIANTS ?= 7-0-0 4-0-0 7-5-0 7-0-1 7-0-2
sim-all:
	@mkdir -p build-sim-logs
	@rm -f build-sim-logs/*.log
	$(MAKE) --no-print-directory -j$(words $(SIM_VARIANTS) gb) $(addprefix sim-v-,$(SIM_VARIANTS)) sim-v-gb
	@echo "---- sim-all ----"
	@for f in build-sim-logs/*.log; do printf '%-36s %s\n' "$$f" "$$(grep '結果:' $$f || echo '結果の行が無い（途中で落ちた）')"; done
	@fail=$$(grep -L '結果: 全部通過' build-sim-logs/*.log); \
	  if [ -n "$$fail" ]; then echo "FAIL: $$fail"; exit 1; else echo "sim-all: 全部通過"; fi

sim-v-gb:
	-$(MAKE) --no-print-directory sim-gb > build-sim-logs/sim-gb.log 2>&1

sim-v-%:
	-$(MAKE) --no-print-directory sim SIM_SHIFT=$(word 1,$(subst -, ,$*)) SIM_SKEW=$(word 2,$(subst -, ,$*)) \
	  SIM_START=$(or $(word 3,$(subst -, ,$*)),0) \
	  > build-sim-logs/sim-$*.log 2>&1

# ひねり係数の ROM を作り直す（生成物もコミットする。差分が出たら理由を README に書く）
twiddle:
	$(PYTHON) tools/gen_tw_rom.py > src/tw_rom.v
	git diff --stat -- src/tw_rom.v

prog:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl

# JTAG チェーンのデバイスを表示するだけ（合成ライセンス不要）
id:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl -tclargs id

# 速度グレード -1 で通るかを確かめる。成果物は build-1-e/（FFT_OPT=perf なら build-1-e-perf/）に出るので build/ は無傷。
# `make timing-check FFT_OPT=perf` のように変種を引き継ぐ（コマンドラインの変数は再帰 make に渡る）。
timing-check:
	$(MAKE) PART=xczu48dr-ffvg1517-1-e

$(OUTDIR):
	mkdir -p $(OUTDIR)

clean:
	rm -rf build build-* .Xil *.jou *.log
