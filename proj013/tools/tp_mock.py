#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""pynq/spectrometer.py の --tp（total power の読み出しと判定）を、実機なしで回す模擬（proj013）。

    python3 tools/tp_mock.py            # 本番・陽性対照 3 通りを回して、それぞれが期待どおり OK / NG になるか

MMIO を Python で模し、時刻からフレーム番号を出して、tp_core の区切り・リングバッファ（512 個）と、
spec_core の RUN・ダンプ（SEQ・DUMP_*・スペクトル）を作る。spectrometer.Spec と tp_run をそのまま動かす。
**模擬が確かめるのは PS 側の論理だけ**（挟み読み・巻き戻り・F0 の個の探し方・番号の連続・パーセバルの式）。
RTL の振る舞いは sim（make sim-tp / make sim）が確かめる。

陽性対照（どれも NG になるべき）:
  seq    リングバッファの 1 個のフレームの番号を 1 つずらす       → TP-4 の「番号の飛び」
  stall  読み出しの途中で 0.7 s 止まる（512 個 = 0.512 s を越える）→ TP-4 の「読み落とし」
  parse  スペクトルの和を 2e-3 だけ小さくする                     → TP-1
"""
import os
import sys
import time
import types
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pynq"))
import spectrometer as S  # noqa: E402

T_FRAME = S.T_FRAME
SIGMA = 40.0                   # 入力の雑音の σ [LSB]


class FakeCore:
    def __init__(self, ch, mode):
        self.ch, self.mode = ch, mode
        self.t0 = time.time() - 0.3                 # Overlay から少し経った
        self.regs = {S.R_TP_N: 500, S.R_NACC: 50000, S.R_NDUMP: 0, S.R_SHIFT: 4}
        self.tp_n_eff = 500
        self.run_frame = None
        self.f0 = None
        self.stalled = False
        self.frozen = None                          # 読み出し窓が指しているダンプ
        # スナップショット: σ = SIGMA の雑音（16 bit、下位 2 bit は 0）。2 サンプルで 1 語
        x = (np.round(np.random.default_rng(ch).normal(0, SIGMA, 8192)).astype(np.int64) * 4) & 0xFFFF
        self.snapw = (x[0::2] | (x[1::2] << 16)).astype(np.uint32)

    def frame(self):
        return int((time.time() - self.t0) / T_FRAME)

    # ---- 区切り: F0 の前は 0 から TP_N（既定）で自走、F0 で打ち切り、F0 からは TP_N ずつ ----
    def bins_done(self):
        """閉じた区切りの (最初のフレーム, フレーム数, FLAGS) を、今の時刻までのぶんだけ返す（生成器ではなく数と関数）"""
        f = self.frame() - 1                        # 区切りは次の区切りの最初のビートで閉じる
        if self.f0 is None or f < self.f0:
            return f // 500, None
        pre = self.f0 // 500 + (1 if self.f0 % 500 else 0)   # F0 までに閉じた個（最後の 1 個は短い）
        post = max(0, (f - self.f0) // self.tp_n_eff)
        return pre + post, pre

    def bin(self, i):
        _, pre = self.bins_done()
        if pre is None or i < pre:
            f0 = 500 * i
            n = 500 if (self.f0 is None or f0 + 500 <= self.f0) else self.f0 - f0
            fl = (8 if i == 0 else 0) | (1 if n != 500 else 0)
        else:
            j = i - pre
            f0 = self.f0 + j * self.tp_n_eff
            n = self.tp_n_eff
            fl = 2 if j == 0 else 0
        rng = np.random.default_rng((self.ch << 40) + i)
        N = 8192 * n
        s = int(N * SIGMA ** 2 * (1.0 + rng.normal() * np.sqrt(2.0 / N)))
        if self.mode == "seq" and i == (pre or 0) + 700:
            f0 += 1
        return s, f0, n, fl

    def entry_words(self, slot):
        wp = self.bins_done()[0]
        i = wp - 1 - ((wp - 1 - slot) % 512)        # その slot に今入っている個
        s, f0, n, fl = self.bin(i)
        return [s & 0xFFFFFFFF, s >> 32, f0 & 0xFFFFFFFF, (fl << 24) | n]

    # ---- ダンプ ----
    def dumps_done(self):
        if self.f0 is None:
            return 0
        nacc = self.run_nacc
        return max(0, (self.frame() - self.f0 - 20) // nacc)   # FFT のレイテンシぶん遅れて閉じる

    def dump(self, k):
        nacc, n = self.run_nacc, self.tp_n_eff
        f0 = self.f0 + k * nacc
        _, pre = self.bins_done()
        T = sum(self.bin(pre + (f0 - self.f0) // n + j)[0] for j in range(nacc // n))
        sh = self.run_shift
        v = 8192.0 * T / (8191.0 * 4.0 ** sh) * (1.0 - 2e-5 - (2e-3 if self.mode == "parse" else 0.0))
        spec = np.full(4096, int(round(v)), dtype=np.uint64)
        return dict(k=k, n=nacc, f0=f0, spec=spec)

    # ---- MMIO ----
    def read(self, a):
        if self.mode == "stall" and not self.stalled and self.f0 is not None and time.time() - self.t0 > 1.5:
            self.stalled = True
            time.sleep(0.7)
        if a == S.R_ID:
            return 0x001301CC
        if a == S.R_BUILD:
            return (1 << 30) | (1 << 28) | S.BUILD_4CH | self.ch
        if a == S.R_TP_PARAM:
            return S.TP_PARAM_EXPECT
        if a == S.R_TP_WP:
            return self.bins_done()[0]
        if a == S.R_TP_NEFF:
            return self.tp_n_eff
        if a in (S.R_RUN_F0_LO, S.R_TP_F0_LO):
            return (self.f0 or 0) & 0xFFFFFFFF
        if a in (S.R_RUN_F0_HI, S.R_TP_F0_HI):
            return (self.f0 or 0) >> 32
        if a == S.R_SEQ:
            nd = self.dumps_done()
            if nd > 0 and (self.frozen is None or self.frozen["k"] != nd - 1):
                self.frozen = self.dump(nd - 1)
            return nd
        if a == S.R_FLAGS:
            return 0
        fr = self.frozen or dict(k=0, n=0, f0=0, spec=np.zeros(4096, np.uint64))
        return {S.R_DUMP_K: fr["k"], S.R_DUMP_N: fr["n"], S.R_DUMP_F0_LO: fr["f0"] & 0xFFFFFFFF,
                S.R_DUMP_F0_HI: fr["f0"] >> 32, S.R_DUMP_SAT: 0, S.R_BANK: 0,
                S.R_SNAP_F_LO: 0, S.R_SNAP_F_HI: 0}.get(a, self.regs.get(a, 0))

    def write(self, a, v):
        if a == S.R_CTRL and v & S.CTRL_RUN:
            self.run_frame = self.frame()
            self.f0 = self.run_frame + 2
            self.tp_n_eff = self.regs[S.R_TP_N] or 1
            self.run_nacc = self.regs[S.R_NACC]
            self.run_shift = self.regs[S.R_SHIFT]
            self.frozen = None
        else:
            self.regs[a] = v

    @property
    def array(self):
        core = self

        class A:
            def __getitem__(self, sl):
                a0, a1 = 4 * sl.start, 4 * sl.stop
                # 1 回の読み出しは 1 つの領域に収まる（Spec.block の使い方）。領域ごとにまとめて作る（模擬を速く保つ）
                if S.SNAP_BASE <= a0 and a1 <= S.SPEC_BASE:
                    return core.snapw[(a0 - S.SNAP_BASE) // 4:(a1 - S.SNAP_BASE) // 4]
                if a0 >= S.SPEC_BASE:
                    spec = (core.frozen or {}).get("spec")
                    if spec is None:
                        spec = np.zeros(4096, np.uint64)
                    w = np.empty(8192, np.uint32)
                    w[0::2] = (spec & np.uint64(0xFFFFFFFF)).astype(np.uint32)
                    w[1::2] = (spec >> np.uint64(32)).astype(np.uint32)
                    return w[(a0 - S.SPEC_BASE) // 4:(a1 - S.SPEC_BASE) // 4]
                out = []
                for i in range(sl.start, sl.stop):
                    a = 4 * i
                    if S.TP_BASE <= a < S.TP_BASE + 16 * 512:
                        out.append(core.entry_words((a - S.TP_BASE) // 16)[(a % 16) // 4])
                    else:
                        out.append(core.read(a))
                return np.array(out, dtype=np.uint32)
        return A()


def run(mode, seconds=3.0):
    specs = [S.Spec(FakeCore(i, mode), idx=i, label=S.CHANS[i][0]) for i in range(4)]
    args = types.SimpleNamespace(tp=seconds, tp_n=500, nacc="50000", tp_no_spec=False, out=None,
                                 bitfile="mock", clkin="mock")
    return S.tp_run(specs, args, {i: 4 for i in range(4)})


if __name__ == "__main__":
    want = {"normal": True, "seq": False, "stall": False, "parse": False}
    res = {}
    for mode, w in want.items():
        print(f"\n######## 模擬: {mode}（期待 {'OK' if w else 'NG'}）########")
        res[mode] = run(mode)
    print()
    bad = [m for m, w in want.items() if res[m] != w]
    for m, w in want.items():
        print(f"  {m:7s} 期待 {'OK' if w else 'NG'} → {'OK' if res[m] else 'NG'}")
    print("結果: " + ("全部通過" if not bad else f"期待と違う: {bad}"))
    sys.exit(1 if bad else 0)
