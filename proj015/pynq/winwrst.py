#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj014 — 判定 W-8: 窓の設定の切り替え（WRST）と Overlay の読み込み直しを繰り返し、毎回 W-0・W-G が通るかを見る。

  python3 winwrst.py --cycles 100 --clkin 0 --ref 10                     WRST を 100 回
  python3 winwrst.py --cycles 30 --reloads 10 --clkin 0 --ref 10         Overlay の読み込み直し 10 回（各 3 回の WRST）も

1 回ごとに（SG は使わない。雑音だけ）:
  1. 窓の設定（幅・中心）を選んで WRST。WCUR の読み返し（Win.set_window）・WRST_CNT が 1 増える
  2. N_ACC = 1 のダンプを 1 つとり、**W-G: ダンプ = 同じフレームのスナップショットの numpy FFT**（window.py --golden と同じ比べ方）。
     スナップショットのフレーム = ダンプの f0
  3. **W-0: FLAGS（[4] 待たされた は除く）= 0・pfb / ddc の飽和 0・ダンプの飽和 0**。待たされたクロック数と tready が 1 になるまでも記録する
窓の設定の選び方: 6 通りの幅を順に回し、中心は帯域の中から乱数（--seed）。**粗い ch の境目（d = ±64）・粗い ch 0 / 16・窓の端が DC / fs/2 に接する置き方**を
ときどき混ぜる（--special の割合）。同じ設定を続けて 2 回打つ回も混ぜる
SHIFT: 雑音の床が 400 LSB² 前後になる見当を幅から出す（SHIFT 11 の真の雑音 ≒ 4.9 × W / 256、下限 0.3 LSB²。実機の W-5 の床から）。
比べる値が 0 ばかりにならず、かつ飽和しないように
"""
import argparse
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
NFFT_W = 4096
WIDTHS = (256, 128, 64, 32, 16, 8)


def log(*a):
    print(*a, flush=True)


def pick(rng, w, special):
    """窓の IF の中心（ch の格子に丸める前）。special の割合で、試しにくい置き方を選ぶ。"""
    lo, hi = 2048.0 + w / 2 + 1.0, 4096.0 - w / 2 - 1.0
    if rng.random() < special:
        kind = rng.integers(4)
        if kind == 0:                                  # 粗い ch の境目 c = 128k + 64
            k = rng.integers(0, 16)
            c = 128.0 * k + 64.0
        elif kind == 1:                                # 粗い ch 0 / 16 の中
            c = rng.choice([w / 2 + 1.0 + rng.random() * (64.0 - w / 2), 2048.0 - w / 2 - 1.0 - rng.random() * (64.0 - w / 2)]) \
                if w < 128 else rng.choice([w / 2 + 1.0, 2048.0 - w / 2 - 1.0])
        elif kind == 2:                                # 窓の端が DC / fs/2 に接する
            c = rng.choice([w / 2, 2048.0 - w / 2])
        else:                                          # 粗い ch の中心（d = 0）
            c = 128.0 * rng.integers(1, 16)
        c = float(np.clip(c, w / 2, 2048.0 - w / 2))
        return 4096.0 - c, ["境目", "ch 0/16", "端", "d=0"][kind]
    return float(lo + rng.random() * (hi - lo)), ""


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cycles", type=int, default=100, help="WRST の回数（Overlay の読み込み直しのぶんは別）")
    p.add_argument("--reloads", type=int, default=0, help="Overlay の読み込み直しの回数（各回のあと --per-reload 回の WRST）")
    p.add_argument("--per-reload", type=int, default=3)
    p.add_argument("--special", type=float, default=0.3, help="試しにくい置き方を選ぶ割合")
    p.add_argument("--repeat", type=float, default=0.1, help="前と同じ設定で WRST を打つ割合")
    p.add_argument("--seed", type=int, default=14)
    p.add_argument("--floor", type=float, default=400.0, help="W-G で狙う雑音の床 [LSB² / フレーム]")
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--settle-reload", type=float, default=2.0)
    p.add_argument("--bitfile", default=None)
    p.add_argument("--allow-nopreset", action="store_true")
    p.add_argument("--out", default=None, help="PREFIX.wrst.npz に 1 回ごとの記録")
    a = p.parse_args()

    import window as WN
    import spectrometer as S
    from pynq import Overlay
    import xrfdc                                   # Overlay() より前に import する（VERSIONS.md）
    bit = a.bitfile or S.BITFILE
    S.setup_clocks(a.clkin, a.ref)

    def load():
        ol = Overlay(bit)
        if not isinstance(ol.rfdc, xrfdc.RFdc):
            log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
        S.check_tiles(ol.rfdc, 2)
        return ol

    ol = load()
    if a.settle > 0:
        time.sleep(a.settle)
    wn = WN.open_win(ol, a.allow_nopreset)
    rng = np.random.default_rng(a.seed)
    rows = []
    fails = []
    prev = None
    plan = ["wrst"] * a.cycles + sum([["reload"] + ["wrst"] * a.per_reload for _ in range(a.reloads)], [])
    t0 = time.time()
    i_w = 0
    for step, what in enumerate(plan):
        if what == "reload":
            t1 = time.time()
            ol = load()
            if a.settle_reload > 0:
                time.sleep(a.settle_reload)
            wn = WN.open_win(ol, a.allow_nopreset)
            log(f"[{step + 1}/{len(plan)}] Overlay を読み込み直した（{time.time() - t1:.1f} s）")
            prev = None
            continue
        if prev is not None and rng.random() < a.repeat:
            if_c, w, tag = prev[0], prev[1], "同じ設定"
        else:
            w = float(WIDTHS[i_w % len(WIDTHS)]); i_w += 1
            if_c, tag = pick(rng, w, a.special)
        c, k, dphi, ns, if_g = WN.window_params(if_c, w, grid=True)
        prev = (if_g, w)
        true11 = max(0.3, 4.9 * w / 256.0)
        shift = int(np.clip(11 - round(np.log(a.floor / true11) / np.log(4.0)), 0, 15))
        n0 = wn.rd(0x7C)                               # WRST_CNT
        err = []
        try:
            wn.set_window(k, dphi, ns)
        except RuntimeError as e:
            err.append(f"WRST: {e}")
        n1 = wn.rd(0x7C)
        if n1 != (n0 + 1) & 0xFFFFFFFF:
            err.append(f"WRST_CNT {n0} → {n1}（1 増えない）")
        time.sleep(0.01)
        f_start = wn.rd(WN.R_FLAGS)
        wn.wr(WN.R_CTRL, WN.CTRL_CLR)
        seq = wn.run(1, 1, shift)
        tf = NFFT_W / w * 1e-6
        if wn.wait_dump(seq, 20 * tf + 1.0) is None:
            err.append("ダンプが閉じない")
            m = None
        else:
            m, spec, snap = wn.read_dump(with_snap=True)
        nbad = -1; floor = np.nan
        if m is not None:
            if m["snap_f"] != m["f0"]:
                err.append(f"スナップショットのフレーム {m['snap_f']} ≠ ダンプの f0 {m['f0']}")
            if m["n"] != 1:
                err.append(f"ダンプの n {m['n']}")
            if m["sat"]:
                err.append(f"ダンプの飽和 {m['sat']}")
            Y = np.fft.fft(snap.astype(complex))
            qr = np.floor(Y.real / 2 ** shift); qi = np.floor(Y.imag / 2 ** shift)
            ok_ch = (np.abs(qr) < 2 ** 17 - 4) & (np.abs(qi) < 2 ** 17 - 4)
            a_np = np.hypot(qr, qi); a_hw = np.sqrt(spec.astype(float))
            d = np.abs(a_hw - a_np)
            tol = 2.0 + 1e-4 * a_np[ok_ch].max()
            nbad = int(np.count_nonzero(d[ok_ch] > tol))
            floor = float(np.median(spec.astype(float)))
            if nbad:
                worst = int(np.argmax(np.where(ok_ch, d / tol, 0)))
                err.append(f"W-G: {nbad} ch が合わない（最悪 ch {worst}: 差 {d[worst]:.1f} / 振幅 {a_np[worst]:.0f}）")
            if floor < 4:
                err.append(f"W-G: 床 {floor:.1f} LSB² で比べる値がほぼ 0（SHIFT {shift} が大きすぎる。判定が弱い）")
        flags = wn.rd(WN.R_FLAGS)
        ps, ds = wn.rd(WN.R_PFB_SAT), wn.rd(WN.R_DDC_SAT)
        if flags & 0x3EF:
            err.append(f"FLAGS {flags:#x}（{WN.flag_text(flags)}）")
        if ps or ds:
            err.append(f"飽和 pfb {ps} / ddc {ds}")
        rdy0, stall = wn.rd(WN.R_WS_RDY0), wn.rd(WN.R_WS_STALL)
        ok = not err
        rows.append((step, w, if_g, k, c - 128 * k, ns, shift, int(ok), nbad, floor, f_start, flags, rdy0, stall))
        line = (f"[{step + 1}/{len(plan)}] W {w:5.0f}・IF {if_g:9.4f}（k {k:2d}・d {c - 128 * k:+7.3f}）SHIFT {shift:2d} {tag:4s}: "
                f"{'OK' if ok else 'NG'}・床 {floor:6.0f}・WRST 後の FLAGS {f_start:#04x}・tready まで {rdy0}・待たされた {stall}")
        log(line + ("" if ok else "\n      " + " / ".join(err)))
        if not ok:
            fails.append((step, err))
    n = len(rows)
    npass = sum(r[7] for r in rows)
    log(f"W-8: {npass} / {n} 回が W-0・W-G とも通過（Overlay の読み込み直し {a.reloads} 回）・かかった時間 {time.time() - t0:.0f} s")
    if rows:
        r = np.array(rows, dtype=float)
        for w in WIDTHS:
            sel = r[:, 1] == w
            if sel.any():
                log(f"  W {w:3d}: {int(sel.sum())} 回・通過 {int(r[sel, 7].sum())}・待たされた（中央値）{np.median(r[sel, 13]):.0f} クロック・"
                    f"tready まで（最大）{r[sel, 12].max():.0f}")
        if a.out:
            np.savez(a.out + ".wrst.npz", rows=r, cols="step, W, IF, k, d, WNS, SHIFT, ok, nbad, floor, flags_start, flags, rdy0, stall")
            log(f"書いた: {a.out}.wrst.npz")
    log("RESULT " + ("OK" if n and npass == n else "NG"))
    return 0 if n and npass == n else 1


if __name__ == "__main__":
    sys.exit(main())
