#!/usr/bin/env python3
"""proj032 K-2 — リングに書かれたレコード（dsink → ring128）を、閉じたダンプの流れ（wsb_dmp.log、機関の d_*）と照らす。

  python3 sim/check_ring.py DIR

照らすもの:
  - レコードの並び: PAD（type 0）は端まで飛ばす。それ以外は頭の magic・rec_ver 2・type 5・core 0・fmt 1・log2 NFFT 12・本体 16384 バイト、
    尾の magic "S45E"・SEQ（頭の w1 と同じ）・CRC（zlib.crc32(頭 ＋ 本体)）
  - SEQ は 0 から 1 ずつ（受け手で捨てたダンプは SEQ を取らない）
  - 本体 = そのダンプ（窓 s・DUMP_K）の 4096 ch の u64 を f32 に丸めたもの（u < 2^53: float32(float64(u))）、ch の順
  - 頭の NS・SHIFT・G・DUMP_N が wsb_run.log の窓の設定と合う
  - R-1: DUMP_F0 = (g0a ＋ K·ng)·2^(G_L2 − 12 − NS)（P-4: g0a は T の原点から数えた格子。古い記録で G0A が無ければ g0）、DUMP_T = そのフレームの頭の標本が入口に入ったビート（wsb_t.log）± 揺れ（≦ 16 ビート）
  - P-4: K_F = DUMP_T − L·DUMP_F0（L = 2^(12 + NS)）が窓ごとに一定。WRST の明けを格子に揃える tb（wsb_run.log に AL 1）では 0 ≦ K_F < L（フレームの頭が T の格子に揃う）
  - 流れの中の揃ったダンプは全部、レコードになっているか捨てた数（EXT_CNT）に入っている: 揃ったダンプ − レコード = EXT_CNT
"""
import os
import re
import struct
import sys
import zlib

import numpy as np


def main(d):
    run = open(os.path.join(d, "wsb_run.log")).read().split("\n")
    g_l2 = int(run[0].split()[3])
    h0 = run[0].split()
    g0 = int(h0[1])
    g0a = int(h0[9]) if len(h0) > 9 else g0
    al = len(h0) > 11 and h0[10] == "AL" and h0[11] == "1"
    kf = {}
    tf = {}
    for l in open(os.path.join(d, "wsb_t.log")):
        a, b, c = l.split()
        tf[(int(a), int(b))] = int(c)
    tmax = 0
    cfg = {}
    for l in run[1:]:
        f = l.split()
        if f and f[0] == "w":
            cfg[int(f[1])] = dict(ns=int(f[3]), sh=int(f[5]), g=int(f[7]))
    # 流れのダンプ: (w, k) → {ch: u64}
    dm = {}
    for l in open(os.path.join(d, "wsb_dmp.log")):
        e, w, k, ch, v = l.split()
        dm.setdefault((int(w), int(k)), {})[int(ch)] = int(v)
    full = {key: v for key, v in dm.items() if len(v) == 4096}
    sim = open(os.path.join(d, "sim.log")).read()
    m = re.search(r"ring: REC_CNT (\d+) DROP_CNT (\d+) EXT_CNT (\d+) PEAK (\d+) sflags (\w+)", sim)
    rec_cnt, drop_cnt, ext_cnt, peak, sflags = int(m[1]), int(m[2]), int(m[3]), int(m[4]), m[5]
    # PAD の後ろ（リングの端まで）は書かれない場所なので x のまま。0 に読み替える（PAD で飛ばすので照らさない）
    raw = bytes.fromhex("".join(l.strip() for l in open(os.path.join(d, "wsb_ring.log"))).replace("x", "0"))
    errs = []
    pos, seq, recs, pads, late, nt = 0, 0, {}, 0, 0, 0
    while pos < len(raw):
        h = raw[pos:pos + 64]
        w = struct.unpack("<8Q", h)
        magic, ver, typ = w[0] & 0xFFFFFFFF, (w[0] >> 32) & 0xFF, (w[0] >> 40) & 0xFF
        if magic != 0x52353453:
            errs.append("位置 %d: magic %08x" % (pos, magic)); break
        if typ == 0:
            pads += 1
            pos += w[7] & 0xFFFFFFFF
            continue
        core, s = (w[0] >> 48) & 0xFF, (w[0] >> 56) & 0xFF
        sq, dk = w[1] & 0xFFFFFFFF, w[1] >> 32
        l2n, ns, sh, g, fmt, src = [(w[4] >> (8 * i)) & 0xFF for i in range(6)]
        dn = w[5] & 0xFFFFFFFF
        P = w[7] & 0xFFFFFFFF
        body = raw[pos + 64:pos + 64 + P]
        tail = struct.unpack("<8Q", raw[pos + 64 + P:pos + 128 + P])
        if (ver, typ, core, fmt, l2n, src, P) != (2, 5, 0, 1, 12, 0, 16384):
            errs.append("SEQ %d: 頭の欄 ver %d type %d core %d fmt %d log2N %d src %d P %d" % (sq, ver, typ, core, fmt, l2n, src, P))
        if tail[0] & 0xFFFFFFFF != 0x45353453 or tail[0] >> 32 != sq:
            errs.append("SEQ %d: 尾 %016x" % (sq, tail[0]))
        if (tail[1] & 0xFFFFFFFF) != zlib.crc32(h + body):
            errs.append("SEQ %d: CRC %08x（期待 %08x）" % (sq, tail[1] & 0xFFFFFFFF, zlib.crc32(h + body)))
        if sq != seq:
            errs.append("SEQ %d（期待 %d）" % (sq, seq))
        seq = sq + 1
        c = cfg[s]
        if (ns, sh, g, dn) != (c["ns"], c["sh"], c["g"], 1 << (g_l2 - 12 - c["ns"])):
            errs.append("SEQ %d 窓 %d: NS %d SHIFT %d G %d DUMP_N %d" % (sq, s, ns, sh, g, dn))
        f0 = (g0 + dk) << (g_l2 - 12 - c["ns"])           # ng = 1（tb）。rst から数えたフレーム（wsb_t.log の番号）
        f0a = (g0a + dk) << (g_l2 - 12 - c["ns"])
        if w[2] != f0a:
            errs.append("SEQ %d 窓 %d K %d: DUMP_F0 %d（期待 %d）" % (sq, s, dk, w[2], f0a))
        k_f = w[3] - (w[2] << (12 + c["ns"]))
        kf.setdefault(s, set()).add(k_f)
        if al and not 0 <= k_f < (1 << (12 + c["ns"])):
            errs.append("SEQ %d 窓 %d K %d: K_F %d が [0, L) の外" % (sq, s, dk, k_f))
        if (s, f0) in tf:
            dt = w[3] - tf[(s, f0)]
            tmax = max(tmax, abs(dt))
            if abs(dt) > 16:
                errs.append("SEQ %d 窓 %d K %d: DUMP_T が入口の時刻と %d ビート違う" % (sq, s, dk, dt))
        else:
            nt += 1
        got = np.frombuffer(body, dtype="<u4")
        ref = full.get((s, dk))
        if ref is None:
            late += 1                       # 流れの記録を閉じた後に揃ったダンプ（照らさない）
        else:
            u = np.array([ref[i] for i in range(4096)], dtype=np.uint64)
            exp = u.astype(np.float64).astype(np.float32).view(np.uint32)
            nb = int(np.count_nonzero(got != exp))
            if nb:
                errs.append("SEQ %d 窓 %d K %d: 本体の不一致 %d ch" % (sq, s, dk, nb))
        recs[(s, dk)] = sq
        pos += 128 + P
    miss = [key for key in full if key not in recs]
    for s_ in sorted(kf):
        if len(kf[s_]) != 1:
            errs.append("窓 %d: K_F が一定でない %s" % (s_, sorted(kf[s_])[:4]))
    print("K_F（窓ごと）: " + " ".join("%d:%s" % (s_, ",".join(str(v) for v in sorted(kf[s_]))) for s_ in sorted(kf)))
    print("照らさないレコード（流れの記録を閉じた後）%d・DUMP_T を照らせないレコード %d・DUMP_T と入口の時刻の差の最大 %d ビート" % (late, nt, tmax))
    print("レコード %d（PAD %d）・REC_CNT %d・揃ったダンプ %d・レコードにないダンプ %d・EXT_CNT %d・DROP_CNT %d・PEAK %d B・sflags %s"
          % (len(recs), pads, rec_cnt, len(full), len(miss), ext_cnt, drop_cnt, peak, sflags))
    if len(recs) != rec_cnt:
        errs.append("レコードの数 %d ≠ REC_CNT %d" % (len(recs), rec_cnt))
    # 捨てたダンプは、流れの記録を閉じた後のものもありうる（EXT_CNT はその分も数える）
    if len(miss) > ext_cnt or (ext_cnt == 0 and miss):
        errs.append("レコードにないダンプ %d ≠ EXT_CNT %d: %s" % (len(miss), ext_cnt, miss[:6]))
    if drop_cnt != ext_cnt:
        errs.append("DROP_CNT %d ≠ EXT_CNT %d（リングでも捨てた）" % (drop_cnt, ext_cnt))
    if int(sflags, 16) & 0xB:
        errs.append("sflags %s" % sflags)
    for e in errs[:10]:
        print("  " + e)
    print("結果: " + ("全部通過" if not errs else "不合格 %d 件" % len(errs)))
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
