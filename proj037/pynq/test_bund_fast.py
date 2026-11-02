#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj036: --fast-ring の束ね（n_sum ≧ 2 の FULL を、リングの上から C で器へ写す・足す）の PL なしの照合。どこでも回る（numpy と libs45fast.so）

PL の形のレコードを numpy の配列のリングに書き（test_ring_fast.py の道具）、本物の plring.Ring.read・G22Backend.pump・poll_win・release・
Bundler・Acq._spec_record_full に通して、今までの道（写す・numpy で足す・Python で記録）と bytes で照らす。
  python3 test_bund_fast.py        # 判定は最後の「判定: OK / NG」
"""
import numpy as np

import plring as PR
import s45acq as A
import s45fast as F
from test_ring_fast import BASE, check, fake_ring, make_acq, make_be, put_rec, NG

CF0 = dict(src=2, shift=7, nacc=160, if_mhz=2000.015625, df_hz=31250.0, ds=1, frame=8192, kind="full")


def fill(r, nrec, seed, nch=65536, t0=996 * BASE, n_of=None, seq0=0):
    """窓 A0・B0（コア 0・1）に交互に SPEC を nrec 個ずつ（BASE ごと）、間に小さい TP。和が 2^53 を越えない大きさ"""
    rng = np.random.default_rng(seed)
    for k in range(nrec):
        for c in (0, 1):
            pay = rng.integers(0, 1 << 44, nch, dtype=np.uint64)
            pay[0], pay[-1] = (1 << 24) + 1, (1 << 51) - 1
            put_rec(r, PR.TYPE_SPEC, c, 0, seq0 + 1 + k, seq0 + k, t0 + k * BASE, pay, n=160 if n_of is None else n_of(c, k))
            put_rec(r, PR.TYPE_TP, c, 0xFF, seq0 + 1 + k, 0, 0, rng.integers(0, 1 << 30, 32, dtype=np.uint64))


def run(be, a, bund, n_sum, n_poll=64):
    """pump → 窓ごとに poll_win → Bundler → _spec_record_full → release（Acq._loop_once の窓の部分と同じ並び。CRC の数え方も同じ）"""
    be.pump()
    cf = dict(CF0, n_sum=n_sum)
    for j in A.G2_WIN:
        bu = bund[j]
        for _ in range(n_poll):
            x = be.poll_win(j)
            if x is None:
                break
            m, spec, miss = x
            a.n_miss[j] += miss
            cb0 = bu.crc_bad
            got, dropped = bu.add(m, spec)
            if bu.crc_bad != cb0:
                be.ring_crc += 1
                a.n_miss[j] += 1
            if dropped is not None:
                a.bdrop.append((j, dropped[1]))
            if got is None:
                continue
            mm, sp = got
            a._spec_record_full(j, mm, sp, cf, 0)
    be.release()


WAYS = (("Python", False, False), ("--fast", False, True), ("--fast-ring", True, True))


def go(name, lazy, fast, fmt, n_sum, nrec, seed, rounds=1, size=64 << 20, posctl=0, corrupt=None, n_of=None):
    r = fake_ring(size)
    be = make_be(r, lazy)
    a = make_acq(be, fmt, fast)
    a.bdrop = []
    bund = {j: A.Bundler(n_sum, 160, fast=F if lazy else None, posctl=posctl) for j in A.G2_WIN}
    for rnd in range(rounds):
        fill(r, nrec, seed + rnd, t0=(996 + rnd * nrec) * BASE, n_of=n_of, seq0=rnd * nrec)
        if corrupt is not None:
            corrupt(r)
        run(be, a, bund, n_sum)
    return a, be, bund


def corrupt_a0(nth):
    """窓 A0 の nth 個目の SPEC の中身を 1 バイト壊す（尾の CRC は壊す前のまま）"""
    def f(r):
        p = k = 0
        while p < r.w:
            h0 = int(r.a64[p >> 3]); pb = int(r.a64[(p >> 3) + 7]) & 0xFFFFFFFF
            if (h0 >> 40) & 0xFF == PR.TYPE_SPEC and (h0 >> 48) & 0xFF == 0:
                k += 1
                if k == nth:
                    r.a8[p + 64 + pb // 2] ^= 0x10
                    return
            p += 64 + pb + 64
    return f


def main():
    print(f"CRC: {'命令' if F.HW_CRC else '表'}")
    for n_sum in (2, 3):
        nrec = 6 * n_sum                       # 束 6 個（996 は 2・3 の倍数なので頭がそろう）
        for fmt in ("f32", "u64", "both"):
            res = {name: go(name, lazy, fast, fmt, n_sum, nrec, 7) for name, lazy, fast in WAYS}
            ref = res["Python"][0].got
            nwant = 12 * (2 if fmt == "both" else 1)
            check(f"n_sum {n_sum} fmt {fmt}: Python の道の記録 {len(ref)} 本（期待 {nwant}）", len(ref) == nwant)
            for name in ("--fast", "--fast-ring"):
                got = res[name][0].got
                same = len(got) == len(ref) and all(g[0] == f[0] and g[1] == f[1] for g, f in zip(got, ref))
                check(f"n_sum {n_sum} fmt {fmt}: {name} = Python（頭・中身・CRC）", same, f"{len(got)} 本")
            be = res["--fast-ring"][1]
            check(f"n_sum {n_sum} fmt {fmt}: --fast-ring で写した残り 0・ring_crc 0・束ねは C の器",
                  be.n_mat == 0 and be.ring_crc == 0 and all(res["--fast-ring"][2][j].buf is not None for j in A.G2_WIN),
                  f"n_mat {be.n_mat}・ring_crc {be.ring_crc}")

    # 束の頭がそろわない始まり（997 から）・途中の欠け（N の違い）も今までの道と同じに捨てる
    for n_sum in (2, 3):
        odd = lambda c, k: 159 if (c == 1 and k == 4) else 160            # B0 の 5 個目の DUMP_N が違う → その束は "N"
        res = {}
        for name, lazy, fast in (WAYS[0], WAYS[2]):
            r = fake_ring(64 << 20); be = make_be(r, lazy); a = make_acq(be, "f32", fast); a.bdrop = []
            bund = {j: A.Bundler(n_sum, 160, fast=F if lazy else None) for j in A.G2_WIN}
            fill(r, 4 * n_sum + 1, 21, t0=997 * BASE, n_of=odd)
            run(be, a, bund, n_sum)
            res[name] = a
        p, q = res["Python"], res["--fast-ring"]
        check(f"n_sum {n_sum}: 頭のずれ・N の違いの捨て方が同じ（記録・BDROP の理由）",
              p.got == q.got and sorted(p.bdrop) == sorted(q.bdrop) and len(p.got) > 0,
              f"記録 {len(p.got)} / {len(q.got)}・BDROP {sorted(p.bdrop)} / {sorted(q.bdrop)}")

    # 陽性対照: 足さずに写す（posctl 1）→ Python と違う
    ref = go("Python", False, False, "f32", 3, 18, 7)[0].got
    bad = go("noacc", True, True, "f32", 3, 18, 7, posctl=F.PC_NOACC)[0].got
    check("陽性対照: 足さずに写す（--posctl-noacc）は Python と違う（全部の記録）",
          len(bad) == len(ref) and all(g[1] != f[1] for g, f in zip(bad, ref)), f"{len(bad)} 本")

    # 陽性対照: レコードを 1 バイト壊す → その束を記録しない・ring_crc 1・読み落とし 1（今までの道と同じ記録）
    for n_sum in (2, 3):
        res = {name: go(name, lazy, fast, "f32", n_sum, 4 * n_sum, 9, corrupt=corrupt_a0(n_sum + 1)) for name, lazy, fast in (WAYS[0], WAYS[2])}
        (pa, pbe, _), (qa, qbe, _) = res["Python"], res["--fast-ring"]
        j0 = A.G2_WIN[0]
        check(f"陽性対照 n_sum {n_sum}: 壊した 1 本の束を記録しない（A0 3 束・B0 4 束）・ring_crc 1・読み落とし 1・記録は Python と同じ",
              len(qa.got) == 7 and qbe.ring_crc == 1 and qa.n_miss[j0] == 1 and qa.got == pa.got and pbe.ring_crc == 1,
              f"記録 {len(qa.got)}・ring_crc {qbe.ring_crc}（Python {pbe.ring_crc}）・miss {qa.n_miss[j0]}・同じ {qa.got == pa.got}")

    # 端をまたぐ（PAD）・器の使い回し: 2 MiB のリングで何周も（1 回に束 1 個ぶん = 512 KiB × n_sum × 2）
    for n_sum in (2, 3):
        res = {name: go(name, lazy, fast, "f32", n_sum, n_sum, 17, rounds=6, size=1 << 22) for name, lazy, fast in (WAYS[0], WAYS[2])}
        p, q = res["Python"][0].got, res["--fast-ring"][0].got
        check(f"n_sum {n_sum}: 端をまたいで何周も（PAD）・器を使い回して = Python", p == q and len(p) == 12, f"{len(p)} / {len(q)} 本")
    print(f"判定: {'OK' if not NG else 'NG'}" + (f"  落ちた: {NG}" if NG else ""))


if __name__ == "__main__":
    main()
