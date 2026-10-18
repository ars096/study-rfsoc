#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj024 手順 3d — 2G-1 の取得の 1 周（1 BASE = 10.24 ms に 1 MiB のレコード 1 個）を、specd と**同じ関数**で通して A53 の時間を測る

    sudo -E $(which python3) bench_g21.py                 # ボード（pynq.allocate のバッファ・範囲の invalidate）。結果は runs/bench_g21.json
    python3 bench_g21.py --no-pynq --bases 40             # PYNQ の無い計算機で道具の動きだけ確かめる（numpy のバッファ）
    sudo -E $(which python3) bench_g21.py --corrupt 50    # 陽性対照: 50 個に 1 個のレコードの中身を 1 バイト壊す → CRC の不一致 = レコード数 / 50
    MALLOC_MMAP_THRESHOLD_=33554432 MALLOC_TRIM_THRESHOLD_=1073741824 python3 bench_g21.py   # 3d 3 回目: 1 MiB の配列を mmap で取らせない

**PL は使わない**（Overlay を載せない）。リングの中身は PS が書いた試験の値で、s45_ring のレジスタの代わりに W を手で進める。
通すもの（本物の関数）:
  1. plring.Ring.read（[R, W) の範囲の invalidate・頭と尾・**1 MiB の CRC-32**・中身の写し）
  2. s45acq.rec_meta → Bundler.add（u64 の写しと和。n_sum 個で 1 束）
  3. Acq._spec_record_full（逆順の写し・float32 の最も近い丸め・**送り出しの CRC-32**・s45ring.Ring.put = 共有メモリの溜まりへ）
溜まりの読み手（specd の送り出し）は別のプロセスなので、ここでは周の外で溜まりを空にする（時間に入れない）。
TP（10 個 / 10.24 ms の小さなレコード）は入れない（1 周に 1 レコード・数十 µs の見当。3d の結果で効くなら足す）。

判定の物差し: 1 BASE（PL のレコード 1 個）あたりの時間の平均・p99・最大と、その 10.24 ms に対する割合。
**specd を止めてから測る**（同じ A53 を取り合う）。CPU を 1 つに固定し（--cpu、既定 3）、SCHED_FIFO（--rt、既定 50。root のとき）で specd の取得と同じ条件に。
"""
import argparse
import gc
import json
import os
import resource
import time
import types
import zlib

import numpy as np

import plring as PR
import s45acq as A
import s45proto as P
import s45ring as R

MiB = 1 << 20


class _M:
    """s45_ring のレジスタの代わり（W は bench が進める。R の書きは受けるだけ）"""

    def __init__(self):
        self.w = 0

    def read(self, a):
        return self.w if a == PR.R_W else 0

    def write(self, a, v):
        pass


def make_ring(size, use_pynq):
    """plring.Ring を PL なしで作る（__init__ の allocate・pyxrt の範囲 sync はボードの本物と同じ）"""
    r = PR.Ring.__new__(PR.Ring)
    r.m = _M()
    r.size = size
    if use_pynq:
        from pynq import allocate
        r.buf = allocate(shape=(size // 8,), dtype=np.uint64, cacheable=True)
        r.a64 = r.buf.view(np.ndarray)
        r.bo_sync = None
        import pyxrt
        bo = r.buf.bo
        d = pyxrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE
        bo.sync(d, 4096, 0)
        r.bo_sync = lambda n, off: bo.sync(d, n, off)
    else:
        r.buf = None
        r.a64 = np.zeros(size // 8, np.uint64)
        r.bo_sync = None
    r.a8 = r.a64.view(np.uint8)
    r.u8 = r.a8
    r.inval = use_pynq
    r.touch = 0
    r.sink = 0
    r.r = 0
    r.base = 0
    return r


def write_rec(r, pos, seq, k, f0, t, n_acc, pay, corrupt=False):
    """INTERFACE 4.4 のレコード（頭 8 語・中身・尾 8 語）を位置 pos に置く。CRC = zlib.crc32(頭 ＋ 中身)"""
    a64, a8 = r.a64, r.a8
    i = pos >> 3
    pb = pay.size * 8
    h = np.zeros(8, np.uint64)
    h[0] = PR.MAGIC_R | (A.TYPE_SPEC << 40) | (0 << 48) | (0 << 56)      # core 0・s 0
    h[1] = seq | (k << 32)
    h[2] = f0
    h[3] = t
    h[4] = 18                                                             # 語 4: log2 NFFT 18（DUMP_H 0）
    h[5] = n_acc
    h[6] = 0
    h[7] = pb
    a64[i:i + 8] = h
    a64[i + 8:i + 8 + pay.size] = pay
    c = zlib.crc32(a8[pos:pos + 64 + pb])
    if corrupt:
        a8[pos + 64 + 8] ^= 1                                             # CRC を付けた後に中身を 1 バイト壊す
    j = (pos + 64 + pb) >> 3
    a64[j] = PR.MAGIC_E | (seq << 32)
    a64[j + 1] = c
    a64[j + 2:j + 8] = 0
    return 64 + pb + 64


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-pynq", dest="pynq", action="store_false")
    p.add_argument("--ring-mib", type=int, default=32, help="リング（specd の既定 32 MiB。1 MiB のレコードが 31 個入る）")
    p.add_argument("--buf-mb", type=int, default=64, help="溜まり（s45ring）の大きさ。周の外で空にする")
    p.add_argument("--bases", type=int, default=400, help="測る BASE の数（400 = 4.1 s ぶん）")
    p.add_argument("--n-sum", type=int, default=4, help="束ねる数（tint / 10.24 ms。既定 4 = 40.96 ms）")
    p.add_argument("--fmt", choices=["f32", "u64", "both"], default="f32")
    p.add_argument("--corrupt", type=int, default=0, help="陽性対照: この数ごとに 1 個のレコードを壊す")
    p.add_argument("--cpu", type=int, default=3)
    p.add_argument("--rt", type=int, default=50)
    p.add_argument("--out", default="runs/bench_g21.json")
    p.add_argument("--gc", action="store_true", help="GC を止めない（3d の 1 回目の形。既定は specd と同じく gc.freeze・gc.disable）")
    p.add_argument("--warm", type=int, default=20, help="最大を「最初の warm BASE を除いて」も出す（溜まり・リングのページの最初の割り当て）")
    a = p.parse_args()

    if a.cpu is not None and a.cpu >= 0:
        try:
            os.sched_setaffinity(0, {a.cpu})
        except OSError as e:
            print(f"CPU の固定ができない: {e}")
    if a.rt:
        try:
            os.sched_setscheduler(0, os.SCHED_FIFO, os.sched_param(a.rt))
        except (OSError, AttributeError) as e:
            print(f"SCHED_FIFO にできない（{e}）。普通の優先度で")

    size = a.ring_mib * MiB
    ring = make_ring(size, a.pynq)
    sh = R.Ring(a.buf_mb << 20)
    rng = np.random.default_rng(1)
    pays = [rng.integers(0, 1 << 40, A.G_NCH, dtype=np.uint64) for _ in range(4)]

    # Acq を specd と同じ形で作り、裏だけ最小のものに（_spec_record_full が見るのは be.clock・be.cfgs・be.bit_kind）
    opts = types.SimpleNamespace(posctl_corrupt=0, posctl_gap=0, proto=2, posctl_f32_trunc=False, tp_cal=None, g21=True, wide=False)
    acq = A.Acq(None, sh, opts)
    acq.st["fmt"] = a.fmt
    acq.st["tint"] = a.n_sum * A.BASE_BEATS / A.BEATS_PER_SEC
    cfgs = A.g21_cfgs(acq.st)
    clock = A.Clock(types.SimpleNamespace(_anchor=dict(utc_sec=1_700_000_000, stamp=0), cal=dict(pps_det_ns=0, adc_to_core_ns=0),
                                          check=lambda: None), {})
    acq.be = types.SimpleNamespace(clock=clock, cfgs=cfgs, bit_kind=11)
    cf = cfgs[0]
    bund = A.Bundler(cf["n_sum"], cf["pl_nacc"])

    if not a.gc:
        gc.collect(); gc.freeze(); gc.disable()                      # specd の Acq.run と同じ
    t_rd, t_bu, t_sp, t_all = [], [], [], []
    flt = []                                                          # 3d 3 回目: 周ごとのページフォルト（minor）の数
    t_bu_k, t_sp_k = [], []                                           # 周ごとの和・記録（レコードが無い周は 0）
    crc_bad = tail_bad = nrec = nspec = 0
    pos = 0
    t0_beat = 1000 * a.n_sum * A.BASE_BEATS + 1                   # specd の START_AT は tint の格子（DUMP_T = START_AT ＋ 1）。格子に乗せないと最初の束が欠ける
    try:
        for k in range(a.bases):
            # PL の代わりにレコードを 1 個書く（時間に入れない）。端に入らなければ PAD で端まで
            L = 64 + A.G_NCH * 8 + 64
            p0 = pos % size
            if size - p0 < L:
                ring.a64[p0 >> 3] = PR.MAGIC_R | (PR.TYPE_PAD << 40)
                ring.a64[(p0 >> 3) + 7] = size - p0
                pos += size - p0
                p0 = 0
            pos += write_rec(ring, p0, k + 1, k, k * A.G_PL_NACC, t0_beat + k * A.BASE_BEATS, A.G_PL_NACC, pays[k % 4],
                             corrupt=bool(a.corrupt and (k + 1) % a.corrupt == 0))
            if ring.buf is not None:
                ring.buf.flush()                                      # PS が書いた行を DDR へ（PL が書いたのと同じ見え方に）
            ring.m.w = pos & 0xFFFFFFFF
            if sh.used() > sh.cap // 2:
                sh.skip_all()                                         # 送り出しの代わりに空にする（時間に入れない）

            f0 = resource.getrusage(resource.RUSAGE_SELF).ru_minflt
            ta = time.perf_counter()
            recs = ring.read()
            tb = time.perf_counter()
            for core, s, seq, hw, pay, crc_ok, tail_ok in recs:
                nrec += 1
                crc_bad += not crc_ok
                tail_bad += not tail_ok
                if not (crc_ok and tail_ok):
                    continue
                got, _ = bund.add(A.rec_meta(hw), pay)
                tc = time.perf_counter()
                if got is not None:
                    m, spec = got
                    acq._spec_record(0, m, spec)
                    nspec += 1
                td = time.perf_counter()
                t_bu.append(tc - tb); t_sp.append(td - tc)
            te = time.perf_counter()
            flt.append(resource.getrusage(resource.RUSAGE_SELF).ru_minflt - f0)
            t_rd.append(tb - ta); t_all.append(te - ta)
            t_bu_k.append(tc - tb if recs else 0.0)
            t_sp_k.append(td - tc if recs else 0.0)
    finally:
        ring.a64 = ring.a8 = ring.u8 = None
        if ring.buf is not None:
            ring.buf.freebuffer()
        sh.close()

    ms = lambda v: np.array(v) * 1e3
    al, rd, bu, sp = ms(t_all), ms(t_rd), ms(t_bu), ms(t_sp)
    base_ms = A.BASE_BEATS / A.BEATS_PER_SEC * 1e3
    res = dict(pynq=a.pynq, ring_mib=a.ring_mib, bases=a.bases, n_sum=a.n_sum, fmt=a.fmt, corrupt=a.corrupt,
               nrec=nrec, nspec=nspec, crc_bad=crc_bad, tail_bad=tail_bad, drop=acq.drop["n"],
               all_mean=float(al.mean()), all_p99=float(np.percentile(al, 99)), all_max=float(al.max()),
               gc_off=not a.gc, max_at=int(al.argmax()), slow=int((al > 10.24).sum()), slow_at=[int(x) for x in np.flatnonzero(al > 10.24)[:20]],
               max_after_warm=float(al[a.warm:].max()) if al.size > a.warm else None,
               load=float(al.mean() / base_ms),
               read_mean=float(rd.mean()), bund_mean=float(bu.mean()) if bu.size else 0.0,
               spec_mean_per_bundle=float(sp[sp > 0].mean()) if (sp > 0).any() else 0.0)
    print(f"2G-1 の 1 BASE（1 MiB のレコード 1 個、{a.bases} 個・n_sum {a.n_sum}・fmt {a.fmt}・{'pynq.allocate' if a.pynq else 'numpy'}）:")
    print(f"  合計  平均 {res['all_mean']:6.2f} ms・p99 {res['all_p99']:6.2f}・最大 {res['all_max']:6.2f} ms（10.24 ms の {100 * res['load']:.0f} %）GC {'止めた' if not a.gc else '動く'}")
    print(f"  裾    最大は {res['max_at']} 番目・最初の {a.warm} を除いた最大 {res['max_after_warm'] if res['max_after_warm'] is None else round(res['max_after_warm'], 2)} ms・10.24 ms を越えた BASE {res['slow']}（番目: {res['slow_at']}）")
    print(f"  内訳  リングの読み（invalidate・CRC・写し）{res['read_mean']:.2f} ms / 束ねの和 {res['bund_mean']:.2f} ms / "
          f"記録（逆順・float32・CRC・溜まり）1 束あたり {res['spec_mean_per_bundle']:.2f} ms（{a.n_sum} BASE に 1 回）")
    print(f"  レコード {nrec}・SPEC の記録 {nspec}（期待 {a.bases // a.n_sum if not a.corrupt else '壊したぶん少ない'}）・"
          f"CRC の不一致 {crc_bad}・尾の不一致 {tail_bad}・溜まりの DROP {acq.drop['n']}")
    fl = np.array(flt)
    kk = np.arange(al.size) % a.n_sum
    res["by_phase"] = {int(q): dict(n=int((kk == q).sum()), all_mean=float(al[kk == q].mean()), all_max=float(al[kk == q].max()),
                                    read_mean=float(rd[kk == q].mean()), bund_mean=float(ms(t_bu_k)[kk == q].mean()),
                                    spec_mean=float(ms(t_sp_k)[kk == q].mean()), flt_mean=float(fl[kk == q].mean()),
                                    slow=int((al[kk == q] > base_ms).sum())) for q in range(a.n_sum)}
    res["flt_total"] = int(fl.sum())
    res["per_base"] = dict(all=al.round(3).tolist(), read=rd.round(3).tolist(), bund=ms(t_bu_k).round(3).tolist(),
                           spec=ms(t_sp_k).round(3).tolist(), flt=fl.tolist())
    res["malloc_env"] = {k: v for k, v in os.environ.items() if k.startswith("MALLOC_")}
    print(f"  周の位相（k mod {a.n_sum}、{a.n_sum - 1} が束を閉じる周）ごと: 平均 ms / 最大 / 読み / 和 / 記録 / ページフォルト / 越えた数")
    for q, v in res["by_phase"].items():
        print(f"    {q}: {v['all_mean']:6.2f} / {v['all_max']:6.2f} / {v['read_mean']:5.2f} / {v['bund_mean']:5.2f} / {v['spec_mean']:5.2f} / "
              f"{v['flt_mean']:7.1f} / {v['slow']}")
    print(f"  ページフォルトの合計 {res['flt_total']}・MALLOC_* {res['malloc_env'] or 'なし'}")
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)


if __name__ == "__main__":
    main()
