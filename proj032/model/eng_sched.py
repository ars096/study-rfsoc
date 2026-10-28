#!/usr/bin/env python3
"""eng_sched — 機関の枠（4096 クロック）ごとの選びが間に合うかの模型（proj032 E-4）。

窓 w（NS 1..5）は周期 P = 4096·2^NS クロックで 1 フレームが溜まる。機関は枠の頭ごとに溜まった仕事を 1 つ選ぶ。
フレーム r の読み始めが「r が溜まった時刻 + P」より後だと、r + 2 の書き込みが r − 3 の面を潰す（履歴 5 面）。
機関の幅の和 256 MHz ちょうど（窓 ≦ 14）の全部の組み合わせで、最悪の遅れ（負なら間に合う）を出す。

  python3 model/eng_sched.py

D-2: 選びを枠の頭の LEAD 前にした形（run_lead）。DDR の窓は DDR に書き終わってから選べる。
"""
import random

def combos(hmax=14):
    out = []
    for n128 in range(3):
        for n64 in range(5):
            for n32 in range(9):
                for n16 in range(17):
                    rest = 256 - 128 * n128 - 64 * n64 - 32 * n32 - 16 * n16
                    if rest < 0 or rest % 8:
                        continue
                    n8 = rest // 8
                    if n128 + n64 + n32 + n16 + n8 > hmax:
                        continue
                    out.append([1] * n128 + [2] * n64 + [3] * n32 + [4] * n16 + [5] * n8)
    return out

def run(ns, seed, J, key, slots=300):
    """J: 溜まる時刻の揺れ（final の lane の待ち）。key: 選びの順。戻り値: 最悪の遅れ・窓ごとの待ちの最大"""
    rnd = random.Random(seed)
    P = [4096 * 2 ** n for n in ns]
    base = [rnd.randrange(4096) for _ in ns]
    T = 4096 * slots
    arr = []
    for w, p in enumerate(P):
        k = 1
        while base[w] + k * p < T:
            arr.append((base[w] + k * p + rnd.randrange(J + 1), base[w] + k * p, w))
            k += 1
    arr.sort()
    q, i, worst, t, maxpend = [], 0, -1e9, 0, 0
    while t < T:
        while i < len(arr) and arr[i][0] <= t:
            q.append(arr[i]); i += 1
        cnt = {}
        for a in q:
            cnt[a[2]] = cnt.get(a[2], 0) + 1
        maxpend = max([maxpend] + list(cnt.values()))
        if q:
            j = min(q, key=lambda a: key(ns, a))
            q.remove(j)
            worst = max(worst, t - (j[1] + P[j[2]]))
        t += 4096
    return worst, maxpend

KEYS = {
    "NS → 番号（RTL）": lambda ns, a: (ns[a[2]], a[2]),
    "到着の順":         lambda ns, a: (a[1], a[2]),
}
def run_lead(ns, ddr, seed, LEAD, JD, slots=300):
    """D-2: 選びを枠の頭の LEAD クロック前に（その時までに着いた仕事から）。DDR の窓は着いてから JD 遅れて選べる（DDR に書き終わるまで）。
    戻り値: 始まり −（着き ＋ 周期）の最悪 [チップ内, DDR]"""
    rnd = random.Random(seed)
    P = [4096 * 2 ** n for n in ns]
    base = [rnd.randrange(4096) for _ in ns]
    T = 4096 * slots
    arr = []
    for w, p in enumerate(P):
        k = 1
        while base[w] + k * p < T:
            a = base[w] + k * p
            arr.append((a + (JD if ddr[w] else 0) + rnd.randrange(65), a, w)); k += 1
    arr.sort()
    q, i, t, wo = [], 0, 4096, [-1e9, -1e9]
    while t < T:
        while i < len(arr) and arr[i][0] <= t - LEAD:
            q.append(arr[i]); i += 1
        if q:
            j = min(q, key=lambda a: (ns[a[2]], a[2]))
            q.remove(j)
            k = 1 if ddr[j[2]] else 0
            wo[k] = max(wo[k], t - (j[1] + P[j[2]]))
        t += 4096
    return wo


if __name__ == "__main__":
    cs = combos()
    for name, key in KEYS.items():
        for J in (0, 64, 256):
            w, mp, bad = -1e9, 0, 0
            for c in cs:
                for s in range(20 if J == 0 else 5):
                    a, b = run(c, s, J, key)
                    w = max(w, a); mp = max(mp, b); bad += a >= 0
            print(f"{name}・揺れ {J:3d}: 組み合わせ {len(cs)}・最悪の遅れ {w:+.0f} クロック・間に合わない回 {bad}・窓ごとの待ちの最大 {mp}")
    # D-2: 選びの前倒しと DDR の窓（窓ごとに半々で DDR）
    for LEAD, JD in ((8, 0), (960, 0), (960, 2000), (960, 4000)):
        wo = [-1e9, -1e9]
        for c in cs:
            for sd in range(10):
                rnd = random.Random(sd + 99)
                ddr = [rnd.random() < 0.5 for _ in c]
                a2 = run_lead(c, ddr, sd, LEAD, JD)
                wo = [max(wo[0], a2[0]), max(wo[1], a2[1])]
        print(f"前倒し {LEAD:4d}・DDR の窓の遅れ {JD:4d}: 始まり −（着き＋周期）の最悪 チップ内 {wo[0]:+.0f}・DDR {wo[1]:+.0f}")
