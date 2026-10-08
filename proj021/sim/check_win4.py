#!/usr/bin/env python3
"""proj015 — win_core（1 ADC × 4 窓）を AXI 越しに動かした sim の照合（make sim-win4）。

  python3 check_win4.py gen DIR       x.hex（雑音 ＋ 各窓の中の CW ＋ 満杯の区間）と cfg.txt（窓ごとの k・WDPHI・WNS・WRST を打つビート）
  python3 check_win4.py check DIR

判定:
  0. 窓ごとに、z が x[8·m_s:] → pfb_fixed → ddc_fixed（model/win_fixed.py）と bit 単位で一致。m_s = 2·WSTART − 10
     （WRST を入力の途中で打った窓は、共有の PFB の途中から始まる。z の数は模型の −2〜0）
  1. 窓 1 の SNAP_SEL のスナップショット = 窓 1 の z のフレーム SNAP_F（4096 語）、DUMP_F0 = SNAP_F。選ばれていない窓 0 の範囲は 0
  2. レジスタ: ADC の共通の ID・NW・SNAP_SEL、窓ごとの ID・WIDX・WCUR、FLAGS（[4] 待たされた を除いて 0）・DDC_OVR 0、無い窓は DEAD_BEEF
  3. ADC の total power: リングの個ごとの Σx² が入力と一致、TP_RUN の後は TP_N = 8 フレームで F0 + 8n に揃う
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import win_fixed as F  # noqa: E402
import win_model as WM  # noqa: E402
import pfb4  # noqa: E402

NSAMP = 16 * 65536
# 窓: (k, d [MHz], NS, WRST を打つビート（0 = 入力の前）)
WINS = [(8, 22.0, 3, 3000), (9, -56.0, 1, 1000), (16, -52.0, 6, 20000), (0, 6.0, 8, 0)]


def gen(d):
    rng = np.random.default_rng(19)
    t = np.arange(NSAMP)
    x = rng.normal(0, 1200, NSAMP)
    for k, dd, ns, _ in WINS:
        c = 128 * k + dd
        W = WM.R0 / 2 ** ns
        x += 1500 * np.cos(2 * np.pi * (c + 0.2 * W) / 4096 * t + k)
    x[300000:300300] = 8191 * np.sign(rng.normal(size=300))
    x = np.clip(np.round(x), -8192, 8191).astype(np.int64)
    w16 = ((x << 2) | rng.integers(0, 4, NSAMP)) & 0xFFFF
    np.save(os.path.join(d, "x14.npy"), x)
    with open(os.path.join(d, "x.hex"), "w") as fp:
        fp.write("\n".join(f"{v:04x}" for v in w16) + "\n")
    with open(os.path.join(d, "cfg.txt"), "w") as fp:
        for k, dd, ns, b in WINS:
            fp.write(f"{k} {F.nco_step(dd)[0]} {ns} {b}\n")
    print(f"入力: {NSAMP} サンプル → {d}/x.hex、窓の設定 → {d}/cfg.txt")


def load_z(path):
    """z の並び。tb は窓の WRST ごとに「# W」を書く（リセットの後は既定の設定で回っている）→ 最後の「# W」の後だけ"""
    lines = open(path).read().splitlines()
    last = max((i for i, l in enumerate(lines) if l.startswith("# W")), default=-1)
    rows = [l.split() for l in lines[last + 1:] if l.strip() and not l.startswith("#")]
    return np.array(rows, dtype=np.int64).reshape(-1, 2)


def judge(ok, msg):
    print(("  OK  " if ok else "  NG  ") + msg)
    return ok


def check(d):
    x = np.load(os.path.join(d, "x14.npy"))
    meta = dict(l.split(" ", 1) for l in open(os.path.join(d, "meta.txt")).read().splitlines())
    mi = {k: int(v) for k, v in meta.items()}
    des = F.prepare(WM.design(60.0, WM.RIPPLE_PP))
    cfg = dict(F.DEFAULT)
    allok = True
    zs = {}
    for g, (k, dd, ns, b) in enumerate(WINS):
        qs = mi[f"wstart{g}"]
        ms = 2 * qs - 10
        cnt = {}
        yr, yi = F.pfb_fixed(x[8 * ms:], k, des, cfg, cnt)
        ne = 2 * (len(yr) // 2)
        zr, zi = F.ddc_fixed(yr[:ne], yi[:ne], F.nco_step(dd)[0], ns, des, cfg, cnt)
        got = load_z(os.path.join(d, f"z_w{g}.txt"))
        n = len(got)
        neq = int(np.count_nonzero((got[:, 0] != zr[:n]) | (got[:, 1] != zi[:n]))) if n <= len(zr) else -1
        wb = meta.get(f"wrst{g}_b", "入力の前").strip()
        allok &= judge(neq == 0 and len(zr) - 2 <= n <= len(zr) and not cnt,
                       f"0: 窓 {g}（k {k}・d {dd:+.1f}・NS {ns}、WRST {wb}）: WSTART {qs}（m_s {ms}）、z {n} 個 / 模型 {len(zr)}、"
                       f"不一致 {neq}、模型の飽和 {cnt or 0}")
        zs[g] = got
        wc = mi[f"wcur{g}"]
        allok &= judge((wc & 31) == k and ((wc >> 8) & 15) == ns, f"2: 窓 {g} の WCUR {wc:#x}")
        fl = mi[f"flags{g}"]
        allok &= judge((fl & ~0x10) == 0 and mi[f"ovr{g}"] == 0, f"2: 窓 {g} の FLAGS {fl:#x}（[4] を除いて 0）・DDC_OVR {mi[f'ovr{g}']}")
        allok &= judge(mi[f"id{g}"] == 0x0020_0100 and mi[f"widx{g}"] == g, f"2: 窓 {g} の ID {mi[f'id{g}']:#010x}・WIDX {mi[f'widx{g}']}")
    snap = np.loadtxt(os.path.join(d, "snap.txt"), dtype=np.int64, ndmin=2)
    f = mi["snap_f"]
    # proj020: スナップショットは PFB の出口（FFT の入力）。z のフレーム 0 = WSTART の後の最初の z（wspec の rst と同じ原点）
    pr, pi = pfb4.pfb4_fixed(zs[1][:, 0], zs[1][:, 1])
    ref = np.stack([pr, pi], axis=1)[4096 * f:4096 * f + 4096]
    allok &= judge(mi["dump_f0"] == f and len(ref) == 4096 and np.array_equal(snap, ref),
                   f"1: 窓 1 のスナップショット（SNAP_SEL 1）= PFB の模型の出力フレーム {f}（DUMP_F0 {mi['dump_f0']}、不一致 "
                   f"{int(np.count_nonzero(snap != ref)) if len(ref) == 4096 else '長さ違い'}）")
    allok &= judge(mi["snap_w0"] == 0 and mi["snap_w0i"] == 0, f"1: 選ばれていない窓 0 のスナップショットの範囲 = {mi['snap_w0']} / {mi['snap_w0i']}（0 のはず）")
    allok &= judge(mi["id_a"] == 0x0020_A100 and mi["nw"] == 4 and mi["snap_sel"] == 1,
                   f"2: ADC の共通 ID {mi['id_a']:#010x}・NW {mi['nw']}・SNAP_SEL {mi['snap_sel']}")
    allok &= judge(mi["bad_sel"] == 0xDEADBEEF, f"2: 無い窓（0xA0000）の読み = {mi['bad_sel']:#010x}")
    # 3. total power（ADC の共通、tp_core）: リングの個ごとに Σx²（x = 14 bit）を x14 から数えて比べる。RUN の後は F0 + 8n に揃う
    tp = np.loadtxt(os.path.join(d, "tp.txt"), dtype=np.int64, ndmin=2)
    wp, f0r = mi["tp_wp"], mi["tp_f0"]
    nbad, nrun, lines = 0, 0, []
    for i in range(min(wp, 512)):
        lo, hi, f0, w3 = [int(v) & 0xFFFFFFFF for v in tp[i]]
        tot = lo + (hi << 32)
        n, fl = w3 & 0xFFFFFF, (w3 >> 24) & 0xFF
        ref = int(np.sum(x[8192 * f0:8192 * (f0 + n)] ** 2))
        ok = tot == ref and 8192 * (f0 + n) <= len(x)
        if f0 >= f0r:
            ok = ok and n == 8 and (f0 - f0r) % 8 == 0
            nrun += 1
        nbad += not ok
        if not ok or len(lines) < 3:
            lines.append(f"個 {i}: F {f0}・{n} フレーム・FLAGS {fl:#x}・和 {tot}（x から {ref}）")
    allok &= judge(nbad == 0 and nrun >= 8 and mi["tp_neff"] == 8,
                   f"3: total power: 個 {min(wp, 512)}（RUN の F0 {f0r} から {nrun} 個）、合わない個 {nbad}、TP_NEFF {mi['tp_neff']}")
    for l in lines[:6]:
        print("        " + l)
    print("総合: 結果: 全部通過" if allok else "総合: 結果: 失敗")
    return 0 if allok else 1


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        gen(sys.argv[2])
    else:
        sys.exit(check(sys.argv[2]))
