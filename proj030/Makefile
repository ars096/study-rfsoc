# proj030 — レーン FFT の 2-for-1（実のレーン 2 本を複素の IP 1 個に）。段階 M: 模型（`make model`）
PYTHON ?= python3

.PHONY: model

# M-1 の模型。成否は最後の「まとめ」の行で読む
model:
	@mkdir -p runs
	$(PYTHON) model/s2_model.py | tee runs/model.txt
