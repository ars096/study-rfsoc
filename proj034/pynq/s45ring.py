#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj018 — 取得のプロセス（書き手 1 つ）と通信のプロセス（読み手 1 つ）の間の溜まり。共有メモリのバイトの環。

- 記録（s45proto の 頭 ＋ 中身）をそのまま連続に置く。環の端に入らないときは PAD の記録で端まで埋めて頭に戻る
  （端までが頭 24 バイトより短いときは、両側とも黙って頭に戻る）
- 位置は単調に増えるバイト数（w = 書いた、r = 読み終えた）。使用 = w − r、空き = CAP − 使用
- **書き手は空きが足りないとき書かない**（呼び手が捨てて数える。溜まっている側は連続のまま）
- w・r の更新は Lock の中で行う（セマフォの取得・解放がメモリの順序の壁になる。aarch64 で中身より先に w が見えることを防ぐ）
- 言語に依らない形（固定の頭 ＋ バイトの環）にしておき、取得の側を C に替えられるようにする（README の方針）
"""
import multiprocessing as mp
from multiprocessing import shared_memory

import numpy as np

import s45proto as P

CTL = 64          # 制御の領域（w・r の 2 語。残りは空き）


class Ring:
    def __init__(self, cap_bytes, lock=None):
        cap = cap_bytes & ~7
        self.cap = cap
        self.shm = shared_memory.SharedMemory(create=True, size=CTL + cap)
        self._ctl_mv = self.shm.buf[:16]
        self.ctl = np.ndarray(2, np.uint64, self._ctl_mv)
        self.ctl[:] = 0
        self.buf = self.shm.buf[CTL:CTL + cap]
        self.lock = lock or mp.Lock()
        self._r = 0           # 読み手の手元の位置（peek で進め、commit で確定）

    def close(self):
        self.ctl = None
        self._ctl_mv.release()
        self.buf.release()
        self.shm.close()
        try:
            self.shm.unlink()
        except FileNotFoundError:
            pass

    # ---- 共通
    def positions(self):
        with self.lock:
            return int(self.ctl[0]), int(self.ctl[1])

    def used(self):
        w, r = self.positions()
        return w - r

    # ---- 書き手
    def put(self, parts):
        """parts（bytes-like の並び、合計は 8 の倍数・頭を含む）を 1 つの記録として置く。入らなければ False"""
        parts = [memoryview(p).cast("B") for p in parts]     # numpy の配列（uint64）もバイトの並びとして
        n = sum(len(p) for p in parts)
        if n & 7:
            raise ValueError("記録の長さが 8 の倍数でない")
        if n > self.cap // 2:
            raise ValueError("記録が溜まりに比べて大きすぎる")
        w, r = self.positions()
        p = w % self.cap
        tail = self.cap - p
        skip = 0 if n <= tail else tail                 # 端に入らない → 端まで埋めて頭へ
        if self.cap - (w - r) < skip + n:
            return False
        if skip:
            if tail >= P.HDR.size:
                self.buf[p:p + P.HDR.size] = P.header(P.T_PAD, tail - P.HDR.size, 0, 0)
            w += skip
            p = 0
        o = p
        for part in parts:
            m = len(part)
            self.buf[o:o + m] = part
            o += m
        with self.lock:
            self.ctl[0] = w + n
        return True

    # ---- 読み手（送る位置 s と、受け側が受け取ったと言った位置 r の 2 つ。r まで来て初めて溜まりから消える）
    def next_record(self):
        """送る位置 s の次の記録を (memoryview, seq, 終わりの位置) で返す。無ければ None。s は進めない（advance で進める）"""
        with self.lock:
            w = int(self.ctl[0])
            r = int(self.ctl[1])
        s = max(getattr(self, "_s", 0), r)
        while s < w:
            p = s % self.cap
            tail = self.cap - p
            if tail < P.HDR.size:
                s += tail
                continue
            rtype, plen, _, seq = P.parse_header(self.buf[p:p + P.HDR.size])
            if rtype == P.T_PAD:
                s += tail
                continue
            self._s = s
            n = P.HDR.size + plen
            return self.buf[p:p + n], seq, s + n
        self._s = s
        return None

    def advance(self, end):
        self._s = end

    def ack_to(self, end):
        """受け側が end の位置まで受け取った（溜まりから消してよい）"""
        with self.lock:
            if end > int(self.ctl[1]):
                self.ctl[1] = end

    def rewind(self):
        """送る位置を、受け取られていない一番古い記録に戻す（受け側が切れた。次の接続で送り直す）"""
        with self.lock:
            self._s = int(self.ctl[1])

    def skip_all(self):
        """溜まっている記録（送ったが受け取られていないものを含む）を全部捨てる。戻り値: (最初の seq, 最後の seq, 数)。無ければ None"""
        with self.lock:
            self._s = int(self.ctl[1])
        first = last = None
        n = 0
        while True:
            r = self.next_record()
            if r is None:
                break
            mv, seq, end = r
            mv.release()
            if seq:
                first = seq if first is None else first
                last = seq
                n += 1
            self.advance(end)
            self.ack_to(end)
        return None if n == 0 else (first, last, n)
