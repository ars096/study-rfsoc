#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj024 手順 4 — 2G-1 の記録（specrecv.py --out の .s45）を読み、頭の欄・雑音の床・CW の ch と IF を判定する（numpy だけ。PC でもボードでも）

    python3 g21cw.py runs/g21_4a.s45                         # 4a: 頭の欄（kind 1・nch 131072・src・nacc・df・DUMP_T の進み）と雑音の床
    python3 g21cw.py runs/g21_4b1.s45 --sg-mhz 3000.25       # 4b: CW の ch と IF（IF の昇順の軸 = s45client.if_axis）
    python3 g21cw.py runs/g21_4b1.s45 --sg-mhz 3000.25 --posctl   # 陽性対照: 送る i と ch c を逆に取らない（c = i）軸で → 落ちる

判定（CW）: **まず CW が見えているか**（ピーク / 中央値 ≧ --min-db、LESSONS: 雑音だけの 2 ch でも境目の判定が通る）→
  ピークの送る番号 i が期待（ch c = round((4096 − f) / df)、i = 131071 − c）と一致・軸の値 if_axis[i] と f の差 ≦ df / 2
"""
import argparse
import sys

import numpy as np

import s45proto as P
from s45client import if_axis

FS, NCH = 4096.0, 131072
DF = FS * 1e6 / (2 * NCH)


def read(fn):
    b = open(fn, "rb").read()
    o, out, tps = 0, [], set()
    while o + 24 <= len(b):
        rt, pl, crc, seq = P.parse_header(b[o:o + 24])
        ver = P.header_ver(b[o:o + 24])
        pay = b[o + 24:o + 24 + pl]
        o += 24 + pl
        if P.crc32(pay) != crc:
            continue
        d = P.decode(rt, pay, ver)
        if rt == P.T_SPEC and d.get("fmt") == P.FMT_F32:
            out.append(d)
        elif rt == P.T_TP:
            tps.add(d["adc"])
    return out, tps


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file")
    p.add_argument("--sg-mhz", type=float, default=None)
    p.add_argument("--src", default=None, help="期待する入力の ADC（A〜D）。無ければ記録の src を表示だけ")
    p.add_argument("--min-db", type=float, default=30.0, help="CW が見えている判定（ピーク / 中央値）")
    p.add_argument("--posctl", action="store_true")
    a = p.parse_args()
    recs, tps = read(a.file)
    ng = []

    def judge(ok, msg):
        print(("OK  " if ok else "NG  ") + msg)
        if not ok:
            ng.append(msg)

    judge(len(recs) > 0, f"f32 の SPEC {len(recs)} 個")
    if not recs:
        print("結果: 不合格"); sys.exit(1)
    d0 = recs[0]
    hd = {(d["kind"], d["nch"], d["core"], d["s"], d["ns"], d["bit_kind"], d["nacc"], d["df_hz"], d["shift"], d["src"]) for d in recs}
    judge(len(hd) == 1 and d0["kind"] == 1 and d0["nch"] == NCH and d0["core"] == 0 and d0["s"] == 0 and d0["ns"] == 0
          and d0["bit_kind"] == 11 and d0["df_hz"] == DF,
          f"頭の欄: kind {d0['kind']}・nch {d0['nch']}・core {d0['core']}・s {d0['s']}・ns {d0['ns']}・bit_kind {d0['bit_kind']}・"
          f"df {d0['df_hz']}・nacc {d0['nacc']}・shift {d0['shift']}・src {'ABCD'[d0['src']]}（組 {len(hd)}）")
    if a.src:
        judge(d0["src"] == "ABCD".index(a.src.upper()), f"src {'ABCD'[d0['src']]}（期待 {a.src.upper()}）")
    dt = np.diff([d["dump_t"] for d in recs])
    want = d0["nacc"] * 16384
    judge(bool(np.all(dt == want)), f"DUMP_T の進み {sorted(set(dt.tolist()))[:4]}（期待 {want} = nacc·16384。欠けがあれば倍数が混じる）")
    k = np.array([d["k"] for d in recs])
    judge(bool(np.all(np.diff(k) == 1)), f"DUMP_K が 1 ずつ（{k[0]}〜{k[-1]}）")
    h = 0; fl = 0; sat = 0
    for d in recs:
        h |= d["health"]; fl |= d["flags"]; sat += d["sat"]
    print(f"    health の OR {h:#x}・flags の OR {fl:#x}・sat の和 {sat}・utc_ns {'あり' if d0['utc_ns'] else '0（時刻なし）'}・TP の ADC {''.join('ABCD'[x] for x in sorted(tps))}")
    sp = np.mean([d["data"].astype(np.float64) for d in recs], axis=0) / d0["nacc"]     # 1 フレームあたり
    med = float(np.median(sp))
    q = np.percentile(sp, [1, 50, 99])
    print(f"    雑音の床（1 フレームあたり、全 ch）: 1 % {q[0]:.3g}・中央値 {q[1]:.3g}・99 % {q[2]:.3g}（SHIFT {d0['shift']}）")
    judge(med > 1.0, f"床の中央値 {med:.3g} > 1（SHIFT が大きすぎて床が 0 に潰れていない。LESSONS: 床は数 LSB² 以上）")
    if a.sg_mhz is not None:
        f = a.sg_mhz
        ax = if_axis(d0) if not a.posctl else d0["if_mhz"] - (np.arange(NCH) - 2047) * (d0["df_hz"] / 1e6)   # 陽性対照: 向きを逆に
        ipk = int(np.argmax(sp))
        r_db = 10 * np.log10(sp[ipk] / med)
        judge(r_db >= a.min_db, f"CW が見えている: ピーク / 中央値 {r_db:.1f} dB（≧ {a.min_db}）・ピークの送る番号 {ipk}")
        c = int(round((FS - f) / (DF / 1e6)))
        iexp = NCH - 1 - c
        judge(ipk == iexp, f"ピークの番号 {ipk}（期待 {iexp} = 131071 − ch {c}）")
        judge(abs(ax[ipk] - f) <= DF / 2e6, f"軸の値 {ax[ipk]:.6f} MHz と SG {f:.6f} MHz の差 {abs(ax[ipk] - f) * 1e6:.1f} Hz（≦ df/2 = {DF / 2:.1f} Hz）")
        nb = sp[ipk - 3:ipk + 4] / sp[ipk]
        print(f"    ピークの前後 ±3 ch（ピーク比 dB）: {' '.join(f'{10 * np.log10(max(x, 1e-30)):+.1f}' for x in nb)}")
    print("結果: 全部通過" if not ng else f"結果: 不合格（{len(ng)}）")
    sys.exit(1 if ng else 0)


if __name__ == "__main__":
    main()
