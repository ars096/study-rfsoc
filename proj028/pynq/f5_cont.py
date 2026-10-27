#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj028 F-6c — RUN を止めずに回し続け、チャンクの全電力の段で「状態」（ON / OFF など）を見分けて状態ごとに足し込む（ボードの上で）

  sudo -E $(which python3) f5_cont.py --chunks 1200 --gains-from f5g_on2_meta.json --out f6c_onoff   # ≒ 5.7 分。その間に雑音源を切り替える
  sudo -E $(which python3) f5_cont.py --chunks 12600 --save-every 600 --out f6_long                  # ≒ 1 時間、切り替えなし

- RUN を止めると PL が冷えて全電力が ≒ 0.2 % 戻る（F-6b）。止めずに、入力の切り替えをチャンクの電力で見つける
- チャンク c（1 以降、160 フレーム）が揃ったら、ch 2〜30 の平均の電力 p_c を出す。p_c を 1 つ後の p_{c+1} が揃ってから決める:
    前の残したチャンクと --step-db 以上違えば、新しい状態の区間を始める
    前後どちらとも --mix-db 以内に無いチャンクは、途中で切り替わった（混ざった）として捨てる
    新しい区間の始めの --settle チャンクも捨てる（雑音源の立ち上がり）
- 区間ごとに: 足したスペクトル（<out>_r<i>_spec.npy、÷ フレームの数）・チャンクの番号の範囲・全電力の列
- 見張り: ≒ 1 s ごとに PL・PS の温度と荒い段の POW（f5_seg と同じ）。--save-every チャンクごとに meta と区間の途中を保存する
"""
import argparse
import json
import sys
import time

import numpy as np

import f5
import f5_seg
from f5 import Regs, Ring, log, NCH, NKEEP, NTOT, CHUNK_BLK, BLK_RATE


class Runs:
    """状態の区間の足し込み。チャンクは decide() に 1 つ遅れで渡す"""

    def __init__(self, a):
        self.a = a
        self.runs = []                  # dict(first, last, n, acc, nfr, ts, p)
        self.dropped = []               # (c, 理由)
        self.prev = None                # 決めを待つチャンク (c, p, spec, nfr, ts)
        self.last_kept_p = None
        self.settle_left = 0

    def push(self, item):
        if self.prev is not None:
            self.decide(self.prev, item[1])
        self.prev = item

    def flush(self):
        if self.prev is not None:
            self.decide(self.prev, None)
            self.prev = None

    def decide(self, item, p_next):
        c, p, spec, nfr, ts = item
        db = lambda x, y: abs(10 * np.log10(x / y))       # noqa: E731
        near_prev = self.last_kept_p is not None and db(p, self.last_kept_p) <= self.a.mix_db
        near_next = p_next is not None and db(p, p_next) <= self.a.mix_db
        if not (near_prev or near_next):
            if self.last_kept_p is not None:           # 最初のチャンクは前が無いので、後ろとだけ比べる（後ろが違えば捨てる）
                self.dropped.append((c, "混ざり"))
                return
            if p_next is not None:
                self.dropped.append((c, "混ざり"))
                return
        if self.last_kept_p is None or db(p, self.last_kept_p) >= self.a.step_db:
            self.runs.append(dict(first=c, last=c, n=0, acc=np.zeros(NTOT), nfr=np.zeros(NCH, np.int64), ts=[], p=[]))
            self.settle_left = self.a.settle if self.last_kept_p is not None else 0
            log(f"  状態の区間 {len(self.runs) - 1} を始めた: チャンク {c}・電力 {p:.6g}"
                + (f"（前の区間に対して {10 * np.log10(p / self.last_kept_p):+.2f} dB）" if self.last_kept_p else ""))
        self.last_kept_p = p
        if self.settle_left > 0:
            self.settle_left -= 1
            self.dropped.append((c, "立ち上がり"))
            return
        r = self.runs[-1]
        r["acc"] += spec
        r["nfr"] += nfr
        r["n"] += 1
        r["last"] = c
        r["ts"].append(ts.tolist())
        r["p"].append(p)

    def save(self, out):
        for i, r in enumerate(self.runs):
            if r["n"]:
                np.save(f"{out}_r{i}_spec.npy", (r["acc"] / np.repeat(np.maximum(r["nfr"], 1), NKEEP)).astype(np.float32))

    def summary(self):
        return [dict(first=r["first"], last=r["last"], n=r["n"], nfr=r["nfr"].tolist(), ts=r["ts"], p=r["p"]) for r in self.runs]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bit", default="proj028.bit")
    ap.add_argument("--zone", type=int, default=1)
    ap.add_argument("--chunks", type=int, default=1200, help="回すチャンクの数（チャンク 0 を除く）")
    ap.add_argument("--shift", type=int, default=7)
    ap.add_argument("--gains-from")
    ap.add_argument("--gain-nacc", type=int, default=1 << 20)
    ap.add_argument("--ring-mib", type=int, default=64)
    ap.add_argument("--step-db", type=float, default=3.0, help="これ以上変われば新しい状態の区間")
    ap.add_argument("--mix-db", type=float, default=0.3, help="前後どちらともこれより離れたチャンクは混ざりとして捨てる")
    ap.add_argument("--settle", type=int, default=2, help="新しい区間の始めに捨てるチャンクの数")
    ap.add_argument("--save-every", type=int, default=200)
    ap.add_argument("--probe-secs", type=float, default=1.0)
    ap.add_argument("--out", default="f6c")
    a = ap.parse_args()

    from pynq import Overlay
    import xrfdc                                  # Overlay() より前
    f5.setup_clocks("stock", 10.0)
    ol = Overlay(a.bit)
    log(f"Overlay: {a.bit}")
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない")
        return 1
    f5.check_tile(ol.rfdc, a.zone)
    meta = dict(bit=a.bit, zone=a.zone, shift=a.shift, chunks=a.chunks, df_hz=f5.DF, step_db=a.step_db, mix_db=a.mix_db, settle=a.settle)
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
        log(f"利得: {a.gains_from} から g {int(g.min())}〜{int(g.max())}")
    else:
        g, _, _ = f5.gain_cal(cs, a.gain_nacc, 256)
    meta["gain"] = g.tolist()
    cs.wr(0x004, f5_seg.PROBE_NACC)

    f5_seg.configure(ctw, ctr, ft, a.shift)
    ring = Ring(Regs(ol, "s45_ring_0"), a.ring_mib << 20)
    ring.enable(True)
    ctr.wr(0x04, 1)
    ctw.wr(0x04, 1)
    t_run = time.time()
    N = a.chunks
    log(f"RUN {time.strftime('%H:%M:%S')}（{N} チャンク ≒ {N * CHUNK_BLK / BLK_RATE / 60:.1f} 分）")
    pend = {}                                      # c → [spec(float64), nfr, ts, 揃った ch の数]
    done_c = set()
    runs = Runs(a)
    nbad, ndup, nact_ng, other = 0, 0, 0, 0
    bad_ex = []
    n_done, last_save, t_probe = 0, 0, 0.0
    tmo = (N + 3) * CHUNK_BLK / BLK_RATE + 10
    try:
        while n_done < N and time.time() - t_run < tmo:
            for kk, c, na, sk, body, crc_ok, tail_ok, hdr_ok in ring.read():
                if not (crc_ok and tail_ok and hdr_ok):
                    nbad += 1
                    if len(bad_ex) < 20:
                        bad_ex.append(dict(k=int(kk), c=int(c), crc=crc_ok, tail=tail_ok, hdr=hdr_ok))
                    continue
                if c == 0 or c > N or kk >= NCH:
                    other += c != 0
                    continue
                if c in done_c:
                    ndup += 1
                    continue
                e = pend.setdefault(c, [np.zeros(NTOT), np.zeros(NCH, np.int64), np.zeros(NCH), np.zeros(NCH, bool)])
                if e[3][kk]:
                    ndup += 1
                    continue
                if na != 160:
                    nact_ng += 1
                e[0][kk * NKEEP:(kk + 1) * NKEEP] = body
                e[1][kk] = na
                e[2][kk] = body.sum() / na / NKEEP
                e[3][kk] = True
                # 揃ったチャンクを番号の順に渡す（ct_rd は ch の順に読むので、c は順に揃う）
                while pend and min(pend) in pend and pend[min(pend)][3].all():
                    cc = min(pend)
                    sp, nf, ts, _ = pend.pop(cc)
                    done_c.add(cc)
                    n_done += 1
                    runs.push((cc, float(ts[2:31].mean()), sp, nf, ts))
            if n_done - last_save >= a.save_every:
                last_save = n_done
                runs.save(a.out)
                meta.update(runs=runs.summary(), dropped=runs.dropped, probe=dict(cols=["t", "seg", "run", "t_pl", "t_ps", "pow"], rows=f5_seg.PROBE))
                json.dump(meta, open(a.out + "_meta.json", "w"), default=float)
                log(f"  途中: {n_done} / {N}（{time.time() - t_run:.0f} s）・区間 {len(runs.runs)}・捨てた {len(runs.dropped)}・違い {nbad}・"
                    f"捨て {ctr.rd(0x28)}・溢れ {ctw.rd(0x28)}・DROP {ring.g.rd(Ring.R_DROP)}・PL {f5_seg.temp(20):.1f} °C")
            if time.time() - t_probe >= a.probe_secs:
                t_probe = time.time()
                f5_seg.probe(cs, 0, True)
            time.sleep(0.01)
    finally:
        f5_seg.stop(ctw, ctr)
        w = f5.watch(ctw, ctr, ft, ring)
        ring.close()
    runs.flush()
    t_el = time.time() - t_run
    runs.save(a.out)
    meta.update(seconds=t_el, chunks_done=n_done, bad=nbad, bad_ex=bad_ex, dup=ndup, nact_ng=nact_ng, other=other, pending=sorted(pend),
                watch=w, prof=ring.prof, runs=runs.summary(), dropped=runs.dropped,
                probe=dict(cols=["t", "seg", "run", "t_pl", "t_ps", "pow"], rows=f5_seg.PROBE))
    json.dump(meta, open(a.out + "_meta.json", "w"), default=float)
    r = w["ring"]
    ok = (n_done == N and nbad == 0 and ndup == 0 and nact_ng == 0 and w["fine"]["flags"] & ~(1 << 7) == 0
          and w["ct_wr"]["ovf"] == 0 and w["ct_wr"]["flags"] == 0 and w["ct_rd"]["drop"] == 0 and w["ct_rd"]["flags"] == 0
          and r["drop"] == 0 and not r["err"])
    log(f"{n_done} / {N} チャンク（{t_el:.0f} s）・違い {nbad}・重なり {ndup}・160 でない {nact_ng} / ct_wr 溢れ {w['ct_wr']['ovf']}・"
        f"ct_rd 捨て {w['ct_rd']['drop']}・fine FLAGS 0x{w['fine']['flags']:03x}・リング DROP {r['drop']}・PEAK {r['peak']}")
    for i, rr in enumerate(runs.runs):
        p = np.array(rr["p"]) if rr["p"] else np.array([np.nan])
        log(f"  区間 {i}: チャンク {rr['first']}〜{rr['last']}・足した {rr['n']}・電力 {np.mean(p):.6g}"
            + (f"（区間 0 に対して {10 * np.log10(np.mean(p) / np.mean(runs.runs[0]['p'])):+.3f} dB）" if i and runs.runs[0]["p"] else ""))
    log(f"  捨てたチャンク: {runs.dropped}")
    log(f"保存: {a.out}_r*_spec.npy・{a.out}_meta.json / 結果: {'通過' if ok else '不合格'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
