#!/usr/bin/env python3
"""proj014 — win_core を AXI 越しに動かした sim の照合（make sim-top）。

  python3 check_top.py gen DIR NS              x.hex を作る（雑音 ＋ 窓の中の CW 2 本 ＋ 窓の外の強い CW ＋ 満杯の区間）
  python3 check_top.py check DIR NS NACC NDUMP SHIFT

判定:
  0. ddc_core の出力 z が、x → pfb_fixed → ddc_fixed（model/win_fixed.py）と bit 単位で一致（入力の途切れ・止めを挟んでも）
  1〜4. sim/check_wspec.py の 4 層（積分・FFT のモデル・帳簿・FLAGS）を、AXI で読んだダンプ・スナップショット・レジスタに
  5. 窓の設定が取り込まれた（WCUR）・飽和なし
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_wspec as CW  # noqa: E402
import win_fixed as F  # noqa: E402
import win_model as WM  # noqa: E402

K = 5
D_MHZ = -37.81234567


def nsamp(ns):
    # RUN（fin ≧ 3）→ N_ACC 2 × 3 ダンプ ＋ 途中の 2 フレーム ＋ 余裕。1 フレーム = 4096 z = 4096·2^NS y = 4096·2^(NS−1) ビート
    frames = 14
    return 16 * 4096 * 2 ** (ns - 1) * frames


def gen(d, ns):
    n = nsamp(ns)
    rng = np.random.default_rng(18)
    t = np.arange(n)
    c = K * 128 + D_MHZ                                   # 窓の中心（f の側、MHz）
    W = WM.R0 / 2 ** ns
    x = rng.normal(0, 1500, n)
    x += 2000 * np.cos(2 * np.pi * (c + 0.20 * W) / 4096 * t) + 300 * np.cos(2 * np.pi * (c - 0.31 * W) / 4096 * t)
    x += 6000 * np.cos(2 * np.pi * (c + 0.7 * W + 3.0) / 4096 * t)    # 窓の外の強い線
    x[200000:200300] = 8191 * np.sign(rng.normal(size=300))
    x = np.clip(np.round(x), -8192, 8191).astype(np.int64)
    w16 = ((x << 2) | rng.integers(0, 4, n)) & 0xFFFF
    np.save(os.path.join(d, "x14.npy"), x)
    with open(os.path.join(d, "x.hex"), "w") as fp:
        fp.write("\n".join(f"{v:04x}" for v in w16) + "\n")
    print(f"入力: {n} サンプル（NS {ns}、{n // 16} ビート）→ {d}/x.hex")
    print(F.nco_step(D_MHZ)[0])


def check(d, ns, nacc, ndump, shift):
    x = np.load(os.path.join(d, "x14.npy"))
    run = os.path.join(d, f"ns{ns}")
    des = F.prepare(WM.design(60.0, WM.RIPPLE_PP))
    cfg = dict(F.DEFAULT)
    cnt = {}
    yr, yi = F.pfb_fixed(x, K, des, cfg, cnt)
    ne = 2 * (len(yr) // 2)
    zr, zi = F.ddc_fixed(yr[:ne], yi[:ne], F.nco_step(D_MHZ)[0], ns, des, cfg, cnt)
    got = np.loadtxt(os.path.join(run, "z.txt"), dtype=np.int64, ndmin=2)
    n = len(got)
    neq = int(np.count_nonzero((got[:, 0] != zr[:n]) | (got[:, 1] != zi[:n])))
    ok = neq == 0 and n <= len(zr) and not cnt
    print(("  OK  " if ok else "  NG  ") + f"0: z が模型と bit 単位で一致（{n} 個 / 模型 {len(zr)}、不一致 {neq}、模型の飽和 {cnt or 0}）")
    np.save(os.path.join(run, "..", f"z_ns{ns}.npy"), np.stack([got[:, 0], got[:, 1]]))
    meta = dict(l.split(" ", 1) for l in open(os.path.join(run, "meta.txt")).read().splitlines())
    wcur = int(meta["wcur"])
    ok5 = (wcur & 31) == K and ((wcur >> 8) & 15) == ns and int(meta["satflags"]) == 0
    print(("  OK  " if ok5 else "  NG  ") + f"5: WCUR = {wcur:#x}（k {K}・NS {ns}）、飽和の印 {meta['satflags']}")
    # proj015: ID・WNS の 4 bit と範囲外の丸め・PARAM の G（[15:12]）
    ok6 = int(meta["id"]) == 0x0015_0300
    for i, (wr, ns_x, g_x) in enumerate([(7, 7, 5), (8, 8, 5), (9, 1, 4), (0, 1, 4)]):
        wc, pa = [int(v) for v in meta[f"regchk{i}"].split()]
        got_ns, got_pns, got_g = (wc >> 8) & 15, (pa >> 8) & 15, (pa >> 12) & 15
        ok = got_ns == ns_x and got_pns == ns_x and got_g == g_x
        print(("  OK  " if ok else "  NG  ") + f"6: WNS {wr} を書いて WRST → WCUR の NS {got_ns}・PARAM の NS {got_pns}・G {got_g}（期待 {ns_x}・{ns_x}・{g_x}）")
        ok6 = ok6 and ok
    print(("  OK  " if int(meta["id"]) == 0x0015_0300 else "  NG  ") + f"6: ID = {int(meta['id']):#010x}（期待 0x00150300）")
    ok5 = ok5 and ok6
    # check_wspec は DIR の 1 つ上の z.npy を読むので、一時にその名前で置く
    zpath = os.path.join(d, "z.npy")
    np.save(zpath, np.stack([got[:, 0], got[:, 1]]))
    rc = CW.check(run, nacc, ndump, shift, False)
    allok = ok and ok5 and rc == 0
    print("総合: 結果: 全部通過" if allok else "総合: 結果: 失敗")
    return 0 if allok else 1


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        gen(sys.argv[2], int(sys.argv[3]))
    else:
        sys.exit(check(sys.argv[2], *[int(v) for v in sys.argv[3:7]]))
