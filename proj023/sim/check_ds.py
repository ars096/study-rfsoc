#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj023 手順 4e — tb_wide_ds の判定: SLICE の遅れ D_S = T_slice − T_raw（INTERFACE 5.2 の D_eff = D_S ＋ 1.5·L の D_S）

    python3 sim/check_ds.py OUT            # 通常（RAW の口は axis_sel4 の 1 段ぶん遅れる。実機の配線）
    python3 sim/check_ds.py OUT posctl     # -DDS_NODELAY の陽性対照（D_S が 0 でない値に動くはず → 判定は落ちるべき）

インパルスごとに:
  T_raw   = RAW の SNAP のレコード（F-2 が adc_to_core を測る道）の DUMP_T ＋ そのサンプルのビート（8192 サンプルの添字 // 16）
  T_slice = K_F ＋ 2048·g ＋ m。m はレーン p の IP の出口の位相（単独のサンプルなら Y[k1] = y·e^{−2πi k1 m / 2048}）、
            g はそのサンプルが入ったフレームのラベル（4 つの出口 g..g＋3 の y が、模型の PFB（check_wide.pfb_int）の 4 タップの値と**全部一致**する g）
  見るもの: (1) T_slice が tb が SLICE の口に入れた T と同じ（wide_spec は口のビートに同じクロックの T を付ける）
           (2) **D_S が全部のインパルスで同じ値で、0**（通常）/ 0 でない（陽性対照）
           (3) 位相 m がフレームの境目（2047・0）を含む（境目の取り違えを見られた）
           (4) 実効の区間の重心: 係数 c² の重心が「新しいフレームの頭 − 1.0 フレーム」→ 矩形との差が 1.5·L（3072 ビート）ちょうど
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_wide as C                                         # noqa: E402


def load(out):
    meta = {}
    for line in open(os.path.join(out, "meta.txt")):
        k, v = line.split()
        meta[k] = int(v)
    imps = []
    for line in open(os.path.join(out, "imp.txt")):
        _, t, p = line.split()
        imps.append((int(t), int(p)))
    recs, cur = [], []
    for line in open(os.path.join(out, "recs.txt")):
        t = line.split()
        if t[0] == "r":
            cur.append(int(t[2], 16))
        else:
            recs.append(cur)
            cur = []
    lanes = {}
    for line in open(os.path.join(out, "lanes.txt")):
        v = line.split()
        r, k1 = int(v[0]), int(v[1])
        vals = np.array(v[2:], dtype=np.int64)
        lanes.setdefault(r, {})[k1] = vals[0::2] + 1j * vals[1::2]
    return meta, imps, recs, lanes


def raw_hits(recs):
    """RAW の SNAP のレコードから、0 でないサンプルを (T_raw, レーン, 値) で"""
    out = []
    for r in recs:
        if not r or ((r[0] >> 40) & 0xFF) != 4:
            continue
        dt = r[3]
        pay = r[8:8 + 2048]
        for w, x in enumerate(pay):
            if x == 0:
                continue
            for q in range(4):
                v = (x >> (16 * q)) & 0xFFFF
                if v:
                    s = 4 * w + q
                    out.append((dt + s // 16, s % 16, v - 65536 if v >= 32768 else v))
    return out


def pred_taps(m, p, a14):
    """フレーム g の (m, p) に a14 の単独のサンプル → 出口 g..g＋3 の y（模型の PFB、丸め・飽和を含む）"""
    x = np.zeros(7 * C.N, np.int64)
    x[3 * C.N + C.P * m + p] = a14
    y, _ = C.pfb_int(x)
    return [int(y[3 + k][C.P * m + p]) for k in range(4)]


def main():
    out = sys.argv[1]
    posctl = len(sys.argv) > 2 and sys.argv[2] == "posctl"
    J = C.Judge()
    meta, imps, recs, lanes = load(out)
    KF, ff, A = meta["KF"], meta["f_first"], meta["A"]
    J(meta["flags"] == 0, "flags = %02x" % meta["flags"])
    hits = raw_hits(recs)
    J(len(hits) == len(imps) and all(v == 4 * A for _, _, v in hits),
      "RAW の SNAP に写ったインパルス %d 個（tb が入れた %d 個）、値はどれも 16 bit の %d" % (len(hits), len(imps), 4 * A))

    ds, ms, bad_tap, bad_port, rows = [], [], 0, 0, []
    for (t_imp, p), hit in zip(imps, hits):
        t_raw, p_raw, _ = hit
        if p_raw != p:
            bad_tap += 1
            continue
        # SLICE: レーン p の出口に、この インパルスの近く（± 6 フレーム）の 0 でないフレーム
        g0 = (t_imp - KF) // 2048
        got = {}
        for r, d in lanes.items():
            lab = ff + r
            if abs(lab - g0) > 6 or len(d) != 2048:
                continue
            Y = np.array([d[k][p] for k in range(2048)])
            yr = np.fft.ifft(Y)                                # 単独のサンプルなら位置 m に y（IP の丸めの雑音は 1 / √2048 に薄まる）
            m = int(np.argmax(np.abs(yr)))
            y0 = int(round(yr[m].real))
            if y0 == 0:
                continue
            got[lab] = (y0, m)
        mset = {m for _, m in got.values()}
        if len(mset) != 1:
            bad_tap += 1
            rows.append("T_imp %d: 出口の位相がそろわない %s" % (t_imp, sorted(got.items())))
            continue
        m = mset.pop()
        pt = pred_taps(m, p, A)
        g = None
        for gc in range(min(got) - 3, min(got) + 1):
            want = {gc + k: pt[k] for k in range(4) if pt[k] != 0}
            if want == {lab: y for lab, (y, _) in got.items()}:
                g = gc
        if g is None:
            bad_tap += 1
            rows.append("T_imp %d: 4 タップの値が模型と合う g が無い（出口 %s、模型 %s）" % (t_imp, {k: v[0] for k, v in got.items()}, pt))
            continue
        t_sl = KF + 2048 * g + m
        bad_port += t_sl != t_imp
        ds.append(t_sl - t_raw)
        ms.append(m)
        rows.append("T_imp %d レーン %2d: T_raw %d・SLICE のフレーム %d の m %4d → T_slice %d・D_S %+d" % (t_imp, p, t_raw, g, m, t_sl, t_sl - t_raw))
    for x in rows:
        print("  " + x)
    J(bad_tap == 0 and len(ds) == len(imps), "SLICE: インパルス %d 個とも、4 つの出口の y が模型の PFB の 4 タップと一致し、出口の位相 m がそろった（NG %d）" % (len(ds), bad_tap))
    J(bad_port == 0, "SLICE は口のビートに同じクロックの T を付ける（T_slice = tb が入れた T、外れ %d）" % bad_port)
    J(2047 in ms and 0 in ms, "フレームの境目（m = 2047・0）を通った（m の集合 %s）" % sorted(set(ms)))
    one = len(set(ds)) == 1
    J(one, "D_S がどのインパルスでも同じ（%s）" % sorted(set(ds)))
    ok0 = J(one and ds[0] == 0, "**D_S = %s ビート**（期待 0: RAW は口のビートに 1 クロック前の T を付け、axis_sel4 の 1 段がそれを打ち消す）" % (ds[0] if ds else None))
    # 重心（係数だけで決まる。RTL の区切りは上の照合で模型と同じと確かめた）
    c = C.coef().astype(np.float64)
    w = c ** 2
    cen = float((w * np.arange(len(c))).sum() / w.sum())             # 4 フレーム（古い順）の窓の中のサンプルの位置
    d_pfb = (3 * C.N + (C.N - 1) / 2.0 - cen) / C.P                   # 矩形（新しいフレーム）の重心 − PFB の重心、ビート
    J(abs(d_pfb - 1.5 * 2048) < 1e-6, "実効の区間の重心: 矩形より %.6f ビート前（1.5·L = 3072）" % d_pfb)
    print("D_eff（SLICE）= D_S ＋ 1.5·L = %s ビート" % (int(round(ds[0] + d_pfb)) if one and ds else None))
    if posctl:
        # 陽性対照: D_S = 0 の判定だけが落ち、ほかは通る（D_S は 1 つの 0 でない値）
        ok = (not ok0) and one and ds and ds[0] != 0 and J.ng == 1
        print("結果: 全部通過（陽性対照が落ちるべきところで落ちた: D_S %+d）" % ds[0] if ok else "結果: NG（陽性対照が落ちなかった・ほかも落ちた）")
        sys.exit(0 if ok else 1)
    print("結果: 全部通過" if J.ng == 0 else "結果: NG %d 件" % J.ng)
    sys.exit(0 if J.ng == 0 else 1)


if __name__ == "__main__":
    main()
