#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""YATSUGATAKE（SAM45-Wide、LMX の出力の強さ）: クロックの櫛 n × 163.84 MHz（n = 13〜24）を、specrecv の .s45 どうしで比べる。

proj019 の櫛の試験（comb16a・_p3）を Wide の SLICE の流れで繰り返すための道具。量は s45spur と同じ:
  r  線の ch の (S − base) / base（base は s45spur.baseline、両側 33 ch の中央値）
  E  線の超過の電力 Σ(S − base)（山の ±2 ch）。ch の幅に依らないので、記録どうしの比 E(後) / E(前) を dB で出す
周波数の軸は s45client と同じ IF = if_mhz ＋ (i − 2047)·df。線は n × 163.84 MHz の ±2 ch の中の最大の ch。

使い方（無入力・同じ設定で PWR だけ替えた記録を、前 → 後の順に）:

    python3 widecomb.py p31.s45 p3.s45                    # 線ごと・ADC ごとの E と比、櫛の和の比
    python3 widecomb.py p31a.s45 p3a.s45 p31b.s45 p3b.s45 --pair   # 交互の 2 組（1-2・3-4）を別々に比べる
    python3 widecomb.py --selftest
"""
import argparse
import math
import sys

import numpy as np

import s45spur as SP

COMB_MHZ = 4096.0 / 25                                   # 163.84 = fs/25
COMB_N = range(13, 25)                                   # 2129.92〜3932.16 MHz（Wide の帯域 2048〜4096 の中の全部）
SEARCH = 2                                               # n × 163.84 の ±2 ch で山を探す


def read_mean(path):
    """.s45 の SLICE の SPEC を流れ（ADC・s）ごとに平均する。戻り値 {鍵: (IF の軸 [MHz], 平均の S, ダンプ数)}"""
    import s45proto as P
    it, _ = SP._read_rec([path], [])
    acc = {}
    for rtype, pl, ver in it():
        if rtype != P.T_SPEC or ver != 2:
            continue
        d = P.decode(rtype, pl, ver)
        if not d.get("df_hz"):
            continue
        k = f"{'ABCD'[d['adc']]}{d['win']}"
        v = d["data"].astype(np.float64) / d["nacc"]
        if k not in acc:
            f = d["if_mhz"] + (np.arange(d["nch"]) - 2047) * (d["df_hz"] / 1e6)
            acc[k] = [f, v.copy(), 1]
        else:
            acc[k][1] += v; acc[k][2] += 1
    return {k: (f, s / n, n) for k, (f, s, n) in acc.items()}


def comb_lines(f, S):
    """櫛の線ごとの {n: dict(f_mhz, r, E)}。流れの帯域の外の n は入れない"""
    b = SP.baseline(S)
    out = {}
    df = abs(f[1] - f[0])
    for n in COMB_N:
        fn = n * COMB_MHZ
        i0 = int(np.argmin(np.abs(f - fn)))
        if abs(f[i0] - fn) > df or i0 < SP.WMED or i0 >= len(f) - SP.WMED:
            continue
        sl = slice(i0 - SEARCH, i0 + SEARCH + 1)
        pk = i0 - SEARCH + int(np.argmax(S[sl] - b[sl]))
        out[n] = dict(f_mhz=float(f[pk]), r=float(S[pk] / b[pk] - 1.0) if b[pk] > 0 else 0.0, E=SP.excess(S, b, pk))
    return out


def measure(path):
    """{ADC: {n: 線}}。同じ ADC に流れが 2 本あれば、線の入っている方（先の方）を使う"""
    res = {}
    for k, (f, S, nd) in sorted(read_mean(path).items()):
        for n, d in comb_lines(f, S).items():
            res.setdefault(k[0], {}).setdefault(n, dict(d, key=k, ndump=nd))
    return res


def db(a, b):
    return 10 * math.log10(a / b) if a > 0 and b > 0 else float("nan")


def compare(pa, pb, la, lb):
    A, B = measure(pa), measure(pb)
    print(f"前 {la}・後 {lb}（E の比 = 10·log10(E 後 / E 前)。E が負や 0 の線は比を出さない）")
    tot = {}
    for adc in "ABCD":
        if adc not in A or adc not in B:
            continue
        print(f"  ADC_{adc}: " + "  ".join(f"{x} の流れ {next(iter(X[adc].values()))['key']}・{next(iter(X[adc].values()))['ndump']} ダンプ"
                                         for x, X in (("前", A), ("後", B))))
        print(f"    {'線 [MHz]':>10} {'n':>3} {'r 前':>9} {'r 後':>9} {'E 前':>10} {'E 後':>10} {'比 [dB]':>8}")
        sa = sb = 0.0
        for n in COMB_N:
            if n not in A[adc] or n not in B[adc]:
                continue
            a, b = A[adc][n], B[adc][n]
            sa += max(a["E"], 0.0); sb += max(b["E"], 0.0)
            print(f"    {a['f_mhz']:10.2f} {n:3d} {a['r']:9.4f} {b['r']:9.4f} {a['E']:10.4g} {b['E']:10.4g} {db(b['E'], a['E']):8.1f}")
        tot[adc] = (sa, sb)
        print(f"    {'櫛の和':>10} {'':3} {'':9} {'':9} {sa:10.4g} {sb:10.4g} {db(sb, sa):8.1f}")
    sa = sum(v[0] for v in tot.values()); sb = sum(v[1] for v in tot.values())
    print(f"  4 ADC の櫛の和: {sa:.4g} → {sb:.4g}（{db(sb, sa):+.1f} dB）")
    return db(sb, sa)


def selftest():
    """合成: 床 1・線 n × 163.84 に超過を入れ、後で 1/4（−6.0 dB）にしたとき比が出るか。帯域の外の n を拾わないか"""
    rng = np.random.default_rng(1)
    f = 3072.0 + (np.arange(4096) - 2047) * 0.5             # B = 4 の SLICE（2048〜4096 MHz、0.5 MHz）
    ok = True
    Es = []
    for scale in (1.0, 0.25):
        S = 1.0 + 1e-3 * rng.standard_normal(4096)
        for n in COMB_N:
            S[int(np.argmin(np.abs(f - n * COMB_MHZ)))] += 0.1 * scale * (n - 12)
        L = comb_lines(f, S)
        ok &= sorted(L) == list(COMB_N)
        Es.append(sum(d["E"] for d in L.values()))
    r = db(Es[1], Es[0])
    ok &= abs(r - db(0.25, 1.0)) < 0.1
    f2 = 3840.0 + (np.arange(4096) - 2047) * 0.125          # B = 1 の流れ（3584〜4096 MHz）: n = 22〜24 だけ
    ok &= sorted(comb_lines(f2, np.ones(4096))) == [22, 23, 24]
    print(f"selftest: 比 {r:+.2f} dB（期待 {db(0.25, 1.0):+.2f}）・帯域の外を拾わない → {'全部通過' if ok else 'NG'}")
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("paths", nargs="*")
    p.add_argument("--pair", action="store_true", help="1-2・3-4 … の組で比べる（交互の取得）")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    if len(a.paths) < 2 or (a.pair and len(a.paths) % 2):
        p.error("記録を前 → 後の順に 2 つ（--pair なら偶数個）")
    pairs = list(zip(a.paths[0::2], a.paths[1::2])) if a.pair else [(a.paths[0], a.paths[1])]
    for pa, pb in pairs:
        compare(pa, pb, pa, pb)
        print()


if __name__ == "__main__":
    main()
