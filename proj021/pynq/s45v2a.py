#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj021 手順 2-3b — V2-a: specd が束ねた 4 個（PL は 10.24 ms）= PL の 40.96 ms の 1 個（整数で）

    python3 s45v2a.py --host <board> --n 100

ADC ごとに窓 0 と窓 1 を**同じ設定**（IF・幅・SHIFT）にし、窓 0 は bundle=1（PL は 10.24 ms、specd が n_sum = 4 個を u64 で足す）、
窓 1 は bundle=0（PL が 40.96 ms を 1 個で）。2 つの窓は同じ ADC・同じ粗い PFB・同じ設定の DDC を同じ WRST で始めるので、
z の列が bit 単位で同じ → **同じ区間の積分値は整数で一致する**はず。
照らすもの（ADC ごと）: dump_t が同じ記録どうしの 4096 ch が全部一致・nacc（Σ DUMP_N）が同じ・k が続く。
陽性対照: 窓 0 の束 j と窓 1 の j+1 を比べる（1 区間ずらす）→ 一致してはいけない
"""
import argparse
import sys

import numpy as np

from s45client import S45


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", required=True)
    p.add_argument("--n", type=int, default=100, help="束の数（40.96 ms × n）")
    p.add_argument("--if-mhz", type=float, default=3000.0)
    p.add_argument("--bw", type=int, default=256)
    p.add_argument("--shift", type=int, default=9)
    a = p.parse_args()
    s = S45(a.host)
    kv = [f"tint=0.04096", f"all.shift={a.shift}"]
    for x in "ABCD":
        kv += [f"{x}0.if={a.if_mhz}", f"{x}1.if={a.if_mhz}", f"{x}0.bw={a.bw}", f"{x}1.bw={a.bw}", f"{x}0.bundle=1", f"{x}1.bundle=0"]
    s.set(" ".join(kv))
    try:
        d = s.acquire(a.n)
    finally:
        st = s.status()
        try:
            s.wait_idle(10)
            s.set(" ".join(f"{x}{w}.bundle=1" for x in "ABCD" for w in "01"))     # 既定に戻す
        except Exception as e:  # noqa: BLE001
            print(f"NOTE: bundle を既定に戻せなかった（{e}）")
    ok = True
    for x in "ABCD":
        m0, m1 = d.meta(f"{x}0"), d.meta(f"{x}1")
        s0, s1 = d.spec(f"{x}0", raw=True), d.spec(f"{x}1", raw=True)
        t1 = {int(t): i for i, t in enumerate(m1["dump_t"])}
        pairs = [(i, t1[int(t)]) for i, t in enumerate(m0["dump_t"]) if int(t) in t1]
        neq = sum(1 for i, j in pairs if not np.array_equal(s0[i], s1[j]))
        nacc_ng = sum(1 for i, j in pairs if m0["nacc"][i] != m1["nacc"][j])
        kgap = int(np.sum(np.diff(m0["k"]) != 1))
        sh = [(i, t1.get(int(m0["dump_t"][i]) + (int(m0["dump_t"][1]) - int(m0["dump_t"][0])))) for i in range(len(m0) - 1)]
        sh = [(i, j) for i, j in sh if j is not None]
        same_shift = sum(1 for i, j in sh if np.array_equal(s0[i], s1[j]))
        good = len(pairs) >= a.n - 2 and neq == 0 and nacc_ng == 0 and kgap == 0 and len(sh) > 0 and same_shift == 0
        ok &= good
        print(f"ADC_{x}: 組 {len(pairs)}（束 {len(m0)}・PL {len(m1)}）・中身の不一致 {neq}・nacc の不一致 {nacc_ng}・束の k の飛び {kgap}・"
              f"1 区間ずらすと一致 {same_shift} / {len(sh)}（陽性対照: 0 であるべき）・nacc {int(m0['nacc'][0]) if len(m0) else '-'}: "
              f"{'OK' if good else 'NG'}")
    chk = s.check()
    print(f"受けた記録の照合: {chk}")
    print(f"specd: pl_dumps {st.get('pl_dumps')}・bdrop {st.get('bdrop')}・r_bad {st.get('r_bad')}・bund_r {st.get('bund_r')}・miss {st.get('miss')}")
    print(f"結果（V2-a）: {'通過' if ok else '失敗'}")
    s.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
