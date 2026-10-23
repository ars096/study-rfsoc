#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 E-2・E-3 — 2 段分光（荒い PFB → PL DDR4 で corner turn → 細かい PFB＋FFT）の資源・帯域・出口の見積もり。表を作るだけ。

決めたこと（README）: os 8/7・M 64・D 56・T_c 27・b 8（S 12）。細かい側は流れ 1 本 × 16 レーンで荒い ch を 1 本ずつ順に処理する。
数字の出どころは定数の注釈に書く。荒い FFT・MIG・corner turn の溜めは S-1 の OOC 合成の実測。**「仮」と書いた値は実装の実測が無い**（荒い PFB の LUT・FF、DDR の読み手・AXI）。

使い方: python3 tools/estimate.py
"""
import math

DEV = dict(DSP=4272, BRAM=1080, URAM=80, LUT=425280, FF=850560)        # XCZU48DR
LIMIT = dict(DSP=0.75, BRAM=0.80, URAM=0.90, LUT=0.65, FF=0.80)         # proj024 と同じ目安
FS = 4096e6
CLK = 256e6
LANES = 16
M, P_OS, Q_OS = 64, 8, 7
D = M * Q_OS // P_OS                      # 56
TC = 27                                   # 荒い PFB の 1 枝のタップ（M-1）
NCOARSE = M // 2                          # 32
B = 8                                     # 再量子化の語長（各成分）
T_FINE = 4
ACC_W = 48
DT_UNIT = Q_OS * 524288 * 16 / FS         # 14.336 ms（q × 2.048 ms）
OUT_RATE = 131072 / 10.24e-3              # 2G-1 の N/dt = 12.8 M ch/s（リング 102.4 MB/s・ネットワーク 51.2 MB/s）
DDR_PEAK = 19.2e9
DDR_BUDGET = 0.70 * DDR_PEAK              # H-0 の仮の目安
DDR_SIZE = 4 * 2 ** 30

# レーン FFT 1 個（bit 反転順）。proj024 の S-1 の実測（OOC。LUT・FF は本番の大きさに直した値）。1024 点は外挿（仮）
FFT_IP = {
    1024: (27, 2600, 5500, 4),            # 仮（2048 点から 2 倍ごとの差で外挿）
    2048: (27, 2912, 5988, 5),
    4096: (27, 3256, 6556, 7),
    8192: (33, 3751, 7534, 13),
    16384: (33, 4149, 8150, 21.5),
}

# 細かい側のレーン FFT 以外（proj023 ビルド 11 の CORE_REST を複素の入力に直す）:
#   PFB 80 → 複素で 160 ＋ 係数の補間の DSP 64（proj027 F-2）、鎖 144 → dft16 の 16 出力全部で 288、TP 24
FINE_REST = dict(DSP=160 + 64 + 288 + 24, LUT=int(12400 * 1.5), FF=int(15700 * 1.5), BRAM=2 + 7.5 + 11)  # 係数 7.5・ひねり係数 11（2G-1 build-PE）
# 荒い段（S-1 の後）: PFB は積和の数で fs·T_c·os / 256 MHz = 494（1 入力サンプルが L/D = 30.9 ブロックに効く）。LUT・FF は仮
#   荒い FFT は S-1 の実測（cfft32、OOC 合成: DSP 252・LUT 12,700・FF 14,250）。出口の回転は M-1d で不要（細かい ch の巡回）。利得 20
COARSE_PFB_DSP = math.ceil(FS * TC * P_OS / Q_OS / CLK)
COARSE = dict(DSP=COARSE_PFB_DSP + 252 + 20, LUT=15000 + 12700 + 3000, FF=30000 + 14250 + 5000, BRAM=8)
# DDR 系（S-1 の後）: MIG は ddr4_pl の実測（DSP 3・LUT 15,124・FF 17,931・BRAM 25.5）、corner turn の溜めは ct_buf の実測（BRAM 57）。
#   読み手・AXI の LUT 6,000・FF 8,000・BRAM 8 は仮
DDRSYS = dict(DSP=3, LUT=15124 + 6000, FF=17931 + 8000, BRAM=25.5 + 57 + 8)
COMMON = dict(DSP=0, BRAM=18, LUT=13900, FF=30400)                     # proj024 と同じ（v2 の共通部・リング・RAW）


def bram36(bits):
    return math.ceil(bits / 36864)


def row(nf):
    L = nf // LANES
    keep = nf * Q_OS // P_OS
    N = NCOARSE * keep
    df = FS / (D * nf)
    frame = D * nf / FS
    # E-3: 出口で決まる dt の下限（14.336 ms の倍数に切り上げ）
    dt = math.ceil(N / OUT_RATE / DT_UNIT - 1e-9) * DT_UNIT
    frames = dt / frame
    # E-1: DDR（継ぎ目の読み直し (T−1)/フレーム数を含む）
    wr = NCOARSE * (FS / D) * 2 * B / 8
    rd = wr * (1 + (T_FINE - 1) / frames)
    ddr = wr + rd
    ddr_size = 2 * dt * wr
    busy = (wr / (2 * B / 8)) * (1 + (T_FINE - 1) / frames) / (LANES * CLK)
    # E-2: 記憶
    hist = bram36((T_FINE - 1) * nf * 2 * B)
    dsp_f, lut_f, ff_f, bram_f = FFT_IP[L]
    acc_uram = math.ceil(2 * keep / (4096 * 72 // ACC_W))
    t = {}
    for k in ("DSP", "LUT", "FF", "BRAM"):
        t[k] = COMMON[k] + COARSE[k] + DDRSYS[k] + FINE_REST[k]
    t["DSP"] += LANES * dsp_f
    t["LUT"] += LANES * lut_f
    t["FF"] += LANES * ff_f
    t["BRAM"] += LANES * bram_f + hist
    t["URAM"] = acc_uram
    return dict(nf=nf, L=L, N=N, df=df, dt=dt, frames=frames, ddr=ddr, ddr_size=ddr_size, busy=busy, hist=hist, t=t)


def main():
    print("== E-2・E-3（os %d/%d・M %d・D %d・T_c %d・b %d、細かい側 1 本 × %d レーン、出口 N/dt ≦ %.1f M ch/s）"
          % (P_OS, Q_OS, M, D, TC, B, LANES, OUT_RATE / 1e6))
    print("  N_f      N         df        dt の下限   フレーム/dt  DDR（目安 %.1f）  DDR の量   忙しさ  "
          "DSP     BRAM    URAM    LUT     FF      目安" % (DDR_BUDGET / 1e9))
    for nf in (16384, 32768, 65536, 131072, 262144):
        r = row(nf)
        t = r["t"]
        pct = {k: t[k] / DEV[k] for k in DEV}
        bad = [k for k in DEV if pct[k] > LIMIT[k]]
        if r["ddr"] > DDR_BUDGET:
            bad.append("DDR 帯域")
        if r["ddr_size"] > DDR_SIZE:
            bad.append("DDR の量")
        print("  %-7d  %-8d  %5.2f kHz  %7.2f ms  %6.0f       %5.2f GB/s       %5.2f GB   %3.0f %%   "
              "%4.1f %%  %4.1f %%  %4.1f %%  %4.1f %%  %4.1f %%  %s"
              % (nf, r["N"], r["df"] / 1e3, r["dt"] * 1e3, r["frames"], r["ddr"] / 1e9, r["ddr_size"] / 2 ** 30,
                 100 * r["busy"], 100 * pct["DSP"], 100 * pct["BRAM"], 100 * pct["URAM"], 100 * pct["LUT"],
                 100 * pct["FF"], "○" if not bad else "× " + "・".join(bad)))
    print("  内訳（N_f 131072）:")
    r = row(131072)
    print("    BRAM: 共通 %d・荒い段 %d・DDR 系 %d・細かい側の残り %.1f・レーン FFT 16 × %.1f・履歴 %d"
          % (COMMON["BRAM"], COARSE["BRAM"], DDRSYS["BRAM"], FINE_REST["BRAM"], FFT_IP[r["L"]][3], r["hist"]))
    print("    DSP:  荒い段 %d（PFB %d）・細かい側の残り %d・レーン FFT 16 × %d" % (COARSE["DSP"], COARSE_PFB_DSP, FINE_REST["DSP"], FFT_IP[r["L"]][0]))


if __name__ == "__main__":
    main()
