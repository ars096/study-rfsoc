#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj032 P-10 — SpW の窓の計画: 利用者の窓（IF の中心・幅）から、流れごとのレジスタ（WK・WDPHI・WNS・WFL・WSL・WG）を決める。numpy も PYNQ も要らない

specd の SET の窓のキー（`A0.if`・`A0.bw`）は「どの頭・どの機関・どの履歴の枠」を持たない。それを決めるのがこの部品:
  1. 中心: c = 4096 − IF（第 2 ナイキスト帯、f の側）を、その窓の ch 幅 df = W / 4096 の倍数に丸める（P-7 の既定。grid=False で丸めない）。
     帯域（W/2 ≦ c ≦ 2048 − W/2）からはみ出せば断る。k·fs/8 の線（IF 2048・2560・3072・3584・4096）が中央 90 % に入れば警告だけ
  2. 粗い ch: 最も近い k1 = round(c / 64)。幅 ≦ 64 MHz の窓は 2 番目に近い k2 も使える（E-2 の偶奇の 2 組、粗い PFB の通過域 92.8 MHz）。
     d = c − 64·k、WDPHI = round(d / 256 · 2^32) mod 2^32（R0 = 256 MHz、格子の上の d は 32 bit で正確）
  3. 頭（流れの番号 s）: PSPLIT で頭 0..H/2−1 は偶の k、H/2..H−1 は奇の k。選べない窓（128 MHz・帯の端）を先に置き、
     選べる窓は近い k の組が空いていればそちら、埋まっていれば遠い k の組へ。組ごとに利用者の並びの順に頭を取る
  4. 機関（WFL）: lane ごとに幅の和 ≦ 256 MHz（8 MHz を 1 として 32）。幅の広い順に、いちばん空いている lane へ
     （幅が 2 のべきで広い順に置くと、置く時点の lane の和はどれもその幅の倍数なので、どこかに空きがあればいちばん空いた lane に入る。入る組は必ず入る）
  5. 履歴の枠（WSL）: チップ内 0..S−1 を流れの順に。S を越える窓は DDR の枠（PL の DDR がある bit だけ、狭い窓から、DDR の幅の和 ≦ 256 MHz）
  6. WG: チップ内の窓は 0。DDR の窓は wg（既定 4）か、前のダンプの中央値から wg_from_median（P-10 の式）
使わない頭は止める窓（WFL = E、WK はその組の偶奇、WSL 0、WNS 1）。

check() は spw_regs.v の WRST の約束 [1]〜[6] を同じ順・同じ単位で数え、WRST_BAD と同じ印 [6:1] を返す（照合は tools/test_spwplan.py と実機の WRST_BAD）。

    python3 spwplan.py 3574:128 3308:64 2782:64 2486:32 ...     # 計画を表で出す（IF:幅 MHz）
"""
import math
import sys

FS = 4096.0
SC = 64.0                    # 粗い ch の間隔
R0 = 256.0                   # 粗い ch の出力レート（M 64・ホップ D 16 で 4096 / 16。P-10 の 1 回目は 512 と書き、WDPHI が半分になった）
KMAX = 32
NFFT = 4096
NS_OF = {128: 1, 64: 2, 32: 3, 16: 4, 8: 5}
ALT_WMAX = 64.0              # 2 番目に近い粗い ch を使える幅の上限
LANE_CAP = 32                # 8 MHz 単位
DDR_CAP = 32
LINES_IF = (2048.0, 2560.0, 3072.0, 3584.0, 4096.0)


class PlanError(ValueError):
    pass


def unit(ns):
    """WRST の約束の幅の単位（8 MHz = 1）。NS が 1..5 の外は 0（約束 [5]）"""
    return (32 >> ns) if 1 <= ns <= 5 else 0


def width(ns):
    return 256.0 / (1 << ns)


def k_options(c, w):
    """(近い k, 遠い k か None)"""
    k1 = int(round(c / SC))
    k2 = None
    if w <= ALT_WMAX:
        kk = k1 + 1 if c >= k1 * SC else k1 - 1
        if 0 <= kk <= KMAX:
            k2 = kk
    return k1, k2


def dphi_of(d):
    return int(round(d / R0 * 2 ** 32)) % (1 << 32)


def d_of(dphi):
    s = dphi - (1 << 32) if dphi >= (1 << 31) else dphi
    return s / 2 ** 32 * R0


def center(if_mhz, w, grid=True):
    if int(w) not in NS_OF or float(w) != int(w):
        raise PlanError(f"幅 {w} MHz は 128・64・32・16・8 のどれか")
    c = FS - float(if_mhz)
    if grid:
        df = w / NFFT
        c = round(c / df) * df
    if not (w / 2 <= c <= FS / 2 - w / 2):
        raise PlanError(f"窓が帯域（IF 2048〜4096 MHz）からはみ出す: IF {FS - c:.6f} ± {w / 2}")
    return c


def plan(wins, H=8, E=3, S=8, NK=8, ddr=False, psplit=True, grid=True, wg=4, force_k=None):
    """wins: [(IF の中心 MHz, 幅 MHz), ...]（利用者の並び = 窓の番号 i）。force_k: {i: "near" | "alt"}（試験用: 粗い ch を決め打つ）
    戻り値: dict(streams=[H 個のレジスタの dict], wins=[窓 i ごとの dict（s・k・d・c・if・ns・fl・sl・wg・alt）], warn=[...])"""
    force_k = force_k or {}
    if len(wins) > H:
        raise PlanError(f"窓 {len(wins)} 本は頭 {H} に入らない")
    ws = []
    for i, (f, w) in enumerate(wins):
        c = center(f, w, grid)
        k1, k2 = k_options(c, w)
        fk = force_k.get(i)
        if fk == "alt":
            if k2 is None:
                raise PlanError(f"窓 {i}: 2 番目に近い粗い ch が使えない（幅 {w}・c {c}）")
            opts = [k2]
        elif fk == "near" or not psplit:
            opts = [k1]
        else:
            opts = [k1] if k2 is None else [k1, k2]
        if not all(0 <= k <= KMAX for k in opts):
            raise PlanError(f"窓 {i}: 粗い ch {opts} が 0..{KMAX} の外")
        ws.append(dict(i=i, if_req=float(f), w=float(w), ns=NS_OF[int(w)], c=c, if_mhz=FS - c, opts=opts))
    # 頭: 選べない窓を先に、組の空きで選ぶ
    half = H // 2
    room = {0: half, 1: H - half} if psplit else {0: H}
    side = {}
    for x in sorted(ws, key=lambda x: (len(x["opts"]), x["i"])):
        pick = None
        for k in x["opts"]:
            g = (k & 1) if psplit else 0
            if room[g] > 0:
                pick = k
                break
        if pick is None:
            raise PlanError(f"窓 {x['i']}（IF {x['if_mhz']}・{x['w']:g} MHz）: 粗い ch {x['opts']} の偶奇の組の頭が埋まっている")
        g = (pick & 1) if psplit else 0
        room[g] -= 1
        x["k"], x["alt"] = pick, pick != x["opts"][0] or force_k.get(x["i"]) == "alt"
        side[x["i"]] = g
    nxt = {0: 0, 1: half} if psplit else {0: 0}
    for x in ws:                                     # 組ごとに利用者の並びの順
        g = side[x["i"]]
        x["s"] = nxt[g]
        nxt[g] += 1
        x["d"] = x["c"] - SC * x["k"]
        x["dphi"] = dphi_of(x["d"])
    # 機関
    lsum = [0] * E
    for x in sorted(ws, key=lambda x: (x["ns"], x["i"])):
        u = unit(x["ns"])
        e = min(range(E), key=lambda e: (lsum[e], e))         # いちばん空いている lane
        if lsum[e] + u <= LANE_CAP:
            lsum[e] += u
            x["fl"] = e
        else:
            raise PlanError(f"機関 {E} 本の幅の和（各 256 MHz）に入らない: 窓の幅の和 {sum(x['w'] for x in ws):g} MHz")
    # 履歴の枠
    by_s = sorted(ws, key=lambda x: x["s"])
    on = by_s if len(by_s) <= S else None
    if on is None:
        if not ddr:
            raise PlanError(f"窓 {len(ws)} 本はチップ内の枠 {S} に入らない（この bit に PL の DDR は無い）")
        narrow = sorted(by_s, key=lambda x: (-x["ns"], x["s"]))[: len(by_s) - S]
        if sum(unit(x["ns"]) for x in narrow) > DDR_CAP or len(narrow) > NK:
            raise PlanError("DDR の窓の幅の和が 256 MHz を越える")
        on = [x for x in by_s if x not in narrow]
        for j, x in enumerate(narrow):
            x["sl"], x["wg"] = S + j, wg
    for j, x in enumerate(on):
        x["sl"], x["wg"] = j, 0
    streams = []
    for s in range(H):
        streams.append(dict(WK=(0 if s < half else 1) if psplit else 0, WDPHI=0, WNS=1, WFL=E, WSL=0, WG=0))
    for x in ws:
        streams[x["s"]] = dict(WK=x["k"], WDPHI=x["dphi"], WNS=x["ns"], WFL=x["fl"], WSL=x["sl"], WG=x["wg"])
    warn = []
    for x in ws:
        for ln in LINES_IF:
            if abs(ln - x["if_mhz"]) < 0.45 * x["w"]:
                warn.append(f"窓 {x['i']}: k·fs/8 の線 IF {ln:g} MHz が窓の中央 90 % に入る")
        if abs(x["if_mhz"] - x["if_req"]) > 1e-9:
            warn.append(f"窓 {x['i']}: 中心を ch の格子に丸めた IF {x['if_req']} → {x['if_mhz']}")
    for x in ws:
        del x["opts"]
    return dict(streams=streams, wins=ws, warn=warn, lane_sum=[u * 8 for u in lsum])


def check(streams, E=3, S=8, NK=8, psplit=True):
    """spw_regs.v の W_CHK と同じ数え方。WRST_BAD の印 [6:1]（bit 0 は使わない）を返す。0 なら通る。
    値はレジスタの幅（WK 6・WNS 3・WFL 2・WSL 4 bit）で切ってから数える（S ＋ NK = 16 の b5 では WSL 16 は 0 になり、[4] の「NK 以上」には届かない）"""
    H = len(streams)
    lsum = [0] * E
    dsum, used, bad = 0, set(), 0
    for ci, r0 in enumerate(streams):
        r = dict(r0, WK=r0["WK"] & 0x3F, WNS=r0["WNS"] & 7, WFL=r0["WFL"] & 3, WSL=r0["WSL"] & 0xF)   # レジスタの幅で切る（書いた値と同じに）
        if r["WFL"] >= E:
            continue
        u = unit(r["WNS"])
        if u == 0:
            bad |= 1 << 5
        if r["WK"] > KMAX or (psplit and (r["WK"] & 1) != (ci >= H // 2)):
            bad |= 1 << 6
        if (lsum[r["WFL"]] + u) % 64 > LANE_CAP:     # RTL の 6 bit の和（越えたら印は粘着するので折り返しは効かない）
            bad |= 1 << 1
        lsum[r["WFL"]] = (lsum[r["WFL"]] + u) % 64
        sl = r["WSL"]
        if sl >= S:
            if (dsum + u) % 64 > DDR_CAP:
                bad |= 1 << 2
            dsum = (dsum + u) % 64
            if sl >= S + NK or sl in used:
                bad |= 1 << 4
        elif sl in used:
            bad |= 1 << 3
        used.add(sl)
    return bad


def ch_of(f_if, x):
    """IF f_if [MHz] の CW が窓 x（plan の wins の 1 つ）で立つ ch（0..4095。ch 0 = 窓の中心、ch は f_bb とともに増える）と端数。窓の外なら None"""
    nu = (FS - f_if) - (SC * x["k"] + d_of(x["dphi"]))
    df = x["w"] / NFFT
    if abs(nu) > x["w"] / 2:
        return None
    b = nu / df
    return int(round(b)) % NFFT, b - round(b)


def wg_from_median(med, ns, ng=5, shift=4, target=20.0, wgmax=10):
    """P-10: DDR の窓の 8 bit の利得。中央値 med（f32 の窓のスペクトル）から σz = √(med / K)、K ≒ 20,000·2^−NS·(NG/5)·4^(4 − SHIFT)（NG・SHIFT の形は予言）。
    WG = ⌈log2(σz / target)⌉ を 0..wgmax に（σ8 を 10〜20 に入れる）"""
    K = 20000.0 * 2.0 ** (-ns) * (ng / 5.0) * 4.0 ** (4 - shift)
    if med <= 0:
        return 0
    sz = math.sqrt(med / K)
    return max(0, min(wgmax, math.ceil(math.log2(sz / target))))


def table(p):
    rows = ["窓  IF の中心 MHz      幅  NS  s   k  d MHz          WDPHI       機関  枠  WG"]
    for x in p["wins"]:
        rows.append(f"{x['i']:>2}  {x['if_mhz']:>15.6f}  {x['w']:>4g}  {x['ns']:>2}  {x['s']}  {x['k']:>2}{'*' if x['alt'] else ' '}"
                    f"{x['d']:>+13.6f}  {x['dphi']:#010x}  {x['fl']:>4}  {x['sl']:>2}  {x['wg']:>2}")
    rows.append(f"機関の幅の和 {p['lane_sum']} MHz（* = 2 番目に近い粗い ch）")
    rows += ["警告: " + w for w in p["warn"]]
    return "\n".join(rows)


if __name__ == "__main__":
    wins = [(float(a.split(":")[0]), float(a.split(":")[1])) for a in sys.argv[1:]]
    try:
        p = plan(wins)
    except PlanError as e:
        print("断る:", e)
        sys.exit(1)
    print(table(p))
    print("約束:", "通る" if check(p["streams"]) == 0 else f"破れる {check(p['streams']):#x}")
