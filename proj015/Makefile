# SPDX-License-Identifier: BSD-3-Clause
# proj014 — proj013 の Makefile（ビルド・spec_core の sim）に、窓（win_core）の模型・sim の標的を後ろに足したもの。
# `make sim-all` = spec_core の sim（sim-spec-all）＋ 窓の sim（sim-win-all）。成否は各ログの「結果: 全部通過」で読む
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
RTL       := src/spec_core.v src/tp_core.v src/cmul.v src/dft16.v src/tw_rom.v

.PHONY: all sim sim-gb sim-tp sim-all sim-spec-all gb-cdc worst-paths survey twiddle prog id timing-check clean

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

# ---- total power（tp_core）の単体試験（proj013。20 秒ほど）----
# 仕様から書いた模型（sim/check_tp.py）とリングバッファの中身を bit 単位で照合する。SIM_TP_POSCTL=1 は陽性対照
# （F0 の判定を「隙間を考えない素朴な形」にした tp_core。**落ちるべきところで落ちたら「結果: 全部通過」**）
SIM_TP_POSCTL ?= 0
SIMTPDIR := build-sim-tp$(if $(filter 1,$(SIM_TP_POSCTL)),-posctl)
sim-tp:
	mkdir -p $(SIMTPDIR)
	$(PYTHON) sim/check_tp.py gen $(SIMTPDIR)
	$(IVERILOG) -g2005 $(if $(filter 1,$(SIM_TP_POSCTL)),-DTP_POSCTL) -DOUT=\"$(SIMTPDIR)\" $$(cat $(SIMTPDIR)/tp_defs) -o $(SIMTPDIR)/tb src/tp_core.v sim/tb_tp_core.v
	$(VVP) -n $(SIMTPDIR)/tb
	$(PYTHON) sim/check_tp.py check $(SIMTPDIR) $(if $(filter 1,$(SIM_TP_POSCTL)),posctl)

# ---- 配置配線後の dcp で gb_fifo の gray ポインタの乗り換えをビットごとに測る（rev6。ビルド不要、数分）----
# DCP を指定しなければ build/ の dcp。結果は dcp と同じ場所の gb_cdc.txt
DCP ?= $(firstword $(wildcard $(OUTDIR)/vivado/proj015.runs/impl_1/*_routed.dcp))
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

# ---- sim の変種を同時に回す（Vivado サーバ向け。iverilog は 1 本 1 コアなので、変種の数だけ並べても時間は 1 本ぶん）----
# SHIFT 7（飽和なし）/ SHIFT 4（強い線が飽和）/ SKEW 5（TLAST の検査だけをずらす陽性対照）。
# proj013: tp_core の単体（sim-tp）とその陽性対照（sim-tp SIM_TP_POSCTL=1）も並べる。
# **成否は make の終了状態ではなく各ログの「結果: 全部通過」で判定する**（make の成功を信用しない）。ログは build-sim-logs/
# `make sim-all &` で `make`（ビルド）と並べて走らせてよい（出力先が別）
# 変種は SHIFT-SKEW-START。7-0-1 は起動の直後の途切れを見張りが吸収すること、7-0-2 は見張りがないと崩れること（陰性対照）
SIM_VARIANTS ?= 7-0-0 4-0-0 7-5-0 7-0-1 7-0-2
sim-spec-all:
	@mkdir -p build-sim-logs
	@rm -f build-sim-logs/*.log
	$(MAKE) --no-print-directory -j$(words $(SIM_VARIANTS) gb tp tpp) $(addprefix sim-v-,$(SIM_VARIANTS)) sim-v-gb sim-v-tp sim-v-tpp
	@echo "---- sim-all ----"
	@for f in build-sim-logs/*.log; do printf '%-36s %s\n' "$$f" "$$(grep '結果:' $$f || echo '結果の行が無い（途中で落ちた）')"; done
	@fail=$$(grep -L '結果: 全部通過' build-sim-logs/*.log); \
	  if [ -n "$$fail" ]; then echo "FAIL: $$fail"; exit 1; else echo "sim-spec-all: 全部通過"; fi

sim-v-gb:
	-$(MAKE) --no-print-directory sim-gb > build-sim-logs/sim-gb.log 2>&1

sim-v-tp:
	-$(MAKE) --no-print-directory sim-tp > build-sim-logs/sim-tp.log 2>&1

sim-v-tpp:
	-$(MAKE) --no-print-directory sim-tp SIM_TP_POSCTL=1 > build-sim-logs/sim-tp-posctl.log 2>&1

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

# ============================================================ proj014: 窓（win_core）の模型と sim
MODEL_A       ?= 60
IVERILOG      ?= iverilog
VVP           ?= vvp
# sim-pfb の粗い ch（0・8・16 は実数化の後処理が自明になる端、4・12 は 45°）
PFB_KS        ?= 0 1 4 5 8 13 15 16
# SIM_PFB_POSCTL=1: 陽性対照（RTL の分岐の和の丸めを切り捨てに）。一致しなければ「結果: 全部通過」
SIM_PFB_POSCTL ?= 0
PFB_DIR       := build-sim-pfb$(if $(filter 1,$(SIM_PFB_POSCTL)),-posctl)
# SIM_DDC_POSCTL=1: 陽性対照（RTL の NCO の番地を 1 つずらす）
SIM_DDC_POSCTL ?= 0
DDC_DIR       := build-sim-ddc$(if $(filter 1,$(SIM_DDC_POSCTL)),-posctl)
DDC_RTL       := src/nco_rom.v src/hb2.v src/pair2.v src/ddc_core.v
WIN_DIR       := build-sim-win$(if $(filter g,$(SIM_WIN_POSCTL)),-g)
# SIM_WSPEC_POSCTL=1: 陽性対照（RTL の積分で初回のフレームでも読み値に足す）→ A が落ちること
# SIM_WSPEC_POSCTL=2: 陽性対照（RTL が FFT IP の tready を見ない = rev1、-DWSPEC_NOREADY）→ B が落ちること
SIM_WSPEC_POSCTL ?= 0
WSPEC_DIR     := build-sim-wspec$(if $(filter 1,$(SIM_WSPEC_POSCTL)),-posctl)$(if $(filter 2,$(SIM_WSPEC_POSCTL)),-noready)
# 変種: 名前:NACC:NDUMP:SHIFT:GAP:RDLY:STALL（GAP 0 = 途切れなし = 256 MHz 窓 / 3 / 32 = 8 MHz 窓の速さ。
#   RDLY = FFT のモデルの tready が解除から 0 のクロック数（既定 5。6000 は最初のフレームが溜まっても IP が受けない = 実機 1 回目の形）/
#   STALL = 3·4096 + 1234 クロックごとに tready を 0 にするクロック数）
WSPEC_VARS    ?= g0:4:4:4:0:5:0 g3:2:4:7:3:5:0 g32:1:3:4:32:5:0 g0r:4:4:4:0:6000:0 g3s:2:4:7:3:5:40
WSPEC_NR_VARS ?= g0r:4:4:4:0:6000:0 g3s:2:4:7:3:5:40


.PHONY: model model-posctl model-sweep fixed fixed-posctl coef sim-pfb sim-ddc sim-win sim-win-g sim-win-all sim-pfb-p sim-ddc-p sim-wspec sim-wspec-p sim-wspec-r sim-top survey clean

# 仕様の模型（numpy だけ。Vivado もライセンスも要らない）。成否は「結果: 全部通過」の行で読む
model:
	mkdir -p build-model
	$(PYTHON) model/win_model.py --a $(MODEL_A) --json build-model/coeffs.json | tee build-model/model.log

# 陽性対照 4 通り（pfb-short / hb-short / nco-sign / ppfb）。どれも落ちれば「結果: 全部通過」
model-posctl:
	mkdir -p build-model
	$(PYTHON) model/win_model.py --a $(MODEL_A) --posctl all | tee build-model/posctl.log

# 要求の深さを振った設計の比較（情報）
model-sweep:
	$(PYTHON) model/win_model.py --A 50 55 60 65 70

# 固定小数点の模型（語長・丸め・NCO）。同じ入力の浮動小数点と比べる。「結果: 全部通過」で読む
fixed:
	mkdir -p build-model
	$(PYTHON) model/win_fixed.py | tee build-model/fixed.log

# 陽性対照（FFT の入力の小数 G = 0 で N1 が落ちる）
fixed-posctl:
	mkdir -p build-model
	$(PYTHON) model/win_fixed.py --posctl | tee build-model/fixed_posctl.log

# 係数の生成物 src/win_coef.vh（リポジトリに入れる。手で直さない）。設計を変えたら作り直して sim-pfb を回し直す
coef:
	$(PYTHON) tools/gen_coef.py src/win_coef.vh

# pfb_core の単体の sim（iverilog）。model/win_fixed.py の pfb_fixed と bit 単位で照合。k ごと × 入力の途切れ あり / なし
sim-pfb:
	mkdir -p $(PFB_DIR)
	$(PYTHON) sim/check_pfb.py gen $(PFB_DIR)
	$(IVERILOG) -g2005 -Isrc $(if $(filter 1,$(SIM_PFB_POSCTL)),-DPFB_POSCTL) -o $(PFB_DIR)/tb src/cmul.v src/dft16f.v src/pfb_core.v sim/tb_pfb.v
	for k in $(PFB_KS); do for g in 0 1; do \
	  $(VVP) -n $(PFB_DIR)/tb +K=$$k +GAP=$$g +IN=$(PFB_DIR)/x.hex +OUT=$(PFB_DIR)/y_k$${k}_g$${g}.txt +NSAMP=16384 | grep '^pfb:' ; \
	done; done
	SIM_PFB_POSCTL=$(SIM_PFB_POSCTL) $(PYTHON) sim/check_pfb.py check $(PFB_DIR) $(PFB_KS) | tee $(PFB_DIR)/check.log

# ddc_core の単体の sim（NCO → 半帯域 × NS）。入力は pfb_fixed の y。NS 1..8 × d 2 通り × 途切れ あり / なし
sim-ddc:
	mkdir -p $(DDC_DIR)
	$(PYTHON) sim/check_ddc.py gen $(DDC_DIR)
	$(IVERILOG) -g2005 -Isrc $(if $(filter 1,$(SIM_DDC_POSCTL)),-DDDC_POSCTL) -o $(DDC_DIR)/tb $(DDC_RTL) sim/tb_ddc.v
	NB=$$(wc -l < $(DDC_DIR)/y.txt); $(PYTHON) sim/check_ddc.py cases | while read ns dp; do for g in 0 1; do \
	  $(VVP) -n $(DDC_DIR)/tb +NS=$$ns +DPHI=$$dp +GAP=$$g +NBEAT=$$NB +IN=$(DDC_DIR)/y.txt +OUT=$(DDC_DIR)/z_ns$${ns}_d$${dp}_g$${g}.txt | grep '^ddc:' ; \
	done; done
	SIM_DDC_POSCTL=$(SIM_DDC_POSCTL) $(PYTHON) sim/check_ddc.py check $(DDC_DIR) | tee $(DDC_DIR)/check.log

# pfb_core → ddc_core をつないだ sim（つなぎ目の試験。8 通りの幅、NS ≦ 6 は 1 本 1 分級・NS 7・8 は 4 倍の長さ）
sim-win:
	mkdir -p $(WIN_DIR)
	$(PYTHON) sim/check_win.py gen $(WIN_DIR)
	$(IVERILOG) -g2005 -Isrc $(if $(filter g,$(SIM_WIN_POSCTL)),-DDDC_POSCTL_G) -o $(WIN_DIR)/tb src/cmul.v src/dft16f.v src/pfb_core.v $(DDC_RTL) sim/tb_win.v
	$(PYTHON) sim/check_win.py cases | while read k ns dp nsamp; do \
	  $(VVP) -n $(WIN_DIR)/tb +K=$$k +NS=$$ns +DPHI=$$dp +GAP=1 +NSAMP=$$nsamp +IN=$(WIN_DIR)/x.hex +OUT=$(WIN_DIR)/z_k$${k}_ns$${ns}.txt | grep '^win:' ; \
	done
	SIM_WIN_POSCTL=$(SIM_WIN_POSCTL) $(PYTHON) sim/check_win.py check $(WIN_DIR) | tee $(WIN_DIR)/check.log
# 陽性対照（proj015）: G の切り替え（NS ≧ 7 で G = 5）を外す → NS 7・8 だけが落ちること
sim-win-g:
	$(MAKE) --no-print-directory sim-win SIM_WIN_POSCTL=g

# wspec_core の単体の sim（溜め → FFT のモデル → 電力 → 積分・スナップショット・帳簿）。4 層の判定（sim/check_wspec.py）
sim-wspec:
	mkdir -p $(WSPEC_DIR)
	$(PYTHON) sim/check_wspec.py gen $(WSPEC_DIR)
	$(IVERILOG) -g2005 -Isrc $(if $(filter 1,$(SIM_WSPEC_POSCTL)),-DWSPEC_POSCTL)$(if $(filter 2,$(SIM_WSPEC_POSCTL)),-DWSPEC_NOREADY) -o $(WSPEC_DIR)/tb src/wspec_core.v sim/win_fft_model.v sim/tb_wspec.v
	rm -f $(WSPEC_DIR)/check.log
	for v in $(WSPEC_VARS); do \
	  nm=$${v%%:*}; r=$${v#*:}; na=$${r%%:*}; r=$${r#*:}; nd=$${r%%:*}; r=$${r#*:}; sh=$${r%%:*}; r=$${r#*:}; gp=$${r%%:*}; r=$${r#*:}; rd=$${r%%:*}; st=$${r#*:}; \
	  mkdir -p $(WSPEC_DIR)/$$nm; \
	  $(VVP) -n $(WSPEC_DIR)/tb +NACC=$$na +NDUMP=$$nd +SHIFT=$$sh +GAP=$$gp +FFT_RDLY=$$rd +FFT_STALL=$$st +IN=$(WSPEC_DIR)/z.txt +DIR=$(WSPEC_DIR)/$$nm | grep '^wspec:' ; \
	  echo "== $$nm" >> $(WSPEC_DIR)/check.log; \
	  SIM_WSPEC_POSCTL=$(SIM_WSPEC_POSCTL) $(PYTHON) sim/check_wspec.py check $(WSPEC_DIR)/$$nm $$na $$nd $$sh $$rd $$st >> $(WSPEC_DIR)/check.log; \
	done
	@cat $(WSPEC_DIR)/check.log | grep -v "  OK"
sim-wspec-p:
	$(MAKE) --no-print-directory sim-wspec SIM_WSPEC_POSCTL=1 WSPEC_VARS=g0:4:4:4:0:5:0
sim-wspec-r:
	$(MAKE) --no-print-directory sim-wspec SIM_WSPEC_POSCTL=2 WSPEC_VARS="$(WSPEC_NR_VARS)"

# sim を全部並べる（iverilog は 1 本 1 コア）。成否は各 check.log の「結果: 全部通過」で読む（make の成功を信用しない）
sim-win-all:
	$(MAKE) --no-print-directory -j8 sim-pfb sim-ddc sim-win sim-wspec sim-pfb-p sim-ddc-p sim-wspec-p sim-wspec-r sim-win-g
	@grep -H "結果" build-sim-*/check.log
sim-pfb-p:
	$(MAKE) --no-print-directory sim-pfb SIM_PFB_POSCTL=1
sim-ddc-p:
	$(MAKE) --no-print-directory sim-ddc SIM_DDC_POSCTL=1

# FFT IP 単体の資源（ライセンスが要る。並列で 10〜20 分の見込み）。結果は build-survey/survey.txt
survey:
	mkdir -p build-survey
	$(VIVADO) -mode batch -nojournal -log build-survey/vivado.log -source tools/ip_survey.tcl -tclargs $(JOBS)

# win_core を AXI4-Lite 越しに端から端まで（x → pfb → ddc → wspec、NS = 1、ダンプ 3 個を AXI で全部読む）。iverilog で 30 分級
sim-top:
	mkdir -p build-sim-top/ns1
	$(PYTHON) sim/check_top.py gen build-sim-top 1
	$(IVERILOG) -g2005 -Isrc -o build-sim-top/tb src/cmul.v src/dft16f.v src/pfb_core.v $(DDC_RTL) src/wspec_core.v src/win_core.v sim/win_fft_model.v sim/tb_top.v
	$(VVP) -n build-sim-top/tb +K=5 +DPHI=3977774351 +NS=1 +NACC=2 +NDUMP=3 +SHIFT=4 +GAP=1 +NSAMP=917504 +IN=build-sim-top/x.hex +DIR=build-sim-top/ns1 | grep '^tb_top:'
	$(PYTHON) sim/check_top.py check build-sim-top 1 2 3 4 | tee build-sim-top/check.log

# spec_core の sim と窓の sim を全部
sim-all:
	$(MAKE) --no-print-directory sim-spec-all
	$(MAKE) --no-print-directory sim-win-all
