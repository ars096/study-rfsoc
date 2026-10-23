#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 S-2 — PL DDR4 の帯域と容量を測る（ボードの上で。build/proj028.bit・.hwh と同じ場所に置く）。

  sudo python3 ddr_bw.py [--bit proj028.bit] [--out ddr_bw.json] [--quick]

1. **ddr_tg より先に clk_mon（pl_clk0 の側、MIG のクロックに依らない）を読む**: 参照クロック（200 MHz）と UI クロック（≒ 300 MHz）が
   回っているか、UI のリセットが明けたか、MIG の較正（init_calib_complete）が済んだか。どれかが駄目なら ddr_tg に触らずに止まる
   （2026-10-23 の 1 回目: 較正の前に ddr_tg を読み、応答が返らず PS ごと止まった）。それから ddr_tg の ID（0x02800001）を照らす
2. 容量: 区間 A（0 番地）と B（4 GiB 番地）に違う SEED で書き、A を読む（4 GB なら B が A に折り返して全部が不一致）
3. 8 GiB 全体を書いて読み返す（誤り 0 を確かめる）
4. 帯域: BL 16・64・256 拍 × 書きだけ・読みだけ・両方同時、各 1 s（UI クロックの拍で数える）
5. 本番の形: 書き 4.68 GB/s ＋ 読み 4.77 GB/s を同時に 10 s（速さの上限 WR_RATE・RD_RATE）。達した速さ ≧ 99.9 % と誤り 0
   （ddr_tg の許可は BL + 2 拍で頭打ちなので、DDR が追いつかないと許可が捨てられ、達した速さが目標を下回る。
    一時の遅れは高々 BL + 2 拍 ≒ 16 KiB で、corner turn の溜め 256 KiB に入る）

RFDC は載せていないので xrfdc・xrfclk は使わない。
"""
import argparse
import json
import sys
import time

F_UI = 1e12 / (833 * 4)              # MIG の UI クロック（tCK 833 ps、4:1）≒ 300.12 MHz
BEAT = 64                            # 512 bit
ID_WANT = 0x02800001
CM_ID = 0x028000C1
GIB = 1 << 30

R = dict(ID=0x00, CTRL=0x04, BL=0x08, WR_RATE=0x0C, RD_RATE=0x10, BASE_LO=0x14, BASE_HI=0x18, SIZE_LO=0x1C, SIZE_HI=0x20,
         SEED=0x24, DUR=0x28, STATUS=0x40, FLAGS=0x44, CYC=0x48, WR_BEATS=0x50, RD_BEATS=0x58, WR_WAIT=0x60, RD_ERR=0x68,
         FIRST_ERR=0x70)


class TG:
    def __init__(self, mmio):
        self.m = mmio

    def w(self, k, v):
        self.m.write(R[k], int(v) & 0xFFFFFFFF)

    def r(self, k):
        return self.m.read(R[k])

    def r64(self, k):
        lo = self.m.read(R[k])
        hi = self.m.read(R[k] + 4)
        return (hi << 32) | lo

    def status(self):
        s = self.r("STATUS")
        return dict(calib=s & 1, wr_busy=(s >> 1) & 1, rd_busy=(s >> 2) & 1, done=(s >> 3) & 1)

    def wait_idle(self, timeout=120.0):
        t0 = time.time()
        while True:
            s = self.status()
            if not s["wr_busy"] and not s["rd_busy"] and (s["done"] or not (self.r("CTRL") & 3)):
                return
            if time.time() - t0 > timeout:
                raise RuntimeError("ddr_tg が終わらない: %s" % s)
            time.sleep(0.01)

    def run(self, wr, rd, base, size, seed, bl=256, wrate=65536, rrate=65536, dur=0, one=False):
        self.wait_idle()
        self.w("BL", bl - 1)                      # レジスタは拍数 − 1
        self.w("BASE_LO", base & 0xFFFFFFFF)
        self.w("BASE_HI", base >> 32)
        self.w("SIZE_LO", size & 0xFFFFFFFF)
        self.w("SIZE_HI", size >> 32)
        self.w("SEED", seed)
        self.w("WR_RATE", wrate)
        self.w("RD_RATE", rrate)
        self.w("DUR", dur)
        self.w("CTRL", (1 if wr else 0) | (2 if rd else 0) | (4 if one else 0))
        self.wait_idle(timeout=max(120.0, 3 * dur / F_UI + 10))
        cyc = self.r64("CYC")
        out = dict(cyc=cyc, wr_beats=self.r64("WR_BEATS"), rd_beats=self.r64("RD_BEATS"), wr_wait=self.r64("WR_WAIT"),
                   rd_err=self.r64("RD_ERR"), first_err=self.r64("FIRST_ERR"), flags=self.r("FLAGS"))
        sec = cyc / F_UI if cyc else float("nan")
        out["sec"] = sec
        out["wr_gbs"] = out["wr_beats"] * BEAT / sec / 1e9 if cyc else 0.0
        out["rd_gbs"] = out["rd_beats"] * BEAT / sec / 1e9 if cyc else 0.0
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bit", default="proj028.bit")
    ap.add_argument("--out", default="ddr_bw.json")
    ap.add_argument("--quick", action="store_true", help="8 GiB の全体の書き読みを省く")
    a = ap.parse_args()
    from pynq import Overlay, MMIO
    ol = Overlay(a.bit)
    res = dict(bit=a.bit)
    # ---- clk_mon（pl_clk0 の側）を先に ----
    ipc = ol.ip_dict["clk_mon_0"]
    cm = MMIO(ipc["phys_addr"], ipc["addr_range"])
    cid = cm.read(0x00)
    print("clk_mon ID 0x%08x" % cid)
    if cid != CM_ID:
        print("ERROR: clk_mon の ID が 0x%08x でない（proj028 S-2 の .bit か確かめる）" % CM_ID)
        sys.exit(1)
    win_s = cm.read(0x10) / 100e6                       # pl_clk0 は 100 MHz
    t0 = time.time()
    while True:
        st = cm.read(0x04)
        if st & 4:
            break
        if time.time() - t0 > 5:
            print("ERROR: clk_mon の窓が回らない（pl_clk0 が来ていない？）")
            sys.exit(1)
        time.sleep(0.1)
    time.sleep(win_s + 0.1)                              # 較正を待つ間に 1 窓ぶん数える
    t0 = time.time()
    while True:
        st = cm.read(0x04)
        ref_mhz = cm.read(0x08) * 16 / win_s / 1e6
        ui_mhz = cm.read(0x0C) * 16 / win_s / 1e6
        calib, ui_rst = st & 1, (st >> 1) & 1
        if (calib and not ui_rst) or time.time() - t0 > 10:
            break
        time.sleep(0.2)
    print("clk_mon: 参照クロック %.3f MHz・UI クロック %.3f MHz・UI のリセット %s・較正 %s"
          % (ref_mhz, ui_mhz, "中" if ui_rst else "明け", "済み" if calib else "まだ"))
    res["clk_mon"] = dict(ref_mhz=ref_mhz, ui_mhz=ui_mhz, ui_rst=ui_rst, calib=calib)
    if not (190 < ref_mhz < 210):
        print("ERROR: DDR4 の参照クロック（G13/G12、200 MHz）が来ていない。ddr_tg には触らずに止める")
        sys.exit(1)
    if not (290 < ui_mhz < 310) or ui_rst:
        print("ERROR: MIG の UI クロックが回っていないか、UI のリセットが明けない。ddr_tg には触らずに止める")
        sys.exit(1)
    if not calib:
        print("ERROR: MIG の較正が 10 s で済まない（足・部品の設定・DDR4 の素性を疑う）。ddr_tg には触らずに止める")
        sys.exit(1)
    # ---- ここから ddr_tg（UI クロックの側）----
    ipd = ol.ip_dict["ddr_tg_0"]
    tg = TG(MMIO(ipd["phys_addr"], ipd["addr_range"]))
    idv = tg.r("ID")
    print("ID 0x%08x" % idv)
    if idv != ID_WANT:
        print("ERROR: 載っている .bit の ID が 0x%08x でない（proj028 S-2 の .bit か確かめる）" % ID_WANT)
        sys.exit(1)
    t0 = time.time()
    while not tg.status()["calib"]:
        if time.time() - t0 > 10:
            print("ERROR: MIG の較正（init_calib_complete）が 10 s で立たない")
            sys.exit(1)
        time.sleep(0.05)
    print("較正: 済み（%.2f s）" % (time.time() - t0))

    # 2. 容量
    S = 64 << 20
    tg.run(True, False, 0, S, 0xAAAA0001, one=True)
    tg.run(True, False, 4 * GIB, S, 0xBBBB0002, one=True)
    ra = tg.run(False, True, 0, S, 0xAAAA0001, one=True)
    rb = tg.run(False, True, 4 * GIB, S, 0xBBBB0002, one=True)
    cap = "8 GB" if ra["rd_err"] == 0 and rb["rd_err"] == 0 else ("4 GB（折り返し）" if ra["rd_err"] == S // BEAT else "不明")
    print("容量: A の不一致 %d / %d 拍・B の不一致 %d → %s" % (ra["rd_err"], S // BEAT, rb["rd_err"], cap))
    res["capacity"] = dict(a_err=ra["rd_err"], b_err=rb["rd_err"], beats=S // BEAT, verdict=cap)
    top = 8 * GIB if cap == "8 GB" else 4 * GIB

    # 3. 全体
    if not a.quick:
        w = tg.run(True, False, 0, top, 0x5EED0003, one=True)
        r = tg.run(False, True, 0, top, 0x5EED0003, one=True)
        print("全体 %d GiB: 書き %.2f GB/s・読み %.2f GB/s・不一致 %d・FLAGS %d"
              % (top // GIB, w["wr_gbs"], r["rd_gbs"], r["rd_err"], w["flags"] | r["flags"]))
        res["full"] = dict(w=w, r=r)

    # 4. 帯域
    one_s = int(F_UI)
    res["bw"] = []
    print("帯域（1 s ずつ、GB/s）:  BL   書きだけ  読みだけ  同時の書き  同時の読み  同時の合計  WR_WAIT/拍")
    for bl in (16, 64, 256):
        w = tg.run(True, False, 0, 1 * GIB, 0x5EED0003, bl=bl, dur=one_s)
        r = tg.run(False, True, 0, 1 * GIB, 0x5EED0003, bl=bl, dur=one_s)
        b = tg.run(True, True, 0, 1 * GIB, 0x5EED0003, bl=bl, dur=one_s)
        print("                         %3d   %6.2f    %6.2f     %6.2f      %6.2f      %6.2f      %.3f"
              % (bl, w["wr_gbs"], r["rd_gbs"], b["wr_gbs"], b["rd_gbs"], b["wr_gbs"] + b["rd_gbs"], b["wr_wait"] / max(b["cyc"], 1)))
        res["bw"].append(dict(bl=bl, w=w, r=r, both=b))
        if w["rd_err"] or r["rd_err"] or b["rd_err"] or (w["flags"] | r["flags"] | b["flags"]):
            print("  ERROR: 不一致か FLAGS（%s）" % [w["flags"], r["flags"], b["flags"]])

    # 5. 本番の形
    tw, tr = 4.68e9, 4.77e9
    wrate = round(tw / (BEAT * F_UI) * 65536)
    rrate = round(tr / (BEAT * F_UI) * 65536)
    p = tg.run(True, True, 0, 2 * GIB, 0x5EED0003, bl=64, wrate=wrate, rrate=rrate, dur=10 * one_s)
    okw = p["wr_gbs"] >= 0.999 * tw / 1e9
    okr = p["rd_gbs"] >= 0.999 * tr / 1e9
    print("本番の形（10 s、BL 64）: 書き %.3f GB/s（目標 %.2f、%s）・読み %.3f GB/s（目標 %.2f、%s）・不一致 %d・FLAGS %d"
          % (p["wr_gbs"], tw / 1e9, "○" if okw else "×", p["rd_gbs"], tr / 1e9, "○" if okr else "×", p["rd_err"], p["flags"]))
    res["prod"] = dict(p, target_w=tw, target_r=tr, ok=bool(okw and okr and p["rd_err"] == 0 and p["flags"] == 0))
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)
    print("書いた: %s" % a.out)


if __name__ == "__main__":
    main()
