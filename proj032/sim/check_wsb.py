#!/usr/bin/env python3
"""check_wsb — tb_wsb の記録を、窓ごとの形（Fine の wspec_core を窓ごとに 1 組）の模型と照らす（E-4・M-1）。

  1. 入口: 窓ごとの標本 y → z = sat18(round(y / 2^bs))（bs = 0, 0, 1, 1, 2）→ フレーム r = 4096 個ずつ
  2. FFT の入口（fi）: 窓 w の札のついた枠が、PFB の式 sat18((Σ_t c[a + 4096 t]·z_{r−3+t}[a] + 2^15) >> 16) と r = 0, 1, 2, … の順に bit 単位で一致
  3. FFT の出口（fo）: 機関ごとに入口の枠と同じ順で、札の窓が同じ・値が倍精度の FFT と ±1 で一致（札の取り違えを見る）
  4. 積分: fo の値から q = sat18(Y >> sh)・p = q_re² + q_im²、F0 = g0·2^e・N = ng·2^e（e = G_L2 − 12 − NS）でダンプ k を積み、
     流れ（dmp）の (窓, k, ch) の値と bit 単位で一致。ダンプは k = 0 .. NDUMP − 1 の全部が出ている（sim の長さが足りる窓）
  python3 sim/check_wsb.py [記録のディレクトリ]
"""
import sys, os
import numpy as np

d = sys.argv[1] if len(sys.argv) > 1 else "."
HERE = os.path.dirname(os.path.abspath(__file__))
NF, NG, NDUMP = 4096, 1, 2
coef = np.array([int(l) for l in open(os.path.join(HERE, "..", "model", "pfb4_coef.txt")) if not l.startswith("#")], dtype=np.int64)
assert len(coef) == 4 * NF

run = open(os.path.join(d, "wsb_run.log")).read().split("\n")
h = run[0].split()
g0, GL2, E, CFG = int(h[1]), int(h[3]), int(h[5]), int(h[7])
win = {}
for l in run[1:]:
    if l.startswith("w "):
        _, w, act, ns, fl, sh = l.split()
        if int(act):
            win[int(w)] = dict(ns=int(ns), fl=int(fl), sh=int(sh))

def sat(a, b=18):
    return np.clip(a, -(1 << (b - 1)), (1 << (b - 1)) - 1)

# ---- 1. 入口 ----
ys = {w: [] for w in win}
for l in open(os.path.join(d, "wsb_in.log")):
    w, r, i = map(int, l.split())
    ys[w].append((r, i))
for w, v in win.items():
    a = np.array(ys[w], dtype=np.int64)
    bs = [0, 0, 0, 1, 1, 2][v["ns"]]
    rnd = (1 << (bs - 1)) if bs else 0
    z = sat((a + rnd) >> bs)
    nfr = len(z) // NF
    v["zr"] = z[:nfr * NF, 0].reshape(nfr, NF)
    v["zi"] = z[:nfr * NF, 1].reshape(nfr, NF)

def pfb(w, r):
    v = win[w]
    acc_r = np.zeros(NF, dtype=np.int64); acc_i = np.zeros(NF, dtype=np.int64)
    for t in range(4):
        f = r - 3 + t
        if f < 0:
            continue
        c = coef[t * NF:(t + 1) * NF]
        acc_r += c * v["zr"][f]; acc_i += c * v["zi"][f]
    return sat((acc_r + (1 << 15)) >> 16), sat((acc_i + (1 << 15)) >> 16)

def frames(fn, tag):
    """記録の行: 枠の頭「tag e w」、値「e re im」（機関の行は混ざって並ぶので、機関ごとに枠を組む）。順は機関ごとの順"""
    out = []  # (e, w, re/im[], 機関の中の順)
    cur = {}
    for l in open(os.path.join(d, fn)):
        p = l.split()
        if p[0] == tag:
            e = int(p[1])
            if e in cur: out.append(cur[e])
            cur[e] = [e, int(p[2]), []]
        else:
            cur[int(p[0])][2].append((int(p[1]), int(p[2])))
    out += cur.values()
    return [(e, w, np.array(x, dtype=np.int64)) for e, w, x in out if len(x) == NF]

fails = []
# ---- 2. FFT の入口 ----
fi = frames("wsb_fi.log", "F")
seen = {w: 0 for w in win}
for e, w, x in fi:
    if w not in win:
        fails.append(f"fi: 動いていない窓 {w}"); continue
    if win[w]["fl"] != e:
        fails.append(f"fi: 窓 {w} が機関 {e}（設定 {win[w]['fl']}）"); continue
    r = seen[w]; seen[w] += 1
    if r >= win[w]["zr"].shape[0]:
        fails.append(f"fi: 窓 {w} のフレーム {r} は入口に無い"); continue
    er, ei = pfb(w, r)
    nbad = int(np.sum((er != x[:, 0]) | (ei != x[:, 1])))
    if nbad:
        fails.append(f"fi: 窓 {w} フレーム {r}: 不一致 {nbad} / 4096")
for w in win:
    nin = win[w]["zr"].shape[0]
    print(f"窓 {w:2d}（NS {win[w]['ns']}・機関 {win[w]['fl']}）: 入口のフレーム {nin}・FFT に入った {seen[w]}")
    if seen[w] < nin - 2:
        fails.append(f"窓 {w}: FFT に入ったフレームが少ない（{seen[w]} / {nin}）")

# ---- 3. FFT の出口 ----
fo = frames("wsb_fo.log", "O")
X = {w: [] for w in win}
for e in range(E):
    ie = [(w, x) for ee, w, x in fi if ee == e]
    oe = [(w, x) for ee, w, x in fo if ee == e]
    for j, (w, x) in enumerate(oe):
        if j >= len(ie):
            fails.append(f"fo: 機関 {e} の出口の枠 {j} に入口が無い"); break
        wi, xi = ie[j]
        if wi != w:
            fails.append(f"fo: 機関 {e} 枠 {j}: 札の窓 {w}、入口は {wi}"); continue
        ref = np.fft.fft(xi[:, 0] + 1j * xi[:, 1])
        dev = max(np.max(np.abs(ref.real - x[:, 0])), np.max(np.abs(ref.imag - x[:, 1])))
        if dev > 1.01:
            fails.append(f"fo: 機関 {e} 枠 {j}（窓 {w}）: FFT との差 {dev:.2f}")
        X[w].append(x)

# ---- 4. 積分 ----
got = {}
for l in open(os.path.join(d, "wsb_dmp.log")):
    e, w, k, ch, v = map(int, l.split())
    key = (w, k)
    got.setdefault(key, {})
    if ch in got[key]:
        fails.append(f"dmp: 窓 {w} ダンプ {k} の ch {ch} が 2 回")
    got[key][ch] = v
ndone = 0
for w, v in win.items():
    e_w = max(0, GL2 - 12 - v["ns"])
    F0, N = g0 << e_w, NG << e_w
    for k in range(NDUMP):
        lo, hi = F0 + k * N, F0 + (k + 1) * N
        if hi >= len(X[w]):           # 次のフレーム（読み出し）まで出口に出ていない
            if (w, k) in got:
                fails.append(f"dmp: 窓 {w} ダンプ {k} は早すぎる")
            continue
        acc = np.zeros(NF, dtype=np.int64)
        for r in range(lo, hi):
            x = X[w][r]
            qr = sat(x[:, 0] >> v["sh"]); qi = sat(x[:, 1] >> v["sh"])
            acc += qr * qr + qi * qi
        g = got.get((w, k), {})
        if len(g) != NF:
            fails.append(f"dmp: 窓 {w} ダンプ {k}: ch {len(g)} / 4096"); continue
        nbad = sum(1 for c in range(NF) if g[c] != int(acc[c]))
        if nbad:
            fails.append(f"dmp: 窓 {w} ダンプ {k}: 不一致 {nbad} / 4096")
        ndone += 1
for (w, k) in got:
    if k >= NDUMP:
        fails.append(f"dmp: 窓 {w} に余分なダンプ {k}")
print(f"FFT の入口 {len(fi)} 枠・出口 {len(fo)} 枠・照らしたダンプ {ndone}（g0 {g0}・G_L2 {GL2}）")
for f in fails[:30]:
    print("  ×", f)
print("結果: " + ("全部通過" if not fails else f"不合格 {len(fails)} 件"))
sys.exit(1 if fails else 0)
