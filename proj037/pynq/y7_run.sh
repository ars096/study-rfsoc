#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj037 Y-7 — P-on・P-a・A1 を 2 巡。各状態で、ノイズで較正を収め → CalFreeze → ノイズを切って y6_cw.py → ノイズを入れて止まっていたかを読む（README Y-7）
#   RFSOC_SG=<SG> RFSOC_NS=<NS> bash y7_run.sh
# 自分で .bit を載せるたびに pl_guard.py save し、各手順の前に check する。別の作業が載せ替えていたら、ノイズを入れて止まる（.bit は載せ直さない）
set -u
cd "$(dirname "$0")"
G="--gains-from runs/y5_g0_meta.json --no-spec"
PG=runs/y7_pl.json
stop() { echo "STOP: $1"; python3 instr.py ns on; python3 instr.py ns state; exit 1; }
guard() { python3 pl_guard.py check $PG || stop "載っている .bit が変わった（$1 の前）"; }
load() {  # $1 = .bit、$2 = 出力の名
  python3 s2run.py --bit $1 $G --chunks 2 --out runs/$2 > runs/$2.log 2>&1; grep 結果: runs/$2.log
  python3 pl_guard.py save $PG
}
one() {   # $1 = 名（pon1 など）、$2 = 載っている .bit
  guard "$1"
  python3 instr.py ns on || stop "ns on"
  sleep 30                                                    # ノイズで背景の較正を収める
  guard "$1 c0"
  python3 y7_cal.py --bit $2 coef ${1}_c0                     # 止める前: 1 s で係数が動く（陽性対照）
  python3 s2run.py --no-load $G --chunks 8 --out runs/y7_${1}_n0 > runs/y7_${1}_n0.log 2>&1; grep 結果: runs/y7_${1}_n0.log
  guard "$1 freeze"
  python3 y7_cal.py --bit $2 freeze || stop "freeze"
  python3 y7_cal.py --bit $2 coef ${1}_f0
  python3 instr.py ns off || stop "ns off"
  python3 y6_cw.py --prefix y7 --tag $1 --guard $PG; [ $? -eq 3 ] && stop "y6_cw の途中"
  python3 instr.py ns on || stop "ns on"
  guard "$1 f1"
  python3 y7_cal.py --bit $2 coef ${1}_f1                     # CW の間も止まっていたか（GCB・OCB2・TSCB は f0 と同じはず）
  python3 s2run.py --no-load $G --chunks 8 --out runs/y7_${1}_n1 > runs/y7_${1}_n1.log 2>&1; grep 結果: runs/y7_${1}_n1.log
  python3 y7_cal.py --bit $2 unfreeze
}
load proj037.bit y7_load_pon1
for i in 1 2; do
  [ $i -eq 2 ] && { guard "load pon2"; load proj037.bit y7_load_pon$i; }
  one pon$i proj037.bit
  guard "adcoff a"; python3 y5_adcoff.py a || stop "adcoff a"
  one pa$i proj037.bit
  guard "adcoff on"; python3 y5_adcoff.py on || stop "adcoff on"
  guard "load a1"; load proj037_a1.bit y7_load_a1$i
  one a1$i proj037_a1.bit
done
guard "end"; load proj037.bit y7_end; echo "end: 載せ直した"
python3 instr.py ns on
python3 instr.py ns state
