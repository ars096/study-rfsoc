#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj021 2-2d — PS の道具（window・spectrometer・timetest・fine…）のための「レコードでダンプを読む」口

2-2d の bit（BIT_REV 2）には仮の読み窓（スペクトル・スナップショットを AXI4-Lite で読む道）が無い。スペクトル・スナップショット・
FULL の TP の値は、PL が DDR に書くリング（s45_ring_0、INTERFACE 4.）のレコードだけで出る。この口は:

- プロセスに 1 つのリング（plring.Ring）を開き、来たレコードを流れ（core, s）ごとに仕分けて持つ（`tap()`）
- 流れの `run()` が RUN の前に REC_CTRL = ALL（| SNAP）を書く（`arm()`）。**ダンプが閉じるたびに PL がレコードを出す**ので、
  N_DUMP で止まった後の最後のダンプも、今までの AXI4-Lite の読みと同じく後から読める
- `latest()` は「今の SEQ のダンプ」（今までの read_dump と同じ: 最後に閉じたダンプ）の SPEC（と SNAP）を返す。
  そのレコードが来ていなければ（リングが溢れた・REC_LATE で捨てられた）、走っている流れなら次のダンプのレコードを待つ

**specd（取得）と同時には使わない**（リングの持ち主は 1 つ。今までの plring と同じ）。

リングは PL の ip_dict（pynq.PL）から s45_ring_0 の番地を引いて開く（Overlay のオブジェクトを渡さなくてよい）。
"""
import time

import numpy as np

import s45core as SC

TYPE_SPEC, TYPE_TP, TYPE_SNAP = 1, 2, 4
REC_ALL, REC_ONE, REC_SNAP = 1, 2, 4
TP_REC_CTRL, TP_K = 0x11C, 10
KEEP = 8                         # 流れごとに持つ SPEC・SNAP の数（新しい方から）
RING_MIB = 32

_TAP = None


class TapError(SC.S45Error):
    pass


def hdr_meta(hw):
    """レコードの頭 w0..w7（np.uint64 × 8）→ 道具の meta の形（Win.meta・Spec.meta と同じ鍵 ＋ t・h・cfg・shift）"""
    w = [int(x) for x in hw]
    return dict(seq=w[1] & 0xFFFFFFFF, k=w[1] >> 32, f0=w[2] & ((1 << 48) - 1), t=w[3],
                shift=(w[4] >> 16) & 0xFF, src=(w[4] >> 40) & 0xFF, h=(w[4] >> 48) & 0xFFFF,
                n=w[5] & 0xFFFFFFFF, sat=w[5] >> 32, cfg=w[6] & 0xFFFFFFFF, flags=w[6] >> 32)


def snap_ddc(pay):
    v = pay.view(np.int32)
    return v[0::2] + 1j * v[1::2]


def snap_full(pay):
    return pay.view(np.int16).copy()


class Tap:
    def __init__(self, mmio=None, size_mib=RING_MIB, ring=None):
        import plring as PR
        self.own = ring is None
        if ring is not None:                 # 道具がもう開いているリング（plring の main）を使う
            mmio = ring.m
        elif mmio is None:
            from pynq import MMIO, PL
            ip = PL.ip_dict.get("s45_ring_0")
            if ip is None:
                raise TapError("PL に s45_ring_0 が無い（proj021 2-2a 以降の .bit を載せてから）")
            mmio = MMIO(ip["phys_addr"], ip["addr_range"])
        self.ring = ring if ring is not None else PR.Ring(mmio, size_mib << 20)
        self.ring.enable(True)
        self.spec = {}               # (core, s) → {seq: rec}
        self.snap = {}
        self.tp = {}                 # (core, s) → [rec, …]（取られるまで溜める）
        self.nbad = 0                # CRC・尾の不一致
        self.armed = []              # close で REC_CTRL を 0 に戻す流れ（mmio, base）

    def drain(self):
        for r in self.ring.read():
            core, s, seq, hw, pay, crc_ok, tail_ok = r
            if not (crc_ok and tail_ok):
                self.nbad += 1
                continue
            ty = int(hw[0]) >> 40 & 0xFF
            key = (core, s)
            if ty == TYPE_TP:
                self.tp.setdefault(key, []).append(r)
                continue
            d = (self.spec if ty == TYPE_SPEC else self.snap).setdefault(key, {})
            d[seq] = r
            if len(d) > KEEP:
                for old in sorted(d)[:len(d) - KEEP]:
                    del d[old]

    def arm(self, mmio, base, snap):
        """流れ（mmio の base の流れのブロック）の REC_CTRL を ALL（| SNAP）に。RUN の前に呼ぶ（SNAP の書く流れはダンプの頭で決まる）"""
        mmio.write(base + SC.S_REC_CTRL, REC_ALL | (REC_SNAP if snap else 0))
        if (mmio, base) not in self.armed:
            self.armed.append((mmio, base))

    def latest(self, key, rd_seq, with_snap=False, timeout=5.0, grace=0.3):
        """流れ key = (core, s) の今の SEQ（rd_seq()）のダンプの SPEC（と SNAP）。(meta, SPEC の本体 u64, SNAP の本体 u64 か None)。
        今の SEQ のレコードが grace 秒たっても来なければ、それより新しいダンプのレコードを timeout 秒まで待つ"""
        t0 = time.time()
        want = rd_seq()
        while True:
            self.drain()
            sp = self.spec.get(key, {})
            sn = self.snap.get(key, {})
            late = time.time() - t0 > grace
            cand = [q for q in sp if q == want or (late and ((q - want) & 0xFFFFFFFF) < (1 << 31) and q != want)]
            if with_snap:
                cand = [q for q in cand if q in sn]
            if cand:
                q = want if want in cand else min(cand, key=lambda x: (x - want) & 0xFFFFFFFF)
                r = sp[q]
                m = hdr_meta(r[3])
                return m, r[4], (sn[q][4] if with_snap else None)
            if time.time() - t0 > timeout:
                have = sorted(sp)
                raise TapError(f"流れ {key} の SEQ {want} のレコードが来ない（来た SPEC の SEQ {have[-4:]}、"
                               f"SNAP {sorted(sn)[-4:]}。RUN の前に REC_CTRL を ALL{' | SNAP' if with_snap else ''} にしたか）")
            time.sleep(0.002)

    def take_tp(self, key):
        """流れ key の TP のレコード（来た順）を渡して空にする"""
        self.drain()
        return self.tp.pop(key, [])

    def close(self):
        if not self.own:
            return                           # リングを開いた道具が閉じる
        for mmio, base in self.armed:
            try:
                mmio.write(base + SC.S_REC_CTRL, 0)
            except Exception:  # noqa: BLE001
                pass
        self.ring.close()


def use_ring(ring):
    """道具が自分で開いた plring.Ring を、この口のリングにする（同じ s45_ring_0 を 2 回開かない）"""
    global _TAP
    _TAP = Tap(ring=ring)
    return _TAP


def tap():
    """プロセスに 1 つの Tap（初めて呼ばれたときにリングを開く。終わりに閉じる）"""
    global _TAP
    if _TAP is None:
        import atexit
        _TAP = Tap()
        atexit.register(_TAP.close)
    return _TAP
