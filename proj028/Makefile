# SPDX-License-Identifier: BSD-3-Clause
# Vivado のインストール先をここで持つ。
# settings64.sh を .bashrc で source しないこと（Xilinx 同梱の古い共有ライブラリが
# LD_LIBRARY_PATH の先頭に入り、git / ssh / python が壊れる）。
# bin/vivado は起動スクリプト自身が環境を組み立てるので、絶対パスで叩けば動く。
#
# proj001 は 2023.2。proj002 から 2024.1 に上げる（BSP と PYNQ v3.1.1 が前提とする版）。
XILINX_VIVADO ?= /tools/Xilinx/Vivado/2024.1
VIVADO        := $(XILINX_VIVADO)/bin/vivado

# RealDigitalOrg/RFSoC4x2-BSP を clone した先の board_files ディレクトリ。
# Vivado のインストールツリーの中には置かない（VERSIONS.md 参照）。
BOARD_REPO ?= $(HOME)/src/RFSoC4x2-BSP/board_files

# part。S-2 の .bit は実機と同じ -1 だけを作る（PS は src/board/ps_preset.tcl を当てる。proj015 から）
PART ?= xczu48dr-ffvg1517-1-e
OUTDIR := build

# 同時に走らせる run の数（launch_runs -jobs）。
# **効くのは IP の OOC 合成だけ。**impl_1 は単一の run なので、いくつにしても 1 つしか走らない。
# 2026-09-17 の proj006 の実測: IP 合成 + synth = 3分43秒 / impl = 5分44秒。
# つまり **-jobs が効くのは全体の 4 割**で、残りは general.maxThreads（既定 8）の領域。
#
# ビルドサーバの nproc = 32 に合わせてある。
# **コア数やメモリの少ない機械では下げること** — run 1 個が独立した Vivado プロセスで
# 数 GB 食うので、8 コアの機械で 30 にするとメモリを食い潰して逆に遅くなる。
# `make JOBS=8` で上書きできる。
JOBS ?= 8
PROJ ?= proj028

export BOARD_REPO PART OUTDIR

PYTHON ?= python3

.PHONY: all build prog id timing-check clean model-m1 model-m2 model-m3 model-m4 estimate sim-cfft32 sim-cpfb sim-cstage sim-ctwr sim-ctrd sim-fpfb sim-fchain sim-facc s1 sim-ddrtg f5ooc f5 f5-pe

# S-2: PL DDR4 の帯域と容量を測る .bit（PS ＋ MIG ＋ ddr_tg。この PC の Vivado、1 時間前後）。成果物は build/proj028.bit・.hwh。
# 成否は make の終了状態でなく build/vivado.log の「TIMING (確定)」「CRITICAL WARNING: n 件」「=== wrote」で読む
build:
	mkdir -p $(OUTDIR)
	VIVADO_LOG=$(OUTDIR)/vivado.log $(VIVADO) -mode batch -nojournal -log $(OUTDIR)/vivado.log -source build.tcl -tclargs $(JOBS)

# 模型 M-1（荒い PFB の原型・タップ数・ポリフェーズの形・トーンの折り返し）。numpy だけ、1 分前後。成否は「結果:」の行
model-m1:
	mkdir -p runs
	$(PYTHON) model/m1_coarse.py all | tee runs/m1.log

# 模型 M-2（荒い段の後の再量子化の損失と強い線の余裕）。数十秒
model-m2:
	mkdir -p runs
	$(PYTHON) model/m2_requant.py all | tee runs/m2.log

# 模型 M-3（荒い段の語長: 係数・SH・利得・8 bit）。数秒
model-m3:
	mkdir -p runs
	$(PYTHON) model/m3_coarse_fixed.py | tee runs/m3.log

# 模型 M-4（つなぎ: 荒い段 → 細かい FFT → bin の巡回・7/8 → 32 ch。N_f 512 に縮めて）。1〜2 分
model-m4:
	mkdir -p runs
	$(PYTHON) model/m4_stitch.py | tee runs/m4.log

# S-1: 荒い FFT の RTL（tools/gen_cfft32.py が作る src/cfft32.v）を iverilog で模型と照らす。ふつうと陽性対照（落ちるべき）。成否は「結果:」の行
sim-cfft32:
	mkdir -p build-sim
	$(PYTHON) tools/sim_cfft32.py | tee build-sim/sim_cfft32.log
	$(PYTHON) tools/sim_cfft32.py --bad | tee build-sim/sim_cfft32_bad.log

# C-1: 荒い PFB（tools/gen_coarse_pfb.py が作る src/coarse_pfb.v）を model/coarse_pfb_ref.py と bit 単位で照らす。ふつう・valid を落とす・陽性対照（落ちるべき）
sim-cpfb:
	mkdir -p build-sim
	$(PYTHON) tools/sim_coarse_pfb.py > build-sim/sim_cpfb.log & $(PYTHON) tools/sim_coarse_pfb.py --gap > build-sim/sim_cpfb_gap.log & $(PYTHON) tools/sim_coarse_pfb.py --bad > build-sim/sim_cpfb_bad.log & wait
	@grep "結果:" build-sim/sim_cpfb.log build-sim/sim_cpfb_gap.log build-sim/sim_cpfb_bad.log

# C-2: 荒い段（coarse_pfb → cfft32 → coarse_post）を整数の模型（coarse_pfb_ref・cfft32_ref・coarse_post_ref）と bit 単位で照らす。ふつうと陽性対照（奇数の ch の共役を抜く）
sim-cstage:
	mkdir -p build-sim
	$(PYTHON) tools/sim_coarse_stage.py > build-sim/sim_cstage.log & $(PYTHON) tools/sim_coarse_stage.py --bad > build-sim/sim_cstage_bad.log & wait
	@grep "結果:" build-sim/sim_cstage.log build-sim/sim_cstage_bad.log

# C-3: corner turn の書き手 ct_wr。DDR の模型の中身を ch ごとに並べ替えた入力と照らす。QB 4・QB 64・陽性対照（回しを 1 ずらす）・STALL（溢れを数える）
sim-ctwr:
	mkdir -p build-sim
	$(PYTHON) tools/sim_ct_wr.py > build-sim/sim_ctwr.log & $(PYTHON) tools/sim_ct_wr.py --qb 64 > build-sim/sim_ctwr_qb64.log & $(PYTHON) tools/sim_ct_wr.py --bad > build-sim/sim_ctwr_bad.log & $(PYTHON) tools/sim_ct_wr.py --stall > build-sim/sim_ctwr_stall.log & wait
	@grep "結果:" build-sim/sim_ctwr.log build-sim/sim_ctwr_qb64.log build-sim/sim_ctwr_bad.log build-sim/sim_ctwr_stall.log

# C-4: corner turn の読み手 ct_rd。出口の拍の並び・中身・tuser・tlast を期待と照らす。ふつうと陽性対照（末尾の番地を 1 拍ずらす）
sim-ctrd:
	mkdir -p build-sim
	$(PYTHON) tools/sim_ct_rd.py > build-sim/sim_ctrd.log & $(PYTHON) tools/sim_ct_rd.py --bad > build-sim/sim_ctrd_bad.log & wait
	@grep "結果:" build-sim/sim_ctrd.log build-sim/sim_ctrd_bad.log

# F-1: 細かい PFB（fine_pfb ＋ fine_coef）を model/fine_fixed.py と bit 単位で。ふつう・valid を落とす・陽性対照 2 つ（端数・ch の頭）。数分
sim-fpfb:
	mkdir -p build-sim
	$(PYTHON) tools/sim_fine_pfb.py > build-sim/sim_fpfb.log & $(PYTHON) tools/sim_fine_pfb.py --gap > build-sim/sim_fpfb_gap.log & $(PYTHON) tools/sim_fine_pfb.py --frac-err > build-sim/sim_fpfb_frac.log & $(PYTHON) tools/sim_fine_pfb.py --no-ch-reset > build-sim/sim_fpfb_nores.log & wait
	@grep "結果:" build-sim/sim_fpfb.log build-sim/sim_fpfb_gap.log build-sim/sim_fpfb_frac.log build-sim/sim_fpfb_nores.log

# F-2: ひねり係数と鎖（fine_tw ＋ fine_chain）を model/fine_fixed.py の chain_Y ＋ power と bit 単位で。ふつう・陽性対照 2 つ。数分
sim-fchain:
	mkdir -p build-sim
	$(PYTHON) tools/sim_fine_chain.py > build-sim/sim_fch.log & $(PYTHON) tools/sim_fine_chain.py --norm > build-sim/sim_fch_norm.log & $(PYTHON) tools/sim_fine_chain.py --tw-hi-err > build-sim/sim_fch_tw.log & wait
	@grep "結果:" build-sim/sim_fch.log build-sim/sim_fch_norm.log build-sim/sim_fch_tw.log

# F-3: 積分器と読み出し（fine_acc ＋ fine_rdo）。出口を Python の和と並べ替えと照らす。ふつう・陽性対照 2 つ
sim-facc:
	mkdir -p build-sim
	$(PYTHON) tools/sim_fine_acc.py > build-sim/sim_facc.log & $(PYTHON) tools/sim_fine_acc.py --first-err > build-sim/sim_facc_first.log & $(PYTHON) tools/sim_fine_acc.py --k2-err > build-sim/sim_facc_k2.log & wait
	@grep "結果:" build-sim/sim_facc.log build-sim/sim_facc_first.log build-sim/sim_facc_k2.log

# S-1: cfft32・ct_buf・DDR4 IP を OOC で合成して資源を数える（この PC の Vivado、30 分前後）。結果は build-s1/s1.txt
S1_JOBS ?= 4
s1:
	mkdir -p build-s1
	$(VIVADO) -mode batch -nojournal -log build-s1/vivado.log -source tools/s1_ooc.tcl -tclargs $(S1_JOBS)

# S-2: 負荷発生器 ddr_tg の単体の sim（AXI4 のメモリの模型）。ふつうと陽性対照（-DALIAS: 4 GB で番地が折り返す模型）を並べて回す。成否は各ログの「結果:」
sim-ddrtg:
	mkdir -p build-sim
	iverilog -g2012 -o build-sim/tb_ddr_tg.vvp tb/tb_ddr_tg.v src/ddr_tg.v
	iverilog -g2012 -DALIAS -o build-sim/tb_ddr_tg_alias.vvp tb/tb_ddr_tg.v src/ddr_tg.v
	iverilog -g2012 -DAW33 -o build-sim/tb_ddr_tg_aw33.vvp tb/tb_ddr_tg.v src/ddr_tg.v
	vvp -n build-sim/tb_ddr_tg.vvp > build-sim/sim_ddrtg.log & vvp -n build-sim/tb_ddr_tg_alias.vvp > build-sim/sim_ddrtg_alias.log & vvp -n build-sim/tb_ddr_tg_aw33.vvp > build-sim/sim_ddrtg_aw33.log & wait
	iverilog -g2012 -o build-sim/tb_clk_mon.vvp tb/tb_clk_mon.v src/clk_mon.v
	iverilog -g2012 -DNO_UI -o build-sim/tb_clk_mon_noui.vvp tb/tb_clk_mon.v src/clk_mon.v
	vvp -n build-sim/tb_clk_mon.vvp > build-sim/sim_clkmon.log & vvp -n build-sim/tb_clk_mon_noui.vvp > build-sim/sim_clkmon_noui.log & wait
	@grep "結果:" build-sim/sim_ddrtg.log build-sim/sim_ddrtg_alias.log build-sim/sim_ddrtg_aw33.log build-sim/sim_clkmon.log build-sim/sim_clkmon_noui.log

# 見積もり E-2・E-3（チップ内の資源・DDR・出口と dt）。表を作るだけ。荒い FFT・MIG・corner turn は仮の値
estimate:
	mkdir -p runs
	$(PYTHON) tools/estimate.py | tee runs/estimate.log


all: build

prog:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl

# JTAG チェーンのデバイスを表示するだけ（合成ライセンス不要）
id:
	$(VIVADO) -mode batch -nojournal -nolog -source program.tcl -tclargs id

# 速度グレード -1 で通るかを確かめる。成果物は build-1-e/ に出るので build/ は無傷。
# proj028 は -1 だけを作るので、build がそのまま -1 の確かめ
timing-check: build


clean:
	rm -rf build build-* .Xil *.jou *.log

# F-5a: 細かい側の全体（fine_top ＋ 本物のレーン FFT × 16）を OOC で合成・配置配線（この PC の Vivado、1〜2 時間）。結果は build-f5ooc/f5ooc.txt
f5ooc:
	mkdir -p build-f5ooc
	$(VIVADO) -mode batch -nojournal -log build-f5ooc/vivado.log -source tools/f5_ooc.tcl -tclargs $(JOBS)

# F-5: 2 段分光の全体の .bit（RFDC → 荒い段 → ct_wr → PL DDR4 → ct_rd → 細かい側 → PS のリング。この PC の Vivado、2〜3 時間）。成果物は build-f5/proj028.bit・.hwh。
# 成否は make の終了状態でなく build-f5/vivado.log の「TIMING (確定)」「CRITICAL WARNING: n 件」「=== wrote」で読む
f5:
	mkdir -p build-f5
	VIVADO_LOG=build-f5/vivado.log $(VIVADO) -mode batch -nojournal -log build-f5/vivado.log -source build_f5.tcl -tclargs $(JOBS)

# F-5: 同じものを実装の戦略 Performance_Explore で（出力は build-f5-pe/）。f5 と並べて回してよい（JOBS は合わせて 16 以下に）
f5-pe:
	mkdir -p build-f5-pe
	F5_OUT=build-f5-pe F5_IMPL=Performance_Explore VIVADO_LOG=build-f5-pe/vivado.log $(VIVADO) -mode batch -nojournal -log build-f5-pe/vivado.log -source build_f5.tcl -tclargs $(JOBS)
