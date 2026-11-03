#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj037 W-1e — proj037.bit を載せ、s2run --chunks 12 を 11 回（README W-1e）。配線は W-1 と同じ（ノイズ ON・SG OFF）、器には触らない
#   bash w1e_run.sh
# 1 回目に載せて pl_guard.py save、2 回目からは --no-load で、各回の前に check する。別の作業が載せ替えていたら止まる（.bit は載せ直さない）
# _spec.npy は 12 チャンクの平均（1 行）に置き換える（1 回 176 MB → 29 MB。raw_shape.py は行の平均を取るので同じ）
set -u
cd "$(dirname "$0")"
G="--gains-from runs/y5_g0_meta.json --chunks 12"
PG=runs/w1e_pl.json
for i in $(seq 1 11); do
  o=runs/w1e_$i
  if [ $i -eq 1 ]; then
    python3 s2run.py --bit proj037.bit $G --out $o > $o.log 2>&1
    python3 pl_guard.py save $PG
  else
    python3 pl_guard.py check $PG || { echo "STOP: 載っている .bit が変わった（$i 回目の前）"; exit 1; }
    python3 s2run.py --no-load $G --out $o > $o.log 2>&1
  fi
  echo "$i: $(grep 結果: $o.log | tail -n 1)"
  python3 -c "import numpy as np; x = np.load('${o}_spec.npy'); np.save('${o}_spec.npy', x.astype(np.float64).mean(0, keepdims=True)); print('  spec', x.shape, '→ 1 行')"
done
python3 pl_guard.py check $PG && echo "end: 載りは変わっていない"
