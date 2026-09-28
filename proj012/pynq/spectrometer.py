#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj012 — 4 本の分光計（ADC_A〜D → 8192 点 FFT → 電力 → 積分）を動かし、判定する。

proj011 の spectrometer.py を 4 本にしたもの。**`--ch` で選ぶ（既定 all）。**判定は選んだ ch を順に回す。
起動のたびに 4 個の spec_core すべてについて、ID・BUILD の ch の番号（[1:0]）がセル名と合うかを確かめる。
4 本すべてのタイルを確かめ、4 本すべてのブロックにナイキストゾーンを設定する（選ばなかった ch も）。
ch の番号 i = 0..3 = ADC_A..D（build.tcl の chans と対。VERSIONS.md の実測）。

4 本で初めて出るもの:
  --probe（2 本以上）   ch ごとの判定 0 の後に、読み出しの時間・FIN のずれ・RUN の開始のずれを出す
  --tone（2 本以上）    線の強さの ch 間の比。`--split` なら 4 分配の一致（≦ 0.3 dB）、`--leak-from I` なら漏れ（≦ −59 dBc）を判定
長い記録（--record / --tick / --flag-timeline）は 1 本ずつ（`--ch` で 1 本を選ぶ）。

PL の spec_core が 1 フレーム 8192 サンプル（2.000 µs）ごとに FFT して電力を積み、
N_ACC フレームごとに 1 ダンプ（4096 ch × 64 bit）を閉じる。PS は AXI4-Lite で
凍っている面を読むだけ。レジスタの意味は src/spec_core.v の冒頭が正。

**周波数軸（ゾーン 2）: ch k は IF = 4096 − 0.5·k MHz。**ch 0 が 4096 MHz、ch 4095 が 2048.5 MHz。
スペクトルは反転している（proj009 と同じ）。

使い方（ボード上で sudo が要る）:

    sudo python3 spectrometer.py --clkin 0 --probe                  # 判定 0: 4 本とも・読み出しの時間・開始のずれ
    sudo python3 spectrometer.py --clkin 0 --ch B --probe           # 1 本だけ（0〜3 か A〜D。カンマ区切りで複数）
    sudo python3 spectrometer.py --clkin 0 --tone 3000.0 --split    # 4 分配した同じ線が 4 本で揃うか
    sudo python3 spectrometer.py --clkin 0 --tone 3000.0 --leak-from 0   # ADC_A だけに入れ、残り 3 本への漏れ
    sudo python3 spectrometer.py --clkin 0 --golden --tone 3000.25  # 判定 2: 同じフレームを numpy と照合
    sudo python3 spectrometer.py --clkin 0 --tone 3000.25           # 判定 1: 線がどの ch に立つか
    sudo python3 spectrometer.py --clkin 0 --radiometer --ndump 50  # 判定 3: σ/μ = 1/√(Δν·τ)
    sudo python3 spectrometer.py --clkin 0 --radiometer --nacc 5000,50000,500000 --ndump 30
    sudo python3 spectrometer.py --clkin 0 --ndump 100 --save run.npz   # 記録（メモリに溜めてから書く。短い記録向け）
    sudo python3 spectrometer.py --clkin 0 --nacc 500000 --record 3600 --out noise1h   # 長時間の連続記録（アラン分散）

1PPS が ADC に入ったまま（SG なし）でできるもの:

    sudo python3 spectrometer.py --clkin 0 --tick 60                     # 判定 7: PPS の縁で積分の連続性を見る
    sudo python3 spectrometer.py --clkin 0 --nacc 500000 --ndump 60 --peaks 30   # 判定 8: 固定の線（60 s 積分）

**トーンを 0.5 MHz の倍数に置くと ch の中心に立つ**（3000.0 MHz → ch 2192）。
0.25 MHz ずらすと ch の境目に落ち、矩形窓の落ち込み（−3.92 dB）が見える。

**レベルを測るときは `--sg-dbm` と `--atten-db` を必ず付ける**（proj003 → proj005 の教訓）。
"""

import argparse
import sys
import time

import numpy as np

BITFILE = "proj012.bit"
FS_HZ = 4096.0e6
NFFT = 8192
NCH_OUT = 4096
DF_HZ = FS_HZ / NFFT              # 0.5 MHz
T_FRAME = NFFT / FS_HZ            # 2.000 µs
ID_EXPECT = 0x00120000            # proj012。[15:8] は rev（1 / 2）、[7:0] は FFT_CFG（変種）なので比べない
ID_MASK = 0xFFFF0000


def feat_rev(ident):
    """機能の世代を proj011 の rev 番号で返す（**機能の有無の判定はこれで行う**）。

    proj011 の PS 側は「rev ≧ 4 なら SRST・≧ 6 なら GRST」のように ID の [15:8] で機能を切り替えている。
    proj012 は rev1 から proj011 rev6 の機能をすべて持つので、生の rev をそのまま比べると
    GRST・生の見張り・BUILD の照合が**黙って旧い道に落ちる**（2026-09-28、複製の直後に気づいた）。
    表示には生の rev（fft_cfg_str）を使う。
    """
    rev = (ident >> 8) & 0xFF
    if (ident & ID_MASK) == 0x00120000:
        return 6
    return rev


def fft_cfg_str(ident):
    """ID の下位 8 bit（src/fft_cfg.tcl の fft_cfg_code）を読める形にする。"""
    c = ident & 0xFF
    thr = "realtime" if c & 1 else "nonrealtime"
    cmul = "use_luts" if c & 8 else ("use_mults_resources" if c & 2 else "use_mults_performance")
    bfly = "use_luts" if c & 4 else "use_xtremedsp_slices"
    name = {0x07: "res", 0x01: "perf"}.get(c, "?")
    return f"rev{(ident >> 8) & 0xFF} / FFT_CFG 0x{c:02x} = {name}（{thr} / {cmul} / {bfly}）"

LMK_FREQ = 245.76
LMX_FREQ = 491.52
# ch の番号 i = 0..3（spec_core_i）→ (SMA のラベル, PYNQ の adc_tiles の番号, blocks の番号)。**VERSIONS.md の実測が正**:
#   ADC_A = Tile 226 / slice 2 = adc_tiles[2].blocks[1]   ADC_B = Tile 226 / slice 0 = adc_tiles[2].blocks[0]
#   ADC_C = Tile 224 / slice 2 = adc_tiles[0].blocks[1]   ADC_D = Tile 224 / slice 0 = adc_tiles[0].blocks[0]
CHANS = [("ADC_A", 2, 1), ("ADC_B", 2, 0), ("ADC_C", 0, 1), ("ADC_D", 0, 0)]
BUILD_4CH = 1 << 23               # BUILD の [23] 4ch のビルド / [1:0] ch の番号（build.tcl の BUILD_TAG）

# ---- レジスタ（src/spec_core.v の冒頭と対）----
R_ID, R_PARAM, R_CTRL, R_NACC, R_NDUMP, R_SHIFT = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14
R_FLAGS, R_SEQ, R_FIN_LO, R_FIN_HI, R_FOUT_LO, R_FOUT_HI = 0x18, 0x1C, 0x20, 0x24, 0x28, 0x2C
R_DUMP_K, R_DUMP_N, R_DUMP_F0_LO, R_DUMP_F0_HI, R_DUMP_SAT = 0x30, 0x34, 0x38, 0x3C, 0x40
R_SNAP_F_LO, R_SNAP_F_HI, R_BANK, R_RUN_F0_LO, R_RUN_F0_HI = 0x44, 0x48, 0x4C, 0x50, 0x54
SNAP_BASE, SPEC_BASE = 0x4000, 0x8000
CTRL_RUN, CTRL_STOP, CTRL_CLR, CTRL_DCLR = 1 << 0, 1 << 1, 1 << 8, 1 << 9
R_DIAG_TL, R_DIAG_EV, R_DIAG_FS, R_DIAG_EVCNT, R_DIAG_FSCNT = 0x58, 0x5C, 0x60, 0x64, 0x68   # rev3
R_BUILD, R_SRST_D, R_SRST_E, R_SRST_CNT = 0x6C, 0x70, 0x74, 0x78                             # rev4
R_ST_GAPS, R_ST_CYC = 0x7C, 0x80                                                              # rev5
R_GB_K, R_ST_N, R_INJ, R_GRST_T, R_GRST_ADJ, R_GRST_CNT = 0x84, 0x88, 0x8C, 0x90, 0x94, 0x98     # rev6
R_RAW_T0, R_RAW_GAPS, R_RAW_FIRST, R_RAW_MAXLEN = 0x9C, 0xA0, 0xA4, 0xA8
R_GB_STAT, R_ADC_STAT, R_INJ_CNT = 0xAC, 0xB0, 0xB4
CTRL_GRST = 1 << 11
INJ_ARM, INJ_AFTER_GRST = 1 << 31, 1 << 30
F_CORE = 256.0e6                  # spec_core のクロック（clk_adc2 = fs/16）
CTRL_SRST = 1 << 10

FLAG_NAMES = ["レーンの出力 valid が不揃い", "レーンの XK_INDEX が不揃い", "レーンの入力 ready が不揃い",
              "IP が入力を受けなかった（サンプル落ち）", "入力に隙間", "IP の TLAST 事象",
              "IP の data_in_channel_halt", "XK_INDEX が 1 ずつ進まない"]


def log(*a):
    print(*a, flush=True)


def ch_of_if(f_mhz, zone=2):
    """IF [MHz] → ch（小数）。ゾーン 2 は fs − f に折り返る。"""
    fa = FS_HZ / 1e6 - f_mhz if zone == 2 else f_mhz
    return fa / (DF_HZ / 1e6)


def if_of_ch(k, zone=2):
    fa = np.asarray(k) * DF_HZ / 1e6
    return FS_HZ / 1e6 - fa if zone == 2 else fa


# --------------------------------------------------------------------- spec_core
class Spec:
    """spec_core の AXI4-Lite。**読んだ中身は seqlock で 1 つのダンプのものと保証する。**"""

    def __init__(self, mmio, slow=False, idx=0, label="?"):
        self.m = mmio
        self.slow = slow
        self.idx = idx
        self.label = label

    def rd(self, a):
        return self.m.read(a)

    def wr(self, a, v):
        self.m.write(a, int(v))

    def rd64(self, lo, hi):
        l = self.rd(lo)                      # LO を読むと HI が固定される（FIN / FOUT）
        return (self.rd(hi) << 32) | l

    def block(self, base, nwords):
        """32 bit 語を nwords 個読む。既定は numpy で一括（速い）。--slow-read で 1 語ずつ。"""
        if self.slow:
            return np.array([self.rd(base + 4 * i) for i in range(nwords)], dtype=np.uint32)
        i0 = base // 4
        return np.array(self.m.array[i0:i0 + nwords], dtype=np.uint32)

    def flags(self):
        return self.rd(R_FLAGS)

    def meta(self):
        return dict(
            seq=self.rd(R_SEQ), k=self.rd(R_DUMP_K), n=self.rd(R_DUMP_N),
            f0=(self.rd(R_DUMP_F0_HI) << 32) | self.rd(R_DUMP_F0_LO),
            sat=self.rd(R_DUMP_SAT),
            snap_f=(self.rd(R_SNAP_F_HI) << 32) | self.rd(R_SNAP_F_LO),
            bank=self.rd(R_BANK), flags=self.rd(R_FLAGS))

    def run(self, nacc, ndump, shift):
        self.wr(R_NACC, nacc)
        self.wr(R_NDUMP, ndump)
        self.wr(R_SHIFT, shift)
        seq0 = self.rd(R_SEQ)
        self.wr(R_CTRL, CTRL_RUN)
        return seq0

    def arm(self, nacc, ndump, shift):
        """RUN の前の設定だけを書く（4 本の開始を揃えるとき、RUN の書き込みを 1 語ずつ続けて打てるように）"""
        self.wr(R_NACC, nacc)
        self.wr(R_NDUMP, ndump)
        self.wr(R_SHIFT, shift)

    def stop(self):
        self.wr(R_CTRL, CTRL_STOP)

    def wait_dump(self, seq_prev, timeout):
        t0 = time.time()
        while True:
            s = self.rd(R_SEQ)
            if s != seq_prev:
                return s
            if time.time() - t0 > timeout:
                return None
            time.sleep(0.001)

    def read_dump(self, with_snap=False, tries=5):
        """凍っている面を読む。**SEQ が読む前後で同じなら 1 つのダンプ。**違えば読み直す。"""
        for _ in range(tries):
            m = self.meta()
            w = self.block(SPEC_BASE, 2 * NCH_OUT)
            spec = w[0::2].astype(np.uint64) | (w[1::2].astype(np.uint64) << np.uint64(32))
            snap = None
            if with_snap:
                s = self.block(SNAP_BASE, NFFT // 2)
                snap = np.empty(NFFT, dtype=np.int16)
                snap[0::2] = (s & 0xFFFF).astype(np.uint16).view(np.int16)
                snap[1::2] = (s >> 16).astype(np.uint16).view(np.int16)
            if self.rd(R_SEQ) == m["seq"]:
                return m, spec, snap
        raise RuntimeError("読み出しのあいだに毎回ダンプが閉じた。積分時間に対して読み出しが遅すぎる")


def flag_text(f):
    return "なし" if f == 0 else " / ".join(n for i, n in enumerate(FLAG_NAMES) if f >> i & 1)


# --------------------------------------------------------------------- 起動（proj009 の adc_capture.py から）
def setup_clocks(clkin="stock", ref_mhz=10.0):
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


def check_tiles(rfdc, zone):
    """タイルは Overlay の時点で動いている。**触らずに確かめ、4 本すべてのブロックにゾーンだけ設定して読み返す。**

    **起動・停止はしない**（VERSIONS.md: 複数タイルへの ShutDown() は順序を直しても成立しない）。
    選ばなかった ch もゾーンを設定する（ch によって周波数軸が違う状態を作らない）。
    """
    for t in sorted({t for _, t, _ in CHANS}, reverse=True):     # 源のタイル（226）から見る
        tile = rfdc.adc_tiles[t]
        lock = tile.PLLLockStatus
        log(f"Tile {224 + t}: PLLLockStatus = {lock}（2 = locked）")
        if lock != 2:
            log(f"ERROR: Tile {224 + t} のタイル PLL がロックしていない")
            sys.exit(1)
    for i, (lbl, t, b) in enumerate(CHANS):
        block = rfdc.adc_tiles[t].blocks[b]
        st = block.BlockStatus
        if abs(st.get("SamplingFreq", 0) * 1e9 - FS_HZ) > 1e3:
            log(f"ERROR: ch {i}（{lbl}）の fs が {st.get('SamplingFreq')} GSPS")
            sys.exit(1)
        block.NyquistZone = zone
        if block.NyquistZone != zone:
            log(f"ERROR: ch {i}（{lbl}）の NyquistZone が {block.NyquistZone} のまま（要求 {zone}）")
            sys.exit(1)
        log(f"ch {i}（{lbl} = Tile {224 + t} / blocks[{b}]）: SamplingFreq {st.get('SamplingFreq')} GSPS / NyquistZone = {zone}")


def open_specs(ol, args):
    """spec_core_0..3 を開き、**全部について** ID と BUILD の ch の番号を確かめる。選んだ ch の Spec を返す。

    同じ RTL の 4 個を見分けるのは BUILD の [1:0] だけ。セル名 spec_core_i と BUILD の ch = i が合わなければ、
    ch の取り違え（ラベルと中身が別の ch）なので止める。
    """
    specs = []
    for i, (lbl, _, _) in enumerate(CHANS):
        ip = getattr(ol, f"spec_core_{i}", None)
        if ip is None:
            log(f"ERROR: ol.spec_core_{i} が無い。1ch の .bit（proj011 など）が載っていないか")
            sys.exit(1)
        sp = Spec(ip.mmio, slow=args.slow_read, idx=i, label=lbl)
        ident = sp.rd(R_ID)
        if (ident & ID_MASK) != ID_EXPECT:
            log(f"ERROR: spec_core_{i} の ID {ident:08x} の上位 16 bit が {ID_EXPECT >> 16:04x} でない。別の proj の .bit が載っている")
            sys.exit(1)
        bt = sp.rd(R_BUILD)
        preset, grade, is4, chn = (bt >> 30) & 1, (bt >> 28) & 3, bool(bt & BUILD_4CH), bt & 3
        log(f"spec_core_{i}（{lbl}）: ID {ident:08x} / {fft_cfg_str(ident)} / BUILD {bt:08x}"
            f"（プリセット {'あり' if preset else '**なし**'} / -{grade} / 4ch {int(is4)} / ch {chn}）")
        if not is4 or chn != i:
            log(f"ERROR: spec_core_{i} の BUILD が「4ch・ch {i}」でない（4ch {int(is4)} / ch {chn}）。セルと ch の対応が崩れている")
            sys.exit(1)
        if (bt >> 27) & 1:
            log(f"NOTE: **遅いビットの検証ビルド**（gb_fifo の gray の bit {(bt >> 24) & 7} をわざと遅らせてある。本番に使わない）")
        if not preset and not args.allow_nopreset:
            log("ERROR: プリセットの無い検証ビルド（build-1-e*/ など）が載っている。実機には build/ の .bit を使う")
            sys.exit(1)
        specs.append(sp)
    return [specs[i] for i in args.chs]


def parse_ch(text):
    """--ch: all / 0〜3 / A〜D（ADC_A〜D）。カンマ区切り。"""
    if text.strip().lower() == "all":
        return list(range(len(CHANS)))
    out = []
    for v in text.split(","):
        v = v.strip().upper().replace("ADC_", "")
        if v.isdigit() and 0 <= int(v) < len(CHANS):
            out.append(int(v))
        elif len(v) == 1 and "A" <= v <= "D":
            out.append(ord(v) - ord("A"))
        else:
            raise ValueError(f"--ch の '{v}' が読めない（all / 0〜3 / A〜D）")
    return sorted(set(out))


def auto_shift(sp):
    """SHIFT: 雑音の成分の σ が SHIFT 後に 2^9 付近になるように選ぶ（強い線が 18 bit に収まる余地を残す）。ch ごと"""
    sp.run(1, 1, 0)
    time.sleep(0.01)
    _, _, snap = sp.read_dump(with_snap=True)
    sx = (snap.astype(np.int64) >> 2).std()
    sz = sx * np.sqrt(NFFT / 2)                    # 成分あたり
    shift = int(max(0, min(15, np.ceil(np.log2(max(sz, 1) / 512)))))
    log(f"SHIFT = {shift}（auto: 入力 std {sx:.1f} LSB → 成分の σ {sz:.0f} → {sz / 2 ** shift:.0f} LSB）")
    return shift


def multi_probe(specs, exact_ok=True):
    """判定 0 の 4 本の部分: 読み出しの時間・FIN のずれ・RUN を順に書いたときの開始のずれ。

    **FIN は ch ごとに別の起動から数えている**（ギアボックスごとに流れ始めが違う）ので、番号どうしは比べられない。
    先に FIN を並べて読んでずれ（オフセット）を測り、RUN_F0 からそのずれを引いて、開始の実時間のずれに直す。
    読み出し 1 回（rd64 = 2 語）に数 µs かかるので、ずれは ±数フレーム（1 フレーム = 2 µs）の精度。
    """
    ok = True
    # 読み出しの時間（1 ダンプ = 4096 ch × 64 bit）
    dts = []
    for sp in specs:
        t0 = time.perf_counter()
        sp.read_dump()
        dts.append(time.perf_counter() - t0)
    t0 = time.perf_counter()
    for sp in specs:
        sp.read_dump()
    tall = time.perf_counter() - t0
    log("読み出しの時間（1 ダンプ）: " + " / ".join(f"{sp.label} {dt * 1e3:.1f} ms" for sp, dt in zip(specs, dts))
        + f" / {len(specs)} 本続けて {tall * 1e3:.1f} ms（予言 4 本で 5〜20 ms）")
    ok &= tall < 0.05                                # 100 ms のダンプに対して半分以内
    # FIN のずれ: ch 0 → ch i → ch 0 と挟んで読み、ch i を読んだ瞬間の ch 0 の FIN を前後の 2 つの間に閉じ込める。
    # 何度も挟んで区間を狭める（判定 0 の深さと同じ方法）。2026-09-28 の初版は「順と逆順の平均」で、
    # PYNQ の MMIO の 1 読み（≒ 10 µs）が遅く ± 36 フレームになった
    def offset(sp, n=300):
        lo, hi = -10**12, 10**12
        for _ in range(n):
            a = specs[0].rd64(R_FIN_LO, R_FIN_HI)
            x = sp.rd64(R_FIN_LO, R_FIN_HI)
            b = specs[0].rd64(R_FIN_LO, R_FIN_HI)
            lo, hi = max(lo, x - b), min(hi, x - a)
        return lo, hi
    offs = [(0, 0)] + [offset(sp) for sp in specs[1:]]
    log("FIN のずれ（ch 0 を基準、挟み読みの区間、フレーム）: "
        + " / ".join(f"{sp.label} [{lo}, {hi}]" for sp, (lo, hi) in zip(specs, offs)))
    if any(lo > hi for lo, hi in offs):
        log("  **区間が成り立たない ch がある**（下限 > 上限。FIN の読み方か、ch 間で FIN の進む速さが違う）")
    # **ハードの数えから出すずれ（こちらを正とする）。**4 個の spec_core は同じ rst_dsp で同じクロックに起動し、
    # ST_CYC（起動から見張りが口を開けるまでのクロック数）の後から FIN を数える。1 フレーム = 512 クロックなので、
    # ずれ = (ST_CYC_0 − ST_CYC_i) / 512 フレームが 1 クロック単位で分かる（挟み読みは MMIO の遅さで ± 8 フレーム止まり。
    # 2026-09-28 の 2 回目の実機で、区間の幅 16〜17 フレームから気づいた）。挟み読みの区間と食い違わないかも見る
    if exact_ok:
        cyc = [sp.rd(R_ST_CYC) for sp in specs]
        exact = [(cyc[0] - c) / 512.0 for c in cyc]
        agree = all(lo - 1 <= e <= hi + 1 for e, (lo, hi) in zip(exact, offs))
        log("FIN のずれ（ST_CYC の差から、フレーム）: " + " / ".join(f"{sp.label} {e:+.3f}" for sp, e in zip(specs, exact))
            + f" → 挟み読みの区間と {'合う' if agree else '**食い違う**（FIN が口の開いた時点から数えていない？）'}")
        ok &= agree
    else:
        # --startup-grst の後は ch ごとに PS が別々の時刻に GRST をかけたので、ST_CYC の差はずれを表さない
        exact = [(lo + hi) / 2.0 for lo, hi in offs]
        log("FIN のずれ: 起動の GRST（--startup-grst）の後なので ST_CYC の差は使えない。挟み読みの区間の中心を使う（± 8 フレーム）")
    # RUN の開始のずれ。設定（N_ACC・N_DUMP・SHIFT）を先に全部に書き、RUN だけを 1 語ずつ続けて打つ。
    # 初版は 1 本ずつ run()（5 回の読み書き）で、1 本あたり ≒ 25 フレーム（50 µs）ずれた（予言 0〜5 の外れ）
    def run_skew(order):
        for sp in specs:
            sp.arm(50000, 1, 4)
        for i in order:
            specs[i].wr(R_CTRL, CTRL_RUN)
        f0 = [sp.rd64(R_RUN_F0_LO, R_RUN_F0_HI) for sp in specs]
        for sp in specs:
            sp.stop()
        return [f - f0[0] - e for f, e in zip(f0, exact)]
    for name, order in (("順（0 → 3）", range(len(specs))), ("逆順（3 → 0）", reversed(range(len(specs))))):
        sk = run_skew(list(order))
        base = "ST_CYC のずれ" if exact_ok else "挟み読みのずれ（± 8）"
        log(f"RUN の開始のずれ {name}（RUN_F0 − {base}、ch 0 基準、フレーム）: "
            + " / ".join(f"{sp.label} {k:+.2f}" for sp, k in zip(specs, sk))
            + f"（幅 {max(sk) - min(sk):.2f}。予言 1 本あたり ≒ 5・4 本で 0〜15。RUN_F0 は FIN + 2 なので ±1 の丸めを含む）")
    for sp in specs:
        sp.wr(R_CTRL, CTRL_CLR)
    log(f"4 本の部分: {'OK' if ok else '**NG**（読み出しが遅いか、FIN のずれが 2 つの測り方で食い違う）'}")
    return ok


# --------------------------------------------------------------------- 判定
def probe(sp):
    """判定 0: 流れているか。fin − fout が一定か。フレームが 1 秒に 500,000 進むか。"""
    ident, prm = sp.rd(R_ID), sp.rd(R_PARAM)
    log(f"ID = {ident:08x}（期待 {ID_EXPECT:08x} の上位 16 bit、{fft_cfg_str(ident)}） / PARAM = {prm:08x}"
        f"（log2 N = {prm & 0xFF} / log2 レーン = {prm >> 8 & 0xFF} / QW = {prm >> 16 & 0xFF} / IW = {prm >> 24}）")
    ok = (ident & ID_MASK) == ID_EXPECT
    fin0, t0 = sp.rd64(R_FIN_LO, R_FIN_HI), time.time()
    time.sleep(1.0)
    fin1, t1 = sp.rd64(R_FIN_LO, R_FIN_HI), time.time()
    rate = (fin1 - fin0) / (t1 - t0)
    log(f"FIN  {fin0} → {fin1}（{rate:,.0f} フレーム/s、期待 {1 / T_FRAME:,.0f}。PS 側の時計で測るので ±0.1 % 程度）")
    ok &= abs(rate * T_FRAME - 1) < 5e-3

    # **FIN と FOUT は別々の AXI4-Lite 読み出しで、間に数十 µs（= 十数フレーム）空く。**
    # 1 回ずつ読んで差を取ると、パイプラインの深さではなく「読み出しの間隔」を測ってしまう
    # （2026-09-19 の初回: FIN − FOUT = −9 → −11。負になるのは FOUT を後で読んでいるため）。
    # FIN → FOUT → FIN と挟んで読めば、FOUT を読んだ瞬間の FIN は前後の 2 つの間にある。
    # 何度も挟んで区間を狭め、深さ L を [下限, 上限] で出す。**時間をおいて 2 回測り、区間が重なれば一定**。
    def depth(n=300):
        lo, hi = -10**9, 10**9
        for _ in range(n):
            a = sp.rd64(R_FIN_LO, R_FIN_HI)
            o = sp.rd64(R_FOUT_LO, R_FOUT_HI)
            b = sp.rd64(R_FIN_LO, R_FIN_HI)
            lo, hi = max(lo, a - o), min(hi, b - o)
        return lo, hi
    d0 = depth()
    time.sleep(5.0)
    d1 = depth()
    log(f"パイプラインの深さ FIN − FOUT（挟み読みの区間）: [{d0[0]}, {d0[1]}] → 5 s 後 [{d1[0]}, {d1[1]}] フレーム")
    cons = d0[0] <= d0[1] and d1[0] <= d1[1]
    same = cons and max(d0[0], d1[0]) <= min(d0[1], d1[1])
    log(f"  区間が成り立つ（下限 ≦ 上限）: {'OK' if cons else '**NG**（カウンタの読み方か意味が想定と違う）'} / "
        f"2 回が重なる = 一定: {'OK' if same else '**NG**（IP がフレームを落としたか、足した）'}")
    ok &= same
    f = sp.flags()
    log(f"FLAGS = {f:02x}（{flag_text(f)}）")
    ok &= f == 0
    # 一括読み出しと 1 語ずつの読み出しが一致するか（MMIO の読み方の確認）
    a = Spec(sp.m, slow=False).block(SPEC_BASE, 64)
    b = Spec(sp.m, slow=True).block(SPEC_BASE, 64)
    log(f"一括読み出しと 1 語ずつの読み出し: {'一致' if np.array_equal(a, b) else '**不一致**（--slow-read を使う）'}")
    ok &= np.array_equal(a, b)
    log(f"判定 0: {'OK' if ok else '**NG**'}")
    return ok


def golden(sp, shift, tone):
    """判定 2: N_ACC = 1 のダンプと、同じフレームのスナップショットを numpy で FFT したものが一致するか。"""
    seq0 = sp.run(1, 1, shift)
    if sp.wait_dump(seq0, 1.0) is None:
        log("ERROR: 1 フレームのダンプが閉じない")
        return False
    m, spec, snap = sp.read_dump(with_snap=True)
    log(f"DUMP: seq {m['seq']} / F0 {m['f0']} / N {m['n']} / SAT {m['sat']} / SNAP_F {m['snap_f']} / "
        f"FLAGS {m['flags']:02x}")
    ok = m["snap_f"] == m["f0"]
    log(f"SNAP_F == DUMP_F0: {'OK' if ok else '**違う**（スナップショットが別のフレーム）'}")
    ok &= bool(np.all(snap & 3 == 0))
    x = (snap.astype(np.int64) >> 2).astype(float)
    X = np.fft.fft(x)[:NCH_OUT]
    ref = np.abs(X) ** 2 / 4.0 ** shift
    hw = spec.astype(float)
    good = ref < 0.9 * (2 ** 17 - 1) ** 2                # 飽和した ch は除く
    # 許容は「2 LSB ＋ 同じ k1（= k mod 512 とその鏡像）の組の最大振幅 × 3e-5」。
    # ひねり係数の丸めの誤差はレーン FFT の出力 Y_p[k1] に比例し、Y_p[k1] には k1 を共有する ch が全部乗る。
    # **強い線は 512 ch おきの ch に −100 dBc 級の誤差を落とす**（sim の SHIFT 4 で確認。sim/check.py）
    full = np.abs(np.fft.fft(x)) / 2.0 ** shift
    grp = full.reshape(-1, 512).max(axis=0)              # [k1]
    k1 = np.arange(NCH_OUT) % 512
    gmax = np.maximum(grp[k1], grp[(512 - k1) % 512])
    d = np.abs(np.sqrt(hw) - np.sqrt(ref))[good]
    # **FFT IP の内部の丸め**（unscaled でも各段のひねり係数の積を入力の LSB で丸める）は、後段の変換で
    # √(残りの点数) 倍に増幅され、**入力の大きさに依らない絶対量**として出る。512 点の基数 2 を各段で丸める
    # 模型（2026-09-19）では、|X| の差の平均 ≒ 8 LSB・最大（4096 ch 中）≒ 45〜65 LSB（SHIFT 0 のとき）。
    # 初回の実機は 9.5 / 61 で、模型と合った。sim のモデルは倍精度の FFT で丸めないので、この項が無かった。
    fl_mean, fl_max = 8.0 / 2 ** shift, 65.0 / 2 ** shift
    tol_max = 2.0 * fl_max + 2.0 + 3e-5 * gmax[good]
    w = int(np.argmax(d / tol_max))
    log(f"振幅の差（SHIFT 後の LSB）: 平均 {d.mean():.2f}（IP の丸めの模型 {fl_mean:.2f}）/ "
        f"最大 {d.max():.2f}（模型 {fl_max:.1f}）/ 差/許容 の最大 {(d / tol_max)[w]:.2f}（{good.sum()} ch）")
    ok &= bool(d.mean() < 2.0 * fl_mean + 1.0) and bool(np.all(d < tol_max))
    xs = x.std()
    log(f"スナップショット: std {xs:.1f}（14 bit の LSB）/ max|x| {np.abs(x).max():.0f}")
    if tone is not None:
        k = int(np.argmax(hw[1:])) + 1
        log(f"最大の ch = {k}（IF {if_of_ch(k):.3f} MHz）/ トーンの期待 ch = {ch_of_if(tone):.2f}")
    return ok


def diag_report(sp, label):
    """rev3 の診断レジスタを読んで 1 行ずつ出す。rev2 以前の .bit では読まない（0xDEADBEEF が返る）。"""
    if feat_rev(sp.rd(R_ID)) < 3:
        log(f"  診断（{label}）: rev3 以降の .bit でないので読まない")
        return None
    tl, ev, fs = sp.rd(R_DIAG_TL), sp.rd(R_DIAG_EV), sp.rd(R_DIAG_FS)
    evc, fsc = sp.rd(R_DIAG_EVCNT), sp.rd(R_DIAG_FSCNT)
    fin = sp.rd64(R_FIN_LO, R_FIN_HI)
    ux, ms = tl & 0xFFFF, tl >> 16
    log(f"  診断（{label}）: TLAST unexpected のレーン {ux:016b} / missing のレーン {ms:016b}"
        f"（{bin(ux).count('1')} / {bin(ms).count('1')} 本）")
    if ev >> 31:
        typ = {1: "unexpected", 2: "missing", 3: "両方"}.get((ev >> 29) & 3, "?")
        log(f"    レーン 0 の最初の TLAST 事象: {typ}、m_in = {ev & 0x1FF} / 事象のクロック数 {evc}"
            f"（FIN {fin} に対して {evc / max(fin, 1):.3f} / フレーム）")
    else:
        log("    レーン 0 に TLAST 事象なし")
    log(f"    frame_started: {'見た' if fs >> 31 else '**見ていない**'}、最初の m_in = {fs & 0x1FF}"
        f"{'、**以後 m_in が違った**' if (fs >> 30) & 1 else '、以後も同じ'}"
        f"{'、**レーン間で揃わなかった**' if (fs >> 29) & 1 else '、レーン間で揃う'} / 回数 {fsc}（FIN {fin}）")
    return dict(tl=tl, ev=ev, fs=fs, evc=evc, fsc=fsc, fin=fin)


def flag_timeline(ol, args, t_ov):
    """起動の途切れ（FLAGS[4]）が**いつ**立つかを見る（2026-09-28。途切れが出る proj010.bit で使う）。

    分けたいのは 2 つ: (a) タイルの起動・データの始まりの瞬間に立つ / (b) PS が RFDC を触ったとき（ナイキストゾーンの設定）か、
    背景較正の待ちの間に立つ。Overlay の直後から sec 秒、FLAGS と CTRL[3]（入力が流れ始めた）を読み続けて、
    それぞれが初めて立った時刻（Overlay() が返ってからの秒）を出す。その後ゾーンを設定して読み、待って読む。
    rev6 以降の .bit なら生の見張りも出す。**FLAGS は消さない。**
    """
    i = args.chs[0]
    sp = Spec(getattr(ol, f"spec_core_{i}").mmio, slow=args.slow_read, idx=i, label=CHANS[i][0])
    log(f"ch {i}（{CHANS[i][0]}）を見る")
    ident = sp.rd(R_ID)
    rev = feat_rev(ident)
    log(f"spec_core: ID = {ident:08x}（{'proj010' if (ident & ID_MASK) == 0x00100000 else f'rev{(ident >> 8) & 0xFF}'}）"
        f" / Overlay() が返ってから {time.time() - t_ov:.3f} s")

    def snap(label):
        f, c = sp.flags(), sp.rd(R_CTRL)
        extra = ""
        if (ident & ID_MASK) == ID_EXPECT and rev >= 6:
            r = raw_state(sp)
            extra = f" / 生の途切れ {r['gaps']}（最初 {r['first']}）・最初の valid まで {r['t0'] / F_CORE * 1e3:.3f} ms"
        log(f"  [{time.time() - t_ov:7.3f} s] {label}: FLAGS {f:02x}（{flag_text(f)}）/ 流れ始めた {(c >> 3) & 1}{extra}")
        return f

    t_start, t_f = None, {}
    t_end = t_ov + args.flag_timeline
    n = 0
    while time.time() < t_end:
        f, c = sp.flags(), sp.rd(R_CTRL)
        now = time.time() - t_ov
        n += 1
        if t_start is None and (c >> 3) & 1:
            t_start = now
        for b in range(8):
            if (f >> b) & 1 and b not in t_f:
                t_f[b] = now
    log(f"Overlay の直後から {args.flag_timeline} s（{n} 回読んだ。1 回 {args.flag_timeline / max(n, 1) * 1e3:.2f} ms）:")
    log(f"  入力が流れ始めた: {'%.4f s' % t_start if t_start is not None else '見ていない（読み始める前から）' if (sp.rd(R_CTRL) >> 3) & 1 else '**まだ**'}")
    for b in sorted(t_f):
        log(f"  FLAGS[{b}]（{FLAG_NAMES[b]}）が初めて立った: {t_f[b]:.4f} s")
    snap("読み続けた後")
    check_tiles(ol.rfdc, args.zone)
    snap("ゾーンの設定の直後")
    if args.settle > 0:
        time.sleep(args.settle)
    snap(f"{args.settle} s 待った後")
    return True


def startguard_report(sp):
    """rev5: 起動の見張り（Overlay の後、入力が STABLE_N クロック途切れずに続くまで入力の口を閉じる）の結果を出す。

    ST_GAPS = 見張りの間に見た入力の途切れの回数（bit 31 = 口が開いた）、ST_CYC = 口が開くまでのクロック数。
    ハードのリセットでだけ数え直す（CTRL_CLR / DCLR / SRST では消えない）。rev4 以前の .bit では読まない。
    """
    if feat_rev(sp.rd(R_ID)) < 5:
        return None
    g, c = sp.rd(R_ST_GAPS), sp.rd(R_ST_CYC)
    opened, gaps = g >> 31, g & 0xFFFF
    log(f"起動の見張り: 途切れ {gaps} 回、{'開くまで' if opened else '**まだ閉じている** / 今まで'} "
        f"{c} クロック（{c / F_CORE * 1e6:.1f} µs）")
    out = dict(opened=opened, gaps=gaps, cyc=c)
    if feat_rev(sp.rd(R_ID)) >= 6:
        raw = raw_state(sp)
        where = "" if raw["gaps"] == 0 else f"（最初 {raw['first']} クロック目・最長 {raw['max']}）"
        log(f"ギアボックスの出口（生）: 途切れ {raw['gaps']} 回{where}"
            f"、起動から最初の valid まで {raw['t0']} クロック（{raw['t0'] / F_CORE * 1e3:.3f} ms）")
        log(f"gb_gate: K = {sp.rd(R_GB_K)}・始めたときの残量 {raw['cnt_arm']}・その後の最小 {raw['cnt_min']}・空振り {raw['under']}"
            f" / RFDC の出口: 途切れ {raw['adc_gaps']} 回{'' if raw['adc_ok'] else '（**2 回の読みが食い違う**）'}")
        out.update(raw)
    return out


def raw_state(sp):
    """rev6: 生の見張り（ギアボックスの出口）・gb_gate・gb_adc の値を読む。ADC_STAT は ADC ドメインの値なので 2 回読んで比べる"""
    g, f, m, t0 = sp.rd(R_RAW_GAPS), sp.rd(R_RAW_FIRST), sp.rd(R_RAW_MAXLEN), sp.rd(R_RAW_T0)
    gs = sp.rd(R_GB_STAT)
    a1, a2 = sp.rd(R_ADC_STAT), sp.rd(R_ADC_STAT)
    return dict(seen=g >> 31, gaps=g & 0xFFFF, first=(None if f == 0xFFFFFFFF else f), max=m & 0xFFFF, t0=t0,
                armed=gs >> 31, cnt_arm=(gs >> 24) & 0x3F, cnt_min=(gs >> 16) & 0x3F, under=gs & 0xFFFF,
                adc_gaps=a2 & 0xFFFF, adc_ok=(a1 == a2))


def grst_once(sp, wait):
    """GRST を 1 回かけ、wait 秒後に起動の結果を読む（rev6）"""
    sp.wr(R_CTRL, CTRL_GRST)
    time.sleep(wait)
    raw = raw_state(sp)
    stg, stc = sp.rd(R_ST_GAPS), sp.rd(R_ST_CYC)
    raw.update(flags=sp.flags(), st_open=stg >> 31, st_gaps=stg & 0xFFFF, st_cyc=stc,
               fs=sp.rd(R_DIAG_FS), tl=sp.rd(R_DIAG_TL))
    return raw


def grst_trials(sp, n, klist, stnlist, adclist, dsplist, adjlist, wait, csv_path=None):
    """rev6: ギアボックスごとの起動のやり直し（GRST）を条件ごとに n 回。起動の途切れの率・位置・対策の効きを数える。

    条件 = しきい値 K × 見張りの長さ ST_N × 書き込み側 / 読み出し側のリセットの長さ × 書き込み側の解除の遅れ ADJ。
    1 回ごとに: 生の途切れ（口の外側）・最初の途切れの位置・最長・gb_gate の残量・RFDC の出口の途切れ・見張りの途切れ・
    FLAGS（[4] 隙間・[5] TLAST 事象・[6] halt）・frame_started の位置が動いたか、を読む。
    **見立て**（README の rev6）: 途切れは起動ごとに高々 1 回・長さ 1 クロック・位置は語 2^b − 1 の受け渡し（b は遅いビット）。
    K ≧ 2 で 0。ADJ（書き込み側の語の位相）で決まるので、同じ条件のくり返しでは同じ結果になりやすい。
    """
    if feat_rev(sp.rd(R_ID)) < 6:
        log("ERROR: --grst-trials は rev6 以降の .bit が要る")
        return False
    n0, i0 = sp.rd(R_GRST_CNT), sp.rd(R_INJ_CNT)
    k_save, stn_save = sp.rd(R_GB_K), sp.rd(R_ST_N)
    rows, allrec = [], []
    for k in klist:
        for stn in stnlist:
            for ta in adclist:
                for td in dsplist:
                    for adj in adjlist:
                        sp.wr(R_GB_K, k)
                        sp.wr(R_ST_N, stn)
                        sp.wr(R_GRST_T, (td << 16) | ta)
                        sp.wr(R_GRST_ADJ, adj)
                        rec = [grst_once(sp, wait) for _ in range(n)]
                        for r in rec:
                            allrec.append(dict(k=k, stn=stn, ta=ta, td=td, adj=adj, **r))
                        gapped = [r for r in rec if r["gaps"] > 0]
                        multi = sum(1 for r in rec if r["gaps"] > 1)
                        firsts = sorted({r["first"] for r in gapped})
                        maxl = max((r["max"] for r in gapped), default=0)
                        tla = sum(1 for r in rec if r["flags"] & 0x20)
                        f4 = sum(1 for r in rec if r["flags"] & 0x10)
                        f6 = sum(1 for r in rec if r["flags"] & 0x40)
                        f3 = sum(1 for r in rec if r["flags"] & 0x08)
                        stg = sum(1 for r in rec if r["st_gaps"] > 0)
                        fsv = sum(1 for r in rec if (r["fs"] >> 30) & 1)
                        und = sum(1 for r in rec if r["under"] > 0)
                        adc = sum(1 for r in rec if r["adc_gaps"] > 0)
                        cmin = sorted({r["cnt_min"] for r in rec})
                        rows.append((k, stn, ta, td, adj, len(gapped), tla))
                        log(f"  K {k:2d} ST_N {stn:5d} T {ta:3d}/{td:3d} ADJ {adj}: 途切れ {len(gapped):3d}/{n}"
                            f"（2 回以上 {multi}、最初 {firsts[:6]}{'…' if len(firsts) > 6 else ''}、最長 {maxl}）"
                            f"  見張り {stg:3d}  FLAGS [3] {f3:3d} [4] {f4:3d} [5] {tla:3d} [6] {f6:3d}  m_in 動く {fsv:3d}"
                            f"  空振り {und:3d}  残量の最小 {cmin}  RFDC {adc}")
    sp.wr(R_GB_K, k_save)
    sp.wr(R_ST_N, stn_save)
    sp.wr(R_GRST_T, (64 << 16) | 64)
    sp.wr(R_GRST_ADJ, 0)
    log(f"GRST の回数: {sp.rd(R_GRST_CNT) - n0}（期待 {len(allrec)}）・注入 {sp.rd(R_INJ_CNT) - i0}（期待 0）")
    if csv_path:
        keys = list(allrec[0].keys()) if allrec else []
        with open(csv_path, "w") as f:
            f.write(",".join(keys) + "\n")
            for r in allrec:
                f.write(",".join("" if r[k] is None else str(r[k]) for k in keys) + "\n")
        log(f"1 回ごとの記録: {csv_path}")
    return True


def inject_test(sp, n, wait):
    """rev6: **実機の陽性対照。**途切れを 1 クロック注入して、見張りと FLAGS が見立てどおりに振る舞うかを n 回ずつ確かめる。

      a. GRST ＋ 見張りの間（最初の valid から 1000 クロック目）に注入 → 見張りが 1 回数え、IP には届かない（FLAGS 0）
      b. 口が開いた後（走っている最中）に注入 → 実際の IP で [4] 隙間・[5] TLAST 事象・[6] halt が立つ（0x70）
      c. 見張りを外して（ST_N 0）GRST ＋ 1000 クロック目に注入 → b と同じ（見張りが無ければ起動の途切れも IP に届く）
      d. 見張りを戻して GRST だけ → FLAGS 0（状態は起動のやり直しで戻る）
    """
    if feat_rev(sp.rd(R_ID)) < 6:
        log("ERROR: --inject-test は rev6 以降の .bit が要る")
        return False
    stn_save = sp.rd(R_ST_N)
    if stn_save == 0:
        log("ERROR: ST_N が 0（見張りなし）。a と d が意味を持たない")
        return False
    # FLAGS[3]（IP が入力を受けなかった）は起動のたびに立つ別の事象（rev4 から 38/38・rev6 の GRST でも毎回）なので判定から外し、数だけ出す。
    # 2026-09-28、初版は FLAGS == 0 を求めて a・d が 0/20 になった（FLAGS 08）
    F3 = 0x08
    # 自然の起動の途切れと混ざらないよう、試験の間はしきい値 K = 4 にする（rev6 の見立てでは K ≧ 2 で自然の途切れは消える）
    k_save = sp.rd(R_GB_K)
    sp.wr(R_GB_K, 4)
    res = {c: 0 for c in "abcd"}
    detail = {c: [] for c in "abcd"}
    for _ in range(n):
        # a
        sp.wr(R_INJ, INJ_ARM | INJ_AFTER_GRST | 1000)
        r = grst_once(sp, wait)
        ok = (r["flags"] & ~F3) == 0 and r["st_gaps"] >= 1 and r["st_open"] == 1
        res["a"] += ok; detail["a"].append((r["flags"], r["st_gaps"], r["gaps"]))
        # b
        sp.wr(R_INJ, INJ_ARM | 0)
        time.sleep(wait)
        f = sp.flags()
        ok = (f & 0x70) == 0x70
        res["b"] += ok; detail["b"].append((f,))
        # c
        sp.wr(R_ST_N, 0)
        sp.wr(R_INJ, INJ_ARM | INJ_AFTER_GRST | 1000)
        r = grst_once(sp, wait)
        ok = (r["flags"] & 0x70) == 0x70
        res["c"] += ok; detail["c"].append((r["flags"], r["gaps"]))
        # d
        sp.wr(R_ST_N, stn_save)
        r = grst_once(sp, wait)
        ok = (r["flags"] & ~F3) == 0
        res["d"] += ok; detail["d"].append((r["flags"], r["gaps"]))
    sp.wr(R_GB_K, k_save)
    for c in "acd":
        n3 = sum(1 for x in detail[c] if x[0] & F3)
        log(f"  （{c}: FLAGS[3] が立った回数 {n3} / {n}。判定には入れない）")
    names = {"a": "GRST ＋ 見張りの間に注入 → FLAGS 0（[3] を除く）・見張り 1 回",
             "b": "走っている最中に注入 → FLAGS に [4][5][6]",
             "c": "見張りなしで GRST ＋ 注入 → FLAGS に [4][5][6]",
             "d": "見張りを戻して GRST → FLAGS 0（[3] を除く）"}
    for c in "abcd":
        ex = "" if res[c] == n else "  **NG** 記録（FLAGS, …）: " + ", ".join(str(x) for x in detail[c][:8])
        log(f"  {c}. {names[c]}: {res[c]} / {n}{ex}")
    return all(v == n for v in res.values())


def srst_trials(sp, n, dlist, elist, wait, shift):
    """rev4: 起動（16 個の IP と数えのリセット）を PS から n 回ずつやり直し、TLAST 事象の率を (D, E) ごとに数える。

    D = リセット解除から入力（tvalid）を開けるまでのクロック、E = 設定の口（config tvalid）を開けるまでのクロック。
    1 回ごとに: D・E を書く → SRST → wait 秒待つ → FLAGS と診断を読む。SRST が FLAGS と診断を消すので、読むのはその回の分だけ。
    **Overlay を読み直す起動とは別の起動**（構成・クロックの立ち上がりは含まない）。両者の率が同じなら、競争は IP のリセットの解除の側にある。
    """
    if feat_rev(sp.rd(R_ID)) < 4:
        log("ERROR: --srst-trials は rev4 以降の .bit が要る")
        return False
    # **最初の SRST の前に、Overlay の起動で立っていたかを読む**（SRST は FLAGS と診断を消す）。
    # Overlay の起動で立ち、SRST のやり直しでは立たないなら、競争は IP のリセットの解除ではなく構成の直後にある。
    # 立っていた起動で、最初の SRST の後に消えるかどうかも、状態が IP のリセットで戻るかの手がかりになる
    time.sleep(3 * 50000 * T_FRAME)
    f_ol = sp.flags()
    log(f"Overlay の起動で立っていた FLAGS: {f_ol:02x}（{flag_text(f_ol)}）")
    diag_report(sp, "Overlay の起動から最初の SRST まで")
    n0 = sp.rd(R_SRST_CNT)
    rows = []
    golden_done = False
    for d in dlist:
        for e in elist:
            hits, lanes, evm, fsm, fsvar, fslanes, evc_per = 0, set(), set(), set(), 0, 0, []
            for _ in range(n):
                sp.wr(R_SRST_D, d)
                sp.wr(R_SRST_E, e)
                sp.wr(R_CTRL, CTRL_SRST)
                time.sleep(wait)
                f = sp.flags()
                tl, ev, fs = sp.rd(R_DIAG_TL), sp.rd(R_DIAG_EV), sp.rd(R_DIAG_FS)
                evc, fin = sp.rd(R_DIAG_EVCNT), sp.rd64(R_FIN_LO, R_FIN_HI)
                fsm.add(fs & 0x1FF)
                fsvar += (fs >> 30) & 1
                fslanes += (fs >> 29) & 1
                if f & 0x20:
                    hits += 1
                    lanes.add(tl)
                    evm.add(((ev >> 29) & 3, ev & 0x1FF))
                    evc_per.append(evc / max(fin, 1))
                    if not golden_done:
                        log(f"  D {d} / E {e}: 最初の事象（FLAGS {f:02x}、TL {tl:08x}）→ --golden と同じ照合を 1 回")
                        ok = golden(sp, shift, None)
                        log(f"  → 照合: {'OK（枠はずれていない）' if ok else '**NG**'}")
                        golden_done = True
            rows.append((d, e, hits, lanes, evm, fsm, fsvar, fslanes, evc_per))
            ev_txt = ", ".join(f"{({1: 'U', 2: 'M', 3: 'UM'}).get(t, '?')}@{m}" for t, m in sorted(evm)) or "—"
            per = f"{np.mean(evc_per):.2f}" if evc_per else "—"
            log(f"  D {d:5d} / E {e:5d}: 事象 {hits:3d} / {n}  レーン {'/'.join(f'{x:08x}' for x in sorted(lanes)) or '—'}"
                f"  最初の事象 {ev_txt}  回/フレーム {per}  frame_started の m_in {sorted(fsm)}"
                f"{'  **m_in が動いた**' if fsvar else ''}{'  **レーン不揃い**' if fslanes else ''}")
    sp.wr(R_SRST_D, 0)
    sp.wr(R_SRST_E, 0)
    log(f"SRST の回数: {sp.rd(R_SRST_CNT) - n0}（期待 {n * len(dlist) * len(elist)}）")
    return all(r[2] == 0 for r in rows)


def flagwatch(sp, seconds, shift, run_nacc):
    """FLAGS を 0.05 s おきに読み、立つたびに時刻・ビット・FIN を記録して消す（proj011 で新設）。

    proj011 rev2 の実機で、realtime の FFT IP の TLAST 事象（FLAGS[5]）が --tone の途中で立った。
    FLAGS は粘着なので、**1 回だけの事象か、立ち続ける（IP のフレームの切れ目がずれた）か**を区別できない。
    ここでは消した直後にもう一度読み、続いているかを見る。最初の事象の後に --golden と同じ照合を 1 回行い、
    **スペクトルがまだ正しい枠で切れているか**（スナップショットの numpy FFT と一致するか）を確かめる。
    run_nacc > 0 なら、見ている間は連続で積分を回す（RUN の有無で率が変わるかを見るため）。
    """
    if run_nacc > 0:
        sp.run(run_nacc, 0, shift)
        log(f"連続積分を開始: N_ACC {run_nacc}（{run_nacc * T_FRAME * 1e3:.1f} ms）")
        time.sleep(3 * run_nacc * T_FRAME + 0.05)    # 最初のダンプが閉じるまで待ってから読む
    # **見張りの前に消す前に、起動の後の CTRL_CLR から今までに立ったものを読む**
    # （初版はここで黙って消していて、SHIFT の自動決定と RUN の立ち上がりで立つ事象を見落とした。2026-09-25）
    f_pre = sp.flags()
    log(f"見張りの前（起動後の消去 → SHIFT の自動決定 → RUN の立ち上がり）に立っていた FLAGS: {f_pre:02x}"
        f"（{flag_text(f_pre)}）")
    diag_report(sp, "起動から見張りの前まで")
    sp.wr(R_CTRL, CTRL_CLR)
    t0 = time.time()
    events = []
    golden_after = None
    log(f"FLAGS を {seconds:.0f} s 見る（0.05 s おき）")
    while time.time() - t0 < seconds:
        f = sp.flags()
        if f:
            t = time.time() - t0
            fin = sp.rd64(R_FIN_LO, R_FIN_HI)
            sp.wr(R_CTRL, CTRL_CLR)
            time.sleep(0.01)                       # 5,000 フレーム
            f2 = sp.flags()
            sp.wr(R_CTRL, CTRL_CLR)
            events.append((t, f, fin, f2))
            log(f"  t = {t:7.2f} s  FLAGS {f:02x}（{flag_text(f)}）/ FIN {fin} / 消して 10 ms 後 {f2:02x}"
                f"{'（**立ち続けている**）' if f2 else ''}")
            if golden_after is None:
                log("  → この状態で --golden と同じ照合を 1 回行う")
                golden_after = golden(sp, shift, None)
                log(f"  → 事象の後の照合: {'OK（枠はずれていない）' if golden_after else '**NG（枠がずれた可能性）**'}")
                if run_nacc > 0:
                    sp.run(run_nacc, 0, shift)
                sp.wr(R_CTRL, CTRL_CLR)
        time.sleep(0.05)
    dur = time.time() - t0
    n = len(events)
    cont = sum(1 for e in events if e[3])
    log(f"事象 {n} 回 / {dur:.0f} s（{n / dur * 60:.2f} 回/分）。立ち続けたもの {cont} 回")
    bits = 0
    for e in events:
        bits |= e[1]
    if n:
        log(f"立ったビットの和: {bits:02x}（{flag_text(bits)}）")
        gaps = np.diff([e[2] for e in events]) if n > 1 else []
        if len(gaps):
            log(f"事象の間隔（フレーム）: 最小 {min(gaps)} / 最大 {max(gaps)}")
    diag_report(sp, "見張りの後（起動からの累積）")
    if run_nacc > 0:
        sp.stop()
    return n == 0 and f_pre == 0


def spectrum_report(spec, m, tone, sg_dbm, atten_db, shift):
    n = max(m["n"], 1)
    p = spec.astype(float) / n                             # 1 フレームあたりの電力（SHIFT 後）
    k = int(np.argmax(p[1:])) + 1
    floor = np.median(p)
    log(f"ダンプ: seq {m['seq']} / k {m['k']} / N {m['n']}（{m['n'] * T_FRAME * 1e3:.1f} ms）/ "
        f"SAT {m['sat']} / FLAGS {m['flags']:02x}（{flag_text(m['flags'])}）")
    log(f"最大の ch = {k}（IF {if_of_ch(k):.3f} MHz）: {10 * np.log10(p[k] / floor):.2f} dB（中央値比）")
    # 振幅（14 bit の LSB）へ戻す: |X| = √p · 2^shift、正弦波 A → |X| = A·N/2
    amp14 = np.sqrt(p[k]) * 2 ** shift * 2 / NFFT
    dbfs = 20 * np.log10(amp14 / 8192)
    log(f"  線の振幅 ≒ {amp14:.1f} LSB（14 bit）= {dbfs:.2f} dBFS（ch の中心に乗っている場合。境目なら最大 −3.92 dB）")
    if tone is not None:
        kt = ch_of_if(tone)
        kr = int(round(kt))
        # **SHIFT は ch ごとに auto で選ぶので、ch 間で比べるときは 4^SHIFT を戻した値を使う**
        # （2026-09-28、模擬で漏れの試験を回して −66 dB のはずが −23 dB と出て気づいた）
        spectrum_report.last = dict(k=k, p_tone=float(p[kr]) * 4.0 ** shift, floor=float(floor) * 4.0 ** shift,
                                    dbfs=dbfs, kt=kt, shift=shift)
        hit = abs(k - kt) <= 0.5
        log(f"  トーン {tone} MHz の期待 ch = {kt:.2f} → 実際 {k}（{'OK' if hit else '**違う**'}）")
        if not hit:
            log("  **トーンが見えていない。**SG の RF ON・周波数・レベル・ケーブルを確かめる（入力 std が雑音だけの値なら来ていない）")
            return k
        # 矩形窓の落ち込み: ch の中心から δ ずれたトーンは sinc²(δ) だけ低く読める（δ = 0.5 で −3.92 dB）。
        # 2026-09-24、3000.25 MHz で帳簿が +9.84 dBm と出た（落ち込みぶんを引いていなかった）
        d = k - kt
        sc = 20 * np.log10(abs(np.sinc(d)))
        dbfs_c = dbfs - sc
        if abs(d) > 1e-6:
            log(f"  ch の中心から {d:+.2f} ch ずれ → 矩形窓の落ち込み {sc:.2f} dB を戻して {dbfs_c:.2f} dBFS")
        if sg_dbm is not None:
            log(f"  レベルの帳簿: SG {sg_dbm:+.2f} dBm − 減衰 {atten_db:.2f} dB = ADC 入力 {sg_dbm - atten_db:+.2f} dBm"
                f" → 0 dBFS 換算 {sg_dbm - atten_db - dbfs_c:+.2f} dBm（VERSIONS.md: +5.8 dBm @ 100 MHz）")
    return k


spectrum_report.last = None


def xch_report(rows, split, leak_from):
    """--tone を 2 本以上で: 期待 ch の強さの ch 間の比。rows = [(sp, last)]"""
    ok = True
    ref = max(r["p_tone"] for _, r in rows) if leak_from is None else \
        next(r["p_tone"] for sp, r in rows if sp.idx == leak_from)
    log("")
    log("---- ch 間の比（トーンの期待 ch の電力、" + ("最大の ch 基準" if leak_from is None else f"ch {leak_from} 基準") + "）----")
    rel = {}
    for sp, r in rows:
        rel[sp.idx] = 10 * np.log10(max(r["p_tone"], 1e-30) / ref)
        log(f"  ch {sp.idx}（{sp.label}）: {rel[sp.idx]:+7.2f} dB / 中央値比 {10 * np.log10(max(r['p_tone'], 1e-30) / r['floor']):6.2f} dB"
            f" / 最大の ch {r['k']} / SHIFT {r['shift']}")
    if split:
        spread = max(rel.values()) - min(rel.values())
        good = spread <= 0.3
        log(f"4 分配の一致: 最大 − 最小 = {spread:.2f} dB（予言 ≦ 0.3 dB。分配器の出口の不揃いを引く前）→ {'OK' if good else '**NG**'}")
        ok &= good
    if leak_from is not None:
        worst = max(v for i, v in rel.items() if i != leak_from)
        good = worst <= -59.0
        log(f"漏れ: 最悪 {worst:.1f} dBc（予言 ≦ −59 dBc。床に埋もれていれば床の値）→ {'OK' if good else '**NG**'}")
        ok &= good
    return ok


def radiometer(sp, nacc_list, ndump, shift):
    """判定 3: 雑音の ch ごとの σ/μ が 1/√(Δν·τ) になるか。

    Δν は矩形窓の等価雑音帯域 = 1 ch = 0.5 MHz。τ = N_ACC × 2 µs。
    **連続する 2 ダンプの差**で σ を取る（利得のゆっくりした変化を消すため）: σ/μ = std(d)/μ/√2。
    外れ方で原因が分かれる: 大きい → デッドタイム・相関・利得の速い揺れ / 小さい → 同じ中身を 2 度積んでいる。
    """
    ok = True
    log("")
    log("   N_ACC      τ[ms]   期待 σ/μ     実測 σ/μ（中央値）  比     共通利得を除いた比  SAT   FLAGS")
    for nacc in nacc_list:
        tau = nacc * T_FRAME
        seq = sp.run(nacc, ndump, shift)
        specs = []
        for i in range(ndump):
            s = sp.wait_dump(seq, tau * 3 + 1.0)
            if s is None:
                log(f"ERROR: ダンプ {i} が閉じない")
                return False
            m, spec, _ = sp.read_dump()
            if m["seq"] != seq + 1 and i > 0:
                log(f"  NOTE: ダンプを {m['seq'] - seq - 1} 個読み落とした（読み出しが遅い）")
            seq = m["seq"]
            specs.append(spec.astype(float))
        a = np.array(specs)
        # 両端（直流付近と ch 4095 側）と強い線を除く
        sel = np.zeros(NCH_OUT, bool)
        sel[50:NCH_OUT - 50] = True
        sel &= a.mean(axis=0) < np.median(a.mean(axis=0)) * 3
        # **1PPS が ADC に入っているときの対策。**PPS の縁（毎秒 2 回、広帯域）を含むダンプだけ全 ch が
        # 持ち上がる。そのダンプと、それを含む差を外す。τ ≧ 1 s ならどのダンプも同じ数の縁を含むので外れない
        tot = a[:, sel].sum(axis=1)
        bad = _outliers(tot)
        if bad.any():
            log(f"  NOTE: 全 ch の和が外れたダンプを {bad.sum()} / {len(bad)} 個外した（PPS の縁と見る）")
        keep = ~bad
        mu = a[keep].mean(axis=0)
        pair = keep[1:] & keep[:-1]
        d = np.diff(a, axis=0)[pair]
        if len(d) < 2:
            log("ERROR: 外れを除いたら差が 2 個未満になった。--ndump を増やす")
            return False
        r = (d[:, sel].std(axis=0) / mu[sel] / np.sqrt(2))
        got = float(np.median(r))
        want = 1 / np.sqrt(DF_HZ * tau)
        ratio = got / want
        # **全 ch に共通の利得の揺れを除いた比。**2026-09-19・24（1PPS が ADC に入ったまま）、全 ch が一緒に 0.25 % 揺れ、
        # ch ごとの比が一様に 1.17 倍になった。各ダンプを静かな ch の和で割ると 1.03 倍に戻った（tick_analyze の 7）。
        # 判定はこちらで行う: 分光計の積分（デッドタイム・二度積み）を見る試験で、アナログの利得の揺れは別の項目。
        # **利得は ch ごとの比の中央値で取る（和ではなく）。**和で取ると、間欠的な混信（2026-09-24 の 823 MHz）が
        # 載る ch の揺れが利得に入り、割ると全 ch に配られる（1 s で 1.63 → 1.86 と悪化した）
        g = np.median(a[:, sel] / a[keep][:, sel].mean(axis=0), axis=1)
        an = a / g[:, None]
        mun = an[keep].mean(axis=0)
        dn = np.diff(an, axis=0)[pair]
        ratio_n = float(np.median(dn[:, sel].std(axis=0) / mun[sel] / np.sqrt(2))) / want
        log(f"  {nacc:>8}  {tau * 1e3:>8.1f}   {want:.3e}    {got:.3e}           {ratio:5.3f}  {ratio_n:5.3f}"
            f"              {m['sat']:>5}  {m['flags']:02x}")
        ok &= abs(ratio_n - 1) < 0.1 and m["flags"] == 0
    return ok


def _outliers(x, nsig=8.0):
    """中央値と MAD から外れ（上側だけ）を出す。雑音の揺れに対して nsig 倍を越えたもの"""
    med = np.median(x)
    sig = 1.4826 * np.median(np.abs(x - med))
    if sig == 0:
        return np.zeros(len(x), bool)
    return (x - med) > nsig * sig


def tick(sp, nacc, seconds, shift, save=None):
    """判定 7: ADC に入っている 1PPS の縁を分光計で見て、**積分が外部の時計と整合して途切れないか**を確かめる。

    PPS（100 µs 幅）の縁は広帯域なので、縁を含むダンプだけ全 ch の和が持ち上がる。ダンプは隙間なく並ぶので、
    **持ち上がるダンプの間隔は 1 s / τ ダンプちょうど**（N_ACC = 50000 なら 10 ダンプ）で、秒の中の位置
    （フレーム番号 mod 500,000）も動かない。フレームを 1 つでも落とせば、秒内の位置がずれる。
    読み出しが追いつかずにダンプを飛ばした場合は、DUMP_K の飛びとして出る（判定から外す）。
    """
    tau = nacc * T_FRAME
    ndump = int(round(seconds / tau))
    fps = int(round(1 / T_FRAME))                   # 500,000 フレーム/s
    seq = sp.run(nacc, 0, shift)
    rows = []                                       # (k, f0, 全 ch の和)
    specs = []
    t0 = time.time()
    while len(rows) < ndump:
        s = sp.wait_dump(seq, tau * 3 + 1.0)
        if s is None:
            log("ERROR: ダンプが閉じない")
            return False
        m, spec, _ = sp.read_dump()
        seq = m["seq"]
        rows.append((m["k"], m["f0"], float(spec[50:NCH_OUT - 50].astype(float).sum()), m["flags"], m["sat"]))
        if save:
            specs.append(spec.astype(np.float32))
    sp.stop()
    k = np.array([r[0] for r in rows])
    f0 = np.array([r[1] for r in rows], dtype=np.int64)
    tot = np.array([r[2] for r in rows])
    flags = [r[3] for r in rows]
    sat = np.array([r[4] for r in rows], dtype=np.int64)
    gaps = int(np.sum(np.diff(k) != 1))
    log(f"τ = {tau * 1e3:.1f} ms × {len(rows)} ダンプ（{time.time() - t0:.1f} s）/ 読み落とし {gaps} 箇所"
        f"（DUMP_K の飛び。読み出しが遅いだけで、積分の連続性とは別）")
    if np.any(np.diff(f0) != np.diff(k) * nacc):
        log("**NG: DUMP_F0 の間隔が DUMP_K × N_ACC と合わない**（ダンプの帳簿が壊れている）")
        return False
    if save:
        np.savez(save, k=k, f0=f0, tot=tot, sat=sat, spec=np.array(specs), nacc=nacc, shift=shift)
        log(f"saved: {save}")
    # **全 ch の和の揺れ方を先に見る。**雑音だけなら揺れは 1/√(帯域·τ) で、隣り合うダンプは無相関
    # （差の揺れ = √2 × 揺れ）。ゆっくり動く（利得・較正・外来の干渉）なら差の揺れのほうがずっと小さい。
    # 2026-09-19 の初回は揺れが期待の 110 倍で、縁が外れとして立たなかった
    med0 = np.median(tot)
    sd = tot.std() / med0
    sdd = np.diff(tot).std() / med0 / np.sqrt(2)
    log(f"全 ch の和の揺れ: σ {sd:.2e} / 隣との差から見た σ {sdd:.2e}（比 {sdd / sd:.2f}。1 なら白い揺れ、"
        f"小さければゆっくり動いている）/ 期待 {1 / np.sqrt(FS_HZ / 2 * tau):.2e}")
    # ゆっくりした動きを除いてから縁を探す（前後 5 ダンプの中央値を引く）
    base = np.array([np.median(tot[max(0, i - 5):i + 6]) for i in range(len(tot))])
    res = tot - base
    bad = _outliers(res)
    med = np.median(tot)
    sig = 1.4826 * np.median(np.abs(res - np.median(res)))
    # 隣り合う外れは 1 つの事象（縁がダンプの境目にかかった）として先頭を取る
    ev = [i for i in np.where(bad)[0] if i == 0 or not bad[i - 1]]
    log(f"全 ch の和: 中央値 {med:.4e} / ゆっくりした動きを除いた揺れ（MAD 換算）{sig / med:.2e}")
    log(f"外れたダンプ: {int(bad.sum())} 個 → 事象 {len(ev)} 個（期待 約 {len(rows) * tau:.0f} 個 = 1 秒に 1 回）")
    if len(ev) < 2:
        log("**PPS の縁が見えない。**ADC_B に 1PPS が来ているか、縁が雑音に埋もれているか（減衰が大きすぎる）")
        return False
    for i in ev[:12]:
        log(f"  k {k[i]:>7}  F0 {f0[i]:>12}  秒内の位置 {f0[i] % fps:>7} フレーム  "
            f"超過 {res[i] / med * 100:+.3f} %（{res[i] / sig:.0f} σ）")
    phase = np.array([f0[i] % fps for i in ev])
    # 秒内の位置は 1 ダンプ（nacc フレーム）の粒度で決まる。縁が境目をまたげば 1 ダンプ揺れうる
    spread = int(phase.max() - phase.min())
    dd = np.diff([k[i] for i in ev])
    per = 1 / tau
    log(f"事象の間隔（ダンプ数）: {sorted(set(dd.tolist()))}（期待 {per:g}）")
    log(f"秒内の位置の広がり: {spread} フレーム（期待 0。縁が境目にかかれば {nacc} まで）")
    ok = spread <= nacc and all(f == 0 for f in flags)
    if abs(per - round(per)) < 1e-9:
        ok &= all(d % int(round(per)) == 0 for d in dd)
    log(f"FLAGS: {'すべて 0' if all(f == 0 for f in flags) else '**0 でないダンプがある**'}")
    return ok


# 運用中に立ったら起動をやり直すフラグ。[3]（IP が入力を受けなかった）は起動のたびに立つ別の事象なので外す（rev6 の実機）
RECOVER_MASK = 0xFF & ~0x08


def recover(sp):
    """運用中の自動のやり直し（rev6）。GRST（rev6 以降。ギアボックスごと）か SRST（rev4・rev5）で起動をやり直し、
    見張り（64 µs）とパイプラインが落ち着くのを待ってから FLAGS を消す。やり直した方法を返す"""
    rev = feat_rev(sp.rd(R_ID))
    sp.stop()
    if rev >= 6:
        sp.wr(R_CTRL, CTRL_GRST)
        how = "GRST"
    elif rev >= 4:
        sp.wr(R_CTRL, CTRL_SRST)
        how = "SRST"
    else:
        how = "なし（rev3 以前の .bit）"
    time.sleep(0.01)
    sp.wr(R_CTRL, CTRL_CLR)
    return how


# ボード内のクロック（proj009 の adc_capture.py の表から）。無入力で立つ線の出どころを当てる
def record(sp, nacc, seconds, shift, prefix, meta_info, auto_recover=True):
    """長時間の連続記録。**ダンプを 1 つずつファイルへ書き、メモリに溜めない**（1 時間の 100 ms 記録は 1.2 GB）。

    書くもの（`tools/allan.py` が読む）:
      PREFIX.spec.npy  [ダンプ, 4096] uint64 — 積分した値そのまま（memmap。途中で止めても書いた分は残る）
      PREFIX.meta.npy  [ダンプ, 7] int64 — seq, k, n, f0, sat, flags, 読んだ時刻（Unix ns、PS の時計）
      PREFIX.info.json — nacc・τ・shift・書けたダンプ数・読み落とし・ボードの設定
    Ctrl-C で止めても、それまでの分は正しく閉じる。

    **自動のやり直し**（rev6、既定で有効。`--no-recover` で切る）: ダンプの FLAGS に [3] 以外が立っていたら、
    そのダンプに印を付け（meta の flags に残る）、GRST / SRST で起動をやり直して RUN し直す。
    やり直しで DUMP_K は 0 に、DUMP_F0 は新しい起動の番号に戻るので、meta の k 列は**通しの番号**に付け替え、
    印の付いたダンプの前後で 2 ずつ飛ばす（tools/allan.py は k が 1 ずつ続く区間しか束ねないので、印の付いたダンプは自然に外れる）。
    やり直しの記録は info.json の recoveries。
    """
    import json
    tau = nacc * T_FRAME
    ndump = int(round(seconds / tau))
    mb = ndump * NCH_OUT * 8 / 1e6
    log(f"記録: τ = {tau * 1e3:.1f} ms × {ndump} ダンプ（{ndump * tau:.0f} s）→ {prefix}.spec.npy（{mb:.0f} MB）")
    spec_f = np.lib.format.open_memmap(prefix + ".spec.npy", mode="w+", dtype=np.uint64, shape=(ndump, NCH_OUT))
    meta_f = np.lib.format.open_memmap(prefix + ".meta.npy", mode="w+", dtype=np.int64, shape=(ndump, 7))
    ident = sp.rd(R_ID)
    info = dict(meta_info, id=f"{ident:08x}", fft_cfg=fft_cfg_str(ident),
                nacc=nacc, tau_s=tau, shift=shift, ndump_planned=ndump, nch=NCH_OUT,
                cols=["seq", "k", "n", "f0", "sat", "flags", "t_unix_ns"], start_unix=time.time())
    seq = sp.run(nacc, 0, shift)
    i, t0, last = 0, time.time(), 0.0
    stopped = "完了"
    kg_base, last_kg = 0, -1
    recoveries, seg = [], np.zeros(ndump, dtype=np.int64)
    segid = 0
    try:
        while i < ndump:
            if sp.wait_dump(seq, tau * 3 + 1.0) is None:
                stopped = "ダンプが閉じない"
                break
            m, spec, _ = sp.read_dump()
            seq = m["seq"]
            bad = m["flags"] & RECOVER_MASK
            if bad and auto_recover:
                kg = last_kg + 2                         # 前後から切り離す
                seg[i] = segid + 1
                segid += 2
            else:
                kg = m["k"] + kg_base
                seg[i] = segid
            spec_f[i] = spec
            meta_f[i] = (m["seq"], kg, m["n"], m["f0"], m["sat"], m["flags"], time.time_ns())
            last_kg = kg
            i += 1
            if bad and auto_recover:
                how = recover(sp)
                ev = dict(i=i - 1, t=time.time() - t0, seq=m["seq"], k=m["k"], f0=m["f0"], flags=m["flags"], how=how)
                recoveries.append(ev)
                log(f"  **FLAGS {m['flags']:02x}（{flag_text(m['flags'])}）→ {how} でやり直した**"
                    f"（ダンプ {i - 1}、{ev['t']:.1f} s、k {m['k']}、F0 {m['f0']}）")
                seq = sp.run(nacc, 0, shift)
                kg_base = kg + 2
            if i % 100 == 0:
                spec_f.flush()
                meta_f.flush()
            el = time.time() - t0
            if el - last >= 60:
                last = el
                log(f"  {i} / {ndump} ダンプ（{el:.0f} s）")
    except KeyboardInterrupt:
        stopped = "Ctrl-C"
    sp.stop()
    spec_f.flush()
    meta_f.flush()
    k = meta_f[:i, 1]
    f0 = meta_f[:i, 3]
    same = (seg[1:i] == seg[:i - 1]) if i > 1 else np.zeros(0, bool)     # 同じ区間（やり直しをまたがない）の隣どうし
    gaps = int(np.sum((np.diff(k) != 1) & same)) if i > 1 else 0
    f0ok = bool(np.all((np.diff(f0) == np.diff(k) * nacc)[same])) if i > 1 else True
    marked = {r["i"] for r in recoveries}
    flags = int(np.bitwise_or.reduce([int(meta_f[j, 5]) & RECOVER_MASK for j in range(i) if j not in marked] or [0]))
    flags_all = int(np.bitwise_or.reduce(meta_f[:i, 5])) if i else 0
    sat = int(meta_f[:i, 4].sum()) if i else 0
    info.update(ndump_written=i, gaps=gaps, f0_consistent=f0ok, flags_or=flags_all, flags_or_unmarked=flags,
                sat_total=sat, stopped=stopped, elapsed_s=time.time() - t0,
                auto_recover=auto_recover, recoveries=recoveries,
                k_note="k は通しの番号。自動のやり直しで印を付けたダンプの前後は 2 飛ばす（DUMP_K そのものではない）")
    with open(prefix + ".info.json", "w") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=1)
    log(f"記録を閉じた（{stopped}）: {i} ダンプ / 読み落とし {gaps} 箇所 / "
        f"DUMP_F0 の間隔 {'OK' if f0ok else '**合わない**'} / FLAGS {flags_all:02x}（印の無いダンプだけなら {flags:02x}）/ SAT 合計 {sat}")
    log(f"  自動のやり直し: {len(recoveries)} 回{'' if auto_recover else '（無効）'}")
    log(f"  → {prefix}.spec.npy / .meta.npy / .info.json（解析は tools/allan.py {prefix}）")
    return f0ok and flags == 0 and i > 0


KNOWN_CLOCKS = [
    ("LMX2594 → RFDC 基準", 491.52e6), ("LMK04828 → LMX 基準", 245.76e6), ("LMK04828 → PL 基準", 122.88e6),
    ("DSP / clk_adc2 = fs/16", 256.0e6), ("ADC ドメイン = fs/12", FS_HZ / 12), ("MMCM の VCO", 1024.0e6),
    ("インタリーブ fs/8", 512.0e6), ("PS pl_clk0", 100.0e6), ("LMK の VCXO", 160.0e6), ("RF SYSREF", 7.68e6),
    # 2026-09-24 の判定 8 で ch 60・120・140・160・220・240・260・280（第 1 ゾーンで 30〜140 MHz の 10 MHz おき）に
    # 線が並んだ。外部基準（CLK_IN の 10 MHz）の高調波の回り込みと見る（--clkin stock との比較で確かめる）
    ("外部基準 10 MHz", 10.0e6),
]


def identify(k, tol_ch=1.0):
    """ch k（第 1 ゾーンに折り返した 0〜2048 MHz の位置）に落ちるクロックの高調波を探す。次数の低いものを優先"""
    best = None
    for name, f in KNOWN_CLOCKS:
        for h in range(1, 33):
            fa = (f * h) % FS_HZ
            fa = min(fa, FS_HZ - fa)
            kk = fa / DF_HZ
            if abs(kk - k) <= tol_ch and (best is None or h < best[0]):
                best = (h, f"{name}{' × %d' % h if h > 1 else ''}（ch {kk:.2f}）")
    return best[1] if best else ""


def peaks(spec, n, m):
    """細い線（周りの床から飛び出した ch）を大きい順に出す。**何も入れていないのに立つ線 = 固定のバーディー**"""
    p = spec.astype(float) / max(m["n"], 1)
    half = 16
    pad = np.pad(p, half, mode="edge")
    base = np.array([np.median(pad[i:i + 2 * half + 1]) for i in range(NCH_OUT)])
    r = p / np.maximum(base, 1e-30)
    order = [i for i in np.argsort(r)[::-1] if 2 <= i < NCH_OUT - 2][:n]
    log("")
    log(f"細い線（床比の大きい順・上位 {n}）")
    log("    ch     IF[MHz]   床比[dB]   候補")
    for i in order:
        log(f"  {i:>5}  {if_of_ch(i):>9.2f}  {10 * np.log10(r[i]):>8.2f}   {identify(i)}")


def image_report(spec, tone, zone=2):
    """判定 5: トーンに対するインタリーブのイメージ（±f + k·fs/8）と高調波の位置で、線の強さを dBc で出す。

    上位 N の線の一覧には床比 4 dB 程度より強いものしか入らないので、**予言した位置を名指しで読む**。
    床は ±16 ch の中央値、床の揺れは同じ範囲の MAD。線が床の揺れの 3 倍に届かなければ上限を出す。
    ch が小数（境目）なら両隣の 2 ch の和で読む（トーン側も同じ扱い）。
    """
    p = spec.astype(float)
    half = 16
    pad = np.pad(p, half, mode="edge")
    base = np.array([np.median(pad[i:i + 2 * half + 1]) for i in range(NCH_OUT)])
    rel = p / base - 1

    def chs(c):
        lo, hi = int(np.floor(c + 1e-9)), int(np.ceil(c - 1e-9))
        return sorted({x for x in (lo, hi) if 0 <= x < NCH_OUT})

    def excess(c):
        ks = chs(c)
        e = sum(p[k] - base[k] for k in ks)
        nb = np.r_[max(0, ks[0] - half):max(0, ks[0] - 2), min(NCH_OUT, ks[-1] + 3):min(NCH_OUT, ks[-1] + half + 1)]
        sig = 1.4826 * np.median(np.abs(rel[nb] - np.median(rel[nb])))
        lim = 3 * sig * np.sqrt(sum(base[k] ** 2 for k in ks))
        return e, lim, ks

    kt = ch_of_if(tone, zone)
    et, lim_t, kts = excess(kt)
    if et <= lim_t:
        log("")
        log(f"判定 5: トーン {tone} MHz（ch {kt:.2f}）が床から立っていないので、イメージの表は出さない")
        return
    b = kt * DF_HZ / 1e6                                   # トーンの第 1 ゾーン換算 [MHz]
    fsm = FS_HZ / 1e6
    cand = []
    for k in range(1, 8):
        for sgn in (1, -1):
            x = (sgn * b + k * fsm / 8) % fsm
            x = min(x, fsm - x)
            cand.append((f"イメージ {'+' if sgn > 0 else '−'}f + {k}·fs/8", x))
    for h in (2, 3):
        x = (h * tone) % fsm
        x = min(x, fsm - x)
        cand.append((f"高調波 H{h}（{h * tone:.0f} MHz）", x))
    seen, rows = set(), []
    for name, x in cand:
        c = x / (DF_HZ / 1e6)
        key = round(c, 2)
        if abs(c - kt) < 1 or key in seen:
            continue
        seen.add(key)
        rows.append((c, name))
    log("")
    log(f"判定 5: トーン {tone} MHz（ch {kt:.2f}、読んだ ch {kts}）に対するイメージと高調波（dBc = 超過の電力の比）")
    log("       ch    IF[MHz]   dBc       名前")
    for c, name in sorted(rows):
        e, lim, ks = excess(c)
        if e > lim:
            txt = f"{10 * np.log10(e / et):7.1f}"
        else:
            txt = f"< {10 * np.log10(max(lim, 1e-30) / et):5.1f}"
        log(f"  {c:>8.2f}  {if_of_ch(c, zone):>8.2f}  {txt:>8}   {name}")


# --------------------------------------------------------------------- main
def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=BITFILE)
    p.add_argument("--startup-grst", action="store_true",
                   help="Overlay の後、判定の前に ch ごとに GRST をかけて起動をやり直す。前と後の途切れを STARTUP の行に出す")
    p.add_argument("--ch", default="all", help="判定する ch: all / 0〜3 / A〜D（ADC_A〜D）。カンマ区切り")
    p.add_argument("--split", action="store_true", help="--tone で、4 分配した同じ線の強さが揃うかを判定（≦ 0.3 dB）")
    p.add_argument("--leak-from", type=int, default=None, metavar="I",
                   help="--tone で、ch I だけに入れて残りへの漏れを判定（≦ −59 dBc）")
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"),
                   help="LMK の PLL1 の基準。0 = CLK_IN（外部 10 MHz）")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--zone", type=int, default=2, choices=(1, 2))
    p.add_argument("--settle", type=float, default=5.0, help="Overlay 後に待つ秒（背景較正の収束。proj009）")
    p.add_argument("--shift", default="auto", help="Z 29 bit → 18 bit の右シフト。auto = スナップショットの std から決める")
    p.add_argument("--nacc", default="50000", help="1 ダンプのフレーム数（2 µs 単位）。カンマ区切りで複数（--radiometer）")
    p.add_argument("--ndump", type=int, default=1)
    p.add_argument("--tone", type=float, default=None, help="入れた CW の IF [MHz]")
    p.add_argument("--sg-dbm", type=float, default=None)
    p.add_argument("--atten-db", type=float, default=0.0)
    p.add_argument("--probe", action="store_true")
    p.add_argument("--golden", action="store_true")
    p.add_argument("--radiometer", action="store_true")
    p.add_argument("--tick", type=float, default=None, metavar="SEC",
                   help="判定 7: ADC に入っている 1PPS の縁を SEC 秒ぶん見る（--nacc の最初の値を使う）")
    p.add_argument("--peaks", type=int, default=0, help="通常の測定の後、細い線を上位 N 個出す")
    p.add_argument("--save", default=None, help="スペクトルとメタデータを .npz で残す")
    p.add_argument("--record", type=float, default=None, metavar="SEC",
                   help="SEC 秒の連続記録をファイルへ少しずつ書く（--out が要る。アラン分散用）")
    p.add_argument("--out", default=None, help="--record の出力の接頭辞（PREFIX.spec.npy など）")
    p.add_argument("--slow-read", action="store_true", help="MMIO を 1 語ずつ読む")
    p.add_argument("--flagwatch", type=float, default=None, metavar="SEC",
                   help="FLAGS を SEC 秒見張り、立つたびに記録して消す。--flagwatch-run N で連続積分を回しながら")
    p.add_argument("--flagwatch-run", type=int, default=0, metavar="N_ACC",
                   help="--flagwatch の間、N_ACC フレームで連続積分を回す（0 = 回さない）")
    p.add_argument("--srst-trials", type=int, default=None, metavar="N",
                   help="rev4: 起動（IP のリセット）を PS から N 回ずつやり直して TLAST 事象の率を数える")
    p.add_argument("--srst-d", default="0", help="--srst-trials の D（入力を開けるまでのクロック）。カンマ区切り")
    p.add_argument("--srst-e", default="0", help="--srst-trials の E（設定の口を開けるまでのクロック）。カンマ区切り")
    p.add_argument("--srst-wait", type=float, default=0.02, help="--srst-trials の 1 回ごとの待ち [s]")
    p.add_argument("--grst-trials", type=int, default=None, metavar="N",
                   help="rev6: ギアボックスごとの起動のやり直し（GRST）を条件ごとに N 回。起動の途切れの率・位置・対策の効きを数える")
    p.add_argument("--gb-k", default="0", help="--grst-trials のしきい値 K（gb_fifo に溜まるまで待つ語数）。カンマ区切り")
    p.add_argument("--st-n", default="16384", help="--grst-trials の見張りの長さ ST_N（0 = 見張らない）。カンマ区切り")
    p.add_argument("--grst-adc", default="64", help="--grst-trials の書き込み側のリセットの長さ（DSP クロック）。カンマ区切り")
    p.add_argument("--grst-dsp", default="64", help="--grst-trials の読み出し側・spec_core のリセットの長さ。カンマ区切り")
    p.add_argument("--grst-adj", default="0,1,2,3", help="--grst-trials の書き込み側の解除の遅れ（0〜3 ADC クロック）。カンマ区切り")
    p.add_argument("--grst-wait", type=float, default=0.02, help="--grst-trials / --inject-test の 1 回ごとの待ち [s]")
    p.add_argument("--grst-csv", default=None, help="--grst-trials の 1 回ごとの記録（CSV）")
    p.add_argument("--inject-test", type=int, default=None, metavar="N",
                   help="rev6: 途切れを注入して、見張りと FLAGS の振る舞いを N 回ずつ確かめる（実機の陽性対照）")
    p.add_argument("--no-recover", action="store_true",
                   help="--record の自動のやり直し（FLAGS の [3] 以外で GRST / SRST）を切る")
    p.add_argument("--flag-timeline", type=float, default=None, metavar="SEC",
                   help="起動の途切れがいつ立つかを見る: Overlay の直後から SEC 秒 FLAGS を読み続け、ゾーンの設定・待ちの後にも読んで終わる。"
                        "**起動の直後の消去をしない**。proj010 の .bit は --any-id")
    p.add_argument("--keep-startup-flags", action="store_true",
                   help="起動（Overlay）直後の FLAGS の消去をしない。起動の瞬間に立ったもの（入力の隙間など）を残して読む")
    p.add_argument("--allow-nopreset", action="store_true",
                   help="ボードのプリセットの無い検証ビルド（make timing-check の成果物）でも動かす。**実機の測定には使わない**")
    p.add_argument("--any-id", action="store_true",
                   help="ID が proj010（0x0010_xxxx）でも受け入れる。**対照実験で proj010.bit を載せるときだけ**。"
                        "レジスタの配置は proj010 と同じ")
    args = p.parse_args()
    if args.atten_db < 0:
        log("ERROR: --atten-db は正の値で書く（10 dB の減衰なら 10）")
        sys.exit(2)
    try:
        args.chs = parse_ch(args.ch)
    except ValueError as e:
        log(f"ERROR: {e}")
        sys.exit(2)
    single = [n for n, v in (("--record", args.record), ("--tick", args.tick), ("--flag-timeline", args.flag_timeline))
              if v is not None]
    if single and len(args.chs) != 1:
        log(f"ERROR: {single[0]} は 1 本ずつ（--ch で 1 本を選ぶ。4 本同時の記録はまだ無い）")
        sys.exit(2)
    if args.any_id:
        log("ERROR: --any-id（proj010.bit の対照）は proj012 の 4 本の道では使えない。proj011 の spectrometer.py を使う")
        sys.exit(2)
    if args.leak_from is not None and args.leak_from not in args.chs:
        log("ERROR: --leak-from の ch が --ch に入っていない")
        sys.exit(2)

    from pynq import Overlay
    import xrfdc                                  # **Overlay() より前に import する**（VERSIONS.md）
    setup_clocks(args.clkin, args.ref)
    ol = Overlay(args.bitfile)
    t_ov = time.time()
    log(f"Overlay: {args.bitfile}")
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない（DefaultIP のまま）")
        sys.exit(1)
    if args.flag_timeline is not None:
        sys.exit(0 if flag_timeline(ol, args, t_ov) else 1)
    check_tiles(ol.rfdc, args.zone)
    if args.settle > 0:
        log(f"背景較正の収束を待つ: {args.settle} s")
        time.sleep(args.settle)

    specs = open_specs(ol, args)
    log(f"判定する ch: " + ", ".join(f"{sp.idx}（{sp.label}）" for sp in specs))
    for sp in specs:
        log(f"---- ch {sp.idx}（{sp.label}）の起動 ----")
        pre = startguard_report(sp) or {}
        sp.stop()
        if args.startup_grst:
            # **Overlay の起動の途切れを、ギアボックスごとの起動のやり直しで避ける**（2026-09-28）。
            # rev1 の ch C は Overlay の起動で 7 / 24 回途切れ（最初の valid から 17036 クロック目で決まって）、
            # GRST では 400 回とも途切れなかった。同じ起動の中で GRST の前と後を並べて数える（対になった比較）
            pf = sp.flags()
            r = grst_once(sp, 0.02)
            # 途切れが IP に届いたか: 見張りの中（口を開ける前）なら吸収される。FLAGS[4][5][6] が立てば届いた
            def where(first, flags):
                if first is None:
                    return "-"
                return "届いた" if flags & 0x70 else "見張りの中で吸収"
            log(f"STARTUP ch {sp.idx} {sp.label}: Overlay の起動 途切れ {pre.get('gaps', '?')} 回"
                f"（最初 {pre.get('first')}・{where(pre.get('first'), pf)}）・空振り {pre.get('under', '?')}・FLAGS {pf:02x}"
                f" → GRST の後 途切れ {r['gaps']} 回（最初 {r['first']}・{where(r['first'], r['flags'])}）・空振り {r['under']}"
                f"・見張りの途切れ {r['st_gaps']}・FLAGS {r['flags']:02x}")
            sp.stop()
        if args.keep_startup_flags:
            # **起動の瞬間に立ったものを残す**（2026-09-25）。通常は消すが、消すと「起動の直後に入力の隙間があり、
            # それが realtime の IP の枠と入力側の数えをずらした」ことの証拠まで消える
            f0 = sp.flags()
            log(f"起動の直後の FLAGS（消さない）: {f0:02x}（{flag_text(f0)}）")
        else:
            sp.wr(R_CTRL, CTRL_CLR)               # 立ち上がりの隙間で立ったフラグを消す

    ok = True
    results = {}
    if args.probe:
        for sp in specs:
            log(f"\n==== 判定 0: ch {sp.idx}（{sp.label}）====")
            results[sp.idx] = probe(sp)
            ok &= results[sp.idx]
        if len(specs) > 1:
            log("\n==== 判定 0: 4 本の部分 ====")
            ok &= multi_probe(specs, exact_ok=not args.startup_grst)
    else:
        tone_rows = []
        for sp in specs:
            log(f"\n==== ch {sp.idx}（{sp.label}）====")
            shift = auto_shift(sp) if args.shift == "auto" else int(args.shift)
            r = measure_one(sp, args, shift)
            results[sp.idx] = r
            ok &= r
            if args.tone is not None and spectrum_report.last is not None:
                tone_rows.append((sp, spectrum_report.last))
                spectrum_report.last = None
        if len(tone_rows) > 1:
            ok &= xch_report(tone_rows, args.split, args.leak_from)
    for sp in specs:
        sp.stop()
    log("")
    log("ch ごと: " + " / ".join(f"{i}（{CHANS[i][0]}）{'OK' if v else 'NG'}" for i, v in sorted(results.items())))
    log(f"RESULT {'OK' if ok else 'NG'}")
    sys.exit(0 if ok else 1)


def measure_one(sp, args, shift):
    """1 本ぶんの判定（proj011 の main の本体を ch ごとに回す形にしたもの）。True / False を返す"""
    ok = True
    ints = lambda t: [int(v) for v in t.split(",")]
    save = args.save
    if save and len(args.chs) > 1:
        save = (save[:-4] if save.endswith(".npz") else save) + f"_{sp.label}.npz"
    if args.grst_trials is not None:
        return grst_trials(sp, args.grst_trials, ints(args.gb_k), ints(args.st_n), ints(args.grst_adc),
                           ints(args.grst_dsp), ints(args.grst_adj), args.grst_wait, args.grst_csv)
    if args.inject_test is not None:
        return inject_test(sp, args.inject_test, args.grst_wait)
    if args.srst_trials is not None:
        return srst_trials(sp, args.srst_trials, ints(args.srst_d), ints(args.srst_e), args.srst_wait, shift)
    if args.flagwatch is not None:
        return flagwatch(sp, args.flagwatch, shift, args.flagwatch_run)
    if args.golden:
        return golden(sp, shift, args.tone)
    if args.radiometer:
        return radiometer(sp, ints(args.nacc), max(args.ndump, 3), shift)
    if args.tick is not None:
        return tick(sp, int(args.nacc.split(",")[0]), args.tick, shift, save)
    if args.record is not None:
        if not args.out:
            log("ERROR: --record には --out PREFIX が要る")
            return False
        return record(sp, int(args.nacc.split(",")[0]), args.record, shift, args.out, auto_recover=not args.no_recover,
                      meta_info=dict(clkin=args.clkin, zone=args.zone, bitfile=args.bitfile, ch=sp.idx, ch_label=sp.label,
                                     if_mhz_ch0=float(if_of_ch(0, args.zone)), df_mhz=DF_HZ / 1e6))
    nacc = int(args.nacc.split(",")[0])
    seq = sp.run(nacc, args.ndump, shift)
    keep = []
    t0 = time.time()
    for i in range(args.ndump):
        if sp.wait_dump(seq, nacc * T_FRAME * 3 + 1.0) is None:
            log("ERROR: ダンプが閉じない")
            return False
        m, spec, _ = sp.read_dump()
        seq = m["seq"]
        keep.append((m, spec))
    sp.stop()
    # **連続して読めたか**: DUMP_K が 1 ずつ増え、DUMP_F0 の間隔が N_ACC ちょうどなら、隙間なく並んだダンプを
    # 1 つも落とさずに読んだことになる（二面で交互に積むので積分のデッドタイムは 0）
    if len(keep) > 1:
        kk = np.array([x["k"] for x, _ in keep])
        ff = np.array([x["f0"] for x, _ in keep], dtype=np.int64)
        gaps = int(np.sum(np.diff(kk) != 1))
        f0ok = bool(np.all(np.diff(ff) == np.diff(kk) * nacc))
        log(f"連続読み出し: {len(keep)} ダンプ × {nacc * T_FRAME * 1e3:.1f} ms を {time.time() - t0:.1f} s で / "
            f"読み落とし {gaps} 箇所 / DUMP_F0 の間隔 {'= DUMP_K × N_ACC（OK）' if f0ok else '**が合わない**'}")
        ok &= f0ok
    m, spec = keep[-1]
    spectrum_report(spec, m, args.tone, args.sg_dbm, args.atten_db, shift)
    if args.peaks > 0:
        # 何ダンプも取ったなら全部を足して床を下げてから探す
        tot = np.sum([sp_.astype(np.float64) for _, sp_ in keep], axis=0)
        mm = dict(m, n=sum(x["n"] for x, _ in keep))
        peaks(tot, args.peaks, mm)
        if args.tone is not None:
            image_report(tot, args.tone, args.zone)
    ok &= m["flags"] == 0
    if save:
        np.savez(save, spec=np.array([s_ for _, s_ in keep]),
                 meta=np.array([[mm["seq"], mm["k"], mm["n"], mm["f0"], mm["sat"], mm["flags"]]
                                for mm, _ in keep], dtype=np.int64),
                 meta_cols=np.array(["seq", "k", "n", "f0", "sat", "flags"]),
                 if_mhz=if_of_ch(np.arange(NCH_OUT), args.zone), shift=shift, ch=sp.idx, ch_label=sp.label,
                 clkin=args.clkin, tone=np.nan if args.tone is None else args.tone,
                 sg_dbm=np.nan if args.sg_dbm is None else args.sg_dbm, atten_db=args.atten_db)
        log(f"saved: {save}")
    return ok


if __name__ == "__main__":
    main()
