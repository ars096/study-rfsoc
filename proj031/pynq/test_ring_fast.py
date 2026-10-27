#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj029 2: --fast-ring（SPEC のレコードを写さずにリングの上から C で記録に）の PL なしの照合。どこでも回る（numpy と libs45fast.so）

PL が書く形のレコード（頭 64 バイト・中身・尾の MAGIC_E と CRC、INTERFACE 4.）を numpy の配列のリングに書き、
本物の plring.Ring.read・G22Backend.pump・poll_win・release・Bundler・Acq._spec_record_full に通して、今までの道（写す・Python）と bytes で照らす。
  python3 test_ring_fast.py        # 判定は最後の「判定: OK / NG」
"""
import collections
import zlib

import numpy as np

import plring as PR
import s45acq as A
import s45fast as F
import s45proto as P

NG = []


def check(name, ok, msg=""):
    print(f"{'OK' if ok else 'NG'}  {name}{('  ' + msg) if msg else ''}")
    if not ok:
        NG.append(name)


class FakeMM:
    def __init__(self):
        self.regs = collections.defaultdict(int)
        self.n_wr_r = 0

    def read(self, a):
        return self.regs[a]

    def write(self, a, v):
        self.regs[a] = v
        if a == PR.R_R:
            self.n_wr_r += 1


def fake_ring(size=8 << 20):
    r = PR.Ring.__new__(PR.Ring)
    r.m = FakeMM()
    r.size = size
    r.a64 = np.zeros(size // 8, np.uint64)
    r.a8 = r.a64.view(np.uint8)
    r.inval, r.touch, r.sink, r.bo_sync = False, 0, 0, None
    r.r, r.hold, r.w = 0, False, 0
    return r


def put_rec(r, ty, core, s, seq, k, t, payload, n=160, cfg=5):
    """PL の形のレコードを W に書く（端を越えるなら PAD で端まで埋める）。返すのは書いた位置"""
    pb = payload.nbytes
    L = 64 + pb + 64
    p = r.w % r.size
    if p + L > r.size:
        h = np.zeros(8, np.uint64)
        h[0] = PR.MAGIC_R | (PR.TYPE_PAD << 40)
        h[7] = r.size - p
        r.a64[p >> 3:(p >> 3) + 8] = h
        r.w += r.size - p
        p = 0
    h = np.zeros(8, np.uint64)
    h[0] = PR.MAGIC_R | (ty << 40) | (core << 48) | (s << 56)
    h[1] = seq | (k << 32)
    h[3] = t
    h[5] = n
    h[6] = cfg
    h[7] = pb
    i = p >> 3
    r.a64[i:i + 8] = h
    r.a8[p + 64:p + 64 + pb] = payload.view(np.uint8)
    crc = zlib.crc32(r.a8[p:p + 64 + pb])
    tl = np.zeros(8, np.uint64)
    tl[0] = PR.MAGIC_E | (seq << 32)
    tl[1] = crc
    r.a64[(p + 64 + pb) >> 3:((p + 64 + pb) >> 3) + 8] = tl
    r.w += L
    r.m.regs[PR.R_W] = r.w & 0xFFFFFFFF
    return p


def make_be(ring, lazy):
    be = A.G22Backend.__new__(A.G22Backend)
    be.ring, be.use_ring, be.W = ring, True, None
    be.jmap = {(c, 0): j for c, j in zip((0, 1), A.G2_WIN)}
    be.q = [collections.deque() for _ in range(4 * A.NW)]
    be.seq = [0] * (4 * A.NW)
    be.running, be.tp_slot, be.n_pump, be.ring_crc, be.n_mat = True, {}, 0, 0, 0
    be.lazy_wins = set(A.G2_WIN) if lazy else set()
    be.bit_kind = 10

    class _Clock:
        ok = True

        def utc_ns(self, t, ns, adc):
            return 1_761_000_000_000_000_000 + int(t) * 4
    be.clock = _Clock()
    return be


def make_acq(be, fmt, fast, trunc=False):
    a = A.Acq.__new__(A.Acq)
    a.st = dict(fmt=fmt)
    a.f32_trunc = trunc
    a.fast = F if fast else None
    a.be = be
    a.h_or = a.fl_or = a.sat = 0
    a.n_miss = [0] * (4 * A.NW)
    a.got = []
    a.logs = []
    a.log = lambda *x: a.logs.append(" ".join(map(str, x)))
    a._put = lambda rtype, parts, crc: a.got.append(([bytes(memoryview(p).cast("B")) for p in parts], crc))
    return a


CF = dict(src=2, shift=7, n_sum=1, nacc=160, if_mhz=2000.015625, df_hz=31250.0, ds=1, frame=8192, kind="full")
BASE = A.BASE_BEATS


def fill(r, nrec, rng, nch=65536, t0=1000 * BASE):
    """窓 A0・B0（コア 0・1）に交互に SPEC を nrec 個ずつ、間に小さい TP のレコード。中身を返す"""
    pays = {0: [], 1: []}
    for k in range(nrec):
        for c in (0, 1):
            pay = rng.integers(0, 1 << 44, nch, dtype=np.uint64)
            pay[0], pay[-1] = (1 << 24) + 1, (1 << 53) - 1
            put_rec(r, PR.TYPE_SPEC, c, 0, 1 + k, k, t0 + k * BASE, pay)
            pays[c].append(pay)
            put_rec(r, PR.TYPE_TP, c, 0xFF, 1 + k, 0, 0, rng.integers(0, 1 << 30, 32, dtype=np.uint64))
    return pays


def run(be, a, n_poll=64):
    """pump → 窓ごとに poll_win を n_poll 個まで → Bundler（n_sum 1）→ _spec_record_full → release。Acq._loop_once の窓の部分と同じ並び"""
    be.pump()
    bund = {j: A.Bundler(1, 160) for j in A.G2_WIN}
    for j in A.G2_WIN:
        for _ in range(n_poll):
            x = be.poll_win(j)
            if x is None:
                break
            m, spec, miss = x
            a.n_miss[j] += miss
            got, _ = bund[j].add(m, spec)
            if got is None:
                continue
            mm, sp = got
            a._spec_record_full(j, mm, sp, CF, 0)
    be.release()


def main():
    rng = np.random.default_rng(2029)
    print(f"CRC: {'命令' if F.HW_CRC else '表'}")
    for fmt in ("f32", "u64", "both"):
        res = {}
        for name, lazy, fast in (("Python", False, False), ("--fast", False, True), ("--fast-ring", True, True)):
            r = fake_ring()
            fill(r, 6, np.random.default_rng(7))
            be = make_be(r, lazy)
            a = make_acq(be, fmt, fast)
            run(be, a)
            res[name] = (a.got, be, a)
        ref = res["Python"][0]
        nwant = 12 * (2 if fmt == "both" else 1)
        check(f"fmt {fmt}: Python の道の記録 {len(ref)} 本（期待 {nwant}）", len(ref) == nwant)
        for name in ("--fast", "--fast-ring"):
            got = res[name][0]
            same = len(got) == len(ref) and all(g[0] == f[0] and g[1] == f[1] for g, f in zip(got, ref))
            check(f"fmt {fmt}: {name} = Python（頭・中身・CRC）", same, f"{len(got)} 本")
        be = res["--fast-ring"][1]
        check(f"fmt {fmt}: --fast-ring で写した残り 0・ring_crc 0", be.n_mat == 0 and be.ring_crc == 0, f"n_mat {be.n_mat}・ring_crc {be.ring_crc}")

    # R の進め方: LazyRec を渡した間は R_R を書かない・release で読んだ所まで
    r = fake_ring(); fill(r, 3, rng)
    be = make_be(r, True)
    n0 = r.m.n_wr_r
    be.pump()
    check("pump（lazy）の後は R_R を書かない・hold", r.m.n_wr_r == n0 and r.hold, f"R_R の書き {r.m.n_wr_r - n0} 回・hold {r.hold}")
    check("列は LazyRec", all(isinstance(x[2], PR.LazyRec) for j in A.G2_WIN for x in be.q[j]) and sum(len(be.q[j]) for j in A.G2_WIN) == 6)
    # 使い切れなかった分（poll しない）→ release で写す・CRC を照らす・R を進める
    pays = [x[2].view().copy() for j in A.G2_WIN for x in be.q[j]]
    be.release()
    after = [x[2] for j in A.G2_WIN for x in be.q[j]]
    check("release: 残り 6 個を写して ndarray に・中身が同じ", be.n_mat == 6 and all(isinstance(x, np.ndarray) and np.array_equal(x, y) for x, y in zip(after, pays)))
    check("release: R_R = 読んだ所・hold が落ちる", r.m.regs[PR.R_R] == r.r and not r.hold, f"R_R {r.m.regs[PR.R_R]}・r {r.r}")
    r.a64[:] = 0                                    # R を進めた後に PL が上書きした（形だけ）
    check("release の後に上書きされても、写した中身は変わらない", all(np.array_equal(x, y) for x, y in zip(after, pays)))
    be2 = make_be(fake_ring(), False)
    be2.ring.m.regs[PR.R_W] = 0
    n0 = be2.ring.m.n_wr_r
    be2.pump()
    check("lazy でない pump は今までどおり R_R を書く", be2.ring.m.n_wr_r == n0 + 1)

    # 陽性対照: PL のレコードの中身を 1 バイト壊す（CRC は壊す前の値のまま）
    for name, lazy, fast in (("Python", False, False), ("--fast-ring", True, True)):
        r = fake_ring(); fill(r, 3, np.random.default_rng(9))
        # 窓 A0 の 2 個目の SPEC の中身の真ん中を壊す
        p = 0; k = 0
        while True:
            h0 = int(r.a64[p >> 3]); pb = int(r.a64[(p >> 3) + 7]) & 0xFFFFFFFF
            if (h0 >> 40) & 0xFF == PR.TYPE_SPEC and (h0 >> 48) & 0xFF == 0:
                k += 1
                if k == 2:
                    r.a8[p + 64 + pb // 2] ^= 0x10
                    break
            p += 64 + pb + 64
        be = make_be(r, lazy); a = make_acq(be, "f32", fast)
        run(be, a)
        j0 = A.G2_WIN[0]
        check(f"陽性対照 {name}: 壊したレコードは記録しない（A0 2 本・B0 3 本）・ring_crc 1・miss 1",
              len(a.got) == 5 and be.ring_crc == 1 and a.n_miss[j0] == 1, f"記録 {len(a.got)}・ring_crc {be.ring_crc}・miss {a.n_miss[j0]}")
    # 陽性対照: 使い切れずに写した分（materialize）でも壊れを捕まえる
    r = fake_ring(); fill(r, 2, np.random.default_rng(11))
    be = make_be(r, True); be.pump()
    x = be.q[A.G2_WIN[1]][0][2]
    r.a8[x.p + 64 + 100] ^= 0x01
    be.release()
    check("陽性対照: 写すとき（release）に壊れを捕まえて捨てる", be.ring_crc == 1 and len(be.q[A.G2_WIN[1]]) == 1 and be.n_mat == 4,
          f"ring_crc {be.ring_crc}・B0 の残り {len(be.q[A.G2_WIN[1]])}・写した {be.n_mat}")
    # 陽性対照: 切り捨て（--posctl-f32-trunc）は --fast-ring でも Python の f32_trunc と同じ・正の道とは違う
    outs = {}
    for name, lazy, fast in (("Python", False, False), ("--fast-ring", True, True)):
        r = fake_ring(); fill(r, 2, np.random.default_rng(13))
        be = make_be(r, lazy); a = make_acq(be, "f32", fast, trunc=True)
        run(be, a); outs[name] = a.got
    check("陽性対照: 切り捨ては --fast-ring = Python の f32_trunc", outs["Python"] == outs["--fast-ring"] and len(outs["Python"]) == 4)
    r = fake_ring(); fill(r, 2, np.random.default_rng(13))
    be = make_be(r, True); a = make_acq(be, "f32", True); run(be, a)
    check("陽性対照: 切り捨ては正の道と違う", all(g[1] != f[1] for g, f in zip(a.got, outs["--fast-ring"])))
    # 端をまたぐ（PAD）: リングを小さくして何周も回す
    r = fake_ring(size=1 << 21)
    tot = {"Python": [], "--fast-ring": []}
    for name, lazy, fast in (("Python", False, False), ("--fast-ring", True, True)):
        r = fake_ring(size=1 << 21)
        be = make_be(r, lazy); a = make_acq(be, "f32", fast)
        g = np.random.default_rng(17)
        for rnd in range(5):                        # 1 回に 1 組（512 KiB × 2）書いて読む。2 MiB のリングを何周も
            for c in (0, 1):
                put_rec(r, PR.TYPE_SPEC, c, 0, 1 + rnd, rnd, (1000 + rnd) * BASE, g.integers(0, 1 << 44, 65536, dtype=np.uint64))
            run(be, a)
        tot[name] = a.got
    check("端をまたいで何周も（PAD）: --fast-ring = Python", tot["Python"] == tot["--fast-ring"] and len(tot["Python"]) == 10)
    print(f"判定: {'OK' if not NG else 'NG'}" + (f"  落ちた: {NG}" if NG else ""))


if __name__ == "__main__":
    main()
