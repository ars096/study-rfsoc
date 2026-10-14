#!/usr/bin/env python3
"""proj015 — pfb_core の 4 窓の sim の照合（make sim-pfbm）。

  python3 check_pfbm.py gen DIR            入力（雑音 + CW 2 本 + 満杯の区間、4096 ビート）
  python3 check_pfbm.py check DIR QW       DIR/y_w*.txt（tb_pfbm.v の出力）を窓ごとに照合（入力は DIR/../x14.npy）

窓 w の区切りごとに、始まりのビート q_s（「# S」の q_start を QW bit の巻き戻りから戻す: 「# R」の時点以降で最小の、合同な q ≧ 5）から
m_s = 2·q_s − 10 を出し、x[8·m_s:] を model/win_fixed.py の pfb_fixed（k_w）に通したものとフレームの順に bit 単位で比べる。
  - 最後の区切り: フレームの数が模型と同じ
  - 打ち直しで切れた区切り（「# X」）: 打ち直しの時点までのフレームの数（2·(X − q_s)）から、途中のパイプラインのぶん（≦ 20 ビート = 40 フレーム ＋ 2。pfb_core の LAT）だけ少なくてよい
判定: 全部の窓・全部の区切りで値が一致・数が合う・飽和 0。
陽性対照（SIM_PFBM_POSCTL=1、RTL の (−j)^(k·m') の偶奇を窓の始まりで揃えない）: どこかの区切りが一致しないこと。
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import win_fixed as F  # noqa: E402
import win_model as WM  # noqa: E402

NSAMP = 16 * 4096
KS = [5, 0, 16, 9]            # tb_pfbm.v の kv と同じ


def gen(d):
    rng = np.random.default_rng(17)
    t = np.arange(NSAMP)
    x = rng.normal(0, 600, NSAMP)
    x += 3000 * np.cos(2 * np.pi * 700.3 / 4096 * t) + 1500 * np.cos(2 * np.pi * 1333.7 / 4096 * t + 1)
    x[20000:20100] = 8191 * np.sign(rng.normal(size=100))
    x = np.clip(np.round(x), -8192, 8191).astype(np.int64)
    w16 = ((x << 2) | rng.integers(0, 4, NSAMP)) & 0xFFFF
    np.save(os.path.join(d, "x14.npy"), x)
    with open(os.path.join(d, "x.hex"), "w") as fp:
        fp.write("\n".join(f"{v:04x}" for v in w16) + "\n")
    print(f"入力: {NSAMP} サンプル → {d}/x.hex")


def segments(path):
    segs, cur = [], None
    for line in open(path):
        if line.startswith("# R"):
            cur = {"R": int(line.split()[2]), "S": None, "X": None, "y": []}
            segs.append(cur)
        elif line.startswith("# S"):
            cur["S"] = int(line.split()[2])
        elif line.startswith("# X"):
            cur["X"] = int(line.split()[2])
        elif line.strip():
            a, b = line.split()
            cur["y"].append((int(a), int(b)))
    return segs


def check(d, qw, posctl):
    x = np.load(os.path.join(d, "..", "x14.npy"))          # gen は DIR の 1 つ上（変種で共有）
    des = F.prepare(WM.design(60.0, WM.RIPPLE_PP))
    cfg = dict(F.DEFAULT)
    bad = 0
    for w, k in enumerate(KS):
        for i, sg in enumerate(segments(os.path.join(d, f"y_w{w}.txt"))):
            if sg["S"] is None:
                print(f"  窓 {w}（k {k}）区切り {i}: フレームが 1 つも出ていない → NG"); bad += 1; continue
            mod = 1 << qw
            q0 = max(sg["R"], 5)
            qs = q0 + ((sg["S"] - q0) % mod)
            ms = 2 * qs - 10
            cnt = {}
            yr, yi = F.pfb_fixed(x[8 * ms:], k, des, cfg, cnt)
            got = np.array(sg["y"], dtype=np.int64).reshape(-1, 2)
            n = min(len(got), len(yr))
            neq = int(np.count_nonzero((got[:n, 0] != yr[:n]) | (got[:n, 1] != yi[:n])))
            if sg["X"] is None:
                ok_len = len(got) == len(yr)
                want = f"{len(yr)}"
            else:
                full = 2 * (sg["X"] - qs)
                ok_len = full - 2 * 20 - 2 <= len(got) <= full + 1      # w_rst を上げた時にパイプラインの中にいた ≦ 20 ビート（40 フレーム。rev2 の LAT）は消える
                want = f"{full - 42}〜{full + 1}（打ち直し {sg['X']} で切れる）"
            st = "OK" if (neq == 0 and ok_len and not cnt) else "NG"
            print(f"  窓 {w}（k {k:2d}）区切り {i}: R {sg['R']} → q_s {qs}（m_s {ms}）、フレーム RTL {len(got)} / 期待 {want}、"
                  f"不一致 {neq}、模型の飽和 {cnt or 0} → {st}")
            bad += st == "NG"
    if posctl:
        ok = bad > 0
        print(f"陽性対照: {bad} 件が NG → " + ("結果: 全部通過" if ok else "結果: 失敗（照合が効いていない）"))
        return 0 if ok else 1
    print("結果: 全部通過" if bad == 0 else f"結果: 失敗 {bad} 件")
    return 1 if bad else 0


if __name__ == "__main__":
    if sys.argv[1] == "gen":
        gen(sys.argv[2])
    else:
        sys.exit(check(sys.argv[2], int(sys.argv[3]), os.environ.get("SIM_PFBM_POSCTL", "0") == "1"))
