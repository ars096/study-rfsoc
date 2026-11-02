#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj025 手順 4 — 2G-2 の記録（specrecv.py --out の .s45）を読み、窓 A0・B0（コア 0・1 の FULL）ごとに頭の欄・雑音の床・CW の ch と IF を判定する。
2 コアに同じ ADC を入れた記録では、同じ DUMP_T の 2 窓のスペクトルが bit 単位で同じかを見る（E-4 の陽性対照の実機版）。numpy だけ。PC でもボードでも

    python3 g22cw.py runs/g22_4a1.s45 --src AB                    # 4a: 2 窓の頭の欄（kind 1・nch 65536・core・src・nacc・df・DUMP_T の進み）・DUMP_T が 2 窓で揃う・床
    python3 g22cw.py runs/g22_4a3.s45 --src CC --same             # 4a-3（E-4）: 同じ DUMP_T の A0・B0 が bit 単位で同じ（fmt=both なら u64 で、無ければ f32 で）
    python3 g22cw.py runs/g22_4a3.s45 --src CC --same --posctl-same   # 陽性対照: 1 ダンプずらして比べる → 全部違うはず（落ちる）
    python3 g22cw.py runs/g22_4b1.s45 --src AB --sg-mhz 3000.25   # 4b: CW の ch と IF（2 窓とも。IF の昇順の軸 = s45client.if_axis）
    python3 g22cw.py runs/g22_4b1.s45 --src AB --sg-mhz 3000.25 --posctl   # 陽性対照: 軸の向きを逆に取る → 落ちる

判定（CW）: **まず CW が見えているか**（ピーク / 中央値 ≧ --min-db）→ ピークの送る番号 i が期待（ch c = round((4096 − f) / df)、i = 65535 − c）と一致・
軸の値 if_axis[i] と f の差 ≦ df / 2
"""
import argparse
import sys

import numpy as np

import s45proto as P
from s45client import if_axis

FS, NCH, FRAME = 4096.0, 65536, 8192
DF = FS * 1e6 / (2 * NCH)                 # 31,250 Hz
KEYS = ("A0", "B0")                        # 窓 A0 = コア 0、B0 = コア 1


def read(fn):
    """{コア: {fmt: [記録]}}・TP の ADC の集合・CRC の不一致の数"""
    b = open(fn, "rb").read()
    o, out, tps, bad = 0, {0: {}, 1: {}}, set(), 0
    while o + 24 <= len(b):
        rt, pl, crc, seq = P.parse_header(b[o:o + 24])
        ver = P.header_ver(b[o:o + 24])
        pay = b[o + 24:o + 24 + pl]
        o += 24 + pl
        if P.crc32(pay) != crc:
            bad += 1
            continue
        d = P.decode(rt, pay, ver)
        if rt == P.T_SPEC:
            out.setdefault(d["core"], {}).setdefault(d["fmt"], []).append(d)
        elif rt == P.T_TP:
            tps.add(d["adc"])
    return out, tps, bad


def cw_check(sp, d0, f, min_db, posctl, judge, key):
    """1 窓の CW の判定（sp: 1 フレームあたりの平均スペクトル、送る順 = IF の昇順）"""
    med = float(np.median(sp))
    ax = if_axis(d0) if not posctl else d0["if_mhz"] - (np.arange(sp.size) - 2047) * (d0["df_hz"] / 1e6)   # 陽性対照: 向きを逆に
    ipk = int(np.argmax(sp))
    r_db = 10 * np.log10(sp[ipk] / med)
    judge(r_db >= min_db, f"{key}: CW が見えている: ピーク / 中央値 {r_db:.1f} dB（≧ {min_db}）・ピークの送る番号 {ipk}")
    c = int(round((FS - f) / (DF / 1e6)))
    iexp = NCH - 1 - c
    judge(ipk == iexp, f"{key}: ピークの番号 {ipk}（期待 {iexp} = 65535 − ch {c}）")
    judge(abs(ax[ipk] - f) <= DF / 2e6, f"{key}: 軸の値 {ax[ipk]:.6f} MHz と SG {f:.6f} MHz の差 {abs(ax[ipk] - f) * 1e6:.1f} Hz（≦ df/2 = {DF / 2:.1f} Hz）")
    nb = sp[max(ipk - 3, 0):ipk + 4] / sp[ipk]
    print(f"    {key}: ピークの前後 ±3 ch（ピーク比 dB）: {' '.join(f'{10 * np.log10(max(x, 1e-30)):+.1f}' for x in nb)}")


def same_check(recs, fmt, posctl, judge):
    """E-4: 同じ DUMP_T の A0・B0 が bit 単位で同じか。posctl なら B0 を 1 ダンプずらして比べる（全部違うはず）"""
    a = {d["dump_t"]: d for d in recs[0][fmt]}
    b = {d["dump_t"]: d for d in recs[1][fmt]}
    ts = sorted(a)
    step = ts[1] - ts[0] if len(ts) > 1 else 0
    pairs = [(t, t + step if posctl else t) for t in ts if (t + step if posctl else t) in b]
    nsame = sum(1 for ta, tb in pairs if np.array_equal(a[ta]["data"], b[tb]["data"]))
    ndiff_ch = [int(np.count_nonzero(a[ta]["data"] != b[tb]["data"])) for ta, tb in pairs]
    what = "1 ダンプずらした組（陽性対照: 全部違うはず）" if posctl else "同じ DUMP_T の組"
    print(f"    {what} {len(pairs)} 組（{'u64' if fmt == P.FMT_RAW else 'f32'}）: bit 単位で同じ {nsame}・違う ch の数 最小 {min(ndiff_ch) if ndiff_ch else '-'}・最大 {max(ndiff_ch) if ndiff_ch else '-'}")
    if posctl:
        judge(len(pairs) > 0 and nsame == len(pairs), f"2 窓が bit 単位で同じ（陽性対照なので落ちるはず）: {nsame} / {len(pairs)} 組")
    else:
        judge(len(pairs) > 0 and nsame == len(pairs), f"2 窓が bit 単位で同じ: {nsame} / {len(pairs)} 組")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file")
    p.add_argument("--src", default=None, help="期待する入力の ADC を A0・B0 の順に 2 文字（例 AB・CD・CC）。無ければ表示だけ")
    p.add_argument("--sg-mhz", type=float, default=None)
    p.add_argument("--min-db", type=float, default=30.0, help="CW が見えている判定（ピーク / 中央値）")
    p.add_argument("--posctl", action="store_true", help="CW の陽性対照: 軸の向きを逆に取る")
    p.add_argument("--same", action="store_true", help="E-4: 同じ DUMP_T の 2 窓が bit 単位で同じ")
    p.add_argument("--posctl-same", action="store_true", help="E-4 の陽性対照: B0 を 1 ダンプずらして比べる")
    a = p.parse_args()
    recs, tps, bad = read(a.file)
    ng = []

    def judge(ok, msg):
        print(("OK  " if ok else "NG  ") + msg)
        if not ok:
            ng.append(msg)

    judge(bad == 0, f"CRC の不一致 {bad}")
    f32 = {c: recs.get(c, {}).get(P.FMT_F32, []) for c in (0, 1)}
    judge(len(f32[0]) > 0 and len(f32[0]) == len(f32[1]), f"f32 の SPEC A0 {len(f32[0])}・B0 {len(f32[1])} 個（同じ数で > 0）")
    if not f32[0] or not f32[1]:
        print("結果: 不合格"); sys.exit(1)
    sps = {}
    for c, key in enumerate(KEYS):
        rs = f32[c]
        d0 = rs[0]
        hd = {(d["kind"], d["nch"], d["core"], d["s"], d["ns"], d["bit_kind"], d["nacc"], d["df_hz"], d["shift"], d["src"]) for d in rs}
        judge(len(hd) == 1 and d0["kind"] == 1 and d0["nch"] == NCH and d0["core"] == c and d0["s"] == 0 and d0["ns"] == 0
              and d0["bit_kind"] == 10 and d0["df_hz"] == DF,
              f"{key}: 頭の欄: kind {d0['kind']}・nch {d0['nch']}・core {d0['core']}・s {d0['s']}・ns {d0['ns']}・bit_kind {d0['bit_kind']}・"
              f"df {d0['df_hz']}・nacc {d0['nacc']}・shift {d0['shift']}・src {'ABCD'[d0['src']]}（組 {len(hd)}）")
        if a.src:
            judge(d0["src"] == "ABCD".index(a.src.upper()[c]), f"{key}: src {'ABCD'[d0['src']]}（期待 {a.src.upper()[c]}）")
        dt = np.diff([d["dump_t"] for d in rs])
        want = d0["nacc"] * FRAME
        judge(bool(np.all(dt == want)), f"{key}: DUMP_T の進み {sorted(set(dt.tolist()))[:4]}（期待 {want} = nacc·8192。欠けがあれば倍数が混じる）")
        k = np.array([d["k"] for d in rs])
        judge(bool(np.all(np.diff(k) == 1)), f"{key}: DUMP_K が 1 ずつ（{k[0]}〜{k[-1]}）")
        h = fl = sat = 0
        for d in rs:
            h |= d["health"]; fl |= d["flags"]; sat += d["sat"]
        print(f"    {key}: health の OR {h:#x}・flags の OR {fl:#x}・sat の和 {sat}・utc_ns {'あり' if d0['utc_ns'] else '0（時刻なし）'}")
        sp = np.mean([d["data"].astype(np.float64) for d in rs], axis=0) / d0["nacc"]     # 1 フレームあたり
        sps[c] = (sp, d0)
        q = np.percentile(sp, [1, 50, 99])
        print(f"    {key}: 雑音の床（1 フレームあたり、全 ch）: 1 % {q[0]:.3g}・中央値 {q[1]:.3g}・99 % {q[2]:.3g}（SHIFT {d0['shift']}）")
        judge(q[1] > 1.0, f"{key}: 床の中央値 {q[1]:.3g} > 1（SHIFT が大きすぎて床が 0 に潰れていない）")
    t0 = [d["dump_t"] for d in f32[0]]
    t1 = [d["dump_t"] for d in f32[1]]
    judge(t0 == t1, f"2 窓の DUMP_T が揃う（同じ RUN_F0。A0 {t0[0]}〜・B0 {t1[0]}〜、差の組 {sorted(set(np.subtract(t1, t0).tolist()))[:3] if len(t0) == len(t1) else '数が違う'}）")
    print(f"    TP の ADC {''.join('ABCD'[x] for x in sorted(tps))}")
    if a.same or a.posctl_same:
        fmt = P.FMT_RAW if recs[0].get(P.FMT_RAW) and recs[1].get(P.FMT_RAW) else P.FMT_F32
        same_check(recs, fmt, a.posctl_same, judge)
    if a.sg_mhz is not None:
        for c, key in enumerate(KEYS):
            cw_check(sps[c][0], sps[c][1], a.sg_mhz, a.min_db, a.posctl, judge, key)
    print("結果: 全部通過" if not ng else f"結果: 不合格（{len(ng)}）")
    sys.exit(1 if ng else 0)


if __name__ == "__main__":
    main()
