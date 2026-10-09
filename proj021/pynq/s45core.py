#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj021 手順 2-1 — インターフェース v2 の自己記述（INTERFACE.md の 2.〜3.）で、載っている .bit のコアと流れを見つける

PS は .hwh の IP の名前（`s45_core_0`〜`3`・`time_core_0`）でコアを引き、各コアの IF_ID・CORE_PORT・NSTREAM と流れの SID を読んで
流れの表を作る。**番地の数値で .bit を見分けない**（照合は IF_VER・BIT_KIND・CORE_KIND・PORT の重複で行う）。

    sudo -E $(which python3) s45core.py --list            # 自己記述の表を出す（S21-4。Overlay を読み込む）
    sudo -E $(which python3) s45core.py --list --no-load  # 載っている .bit をそのまま読む（Overlay(download=False)）

番地（proj021 手順 2-1。コアの 1 MiB）:
  0x00000–0x000FF コアの共通 / 0x00100 TP のレジスタ / 0x02000 TP のリング / 0x04000 + 0x400·s 流れ s のブロック /
  0x80000 + 0x20000·w 窓 w の仮の読み窓 / 0xC0000 FULL の仮の読み窓 / 0xE0000 仮の SNAP_SEL（**仮の 3 つは 2-2 で無くなる**）
"""
import argparse
import sys

IF_VER = 2
BIT_KINDS = {1: "SAM45-Wide", 2: "SAM45-Fine", 3: "2G", 4: "512M", 5: "256M", 6: "SpW6", 7: "SpW8", 8: "SpW20", 9: "Fine"}
CORE_KIND_ADC, CORE_KIND_TIME, CORE_KIND_RING = 1, 2, 3
KIND_FULL, KIND_SLICE, KIND_DDC = 1, 2, 3
KIND_NAMES = {KIND_FULL: "FULL", KIND_SLICE: "SLICE", KIND_DDC: "DDC"}
ADC_NAMES = ("ADC_A", "ADC_B", "ADC_C", "ADC_D")
PROJ_EXPECT = 0x0021_0200        # この README の手順 2-1 の .bit（追跡のため。照合には使わない）
BIT_KIND_EXPECT = 2              # SAM45-Fine

# ---- コアの共通（INTERFACE 2.4。0x20〜 は表 A を +0x10）----
C_IF_ID, C_PROJ, C_NSTREAM, C_CAPS, C_BASE_BEATS, C_BUILD, C_CORE_PORT = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18
C_TP_CTRL, C_TFIN_LO, C_TFIN_HI, C_GB_K = 0x20, 0x24, 0x28, 0x2C
C_GB_STAT, C_ADC_STAT, C_ANCH_F, C_ANCH_T, C_ANCH_ST, C_TP_RUN_T, C_OVR, C_GAP = 0x34, 0x38, 0x3C, 0x44, 0x4C, 0x50, 0x58, 0x5C
TP_REG, TP_RING = 0x100, 0x2000
# ---- 流れのブロック（INTERFACE 2.5）----
BLK, BLK_STRIDE = 0x4000, 0x400
S_SID, S_PARAM, S_CTRL, S_NACC, S_NDUMP, S_SHIFT, S_FLAGS, S_SEQ = 0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C
S_NCH, S_FRAME_BEATS, S_SRC, S_CFG, S_RUN_CFG, S_WRST_CFG, S_RUN_SHIFT = 0x20, 0x24, 0x28, 0x2C, 0x30, 0x34, 0x38
S_DUMP_K, S_DUMP_F0, S_DUMP_N, S_DUMP_SAT, S_DUMP_T, S_DUMP_H, S_DUMP_CFG = 0x3C, 0x40, 0x48, 0x4C, 0x50, 0x58, 0x5C
S_RUN_T, S_RUN_F0, S_FIN, S_FOUT, S_NFFT_MIN_MAX, S_REC_CTRL, S_REC_LATE = 0x60, 0x68, 0x70, 0x78, 0x80, 0x84, 0x88
# DDC に固有
S_WK, S_WDPHI, S_WNS, S_WCUR, S_WCUR_DPHI, S_WSTART, S_NS_MIN_MAX, S_WRST_T = 0x100, 0x104, 0x108, 0x10C, 0x110, 0x114, 0x118, 0x11C
# 診断（約束の外）
D_PFB_SAT, D_DDC_SAT, D_WS_STALL, D_WS_RDY0, D_DDC_OVR, D_WRST_CNT, D_SNAP_F, D_BANK = 0x200, 0x204, 0x208, 0x20C, 0x210, 0x214, 0x218, 0x220
DF_SNAP_F, DF_BANK = 0x260, 0x268      # FULL の診断の SNAP_F・BANK（旧 0x44・0x4C）
# ---- 仮（2-2 で無くなる）----
LEG_WIN, LEG_WIN_STRIDE, LEG_FULL, LEG_SNAP_SEL = 0x80000, 0x20000, 0xC0000, 0xE0000
# time_core
T_IF_ID, T_PROJ = 0x00, 0x5C


def blk(s):
    return BLK + BLK_STRIDE * s


def leg_win(w):
    return LEG_WIN + LEG_WIN_STRIDE * w


class S45Error(RuntimeError):
    pass


def split_if_id(v):
    return dict(if_ver=v >> 24 & 0xFF, bit_kind=v >> 16 & 0xFF, bit_rev=v >> 8 & 0xFF, core_kind=v & 0xFF)


class Stream:
    """流れ 1 本（コア c の s）。base = 流れのブロック、lbase = 仮の読み窓"""

    def __init__(self, core, s, sid):
        self.core, self.s, self.sid = core, s, sid
        self.kind = sid >> 16 & 0xFF
        self.base = blk(s)
        self.lbase = leg_win(s) if self.kind == KIND_DDC else LEG_FULL
        self.m = core.m

    @property
    def name(self):
        return f"{self.core.adc_name}{self.s}" if self.kind == KIND_DDC else f"FULL（{self.core.name} の s {self.s}）"

    def rd(self, a):
        return int(self.m.read(self.base + a)) & 0xFFFFFFFF

    def wr(self, a, v):
        self.m.write(self.base + a, int(v) & 0xFFFFFFFF)


class Core:
    """s45_core_i 1 個"""

    def __init__(self, name, mmio):
        self.name, self.m = name, mmio
        self.if_id = self.rd(C_IF_ID)
        f = split_if_id(self.if_id)
        self.if_ver, self.bit_kind, self.bit_rev, self.core_kind = f["if_ver"], f["bit_kind"], f["bit_rev"], f["core_kind"]
        self.proj = self.rd(C_PROJ)
        self.nstream = self.rd(C_NSTREAM)
        self.caps = self.rd(C_CAPS)
        self.base_beats = self.rd(C_BASE_BEATS)
        self.build = self.rd(C_BUILD)
        p = self.rd(C_CORE_PORT)
        self.adc, self.tile, self.slice = p & 0xF, p >> 8 & 0xF, p >> 12 & 0xF
        self.streams = []

    @property
    def adc_name(self):
        return ADC_NAMES[self.adc] if self.adc < len(ADC_NAMES) else f"ADC{self.adc}"

    def rd(self, a):
        return int(self.m.read(a)) & 0xFFFFFFFF

    def wr(self, a, v):
        self.m.write(a, int(v) & 0xFFFFFFFF)

    def rd64(self, a):
        lo = self.rd(a)
        return (self.rd(a + 4) << 32) | lo

    def ddc(self):
        return [s for s in self.streams if s.kind == KIND_DDC]

    def full(self):
        return [s for s in self.streams if s.kind == KIND_FULL]


def discover(ol, bit_kind=BIT_KIND_EXPECT, ncore=4):
    """s45_core_0..ncore−1 と time_core_0 を名前で引き、照合して (cores（ADC の順）, time_core の mmio) を返す"""
    cores = []
    for i in range(ncore):
        ip = getattr(ol, f"s45_core_{i}", None)
        if ip is None:
            raise S45Error(f"ol.s45_core_{i} が無い（インターフェース v2 の .bit ではない。.hwh の IP の名前を見る）")
        c = Core(f"s45_core_{i}", ip.mmio)
        if c.if_ver != IF_VER:
            raise S45Error(f"{c.name} の IF_VER {c.if_ver}（IF_ID {c.if_id:#010x}。期待 {IF_VER}）")
        if c.core_kind != CORE_KIND_ADC:
            raise S45Error(f"{c.name} の CORE_KIND {c.core_kind}（期待 {CORE_KIND_ADC} = ADC のコア）")
        if bit_kind is not None and c.bit_kind != bit_kind:
            raise S45Error(f"{c.name} の BIT_KIND {c.bit_kind}（{BIT_KINDS.get(c.bit_kind, '?')}。期待 {bit_kind} = {BIT_KINDS.get(bit_kind)}）")
        if not 1 <= c.nstream <= 48:
            raise S45Error(f"{c.name} の NSTREAM {c.nstream}")
        for s in range(c.nstream):
            sid = c.rd(blk(s) + S_SID)
            if sid >> 24 != IF_VER or (sid >> 8 & 0xFF) != s or sid >> 16 & 0xFF not in KIND_NAMES:
                raise S45Error(f"{c.name} の流れ {s} の SID {sid:#010x}")
            c.streams.append(Stream(c, s, sid))
        cores.append(c)
    ports = [c.adc for c in cores]
    if len(set(ports)) != len(ports):
        raise S45Error(f"CORE_PORT の ADC が重なっている {ports}")
    kinds = {(c.bit_kind, c.bit_rev, c.proj) for c in cores}
    if len(kinds) != 1:
        raise S45Error(f"コアの BIT_KIND・BIT_REV・PROJ が揃っていない {kinds}")
    cores.sort(key=lambda c: c.adc)
    tip = getattr(ol, "time_core_0", None)
    if tip is None:
        raise S45Error("ol.time_core_0 が無い")
    tid = int(tip.mmio.read(T_IF_ID)) & 0xFFFFFFFF
    f = split_if_id(tid)
    if f["if_ver"] != IF_VER or f["core_kind"] != CORE_KIND_TIME or f["bit_kind"] != cores[0].bit_kind:
        raise S45Error(f"time_core_0 の IF_ID {tid:#010x}")
    return cores, tip.mmio


def full_stream(cores):
    """FULL の流れ（SAM45-Fine は 1 本）"""
    fs = [s for c in cores for s in c.full()]
    if len(fs) != 1:
        raise S45Error(f"FULL の流れが {len(fs)} 本（期待 1）")
    return fs[0]


def table(cores, tmm=None):
    out = []
    c0 = cores[0]
    out.append(f"bit: {BIT_KINDS.get(c0.bit_kind, '?')}（BIT_KIND {c0.bit_kind}）rev {c0.bit_rev} / PROJ {c0.proj:#010x}"
               f"{'' if c0.proj == PROJ_EXPECT else f'（この README は {PROJ_EXPECT:#010x}）'}")
    if tmm is not None:
        out.append(f"time_core_0: IF_ID {int(tmm.read(T_IF_ID)) & 0xFFFFFFFF:#010x} / PROJ {int(tmm.read(T_PROJ)) & 0xFFFFFFFF:#010x}")
    out.append("コア          ADC    タイル スライス IF_ID       NSTREAM CAPS  BASE_BEATS BUILD")
    for c in cores:
        out.append(f"{c.name:<13} {c.adc_name:<6} {c.tile:>6} {c.slice:>8} {c.if_id:#010x} {c.nstream:>7} {c.caps:#05x} {c.base_beats:>10} {c.build:#010x}")
    out.append("流れ                 KIND  s  SID         NCH   FRAME_BEATS SRC         PARAM       NFFT_MIN_MAX")
    for c in cores:
        for s in c.streams:
            out.append(f"{s.name:<20} {KIND_NAMES[s.kind]:<5} {s.s:>2} {s.sid:#010x} {s.rd(S_NCH):>5} {s.rd(S_FRAME_BEATS):>11} "
                       f"{s.rd(S_SRC):#010x} {s.rd(S_PARAM):#010x} {s.rd(S_NFFT_MIN_MAX):#06x}")
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="自己記述の表を出す")
    p.add_argument("--bitfile", default="proj021.bit")
    p.add_argument("--no-load", action="store_true", help="Overlay を download=False で（載っている .bit をそのまま読む）")
    p.add_argument("--clkin", default="stock")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0, help="Overlay の後、コアを読むまで待つ [s]")
    a = p.parse_args()
    if not a.list:
        p.print_help(); return
    import spectrometer as S
    if not a.no_load:
        S.setup_clocks(a.clkin, a.ref)
    from pynq import Overlay
    import xrfdc  # noqa: F401  Overlay() より前に import する（VERSIONS.md）
    ol = Overlay(a.bitfile, download=not a.no_load)
    # **コアは DSP ドメイン（RFDC のタイルのクロック → Clocking Wizard）にある。タイルが起き、MMCM がロックして rst_dsp が
    #   明けるまで AXI4-Lite を読むと、SmartConnect が応答を待ち続けて PS ごと止まる**（2026-10-09、この道具の 1 回目で止まった）。
    #   window.py などと同じく、タイルの確認と待ちを済ませてから読む
    import xrfdc
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        print("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    S.check_tiles(ol.rfdc, 2)
    if not a.no_load and a.settle > 0:
        import time
        time.sleep(a.settle)
    try:
        cores, tmm = discover(ol)
    except S45Error as e:
        print(f"ERROR: {e}"); sys.exit(1)
    print(table(cores, tmm))


if __name__ == "__main__":
    main()
