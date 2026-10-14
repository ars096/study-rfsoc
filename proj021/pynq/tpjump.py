#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj021 B2 — TP の跳ねの見張り（README の B2、検討事項 3 (2)）

ADC 1 本の TP（1 個 = 1.024 ms の Σx² / (nfr·8192)）を dB にし、直前 W 個（既定 1,000 ≒ 1 s）の中央値からのずれを、
同じ W 個の MAD による σ（下限 sig_min_db）の k 倍と比べる。越えた個が「跳ね」。続く跳ねは 1 回にまとめ
（跳ねでない個が gap 個続いたら閉じる）、閉じたものを返す。中央値・MAD は feed 1 回（TP の記録の区切り = 40 個）ごとに 1 回だけ計算する。

    tj = TpJump()
    events = tj.feed(t_beat, power, flags)   # 配列（同じ長さ）。閉じた跳ねのリスト
    events += tj.finish()                    # RUN の終わりに開いている跳ねを閉じる

跳ね: dict(t_beat=最初の個の頭, i0=最初の個の通し番号, n=個の数, db=ずれの最大（符号つき）, sigma_db, ovr=FLAGS[4] があったか)
"""
import numpy as np

TPF_OVR = 16


class TpJump:
    def __init__(self, k=6.0, win=1000, warm=200, sig_min_db=0.002, gap=10):
        self.k, self.win, self.warm, self.sig_min, self.gap = float(k), int(win), int(warm), float(sig_min_db), int(gap)
        self.reset()

    def reset(self):
        self.hist = np.zeros(self.win)
        self.nh = 0                    # 溜めた数（win まで）
        self.ph = 0                    # 次に書く場所
        self.i = 0                     # 通し番号
        self.open = None               # 開いている跳ね
        self.quiet = 0
        self.count = 0                 # 閉じた跳ねの数
        self.sigma_db = None

    def _push(self, d):
        n = len(d)
        if n >= self.win:
            self.hist[:] = d[-self.win:]
            self.ph, self.nh = 0, self.win
            return
        idx = (self.ph + np.arange(n)) % self.win
        self.hist[idx] = d
        self.ph = (self.ph + n) % self.win
        self.nh = min(self.win, self.nh + n)

    def feed(self, t_beat, power, flags=None):
        p = np.asarray(power, dtype=np.float64)
        n = len(p)
        if n == 0:
            return []
        d = 10.0 * np.log10(np.maximum(p, 1e-30))
        fl = np.zeros(n, dtype=np.int64) if flags is None else np.asarray(flags, dtype=np.int64)
        tb = np.asarray(t_beat, dtype=np.int64)
        out = []
        if self.nh >= self.warm:
            h = self.hist[:self.nh]
            med = float(np.median(h))
            sig = max(1.4826 * float(np.median(np.abs(h - med))), self.sig_min)
            self.sigma_db = sig
            dev = d - med
            hit = np.abs(dev) > self.k * sig
            if not hit.any():                  # ふだんはここだけ（Python の 1 個ずつの回しを避ける）
                if self.open is not None:
                    self.quiet += n
                    if self.quiet >= self.gap:
                        out.append(self._close())
                self._push(d)
                self.i += n
                return out
            for j in range(n):
                if hit[j]:
                    if self.open is None:
                        self.open = dict(t_beat=int(tb[j]), i0=self.i + j, n=0, db=0.0, sigma_db=sig, ovr=False)
                    o = self.open
                    o["n"] += 1
                    if abs(dev[j]) > abs(o["db"]):
                        o["db"] = float(dev[j])
                    o["ovr"] = o["ovr"] or bool(fl[j] & TPF_OVR)
                    self.quiet = 0
                elif self.open is not None:
                    self.quiet += 1
                    if self.quiet >= self.gap:
                        out.append(self._close())
        self._push(d)
        self.i += n
        return out

    def _close(self):
        o, self.open, self.quiet = self.open, None, 0
        self.count += 1
        o["db"] = round(o["db"], 4)
        o["sigma_db"] = round(o["sigma_db"], 5)
        return o

    def finish(self):
        return [self._close()] if self.open is not None else []
