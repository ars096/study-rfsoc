#!/usr/bin/env python3
"""dump_burst — 閉じたダンプの流れの山と、受け手の溜めの大きさ（proj032 K-1）。numpy なし。

機関 e は、窓のダンプの区切りの最初のフレームの仕事で、前のダンプ（4096 ch）を 1 語 / クロックで流す（eng の d_*）。
全窓のダンプの区切りは同じ格子にそろうので、1 ADC の 3 機関が同じ枠に流しうる（山は最大 3 語 / クロック）。
受け手は ADC ごとに、流れを溜め（FIFO）に入れ、PS の DDR へ R [バイト / クロック] で書き出す。溜めの最大を数える。

窓の組: 機関（lane）ごとに幅の和 ≦ 256 MHz、ADC で窓 ≦ 14。選びは eng と同じ（枠の頭の LEAD 前、NS → 番号の固定優先）。
フレーム k の着きは k·P + 揺れ（0〜64）。格子 B（全窓の周期の倍数）で全窓のダンプが閉じる。

  python3 model/dump_burst.py
"""
import random

H, E, LEAD = 14, 3, 960
SLOT = 4096
NCH = 4096


def lane_sets(hmax=14):
    """機関 1 つに載る窓の NS の組（幅の和 ≦ 256 MHz）"""
    out = []
    for n1 in range(3):
        for n2 in range(5):
            for n3 in range(9):
                for n4 in range(17):
                    for n5 in range(33):
                        if 128 * n1 + 64 * n2 + 32 * n3 + 16 * n4 + 8 * n5 > 256:
                            break
                        if n1 + n2 + n3 + n4 + n5 > hmax:
                            break
                        out.append([1] * n1 + [2] * n2 + [3] * n3 + [4] * n4 + [5] * n5)
    return out


def emit(wins, seed, per_engine=False):
    """wins: [(ns, lane)]。戻り値: 枠ごとの、ダンプを流す機関の数（格子 B の前後）。per_engine なら機関ごとの印のリスト"""
    rnd = random.Random(seed)
    P = [SLOT * 2 ** ns for ns, _ in wins]
    B = SLOT * 2 ** 5 * 4                               # 格子（全窓の周期の倍数）
    T = B + SLOT * 48
    arr = []
    for w, p in enumerate(P):
        k = 1
        while k * p < T:
            arr.append((k * p + rnd.randrange(65), w, k * p == B + p))   # 区切りの最初のフレーム = ダンプを流す仕事
            k += 1
    arr.sort()
    q = [[] for _ in range(E)]
    i, t, out = 0, SLOT, []
    while t < T:
        while i < len(arr) and arr[i][0] <= t - LEAD:
            q[wins[arr[i][1]][1]].append(arr[i]); i += 1
        n = [0] * E
        for e in range(E):
            if q[e]:
                j = min(q[e], key=lambda a: (wins[a[1]][0], a[1]))
                q[e].remove(j)
                n[e] = int(j[2])
        if t >= B - SLOT:
            out.append(n if per_engine else sum(n))
        t += SLOT
    return out


def peak(ns_slot, wb, R):
    """枠ごとの流す機関の数 → 溜めの最大 [バイト]。1 語 wb バイト、書き出し R バイト / クロック（枠の中は一様と見る）"""
    occ, pk = 0.0, 0.0
    for n in ns_slot:
        occ = max(0.0, occ + SLOT * (n * wb - R))
        pk = max(pk, occ)
    return pk


def sink(slots, R, early, G=64):
    """K-2: 受け手の溜め（機関ごとの FIFO）とレコード単位の書き出しの模型。語 = 64 bit = f32 2 つ。
    機関は流す枠で 0.5 語 / クロック（ダンプ 1 つ = 2048 語）。書き出しは合計 R 語 / クロックで、レコード（頭 8 ＋ 本体 2048 ＋ 尾 8 語）を 1 つずつ、機関を順番に。
    early = False: ダンプが揃ってから選ぶ / True: 流れ始めたら選ぶ（本体がまだ来ていなければ書き出しは待つ）。
    戻り値: 機関ごとの溜めの最大 [語]。G クロックずつ進める"""
    occ = [0.0] * E                      # 溜めの中の語（本体）
    pend = [[] for _ in range(E)]        # 溜めの中のダンプ: [書かれた語, 書き出した語]
    pk = [0.0] * E
    cur, rr, hdr = None, 0, 0.0
    for sl in slots + [[0] * E] * 16:
        for _ in range(SLOT // G):
            for e in range(E):
                if sl[e]:
                    if not pend[e] or pend[e][-1][0] >= 2048:
                        if _ == 0:
                            pend[e].append([0.0, 0.0])
                    d = pend[e][-1]
                    d[0] = min(2048.0, d[0] + 0.5 * G)
                    occ[e] += 0.5 * G
            budget = R * G
            while budget > 1e-9:
                if cur is None:
                    for i in range(E):
                        e = (rr + i) % E
                        if pend[e] and (early or pend[e][0][0] >= 2048):
                            cur, rr, hdr = e, (e + 1) % E, 16.0
                            break
                    if cur is None:
                        break
                d = pend[cur][0]
                h = min(budget, hdr); hdr -= h; budget -= h
                m = min(budget, d[0] - d[1]); d[1] += m; occ[cur] -= m; budget -= m
                if d[1] >= 2048 and hdr <= 0:
                    pend[cur].pop(0); cur = None
                elif m < 1e-9 and h < 1e-9:
                    break                    # 本体がまだ来ていない（early）: 書き出しは待つ
            for e in range(E):
                pk[e] = max(pk[e], occ[e])
    return pk


def main():
    ls = lane_sets()
    rnd = random.Random(32)
    cfgs = []
    # 同じ NS の窓 14 本を 3 機関に 5・5・4（区切りの直後に 3 機関が同時に流す、上限の形）
    for ns in (4, 5):
        cfgs.append(("NS %d × 14（5・5・4）" % ns, [(ns, i % 3) for i in range(14)]))
    cfgs.append(("NS 5 × 14（1 機関）", [(5, 0)] * 14))
    cfgs.append(("NS 1 × 6（2・2・2）", [(1, i % 3) for i in range(6)]))
    # 乱数の組（機関ごとに lane_sets から、ADC で 14 本まで）
    for _ in range(3000):
        wins = []
        for e in rnd.sample(range(E), E):
            s = rnd.choice([c for c in ls if len(c) <= H - len(wins)])
            wins += [(ns, e) for ns in s]
        cfgs.append(("乱数", wins))
    Rs = [(8, "2 GB/s"), (12, "3 GB/s"), (16, "4 GB/s")]
    print("1 ADC の溜めの最大 [KiB]（書き出し R、語 u64 = 8 B・f32 = 4 B）")
    print("  %-22s %4s  %s" % ("窓の組", "山", "  ".join("u64 %s  f32 %s" % (n, n) for _, n in Rs)))
    worst = {}
    nrand = 0
    for name, wins in cfgs:
        for sd in range(3 if name == "乱数" else 5):
            ns = emit(wins, sd)
            row = []
            for R, _ in Rs:
                for wb in (8, 4):
                    v = peak(ns, wb, R) / 1024
                    row.append(v)
                    worst[(R, wb)] = max(worst.get((R, wb), 0), v)
            if name != "乱数" and sd == 0:
                print("  %-22s %4d  %s" % (name, max(ns), "  ".join("%9.0f %9.0f" % (row[2 * i], row[2 * i + 1]) for i in range(len(Rs)))))
        nrand += name == "乱数"
    print("  %-22s       %s" % ("最悪（乱数 %d 組を含む）" % nrand,
                                "  ".join("%9.0f %9.0f" % (worst[(R, 8)], worst[(R, 4)]) for R, _ in Rs)))
    tot = H * NCH
    print("理屈の上限（3 機関が区切りの直後から続けて流す）: 溜め = 14·4096 語 × (1 − R / (3·語)) ")
    for R, n in Rs:
        print("  %s: u64 %.0f KiB・f32 %.0f KiB" % (n, max(0, tot * 8 * (1 - R / 24)) / 1024, max(0, tot * 4 * (1 - R / 12)) / 1024))


def main_k2():
    cfgs = [("NS 5 × 14（5・5・4）", [(5, i % 3) for i in range(14)]), ("NS 1 × 6（2・2・2）", [(1, i % 3) for i in range(6)])]
    rnd = random.Random(33)
    ls = lane_sets()
    for _ in range(300):
        wins = []
        for e in rnd.sample(range(E), E):
            s = rnd.choice([c for c in ls if len(c) <= H - len(wins)])
            wins += [(ns, e) for ns in s]
        cfgs.append(("乱数", wins))
    print("K-2: 機関ごとの溜めの最大 [KiB]（語 64 bit、書き出し R 語 / クロック = R × 2.05 GB/s、レコードを機関の順番で）")
    for R in (0.25, 0.5, 0.75, 1.0, 1.5, 2.0):
        for early in (False, True):
            w = 0.0
            for name, wins in cfgs:
                sl = emit(wins, 0, per_engine=True)
                w = max(w, max(sink(sl, R, early)))
            print("  R %.2f（%.2f GB/s）・%s: %.1f KiB" % (R, R * 8 * F_CLK / 1e9, "流れ始めたら" if early else "揃ってから  ", w * 8 / 1024))


F_CLK = 256e6


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "k2":
        main_k2()
        sys.exit(0)
    main()
