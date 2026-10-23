#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj029 1: SPEC の記録 1 本の C（s45fast）を、本物の Acq._spec_record_full（_put で出口を捕まえる）と bytes 単位で照らし、時間を測る

  python3 test_s45fast.py                  # 照合と陽性対照（どこでも。判定は最後の「判定: OK / NG」）
  python3 test_s45fast.py --bench 1000 --cpu 3 --out ../runs/fast_1a.json    # ボード（root）。1 本あたりの時間
"""
import argparse
import json
import os
import platform
import time
import zlib

import numpy as np

import s45acq
import s45fast as F
import s45proto as P
import s45ring

NG = []


def check(name, ok, msg=""):
    print(f"{'OK' if ok else 'NG'}  {name}{('  ' + msg) if msg else ''}")
    if not ok:
        NG.append(name)


# ---- 本物の _spec_record_full を動かす最小の Acq
class _Clock:
    ok = True

    def utc_ns(self, t, ns, adc):
        return 1_761_000_000_000_000_000 + int(t) * 4


class _Be:
    bit_kind = 10
    clock = _Clock()


def make_acq(fmt, trunc=False):
    a = s45acq.Acq.__new__(s45acq.Acq)
    a.st = dict(fmt=fmt)
    a.f32_trunc = trunc
    a.be = _Be()
    a.h_or = a.fl_or = a.sat = 0
    a.got = []
    a._put = lambda rtype, parts, crc: a.got.append((rtype, [bytes(memoryview(p).cast("B")) for p in parts], crc))
    return a


CF = dict(src=2, shift=7, n_sum=1, nacc=160, if_mhz=2000.015625, df_hz=31250.0, ds=1, frame=8192)
M = dict(t=123_456_789_012, cfg=5, k=42, sat=0, flags=0, h=0)


def py_record(spec, fmt, trunc=False):
    """[(code, hd, data, crc)]（fmt both なら u64・f32 の 2 つ）"""
    a = make_acq(fmt, trunc)
    a._spec_record_full(0, dict(M), spec, CF, 0)
    out = []
    for rtype, parts, crc in a.got:
        assert rtype == P.T_SPEC and len(parts) == 2
        code = P.SPEC2_H.unpack_from(parts[0])[6]
        out.append((code, parts[0], parts[1], crc))
    return out


def edge_spec(n, rng):
    s = rng.integers(0, 1 << 40, n, dtype=np.uint64)
    s[: n // 4] = rng.integers(0, 1 << 53, n // 4, dtype=np.uint64)        # 大きい値（float32 の丸めが効く）
    e = [0, 1, 2, (1 << 24) - 1, 1 << 24, (1 << 24) + 1, (1 << 24) + 2, (1 << 24) + 3, (1 << 25) + 2, (1 << 25) + 6,
         (1 << 53) - 1, (1 << 53) - 2, (1 << 52) + 1, 0xFFFFFFFF, 1 << 32, (1 << 32) + 255, (1 << 32) + 256, (1 << 32) + 257]
    pos = rng.choice(n, len(e) * 4, replace=False)
    for i, p in enumerate(pos):
        s[p] = e[i % len(e)]
    s[n // 2: n // 2 + 64] = s[n // 2]                                        # 続く同じ値
    s[0], s[-1] = (1 << 24) + 1, (1 << 53) - 1                                # 両端（逆順の取り違えが端に出る）
    return s


def cmp(name, ref_data, ref_crc, data, crc, want_same=True):
    b = data.tobytes()
    diff = np.flatnonzero(np.frombuffer(ref_data, data.dtype) != data) if len(b) == len(ref_data) else np.array([-1])
    same = b == ref_data and crc == ref_crc
    msg = f"不一致 {diff.size} か所{(' 最初 ' + str(int(diff[0]))) if diff.size else ''}・CRC {'一致' if crc == ref_crc else '不一致'}"
    check(name, same == want_same, msg)
    return diff


def tests():
    rng = np.random.default_rng(29)
    print(f"CRC: {'命令' if F.HW_CRC else '表'}（{platform.machine()}）")
    # CRC の口だけ（長さ・位置のずれ、初期値の続き）
    buf = rng.integers(0, 256, 4096 + 17, dtype=np.uint8).tobytes()
    bad = [(o, n) for o in range(0, 9) for n in (0, 1, 7, 8, 9, 88, 1000, 4096) if F.crc32(buf[o:o + n]) != zlib.crc32(buf[o:o + n])]
    bad += [("init", 0)] if F.crc32(buf[100:200], zlib.crc32(buf[:100])) != zlib.crc32(buf[:200]) else []
    check("crc32 = zlib.crc32（位置 0〜8・長さ 0〜4096・初期値の続き）", not bad, f"外れ {bad[:4]}")

    for n in (65536, 131072):
        spec = edge_spec(n, rng)
        ref = {code: (hd, data, crc) for code, hd, data, crc in py_record(spec, "both")}
        hd, rd, rc = ref[P.FMT_F32]
        d, c = F.spec_f32(spec, hd)
        cmp(f"n {n} f32 = _spec_record_full", rd, rc, d, c)
        hdu, rdu, rcu = ref[P.FMT_RAW]
        du, cu = F.spec_u64(spec, hdu)
        cmp(f"n {n} u64 = _spec_record_full", rdu, rcu, du, cu)
        # fmt f32 だけの道（both と同じ頭・中身のはず）
        (code1, hd1, rd1, rc1), = py_record(spec, "f32")
        d1, c1 = F.spec_f32(spec, hd1)
        cmp(f"n {n} f32（fmt f32）= _spec_record_full", rd1, rc1, d1, c1)
        # out を使い回す口（前の中身が残らない）
        out = np.full(n, np.nan, np.float32)
        d2, c2 = F.spec_f32(spec, hd, out=out)
        cmp(f"n {n} f32 out を渡す", rd, rc, d2, c2)
        # 陽性対照（落ちるべきもの）
        s1 = spec.copy(); ch = 12345; s1[ch] += np.uint64(1 << 30)
        dp, cp = F.spec_f32(s1, hd)
        diff = cmp(f"n {n} p1 1 ch だけ変える → 不一致", rd, rc, dp, cp, want_same=False)
        check(f"n {n} p1 不一致は 1 か所・位置 n−1−ch", diff.size == 1 and int(diff[0]) == n - 1 - ch, f"{diff[:3].tolist()}")
        dt_, ct_ = F.spec_f32(spec, hd, posctl=F.PC_TRUNC)
        cmp(f"n {n} p2 0 への切り捨て → 不一致", rd, rc, dt_, ct_, want_same=False)
        (_, hdt, rdt, rct), = py_record(spec, "f32", trunc=True)
        cmp(f"n {n} p2 の C = Python の f32_trunc（陽性対照どうしが同じもの）", rdt, rct, dt_, ct_)
        dn, cn = F.spec_f32(spec, hd, posctl=F.PC_NOREV)
        cmp(f"n {n} p3 逆順にしない → 不一致", rd, rc, dn, cn, want_same=False)
        dnu, cnu = F.spec_u64(spec, hdu, posctl=F.PC_NOREV)
        cmp(f"n {n} p3 u64 逆順にしない → 不一致", rdu, rcu, dnu, cnu, want_same=False)
        s4 = spec.copy(); s4[777] = np.uint64(1 << 53)
        e_py = e_c = None
        try:
            py_record(s4, "f32")
        except ValueError as e:
            e_py = str(e)
        try:
            F.spec_f32(s4, hd)
        except ValueError as e:
            e_c = str(e)
        check(f"n {n} p4 2^53 → 両方が拒否", e_py is not None and e_c == e_py, f"Python {e_py!r}・C {e_c!r}")


# ---- 時間
def stat(ts):
    a = np.array(ts) * 1e3
    return dict(median=float(np.median(a)), mean=float(a.mean()), p99=float(np.percentile(a, 99)), max=float(a.max()), n=int(a.size))


def tm(f, n):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        f()
        ts.append(time.perf_counter() - t0)
    return stat(ts)


def bench(n_rep, nch):
    rng = np.random.default_rng(1)
    spec = rng.integers(0, 1 << 40, nch, dtype=np.uint64)
    a = make_acq("f32")
    a._put = lambda rtype, parts, crc: None                     # put を除く
    (code, hd, rd, rc), = py_record(spec, "f32")
    out = np.empty(nch, np.float32)
    ring = s45ring.Ring(64 << 20)
    hdr = P.header(P.T_SPEC, len(hd) + rd.__len__(), rc, 1)
    data = np.frombuffer(rd, np.float32)

    def put():
        ring.put([hdr, hd, data])
        with ring.lock:
            ring.ctl[1] = ring.ctl[0]                           # 読み手が読み終えた形（溜まりを満たさない）

    r = {}
    r["py_record"] = tm(lambda: a._spec_record_full(0, dict(M), spec, CF, 0), n_rep)
    r["py_rev"] = tm(lambda: np.ascontiguousarray(np.asarray(spec, np.uint64)[::-1]), n_rep)
    raw = np.ascontiguousarray(spec[::-1])
    r["py_f32_round"] = tm(lambda: P.f32_round(raw), n_rep)
    f = P.f32_round(raw)
    r["py_crc32"] = tm(lambda: P.crc32(hd, f), n_rep)
    r["c_spec_f32_out"] = tm(lambda: F.spec_f32(spec, hd, out=out), n_rep)
    r["c_spec_f32_new"] = tm(lambda: F.spec_f32(spec, hd), n_rep)
    r["c_crc32_256k"] = tm(lambda: F.crc32(f), n_rep)
    r["c_nop"] = tm(F.nop, n_rep)
    r["ring_put"] = tm(put, n_rep)
    ring.close()
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", type=int, default=0, help="時間を測る回数（0 = 照合だけ）")
    ap.add_argument("--nch", type=int, default=65536)
    ap.add_argument("--cpu", type=int, default=None)
    ap.add_argument("--out", default=None)
    o = ap.parse_args()
    if o.cpu is not None:
        os.sched_setaffinity(0, {o.cpu})
    print(s45acq.malloc_tune()[1])
    tests()
    res = dict(machine=platform.machine(), hw_crc=F.HW_CRC, ng=NG)
    if o.bench:
        import gc
        gc.collect(); gc.disable()
        b = bench(o.bench, o.nch)
        gc.enable()
        res.update(nch=o.nch, cpu=o.cpu, bench_ms=b)
        print(f"時間（ms、{o.bench} 回、nch {o.nch}、CPU {o.cpu}）:  中央値 / 平均 / p99 / 最大")
        for k, v in b.items():
            print(f"  {k:16s} {v['median']:8.3f} {v['mean']:8.3f} {v['p99']:8.3f} {v['max']:8.3f}")
        py, c = b["py_record"]["median"], b["c_spec_f32_out"]["median"]
        print(f"比（Python の記録 / C、中央値）: {py / c:.1f} 倍")
    if o.out:
        with open(o.out, "w") as fh:
            json.dump(res, fh, indent=1, ensure_ascii=False)
    print(f"判定: {'OK' if not NG else 'NG'}" + (f"  落ちた: {NG}" if NG else ""))


if __name__ == "__main__":
    main()
