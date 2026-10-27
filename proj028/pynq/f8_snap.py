#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-8 — 荒い段の入口の生の標本（adc_snap_0、131,072 標本 = 32 µs）を取り、平均した電力スペクトルで f ± k·fs/56 の線を見る（ボードの上で）

  sudo -E $(which python3) f8_snap.py --bit proj028_f8.bit --clkin 0 --sg <SG> --f-mhz 1151.999442 --dbm 0 --n 64 --out f8_a

順序: クロック → Overlay → タイル・ID（adc_snap_0 を含む）→ 荒い段の利得 → SG（読み返し）→
  (1) idle: 荒い段だけ動いている（corner turn・細かい段は止めたまま）で --n 回
  (2) run : corner turn・細かい段・リングを RUN して（リングは読んで捨てる）--n 回
  (3) idle2: RUN を止めて --n 回（(1) と並べて、RUN の前後の違いと時刻の違いを分ける）
- 1 回ごとに: ARM → DONE → 溜め中の valid の欠け（0 でなければ捨てる）→ 65,536 語を読む（速い写しを、1 語ずつの読みの 256 点で確かめる）
- スペクトル: Blackman-Harris（4 項）で窓をかけ rfft、電力を平均（刻み 31.25 kHz）
- 保存: <out>.npz（状態ごとの平均の電力スペクトル・最初の 2 回の生の標本）・<out>.json（線の高さの表）
"""
import argparse
import json
import sys
import time

import numpy as np

import f5
import f5_seg
from f5 import Regs, Ring, log, NCH

FS = 4.096e9
NS = 131072
FO = FS / 56
ID_SNAP = 0x028000C8


def bh4(n):
    t = 2 * np.pi * np.arange(n) / n
    return 0.35875 - 0.48829 * np.cos(t) + 0.14128 * np.cos(2 * t) - 0.01168 * np.cos(3 * t)


class Snap:
    def __init__(self, ol):
        from pynq import MMIO
        ip = ol.ip_dict["adc_snap_0"]
        self.m = MMIO(ip["phys_addr"], ip["addr_range"])
        self.depth = int(self.m.read(0x0C))
        self.fast_ok = None

    def take(self):
        self.m.write(0x04, 1)
        t0 = time.time()
        while not int(self.m.read(0x04)) & 2:
            if time.time() - t0 > 1:
                raise RuntimeError("adc_snap: DONE が立たない")
        gap = int(self.m.read(0x14))
        nw = self.depth * 8
        base = 0x40000 // 4
        w = np.array(self.m.array[base:base + nw], dtype=np.uint32)
        if self.fast_ok is None:                          # 速い写しを 1 語ずつの読みと突き合わせる（初回だけ）
            idx = np.random.default_rng(0).integers(0, nw, 256)
            slow = np.array([int(self.m.read(0x40000 + 4 * int(i))) & 0xFFFFFFFF for i in idx], dtype=np.uint32)
            self.fast_ok = bool(np.array_equal(slow, w[idx]))
            log(f"adc_snap: 速い写しと 1 語ずつの読み（256 点）が{'一致' if self.fast_ok else '違う → 1 語ずつ読む'}")
        if not self.fast_ok:
            w = np.array([int(self.m.read(0x40000 + 4 * i)) & 0xFFFFFFFF for i in range(nw)], dtype=np.uint32)
        return w.view(np.int16).astype(np.float64), gap


def lines(P, f, df):
    """f と f ± k·FO（k = −8..8、0..fs/2 に折り返す）・f ± 512 MHz の高さ（線の ±4 bin の和、線に対して dB）と、そこの床"""
    def fold(x):
        x = x % FS
        return FS - x if x > FS / 2 else x

    def level(fx):
        b = int(round(fold(fx) / df))
        lo, hi = max(b - 4, 0), min(b + 5, len(P))
        loc = P[max(b - 2000, 0):b + 2000]
        return P[lo:hi].sum(), float(np.median(loc)) * 9
    pt, fl0 = level(f)
    out = dict(tone=10 * np.log10(pt), floor_rel=10 * np.log10(fl0 / pt))
    for k in list(range(-8, 0)) + list(range(1, 9)):
        p, fl = level(f + k * FO)
        out[f"k{k:+d}"] = (10 * np.log10(p / pt), 10 * np.log10(p / fl))
    for s in (-1, 1):
        p, fl = level(f + s * 512e6)
        out[f"i{s * 512:+d}"] = (10 * np.log10(p / pt), 10 * np.log10(p / fl))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bit", default="proj028_f8.bit")
    ap.add_argument("--clkin", default="0")
    ap.add_argument("--ref", type=float, default=10.0)
    ap.add_argument("--zone", type=int, default=1)
    ap.add_argument("--n", type=int, default=64)
    ap.add_argument("--sg", help="SG の HOST[:PORT]（無ければ SG に触らない）")
    ap.add_argument("--f-mhz", type=float, default=1151.999442)
    ap.add_argument("--dbm", type=float, default=0.0)
    ap.add_argument("--out", default="f8_a")
    a = ap.parse_args()

    from pynq import Overlay
    import xrfdc                                  # Overlay() より前
    f5.setup_clocks(a.clkin, a.ref)
    ol = Overlay(a.bit)
    log(f"Overlay: {a.bit}")
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない")
        return 1
    f5.check_tile(ol.rfdc, a.zone)
    f5.check_clk_mon(Regs(ol, "clk_mon_0"))
    if "adc_snap_0" not in ol.ip_dict:
        log("ERROR: adc_snap_0 が .hwh に無い（F-8 の .bit か確かめる）")
        return 1
    cs, ctw, ctr, ft = (Regs(ol, n) for n in ("coarse_stage_0", "ct_wr_0", "ct_rd_0", "fine_top_0"))
    sn = Snap(ol)
    for g, want in ((cs, f5.ID_CS), (ctw, f5.ID_CTW), (ctr, f5.ID_CTR), (ft, f5.ID_FT)):
        if g.rd(0) != want:
            log(f"ERROR: {g.name} の ID 0x{g.rd(0):08x}")
            return 1
    if int(sn.m.read(0)) != ID_SNAP or sn.depth != 8192:
        log(f"ERROR: adc_snap_0 の ID 0x{int(sn.m.read(0)):08x}・DEPTH {sn.depth}")
        return 1
    log("ID: 荒い段・ct_wr・ct_rd・fine_top・adc_snap とも一致（DEPTH 8192）")
    g, _, _ = f5.gain_cal(cs, 1 << 20, 256)
    sg = None
    if a.sg:
        from sg import SG
        sg = SG(a.sg, log=log)
        sg.set_freq_mhz(a.f_mhz)
        sg.set_dbm(a.dbm)
        sg.set_output(True)
        time.sleep(0.5)

    win = bh4(NS)
    df = FS / NS
    res = dict(bit=a.bit, clkin=a.clkin, f_mhz=a.f_mhz, dbm=a.dbm, n=a.n, gain=g.tolist(), sg=sg.state() if sg else None, states={})
    spectra, raw = {}, {}
    ring = None

    def collect(name):
        acc = np.zeros(NS // 2 + 1)
        pw, gaps, nok = [], 0, 0
        for i in range(a.n):
            x, gap = sn.take()
            if ring is not None:
                ring.read()                            # 読んで捨てる（リングを溢れさせない）
            if gap:
                gaps += 1
                continue
            if i < 2:
                raw.setdefault(name, []).append(x.astype(np.int16))
            pw.append(float(np.mean(x * x)))
            acc += np.abs(np.fft.rfft(x * win)) ** 2
            nok += 1
        P = acc / max(nok, 1)
        spectra[name] = P
        st = lines(P, a.f_mhz * 1e6, df) if sg else {}
        pw = np.array(pw)
        st.update(n_ok=nok, n_gap=gaps, pow_mean=float(pw.mean()), pow_cv=float(pw.std() / pw.mean()), pow=pw.tolist())
        res["states"][name] = st
        txt = (f"{name}: {nok} 回（欠けで捨てた {gaps}）・標本の電力 {pw.mean():.4g}（回ごとの σ {100 * pw.std() / pw.mean():.2f} %）")
        if sg:
            txt += (f"・線 {st['tone']:.1f} dB・床 {st['floor_rel']:+.1f} dB\n    " +
                    " ".join(f"{k}:{v[0]:+.1f}({v[1]:+.0f})" for k, v in st.items() if k.startswith(("k", "i")) and isinstance(v, tuple)))
        log(txt)

    try:
        collect("idle")
        f5_seg.configure(ctw, ctr, ft, 7)
        ring = Ring(Regs(ol, "s45_ring_0"), 64 << 20)
        ring.enable(True)
        ctr.wr(0x04, 1)
        ctw.wr(0x04, 1)
        time.sleep(1.0)
        collect("run")
        w = f5.watch(ctw, ctr, ft, ring)
        f5_seg.stop(ctw, ctr)
        ring.enable(False)
        ring.read()
        ring = None
        res["watch_run"] = w
        time.sleep(1.0)
        collect("idle2")
    finally:
        if sg:
            sg.close()
    np.savez_compressed(a.out + ".npz", **{f"P_{k}": v for k, v in spectra.items()}, **{f"x_{k}": np.array(v) for k, v in raw.items()})
    json.dump(res, open(a.out + ".json", "w"), indent=1, default=float)
    log(f"保存: {a.out}.npz・{a.out}.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
