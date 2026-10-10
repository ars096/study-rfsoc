#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj021 手順 2-2a — PL が書くリング（s45_ring_0、INTERFACE 4.）を PS から読む道具。S22a-4 の判定に使う

**s45ring.py（proj018 の PS の中の溜まり。specd が使う）とは別物**。こちらは書き手が PL、読み手が PS（specd は 2-3 でこれを使う）。

    sudo -E $(which python3) plring.py --clkin 0 --ref 10 --list
    sudo -E $(which python3) plring.py --clkin 0 --ref 10 --compare              # 全部の流れ: レコード = AXI4-Lite（bit 単位）
    sudo -E $(which python3) plring.py --clkin 0 --ref 10 --soak 60              # ALL・10.24 ms を 60 s
    sudo -E $(which python3) plring.py --clkin 0 --ref 10 --soak 20 --no-inval   # 陽性対照: キャッシュを捨てずに読む → CRC の不一致
    sudo -E $(which python3) plring.py --clkin 0 --ref 10 --soak 20 --pause 3    # 陽性対照: 3 s 読まない → DROP_CNT = SEQ の飛び

--compare: 流れごとに N_ACC を長く（ダンプ ≈ --period s）し、REC_CTRL の ONE で 1 個出させ、リングに来たら**次のダンプが閉じる前に**
  同じ流れの仮の読み窓を AXI4-Lite（seqlock）で読み、SEQ が同じ・頭（DUMP_*）・本体 4096 語が bit 単位で同じことを確かめる。
--soak: 全部の流れを BASE（10.24 ms）のダンプ・ALL で回し、リングを読み続ける。数えるもの: 流れごとのレコード・SEQ の飛び・CRC の不一致・
  DROP_CNT・REC_LATE・PEAK・1 周の読みの時間。**DROP_CNT ＝ SEQ の飛びの和**（INTERFACE 4.1）を確かめる。

キャッシュ: HP0 は coherent でないので、[R, W) を読む前に**その範囲だけ**キャッシュを捨てる（pyxrt の bo.sync(FROM_DEVICE, size, offset)。
  使えなければ PYNQ の invalidate（バッファ全体）。bench_ps.py の M-6）。
"""
import argparse
import sys
import time
import zlib

import numpy as np

import s45core as SC

MiB = 1 << 20
R_IF_ID, R_CTRL, R_BASE_LO, R_BASE_HI, R_SIZE, R_W, R_R = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18
R_DROP, R_RECCNT, R_PEAK, R_ERRST, R_PROJ = 0x1C, 0x20, 0x24, 0x28, 0x2C
MAGIC_R, MAGIC_E = 0x52353453, 0x45353453
TYPE_PAD, TYPE_SPEC = 0, 1
NCH = 4096


def log(*a):
    print(*a, flush=True)


class StaleError(SC.S45Error):
    """キャッシュの古い行を読んだ（--no-inval の陽性対照で期待するもの）"""


class Ring:
    """s45_ring_0 と、PS の DDR のリング（pynq.allocate）"""

    def __init__(self, mmio, size, inval=True):
        from pynq import allocate
        self.m = mmio
        v = self.rd(R_IF_ID)
        f = SC.split_if_id(v)
        if f["if_ver"] != SC.IF_VER or f["core_kind"] != SC.CORE_KIND_RING:
            raise SC.S45Error(f"s45_ring_0 の IF_ID {v:#010x}（CORE_KIND {SC.CORE_KIND_RING} を期待）")
        if size & (size - 1) or not 64 * 1024 <= size <= 1 << 30:
            raise SC.S45Error(f"SIZE {size} は 64 KiB〜1 GiB の 2 の冪")
        self.size = size
        self.buf = allocate(shape=(size // 8,), dtype=np.uint64, cacheable=True)
        self.u8 = self.buf.view(np.uint8)
        self.inval = inval
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
        self.wr(R_CTRL, 0)
        t0 = time.time()
        while self.rd(R_CTRL) & 2:
            if time.time() - t0 > 1:
                raise SC.S45Error("リングが止まらない（busy）")
        self.wr(R_CTRL, 2)                                   # RST（EN = 0 で）
        pa = int(self.buf.physical_address)
        self.wr(R_BASE_LO, pa & 0xFFFFFFFF)
        self.wr(R_BASE_HI, pa >> 32)
        self.wr(R_SIZE, size)
        if self.rd(R_SIZE) != size or (self.rd(R_BASE_HI) << 32 | self.rd(R_BASE_LO)) != pa:
            raise SC.S45Error("BASE・SIZE を書けない")
        self.r = 0
        self.base = pa

    def rd(self, a):
        return int(self.m.read(a)) & 0xFFFFFFFF

    def wr(self, a, v):
        self.m.write(a, int(v) & 0xFFFFFFFF)

    def enable(self, on=True):
        self.wr(R_CTRL, 1 if on else 0)

    def regs(self):
        c = self.rd(R_CTRL)
        return dict(en=c & 1, busy=c >> 1 & 1, err=c >> 2 & 1, w=self.rd(R_W), r=self.rd(R_R), drop=self.rd(R_DROP),
                    rec=self.rd(R_RECCNT), peak=self.rd(R_PEAK), err_stat=self.rd(R_ERRST), proj=self.rd(R_PROJ))

    def _invalidate(self, pos, n):
        if not self.inval or n <= 0:
            return
        if self.bo_sync is None:
            self.buf.invalidate()
            return
        a = (pos % self.size) & ~4095
        e = min(self.size, ((pos % self.size) + n + 4095) & ~4095)
        self.bo_sync(e - a, a)

    def read(self):
        """[R, W) のレコードを返す: [(core, s, seq, hdr(8 語), payload(np.uint64 の写し), crc_ok, tail_ok)]。R を進める"""
        w = self.rd(R_W)
        out = []
        while self.r != w:
            p = self.r % self.size
            # 端までの残り（PAD を含む）と、レコードの範囲だけ捨てる。まず頭だけ
            self._invalidate(p, 64)
            h = self.buf[p // 8: p // 8 + 8].copy()
            if int(h[0]) & 0xFFFFFFFF != MAGIC_R:
                # キャッシュを捨てずに読むと、頭が古い行（初めに書いた 0）のまま見える（2026-10-10 の実機の 1 回目）。
                #   長さが読めないのでそこで止める。--no-inval の陽性対照ではこれを「古い行を見つけた」として数える
                cls = StaleError if not self.inval else SC.S45Error
                raise cls(f"magic が違う（位置 {self.r}、W {w}）: {int(h[0]):#018x}")
            ty = int(h[0]) >> 40 & 0xFF
            if ty == TYPE_PAD:
                n = int(h[7]) & 0xFFFFFFFF
                if p + n != self.size:
                    raise SC.S45Error(f"PAD の長さ {n} が端まで（{self.size - p}）と違う")
                self.r = (self.r + n) & 0xFFFFFFFF
                continue
            pb = int(h[7]) & 0xFFFFFFFF
            L = 64 + pb + 64
            self._invalidate(p, L)
            nb = 64 + pb
            crc = zlib.crc32(self.u8[p:p + nb])
            tl = self.buf[(p + nb) // 8:(p + nb) // 8 + 8]
            seq = int(h[1]) & 0xFFFFFFFF
            tail_ok = (int(tl[0]) & 0xFFFFFFFF) == MAGIC_E and (int(tl[0]) >> 32) == seq
            crc_ok = crc == (int(tl[1]) & 0xFFFFFFFF)
            hw = self.buf[p // 8: p // 8 + 8].copy()
            out.append((int(hw[0]) >> 48 & 0xFF, int(hw[0]) >> 56 & 0xFF, seq, hw,
                        self.buf[p // 8 + 8: p // 8 + 8 + pb // 8].copy(), crc_ok, tail_ok))
            self.r = (self.r + L) & 0xFFFFFFFF
        self.wr(R_R, self.r)
        return out

    def close(self, streams=()):
        """**PL が書き終えてからバッファを返す**（書きかけのまま返すと、CMA に PL が書き込む。2026-10-10 の実機の 1 回目は
        例外で REC_CTRL が ALL のまま閉じ、終わりに Segmentation fault が出た）"""
        for st in streams:
            st.wr(SC.S_REC_CTRL, 0)
        self.enable(False)
        t0 = time.time()
        while self.rd(R_CTRL) & 2:
            if time.time() - t0 > 1.0:
                log("WARNING: リングが 1 s たっても止まらない（busy）。バッファは返さずに残す")
                return
            time.sleep(0.001)
        self.buf.freebuffer()


# ------------------------------------------------------------------ 流れの設定
def streams_all(cores):
    return [s for c in cores for s in c.streams]


def setup(cores, period, shift_ddc, shift_full, ns):
    """全部の流れを止め、REC_CTRL = 0、DDC は IF 3000 MHz の窓（NS ns）、FULL は ADC_A。N_ACC はダンプ ≈ period s"""
    import window as WN
    import spectrometer as S
    base = cores[0].base_beats
    for st in streams_all(cores):
        st.wr(SC.S_CTRL, 1 << 1)                              # STOP
        st.wr(SC.S_REC_CTRL, 0)
    out = []
    for c in cores:
        for st in c.ddc():
            wn = WN.Win(c.m, base=st.base, adc=c.adc, win=st.s, lbase=st.lbase)
            _, k, dphi, ns_, _ = WN.window_params(3000.0 + 37.0 * st.s, 256 >> (ns - 1))
            wn.set_window(k, dphi, ns_)
            fb = st.rd(SC.S_FRAME_BEATS)
            nacc = max(1, int(round(period * 256e6 / fb))) if period > 0 else base // fb
            out.append((st, wn, nacc, shift_ddc))
    fs = SC.full_stream(cores)
    sp = S.open_full_stream(fs, 0)
    fb = fs.rd(SC.S_FRAME_BEATS)
    nacc = max(1, int(round(period * 256e6 / fb))) if period > 0 else base // fb
    out.append((fs, sp, nacc, shift_full))
    for st, o, nacc, sh in out:
        o.run(nacc, 0, sh)
    return out


def hdr_from_axi(st):
    """AXI4-Lite で DUMP_* を読み、レコードの頭 w1..w6 を組む（seqlock。崩れたら None）"""
    rd = st.rd
    s0 = rd(SC.S_SEQ)
    k, f0 = rd(SC.S_DUMP_K), rd(SC.S_DUMP_F0) | rd(SC.S_DUMP_F0 + 4) << 32
    t = rd(SC.S_DUMP_T) | rd(SC.S_DUMP_T + 4) << 32
    par, sh, src, h = rd(SC.S_PARAM), rd(SC.S_RUN_SHIFT), rd(SC.S_SRC), rd(SC.S_DUMP_H)
    n, sat, fl, cfg = rd(SC.S_DUMP_N), rd(SC.S_DUMP_SAT), rd(SC.S_FLAGS), rd(SC.S_DUMP_CFG)
    if rd(SC.S_SEQ) != s0:
        return None, s0
    ddc = st.kind == SC.KIND_DDC
    w4 = ((12 if ddc else 13) | ((par >> 8 & 15) if ddc else 0) << 8 | (sh & 15) << 16 | ((par >> 12 & 15) if ddc else 0) << 24
          | (src & 15) << 40 | (h & 0xFFFF) << 48)
    return [s0 | k << 32, f0, t, w4, n | sat << 32, cfg | fl << 32], s0


def axi_spectrum(st, o):
    """仮の読み窓のスペクトル（seqlock）。(seq, np.uint64[4096])"""
    m, spec, _ = o.read_dump()
    return m["seq"], spec


# ------------------------------------------------------------------ 判定
def do_compare(cores, ring, a):
    ss = setup(cores, a.period, a.shift, a.shift_full, a.ns)
    ring.enable(True)
    time.sleep(2 * a.period + 0.5)
    ring.read()                                               # 出だしの残り（無いはず）を捨てる
    ng = 0
    for st, o, nacc, _ in ss:
        st.wr(SC.S_REC_CTRL, 2)                               # ONE
        t0 = time.time()
        got = []
        while not got and time.time() - t0 < 3 * a.period + 2:
            got = [r for r in ring.read() if (r[0], r[1]) == (st.core.adc, st.s)]
            time.sleep(0.002)
        if not got:
            log(f"NG {st.name}: ONE を書いたのにレコードが来ない"); ng += 1; continue
        core, s, seq, hw, pay, crc_ok, tail_ok = got[0]
        hdr, hseq = hdr_from_axi(st)
        aseq, spec = axi_spectrum(st, o)
        rc = st.rd(SC.S_REC_CTRL)
        res = []
        if not (crc_ok and tail_ok): res.append("CRC・尾")
        if len(got) != 1: res.append(f"ONE で {len(got)} 個")
        if rc & 2: res.append(f"ONE が 0 に戻らない（REC_CTRL {rc:#x}）")
        if hdr is None or hseq != seq: res.append(f"頭の seqlock（AXI SEQ {hseq} / レコード {seq}）")
        elif [int(x) for x in hw[1:7]] != hdr:
            bad = [i + 1 for i in range(6) if int(hw[1 + i]) != hdr[i]]
            res.append(f"頭の w{bad} が DUMP_* と違う")
        if aseq != seq: res.append(f"AXI の SEQ {aseq}（次のダンプが閉じた。--period を長く）")
        elif not np.array_equal(pay, spec):
            res.append(f"本体が {int(np.sum(pay != spec))} 語違う")
        tag = "OK" if not res else "NG " + "・".join(res)
        ng += bool(res)
        log(f"{st.name:<22} SEQ {seq:>6} N_ACC {nacc:>7}: {tag}（Σ {int(pay.sum(dtype=np.uint64)):#x}）")
        st.wr(SC.S_REC_CTRL, 0)
    r = ring.regs()
    log(f"リング: REC_CNT {r['rec']} / DROP_CNT {r['drop']} / PEAK {r['peak']} / ERR {r['err']}")
    log(f"結果: {'通過' if ng == 0 and r['drop'] == 0 and not r['err'] else f'失敗（{ng} 本）'}")
    return ng


TP_N_REG, TP_WP, TP_REC_CTRL, TP_REC_LATE, TP_RING = 0x100, 0x108, 0x11C, 0x120, 0x2000
C_TP_CTRL_TP_RUN, C_TP_CTRL_TANCH = 1 << 0, 1 << 4
TP_K = 10


def tp_on(cores, tpn=512, k=TP_K):
    """proj021 2-2b: 4 ADC の TP を TP_N = tpn フレーム（512 = 1.024 ms）・K 個 / レコードで、F0 から区切り直す"""
    for c in cores:
        c.wr(TP_N_REG, tpn)
        c.wr(TP_REC_CTRL, (k << 8) | 1)
    for c in cores:
        c.wr(SC.C_TP_CTRL, C_TP_CTRL_TP_RUN)


def tp_off(cores):
    for c in cores:
        c.wr(TP_REC_CTRL, TP_K << 8)


def acct(r_, last, nrec):
    """1 レコードを数える。戻り: (捨てられたレコードの数の見積り, CRC の不一致, 尾の不一致)。
    SPEC: SEQ は 1 ずつ。TP（s = 0xFF）: SEQ は個の番号で、次の SEQ = SEQ + DUMP_N（飛んだ個 / K を切り上げてレコードの数に）"""
    core, s, seq, hw, pay, crc_ok, tail_ok = r_
    k = (core, s)
    nrec[k] = nrec.get(k, 0) + 1
    g = 0
    if s == 0xFF:
        n = int(hw[5]) & 0xFFFFFFFF
        if k in last and seq != last[k]:
            g = -(-((seq - last[k]) & 0xFFFFFFFF) // TP_K)
        last[k] = seq + n
    else:
        if k in last and seq != last[k] + 1:
            g = (seq - last[k] - 1) & 0xFFFFFFFF
        last[k] = seq
    return g, int(not crc_ok), int(not tail_ok)


def do_tpcompare(cores, ring, a):
    """V2-e: TP のレコードの個 = AXI4-Lite の TP のリングの個（bit 単位）・SEQ の飛び 0・DUMP_T = ANCH_T + (DUMP_F0 − ANCH_F)·512"""
    for st in streams_all(cores):
        st.wr(SC.S_CTRL, 1 << 1)
        st.wr(SC.S_REC_CTRL, 0)
    tp_on(cores)
    for c in cores:
        c.wr(SC.C_TP_CTRL, C_TP_CTRL_TANCH)                   # 次の ADC のフレームの頭で (F, T) の錨
    time.sleep(0.05)
    anch = {}
    for c in cores:
        if not c.rd(SC.C_ANCH_ST) & 2:
            log(f"NG {c.adc_name}: TANCH の錨が取れない"); return 1
        anch[c.adc] = (c.rd64(SC.C_ANCH_F), c.rd64(SC.C_ANCH_T), c.rd(SC.C_GAP))
    ring.enable(True)
    t0 = time.time()
    recs = []
    while time.time() - t0 < a.tp_seconds:
        recs += ring.read()
        time.sleep(0.02)
    # AXI4-Lite の TP のリング（最後の 512 個。TP_WP を前後で読み、その間に上書きされた個は使わない）
    axi = {}
    for c in cores:
        w0 = c.rd(TP_WP)
        i0 = c.m.array[TP_RING // 4:(TP_RING + 512 * 16) // 4].copy()
        w1 = c.rd(TP_WP)
        for idx in range(max(0, w1 - 512 + (w1 - w0) + 1), w0):
            b = (idx % 512) * 4
            v = [int(x) for x in i0[b:b + 4]]
            axi[(c.adc, idx)] = (v[0] | v[1] << 32, v[2] | v[3] << 32)
    tp_off(cores)
    time.sleep(0.05)
    recs += ring.read()
    ng = 0
    by = {}
    for core, s, seq, hw, pay, crc_ok, tail_ok in recs:
        if s != 0xFF:
            continue
        by.setdefault(core, []).append((seq, hw, pay, crc_ok and tail_ok))
    for c in cores:
        rs = by.get(c.adc, [])
        ncmp = nbad = nskip = gaps = tbad = crc = 0
        prev = None
        af, at, ag = anch[c.adc]
        gap_now = c.rd(SC.C_GAP)
        for seq, hw, pay, ok in rs:
            n = int(hw[5]) & 0xFFFFFFFF
            crc += not ok
            if prev is not None and seq != prev:
                gaps += 1
            prev = seq + n
            f0, t = int(hw[2]), int(hw[3])
            if gap_now == ag and t != at + (f0 - af) * 512:
                tbad += 1
            for i in range(n):
                it = axi.get((c.adc, seq + i))
                if it is None:
                    nskip += 1
                    continue
                ncmp += 1
                if (int(pay[2 * i]), int(pay[2 * i + 1])) != it:
                    nbad += 1
        res = (len(rs) >= 3 and ncmp >= 30 and nbad == 0 and gaps == 0 and tbad == 0 and crc == 0 and gap_now == ag)
        ng += not res
        log(f"{c.adc_name}: TP のレコード {len(rs)} 個・照らした個 {ncmp}（AXI4-Lite のリングの外 {nskip}）・不一致 {nbad}・"
            f"SEQ の飛び {gaps}・DUMP_T の式の外れ {tbad}（GAP_CNT {ag} → {gap_now}）・CRC {crc}: {'OK' if res else 'NG'}")
    r = ring.regs()
    log(f"リング: REC_CNT {r['rec']} / DROP_CNT {r['drop']} / ERR {r['err']}")
    ok = ng == 0 and r["drop"] == 0 and not r["err"]
    log(f"結果（V2-e）: {'通過' if ok else '失敗'}")
    return 0 if ok else 1


def do_soak(cores, ring, a):
    ss = setup(cores, 0, a.shift, a.shift_full, a.ns)
    for st, *_ in ss:
        st.wr(SC.S_REC_CTRL, 1)                               # ALL
    late0 = {(st.core.adc, st.s): st.rd(SC.S_REC_LATE) for st, *_ in ss}
    tp_on(cores)                                              # proj021 2-2b: TP のレコードも（4 ADC、10.24 ms ごと）
    tplate0 = {c.adc: c.rd(TP_REC_LATE) for c in cores}
    ring.enable(True)
    t0 = time.time()
    last = {}
    nrec = {}
    gaps = crc_bad = tail_bad = 0
    t_rd = []
    paused = False
    stale = 0
    while time.time() - t0 < a.soak:
        if a.pause and not paused and time.time() - t0 > a.soak / 2:
            log(f"陽性対照: {a.pause} s 読まない"); time.sleep(a.pause); paused = True
        tt = time.perf_counter()
        try:
            recs = ring.read()
        except StaleError as e:
            log(f"古い行を読んだ: {e}")
            stale += 1
            break
        t_rd.append(time.perf_counter() - tt)
        for r_ in recs:
            g, cb, tb = acct(r_, last, nrec)
            gaps += g; crc_bad += cb; tail_bad += tb
        time.sleep(a.poll)
    for st, *_ in ss:
        st.wr(SC.S_REC_CTRL, 0)
    time.sleep(0.05)
    try:
        tail = ring.read() if not stale else []
    except StaleError as e:
        log(f"古い行を読んだ: {e}")
        stale += 1
        tail = []
    for r_ in tail:
        g, cb, tb = acct(r_, last, nrec)
        gaps += g; crc_bad += cb; tail_bad += tb
    r = ring.regs()
    late = sum(st.rd(SC.S_REC_LATE) - late0[(st.core.adc, st.s)] for st, *_ in ss)
    late += sum(c.rd(TP_REC_LATE) - tplate0[c.adc] for c in cores)
    tp_off(cores)
    t_rd = np.array(t_rd if t_rd else [0.0]) * 1e3
    log(f"流れごとのレコード: {dict(sorted(nrec.items()))}")
    log(f"SEQ の飛び {gaps} / DROP_CNT {r['drop']} / REC_LATE（増えた分）{late} / CRC の不一致 {crc_bad} / 尾の不一致 {tail_bad}")
    log(f"PEAK {r['peak']} B（{100 * r['peak'] / ring.size:.1f} %）/ REC_CNT {r['rec']} / ERR {r['err']}")
    log(f"1 回の読み: 中央 {np.median(t_rd):.2f} ms / p99 {np.percentile(t_rd, 99):.2f} ms / 最大 {t_rd.max():.2f} ms（{len(t_rd)} 回）")
    ok = (r["drop"] == gaps and not r["err"])
    if a.no_inval:
        # 古い行は CRC の不一致か、頭の magic の不一致（そこで読みを止める）として見える。どちらかが立てば陽性対照は通過
        ok = (crc_bad > 0 or tail_bad > 0 or stale > 0) and not r["err"]
        log(f"古い行: CRC の不一致 {crc_bad} / 尾の不一致 {tail_bad} / 頭の magic の不一致 {stale}")
        log(f"結果（陽性対照 --no-inval: 古い行が見つかるべき）: {'通過' if ok else '失敗'}")
    elif a.pause:
        ok = ok and gaps > 0 and crc_bad == 0
        log(f"結果（陽性対照 --pause: DROP_CNT = SEQ の飛び > 0）: {'通過' if ok else '失敗'}")
    else:
        ok = ok and gaps == 0 and crc_bad == 0 and tail_bad == 0 and late == 0
        log(f"結果: {'通過' if ok else '失敗'}")
    return 0 if ok else 1


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default="proj021.bit")
    p.add_argument("--clkin", default="stock")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--size-mib", type=int, default=32)
    p.add_argument("--list", action="store_true")
    p.add_argument("--compare", action="store_true")
    p.add_argument("--soak", type=float, default=0.0)
    p.add_argument("--tpcompare", action="store_true", help="proj021 2-2b V2-e: TP のレコード = AXI4-Lite の TP のリング")
    p.add_argument("--tp-seconds", type=float, default=3.0, help="--tpcompare で集める時間 [s]（AXI4-Lite のリングは 0.52 s ぶん）")
    p.add_argument("--period", type=float, default=1.0, help="--compare のダンプの長さ [s]")
    p.add_argument("--ns", type=int, default=1, help="DDC の NS（1 = 256 MHz）")
    p.add_argument("--shift", type=int, default=4)
    p.add_argument("--shift-full", type=int, default=6)
    p.add_argument("--poll", type=float, default=0.005, help="--soak の読みの間 [s]")
    p.add_argument("--no-inval", action="store_true", help="陽性対照: キャッシュを捨てずに読む")
    p.add_argument("--pause", type=float, default=0.0, help="陽性対照: --soak の途中でこれだけ読まない [s]")
    a = p.parse_args()
    import spectrometer as S
    S.setup_clocks(a.clkin, a.ref)
    from pynq import Overlay
    import xrfdc
    ol = Overlay(a.bitfile)
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    S.check_tiles(ol.rfdc, 2)
    time.sleep(a.settle)                                       # DSP のクロックが明けてから読む（s45core.py の注）
    try:
        cores, tmm = SC.discover(ol)
        rip = getattr(ol, "s45_ring_0", None)
        if rip is None:
            raise SC.S45Error("ol.s45_ring_0 が無い（手順 2-2a 以降の .bit ではない）")
        ring = Ring(rip.mmio, a.size_mib * MiB, inval=not a.no_inval)
    except SC.S45Error as e:
        log(f"ERROR: {e}"); sys.exit(1)
    log(SC.table(cores, tmm))
    r = ring.regs()
    log(f"s45_ring_0: IF_ID {ring.rd(R_IF_ID):#010x} / PROJ {r['proj']:#010x} / BASE {ring.base:#x} / SIZE {ring.size} / "
        f"CAPS（コア）{[c.caps for c in cores]} / 範囲の invalidate {'あり' if ring.bo_sync else 'なし'}")
    rc = 0
    try:
        if a.compare:
            rc |= do_compare(cores, ring, a) != 0
        if a.tpcompare:
            rc |= do_tpcompare(cores, ring, a)
        if a.soak > 0:
            rc |= do_soak(cores, ring, a)
    finally:
        ring.close(streams_all(cores))
    sys.exit(rc)


if __name__ == "__main__":
    main()
