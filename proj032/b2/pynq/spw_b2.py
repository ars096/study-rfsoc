#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj032 P-8 — SpW のコア 1 個（ADC_A）に PL の DDR（MIG）を足した .bit（build/proj032b2.bit）で、DDR の枠の窓を動かして照らす

    sudo -E $(which python3) spw_b2.py --clkin 0 --ref 10 --sec 10 --cfg A --wg 4 --out runs/p8_a1

spw_b1.py（P-7）からの差:
  - Overlay の直後、コアに触る前に clk_mon_0（pl_clk0 の側）で MIG の参照クロック 200 MHz・UI クロック 300 MHz・較正を確かめる（較正していなければ止める）
  - 窓の構成 --cfg: b1 の 6 窓（チップ内）に、同じ WK・NS の**双子**を DDR の枠（WSL ≧ S）に置く。
      A: DDR の窓 4 本（NS 2 × 3・NS 3 × 1、DDR の幅の和 224 MHz）/ B: DDR の窓 NS 1 × 2（256 MHz = 設計の上限）
  - DDR の窓の 8 bit の利得 WG = --wg（h = sat8(round(z / 2^g))）。機関の FLAGS[8]（8 bit の飽和）は利得しだいなので合否から外し、診断に出す
  - 診断に双子の比（DDR の窓 / チップ内の窓、ch ごと、fftshift の中央 14/16）。入力は同じ標本なので、違いは 8 bit の丸めの雑音だけ:
    比の中央値 − 1 ≒ 1/(12·σ8²)（σ8 = 8 bit の rms）。番地・区画・タップの取り違えがあれば、比の揺れが独立な雑音の大きさ（√(2/N)）になる
以下は spw_b1.py の注

手順: クロック → Overlay（xrfdc を先に import）→ ID・ギアボックス・時刻の確かめ → リング（plring.Ring、PS の DDR 32 MiB）→
      TP のレコード（TP_REC_CTRL 10 個）・TP_RUN → 窓の設定（6 窓、残り 8 窓は止める窓）・NG・NDUMP 0 → WRST ＋ RUN →
      --sec 秒リングを読み続ける → STOP → 見張り（CORE_FLAGS・窓の FLAGS・リングの DROP・EXT・ERR）
照らすもの（合否）:
  - ID: コアの IF_ID 0x0207_0201（--rev 1 なら 0x0207_0101）・PROJ 0x0032_0300・NSTREAM 14・CAPS 3・CORE_PORT 0x2200、time_core 0x0207_0202、リング 0x0207_0203
  - ギアボックス: GB_STAT の開始・空振り 0（2 回読んで増えない）、ADC_STAT の valid を見た・落ち 0
  - 窓のレコード（type 5）: CRC・尾、SEQ が 0 から 1 ずつ、窓ごとの DUMP_K が 1 ずつ、頭の NS・SHIFT・DUMP_N、
    K_F = DUMP_T − 2^(12+NS)·DUMP_F0 が窓ごとに一定で 0 ≦ K_F < 2^(12+NS)（P-4 の格子）、本体が有限で負でない、動いている窓だけから来る
  - TP のレコード（type 2）: CRC・尾、SEQ が前 ＋ DUMP_N、個のフレームが続いている
  - 終わりの見張り（RUN の --settle 秒後に FLAGS を消した後の分）: CORE_FLAGS 0・窓の FLAGS 0・DROP_CNT 0・EXT_CNT 0・ERR_STAT 0・レコードの数 = REC_CNT
診断（合否にしない）: 窓ごとの平均スペクトルの中央値・最大 / 中央値・最大の ch、窓ごとの平らさ、**同じ中心の NS 1 と NS 2 の窓の重なり**（w0 と w1）の形の比
  （ch 0 は窓の中心。fftshift し、NS 2 の 0.5・1・0.5 を NS 1 の 1 ch に合わせ、比の揺れ）。重なりは枠がずれても合う（P-7 の 1 回目）ので、正しさは平らさと CW の位置で見る。--out に .json（要約）と .npz（平均スペクトル）
"""
import argparse
import json
import os
import struct
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

BITFILE = "proj032b2.bit"
LMK_FREQ, LMX_FREQ = 245.76, 491.52
H, E, S, G_L2 = 14, 3, 6, 19
PROJ = 0x0032_0300
REV = 3                                          # BIT_REV。3 = b2（MIG あり）。b1 は 1・2


def ids_for(rev):
    """IF_ID {IF_VER 2, BIT_KIND 7, BIT_REV, CORE_KIND}: コア 1・time_core 2・リング 3"""
    return tuple(0x0207_0000 | rev << 8 | ck for ck in (1, 2, 3))


# コアの番地
C_IF_ID, C_PROJ, C_NSTREAM, C_CAPS, C_CORE_PORT, C_TP_CTRL, C_GB_K, C_GB_STAT, C_ADC_STAT = 0x00, 0x04, 0x08, 0x0C, 0x18, 0x20, 0x2C, 0x34, 0x38
C_CORE_FLAGS, C_NG, C_NDUMP, C_WRST_BAD, C_WRST_CNT = 0x80, 0x84, 0x88, 0x8C, 0x90
TP_N, TP_WP, TP_REC_CTRL = 0x100, 0x108, 0x11C
S_CTRL, S_SHIFT, S_FLAGS, S_WK, S_WDPHI, S_WNS, S_WFL, S_WSL, S_WG = 0x08, 0x14, 0x18, 0x100, 0x104, 0x108, 0x120, 0x124, 0x128
CT_RUN, CT_STOP, CT_FCLR, CT_WRST = 1, 2, 1 << 8, 1 << 12
R_EXT = 0x30
# 窓: (s, WK, NS, lane, WSL)。頭 0..6 は偶の k、7..13 は奇の k（PSPLIT、WRST の約束 [6]）。WSL ≧ S は DDR の枠 WSL − S
#   WRST の約束: lane ごとの幅の和 ≦ 256 MHz（NS 1 = 128・2 = 64・3 = 32）、DDR の窓の幅の和 ≦ 256 MHz
WINS_B1 = [(0, 8, 1, 0, 0), (1, 8, 2, 0, 1), (2, 12, 2, 1, 2), (7, 9, 1, 1, 3), (8, 21, 2, 2, 4), (9, 25, 3, 2, 5)]
CFGS = {
    # A: b1 の 6 窓 ＋ 双子 4 本（3 ↔ 1・4 ↔ 2・11 ↔ 8・10 ↔ 9）。lane 0 = 128 + 64 + 32・1 = 64 + 128 + 64・2 = 64 + 32 + 64 + 64 MHz、DDR 224 MHz
    "A": (WINS_B1 + [(3, 8, 2, 2, 6), (4, 12, 2, 2, 7), (11, 21, 2, 1, 8), (10, 25, 3, 0, 9)], {3: 1, 4: 2, 11: 8, 10: 9}),
    # B: NS 1 の双子 2 本（3 ↔ 0・10 ↔ 7）で DDR の幅の和 256 MHz。lane 0 = 128 + 128・1 = 128 + 128・2 = 64 × 3 + 32 MHz
    "B": ([(0, 8, 1, 0, 0), (3, 8, 1, 0, 6), (7, 9, 1, 1, 3), (10, 9, 1, 1, 7),
           (1, 8, 2, 2, 1), (2, 12, 2, 2, 2), (8, 21, 2, 2, 4), (9, 25, 3, 2, 5)], {3: 0, 10: 7}),
    "b1": (WINS_B1, {}),
}
F_SAT8 = 1 << 8                                  # 機関の FLAGS[8]: DDR の窓の 8 bit の飽和（利得しだい。合否にしない）
CM_ID = 0x0280_00C1


def log(*a):
    print(*a, flush=True)


def blk(s, a):
    return 0x4000 + 0x400 * s + a


def setup_clocks(clkin, ref):
    if clkin != "stock":
        import extref
        extref.set_clocks(int(clkin), ref_mhz=ref)
        return
    import xrfclk
    fn = getattr(xrfclk, "set_ref_clks", None) or getattr(xrfclk, "set_ref_clk")
    fn(lmk_freq=LMK_FREQ, lmx_freq=LMX_FREQ)


class Regs:
    def __init__(self, ip, size):
        from pynq import MMIO
        self.m = MMIO(ip["phys_addr"], size)

    def rd(self, a):
        return int(self.m.read(a)) & 0xFFFFFFFF

    def wr(self, a, v):
        self.m.write(a, int(v) & 0xFFFFFFFF)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--clkin", default="0", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--zone", type=int, default=2, help="ADC_A の NyquistZone")
    p.add_argument("--bitfile", default=os.path.join(HERE, BITFILE))
    p.add_argument("--rev", type=int, default=REV, help="載っているはずの BIT_REV（旧版 build_r1 を交互に回すときは 1）")
    p.add_argument("--sec", type=float, default=10.0)
    p.add_argument("--ng", type=int, default=5, help="ダンプの長さ（G = 2.048 ms の数。5 = 10.24 ms）")
    p.add_argument("--shift", type=int, default=4)
    p.add_argument("--ring-mib", type=int, default=32)
    p.add_argument("--settle", type=float, default=0.5, help="RUN の後、FLAGS を読んで消すまで [s]（起動の時だけの印を分ける）")
    p.add_argument("--cfg", default="A", choices=sorted(CFGS), help="窓の構成（A・B は DDR の窓あり、b1 は P-7 と同じ 6 窓）")
    p.add_argument("--wg", type=int, default=4, help="DDR の窓の 8 bit の利得 WG（右シフト 0..10）")
    p.add_argument("--out", default=None)
    a = p.parse_args()
    WINS, TWINS = CFGS[a.cfg]

    bad = []
    setup_clocks(a.clkin, a.ref)
    import xrfdc                                     # Overlay() より前に import する（VERSIONS.md）
    from pynq import Overlay
    import plring
    import hashlib
    with open(a.bitfile, "rb") as f:
        bit_sha = hashlib.sha256(f.read()).hexdigest()
    log(f"ビルドの指紋: {os.path.basename(a.bitfile)} sha256 {bit_sha[:16]}…・期待する BIT_REV {a.rev}")
    ol = Overlay(a.bitfile)
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    tile = ol.rfdc.adc_tiles[2]
    if tile.PLLLockStatus != 2:
        log(f"ERROR: Tile 226 の PLL がロックしていない（{tile.PLLLockStatus}）"); sys.exit(1)
    blkA = tile.blocks[1]                            # ADC_A = Tile 226 / slice 2 = blocks[1]（VERSIONS.md の実測）
    blkA.NyquistZone = a.zone
    log(f"ADC_A: SamplingFreq {blkA.BlockStatus.get('SamplingFreq')} GSPS・NyquistZone {blkA.NyquistZone}")

    # MIG の見張り（pl_clk0 の側。MIG のクロックに依らずに読める）。**コアに DDR の窓を設定する前に**較正を確かめる（LESSONS、proj028 S-2d）
    cm = Regs(ol.ip_dict["clk_mon_0"], 0x1000)
    t0 = time.time()
    while not cm.rd(0x04) >> 2 & 1:
        if time.time() - t0 > 3.0:
            log("ERROR: clk_mon が窓を 1 回も数えない"); sys.exit(1)
        time.sleep(0.1)
    time.sleep(1.1)                                  # 直前の窓（1 s）を数え終えた値を読む
    cm_st, cm_win = cm.rd(0x04), cm.rd(0x10)
    mig = dict(id=cm.rd(0x00), calib=cm_st & 1, ui_rst=cm_st >> 1 & 1,
               ref_mhz=cm.rd(0x08) * 16 / (cm_win / 100e6) / 1e6, ui_mhz=cm.rd(0x0C) * 16 / (cm_win / 100e6) / 1e6)
    log(f"MIG: clk_mon ID {mig['id']:#010x}・参照 {mig['ref_mhz']:.3f} MHz・UI {mig['ui_mhz']:.3f} MHz・較正 {mig['calib']}・UI のリセット {mig['ui_rst']}")
    if mig["id"] != CM_ID or not mig["calib"] or mig["ui_rst"] or abs(mig["ref_mhz"] - 200) > 0.5 or abs(mig["ui_mhz"] - 300) > 0.5:
        log("ERROR: MIG が使える状態でない（DDR の窓を設定しない）"); sys.exit(1)

    core = Regs(ol.ip_dict["s45_core_0"], 0x10000)
    tc = Regs(ol.ip_dict["time_core_0"], 0x1000)
    rmm = Regs(ol.ip_dict["s45_ring_0"], 0x1000)
    ids = dict(core=core.rd(C_IF_ID), proj=core.rd(C_PROJ), nstream=core.rd(C_NSTREAM), caps=core.rd(C_CAPS), port=core.rd(C_CORE_PORT),
               time=tc.rd(0x00), ring=rmm.rd(0x00), ring_proj=rmm.rd(0x2C), time_bps=tc.rd(0x04))
    log("ID: " + " ".join(f"{k} {v:#010x}" for k, v in ids.items()))
    ID_CORE, ID_TIME, ID_RING = ids_for(a.rev)
    for k, want in (("core", ID_CORE), ("proj", PROJ), ("nstream", H), ("caps", 3), ("port", 0x2200), ("time", ID_TIME),
                    ("ring", ID_RING), ("ring_proj", PROJ), ("time_bps", 256_000_000)):
        if ids[k] != want:
            bad.append(f"ID {k} {ids[k]:#x}（期待 {want:#x}）")
    if bad:
        log("ERROR: 載っている .bit が違う: " + "・".join(bad)); sys.exit(1)

    def gb():
        g, d = core.rd(C_GB_STAT), core.rd(C_ADC_STAT)
        return dict(armed=g >> 31 & 1, under=g & 0xFFFF, adc_seen=d >> 31 & 1, adc_gaps=d & 0xFFFF, gb_k=core.rd(C_GB_K))
    t1, g1 = (tc.rd(0x18) | tc.rd(0x1C) << 32), gb()
    time.sleep(1.0)
    t2, g2 = (tc.rd(0x18) | tc.rd(0x1C) << 32), gb()
    log(f"ギアボックス: {g1} → {g2}・T の進み {t2 - t1} ビート / 約 1 s")
    if not (g1["armed"] and g1["adc_seen"]) or g1["under"] or g2["under"] != g1["under"] or g1["adc_gaps"] or g2["adc_gaps"]:
        bad.append("ギアボックス・ADC の見張り")
    if not 200e6 < t2 - t1 < 400e6:
        bad.append(f"T が進まない（{t2 - t1}）")

    from pynq import MMIO
    ring = plring.Ring(MMIO(ol.ip_dict["s45_ring_0"]["phys_addr"], 0x1000), a.ring_mib << 20)
    ring.enable(True)
    # TP: 1.024 ms の区切り（TP_N 512 フレーム）を 10 個で 1 レコード、TP_RUN
    core.wr(TP_N, 512)
    core.wr(TP_REC_CTRL, (10 << 8) | 1)
    core.wr(C_TP_CTRL, 1)
    # 窓
    act = {}
    for s in range(H):
        core.wr(blk(s, S_WFL), 3)                    # 止める窓
        core.wr(blk(s, S_WK), 2 * s if s < H // 2 else 2 * (s - H // 2) + 1)
        core.wr(blk(s, S_WSL), 0)
    for s, k, ns, fl, sl in WINS:
        for reg, v in ((S_WK, k), (S_WDPHI, 0), (S_WNS, ns), (S_WFL, fl), (S_WSL, sl), (S_WG, a.wg if sl >= S else 0), (S_SHIFT, a.shift)):
            core.wr(blk(s, reg), v)
        act[s] = dict(k=k, ns=ns, fl=fl, sl=sl)
    core.wr(C_NG, a.ng)
    core.wr(C_NDUMP, 0)
    core.wr(blk(0, S_CTRL), CT_FCLR)
    cnt0 = core.rd(C_WRST_CNT)
    core.wr(blk(0, S_CTRL), CT_WRST | CT_RUN)
    t0 = time.time()
    while not core.rd(blk(0, S_CTRL)) & 1:
        if time.time() - t0 > 1.0:
            log(f"ERROR: RUN に入らない（CTRL {core.rd(blk(0, S_CTRL)):#x}・WRST_BAD {core.rd(C_WRST_BAD):#x}・CORE_FLAGS {core.rd(C_CORE_FLAGS):#x}）")
            sys.exit(1)
    log(f"WRST ＋ RUN: WRST_CNT {cnt0} → {core.rd(C_WRST_CNT)}・WRST_BAD {core.rd(C_WRST_BAD):#x}・CORE_FLAGS {core.rd(C_CORE_FLAGS):#x}")
    # 起動の時だけの印か、動いている間も立つのかを分ける: RUN の後 --settle 秒で FLAGS を読んで消す（終わりの見張りは消した後の分）
    time.sleep(a.settle)
    fl_early = {s: core.rd(blk(s, S_FLAGS)) for s in act}
    cf_early = core.rd(C_CORE_FLAGS)
    core.wr(blk(0, S_CTRL), CT_FCLR)
    log(f"RUN の {a.settle} s 後: CORE_FLAGS {cf_early:#x}・窓の FLAGS {fl_early} → 消した: CORE_FLAGS {core.rd(C_CORE_FLAGS):#x}・窓の FLAGS {[core.rd(blk(s, S_FLAGS)) for s in act]}")

    # ---- 読み続ける ----
    seq, nrec, ntp, tp_seq = 0, {}, 0, None
    tp_sum, tp_nfr = 0, 0                            # TP の和 Σ(x16 >>> 2)² とフレーム数（1 フレーム 8192 標本）
    dk_last, kf = {}, {}
    acc = {s: np.zeros(4096) for s in act}
    nerr = 0

    def err(msg):
        nonlocal nerr
        nerr += 1
        if nerr <= 20:
            log("  " + msg)

    t_end = time.time() + a.sec
    while time.time() < t_end:
        for core_i, s, sq, hw, pay, crc_ok, tail_ok in ring.read():
            w = [int(x) for x in hw]
            typ = (w[0] >> 40) & 0xFF
            if not (crc_ok and tail_ok):
                err(f"type {typ} s {s} SEQ {sq}: CRC {crc_ok}・尾 {tail_ok}")
            if typ == 2:
                ntp += 1
                n = w[5] & 0xFFFFFFFF
                if tp_seq is not None and sq != tp_seq:
                    err(f"TP SEQ {sq}（期待 {tp_seq}）")
                tp_seq = sq + n
                b = pay.view(np.uint8).tobytes()
                ents = [struct.unpack("<QII", b[16 * i:16 * i + 16]) for i in range(n)]
                for e in ents:
                    tp_sum += e[0]; tp_nfr += e[2] & 0xFFFFFF
                for i in range(1, n):
                    if ents[i][1] != ents[i - 1][1] + (ents[i - 1][2] & 0xFFFFFF):
                        err(f"TP SEQ {sq} 個 {i}: フレームが続いていない")
                continue
            if typ != 5:
                err(f"type {typ} のレコード"); continue
            if sq != seq:
                err(f"SEQ {sq}（期待 {seq}）")
            seq = sq + 1
            if s not in act:
                err(f"動いていない窓 {s} のレコード"); continue
            c = act[s]
            dk = w[1] >> 32
            l2n, ns, sh, g, fmt, src = [(w[4] >> (8 * i)) & 0xFF for i in range(6)]
            dn = w[5] & 0xFFFFFFFF
            if (l2n, ns, sh, fmt, dn) != (12, c["ns"], a.shift, 1, a.ng << (G_L2 - 12 - c["ns"])):
                err(f"窓 {s} SEQ {sq}: 頭 log2N {l2n} NS {ns} SHIFT {sh} fmt {fmt} DUMP_N {dn}")
            if s in dk_last and dk != dk_last[s] + 1:
                err(f"窓 {s}: DUMP_K {dk_last[s]} → {dk}")
            dk_last[s] = dk
            L = 1 << (12 + c["ns"])
            k_f = w[3] - w[2] * L
            kf.setdefault(s, set()).add(k_f)
            if not 0 <= k_f < L:
                err(f"窓 {s} K {dk}: K_F {k_f} が [0, {L}) の外")
            x = pay.view(np.float32).astype(np.float64)
            if not np.all(np.isfinite(x)) or np.any(x < 0):
                err(f"窓 {s} K {dk}: 本体に負か有限でない値")
            acc[s] += x
            nrec[s] = nrec.get(s, 0) + 1
        time.sleep(0.02)
    core.wr(blk(0, S_CTRL), CT_STOP)
    core.wr(C_TP_CTRL, 0)
    time.sleep(0.1)
    for core_i, s, sq, hw, pay, crc_ok, tail_ok in ring.read():
        pass                                         # STOP の後に閉じたダンプ（照らさない、数えない）
    rr = ring.regs()
    fl = {s: core.rd(blk(s, S_FLAGS)) for s in act}
    cf = core.rd(C_CORE_FLAGS)
    ext = rmm.rd(R_EXT)
    log(f"レコード: 窓 {sum(nrec.values())}（{nrec}）・TP {ntp}・照らしの誤り {nerr}")
    # TP の dBFS: 平均の二乗 / (8192²/2)（0 dBFS = 14 bit の満杯の正弦波の電力。YATSUGATAKE の s45cal・s45lin と同じ）
    tp_dbfs = float(10 * np.log10(tp_sum / (tp_nfr * 8192) / (8192 ** 2 / 2))) if tp_nfr and tp_sum else None
    log(f"TP: {tp_dbfs:.2f} dBFS（{tp_nfr} フレーム）" if tp_dbfs is not None else "TP: 和が無い")
    log(f"K_F: " + " ".join(f"{s}:{','.join(str(v) for v in sorted(kf.get(s, [])))}" for s in act))
    log(f"見張り: CORE_FLAGS {cf:#x}・窓の FLAGS {fl}・リング {rr}・EXT_CNT {ext}・TP_WP {core.rd(TP_WP)}")
    if nerr:
        bad.append(f"照らしの誤り {nerr}")
    for s in act:
        if nrec.get(s, 0) < a.sec / (a.ng * 2.048e-3) * 0.5:
            bad.append(f"窓 {s} のレコードが少ない（{nrec.get(s, 0)}）")
        if len(kf.get(s, ())) != 1:
            bad.append(f"窓 {s} の K_F が一定でない")
    if ntp == 0:
        bad.append("TP のレコードが無い")
    sat8 = {s: v for s, v in fl.items() if v & F_SAT8}
    if sat8:
        log(f"8 bit の飽和（FLAGS[8]、合否にしない）: 窓 {sorted(sat8)}・WG {a.wg}")
    cf_x = cf & ~0x2 if all(not (v & ~F_SAT8) for v in fl.values()) else cf     # CORE_FLAGS[1] が FLAGS[8] だけから来ているなら外す
    if cf_x or any(v & ~F_SAT8 for v in fl.values()) or rr["drop"] or ext or rr["err_stat"]:
        bad.append("終わりの見張り")
    # 診断: 窓ごとの平均スペクトル
    diag = {}
    for s in act:
        m = acc[s] / max(1, nrec.get(s, 0))
        med = float(np.median(m)) if nrec.get(s) else 0.0
        diag[s] = dict(n=nrec.get(s, 0), median=med, max_over_med=float(m.max() / med) if med > 0 else None, argmax=int(m.argmax()))
        log(f"窓 {s}（k {act[s]['k']}・NS {act[s]['ns']}）: 平均の中央値 {med:.4g}・最大 / 中央値 {diag[s]['max_over_med']}・最大の ch {diag[s]['argmax']}")
        # 平らさ: fftshift した 16 区間の中央値 / 全体の中央値（縁の 2 区間を除いた幅）。ch 0 は窓の中心（DC）で、窓の縁は ch 2048
        if nrec.get(s):
            seg = np.median(np.fft.fftshift(m).reshape(16, -1), axis=1) / med
            diag[s]["seg16"] = [float(x) for x in seg]
            log(f"  平らさ（fftshift の 16 区間 / 中央値、縁の 2 区間を除く）: {seg[1:-1].min():.3f}〜{seg[1:-1].max():.3f}")
    if nrec.get(0) and nrec.get(1):
        # P-7: ch の並びは FFT の自然な順（ch 0 = 窓の中心）。fftshift してから重ねる（1 回目の版は並びを取り違え、窓の縁の側を比べていた）。
        #   NS 1 の ch j（中心 (j − 2048)·d）は NS 2 の ch i = 2j − 2048 とその両隣の半分（境目が半 ch ずれる）。中心の線と NS 2 の縁の 64 ch は外す
        a0, a1 = np.fft.fftshift(acc[0] / nrec[0]), np.fft.fftshift(acc[1] / nrec[1])
        j = np.arange(1025, 3071)
        i = 2 * j - 2048
        n0, n1 = a0[j], 0.5 * a1[i - 1] + a1[i] + 0.5 * a1[i + 1]
        keep = (np.abs(j - 2048) > 2) & (np.abs(j - 2048) < 1024 - 64)
        r = n0[keep] / n1[keep]
        diag["overlap"] = dict(ratio_median=float(np.median(r)), ratio_rel_std=float(np.std(r) / np.mean(r)),
                               corr=float(np.corrcoef(n0[keep], n1[keep])[0, 1]))
        log(f"重なり（w0 NS 1 と w1 NS 2 の 0.5・1・0.5、fftshift 後の中央、DC と縁を除く）: 比の中央値 {diag['overlap']['ratio_median']:.4g}・比の相対の揺れ "
            f"{diag['overlap']['ratio_rel_std']:.3g}・形の相関 {diag['overlap']['corr']:.4f}")
    # P-8: 双子の比（DDR の窓 / チップ内の窓）。fftshift の中央 14/16（縁の 2 区間を除く）、中心の 5 ch（DC の線）を除く
    for sd, sc in TWINS.items():
        if not (nrec.get(sd) and nrec.get(sc)):
            bad.append(f"双子 {sd}↔{sc} のレコードが無い"); continue
        md, mc = np.fft.fftshift(acc[sd] / nrec[sd]), np.fft.fftshift(acc[sc] / nrec[sc])
        j = np.arange(256, 4096 - 256)
        j = j[np.abs(j - 2048) > 2]
        r = md[j] / mc[j]
        nn = min(nrec[sd], nrec[sc])
        tw = dict(ratio_median=float(np.median(r)), ratio_rel_std=float(np.std(r) / np.mean(r)), indep=float(np.sqrt(2.0 / nn)),
                  corr=float(np.corrcoef(md[j], mc[j])[0, 1]), argmax=(int(acc[sd].argmax()), int(acc[sc].argmax())))
        ex = tw["ratio_median"] - 1
        tw["sigma8"] = float(1 / np.sqrt(12 * ex)) if ex > 0 else None
        diag[f"twin_{sd}_{sc}"] = tw
        log(f"双子 {sd}（DDR）↔ {sc}（チップ内）: 比の中央値 {tw['ratio_median']:.5f}・比の相対の揺れ {tw['ratio_rel_std']:.4f}"
            f"（独立な雑音なら ≒ {tw['indep']:.4f}）・形の相関 {tw['corr']:.5f}・最大の ch {tw['argmax']}・8 bit の rms の見当 {tw['sigma8']}")
        if tw["ratio_rel_std"] > 0.25 * tw["indep"]:      # 最大の ch は雑音だけのとき決まらないので合否にしない（CW の run で見る）
            bad.append(f"双子 {sd}↔{sc} が合わない")
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        np.savez(a.out + ".npz", **{f"w{s}": acc[s] / max(1, nrec.get(s, 0)) for s in act})
        with open(a.out + ".json", "w") as f:
            json.dump(dict(args=vars(a), bit_sha256=bit_sha, ids=ids, mig=mig, wins=WINS, flags_early=fl_early, core_flags_early=cf_early, gb=[g1, g2], nrec=nrec, ntp=ntp, tp_dbfs=tp_dbfs, nerr=nerr, kf={s: sorted(v) for s, v in kf.items()},
                           core_flags=cf, flags=fl, ring=rr, ext=ext, diag=diag, bad=bad), f, indent=1, ensure_ascii=False)
        log(f"→ {a.out}.json・.npz")
    log("結果: " + ("全部通過" if not bad else "不合格: " + "・".join(bad)))
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
