#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj037 Z-1c — --keep-buf で、止めた後 2 s にリングのバッファへ書かれた語を数える。チャンク 2 を 3 回・12 を 2 回（README Z-1c）
set -u
cd "$(dirname "$0")"
PG=runs/z1_pl.json; n=0
for c in 2 12 2 12 2; do
  python3 pl_guard.py check $PG || { echo "STOP: 載っている .bit が変わった"; exit 1; }
  n=$((n + 1)); o=runs/z1c_${n}_c$c
  python3 -X faulthandler s2run.py --no-load --gains-from runs/y5_g0_meta.json --no-spec --chunks $c --keep-buf --out $o > $o.log 2>&1
  echo "$n chunks $c: rc $?・$(grep 'ring: バッファは返さない' $o.log)"
done
python3 pl_guard.py check $PG && echo "end: 載りは変わっていない"
