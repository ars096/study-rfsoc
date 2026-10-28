# SPDX-License-Identifier: BSD-3-Clause
# proj033 — 2G-1-Fast にレーン FFT の 2-for-1（README）。今は模型（M-1・M-2）だけ。P-4 で proj024-m0 の Makefile を写して後ろに足す
PYTHON ?= python3

.PHONY: model

# M-1・M-2: 2-for-1 の式・鎖の全体・溜めの深さ・(B) の鎖と均しの待ち行列。成否は最後の「まとめ」の行で読む
model:
	@mkdir -p runs
	$(PYTHON) model/s2_model.py | tee runs/model.txt
