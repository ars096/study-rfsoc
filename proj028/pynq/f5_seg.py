#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-6a — Overlay を 1 回だけ読み、RUN を区間ごとに繰り返してスペクトルを足し込む（ボードの上で。f5.py と同じ場所に置く）

  sudo -E $(which python3) f5_seg.py --segs on,off,on --chunks 40 --wait file --out f6_onoff   # 区間の間で <out>.go<i> を待つ
  sudo -E $(which python3) f5_seg.py --segs long --chunks 12600 --out f6_long                    # 1 区間 ≒ 1 時間

- 読み直しを挟むと全電力が ≒ 0.5 % の刻みで飛ぶ（F-5i）。ON / OFF を挟むときは同じ Overlay・同じ利得のまま RUN だけを止めて回し直す
- 利得: --gains-from（meta の gain）があればそれを書く。無ければ最初に 1 回だけ合わせる（区間の間で変えない）
- 区間ごとに: 止める → corner turn・細かい側の設定 → fine_top の SRST → リング → RUN（ct_wr の数えは RUN の 0 → 1 で 0 から）
  → チャンク 1〜--chunks を集める（チャンク 0 は 157 フレームなので足さない）→ 止める → 見張りを読む
- **チャンクを溜めずに足し込む**（PS のメモリに依らず何時間でも回せる）。チャンクごと・荒い ch ごとの全電力の列だけを残す
- 区間の間: --wait file（<out>.go<i> ができるまで待つ。ssh で touch する）か、--wait <秒>
- 保存: <out>_s<i>_spec.npy（足したスペクトル ÷ フレームの数、float32）・<out>_meta.json（区間ごとの見張り・全電力の列・時刻）。
  長い区間は --save-every チャンクごとに途中を保存する
"""
import argparse
import json
import os
import sys
import time

import numpy as np

import f5
from f5 import Regs, Ring, log, NCH, NKEEP, NTOT, CHUNK_BLK, BLK_RATE, CHS, PLANE, GPD, NPLANE, HB

AMS = "/sys/bus/iio/devices/iio:device0/"
PROBE_NACC = 1 << 20                              # 見張りの POW の区切り（≒ 14 ms。区切り 2 つを待つので ≒ 30〜45 ms 止まる）
PROBE = []                                         # (時刻, 区間, RUN 中か, PL の温度 °C, PS の温度 °C, 荒い段の ch 2〜30 の POW の和)


def temp(ch):
    try:
        return int(open(f"{AMS}in_temp{ch}_input").read()) / 1000.0
    except OSError:
        return float("nan")


def probe(cs, seg, running):
    """PL（in_temp20）・PS（in_temp7）の温度と、荒い段の POW を 1 つ記録する（RUN の中でも外でも同じ量）"""
    p, _ = f5.coarse_pow(cs, PROBE_NACC)
    PROBE.append((round(time.time(), 3), seg, int(running), temp(20), temp(7), float(p[2:31].sum())))


def stop(ctw, ctr):
    ctw.wr(0x04, 0)
    t0 = time.time()
    while ctw.rd(0x20) & 1 and time.time() - t0 < 2:
        time.sleep(0.01)
    time.sleep(CHUNK_BLK / BLK_RATE * 1.2)     # 読み途中のチャンクを読み切らせる
    ctr.wr(0x04, 0)


def configure(ctw, ctr, ft, shift):
    stop(ctw, ctr)
    for r, v in ((0x08, 0), (0x0C, CHS), (0x10, PLANE), (0x14, GPD), (0x18, NPLANE)):
        ctw.wr(r, v)
    for r, v in ((0x08, 0), (0x0C, CHS), (0x10, PLANE), (0x14, NPLANE), (0x18, HB)):
        ctr.wr(r, v)
    got = [ctw.rd(r) for r in (0x08, 0x0C, 0x10, 0x14, 0x18)] + [ctr.rd(r) for r in (0x08, 0x0C, 0x10, 0x14, 0x18)]
    if got != [0, CHS, PLANE, GPD, NPLANE, 0, CHS, PLANE, NPLANE, HB]:
        log(f"ERROR: corner turn の設定を読み返すと違う: {got}")
        sys.exit(1)
    ft.wr(0x08, shift)
    ft.wr(0x04, 1)
    time.sleep(0.01)
    ft.wr(0x04, 0)
    if ft.rd(0x08) != shift or ft.rd(0x10) != 0 or ft.rd(0x14) != 0:
        log(f"ERROR: fine_top の SHIFT {ft.rd(0x08)}・FLAGS 0x{ft.rd(0x10):x}・N_REC {ft.rd(0x14)}（SRST の後は 0）")
        sys.exit(1)


def segment(ol, cs, ctw, ctr, ft, a, out_stem, seg):
    """1 区間: チャンク 1..a.chunks を足し込む。戻り: (acc, nfr, ts, info)"""
    configure(ctw, ctr, ft, a.shift)
    ring = Ring(Regs(ol, "s45_ring_0"), a.ring_mib << 20)
    ring.enable(True)
    ctr.wr(0x04, 1)
    ctw.wr(0x04, 1)
    t_run = time.time()
    N = a.chunks
    acc = np.zeros(NTOT, dtype=np.float64)
    nfr = np.zeros(NCH, dtype=np.int64)                 # 荒い ch ごとに足したフレームの数
    ts = np.zeros((N + 1, NCH), dtype=np.float64)      # チャンク・ch ごとの平均の電力（bin の平均）
    seen = np.zeros((N + 1, NCH), dtype=bool)
    nbad, ndup, nact_ng, other = 0, 0, 0, 0
    bad_ex = []
    tmo = (N + 3) * CHUNK_BLK / BLK_RATE + 5
    last_save = 0
    t_probe = 0.0
    try:
        while not seen[1:].all() and time.time() - t_run < tmo:
            for kk, c, na, sk, body, crc_ok, tail_ok, hdr_ok in ring.read():
                if not (crc_ok and tail_ok and hdr_ok):
                    nbad += 1
                    if len(bad_ex) < 20:
                        bad_ex.append(dict(k=int(kk), c=int(c), crc=crc_ok, tail=tail_ok, hdr=hdr_ok))
                    continue
                if c > N or kk >= NCH:
                    other += 1
                    continue
                if seen[c, kk]:
                    ndup += 1
                    continue
                seen[c, kk] = True
                if c == 0:                              # 157 フレーム。足さない
                    continue
                if na != 160:
                    nact_ng += 1
                sl = slice(kk * NKEEP, (kk + 1) * NKEEP)
                acc[sl] += body
                nfr[kk] += na
                ts[c, kk] = body.sum() / na / NKEEP
            if a.save_every and seen[1:].all(axis=1).sum() - last_save >= a.save_every:
                last_save = int(seen[1:].all(axis=1).sum())
                np.save(out_stem + "_spec.npy", (acc / np.repeat(np.maximum(nfr, 1), NKEEP)).astype(np.float32))
                log(f"  途中: {last_save} / {N} チャンク（{time.time() - t_run:.0f} s）・違い {nbad}・捨て {ctr.rd(0x28)}・溢れ {ctw.rd(0x28)}・DROP {ring.g.rd(Ring.R_DROP)}")
            if time.time() - t_probe >= a.probe_secs:
                t_probe = time.time()
                probe(cs, seg, True)
            time.sleep(0.01)
    finally:
        stop(ctw, ctr)
        w = f5.watch(ctw, ctr, ft, ring)
        ring.close()
    t_el = time.time() - t_run
    done = int(seen[1:].all(axis=1).sum())
    info = dict(t_start=t_run, seconds=t_el, chunks_done=done, bad=nbad, bad_ex=bad_ex, dup=ndup, nact_ng=nact_ng, other=other,
                watch=w, prof=ring.prof, nfr=nfr.tolist())
    return acc, nfr, ts[1:], info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bit", default="proj028.bit")
    ap.add_argument("--zone", type=int, default=1)
    ap.add_argument("--segs", default="a", help="区間の名前をカンマで（例 on,off,on）")
    ap.add_argument("--chunks", type=int, default=40, help="区間ごとに足すチャンクの数（チャンク 0 を除く）")
    ap.add_argument("--wait", default="file", help="区間の間: file（<out>.go<i> を待つ）か秒数")
    ap.add_argument("--shift", type=int, default=7)
    ap.add_argument("--gains-from")
    ap.add_argument("--gain-nacc", type=int, default=1 << 20)
    ap.add_argument("--ring-mib", type=int, default=64)
    ap.add_argument("--save-every", type=int, default=0, help="長い区間で途中を保存するチャンクの間隔（0 で保存しない）")
    ap.add_argument("--probe-secs", type=float, default=1.0, help="温度と荒い段の POW を記録する間隔（RUN の中でも外でも）")
    ap.add_argument("--out", default="f6_seg")
    a = ap.parse_args()
    segs = a.segs.split(",")

    from pynq import Overlay
    import xrfdc                                  # Overlay() より前
    f5.setup_clocks("stock", 10.0)
    ol = Overlay(a.bit)
    log(f"Overlay: {a.bit}（この 1 回だけ読む）")
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない")
        return 1
    f5.check_tile(ol.rfdc, a.zone)
    meta = dict(bit=a.bit, zone=a.zone, shift=a.shift, chunks=a.chunks, segs=segs, df_hz=f5.DF)
    meta["clk_mon"] = f5.check_clk_mon(Regs(ol, "clk_mon_0"))
    cs, ctw, ctr, ft = (Regs(ol, n) for n in ("coarse_stage_0", "ct_wr_0", "ct_rd_0", "fine_top_0"))
    for g, want in ((cs, f5.ID_CS), (ctw, f5.ID_CTW), (ctr, f5.ID_CTR), (ft, f5.ID_FT)):
        if g.rd(0) != want:
            log(f"ERROR: {g.name} の ID 0x{g.rd(0):08x}（0x{want:08x} を期待）")
            return 1
    txt, gbs, adcs = f5.gb_text(ft)
    log(txt)
    if not (gbs >> 31 and adcs >> 31):
        log("ERROR: ギアボックスが開始していないか、RFDC の valid を見ていない")
        return 1

    if a.gains_from:
        g = np.array(json.load(open(a.gains_from))["gain"], dtype=np.int64)
        cs.wr(0x004, a.gain_nacc)
        for k in range(NCH):
            cs.wr(0x100 + 4 * k, int(g[k]))
        p, clip = f5.coarse_pow(cs, a.gain_nacc)
        sig = np.sqrt(p / a.gain_nacc / 2.0)
        log(f"利得: {a.gains_from} から g {int(g.min())}〜{int(g.max())} → σ {sig.min():.2f}〜{sig.max():.2f} LSB・飽和 {int(clip.sum())}")
    else:
        g, sig, clip = f5.gain_cal(cs, a.gain_nacc, 256)
    meta.update(gain=g.tolist(), sigma0=sig.tolist())

    meta["seg"] = []
    ok_all = True
    for i, name in enumerate(segs):
        if i > 0:
            if a.wait == "file":
                go = f"{a.out}.go{i}"
                log(f"待つ: 区間 {i}（{name}）は {go} ができたら始める")
                while not os.path.exists(go):
                    probe(cs, i - 0.5, False)
                    time.sleep(max(0.0, a.probe_secs - 0.05))
            else:
                log(f"待つ: {a.wait} s")
                t_w = time.time()
                while time.time() - t_w < float(a.wait):
                    probe(cs, i - 0.5, False)
                    time.sleep(max(0.0, a.probe_secs - 0.05))
        p, clip = f5.coarse_pow(cs, a.gain_nacc)
        sig = np.sqrt(p / a.gain_nacc / 2.0)
        log(f"区間 {i}（{name}）: 始め {time.strftime('%H:%M:%S')}・σ {sig.min():.2f}〜{sig.max():.2f} LSB・飽和 {int(clip.sum())}")
        stem = f"{a.out}_s{i}"
        acc, nfr, ts, info = segment(ol, cs, ctw, ctr, ft, a, stem, i)
        spec = (acc / np.repeat(np.maximum(nfr, 1), NKEEP)).astype(np.float32)
        np.save(stem + "_spec.npy", spec)
        w, r = info["watch"], info["watch"]["ring"]
        ok = (info["chunks_done"] == a.chunks and info["bad"] == 0 and info["dup"] == 0 and info["nact_ng"] == 0
              and w["fine"]["flags"] & ~(1 << 7) == 0 and w["ct_wr"]["ovf"] == 0 and w["ct_wr"]["flags"] == 0
              and w["ct_rd"]["drop"] == 0 and w["ct_rd"]["flags"] == 0 and r["drop"] == 0 and not r["err"])
        ok_all &= ok
        band = ts[:, 2:31].mean(1)
        q = 100 * (band / band.mean() - 1)
        log(f"区間 {i}（{name}）: {info['chunks_done']} / {a.chunks} チャンク（{info['seconds']:.1f} s）・違い {info['bad']}・重なり {info['dup']}・"
            f"160 でないフレーム数 {info['nact_ng']} / ct_wr 溢れ {w['ct_wr']['ovf']}・ct_rd 捨て {w['ct_rd']['drop']}・"
            f"fine FLAGS 0x{w['fine']['flags']:03x}・リング DROP {r['drop']}・PEAK {r['peak']} → {'通過' if ok else '不合格'}")
        log(f"  ch 2〜30 の全電力: チャンクの間の σ {q.std():.3f} %・幅 {q.min():+.3f}〜{q.max():+.3f} %")
        info.update(name=name, ok=ok, sigma=sig.tolist(), clip=clip.tolist(), ts=ts.tolist())
        meta["seg"].append(info)
        meta["probe"] = dict(cols=["t", "seg", "run", "t_pl", "t_ps", "pow"], rows=PROBE)
        pr = [x for x in PROBE if x[1] == i]
        if pr:
            log(f"  PL の温度 {pr[0][3]:.1f} → {pr[-1][3]:.1f} °C・荒い段の POW（ch 2〜30）{100 * (pr[-1][5] / pr[0][5] - 1):+.3f} %（区間の頭から終わり）")
        json.dump(meta, open(a.out + "_meta.json", "w"), default=float)
    if len(segs) > 1:
        b = [np.array(s["ts"])[:, 2:31].mean() for s in meta["seg"]]
        log("区間の ch 2〜30 の全電力（区間 0 に対して）: " + "・".join(f"{n} {10 * np.log10(x / b[0]):+.3f} dB" for n, x in zip(segs, b)))
    log(f"保存: {a.out}_s*_spec.npy・{a.out}_meta.json / 結果: {'通過' if ok_all else '不合格'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
