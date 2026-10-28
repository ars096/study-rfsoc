#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj032 D-3 — PL から PS の DDR へ、HP の口 4 本（ADC ごと）で同時に書けるかを測る（ボードの上で。proj032d3.bit・.hwh と同じ場所に置く）。

  sudo python3 hp_bw.py [--bit proj032d3.bit] [--out hp_bw.json] [--sec 10]

K-1（README）: ダンプの受け手は、f32 にしたダンプを ADC ごとに HP の口 1 本で PS の DDR のリングへ書く。
4 ADC の区切りはそろうので、山では 4 本が同時に書く。機関ごとに URAM 1 つ（32 KiB）の溜めで足りるのは、口 1 本が 2 GB/s 出るとき。

試験（clk_dsp 256 MHz の拍で数える。1 拍 = 16 B、2 GB/s = 0.488 拍 / クロック）:
  T0 中身: 4 本とも 1 回ずつ書いて、PS で全部の拍を式と照らす（不一致 0）
  T1 1 本だけ・上限なし（BL 16・64・256 拍 = 256 B・1 KiB・4 KiB）: 口 1 本の天井（情報）
  T2 4 本同時・上限なし（同じ BL）: 4 本の天井（情報）
  T3 本番の形: 4 本同時に 2 GB/s ずつ、--sec 秒 → 達した速さ ≧ 99.9 %・FLAGS 0（合否）。溜めの最大も
  T4 ダンプの山の形: 4 本同時に、10.24 ms ごとに最初の 74.7 µs だけ 3.07 GB/s（f32 の 3 機関 = 0.75 拍 / クロック。
     1 ADC の 14 窓 × 16 KiB = 224 KiB を 19,115 クロックで）→ 溜めの最大（合否: ≦ 96 KiB = 機関 3 つ × URAM 1 つ）
  T5 余裕: 4 本同時に 2.5・3.0・3.5 GB/s ずつ（情報）
予言: PS の DDR4 は DDR4-1600・64 bit（build.tcl の読み返し）で天井 12.8 GB/s。HP の口 1 本は 128 bit × 256 MHz = 4.1 GB/s。
  T3（合計 8.2 GB/s = 天井の 64 %）は通過。T2 の 4 本の天井は 9〜11 GB/s。T4 の溜めは 64 KiB 前後
"""
import argparse
import json
import sys
import time

import numpy as np

F = 256e6
BEAT = 16
NHP = 4
ID_WANT = 0x03200D31
CM_ID = 0x028000C1
MIB = 1 << 20

R = dict(ID=0x00, CTRL=0x04, BL=0x08, RATE=0x0C, BASE_LO=0x10, BASE_HI=0x14, SIZE=0x18, SEED=0x1C, DUR=0x20, ON=0x24,
         PERIOD=0x28, OUTS=0x2C, STATUS=0x40, FLAGS=0x44, CYC=0x48, WR_BEATS=0x50, B_CNT=0x58, WR_WAIT=0x60,
         BACKLOG_MAX=0x68, AW_WAIT=0x6C, LAT_MAX=0x70)


def rate(gbs):
    return min(65536, round(gbs * 1e9 / (BEAT * F) * 65536))


def gbs_of(rt):
    """RATE の値で実際に入る速さ（丸めの後）"""
    return rt * BEAT * F / 65536 / 1e9


class TG:
    def __init__(self, mmio):
        self.m = mmio

    def w(self, k, v):
        self.m.write(R[k], int(v) & 0xFFFFFFFF)

    def r(self, k):
        return self.m.read(R[k])

    def r64(self, k):
        lo = self.m.read(R[k])
        return (self.m.read(R[k] + 4) << 32) | lo

    def setup(self, base, size, seed, bl, rt, dur, on=0, per=0, outs=8):
        self.w("CTRL", 0)
        self.w("BL", bl - 1); self.w("RATE", rt)
        self.w("BASE_LO", base & 0xFFFFFFFF); self.w("BASE_HI", base >> 32); self.w("SIZE", size)
        self.w("SEED", seed); self.w("DUR", dur); self.w("ON", on); self.w("PERIOD", per); self.w("OUTS", outs)

    def done(self):
        return (self.r("STATUS") >> 3) & 1

    def result(self):
        cyc = self.r64("CYC")
        out = dict(cyc=cyc, wr_beats=self.r64("WR_BEATS"), b_cnt=self.r64("B_CNT"), wr_wait=self.r64("WR_WAIT"),
                   backlog_max=self.r("BACKLOG_MAX"), aw_wait=self.r("AW_WAIT"), lat_max=self.r("LAT_MAX"), flags=self.r("FLAGS"))
        out["gbs"] = out["wr_beats"] * BEAT / (cyc / F) / 1e9 if cyc else 0.0
        out["backlog_kib"] = out["backlog_max"] * BEAT / 1024
        return out


def run(tgs, bufs, which, bl, rt, sec, seed, on=0, per=0, outs=8):
    dur = int(sec * F)
    for i in which:
        tgs[i].setup(bufs[i].device_address, bufs[i].nbytes, seed + i, bl, rt, dur, on, per, outs)
    for i in which:                                       # 起動は続けて（数 µs のずれ）
        tgs[i].w("CTRL", 1)
    t0 = time.time()
    while not all(tgs[i].done() for i in which):
        if time.time() - t0 > sec * 3 + 10:
            raise RuntimeError("hp_tg が終わらない")
        time.sleep(0.01)
    res = {i: tgs[i].result() for i in which}
    for i in which:
        tgs[i].w("CTRL", 0)
    return res


def check(buf, seed, nbeat):
    """書いた先頭 nbeat 拍を式と照らす。戻り値: 不一致の拍の数"""
    buf.invalidate()
    w = np.asarray(buf).view(np.uint32)[: nbeat * 4].reshape(-1, 4)
    a = ((buf.device_address >> 4) + np.arange(nbeat, dtype=np.uint64)) & 0xFFFFFFFF
    x = (a.astype(np.uint32) ^ np.uint32(seed))
    e = np.stack([x, x ^ np.uint32(0x01010101), x ^ np.uint32(0x02020202), ~(x ^ np.uint32(0x03030303))], axis=1)
    return int(np.count_nonzero((w != e).any(axis=1)))


def bring_up(bit):
    from pynq import MMIO, Overlay
    ol = Overlay(bit)
    ipc = ol.ip_dict["clk_mon_0"]
    cm = MMIO(ipc["phys_addr"], ipc["addr_range"])
    cid = cm.read(0x00)
    if cid != CM_ID:
        print("ERROR: clk_mon の ID 0x%08x（proj032 D-3 の .bit か確かめる）" % cid); sys.exit(1)
    win_s = cm.read(0x10) / 100e6
    t0 = time.time()
    while not (cm.read(0x04) & 4):
        if time.time() - t0 > 5:
            print("ERROR: clk_mon の窓が回らない"); sys.exit(1)
        time.sleep(0.1)
    time.sleep(win_s + 0.1)
    st = cm.read(0x04)
    f_mhz = cm.read(0x08) * 16 / win_s / 1e6
    locked, rst = st & 1, (st >> 1) & 1
    print("clk_mon: clk_dsp %.3f MHz・locked %d・rst_dsp %s" % (f_mhz, locked, "中" if rst else "明け"))
    if not (255 < f_mhz < 257) or not locked or rst:
        print("ERROR: clk_dsp が 256 MHz で回っていないか、リセットが明けない。hp_tg には触らずに止める"); sys.exit(1)
    tgs = []
    for i in range(NHP):
        ip = ol.ip_dict["hp_tg_%d" % i]
        tg = TG(MMIO(ip["phys_addr"], ip["addr_range"]))
        if tg.r("ID") != ID_WANT:
            print("ERROR: hp_tg_%d の ID 0x%08x" % (i, tg.r("ID"))); sys.exit(1)
        tgs.append(tg)
    print("hp_tg × %d: ID 0x%08x" % (NHP, ID_WANT))
    return tgs, dict(bit=bit, clk_dsp_mhz=f_mhz)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bit", default="proj032d3.bit")
    ap.add_argument("--out", default="hp_bw.json")
    ap.add_argument("--sec", type=float, default=10.0)
    ap.add_argument("--mib", type=int, default=16, help="口ごとのリングの大きさ")
    a = ap.parse_args()
    from pynq import allocate
    tgs, res = bring_up(a.bit)
    bufs = [allocate(shape=(a.mib * MIB,), dtype=np.uint8, cacheable=True) for _ in range(NHP)]
    for i, b in enumerate(bufs):
        if b.device_address & 0xFFF:
            print("ERROR: バッファ %d が 4 KiB 揃えでない" % i); sys.exit(1)
        print("リング %d: 0x%x + %d MiB" % (i, b.device_address, a.mib))
    seed = 0x5B320300
    allok = True
    res["runs"] = []

    def rec(name, r, extra=None):
        for i, v in r.items():
            res["runs"].append(dict(v, name=name, port=i, **(extra or {})))

    # T0 中身（上限なし 1 ms: 口 1 本で ≦ 4.1 MB < リング）
    r = run(tgs, bufs, range(NHP), 16, 65536, 1e-3, seed)
    bad = [check(bufs[i], seed + i, int(r[i]["wr_beats"])) for i in range(NHP)]
    ok = all(b == 0 for b in bad) and all(v["flags"] & 2 == 0 for v in r.values())
    allok &= ok
    print("T0 中身: 拍 %s・不一致 %s → %s" % ([int(v["wr_beats"]) for v in r.values()], bad, "○" if ok else "×"))
    rec("T0", r, dict(bad=bad))

    def line(name, r, target=None):
        tot = sum(v["gbs"] for v in r.values())
        s = "・".join("%.3f" % v["gbs"] for v in r.values())
        bk = max(v["backlog_kib"] for v in r.values())
        lat = max(v["lat_max"] for v in r.values())
        fl = max(v["flags"] & 2 for v in r.values())
        ok = None
        if target is not None:
            ok = all(v["gbs"] >= 0.999 * target for v in r.values()) and fl == 0
        print("%-28s 口ごと %s GB/s・合計 %6.3f・溜めの最大 %7.1f KiB・B の待ち最大 %5d クロック・BRESP %s%s"
              % (name, s, tot, bk, lat, "×" if fl else "0", "" if ok is None else " → " + ("○" if ok else "×")))
        return ok

    for bl in (16, 64, 256):
        r = run(tgs, bufs, [0], bl, 65536, 1.0, seed); line("T1 1 本・BL %d" % bl, r); rec("T1", r, dict(bl=bl))
    for bl in (16, 64, 256):
        r = run(tgs, bufs, range(NHP), bl, 65536, 1.0, seed); line("T2 4 本・BL %d" % bl, r); rec("T2", r, dict(bl=bl))
    for bl in (16, 64):
        r = run(tgs, bufs, range(NHP), bl, rate(2.0), a.sec, seed)
        ok = line("T3 本番 2 GB/s × 4・BL %d" % bl, r, gbs_of(rate(2.0))); allok &= ok; rec("T3", r, dict(bl=bl))
    # T4 ダンプの山: 0.75 拍 / クロック × 19,115 クロック、周期 10.24 ms
    for bl in (16, 64):
        r = run(tgs, bufs, range(NHP), bl, 49152, a.sec, seed, on=19115, per=2621440)
        bk = max(v["backlog_kib"] for v in r.values())
        line("T4 山（3.07 GB/s × 74.7 µs）・BL %d" % bl, r)
        ok = bk <= 96 and all(v["flags"] & 2 == 0 for v in r.values())
        print("    溜めの最大 %.1f KiB（合否 ≦ 96 KiB）→ %s" % (bk, "○" if ok else "×"))
        allok &= ok; rec("T4", r, dict(bl=bl))
    for g in (2.5, 3.0, 3.5):
        r = run(tgs, bufs, range(NHP), 64, rate(g), min(a.sec, 3.0), seed)
        line("T5 %.1f GB/s × 4・BL 64" % g, r, gbs_of(rate(g))); rec("T5", r, dict(gbs=g))
    res["ok"] = bool(allok)
    print("結果: %s" % ("全部通過" if allok else "不合格あり"))
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)
    print("書いた: %s" % a.out)


if __name__ == "__main__":
    main()
