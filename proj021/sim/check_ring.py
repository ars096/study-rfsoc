#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""check_ring.py — リング（s45_ring）の sim の出力を照合する（proj021 手順 2-2a）

  python3 sim/check_ring.py u <dir> [--flip] [--noread]     # sim-ringu（tb_ring_u）の ring_u.txt と log
  python3 sim/check_ring.py core <dir> [--flip]             # sim-ring（tb_ring）の ring.txt と peek.txt と log

共通の照合（レコードごと）:
  - 頭の magic "S45R"・rec_ver 1・type 1、尾の magic "S45E"・尾の SEQ = 頭の SEQ、尾の w2..w7 = 0
  - CRC-32（zlib.crc32、頭 64 バイト ＋ 本体）= 尾の w1 の下位 32 bit（--flip: 照合する側で 1 bit 反転 → 全部 NG になるべき）
  - PAD（type 0）は w7 = 端までのバイト数（位置 mod SIZE ＋ w7 = SIZE）
  - 流れ（core, s）ごとに SEQ が増える順。飛びの数を数える
u: 本体・頭を tb の式で作り直して比べる。DROP_CNT = Σ(NREC − 受けた数) ＋ rec_drop の数（入口 2 の seq % 5 == 4）、
   REC_CNT = 受けた数、捨てるべき（入口 1 の seq % 7 == 3）が来ていない
core: 本体を peek.txt（tb が凍ったバンクを直に写したもの）と、頭を peek の DUMP_* と比べる
"""
import sys, zlib, re

M64 = (1 << 64) - 1


def pw(i, sq, j):
    a = ((sq & 0xFFFFFFFF) << 32) | ((i & 0xFF) << 24) | (j & 0xFFFFFF)
    return (a ^ ((0x9E3779B97F4A7C15 * (j + 1)) & M64) ^ ((i & 0xFF) << 56)) & M64


def hw(i, sq, n):
    return (((sq ^ 0xA5A50000) & 0xFFFFFFFF) << 32) | ((i & 0xFF) << 16) | (n & 0xFF)


def load_recs(path):
    recs = []
    for ln in open(path):
        t = ln.split()
        if not t or t[0] != 'R':
            continue
        recs.append((int(t[1]), [int(x, 16) for x in t[2:]]))
    return recs


def log_vals(path, tag):
    v = {}
    for ln in open(path):
        m = re.match(r'^%s: (\w+) = (\S+)' % tag, ln)
        if m:
            v[m.group(1)] = m.group(2)
    return v


def check_common(recs, size, flip, ng):
    """レコードを (core, s, seq, words) に。PAD を確かめる"""
    out = []
    for pos, w in recs:
        w0 = w[0]
        if (w0 & 0xFFFFFFFF) != 0x52353453:
            ng.append('magic が違う @%d: %016x' % (pos, w0)); continue
        ver, ty, core, s = (w0 >> 32) & 0xFF, (w0 >> 40) & 0xFF, (w0 >> 48) & 0xFF, (w0 >> 56) & 0xFF
        if ver != 1:
            ng.append('rec_ver %d @%d' % (ver, pos))
        if ty == 0:
            e = w[7] & 0xFFFFFFFF
            if (pos % size) + e != size:
                ng.append('PAD の長さ %d が端まで（%d）と違う @%d' % (e, size - pos % size, pos))
            continue
        if ty not in (1, 2):
            ng.append('type %d @%d' % (ty, pos)); continue
        if ty == 2 and s != 0xFF:
            ng.append('TP のレコードの s が 0xFF でない @%d' % pos)
        p = w[7] & 0xFFFFFFFF
        nb = 8 + p // 8
        if len(w) != nb + 8:
            ng.append('長さ %d 語（要る %d）@%d' % (len(w), nb + 8, pos)); continue
        seq = w[1] & 0xFFFFFFFF
        t0, t1 = w[nb], w[nb + 1]
        if (t0 & 0xFFFFFFFF) != 0x45353453 or (t0 >> 32) != seq:
            ng.append('尾の magic・SEQ @%d: %016x（SEQ %d）' % (pos, t0, seq))
        if any(w[nb + 2:nb + 8]) or (t1 >> 32) != 0:
            ng.append('尾の予約が 0 でない @%d' % pos)
        crc = zlib.crc32(b''.join(x.to_bytes(8, 'little') for x in w[:nb]))
        if flip:
            crc ^= 1
        if crc != (t1 & 0xFFFFFFFF):
            ng.append('CRC が違う @%d（core %d s %d SEQ %d）: 計算 %08x / 尾 %08x' % (pos, core, s, seq, crc, t1 & 0xFFFFFFFF))
        out.append((core, s, seq, w[:nb]))
    return out


def gaps(recs):
    by = {}
    for core, s, seq, _ in recs:
        by.setdefault((core, s), []).append(seq)
    n = 0
    bad = []
    for k, v in by.items():
        for a, b in zip(v, v[1:]):
            if b <= a:
                bad.append('流れ %s の SEQ が増えない: %d → %d' % (k, a, b))
            n += b - a - 1
    return by, n, bad


def main_u(d, flip, noread, berr=False):
    lg = log_vals(d + '/log.txt', 'tb_ring_u')
    ng = []
    size = int(re.search(r'SIZE = (\d+)', open(d + '/log.txt').read()).group(1))
    nrec = int(re.search(r'NREC = (\d+)', open(d + '/log.txt').read()).group(1))
    recs = check_common(load_recs(d + '/ring_u.txt'), size, flip, ng)
    PB = {0: 32768, 1: 1024, 2: 512, 3: 4096}
    for core, s, seq, w in recs:
        if core != s or core not in PB:
            ng.append('core・s が違う %d %d' % (core, s)); continue
        if (w[1] >> 32) != 1000 + seq:
            ng.append('DUMP_K の語 @%d/%d' % (core, seq))
        for n in range(2, 7):
            if w[n] != hw(core, seq, n):
                ng.append('頭の w%d が違う（%d/%d）' % (n, core, seq))
        if (w[7] & 0xFFFFFFFF) != PB[core]:
            ng.append('w7 が違う')
        exp = [pw(core, seq, j) for j in range(PB[core] // 8)]
        if w[8:] != exp:
            bad = sum(1 for a, b in zip(w[8:], exp) if a != b)
            ng.append('本体が違う（入口 %d SEQ %d、%d 語）' % (core, seq, bad))
        if core == 1 and seq % 7 == 3:
            ng.append('捨てるべきレコードが来た（入口 1 SEQ %d）' % seq)
    by, ngap, bad = gaps(recs)
    ng += bad
    got = len(recs)
    ext = sum(1 for q in range(1, nrec + 1) if q % 5 == 4)
    miss = 4 * nrec - got
    drop, rcnt = int(lg['DROP_CNT']), int(lg['REC_CNT'])
    print('check_ring u: 受けたレコード %d（PAD を除く）/ 作った %d、SEQ の飛び %d、DROP_CNT %d、REC_CNT %d、PEAK %s、rec_drop %d'
          % (got, 4 * nrec, ngap, drop, rcnt, lg['PEAK'], ext))
    if rcnt != got:
        ng.append('REC_CNT %d ≠ 受けた数 %d' % (rcnt, got))
    if berr:
        # +BERR: 悪い BRESP の後は ERR が立ち、W が止まる（以後のレコードは全部捨てる）
        ctrl, es = int(lg['CTRL'], 16), int(lg['ERR_STAT'], 16)
        print('check_ring u: BERR の変種: CTRL %x ERR_STAT %08x' % (ctrl, es))
        if not (ctrl & 4):
            ng.append('悪い BRESP なのに ERR が立たない')
        if (es & 3) != 2:
            ng.append('ERR_STAT の BRESP が SLVERR でない')
        if got >= 4 * nrec - 2:
            ng.append('ERR の後も書き続けている')
        return ng
    if drop != miss + ext:
        ng.append('DROP_CNT %d ≠ 来なかった数 %d ＋ rec_drop %d' % (drop, miss, ext))
    # 来なかった数 = SEQ の飛び ＋ 流れの頭と尾の欠け
    tail = sum(nrec - max(v) + (min(v) - 1) for v in by.values()) + (4 - len(by)) * nrec
    if ngap + tail != miss:
        ng.append('SEQ の飛び %d ＋ 頭と尾の欠け %d ≠ 来なかった数 %d' % (ngap, tail, miss))
    if noread and drop <= ext + nrec // 7 + 1:
        ng.append('R を進めないのに空きなしの捨てが無い（DROP_CNT %d）。リングが大きすぎる' % drop)
    if not noread and miss != sum(1 for q in range(1, nrec + 1) if q % 7 == 3):
        ng.append('読んでいるのに捨てられた（来なかった %d）' % miss)
    if int(re.search(r'見張りの NG = (\d+)', open(d + '/log.txt').read()).group(1)) != 0:
        ng.append('tb の見張りに NG')
    return ng


def main_core(d, flip):
    lg = log_vals(d + '/log.txt', 'tb_ring')
    size = int(lg['SIZE'])
    ng = []
    recs = check_common(load_recs(d + '/ring.txt'), size, flip, ng)
    qq, hh, tt = {}, {}, {}
    for ln in open(d + '/peek.txt'):
        t = ln.split()
        if t and t[0] in ('Q', 'H'):
            k = (int(t[1]), int(t[2]), int(t[3]))
            (qq if t[0] == 'Q' else hh)[k] = [int(x, 16) for x in t[4:]]
        elif t and t[0] == 'T':
            v = int(t[3], 16)
            tt[(int(t[1]), int(t[2]))] = (v & ((1 << 64) - 1), v >> 64)    # 個 = 2 語（和・{FLAGS|フレーム数, F0}）
    # proj021 2-2b: TP のレコード（s = 0xFF）は AXI4-Lite の TP のリングの個（T 行）と比べる
    tps = [r for r in recs if r[1] == 0xFF]
    recs = [r for r in recs if r[1] != 0xFF]
    ntp_ok, ntp_items, tp_gap, prev = 0, 0, 0, None
    for core, s_, seq, w in tps:
        n = w[5] & 0xFFFFFFFF
        if prev is not None and seq != prev:
            tp_gap += 1
        prev = seq + n
        good = w[7] == ((n + 3) // 4) * 64
        for i in range(n):
            it = tt.get((core, seq + i))
            ntp_items += 1
            if it is None or [w[8 + 2 * i], w[9 + 2 * i]] != [it[0], it[1]]:
                good = False
        if n and tt.get((core, seq)) is not None and (w[2] & 0xFFFFFFFF) != (tt[(core, seq)][1] & 0xFFFFFFFF):
            good = False
        if any(w[8 + 2 * n:]):
            good = False
        if good:
            ntp_ok += 1
        else:
            ng.append('TP のレコード core %d SEQ %d（%d 個）が AXI4-Lite の TP のリングと違う' % (core, seq, n))
    print('check_ring core: TP のレコード %d（個 %d・AXI4-Lite の TP のリングと一致 %d）、SEQ の飛び %d' % (len(tps), ntp_items, ntp_ok, tp_gap))
    if len(tps) < 3:
        ng.append('TP のレコードが少ない（%d）' % len(tps))
    nok = nh = 0
    for core, s, seq, w in recs:
        k = (core, s, seq)
        if k not in qq:
            ng.append('凍ったバンクを写していないレコード core %d s %d SEQ %d' % k); continue
        if w[8:] != qq[k]:
            bad = [i for i, (a, b) in enumerate(zip(w[8:], qq[k])) if a != b]
            ng.append('本体が凍ったバンクと違う（%s）: %d 語、最初 ch %d' % (k, len(bad), bad[0] if bad else -1))
            continue
        if k in hh:
            nh += 1
            for n in range(1, 7):
                if w[n] != hh[k][n - 1]:
                    ng.append('頭の w%d が AXI4-Lite の DUMP_* と違う（%s）: %016x / %016x' % (n, k, w[n], hh[k][n - 1]))
        nok += 1
    by, ngap, bad = gaps(recs)
    ng += bad
    late = sum(int(v) for kk, v in lg.items() if kk.startswith('REC_LATE'))
    late_all = late + int(lg.get('TP_REC_LATE', '0'))
    drop, rcnt = int(lg['DROP_CNT']), int(lg['REC_CNT'])
    print('check_ring core: レコード %d（本体が凍ったバンクと一致 %d、うち頭を AXI4-Lite と照らした %d）、流れごと %s、'
          'SEQ の飛び %d、REC_LATE 計 %d、DROP_CNT %d、REC_CNT %d、PEAK %s'
          % (len(recs), nok, nh, {k: len(v) for k, v in sorted(by.items())}, ngap, late, drop, rcnt, lg['PEAK']))
    if rcnt != len(recs) + len(tps):
        ng.append('REC_CNT %d ≠ 受けた数 %d（SPEC %d ＋ TP %d）' % (rcnt, len(recs) + len(tps), len(recs), len(tps)))
    if ngap > drop:
        ng.append('SEQ の飛び %d > DROP_CNT %d' % (ngap, drop))
    if late_all > drop:
        ng.append('REC_LATE（TP を含む）の和 %d > DROP_CNT %d' % (late_all, drop))
    if lg.get('AXI_CMP') != 'OK':
        ng.append('AXI4-Lite の 16 ch の照合: %s' % lg.get('AXI_CMP'))
    want = lg.get('WANT', '')
    if want == 'nolate':
        if late != 0 or drop != 0 or ngap != 0 or tp_gap != 0 or int(lg.get('TP_REC_LATE', '0')) != 0:
            ng.append('取りこぼしがある（REC_LATE %d・DROP %d・飛び %d・TP の飛び %d・TP_REC_LATE %s）' % (late, drop, ngap, tp_gap, lg.get('TP_REC_LATE')))
        if len(by.get((0, 1), [])) != 1 or lg.get('ONE') != 'OK':
            ng.append('ONE の流れ 1 のレコードが %d 個（1 個であるべき）・REC_CTRL の戻り %s' % (len(by.get((0, 1), [])), lg.get('ONE')))
        if len(by.get((0, 0), [])) < 3 or len(by.get((0, 2), [])) < 3:
            ng.append('ALL の流れのレコードが少ない')
        if nh < len(recs) - 3:
            ng.append('頭を AXI4-Lite と照らせたレコードが少ない（%d / %d）' % (nh, len(recs)))
    elif want == 'late':
        if late == 0:
            ng.append('N_ACC = 1 なのに REC_LATE が 0')
        if len(recs) < 5:
            ng.append('レコードが少なすぎる（%d）' % len(recs))
    if int(lg.get('NG', '0')) != 0:
        ng.append('tb の見張りに NG %s' % lg['NG'])
    return ng


if __name__ == '__main__':
    mode, d = sys.argv[1], sys.argv[2]
    flip = '--flip' in sys.argv
    ng = main_u(d, flip, '--noread' in sys.argv, '--berr' in sys.argv) if mode == 'u' else main_core(d, flip)
    for x in ng[:30]:
        print('  NG: ' + x)
    if len(ng) > 30:
        print('  …ほか %d 件' % (len(ng) - 30))
    print('結果: ' + ('通過' if not ng else '失敗（%d 件）' % len(ng)))
