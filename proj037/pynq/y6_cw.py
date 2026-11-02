#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-6 — 載っている .bit のまま、SG の CW を周波数ごとに入れて RAW の SNAP を取る（ボードの上で、README Y-6）

  RFSOC_SG=<SG> python3 y6_cw.py --tag pon1 [--dbm 9]

周波数は荒い ch 3・7・8・23・24 の f = 64k ＋ 1.3 ＋ 4n MHz（n = 0〜15）。頭と尾に SG OFF を 1 回ずつ。
1 点ごとに s2run --no-load --chunks 2 --no-spec → runs/y6_<tag>_<i>_raw.npy。周波数の表は runs/y6_<tag>.json。
ノイズソースは道具の外（y6_run.sh）で切っておく。SG の出力は終わりに切る（sg.py の約束）。
"""
import argparse
import json
import subprocess
import sys

from sg import SG

CH = (3, 7, 8, 23, 24)
FREQS = [64 * k + 1.3 + 4 * n for k in CH for n in range(16)]


def grab(o):
    r = subprocess.run(f"python3 s2run.py --no-load --gains-from runs/y5_g0_meta.json --no-spec --chunks 2 --out {o} > {o}.log 2>&1",
                       shell=True)
    lines = open(o + ".log", errors="replace").read().strip().splitlines()
    res = [s for s in lines if "結果:" in s][-1:]             # 終わり際の Segmentation fault が最終行に来る（Y-6）
    return r.returncode, (res[0] if res else (lines[-1] if lines else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--dbm", type=float, default=9.0)
    a = ap.parse_args()
    sg = SG()
    rows = []
    sg.set_output(False)
    rows.append(dict(i=0, f=None, rc=grab(f"runs/y6_{a.tag}_0")))
    sg.set_dbm(a.dbm)
    for i, f in enumerate(FREQS, 1):
        sg.set_freq_mhz(f)
        if i == 1:
            sg.set_output(True)
        rc = grab(f"runs/y6_{a.tag}_{i}")
        rows.append(dict(i=i, f=f, rc=rc))
    sg.set_output(False)
    rows.append(dict(i=len(FREQS) + 1, f=None, rc=grab(f"runs/y6_{a.tag}_{len(FREQS) + 1}")))
    json.dump(dict(tag=a.tag, dbm=a.dbm, sg=sg.state(), rows=rows), open(f"runs/y6_{a.tag}.json", "w"), indent=1)
    sg.close()
    bad = [r for r in rows if "結果:" not in r["rc"][1]]
    print(f"{a.tag}: {len(rows)} 回・判定の行の無い回 {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
