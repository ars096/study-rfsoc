#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj017 — SAM45-Fine の運転の形の判定（README の F-4・F-5）。4 ADC × NW 窓・積分 40.96 ms・ADC ごとの total power 1.024 ms

    sudo -E $(which python3) fine.py --clkin 0 --ref 10 --f4 --dumps 44000 --out runs/f4   # F-4: 40.96 ms × 44,000 回 ≒ 30.0 分
    sudo -E $(which python3) fine.py --clkin 0 --ref 10 --f4 --dumps 200 --offgrid 12345  # F-4 の陽性対照（下）
    sudo -E $(which python3) fine.py --clkin 0 --ref 10 --f5                                # F-5: ADC ごとの TP と全帯域の TP の比

時刻の格子（BITS.md・README の決定、2026-10-02）: G = 524,288 ビート（2.048 ms）。窓の WRST・RUN・TP_ARM の START_AT を G の倍数に置き、
窓の N_ACC は N·L = 40.96 ms（= 20 G）。wspec_core が F0 を格子に寄せるので、**8 窓のダンプの区切りがサンプルの時刻で揃う**（同じ k どうし）。
TP の区切りは 512 フレーム = 1.024 ms（= G / 2）で、ADC のフレーム（2 µs）の格子にしか切れないので、窓の区切りから一定の小さなずれ。

F-4 の約束:
  - 窓 4 × NW を格子の START_AT で一斉に WRST（WSTART が ADC の中で全窓同じ）、窓と TP 4 本を次の格子の START_AT で同時に始める
    （RUN_T = TP_RUN_T = START_AT + 1）
  - **8 窓の DUMP_T(k) − D(NS) − X(NS) が全ダンプで一致（±2 ビート）**（D・X は timebase の WIN_DELAY_BEATS・WIN_BOUNDARY_BEATS、
    sim-wdelay の値。X(NS) は幅の違う窓に残る一定の差: 窓のフレーム 0 = 最初の z が群遅延ぶん遅れて出るため。2026-10-03 に受け入れた）
  - TP の区切りの頭 − 窓の区切り（DUMP_T − D）が窓ごとに一定（符号つき、±131,072 に折り返す。値を出す）
  - `--recheck PREFIX.f4.npz` で記録から区切りの判定だけを回し直せる
  - 陽性対照 --offgrid B: 揃えた後に ADC_A の窓 0 だけを格子 ＋ B ビートで WRST し直す → その窓だけ一致しないはず
  - 窓は SEQ が 1 ずつ・DUMP_K が 1 ずつ進み、DUMP_T(k) − DUMP_T(0) = k·N·L（z の出方の揺れに ±16 ビートを許す。T-1 と同じ。
    proj016 の実機の 30 分は 0）、健全性なし、FLAGS は [4]（FFT IP に待たされた。rev2 から正常）以外 0
  - TP は ADC ごとに F0 の区切りから最後まで、区切りの番号が TP_N（512 フレーム = 1.024 ms）ずつ進む。読み落とし 0。
    FLAGS は [4] 振り切れ（proj017）以外 0。区切りの時刻 = ANCH_T + (f − ANCH_F)·512 ビート（TANCH で ADC ごとに残す）。区切り 262,144 ビート。
    **その式が測っている間ずっと成り立つこと**を、始めと終わりの TANCH の組が 512 ビート / フレームで結ばれること・GAP_CNT が
    増えていないことで確かめる（区切りの番号の連続だけでは、入力の途切れでフレームと T の対応がずれても通る）
  - 読み出しは AXI4-Lite（DMA なし）。1 周の読み出しの時間を測って出す
記録（--out PREFIX）: PREFIX.f4.npz に窓のメタ・ダンプの和・--keep ごとのスペクトル、TP の全部（ADC ごと）、錨
"""
import argparse
import os
import sys
import time

import numpy as np

import spectrometer as S
import timetest as T
import window as W
from timebase import BEATS_PER_SEC, WIN_BOUNDARY_BEATS, WIN_DELAY_BEATS, Timebase, TimebaseError, beats_to_ns

log = S.log
TPF_RUN, TPF_OVR = 2, 16
TP_N = 512                       # proj017: 1.024 ms（= G / 2）。proj016 までは 500 = 1 ms
TP_BEATS = TP_N * 512            # 262,144 ビート
G = T.G_BEATS


class WinTp:
    """win_core_i の ADC の共通にある tp_core を Spec と同じ口（rd・block・番地は tp_core の並び）で見せる"""

    def __init__(self, mmio):
        self.m = mmio

    def rd(self, a):
        return int(self.m.read(W.A_BASE + a)) & 0xFFFFFFFF

    def wr(self, a, v):
        self.m.write(W.A_BASE + a, int(v) & 0xFFFFFFFF)

    def block(self, base, nwords):
        i0 = (W.A_BASE + base) // 4
        return np.array(self.m.array[i0:i0 + nwords], dtype=np.uint32)


class NpTpReader(S.TpReader):
    """TpReader の記録を numpy の前置きの配列に（30 分 × 1.024 ms × 4 ADC を Python のリストで持たない）。FLAGS[4] は異常に数えない"""

    def __init__(self, sp, tp_n, run_f0, cap):
        super().__init__(sp, tp_n, run_f0)
        self.n = 0
        self.a_f0 = np.zeros(cap, np.int64); self.a_nfr = np.zeros(cap, np.int32)
        self.a_sum = np.zeros(cap, np.uint64); self.a_fl = np.zeros(cap, np.uint8)
        self.n_ovr = 0
        self.overflow = 0

    def _take(self, tsum, f0lo, fl, nfr):
        if not self.started:
            if (fl & TPF_RUN) and f0lo == (self.run_f0 & 0xFFFFFFFF):
                self.started = True
                f0 = self.run_f0
            else:
                self.pre += 1
                return
        else:
            exp = self.last_f0 + int(self.a_nfr[self.n - 1])
            f0 = exp + ((f0lo - (exp & 0xFFFFFFFF) + (1 << 31)) % (1 << 32)) - (1 << 31)
            if f0 != exp:
                self.bad_seq += 1
            if fl & ~TPF_OVR:
                self.bad_flag += 1
        if fl & TPF_OVR:
            self.n_ovr += 1
        if nfr != self.tp_n:
            self.bad_nfr += 1
        self.last_f0 = f0
        if self.n >= len(self.a_f0):
            self.overflow += 1
            return
        self.a_f0[self.n] = f0; self.a_nfr[self.n] = nfr; self.a_sum[self.n] = tsum; self.a_fl[self.n] = fl
        self.n += 1

    def arrays(self):
        k = self.n
        return self.a_f0[:k], self.a_nfr[:k], self.a_sum[:k], self.a_fl[:k]


def tanch(wm, timeout=0.5):
    """次の ADC のフレームの頭で (ANCH_F, ANCH_T) を残させて読む"""
    wm.write(W.A_BASE + T.RA_TP_CTRL, T.TP_ANCH)
    t_e = time.time() + timeout
    while not (int(wm.read(W.A_BASE + T.RA_ANCH_ST)) & 2):
        if time.time() > t_e:
            raise RuntimeError("TANCH が残らない")
        time.sleep(0.001)
    af = int(wm.read(W.A_BASE + T.RA_ANCH_F)) | (int(wm.read(W.A_BASE + T.RA_ANCH_F + 4)) << 32)
    at = int(wm.read(W.A_BASE + T.RA_ANCH_T)) | (int(wm.read(W.A_BASE + T.RA_ANCH_T + 4)) << 32)
    return af, at


def read_win(c, tries=5):
    """窓 c の閉じたダンプのメタとスペクトル（seqlock: SEQ → メタ・中身 → SEQ）"""
    wn = W.Win(c.m, base=c.base, win=c.widx or 0, lbase=getattr(c, "lbase", None))
    for _ in range(tries):
        m = c.meta()
        w = wn.block(W.SPEC_BASE, 2 * W.NFFT_W)
        m["flags"] = c.rd(W.R_FLAGS)
        if c.rd(W.R_SEQ) == m["seq"]:
            spec = w[0::2].astype(np.uint64) | (w[1::2].astype(np.uint64) << np.uint64(32))
            return m, spec
    raise RuntimeError(f"{c.name}: 読む間に毎回ダンプが閉じた（読み出しが積分に間に合わない）")


# ---------------------------------------------------------------- 窓の区切りの一致
def align_report(wmeta, ks_, ts_, tpi, offgrid=0, lim=2):
    """8 窓の区切りの実効の時刻（DUMP_T − D(NS)）を同じ k どうしで比べる。**幅の違う窓には NS ごとの一定の差 X(NS) が残る**
    （窓のフレーム 0 は WSTART の後の最初の z で、最初の z は群遅延ぶん遅れて出る。timebase.WIN_BOUNDARY_BEATS、sim-wdelay の値。
    2026-10-03 の F-4 で sim と 1 ビート以内で一致し、受け入れると決めた）。判定は DUMP_T − D(NS) − X(NS) が 8 窓で ±lim ビートの内。
    wmeta = [(名前, adc, ns)]、ks_・ts_ = 窓ごとの DUMP_K・DUMP_T、tpi = [(ラベル, TP の最初の区切りのフレーム番号, ANCH_F, ANCH_T)]。戻り値: NG の数"""
    bad = 0
    nw_all = len(wmeta)
    vk = []
    for (name, adc, ns), k, t in zip(wmeta, ks_, ts_):
        vk.append(dict(zip(k.tolist(), (t - int(round(WIN_DELAY_BEATS[ns]))).tolist())))
    ks = sorted(set.intersection(*[set(d.keys()) for d in vk]))
    if not ks:
        log("  NG: 全窓に共通のダンプの番号が無い")
        return 1
    mat = np.array([[vk[j][k_] for k_ in ks] for j in range(nw_all)], np.int64)
    xs = np.array([WIN_BOUNDARY_BEATS[ns] for (_, _, ns) in wmeta])
    raw = mat - np.median(mat, axis=0)
    adj = mat - np.round(xs - xs.min()).astype(np.int64)[:, None]
    dv = adj - np.median(adj, axis=0)
    log(f"  窓の区切りの実効の時刻（DUMP_T − D(NS)、{len(ks)} 回の共通の k）。中央値からのずれ（生）/ NS ごとの差 X(NS) − X(1) を引いた残り:")
    for j, (name, adc, ns) in enumerate(wmeta):
        log(f"    {name}（NS {ns}）: 生 {int(raw[j].min()):+d}〜{int(raw[j].max()):+d} / X − X(1) = {xs[j] - xs.min():+.1f} / "
            f"残り {int(dv[j].min()):+d}〜{int(dv[j].max()):+d}")
    bad_w = [wmeta[j][0] for j in range(nw_all) if np.abs(dv[j]).max() > lim]
    if bad_w:
        log(f"  {'NOTE（陽性対照どおり）' if offgrid else 'NG'}: 区切りが揃っていない窓 {bad_w}（許容 ±{lim}）")
        if not offgrid:
            bad += 1
    elif offgrid:
        log("  NG: 陽性対照なのに全窓が揃った（揃いの見張りが効いていない）"); bad += 1
    else:
        log(f"  OK: 8 窓の区切りは X(NS) を除いて ±{lim} ビートの内で揃っている")
    # TP の区切り（ADC ごと）と窓の区切り（その ADC の窓ごと）のずれ。窓ごと・符号つき（±TP_BEATS/2 に折り返す）で一定か
    for i, (lbl, f0first, af, at) in enumerate(tpi):
        if f0first is None:
            continue
        t_tp0 = at + (f0first - af) * 512
        for j, (name, adc, ns) in enumerate(wmeta):
            if adc != i:
                continue
            d = ((mat[j] - t_tp0 + TP_BEATS // 2) % TP_BEATS) - TP_BEATS // 2
            okj = int(d.max() - d.min()) <= 2
            log(f"  TP {lbl} と {name}（NS {ns}）: 窓の区切り − TP の区切り = {int(d.min()):+d}〜{int(d.max()):+d} ビート"
                f"（{beats_to_ns(int(np.median(d))) / 1000:+.2f} µs）{'OK（一定）' if okj else 'NG（一定でない）'}")
            if not offgrid and not okj:
                bad += 1
    return bad


def recheck(path):
    """F-4 の記録（PREFIX.f4.npz）から、窓の区切りの一致と TP とのずれを回し直す（ハードは要らない）"""
    z = np.load(path)
    names = [str(x) for x in z["names"]]
    wmeta, ks_, ts_ = [], [], []
    for j, name in enumerate(names):
        adc, widx, ns, nacc, L = [int(x) for x in z[f"w{j}_meta"]]
        wmeta.append((name, adc, ns)); ks_.append(z[f"w{j}_k"]); ts_.append(z[f"w{j}_t"])
    tpi = []
    i = 0
    while f"tp{i}_f0" in z:
        f0 = z[f"tp{i}_f0"]
        af, at = [int(x) for x in z[f"tp{i}_anch"]]
        tpi.append((S.CHANS[i][0], int(f0[0]) if len(f0) else None, af, at))
        i += 1
    log(f"F-4 の記録 {path} を回し直す: 窓 {len(names)}・TP {len(tpi)}")
    bad = align_report(wmeta, ks_, ts_, tpi)
    log(f"F-4（区切りの一致・TP とのずれ）: {'通過' if bad == 0 else f'失敗（{bad} 件）'}")
    return bad == 0


# ---------------------------------------------------------------- F-4
def f4(tc, tb, wins, full, wms, ndumps, tint, shift, keep, out=None, offgrid=0, ns_list=None, if_c=3000.0):
    nw_all = len(wins)
    seconds = ndumps * tint
    log(f"F-4: 窓 {nw_all}・TP {len(wms)} を同時に開始し、積分 {tint * 1e3:.2f} ms・TP {TP_N * 2e-3:.3f} ms で {ndumps} 回"
        f"（{seconds:.1f} 秒）、全部を読む{f'（陽性対照: ADC_A の窓 0 を格子 ＋ {offgrid} ビートで WRST し直す）' if offgrid else ''}")
    nacc = [max(1, int(round(tint * BEATS_PER_SEC / c.L))) for c in wins]
    for c, n in zip(wins, nacc):
        if (n * c.L) % G:
            log(f"ERROR: {c.name} の N·L = {n} × {c.L} が格子 G = {G} の倍数でない（--tint {tint} は 2.048 ms の倍数に）"); return False
    if offgrid:
        T.wrst_on_grid(tc, tb, wins, full, wms, ns_list, if_c, 0x0020_00FF, offset=offgrid, only=[0])
    for c, n in zip(wins, nacc):
        c.wr(W.R_NACC, n); c.wr(W.R_NDUMP, 0); c.wr(W.R_SHIFT, shift)
    for wm in wms:
        wm.write(W.A_BASE + T.RA_TP_N, TP_N)
    log("  N_ACC: " + " / ".join(f"{c.name}（NS {c.ns}）{n} = {n * c.L / BEATS_PER_SEC * 1e3:.3f} ms" for c, n in zip(wins, nacc)))
    sa = T.start_at_grid(tb)
    T.arm_all(tc, wins, full, wms, sa, tp=True, with_full=False)
    log(f"  START_AT = {sa}（格子 {sa // G}·G、UTC {tb.beat_utc_ns(sa) / 1e9:.6f}）")
    while not tc.status()["fired"]:
        time.sleep(0.01)
    bad = 0
    runts = [c.rd64(c.r["run_t"]) for c in wins] + [T.tp_run_t(wm) for wm in wms]
    names = [c.name for c in wins] + [f"TP {S.CHANS[i][0]}" for i in range(len(wms))]
    if any(t != sa + 1 for t in runts):
        log("  NG RUN_T: " + " / ".join(f"{n} {t - sa:+d}" for n, t in zip(names, runts))); bad += 1
    else:
        log(f"  RUN_T: {len(runts)} コアとも START_AT + 1")
    tps = [WinTp(wm) for wm in wms]
    cap = int(seconds * BEATS_PER_SEC / TP_BEATS) + 4000
    rds = []
    for tp in tps:
        tf0 = tp.rd(S.R_TP_F0_LO) | (tp.rd(S.R_TP_F0_HI) << 32)
        rds.append(NpTpReader(tp, TP_N, tf0, cap))
    anch = [tanch(wm) for wm in wms]
    gap0 = [int(wm.read(W.A_BASE + T.RA_GAP)) for wm in wms]
    # 窓の記録
    rec = {c.name: dict(k=[], t=[], h=[], cfg=[], fl=[], sum=[], spec=[], spec_k=[]) for c in wins}
    seq = {c.name: c.rd(W.R_SEQ) for c in wins}
    miss = {c.name: 0 for c in wins}
    t_loop, n_loop = [], 0
    t0_ = time.time()
    t_end = t0_ + seconds + 30                    # ダンプ ndumps 回で止める（時間は安全の上限）
    t_rep = t0_ + 60
    while time.time() < t_end and min(len(rec[c.name]["k"]) for c in wins) < ndumps:
        ts = time.perf_counter()
        for c in wins:
            s = c.rd(W.R_SEQ)
            if s == seq[c.name]:
                continue
            m, spec = read_win(c)
            d = (m["seq"] - seq[c.name]) & 0xFFFFFFFF
            if d != 1:
                miss[c.name] += d - 1
            seq[c.name] = m["seq"]
            r = rec[c.name]
            r["k"].append(m["k"]); r["t"].append(m["t"]); r["h"].append(m["h"]); r["cfg"].append(m["cfg"]); r["fl"].append(m["flags"])
            r["sum"].append(float(spec.sum()))
            if keep and m["k"] % keep == 0:
                r["spec"].append(spec.astype(np.float32)); r["spec_k"].append(m["k"])
        for rd in rds:
            rd.poll()
        t_loop.append(time.perf_counter() - ts)
        n_loop += 1
        if time.time() > t_rep:
            t_rep += 60
            log(f"  {time.time() - t0_:6.0f} s: 窓のダンプ {sum(len(rec[c.name]['k']) for c in wins)}・読み落とし {sum(miss.values())} / "
                f"TP {sum(rd.n for rd in rds)} 個・落とし {sum(rd.lost for rd in rds)} / 1 周の最大 {max(t_loop[-2000:]) * 1e3:.1f} ms")
        time.sleep(0.003)
    for c in wins:
        c.wr(W.R_CTRL, W.CTRL_STOP)
    anch1 = [tanch(wm) for wm in wms]
    gap1 = [int(wm.read(W.A_BASE + T.RA_GAP)) for wm in wms]
    tl = np.array(t_loop) * 1e3
    log(f"  読み出しの 1 周: {n_loop} 回 / 中央値 {np.median(tl):.2f} ms・99 % {np.percentile(tl, 99):.2f} ms・最大 {tl.max():.2f} ms"
        f"（積分 {tint * 1e3:.0f} ms。面は 2 つなので 1 周がこれを越えなければ落とさない）")
    # 窓の判定
    for c, n in zip(wins, nacc):
        r = rec[c.name]
        k = np.array(r["k"], np.int64); t = np.array(r["t"], np.int64); h = np.array(r["h"], np.int64)
        if len(k) < 2:
            log(f"  NG {c.name}: ダンプ {len(k)} 個"); bad += 1; continue
        dev = (t - t[0]) - (k - k[0]) * n * c.L
        kgap = int(np.sum(np.diff(k) != 1))
        hs = int(np.bitwise_or.reduce(h)); fs = int(np.bitwise_or.reduce(np.array(r["fl"], np.int64)))
        # FLAGS: [4] は FFT IP に待たされた（rev2 からデータを保って待つだけで正常。window.py と同じく外す）。[10] は ddc の追い越し（0 のはず）
        ok = miss[c.name] == 0 and kgap == 0 and np.all(np.abs(dev) <= 16) and hs == 0 and (fs & 0x7EF) == 0
        log(f"  {c.name}: {len(k)} 個（{len(k) * n * c.L / BEATS_PER_SEC:.1f} s）/ 読み落とし {miss[c.name]}・DUMP_K の飛び {kgap} / "
            f"DUMP_T のずれ {dev.min():+d}〜{dev.max():+d}（許容 ±16）/ 健全性 {T.h_text(hs)} / FLAGS {W.flag_text(fs)} {'OK' if ok else 'NG'}")
        bad += not ok
    # TP の判定
    t_first = []
    for i, (rd, (af, at), (af1, at1)) in enumerate(zip(rds, anch, anch1)):
        f0, nfr, tsum, fl = rd.arrays()
        lbl = S.CHANS[i][0]
        exp_n = seconds * BEATS_PER_SEC / TP_BEATS
        ok = rd.started and rd.lost == 0 and rd.bad_seq == 0 and rd.bad_flag == 0 and rd.bad_nfr == 0 and rd.overflow == 0 \
            and len(f0) >= 0.99 * exp_n
        # 錨の式の前提: 始めと終わりの TANCH が 512 ビート / フレームで結ばれ、その間に入力の途切れが無い
        a_dev = (at1 - at) - (af1 - af) * 512
        ok_a = a_dev == 0 and gap1[i] == gap0[i]
        if len(f0):
            t_first.append(int(at + (int(f0[0]) - af) * 512))
        log(f"  TP {lbl}: {len(f0)} 個（期待 ≒ {exp_n:.0f}）/ 落とし {rd.lost}・番号の飛び {rd.bad_seq}・FLAGS の異常 {rd.bad_flag}・"
            f"フレーム数の違い {rd.bad_nfr}・振り切れ [4] {rd.n_ovr} 個 / F0 より前に捨てた {rd.pre} / "
            f"錨の組の始め → 終わり {af1 - af} フレームで T のずれ {a_dev:+d}・GAP_CNT {gap0[i]} → {gap1[i]} "
            f"{'OK' if ok and ok_a else 'NG'}")
        bad += not (ok and ok_a)
    # 8 窓の区切りの一致（同じ k どうし）と、TP の区切りとのずれ（align_report。--recheck で記録から回し直せる）
    tpi = []
    for i, (rd, (af, at)) in enumerate(zip(rds, anch)):
        f0 = rd.arrays()[0]
        tpi.append((S.CHANS[i][0], int(f0[0]) if len(f0) else None, af, at))
    bad += align_report([(c.name, c.adc, c.ns) for c in wins],
                        [np.array(rec[c.name]["k"], np.int64) for c in wins],
                        [np.array(rec[c.name]["t"], np.int64) for c in wins], tpi, offgrid)
    if len(t_first) == len(rds):
        tf = np.array(t_first)
        log("  TP の最初の区切りの頭の T − START_AT: " + " / ".join(f"{S.CHANS[i][0]} {t_ - sa:+d}" for i, t_ in enumerate(tf))
            + f" ビート（ADC のフレームの格子の位相の差。ADC の間の差 {tf.max() - tf.min()} ビート = {beats_to_ns(tf.max() - tf.min())} ns）")
    if out:
        d = {}
        for j, c in enumerate(wins):
            r = rec[c.name]
            for key in ("k", "t", "h", "cfg", "fl"):
                d[f"w{j}_{key}"] = np.array(r[key], np.int64)
            d[f"w{j}_sum"] = np.array(r["sum"])
            d[f"w{j}_spec"] = np.array(r["spec"], np.float32).reshape(-1, W.NFFT_W)
            d[f"w{j}_spec_k"] = np.array(r["spec_k"], np.int64)
            d[f"w{j}_meta"] = np.array([c.adc, c.widx, c.ns, nacc[j], c.L], np.int64)
        for i, rd in enumerate(rds):
            f0, nfr, tsum, fl = rd.arrays()
            d[f"tp{i}_f0"], d[f"tp{i}_nfr"], d[f"tp{i}_sum"], d[f"tp{i}_fl"] = f0, nfr, tsum, fl
            d[f"tp{i}_anch"] = np.array(anch[i], np.int64)
        np.savez(out + ".f4.npz", start_at=sa, names=np.array([c.name for c in wins]), loop_ms=tl.astype(np.float32),
                 anchor=np.array([tb._anchor["utc_sec"], tb._anchor["stamp"]], np.int64), **d)
        log(f"  記録: {out}.f4.npz")
    log(f"F-4: {'通過' if bad == 0 else f'失敗（{bad} 件）'}")
    return bad == 0


# ---------------------------------------------------------------- F-5
def f5(tc, tb, wins, full, wms, seconds=1.0):
    """ADC ごとの TP（win_core_i の tp_core）と、同じ ADC につないだ全帯域（spec_core_0 の中の tp_core）の TP の、
    1 フレームあたりの平均の比。同じサンプルの Σx² なので、区切りの位相の違い（< 1 フレーム / 区切り）を除けば 1 に一致する"""
    log(f"F-5: ADC ごとの TP と全帯域の TP の比（{seconds} s 平均）")
    bad = 0
    for i, wm in enumerate(wms):
        T.select_full(wms, full, i)                 # SRST で spec_core_0 の中の tp_core も起動し直す（TP_N は既定 512 = 1.024 ms）
        time.sleep(seconds + 0.1)                   # どちらの TP も RUN なしで自走している（区切りは起動からのフレーム）
        vals = []
        for a in (WinTp(wm), S.Spec(full.m, idx=i, label=S.CHANS[i][0], base=full.base, lbase=full.lbase)):
            if a.rd(S.R_TP_NEFF) != TP_N:
                log(f"  NG {S.CHANS[i][0]}: TP_NEFF {a.rd(S.R_TP_NEFF)}（期待 {TP_N}）"); bad += 1
            n = min(int(seconds * 1000), 480)
            wp = a.rd(S.R_TP_WP)
            ent = np.array([a.block(S.TP_BASE + 16 * (j % S.TP_DEPTH), 4) for j in range(wp - n, wp)], np.uint64)
            sm = (ent[:, 0] | (ent[:, 1] << np.uint64(32))).astype(np.float64)
            nf = (ent[:, 3] & np.uint64(0xFFFFFF)).astype(np.float64)
            vals.append(sm.sum() / nf.sum())
        r = vals[0] / vals[1]
        ok = abs(r - 1) < 2e-3
        log(f"  {S.CHANS[i][0]}: 1 フレームあたり 窓の側 {vals[0]:.4e} / 全帯域 {vals[1]:.4e} → 比 {r:.6f} {'OK' if ok else 'NG'}（許容 ±2e-3）")
        bad += not ok
    log(f"F-5: {'通過' if bad == 0 else f'失敗（{bad} 件）'}")
    return bad == 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=S.BITFILE)
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--path", default="trig", choices=("trig", "comp"))
    p.add_argument("--ns", default="1,2,3,4,5,6,1,6", help="窓の NS。ADC の順・窓の順に 4 × NW 個")
    p.add_argument("--if", dest="if_c", type=float, default=3000.0)
    p.add_argument("--dumps", type=int, default=44000, help="F-4 のダンプの回数（44,000 × 40.96 ms ≒ 30.0 分）")
    p.add_argument("--tint", type=float, default=0.04096, help="積分時間 [s]（SAM45-Fine は 40.96 ms = 20 × 2.048 ms）")
    p.add_argument("--offgrid", type=int, default=0, help="F-4 の陽性対照: ADC_A の窓 0 を格子 ＋ この数のビートで WRST し直す")
    p.add_argument("--shift", type=int, default=4)
    p.add_argument("--keep", type=int, default=250, help="スペクトルを残す間隔（ダンプの番号 k がこの倍数のとき。0 = 残さない）")
    p.add_argument("--out", default=None)
    p.add_argument("--f4", action="store_true")
    p.add_argument("--f5", action="store_true")
    p.add_argument("--recheck", default=None, help="F-4 の記録 PREFIX.f4.npz から区切りの一致と TP とのずれだけを回し直す（ボードの PL は使わない）")
    a = p.parse_args()
    if a.recheck:
        sys.exit(0 if recheck(a.recheck) else 1)
    ns_list = [int(x) for x in a.ns.split(",")]
    if a.out:
        d = os.path.dirname(a.out) or "."
        os.makedirs(d, exist_ok=True)
        if not os.access(d, os.W_OK):
            log(f"ERROR: {d} に書けない"); sys.exit(1)

    from pynq import Overlay
    import xrfdc                                   # Overlay() より前に import する（VERSIONS.md）
    S.setup_clocks(a.clkin, a.ref)
    ol = Overlay(a.bitfile)
    log(f"Overlay: {a.bitfile}")
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    S.check_tiles(ol.rfdc, 2)
    if a.settle > 0:
        time.sleep(a.settle)
    tc, wms, wins, full = T.open_all(ol, ns_list)
    for wm in wms:
        prm = int(wm.read(W.A_BASE + S.R_TP_PARAM)) & 0xFFFFFFFF
        if prm != S.TP_PARAM_EXPECT:
            log(f"ERROR: TP_PARAM {prm:08x}（期待 {S.TP_PARAM_EXPECT:08x}: FLAGS[4] のある tp_core）"); sys.exit(1)
    tc.configure(src=a.path, tol=1)
    tb = Timebase(tc, path=a.path)
    try:
        anc = tb.anchor()
    except TimebaseError as e:
        log(f"ERROR: 錨を打てない: {e}"); sys.exit(1)
    log(f"錨: UTC {anc['utc_sec']} 秒 = スタンプ {anc['stamp']}（EPOCH {anc['epoch']}）")
    T.wrst_on_grid(tc, tb, wins, full, wms, ns_list, a.if_c, 0x0020_0004)   # 格子の START_AT で一斉に WRST
    ok = True
    if a.f4:
        ok &= f4(tc, tb, wins, full, wms, a.dumps, a.tint, a.shift, a.keep, a.out, offgrid=a.offgrid, ns_list=ns_list, if_c=a.if_c)
    if a.f5:
        ok &= f5(tc, tb, wins, full, wms)
    log(f"総合: {'通過' if ok else '失敗'}")


if __name__ == "__main__":
    main()
