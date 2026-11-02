#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj037 Y-6 — P-on・P-a・A1 を 2 巡、各状態で y6_cw.py（README Y-6）。ノイズソースは頭で切り、終わりに入れ直す
#   RFSOC_SG=<SG> RFSOC_NS=<NS> bash y6_run.sh
set -u
cd "$(dirname "$0")"
python3 instr.py ns off || exit 1
G="--gains-from runs/y5_g0_meta.json --no-spec --chunks 2"
for i in 1 2; do
  python3 s2run.py --bit proj037.bit $G --out runs/y6_load_pon$i > runs/y6_load_pon$i.log 2>&1; tail -n 1 runs/y6_load_pon$i.log
  python3 y6_cw.py --tag pon$i
  python3 y5_adcoff.py a || break
  python3 y6_cw.py --tag pa$i
  python3 y5_adcoff.py on || break
  python3 s2run.py --bit proj037_a1.bit $G --out runs/y6_load_a1$i > runs/y6_load_a1$i.log 2>&1; tail -n 1 runs/y6_load_a1$i.log
  python3 y6_cw.py --tag a1$i
done
python3 s2run.py --bit proj037.bit $G --out runs/y6_end > runs/y6_end.log 2>&1; echo "end: $(tail -n 1 runs/y6_end.log)"
python3 instr.py ns on
python3 instr.py ns state
