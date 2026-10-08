#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj021 手順 0 — PL を変えずに、PS（A53・Python）の量を測る（README の M-2〜M-5）

  sudo python3 bench_ps.py                      # 全部（M-2・M-3・M-4・M-5）。結果を runs/bench_ps.json に
  sudo python3 bench_ps.py --only m3 m4         # 一部だけ
  python3 bench_ps.py --no-pynq --quick         # PYNQ の無い計算機で道具の動きだけ確かめる（M-2 と cacheable=False は飛ばす）

M-2  CMA: /proc/meminfo の Cma と、pynq.allocate で取れる最大（16 MiB から倍々に、取れたら直ちに解放）
M-3  allocate したバッファを numpy で読む速さ。cacheable = True（読む前に invalidate）と False（キャッシュなし）
     読み方 3 通り: np.sum（読むだけ）・np.copyto（普通のメモリへ写す）・invalidate だけの時間
M-4  CRC-32（zlib.crc32）の速さ。普通のメモリと、allocate したバッファ（cacheable 両方）
M-5  束ねの 1 周: リングを模したバッファに 1 BASE（10.24 ms）ぶんのレコードを置き、
     invalidate → 頭と尾を読む → CRC-32 → u64 の和 → n_sum 個ごとに float32 に丸めて送り出しの CRC、を繰り返す。
     1 BASE あたりの時間（平均・p99・最大）を 10.24 ms と比べる。構成は INTERFACE.md の ② の表から:
       sam45fine  8 流れ × 4096 ch（n_sum 4 = 40.96 ms）
       2g         2 流れ × 65536 ch（n_sum 1）
       256m       4 流れ × 65536 ch（n_sum 2 = ネットワークの tint 20.48 ms、BITS.md の制限）
       spw6       24 流れ × 8192 ch（n_sum 1）
     **PL は使わない**（バッファに試験の値を書いて読む）。ソケットへは送らない（M-1 の iperf3 で別に測る）
     invalidate はバッファ全体にかかる（PYNQ の invalidate に範囲の指定が無い）。リングが大きいほど重くなるので、
     M-3 の「invalidate だけ」の時間と合わせて読む（HPC0 にすれば要らなくなる、が手順 0 で決めたいこと）
     陽性対照: --corrupt で 1 つのレコードの中身を 1 バイト壊し、不一致が周ごとに 1 件ずつ数えられることを確かめる

**specd を止めてから測る**（同じ A53 を取り合うと数が意味を持たない）。測る前に README の予言を書く。
"""
import argparse
import faulthandler
import json
import os
import struct
import sys
import time
import zlib

import numpy as np

BASE_S = 10.24e-3
MiB = 1 << 20
HDR, TRL = 64, 64
CONFIGS = {
    "sam45fine": dict(nstream=8, nch=4096, n_sum=4),
    "2g": dict(nstream=2, nch=65536, n_sum=1),
    "256m": dict(nstream=4, nch=65536, n_sum=2),
    "spw6": dict(nstream=24, nch=8192, n_sum=1),
}


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------ バッファ
class Buf:
    """pynq.allocate か、PYNQ が無いときは普通の numpy（cacheable=True 相当、invalidate は何もしない）"""

    def __init__(self, nbytes, cacheable, use_pynq):
        self.cacheable = cacheable
        if use_pynq:
            from pynq import allocate
            self.a = allocate(shape=(nbytes // 8,), dtype=np.uint64, cacheable=cacheable)
        else:
            self.a = np.zeros(nbytes // 8, np.uint64)
        self.pynq = use_pynq

    def invalidate(self):
        if self.pynq and self.cacheable:
            self.a.invalidate()

    def flush(self):
        if self.pynq and self.cacheable:
            self.a.flush()

    def free(self):
        if self.pynq:
            self.a.freebuffer()
        self.a = None


def rate(nbytes, dt):
    return nbytes / dt / 1e6


def timeit(fn, n):
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append(time.perf_counter() - t0)
    ts.sort()
    return ts[len(ts) // 2], ts[0], ts[-1]


# ------------------------------------------------------------------ M-2
def m2(args):
    out = {}
    try:
        with open("/proc/meminfo") as f:
            out["meminfo"] = {k.strip(): v.strip() for k, v in (l.split(":", 1) for l in f) if k.startswith("Cma")}
    except OSError as e:
        out["meminfo"] = str(e)
    log("M-2 /proc/meminfo:", out["meminfo"])
    if not args.pynq:
        log("M-2 allocate: --no-pynq なので飛ばす")
        return out
    ok, mib = 0, 16
    while mib <= args.cma_max_mib:
        try:
            b = Buf(mib * MiB, True, True)
            b.free()
            ok = mib
            log(f"M-2 allocate {mib} MiB: 取れた")
            mib *= 2
        except Exception as e:  # noqa: BLE001  取れなかった理由を残す
            log(f"M-2 allocate {mib} MiB: 取れない（{type(e).__name__}: {e}）")
            out["fail_at_mib"] = mib
            out["fail"] = f"{type(e).__name__}: {e}"
            break
    out["max_alloc_mib"] = ok
    return out


# ------------------------------------------------------------------ M-3・M-4
def m3m4(args, which):
    nbytes = args.buf_mib * MiB
    res = {}
    plain = np.arange(nbytes // 8, dtype=np.uint64)
    dst = np.empty_like(plain)
    if "m4" in which:
        med, lo, hi = timeit(lambda: zlib.crc32(plain), args.rep)
        res["m4_plain_crc32_MBps"] = rate(nbytes, med)
        log(f"M-4 普通のメモリ  crc32  {rate(nbytes, med):8.1f} MB/s（中央値、{args.rep} 回）")
    for cacheable in ([True, False] if args.pynq else [True]):
        tag = "cache" if cacheable else "nocache"
        b = Buf(nbytes, cacheable, args.pynq)
        b.a[:] = plain
        b.flush()
        if "m3" in which:
            def rd():
                b.invalidate()
                return int(np.sum(b.a))
            med, _, _ = timeit(rd, args.rep)
            res[f"m3_{tag}_sum_MBps"] = rate(nbytes, med)
            def cp():
                b.invalidate()
                np.copyto(dst, b.a)
            med2, _, _ = timeit(cp, args.rep)
            res[f"m3_{tag}_copy_MBps"] = rate(nbytes, med2)
            line = f"M-3 {tag:8s} sum {rate(nbytes, med):8.1f} MB/s  copy {rate(nbytes, med2):8.1f} MB/s"
            if cacheable and args.pynq:
                med3, _, _ = timeit(b.invalidate, args.rep)
                res[f"m3_{tag}_invalidate_ms"] = med3 * 1e3
                line += f"  invalidate だけ {med3 * 1e3:.2f} ms / {args.buf_mib} MiB"
            log(line)
            # 照合（読めた中身が書いた値と同じ）
            b.invalidate()
            if not np.array_equal(b.a, plain):
                log(f"M-3 {tag}: **読んだ中身が書いた値と違う**")
                res[f"m3_{tag}_mismatch"] = True
        if "m4" in which:
            def crc():
                b.invalidate()
                return zlib.crc32(b.a)
            med, _, _ = timeit(crc, args.rep)
            res[f"m4_{tag}_crc32_MBps"] = rate(nbytes, med)
            log(f"M-4 {tag:8s} crc32  {rate(nbytes, med):8.1f} MB/s")
        b.free()
    return res


# ------------------------------------------------------------------ M-5
def build_ring(b, cfg, nbase, rng):
    """1 BASE ぶん（nstream 個）のレコードを nbase 回ぶん並べ、CRC を正しく付ける。戻り: レコードの (位置, 長さ) の表"""
    nstream, nch = cfg["nstream"], cfg["nch"]
    plen = nch * 8
    rlen = HDR + plen + TRL
    u8 = b.a.view(np.uint8)
    recs = []
    pos = 0
    for k in range(nbase):
        for s in range(nstream):
            seq = k
            hdr = np.zeros(HDR, np.uint8)
            struct.pack_into("<4sBBBB", hdr, 0, b"S45R", 1, 1, 0, s)
            struct.pack_into("<II", hdr, 8, seq, k)
            struct.pack_into("<I", hdr, 56, plen)
            u8[pos:pos + HDR] = hdr
            pay = rng.integers(0, 1 << 40, nch, dtype=np.uint64)
            u8[pos + HDR:pos + HDR + plen] = pay.view(np.uint8)
            c = zlib.crc32(u8[pos:pos + HDR + plen])
            trl = np.zeros(TRL, np.uint8)
            struct.pack_into("<4sII", trl, 0, b"S45E", seq, c)
            u8[pos + HDR + plen:pos + rlen] = trl
            recs.append((pos, rlen))
            pos += rlen
    b.flush()
    return recs, pos


def m5(args):
    res = {}
    rng = np.random.default_rng(1)
    for name in args.configs:
        cfg = CONFIGS[name]
        nstream, nch, n_sum = cfg["nstream"], cfg["nch"], cfg["n_sum"]
        rlen = HDR + nch * 8 + TRL
        per_base = nstream * rlen
        nbase = max(4, min(args.m5_bases, (args.buf_mib * MiB) // per_base))
        nbase -= nbase % n_sum
        b = Buf(nbase * per_base, True, args.pynq)
        recs, _ = build_ring(b, cfg, nbase, rng)
        u8 = b.a.view(np.uint8)
        if args.corrupt:
            pos0 = recs[0][0] + HDR + 8
            u8[pos0] ^= 0x01
            b.flush()
        acc = [np.zeros(nch, np.uint64) for _ in range(nstream)]
        ts, bad = [], 0
        for rep in range(args.m5_rep):
            for k in range(nbase):
                t0 = time.perf_counter()
                b.invalidate()                    # PL が書いた後の [R, W) を読む前（4.1 の PS の責任）。実際はその範囲だけ
                for s in range(nstream):
                    pos, rl = recs[k * nstream + s]
                    hdr = u8[pos:pos + HDR]
                    plen = struct.unpack_from("<I", hdr, 56)[0]
                    trl = u8[pos + HDR + plen:pos + rl]
                    m1, seq1 = struct.unpack_from("<4sI", hdr, 0)[0], struct.unpack_from("<I", hdr, 8)[0]
                    m2_, seq2, c = struct.unpack_from("<4sII", trl, 0)
                    if args.crc and zlib.crc32(u8[pos:pos + HDR + plen]) != c:
                        bad += 1
                    if m1 != b"S45R" or m2_ != b"S45E" or seq1 != seq2:
                        bad += 1
                    pay = u8[pos + HDR:pos + HDR + plen].view(np.uint64)
                    if k % n_sum == 0:
                        np.copyto(acc[s], pay)
                    else:
                        acc[s] += pay
                    if k % n_sum == n_sum - 1:
                        f = acc[s].astype(np.float32)   # 4.5: 束ねた u64 を最も近い float32 に
                        zlib.crc32(f)                   # 送り出しの CRC（s45proto の頭）
                ts.append(time.perf_counter() - t0)
        # 2026-10-08: バッファを解放する前に、そのバッファを指す numpy の view を全部手放す
        # （view が残ったまま freebuffer すると、後で view が消えるときに解放済みの領域を触る疑い）
        del u8, hdr, trl, pay, recs
        b.free()
        a = np.array(ts) * 1e3
        r = dict(nstream=nstream, nch=nch, n_sum=n_sum, MBps_per_base=per_base / BASE_S / 1e6,
                 mean_ms=float(a.mean()), p99_ms=float(np.percentile(a, 99)), max_ms=float(a.max()),
                 load=float(a.mean() / (BASE_S * 1e3)), crc_checked=args.crc, bad=bad, n=len(a))
        res[name] = r
        log(f"M-5 {name:9s} {nstream:2d} 流れ × {nch:6d} ch（{r['MBps_per_base']:6.1f} MB/s）n_sum {n_sum}: "
            f"1 BASE 平均 {r['mean_ms']:6.2f} ms・p99 {r['p99_ms']:6.2f}・最大 {r['max_ms']:6.2f} ms"
            f"（10.24 ms の {100 * r['load']:.0f} %）CRC {'あり' if args.crc else 'なし'}・不一致 {bad}")
    return res


def main():
    faulthandler.enable()          # 2026-10-08: M-5 が traceback なしに sam45fine の後で止まった。落ちたら場所を stderr に出す
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="+", choices=["m2", "m3", "m4", "m5"], default=["m2", "m3", "m4", "m5"])
    p.add_argument("--no-pynq", dest="pynq", action="store_false", help="PYNQ の無い計算機で道具を確かめる")
    p.add_argument("--quick", action="store_true", help="量を減らす（道具の確かめ用）")
    p.add_argument("--buf-mib", type=int, default=64, help="M-3・M-4・M-5 のバッファ（MiB）")
    p.add_argument("--rep", type=int, default=7, help="M-3・M-4 の繰り返し（中央値を取る）")
    p.add_argument("--cma-max-mib", type=int, default=2048)
    p.add_argument("--configs", nargs="+", choices=list(CONFIGS), default=list(CONFIGS))
    p.add_argument("--m5-bases", type=int, default=40, help="M-5 のバッファに並べる BASE の数（バッファに入る分まで）")
    p.add_argument("--m5-rep", type=int, default=5, help="M-5 でバッファを何周するか")
    p.add_argument("--no-crc", dest="crc", action="store_false", help="M-5 でレコードの CRC を確かめない（間引いたときの見当）")
    p.add_argument("--corrupt", action="store_true", help="M-5 の陽性対照: レコード 1 つの中身を 1 バイト壊す（不一致 = 周の数になるはず）")
    p.add_argument("--out", default="runs/bench_ps.json")
    args = p.parse_args()
    if args.quick:
        args.buf_mib, args.rep, args.m5_bases, args.m5_rep = 16, 3, 8, 1
    res = dict(args={k: v for k, v in vars(args).items()}, time_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               python=sys.version.split()[0], numpy=np.__version__, zlib=zlib.ZLIB_RUNTIME_VERSION)
    try:
        with open("/proc/cpuinfo") as f:
            res["cpu"] = sorted({l.split(":", 1)[1].strip() for l in f if l.startswith(("model name", "CPU part"))})
    except OSError:
        pass
    if "m2" in args.only:
        res["m2"] = m2(args)
    if {"m3", "m4"} & set(args.only):
        res.update(m3m4(args, set(args.only)))
    if "m5" in args.only:
        res["m5"] = {}
        for name in args.configs:          # 構成ごとに。1 つが落ちても残りを測り、結果を残す
            a1 = argparse.Namespace(**{**vars(args), "configs": [name]})
            try:
                res["m5"].update(m5(a1))
            except Exception as e:  # noqa: BLE001  落ちた理由を結果に残す
                log(f"M-5 {name}: 落ちた（{type(e).__name__}: {e}）")
                res["m5"][name] = dict(error=f"{type(e).__name__}: {e}")
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    log(f"→ {args.out}")


if __name__ == "__main__":
    main()
