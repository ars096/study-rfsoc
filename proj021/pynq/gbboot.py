#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj021 手順 1b — 判定 G-3・G-4: Overlay の読み込み直しを N 回繰り返し、4 ADC のギアボックスの起動を毎回見る

  python3 gbboot.py --loads 50 --clkin 0 --ref 10 --out runs/g3              # G-3（proj021.bit、K = 2）
  python3 gbboot.py --loads 50 --clkin 0 --ref 10 --bitfile proj021_k0.bit \\
                                     --expect-k 0 --out runs/g4                                 # G-4（陽性対照、GB_K=0 のビルド）

proj015 から GRST（PS からの起動のやり直し）は無い（win_core.v の冒頭）ので、起動は Overlay の読み込みでしか起こせない。
1 回ごとに、コアの共通（proj021 2-1 から s45_core_i の 0x00000 ＋。1b までは win_core_i の 0x80000 ＋ 表 A）を、読み込みの --settle 秒後と、さらに --dwell 秒後の 2 回読む:
  GB_STAT  [31] 開始した（armed）/ [29:24] 開始したときの FIFO の残量 / [21:16] その後の FIFO の残量の最小 / [15:0] 空振り（出口が空なのに下流が欲しかったクロック）
  ADC_STAT [31] RFDC の valid を見た / [15:0] RFDC の valid が落ちた回数（2 回読んで一致を確かめる）
  GB_K     起動に効いたしきい値
合格（G-3）: 全部の回・全部の ADC で armed・空振り 0・dwell の間に空振りが増えない・RFDC の valid の落ち 0・GB_K = --expect-k
陽性対照（G-4、K = 0）: 空振りが 1 回以上ある起動が出る（proj011〜012 の K = 0 の実機と同じ形）。**出なければ見張りが壊れているか、
起動の途切れが起きにくい日なので、G-3 の結果を「起動の途切れが無い」とは読まない**（回数を増やして測り直す）
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 旧（proj021 1b まで、win_core_i）: ADC の共通 = 0x80000 ＋ 表 A。proj021 手順 2-1 から（s45_core_i）: コアの共通 = 0x00000 ＋（表 A ＋ 0x10）。
#   どちらの .bit かは .hwh の IP の名前で決める（LAYOUT）
LAYOUT = {
    "win_core": dict(base=0x80000, r_id=0x00, r_gb_k=0x1C, r_gb_stat=0x24, r_adc_stat=0x28, id=None),
    "s45_core": dict(base=0x00000, r_id=0x00, r_gb_k=0x2C, r_gb_stat=0x34, r_adc_stat=0x38, id=0x0202_0101),
}
LABELS = ["ADC_A", "ADC_B", "ADC_C", "ADC_D"]


def log(*a):
    print(*a, flush=True)


def gb_fields(v):
    return dict(armed=(v >> 31) & 1, cnt_arm=(v >> 24) & 0x3F, cnt_min=(v >> 16) & 0x3F, under=v & 0xFFFF)


def read_adc(mm, L):
    b = L["base"]
    gs = mm.read(b + L["r_gb_stat"])
    a1 = mm.read(b + L["r_adc_stat"])
    a2 = mm.read(b + L["r_adc_stat"])
    return dict(id=mm.read(b + L["r_id"]), gb_k=mm.read(b + L["r_gb_k"]) & 0x3F, gb_stat=gs, adc_stat=a1,
                adc_stable=(a1 == a2), adc_seen=(a1 >> 31) & 1, adc_gaps=a1 & 0xFFFF, **gb_fields(gs))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--loads", type=int, default=50, help="Overlay の読み込みの回数")
    p.add_argument("--clkin", default="stock", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=2.0, help="読み込みから 1 回目に読むまで [s]")
    p.add_argument("--dwell", type=float, default=5.0, help="1 回目から 2 回目に読むまで [s]（その間に空振りが増えないこと）")
    p.add_argument("--bitfile", default=None)
    p.add_argument("--expect-k", type=int, default=2, help="起動に効いているはずの GB_K（ビルドの GB_K_RST）")
    p.add_argument("--any-id", action="store_true", help="ID を照合しない（proj020.bit と比べるとき）")
    p.add_argument("--out", default=None, help="PREFIX.gbboot.json に 1 回ごとの記録")
    a = p.parse_args()

    import spectrometer as S
    import window as WN
    from pynq import MMIO, Overlay
    import xrfdc                                   # Overlay() より前に import する（VERSIONS.md）
    bit = a.bitfile or S.BITFILE
    S.setup_clocks(a.clkin, a.ref)
    rows, t0 = [], time.time()
    nbad = nunder = 0
    for k in range(a.loads):
        ol = Overlay(bit)
        if not isinstance(ol.rfdc, xrfdc.RFdc):
            log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
        S.check_tiles(ol.rfdc, 2)
        kind = "s45_core" if "s45_core_0" in ol.ip_dict else "win_core"
        L = LAYOUT[kind]
        mms = [None] * 4
        for i in range(4):
            ip = ol.ip_dict.get(f"{kind}_{i}")
            if ip is None:
                log(f"ERROR: {kind}_{i} が .hwh に無い"); sys.exit(1)
            m = MMIO(ip["phys_addr"], 0x100000)
            adc = (m.read(0x18) & 0xF) if kind == "s45_core" else i      # v2: CORE_PORT の ADC の番号で並べる
            mms[adc] = m
        if any(m is None for m in mms):
            log("ERROR: CORE_PORT の ADC が 0..3 を埋めていない"); sys.exit(1)
        time.sleep(a.settle)
        r1 = [read_adc(m, L) for m in mms]
        time.sleep(a.dwell)
        r2 = [read_adc(m, L) for m in mms]
        bad = []
        for i in range(4):
            x, y = r1[i], r2[i]
            want_id = L["id"] if L["id"] is not None else 0x0021_A100
            if not a.any_id and x["id"] != want_id:
                bad.append(f"{LABELS[i]} ID {x['id']:#010x}（期待 {want_id:#010x}）")
            if x["gb_k"] != a.expect_k:
                bad.append(f"{LABELS[i]} GB_K {x['gb_k']}（期待 {a.expect_k}）")
            if not x["armed"]:
                bad.append(f"{LABELS[i]} 開始していない")
            if x["under"] or y["under"]:
                bad.append(f"{LABELS[i]} 空振り {x['under']} → {y['under']}")
            if y["under"] != x["under"]:
                bad.append(f"{LABELS[i]} dwell の間に空振りが増えた")
            if not (x["adc_stable"] and x["adc_seen"]) or x["adc_gaps"] or y["adc_gaps"] != x["adc_gaps"]:
                bad.append(f"{LABELS[i]} RFDC の valid: 見た {x['adc_seen']}・落ち {x['adc_gaps']} → {y['adc_gaps']}")
        nunder += any(r["under"] for r in r1 + r2)
        nbad += bool(bad)
        line = " ".join(f"{LABELS[i][-1]}:arm{r1[i]['cnt_arm']:2d}/min{r1[i]['cnt_min']:2d}/空振り{r2[i]['under']}" for i in range(4))
        log(f"{k + 1:3d}/{a.loads}  {line}  {'OK' if not bad else 'NG: ' + '・'.join(bad)}")
        rows.append(dict(k=k, t=time.time() - t0, first=r1, second=r2, bad=bad))
        del ol
    log(f"G-3/G-4: {a.loads} 回の起動のうち、空振りのあった起動 {nunder}・何かが NG の起動 {nbad}（{time.time() - t0:.0f} s）")
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out + ".gbboot.json", "w") as f:
            json.dump(dict(args=vars(a), bit=bit, rows=rows, n_under=nunder, n_bad=nbad), f, indent=1, ensure_ascii=False)
        log(f"→ {a.out}.gbboot.json")


if __name__ == "__main__":
    main()
