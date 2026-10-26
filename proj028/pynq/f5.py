#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-5 — 2 段分光の全体の .bit を動かして、スペクトルを取る（ボードの上で。build-f5/proj028.bit・.hwh と同じ場所に置く）

  sudo -E $(which python3) f5.py --chunks 3 --out f5_run           # 出荷時のクロック・ADC_A・3 チャンク（≒ 0.9 s）
  sudo -E $(which python3) f5.py --clkin 0 --ref 10 --chunks 3       # 外部の 10 MHz（extref.py。proj024 と同じ）
  sudo -E $(which python3) f5.py --gain-only                         # 荒い段の利得を合わせて σ を出すだけ

順序:
1. クロック → Overlay（**xrfdc を先に import**）→ RFDC のタイル（Tile 226 の PLL のロック・fs・ナイキスト帯）
2. **clk_mon（pl_clk0 の側）を先に読む**: 参照クロック 200 MHz・UI クロック 300 MHz・UI のリセット・MIG の較正。駄目なら DDR に触らずに止まる（S-2d）
3. ID の照合（clk_mon・荒い段・ct_wr・ct_rd・fine_top・リング）。ギアボックスの見張り（fine_top の GB_STAT・ADC_STAT）
4. 荒い段の利得: ch ごとに σ（8 bit の後、各成分）= S 12 LSB になるよう、電力の数え（POW、NACC ブロック）から 3 回合わせる（M-3）
5. corner turn と細かい側の設定 → fine_top を SRST で消す → リング（PS の DDR、pynq.allocate）→ ct_rd、ct_wr の順に RUN
6. リングを読み続け、チャンク --chunks 個 × 32 レコードを集める（CRC・尾・頭の照合）→ 止める → 見張りの数えを全部読む
7. 保存: <out>_spec.npy（チャンク × 3,670,016 点、積んだフレームの数で割った電力）・<out>_meta.json

周波数: つないだ bin G（0..3,670,015）の周波数は f = G · fs / (56 · 131072)（≒ 558.04 Hz の刻み、0〜2.048 GHz。README の M-4・F-3）
チャンク 0 は前のチャンクの末尾が無いので、ch ごとの積分は 157 フレーム（1 以降は 160）
"""
import argparse
import json
import sys
import time
import zlib

import numpy as np

FS = 4.096e9
NF = 131072
NCH = 32
NKEEP = 114688                        # 荒い ch ごとに残す bin（7/8）
NTOT = NCH * NKEEP                    # 3,670,016
DF = FS / (56 * NF)
BLK_RATE = FS / 56                    # 荒い段のブロック（1 ch あたりのサンプル）の速さ
S_TARGET = 12.0                       # 8 bit の後の σ（各成分、LSB）。M-2・M-3
GAIN_MAX = (1 << 17) - 1

# 荒い段の並べ（README の C-3・C-4・E-1）: 1 チャンク = 286.72 ms = 20,971,520 ブロック = 160 フレーム × 131072
CHUNK_BLK = 20971520
QB = 64
GPD = CHUNK_BLK // (32 * QB)          # 10240 群
CHS = CHUNK_BLK * 2                   # ch ごとの本体 41,943,040 バイト（1 サンプル 2 バイト）
PLANE = NCH * CHS                     # 1.25 GiB
NPLANE = 3
HB = 3 * NF * 2                       # 前のチャンクの末尾 786,432 バイト（3 フレーム）

ID_CM, ID_CS, ID_CTW, ID_CTR, ID_FT, ID_REC = 0x028000C1, 0x028000C2, 0x028000C3, 0x028000C4, 0x028000F6, 0x028000F5
RING_IF_ID = (2 << 24) | (28 << 16) | (1 << 8) | 3
RING_PROJ = 0x00280500
MAGIC_R, MAGIC_E = 0x52353453, 0x45353453
REC_BYTES = NKEEP * 8                 # 917,504

FT_FLAGS = ["待ち行列の溢れ", "IP の TLAST", "IP の halt", "ひねり係数の番地", "係数の番地", "読み出しを捨てた", "帳簿",
            "PFB の飽和", "空のフレームの重なり"]


def log(*a):
    print(*a, flush=True)


class Regs:
    def __init__(self, ol, name):
        from pynq import MMIO
        ip = ol.ip_dict[name]
        self.name = name
        self.m = MMIO(ip["phys_addr"], ip["addr_range"])

    def rd(self, a):
        return int(self.m.read(a)) & 0xFFFFFFFF

    def wr(self, a, v):
        self.m.write(a, int(v) & 0xFFFFFFFF)


# --------------------------------------------------------------------- 起動
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
    """ADC_A = Tile 226 / blocks[1]（VERSIONS.md の実測。proj024 の CHANS）。起動・停止はしない"""
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


# --------------------------------------------------------------------- 荒い段の利得
def coarse_pow(cs, nacc):
    """次に閉じる区切りの POW（ch ごと、64 bit）と CLIP を返す（SEQ が 2 つ進むのを待つ: 書いた利得が丸ごと効いた区切り）"""
    s0 = cs.rd(0x008)
    t0 = time.time()
    tmo = 5 + 4 * nacc / BLK_RATE
    while (cs.rd(0x008) - s0) & 0xFFFFFFFF < 2:
        if time.time() - t0 > tmo:
            log("ERROR: 荒い段の電力の区切り（SEQ）が進まない（ADC の流れが来ていない？ GB_STAT を見る）")
            sys.exit(1)
        time.sleep(0.005)
    for _ in range(3):
        s1 = cs.rd(0x008)
        p = np.array([cs.rd(0x200 + 8 * k) | cs.rd(0x204 + 8 * k) << 32 for k in range(NCH)], dtype=np.float64)
        c = np.array([cs.rd(0x400 + 4 * k) for k in range(NCH)])
        if cs.rd(0x008) == s1:
            return p, c
    log("ERROR: 荒い段の POW を区切りの途中で読み続けた")
    sys.exit(1)


def gain_cal(cs, nacc, g0, rounds=3):
    cs.wr(0x004, nacc)
    g = np.full(NCH, g0, dtype=np.int64)
    # σ < 1 LSB は丸めで 0 に潰れ、比で合わせられない（F-5c-0: ノイズソース OFF で g 256 → σ 0.002）。8 倍ずつ上げてから合わせる
    while True:
        for k in range(NCH):
            cs.wr(0x100 + 4 * k, int(g[k]))
        p, clip = coarse_pow(cs, nacc)
        sig = np.sqrt(p / nacc / 2.0)
        low = (sig < 1.0) & (g < GAIN_MAX)
        if not low.any():
            break
        log(f"利得の下見: g {int(g.min())}〜{int(g.max())} → σ {sig.min():.3f}〜{sig.max():.3f} LSB。σ < 1 の {int(low.sum())} ch を 8 倍")
        g[low] = np.minimum(g[low] * 8, GAIN_MAX)
    for r in range(rounds):
        for k in range(NCH):
            cs.wr(0x100 + 4 * k, int(g[k]))
        p, clip = coarse_pow(cs, nacc)
        sig = np.sqrt(p / nacc / 2.0)                  # 各成分の σ（LSB、8 bit の後）
        log(f"利得 {r}: g {int(g.min())}〜{int(g.max())} → σ {sig.min():.2f}〜{sig.max():.2f} LSB・飽和 {int(clip.sum())}")
        if np.any(sig <= 0):
            log("ERROR: σ が 0 の ch がある（利得 0 か、入力が無い）")
            sys.exit(1)
        g = np.clip(np.round(g * S_TARGET / sig), 1, GAIN_MAX).astype(np.int64)
    for k in range(NCH):
        cs.wr(0x100 + 4 * k, int(g[k]))
    p, clip = coarse_pow(cs, nacc)
    sig = np.sqrt(p / nacc / 2.0)
    log(f"利得（決め）: g {int(g.min())}〜{int(g.max())} → σ {sig.min():.2f}〜{sig.max():.2f} LSB（目標 {S_TARGET}）・飽和 {int(clip.sum())}")
    log("  ch ごとの σ: " + " ".join(f"{s:.1f}" for s in sig))
    return g, sig, clip


# --------------------------------------------------------------------- リング（proj024 の plring.py の読み方を写した。レコードの頭は fine_rdo の形）
class Ring:
    R_IF_ID, R_CTRL, R_BASE_LO, R_BASE_HI, R_SIZE, R_W, R_R = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18
    R_DROP, R_RECCNT, R_PEAK, R_ERRST, R_PROJ = 0x1C, 0x20, 0x24, 0x28, 0x2C

    def __init__(self, regs, size):
        from pynq import allocate
        self.g = regs
        if regs.rd(self.R_IF_ID) != RING_IF_ID or regs.rd(self.R_PROJ) != RING_PROJ:
            log(f"ERROR: s45_ring_0 の IF_ID 0x{regs.rd(0):08x}・PROJ 0x{regs.rd(self.R_PROJ):08x}"
                f"（0x{RING_IF_ID:08x}・0x{RING_PROJ:08x} を期待）")
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
        self.prof = dict(inval=0.0, parse=0.0, crc=0.0, copy=0.0, n=0)   # 読みの時間（s）。追いつかないときにどこが遅いかを見る

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
        """[R, W) のレコード: [(k, c, nact, s_k, body(u64 の写し), crc_ok, tail_ok, hdr_ok)]"""
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
            if h[0] & 0xFFFFFFFF == MAGIC_R and (h[0] >> 40) & 0xFF == 0:      # PAD（リングが書く）
                n = h[7] & 0xFFFFFFFF
                if p + n != self.size:
                    raise RuntimeError(f"PAD の長さ {n} が端まで（{self.size - p}）と違う")
                self.r = (self.r + n) & 0xFFFFFFFF
                continue
            if h[0] >> 32 != ID_REC:
                raise RuntimeError(f"レコードの頭が違う（位置 {self.r}、W {w}）: 0x{h[0]:016x}")
            pb = h[7] & 0xFFFFFFFF
            nb = 64 + pb
            tc = time.perf_counter()
            crc = zlib.crc32(a8[p:p + nb])
            self.prof["crc"] += time.perf_counter() - tc
            t0, t1 = [int(x) for x in a64[(p + nb) >> 3:((p + nb) >> 3) + 2]]
            c = h[1] & 0xFFFFFFFF
            kk = h[1] >> 32
            hdr_ok = (h[0] & 0xFFFFFFFF) == NKEEP and pb == REC_BYTES and h[3] == (14 * kk + 7) % 16 and h[4:7] == [0, 0, 0]
            tail_ok = (t0 & 0xFFFFFFFF) == MAGIC_E and (t0 >> 32) == c
            tc = time.perf_counter()
            body = a64[i + 8:i + 8 + (pb >> 3)].copy()
            self.prof["copy"] += time.perf_counter() - tc
            self.prof["n"] += 1
            out.append((kk, c, h[2], h[3], body, crc == (t1 & 0xFFFFFFFF), tail_ok, hdr_ok))
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


# --------------------------------------------------------------------- 見張り
def watch(ctw, ctr, ft, ring):
    f = ft.rd(0x10)
    d = dict(ct_wr=dict(chunks=ctw.rd(0x24), ovf=ctw.rd(0x28), groups=ctw.rd(0x2C), flags=ctw.rd(0x30), busy=ctw.rd(0x20) & 1),
             ct_rd=dict(done=ctr.rd(0x24), drop=ctr.rd(0x28), flags=ctr.rd(0x2C), status=ctr.rd(0x20)),
             fine=dict(flags=f, flag_names=[n for i, n in enumerate(FT_FLAGS) if f >> i & 1], n_rec=ft.rd(0x14)),
             ring=ring.regs() if ring else None)
    return d


def gb_text(ft):
    g, a = ft.rd(0x20), ft.rd(0x24)
    return (f"ギアボックス: 開始 {g >> 31}・開始の残量 {g >> 24 & 63}・最小の残量 {g >> 16 & 63}・空振り {g & 0xFFFF} / "
            f"ADC: valid を見た {a >> 31}・落ちた {a & 0xFFFF}"), g, a


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bit", default="proj028.bit")
    ap.add_argument("--clkin", default="stock", help="stock（出荷時）か、extref.py の入力の番号")
    ap.add_argument("--ref", type=float, default=10.0, help="外部の基準の周波数 MHz（--clkin を使うとき）")
    ap.add_argument("--zone", type=int, default=1)
    ap.add_argument("--chunks", type=int, default=3)
    ap.add_argument("--shift", type=int, default=7, help="細かい側の電力の前の右シフト（fine_top の SHIFT）")
    ap.add_argument("--gain-nacc", type=int, default=1 << 20, help="利得を合わせる区切り（ブロック、2^20 ≒ 14.3 ms）")
    ap.add_argument("--gain0", type=int, default=256)
    ap.add_argument("--gain-only", action="store_true")
    ap.add_argument("--ring-mib", type=int, default=64, help="リングの大きさ（CMA は 128 MiB。1 チャンクのレコードは 29.4 MB）")
    ap.add_argument("--out", default="f5_run")
    ap.add_argument("--trace", action="store_true", help="読みのループごとに ct_wr・ct_rd・fine_top の数えを時刻つきで meta に残す")
    a = ap.parse_args()
    if not 1 <= a.chunks <= 64:
        log("ERROR: --chunks は 1〜64")
        sys.exit(2)

    from pynq import Overlay
    import xrfdc                                  # **Overlay() より前に import する**（VERSIONS.md）
    setup_clocks(a.clkin, a.ref)
    ol = Overlay(a.bit)
    log(f"Overlay: {a.bit}")
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない（DefaultIP のまま）")
        sys.exit(1)
    check_tile(ol.rfdc, a.zone)
    meta = dict(bit=a.bit, clkin=a.clkin, ref=a.ref, zone=a.zone, shift=a.shift, chunks=a.chunks, df_hz=DF)
    meta["clk_mon"] = check_clk_mon(Regs(ol, "clk_mon_0"))

    cs, ctw, ctr, ft = (Regs(ol, n) for n in ("coarse_stage_0", "ct_wr_0", "ct_rd_0", "fine_top_0"))
    for g, want in ((cs, ID_CS), (ctw, ID_CTW), (ctr, ID_CTR), (ft, ID_FT)):
        if g.rd(0) != want:
            log(f"ERROR: {g.name} の ID 0x{g.rd(0):08x}（0x{want:08x} を期待）。載っている .bit が proj028 F-5 か確かめる")
            sys.exit(1)
    log("ID: clk_mon・coarse_stage・ct_wr・ct_rd・fine_top とも一致")
    txt, gbs, adcs = gb_text(ft)
    log(txt)
    meta["gb_stat0"], meta["adc_stat0"] = gbs, adcs
    if not (gbs >> 31 and adcs >> 31):
        log("ERROR: ギアボックスが開始していないか、RFDC の valid を見ていない")
        sys.exit(1)

    g, sig, clip = gain_cal(cs, a.gain_nacc, a.gain0)
    meta.update(gain=g.tolist(), sigma=sig.tolist(), clip=clip.tolist())
    if a.gain_only:
        json.dump(meta, open(a.out + "_meta.json", "w"), indent=1)
        return 0

    # ---- 止めて設定する（RUN = 0 → 書く）----
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
    ft.wr(0x08, a.shift)
    ft.wr(0x04, 1)                                # SRST（ct_wr・ct_rd は止まっている）
    time.sleep(0.01)
    ft.wr(0x04, 0)
    if ft.rd(0x08) != a.shift or ft.rd(0x10) != 0 or ft.rd(0x14) != 0:
        log(f"ERROR: fine_top の SHIFT {ft.rd(0x08)}・FLAGS 0x{ft.rd(0x10):x}・N_REC {ft.rd(0x14)}（SRST の後は 0）")
        sys.exit(1)
    log(f"corner turn: CHS {CHS}・面 {PLANE}（{NPLANE} 面）・GPD {GPD}・末尾 {HB} バイト / 細かい側の SHIFT {a.shift}")

    ring = Ring(Regs(ol, "s45_ring_0"), a.ring_mib << 20)
    ring.enable(True)
    ctr.wr(0x04, 1)
    ctw.wr(0x04, 1)
    t_run = time.time()
    log(f"RUN（1 チャンク {CHUNK_BLK / BLK_RATE * 1e3:.2f} ms・{a.chunks} チャンク × 32 レコードを待つ）")

    raw = np.zeros((a.chunks, NTOT), dtype=np.uint64)      # 積算のまま溜め、割るのは最後（F-5c-0: ループで float64 に直すと 1 レコード 3 ms かかり、読みが追いつかなかった）
    seen = np.zeros((a.chunks, NCH), dtype=bool)
    nact = np.zeros((a.chunks, NCH), dtype=np.int64)
    bad = []
    other = 0
    t_spec = 0.0
    trace = []
    tmo = (a.chunks + 3) * CHUNK_BLK / BLK_RATE + 5
    try:
        while not seen.all() and time.time() - t_run < tmo:
            if a.trace:
                trace.append((round(time.time() - t_run, 4), ctw.rd(0x24), ctr.rd(0x24), ctr.rd(0x28), ctr.rd(0x20), ft.rd(0x14), ring.g.rd(Ring.R_RECCNT)))
            for kk, c, na, sk, body, crc_ok, tail_ok, hdr_ok in ring.read():
                if not (crc_ok and tail_ok and hdr_ok):
                    bad.append(dict(k=kk, c=c, crc=crc_ok, tail=tail_ok, hdr=hdr_ok))
                if c >= a.chunks or kk >= NCH:
                    other += 1
                    continue
                if seen[c, kk]:
                    bad.append(dict(k=kk, c=c, dup=True))
                seen[c, kk] = True
                nact[c, kk] = na
                tc = time.perf_counter()
                raw[c, kk * NKEEP:(kk + 1) * NKEEP] = body
                t_spec += time.perf_counter() - tc
            time.sleep(0.01)
    finally:
        ctw.wr(0x04, 0)
        t0 = time.time()
        while ctw.rd(0x20) & 1 and time.time() - t0 < 2:
            time.sleep(0.01)
        time.sleep(CHUNK_BLK / BLK_RATE * 1.2)     # 読み途中のチャンクを読み切らせる
        ctr.wr(0x04, 0)
        w = watch(ctw, ctr, ft, ring)
        ring.close()
    t_el = time.time() - t_run
    spec = np.empty((a.chunks, NTOT), dtype=np.float32)
    for c in range(a.chunks):
        spec[c] = raw[c] / np.repeat(np.maximum(nact[c], 1), NKEEP)
    del raw
    txt, gbs, adcs = gb_text(ft)
    log(txt)
    meta.update(watch=w, gb_stat1=gbs, adc_stat1=adcs, nact=nact.tolist(), bad=bad, other=other, seconds=t_el)
    pf = dict(ring.prof, spec=t_spec)
    meta["prof"] = pf
    if a.trace:
        meta["trace"] = dict(cols=["t", "ctw_chunks", "ctr_done", "ctr_drop", "ctr_status", "ft_nrec", "ring_rec"], rows=trace)
    log(f"PS の読みの時間: {pf['n']} レコード・invalidate {pf['inval']:.2f} s・解く {pf['parse']:.2f} s（うち CRC {pf['crc']:.2f}・写し {pf['copy']:.2f}）・"
        f"spec へ {t_spec:.2f} s / 経過 {t_el:.2f} s（追いつくには 1 レコード {CHUNK_BLK / BLK_RATE / NCH * 1e3:.2f} ms 以内）")
    log(f"ct_wr: チャンク {w['ct_wr']['chunks']}・溢れ {w['ct_wr']['ovf']}・FLAGS 0x{w['ct_wr']['flags']:x} / "
        f"ct_rd: 読んだ {w['ct_rd']['done']}・捨てた {w['ct_rd']['drop']}・FLAGS 0x{w['ct_rd']['flags']:x}")
    log(f"fine_top: FLAGS 0x{w['fine']['flags']:03x}（{'・'.join(w['fine']['flag_names']) or 'なし'}）・レコード {w['fine']['n_rec']}")
    r = w["ring"]
    log(f"リング: REC_CNT {r['rec']}・DROP_CNT {r['drop']}・ERR {r['err']}・PEAK {r['peak']}")
    log(f"集めた: {int(seen.sum())} / {seen.size} レコード（{t_el:.2f} s）・頭・CRC・尾の違い {len(bad)}・範囲の外 {other}（止めるまでに来た先のチャンク。誤りではない）")
    want_n = np.where(np.arange(a.chunks)[:, None] == 0, 157, 160)
    n_ng = int(((nact != want_n) & seen).sum())
    log(f"積んだフレームの数: チャンク 0 = {sorted(set(nact[0][seen[0]].tolist()))}・1 以降 = "
        f"{sorted(set(nact[1:][seen[1:]].tolist())) if a.chunks > 1 else '-'}（157・160 を期待、違う {n_ng}）")

    np.save(a.out + "_spec.npy", spec)
    json.dump(meta, open(a.out + "_meta.json", "w"), indent=1, default=int)
    log(f"保存: {a.out}_spec.npy（{a.chunks} × {NTOT}、float32）・{a.out}_meta.json")
    for c in range(a.chunks):
        if not seen[c].all():
            continue
        s = spec[c]
        G = int(np.argmax(s))
        med = float(np.median(s))
        log(f"チャンク {c}: 中央値 {med:.4g}・最大 bin {G}（{G * DF / 1e6:.6f} MHz、中央値の {10 * np.log10(s[G] / med):.1f} dB 上）")

    ok = (seen.all() and not bad and n_ng == 0 and w["fine"]["flags"] & ~(1 << 7) == 0
          and w["ct_wr"]["ovf"] == 0 and w["ct_wr"]["flags"] == 0 and w["ct_rd"]["drop"] == 0 and w["ct_rd"]["flags"] == 0
          and r["drop"] == 0 and not r["err"])
    log("結果: " + ("通過" if ok else "不合格（上の数えを見る）") +
        ("（PFB の飽和 FLAGS[7] は立った: 入力が強すぎるか S が大きい）" if w["fine"]["flags"] >> 7 & 1 else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
