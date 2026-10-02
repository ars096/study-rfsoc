#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj014 — 窓の分光計（win_core_0、ADC_B）を PYNQ から動かす。起動（クロック・Overlay・タイルの確認）は spectrometer.py と同じもの。

使い方（ボードで、proj014.bit / .hwh と同じ場所に spectrometer.py・extref.py と置く）:
  sudo python3 window.py --if 3000 --w 256 --probe
      判定 W-0: ID・BUILD（窓のコア・ch 1）・WRST の後の WCUR・z が流れる・FLAGS 0・飽和 0
  sudo python3 window.py --if 3000 --w 64 --tone 3010.5
      判定 W-1: CW（IF 3010.5 MHz）が予言の ch に出るか。ch の格子の上に置けば 0.00 ch でずれる
  sudo python3 window.py --if 3000 --w 256 --golden          （SHIFT は既定で 7。4 だと FFT IP の中の丸めで許容をわずかに超える）
      判定 W-G: N_ACC = 1 のダンプを、同じフレームのスナップショット（FFT の入力 z）を numpy で FFT した電力と ch ごとに比べる。
      **FFT IP がフレームの枠どおりに変換しているか**の直接の証拠（proj010 の --golden の型）。FLAGS[2]（IP の TLAST 事象）が立つときの切り分けに
  sudo python3 window.py --if 3000 --w 256 --tone 3010.5 --w6
      判定 W-6: 同じ ADC_B の spec_core_1（全帯域）と同じ CW を同時に測り、電力の比を予言と比べる:
        P_win / P_full（1 フレームあたり）= 64 · 4^(SHIFT_full − SHIFT_win)（窓の通過帯域の利得 1、18 bit の手前の桁の違いだけ）

SG を自動で: --sg HOST[:PORT]（または環境変数 RFSOC_SG）と --sg-dbm を付けると、--tone の周波数・レベルを SG に設定し、読み返してから測る。
  SG の *IDN?・周波数・レベルはログと --out の npz に残る（pynq/sg.py。**宛先はリポジトリに書かない**）

窓の指定: --if（IF の中心 MHz、2048〜4096）と --w（幅 MHz: 256 / 128 / 64 / 32 / 16 / 8 / 4 / 2）。
  f の側の中心 c = 4096 − IF を **ch の格子（W / 4096 刻み）に丸める**（PS の既定。README の「中心の格子」）。--no-grid で丸めない。
  2560・3072・3584 MHz（k·fs/8 の線）が中央 90 % に入れば警告する（禁止はしない）。
ch の並び: ch b ↔ ν = b·W/4096（b < 2048）/ (b − 4096)·W/4096、f = c + ν、**IF = 4096 − c − ν**（ゾーン 2 で反転する）。
"""
import argparse
import atexit
import os
import sys
import time

import numpy as np

import spectrometer as S

try:
    import sg as SGMOD
except ImportError:                      # sg.py を置いていなければ --sg は使えない
    SGMOD = None

ID_WIN = 0x0016_0100             # proj016 rev1: 時刻・設定番号（SHIFT は RUN で取り込む）・健全性（窓の中身は proj015 rev3 と同じ）
ID_WIN_P15 = (0x0015_0300,)      # proj015 rev3
ID_WIN_R2 = (0x0015_0200,)       # proj015 rev2: rev1 の `-1` の最悪経路に段を足した（値は同じ。`-1` で -0.199 ns）
ID_WIN_R1 = (0x0015_0100,)       # proj015 rev1（`-1` で閉じない。`-2` の build/ は +0.007 ns で閉じた）
ID_WIN_OLD = (0x0014_0100,)      # proj014 rev1（FFT IP の tready を見ない版。枠がずれる）
ID_WIN_P14 = (0x0014_0200,)      # proj014 rev2（幅は 256〜8 MHz だけ。G は 4 固定）
BUILD_WIN = 1 << 22
WIN_CH = 0                       # 既定の ADC（proj016: ADC_A の 1 本だけ。proj015 は 1 = ADC_B）
WIN_STRIDE = 0x20000             # proj015: win_core の窓 w は 0x20000·w（1 ADC に NW 窓）
A_BASE = 0x80000                 # proj015: ADC の共通
R_A_ID, R_A_NW, R_A_SNAP_SEL, R_A_BUILD, R_A_TP_CTRL = 0x00, 0x04, 0x08, 0x0C, 0x10
R_A_TFIN_LO, R_A_TFIN_HI, R_A_GB_K, R_A_FULL_SEL, R_A_GB_STAT, R_A_ADC_STAT = 0x14, 0x18, 0x1C, 0x20, 0x24, 0x28
ID_ADC = 0x0016_A100
ID_ADC_R1 = (0x0015_A100, 0x0015_A200, 0x0015_A300)
SEL = {"adc": WIN_CH, "win": 0}  # add_sel_args / set_sel で決める（open_win・open_full が使う）
NFFT_W = 4096
R_ID, R_PARAM, R_CTRL, R_NACC, R_NDUMP, R_SHIFT, R_FLAGS, R_SEQ = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C
R_FIN_LO, R_FIN_HI, R_FOUT_LO, R_FOUT_HI = 0x20, 0x24, 0x28, 0x2C
R_DUMP_K, R_DUMP_N, R_DUMP_F0_LO, R_DUMP_F0_HI, R_DUMP_SAT = 0x30, 0x34, 0x38, 0x3C, 0x40
R_SNAP_F_LO, R_SNAP_F_HI, R_BANK, R_RUN_F0_LO, R_RUN_F0_HI = 0x44, 0x48, 0x4C, 0x50, 0x54
R_WK, R_WDPHI, R_WNS, R_WCUR, R_WCUR_DPHI, R_PFB_SAT, R_DDC_SAT, R_BUILD = 0x58, 0x5C, 0x60, 0x64, 0x68, 0x6C, 0x70, 0x74
R_WS_STALL, R_WS_RDY0 = 0x80, 0x84    # rev2
CTRL_RUN, CTRL_STOP, CTRL_CLR, CTRL_WRST = 1 << 0, 1 << 1, 1 << 8, 1 << 12
SNAP_BASE, SPEC_BASE = 0x08000, 0x10000
FLAG_NAMES = ["XK_INDEX の飛び", "溜めの読み出しが間に合わない", "IP の TLAST 事象", "IP の入力の途切れ", "IP に待たされた（tready = 0）"]
LINES_IF = (2048.0, 2560.0, 3072.0, 3584.0, 4096.0)   # k·fs/8（2048 = fs/2・4096 = DC も ADC の線が立つ）


def log(*a):
    print(*a, flush=True)


def window_params(if_c, w, grid=True):
    """IF の中心 [MHz]・幅 [MHz] → (c, WK, WDPHI, WNS, 実際の IF の中心)。win_model.py の window_params / nco_step と同じ式。"""
    ns = {256: 1, 128: 2, 64: 3, 32: 4, 16: 5, 8: 6, 4: 7, 2: 8}.get(int(w))
    if ns is None:
        raise SystemExit(f"--w は 256 / 128 / 64 / 32 / 16 / 8 / 4 / 2（MHz）: {w}")
    c = 4096.0 - if_c
    if grid:
        c = round(c / (w / NFFT_W)) * (w / NFFT_W)
    if not (w / 2 <= c <= 2048.0 - w / 2):
        raise SystemExit(f"窓が帯域（IF 2048〜4096 MHz）からはみ出す: IF {4096 - c:.4f} ± {w / 2}")
    k = int(round(c / 128.0))
    d = c - 128.0 * k
    dphi = int(round(d / 512.0 * 2 ** 32)) % (1 << 32)
    return c, k, dphi, ns, 4096.0 - c


def g_of(ns):
    """FFT の入力の小数 G（ddc_core・win_fixed.py の gz と同じ。NS ≧ 7 = 4・2 MHz は 5）。"""
    return 5 if ns >= 7 else 4


def pred_ratio(ns, shift_full, shift_win):
    """同じ CW の窓 / 全帯域の電力の比の予言。G = 4 で 64·4^(SHIFT_full − SHIFT_win)（proj014）、G が 1 増えるごとに ×4。"""
    return 64.0 * 4.0 ** (g_of(ns) - 4) * 4.0 ** (shift_full - shift_win)


def peak_frac(p, b, circular):
    """矩形窓の FFT の CW: 山の ch b と隣の振幅の比から、ch の中心からの端数 δ（ch、−0.5..0.5）と山の ch の電力の目減り sinc²(δ) を出す。
    隣の振幅 / 山の振幅 = |δ| / (1 − |δ|)（窓関数を掛けない FFT。窓の FFT も全帯域の 8192 点の FFT もそう）"""
    n = len(p)
    a = np.sqrt(np.maximum(p, 0.0))
    lo = a[(b - 1) % n] if (circular or b > 0) else 0.0
    hi = a[(b + 1) % n] if (circular or b < n - 1) else 0.0
    if hi >= lo:
        r = hi / a[b]; d = r / (1 + r)
    else:
        r = lo / a[b]; d = -r / (1 + r)
    return d, float(np.sinc(d) ** 2)


def ch_if(c, w):
    b = np.arange(NFFT_W)
    nu = np.where(b < NFFT_W // 2, b, b - NFFT_W) * (w / NFFT_W)
    return 4096.0 - c - nu


class Win:
    """win_core の窓 1 つの AXI4-Lite（proj015: win_core_i の窓 w、base = 0x20000·w）。読んだ中身は seqlock（SEQ → 中身 → SEQ）で
    1 つのダンプのものと保証する。ADC の共通（0x80000–）は ard / awr"""

    def __init__(self, mmio, base=0, adc=None, win=0):
        self.m = mmio
        self.base = base
        self.adc = adc
        self.win = win

    def rd(self, a):
        return self.m.read(self.base + a)

    def wr(self, a, v):
        self.m.write(self.base + a, int(v))

    def ard(self, a):
        return self.m.read(A_BASE + a)

    def awr(self, a, v):
        self.m.write(A_BASE + a, int(v))

    def block(self, base, nwords):
        i0 = (self.base + base) // 4
        return np.array(self.m.array[i0:i0 + nwords], dtype=np.uint32)

    def set_window(self, k, dphi, ns):
        self.wr(R_WK, k); self.wr(R_WDPHI, dphi); self.wr(R_WNS, ns)
        self.wr(R_CTRL, CTRL_WRST)
        t0 = time.time()
        while self.rd(R_CTRL) & (1 << 4):
            if time.time() - t0 > 1.0:
                raise RuntimeError("WRST が終わらない")
        cur = self.rd(R_WCUR)
        if (cur & 31) != k or ((cur >> 8) & 15) != ns or self.rd(R_WCUR_DPHI) != dphi:
            raise RuntimeError(f"WRST の後の WCUR {cur:#x} / {self.rd(R_WCUR_DPHI):#x} が書いた値（k {k}・NS {ns}・Δ {dphi:#x}）と違う")
        par = self.rd(R_PARAM)
        if ((par >> 8) & 15) != ns or ((par >> 12) & 15) != g_of(ns):
            raise RuntimeError(f"WRST の後の PARAM {par:#x} の NS・G が期待（NS {ns}・G {g_of(ns)}）と違う")

    def run(self, nacc, ndump, shift):
        self.wr(R_NACC, nacc); self.wr(R_NDUMP, ndump); self.wr(R_SHIFT, shift)
        self.wr(R_CTRL, CTRL_CLR)
        seq0 = self.rd(R_SEQ)
        self.wr(R_CTRL, CTRL_RUN)
        return seq0

    def wait_dump(self, seq_prev, timeout):
        t0 = time.time()
        while time.time() - t0 < timeout:
            s = self.rd(R_SEQ)
            if s != seq_prev:
                return s
            time.sleep(0.001)
        return None

    def meta(self):
        return dict(seq=self.rd(R_SEQ), k=self.rd(R_DUMP_K), n=self.rd(R_DUMP_N),
                    f0=(self.rd(R_DUMP_F0_HI) << 32) | self.rd(R_DUMP_F0_LO), sat=self.rd(R_DUMP_SAT),
                    snap_f=(self.rd(R_SNAP_F_HI) << 32) | self.rd(R_SNAP_F_LO), bank=self.rd(R_BANK), flags=self.rd(R_FLAGS))

    def read_dump(self, with_snap=False, tries=5):
        for _ in range(tries):
            m = self.meta()
            w = self.block(SPEC_BASE, 2 * NFFT_W)
            spec = w[0::2].astype(np.uint64) | (w[1::2].astype(np.uint64) << np.uint64(32))
            snap = None
            if with_snap:
                s = self.block(SNAP_BASE, 2 * NFFT_W).view(np.int32)
                snap = s[0::2] + 1j * s[1::2]
            if self.rd(R_SEQ) == m["seq"]:
                return m, spec, snap
        raise RuntimeError("読み出しのあいだに毎回ダンプが閉じた。積分時間に対して読み出しが遅すぎる")


def flag_text(f):
    s = [n for i, n in enumerate(FLAG_NAMES) if f >> i & 1]
    if f >> 8 & 1: s.append("pfb の飽和")
    if f >> 9 & 1: s.append("ddc の飽和")
    return "なし" if not s else " / ".join(s)


def add_sel_args(p):
    """--adc（0..3 = ADC_A..D）と --win（その ADC の窓 0..3）。proj015"""
    p.add_argument("--adc", type=int, default=WIN_CH, choices=(0, 1, 2, 3), help="窓の ADC（0..3 = ADC_A..D。既定 1 = ADC_B）")
    p.add_argument("--win", type=int, default=0, choices=(0, 1, 2, 3), help="その ADC の窓の番号（既定 0）")


def set_sel(a):
    SEL["adc"], SEL["win"] = a.adc, a.win


def open_full(ol):
    """全帯域の分光（W-6・W-2・W-3 の基準）。proj015 は spec_core_0 の 1 本を FULL_SEL で窓と同じ ADC につなぎ、SRST で起動し直す"""
    adc = SEL["adc"]
    ip0 = ol.spec_core_0
    if ip0.mmio.read(S.R_BUILD) & S.BUILD_SEL:
        ol.win_core_0.mmio.write(A_BASE + R_A_FULL_SEL, adc)
        if (ol.win_core_0.mmio.read(A_BASE + R_A_FULL_SEL) & 3) != adc:
            raise RuntimeError("FULL_SEL が書けない")
        time.sleep(0.01)
        ip0.mmio.write(S.R_CTRL, S.CTRL_SRST)
        time.sleep(0.1)
        log(f"全帯域: spec_core_0 を FULL_SEL = ch {adc}（{S.CHANS[adc][0]}）につないで SRST")
        return S.Spec(ip0.mmio, idx=adc, label=S.CHANS[adc][0])
    return S.Spec(getattr(ol, f"spec_core_{adc}").mmio, idx=adc, label=S.CHANS[adc][0])


def open_win(ol, allow_nopreset=False, allow_rev1=False):
    adc, win = SEL["adc"], SEL["win"]
    name = f"win_core_{adc}"
    ip = getattr(ol, name, None)
    if ip is None:
        log(f"ERROR: ol.{name} が無い。proj015 の窓の .bit（4 ADC × 4 窓）が載っていないか"); sys.exit(1)
    wn = Win(ip.mmio, base=WIN_STRIDE * win, adc=adc, win=win)
    ia, nw = wn.ard(R_A_ID), wn.ard(R_A_NW)
    if ia not in (ID_ADC,) + ID_ADC_R1 or not (0 <= win < nw):
        log(f"ERROR: {name} の ADC の共通 ID {ia:08x}（期待 {ID_ADC:08x}）・NW {nw}（窓 {win}）"); sys.exit(1)
    ident, bt = wn.rd(R_ID), wn.rd(R_BUILD)
    log(f"{name} の窓 {win}: ID {ident:08x} / BUILD {bt:08x}（プリセット {'あり' if bt >> 30 & 1 else '**なし**'} / -{bt >> 28 & 3} / 窓 {bt >> 22 & 1} / ch {bt & 3}）/ NW {nw}")
    if wn.rd(0x90) != win:
        log(f"ERROR: 窓の WIDX {wn.rd(0x90)} が {win} でない"); sys.exit(1)
    wn.awr(R_A_SNAP_SEL, win)                     # スナップショットはこの窓（ADC で 1 つ）
    if ident in ID_WIN_OLD and allow_rev1:
        log(f"注意: ID {ident:08x} は rev1。--allow-rev1 で続ける（W-G・W-0 の FLAGS は NG になる。W-1・W-6 は下見。rev2 でやり直す）")
    elif ident in ID_WIN_OLD:
        log(f"ERROR: ID {ident:08x} は rev1（FFT IP の tready を見ない版。枠がずれる）。rev2（{ID_WIN:08x}）の .bit を載せる"); sys.exit(1)
    elif ident in ID_WIN_R2:
        log(f"注意: ID {ident:08x} は proj015 rev2（中身は rev3 と同じ。読み出しの応答が 1 クロック早いだけ）。続ける")
    elif ident in ID_WIN_R1:
        log(f"注意: ID {ident:08x} は proj015 rev1（中身は rev2 と同じ。`-1` で閉じなかった版）。続ける")
    elif ident in ID_WIN_P14:
        log(f"ERROR: ID {ident:08x} は proj014 rev2（4・2 MHz が無く、PARAM に G が無い）。proj015 の .bit（{ID_WIN:08x}）を載せる"); sys.exit(1)
    elif ident != ID_WIN:
        log(f"ERROR: ID が {ID_WIN:08x} でない"); sys.exit(1)
    if not (bt & BUILD_WIN) or (bt & 3) != adc:
        log(f"ERROR: BUILD が「窓・ch {adc}」でない"); sys.exit(1)
    if not (bt >> 30 & 1) and not allow_nopreset:
        log("ERROR: プリセットの無い検証ビルドが載っている"); sys.exit(1)
    return wn


def nacc_for(w, seconds):
    return max(1, int(round(seconds / (NFFT_W / (w * 1e6)))))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bitfile", default=S.BITFILE)
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--if", dest="if_c", type=float, default=3000.0, help="窓の IF の中心 [MHz]")
    p.add_argument("--w", type=float, default=256.0, help="窓の幅 [MHz]")
    p.add_argument("--no-grid", action="store_true", help="中心を ch の格子に丸めない")
    p.add_argument("--shift", type=int, default=None, help="窓の SHIFT（既定 4。--golden だけのときは 7: proj014 で W-G を通した条件）")
    p.add_argument("--tint", type=float, default=0.1, help="1 ダンプの積分時間 [s]")
    p.add_argument("--ndump", type=int, default=3)
    p.add_argument("--probe", action="store_true", help="判定 W-0")
    p.add_argument("--tone", type=float, default=None, help="判定 W-1: CW の IF [MHz]")
    p.add_argument("--w6", action="store_true", help="判定 W-6: spec_core_1 と同時に測って電力の比を見る（--tone と一緒に）")
    p.add_argument("--shift-full", type=int, default=4, help="W-6 の spec_core_1 の SHIFT")
    p.add_argument("--golden", action="store_true", help="判定 W-G（N_ACC = 1 のダンプ = スナップショットの numpy FFT）")
    p.add_argument("--sg", default=None, help="SG の HOST[:PORT]（環境変数 RFSOC_SG でも可）。--tone を SG に設定する")
    p.add_argument("--sg-dbm", type=float, default=None, help="SG のレベル [dBm]（--sg と一緒に）")
    p.add_argument("--allow-nopreset", action="store_true")
    p.add_argument("--allow-rev1", action="store_true",
                   help="rev1 の .bit でも続ける（下見用）。IP の枠は起動の瞬間にずれるだけで、以後は途切れない 4096 点ずつなので、"
                        "CW の電力スペクトル（W-1・W-6）は意味を持つ。W-G はスナップショットと枠が合わないので NG になる")
    p.add_argument("--out", default=None, help="ダンプを PREFIX.win.npz に")
    add_sel_args(p)
    args = p.parse_args()
    # proj015 実機（2026-10-02）: --golden を SHIFT 4 で測ると、16 窓とも 4096 ch のうち 18 ch ほどが許容（2.0 + 1e-4·最大）を
    #   わずかに超えた（最悪 差 2.8 / 振幅 156）。比べる値が 8 倍に拡大され、FFT IP の中の丸めが見えるため。SHIFT 7 では 20 回とも超えた ch 0
    if args.shift is None:
        args.shift = 7 if (args.golden and args.tone is None and not args.w6) else 4
    set_sel(args)

    c, k, dphi, ns, if_c = window_params(args.if_c, args.w, grid=not args.no_grid)
    w = args.w
    log(f"窓: IF {if_c:.6f} MHz ± {w / 2}（f の側 c = {c:.6f}）/ WK {k} / WDPHI {dphi:#010x}（d = {c - 128 * k:+.6f} MHz）/ WNS {ns}")
    for lf in LINES_IF:
        if abs(lf - if_c) <= 0.45 * w:
            log(f"注意: IF {lf:.0f} MHz（k·fs/8 の線）が窓の中央 90 % に入る")

    from pynq import Overlay
    import xrfdc                                  # Overlay() より前に import する（VERSIONS.md）
    S.setup_clocks(args.clkin, args.ref)
    ol = Overlay(args.bitfile)
    log(f"Overlay: {args.bitfile}")
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    S.check_tiles(ol.rfdc, 2)
    if args.settle > 0:
        time.sleep(args.settle)
    wn = open_win(ol, args.allow_nopreset, args.allow_rev1)      # SG を触る前に、載っている .bit を確かめる
    sg = None
    sg_state = None
    if args.tone is not None and not (args.sg or os.environ.get("RFSOC_SG")):
        log("注意: --tone があるが SG の宛先が無い（--sg も 環境変数 RFSOC_SG も無い）→ **SG を操作しない**。"
            "SG を手で " + f"{args.tone} MHz・ON にしてあること（--sg-dbm も効かない）")
    if (args.sg or os.environ.get("RFSOC_SG")) and args.tone is not None:
        if SGMOD is None:
            log("ERROR: sg.py が無い"); sys.exit(1)
        sg = SGMOD.SG(args.sg, log=log)
        atexit.register(sg.close)                 # 途中で止まっても SG の出力を元の状態に戻す
        sg.set_freq_mhz(args.tone)
        if args.sg_dbm is not None:
            sg.set_dbm(args.sg_dbm)
        sg.set_output(True)
        sg_state = sg.state()
    wn.set_window(k, dphi, ns)
    # FLAGS の切り分け: WRST の直後に立っていたもの（起動の瞬間）と、消してから 0.2 s のあいだに立ったもの（動いているあいだ）を分けて読む
    time.sleep(0.05)
    f_start = wn.rd(R_FLAGS)
    wn.wr(R_CTRL, CTRL_CLR)
    time.sleep(0.2)
    f_run = wn.rd(R_FLAGS)
    log(f"FLAGS: WRST の後 50 ms = {f_start:#x}（{flag_text(f_start)}）/ 消してから 0.2 s = {f_run:#x}（{flag_text(f_run)}）")
    if wn.rd(R_ID) == ID_WIN:
        log(f"FFT IP: WRST の解除から tready が 1 になるまで {wn.rd(R_WS_RDY0)} クロック / 待たされた {wn.rd(R_WS_STALL)} クロック（WRST 以来）")
    nacc = 1 if args.golden else nacc_for(w, args.tint)
    if args.golden:
        args.ndump = 1
    ok = True

    def judge(cond, msg):
        nonlocal ok
        log(("  OK  " if cond else "  NG  ") + msg)
        ok &= bool(cond)

    spf = None
    if args.w6:
        spf = open_full(ol)
        nacc_full = int(round(args.tint / S.T_FRAME))
        seqf = spf.run(nacc_full, args.ndump, args.shift_full)
    seq = wn.run(nacc, args.ndump, args.shift)
    dumps = []
    for i in range(args.ndump):
        s = wn.wait_dump(seq, timeout=args.tint * 3 + 2)
        if s is None:
            judge(False, f"ダンプ {i} が {args.tint * 3 + 2:.1f} s のうちに閉じない"); break
        seq = s
        m, spec, snap = wn.read_dump(with_snap=(i == 0))
        dumps.append((m, spec))
        log(f"ダンプ {m['k']}: f0 {m['f0']} / n {m['n']} / 飽和 {m['sat']} / FLAGS {flag_text(m['flags'])}")
    flags = wn.rd(R_FLAGS)
    if True:                                  # W-0 は毎回
        cr = wn.rd(R_CTRL)
        judge(cr >> 3 & 1, "W-0: z が流れている（CTRL[3]）")
        # FLAGS[4]（IP に待たされた）は rev2 ではデータを保って待つだけなので判定から外し、量（1 フレームあたりのクロック数）を出す。
        # 実機 4 回目（W = 8 MHz）: 待たされたのは 1 フレームにほぼ 1 クロック（途切れの後の面の頭で IP が 1 クロック待たせると読む。未確認）
        judge((flags & 0x3EF) == 0, f"W-0: FLAGS = {flags:#x}（{flag_text(flags)}）" + ("（[4] は判定に入れない）" if flags & 0x10 else ""))
        if wn.rd(R_ID) == ID_WIN:
            fin_now = wn.rd(R_FIN_LO) | (wn.rd(R_FIN_HI) << 32)
            st = wn.rd(R_WS_STALL)
            log(f"  FFT IP に待たされた {st} クロック / 溜め終えたフレーム {fin_now}（1 フレームあたり {st / max(fin_now, 1):.3f}）"
                "。読み出しの遅れは FLAGS[1] が見る")
        judge(wn.rd(R_PFB_SAT) == 0 and wn.rd(R_DDC_SAT) == 0, f"W-0: 飽和 pfb {wn.rd(R_PFB_SAT)} / ddc {wn.rd(R_DDC_SAT)}")
        judge(len(dumps) == args.ndump and all(d[0]["n"] == nacc for d in dumps), f"W-0: ダンプ {len(dumps)} 個・各 {nacc} フレーム")
    if dumps and args.golden:
        m, spec = dumps[0]
        _, _, snap = wn.read_dump(with_snap=True)
        judge(m["snap_f"] == m["f0"], f"W-G: スナップショットのフレーム {m['snap_f']} = ダンプの f0 {m['f0']}")
        Y = np.fft.fft(snap.astype(complex))                     # IP と同じ順変換・unscaled（倍精度）
        qr = np.floor(Y.real / 2 ** args.shift); qi = np.floor(Y.imag / 2 ** args.shift)
        ok_ch = (np.abs(qr) < 2 ** 17 - 4) & (np.abs(qi) < 2 ** 17 - 4)      # 18 bit に飽和しない ch だけ比べる
        a_np = np.hypot(qr, qi)
        a_hw = np.sqrt(spec.astype(float))
        d = np.abs(a_hw - a_np)
        tol = 2.0 + 1e-4 * a_np[ok_ch].max()
        nbad = int(np.count_nonzero(d[ok_ch] > tol))
        worst = int(np.argmax(np.where(ok_ch, d / tol, 0)))
        judge(nbad == 0, f"W-G: ダンプ = スナップショットの numpy FFT（{int(ok_ch.sum())} ch、許容 {tol:.1f}、超えた ch {nbad}、"
                         f"最悪 ch {worst}: 差 {d[worst]:.1f} / 振幅 {a_np[worst]:.0f}）")
    if dumps and args.tone is not None:
        m, spec = dumps[-1]
        p = spec.astype(float) / m["n"]
        ifs = ch_if(c, w)
        b_pred = int(np.argmin(np.abs(ifs - args.tone)))
        off_pred = (4096.0 - args.tone - c) / (w / NFFT_W)
        b_meas = int(np.argmax(p))
        judge(b_meas == b_pred, f"W-1: CW IF {args.tone} MHz → ch 予言 {b_pred}（ν = {off_pred:+.3f} ch）/ 実測 {b_meas}（IF {ifs[b_meas]:.6f} MHz）")
        dw, gw = peak_frac(p, b_meas, circular=True)
        nu_b = b_meas if b_meas < NFFT_W // 2 else b_meas - NFFT_W
        if_w = 4096.0 - c - (nu_b + dw) * (w / NFFT_W)
        nb = "・".join(f"{10 * np.log10(max(p[(b_meas + j) % NFFT_W], 1e-30) / p[b_meas]):+.1f}" for j in (-2, -1, 1, 2))
        log(f"  窓の山: ch {b_meas} の隣（−2・−1・+1・+2）{nb} dB → 端数 δ = {dw:+.3f} ch（f の側）/ 推定 IF {if_w:.6f} MHz"
            f"（SG との差 {(if_w - args.tone) * 1e3:+.2f} kHz = {(if_w - args.tone) / args.tone * 1e6:+.2f} ppm）/ 山の ch の目減り {10 * np.log10(gw):+.3f} dB")
        if spf is not None:
            sf = spf.wait_dump(seqf, timeout=args.tint * args.ndump * 3 + 2)
            mf, specf, _ = spf.read_dump()
            pf = specf.astype(float) / mf["n"]
            kf = int(round(S.ch_of_if(args.tone)))
            kf = kf - 3 + int(np.argmax(pf[kf - 3:kf + 4]))          # 全帯域の山（予言の ch ± 3 の中）
            df, gf = peak_frac(pf, kf, circular=False)
            if_f = 4096.0 - (kf + df) * (S.DF_HZ / 1e6)
            log(f"  全帯域の山: ch {kf}・端数 δ = {df:+.3f} ch / 推定 IF {if_f:.6f} MHz（SG との差 {(if_f - args.tone) * 1e3:+.2f} kHz）/ 目減り {10 * np.log10(gf):+.3f} dB")
            judge(abs(if_w - if_f) < 0.01, f"W-1b: 窓と全帯域の推定 IF の差 {(if_w - if_f) * 1e3:+.2f} kHz（許容 ±10 kHz。"
                                           "同じ ADC のクロックで測るので基準のずれは打ち消す。窓の周波数軸そのものの確かめ）")
            ratio = p[b_meas] / pf[kf]
            pred = pred_ratio(ns, args.shift_full, args.shift)
            db_raw = 10 * np.log10(ratio / pred)
            db = 10 * np.log10(ratio / pred * gf / gw)
            judge(abs(db) < 0.1, f"W-6: 窓 / 全帯域（ch {kf}）の電力の比 {ratio:.4g}、予言 {pred:.4g} → そのまま {db_raw:+.3f} dB /"
                                 f" 山の ch の目減り（sinc²）を戻して {db:+.3f} dB（許容 ±0.1 dB）")
    if args.out and dumps:
        np.savez(args.out + ".win.npz", spec=np.stack([d[1] for d in dumps]), if_mhz=ch_if(c, w),
                 sg=str(sg_state), f_start=f_start, f_run=f_run,
                 f0=np.array([d[0]["f0"] for d in dumps]), n=np.array([d[0]["n"] for d in dumps]),
                 k=k, dphi=dphi, ns=ns, c=c, w=w, shift=args.shift)
        log(f"書いた: {args.out}.win.npz")
    if sg is not None:
        sg.close()
    log("RESULT " + ("OK" if ok else "NG"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
