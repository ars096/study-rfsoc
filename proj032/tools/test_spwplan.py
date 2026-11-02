#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj032 P-10 — b5/pynq/spwplan.py の照らし（机の上、numpy なし）

  python3 tools/test_spwplan.py [--n 3000] [--posctl]

1. 手で書いた構成（spw_b5.py の b1・b5）が check() を通る。b5 の窓を IF で与えた計画が、手の WK・NS・頭と同じになる
2. 約束 [1]〜[6] をそれぞれ 1 つだけ破った構成で、その印だけが立つ（check() の陽性対照）
3. 乱数の窓の組（半分は 1〜8 本・幅・IF が一様、半分は 5〜8 本で広い窓が多く中心が少ない粗い ch の近くと帯の端に寄る）: 計画が通した組は check() 0・WDPHI が d を正確に表す・中心の CW が ch 0・df ずらすと ch 1。
   計画が断った組は、総当たり（粗い ch の選び × 機関の割り当て）でも入らない。総当たりで入る組を計画が断れば落ちる
0. spwplan の定数（FS・粗い ch の間隔・R0・NFFT・ALT_WMAX）が模型 model/win64_model.py と同じ
--posctl r0: R0 を 512 にした版で 0 が落ちる / --posctl lane: 計画の機関を全部 lane 0 にした版で 3 の「約束を破る」が落ちる / --posctl alt: 計画が 2 番目に近い粗い ch を使わない版で 3 の「入るのに断った」が落ちる
"""
import argparse
import itertools
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "b5", "pynq"))
import spwplan as P  # noqa: E402

H, E, S, NK = 8, 3, 8, 8


def streams_of(wins, h=H):
    st = [dict(WK=(0 if s < h // 2 else 1), WDPHI=0, WNS=1, WFL=E, WSL=0, WG=0) for s in range(h)]
    for s, k, ns, fl, sl in wins:
        st[s] = dict(WK=k, WDPHI=0, WNS=ns, WFL=fl, WSL=sl, WG=0)
    return st


def feasible(ws):
    """総当たり: 粗い ch の選び（偶奇の組の頭 ≦ H/2）× 機関（各 ≦ 32 単位）× 枠（≦ S）"""
    if len(ws) > S:
        return False
    opts = []
    for f, w in ws:
        try:
            c = P.center(f, w)
        except P.PlanError:
            return False
        k1 = int(round(c / 64.0))                    # 計画の k_options と独立に書く（--posctl alt で計画の側だけを壊す）
        k2 = (k1 + 1 if c >= k1 * 64.0 else k1 - 1) if w <= 64 else None
        k2 = k2 if k2 is not None and 0 <= k2 <= 32 else None
        opts.append([k1] if k2 is None else [k1, k2])
    ok_par = False
    for ks in itertools.product(*opts):
        ne = sum(1 for k in ks if k % 2 == 0)
        if ne <= H // 2 and len(ks) - ne <= H - H // 2:
            ok_par = True
            break
    if not ok_par:
        return False
    us = [P.unit(P.NS_OF[int(w)]) for _, w in ws]
    for asg in itertools.product(range(E), repeat=len(us)):
        ls = [0] * E
        for u, e in zip(us, asg):
            ls[e] += u
        if max(ls) <= P.LANE_CAP:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--posctl", choices=("lane", "alt", "r0"), default=None)
    a = ap.parse_args()
    if a.posctl == "r0":
        P.R0 = 512.0
    if a.posctl == "alt":                    # 計画が 2 番目に近い粗い ch を使わない: 偶奇の組が埋まる組で「入るのに断った」が出るはず
        P.ALT_WMAX = 0.0
    if a.posctl == "lane":
        orig = P.plan

        def plan_bad(*x, **kw):              # 機関を全部 lane 0 に（約束 [1] を破る計画）
            p = orig(*x, **kw)
            for w in p["wins"]:
                w["fl"] = 0
                p["streams"][w["s"]]["WFL"] = 0
            return p
        P.plan = plan_bad
    nbad = 0

    def ng(msg):
        nonlocal nbad
        nbad += 1
        if nbad <= 20:
            print("  落ちた:", msg)

    # 0. 定数を模型と照らす（P-10 の 1 回目は R0 を 512 と書き、WDPHI が半分になったのを机の上で見落とした）
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
    import win64_model as WM
    for k, v, want in (("FS", P.FS, WM.FS), ("SC", P.SC, WM.S), ("R0", P.R0, WM.R0), ("NFFT", P.NFFT, WM.NFFT), ("ALT_WMAX", P.ALT_WMAX, WM.ALT_WMAX)):
        if v != want:
            ng(f"spwplan.{k} {v} ≠ 模型 {want}")
    print(f"0. 定数: FS {P.FS}・粗い ch の間隔 {P.SC}・R0 {P.R0}（模型 {WM.R0}）")
    # 1. 手の構成
    b5 = [(0, 8, 1, 0, 0), (1, 8, 2, 0, 1), (2, 12, 2, 1, 2), (3, 16, 4, 0, 6),
          (4, 9, 1, 1, 3), (5, 21, 2, 2, 4), (6, 25, 3, 2, 5), (7, 17, 5, 2, 7)]
    b1h8 = [(0, 8, 1, 0, 0), (1, 8, 2, 0, 1), (2, 12, 2, 1, 2), (4, 9, 1, 1, 3), (5, 21, 2, 2, 4), (6, 25, 3, 2, 5)]
    for name, wins in (("b5", b5), ("b1（H 8）", b1h8)):
        b = P.check(streams_of(wins))
        print(f"1. 手の構成 {name}: check {b:#x}")
        if b:
            ng(f"手の構成 {name} が約束を破る {b:#x}")
    req = [(4096 - 64 * k, P.width(ns)) for s, k, ns, fl, sl in sorted(b5)]
    p = P.plan(req)
    got = sorted((x["s"], x["k"], x["ns"]) for x in p["wins"])
    want = sorted((s, k, ns) for s, k, ns, fl, sl in b5)
    print(f"   b5 の窓を IF で計画: 頭・WK・NS {'同じ' if got == want else '違う'}・機関の幅の和 {p['lane_sum']}")
    if got != want or any(x["dphi"] != 0 for x in p["wins"]):
        ng(f"b5 の計画 {got} ≠ {want}")
    # 2. 約束を 1 つずつ破る
    base = streams_of(b5)
    cases = {
        1: lambda st: [r.update(WFL=0) for r in st[:4]] and None,                   # lane 0 に 128+64+64+16 ＋ 既存
        3: lambda st: st[1].update(WSL=0),                                          # チップ内の枠 0 の重なり
        4: lambda st: (st[7].update(WSL=S), st[6].update(WSL=S)) and None,           # DDR の枠の重なり（S ＋ NK = 16 は 4 bit で 0 になる）
        5: lambda st: st[2].update(WNS=6),
        6: lambda st: st[4].update(WK=8),                                           # 奇の組に偶の k
    }

    def c2(st):                                                                     # DDR の窓の幅の和 > 256 MHz
        st[0].update(WSL=S); st[4].update(WSL=S + 1); st[1].update(WSL=S + 2)
    cases[2] = c2
    for bit in sorted(cases):
        st = [dict(r) for r in base]
        cases[bit](st)
        b = P.check(st)
        print(f"2. 約束 [{bit}] を破る: check {b:#x}")
        if not b & (1 << bit):
            ng(f"約束 [{bit}] を破っても印が立たない（{b:#x}）")
        if bit != 1 and b & ~(1 << bit):
            ng(f"約束 [{bit}] 以外の印も立つ（{b:#x}）")
    st = [dict(r) for r in base]
    st[7].update(WSL=S + NK)                                                        # 4 bit で 0 → チップ内の枠 0 の重なり [3]
    if P.check(st) != 1 << 3:
        ng(f"WSL {S + NK} を 4 bit で切っていない（{P.check(st):#x}）")
    st = [dict(r) for r in base]
    st[3].update(WFL=E, WNS=7, WK=40, WSL=0)                                        # 止める窓は数えない
    if P.check(st):
        ng(f"止める窓を数えた（{P.check(st):#x}）")
    # 3. 乱数
    rng = random.Random(a.seed)
    n_ok = n_ref = n_alt = 0
    for t in range(a.n):
        ws = []
        if t % 2 == 0:                       # 一様
            for _ in range(rng.randint(1, 8)):
                w = rng.choice([128, 64, 32, 16, 8])
                ws.append((rng.uniform(2048 + w / 2, 4096 - w / 2), w))
        else:                                # 厳しい組: 広い窓が多く、中心が少ない粗い ch の近く・帯の端に寄る
            ks = [rng.randint(0, 32) for _ in range(rng.randint(1, 3))]
            for _ in range(rng.randint(5, 8)):
                w = rng.choice([128, 128, 64, 64, 32, 16, 8])
                f = 4096 - 64 * rng.choice(ks) + rng.uniform(-40, 40)
                ws.append((min(max(f, 2048 + w / 2), 4096 - w / 2), w))
        try:
            p = P.plan(ws)
        except P.PlanError as e:
            n_ref += 1
            if feasible(ws):
                ng(f"組 {t}: 入るのに断った（{e}）{ws}")
            continue
        n_ok += 1
        b = P.check(p["streams"])
        if b:
            ng(f"組 {t}: 計画が約束を破る {b:#x}")
        for x in p["wins"]:
            n_alt += x["alt"]
            if abs(P.d_of(x["dphi"]) - x["d"]) > 1e-12 or abs(x["d"]) > (64 if x["alt"] else 32) + 1e-9:
                ng(f"組 {t} 窓 {x['i']}: d {x['d']} ≠ WDPHI の d {P.d_of(x['dphi'])}")
            df = x["w"] / 4096
            if P.ch_of(x["if_mhz"], x) != (0, 0.0) or P.ch_of(x["if_mhz"] - df, x)[0] != 1 or P.ch_of(x["if_mhz"] + df, x)[0] != 4095:
                ng(f"組 {t} 窓 {x['i']}: 中心の ch {P.ch_of(x['if_mhz'], x)}")
            if abs(x["if_mhz"] - x["if_req"]) > df / 2 + 1e-12:
                ng(f"組 {t} 窓 {x['i']}: 丸めが df/2 を越える")
    print(f"3. 乱数の組 {a.n}: 計画した {n_ok}（2 番目に近い粗い ch {n_alt} 窓）・断った {n_ref}")
    print("結果: " + ("全部通過" if nbad == 0 else f"不合格 {nbad}"))
    sys.exit(0 if nbad == 0 else 1)


if __name__ == "__main__":
    main()
