#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj024 — 2G の資源の見積もり（E-1）。表を作るだけ。数字の出どころは下の定数の注釈に書く。

作りの案（README の D-1）:
  O4  2G-4 の bit: 4 ADC × 65536 点（4 コア × 16 レーン × 4096 点）。SAM45-Wide から束ね・切り出しを外し、レーン FFT を 2 倍に
  O2  2G-2 の bit: 2 ADC × 131072 点（2 コア × 16 レーン × 8192 点）
  O1  2G-1 の bit: 1 ADC × 262144 点（1 コア × 16 レーン × 16384 点）
  R   1 本の bit でレジスタで 1 / 2 / 4 を切り替える: 65536 点のコア × 4 ＋ 前段（model の M-1b）。
      履歴はコアごとに 4 フレーム（r < 4 では自分の 1/r の区間を 4 フレーム分持つ）、係数は補間（表では入らない）

部品ごとに「置き場・作り方の案」を持ち、全部の組み合わせについて DSP・BRAM（RAMB36 換算）・URAM・LUT・FF を足し、
目安（DSP ≦ 75 %・BRAM ≦ 80 %・URAM ≦ 90 %・LUT ≦ 65 %・FF ≦ 80 %）に入るものを並べる。
LUT の目安は proj022 の 70 % から 65 % に下げた（SAM45-Wide は 59.8 % で `-1` の余裕が +0.001〜0.04 ns しかなかった）。

レーン FFT 1 個の資源（FFT_IP の表）は S-1 の survey の実測（2026-10-17）。その前は外挿の仮の値だった（README の E-1 の「S-1 の前」）。

使い方: python3 estimate.py [--design O4|O2|O1|R|all] [--all] [--fft "4096,nat,30,3320,7000,15" ...]
"""
import argparse
import itertools
import math

DEV = dict(DSP=4272, BRAM=1080, URAM=80, LUT=425280, FF=850560)        # XCZU48DR
LIMIT = dict(DSP=0.75, BRAM=0.80, URAM=0.90, LUT=0.65, FF=0.80)
LANES = 16
XW = 14

# レーン FFT 1 個（固定長・realtime・unscaled・入力 15 bit・use_mults_resources・use_luts）。(点数, 出力順) → DSP, LUT, FF, BRAM
#   **S-1 の survey の実測**（2026-10-17、runs/survey_s1.txt）。DSP・BRAM は OOC のまま。LUT・FF は OOC 単体が本番より多めに出るので、
#   物差し（2048 点・自然順 = proj023 の lane_fft_w）の比で本番の大きさに直した: LUT × 2993 / 3157・FF × 6237 / 6343
FFT_IP = {
    (2048, "nat"): (27, 2993, 6237, 8),
    (2048, "rev"): (27, 2912, 5988, 5),
    (4096, "nat"): (27, 3365, 6820, 13.5),
    (4096, "rev"): (27, 3256, 6556, 7),
    (8192, "nat"): (33, 3896, 7814, 26),
    (8192, "rev"): (33, 3751, 7534, 13),
    (16384, "nat"): (33, 4348, 8446, 48.5),
    (16384, "rev"): (33, 4149, 8150, 21.5),
}

# コア 1 個の残り（レーン FFT・メモリの置き場を選ぶ部品を除く）。proj023 ビルド 11 の実測から:
#   DSP: PFB 80・鎖（ひねり係数の cmul・dft16・電力）144・TP 24（コアごとの DSP 680 − レーン FFT 432）
#   LUT: (全体 255,211 − レーン FFT 64 × 2,993 − 共通 13,900) / 4 ≒ 12,400
#   FF:  (全体 492,223 − レーン FFT 64 × 6,237 − 共通 30,400) / 4 ≒ 15,700
CORE_REST = dict(DSP=80 + 144 + 24, LUT=12400, FF=15700, BRAM=2)       # BRAM 2 = TP のリング
COMMON = dict(DSP=0, BRAM=10 + 8, URAM=0, LUT=13900, FF=30400)          # v2 の共通部・リング・SmartConnect ＋ RAW（proj023: 7.5）
CMUL_DSP = 4                                                           # 18 × 27 の複素乗算 1 個（cmul.v）

DESIGNS = {
    #      コア数  レーン FFT の点数  履歴のフレーム  係数の表を共有するコア数（T の格子で揃える）
    "O4": dict(ncore=4, M=4096, hist_frames=3, coef_share=4, front=False),
    "O2": dict(ncore=2, M=8192, hist_frames=3, coef_share=2, front=False),
    "O1": dict(ncore=1, M=16384, hist_frames=3, coef_share=1, front=False),
    "R": dict(ncore=4, M=4096, hist_frames=4, coef_share=1, front=True),
}

# ---------------------------------------------------------------- 記憶の割り付け

BRAM36_SHAPES = [(512, 72), (1024, 36), (2048, 18), (4096, 9), (8192, 4), (16384, 2), (32768, 1)]


def n_bram(depth, width):
    """深さ × 幅の記憶を RAMB36 で（いちばん少ない形。RAMB18 は 0.5）"""
    best = min(math.ceil(depth / d) * math.ceil(width / w) for d, w in BRAM36_SHAPES)
    if depth <= 512 and width <= 36:
        best = min(best, 0.5 * math.ceil(width / 36))
    return best


def n_uram(depth, width):
    return math.ceil(width / 72) * math.ceil(depth / 4096)


# ---------------------------------------------------------------- 部品の案（1 個の設計の中で選ぶ）

def options(d):
    M, nc = d["M"], d["ncore"]
    N_core = LANES * M
    o = {}
    # 出口の順（IP の設定）。bit 反転順なら積分器の番地を k1 の bit 反転で引く（記憶の番地なので並べ替えは無料）
    o["order"] = {"自然順": "nat", "bit 反転順": "rev"}
    # 積分器: 8 銀行（k2 = 0..7）× 深さ M × 2 面、幅 64 / 48 bit
    acc = {}
    for w in (64, 48):
        acc[f"{w} bit・URAM"] = dict(URAM=nc * n_uram(2 * M, 8 * w))
        acc[f"{w} bit・BRAM"] = dict(BRAM=nc * n_bram(2 * M, 8 * w))
    o["acc"] = acc
    # PFB の履歴: 16 レーン × 14 bit × フレーム数、深さ M。PFB を入れない案は履歴も係数も無い
    F = d["hist_frames"]
    # 履歴は幅を URAM の列（72 bit）と BRAM に分けてよい（URAM の列の数 u をコアごとに同じに）
    W = LANES * XW * F
    nu = math.ceil(W / 72)
    pfb = {}
    for u in sorted({0, nu // 4, nu // 2, (3 * nu) // 4, nu}):
        rest = max(0, W - 72 * u)
        lab = "URAM" if u == nu else ("BRAM" if u == 0 else f"URAM {u} 列 ＋ BRAM")
        pfb[f"T 4・履歴 {lab}"] = dict(URAM=nc * u * math.ceil(M / 4096),
                                      BRAM=nc * (n_bram(M, rest) if rest else 0), _pfb=True)
    pfb["PFB なし（矩形）"] = dict(DSP=-nc * 80, _pfb=False)
    o["pfb"] = pfb
    # PFB の係数（T 4 のときだけ効く）: 表（16 レーン × 4 タップ × 18 bit、深さ M）を共有のコアで 1 組 / 線形補間（D 64）
    ntab = math.ceil(nc / d["coef_share"])
    coef = {}
    if not d["front"]:
        coef["表（BRAM・共有）"] = dict(BRAM=ntab * n_bram(M, LANES * T_ * 18))
    else:
        # 案 R: r ごとに読む区間が違うので、表ならモードごと・コアごと（r 1: 4N/4 = 2^18 タップ / コア ほか）→ 入らない
        coef["表（BRAM・モードごと）"] = dict(BRAM=nc * (n_bram(M, 1152) + n_bram(M, 1152) + n_bram(M, 1152)))
    # 補間: 1 タップ 1 読み（1 拍の 16 レーンは同じ区間に入る。D 64 は 16 の倍数）× 4 タップ、値と傾き 24 bit × 2
    #       傾き × 端数（6 bit）は LUT の掛け算（≒ 60 LUT）× 16 レーン × 4 タップ
    L_taps = 4 * N_core * (4 if d["front"] else 1)                         # R はコアごとに 1 ADC の原型の全部を引けるように
    # M-8（2026-10-17）: 表は片側 L/128 区間 × 35 bit（節 23 ＋ 傾き 12、G 5）。1 拍の 4 読みは t 0・3 が前半、t 1・2 が後半
    #   → 前半・後半を 2 ポートの ROM に（2G-1 で RAMB36 8 個）。R は M-8 の前の数え（4 タップ × 48 bit）のまま
    if d["front"]:
        coef["線形補間（D 64）"] = dict(BRAM=nc * T_ * n_bram(L_taps // 64 // T_, 48), LUT=nc * 64 * 60, FF=nc * 64 * 24)
    else:
        coef["線形補間（D 64）"] = dict(BRAM=nc * 2 * n_bram(L_taps // 128 // 2, 35), LUT=nc * 64 * 60, FF=nc * 64 * 24)
    o["coef"] = coef
    # ひねり係数 W_N^(p·k1)（15 レーン × M × 36 bit）: コアごとの表（IP の出口の位相はコアで揃う保証が無い。LESSONS）/ 2 つの小さな表の積
    o["tw"] = {
        "表（BRAM・コアごと）": dict(BRAM=nc * n_bram(M, 15 * 36)),
        "2 つの表の積": dict(BRAM=nc * 2 * n_bram(128, 15 * 36), DSP=nc * 15 * CMUL_DSP, LUT=nc * 1500, FF=nc * 2000),
    }
    # 案 R の前段: r 点の DFT（加算だけ）＋ W_N^(n·m) の cmul（コア m = 1..3 の 16 レーン）＋ 入力の振り分け
    if d["front"]:
        o["front"] = {
            "前段のひねり係数を表で": dict(BRAM=3 * n_bram(M, LANES * 36), DSP=3 * LANES * CMUL_DSP, LUT=nc * 9000, FF=nc * 12000),
            "前段のひねり係数を積で": dict(BRAM=3 * 4, DSP=3 * LANES * 2 * CMUL_DSP, LUT=nc * 10000, FF=nc * 14000),
        }
    return o


T_ = 4


def total(d, choice, opts):
    t = {k: COMMON.get(k, 0) for k in DEV}
    nc = d["ncore"]
    dsp, lut, ff, bram = FFT_IP[(d["M"], opts["order"][choice["order"]])]
    t["DSP"] += nc * LANES * dsp
    t["LUT"] += nc * LANES * lut
    t["FF"] += nc * LANES * ff
    t["BRAM"] += nc * LANES * bram
    for k in ("DSP", "LUT", "FF", "BRAM"):
        t[k] += nc * CORE_REST[k]
    pfb_on = opts["pfb"][choice["pfb"]]["_pfb"]
    for part, name in choice.items():
        if part == "order":
            continue
        if part == "coef" and not pfb_on:
            continue
        for k, v in opts[part][name].items():
            if not k.startswith("_"):
                t[k] += v
    return t


def run(dname, show_all):
    d = DESIGNS[dname]
    opts = options(d)
    parts = list(opts)
    rows = []
    for combo in itertools.product(*[list(opts[p]) for p in parts]):
        choice = dict(zip(parts, combo))
        if not opts["pfb"][choice["pfb"]]["_pfb"] and choice["coef"] != list(opts["coef"])[0]:
            continue                                                   # PFB なしでは係数の案は意味が無い（1 つだけ数える）
        t = total(d, choice, opts)
        u = {k: t[k] / DEV[k] for k in DEV}
        ok = all(u[k] <= LIMIT[k] for k in DEV)
        score = max(u[k] / LIMIT[k] for k in DEV)
        rows.append((ok, score, choice, t, u))
    rows.sort(key=lambda r: r[1])
    n_ok = sum(r[0] for r in rows)
    print(f"==== {dname}: コア {d['ncore']} × 16 レーン × {d['M']} 点"
          f"{'（＋前段、1 / 2 / 4 をレジスタで）' if d['front'] else ''} — 組み合わせ {len(rows)} 通りのうち目安に入るもの {n_ok} 通り")
    shown = 0
    for ok, score, choice, t, u in rows:
        if not ok and not show_all and shown >= 3:
            break
        if not ok and not show_all and n_ok > 0:
            continue
        print(("  ○ " if ok else "  × ") + " / ".join(f"{choice[p]}" for p in parts if not (p == "coef" and "なし" in choice["pfb"])))
        print("      " + "  ".join(f"{k} {t[k]:,.0f}（{100 * u[k]:.1f} %）" for k in DEV))
        shown += 1
        if shown >= (12 if not show_all else 10 ** 9):
            break
    def best(label, cond):
        sel = [r for r in rows if cond(r[2])]
        if not sel:
            return
        ok, score, choice, t, u = min(sel, key=lambda r: r[1])
        print(f"  {label}: " + " / ".join(choice[p] for p in parts))
        print("      " + "  ".join(f"{k} {100 * u[k]:.1f} %" for k in DEV) + ("  → 入る" if ok else "  → 入らない"))

    pfb = lambda c: "なし" not in c["pfb"]
    best("PFB あり（T 4）の最良", pfb)
    best("PFB あり・自然順の最良", lambda c: pfb(c) and c["order"] == "自然順")
    best("何も工夫しない（自然順・64 bit・ひねり係数は表・PFB あり）の最良",
         lambda c: pfb(c) and c["order"] == "自然順" and c["tw"].startswith("表") and c["acc"].startswith("64"))
    # 感度: PFB あり（T 4）で、レーン FFT 1 個の BRAM がいくつまでなら入るか（ほかの案は最良を選ぶ）
    order = "rev"
    key = (d["M"], order)
    keep = FFT_IP[key]
    lim = None
    for b in [x / 2 for x in range(80, -1, -1)]:
        FFT_IP[key] = keep[:3] + (b,)
        if any(all(total(d, c, opts)[k] / DEV[k] <= LIMIT[k] for k in DEV)
               for c in (dict(zip(parts, cb)) for cb in itertools.product(*[list(opts[p]) for p in parts]))
               if "なし" not in c["pfb"] and c["order"] == "bit 反転順"):
            lim = b
            break
    FFT_IP[key] = keep
    print(f"  感度: PFB あり・bit 反転順で目安に入るのは、レーン FFT（{d['M']} 点）1 個の "
          + (f"BRAM ≦ {lim:g} のとき（今の値 {keep[3]:g}）" if lim is not None
             else "BRAM がいくつでも入らない（BRAM 以外が律速）"))
    print()
    return n_ok


def mem_table():
    """記憶の量（Mbit、割り付けの前）。どこが重いかを先に見る"""
    print("記憶の量（Mbit、割り付けの前）。デバイスは BRAM 38.9・URAM 23.6、計 62.5 Mbit")
    print(f"  {'':4s} {'積分器 64b':>10s} {'48b':>6s} {'履歴':>6s} {'係数(表)':>9s} {'tw(表)':>7s} {'FFT IP(自然順)':>11s}")
    for name, d in DESIGNS.items():
        M, nc = d["M"], d["ncore"]
        acc64 = nc * 2 * 8 * M * 64 / 1e6
        acc48 = acc64 * 48 / 64
        hist = nc * LANES * XW * d["hist_frames"] * M / 1e6
        ntab = math.ceil(nc / d["coef_share"]) * (3 if d["front"] else 1)
        coef = ntab * LANES * 4 * 18 * M / 1e6
        tw = nc * 15 * 36 * M / 1e6
        fft = nc * LANES * FFT_IP[(M, "nat")][3] * 36.864 / 1e3
        print(f"  {name:4s} {acc64:10.1f} {acc48:6.1f} {hist:6.1f} {coef:9.1f} {tw:7.1f} {fft:11.1f}")
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--design", default="all")
    ap.add_argument("--all", action="store_true", help="入らない組み合わせも全部出す")
    ap.add_argument("--fft", action="append", default=[],
                    help="S-1 の実測で置き換える: '点数,nat|rev,DSP,LUT,FF,BRAM'（何回でも）")
    a = ap.parse_args()
    for s in a.fft:
        n, o, *v = s.split(",")
        FFT_IP[(int(n), o)] = tuple(float(x) for x in v)
    print("レーン FFT 1 個（DSP・LUT・FF・BRAM）: " + "  ".join(f"{n}{'n' if o == 'nat' else 'r'} {v}" for (n, o), v in sorted(FFT_IP.items())))
    print("  （S-1 の survey の実測。LUT・FF は物差しの比で本番の大きさに直した）" if not a.fft else "  （--fft で置き換えた値を含む）")
    print()
    mem_table()
    for dn in (DESIGNS if a.design == "all" else [a.design]):
        run(dn, a.all)


if __name__ == "__main__":
    main()
