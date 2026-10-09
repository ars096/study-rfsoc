#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj022 — SAM45-Wide の資源の見積もり（E-1）。表を作るだけ。数字の出どころは下の COMPONENTS に書く。

部品ごとに「置き場の案」を持ち、全部の組み合わせについて DSP・BRAM（RAMB36 換算）・URAM・LUT・FF を足し、
`-1` で閉じる見込みの目安（DSP ≦ 75 %・BRAM ≦ 80 %・URAM ≦ 90 %・LUT ≦ 70 %）に入るものを並べる。

**仮の値**（S-1 の survey と proj021 の最後で置き換える）:
  - レーン FFT 2048 点（実行時の長さ切り替え）の 1 個: proj014 の survey（入力 14 bit）→ S-1（入力 16 bit）で置き換え
  - v2 の共通部: proj021 2-1 の build-2-1-PE の実測（リングの分は 2-2 で増える）

使い方: python3 estimate.py [--fft-bram 7.5] [--fft-lut 3773] [--fft-ff 7186] [--fft-dsp 27] [--all]
"""
import argparse
import itertools

DEV = dict(DSP=4272, BRAM=1080, URAM=80, LUT=425280, FF=850560)        # XCZU48DR
LIMIT = dict(DSP=0.75, BRAM=0.80, URAM=0.90, LUT=0.70, FF=0.80)
NADC = 4
LANES = 16

# 1 ADC あたり（shared = True の案は 4 ADC で 1 組）
#   出どころ: proj021 build-2-1-PE の utilization_hier（FULL = spec_core_0: LUT 43,346・FF 82,935・RAMB36 25・RAMB18 112・DSP 504）
#   から lane_fft（物差し 512 点: DSP 21・LUT 2,336・FF 4,715・BRAM 3）× 16 を引いた残りを「鎖の残り」にする
REST = dict(DSP=504 - 16 * 21, LUT=43346 - 16 * 2336, FF=82935 - 16 * 4715)   # ひねり係数の cmul・16 点 DFT・電力・積分・TP・帳簿
COMMON = dict(DSP=0, BRAM=10, URAM=0, LUT=13900, FF=30400)                     # v2 の共通部・ギアボックス・SmartConnect（proj021 2-1 ＋ リングの見込み 10）

OPTIONS = {
    # PFB の係数（4 タップ × 長さ 3 本: 2048 + 1024 + 512 行 / レーン）
    "coef": {
        "BRAM・ADC ごと（対称で 32 ROM × 2）": dict(BRAM=64),
        "BRAM・4 ADC で共有": dict(BRAM=64 / NADC),
        "URAM・ADC ごと（1 語 = 4 タップ × 18 bit、16 個）": dict(URAM=16),
        "URAM・4 ADC で共有": dict(URAM=16 / NADC),
    },
    # ひねり係数 W_N^(p·k1)（1 本の表を長さに応じて 1・2・4 個おきに読む。レーン 0 は 1 なので 15 本 × 2048 × 36 bit）
    "tw": {
        "BRAM・ADC ごと（15 × 2）": dict(BRAM=30),
        "BRAM・4 ADC で共有": dict(BRAM=30 / NADC),
    },
    # PFB の履歴（x の 3 フレーム、14 bit × 3 = 42 bit / レーン、2048 行。読んで 1 つずらして書き戻す）
    "hist": {
        "BRAM（672 bit × 2048 → 10 × 4）": dict(BRAM=40),
        "URAM（672 bit → 10 個、深さの半分）": dict(URAM=10),
    },
    # 積分器（64 bit・2 面）
    "acc": {
        "切り出しだけ・BRAM（8 銀行 × 1024 × 2 面 → 32）": dict(BRAM=32),
        "切り出しだけ・URAM（16、深さの 1/4）": dict(URAM=16),
        "全 ch・BRAM（8 銀行 × 2048 × 2 面 → 64）": dict(BRAM=64),
        "全 ch・URAM（16、深さの半分）": dict(URAM=16),
    },
}
# 共有の案は、ADC ごとの固定のずれ（ビート）を吸う可変の遅延（SRL）を ADC ごとに: 係数 64 × 18 bit・ひねり係数 15 × 36 bit
SHARE_LUT = {"coef": 64 * 18, "tw": 15 * 36}


def per_adc_fixed(fft):
    """置き場を選ばない部品（1 ADC あたり）"""
    d = dict(DSP=0, BRAM=0, URAM=0, LUT=0, FF=0)
    for k in ("DSP", "BRAM", "LUT", "FF"):
        d[k] += LANES * fft[k]                         # レーン FFT × 16
    d["DSP"] += REST["DSP"] + 64                       # 鎖の残り ＋ PFB の積和（16 レーン × 4 タップ、14 × 18 bit、PCIN の縦続）
    d["LUT"] += REST["LUT"] + 1000                     # ＋ 切り出しの番地と 8 → 8 の振り分け（37 bit）
    d["FF"] += REST["FF"] + 3000 + 2000                # ＋ PFB の段（16 × 4 × 32 bit）・履歴の詰め直し
    d["BRAM"] += 8 + 2                                 # スナップショット（今と同じ）・TP のリング
    return d


def total(fft, choice):
    t = {k: COMMON[k] for k in DEV}
    f = per_adc_fixed(fft)
    for k in DEV:
        t[k] += NADC * f[k]
    for part, name in choice.items():
        for k, v in OPTIONS[part][name].items():
            t[k] += NADC * v
        if "共有" in name:
            t["LUT"] += NADC * SHARE_LUT[part]
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fft-dsp", type=float, default=27)
    ap.add_argument("--fft-lut", type=float, default=3773)
    ap.add_argument("--fft-ff", type=float, default=7186)
    ap.add_argument("--fft-bram", type=float, default=7.5)
    ap.add_argument("--all", action="store_true", help="入らない組み合わせも出す")
    a = ap.parse_args()
    fft = dict(DSP=a.fft_dsp, LUT=a.fft_lut, FF=a.fft_ff, BRAM=a.fft_bram)

    f = per_adc_fixed(fft)
    print(f"レーン FFT 1 個: DSP {a.fft_dsp:g}・LUT {a.fft_lut:g}・FF {a.fft_ff:g}・BRAM {a.fft_bram:g}（S-1 で置き換える）")
    print(f"置き場を選ばない部品（1 ADC）: DSP {f['DSP']:.0f}・BRAM {f['BRAM']:.0f}・LUT {f['LUT']:.0f}・FF {f['FF']:.0f}"
          f"（うちレーン FFT × 16: BRAM {LANES * a.fft_bram:g}）、共通部 {COMMON}")
    print()
    rows = []
    parts = list(OPTIONS)
    for combo in itertools.product(*[list(OPTIONS[p]) for p in parts]):
        choice = dict(zip(parts, combo))
        t = total(fft, choice)
        u = {k: t[k] / DEV[k] for k in DEV}
        ok = all(u[k] <= LIMIT[k] for k in DEV)
        rows.append((ok, max(u["BRAM"] / LIMIT["BRAM"], u["URAM"] / LIMIT["URAM"]), choice, t, u))
    rows.sort(key=lambda r: (not r[0], r[1]))
    n_ok = sum(r[0] for r in rows)
    print(f"組み合わせ {len(rows)} 通りのうち、目安に入るもの {n_ok} 通り（DSP ≦ 75 %・BRAM ≦ 80 %・URAM ≦ 90 %・LUT ≦ 70 %・FF ≦ 80 %）")
    print()
    for ok, score, choice, t, u in rows:
        if not ok and not a.all:
            continue
        print(("○ " if ok else "× ") + " / ".join(f"{p}: {choice[p]}" for p in parts))
        print("    " + "  ".join(f"{k} {t[k]:,.0f}（{100 * u[k]:.1f} %）" for k in DEV))
    # 共有なしの最良（入らないことの確かめ）
    best_none = min((r for r in rows if all("共有" not in v for v in r[2].values())), key=lambda r: r[1])
    print()
    print("共有なしで BRAM・URAM がいちばん楽な組み合わせ:")
    print("    " + " / ".join(f"{p}: {best_none[2][p]}" for p in parts))
    print("    " + "  ".join(f"{k} {best_none[3][k]:,.0f}（{100 * best_none[4][k]:.1f} %）" for k in DEV)
          + ("  → 目安に入る" if best_none[0] else "  → 目安に入らない"))


if __name__ == "__main__":
    main()
