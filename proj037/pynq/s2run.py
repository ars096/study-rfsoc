#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj037 W — 2G-1-Fine の .bit（BIT_KIND 12、STAGE2 ＋ RAW）を動かし、STAGE2 のレコードを INTERFACE 4.4 の頭で照らす（ボードの上で）

  sudo -E $(which python3) s2run.py --chunks 12 --out runs/w1            # ADC_A・12 チャンク（≒ 3.4 s）・RAW も同じ go で
  sudo -E $(which python3) s2run.py --chunks 3 --start-off 1 --out runs/w1_bad   # 陽性対照: START_AT を 7 の倍数から 1 ずらす → RUN を受けず FLAGS[1]
  sudo -E $(which python3) s2run.py --gain-only                          # 荒い段の利得を合わせて σ を出すだけ

proj028 pynq/f5.py（F-5）を写して直した。順序:
1. クロック → Overlay（**xrfdc を先に import**）→ ADC_A（Tile 226 / blocks[1]）の PLL・fs・ナイキスト帯
2. **clk_mon を先に読む**（参照 200 MHz・UI 300 MHz・UI のリセット・MIG の較正。駄目なら DDR に触らずに止まる。proj028 S-2d）
3. ID の照合: s45_core_0（IF_ID {2, 12, 1, 1}・PROJ 0x0037_0100・NSTREAM 2・BASE_BEATS）・流れ 0 の SID {2, 5, 0, 0}・流れ 1 の SID {2, 4, 1, 0}・
   time_core_0・s45_ring_0（{2, 12, 1, 2}・{2, 12, 1, 3}）・ct_wr・ct_rd・clk_mon の ID。ギアボックスの見張り（コアの GB_STAT・ADC_STAT）
4. 荒い段の利得（流れ 0 の 0x100 + 4k。POW 0x200 + 8k・NACC 0x380・SEQ 0x384）: σ = 12 LSB に 3 回合わせる（proj028 M-3）
5. corner turn の設定（ct_wr・ct_rd。RUN 0 で書いて読み返す）→ 細かい側の SRST（流れ 0 の 0x3C0）→ リング（PS の DDR）→ ct_rd・ct_wr を RUN
   （ct_wr は印のブロックで数えを 0 にしてチャンク 0 を始める。印の前は valid が来ない）
6. 流れ 0（STAGE2）: N_DUMP = --chunks・REC_CTRL ALL・SHIFT・FLAGS を消す → CTRL ARM_RUN。流れ 1（RAW）も同じ go で（--no-raw で外す）
   → time_core の START_AT = 今の T ＋ --start-delay 秒を 7 の倍数に（＋ --start-off）→ arm
7. リングを読み続け、--chunks × 32 の STAGE2 のレコードと RAW の SNAP を集める。照らす（STAGE2）:
   CRC・尾（{SEQ, "S45E"}）・語 0 {s 0, core 0, type 1, ver 1}・SEQ が 0 から 1 ずつ（32 本で 1 チャンク）・DUMP_K = c・S0 = k·114,688・
   P = 917,504・DUMP_F0 = c·B_C・**DUMP_T = RUN_T ＋ c·BASE_BEATS**・RUN_T = START_AT・語 4 {NS 6, 17, SHIFT}・DUMP_N（チャンク 0 は 157、以降 160）・FLAGS（[11] PFB の飽和だけ許す）
   RAW: DUMP_T の進み = N_ACC·512（= BASE_BEATS）・DUMP_K が 1 ずつ・CRC・尾
8. 止めて、見張りの数えを全部読む（流れ 0 の FLAGS・REC_LATE・細かい側の FLAGS・N_REC・ct_wr の溢れ・ct_rd の捨て・リングの DROP）
9. 保存: <out>_spec.npy（チャンク × 3,670,016 点、積んだフレームの数で割った電力、float32）・<out>_meta.json

周波数: つないだ bin G（0..3,670,015）の周波数は f = G · fs / (56 · 131072)（≒ 558.04 Hz の刻み、0〜2.048 GHz。proj028 の M-4・F-3）
"""
import argparse
import json
import os
import sys
import time
import zlib

import numpy as np

FS = 4.096e9
NF = 131072
NCH = 32
NKEEP = 114688
NTOT = NCH * NKEEP
DF = FS / (56 * NF)
BLK_RATE = FS / 56
BEATS = 256_000_000                   # time_core の 1 秒
S_TARGET = 12.0
GAIN_MAX = (1 << 17) - 1

CHUNK_BLK = 20971520                  # B_C
BASE_BEATS = 73400320                 # = 3.5·B_C
QB = 64
GPD = CHUNK_BLK // (32 * QB)          # 10240 群
CHS = CHUNK_BLK * 2
PLANE = NCH * CHS
NPLANE = 3
HB = 3 * NF * 2
REC_BYTES = NKEEP * 8                 # 917,504
RAW_BYTES = 16384

BIT_KIND, BIT_REV, PROJ = 12, 1, 0x0037_0100
CORE_IF_ID = (2 << 24) | (BIT_KIND << 16) | (BIT_REV << 8) | 1
TIME_IF_ID = (2 << 24) | (BIT_KIND << 16) | (BIT_REV << 8) | 2
RING_IF_ID = (2 << 24) | (BIT_KIND << 16) | (BIT_REV << 8) | 3
SID_S2, SID_RAW = 0x0205_0000, 0x0204_0100
ID_CM, ID_CTW, ID_CTR = 0x028000C1, 0x028000C3, 0x028000C4
MAGIC_R, MAGIC_E = 0x52353453, 0x45353453

# 流れのブロック（コアの 0x4000 + 0x400·s）
BLK0, BLK1 = 0x4000, 0x4400
S_SID, S_CTRL, S_NACC, S_NDUMP, S_SHIFT, S_FLAGS, S_SEQ = 0x00, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C
S_SRC, S_CFG, S_DUMP_K, S_RUN_T, S_REC_CTRL, S_REC_LATE = 0x28, 0x2C, 0x3C, 0x60, 0x84, 0x88
S2_GAIN, S2_POW, S2_CLIP, S2_NACC, S2_PSEQ = 0x100, 0x200, 0x300, 0x380, 0x384
S2_SRST, S2_FFLAGS, S2_FNREC, S2_TAG, S2_PH = 0x3C0, 0x3C4, 0x3C8, 0x3CC, 0x3D0
CTRL_RUN, CTRL_STOP, CTRL_ARM, CTRL_FCLR = 1, 2, 4, 256

S2_FLAGS = {0: "ブロックの位相の食い違い", 1: "START_AT が対の頭でない", 2: "スタンプが式と違う", 3: "帳簿の c が違う（捨てた）",
            14: "前の RUN が済む前の RUN"}
FT_FLAGS = ["待ち行列の溢れ", "IP の TLAST", "IP の halt", "ひねり係数の番地", "係数の番地", "読み出しを捨てた", "帳簿",
            "PFB の飽和", "空のフレームの重なり"]
for i, n in enumerate(FT_FLAGS):
    S2_FLAGS[4 + i] = "細かい側: " + n
SAT_OK = 1 << (4 + 7)                 # 細かい PFB の飽和だけは止めない（proj028 F-5 と同じ。入力が強いと立つ）


def log(*a):
    print(*a, flush=True)


def flag_text(f):
    return "・".join(S2_FLAGS.get(i, f"[{i}]") for i in range(32) if f >> i & 1) or "なし"


class Regs:
    def __init__(self, ol, name, base=0):
        from pynq import MMIO
        ip = ol.ip_dict[name]
        self.name = name
        self.base = base
        self.m = MMIO(ip["phys_addr"], ip["addr_range"])

    def rd(self, a):
        return int(self.m.read(self.base + a)) & 0xFFFFFFFF

    def wr(self, a, v):
        self.m.write(self.base + a, int(v) & 0xFFFFFFFF)

    def rd64(self, a):
        lo = self.rd(a)
        return self.rd(a + 4) << 32 | lo


# --------------------------------------------------------------------- 起動（proj028 f5.py と同じ）
LMK_FREQ, LMX_FREQ = 245.76, 491.52


def setup_clocks(clkin, ref_mhz):
    if clkin != "stock":
        import extref
        extref.set_clocks(int(clkin), ref_mhz=ref_mhz)
        return
    import xrfclk
    fn = getattr(xrfclk, "set_ref_clks", None) or getattr(xrfclk, "set_ref_clk", None)
    if fn is None:
        log("ERROR: xrfclk に set_ref_clks / set_ref_clk のどちらも無い")
        sys.exit(1)
    log(f"xrfclk.{fn.__name__}(lmk_freq={LMK_FREQ}, lmx_freq={LMX_FREQ})   ← 出荷時のクロック源")
    fn(lmk_freq=LMK_FREQ, lmx_freq=LMX_FREQ)


def check_tile(rfdc, zone):
    tile = rfdc.adc_tiles[2]
    lock = tile.PLLLockStatus
    log(f"Tile 226: PLLLockStatus = {lock}（2 = locked）")
    if lock != 2:
        log("ERROR: Tile 226 のタイル PLL がロックしていない")
        sys.exit(1)
    block = tile.blocks[1]
    st = block.BlockStatus
    if abs(st.get("SamplingFreq", 0) * 1e9 - FS) > 1e3:
        log(f"ERROR: ADC_A の fs が {st.get('SamplingFreq')} GSPS")
        sys.exit(1)
    block.NyquistZone = zone
    if block.NyquistZone != zone:
        log(f"ERROR: ADC_A の NyquistZone が {block.NyquistZone} のまま（要求 {zone}）")
        sys.exit(1)
    log(f"ADC_A（Tile 226 / blocks[1]）: SamplingFreq {st.get('SamplingFreq')} GSPS / NyquistZone {zone}")


def check_clk_mon(cm):
    if cm.rd(0x00) != ID_CM:
        log(f"ERROR: clk_mon の ID 0x{cm.rd(0):08x}（0x{ID_CM:08x} を期待）")
        sys.exit(1)
    win_s = cm.rd(0x10) / 100e6
    t0 = time.time()
    while not cm.rd(0x04) & 4:
        if time.time() - t0 > 5:
            log("ERROR: clk_mon の窓が回らない（pl_clk0 が来ていない？）")
            sys.exit(1)
        time.sleep(0.1)
    time.sleep(win_s + 0.1)
    t0 = time.time()
    while True:
        st = cm.rd(0x04)
        ref_mhz = cm.rd(0x08) * 16 / win_s / 1e6
        ui_mhz = cm.rd(0x0C) * 16 / win_s / 1e6
        calib, ui_rst = st & 1, st >> 1 & 1
        if (calib and not ui_rst) or time.time() - t0 > 10:
            break
        time.sleep(0.2)
    log(f"clk_mon: 参照 {ref_mhz:.3f} MHz・UI {ui_mhz:.3f} MHz・UI のリセット {'中' if ui_rst else '明け'}・較正 {'済み' if calib else 'まだ'}")
    if not (190 < ref_mhz < 210 and 290 < ui_mhz < 310 and calib and not ui_rst):
        log("ERROR: PL DDR4 の側が動いていない。corner turn には触らずに止める")
        sys.exit(1)
    return dict(ref_mhz=ref_mhz, ui_mhz=ui_mhz)


# --------------------------------------------------------------------- 荒い段の利得（proj028 f5.py の gain_cal を流れ 0 の番地に）
def coarse_pow(s2, nacc):
    s0 = s2.rd(S2_PSEQ)
    t0 = time.time()
    tmo = 5 + 4 * nacc / BLK_RATE
    while (s2.rd(S2_PSEQ) - s0) & 0xFFFFFFFF < 2:
        if time.time() - t0 > tmo:
            log("ERROR: 荒い段の電力の区切り（SEQ）が進まない（ADC の流れが来ていない？ GB_STAT を見る）")
            sys.exit(1)
        time.sleep(0.005)
    for _ in range(3):
        q = s2.rd(S2_PSEQ)
        p = np.array([s2.rd(S2_POW + 8 * k) | s2.rd(S2_POW + 4 + 8 * k) << 32 for k in range(NCH)], dtype=np.float64)
        c = np.array([s2.rd(S2_CLIP + 4 * k) for k in range(NCH)])
        if s2.rd(S2_PSEQ) == q:
            return p, c
    log("ERROR: 荒い段の POW を区切りの途中で読み続けた")
    sys.exit(1)


def gain_cal(s2, nacc, g0, rounds=3):
    s2.wr(S2_NACC, nacc)
    g = np.full(NCH, g0, dtype=np.int64)
    while True:
        for k in range(NCH):
            s2.wr(S2_GAIN + 4 * k, int(g[k]))
        p, clip = coarse_pow(s2, nacc)
        sig = np.sqrt(p / nacc / 2.0)
        low = (sig < 1.0) & (g < GAIN_MAX)
        if not low.any():
            break
        log(f"利得の下見: g {int(g.min())}〜{int(g.max())} → σ {sig.min():.3f}〜{sig.max():.3f} LSB。σ < 1 の {int(low.sum())} ch を 8 倍")
        g[low] = np.minimum(g[low] * 8, GAIN_MAX)
    for r in range(rounds):
        for k in range(NCH):
            s2.wr(S2_GAIN + 4 * k, int(g[k]))
        p, clip = coarse_pow(s2, nacc)
        sig = np.sqrt(p / nacc / 2.0)
        log(f"利得 {r}: g {int(g.min())}〜{int(g.max())} → σ {sig.min():.2f}〜{sig.max():.2f} LSB・飽和 {int(clip.sum())}")
        if np.any(sig <= 0):
            log("ERROR: σ が 0 の ch がある（利得 0 か、入力が無い）")
            sys.exit(1)
        g = np.clip(np.round(g * S_TARGET / sig), 1, GAIN_MAX).astype(np.int64)
    for k in range(NCH):
        s2.wr(S2_GAIN + 4 * k, int(g[k]))
    p, clip = coarse_pow(s2, nacc)
    sig = np.sqrt(p / nacc / 2.0)
    log(f"利得（決め）: g {int(g.min())}〜{int(g.max())} → σ {sig.min():.2f}〜{sig.max():.2f} LSB（目標 {S_TARGET}）・飽和 {int(clip.sum())}")
    log("  ch ごとの σ: " + " ".join(f"{s:.1f}" for s in sig))
    return g, sig, clip


# --------------------------------------------------------------------- リング（proj028 f5.py の Ring。頭は INTERFACE 4.4 の形で読む）
class Ring:
    R_IF_ID, R_CTRL, R_BASE_LO, R_BASE_HI, R_SIZE, R_W, R_R = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18
    R_DROP, R_RECCNT, R_PEAK, R_ERRST, R_PROJ = 0x1C, 0x20, 0x24, 0x28, 0x2C

    def __init__(self, regs, size):
        from pynq import allocate
        self.g = regs
        if regs.rd(self.R_IF_ID) != RING_IF_ID or regs.rd(self.R_PROJ) != PROJ:
            log(f"ERROR: s45_ring_0 の IF_ID 0x{regs.rd(0):08x}・PROJ 0x{regs.rd(self.R_PROJ):08x}（0x{RING_IF_ID:08x}・0x{PROJ:08x} を期待）")
            sys.exit(1)
        self.size = size
        self.buf = allocate(shape=(size // 8,), dtype=np.uint64, cacheable=True)
        self.a64 = self.buf.view(np.ndarray)
        self.a8 = self.a64.view(np.uint8)
        self.bo_sync = None
        try:
            import pyxrt
            bo = self.buf.bo
            d = pyxrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE
            bo.sync(d, 4096, 0)
            self.bo_sync = lambda n, off: bo.sync(d, n, off)
        except Exception as e:  # noqa: BLE001
            log(f"NOTE: 範囲を絞った invalidate が使えない（{type(e).__name__}: {e}）。バッファ全体を捨てる")
        self.buf[:] = 0
        self.buf.flush()
        regs.wr(self.R_CTRL, 0)
        t0 = time.time()
        while regs.rd(self.R_CTRL) & 2:
            if time.time() - t0 > 1:
                log("ERROR: リングが止まらない（busy）")
                sys.exit(1)
        regs.wr(self.R_CTRL, 2)
        pa = int(self.buf.physical_address)
        regs.wr(self.R_BASE_LO, pa & 0xFFFFFFFF)
        regs.wr(self.R_BASE_HI, pa >> 32)
        regs.wr(self.R_SIZE, size)
        if regs.rd(self.R_SIZE) != size or (regs.rd(self.R_BASE_HI) << 32 | regs.rd(self.R_BASE_LO)) != pa:
            log("ERROR: リングの BASE・SIZE を書けない")
            sys.exit(1)
        self.r = 0
        self.prof = dict(inval=0.0, parse=0.0, crc=0.0, copy=0.0, n=0)

    def enable(self, on):
        self.g.wr(self.R_CTRL, 1 if on else 0)

    def regs(self):
        c = self.g.rd(self.R_CTRL)
        return dict(en=c & 1, busy=c >> 1 & 1, err=c >> 2 & 1, drop=self.g.rd(self.R_DROP), rec=self.g.rd(self.R_RECCNT),
                    peak=self.g.rd(self.R_PEAK), err_stat=self.g.rd(self.R_ERRST))

    def _inval(self, p, n):
        if n <= 0:
            return
        if self.bo_sync is None:
            self.buf.invalidate()
            return
        a = p & ~4095
        e = min(self.size, (p + n + 4095) & ~4095)
        self.bo_sync(e - a, a)

    def read(self):
        """[R, W) のレコード: [(頭 8 語, 本体（u64 の写し）, crc_ok, tail_ok)]（PAD は飛ばす）"""
        w = self.g.rd(self.R_W)
        n_all = (w - self.r) & 0xFFFFFFFF
        out = []
        t0 = time.perf_counter()
        if n_all:
            p0 = self.r % self.size
            k = min(n_all, self.size - p0)
            self._inval(p0, k)
            if n_all > k:
                self._inval(0, n_all - k)
        tp = time.perf_counter()
        self.prof["inval"] += tp - t0
        a64, a8 = self.a64, self.a8
        while self.r != w:
            p = self.r % self.size
            i = p >> 3
            h = [int(x) for x in a64[i:i + 8]]
            if h[0] & 0xFFFFFFFF != MAGIC_R:
                raise RuntimeError(f"レコードの頭が違う（位置 {self.r}、W {w}）: 0x{h[0]:016x}")
            if (h[0] >> 40) & 0xFF == 0:                    # PAD（リングが書く）
                n = h[7] & 0xFFFFFFFF
                if p + n != self.size:
                    raise RuntimeError(f"PAD の長さ {n} が端まで（{self.size - p}）と違う")
                self.r = (self.r + n) & 0xFFFFFFFF
                continue
            pb = h[7] & 0xFFFFFFFF
            nb = 64 + pb
            tc = time.perf_counter()
            crc = zlib.crc32(a8[p:p + nb])
            self.prof["crc"] += time.perf_counter() - tc
            t0w, t1w = [int(x) for x in a64[(p + nb) >> 3:((p + nb) >> 3) + 2]]
            tail_ok = (t0w & 0xFFFFFFFF) == MAGIC_E and (t0w >> 32) == (h[1] & 0xFFFFFFFF)
            tc = time.perf_counter()
            body = a64[i + 8:i + 8 + (pb >> 3)].copy()
            self.prof["copy"] += time.perf_counter() - tc
            self.prof["n"] += 1
            out.append((h, body, crc == (t1w & 0xFFFFFFFF), tail_ok))
            self.r = (self.r + 64 + pb + 64) & 0xFFFFFFFF
        self.g.wr(self.R_R, self.r)
        self.prof["parse"] += time.perf_counter() - tp
        return out

    def close(self):
        self.enable(False)
        t0 = time.time()
        while self.g.rd(self.R_CTRL) & 2:
            if time.time() - t0 > 1.0:
                log("WARNING: リングが 1 s たっても止まらない（busy）。バッファは返さずに残す")
                return
            time.sleep(0.001)
        self.buf.freebuffer()


def watch(s2, raw, ctw, ctr, ring):
    return dict(s2=dict(flags=s2.rd(S_FLAGS), rec_late=s2.rd(S_REC_LATE), seq=s2.rd(S_SEQ), dump_k=s2.rd(S_DUMP_K), ctrl=s2.rd(S_CTRL),
                        fflags=s2.rd(S2_FFLAGS), fnrec=s2.rd(S2_FNREC), ph=s2.rd(S2_PH), run_t=s2.rd64(S_RUN_T)),
                raw=dict(flags=raw.rd(S_FLAGS), rec_late=raw.rd(S_REC_LATE), seq=raw.rd(S_SEQ), ctrl=raw.rd(S_CTRL), run_t=raw.rd64(S_RUN_T)),
                ct_wr=dict(chunks=ctw.rd(0x24), ovf=ctw.rd(0x28), groups=ctw.rd(0x2C), flags=ctw.rd(0x30), busy=ctw.rd(0x20) & 1, marks=ctw.rd(0x34)),
                ct_rd=dict(done=ctr.rd(0x24), drop=ctr.rd(0x28), flags=ctr.rd(0x2C), status=ctr.rd(0x20)),
                ring=ring.regs() if ring else None)


def gb_text(core):
    g, a = core.rd(0x34), core.rd(0x38)
    return (f"ギアボックス: 開始 {g >> 31}・開始の残量 {g >> 24 & 63}・最小の残量 {g >> 16 & 63}・空振り {g & 0xFFFF} / "
            f"ADC: valid を見た {a >> 31}・落ちた {a & 0xFFFF}"), g, a


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bit", default="proj037.bit")
    ap.add_argument("--clkin", default="stock", help="stock（出荷時）か、extref.py の入力の番号")
    ap.add_argument("--ref", type=float, default=10.0)
    ap.add_argument("--zone", type=int, default=1)
    ap.add_argument("--chunks", type=int, default=12)
    ap.add_argument("--shift", type=int, default=7, help="細かい側の電力の前の右シフト（流れ 0 の SHIFT、RUN で取り込む）")
    ap.add_argument("--gain-nacc", type=int, default=1 << 20)
    ap.add_argument("--gain0", type=int, default=256)
    ap.add_argument("--gains-from", default=None, help="利得を合わせずに、この meta.json の gain を使う")
    ap.add_argument("--gain-only", action="store_true")
    ap.add_argument("--no-raw", action="store_true", help="RAW（流れ 1）を回さない")
    ap.add_argument("--start-delay", type=float, default=0.5, help="START_AT を今から何秒後に置くか")
    ap.add_argument("--start-off", type=int, default=0, help="START_AT に足すビート（1 で 7 の倍数でない: 陽性対照）")
    ap.add_argument("--ring-mib", type=int, default=64)
    ap.add_argument("--out", default="runs/w1")
    ap.add_argument("--no-load", action="store_true", help="Overlay を読み直さない（載っている .bit をそのまま）")
    a = ap.parse_args()
    if not 1 <= a.chunks <= 64:
        log("ERROR: --chunks は 1〜64")
        sys.exit(2)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)

    from pynq import Overlay
    import xrfdc                                  # **Overlay() より前に import する**（VERSIONS.md）
    if not a.no_load:
        setup_clocks(a.clkin, a.ref)
    ol = Overlay(a.bit, download=not a.no_load)
    log(f"Overlay: {a.bit}（{'読み直した' if not a.no_load else '載っているまま'}）")
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない（DefaultIP のまま）")
        sys.exit(1)
    check_tile(ol.rfdc, a.zone)
    meta = dict(bit=a.bit, clkin=a.clkin, ref=a.ref, zone=a.zone, shift=a.shift, chunks=a.chunks, df_hz=DF, start_off=a.start_off)
    meta["clk_mon"] = check_clk_mon(Regs(ol, "clk_mon_0"))

    core = Regs(ol, "s45_core_0")
    s2, raw = Regs(ol, "s45_core_0", BLK0), Regs(ol, "s45_core_0", BLK1)
    tc, ctw, ctr = Regs(ol, "time_core_0"), Regs(ol, "ct_wr_0"), Regs(ol, "ct_rd_0")
    ids = [("s45_core_0 IF_ID", core.rd(0x00), CORE_IF_ID), ("s45_core_0 PROJ", core.rd(0x04), PROJ),
           ("s45_core_0 NSTREAM", core.rd(0x08), 2), ("s45_core_0 BASE_BEATS", core.rd(0x10), BASE_BEATS),
           ("流れ 0 SID", s2.rd(S_SID), SID_S2), ("流れ 1 SID", raw.rd(S_SID), SID_RAW),
           ("time_core_0 IF_ID", tc.rd(0x00), TIME_IF_ID), ("time_core_0 1 秒", tc.rd(0x04), BEATS),
           ("ct_wr_0 ID", ctw.rd(0), ID_CTW), ("ct_rd_0 ID", ctr.rd(0), ID_CTR)]
    ng = [f"{n} 0x{g:08x}（0x{w:08x} を期待）" for n, g, w in ids if g != w]
    if ng:
        log("ERROR: ID が違う（載っている .bit が proj037 V か確かめる）: " + " / ".join(ng))
        sys.exit(1)
    log(f"ID: s45_core_0 {{2, 12, 1, 1}}・PROJ 0x{PROJ:08x}・NSTREAM 2・BASE {BASE_BEATS}・STAGE2 と RAW の SID・time_core・ct_wr・ct_rd とも一致"
        f"（BUILD_TAG 0x{s2.rd(S2_TAG):08x}・位相 {{err, lock}} = {s2.rd(S2_PH):02b}）")
    txt, gbs, adcs = gb_text(core)
    log(txt)
    meta["gb_stat0"], meta["adc_stat0"] = gbs, adcs
    if not (gbs >> 31 and adcs >> 31):
        log("ERROR: ギアボックスが開始していないか、RFDC の valid を見ていない")
        sys.exit(1)

    if a.gains_from:
        g = np.array(json.load(open(a.gains_from))["gain"], dtype=np.int64)
        for k in range(NCH):
            s2.wr(S2_GAIN + 4 * k, int(g[k]))
        s2.wr(S2_NACC, a.gain_nacc)
        p, clip = coarse_pow(s2, a.gain_nacc)
        sig = np.sqrt(p / a.gain_nacc / 2.0)
        log(f"利得（{a.gains_from} から）: g {int(g.min())}〜{int(g.max())} → σ {sig.min():.2f}〜{sig.max():.2f} LSB・飽和 {int(clip.sum())}")
    else:
        g, sig, clip = gain_cal(s2, a.gain_nacc, a.gain0)
    meta.update(gain=g.tolist(), sigma=sig.tolist(), clip=clip.tolist())
    if a.gain_only:
        json.dump(meta, open(a.out + "_meta.json", "w"), indent=1, default=int)
        return 0

    # ---- 止めて設定する ----
    for b in (s2, raw):
        b.wr(S_CTRL, CTRL_STOP)
    ctw.wr(0x04, 0)
    t0 = time.time()
    while ctw.rd(0x20) & 1:
        if time.time() - t0 > 2:
            log("ERROR: ct_wr が止まらない（busy）")
            sys.exit(1)
        time.sleep(0.01)
    ctr.wr(0x04, 0)
    for r, v in ((0x08, 0), (0x0C, CHS), (0x10, PLANE), (0x14, GPD), (0x18, NPLANE)):
        ctw.wr(r, v)
    for r, v in ((0x08, 0), (0x0C, CHS), (0x10, PLANE), (0x14, NPLANE), (0x18, HB)):
        ctr.wr(r, v)
    got = [ctw.rd(r) for r in (0x08, 0x0C, 0x10, 0x14, 0x18)] + [ctr.rd(r) for r in (0x08, 0x0C, 0x10, 0x14, 0x18)]
    want = [0, CHS, PLANE, GPD, NPLANE, 0, CHS, PLANE, NPLANE, HB]
    if got != want:
        log(f"ERROR: corner turn の設定を読み返すと違う: {got}（{want}）")
        sys.exit(1)
    s2.wr(S2_SRST, 1)                             # 細かい側の SRST（ct_wr・ct_rd は止まっている）
    time.sleep(0.01)
    s2.wr(S2_SRST, 0)
    if s2.rd(S2_FFLAGS) != 0 or s2.rd(S2_FNREC) != 0:
        log(f"ERROR: 細かい側の FLAGS 0x{s2.rd(S2_FFLAGS):x}・N_REC {s2.rd(S2_FNREC)}（SRST の後は 0）")
        sys.exit(1)
    log(f"corner turn: CHS {CHS}・面 {PLANE}（{NPLANE} 面）・GPD {GPD}・末尾 {HB} バイト")

    s2.wr(S_NDUMP, a.chunks)
    s2.wr(S_REC_CTRL, 1)
    s2.wr(S_SHIFT, a.shift)
    s2.wr(S_CTRL, CTRL_FCLR)
    use_raw = not a.no_raw
    if use_raw:
        raw.wr(S_NDUMP, a.chunks)
        raw.wr(S_REC_CTRL, 1)
        raw.wr(S_CTRL, CTRL_FCLR)
        raw_nacc = raw.rd(S_NACC)
    if s2.rd(S_FLAGS) != 0 or s2.rd(S_NDUMP) != a.chunks:
        log(f"ERROR: 流れ 0 の FLAGS 0x{s2.rd(S_FLAGS):x}（{flag_text(s2.rd(S_FLAGS))}）・N_DUMP {s2.rd(S_NDUMP)}")
        sys.exit(1)

    ring = Ring(Regs(ol, "s45_ring_0"), a.ring_mib << 20)
    ring.enable(True)
    ctr.wr(0x04, 1)
    ctw.wr(0x04, 1)
    s2.wr(S_CTRL, CTRL_ARM)
    if use_raw:
        raw.wr(S_CTRL, CTRL_ARM)
    t_now = tc.rd64(0x18)
    start_at = ((t_now + int(a.start_delay * BEATS)) // 7 + 1) * 7 + a.start_off
    tc.wr(0x10, start_at & 0xFFFFFFFF)
    tc.wr(0x14, start_at >> 32)
    tc.wr(0x08, 1)
    st = tc.rd(0x08)
    if st & 2 or not st & 9:
        log(f"ERROR: time_core の ARM が効いていない（STATUS 0x{st:x}、今 {t_now}・START_AT {start_at}）")
        sys.exit(1)
    t_run = time.time()
    meta.update(start_at=start_at, t_arm=t_now)
    log(f"ARM_RUN: START_AT {start_at}（今 {t_now} ＋ {(start_at - t_now) / BEATS:.3f} s、mod 7 = {start_at % 7}）・{a.chunks} チャンク × 32 レコード"
        f"{'・RAW も' if use_raw else ''}")

    raw_spec = np.zeros((a.chunks, NTOT), dtype=np.uint64)
    seen = np.zeros((a.chunks, NCH), dtype=bool)
    nact = np.zeros((a.chunks, NCH), dtype=np.int64)
    hdrs, raws, bad, other = [], [], [], []
    raw_body = []                                            # (DUMP_K, int16 × 8192)
    tmo = a.start_delay + (a.chunks + 3) * BASE_BEATS / BEATS + 5
    if a.start_off:
        tmo = a.start_delay + 2 * BASE_BEATS / BEATS + 1           # 陽性対照: レコードは来ないはず。待つのは 2 チャンクぶん
    try:
        while not seen.all() and time.time() - t_run < tmo:
            for h, body, crc_ok, tail_ok in ring.read():
                s, ty = h[0] >> 56, (h[0] >> 40) & 0xFF
                if s == 1 and ty == 4:
                    raws.append(dict(k=h[1] >> 32, seq=h[1] & 0xFFFFFFFF, f0=h[2], t=h[3], n=h[5] & 0xFFFF, flags=h[6] >> 32,
                                     crc=crc_ok, tail=tail_ok, p=h[7] & 0xFFFFFFFF))
                    raw_body.append((h[1] >> 32, np.array(body, dtype=np.uint64).view(np.int16)))   # 語 j = サンプル 4j〜4j+3
                    continue
                if not (s == 0 and ty == 1):
                    other.append(dict(s=s, ty=ty, w0=h[0]))
                    continue
                c, seq = h[1] >> 32, h[1] & 0xFFFFFFFF
                s0, pb = h[7] >> 32, h[7] & 0xFFFFFFFF
                k = s0 // NKEEP
                d = dict(c=c, seq=seq, k=k, s0=s0, p=pb, f0=h[2], t=h[3], w4=h[4], sat=h[5] >> 32, n=h[5] & 0xFFFF,
                         flags=h[6] >> 32, cfg=h[6] & 0xFFFFFFFF, w0=h[0], crc=crc_ok, tail=tail_ok)
                hdrs.append(d)
                if c >= a.chunks or k >= NCH or s0 % NKEEP or pb != REC_BYTES:
                    bad.append(dict(d, why="範囲の外"))
                    continue
                if seen[c, k]:
                    bad.append(dict(d, why="重なり"))
                seen[c, k] = True
                nact[c, k] = d["n"]
                raw_spec[c, k * NKEEP:(k + 1) * NKEEP] = body
            time.sleep(0.01)
    finally:
        t_end = time.time()
        time.sleep(0.3)
        for b in (s2, raw):
            b.wr(S_CTRL, CTRL_STOP)
        ctw.wr(0x04, 0)
        t0 = time.time()
        while ctw.rd(0x20) & 1 and time.time() - t0 < 2:
            time.sleep(0.01)
        time.sleep(CHUNK_BLK / BLK_RATE * 1.2)
        for h, body, crc_ok, tail_ok in ring.read():
            other.append(dict(s=h[0] >> 56, ty=(h[0] >> 40) & 0xFF, w0=h[0], late=True))
        ctr.wr(0x04, 0)
        w = watch(s2, raw, ctw, ctr, ring)
        ring.close()
    t_el = t_end - t_run
    txt, gbs, adcs = gb_text(core)
    log(txt)
    meta.update(watch=w, gb_stat1=gbs, adc_stat1=adcs, nact=nact.tolist(), seconds=t_el, hdrs=hdrs, raws=raws, bad=bad, other=other,
                prof=ring.prof)
    run_t = w["s2"]["run_t"]
    log(f"流れ 0: FLAGS 0x{w['s2']['flags']:x}（{flag_text(w['s2']['flags'])}）・REC_LATE {w['s2']['rec_late']}・SEQ {w['s2']['seq']}・"
        f"RUN_T {run_t}（START_AT {start_at}）・細かい側 FLAGS 0x{w['s2']['fflags']:03x}・N_REC {w['s2']['fnrec']}・位相 {w['s2']['ph']:02b}")
    log(f"ct_wr: チャンク {w['ct_wr']['chunks']}・溢れ {w['ct_wr']['ovf']}・FLAGS 0x{w['ct_wr']['flags']:x}・印 {w['ct_wr']['marks']} / "
        f"ct_rd: 読んだ {w['ct_rd']['done']}・捨てた {w['ct_rd']['drop']}・FLAGS 0x{w['ct_rd']['flags']:x}")
    r = w["ring"]
    log(f"リング: REC_CNT {r['rec']}・DROP_CNT {r['drop']}・ERR {r['err']}・PEAK {r['peak']} / 読みの時間: {ring.prof['n']} レコード・"
        f"invalidate {ring.prof['inval']:.2f} s・CRC {ring.prof['crc']:.2f} s・写し {ring.prof['copy']:.2f} s / 経過 {t_el:.2f} s")

    ngs = []

    def judge(ok, msg):
        log(("OK  " if ok else "NG  ") + msg)
        if not ok:
            ngs.append(msg)

    if a.start_off:
        # RAW は同じ go を受け、START_AT の 7 の倍数を見ないので出てよい（README W-1 の注）。数えて残すだけ
        judge(len(hdrs) == 0, f"陽性対照（START_AT mod 7 = {start_at % 7}）: STAGE2 のレコード {len(hdrs)}（0 を期待）・RAW の SNAP {len(raws)}（数えるだけ）")
        judge(w["s2"]["flags"] >> 1 & 1 == 1, f"流れ 0 の FLAGS[1]（START_AT が対の頭でない）= {w['s2']['flags'] >> 1 & 1}（1 を期待）")
        judge(w["ct_wr"]["marks"] == 0 and w["ct_wr"]["chunks"] == 0, f"ct_wr の印 {w['ct_wr']['marks']}・チャンク {w['ct_wr']['chunks']}（0 を期待）")
        meta["ng"] = ngs
        json.dump(meta, open(a.out + "_meta.json", "w"), indent=1, default=int)
        log("結果: " + ("陽性対照として正しく RUN を受けなかった" if not ngs else f"不合格（{len(ngs)}）"))
        return 0 if not ngs else 1

    n_want = a.chunks * NCH
    judge(seen.all() and not bad, f"STAGE2 のレコード {int(seen.sum())} / {n_want}・範囲の外や重なり {len(bad)}")
    judge(all(d["crc"] and d["tail"] for d in hdrs), f"CRC・尾: 外れ {sum(1 for d in hdrs if not (d['crc'] and d['tail']))} / {len(hdrs)}")
    hs = sorted(hdrs, key=lambda d: d["seq"])
    seqs = [d["seq"] for d in hs]
    judge(seqs == list(range(len(hs))), f"SEQ が 0 から 1 ずつ（{seqs[:1]}〜{seqs[-1:]}、{len(hs)} 本）")
    order = [(d["c"], d["k"]) for d in hs]
    judge(order == [(c, k) for c in range(a.chunks) for k in range(NCH)][:len(hs)], "SEQ の順 = (c, k) の順（チャンクごとに k = 0..31）")
    judge(all(d["w0"] & 0xFFFFFFFFFFFF == (1 << 40 | 1 << 32 | MAGIC_R) and (d["w0"] >> 48) & 0xFF == 0 for d in hdrs),
          "語 0 = {s 0, core 0, type 1, rec_ver 1, \"S45R\"}")
    judge(all(d["f0"] == d["c"] * CHUNK_BLK for d in hdrs), "DUMP_F0 = c·B_C")
    judge(run_t == start_at, f"RUN_T {run_t} = START_AT {start_at}")
    dt_bad = [d for d in hdrs if d["t"] != run_t + d["c"] * BASE_BEATS]
    judge(not dt_bad, f"DUMP_T = RUN_T ＋ c·BASE_BEATS（外れ {len(dt_bad)}）")
    w4s = {d["w4"] & 0xFFFFFF for d in hdrs}
    judge(w4s == {(a.shift << 16) | (6 << 8) | 17}, f"語 4 の {{SHIFT, NS, log2N}} = {sorted(hex(x) for x in w4s)}（{(a.shift << 16) | (6 << 8) | 17:#x} を期待）")
    want_n = np.where(np.arange(a.chunks)[:, None] == 0, 157, 160)
    n_ng = int(((nact != want_n) & seen).sum())
    judge(n_ng == 0, f"DUMP_N: チャンク 0 = {sorted(set(nact[0][seen[0]].tolist()))}・1 以降 = "
          f"{sorted(set(nact[1:][seen[1:]].tolist())) if a.chunks > 1 else '-'}（157・160 を期待、違う {n_ng}）")
    fl = 0
    for d in hdrs:
        fl |= d["flags"]
    judge(fl & ~SAT_OK == 0 and w["s2"]["flags"] & ~SAT_OK == 0, f"FLAGS（頭の OR 0x{fl:x}・流れ 0x{w['s2']['flags']:x}）: {flag_text(fl | w['s2']['flags'])}")
    judge(w["s2"]["rec_late"] == 0 and r["drop"] == 0 and not r["err"], f"REC_LATE {w['s2']['rec_late']}・DROP_CNT {r['drop']}・ERR {r['err']}")
    judge(w["ct_wr"]["ovf"] == 0 and w["ct_wr"]["flags"] == 0 and w["ct_wr"]["marks"] == 1 and w["ct_wr"]["chunks"] == a.chunks,
          f"ct_wr: 溢れ {w['ct_wr']['ovf']}・FLAGS 0x{w['ct_wr']['flags']:x}・印 {w['ct_wr']['marks']}（1）・チャンク {w['ct_wr']['chunks']}（{a.chunks}）")
    judge(w["ct_rd"]["drop"] == 0 and w["ct_rd"]["flags"] == 0, f"ct_rd: 捨てた {w['ct_rd']['drop']}・FLAGS 0x{w['ct_rd']['flags']:x}")
    judge(not other, f"ほかのレコード {len(other)}（0 を期待。TP は回していない）")
    if use_raw:
        rs = sorted(raws, key=lambda d: d["k"])
        ks = [d["k"] for d in rs]
        dts = sorted({rs[i + 1]["t"] - rs[i]["t"] for i in range(len(rs) - 1)})
        judge(len(rs) == a.chunks and ks == list(range(a.chunks)) and all(d["crc"] and d["tail"] and d["p"] == RAW_BYTES for d in rs),
              f"RAW: SNAP {len(rs)} 本（{a.chunks}）・DUMP_K {ks[:1]}〜{ks[-1:]}・CRC と尾")
        judge(dts == [raw_nacc * 512] and raw_nacc * 512 == BASE_BEATS, f"RAW の DUMP_T の進み {dts}（N_ACC {raw_nacc} × 512 = {raw_nacc * 512}、BASE {BASE_BEATS}）")
        if rs:
            off = rs[0]["t"] - run_t
            log(f"    RAW の DUMP_T[0] − STAGE2 の RUN_T = {off} ビート（{off / 512:.2f} フレーム。raw_core は RUN の 2 フレーム先から）")
            meta["raw_t0_minus_run_t"] = off
        judge(w["raw"]["rec_late"] == 0, f"RAW の REC_LATE {w['raw']['rec_late']}・FLAGS 0x{w['raw']['flags']:x}")

    spec = np.empty((a.chunks, NTOT), dtype=np.float32)
    for c in range(a.chunks):
        spec[c] = raw_spec[c] / np.repeat(np.maximum(nact[c], 1), NKEEP)
    del raw_spec
    np.save(a.out + "_spec.npy", spec)
    if raw_body:                                            # RAW の SNAP の中身（荒い段を通らない参照。W-1c の診断）
        np.save(a.out + "_raw.npy", np.stack([b for _, b in sorted(raw_body, key=lambda x: x[0])]))
    meta["ng"] = ngs
    json.dump(meta, open(a.out + "_meta.json", "w"), indent=1, default=int)
    log(f"保存: {a.out}_spec.npy（{a.chunks} × {NTOT}、float32）・{a.out}_meta.json")
    for c in range(a.chunks):
        if not seen[c].all():
            continue
        s = spec[c]
        G = int(np.argmax(s))
        med = float(np.median(s))
        log(f"チャンク {c}: 中央値 {med:.4g}・最大 bin {G}（{G * DF / 1e6:.6f} MHz、中央値の {10 * np.log10(s[G] / med):.1f} dB 上）")
    log("結果: " + ("全部通過" if not ngs else f"不合格（{len(ngs)}）") +
        ("（細かい PFB の飽和は立った: 入力が強すぎるか S が大きい）" if fl & SAT_OK else ""))
    return 0 if not ngs else 1


if __name__ == "__main__":
    sys.exit(main())
