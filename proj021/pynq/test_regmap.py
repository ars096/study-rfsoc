#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj021 手順 2-1 S21-1 の後半 — PS の読み手（s45core・window・spectrometer・timetest・timebase）の番地が RTL と合うか

`make sim-regmap` の tb_regmap が書き出した読み（build-sim-regmap/regs.txt: 「コア 番地 値」）を偽の mmio にして、
PS の読み手をそのまま回す。tb_regmap が書いた値（流れごとに違う N_ACC・CFG_ID・WK…）が、PS の定数の番地から読めることを確かめる。
PYNQ もボードも要らない（numpy だけ）。

    python3 test_regmap.py ../build-sim-regmap/regs.txt
"""
import sys

import s45core as SC
import spectrometer as S
import timebase as TB
import timetest as T
import window as W


class FakeMMIO:
    def __init__(self, regs):
        self.regs = regs

    def read(self, a):
        if a not in self.regs:
            raise KeyError(f"tb が読んでいない番地 {a:#07x}")
        return self.regs[a]

    def write(self, a, v):
        raise RuntimeError("この試験では書かない")


class IP:
    def __init__(self, regs):
        self.mmio = FakeMMIO(regs)


class FakeOL:
    pass


def main():
    regs = {0: {}, 1: {}, 2: {}}
    for line in open(sys.argv[1]):
        c, a, v = line.split()
        regs[int(c)][int(a, 16)] = int(v, 16)
    ol = FakeOL()
    ol.s45_core_0, ol.s45_core_1, ol.time_core_0 = IP(regs[0]), IP(regs[1]), IP(regs[2])
    ng = 0
    nchk = 0

    def judge(cond, msg):
        nonlocal ng, nchk
        nchk += 1
        if not cond:
            ng += 1
            print(f"test_regmap: NG {msg}")

    cores, tmm = SC.discover(ol, ncore=2)
    print("test_regmap: 自己記述の表（tb_regmap の 2 コア）")
    for ln in SC.table(cores, tmm).splitlines():
        print("test_regmap:   " + ln)
    judge([c.adc for c in cores] == [0, 1], "CORE_PORT の ADC")
    judge((cores[0].tile, cores[0].slice, cores[1].tile, cores[1].slice) == (2, 2, 2, 0), "CORE_PORT のタイル・スライス")
    judge([len(c.ddc()) for c in cores] == [2, 2] and len(cores[0].full()) == 1 and not cores[1].full(), "流れの数と KIND")
    fs = SC.full_stream(cores)
    judge((fs.core.name, fs.s, fs.base, fs.lbase) == ("s45_core_0", 2, 0x4800, 0xC0000), "FULL の流れの番地")
    # 窓（tb: 流れ s・コア c で k = 16c + s。N_ACC 100 + k・N_DUMP 200 + k・SHIFT (5 + k) & 15・CFG_ID 0xC0F0_0000 + k・
    #   WK (k + 1) & 31・WDPHI 0x1357_0000 + k・WNS 3 + s・WRST_T 80 + k。WRST の後）
    for c in cores:
        for st in c.ddc():
            k = 16 * c.adc + st.s
            wn = W.Win(c.m, base=st.base, adc=c.adc, win=st.s, lbase=st.lbase)
            ns = 3 + st.s
            got = dict(nacc=wn.rd(W.R_NACC), ndump=wn.rd(W.R_NDUMP), shift=wn.rd(W.R_SHIFT), cfg=wn.rd(T.R_CFG),
                       wrst_cfg=wn.rd(T.R_WRST_CFG), wk=wn.rd(W.R_WK), wdphi=wn.rd(W.R_WDPHI), wns=wn.rd(W.R_WNS),
                       wcur=wn.rd(W.R_WCUR), wcur_dphi=wn.rd(W.R_WCUR_DPHI), wrst_cnt=wn.rd(W.R_WRST_CNT),
                       par_ns=(wn.rd(W.R_PARAM) >> 8) & 15, par_g=(wn.rd(W.R_PARAM) >> 12) & 15, sid=wn.rd(W.R_ID))
            want = dict(nacc=100 + k, ndump=200 + k, shift=(5 + k) & 15, cfg=0xC0F0_0000 + k, wrst_cfg=0xC0F0_0000 + k,
                        wk=(k + 1) & 31, wdphi=0x1357_0000 + k, wns=ns, wcur=(ns << 8) | ((k + 1) & 31), wcur_dphi=0x1357_0000 + k,
                        wrst_cnt=1, par_ns=ns, par_g=W.g_of(ns), sid=0x0203_0000 | (st.s << 8))
            for key in want:
                judge(got[key] == want[key], f"{c.adc_name} 窓 {st.s} の {key} = {got[key]:#x}（期待 {want[key]:#x}）")
            judge(st.rd(SC.S_FRAME_BEATS) == 4096 << (ns - 1), f"{c.adc_name} 窓 {st.s} の FRAME_BEATS（s45acq.frame_beats と同じ式）")
        judge(c.rd(W.A_BASE + W.R_A_GB_K) == 3 + c.adc, f"{c.adc_name} の GB_K（コアの共通）")
        judge(c.rd(W.A_BASE + S.R_TP_PARAM) == S.TP_PARAM_EXPECT, f"{c.adc_name} の TP_PARAM（コアの TP）")
    # 全帯域（FULL。tb: k = 2）
    sp = S.Spec(fs.m, idx=1, label="ADC_B", base=fs.base, lbase=fs.lbase)
    judge(sp.rd(S.R_NACC) == 102 and sp.rd(S.R_NDUMP) == 202 and sp.rd(S.R_SHIFT) == 7, "FULL の N_ACC・N_DUMP・SHIFT")
    judge(sp.rd(T.RS_CFG) == 0xC0F0_0002, "FULL の CFG_ID（timetest.RS_CFG）")
    judge(sp.rd(S.R_SRC) == 0x8000_0001, f"FULL の SRC {sp.rd(S.R_SRC):#x}（ARM_WRST で 1）")
    judge(sp.rd(S.R_BUILD) == 0x5678_0000, "FULL の BUILD（診断 0x214）")
    judge(sp.legacy_id() == 0x0021_02A5 and S.feat_rev(sp.rd(S.R_ID)) == 6, "FULL の FFT_CFG（PARAM）と feat_rev")
    judge(sp.rd(S.R_TP_PARAM) == S.TP_PARAM_EXPECT, "FULL の TP_PARAM（Spec.rd の 0x100 → 仮の 0xC1100）")
    judge(cores[0].rd(W.A_BASE + W.R_A_SNAP_SEL) == 1, "仮の SNAP_SEL（window.R_A_SNAP_SEL）")
    # time_core
    tc = TB.TimeCore(tmm)
    judge(tc.proj == 0x0021_0200 and tc.proj in TB.CAL, "time_core の PROJ と CAL の鍵")
    print(f"test_regmap: {nchk} 項目")
    print("test_regmap: 結果: " + ("全部通過" if ng == 0 else f"失敗（{ng} 件）"))
    return 0 if ng == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
