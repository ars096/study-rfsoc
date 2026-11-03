#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj037 Z-1b — チャンク 2 で、素のまま・--keep-buf（リングのバッファを返さない）・--no-raw を交互に 4 回ずつ（README Z-1b）
#   bash z1b_run.sh
set -u
cd "$(dirname "$0")"
PG=runs/z1_pl.json; n=0
for r in 1 2 3 4; do
  for v in plain keep noraw; do
    python3 pl_guard.py check $PG || { echo "STOP: 載っている .bit が変わった"; exit 1; }
    n=$((n + 1)); o=runs/z1b_${n}_$v
    x=""; [ $v = keep ] && x="--keep-buf"; [ $v = noraw ] && x="--no-raw"
    python3 -X faulthandler s2run.py --no-load --gains-from runs/y5_g0_meta.json --no-spec --chunks 2 $x --out $o > $o.log 2>&1
    rc=$?
    echo "$n $v: rc $rc・$(grep '結果:' $o.log | tail -n 1)・NG（SEQ 以外）$(grep '^NG' $o.log | grep -v -c SEQ)"
  done
done
python3 pl_guard.py check $PG && echo "end: 載りは変わっていない"
