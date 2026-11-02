#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj037 Y-4 — proj037.bit（全部動く・A だけ）と proj037_a1.bit（ADC_A だけを設計に持つ、RAW の取得にだけ使う）を交互に載せて RAW を取る（ボードの上で、README Y-4）
#   bash y4_run.sh [巡の数 6] [チャンク 44]
set -u
cd "$(dirname "$0")"
N=${1:-6}; C=${2:-44}
G="--gains-from runs/y5_g0_meta.json --no-spec --chunks $C"
sum() { echo "$1 $(grep -ac '^NG' "$2.log") NG: $(grep -a '^NG' "$2.log" | cut -c1-40 | tr '\n' '/') $(tail -n 1 "$2.log")"; }
for i in $(seq 1 "$N"); do
  o=runs/y4_pon_$i; python3 s2run.py --bit proj037.bit $G --out "$o" > "$o.log" 2>&1; sum "$i pon" "$o"
  python3 y5_adcoff.py a || exit 1
  o=runs/y4_pa_$i; python3 s2run.py --no-load $G --out "$o" > "$o.log" 2>&1; sum "$i pa" "$o"
  python3 y5_adcoff.py on || exit 1          # 止めたまま載せ直すと終わり際に落ちた（Y-5）ので戻してから
  o=runs/y4_a1_$i; python3 s2run.py --bit proj037_a1.bit $G --out "$o" > "$o.log" 2>&1; sum "$i a1" "$o"
  df -h / | tail -n 1
done
python3 s2run.py --bit proj037.bit --chunks 4 --no-spec --out runs/y4_end > runs/y4_end.log 2>&1; echo "end: $(tail -n 1 runs/y4_end.log)"
