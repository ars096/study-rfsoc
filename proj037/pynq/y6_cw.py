#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 Y-6 — 載っている .bit のまま、SG の CW を周波数ごとに入れて RAW の SNAP を取る（ボードの上で、README Y-6）

  RFSOC_SG=<SG> python3 y6_cw.py --tag pon1 [--dbm 9] [--prefix y6]

周波数は荒い ch 3・7・8・23・24 の f = 64k ＋ 1.3 ＋ 4n MHz（n = 0〜15）。頭と尾に SG OFF を 1 回ずつ。
1 点ごとに s2run --no-load --chunks 2 --no-spec → runs/<prefix>_<tag>_<i>_raw.npy。周波数の表は runs/<prefix>_<tag>.json。
ノイズソースは道具の外（y6_run.sh）で切っておく。SG の出力は終わりに切る（sg.py の約束）。
"""
import argparse
import json
import subprocess
import sys

from sg import SG
import pl_guard

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
    ap.add_argument("--prefix", default="y6", help="出力の名の頭（Y-7 は y7）")
    ap.add_argument("--freqs", help="start:stop:step（MHz、stop を含む）。無ければ Y-6 の 80 点（Y-9 は 50.3:2000.3:10）")
    ap.add_argument("--guard", help="pl_guard.py save の file。各点の前に載りを見て、変わっていたら SG を切って止まる（Y-7）")
    a = ap.parse_args()
    freqs = FREQS
    if a.freqs:
        lo, hi, st = map(float, a.freqs.split(":"))
        freqs = [round(lo + st * n, 6) for n in range(int(round((hi - lo) / st)) + 1)]
    sg = SG()
    rows = []
    sg.set_output(False)
    rows.append(dict(i=0, f=None, rc=grab(f"runs/{a.prefix}_{a.tag}_0")))
    sg.set_dbm(a.dbm)
    for i, f in enumerate(freqs, 1):
        if a.guard and not pl_guard.check(a.guard)[0]:
            sg.set_output(False)
            print(f"ERROR: {f} MHz の前に、載っている .bit が変わった（{pl_guard.check(a.guard)[1]}）。SG を切って止まる")
            json.dump(dict(tag=a.tag, dbm=a.dbm, sg=sg.state(), rows=rows, stopped=f), open(f"runs/{a.prefix}_{a.tag}.json", "w"), indent=1)
            sg.close()
            return 3
        sg.set_freq_mhz(f)
        if i == 1:
            sg.set_output(True)
        rc = grab(f"runs/{a.prefix}_{a.tag}_{i}")
        rows.append(dict(i=i, f=f, rc=rc))
    sg.set_output(False)
    rows.append(dict(i=len(freqs) + 1, f=None, rc=grab(f"runs/{a.prefix}_{a.tag}_{len(freqs) + 1}")))
    json.dump(dict(tag=a.tag, dbm=a.dbm, sg=sg.state(), rows=rows), open(f"runs/{a.prefix}_{a.tag}.json", "w"), indent=1)
    sg.close()
    bad = [r for r in rows if "結果:" not in r["rc"][1]]
    print(f"{a.tag}: {len(rows)} 回・判定の行の無い回 {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
