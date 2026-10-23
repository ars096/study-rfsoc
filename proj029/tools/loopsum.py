#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj029: specd のログ（--loop-log-ms 0.1）から、運転（[acq] RUN 〜 [acq] STOP）ごとに 1 BASE あたりの段の時間を出す（proj025 追補 5 の数え方）

  python3 loopsum.py <specd のログ> [--nwin 2]
- ログに残った全部の周の段の時間の和を、書いた SPEC の記録の本数 / nwin（= BASE の数）で割る
- 周のログが 300 周の上限に達した運転は、全部の周を数えていない（そう表示する）
"""
import argparse
import re
import sys

PAT = re.compile(r"1 周が ([\d.]+) ms（周 (\d+)・リングのレコード (\d+)・SPEC の記録 (\d+)）: リングの読み ([\d.]+)・振り分け ([\d.]+)・"
                 r"窓の記録 ([\d.]+)・TP ([\d.]+)・時刻の確かめ ([\d.]+) ms")
STAGES = ("リングの読み", "振り分け", "窓の記録", "TP", "時刻")
BASE_MS = 10.24


def runs(lines):
    cur = None
    for ln in lines:
        if ln.startswith("[acq] RUN"):
            cur = dict(loops=[])
        elif ln.startswith("[acq] STOP") and cur is not None:
            cur["stop"] = ln.strip()[:60]
            yield cur
            cur = None
        elif cur is not None:
            m = PAT.search(ln)
            if m:
                cur["loops"].append([float(x) for x in m.groups()])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--nwin", type=int, default=2)
    o = ap.parse_args()
    text = open(o.log, encoding="utf-8", errors="replace").read().splitlines()
    fast = any("SPEC の記録（FULL）は C" in ln for ln in text)
    print(f"{o.log}: SPEC の記録は {'C（--fast）' if fast else 'Python'}")
    for i, r in enumerate(runs(text)):
        L = r["loops"]
        if not L:
            print(f"運転 {i}: 周のログなし")
            continue
        nspec = sum(x[3] for x in L)
        nbase = nspec / o.nwin
        sums = [sum(x[4 + k] for x in L) for k in range(5)]
        tot = sum(sums)
        mx = max(x[0] for x in L)
        cap = "（周のログが 300 周の上限: 全部ではない）" if len(L) >= 300 else ""
        print(f"運転 {i}: 周 {len(L)}・SPEC の記録 {int(nspec)}・BASE {nbase:g}・1 周の最大 {mx:.1f} ms{cap}")
        if nbase:
            print("  1 BASE あたり: " + "・".join(f"{s} {v / nbase:.2f}" for s, v in zip(STAGES, sums)) +
                  f" ms → 計 {tot / nbase:.2f} ms（{100 * tot / nbase / BASE_MS:.0f} %）")


if __name__ == "__main__":
    sys.exit(main())
