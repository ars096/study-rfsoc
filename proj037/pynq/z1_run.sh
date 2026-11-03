#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj037 Z-1 — s2run の終わり際の Segmentation fault がチャンクの数で決まるかを見る（README Z-1）
#   bash z1_run.sh
# 載っている proj037.bit のまま（--no-load）。器には触らない。python3 -X faulthandler で落ちた所の Python の呼び出しの列をログに残す
# 各回の前に pl_guard の check。別の作業が載せ替えていたら止まる
set -u
cd "$(dirname "$0")"
PG=runs/z1_pl.json; n=0
python3 pl_guard.py save $PG
for c in 2 12 2 12 2 12 2 12 2 12 3 4 6 8 3 4 6 8; do
  python3 pl_guard.py check $PG || { echo "STOP: 載っている .bit が変わった"; exit 1; }
  n=$((n + 1)); o=runs/z1_${n}_c$c
  python3 -X faulthandler s2run.py --no-load --gains-from runs/y5_g0_meta.json --no-spec --chunks $c --out $o > $o.log 2>&1
  rc=$?
  echo "$n chunks $c: rc $rc・$(grep '結果:' $o.log | tail -n 1)・NG（SEQ 以外）$(grep '^NG' $o.log | grep -v -c SEQ)"
done
python3 pl_guard.py check $PG && echo "end: 載りは変わっていない"
