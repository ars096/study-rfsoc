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

# part。proj015: **既定を -1 に**（実機の .bit を -1 で配置配線する。PS には src/ps_preset.tcl を当てる。build.tcl の冒頭）。
# -2（board_part ＋ プリセット、proj014 までの build/ の作り）は PART=xczu48dr-ffvg1517-2-e → build-2-e/
PART_DEFAULT := xczu48dr-ffvg1517-1-e
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
#   build/            -1・res（proj015 から）   build-perf/      -1・perf
#   build-2-e/        -2・res                   build-2-e-perf/  -2・perf
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

# proj015 rev2: 実装の戦略（impl_1 の strategy）。空なら Vivado の既定。例: make IMPL=Performance_Explore → build-pe/ など
# **`-1` が閉じないときの次の手**。戦略を変えても RTL は同じなので ID は変わらない（BUILD_TAG も同じ）。PS は build/ の .bit を使う
IMPL ?=
ifneq ($(IMPL),)
  OUTDIR := $(OUTDIR)-$(shell echo $(IMPL) | tr -cd 'A-Z')
endif

# 同時に走らせる run の数（launch_runs -jobs）。効くのは IP の OOC 合成だけ。
# proj010 から lane_fft（FFT IP）の OOC 合成が 1 本増えている（proj011 も同じ）。ビルドサーバの nproc = 32 に合わせてある。
# コア数やメモリの少ない機械では `make JOBS=8` に下げること。
JOBS ?= 30

export BOARD_REPO PART OUTDIR FFT_OPT GB_K GB_SLOW GB_SLOW_SITE IMPL

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
RTL       := src/spec_core.v src/tp_core.v src/cmul.v src/dft16.v src/tw_rom.v src/dstamp.v src/adc_ev.v

.PHONY: sim-time sim-time-p sim-wstamp sim-wstamp-p sim-tsys sim-tsys-p sim-wdelay sim-t-all sim-t4adc sim-t4adc-p sim-wgrid sim-wgrid-p
.PHONY: all sim sim-gb sim-tp sim-all sim-spec-all gb-cdc worst-paths survey twiddle prog id timing-check ps-preset clean

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
# proj017: SIM_TP_POSCTL=2 は振り切れの FLAGS[4] の陽性対照（しきい値の ≧ を > に。+32764 を見落とすはず）
SIMTPDIR := build-sim-tp$(if $(filter 1,$(SIM_TP_POSCTL)),-posctl)$(if $(filter 2,$(SIM_TP_POSCTL)),-ovrpc)
sim-tp:
	mkdir -p $(SIMTPDIR)
	$(PYTHON) sim/check_tp.py gen $(SIMTPDIR)
	$(IVERILOG) -g2005 $(if $(filter 1,$(SIM_TP_POSCTL)),-DTP_POSCTL) $(if $(filter 2,$(SIM_TP_POSCTL)),-DTP_OVR_POSCTL) -DOUT=\"$(SIMTPDIR)\" $$(cat $(SIMTPDIR)/tp_defs) -o $(SIMTPDIR)/tb src/tp_core.v sim/tb_tp_core.v
	$(VVP) -n $(SIMTPDIR)/tb
	$(PYTHON) sim/check_tp.py check $(SIMTPDIR) $(if $(filter 1,$(SIM_TP_POSCTL)),posctl)$(if $(filter 2,$(SIM_TP_POSCTL)),ovr)

# ---- 配置配線後の dcp で gb_fifo の gray ポインタの乗り換えをビットごとに測る（rev6。ビルド不要、数分）----
# DCP を指定しなければ build/ の dcp。結果は dcp と同じ場所の gb_cdc.txt
DCP ?= $(firstword $(wildcard $(OUTDIR)/vivado/proj016.runs/impl_1/*_routed.dcp))
gb-cdc:
	@test -n "$(DCP)" || { echo "DCP が無い（make gb-cdc DCP=...）"; exit 1; }
	$(VIVADO) -mode batch -nojournal -nolog -source tools/gb_cdc.tcl -tclargs $(DCP) $(dir $(DCP))gb_cdc.txt

# ---- 配置配線後の dcp で setup / hold の最悪経路の中身を読む（rev3。ビルド不要、数分）----
# DCP は gb-cdc と同じ既定（$(OUTDIR) の dcp）。proj015 から既定の build/ が -1（-2 は PART=xczu48dr-ffvg1517-2-e）。
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
	$(MAKE) --no-print-directory -j$(words $(SIM_VARIANTS) gb tp tpp tpo) $(addprefix sim-v-,$(SIM_VARIANTS)) sim-v-gb sim-v-tp sim-v-tpp sim-v-tpo
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

sim-v-tpo:
	-$(MAKE) --no-print-directory sim-tp SIM_TP_POSCTL=2 > build-sim-logs/sim-tp-ovrpc.log 2>&1

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
# proj015: 既定が -1 になったので `make` と同じ（build/）。互換のために残す
timing-check:
	$(MAKE)

# ボードプリセットが PS に当てる設定を src/ps_preset.tcl に書き出す（proj015。BOARD_REPO が要る。数分）。
# 書き直したら git diff で中身を見てからコミットする
ps-preset:
	mkdir -p build-ps-preset
	$(VIVADO) -mode batch -nojournal -log build-ps-preset/vivado.log -source tools/dump_ps_preset.tcl

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
DDC_RTL       := src/nco_rom.v src/hb2.v src/hb2s.v src/pair2.v src/ddc_core.v
WIN_DIR       := build-sim-win$(if $(SIM_WIN_POSCTL),-$(SIM_WIN_POSCTL))
# SIM_WSPEC_POSCTL=1: 陽性対照（RTL の積分で初回のフレームでも読み値に足す）→ A が落ちること
# SIM_WSPEC_POSCTL=2: 陽性対照（RTL が FFT IP の tready を見ない = rev1、-DWSPEC_NOREADY）→ B が落ちること
SIM_WSPEC_POSCTL ?= 0
WSPEC_DIR     := build-sim-wspec$(if $(filter 1,$(SIM_WSPEC_POSCTL)),-posctl)$(if $(filter 2,$(SIM_WSPEC_POSCTL)),-noready)$(if $(filter 3,$(SIM_WSPEC_POSCTL)),-pfbrev)$(if $(filter 1,$(SIM_WSPEC_SAT)),-sat)
# 変種: 名前:NACC:NDUMP:SHIFT:GAP:RDLY:STALL（GAP 0 = 途切れなし = 256 MHz 窓 / 3 / 32 = 8 MHz 窓の速さ。
#   RDLY = FFT のモデルの tready が解除から 0 のクロック数（既定 5。6000 は最初のフレームが溜まっても IP が受けない = 実機 1 回目の形）/
#   STALL = 3·4096 + 1234 クロックごとに tready を 0 にするクロック数）
WSPEC_VARS    ?= g0:4:4:4:0:5:0 g3:2:4:7:3:5:0 g32:1:3:4:32:5:0 g0r:4:4:4:0:6000:0 g3s:2:4:7:3:5:40 e0:4:4:4:0:5:0
WSPEC_NR_VARS ?= g0r:4:4:4:0:6000:0 g3s:2:4:7:3:5:40


.PHONY: model model-posctl model-sweep fixed fixed-posctl coef sim-pfb sim-ddc sim-win sim-win-g sim-win-ts sim-hb2s sim-pfbm sim-pfbm-p sim-win-all sim-pfb-p sim-ddc-p sim-wspec sim-wspec-p sim-wspec-r sim-top sim-win4 survey ooc-ddc clean

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

# pfb_core を 4 窓で（proj015 手順 3）。窓ごとに別の k・別の始まり、窓 3 は途中で打ち直す。変種: 途切れ なし / あり、
# ビートの番号 8 bit（4096 ビートで 16 回巻き戻る）。成否は $(PFBM_DIR)/check.log の「結果」。
# SIM_PFBM_POSCTL=1: 陽性対照（(−j)^(k·m') の偶奇を窓の始まりで揃えない）→ どこかの区切りが NG
SIM_PFBM_POSCTL ?= 0
PFBM_DIR := build-sim-pfbm$(if $(filter 1,$(SIM_PFBM_POSCTL)),-posctl)
PFBM_VARS ?= g0:32 g1:32 g1:8
sim-pfbm:
	mkdir -p $(PFBM_DIR); rm -f $(PFBM_DIR)/check.log
	$(PYTHON) sim/check_pfbm.py gen $(PFBM_DIR)
	for v in $(PFBM_VARS); do g=$${v%%:*}; q=$${v#*:}; g=$${g#g}; mkdir -p $(PFBM_DIR)/$$v; \
	  $(IVERILOG) -g2005 -Isrc -DPFB_QW=$$q $(if $(filter 1,$(SIM_PFBM_POSCTL)),-DPFBM_POSCTL) -o $(PFBM_DIR)/tb_$$q src/cmul.v src/dft16f.v src/pfb_core.v sim/tb_pfbm.v && \
	  $(VVP) -n $(PFBM_DIR)/tb_$$q +GAP=$$g +IN=$(PFBM_DIR)/x.hex +DIR=$(PFBM_DIR)/$$v | grep '^pfbm:' ; \
	  echo "== $$v" >> $(PFBM_DIR)/check.log; \
	  SIM_PFBM_POSCTL=$(SIM_PFBM_POSCTL) $(PYTHON) sim/check_pfbm.py check $(PFBM_DIR)/$$v $$q >> $(PFBM_DIR)/check.log; \
	done
	@cat $(PFBM_DIR)/check.log
	@n=$$(grep -c '結果: 全部通過' $(PFBM_DIR)/check.log); if [ $$n -eq $(words $(PFBM_VARS)) ]; then echo "結果: 全部通過（$$n 変種）" | tee -a $(PFBM_DIR)/check.log; else echo "結果: 失敗（通過 $$n / $(words $(PFBM_VARS))）" | tee -a $(PFBM_DIR)/check.log; fi
sim-pfbm-p:
	$(MAKE) --no-print-directory sim-pfbm SIM_PFBM_POSCTL=1 PFBM_VARS=g1:32

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
	$(IVERILOG) -g2005 -Isrc $(if $(filter g,$(SIM_WIN_POSCTL)),-DDDC_POSCTL_G)$(if $(filter ts,$(SIM_WIN_POSCTL)),-DDDC_POSCTL_TS) -o $(WIN_DIR)/tb src/cmul.v src/dft16f.v src/pfb_core.v $(DDC_RTL) sim/tb_win.v
	$(PYTHON) sim/check_win.py cases | while read k ns dp nsamp; do \
	  $(VVP) -n $(WIN_DIR)/tb +K=$$k +NS=$$ns +DPHI=$$dp +GAP=1 +NSAMP=$$nsamp +IN=$(WIN_DIR)/x.hex +OUT=$(WIN_DIR)/z_k$${k}_ns$${ns}.txt | grep '^win:' ; \
	done
	SIM_WIN_POSCTL=$(SIM_WIN_POSCTL) $(PYTHON) sim/check_win.py check $(WIN_DIR) | tee $(WIN_DIR)/check.log
# hb2s（時分割の半帯域）が hb2 と bit 単位で同じか（proj015）。light の C 1・2・4・5・8、final の C 2・4・18。
# 陽性対照: 組の間隔を C より短く（前提を破る）→ ovr が立って一致しないこと。成否は build-sim-hb2s/check.log の「結果」
HB2S_CASES := 1:0:1 2:0:2 4:0:4 5:0:5 8:0:8 2:1:2 4:1:4 18:1:18
HB2S_NEG   := 4:0:3 2:0:1
sim-hb2s:
	mkdir -p build-sim-hb2s; rm -f build-sim-hb2s/check.log
	for v in $(HB2S_CASES) $(HB2S_NEG); do c=$${v%%:*}; r=$${v#*:}; f=$${r%%:*}; g=$${r#*:}; \
	  $(IVERILOG) -g2005 -Isrc -DHB_C=$$c $$( [ $$f = 1 ] && echo -DHB_FINAL ) -o build-sim-hb2s/tb_$${c}_$${f} src/hb2.v src/hb2s.v sim/tb_hb2s.v && \
	  $(VVP) -n build-sim-hb2s/tb_$${c}_$${f} +GAP=$$g +NPAIR=20000 | grep '^hb2s:' | tr '\n' ' ' >> build-sim-hb2s/check.log; echo " [$$v]" >> build-sim-hb2s/check.log; done
	@cat build-sim-hb2s/check.log
	@n_ok=$$(for v in $(HB2S_CASES); do grep "\[$$v\]" build-sim-hb2s/check.log; done | grep -c 'hb2s: 一致'); \
	 n_neg=$$(for v in $(HB2S_NEG); do grep "\[$$v\]" build-sim-hb2s/check.log; done | grep -c 'hb2s: 不一致'); \
	 if [ $$n_ok -eq $(words $(HB2S_CASES)) ] && [ $$n_neg -eq $(words $(HB2S_NEG)) ]; then echo "結果: 全部通過（一致 $$n_ok・陽性対照 $$n_neg）" | tee -a build-sim-hb2s/check.log; \
	 else echo "結果: 失敗（一致 $$n_ok / $(words $(HB2S_CASES))・陽性対照 $$n_neg / $(words $(HB2S_NEG))）" | tee -a build-sim-hb2s/check.log; fi

# 陽性対照（proj015）: G の切り替え（NS ≧ 7 で G = 5）を外す → NS 7・8 だけが落ちること
sim-win-g:
	$(MAKE) --no-print-directory sim-win SIM_WIN_POSCTL=g
# 陽性対照（proj015 手順 2）: light の 2 段目の時分割の C を 1 つ大きく → 追い越しが立ち、NS 3..8 だけが落ちること
sim-win-ts:
	$(MAKE) --no-print-directory sim-win SIM_WIN_POSCTL=ts

# wspec_core の単体の sim（溜め → FFT のモデル → 電力 → 積分・スナップショット・帳簿）。4 層の判定（sim/check_wspec.py）
sim-wspec:
	mkdir -p $(WSPEC_DIR)
	SIM_WSPEC_SAT=$(SIM_WSPEC_SAT) $(PYTHON) sim/check_wspec.py gen $(WSPEC_DIR)
	$(IVERILOG) -g2005 -Isrc $(if $(filter 1,$(SIM_WSPEC_POSCTL)),-DWSPEC_POSCTL)$(if $(filter 2,$(SIM_WSPEC_POSCTL)),-DWSPEC_NOREADY)$(if $(filter 3,$(SIM_WSPEC_POSCTL)),-DWSPEC_PFB_POSCTL) -o $(WSPEC_DIR)/tb src/wspec_core.v src/dstamp.v src/pfb4_rom.v sim/win_fft_model.v sim/tb_wspec.v
	rm -f $(WSPEC_DIR)/check.log
	for v in $(WSPEC_VARS); do \
	  nm=$${v%%:*}; r=$${v#*:}; na=$${r%%:*}; r=$${r#*:}; nd=$${r%%:*}; r=$${r#*:}; sh=$${r%%:*}; r=$${r#*:}; gp=$${r%%:*}; r=$${r#*:}; rd=$${r%%:*}; st=$${r#*:}; \
	  mkdir -p $(WSPEC_DIR)/$$nm; ru=3; case $$nm in e*) ru=0;; esac; \
	  $(VVP) -n $(WSPEC_DIR)/tb +RUNAT=$$ru +NACC=$$na +NDUMP=$$nd +SHIFT=$$sh +GAP=$$gp +FFT_RDLY=$$rd +FFT_STALL=$$st +IN=$(WSPEC_DIR)/z.txt +DIR=$(WSPEC_DIR)/$$nm | grep '^wspec:' ; \
	  echo "== $$nm" >> $(WSPEC_DIR)/check.log; \
	  SIM_WSPEC_SAT=$(SIM_WSPEC_SAT) SIM_WSPEC_POSCTL=$(SIM_WSPEC_POSCTL) $(PYTHON) sim/check_wspec.py check $(WSPEC_DIR)/$$nm $$na $$nd $$sh $$rd $$st >> $(WSPEC_DIR)/check.log; \
	done
	@cat $(WSPEC_DIR)/check.log | grep -v "  OK"
sim-wspec-p:
	$(MAKE) --no-print-directory sim-wspec SIM_WSPEC_POSCTL=1 WSPEC_VARS=g0:4:4:4:0:5:0
sim-wspec-r:
	$(MAKE) --no-print-directory sim-wspec SIM_WSPEC_POSCTL=2 WSPEC_VARS="$(WSPEC_NR_VARS)"
# proj020: ch の間ちょうどの強い CW で PFB の出口を飽和させ、FLAGS[5] が立つこと・飽和した値も模型と bit 単位で一致すること
sim-wspec-sat:
	$(MAKE) --no-print-directory sim-wspec SIM_WSPEC_SAT=1 WSPEC_VARS=g0:4:4:4:0:5:0
# proj020: PFB のフレームの順を逆に → スナップショットの照合が落ちること
sim-wspec-pfb:
	$(MAKE) --no-print-directory sim-wspec SIM_WSPEC_POSCTL=3 WSPEC_VARS=g0:4:4:4:0:5:0

# sim を全部並べる（iverilog は 1 本 1 コア）。成否は各 check.log の「結果: 全部通過」で読む（make の成功を信用しない）
sim-win-all:
	$(MAKE) --no-print-directory -j8 sim-pfb sim-ddc sim-win sim-wspec sim-pfb-p sim-ddc-p sim-wspec-p sim-wspec-r sim-wspec-pfb sim-wspec-sat sim-win-g sim-win-ts sim-hb2s sim-pfbm sim-pfbm-p
	@grep -H "結果" build-sim-*/check.log
sim-pfb-p:
	$(MAKE) --no-print-directory sim-pfb SIM_PFB_POSCTL=1
sim-ddc-p:
	$(MAKE) --no-print-directory sim-ddc SIM_DDC_POSCTL=1

# ddc_core 単体の資源（proj015 手順 2）。時分割あり（TS = 1）となし（TS = 0）。結果は build-ooc-ddc/ooc.txt（ライセンスが要る）
ooc-ddc:
	mkdir -p build-ooc-ddc
	$(VIVADO) -mode batch -nojournal -log build-ooc-ddc/vivado.log -source tools/ooc_ddc.tcl

# FFT IP 単体の資源（ライセンスが要る。並列で 10〜20 分の見込み）。結果は build-survey/survey.txt
survey:
	mkdir -p build-survey
	$(VIVADO) -mode batch -nojournal -log build-survey/vivado.log -source tools/ip_survey.tcl -tclargs $(JOBS)

# win_core を AXI4-Lite 越しに端から端まで（x → pfb → ddc → wspec、NS = 1、ダンプ 3 個を AXI で全部読む）。iverilog で 30 分級
sim-top:
	mkdir -p build-sim-top/ns1
	$(PYTHON) sim/check_top.py gen build-sim-top 1
	$(IVERILOG) -g2005 -Isrc -o build-sim-top/tb src/cmul.v src/dft16f.v src/pfb_core.v $(DDC_RTL) src/wspec_core.v src/dstamp.v src/pfb4_rom.v src/tp_core.v src/win_core.v src/adc_ev.v sim/win_fft_model.v sim/tb_top.v
	$(VVP) -n build-sim-top/tb +K=5 +DPHI=3977774351 +NS=1 +NACC=2 +NDUMP=3 +SHIFT=4 +GAP=1 +NSAMP=917504 +IN=build-sim-top/x.hex +DIR=build-sim-top/ns1 | grep '^tb_top:'
	$(PYTHON) sim/check_top.py check build-sim-top 1 2 3 4 | tee build-sim-top/check.log

# win_core を 1 ADC × 4 窓（NW = 4）で AXI 越しに（proj015 手順 4）。窓ごとに別の k・d・NS・WRST の時刻、窓 1 のスナップショット（SNAP_SEL）。
# iverilog で 1 時間級。成否は build-sim-win4/check.log の「総合: 結果」
sim-win4:
	mkdir -p build-sim-win4
	$(PYTHON) sim/check_win4.py gen build-sim-win4
	$(IVERILOG) -g2005 -Isrc -o build-sim-win4/tb src/cmul.v src/dft16f.v src/pfb_core.v $(DDC_RTL) src/wspec_core.v src/dstamp.v src/pfb4_rom.v src/tp_core.v src/win_core.v src/adc_ev.v sim/win_fft_model.v sim/tb_win4.v
	$(VVP) -n build-sim-win4/tb +IN=build-sim-win4/x.hex +CFG=build-sim-win4/cfg.txt +DIR=build-sim-win4 +NSAMP=1048576 | grep '^tb_win4:'
	$(PYTHON) sim/check_win4.py check build-sim-win4 | tee build-sim-win4/check.log

# ---- proj016: 時刻・設定番号・健全性の sim ----
# sim-time: time_core 単体（S-T1）。陽性対照 sim-time-p（発火を 1 クロック早く）は「結果: 失敗」になること
TIME_DIR := build-sim-time
sim-time:
	mkdir -p $(TIME_DIR)
	$(IVERILOG) -g2005 -Isrc $(if $(filter 1,$(SIM_TIME_POSCTL)),-DTIME_POSCTL) -o $(TIME_DIR)/tb$(SIM_TIME_POSCTL) src/time_core.v sim/tb_time.v
	$(VVP) -n $(TIME_DIR)/tb$(SIM_TIME_POSCTL) | grep '^tb_time:' | tee $(TIME_DIR)/check$(SIM_TIME_POSCTL).log
sim-time-p:
	$(MAKE) --no-print-directory sim-time SIM_TIME_POSCTL=1
# sim-wstamp: wspec_core ＋ dstamp（S-T2）。変種 名前:NACC:NDUMP:GAP:FFT_LAT。L は FFT の遅れを大きく（N = 1 で輪の深さを試す）
WSTAMP_VARS ?= n2:2:6:0:200 n1:1:10:0:200 g3:1:6:3:200 L1:1:12:0:9000
WSTAMP_DIR  := build-sim-wstamp$(if $(filter 1,$(SIM_WSTAMP_POSCTL)),-posctl)
sim-wstamp:
	mkdir -p $(WSTAMP_DIR); rm -f $(WSTAMP_DIR)/check.log
	for v in $(WSTAMP_VARS); do nm=$${v%%:*}; r=$${v#*:}; na=$${r%%:*}; r=$${r#*:}; nd=$${r%%:*}; r=$${r#*:}; gp=$${r%%:*}; lat=$${r#*:}; \
	  $(IVERILOG) -g2005 -Isrc -DFFT_LAT=$$lat $(if $(filter 1,$(SIM_WSTAMP_POSCTL)),-DDSTAMP_POSCTL) -o $(WSTAMP_DIR)/tb_$$nm src/wspec_core.v src/dstamp.v src/pfb4_rom.v sim/win_fft_model.v sim/tb_wstamp.v && \
	  $(VVP) -n $(WSTAMP_DIR)/tb_$$nm +NACC=$$na +NDUMP=$$nd +GAP=$$gp | grep '^wstamp:' | sed "s/^/[$$nm] /" >> $(WSTAMP_DIR)/check.log; done
	@cat $(WSTAMP_DIR)/check.log
	@n=$$(grep -c '結果: 全部通過' $(WSTAMP_DIR)/check.log); if [ $$n -eq $(words $(WSTAMP_VARS)) ]; then echo "結果: 全部通過（$$n 変種）" | tee -a $(WSTAMP_DIR)/check.log; \
	 else echo "結果: 失敗（通過 $$n / $(words $(WSTAMP_VARS))）" | tee -a $(WSTAMP_DIR)/check.log; fi
# 陽性対照: スタンプを 1 ビートずらす → 失敗になること（成否は「結果: 失敗」）
sim-wstamp-p:
	$(MAKE) --no-print-directory sim-wstamp SIM_WSTAMP_POSCTL=1 WSTAMP_VARS=n2:2:4:0:200
# sim-tsys: time_core ＋ win_core（NW 2）＋ spec_core（S-T3・S-T4・系での S-T2）。iverilog で 1〜2 時間級（FFT のモデルが重い）
#   陽性対照 sim-tsys-p: SHIFT・CFG を RUN で取り込まない（-DWIN_POSCTL_SHIFT -DSPEC_POSCTL_SHIFT）→ 3 が落ちること
TSYS_DIR := build-sim-tsys$(if $(filter 1,$(SIM_TSYS_POSCTL)),-posctl)
sim-tsys:
	mkdir -p $(TSYS_DIR)
	$(IVERILOG) -g2005 -Isrc $(if $(filter 1,$(SIM_TSYS_POSCTL)),-DWIN_POSCTL_SHIFT -DSPEC_POSCTL_SHIFT) -o $(TSYS_DIR)/tb src/time_core.v src/cmul.v src/dft16f.v src/pfb_core.v $(DDC_RTL) \
	  src/wspec_core.v src/dstamp.v src/pfb4_rom.v src/tp_core.v src/win_core.v src/adc_ev.v src/spec_core.v src/dft16.v src/tw_rom.v sim/win_fft_model.v sim/lane_fft_model.v sim/tb_tsys.v
	$(VVP) -n $(TSYS_DIR)/tb | grep '^tb_tsys:' | tee $(TSYS_DIR)/check.log
sim-tsys-p:
	$(MAKE) --no-print-directory sim-tsys SIM_TSYS_POSCTL=1
# proj017 S-4: wspec_core × 6（NS 1..6、格子を 2^17 ビートに縮める）。F0 = (⌊fin / M⌋ + 2)·M で、幅の違う窓のダンプの区切りが
#   サンプルの時刻で揃うこと。陽性対照 sim-wgrid-p（格子に寄せない）→ 落ちるべき。成否は「結果:」の行
WGRID_DIR := build-sim-wgrid$(if $(filter 1,$(SIM_WGRID_POSCTL)),-posctl)
sim-wgrid:
	mkdir -p $(WGRID_DIR)
	$(IVERILOG) -g2005 -Isrc $(if $(filter 1,$(SIM_WGRID_POSCTL)),-DWSPEC_NOGRID) -o $(WGRID_DIR)/tb src/wspec_core.v src/dstamp.v src/pfb4_rom.v sim/win_fft_model.v sim/tb_wgrid.v
	$(VVP) -n $(WGRID_DIR)/tb | grep '^wgrid:' | tee $(WGRID_DIR)/check.log
sim-wgrid-p:
	$(MAKE) --no-print-directory sim-wgrid SIM_WGRID_POSCTL=1
# proj017 S-2: time_core 1 個 ＋ win_core（NW 2）× 4。8 窓と TP 4 本が同じクロックに RUN を受けること。陽性対照 sim-t4adc-p
#   （ADC 3 の時刻のバスを 1 段遅らせる → 落ちるべき）。成否は「結果:」の行
T4_DIR := build-sim-t4adc$(if $(filter 1,$(SIM_T4_POSCTL)),-posctl)
sim-t4adc:
	mkdir -p $(T4_DIR)
	$(IVERILOG) -g2005 -Isrc $(if $(filter 1,$(SIM_T4_POSCTL)),-DT4_POSCTL) -o $(T4_DIR)/tb src/time_core.v src/cmul.v src/dft16f.v src/pfb_core.v $(DDC_RTL) \
	  src/wspec_core.v src/dstamp.v src/pfb4_rom.v src/tp_core.v src/win_core.v src/adc_ev.v sim/win_fft_model.v sim/tb_t4adc.v
	$(VVP) -n $(T4_DIR)/tb | grep '^tb_t4adc:' | tee $(T4_DIR)/check.log
sim-t4adc-p:
	$(MAKE) --no-print-directory sim-t4adc SIM_T4_POSCTL=1
# sim-wdelay: 窓の遅れ D(NS)（ADC のビート → z が wspec に入るまで）。pynq/timebase.py の WIN_DELAY_BEATS の出どころ
sim-wdelay:
	mkdir -p build-sim-wdelay
	$(IVERILOG) -g2005 -Isrc -o build-sim-wdelay/tb src/cmul.v src/dft16f.v src/pfb_core.v $(DDC_RTL) sim/tb_wdelay.v
	for n in 1 2 3 4 5 6 7 8; do $(VVP) -n build-sim-wdelay/tb +NS=$$n +LEN=$$(( n < 4 ? 8000 : 1000 << (n - 2) )) | grep -E '^(wdelay|wfirst):'; done | tee build-sim-wdelay/delay.log
sim-t-all:
	$(MAKE) --no-print-directory -j4 sim-time sim-time-p sim-wstamp sim-wstamp-p sim-t4adc sim-t4adc-p sim-wgrid sim-wgrid-p
	@grep -H "結果" build-sim-time/check.log build-sim-time/check1.log build-sim-wstamp/check.log build-sim-wstamp-posctl/check.log \
	  build-sim-t4adc/check.log build-sim-t4adc-posctl/check.log build-sim-wgrid/check.log build-sim-wgrid-posctl/check.log

# spec_core の sim と窓の sim を全部（proj016: ＋ 時刻の速い sim。sim-tsys・sim-win4 は別に回す）
sim-all:
	$(MAKE) --no-print-directory sim-spec-all
	$(MAKE) --no-print-directory sim-win-all
	$(MAKE) --no-print-directory sim-t-all
