#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""spec_core のシミュレーションの入力を作り、結果を判定する。

    python3 sim/check.py gen   OUT      # OUT/stim.hex を作る
    python3 sim/check.py check OUT SHIFT

判定は 3 層で、**それぞれ別のものを確かめる**:

  A. bit 単位: レーン FFT の出力（lanes.txt）を、自作部分の整数模型（model_frame）に通した結果が、
     ダンプのスペクトルと **1 bit も違わない**こと。ひねり係数・16 点 DFT・丸め・飽和・電力・
     積分・面の切り替えを確かめる
  B. 浮動小数: スナップショット（ダンプと同じフレームの生サンプル）を numpy で 8192 点 FFT した
     電力と、ダンプが一致すること（丸めの分だけ違ってよい）。**分解の式そのもの**
     （どのレーンにどのサンプルが入り、どの ch がどこに出るか）を、模型を介さずに確かめる
  C. 帳簿: FLAGS = 0、SNAP_F = DUMP_F0、DUMP_N、DUMP_K、SEQ の進み方、飽和の数

A だけでは模型と RTL が同じ誤解をしていても通る。B はその保険。
"""
import sys
import os
import math
import numpy as np

N, P, M = 8192, 16, 512
QW = 18
QMAX, QMIN = (1 << (QW - 1)) - 1, -(1 << (QW - 1))


# ---------------------------------------------------------------- 入力
def gen(out):
    rng = np.random.default_rng(10)
    nf = 8
    n = np.arange(nf * N)
    x = rng.normal(0.0, 200.0, nf * N)
    x += 2000.0 * np.cos(2 * np.pi * 1000.3 * n / N + 0.4)    # ビンの間の強い線
    x += 500.0 * np.cos(2 * np.pi * 3000.0 * n / N)            # ビンに乗る線
    x += 3000.0 * np.cos(2 * np.pi * 4095.0 * n / N + 1.0)     # 最後の ch（k2 = 7 の端）
    x14 = np.clip(np.round(x), -8192, 8191).astype(np.int64)
    x16 = (x14 * 4) & 0xFFFF
    with open(os.path.join(out, "stim.hex"), "w") as f:
        for m in range(nf * M):
            w = 0
            for p in range(P):
                w |= int(x16[16 * m + p]) << (16 * p)
            f.write("%064x\n" % w)
    np.save(os.path.join(out, "stim14.npy"), x14)
    print("wrote %s/stim.hex（%d フレーム）" % (out, nf))


# ---------------------------------------------------------------- 整数模型
def tw(p, k1):  # tools/gen_tw_rom.py と同じ式
    a = 2.0 * math.pi * p * k1 / N
    return round(65536 * math.cos(a)), round(-65536 * math.sin(a))


TW = np.array([[tw(p, k1) for k1 in range(M)] for p in range(P)], dtype=object)
W16 = {0: (65536, 0), 1: (60547, -25080), 2: (46341, -46341), 3: (25080, -60547),
       4: (0, -65536), 6: (-46341, -46341), 9: (-60547, 25080)}


def cmul(ar, ai, wr, wi, ow):
    yr = (ar * wr - ai * wi + (1 << 15)) >> 16
    yi = (ar * wi + ai * wr + (1 << 15)) >> 16
    lim = 1 << (ow - 1)
    assert -lim <= yr < lim and -lim <= yi < lim, "cmul の出力が %d bit に収まらない" % ow
    return yr, yi


def model_frame(Y, shift):
    """Y[p][k1] = (re, im)（レーン FFT の出力）→ 電力[4096]、飽和数"""
    pw = [0] * 4096
    nsat = 0
    for k1 in range(M):
        V = [cmul(Y[p][k1][0], Y[p][k1][1], TW[p][k1][0], TW[p][k1][1], 25) for p in range(P)]
        # 段 1
        U = {}
        for b in range(4):
            x = [V[4 * a + b] for a in range(4)]
            U[b, 0] = (x[0][0] + x[1][0] + x[2][0] + x[3][0], x[0][1] + x[1][1] + x[2][1] + x[3][1])
            U[b, 1] = (x[0][0] + x[1][1] - x[2][0] - x[3][1], x[0][1] - x[1][0] - x[2][1] + x[3][0])
            U[b, 2] = (x[0][0] - x[1][0] + x[2][0] - x[3][0], x[0][1] - x[1][1] + x[2][1] - x[3][1])
            U[b, 3] = (x[0][0] - x[1][1] - x[2][0] + x[3][1], x[0][1] + x[1][0] - x[2][1] - x[3][0])
        # 段 2
        T = {}
        for b in range(4):
            for c in range(4):
                wr, wi = W16[b * c]
                T[b, c] = cmul(U[b, c][0], U[b, c][1], wr, wi, 27)
        # 段 3
        for c in range(4):
            y = [T[b, c] for b in range(4)]
            Z0 = (y[0][0] + y[1][0] + y[2][0] + y[3][0], y[0][1] + y[1][1] + y[2][1] + y[3][1])
            Z1 = (y[0][0] + y[1][1] - y[2][0] - y[3][1], y[0][1] - y[1][0] - y[2][1] + y[3][0])
            for k2, Z in ((c, Z0), (c + 4, Z1)):
                s = False
                q = []
                for v in Z:
                    t = v >> shift
                    if t > QMAX:
                        t, s = QMAX, True
                    elif t < QMIN:
                        t, s = QMIN, True
                    q.append(t)
                nsat += s
                pw[k1 + 512 * k2] = q[0] * q[0] + q[1] * q[1]
    return pw, nsat


# ---------------------------------------------------------------- 読み込み
def load_lanes(out):
    frames = {}
    with open(os.path.join(out, "lanes.txt")) as f:
        for line in f:
            v = [int(t) for t in line.split()]
            fr, k1 = v[0], v[1]
            Y = frames.setdefault(fr, [[None] * M for _ in range(P)])
            for p in range(P):
                Y[p][k1] = (v[2 + 2 * p], v[3 + 2 * p])
    return {fr: Y for fr, Y in frames.items() if all(Y[p][k] is not None for p in range(P) for k in range(M))}


REGS = {0x00: "ID", 0x04: "PARAM", 0x08: "CTRL", 0x0C: "N_ACC", 0x10: "N_DUMP", 0x14: "SHIFT",
        0x18: "FLAGS", 0x1C: "SEQ", 0x20: "FIN_LO", 0x24: "FIN_HI", 0x28: "FOUT_LO", 0x2C: "FOUT_HI",
        0x30: "DUMP_K", 0x34: "DUMP_N", 0x38: "DUMP_F0_LO", 0x3C: "DUMP_F0_HI", 0x40: "DUMP_SAT",
        0x44: "SNAP_F_LO", 0x48: "SNAP_F_HI", 0x4C: "BANK", 0x50: "RUN_F0_LO", 0x54: "RUN_F0_HI",
        0x58: "DIAG_TL", 0x5C: "DIAG_EV", 0x60: "DIAG_FS", 0x64: "DIAG_EVCNT", 0x68: "DIAG_FSCNT",
        0x6C: "BUILD", 0x70: "SRST_D", 0x74: "SRST_E", 0x78: "SRST_CNT"}


def load_dump(out, name):
    r, snap, spec, seq_after = {}, np.zeros(8192, np.int64), [0] * 4096, None
    with open(os.path.join(out, "dump_%s.txt" % name)) as f:
        for line in f:
            t = line.split()
            if t[0] == "reg":
                r[REGS[int(t[1])]] = int(t[2])
            elif t[0] == "snap":
                i, w = int(t[1]), int(t[2])
                lo, hi = w & 0xFFFF, (w >> 16) & 0xFFFF
                snap[2 * i] = lo - 65536 if lo >= 32768 else lo
                snap[2 * i + 1] = hi - 65536 if hi >= 32768 else hi
            elif t[0] == "spec":
                spec[int(t[1])] = (int(t[2]) << 32) | int(t[3])
            elif t[0] == "seq_after":
                seq_after = int(t[1])
            elif t[0] == "bdcheck":
                r["BDCHECK"] = (int(t[1]), int(t[2]))
    r["DUMP_F0"] = (r["DUMP_F0_HI"] << 32) | r["DUMP_F0_LO"]
    r["SNAP_F"] = (r["SNAP_F_HI"] << 32) | r["SNAP_F_LO"]
    return r, snap, spec, seq_after


# ---------------------------------------------------------------- 判定
def check(out, shift, skew=0):
    lanes = load_lanes(out)
    x14 = np.load(os.path.join(out, "stim14.npy"))
    nfail = 0

    def judge(ok, msg):
        nonlocal nfail
        print("  [%s] %s" % ("OK  " if ok else "FAIL", msg))
        if not ok:
            nfail += 1

    cache = {}

    def mf(fr):
        if fr not in cache:
            cache[fr] = model_frame(lanes[fr], shift)
        return cache[fr]

    for name, n_acc, want_k, snap_must in (("t1", 1, 0, True), ("t2", 3, 1, True), ("t3", 2, None, False),
                                           ("t4", 1, 0, True)):
        print("---- %s ----" % name)
        r, snap, spec, seq_after = load_dump(out, name)
        f0, n = r["DUMP_F0"], r["DUMP_N"]
        if "BDCHECK" in r:
            nchk, nmis = r["BDCHECK"]
            judge(nmis == 0, "裏口の読み出しが AXI4-Lite と %d か所中 %d か所で食い違う（0 が期待）" % (nchk, nmis))
        judge(r["ID"] == 0x00110400, "ID = %08x（期待 00110400: proj011 rev4、FFT_CFG は sim の既定 0）" % r["ID"])
        want_sr = 1 if name == "t4" else 0
        judge(r["SRST_CNT"] == want_sr and r["BUILD"] == 0,
              "SRST_CNT = %d（期待 %d）/ BUILD = %08x（sim の既定 0）" % (r["SRST_CNT"], want_sr, r["BUILD"]))
        if name == "t4":
            judge(r["SRST_D"] == 7 and r["SRST_E"] == 3, "SRST_D / SRST_E の読み返し = %d / %d" % (r["SRST_D"], r["SRST_E"]))
        base = 100000 * r["SRST_CNT"]         # lanes.txt のフレーム番号（tb が SRST の回ごとに分ける）
        want_flags = 0x20 if skew else 0
        judge(r["FLAGS"] == want_flags, "FLAGS = %02x（期待 %02x）" % (r["FLAGS"], want_flags))
        # 診断（rev3）。リセット以来の累積（tb は CTRL[9] を書かない）
        fin = (r["FIN_HI"] << 32) | r["FIN_LO"]
        tl, ev, fs = r["DIAG_TL"], r["DIAG_EV"], r["DIAG_FS"]
        judge(fs >> 31 == 1 and (fs >> 30) & 1 == 0 and (fs >> 29) & 1 == 0,
              "DIAG_FS: frame_started を見た・m_in が一定・レーン間で揃う（%08x、m_in %d）" % (fs, fs & 0x1FF))
        judge(abs(r["DIAG_FSCNT"] - fin) <= 2, "DIAG_FSCNT = %d（FIN %d と ±2 で一致）" % (r["DIAG_FSCNT"], fin))
        if skew:
            judge(tl == 0xFFFFFFFF, "DIAG_TL = %08x（期待 ffffffff: 16 レーンとも unexpected も missing も）" % tl)
            evm = ev & 0x1FF
            judge(ev >> 31 == 1 and evm in (0, (512 - skew) % 512),
                  "DIAG_EV: 事象あり・最初の m_in %d（期待 0 か %d）・種類 %d" % (evm, (512 - skew) % 512, (ev >> 29) & 3))
            judge(abs(r["DIAG_EVCNT"] - 2 * fin) <= 4,
                  "DIAG_EVCNT = %d（期待 ≒ 2 × FIN = %d: 1 フレームに unexpected と missing が 1 回ずつ）" % (r["DIAG_EVCNT"], 2 * fin))
        else:
            judge(tl == 0 and ev >> 31 == 0 and r["DIAG_EVCNT"] == 0,
                  "DIAG_TL / DIAG_EV / DIAG_EVCNT が 0（%08x / %08x / %d）" % (tl, ev, r["DIAG_EVCNT"]))
        judge(n == n_acc, "DUMP_N = %d（期待 %d）" % (n, n_acc))
        if want_k is not None:
            judge(r["DUMP_K"] == want_k, "DUMP_K = %d（期待 %d）" % (r["DUMP_K"], want_k))
        judge(seq_after == r["SEQ"], "読み出しのあいだ SEQ が動かない（%d → %d）" % (r["SEQ"], seq_after))
        judge(r["CTRL"] & 0x3 == 0, "終わった後は積分中でも開始待ちでもない（CTRL = %x）" % r["CTRL"])

        # A. bit 単位
        need = list(range(base + f0, base + f0 + n))
        missing = [fr for fr in need if fr not in lanes]
        if missing:
            judge(False, "lanes.txt にフレーム %s が無い" % missing)
            continue
        want = [0] * 4096
        wsat = 0
        for fr in need:
            pw, s = mf(fr)
            want = [a + b for a, b in zip(want, pw)]
            wsat += s
        nbad = sum(1 for a, b in zip(want, spec) if a != b)
        judge(nbad == 0, "A: 模型とダンプが bit 単位で一致（不一致 %d ch / 4096、フレーム %d〜%d）"
              % (nbad, f0, f0 + n - 1))
        judge(r["DUMP_SAT"] == wsat, "A: 飽和の数 %d（模型 %d）" % (r["DUMP_SAT"], wsat))

        # C. スナップショットが同じフレームか
        same = r["SNAP_F"] == f0
        if snap_must:
            judge(same, "C: SNAP_F = %d / DUMP_F0 = %d" % (r["SNAP_F"], f0))
        else:
            print("  [info] SNAP_F = %d / DUMP_F0 = %d（連続運転では次の予約で上書きされうる。"
                  "一致しないことを読み出しで検出できる）" % (r["SNAP_F"], f0))
        if not same:
            continue

        # スナップショットは刺激のどこかと一致するか（レーンの並びの確認）
        s14 = snap >> 2
        judge(np.all(snap & 3 == 0), "C: スナップショットの下位 2 bit が 0")
        L = len(x14)
        hit = [o for o in range(0, L, 16) if np.array_equal(np.take(x14, np.arange(o, o + N), mode="wrap"), s14)]
        judge(len(hit) == 1, "C: スナップショットが刺激の 1 か所と一致（位置 %s）" % hit)

        # レーン FFT の入力の並び: Y_p = FFT512(x[p::16])
        Y = lanes[base + f0]
        ref = [np.fft.fft(s14[p::16]) for p in range(P)]
        err = max(abs(Y[p][k][0] - ref[p][k].real) + abs(Y[p][k][1] - ref[p][k].imag)
                  for p in range(P) for k in range(M))
        judge(err < 2.0, "C: レーン p に x[16m + p] が入っている（最大誤差 %.2f）" % err)

        # B. 浮動小数（t1 だけ: 1 フレーム）
        if n == 1:
            X = np.fft.fft(s14.astype(float))[:4096]
            ref_pw = np.abs(X) ** 2 / 4.0 ** shift
            hw = np.array(spec, dtype=float)
            # 比べるのは振幅（√電力）で、単位は SHIFT 後の LSB。誤差は 2 種類ある:
            #   切り捨て（成分ごとに < 1 LSB。どの ch でも同じ）
            #   ひねり係数の 18 bit 丸め（相対 2^-17 程度）。**丸めの誤差はレーン FFT の出力 Y_p[k1] に
            #   比例して入り、Y_p[k1] には k1 を共有する 16 本の ch（k1 + 512·k2 とその鏡像）が全部乗っている。**
            #   したがって強い線の誤差は、同じ k1 を持つ弱い ch に出る（512 ch おきの −100 dBc 級のスプリアス）
            # 許容は「2 LSB ＋ 同じ k1 の組の最大振幅 × 3e-5」。
            # 経緯: 電力の相対誤差 1 % で比べて落ちた（弱い ch で量子化が効く）→ 振幅の差を固定 2 LSB で
            # 比べて SHIFT 4 で落ちた（振幅 1454 LSB の ch が 3.4 LSB ずれた。同じ k1 に 7.7e5 LSB の線がいる）
            ok_ch = ref_pw < 0.9 * QMAX ** 2          # 飽和した ch は除く（A が見ている）
            amp_all = np.sqrt(ref_pw)
            full = np.abs(np.fft.fft(s14.astype(float))) / 2.0 ** shift     # 8192 本（鏡像込み）
            grp = np.zeros(M)
            for kk in range(N):
                k1 = kk % M
                grp[k1] = max(grp[k1], full[kk])
            k1s = np.arange(4096) % M
            gmax = np.maximum(grp[k1s], grp[(M - k1s) % M])
            d = np.abs(np.sqrt(hw) - amp_all)[ok_ch]
            tol = (2.0 + 3e-5 * gmax)[ok_ch]
            worst = int(np.argmax(d / tol))
            judge(np.all(d < tol), "B: numpy の 8192 点 FFT と振幅で一致（%d ch、差/許容 の最大 %.2f"
                  "（差 %.2f LSB、同じ k1 の最大振幅 %.0f LSB）、平均の差 %.3f LSB）"
                  % (ok_ch.sum(), (d / tol)[worst], d[worst], gmax[ok_ch][worst], d.mean()))
            for k in (1000, 1001, 3000, 4095):
                print("       ch %4d  hw %.4e  numpy %.4e" % (k, hw[k], ref_pw[k]))


    print()
    print("結果: %s" % ("全部通過" if nfail == 0 else "%d 件失敗" % nfail))
    return nfail


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        gen(sys.argv[2])
    else:
        sys.exit(1 if check(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 0) else 0)
