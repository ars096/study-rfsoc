#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj024 — 2G-1 の部品の sim の判定（model/g21_fixed.py の定義と bit 単位で比べる）。

    python3 sim/check_g21.py coef <sim の出力ディレクトリ> [tb のログ]
    python3 sim/check_g21.py tw   <sim の出力ディレクトリ> [tb のログ]
    python3 sim/check_g21.py pfb-gen <sim の出力ディレクトリ>     （x.hex を書く）
    python3 sim/check_g21.py pfb  <sim の出力ディレクトリ> <tb のログ>
    python3 sim/check_g21.py chain-gen <sim の出力ディレクトリ>   （yre.hex・yim.hex を書く）
    python3 sim/check_g21.py lane-gen <sim の出力ディレクトリ>    （lx.hex を書く）
    python3 sim/check_g21.py acc <sim の出力ディレクトリ>
    python3 sim/check_g21.py spec-gen <sim の出力ディレクトリ>    （x.hex を書く）
    python3 sim/check_g21.py spec <sim の出力ディレクトリ> <tb のログ> <SHIFT>
    python3 sim/check_g21.py lane <sim の出力ディレクトリ> <tb のログ> <tready の下げを入れたか 0|1>
    python3 sim/check_g21.py chain <sim の出力ディレクトリ> <tb のログ> <SHIFT>
成否は最後の「結果:」の行で読む（make の成功を信用しない）。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import g21_fixed as F  # noqa: E402
from g2_model import core_fft, design, pfb_float  # noqa: E402


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


def lane_x():
    """2a の刺激: 1 レーン 3 フレーム。0: PFB の出口に近い CW ＋ 雑音、1: ±11507 の満杯（同相の最悪に近い）、2: 雑音 σ 30。int（15 bit）"""
    rng = np.random.default_rng(2)
    n = np.arange(F.M)
    f0 = np.clip(np.round(3000 * np.cos(2 * np.pi * 1234.3 * n / F.M) + rng.normal(0, 300, F.M)), -11507, 11507)
    f1 = np.where(rng.random(F.M) < 0.5, 11507, -11507)
    f2 = np.round(rng.normal(0, 30, F.M))
    return np.concatenate([f0, f1, f2]).astype(np.int64)


def lane_gen(outdir):
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "lx.hex"), "w") as fo:
        for v in lane_x():
            fo.write("%04x\n" % (int(v) & 0xFFFF))


def lane(outdir, tblog, stalled):
    import re as _re
    x = lane_x().reshape(3, F.M)
    ref = [np.fft.fft(x[f].astype(np.float64)) for f in range(3)]
    rows = [l.split() for l in open(os.path.join(outdir, "lane.txt"))]
    br = F.bitrev(np.arange(F.M), 14)
    order_ok = len(rows) == 3 * F.M
    nd = nexact = 0
    dmax = 0
    for j, (ks, rs, is_, ls) in enumerate(rows):
        f, i = divmod(j, F.M)
        k = int(ks)
        if f >= 3 or k != br[i] or int(ls) != (i == F.M - 1):
            order_ok = False
            continue
        e = ref[f][k]
        d = max(abs(int(rs) - e.real), abs(int(is_) - e.imag))
        er, ei = np.floor(e.real + 0.5), np.floor(e.imag + 0.5)
        if int(rs) == er and int(is_) == ei:
            nexact += 1
        else:
            nd += 1
        dmax = max(dmax, d)
    log = open(tblog, encoding="utf-8", errors="replace").read()
    m = _re.search(r"tready で待った (\d+) クロック（最初に受ける前の待ち \d+）・TLAST の事象 (\d+) / (\d+)", log)
    nst, ntu, ntm = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (-1, -1, -1)
    ymax = max(np.abs(r.real).max() for r in ref)
    print(f"check lane: {len(rows)} 行（期待 {3 * F.M}）・並び（bit 反転順の XK_INDEX・TLAST）{'OK' if order_ok else 'NG'}・"
          f"floor(x + 0.5) と一致 {nexact}・違う {nd}・|RTL − DFT| の最大 {dmax:.3f}・|Y| の最大 {ymax:.0f}（29 bit ≦ 2^28 = 268435456）")
    print(f"check lane: 流し始めた後に tready で待った {nst} クロック（下げを入れた: {stalled}）・TLAST の事象 {ntu} / {ntm}")
    ok = order_ok and dmax < 1.0 and ntu == 0 and ntm == 0 and ((nst > 0) == bool(stalled))
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


def acc_p(f, k1, b):
    """tb_g21_acc の電力の式（64 bit で掛けて下 35 bit）。k1・b は numpy 配列でよい"""
    t = (1315423911 * f + 2654435761 * k1.astype(object) + 97531 * b + 12345) * 2246822519
    return np.array([int(v) & ((1 << 35) - 1) for v in np.ravel(t)], dtype=object).reshape(np.shape(t))


def acc(outdir):
    NA = 9
    k1 = np.arange(F.M)
    ok = True
    for d, name in enumerate("ABC"):
        exp = np.zeros((8, F.M), dtype=object)
        for f in range(d * NA, (d + 1) * NA):
            for b in range(8):
                exp[b] += acc_p(f, k1, b)
        path = os.path.join(outdir, f"rd_{name}.txt")
        rows = [l.split() for l in open(path)] if os.path.exists(path) else []
        nbad = 0
        first = None
        seen = 0
        for cs, vs in rows:
            c = int(cs)
            try:
                v = int(vs)
            except ValueError:
                v = None
            e = int(exp[c >> 14, c & (F.M - 1)])
            if v != e:
                nbad += 1
                if first is None:
                    first = (c, v, e)
            seen += 1
        good = seen == 8 * F.M and nbad == 0
        print(f"check acc: ダンプ {name}（面 {d % 2}）: 読んだ ch {seen} / {8 * F.M}・模型と違う ch {nbad}"
              + (f"（最初: ch {first[0]}: RTL {first[1]} / 期待 {first[2]}）" if first else "")
              + f"・和の最大 {max(int(v) for v in exp.ravel()):,}（48 bit ≦ {(1 << 48) - 1:,}）")
        ok &= good
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


SPEC_NB = 10 * 16384


def spec_x():
    """2c の刺激: T のビートごとの 16 サンプル（int、長さ SPEC_NB·16）。CW 100（ch 40000）＋ 雑音 σ 100"""
    rng = np.random.default_rng(3)
    n = np.arange(SPEC_NB * 16)
    return np.clip(np.round(100 * np.cos(2 * np.pi * 40000 * n / F.N) + rng.normal(0, 100, n.size)), -8192, 8191).astype(np.int64)


def spec_gen(outdir):
    os.makedirs(outdir, exist_ok=True)
    x = spec_x().reshape(-1, 16)
    with open(os.path.join(outdir, "x.hex"), "w") as fo:
        for row in x:
            fo.write("%064x\n" % _pack([(int(v) << 2) & 0xFFFF for v in row], 16))


def spec(outdir, tblog, shift):
    import re as _re
    log = open(tblog, encoding="utf-8", errors="replace").read()
    m = _re.search(r"ダンプ (\d+)・flags (\w+)・SHIFT (\d+)・ipq (\w+)（待たされた (\d+)）・f_first (\d+)・rd の不一致 (\d+)", log)
    if not m:
        print("check spec: tb のログに結果の行が無い（時間切れか途中で落ちた）")
        print("結果: 不合格")
        return False
    ndump, flags, c_shift, ipq, nstall, f_first, nrd = (int(m.group(1)), int(m.group(2), 16), int(m.group(3)), m.group(4),
                                                         int(m.group(5)), int(m.group(6)), int(m.group(7)))
    x = spec_x()
    b0 = f_first * F.M                                      # PFB のフレーム 0 の最初のビート（T = 16384·f_first、K_F 0）
    xs = x[b0 * 16:]
    nfr = len(xs) // F.N
    ok = True
    # ---- A1: PFB の出口 ----
    yref, _ = F.pfb_int(xs[: nfr * F.N], F.coef_interp())
    rows = [l.split() for l in open(os.path.join(outdir, "y.txt"))]
    a1bad = 0
    for j, (ms, hx) in enumerate(rows):
        f, mm = divmod(j, F.M)
        if f >= nfr or int(ms) != mm:
            a1bad += 1
            continue
        w = int(hx, 16)
        got = [sx((w >> (15 * p)) & 0x7FFF, 15) for p in range(16)]
        if got != list(yref[f, 16 * mm: 16 * mm + 16]):
            a1bad += 1
    print(f"check spec A1（PFB の出口）: {len(rows)} ビート（{len(rows) / F.M:.2f} フレーム）・模型と違うビート {a1bad}")
    ok &= a1bad == 0 and len(rows) >= 7 * F.M
    # ---- A2: IP の出口 → 鎖 → 積む ----
    twr, twi = F.tw_prod()
    frames = []
    cur = None
    br_ok = True
    for ks, hx in (l.split() for l in open(os.path.join(outdir, "ip.txt"))):
        k = int(ks)
        if k == 0:
            cur = (np.zeros((16, F.M), dtype=np.int64), np.zeros((16, F.M), dtype=np.int64), [])
            frames.append(cur)
        if cur is None:
            br_ok = False
            continue
        w = int(hx, 16)
        for p in range(16):
            cur[0][p, k] = sx((w >> (64 * p)) & ((1 << 32) - 1), 32)
            cur[1][p, k] = sx((w >> (64 * p + 32)) & ((1 << 32) - 1), 32)
        cur[2].append(k)
    br = list(F.bitrev(np.arange(F.M), 14))
    full = [fr for fr in frames if fr[2] == br]
    print(f"check spec A2: IP の出口のフレーム {len(frames)}（bit 反転順で揃った {len(full)}）")
    lo, hi = -(1 << 17), (1 << 17) - 1
    pw_fr, sat_fr = [], []
    for Yr, Yi, _ in frames:
        Zr, Zi = F.chain_Y(Yr, Yi, twr, twi)
        qr, qi = Zr >> shift, Zi >> shift
        sat = (qr < lo) | (qr > hi) | (qi < lo) | (qi > hi)
        qr, qi = np.clip(qr, lo, hi), np.clip(qi, lo, hi)
        pw_fr.append(qr * qr + qi * qi)
        sat_fr.append(int(sat.sum()))
    # ---- B: 浮動小数点の PFB ＋ FFT ----
    yfl = pfb_float(xs[: nfr * F.N].astype(np.float64), design(F.N), F.N)
    for dname in ("dump1.txt", "dump2.txt"):
        path = os.path.join(outdir, dname)
        if not os.path.exists(path):
            print(f"check spec: {dname} が無い"); ok = False; continue
        lines = open(path).read().split("\n")
        hd = dict(zip(lines[0].split()[1::2], [int(v) for v in lines[0].split()[2::2]]))
        got = np.zeros((8, F.M), dtype=object)
        for k, hx in enumerate(lines[1:1 + F.M]):
            w = int(hx, 16)
            for b in range(8):
                got[b, k] = (w >> (48 * b)) & ((1 << 48) - 1)
        js = [hd["df0"] + i - f_first for i in range(hd["dn"])]
        exp = sum(pw_fr[j].astype(object) for j in js)
        esat = sum(sat_fr[j] for j in js)
        nbad = int(np.sum(got != exp))
        # B: 電力 ≒ |X|² / (16·2^SHIFT)²
        fx = sum(np.abs(core_fft(yfl[j])) ** 2 for j in js) / (16.0 * 2 ** shift) ** 2
        gc = np.array([float(got[c >> 14, c & (F.M - 1)]) for c in range(F.N // 2)])
        cw = 10 * np.log10(gc[40000] / fx[40000])
        mask = np.abs(np.arange(F.N // 2) - 40000) > 3
        mask[:8] = False
        fl = np.median(gc[mask]) / np.median(fx[mask])
        print(f"check spec {dname}: seq {hd['seq']}・dk {hd['dk']}・df0 {hd['df0']}・dn {hd['dn']}・面 {hd['plane']}・"
              f"A2 模型と違う ch {nbad} / {8 * F.M}・dsat {hd['dsat']}（模型 {esat}）・B: CW の ch {cw:+.3f} dB・床の中央値の比 {fl:.4f}")
        ok &= nbad == 0 and hd["dsat"] == esat and hd["dn"] == 2 and abs(cw) < 0.05 and abs(fl - 1) < 0.02
    print(f"check spec: ダンプ {ndump}・flags {flags:02x}・SHIFT {c_shift}・IP に待たされた {nstall} クロック・"
          f"f_first {f_first}・読み出しの口の不一致 {nrd}")
    ok &= ndump == 2 and flags == 0 and c_shift == shift and nrd == 0 and br_ok
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "coef":
        sys.exit(0 if coef(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None) else 1)
    if what == "spec-gen":
        spec_gen(sys.argv[2]); sys.exit(0)
    if what == "spec":
        sys.exit(0 if spec(sys.argv[2], sys.argv[3], int(sys.argv[4])) else 1)
    if what == "acc":
        sys.exit(0 if acc(sys.argv[2]) else 1)
    if what == "lane-gen":
        lane_gen(sys.argv[2]); sys.exit(0)
    if what == "lane":
        sys.exit(0 if lane(sys.argv[2], sys.argv[3], int(sys.argv[4])) else 1)
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
