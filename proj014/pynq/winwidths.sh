#!/bin/sh
# SPDX-License-Identifier: BSD-3-Clause
# proj014 — 窓の幅ごとに W-2・W-3（winsweep.py）と W-5（winnoise.py）を続けて回し、ログと npz を runs/ に残す
#
#   RFSOC_SG=<SG の宛先> sh winwidths.sh                   既定の 4 通り（128 / 64 / 32 / 16 MHz）
#   RFSOC_SG=<SG の宛先> sh winwidths.sh "128 2900" "16 2950"   幅と IF の中心を指定
#
# 既定の IF の中心は、k·fs/8 の線（2560・3072・3584 MHz）が窓に入らず、粗い ch の中の位置（d）がばらけるように選んだ:
#   128 MHz: 2900（c 1196・k 9・d +44）/ 64 MHz: 3200（c 896・k 7・d 0）/ 32 MHz: 3100（c 996・k 8・d −28）/ 16 MHz: 2950（c 1146・k 9・d −6）
# W-3 の窓の SHIFT は winsweep.py が SG を切った床から自動で選ぶ。W-5 の SHIFT は winnoise.py が選ぶ
set -u
CLK="--clkin 0 --ref 10"
if [ $# -eq 0 ]; then set -- "128 2900" "64 3200" "32 3100" "16 2950"; fi
mkdir -p runs
for spec in "$@"; do
    set -- $spec
    W=$1; IF=$2
    tag="w${W}_if${IF}"
    echo "==== W = $W MHz・IF $IF MHz"
    python3 winsweep.py --if "$IF" --w "$W" $CLK --w3-dbm 0 --w3-shift-full 12 --save-spectra --out "runs/$tag" 2>&1 \
        | grep -v "UserWarning\|fig.tight_layout" | tee "runs/$tag.sweep.log" | grep -E "^  (OK|NG)|RESULT|自動"
    python3 winnoise.py --if "$IF" --w "$W" $CLK --out "runs/$tag" 2>&1 \
        | tee "runs/$tag.noise.log" | grep -E "^  (OK|NG|--)|RESULT|SHIFT 11"
done
echo "==== まとめ"
for f in runs/*.log; do
    printf '%-32s %s\n' "$f" "$(grep -a 'RESULT' "$f" | tail -1)"
    grep -a '^  NG' "$f"
done
