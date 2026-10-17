#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj024 — 2G-1 の部品の sim の判定（model/g21_fixed.py の定義と bit 単位で比べる）。

    python3 sim/check_g21.py coef <sim の出力ディレクトリ> [tb のログ]
    python3 sim/check_g21.py tw   <sim の出力ディレクトリ> [tb のログ]
    python3 sim/check_g21.py pfb-gen <sim の出力ディレクトリ>     （x.hex を書く）
    python3 sim/check_g21.py pfb  <sim の出力ディレクトリ> <tb のログ>
    python3 sim/check_g21.py chain-gen <sim の出力ディレクトリ>   （yre.hex・yim.hex を書く）
    python3 sim/check_g21.py chain <sim の出力ディレクトリ> <tb のログ> <SHIFT>
成否は最後の「結果:」の行で読む（make の成功を信用しない）。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import g21_fixed as F  # noqa: E402


def sx(v, w):
    return v - (1 << w) if v >> (w - 1) else v


def coef(outdir, tblog=None):
    V, S = F.coef_tables()
    ref = F.coef_beat(V, S)                       # [t, m, p]
    seen = {}
    nbad = nline = 0
    first = None
    for line in open(os.path.join(outdir, "coef.txt")):
        ms, hx = line.split()
        m = int(ms)
        w = int(hx, 16)
        got = np.array([[sx((w >> (72 * p + 18 * t)) & 0x3FFFF, 18) for p in range(16)] for t in range(4)])
        d = got != ref[:, m, :]
        if d.any():
            nbad += 1
            if first is None:
                t, p = np.argwhere(d)[0]
                first = (m, t, p, int(got[t, p]), int(ref[t, m, p]))
        seen[m] = seen.get(m, 0) + 1
        nline += 1
    cover = len(seen) == F.M
    print(f"check coef: {nline} 行・m の種類 {len(seen)} / {F.M}・模型と違う行 {nbad}"
          + (f"（最初: m {first[0]}・t {first[1]}・p {first[2]}: RTL {first[3]} / 模型 {first[4]}）" if first else ""))
    tb_ok = True
    if tblog:
        tb_ok = "tb: 口の振る舞い OK" in open(tblog, encoding="utf-8", errors="replace").read()
        print(f"check coef: tb の口の振る舞い {'OK' if tb_ok else 'NG'}")
    ok = nbad == 0 and cover and tb_ok
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


def tw(outdir, tblog=None):
    pr, pi = F.tw_prod()
    nline = nbad = 0
    first = None
    seq = []
    for line in open(os.path.join(outdir, "tw.txt")):
        ks, hx = line.split()
        k = int(ks)
        w = int(hx, 16)
        re = np.array([sx((w >> (36 * p)) & 0x3FFFF, 18) for p in range(16)])
        im = np.array([sx((w >> (36 * p + 18)) & 0x3FFFF, 18) for p in range(16)])
        d = (re != pr[:, k]) | (im != pi[:, k])
        if d.any():
            nbad += 1
            if first is None:
                p = int(np.argmax(d))
                first = (k, p, int(re[p]), int(im[p]), int(pr[p, k]), int(pi[p, k]))
        seq.append(k)
        nline += 1
    # k1_out の並び: 16383 の待ちの後に bit 反転順の 0..16383 ＋ 頭 256、その後 16383
    exp = [int(F.bitrev(np.array([i % F.M]), 14)[0]) for i in range(F.M + 256)]
    try:
        i0 = seq.index(0)
    except ValueError:
        i0 = -1
    order_ok = i0 >= 0 and seq[i0:i0 + len(exp)] == exp
    kinds = len(set(seq[i0:i0 + F.M])) if i0 >= 0 else 0
    print(f"check tw: {nline} 行・模型と違う行 {nbad}"
          + (f"（最初: k1 {first[0]}・p {first[1]}: RTL ({first[2]}, {first[3]}) / 模型 ({first[4]}, {first[5]})）" if first else "")
          + f"・k1_out の並び {'入れたとおり' if order_ok else '違う'}（1 フレームの k1 の種類 {kinds}）")
    tb_ok = True
    if tblog:
        tb_ok = "tb: 口の振る舞い OK" in open(tblog, encoding="utf-8", errors="replace").read()
        print(f"check tw: tb の口の振る舞い {'OK' if tb_ok else 'NG'}")
    ok = nbad == 0 and order_ok and kinds == F.M and tb_ok
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


PRE, NF = 384, 5


def pfb_x():
    """1c の刺激: 雑音 σ 100 ＋ CW 1000（ch 40000）、フレーム 3 の頭の 2000 ビートは ±8191 の満杯（PFB の出口の最大に近づける。
    y は Σ|c| ≦ 1.405 なので 15 bit で飽和しない — M-4。sat_cnt は 0 のはず）。int、長さ PRE·16 + NF·N。"""
    rng = np.random.default_rng(1)
    n = np.arange(NF * F.N)
    x = np.round(1000 * np.cos(2 * np.pi * 40000 * n / F.N) + rng.normal(0, 100, NF * F.N))
    full = slice(3 * F.N, 3 * F.N + 2000 * 16)
    x[full] = np.where(np.arange(2000 * 16) % 32 < 16, 8191, -8192)
    x = np.clip(x, -8192, 8191).astype(np.int64)
    pre = np.clip(np.round(rng.normal(0, 3000, PRE * 16)), -8192, 8191).astype(np.int64)
    return pre, x


def pfb_gen(outdir):
    os.makedirs(outdir, exist_ok=True)
    pre, x = pfb_x()
    allx = np.concatenate([pre, x]).reshape(-1, 16)
    with open(os.path.join(outdir, "x.hex"), "w") as fo:
        for row in allx:
            w = 0
            for p in range(16):
                w |= ((int(row[p]) << 2) & 0xFFFF) << (16 * p)      # ADC の 16 bit（本体が >>> 2 する）
            fo.write("%064x\n" % w)
    print(f"pfb-gen: {len(allx)} ビート")


def pfb(outdir, tblog):
    pre, x = pfb_x()
    yref, nsat = F.pfb_int(x, F.coef_interp())             # (NF, N)
    rows = [l.split() for l in open(os.path.join(outdir, "y.txt"))]
    log = open(tblog, encoding="utf-8", errors="replace").read()
    import re as _re
    mt = _re.search(r"sat_cnt (\d+)・coef_mis (\d+)", log)
    sat_cnt, coef_mis = (int(mt.group(1)), int(mt.group(2))) if mt else (-1, -1)
    nbad = 0
    first = None
    order_ok = len(rows) == NF * F.M
    for j, (ms, frs, fst, hx) in enumerate(rows):
        f, mm = divmod(j, F.M)
        if int(ms) != mm or int(frs) != min(f, 3) or int(fst) != (mm == 0):
            order_ok = False
        if f >= NF:
            continue
        ref = yref[f, 16 * mm: 16 * mm + 16]
        try:
            w = int(hx, 16)
        except ValueError:                                  # x・z を含む（初期化していない履歴を読んだ）
            nbad += 1
            if first is None:
                first = (f, mm, -1, hx[:8], "x/z")
            continue
        got = np.array([sx((w >> (15 * p)) & 0x7FFF, 15) for p in range(16)])
        if (got != ref).any():
            nbad += 1
            if first is None:
                p = int(np.argmax(got != ref))
                first = (f, mm, p, int(got[p]), int(ref[p]))
    print(f"check pfb: {len(rows)} ビート（期待 {NF * F.M}）・並び（y_m・y_fr・y_first）{'OK' if order_ok else 'NG'}・"
          f"模型と違うビート {nbad}" + (f"（最初: フレーム {first[0]}・m {first[1]}・p {first[2]}: RTL {first[3]} / 模型 {first[4]}）" if first else ""))
    print(f"check pfb: sat_cnt {sat_cnt}（模型の飽和 {nsat}）・coef_mis {coef_mis}")
    ok = order_ok and nbad == 0 and sat_cnt == min(nsat, 0xFFFF) and coef_mis == 0
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


def chain_Y_frames():
    """1d の刺激: レーン FFT の出口 Y（re, im）を 3 フレーム。0: CW 1000 ＋ 雑音 σ 100（PFB の履歴が埋まった 4 フレーム目）、
    1: 雑音だけ σ 30、2: 最悪の同相（y がすべて +11507 → k1 = 0 で |Y| = 11507·16384、29 bit いっぱい）。戻り値 [(Yr, Yi)] × 3（各 (16, M)）"""
    rng = np.random.default_rng(4)
    n = np.arange(4 * F.N)
    x = np.clip(np.round(1000 * np.cos(2 * np.pi * 40000 * n / F.N) + rng.normal(0, 100, 4 * F.N)), -8192, 8191).astype(np.int64)
    y, _ = F.pfb_int(x, F.coef_interp())
    xn = np.clip(np.round(rng.normal(0, 30, 4 * F.N)), -8192, 8191).astype(np.int64)
    yn, _ = F.pfb_int(xn, F.coef_interp())
    yw = np.full(F.N, 11507, dtype=np.int64)
    return [F.lane_fft(y[3]), F.lane_fft(yn[3]), F.lane_fft(yw)]


def _pack(vals, w):
    out = 0
    for p, v in enumerate(vals):
        out |= (int(v) & ((1 << w) - 1)) << (w * p)
    return out


def chain_gen(outdir):
    os.makedirs(outdir, exist_ok=True)
    fr = chain_Y_frames()
    br = F.bitrev(np.arange(F.M), 14)
    with open(os.path.join(outdir, "yre.hex"), "w") as fr_, open(os.path.join(outdir, "yim.hex"), "w") as fi_:
        for Yr, Yi in fr:
            assert max(np.abs(Yr).max(), np.abs(Yi).max()) < (1 << 28), "Y が 29 bit に入らない"
            for i in range(F.M):
                k = br[i]
                fr_.write("%0116x\n" % _pack(Yr[:, k], 29))
                fi_.write("%0116x\n" % _pack(Yi[:, k], 29))
    print(f"chain-gen: {len(fr) * F.M} ビート")


def chain(outdir, tblog, shift):
    import re as _re
    fr = chain_Y_frames()
    twr, twi = F.tw_prod()
    lo, hi = -(1 << 17), (1 << 17) - 1
    refs = []
    for Yr, Yi in fr:
        Zr, Zi = F.chain_Y(Yr, Yi, twr, twi)
        qr, qi = Zr >> shift, Zi >> shift
        sat = (qr < lo) | (qr > hi) | (qi < lo) | (qi > hi)
        qr, qi = np.clip(qr, lo, hi), np.clip(qi, lo, hi)
        refs.append((qr * qr + qi * qi, sat.sum(axis=0)))       # (8, M)・(M,)
    br = F.bitrev(np.arange(F.M), 14)
    rows = [l.split() for l in open(os.path.join(outdir, "p.txt"))]
    log = open(tblog, encoding="utf-8", errors="replace").read()
    mt = _re.search(r"tw_mis (\d+)", log)
    tw_mis = int(mt.group(1)) if mt else -1
    nbad = nsat_beats = 0
    first = None
    order_ok = len(rows) == len(fr) * F.M
    for j, (ks, ss, hx) in enumerate(rows):
        f, i = divmod(j, F.M)
        if f >= len(fr):
            order_ok = False
            break
        k = int(ks)
        if k != br[i]:
            order_ok = False
        pw, sc = refs[f]
        w = int(hx, 16)
        got = [(w >> (37 * b)) & ((1 << 37) - 1) for b in range(8)]
        exp = [int(pw[b, k]) for b in range(8)]
        if got != exp or int(ss) != int(sc[k]):
            nbad += 1
            if first is None:
                b = next((b for b in range(8) if got[b] != exp[b]), -1)
                first = (f, k, b, got[b] if b >= 0 else None, exp[b] if b >= 0 else None, int(ss), int(sc[k]))
        if int(sc[k]) > 0:
            nsat_beats += 1
    print(f"check chain: {len(rows)} ビート（期待 {len(fr) * F.M}）・k1 の並び {'OK' if order_ok else 'NG'}・模型と違うビート {nbad}"
          + (f"（最初: フレーム {first[0]}・k1 {first[1]}・銀行 {first[2]}: RTL {first[3]} / 模型 {first[4]}、飽和 {first[5]} / {first[6]}）" if first else ""))
    print(f"check chain: SHIFT {shift}・模型で飽和を含むビート {nsat_beats}・tw_mis {tw_mis}")
    ok = order_ok and nbad == 0 and tw_mis == 0
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "coef":
        sys.exit(0 if coef(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None) else 1)
    if what == "chain-gen":
        chain_gen(sys.argv[2]); sys.exit(0)
    if what == "chain":
        sys.exit(0 if chain(sys.argv[2], sys.argv[3], int(sys.argv[4])) else 1)
    if what == "pfb-gen":
        pfb_gen(sys.argv[2]); sys.exit(0)
    if what == "pfb":
        sys.exit(0 if pfb(sys.argv[2], sys.argv[3]) else 1)
    if what == "tw":
        sys.exit(0 if tw(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None) else 1)
    sys.exit(2)
