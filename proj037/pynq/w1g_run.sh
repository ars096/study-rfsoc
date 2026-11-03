#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj037 W-1g — ノイズソースを切って入れ直し、入れてからの時間で RAW の形と電源の電流がどう動くかを見る（README W-1g）
#   RFSOC_NS=<NS> bash w1g_run.sh [切っておく秒 1800] [入れてからの終わり 秒 7200]
# 巡 = s2run --no-load --no-spec --chunks 12 を 4 回（RAW 48 本）。巡 0 は切る前（温まった状態）。
# 入れてから 30 分は巡を続けて回し、その後は 10 分おき。巡ごとに runs/w1g_env.txt へ 入れてからの秒・時刻・温度・電源の読み
# 載っている .bit は変えない（各回の前に pl_guard の check。別の作業が載せ替えていたら、ノイズを入れて止まる）。ATT・SG には触らない
set -u
cd "$(dirname "$0")"
OFF=${1:-1800}; END=${2:-7200}
G="--gains-from runs/y5_g0_meta.json --no-spec --chunks 12"
PG=runs/w1g_pl.json
stop() { echo "STOP: $1"; python3 instr.py ns on; python3 instr.py ns state; exit 1; }
temp() { local d=/sys/bus/iio/devices/iio:device0; python3 -c "print(f'{(int(open(\"$d/in_temp$1_raw\").read()) + int(open(\"$d/in_temp$1_offset\").read())) * float(open(\"$d/in_temp$1_scale\").read()) / 1000:.2f}')"; }
env() { echo "$1 $2 $(date -u +%H:%M:%S) temp20 $(temp 20) temp7 $(temp 7) $(python3 instr.py ns state 2>&1 | grep 設定)" | tee -a runs/w1g_env.txt; }
round() {  # $1 = 巡、$2 = 入れてからの秒（巡 0 は -）
  env $1 $2
  for i in 1 2 3 4; do
    python3 pl_guard.py check $PG || stop "載っている .bit が変わった（巡 $1・$i 回目の前）"
    o=runs/w1g_${1}_$i
    python3 s2run.py --no-load $G --out $o > $o.log 2>&1
    n=$(grep '^NG' $o.log | grep -v -c 'SEQ'); [ $n -ne 0 ] && echo "  $1.$i: SEQ 以外の NG $n"
  done
}
python3 pl_guard.py save $PG
round 0 -
python3 instr.py ns off || stop "ノイズを切れない"
env off -
sleep $OFF
python3 pl_guard.py check $PG || stop "載っている .bit が変わった（切っている間）"
env off_end -
python3 instr.py ns on || stop "ノイズを入れられない"
t0=$(date +%s); r=1
while [ $(( $(date +%s) - t0 )) -lt 1800 ]; do round $r $(( $(date +%s) - t0 )); r=$((r + 1)); done
for t in $(seq 2400 600 $END); do
  while [ $(date +%s) -lt $((t0 + t)) ]; do sleep 5; done
  round $r $(( $(date +%s) - t0 )); r=$((r + 1))
done
env end $(( $(date +%s) - t0 ))
python3 pl_guard.py check $PG && echo "end: 載りは変わっていない。ノイズは ON のまま"
