#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj037 Y-5 — 1 回だけ載せ、ON → cd → b → a を巡らせて s2run の RAW を取る（ボードの上で、README Y-5）
#   bash y5_run.sh [巡の数 6] [チャンク 44]
set -u
cd "$(dirname "$0")"
N=${1:-6}; C=${2:-44}
python3 s2run.py --chunks 4 --out runs/y5_g0 > runs/y5_g0.log 2>&1
tail -n 1 runs/y5_g0.log
for i in $(seq 1 "$N"); do
  for s in on cd b a; do
    python3 y5_adcoff.py "$s" || exit 1
    o=runs/y5_${s}_$i
    python3 s2run.py --no-load --gains-from runs/y5_g0_meta.json --chunks "$C" --out "$o" > "$o.log" 2>&1
    echo "$i $s $(grep -c '^NG' "$o.log") NG: $(grep '^NG' "$o.log" | cut -c1-40 | tr '\n' '/') $(tail -n 1 "$o.log")"
    python3 y5_adcoff.py read
  done
done
python3 y5_adcoff.py on
