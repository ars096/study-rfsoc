#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj032 P-9 — SpW のコア 4 個（ADC_A〜D、H 8・S 8）・PL の DDR なしの .bit（build/proj032b5.bit）で、4 コアを同時に動かして照らす

    python3 spw_b5.py --clkin 0 --ref 10 --sec 10 --cfg b5 --out runs/p9b5_b5

spw_b4.py（b4 rev 8、H 6・S 6）からの差:
  - H 8・S 8（rev 9）。頭 0..3 が偶の k、4..7 が奇の k
  - 既定の構成 b5: 窓 8 本（128・64・64・16 / 128・64・32・8 MHz）で、チップ内の枠 0..7 を全部使う。16 MHz（NS 4）と 8 MHz（NS 5）の窓を初めて実機に入れる
    lane 0 = 128 + 64 + 16・1 = 64 + 128・2 = 64 + 32 + 8 MHz
  - 構成 b1（P-7 と同じ 6 窓）も残す（b2 の頭の番号 0..2 → 0..2・7..9 → 4..6）
  - P-10: --win "IF:幅,IF:幅,..." で窓を spwplan.py の計画から入れる（WDPHI ≠ 0・2 番目に近い粗い ch を初めて実機に）。
    --alt i,j: 窓 i を 2 番目に近い粗い ch で作り、同じ IF・幅で近い ch の窓 j と双子にする（比の揺れ ≦ 独立な雑音の 1/4 を合否に）。
    --tone F: SG の CW（IF F MHz、SG は手で設定する）が、F を含む窓で計画の予言の ch に立つかを合否に（ピーク / 中央値 ≧ 20 dB の窓だけ）。
    --wrst-test: コア 0 に約束 [1]〜[6] を 1 つずつ破る設定を書いて WRST し、PL の WRST_BAD と spwplan.check() の印が同じかを合否に（設定は効かない）
  - P-13: --fast で窓のレコードを C（spwfast.c → libspwfast.so）で読む: 写さずに（plring の LazyRec）、PL の CRC と器への足し込みを 1 回のなめで
    （YATSUGATAKE specd の --fast-ring と同じ形。Python の道は 1 本ずつ zlib・写し・float64 への変換で、10.24 ms × 32 窓に追いつかなかった）。
    読みの手間（輪の中の時間の割合・1 本あたり）を出す。--fast-posctl: C の CRC の期待値を 1 bit 反転 → 窓のレコードが全部 CRC の誤りになるはず
以下は spw_b4.py の注

spw_b3.py（b3、MIG あり。配線できず .bit は無い）からの差:
  - MIG と clk_mon_0 が無い（その見張りを外した）。窓はチップ内の枠（WSL < S）だけ: DDR の枠を使う構成（A・B）は断る。既定の構成は b1（6 窓、双子なし）
  - H 6（rev 8）。窓の番号は H 6 に詰める（頭 0..2 が偶の k、3..5 が奇の k）: b2 の 0..2 → 0..2・7..9 → 3..5。rev 7（H 12）は .bit なし
以下は spw_b3.py の注

spw_b2.py（P-8）からの差:
  - コア 4 個（s45_core_0〜3 = ADC_A〜D）に同じ窓の構成を入れ、同じリングから読む。レコードはコアの番号（w0 の core = CORE_PORT[7:0]）で分け、
    SEQ・DUMP_K・K_F・TP・見張り・双子の比はコアごとに照らす。--cores で一部のコアだけを動かせる（動かさないコアのレコードは誤り）
  - 窓の番号は H 12 に合わせて詰める（頭 0..5 が偶の k、6..11 が奇の k）。構成は b2 と同じ窓を、奇の頭だけ 1 つ前に（b2 の 7..13 → 6..12）
  - 番地は hwh の名前で引く（b3 で time・ring・clk_mon の番地が動いた）
  - 双子の比の合否（比の揺れ ≦ 独立な雑音の 1/4）は、TP が --tp-min dBFS 以上のコアだけ（入力の無い ADC は 8 bit の丸めが効きすぎて比が意味を持たない）
以下は spw_b2.py の注

spw_b1.py（P-7）からの差:
  - Overlay の直後、コアに触る前に clk_mon_0（pl_clk0 の側）で MIG の参照クロック 200 MHz・UI クロック 300 MHz・較正を確かめる（較正していなければ止める）
  - 窓の構成 --cfg: b1 の 6 窓（チップ内）に、同じ WK・NS の**双子**を DDR の枠（WSL ≧ S）に置く。
      A: DDR の窓 4 本（NS 2 × 3・NS 3 × 1、DDR の幅の和 224 MHz）/ B: DDR の窓 NS 1 × 2（256 MHz = 設計の上限）
  - DDR の窓の 8 bit の利得 WG = --wg（h = sat8(round(z / 2^g))）。機関の FLAGS[8]（8 bit の飽和）は利得しだいなので合否から外し、診断に出す
  - 診断に双子の比（DDR の窓 / チップ内の窓、ch ごと、fftshift の中央 14/16）。入力は同じ標本なので、違いは 8 bit の丸めの雑音だけ:
    比の中央値 − 1 ≒ 1/(12·σ8²)（σ8 = 8 bit の rms）。番地・区画・タップの取り違えがあれば、比の揺れが独立な雑音の大きさ（√(2/N)）になる
以下は spw_b1.py の注

手順: クロック → Overlay（xrfdc を先に import）→ ID・ギアボックス・時刻の確かめ → リング（plring.Ring、PS の DDR 32 MiB）→
      TP のレコード（TP_REC_CTRL 10 個）・TP_RUN → 窓の設定（6 窓、残り 8 窓は止める窓）・NG・NDUMP 0 → WRST ＋ RUN →
      --sec 秒リングを読み続ける → STOP → 見張り（CORE_FLAGS・窓の FLAGS・リングの DROP・EXT・ERR）
照らすもの（合否）:
  - ID: コアの IF_ID 0x0207_0201（--rev 1 なら 0x0207_0101）・PROJ 0x0032_0300・NSTREAM 14・CAPS 3・CORE_PORT 0x2200、time_core 0x0207_0202、リング 0x0207_0203
  - ギアボックス: GB_STAT の開始・空振り 0（2 回読んで増えない）、ADC_STAT の valid を見た・落ち 0
  - 窓のレコード（type 5）: CRC・尾、SEQ が 0 から 1 ずつ、窓ごとの DUMP_K が 1 ずつ、頭の NS・SHIFT・DUMP_N、
    K_F = DUMP_T − 2^(12+NS)·DUMP_F0 が窓ごとに一定で 0 ≦ K_F < 2^(12+NS)（P-4 の格子）、本体が有限で負でない、動いている窓だけから来る
  - TP のレコード（type 2）: CRC・尾、SEQ が前 ＋ DUMP_N、個のフレームが続いている
  - 終わりの見張り（RUN の --settle 秒後に FLAGS を消した後の分）: CORE_FLAGS 0・窓の FLAGS 0・DROP_CNT 0・EXT_CNT 0・ERR_STAT 0・レコードの数 = REC_CNT
診断（合否にしない）: 窓ごとの平均スペクトルの中央値・最大 / 中央値・最大の ch、窓ごとの平らさ、**同じ中心の NS 1 と NS 2 の窓の重なり**（w0 と w1）の形の比
  （ch 0 は窓の中心。fftshift し、NS 2 の 0.5・1・0.5 を NS 1 の 1 ch に合わせ、比の揺れ）。重なりは枠がずれても合う（P-7 の 1 回目）ので、正しさは平らさと CW の位置で見る。--out に .json（要約）と .npz（平均スペクトル）
"""
import argparse
import ctypes
import json
import os
import struct
import sys
import time
import zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

BITFILE = "proj032b5.bit"
LMK_FREQ, LMX_FREQ = 245.76, 491.52
H, E, S, G_L2 = 8, 3, 8, 19
NCORE = 4
LABELS = ("ADC_A", "ADC_B", "ADC_C", "ADC_D")
TILE_BLK = ((2, 1), (2, 0), (0, 1), (0, 0))     # (adc_tiles の添字, blocks の添字)。VERSIONS.md の実測
PORTS = (0x2200, 0x0201, 0x2002, 0x0003)          # CORE_PORT: [3:0] コア・[11:8] タイル・[15:12] スライス
PROJ = 0x0032_0300
REV = 10                                         # BIT_REV。10 = b5 の rev 10（RTL の扇出の直し）・9 = b5（4 ADC・H 8・S 8・PL の DDR なし）・8 = b4（H 6）。7 = b4 の H 12・b3 は 5・6（.bit なし）、b2 は 3・4、b1 は 1・2


def ids_for(rev):
    """IF_ID {IF_VER 2, BIT_KIND 7, BIT_REV, CORE_KIND}: コア 1・time_core 2・リング 3"""
    return tuple(0x0207_0000 | rev << 8 | ck for ck in (1, 2, 3))


# コアの番地
C_IF_ID, C_PROJ, C_NSTREAM, C_CAPS, C_CORE_PORT, C_TP_CTRL, C_GB_K, C_GB_STAT, C_ADC_STAT = 0x00, 0x04, 0x08, 0x0C, 0x18, 0x20, 0x2C, 0x34, 0x38
C_CORE_FLAGS, C_NG, C_NDUMP, C_WRST_BAD, C_WRST_CNT = 0x80, 0x84, 0x88, 0x8C, 0x90
TP_N, TP_WP, TP_REC_CTRL = 0x100, 0x108, 0x11C
S_CTRL, S_SHIFT, S_FLAGS, S_WK, S_WDPHI, S_WNS, S_WFL, S_WSL, S_WG = 0x08, 0x14, 0x18, 0x100, 0x104, 0x108, 0x120, 0x124, 0x128
CT_RUN, CT_STOP, CT_FCLR, CT_WRST = 1, 2, 1 << 8, 1 << 12
R_EXT = 0x30
# 窓: (s, WK, NS, lane, WSL)。頭 0..6 は偶の k、7..13 は奇の k（PSPLIT、WRST の約束 [6]）。WSL ≧ S は DDR の枠 WSL − S
#   WRST の約束: lane ごとの幅の和 ≦ 256 MHz（NS 1 = 128・2 = 64・3 = 32）、DDR の窓の幅の和 ≦ 256 MHz
WINS_B1 = [(0, 8, 1, 0, 0), (1, 8, 2, 0, 1), (2, 12, 2, 1, 2), (7, 9, 1, 1, 3), (8, 21, 2, 2, 4), (9, 25, 3, 2, 5)]
CFGS14 = {
    # A: b1 の 6 窓 ＋ 双子 4 本（3 ↔ 1・4 ↔ 2・11 ↔ 8・10 ↔ 9）。lane 0 = 128 + 64 + 32・1 = 64 + 128 + 64・2 = 64 + 32 + 64 + 64 MHz、DDR 224 MHz
    "A": (WINS_B1 + [(3, 8, 2, 2, 6), (4, 12, 2, 2, 7), (11, 21, 2, 1, 8), (10, 25, 3, 0, 9)], {3: 1, 4: 2, 11: 8, 10: 9}),
    # B: NS 1 の双子 2 本（3 ↔ 0・10 ↔ 7）で DDR の幅の和 256 MHz。lane 0 = 128 + 128・1 = 128 + 128・2 = 64 × 3 + 32 MHz
    "B": ([(0, 8, 1, 0, 0), (3, 8, 1, 0, 6), (7, 9, 1, 1, 3), (10, 9, 1, 1, 7),
           (1, 8, 2, 2, 1), (2, 12, 2, 2, 2), (8, 21, 2, 2, 4), (9, 25, 3, 2, 5)], {3: 0, 10: 7}),
    "b1": (WINS_B1, {}),
}


def hmap(s):
    """b2（H 14）の頭の番号 → H 8 の番号（偶の頭 0..3 はそのまま、奇の頭 7..10 → 4..7）。H 8 に無い頭は None"""
    if s < 4:
        return s
    if 7 <= s < 11:
        return s - 3
    return None


def cfg_h8(wins, tw):
    m = [(hmap(s), k, ns, fl, sl) for s, k, ns, fl, sl in wins]
    return None if any(s is None for s, *_ in m) else (m, {hmap(d): hmap(c) for d, c in tw.items()})


# A・B（DDR の枠の双子）は b5 では使わない: S 8 では b2 の DDR の枠 6・7 がチップ内の枠になり、双子の比べが意味を持たない
CFGS = {"b1": cfg_h8(*CFGS14["b1"])}
# b5: 窓 8 本、チップ内の枠 0..7（H 8 の番号のまま）。(s, WK, NS, lane, WSL)
CFGS["b5"] = ([(0, 8, 1, 0, 0), (1, 8, 2, 0, 1), (2, 12, 2, 1, 2), (3, 16, 4, 0, 6),
               (4, 9, 1, 1, 3), (5, 21, 2, 2, 4), (6, 25, 3, 2, 5), (7, 17, 5, 2, 7)], {})
F_SAT8 = 1 << 8                                  # 機関の FLAGS[8]: DDR の窓の 8 bit の飽和（利得しだい。合否にしない）
CM_ID = 0x0280_00C1


def log(*a):
    print(*a, flush=True)


def blk(s, a):
    return 0x4000 + 0x400 * s + a


def setup_clocks(clkin, ref):
    if clkin != "stock":
        import extref
        extref.set_clocks(int(clkin), ref_mhz=ref)
        return
    import xrfclk
    fn = getattr(xrfclk, "set_ref_clks", None) or getattr(xrfclk, "set_ref_clk")
    fn(lmk_freq=LMK_FREQ, lmx_freq=LMX_FREQ)


class Regs:
    def __init__(self, ip, size):
        from pynq import MMIO
        self.m = MMIO(ip["phys_addr"], size)

    def rd(self, a):
        return int(self.m.read(a)) & 0xFFFFFFFF

    def wr(self, a, v):
        self.m.write(a, int(v) & 0xFFFFFFFF)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--clkin", default="0", choices=("stock", "0", "1", "2"))
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--zone", type=int, default=2, help="ADC の NyquistZone（4 本とも）")
    p.add_argument("--bitfile", default=os.path.join(HERE, BITFILE))
    p.add_argument("--rev", type=int, default=REV, help="載っているはずの BIT_REV")
    p.add_argument("--cores", default="0123", help="動かすコア（例: 0123・0）")
    p.add_argument("--sec", type=float, default=10.0)
    p.add_argument("--ng", type=int, default=5, help="ダンプの長さ（G = 2.048 ms の数。5 = 10.24 ms）")
    p.add_argument("--shift", type=int, default=4)
    p.add_argument("--ring-mib", type=int, default=64)
    p.add_argument("--settle", type=float, default=0.5, help="RUN の後、FLAGS を読んで消すまで [s]（起動の時だけの印を分ける）")
    p.add_argument("--cfg", default="b5", choices=sorted(CFGS), help="窓の構成（b5 = 8 窓・既定、b1 = P-7 と同じ 6 窓。PL の DDR が無いので A・B は断る）")
    p.add_argument("--wg", type=int, default=4, help="DDR の窓の 8 bit の利得 WG（右シフト 0..10）")
    p.add_argument("--win", default=None, help="P-10: 窓を IF:幅 MHz の並びで（spwplan.py で計画）。--cfg より先")
    p.add_argument("--alt", default=None, help="P-10: i,j = 窓 i を 2 番目に近い粗い ch で、近い ch の窓 j と双子に（同じ IF・幅）")
    p.add_argument("--tone", type=float, default=None, help="P-10: SG の CW の IF [MHz]（SG は手で）。含む窓で予言の ch を照らす")
    p.add_argument("--wrst-test", action="store_true", help="P-10: 約束を破る設定で PL の WRST_BAD と spwplan.check() を照らす（コア 0）")
    p.add_argument("--tp-min", type=float, default=-40.0, help="双子の比を合否に入れるコアの TP の下限 [dBFS]")
    p.add_argument("--fast", action="store_true", help="P-13: 窓のレコードを C で（libspwfast.so）")
    p.add_argument("--fast-posctl", action="store_true", help="P-13: 陽性対照（C の CRC の期待値を反転）")
    p.add_argument("--out", default=None)
    a = p.parse_args()
    if CFGS[a.cfg] is None:
        p.error(f"--cfg {a.cfg} は H 8 の頭に収まらない")
    WINS, TWINS = CFGS[a.cfg]
    DPHI, PLAN = {}, None
    if a.win:
        import spwplan
        req = [tuple(float(v) for v in x.split(":")) for x in a.win.split(",")]
        fk, tw_ij = {}, None
        if a.alt:
            i, j = (int(v) for v in a.alt.split(","))
            if req[i] != req[j]:
                p.error(f"--alt {a.alt}: 窓 {i} と {j} の IF・幅が違う")
            fk, tw_ij = {i: "alt", j: "near"}, (i, j)
        try:
            PLAN = spwplan.plan(req, H=H, E=E, S=S, ddr=False, force_k=fk)
        except spwplan.PlanError as e:
            p.error(f"--win を計画できない: {e}")
        log(spwplan.table(PLAN))
        if spwplan.check(PLAN["streams"], E=E, S=S):
            p.error("計画が約束を破る（spwplan の誤り）")
        WINS = [(x["s"], x["k"], x["ns"], x["fl"], x["sl"]) for x in PLAN["wins"]]
        DPHI = {x["s"]: x["dphi"] for x in PLAN["wins"]}
        TWINS = {PLAN["wins"][tw_ij[0]]["s"]: PLAN["wins"][tw_ij[1]]["s"]} if tw_ij else {}
    if any(sl >= S for _, _, _, _, sl in WINS):
        p.error(f"--cfg {a.cfg} は DDR の枠（WSL ≧ {S}）を使う。b5 には PL の DDR が無い")
    cores = sorted({int(c) for c in a.cores})
    assert all(0 <= c < NCORE for c in cores)

    bad = []
    setup_clocks(a.clkin, a.ref)
    import xrfdc                                     # Overlay() より前に import する（VERSIONS.md）
    from pynq import Overlay, MMIO
    import plring
    import hashlib
    with open(a.bitfile, "rb") as f:
        bit_sha = hashlib.sha256(f.read()).hexdigest()
    log(f"ビルドの指紋: {os.path.basename(a.bitfile)} sha256 {bit_sha[:16]}…・期待する BIT_REV {a.rev}")
    ol = Overlay(a.bitfile)
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    for t in (0, 2):
        if ol.rfdc.adc_tiles[t].PLLLockStatus != 2:
            log(f"ERROR: Tile {224 + t} の PLL がロックしていない（{ol.rfdc.adc_tiles[t].PLLLockStatus}）"); sys.exit(1)
    for c, (t, b) in enumerate(TILE_BLK):
        blk_ = ol.rfdc.adc_tiles[t].blocks[b]
        blk_.NyquistZone = a.zone
        log(f"{LABELS[c]}（Tile {224 + t} / blocks[{b}]）: SamplingFreq {blk_.BlockStatus.get('SamplingFreq')} GSPS・NyquistZone {blk_.NyquistZone}")

    mig = None                                       # b4・b5 は MIG・clk_mon_0 を置かない

    cr = [Regs(ol.ip_dict[f"s45_core_{c}"], 0x10000) for c in range(NCORE)]
    tc = Regs(ol.ip_dict["time_core_0"], 0x1000)
    rmm = Regs(ol.ip_dict["s45_ring_0"], 0x1000)
    ID_CORE, ID_TIME, ID_RING = ids_for(a.rev)
    ids = dict(time=tc.rd(0x00), ring=rmm.rd(0x00), ring_proj=rmm.rd(0x2C), time_bps=tc.rd(0x04))
    for k, want in (("time", ID_TIME), ("ring", ID_RING), ("ring_proj", PROJ), ("time_bps", 256_000_000)):
        if ids[k] != want:
            bad.append(f"ID {k} {ids[k]:#x}（期待 {want:#x}）")
    for c in range(NCORE):
        r = cr[c]
        got = dict(core=r.rd(C_IF_ID), proj=r.rd(C_PROJ), nstream=r.rd(C_NSTREAM), caps=r.rd(C_CAPS), port=r.rd(C_CORE_PORT))
        ids[f"core{c}"] = got
        for k, want in (("core", ID_CORE), ("proj", PROJ), ("nstream", H), ("caps", 3), ("port", PORTS[c])):
            if got[k] != want:
                bad.append(f"ID コア {c} {k} {got[k]:#x}（期待 {want:#x}）")
    log("ID: " + " ".join(f"{k} {v:#010x}" for k, v in ids.items() if isinstance(v, int)) + " / " +
        " ".join(f"コア {c}: " + ",".join(f"{v:#x}" for v in ids[f'core{c}'].values()) for c in range(NCORE)))
    if bad:
        log("ERROR: 載っている .bit が違う: " + "・".join(bad)); sys.exit(1)

    def gb(c):
        g, d = cr[c].rd(C_GB_STAT), cr[c].rd(C_ADC_STAT)
        return dict(armed=g >> 31 & 1, under=g & 0xFFFF, adc_seen=d >> 31 & 1, adc_gaps=d & 0xFFFF, gb_k=cr[c].rd(C_GB_K))
    t1, g1 = (tc.rd(0x18) | tc.rd(0x1C) << 32), [gb(c) for c in range(NCORE)]
    time.sleep(1.0)
    t2, g2 = (tc.rd(0x18) | tc.rd(0x1C) << 32), [gb(c) for c in range(NCORE)]
    for c in range(NCORE):
        log(f"ギアボックス コア {c}: {g1[c]} → {g2[c]}")
        x, y = g1[c], g2[c]
        if not (x["armed"] and x["adc_seen"]) or x["under"] or y["under"] != x["under"] or x["adc_gaps"] or y["adc_gaps"]:
            bad.append(f"ギアボックス・ADC の見張り（コア {c}）")
    log(f"T の進み {t2 - t1} ビート / 約 1 s")
    if not 200e6 < t2 - t1 < 400e6:
        bad.append(f"T が進まない（{t2 - t1}）")

    if a.wrst_test:
        import spwplan
        r = cr[0]
        base = [dict(WK=(0 if s < H // 2 else 1), WDPHI=0, WNS=1, WFL=E, WSL=0, WG=0) for s in range(H)]
        for s, k, ns, fl, sl in CFGS["b5"][0]:
            base[s] = dict(WK=k, WDPHI=0, WNS=ns, WFL=fl, WSL=sl, WG=0)
        muts = {1: [(s, "WFL", 0) for s in range(4)], 2: [(0, "WSL", S), (4, "WSL", S + 1), (1, "WSL", S + 2)], 3: [(1, "WSL", 0)],
                4: [(7, "WSL", S), (6, "WSL", S)], 5: [(2, "WNS", 6)], 6: [(4, "WK", 8)], 0: []}
        wt = {}
        for bit, mu in muts.items():
            st = [dict(x) for x in base]
            for s, k, v in mu:
                st[s][k] = v
            want = spwplan.check(st, E=E, S=S)
            for s in range(H):
                for reg, k in ((S_WK, "WK"), (S_WDPHI, "WDPHI"), (S_WNS, "WNS"), (S_WFL, "WFL"), (S_WSL, "WSL"), (S_WG, "WG")):
                    r.wr(blk(s, reg), st[s][k])
            r.wr(blk(0, S_CTRL), CT_FCLR)
            n0 = r.rd(C_WRST_CNT)
            r.wr(blk(0, S_CTRL), CT_WRST)
            time.sleep(0.05)
            got_cf, got_bad, n1 = r.rd(C_CORE_FLAGS), r.rd(C_WRST_BAD), r.rd(C_WRST_CNT)
            refused = bool(got_cf & 1)
            ok = (refused and n1 == n0 and got_bad == want) if want else (not refused and n1 == n0 + 1)
            wt[bit] = dict(want=want, wrst_bad=got_bad, core_flags=got_cf, wrst_cnt=(n0, n1), ok=ok)
            log(f"WRST の約束 [{bit}]: check {want:#x}・PL WRST_BAD {got_bad:#x}・CORE_FLAGS {got_cf:#x}・WRST_CNT {n0} → {n1}: {'合う' if ok else '合わない'}")
            if not ok:
                bad.append(f"WRST の約束 [{bit}] の照らし")
        r.wr(blk(0, S_CTRL), CT_FCLR)
    ring = plring.Ring(MMIO(ol.ip_dict["s45_ring_0"]["phys_addr"], 0x1000), a.ring_mib << 20)
    fastlib = None
    if a.fast:
        fastlib = ctypes.CDLL(os.path.join(HERE, "libspwfast.so"))
        fastlib.spw_rec_acc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint32)]
        fastlib.spw_rec_acc.restype = ctypes.c_int
        log(f"P-13: --fast（libspwfast.so、CRC 命令 {fastlib.spw_hw_crc()}）" + ("・陽性対照（CRC の期待値を反転）" if a.fast_posctl else ""))
    ring.enable(True)
    act = {}
    for c in cores:
        r = cr[c]
        # TP: 1.024 ms の区切り（TP_N 512 フレーム）を 10 個で 1 レコード、TP_RUN
        r.wr(TP_N, 512)
        r.wr(TP_REC_CTRL, (10 << 8) | 1)
        r.wr(C_TP_CTRL, 1)
        for s in range(H):
            r.wr(blk(s, S_WFL), 3)                   # 止める窓
            r.wr(blk(s, S_WK), 2 * s if s < H // 2 else 2 * (s - H // 2) + 1)
            r.wr(blk(s, S_WSL), 0)
        for s, k, ns, fl, sl in WINS:
            for reg, v in ((S_WK, k), (S_WDPHI, DPHI.get(s, 0)), (S_WNS, ns), (S_WFL, fl), (S_WSL, sl), (S_WG, a.wg if sl >= S else 0), (S_SHIFT, a.shift)):
                r.wr(blk(s, reg), v)
            act[(c, s)] = dict(k=k, ns=ns, fl=fl, sl=sl)
        r.wr(C_NG, a.ng)
        r.wr(C_NDUMP, 0)
        r.wr(blk(0, S_CTRL), CT_FCLR)
        cnt0 = r.rd(C_WRST_CNT)
        r.wr(blk(0, S_CTRL), CT_WRST | CT_RUN)
        t0 = time.time()
        while not r.rd(blk(0, S_CTRL)) & 1:
            if time.time() - t0 > 1.0:
                log(f"ERROR: コア {c} が RUN に入らない（CTRL {r.rd(blk(0, S_CTRL)):#x}・WRST_BAD {r.rd(C_WRST_BAD):#x}・CORE_FLAGS {r.rd(C_CORE_FLAGS):#x}）")
                sys.exit(1)
        log(f"コア {c} WRST ＋ RUN: WRST_CNT {cnt0} → {r.rd(C_WRST_CNT)}・WRST_BAD {r.rd(C_WRST_BAD):#x}・CORE_FLAGS {r.rd(C_CORE_FLAGS):#x}")
    # 起動の時だけの印か、動いている間も立つのかを分ける: RUN の後 --settle 秒で FLAGS を読んで消す（終わりの見張りは消した後の分）
    time.sleep(a.settle)
    fl_early = {f"{c}.{s}": cr[c].rd(blk(s, S_FLAGS)) for c, s in act}
    cf_early = {c: cr[c].rd(C_CORE_FLAGS) for c in cores}
    for c in cores:
        cr[c].wr(blk(0, S_CTRL), CT_FCLR)
    log(f"RUN の {a.settle} s 後: CORE_FLAGS {cf_early}・窓の FLAGS {fl_early} → 消した")

    # ---- 読み続ける ----
    seq = {c: 0 for c in cores}
    nrec, ntp, tp_seq = {}, {c: 0 for c in cores}, {c: None for c in cores}
    tp_sum, tp_nfr = {c: 0 for c in cores}, {c: 0 for c in cores}
    dk_last, kf = {}, {}
    acc = {cs: np.zeros(4096) for cs in act}
    nerr = 0
    crc_c = ctypes.c_uint32()
    n_xchk = 0                                       # C の CRC を zlib と照らした数（初めの 50 本）
    t_busy, n_loop, t_lmax, nbyte = 0.0, 0, 0.0, 0
    acc_p = {cs: v.ctypes.data for cs, v in acc.items()}     # ndarray.ctypes.data は 1 回 16 µs（ボード）。番地は先に引いておく
    ring_p = ring.a8.ctypes.data
    crc_r = ctypes.byref(crc_c)

    def err(msg):
        nonlocal nerr
        nerr += 1
        if nerr <= 20:
            log("  " + msg)

    t_end = time.time() + a.sec
    t_start = time.time()
    lazy = (lambda c, s, ty: ty == 5) if a.fast else None
    while time.time() < t_end:
        tl0 = time.perf_counter()
        for c, s, sq, hw, pay, crc_ok, tail_ok in ring.read(lazy=lazy):
            w = [int(x) for x in hw]
            typ = (w[0] >> 40) & 0xFF
            if crc_ok is None:                       # --fast: 窓のレコード（LazyRec）。CRC と足し込みは C で、下の本体で
                cs = (c, s)
                if cs in act:
                    nb = fastlib.spw_rec_acc(ring_p + pay.p, pay.pb >> 2, acc_p[cs], 0, crc_r)
                    crc_ok = (crc_c.value ^ (1 if a.fast_posctl else 0)) == pay.crc_exp
                    if n_xchk < 50:                  # C の CRC を zlib と照らす
                        n_xchk += 1
                        if crc_c.value != zlib.crc32(ring.a8[pay.p:pay.p + 64 + pay.pb]):
                            err(f"コア {c} 窓 {s} SEQ {sq}: C の CRC {crc_c.value:#x} ≠ zlib")
                    if nb:
                        err(f"コア {c} 窓 {s} SEQ {sq}: 本体に負か有限でない値 {nb} 個")
                    nbyte += 128 + pay.pb
                else:
                    crc_ok = True                    # 下で「動いていない窓」として数える
            if not (crc_ok and tail_ok):
                err(f"コア {c} type {typ} s {s} SEQ {sq}: CRC {crc_ok}・尾 {tail_ok}")
            if c not in seq:
                err(f"動いていないコア {c} のレコード（type {typ}）"); continue
            if typ == 2:
                ntp[c] += 1
                n = w[5] & 0xFFFFFFFF
                if tp_seq[c] is not None and sq != tp_seq[c]:
                    err(f"コア {c} TP SEQ {sq}（期待 {tp_seq[c]}）")
                tp_seq[c] = sq + n
                b = pay.view(np.uint8).tobytes()
                ents = [struct.unpack("<QII", b[16 * i:16 * i + 16]) for i in range(n)]
                for e in ents:
                    tp_sum[c] += e[0]; tp_nfr[c] += e[2] & 0xFFFFFF
                for i in range(1, n):
                    if ents[i][1] != ents[i - 1][1] + (ents[i - 1][2] & 0xFFFFFF):
                        err(f"コア {c} TP SEQ {sq} 個 {i}: フレームが続いていない")
                continue
            if typ != 5:
                err(f"コア {c} type {typ} のレコード"); continue
            if sq != seq[c]:
                err(f"コア {c} SEQ {sq}（期待 {seq[c]}）")
            seq[c] = sq + 1
            cs = (c, s)
            if cs not in act:
                err(f"コア {c} 動いていない窓 {s} のレコード"); continue
            x_ = act[cs]
            dk = w[1] >> 32
            l2n, ns, sh, g, fmt, src = [(w[4] >> (8 * i)) & 0xFF for i in range(6)]
            dn = w[5] & 0xFFFFFFFF
            if (l2n, ns, sh, fmt, dn, src) != (12, x_["ns"], a.shift, 1, a.ng << (G_L2 - 12 - x_["ns"]), c):
                err(f"コア {c} 窓 {s} SEQ {sq}: 頭 log2N {l2n} NS {ns} SHIFT {sh} fmt {fmt} DUMP_N {dn} src {src}")
            if cs in dk_last and dk != dk_last[cs] + 1:
                err(f"コア {c} 窓 {s}: DUMP_K {dk_last[cs]} → {dk}")
            dk_last[cs] = dk
            L = 1 << (12 + x_["ns"])
            k_f = w[3] - w[2] * L
            kf.setdefault(cs, set()).add(k_f)
            if not 0 <= k_f < L:
                err(f"コア {c} 窓 {s} K {dk}: K_F {k_f} が [0, {L}) の外")
            if not a.fast:
                x = pay.view(np.float32).astype(np.float64)
                if not np.all(np.isfinite(x)) or np.any(x < 0):
                    err(f"コア {c} 窓 {s} K {dk}: 本体に負か有限でない値")
                acc[cs] += x
                nbyte += pay.nbytes + 128
            nrec[cs] = nrec.get(cs, 0) + 1
        ring.release()
        dt = time.perf_counter() - tl0
        t_busy += dt; n_loop += 1; t_lmax = max(t_lmax, dt)
        time.sleep(0.01)
    t_run = time.time() - t_start
    nwin = sum(nrec.values())
    rd_stat = dict(fast=a.fast, t_run=t_run, busy=t_busy / t_run, loops=n_loop, loop_max_ms=1e3 * t_lmax,
                   us_per_rec=1e6 * t_busy / max(1, nwin), mb_s=nbyte / t_run / 1e6, xchk=n_xchk)
    log(f"読み: {'C（--fast）' if a.fast else 'Python'}・{nbyte / t_run / 1e6:.1f} MB/s・輪の中の時間の割合 {100 * t_busy / t_run:.1f} %"
        f"・1 本 {rd_stat['us_per_rec']:.0f} µs・1 周の最長 {1e3 * t_lmax:.1f} ms・C の CRC を zlib と照らした {n_xchk} 本")
    for c in cores:
        cr[c].wr(blk(0, S_CTRL), CT_STOP)
        cr[c].wr(C_TP_CTRL, 0)
    time.sleep(0.1)
    for _ in ring.read():
        pass                                         # STOP の後に閉じたダンプ（照らさない、数えない）
    ring.release()
    rr = ring.regs()
    fl = {cs: cr[cs[0]].rd(blk(cs[1], S_FLAGS)) for cs in act}
    cf = {c: cr[c].rd(C_CORE_FLAGS) for c in cores}
    ext = rmm.rd(R_EXT)
    log(f"レコード: 窓 {sum(nrec.values())}・TP {ntp}・照らしの誤り {nerr}")
    tp_dbfs = {c: (float(10 * np.log10(tp_sum[c] / (tp_nfr[c] * 8192) / (8192 ** 2 / 2))) if tp_nfr[c] and tp_sum[c] else None) for c in cores}
    log("TP: " + "・".join(f"コア {c} {v:.2f} dBFS" if v is not None else f"コア {c} 和が無い" for c, v in tp_dbfs.items()))
    log(f"K_F: " + " ".join(f"{c}.{s}:{','.join(str(v) for v in sorted(kf.get((c, s), [])))}" for c, s in act))
    log(f"見張り: CORE_FLAGS {cf}・窓の FLAGS {{{', '.join(f'{c}.{s}: {v:#x}' for (c, s), v in fl.items() if v)}}}・リング {rr}・EXT_CNT {ext}")
    for c in cores:
        log(f"  コア {c} TP_WP {cr[c].rd(TP_WP)}")
    if nerr:
        bad.append(f"照らしの誤り {nerr}")
    for cs in act:
        if nrec.get(cs, 0) < a.sec / (a.ng * 2.048e-3) * 0.5:
            bad.append(f"窓 {cs} のレコードが少ない（{nrec.get(cs, 0)}）")
        if len(kf.get(cs, ())) != 1:
            bad.append(f"窓 {cs} の K_F が一定でない")
    for c in cores:
        if ntp[c] == 0:
            bad.append(f"コア {c} の TP のレコードが無い")
    sat8 = sorted(cs for cs, v in fl.items() if v & F_SAT8)
    if sat8:
        log(f"8 bit の飽和（FLAGS[8]、合否にしない）: 窓 {sat8}・WG {a.wg}")
    for c in cores:
        flc = [v for (cc, s), v in fl.items() if cc == c]
        cf_x = cf[c] & ~0x2 if all(not (v & ~F_SAT8) for v in flc) else cf[c]     # CORE_FLAGS[1] が FLAGS[8] だけから来ているなら外す
        if cf_x or any(v & ~F_SAT8 for v in flc):
            bad.append(f"終わりの見張り（コア {c}）")
    if rr["drop"] or ext or rr["err_stat"]:
        bad.append("終わりの見張り（リング）")
    # 診断: 窓ごとの平均スペクトル
    diag = {}
    for cs in act:
        c, s = cs
        m = acc[cs] / max(1, nrec.get(cs, 0))
        med = float(np.median(m)) if nrec.get(cs) else 0.0
        d = dict(n=nrec.get(cs, 0), median=med, max_over_med=float(m.max() / med) if med > 0 else None, argmax=int(m.argmax()))
        if nrec.get(cs) and med > 0:
            seg = np.median(np.fft.fftshift(m).reshape(16, -1), axis=1) / med
            d["seg16"] = [float(x) for x in seg]
            d["flat"] = (float(seg[1:-1].min()), float(seg[1:-1].max()))
        diag[f"{c}.{s}"] = d
        log(f"コア {c} 窓 {s}（k {act[cs]['k']}・NS {act[cs]['ns']}）: n {d['n']}・中央値 {med:.4g}・最大 / 中央値 {d['max_over_med']}・最大の ch {d['argmax']}・平らさ {d.get('flat')}")
    # P-10: CW が計画の予言の ch に立つか（含む窓のうちピーク / 中央値 ≧ 20 dB のもの）
    tone = {}
    if a.tone is not None and PLAN:
        import spwplan
        for c in cores:
            for x in PLAN["wins"]:
                pr = spwplan.ch_of(a.tone, x)
                d = diag.get(f"{c}.{x['s']}")
                if pr is None or not d or not d.get("max_over_med"):
                    continue
                hit = d["max_over_med"] >= 100
                key = f"{c}.{x['s']}"
                tone[key] = dict(pred=pr[0], frac=pr[1], argmax=d["argmax"], pk_db=10 * np.log10(d["max_over_med"]), judged=hit)
                log(f"CW IF {a.tone}: コア {c} 窓 {x['s']}（k {x['k']}{'*' if x['alt'] else ''}・{x['w']:g} MHz）予言 ch {pr[0]}（端数 {pr[1]:+.3f}）・"
                    f"最大の ch {d['argmax']}・ピーク / 中央値 {tone[key]['pk_db']:.1f} dB" + ("" if hit else "（20 dB 未満、合否にしない）"))
                if hit and d["argmax"] != pr[0]:
                    bad.append(f"CW の ch（コア {c} 窓 {x['s']}: {d['argmax']} ≠ {pr[0]}）")
        if not any(v["judged"] for v in tone.values()):
            bad.append("CW が立った窓が無い")
    # P-8: 双子の比（DDR の窓 / チップ内の窓）。fftshift の中央 14/16（縁の 2 区間を除く）、中心の 5 ch（DC の線）を除く
    for c in cores:
        for sd, sc in TWINS.items():
            kd, kc = (c, sd), (c, sc)
            if not (nrec.get(kd) and nrec.get(kc)):
                bad.append(f"コア {c} 双子 {sd}↔{sc} のレコードが無い"); continue
            md, mc = np.fft.fftshift(acc[kd] / nrec[kd]), np.fft.fftshift(acc[kc] / nrec[kc])
            j = np.arange(256, 4096 - 256)
            j = j[np.abs(j - 2048) > 2]
            r = md[j] / mc[j]
            nn = min(nrec[kd], nrec[kc])
            tw = dict(ratio_median=float(np.median(r)), ratio_rel_std=float(np.std(r) / np.mean(r)), indep=float(np.sqrt(2.0 / nn)),
                      corr=float(np.corrcoef(md[j], mc[j])[0, 1]), argmax=(int(acc[kd].argmax()), int(acc[kc].argmax())))
            ex = tw["ratio_median"] - 1
            tw["sigma8"] = float(1 / np.sqrt(12 * ex)) if ex > 0 else None
            judged = tp_dbfs[c] is not None and tp_dbfs[c] >= a.tp_min
            tw["judged"] = judged
            diag[f"twin_{c}_{sd}_{sc}"] = tw
            log(f"コア {c} 双子 {sd} ↔ {sc}: 比の中央値 {tw['ratio_median']:.5f}・比の相対の揺れ {tw['ratio_rel_std']:.4f}"
                f"（独立な雑音なら ≒ {tw['indep']:.4f}）・形の相関 {tw['corr']:.5f}・最大の ch {tw['argmax']}・8 bit の rms の見当 {tw['sigma8']}"
                + ("" if judged else "（TP が低いので合否にしない）"))
            if judged and tw["ratio_rel_std"] > 0.25 * tw["indep"]:
                bad.append(f"コア {c} 双子 {sd}↔{sc} が合わない")
    if a.out:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        np.savez(a.out + ".npz", **{f"c{c}w{s}": acc[(c, s)] / max(1, nrec.get((c, s), 0)) for c, s in act})
        with open(a.out + ".json", "w") as f:
            json.dump(dict(args=vars(a), bit_sha256=bit_sha, ids=ids, mig=mig, wins=WINS, twins=TWINS, flags_early=fl_early,
                           core_flags_early=cf_early, gb=[g1, g2], nrec={f"{c}.{s}": v for (c, s), v in nrec.items()}, ntp=ntp, tp_dbfs=tp_dbfs,
                           nerr=nerr, kf={f"{c}.{s}": sorted(v) for (c, s), v in kf.items()}, core_flags=cf,
                           flags={f"{c}.{s}": v for (c, s), v in fl.items()}, ring=rr, ext=ext, diag=diag, tone=tone, plan=PLAN, rd=rd_stat, bad=bad), f, indent=1, ensure_ascii=False)
        log(f"→ {a.out}.json・.npz")
    log("結果: " + ("全部通過" if not bad else "不合格: " + "・".join(bad)))
    sys.exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
