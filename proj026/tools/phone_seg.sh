#!/bin/bash
# SPDX-License-Identifier: BSD-3-Clause
# proj026 — 携帯電話の試験の 1 区間（60 s = 1465 ダンプ × 40.96 ms）を受ける。制御 PC で、proj026/ から。
#   B=<ボード> tools/phone_seg.sh runs/c1_off1          # → runs/c1_off1.s45・.json・.status.txt
# specd は SET 済み（README の手順）。受けを先に立ててから START する（前の運転の溜まりを混ぜない）。
set -eu
name=${1:?区間の名前（例: runs/c1_off1）}
n=${N:-1465}
PYDIR=${PYDIR:-$HOME/git/YATSUGATAKE/sw/pynq}
: "${B:?環境変数 B にボードの宛先を（export B）}"
# specrecv は既にある .s45 に足して書く（2026-10-21 の C2b で 2 回分が 1 つのファイルに入った）→ 同じ名前は止める
if [ -e "$name.s45" ]; then echo "$name.s45 は既にある。別の名前にするか、退けてから" >&2; exit 1; fi
python3 "$PYDIR/specrecv.py" --host "$B" --out "$name.s45" --seconds $(( n * 4096 / 100000 + 15 )) --json "$name.json" --report 30 &
rp=$!
sleep 2
date -Is | tee "$name.status.txt"
python3 "$PYDIR/specctl.py" --host "$B" "START n=$n" "SEND ON" | tee -a "$name.status.txt"
wait $rp
python3 "$PYDIR/specctl.py" --host "$B" "STATUS" | tee -a "$name.status.txt"
