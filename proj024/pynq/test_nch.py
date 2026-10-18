#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj024 手順 3b — 受け側（s45client.if_axis）の IF の軸を記録の nch から作るかの単体試験（PL・通信なし、numpy だけ）

    python3 test_nch.py             # 「結果: 全部通過」
    python3 test_nch.py --posctl    # 陽性対照: 軸を P.NCH（4096）で作る土台の形 → nch 131072 で落ちる（「結果: 不合格」）

- v2 の SPEC を s45proto で pack して decode し、nch 4096（DDC・SLICE）・131072（2G-1 の FULL）で軸の長さ・差・2047 番目を見る
- nch 4096 の v2・v1 は、土台（1ebc92c の s45client.freq）の式と配列が一致すること
"""
import sys

import numpy as np

import s45proto as P
from s45client import if_axis

POS = "--posctl" in sys.argv


def base_freq(d):
    """土台（proj023 1ebc92c）の s45client.freq の式そのまま（比べる相手・陽性対照）"""
    if d.get("df_hz"):
        return d["if_mhz"] + (np.arange(P.NCH) - 2047) * (d["df_hz"] / 1e6)
    w = 512.0 / (1 << d["ns"])
    b = P.IF_ORDER
    return d["if_mhz"] - np.where(b < P.NCH // 2, b, b - P.NCH) * (w / P.NCH)


axis = base_freq if POS else if_axis


def v2(nch, kind, if_mhz, df):
    data = np.arange(nch, dtype=np.float32)
    hd = P.SPEC2_H.pack(0, 0, 2, kind, 1, 4, P.FMT_F32, 11, nch, 4, 0, 1, 4, 0, 0, 0, 0, 0, 65536, 0, P.BASE_NS, if_mhz, df)
    return P.decode(P.T_SPEC, hd + data.tobytes(), ver=2)


def v1(ns, if_mhz):
    hd = P.SPEC_H.pack(0, 0, ns, 9, P.FMT_RAW, 4, 0, 0, 1, 4, 0, 0, 0, 512, 0, if_mhz)
    return P.decode(P.T_SPEC, hd + np.zeros(P.NCH, np.uint64).tobytes(), ver=1)


ng = []


def judge(ok, msg):
    print(("OK  " if ok else "NG  ") + msg)
    if not ok:
        ng.append(msg)


# 2G-1 の FULL: 131072 ch、df = 4096 MHz / 262144 = 15.625 kHz。if_mhz は送る 2047 番目の IF（試験の値は任意）
for nch, kind, if_mhz, df in ((131072, 1, 2047.0 + 2047 * 0.015625, 15625.0), (4096, 2, 3000.0, 125000.0), (4096, 3, 2900.0, 512e6 / 2 / 4096)):
    d = v2(nch, kind, if_mhz, df)
    f = axis(d)
    judge(d["nch"] == nch and d["data"].size == nch, f"v2 kind {kind}: decode の nch {d['nch']}・data {d['data'].size}（期待 {nch}）")
    judge(f.size == nch, f"v2 kind {kind}: 軸の長さ {f.size}（期待 {nch}）")
    if f.size == nch:
        judge(np.allclose(np.diff(f), df / 1e6, rtol=0, atol=1e-9) and f[2047] == if_mhz,
              f"v2 kind {kind}: 差 = df {df / 1e6} MHz・2047 番目 = if_mhz {if_mhz}")
    if nch == P.NCH:
        judge(np.array_equal(f, base_freq(d)), f"v2 kind {kind} nch 4096: 土台の式と配列が一致")
for ns in (1, 3, 6):
    d = v1(ns, 3000.0)
    judge(np.array_equal(axis(d), base_freq(d)) and axis(d).size == 4096, f"v1 ns {ns}: 4096 ch・土台の式と配列が一致")

print("結果: 全部通過" if not ng else f"結果: 不合格（{len(ng)}）")
sys.exit(1 if ng else 0)
