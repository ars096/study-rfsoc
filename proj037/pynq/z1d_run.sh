#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj037 Z-1d — bo_sync を捨ててから返す直しで落ちなくなるか。チャンク 2 で、直しあり 5 回・--keep-bo（直しを外す）3 回を交互に。12 も直しありで 2 回（README Z-1d）
set -u
cd "$(dirname "$0")"
PG=runs/z1_pl.json; n=0
for v in fix old fix old fix old fix fix 12 12; do
  python3 pl_guard.py check $PG || { echo "STOP: 載っている .bit が変わった"; exit 1; }
  n=$((n + 1)); c=2; x=""
  [ $v = old ] && x="--keep-bo"; [ $v = 12 ] && c=12
  o=runs/z1d_${n}_$v
  python3 -X faulthandler s2run.py --no-load --gains-from runs/y5_g0_meta.json --no-spec --chunks $c $x --out $o > $o.log 2>&1
  echo "$n $v（チャンク $c）: rc $?・$(grep '結果:' $o.log | tail -n 1)・NG（SEQ 以外）$(grep '^NG' $o.log | grep -v -c SEQ)"
done
python3 pl_guard.py check $PG && echo "end: 載りは変わっていない"
