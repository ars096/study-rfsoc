#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj021 B2 — TP の跳ねの見張り（README の B2、検討事項 3 (2)）

ADC 1 本の TP（1 個 = 1.024 ms の Σx² / (nfr·8192)）を dB にし、直前 W 個（既定 1,000 ≒ 1 s）の中央値からのずれを、
同じ W 個の MAD による σ（下限 sig_min_db）の k 倍と比べる。越えた個が「跳ね」。続く跳ねは 1 回にまとめ
（跳ねでない個が gap 個続いたら閉じる）、閉じたものを返す。中央値は feed 1 回（TP の記録の区切り = 40 個）ごとに np.partition で
（np.median は A53 で 0.25 ms、partition は 0.05 ms。B2b）、σ（MAD）は sig_every 個（≒ 1 s）に 1 回だけ計算し直す。
phase で ADC ごとに計算し直す区切りをずらす（4 ADC が同じ周で重ならないように）。

    tj = TpJump()
    events = tj.feed(t_beat, power, flags)   # 配列（同じ長さ）。閉じた跳ねのリスト
    events += tj.finish()                    # RUN の終わりに開いている跳ねを閉じる

跳ね: dict(t_beat=最初の個の頭, i0=最初の個の通し番号, n=個の数, db=ずれの最大（符号つき）,
          step_db=閉じた区切りの中央値 − 開いた区切りの中央値（段差の大きさ。スパイク・瞬断だけなら ≒ 0）, sigma_db, ovr=FLAGS[4] があったか)
"""
import numpy as np

TPF_OVR = 16


class TpJump:
    def __init__(self, k=6.0, win=1000, warm=200, sig_min_db=0.002, gap=10, sig_every=1000, phase=0):
        self.k, self.win, self.warm, self.sig_min, self.gap = float(k), int(win), int(warm), float(sig_min_db), int(gap)
        self.sig_every, self.phase = int(sig_every), int(phase) % max(int(sig_every), 1)
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
        self.sig_next = 0              # σ を次に計算し直す通し番号（最初は暖まったところで）
        self.med = None                # 最後に計算した中央値
        self.n_sig = 0                 # σ を計算した回数（試験用）

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
            m = self.nh // 2
            med = float(np.partition(h, m)[m])
            # σ は sig_every 個に 1 回。ただし窓が溜まりきるまで（RUN の頭の ≒ 1 s）は毎回: 窓が伸びる間は中央値の遅れも伸びるので、
            # 短い窓で計った σ のままだと傾きで誤検出する（B2b の試験 (a) で 1 回出た）
            if self.sigma_db is None or self.nh < self.win or self.i >= self.sig_next:
                self.sigma_db = max(1.4826 * float(np.partition(np.abs(h - med), m)[m]), self.sig_min)
                self.n_sig += 1
                if self.sig_next == 0:
                    self.sig_next = self.i + self.sig_every - self.phase
                while self.sig_next <= self.i:
                    self.sig_next += self.sig_every
            sig = self.sigma_db
            self.med = med
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
                        self.open = dict(t_beat=int(tb[j]), i0=self.i + j, n=0, db=0.0, step_db=0.0, med0=med, sigma_db=sig, ovr=False)
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
        o["step_db"] = round(self.med - o.pop("med0"), 4)
        o["sigma_db"] = round(o["sigma_db"], 5)
        return o

    def finish(self):
        return [self._close()] if self.open is not None else []
