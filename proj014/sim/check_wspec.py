#!/usr/bin/env python3
"""proj014 — wspec_core の単体の sim の照合（make sim-wspec）。

  python3 check_wspec.py gen DIR               z.txt を作る（複素の雑音 ＋ 飽和する強い線 ＋ 弱い線、28 フレーム）
  python3 check_wspec.py check DIR/変種 NACC NDUMP SHIFT [RDLY STALL]   （入力 z.npy は DIR に共通）

判定は 4 層（proj013 の check.py の型）:
  A. bit 単位: FFT のモデルの出力（fft.txt）を電力・積分の整数模型（sat18(Y >>> SHIFT) → re² + im² → 和）に通した値 = ダンプ（全 ch）。飽和の回数も
  B. FFT のモデル = numpy の複素 4096 点 FFT（z のフレーム f と FFT の出力のフレーム f が同じもの。差 ≦ 1 LSB）
  C. 帳簿: ダンプ k の f0 = RUN_F0 + k·N、n = N、SEQ が 1 ずつ、面が交互、スナップショットの番号 = f0 で中身 = z のフレーム f0
  D. FLAGS = 0（ただし [4] 待たされた は、FFT のモデルが待たせる変種（RDLY > 4096 か STALL > 0）でだけ立ち、立つこと）、
     0 ≦ fin − fout ≦ 3（溜め切ったフレームは順に FFT を通っている。途中の 2 フレーム ＋ 待たされて予約中の 1 面まで）
陽性対照 1（SIM_WSPEC_POSCTL=1、RTL の -DWSPEC_POSCTL: 初回のフレームでも読み値に足す）: A が落ちること
陽性対照 2（SIM_WSPEC_POSCTL=2、RTL の -DWSPEC_NOREADY: tready を見ない = rev1）: 待たせる変種で B が落ちること
"""
import os
import sys

import numpy as np

NF = 4096
NFRM = 28


def gen(d):
    rng = np.random.default_rng(17)
    n = np.arange(NF * NFRM)
    z = rng.normal(0, 500, NF * NFRM) + 1j * rng.normal(0, 500, NF * NFRM)
    z += 30000 * np.exp(2j * np.pi * 1000 * n / NF)            # ch 1000: SHIFT 4 で飽和する
    z += 300 * np.exp(2j * np.pi * (3000.37) * n / NF + 0.3)    # ch の間に落ちる弱い線
    zr = np.clip(np.round(z.real), -131072, 131071).astype(np.int64)
    zi = np.clip(np.round(z.imag), -131072, 131071).astype(np.int64)
    np.save(os.path.join(d, "z.npy"), np.stack([zr, zi]))
    with open(os.path.join(d, "z.txt"), "w") as fp:
        fp.write("\n".join(f"{a} {b}" for a, b in zip(zr, zi)) + "\n")
    print(f"入力: {NFRM} フレーム → {d}/z.txt")


def sat18(y, sh):
    t = y >> sh
    s = (t > 131071) | (t < -131072)
    return np.clip(t, -131072, 131071), s


def check(d, nacc, ndump, shift, posctl, rdly=5, stall=0):
    z = np.load(os.path.join(os.path.dirname(os.path.normpath(d)), "z.npy"))   # 入力は変種の 1 つ上の DIR に共通
    zc = z[0] + 1j * z[1]
    fft = np.loadtxt(os.path.join(d, "fft.txt"), dtype=np.int64, ndmin=2)
    meta = dict(l.split(" ", 1) for l in open(os.path.join(d, "meta.txt")).read().splitlines())
    run_f0 = int(meta["run_f0"])
    flags = int(meta["flags"])
    fin, fout = [int(v) for v in meta["fin"].replace("fout", "").split()]
    st_cnt = int(meta.get("stall", "0"))
    rdy0 = int(meta.get("rdy0", "0"))
    exp_wait = rdly > NF or stall > 0
    ok = True

    def judge(c, msg):
        nonlocal ok
        print(("  OK  " if c else "  NG  ") + msg)
        ok &= bool(c)

    nfo = len(fft) // NF
    fft = fft[: nfo * NF]
    judge(np.all(fft[:, 0] == np.tile(np.arange(NF), nfo)), f"FFT の出力 {nfo} フレーム、XK_INDEX が 0..4095 で並ぶ")
    Y = fft[:, 1].reshape(nfo, NF) + 1j * fft[:, 2].reshape(nfo, NF)
    # B
    nb = min(nfo, len(zc) // NF)
    ref = np.fft.fft(zc[: nb * NF].reshape(nb, NF), axis=1)
    db = np.max(np.abs(np.round(ref.real) - Y[:nb].real) + np.abs(np.round(ref.imag) - Y[:nb].imag))
    b_ok = db <= 2
    judge(b_ok, f"B: FFT のモデル = numpy（{nb} フレーム、差の最大 {db:.0f} LSB）")
    # ダンプを読む
    lines = open(os.path.join(d, "dumps.txt")).read().splitlines()
    snaps = np.loadtxt(os.path.join(d, "snaps.txt"), dtype=np.int64, ndmin=2)
    dumps = []
    i = 0
    while i < len(lines):
        h = [int(v) for v in lines[i][2:].split()]
        vals = np.array([int(v) for v in lines[i + 1: i + 1 + NF]], dtype=object)
        dumps.append((h, vals))
        i += 1 + NF
    judge(len(dumps) == ndump, f"ダンプ {len(dumps)} 個（NDUMP {ndump}）")
    seq0 = dumps[0][0][0]
    nbad_a = 0
    for j, (h, vals) in enumerate(dumps):
        seq, k, f0, n, satc, bank, snf = h
        judge(seq == seq0 + j and k == j and f0 == run_f0 + j * nacc and n == nacc and bank == (j & 1) and snf == f0,
              f"C: ダンプ {j}: SEQ {seq}・k {k}・f0 {f0}（予言 {run_f0 + j * nacc}）・n {n}・面 {bank}・スナップショット {snf}")
        # A
        acc = np.zeros(NF, dtype=object)
        sc = 0
        for f in range(f0, f0 + n):
            qr, sr = sat18(fft[f * NF:(f + 1) * NF, 1], shift)
            qi, si = sat18(fft[f * NF:(f + 1) * NF, 2], shift)
            acc += (qr.astype(object) ** 2 + qi.astype(object) ** 2)
            sc += int(np.count_nonzero(sr | si))
        nbad = int(sum(1 for a, b in zip(acc, vals) if a != b))
        nbad_a += nbad + (satc != sc)
        judge(nbad == 0 and satc == sc, f"A: ダンプ {j} の 4096 ch が模型と bit 単位で一致（不一致 {nbad}）、飽和 {satc}（模型 {sc}）")
        # スナップショット
        sn = snaps[j * NF:(j + 1) * NF]
        judge(np.array_equal(sn[:, 0], z[0][f0 * NF:(f0 + 1) * NF]) and np.array_equal(sn[:, 1], z[1][f0 * NF:(f0 + 1) * NF]),
              f"C: ダンプ {j} のスナップショット = z のフレーム {f0}")
    judge((flags & 0xEF) == 0 and bool(flags & 0x10) == exp_wait,
          f"D: FLAGS = {flags:02x}（[4] 待たされた: {'立つはず' if exp_wait else '立たないはず'}）")
    judge((st_cnt > 0) == exp_wait and rdy0 == rdly,
          f"D: 待たされた {st_cnt} クロック / tready まで {rdy0} クロック（モデルの RDLY {rdly}、STALL {stall}）")
    judge(0 <= fin - fout <= 3, f"D: fin {fin} − fout {fout} = {fin - fout}（溜めの読み出しと FFT の中の 2 フレーム ＋ 予約 1 面以内）")
    if posctl == 2:
        if not b_ok:
            print("陽性対照 2: B が落ちた → 結果: 全部通過")
            return 0
        print("陽性対照 2: B が落ちなかった → 結果: 失敗（tready の照合が効いていない）")
        return 1
    if posctl:
        if nbad_a:
            print("陽性対照: A が落ちた → 結果: 全部通過")
            return 0
        print("陽性対照: A が落ちなかった → 結果: 失敗（照合が効いていない）")
        return 1
    print("結果: 全部通過" if ok else "結果: 失敗")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        gen(sys.argv[2])
    else:
        ex = [int(v) for v in sys.argv[6:8]]
        sys.exit(check(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]),
                       int(os.environ.get("SIM_WSPEC_POSCTL", "0")), *ex))
