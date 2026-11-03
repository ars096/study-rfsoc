#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj037 W-1f — 載っている proj037.bit のまま、10 分おきに RAW を 132 本（s2run --no-load --no-spec --chunks 12 を 11 回）× 12 巡（README W-1f）
#   RFSOC_NS=<NS> bash w1f_run.sh [巡の数 12] [載せ直す巡 7] [間隔 s 600]
# 載せ直す巡だけ、1 回目に proj037.bit を載せ直して pl_guard.py save。ほかは各回の前に check し、別の作業が載せ替えていたら止まる（載せ直さない）
# 巡ごとに runs/w1f_env.txt へ 時刻・PL の温度（temp20）・PS の温度（temp7）・ノイズソースの電源の読みを足す。器の設定には触らない
set -u
cd "$(dirname "$0")"
N=${1:-12}; RL=${2:-7}; DT=${3:-600}
G="--gains-from runs/y5_g0_meta.json --no-spec --chunks 12"
PG=runs/w1f_pl.json
temp() { local d=/sys/bus/iio/devices/iio:device0; python3 -c "print(f'{(int(open(\"$d/in_temp$1_raw\").read()) + int(open(\"$d/in_temp$1_offset\").read())) * float(open(\"$d/in_temp$1_scale\").read()) / 1000:.2f}')"; }
python3 pl_guard.py save $PG
t0=$(date +%s)
for r in $(seq 1 $N); do
  while [ $(date +%s) -lt $((t0 + (r - 1) * DT)) ]; do sleep 5; done
  echo "$r $(date -u +%H:%M:%S) temp20 $(temp 20) temp7 $(temp 7) $(python3 instr.py ns state 2>&1 | grep 設定)" | tee -a runs/w1f_env.txt
  for i in $(seq 1 11); do
    o=runs/w1f_${r}_$i
    if [ $r -eq $RL ] && [ $i -eq 1 ]; then
      python3 pl_guard.py check $PG || { echo "STOP: 載っている .bit が変わった（巡 $r の載せ直しの前）"; exit 1; }
      python3 s2run.py --bit proj037.bit $G --out $o > $o.log 2>&1
      python3 pl_guard.py save $PG
    else
      python3 pl_guard.py check $PG || { echo "STOP: 載っている .bit が変わった（巡 $r・$i 回目の前）"; exit 1; }
      python3 s2run.py --no-load $G --out $o > $o.log 2>&1
    fi
    echo "  $r.$i: NG $(grep -c '^NG' $o.log)・$(grep '^NG' $o.log | grep -v 'SEQ' | head -n 1)"
  done
done
echo "$((N + 1)) $(date -u +%H:%M:%S) temp20 $(temp 20) temp7 $(temp 7) $(python3 instr.py ns state 2>&1 | grep 設定)" | tee -a runs/w1f_env.txt
python3 pl_guard.py check $PG && echo "end: 載りは変わっていない"
