#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj027 — 2G-4 の部品の sim の判定（model/g24_fixed.py の定義と bit 単位で比べる）。proj025 の check_g22.py（段階 A の版）を写した。2a 以降の分は段階 B で proj025-m0 から写した（名前だけ g24 に。期待の長さはまだ 2G-2、2a〜で直す）。

    python3 sim/check_g24.py coef <sim の出力ディレクトリ> [tb のログ]
    python3 sim/check_g24.py tw   <sim の出力ディレクトリ> [tb のログ]
    python3 sim/check_g24.py pfb-gen <sim の出力ディレクトリ>     （x.hex を書く）
    python3 sim/check_g24.py pfb  <sim の出力ディレクトリ> <tb のログ>
    python3 sim/check_g24.py chain-gen <sim の出力ディレクトリ>   （yre.hex・yim.hex を書く）
    python3 sim/check_g24.py chain <sim の出力ディレクトリ> <tb のログ> <SHIFT>
    python3 sim/check_g24.py lane-gen <sim の出力ディレクトリ>    （lx.hex を書く）
    python3 sim/check_g24.py acc <sim の出力ディレクトリ>
    python3 sim/check_g24.py spec-gen <sim の出力ディレクトリ>    （x.hex を書く）
    python3 sim/check_g24.py spec <sim の出力ディレクトリ> <tb のログ> <SHIFT>
    python3 sim/check_g24.py core <sim の出力ディレクトリ> <tb のログ>        （2d。入力は spec-gen の x.hex）
    python3 sim/check_g24.py s45 <sim の出力ディレクトリ> <tb のログ>         （2e。ADC 2 は spec-gen の x.hex、0・1・3 は adc_x の式）
    python3 sim/check_g24.py ds <sim の出力ディレクトリ> [posctl]             （4d-2。tb_g24_ds の D_S・D_eff）
    python3 sim/check_g24.py lane <sim の出力ディレクトリ> <tb のログ> <tready の下げを入れたか 0|1>
成否は最後の「結果:」の行で読む（make の成功を信用しない）。
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import g24_fixed as F  # noqa: E402
import s2_model as S2  # noqa: E402  proj030: IP の出口（8 個の複素の Z）から先は 2-for-1 の定義（S2.power_s2）
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
    # k1_out の並び: M − 1 の待ちの後に bit 反転順の 0..M − 1 ＋ 頭 256、その後 M − 1
    exp = [int(F.bitrev(np.array([i % F.M]), F.KB)[0]) for i in range(F.M + 256)]
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
    """1c の刺激: 雑音 σ 100 ＋ CW 1000（ch 20000）、フレーム 3 の頭の 2000 ビートは ±8191 の満杯（PFB の出口の最大に近づける。
    y は Σ|c| ≦ 1.405 なので 15 bit で飽和しない — M-4。sat_cnt は 0 のはず）。int、長さ PRE·16 + NF·N。"""
    rng = np.random.default_rng(1)
    n = np.arange(NF * F.N)
    x = np.round(1000 * np.cos(2 * np.pi * 20000 * n / F.N) + rng.normal(0, 100, NF * F.N))
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
    1: 雑音だけ σ 30、2: 最悪の同相（y がすべて +11507 → k1 = 0 で |Y| = 11507·4096、27 bit に入る）。戻り値 [(Yr, Yi)] × 3（各 (16, M)）"""
    rng = np.random.default_rng(4)
    n = np.arange(4 * F.N)
    x = np.clip(np.round(1000 * np.cos(2 * np.pi * 20000 * n / F.N) + rng.normal(0, 100, 4 * F.N)), -8192, 8191).astype(np.int64)
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
    br = F.bitrev(np.arange(F.M), F.KB)
    with open(os.path.join(outdir, "yre.hex"), "w") as fr_, open(os.path.join(outdir, "yim.hex"), "w") as fi_:
        for Yr, Yi in fr:
            assert max(np.abs(Yr).max(), np.abs(Yi).max()) < (1 << 26), "Y が 27 bit に入らない"
            for i in range(F.M):
                k = br[i]
                fr_.write("%0108x\n" % _pack(Yr[:, k], 27))
                fi_.write("%0108x\n" % _pack(Yi[:, k], 27))
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
    br = F.bitrev(np.arange(F.M), F.KB)
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
    br = F.bitrev(np.arange(F.M), F.KB)
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
          f"floor(x + 0.5) と一致 {nexact}・違う {nd}・|RTL − DFT| の最大 {dmax:.3f}・|Y| の最大 {ymax:.0f}（27 bit ≦ 2^26 = 67108864）")
    print(f"check lane: 流し始めた後に tready で待った {nst} クロック（下げを入れた: {stalled}）・TLAST の事象 {ntu} / {ntm}")
    ok = order_ok and dmax < 1.0 and ntu == 0 and ntm == 0 and ((nst > 0) == bool(stalled))
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


def acc_p(f, k1, b):
    """tb_g24_acc の電力の式（64 bit で掛けて下 35 bit）。k1・b は numpy 配列でよい"""
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
            e = int(exp[c >> F.KB, c & (F.M - 1)])
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


SPEC_NB = 12 * 4096   # tb の NB と同じ。proj027 で 10 → 12 フレーム（2c の 1 回目、入力が 2 個目のダンプの後の待ちの間に尽き、flags[2] が立った）


def spec_x():
    """2c の刺激: T のビートごとの 16 サンプル（int、長さ SPEC_NB·16）。CW 100（ch 20000）＋ 雑音 σ 100"""
    rng = np.random.default_rng(3)
    n = np.arange(SPEC_NB * 16)
    return np.clip(np.round(100 * np.cos(2 * np.pi * 20000 * n / F.N) + rng.normal(0, 100, n.size)), -8192, 8191).astype(np.int64)


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
    b0 = f_first * F.M                                      # PFB のフレーム 0 の最初のビート（T = 4096·f_first、K_F 0）
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
    br = list(F.bitrev(np.arange(F.M), F.KB))
    full = [fr for fr in frames if fr[2] == br]
    print(f"check spec A2: IP の出口のフレーム {len(frames)}（bit 反転順で揃った {len(full)}）")
    lo, hi = -(1 << 17), (1 << 17) - 1
    pw_fr, sat_fr = [], []
    for Yr, Yi, _ in frames:
        pw, ns = S2.power_s2(Yr[:S2.NQ], Yi[:S2.NQ], twr, twi, shift)   # proj030: ip.txt の下 8 個が IP の Z
        pw_fr.append(pw)
        sat_fr.append(ns)
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
        # B: 電力 ≒ |X|² / (2^(D1+2)·2^SHIFT)²（Y の丸め 2^D1 × ひねり係数 2^16 / cmul の SH 2^18 = 1/4）。
        #    2G-1 は D1 = 2 で 16。2G-2 は D1 = 1 で 8（proj025 2c の 1 回目は 16 のままで、CW・床とも +6.02 dB で落ちた）。2G-4 は D1 = 0 で 4
        fx = sum(np.abs(core_fft(yfl[j])) ** 2 for j in js) / (float(1 << (F.D1 + 2)) * 2 ** shift) ** 2
        gc = np.array([float(got[c >> F.KB, c & (F.M - 1)]) for c in range(F.N // 2)])
        cw = 10 * np.log10(gc[20000] / fx[20000])
        mask = np.abs(np.arange(F.N // 2) - 20000) > 3
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


# ---- 2d: g24_core（レコード・TP・レジスタ）----
CORE_SID, CORE_RC, CORE_SHIFT, CORE_NACC, CORE_TPN, CORE_TPK = 2, 1, 4, 2, 16, 4
S45_TPN = 8   # tb_g24_s45 の TP_N（FULL・コアとも）。proj027: 2G-2 と同じ「1 個 = 1 フレーム」に（16 では TP の溜めが溢れず、捨てた数の見張りが立たなかった）
MAGIC = 0x52353453


def _records(path):
    """rec.txt → [(tuser, [u64 ...])]（tlast で区切る）"""
    recs, cur = [], []
    for l in open(path):
        tl, tu, hx = l.split()
        cur.append(int(hx, 16))
        if tl == "1":
            recs.append((int(tu), cur))
            cur = []
    return recs, len(cur)


def core(outdir, tblog):
    import re as _re
    log = open(tblog, encoding="utf-8", errors="replace").read()
    m = _re.search(r"ダンプ (\d+)・SPEC のレコード (\d+)・レコード (\d+)・src_sel (\d+)・rec_drop のクロック (\d+)・flags (\w+)", log)
    if not m:
        print("check core: tb のログに結果の行が無い（時間切れか途中で落ちた）")
        print("結果: 不合格")
        return False
    ndump, nspec, nrec, src_sel, ndrop, flags = [int(m.group(i)) for i in range(1, 6)] + [int(m.group(6), 16)]
    ok = True
    regs = {}
    for l in open(os.path.join(outdir, "regs.txt")):
        name, _a, hx = l.split()
        regs[name] = int(hx, 16)
    recs, tail = _records(os.path.join(outdir, "rec.txt"))
    spec_r = [r for r in recs if (r[1][0] >> 40) & 0xFF == 1]
    tp_r = [r for r in recs if (r[1][0] >> 40) & 0xFF == 2]
    print(f"check core: レコード {len(recs)}（SPEC {len(spec_r)}・TP {len(tp_r)}・途中で切れた語 {tail}）・ダンプ {ndump}・"
          f"src_sel {src_sel}・rec_drop {ndrop}・flags {flags:02x}")
    ok &= ndump == 1 and len(spec_r) == 1 and src_sel == 2 and flags == 0 and len(recs) == len(spec_r) + len(tp_r)

    # ---- ダンプの期待: IP の出口 → 鎖（SHIFT 4）→ 積む（2c の A2 と同じ）----
    lines = open(os.path.join(outdir, "dump1.txt")).read().split("\n")
    hd = dict(zip(lines[0].split()[1::2], [int(v) for v in lines[0].split()[2::2]]))
    snap = np.zeros((8, F.M), dtype=object)
    for k, hx in enumerate(lines[1:1 + F.M]):
        w = int(hx, 16)
        for b in range(8):
            snap[b, k] = (w >> (48 * b)) & ((1 << 48) - 1)
    twr, twi = F.tw_prod()
    frames, cur = [], None
    for ks, hx in (l.split() for l in open(os.path.join(outdir, "ip.txt"))):
        k = int(ks)
        if k == 0:
            cur = (np.zeros((16, F.M), dtype=np.int64), np.zeros((16, F.M), dtype=np.int64))
            frames.append(cur)
        if cur is None:
            continue
        w = int(hx, 16)
        for p in range(16):
            cur[0][p, k] = sx((w >> (64 * p)) & ((1 << 32) - 1), 32)
            cur[1][p, k] = sx((w >> (64 * p + 32)) & ((1 << 32) - 1), 32)
    lo, hi = -(1 << 17), (1 << 17) - 1
    exp = np.zeros((8, F.M), dtype=object)
    esat = 0
    for i in range(hd["dn"]):
        Yr, Yi = frames[hd["df0"] + i - hd["f_first"]]
        pw, ns = S2.power_s2(Yr[:S2.NQ], Yi[:S2.NQ], twr, twi, CORE_SHIFT)   # proj030
        esat += ns
        exp += pw.astype(object)
    nsnap = int(np.sum(snap != exp))
    print(f"check core ダンプ: seq {hd['seq']}・dk {hd['dk']}・df0 {hd['df0']}・dn {hd['dn']}・dsat {hd['dsat']}（模型 {esat}）・"
          f"凍った面と模型の違う ch {nsnap}")
    ok &= nsnap == 0 and hd["dsat"] == esat and hd["dn"] == CORE_NACC and hd["seq"] == 1

    # ---- SPEC のレコード ----
    if spec_r:
        tu, w = spec_r[0]
        body = w[8:]
        f0 = hd["df0"]
        eh = [
            MAGIC | (1 << 32) | (1 << 40) | (CORE_RC << 48) | (CORE_SID << 56),
            hd["seq"] | (hd["dk"] << 32),
            f0,
            F.M * f0,                                                   # DUMP_T = K_F ＋ 4096·DUMP_F0（K_F 0）
            16 | (0 << 8) | (CORE_SHIFT << 16) | (0 << 24) | (0 << 32) | (2 << 40) | (0 << 48),   # DUMP_H 0・src 2
            hd["dn"] | (hd["dsat"] << 32),
            0x00C0FFEE | (0 << 32),
            (F.M * 8 * 8) | (0 << 32),                                  # 256 KiB・KIND に固有 0
        ]
        hbad = [i for i in range(8) if w[i] != eh[i]]
        ebody = [int(exp[c >> F.KB, c & (F.M - 1)]) for c in range(8 * F.M)]
        nb = sum(1 for a, b in zip(body, ebody) if a != b) + abs(len(body) - len(ebody))
        first = next((c for c, (a, b) in enumerate(zip(body, ebody)) if a != b), None)
        print(f"check core SPEC: 語 {len(w)}（期待 {8 + 8 * F.M}）・tuser {tu}・頭の違う語 {hbad}"
              + "".join(f"（語 {i}: {w[i]:016x} / 期待 {eh[i]:016x}）" for i in hbad)
              + f"・中身の模型と違う ch {nb}" + (f"（最初 ch {first}: {body[first]} / 期待 {ebody[first]}）" if first is not None else ""))
        ok &= tu == 0 and len(w) == 8 + 8 * F.M and not hbad and nb == 0
    # ---- TP のレコード（RUN の F0 × 16 から 16 小フレームの区切り × 4。2G-1 は × 32）----
    x = spec_x().reshape(-1, 16)
    x2 = (x.astype(np.int64) ** 2).sum(axis=1)                       # ビートごとの Σx²
    tf0 = (F.M // 512) * hd["df0"]
    nfull, nbad_it, hdr_bad, aligned = 0, 0, 0, False
    # 捨てた TP のレコード: SEQ（最初の個の TP_WP）の飛びから数える。tb は TP を 2 フレームに 1 レコードに詰めたので、256 KiB の SPEC が出口を
    # 塞ぐ間（≒ 15 万クロック）に TP の溜め 2 面が溢れて捨てる（実際の 10.24 ms ごとなら 20 倍の余裕）。捨てた数 = TP_REC_LATE = rec_drop を照らす
    gap_items = sum((b[1][1] & 0xFFFFFFFF) - ((a[1][1] & 0xFFFFFFFF) + (a[1][5] & 0xFFFFFFFF)) for a, b in zip(tp_r, tp_r[1:]))
    for tu, w in tp_r:
        n = w[5] & 0xFFFFFFFF
        rf0, rt = w[2], w[3]
        if (w[0] & 0xFFFFFFFFFFFF) != (MAGIC | (1 << 32) | (2 << 40)) or (w[0] >> 48) & 0xFF != CORE_RC or (w[0] >> 56) != CORE_SID \
                or rt != 512 * rf0 or tu != 0 or (w[7] & 0xFFFFFFFF) != ((n + 3) // 4) * 64:
            hdr_bad += 1
        if rf0 < tf0:
            continue
        aligned |= rf0 == tf0
        for i in range(n):
            s, hw = w[8 + 2 * i], w[9 + 2 * i]
            f0lo, nfr, fl = hw & 0xFFFFFFFF, (hw >> 32) & 0xFFFFFF, hw >> 56
            sb = f0lo * 512
            e = int(sum(int(x2[b]) for b in range(sb, sb + 512 * CORE_TPN) if b < len(x2)))
            efl = 2 if (f0lo == tf0) else 0
            if s != e or nfr != CORE_TPN or fl != efl or f0lo != rf0 + CORE_TPN * i:
                nbad_it += 1
            nfull += 1
    tlate = regs.get("TP_REC_LATE", -1)
    print(f"check core TP: レコード {len(tp_r)}・頭の誤り {hdr_bad}・ダンプと同じ T から始まるレコード {'あり' if aligned else '無し'}"
          f"（期待の F0 {tf0} 小フレーム = T {512 * tf0}・SPEC の DUMP_T {F.M * hd['df0']}）・F0 以後の個 {nfull}・模型と違う個 {nbad_it}・"
          f"SEQ の飛び {gap_items} 個（= {gap_items / CORE_TPK:g} レコード）・TP_REC_LATE {tlate}・rec_drop {ndrop}")
    ok &= hdr_bad == 0 and aligned and nfull >= 8 and nbad_it == 0
    ok &= gap_items == CORE_TPK * tlate and tlate == ndrop and regs.get("REC_LATE") == 0
    # ---- レジスタ ----
    er = {"SRC_pre": 0x80000000, "SRC": 0x80000002, "WRST_CFG": 0x00C0FFEE, "RUN_SHIFT0": 7, "RUN_SHIFT1": CORE_SHIFT,
          "RUN_F0": hd["df0"], "TP_F0": tf0, "TP_NEFF": CORE_TPN,
          "SID": 0x02010000 | (CORE_SID << 8), "PARAM": 0x00400010, "FLAGS": 0, "SEQ": 1, "NCH": 32768, "FRAME_BEATS": 4096,
          "DUMP_K": hd["dk"], "DUMP_F0": hd["df0"], "DUMP_N": hd["dn"], "DUMP_SAT": hd["dsat"],
          "DUMP_T_LO": (F.M * hd["df0"]) & 0xFFFFFFFF, "DUMP_T_HI": (F.M * hd["df0"]) >> 32, "DUMP_H": 0, "DUMP_CFG": 0x00C0FFEE,
          "NFFT_MM": 0x1010, "REC_CTRL": 1, "REC_LATE": 0, "BUILD_TAG": 0x20240d00}
    rbad = [(k, regs.get(k), v) for k, v in er.items() if regs.get(k) != v]
    print(f"check core レジスタ: {len(er)} 個・違う {len(rbad)}" + "".join(f"（{k}: {g if g is None else hex(g)} / 期待 {hex(v)}）" for k, g, v in rbad)
          + f"・CTRL {regs.get('CTRL', 0):08x}")
    ok &= not rbad
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


# ---- 2e: g24_s45_core（コア 1 個: 共通・FULL（s 0）・RAW（s 1）・axis_sel4 × 2）----
def adc_x(adc, T):
    """tb_g24_s45 の ADC の値（14 bit の整数、shape (len(T), 16)）。ADC 2 は 2c の刺激（T < SPEC_NB、その後は 0）、ほかは式"""
    T = np.asarray(T, dtype=np.int64)
    if adc == 2:
        x = spec_x().reshape(-1, 16)
        out = np.zeros((len(T), 16), dtype=np.int64)
        ok = (T >= 0) & (T < len(x))
        out[ok] = x[T[ok]]
        return out
    n = ((16 * T[:, None] + np.arange(16)[None, :]) & 0xFFFFFFFF).astype(np.uint64)
    h = ((n * np.uint64(0x9E3779B1)) & np.uint64(0xFFFFFFFF)) ^ np.uint64(adc << 20)
    v = ((h >> np.uint64(17)) & np.uint64(0x3FFF)).astype(np.int64)
    return np.where(v & 0x2000, v - 0x4000, v)


def _tp_check(recs, adc, off, tpn, name):
    """TP のレコードの個の Σx² を ADC の値と比べる。データの T = 個の頭の T（レコードの DUMP_T ＋ 512·tpn·i）＋ off"""
    nit, nbad = 0, 0
    for tu, w in recs:
        n = w[5] & 0xFFFFFFFF
        for i in range(n):
            s, hw = w[8 + 2 * i], w[9 + 2 * i]
            nfr, fl = (hw >> 32) & 0xFFFFFF, hw >> 56
            if nfr != tpn or (fl & 1):
                continue                                    # 短い個（起動・F0 の前）は数えない
            t0 = w[3] + 512 * tpn * i + off
            e = int((adc_x(adc, np.arange(t0, t0 + 512 * tpn)) ** 2).sum())
            nit += 1
            nbad += s != e
    return nit, nbad


def s45(outdir, tblog):
    import re as _re
    log = open(tblog, encoding="utf-8", errors="replace").read()
    m = _re.search(r"ダンプ (\d+)・SPEC のレコード (\d+)・レコード (\d+)・full_sel (\d+)・raw_sel (\d+)・rec_drop の和 (\d+)・flags (\w+)", log)
    if not m:
        print("check s45: tb のログに結果の行が無い（時間切れか途中で落ちた）")
        print("結果: 不合格")
        return False
    ndump, nspec, nrec, fsel, rsel, ndrop = [int(m.group(i)) for i in range(1, 7)]
    flags = int(m.group(7), 16)
    regs = {}
    for l in open(os.path.join(outdir, "regs.txt")):
        name, _a, hx = l.split()
        regs[name] = int(hx, 16)
    ok = True
    recs, tail = _records(os.path.join(outdir, "rec.txt"))
    def kind(w):
        return ((w[0] >> 40) & 0xFF, w[0] >> 56)
    spec_r = [r for r in recs if kind(r[1]) == (1, 0)]
    ftp_r = [r for r in recs if kind(r[1]) == (2, 0)]
    ctp_r = [r for r in recs if kind(r[1]) == (2, 0xFF)]
    snap_r = [r for r in recs if kind(r[1]) == (4, 1)]
    other = len(recs) - len(spec_r) - len(ftp_r) - len(ctp_r) - len(snap_r)
    print(f"check s45: レコード {len(recs)}（SPEC {len(spec_r)}・FULL の TP {len(ftp_r)}・コアの TP {len(ctp_r)}・SNAP {len(snap_r)}・"
          f"ほか {other}・途中で切れた語 {tail}）・ダンプ {ndump}・full_sel {fsel}・raw_sel {rsel}・flags {flags:02x}")
    ok &= ndump == 1 and len(spec_r) == 1 and other == 0 and fsel == 2 and rsel == 1 and flags == 0 and all(r[0] == 0 for r in recs)
    ok &= all(((w[0] >> 48) & 0xFF) == 0 and (w[0] & 0xFFFFFFFFFF) == (MAGIC | (1 << 32)) for _, w in recs)

    # ---- レジスタ（番地の振り分け）----
    er = {"IF_ID": 0x02030101, "PROJ": 0x00310200, "NSTREAM": 2, "FFT_N": 0, "SID0": 0x02010000, "SID1": 0x02040100, "SID_none": 0,
          "NCH0": 32768, "NCH1": 0, "SRC0": 0x80000002, "SRC1": 0x80000001, "SEQ0": 1, "SEQ1": 2, "FLAGS0": 0, "FLAGS1": 0}
    rbad = [(k, regs.get(k), v) for k, v in er.items() if regs.get(k) != v]
    print(f"check s45 レジスタ: {len(er)} 個・違う {len(rbad)}" + "".join(f"（{k}: {g if g is None else hex(g)} / 期待 {hex(v)}）" for k, g, v in rbad))
    ok &= not rbad

    # ---- SPEC（2d と同じ: IP の出口 → chain_Y → 積む）----
    lines = open(os.path.join(outdir, "dump1.txt")).read().split("\n")
    hd = dict(zip(lines[0].split()[1::2], [int(v) for v in lines[0].split()[2::2]]))
    twr, twi = F.tw_prod()
    frames, cur = [], None
    for ks, hx in (l.split() for l in open(os.path.join(outdir, "ip.txt"))):
        k = int(ks)
        if k == 0:
            cur = (np.zeros((16, F.M), dtype=np.int64), np.zeros((16, F.M), dtype=np.int64))
            frames.append(cur)
        if cur is None:
            continue
        w = int(hx, 16)
        for p in range(16):
            cur[0][p, k] = sx((w >> (64 * p)) & ((1 << 32) - 1), 32)
            cur[1][p, k] = sx((w >> (64 * p + 32)) & ((1 << 32) - 1), 32)
    lo, hi = -(1 << 17), (1 << 17) - 1
    exp = np.zeros((8, F.M), dtype=object)
    for i in range(hd["dn"]):
        Yr, Yi = frames[hd["df0"] + i - hd["f_first"]]
        exp += S2.power_s2(Yr[:S2.NQ], Yi[:S2.NQ], twr, twi, CORE_SHIFT)[0].astype(object)   # proj030
    if spec_r:
        tu, w = spec_r[0]
        ebody = [int(exp[c >> F.KB, c & (F.M - 1)]) for c in range(8 * F.M)]
        nb = sum(1 for a, b in zip(w[8:], ebody) if a != b) + abs(len(w) - 8 - len(ebody))
        src = (w[4] >> 40) & 0xFF
        print(f"check s45 SPEC: 語 {len(w)}・DUMP_F0 {w[2]}・DUMP_T {w[3]}・src {src}・中身の模型と違う ch {nb}")
        ok &= len(w) == 8 + 8 * F.M and nb == 0 and src == 2 and w[3] == F.M * w[2] and w[2] == hd["df0"]

    # ---- TP: データの T と頭の T のずれを {−1, 0, +1} で調べ、予言（FULL −1・コア +1）と比べる ----
    res = {}
    for name, rr, adc, pred in (("FULL の TP（ADC 2）", ftp_r, 2, -1), ("コアの TP（ADC 0）", ctp_r, 0, +1)):
        found = []
        for off in (-1, 0, 1):
            nit, nbad = _tp_check(rr, adc, off, S45_TPN, name)
            if nit and nbad == 0:
                found.append(off)
        nit, nbad = _tp_check(rr, adc, pred, S45_TPN, name)
        print(f"check s45 {name}: レコード {len(rr)}・個 {nit}・予言のずれ {pred:+d} で違う個 {nbad}・合うずれ {found}")
        ok &= nit >= 4 and nbad == 0 and found == [pred]
        res[name] = found
    ft0 = [w[2] for _, w in ftp_r]
    print(f"check s45 FULL の TP の F0: {sorted(ft0)[:6]}…（期待 {(F.M // 512) * hd['df0']} がある）")
    ok &= ((F.M // 512) * hd["df0"]) in ft0
    # ---- SNAP（RAW、ADC 1）: 語 j = サンプル 4j〜4j+3。予言のずれ 0（DUMP_T = データの T）----
    nsb = 0
    for tu, w in snap_r:
        T0 = w[3]
        x = adc_x(1, np.arange(T0, T0 + 512))
        e = []
        for mm in range(512):
            for q in range(4):
                vv = 0
                for r in range(4):
                    vv |= ((int(x[mm, 4 * q + r]) << 2) & 0xFFFF) << (16 * r)
                e.append(vv)
        bad = sum(1 for a, b in zip(w[8:], e) if a != b) + abs(len(w) - 8 - len(e))
        src = (w[4] >> 40) & 0xFF
        print(f"check s45 SNAP: SEQ {w[1] & 0xFFFFFFFF}・DUMP_T {T0}・src {src}・語 {len(w)}・ADC 1（ずれ 0）と違う語 {bad}")
        nsb += bad + (src != 1) + (len(w) != 8 + 2048)
    ok &= len(snap_r) == 2 and nsb == 0
    # ---- 捨てた数の帳尻（rec_drop の和 = 4 本の LATE の和）----
    lates = {k: regs.get(k, -1) for k in ("REC_LATE0", "TP_REC_LATE0", "REC_LATE1", "TP_REC_LATEc")}
    print(f"check s45 捨てた数: rec_drop の和 {ndrop}・LATE {lates}（和 {sum(lates.values())}）")
    ok &= ndrop == sum(lates.values()) and lates["TP_REC_LATE0"] >= 1
    print("結果: 全部通過" if ok else "結果: 不合格")
    return ok


# ---- 4d-2: FULL の流れの遅れ D_eff = D_S ＋ 1.5·L（tb_g24_ds、proj023 の check_ds と同じ形）----
def ds(outdir, posctl=False):
    """インパルスごとに:
      T_raw  = RAW の SNAP のレコードの DUMP_T ＋ そのサンプルのビート（(i) だけ。F-2 が adc_to_core を測る道）
      T_full = K_F ＋ 4096·g ＋ m。m はレーン p の IP の出口の位置（単独のサンプルなら Y[k1] = y·e^{−2πi k1 m / 4096}）、
               g はそのサンプルが入ったフレームのラベル（4 つの出口 g..g＋3 の y が、模型の PFB（F.pfb_int）の 4 タップと**全部一致**する g）
      見るもの: (1) RAW: T_raw = tb が ADC に入れた T（2e のずれ 0 をインパルスで）。(ii) は RAW に写らないので T_raw = tb の T とする
               (2) **D_S = T_full − T_raw が全部のインパルスで同じ値で、+1**（通常）/ 0（陽性対照: FULL の口に axis_sel4 の段が無い）
               (3) 位相 m がフレームの境目（4095・0）を通った
               (4) 実効の区間の重心: 係数 c² の重心が矩形より 1.5·L（6,144 ビート）前"""
    meta = {}
    for line in open(os.path.join(outdir, "meta.txt")):
        k, v = line.split()
        meta[k] = int(v)
    imps = [(int(a), int(b), int(c)) for _, a, b, c in (l.split() for l in open(os.path.join(outdir, "imp.txt")))]
    KF, ff, A = meta["KF"], meta["f_first"], meta["A"]
    ok = True
    ng = []

    def J(cond, msg):
        print(("OK  " if cond else "NG  ") + msg)
        if not cond:
            ng.append(msg)
        return cond

    J(meta["flags"] == 0 and meta["full_sel"] == 2 and meta["raw_sel"] == 2,
      f"flags {meta['flags']:02x}・full_sel {meta['full_sel']}・raw_sel {meta['raw_sel']}（期待 0・2・2）")
    J(meta["nimp"] == len(imps) and len(imps) >= 4, f"インパルス {len(imps)} 個（tb の数 {meta['nimp']}）")
    # ---- RAW ----
    recs, _tail = _records(os.path.join(outdir, "rec.txt"))
    hits = []
    nsnap = 0
    for _tu, w in recs:
        if ((w[0] >> 40) & 0xFF, w[0] >> 56) != (4, 1):
            continue
        nsnap += 1
        dt = w[3]
        for jw, x in enumerate(w[8:8 + 2048]):
            if x == 0:
                continue
            for q in range(4):
                vv = (x >> (16 * q)) & 0xFFFF
                if vv:
                    s_ = 4 * jw + q
                    hits.append((dt + s_ // 16, s_ % 16, vv - 65536 if vv >= 32768 else vv))
    imp_i = [x for x in imps if x[2] == 0]
    traw = {}
    for t_imp, p, _k in imp_i:
        h = [x for x in hits if x[1] == p and abs(x[0] - t_imp) < 600]
        if len(h) == 1 and h[0][2] == 4 * A:
            traw[t_imp] = h[0][0]
    J(len(hits) == len(imp_i) and len(traw) == len(imp_i),
      f"RAW: SNAP {nsnap} 個に写ったインパルス {len(hits)} 個（(i) は {len(imp_i)} 個）、値はどれも 16 bit の {4 * A}")
    J(all(traw[t] == t for t in traw), "RAW: T_raw = tb が ADC に入れた T（ずれ 0）: " + ", ".join(f"{traw[t] - t:+d}" for t in sorted(traw)))
    # ---- FULL: IP の出口 ----
    lanes = {}
    nx = 0
    for line in open(os.path.join(outdir, "lanes.txt")):
        r, k1, p, re_, im_ = line.split()
        if re_ == "x":
            nx += 1
            continue
        lanes.setdefault((int(r), int(p)), {})[int(k1)] = int(re_) + 1j * int(im_)
    J(nx == 0, f"IP の出口に x・z の値 {nx}")
    used = set()
    c = F.coef_interp()
    ds_, ms, rows, bad = [], [], [], 0
    for t_imp, p, kind in imps:
        g0 = (t_imp - KF) // F.M
        got = {}
        for (r, pp), d in lanes.items():
            lab = ff + r
            if pp != p or not (g0 - 1 <= lab <= g0 + 5):        # 足は g..g＋3（g は g0 か g0 ＋ 1）。±6 では前のインパルスの足が同じレーンに入る（4d-2 の 1 回目）
                continue
            Y = np.zeros(F.M, dtype=complex)
            for k1, val in d.items():
                Y[k1] = val
            yr = np.fft.ifft(Y)
            m = int(np.argmax(np.abs(yr)))
            y0 = int(round(yr[m].real))
            if y0 != 0:
                got[lab] = (y0, m)
                used.add((r, pp))
        mset = {m for _, m in got.values()}
        if len(mset) != 1:
            bad += 1
            rows.append(f"T_imp {t_imp}: 出口の位置がそろわない {sorted(got.items())}")
            continue
        m = mset.pop()
        x = np.zeros(7 * F.N, np.int64)
        x[3 * F.N + 16 * m + p] = A
        y, _ = F.pfb_int(x, c)
        pt = [int(y[3 + k][16 * m + p]) for k in range(4)]
        g = None
        for gc in range(min(got) - 3, min(got) + 1):
            if {gc + k: pt[k] for k in range(4) if pt[k] != 0} == {lab: yv for lab, (yv, _) in got.items()}:
                g = gc
        if g is None:
            bad += 1
            rows.append(f"T_imp {t_imp}: 4 タップの値が模型と合う g が無い（出口 {[(k, v[0]) for k, v in sorted(got.items())]}、模型 {pt}）")
            continue
        t_full = KF + F.M * g + m
        t_raw = traw.get(t_imp, t_imp) if kind == 0 else t_imp
        ds_.append(t_full - t_raw)
        ms.append(m)
        rows.append(f"T_imp {t_imp}（{'(i) RAW' if kind == 0 else '(ii) 境目'}）レーン {p:2d}: FULL のフレーム {g} の m {m:5d} → T_full {t_full}・"
                    f"T_raw {t_raw}・D_S {t_full - t_raw:+d}（タップ {pt}）")
    for x_ in rows:
        print("  " + x_)
    J(bad == 0 and len(ds_) == len(imps), f"FULL: インパルス {len(ds_)} 個とも、4 つの出口の y が模型の PFB の 4 タップと一致し、位置 m がそろった（NG {bad}）")
    nstray = sum(1 for k in lanes if k not in used)
    J(nstray == 0, f"FULL: インパルスに対応しない 0 でない出口（フレーム × レーン）{nstray}")
    J((F.M - 1) in ms and 0 in ms, f"フレームの境目（m = {F.M - 1}・0）を通った（m の集合 {sorted(set(ms))}）")
    one = len(set(ds_)) == 1
    J(one, f"D_S がどのインパルスでも同じ（{sorted(set(ds_))}）")
    ok1 = J(one and ds_[0] == 1, f"**D_S = {ds_[0] if ds_ else None} ビート**（期待 +1: FULL は axis_sel4 の 1 段の後で同じクロックの T、RAW は 1 クロック前の T）")
    w = c.astype(np.float64) ** 2
    cen = float((w * np.arange(len(c))).sum() / w.sum())
    d_pfb = (3 * F.N + (F.N - 1) / 2.0 - cen) / 16
    J(abs(d_pfb - 1.5 * F.M) < 1e-6, f"実効の区間の重心: 矩形より {d_pfb:.6f} ビート前（1.5·L = {1.5 * F.M:.0f}）")
    print(f"D_eff（FULL）= D_S ＋ 1.5·L = {int(round(ds_[0] + d_pfb)) if one and ds_ else None} ビート")
    if posctl:
        ok = (not ok1) and one and ds_ and ds_[0] == 0 and len(ng) == 1
        print(f"結果: 全部通過（陽性対照が落ちるべきところで落ちた: D_S {ds_[0]:+d}）" if ok else "結果: 不合格（陽性対照が落ちなかった・ほかも落ちた）")
        return ok
    ok = not ng
    print("結果: 全部通過" if ok else f"結果: 不合格（NG {len(ng)} 件）")
    return ok


if __name__ == "__main__":
    what = sys.argv[1]
    if what == "coef":
        sys.exit(0 if coef(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None) else 1)
    if what == "spec-gen":
        spec_gen(sys.argv[2]); sys.exit(0)
    if what == "spec":
        sys.exit(0 if spec(sys.argv[2], sys.argv[3], int(sys.argv[4])) else 1)
    elif what == "core":
        sys.exit(0 if core(sys.argv[2], sys.argv[3]) else 1)
    elif what == "s45":
        sys.exit(0 if s45(sys.argv[2], sys.argv[3]) else 1)
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
    if what == "ds":
        sys.exit(0 if ds(sys.argv[2], len(sys.argv) > 3 and sys.argv[3] == "posctl") else 1)
    if what == "tw":
        sys.exit(0 if tw(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None) else 1)
    sys.exit(2)
