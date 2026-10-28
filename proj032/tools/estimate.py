#!/usr/bin/env python3
"""estimate — proj032 の資源の見積もり（E-1・E-2 の実数から。構成 H・E・S を引数で）。

部品ごとの値は README の E-1（SAM45-Fine の配置後）・E-2（pfb64_core の OOC）が出典。
数えた値と、そこからの推し量り（「推」）を分けて持つ。推し量りの根拠はそれぞれの行の注に書く。

  python3 tools/estimate.py                 # γ（H 16・E 3・S 8・偶奇の 2 組）
  python3 tools/estimate.py --H 12 --S 6    # 構成を変えて
"""
import argparse

CHIP = {"LUT": 425_280, "DSP": 4_272, "BRAM": 1_080, "URAM": 80}
KB_RAMB36, KB_URAM = 36.864, 294.912     # kbit

ap = argparse.ArgumentParser()
ap.add_argument("--H", type=int, default=16, help="ADC ごとの窓の頭")
ap.add_argument("--E", type=int, default=3, help="ADC ごとの機関（帯域の和 256 MHz ずつ）")
ap.add_argument("--S", type=int, default=8, help="ADC ごとの、PFB の履歴をチップ内に持つ窓")
ap.add_argument("--no-psplit", action="store_true", help="頭を偶奇の 2 組に分けない")
ap.add_argument("--nco-p", type=int, default=14, help="NCO の位相の bit（14: RAMB36 2 / 頭、12: RAMB18 1 / 頭）")
a = ap.parse_args()
H, E, S = a.H, a.E, a.S
psplit = not a.no_psplit
NADC = 4

rows = []   # (名前, LUT, DSP, RAMB36, URAM, 出典)

def L_LANES(h):   # light の lane: 2 段目 ⌈h/4⌉・3 段目 ⌈h/8⌉・4 段目 ⌈h/16⌉
    return (h + 3) // 4 + (h + 7) // 8 + (h + 15) // 16
DDCB_REF = dict(H=14, E=3, LUT=18_366)     # E-3 の ddcb の OOC（配置後）の LUT。下の DDCB_LUT が lane の数で比例させる
def DDCB_LUT(h, e):
    # 実数は H 14・E 3。lane（light 685・final 2,151 の配置後の実数）と、窓ごとのつなぎ（残り）に分けて比例させる
    lanes_ref = 685 * L_LANES(14) + 2_151 * 3
    glue_ref = DDCB_REF["LUT"] - lanes_ref
    return 685 * L_LANES(h) + 2_151 * e + glue_ref * h / 14
def add(name, lut, dsp, bram, uram, src):
    rows.append((name, lut, dsp, bram, uram, src))

# ---- ADC ごと ----
add("粗い PFB（共有部分）", 10_077, 312, 0, 0, "E-3 実（配置後）: OOC NH 1 の 10,866 から頭 1 つ分を引いた")
add(f"粗い PFB の頭ごとの選択・実数化 × {H}", H * (789 if psplit else 1_426), H * 4, 0, 0,
    "E-3 実（配置後）: NH 1 と NH 14（偶奇の 2 組）の傾き" + ("" if psplit else "（偶奇なしは合成の数）"))
nco_bram = 2 if a.nco_p == 14 else 0.5
add(f"頭の NCO ＋ light 1 段目 × {H}", H * 791, H * 10, H * nco_bram, 0,
    "E-3 実（配置後）: head_core")
add(f"後段の共有（light 2〜4 段目・final {E} 本、ddcb）", DDCB_LUT(H, E), 10 * L_LANES(H) + 36 * E, 0, 0,
    "E-3 実（配置後）: ddcb の OOC（H・E が違うときは lane の数で比例）")
add(f"機関（窓の PFB ＋ FFT ＋ 積分の制御）× {E}", E * 5_900, E * 42, E * 19, 0,
    "推: Fine の u_ws（42 DSP・5,890 LUT・FFT 15 ＋ 係数 4）")
add(f"窓ごとの積分器 × {H}", H * 300, 0, 0, H * 1, "推: 4096 × 48 bit = URAM 1、制御 300 LUT")
hist_kbit = S * 5 * 4096 * 36 / 1000
add(f"チップ内の履歴（5 フレーム × 36 bit）× {S}", S * 200, 0, hist_kbit / KB_RAMB36, 0,
    "推: 737 kbit / 窓。ここでは全部 BRAM に置いて数える（URAM の残りに寄せれば減る）")
add("DDR の道（書き手・読み手・溜め）", 3_000, 0, 13, 0, "推: proj028 の ct_wr。BRAM は D-1 の実機から: 書きのバースト 2 KiB × 2 面 × 窓 14")
add("TP・RAW・コアの上位", 3_700, 24, 10, 0, "E-1 実: Fine の u_tp・u_raw・u_win の上位")

per = [sum(r[i] for r in rows) for i in (1, 2, 3, 4)]
tot = [NADC * v for v in per]
# ---- チップに 1 つ ----
glob = [("MIG（DDR4）", 15_600, 0, 25.5, 0, "proj028 S-1 実"),
        ("基盤（PS・SmartConnect・ギアボックス・時刻・リング）", 17_000, 0, 9.5, 0, "E-1 実: Fine の全体 − u_win × 4")]
for g in glob:
    for i in range(4):
        tot[i] += g[i + 1]

print(f"構成: H {H}・E {E}・S {S}・偶奇の 2 組 {'あり' if psplit else 'なし'}・NCO {a.nco_p} bit")
print(f"{'部品（ADC ごと）':<40} {'LUT':>8} {'DSP':>6} {'RAMB36':>7} {'URAM':>5}  出典")
for r in rows:
    print(f"{r[0]:<40} {r[1]:>8,.0f} {r[2]:>6,.0f} {r[3]:>7.1f} {r[4]:>5.0f}  {r[5]}")
print(f"{'ADC ごとの計':<40} {per[0]:>8,.0f} {per[1]:>6,.0f} {per[2]:>7.1f} {per[3]:>5.0f}")
for g in glob:
    print(f"{g[0]:<40} {g[1]:>8,.0f} {g[2]:>6,.0f} {g[3]:>7.1f} {g[4]:>5.0f}  {g[5]}")
print(f"{'全体（4 ADC ＋ チップに 1 つ）':<40} {tot[0]:>8,.0f} {tot[1]:>6,.0f} {tot[2]:>7.1f} {tot[3]:>5.0f}")
print("チップ比: LUT {:.1f} %・DSP {:.1f} %・BRAM {:.1f} %・URAM {:.1f} %".format(
    100 * tot[0] / CHIP["LUT"], 100 * tot[1] / CHIP["DSP"], 100 * tot[2] / CHIP["BRAM"], 100 * tot[3] / CHIP["URAM"]))
