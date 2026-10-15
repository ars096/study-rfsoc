#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj023 手順 4 — SAM45-Wide（BIT_KIND 1）の SLICE の流れを PS から動かし、レコードだけでスペクトルと ch → IF を読む道具

コア（s45_core_i = wide_s45_core）ごとに束ね B（1 / 2 / 4。コアの FFT_N = log2(32768 / B)）と、流れ s = 0・1 の最初の ch S0 を選ぶ。
**モードはコアごとに独立**（README D-6）。B 4 では流れ 1 は空（NCH 0。N/2 = 4096 ch を流れ 0 だけで出す）。

    sudo -E $(which python3) wide.py --clkin 0 --ref 10 --list
    sudo -E $(which python3) wide.py --clkin 0 --ref 10 --mode A=1,B=2,C=4,D=1 --s0 A0=0,A1=4096,B0=0,B1=4096 --nacc 100 --ndump 5 --out w1
    sudo -E $(which python3) wide.py --clkin 0 --ref 10 --mode A=2 --s0 A0=1000 --tone-ch A0:1234 --sg HOST --dbm -30 --out h2a   # H-2
    sudo -E $(which python3) wide.py --clkin 0 --ref 10 --switch 20 --nacc 100 --ndump 3                                       # H-4

ch → IF（INTERFACE 2.1、ナイキストゾーン 2）: 流れの ch i の ADC の周波数 f = (S0 + i + (B − 1)/(2B))·fs / N（N = 32768 / B）、
  IF = fs − f。**S0・N・B はレコードの頭から読む**（語 4 の log2 NFFT・log2 B、語 7 の上位 = S0_CUR。レジスタは使わない）。
  中身は ch の順（i = 0..4095）で、IF は i とともに下がる。npz には ch の順のまま入れ、IF の軸を添える。

--tone-ch KEY:i（H-2）: 流れ KEY の ch i の**中心**に SG を合わせる（--sg があれば道具が SG を設定し、読み返す。無ければ周波数を出して待つ）。
  捉えたスペクトルの最大の ch と、±1 ch の電力の重心（ch の単位）を出し、i との差を判定する（±0.1 ch 以内）。
  **(B − 1)/(2B) を取り違えると 1/4〜3/8 ch 外れる**（H-2 の狙い）。同じ周波数で B を変えた 3 回を並べるのが本番の形。

--switch K（H-4）: 4 コアの B を 1 → 2 → 4 → 1 …（コアごとにずらす）と K 回切り替え、毎回 N_DUMP 個のダンプをレコードで受ける。
  見るもの: 毎回のレコードの頭（log2 NFFT・log2 B・S0）がその回の設定と一致・RUN の中の SEQ が連続・DROP_CNT・REC_LATE が増えない。

判定に使う値は**道具が書いた値**（モード・S0・N_ACC）。DUT の読み返し（FFT_N・S0_CUR）は「効いたか」の照合に使い、期待には使わない
（手順 3a の陽性対照で分かった穴: 期待を DUT の状態から取ると、効かなかった設定でもつじつまが合う）。
"""
import argparse
import json
import math
import sys
import time

import numpy as np

import s45core as SC

FS_MHZ = 4096.0
N_PHYS = 32768
NCH = 4096
C_FFT_N = 0x80
S_S0, S_S0_CUR, S_S0_STEP = 0x100, 0x104, 0x108
CTRL_RUN, CTRL_STOP, CTRL_FCLR, CTRL_WRST = 1, 1 << 1, 1 << 8, 1 << 12
TYPE_SPEC = 1
KEYS = [f"{a}{s}" for a in "ABCD" for s in "01"]


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------ 純粋な式（ボード無しで試せる）
def lb_of(b):
    if b not in (1, 2, 4):
        raise ValueError(f"束ね B は 1 / 2 / 4（{b}）")
    return {1: 0, 2: 1, 4: 2}[b]


def n_of(b):
    return N_PHYS // b


def s0_max(b):
    return n_of(b) // 2 - NCH


def nch_of(b, s):
    """流れ s の ch 数（B 4 の流れ 1 は空）"""
    return 0 if (b == 4 and s == 1) else NCH


def f_adc_mhz(s0, i, b):
    """ch i の中心の ADC の周波数 [MHz]（INTERFACE 2.1）"""
    n = n_of(b)
    return (s0 + np.asarray(i, dtype=float) + (b - 1) / (2 * b)) * FS_MHZ / n


def if_mhz(s0, i, b, zone=2):
    f = f_adc_mhz(s0, i, b)
    return FS_MHZ - f if zone == 2 else f


def ch_of_if(f_if, s0, b, zone=2):
    """IF [MHz] → 流れの ch（小数。中心が整数）"""
    f = FS_MHZ - f_if if zone == 2 else f_if
    return f * n_of(b) / FS_MHZ - s0 - (b - 1) / (2 * b)


def parse_hdr(hw):
    """レコードの頭 8 語（u64）→ dict（INTERFACE 4.4）"""
    w = [int(x) for x in hw]
    return dict(rtype=w[0] >> 40 & 0xFF, core=w[0] >> 48 & 0xFF, s=w[0] >> 56 & 0xFF,
                seq=w[1] & 0xFFFFFFFF, dump_k=w[1] >> 32, dump_f0=w[2], dump_t=w[3],
                log2n=w[4] & 0xFF, log2b=w[4] >> 8 & 0xFF, shift=w[4] >> 16 & 0xFF, src=w[4] >> 40 & 0xFF, dump_h=w[4] >> 48 & 0xFFFF,
                dump_n=w[5] & 0xFFFFFFFF, dump_sat=w[5] >> 32, dump_cfg=w[6] & 0xFFFFFFFF, flags=w[6] >> 32,
                nbytes=w[7] & 0xFFFFFFFF, s0=w[7] >> 32)


def centroid(p, k):
    """ch k の ±1 ch の電力の重心（ch の単位）。端なら k"""
    if k <= 0 or k >= len(p) - 1:
        return float(k)
    w = np.asarray(p[k - 1:k + 2], dtype=float)
    return float(k + (w[2] - w[0]) / w.sum())


def parse_kv(s, keys, conv=int):
    out = {}
    if not s:
        return out
    for it in s.split(","):
        k, v = it.split("=")
        k = k.strip().upper()
        if k not in keys:
            raise ValueError(f"{k} は {keys} のどれか")
        out[k] = conv(v)
    return out


def selftest():
    """式の自己検査（ボード無し）。戻り値: NG の数"""
    ng = 0
    for b in (1, 2, 4):
        for s0 in (0, 1, s0_max(b)):
            for i in (0, 1, 1234, NCH - 1):
                f = float(if_mhz(s0, i, b))
                c = ch_of_if(f, s0, b)
                if abs(c - i) > 1e-9:
                    log(f"NG: B {b} S0 {s0} i {i}: IF {f} → ch {c}"); ng += 1
        # 束ねた ch の中心 = 細かい ch B·j 〜 B·j + B − 1 の中心
        j = 777
        fine = [(b * j + q) * FS_MHZ / N_PHYS for q in range(b)]
        if abs(float(f_adc_mhz(0, j, b)) - sum(fine) / b) > 1e-9:
            log(f"NG: B {b}: 束ねた ch の中心が細かい ch の中心の平均と違う"); ng += 1
    # 陽性対照: (B − 1)/(2B) を落とした式は B 2・4 で 1/4・3/8 ch ずれる
    for b, want in ((2, 0.25), (4, 0.375)):
        wrong = (FS_MHZ - float(if_mhz(0, 100, b))) * n_of(b) / FS_MHZ - 100   # 式 (S0 + i)·fs / N との差 = (B − 1)/(2B)
        if abs(wrong - want) > 1e-9:
            log(f"NG: 陽性対照 B {b}: 中心のずれ {wrong}（期待 {want}）"); ng += 1
    hw = np.zeros(8, dtype=np.uint64)
    hw[0] = np.uint64((0x53 << 0) | (1 << 40) | (2 << 48) | (1 << 56))
    hw[4] = np.uint64(14 | (1 << 8) | (7 << 16) | (2 << 40))
    hw[7] = np.uint64(32768 | (4096 << 32))
    h = parse_hdr(hw)
    if (h["rtype"], h["core"], h["s"], h["log2n"], h["log2b"], h["shift"], h["src"], h["s0"], h["nbytes"]) != (1, 2, 1, 14, 1, 7, 2, 4096, 32768):
        log(f"NG: parse_hdr {h}"); ng += 1
    p = np.zeros(10); p[4], p[5], p[6] = 1, 2, 1
    if abs(centroid(p, 5) - 5.0) > 1e-12:
        log("NG: centroid"); ng += 1
    log(f"selftest: {'全部通過' if ng == 0 else f'NG {ng} 件'}")
    return ng


# ------------------------------------------------------------------ ボード
def slices(c):
    return [s for s in c.streams if s.kind == SC.KIND_SLICE]


def key_of(st):
    return f"{st.core.adc_name[-1]}{st.s}"


def set_mode(c, b, s0s):
    """コア c を束ね b に、流れ s の S0 を s0s[s] にして WRST。効いたかを読み返す（期待は書いた値）。NG の文のリスト"""
    ng = []
    ss = slices(c)
    for st in ss:
        st.wr(SC.S_CTRL, CTRL_STOP)
        st.wr(SC.S_REC_CTRL, 0)
    c.wr(C_FFT_N, 15 - lb_of(b))
    for st in ss:
        st.wr(S_S0, s0s.get(st.s, 0))
    ss[0].wr(SC.S_CTRL, CTRL_WRST)                            # どちらの流れに書いてもコアの WRST（wide_core）
    time.sleep(0.005)
    fr = c.rd(C_FFT_N)
    if (fr & 0xFF, fr >> 8 & 0xFF, fr >> 16 & 0xFF) != (15 - lb_of(b), 15 - lb_of(b), 15):
        ng.append(f"{c.name}: FFT_N {fr:#08x}（期待 効いた {15 - lb_of(b)}・書いた {15 - lb_of(b)}・物理 15）")
    for st in ss:
        want = s0s.get(st.s, 0)
        if nch_of(b, st.s) and st.rd(S_S0_CUR) != want:
            ng.append(f"{key_of(st)}: S0_CUR {st.rd(S_S0_CUR)}（書いた {want}。0 ≦ S0 ≦ {s0_max(b)} の外は効かない）")
        if st.rd(SC.S_NCH) != nch_of(b, st.s):
            ng.append(f"{key_of(st)}: NCH {st.rd(SC.S_NCH)}（期待 {nch_of(b, st.s)}）")
        if st.rd(SC.S_PARAM) & 0xFF != 15 - lb_of(b):
            ng.append(f"{key_of(st)}: PARAM[7:0] {st.rd(SC.S_PARAM) & 0xFF}（期待 {15 - lb_of(b)}）")
    return ng


def run_streams(sts, nacc, ndump, shift):
    for st in sts:
        st.wr(SC.S_NACC, nacc); st.wr(SC.S_NDUMP, ndump); st.wr(SC.S_SHIFT, shift)
        st.wr(SC.S_REC_CTRL, 1)                               # ALL
    for st in sts:
        st.wr(SC.S_CTRL, CTRL_FCLR | CTRL_RUN)


def collect(ring, sts, ndump, timeout):
    """流れごとに SPEC のレコードを ndump 個まで集める。{key: [(hdr dict, payload u64, crc_ok and tail_ok)]}"""
    want = {(st.core.adc, st.s): key_of(st) for st in sts}
    got = {k: [] for k in want.values()}
    t0 = time.time()
    while time.time() - t0 < timeout:
        for core, s, seq, hw, pay, crc_ok, tail_ok in ring.read():
            h = parse_hdr(hw)
            k = want.get((core, s))
            if k is None or h["rtype"] != TYPE_SPEC:
                continue
            got[k].append((h, pay, crc_ok and tail_ok))
        if all(len(v) >= ndump for v in got.values()):
            break
        time.sleep(0.005)
    return got


def check_recs(key, recs, b, s0, nacc, ndump):
    """レコードの頭を**書いた値**と照らす。NG の文のリスト"""
    ng = []
    if len(recs) < ndump:
        ng.append(f"{key}: レコード {len(recs)} 個（期待 {ndump}）")
    seqs = [h["seq"] for h, _, _ in recs]
    if any((y - x) & 0xFFFFFFFF != 1 for x, y in zip(seqs, seqs[1:])):
        ng.append(f"{key}: SEQ が連続していない {seqs}")
    for h, pay, ok in recs:
        if not ok:
            ng.append(f"{key}: SEQ {h['seq']} の CRC・尾"); continue
        if (h["log2n"], h["log2b"], h["s0"]) != (15 - lb_of(b), lb_of(b), s0):
            ng.append(f"{key}: SEQ {h['seq']} の頭 log2N {h['log2n']}・log2B {h['log2b']}・S0 {h['s0']}"
                      f"（書いた {15 - lb_of(b)}・{lb_of(b)}・{s0}）")
        if h["dump_n"] != nacc:
            ng.append(f"{key}: SEQ {h['seq']} の DUMP_N {h['dump_n']}（N_ACC {nacc}）")
        if pay.size != NCH or h["nbytes"] != NCH * 8:
            ng.append(f"{key}: 中身 {pay.size} 語・{h['nbytes']} バイト")
    return ng


FLAG_NAMES = ("coef_mis", "tw_mis", "口の後の途切れ", "16 レーンの不揃い", "IP の TLAST 事象", "IP が受けない", "k1 の飛び", "書き込みの衝突")


def flag_str(v):
    return f"{v:#04x}" + ("（" + "・".join(n for i, n in enumerate(FLAG_NAMES) if v >> i & 1) + "）" if v else "")


def diag(cores, wait=0.5):
    """起動の後の見張り（FLAGS は粘着。**Overlay から今までに立ったもの**）→ 消して wait 秒後にもう一度（立ち続けるもの）。
    あわせて口（go）・最初のフレーム・FIN − FOUT（入力と出口のフレームの差。一定のはず）"""
    out = []
    for c in cores:
        st = slices(c)[0]
        f0 = st.rd(SC.S_FLAGS)
        gh = st.rd(0x204)
        fin = st.rd(SC.S_FIN); fout = st.rd(SC.S_FOUT)
        out.append([c, f0, gh, (fin - fout) & 0xFFFFFFFF])
    for c in cores:
        slices(c)[0].wr(SC.S_CTRL, CTRL_FCLR)
    time.sleep(wait)
    for o in out:
        o.append(slices(o[0])[0].rd(SC.S_FLAGS))
    log("起動の見張り（FLAGS: Overlay から今まで → 消して %.1f s 後）" % wait)
    for c, f0, gh, d, f1 in out:
        log(f"  {c.adc_name}: {flag_str(f0)} → {flag_str(f1)} / go {gh >> 1 & 1}・have_first {gh & 1} / FIN − FOUT {d}")
    return out


def open_board(a):
    import spectrometer as S
    S.setup_clocks(a.clkin, a.ref)
    from pynq import Overlay
    import xrfdc
    ol = Overlay(a.bitfile)
    if not isinstance(ol.rfdc, xrfdc.RFdc):
        log("ERROR: RFDC に xrfdc のドライバが当たっていない"); sys.exit(1)
    S.check_tiles(ol.rfdc, 2)
    time.sleep(a.settle)                                       # DSP のクロックが明けてから読む（s45core.py の注）
    cores, tmm = SC.discover(ol, bit_kind=1, bit_rev_min=1)
    for c in cores:
        if len(slices(c)) != 2 or [s.s for s in slices(c)] != [0, 1]:
            raise SC.S45Error(f"{c.name} の SLICE の流れが s = 0・1 でない（{[(s.s, s.kind) for s in c.streams]}）")
    return ol, cores, tmm


def capture(cores, ring, mode, s0, nacc, ndump, shift, timeout):
    """mode {ADC の文字: B}・s0 {KEY: S0} で WRST → RUN → 集める。戻り: (結果 dict, NG のリスト)"""
    ng = []
    sts = []
    for c in cores:
        L = c.adc_name[-1]
        b = mode.get(L, 1)
        ng += set_mode(c, b, {s: s0.get(f"{L}{s}", 0) for s in (0, 1)})
        sts += [st for st in slices(c) if nch_of(b, st.s)]
    ring.read()
    d0 = ring.regs()["drop"]
    late0 = {key_of(st): st.rd(SC.S_REC_LATE) for st in sts}
    run_streams(sts, nacc, ndump, shift)
    got = collect(ring, sts, ndump, timeout)
    out = {}
    for st in sts:
        k = key_of(st)
        b = mode.get(k[0], 1)
        ng += check_recs(k, got[k], b, s0.get(k, 0), nacc, ndump)
        late = st.rd(SC.S_REC_LATE) - late0[k]
        if late:
            ng.append(f"{k}: REC_LATE +{late}")
        if got[k]:
            spec = np.mean([p.astype(np.float64) for _, p, _ in got[k]], axis=0)
            h = got[k][0][0]
            bb = 1 << h["log2b"]
            out[k] = dict(spec=spec, if_mhz=if_mhz(h["s0"], np.arange(NCH), bb), b=bb, s0=h["s0"], log2n=h["log2n"],
                          seq=[x[0]["seq"] for x in got[k]], dump_t=[x[0]["dump_t"] for x in got[k]],
                          flags=[x[0]["flags"] for x in got[k]], sat=[x[0]["dump_sat"] for x in got[k]])
    dd = ring.regs()["drop"] - d0
    if dd:
        ng.append(f"DROP_CNT +{dd}")
    for st in sts:
        st.wr(SC.S_CTRL, CTRL_STOP)
        st.wr(SC.S_REC_CTRL, 0)
    return out, ng


def save(path, res, meta):
    arr = {}
    for k, v in res.items():
        arr[f"{k}_spec"] = v["spec"]
        arr[f"{k}_if_mhz"] = v["if_mhz"]
    meta = dict(meta, streams={k: {kk: vv for kk, vv in v.items() if kk not in ("spec", "if_mhz")} for k, v in res.items()})
    np.savez_compressed(path + ".wide.npz", meta=json.dumps(meta, default=int), **arr)
    log(f"wrote {path}.wide.npz")


# 境目の電力比の物差し（model/wide_model の量子化した係数の ch の応答から、2026-10-15）: 2 つの ch の境目から δ 束ねた ch だけずれた
#   CW の 10·log10(P_i / P_{i+1}) [dB]。δ = 0.1 での値を判定の線に、0 の近くの傾き [dB / ch] を δ の見積もりに使う
EDGE_DB_AT_01 = {1: 4.82, 2: 10.37, 4: 28.68}
EDGE_SLOPE = {1: 46.9, 2: 93.9, 4: 188.2}


def do_tone(cores, ring, a, mode, s0):
    """H-2: 流れ KEY の (1) ch i の中心 → 最大の ch が i、(2) ch i と i + 1 の境目 → 両側の電力がそろう（±0.1 ch の線）。
    中心だけでは、束ねた ch の上が平らなので 1/4 ch のずれが見えにくい。**境目の電力比は 0.1 ch で 4.8〜29 dB 動く**ので、こちらで判定する"""
    key, i = a.tone_ch.split(":")
    key, i = key.strip().upper(), int(i)
    b = mode.get(key[0], 1)
    k0 = s0.get(key, 0)
    sg = None
    if a.sg:
        import sg as SGM
        sg = SGM.SG(a.sg, log=log)
    out, ngs, r = {}, [], dict(key=key, b=b, s0=k0, ch=i)
    try:
        for tag, x in (("center", float(i)), ("edge", i + 0.5)):
            f_if = float(if_mhz(k0, x, b))
            log(f"H-2 {tag}: {key}（B {b}・S0 {k0}）の ch {x} = IF {f_if:.6f} MHz（ADC {FS_MHZ - f_if:.6f} MHz）")
            if sg is not None:
                sg.set_freq_mhz(f_if); sg.set_dbm(a.dbm); sg.set_output(True)
                time.sleep(0.2)
            else:
                input(f"SG を {f_if:.6f} MHz・{a.dbm} dBm にして Enter: ")
            res, ng = capture(cores, ring, mode, s0, a.nacc, a.ndump, a.shift, a.timeout)
            ngs += ng
            if key not in res:
                ngs.append(f"{key} のスペクトルが無い"); continue
            out.update({f"{kk}_{tag}": v for kk, v in res.items()})
            p = res[key]["spec"]
            r[f"{tag}_if_mhz"] = f_if
            if tag == "center":
                k = int(np.argmax(p))
                r.update(peak=k, peak_pow=float(p[k]), centroid=centroid(p, k))
                ok = k == i
                log(f"  {'OK' if ok else 'NG'}  最大の ch {k}（期待 {i}）/ 重心 {r['centroid']:.4f}（参考）/ 電力 {p[k]:.4g}")
                if not ok:
                    ngs.append(f"H-2: 中心の CW の最大の ch {k}（期待 {i}）")
            else:
                ratio = 10 * math.log10(max(p[i], 1e-30) / max(p[i + 1], 1e-30))
                lim = EDGE_DB_AT_01[b]
                d = ratio / EDGE_SLOPE[b]
                r.update(edge_db=ratio, edge_delta_ch=d, edge_lim_db=lim)
                ok = abs(ratio) <= lim
                log(f"  {'OK' if ok else 'NG'}  境目の電力比 P[{i}]/P[{i + 1}] = {ratio:+.2f} dB（±{lim} dB = ±0.1 ch の線）/ "
                    f"ずれの見積もり {d:+.3f} ch（(B − 1)/(2B) を落とすと {(b - 1) / (2 * b):.3f}）")
                if not ok:
                    ngs.append(f"H-2: 境目の電力比 {ratio:+.2f} dB（±{lim}）")
    finally:
        if sg is not None:
            sg.close()
    return out, ngs, r


def do_switch(cores, ring, a):
    """H-4: コアごとに B をずらして K 回切り替え、毎回レコードで照らす"""
    seqB = (1, 2, 4)
    ng_all = 0
    for n in range(a.switch):
        mode = {c.adc_name[-1]: seqB[(n + j) % 3] for j, c in enumerate(cores)}
        s0 = {}
        for c in cores:
            L = c.adc_name[-1]
            b = mode[L]
            s0[f"{L}0"] = min(17 * n, s0_max(b))
            s0[f"{L}1"] = s0_max(b)
        res, ng = capture(cores, ring, mode, s0, a.nacc, a.ndump, a.shift, a.timeout)
        log(f"  {n + 1:>3}/{a.switch} B {mode} → 流れ {len(res)} 本 {'OK' if not ng else 'NG ' + str(len(ng))}")
        for x in ng:
            log(f"      {x}")
        ng_all += len(ng)
    log(f"H-4: {a.switch} 回の切り替えで NG {ng_all} 件")
    return 1 if ng_all else 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--selftest", action="store_true", help="式の自己検査（ボード無し）")
    p.add_argument("--bitfile", default="proj023.bit")
    p.add_argument("--clkin", default="stock")
    p.add_argument("--ref", type=float, default=10.0)
    p.add_argument("--settle", type=float, default=5.0)
    p.add_argument("--size-mib", type=int, default=32)
    p.add_argument("--list", action="store_true")
    p.add_argument("--mode", default="", help="コアの束ね: A=1,B=2,…（既定 1）")
    p.add_argument("--s0", default="", help="流れの S0: A0=0,A1=4096,…（既定 0）")
    p.add_argument("--nacc", type=int, default=1250, help="N_ACC（フレーム 8 µs。1250 = 10 ms）")
    p.add_argument("--ndump", type=int, default=3)
    p.add_argument("--shift", type=int, default=7)
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--out", default="")
    p.add_argument("--tone-ch", default="", help="H-2: KEY:i（流れ KEY の ch i の中心に SG）")
    p.add_argument("--sg", default="", help="SG の宛先（HOST[:PORT]。リポジトリに書かない）")
    p.add_argument("--dbm", type=float, default=-30.0)
    p.add_argument("--switch", type=int, default=0, help="H-4: 切り替えの回数")
    a = p.parse_args()
    if a.selftest:
        sys.exit(1 if selftest() else 0)
    mode = parse_kv(a.mode, list("ABCD"))
    s0 = parse_kv(a.s0, KEYS)
    for L, b in mode.items():
        lb_of(b)
    for k, v in s0.items():
        b = mode.get(k[0], 1)
        if not 0 <= v <= s0_max(b) or (b == 4 and k[1] == "1"):
            log(f"ERROR: {k} の S0 {v}（B {b} では 0〜{s0_max(b)}、B 4 の流れ 1 は空）"); sys.exit(1)
    try:
        ol, cores, tmm = open_board(a)
        rip = getattr(ol, "s45_ring_0", None)
        if rip is None:
            raise SC.S45Error("ol.s45_ring_0 が無い")
        import plring
        ring = plring.Ring(rip.mmio, a.size_mib * plring.MiB)
    except SC.S45Error as e:
        log(f"ERROR: {e}"); sys.exit(1)
    log(SC.table(cores, tmm))
    diag(cores)                                               # 起動の見張りは Overlay の直後に読む（RUN の FCLR で消える前に）
    rc = 0
    allst = [st for c in cores for st in c.streams]
    try:
        ring.enable(True)
        meta = dict(bitfile=a.bitfile, mode=mode, s0=s0, nacc=a.nacc, ndump=a.ndump, shift=a.shift, proj=cores[0].proj,
                    build=[c.build for c in cores], t=time.time())
        if a.list:
            pass
        elif a.switch:
            rc = do_switch(cores, ring, a)
        elif a.tone_ch:
            res, ng, r = do_tone(cores, ring, a, mode, s0)
            for x in ng:
                log(f"  NG: {x}")
            rc = 1 if ng else 0
            if a.out:
                save(a.out, res, dict(meta, tone=r))
        else:
            res, ng = capture(cores, ring, mode, s0, a.nacc, a.ndump, a.shift, a.timeout)
            for k, v in res.items():
                kk = int(np.argmax(v["spec"]))
                log(f"  {k}: B {v['b']} S0 {v['s0']} IF {v['if_mhz'][-1]:.3f}〜{v['if_mhz'][0]:.3f} MHz / SEQ {v['seq']} / "
                    f"最大 ch {kk}（IF {v['if_mhz'][kk]:.4f}）/ SAT {v['sat']} / FLAGS {[hex(x) for x in v['flags']]}")
            for x in ng:
                log(f"  NG: {x}")
            log(f"結果: {'全部通過' if not ng else f'NG {len(ng)} 件'}")
            rc = 1 if ng else 0
            if a.out:
                save(a.out, res, meta)
    finally:
        ring.close(allst)
    sys.exit(rc)


if __name__ == "__main__":
    main()
