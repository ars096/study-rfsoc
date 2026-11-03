#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj037 Y-9 — P-on・A1 を 2 巡、全帯域の CW（50.3〜2000.3 MHz、10 MHz おき）。ノイズソースは切り、終わりに入れ直す（README Y-9）
#   RFSOC_SG=<SG> RFSOC_NS=<NS> bash y9_run.sh
# 自分で .bit を載せるたびに pl_guard.py save し、各手順の前に check する。別の作業が載せ替えていたら、ノイズを入れて止まる（.bit は載せ直さない）
set -u
cd "$(dirname "$0")"
G="--gains-from runs/y5_g0_meta.json --no-spec --chunks 2"
PG=runs/y9_pl.json
stop() { echo "STOP: $1"; python3 instr.py ns on; python3 instr.py ns state; exit 1; }
guard() { python3 pl_guard.py check $PG || stop "載っている .bit が変わった（$1 の前）"; }
load() {  # $1 = .bit、$2 = 出力の名
  python3 s2run.py --bit $1 $G --out runs/$2 > runs/$2.log 2>&1; grep 結果: runs/$2.log
  python3 pl_guard.py save $PG
}
cw() { python3 y6_cw.py --prefix y9 --tag $1 --freqs 50.3:2000.3:10 --guard $PG; [ $? -eq 3 ] && stop "y6_cw の途中（$1）"; }
python3 instr.py ns off || exit 1
load proj037.bit y9_load_pon1
for i in 1 2; do
  [ $i -eq 2 ] && { guard "load pon2"; load proj037.bit y9_load_pon$i; }
  cw pon$i
  guard "load a1"; load proj037_a1.bit y9_load_a1$i
  cw a1$i
done
guard "end"; load proj037.bit y9_end; echo "end: 載せ直した"
python3 instr.py ns on
python3 instr.py ns state
