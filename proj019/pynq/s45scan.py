#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj019 — specrecv の照合が「失敗」した .s45 の中を見る（どこで・何が・どれだけ）。numpy と s45proto.py だけ。

    python3 s45scan.py cwnight1.s45                  # CRC も確かめる（全部読む。specrecv --file と同じくらいの時間）
    python3 s45scan.py cwnight1.s45 --no-crc         # 頭だけ読んで中身は飛ばす（速い）
    python3 s45scan.py cwnight1.s45 --bin 600        # 時間の区切り（秒、既定 600 = 10 分）

出すもの:
  1. EVENT の全部（START・STOP・DROP・SKIP …）
  2. (ADC, 窓) ごと: 記録の数・DUMP_K の始めと終わり・抜けた K の数（= 読み落とし。PL の面が 2 つなので、読み出しが 1 周遅れると上書きされる）・
     同じ K がもう一度来た数（重複）・K が戻った数・跳びの大きさの分布・DUMP_T と UTC の始めと終わり・tint（N_ACC·L）
  3. 抜けの時間分布（--bin 秒ごと、8 窓の合計）
  4. CRC が合わない記録: seq・種類・ファイルの中の位置・前後の seq
  5. H_NOTIME（時刻を答えられない）の記録: 数・最初と最後の DUMP_K・直前の時刻のある記録の UTC
"""
import argparse
import collections
import json
import sys

import numpy as np

import s45proto as P

BEAT = 1 / 256e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--no-crc", action="store_true")
    ap.add_argument("--bin", type=float, default=600.0)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()
    f = open(a.path, "rb", buffering=1 << 22)
    hs, ss = P.HDR.size, P.SPEC_H.size
    win = {}                      # key → dict
    events, crcbad, notime = [], [], collections.Counter()
    notime_first, last_time_ok = {}, {}
    tp = collections.Counter()
    tp_notime = 0
    t0_beat = None
    miss_bins = collections.Counter()
    prev_seq, pos, nrec = None, 0, 0
    while True:
        h = f.read(hs)
        if len(h) < hs:
            break
        rtype, plen, crc, seq = P.parse_header(h)
        nrec += 1
        if a.no_crc and rtype == P.T_SPEC:
            sh = f.read(ss)
            f.seek(plen - ss, 1)
            payload, bad = sh, False
        else:
            payload = f.read(plen)
            bad = P.crc32(payload) != crc
        if bad:
            crcbad.append(dict(seq=seq, type=P.T_NAMES.get(rtype, rtype), plen=plen, offset=pos, prev_seq=prev_seq))
        pos += hs + plen
        if seq:
            prev_seq = seq
        if bad:
            continue
        if rtype == P.T_SPEC:
            (adc, w, ns, shift, fmt, g, _, cfg, k, nacc, sat, flags, health, dump_t, utc_ns, if_mhz) = P.SPEC_H.unpack_from(payload)
            key = f"{'ABCD'[adc]}{w}"
            L = 4096 << (ns - 1)
            d = win.get(key)
            if d is None:
                d = win[key] = dict(n=0, k0=k, k1=k, miss=0, dup=0, back=0, jumps=collections.Counter(), t0=dump_t, t1=dump_t,
                                    u0=utc_ns, u1=utc_ns, tint_ms=nacc * L * BEAT * 1e3, ns=ns, shift=shift, if_mhz=if_mhz, sat=0)
            else:
                dk = k - d["k1"]
                if dk == 0:
                    d["dup"] += 1
                elif dk < 0:
                    d["back"] += 1
                elif dk > 1:
                    d["miss"] += dk - 1
                    d["jumps"][min(dk - 1, 20)] += 1
                    if t0_beat is not None:
                        miss_bins[int((dump_t - t0_beat) * BEAT // a.bin)] += dk - 1
                d["k1"], d["t1"] = max(k, d["k1"]), dump_t
                if utc_ns:
                    d["u1"] = utc_ns
            if t0_beat is None:
                t0_beat = dump_t
            d["n"] += 1
            d["sat"] += sat
            if health & P.H_NOTIME:
                notime[key] += 1
                notime_first.setdefault(key, dict(k=k, last_utc_ok=last_time_ok.get(key)))
            elif utc_ns:
                last_time_ok[key] = utc_ns
        elif rtype == P.T_TP:
            adc, _, _, n = P.TP_H.unpack_from(payload)
            tp["ABCD"[adc]] += n
            if not a.no_crc:
                e = np.frombuffer(payload, P.TP_E, n, P.TP_H.size)
                tp_notime += int(np.count_nonzero(e["flags"] & P.TPF_NOTIME))
        elif rtype == P.T_EVENT:
            ev = P.decode(rtype, payload)
            ev["_seq"] = seq
            events.append(ev)
    print(f"記録 {nrec}・{pos / 2**30:.1f} GiB・最後の seq {prev_seq}")
    print("\n1. EVENT")
    for ev in events:
        s = json.dumps({k: v for k, v in ev.items() if k not in ("tp_cal",)}, ensure_ascii=False)
        print(f"  seq {ev['_seq']}: {s[:400]}")
    if not any(ev.get("ev") == "STOP" for ev in events):
        print("  （STOP の EVENT が無い: 記録は取得の途中で切れている）")
    print("\n2. 窓ごと")
    print("  窓   tint[ms]  記録      K の始め〜終わり       抜け（率）          重複  戻り  時間 [h]  跳び（抜けた数: 回）")
    for key in sorted(win):
        d = win[key]
        span = d["k1"] - d["k0"] + 1
        hrs = (d["t1"] - d["t0"]) * BEAT / 3600
        jj = " ".join(f"{j}:{c}" for j, c in sorted(d["jumps"].items())[:8])
        print(f"  {key}  {d['tint_ms']:8.2f}  {d['n']:8d}  {d['k0']:9d}〜{d['k1']:9d}  {d['miss']:8d}（{d['miss'] / max(span, 1) * 100:5.2f} %）"
              f"  {d['dup']:5d} {d['back']:5d}  {hrs:7.3f}  {jj}")
    print(f"\n3. 抜けの時間分布（{a.bin:.0f} 秒ごと、8 窓の合計。DUMP_T の最初から）")
    for b in sorted(miss_bins):
        print(f"  {b * a.bin / 3600:6.2f} h〜: {miss_bins[b]}")
    if not miss_bins:
        print("  抜けなし")
    print(f"\n4. CRC が合わない記録: {len(crcbad)}" + ("（--no-crc なので SPEC は見ていない）" if a.no_crc else ""))
    for c in crcbad:
        print(f"  seq {c['seq']}・{c['type']}・{c['plen']} バイト・位置 {c['offset']}（{c['offset'] / 2**30:.2f} GiB）・直前の seq {c['prev_seq']}")
    print(f"\n5. H_NOTIME（時刻を答えられない）: SPEC {sum(notime.values())} 個" + (f"・TP の区切り {tp_notime}" if not a.no_crc else ""))
    for key in sorted(notime):
        nf = notime_first[key]
        print(f"  {key}: {notime[key]} 個・最初の DUMP_K {nf['k']}・直前の時刻のある記録の UTC {nf['last_utc_ok']}")
    print(f"\nTP の区切り: " + " / ".join(f"{k} {v}" for k, v in sorted(tp.items())))
    if a.json:
        out = dict(win={k: {kk: (dict(vv) if isinstance(vv, collections.Counter) else vv) for kk, vv in v.items()} for k, v in win.items()},
                   miss_bins={str(k): v for k, v in miss_bins.items()}, crc_bad=crcbad, notime=dict(notime), events=len(events))
        json.dump(out, open(a.json, "w"), ensure_ascii=False, indent=1, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
