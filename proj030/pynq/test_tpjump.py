#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj021 B2 — tpjump.TpJump の試験（PL なし、numpy だけ）。README の B2 の予言 1。最後の行が「test_tpjump: 全部通過」"""
import sys

import numpy as np

from tpjump import TpJump

REL = 7e-4          # 1.024 ms の熱雑音（1/√(B·τ)）
CH = 40             # specd の TP の記録の区切り


def run(p, flags=None):
    tj = TpJump()
    ev = []
    for a in range(0, len(p), CH):
        ev += tj.feed(np.arange(a, min(a + CH, len(p))) * 512, p[a:a + CH], None if flags is None else flags[a:a + CH])
    return ev + tj.finish()


def base(n, seed):
    rng = np.random.default_rng(seed)
    return 1e4 * (1 + REL * rng.standard_normal(n))


ng = 0


def judge(ok, msg):
    global ng
    print(("test_tpjump: OK  " if ok else "test_tpjump: NG  ") + msg)
    ng += not ok


N = 60_000                                           # 61 s
db = lambda x: 10 ** (x / 10)
# (a) 1 dB / 60 s の傾き
p = base(N, 1) * db(np.linspace(0, 1, N))
ev = run(p)
judge(len(ev) == 0, f"(a) 1 dB / 60 s の傾き: 跳ね {len(ev)}（0 のはず）")
# (b) +0.05 dB × 3 個 × 10 本
p = base(N, 2)
pos = [3000 + 5000 * i for i in range(10)]
for q in pos:
    p[q:q + 3] *= db(0.05)
ev = run(p)
ok = len(ev) == 10 and all(e["n"] == 3 and abs(e["db"] - 0.05) < 0.01 and abs(e["step_db"]) < 0.01 for e in ev) and [e["i0"] for e in ev] == pos
judge(ok, f"(b) +0.05 dB × 3 個 × 10 本: 跳ね {len(ev)}・n {sorted({e['n'] for e in ev})}・db {sorted({round(e['db'], 3) for e in ev})}"
          f"・step_db 最大 {max((abs(e['step_db']) for e in ev), default=None)}")
# (c) +0.005 dB × 3 個 × 10 本（≒ 1.6σ）
p = base(N, 3)
for q in pos:
    p[q:q + 3] *= db(0.005)
ev = run(p)
judge(len(ev) == 0, f"(c) +0.005 dB（≒ 1.6σ）: 跳ね {len(ev)}（0 のはず）")
# (d) −1 dB の段差
p = base(N, 4)
p[30000:] *= db(-1.0)
ev = run(p)
judge(len(ev) == 1 and abs(ev[0]["db"] + 1.0) < 0.05 and abs(ev[0]["step_db"] + 1.0) < 0.03 and ev[0]["i0"] == 30000 and 300 <= ev[0]["n"] <= 700,
      f"(d) −1 dB の段差: 跳ね {len(ev)}" + (f"・db {ev[0]['db']}・step_db {ev[0]['step_db']}・i0 {ev[0]['i0']}・n {ev[0]['n']}" if ev else ""))
# (h) −1 dB の段差の頭に瞬断（陽性対照 rb4 の形: −4・−48・−10 dB の 3 個）
p = base(N, 8)
p[30000:] *= db(-1.0)
p[30000:30003] *= db(np.array([-3.0, -47.0, -9.2]))
ev = run(p)
judge(len(ev) == 1 and abs(ev[0]["db"] + 48.0) < 0.5 and abs(ev[0]["step_db"] + 1.0) < 0.03,
      f"(h) 瞬断つきの −1 dB の段差: 跳ね {len(ev)}" + (f"・db {ev[0]['db']}・step_db {ev[0]['step_db']}・n {ev[0]['n']}" if ev else ""))
# (e) 揺らぎだけ 60 万個（10 分ぶん）
p = base(600_000, 5)
ev = run(p)
judge(len(ev) <= 1, f"(e) 揺らぎだけ 60 万個: 誤検出 {len(ev)}（≦ 1）")
# (f) FLAGS[4]（振り切れ）が跳ねの中にあれば ovr
p = base(N, 6)
fl = np.zeros(N, dtype=np.int64)
p[20000:20005] *= db(3.0)
fl[20002] = 16
ev = run(p, fl)
judge(len(ev) == 1 and ev[0]["ovr"], f"(f) 振り切れの印: 跳ね {len(ev)}・ovr {ev[0]['ovr'] if ev else None}")
# (g) 一定の TP（偽物）: σ の下限で 0 割りにならず、跳ね 0
ev = run(np.full(N, 3e9))
judge(len(ev) == 0, f"(g) 一定の TP: 跳ね {len(ev)}")
# (i) B2b: ADC ごとの位相（phase 250・500・750）でも (a) の傾きで 0、σ を計算し直す区切りが 4 ADC で重ならない
p = base(N, 1) * db(np.linspace(0, 1, N))
nph = []
redo = []
for ph in (0, 250, 500, 750):
    tj = TpJump(phase=ph)
    e, r = [], set()
    for a in range(0, N, CH):
        full, k0 = tj.nh >= tj.win, tj.n_sig
        e += tj.feed(np.arange(a, a + CH) * 512, p[a:a + CH])
        if full and tj.n_sig > k0:              # 窓が溜まりきった後の計算し直し
            r.add(a)
    nph.append(len(e + tj.finish())); redo.append(r)
clash = sum(len(redo[x] & redo[y]) for x in range(4) for y in range(x + 1, 4))
judge(sum(nph) == 0 and clash == 0 and all(55 <= len(r) <= 61 for r in redo),
      f"(i) 位相: 傾きで跳ね {nph}・σ の計算し直し {[len(r) for r in redo]} 回・同じ区切りで重なり {clash}")
# 陽性対照: k を 1 にすると揺らぎで跳ねが山ほど出る（見張りが効いていることの確かめ）
tj = TpJump(k=1.0)
p = base(N, 7)
nev = sum(len(tj.feed(np.arange(a, a + CH), p[a:a + CH])) for a in range(0, N, CH))
judge(nev > 100, f"陽性対照（k = 1）: 跳ね {nev}（たくさん出るはず）")
print("test_tpjump: " + ("全部通過" if ng == 0 else f"失敗（{ng} 件）"))
sys.exit(1 if ng else 0)
