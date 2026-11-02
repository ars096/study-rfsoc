#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj018 — データの流れ（サーバー → ダウンロード PC）の記録の形。サーバー・受け側の両方がこのファイルを使う（numpy だけ。PYNQ は要らない）

記録 = 共通の頭（24 バイト）＋ 中身（plen バイト）。すべてリトルエンディアン。plen は 8 の倍数（記録の先頭は 8 バイト境界）。

共通の頭  <4sHHIIQ
  magic  b"S45F"
  ver    VERSION
  type   T_SPEC / T_TP / T_EVENT（T_PAD は溜まりの中だけ。送らない）
  plen   中身のバイト数
  crc    中身の CRC-32（zlib.crc32）。**取得の側が PL から読んだ値で計算する**（溜まり・ソケットを通った後に受け側で照合）
  seq    記録の通し番号（取得のプロセスの起動から 1, 2, ...）。**欠けた番号 = 捨てた記録**（DROP / SKIP の EVENT が範囲を言う）。
         seq = 0 は通信の側が作った EVENT（番号を持たない）

SPEC の中身  <BBBBBBHIIIIIIqqd ＋ 4096 × uint64
  adc win ns shift fmt g rsv | cfg k nacc sat flags health | dump_t utc_ns | if_mhz
  adc    0..3（ADC_A..D）、win 0..1、ns 1..6、shift（RUN_SHIFT）、fmt FMT_RAW（proj018 は raw だけ）、g（FFT の入力の小数 4 / 5）
  cfg    DUMP_CFG（CFG_ID）、k DUMP_K、nacc N_ACC、sat DUMP_SAT（18 bit で飽和した点の数）、flags 窓の FLAGS、
  health DUMP_H（[0..15] PL の健全性）| サーバーの印（[16] 時刻を答えられない: utc_ns は 0 / [17] START を force で始めた）
  dump_t DUMP_T（ビート）、utc_ns 最初のサンプルの UTC（timebase.sample_utc_ns と同じ式。H_NOTIME なら 0）、if_mhz 窓の中心の IF
  4096 ch は **IF の昇順**（window.ch_if。第 2 ナイキストで反転しているので FFT の ch の順 b とは逆:
  送る i ↔ b = (2047 − i) mod 4096）。値は PL の 64 bit の積分値そのまま（Σ_N_ACC (q_re² + q_im²)）

TP の中身  <BBHI ＋ n × <qqQII
  adc rsv rsv2 n | 区切りごと: t_beat utc_ns sum nfr flags
  t_beat 区切りの最初のフレームの頭のビート（ANCH_T + (f − ANCH_F)·512）、utc_ns その UTC（0 = 答えられない）、
  sum Σx²（14 bit の x = ADC の 16 bit >>> 2 の二乗。レーン FFT と同じ値）、nfr フレーム数（512）、flags tp_core の FLAGS（[4] 振り切れ）| サーバーの印（[16] 時刻を答えられない）

SNAP の中身  <BBHIqqQII ＋ n × int16（proj019 追加。ADC の生サンプル、SNAP 命令で IDLE のときに取る）
  adc kind rsv n | dump_t utc_ns | frame | health k
  kind 0 = 全帯域コア（spec_core_0）のスナップショット: ダンプの最初のフレーム 8192 サンプル（2 µs）を ADC の 16 bit のまま
  （**下位 2 bit は常に 0。14 bit の x = 値 >> 2**）。dump_t = そのフレームの頭のビート、utc_ns その UTC（0 = 答えられない）、
  frame = フレームの番号（SNAP_F = DUMP_F0 を確かめたもの）、health = DUMP_H | サーバーの印、k = SNAP の中での通し番号（0, 1, …）

**v2（proj021 手順 2-3c、INTERFACE 6.）**: 共通の頭の ver = 2。SPEC の中身だけが変わる（TP・SNAP・EVENT は v1 と同じ形）。受け側は ver 1・2 の両方を読む
SPEC v2 の中身  <8B10I3q2d（88 バイト）＋ nch × float32（fmt 1）/ uint64（fmt 0、試験の照合のときだけ）
  core s src kind ns shift fmt bit_kind | nch n_sum cfg k nacc sat flags health g rsv | dump_t utc_ns base_ns | if_mhz df_hz
  core   コアの ADC（CORE_PORT）、s 流れの番号、src そのダンプの入力の ADC、kind 流れの KIND（3 = DDC・1 = FULL）、bit_kind BIT_KIND
  nch    ch 数、n_sum 束ねた PL のダンプの数、nacc 束の総フレーム数 ΣDUMP_N、base_ns 基本の単位（10,240,000）、df_hz ch の幅
  utc_ns **実効の区間の始まり**（INTERFACE 5.2: beat_utc(dump_t) − adc_to_core[src] − D_eff。DDC は D(NS) ＋ 1.5·L(NS)）。区間の中心 = utc_ns ＋ tint/2
  中身   IF の昇順（v1 と同じ）。float32 は u64 の束を**最も近い float32 に丸めたもの**（u64 → float64 は 2^53 未満で厳密 → float32 で 1 回だけ丸める）

EVENT の中身  UTF-8 の JSON（後ろは空白で 8 の倍数に詰める）。{"ev": "START" | "STOP" | "DROP" | "SKIP" | "ERROR" | ...}
  DROP / SKIP は {"ev": ..., "from": 最初の seq, "to": 最後の seq, "n": 数}（両端を含む）
"""
import json
import struct
import zlib

import numpy as np

MAGIC = b"S45F"
VERSION = 2                                         # proj021 2-3c: 送る版（specd の --proto 1 で v1）
VERSIONS = (1, 2)                                   # 読める版
T_PAD, T_SPEC, T_TP, T_EVENT, T_SNAP = 0, 1, 2, 3, 4
T_NAMES = {T_PAD: "PAD", T_SPEC: "SPEC", T_TP: "TP", T_EVENT: "EVENT", T_SNAP: "SNAP"}
FMT_RAW = 0                                         # u64（v1 はこれだけ。v2 では試験の照合のとき）
FMT_F32 = 1                                         # v2 の運転の形
NCH = 4096

HDR = struct.Struct("<4sHHIIQ")                     # 24
SPEC_H = struct.Struct("<BBBBBBHIIIIIIqqd")          # 56
TP_H = struct.Struct("<BBHI")                       # 8
SNAP_H = struct.Struct("<BBHIqqQII")                 # 40
SNAP_N = 8192
TP_E = np.dtype([("t_beat", "<i8"), ("utc_ns", "<i8"), ("sum", "<u8"), ("nfr", "<u4"), ("flags", "<u4")])   # 32
SPEC_PLEN = SPEC_H.size + 8 * NCH                   # 32824
SPEC2_H = struct.Struct("<8B10I3q2d")               # 88（v2）
BASE_NS = 10_240_000
H_NOTIME, H_FORCED = 1 << 16, 1 << 17
TPF_NOTIME = 1 << 16

# 送る i 番目 = FFT の ch b = (2047 − i) mod 4096（IF の昇順）。送る配列 = raw[IF_ORDER]
IF_ORDER = (2047 - np.arange(NCH)) % NCH


def pad8(n):
    return (n + 7) & ~7


def header(rtype, plen, crc, seq, ver=VERSION):
    return HDR.pack(MAGIC, ver, rtype, plen, crc, seq)


def parse_header(b):
    magic, ver, rtype, plen, crc, seq = HDR.unpack_from(b)
    if magic != MAGIC:
        raise ValueError(f"記録の印が違う: {bytes(magic)!r}")
    if ver not in VERSIONS:
        raise ValueError(f"記録の版 {ver}（この道具は {VERSIONS}）")
    return rtype, plen, crc, seq


def header_ver(b):
    """共通の頭の ver（decode に渡す。SPEC の形が版で違う）"""
    return HDR.unpack_from(b)[1]


def f32_round(u):
    """u64 → 最も近い float32（2^53 未満なら float64 は厳密なので、丸めは float32 への 1 回だけ）"""
    u = np.asarray(u, np.uint64)
    if u.size and int(u.max()) >= 1 << 53:
        raise ValueError("u64 が 2^53 以上（float64 で厳密でない）")
    return u.astype(np.float64).astype(np.float32)


def event_payload(d):
    b = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode()
    return b + b" " * (pad8(len(b)) - len(b))


def event_record(d, seq=0):
    p = event_payload(d)
    return header(T_EVENT, len(p), crc32(p), seq) + p


def decode(rtype, payload, ver=1):
    """中身を辞書に（受け側）。SPEC の data は v1: uint64 の 4096 個（IF の昇順）/ v2: float32（fmt 1）か uint64（fmt 0）の nch 個。
    v2 の SPEC にも adc（= core）・win（= s）を入れる（v1 の鍵で読む道具のため）"""
    if rtype == T_SPEC and ver == 2:
        (core, s, src, kind, ns, shift, fmt, bit_kind, nch, n_sum, cfg, k, nacc, sat, flags, health, g, _,
         dump_t, utc_ns, base_ns, if_mhz, df_hz) = SPEC2_H.unpack_from(payload)
        data = np.frombuffer(payload, "<f4" if fmt == FMT_F32 else "<u8", nch, SPEC2_H.size)
        return dict(ver=2, core=core, s=s, src=src, kind=kind, adc=core, win=s, ns=ns, shift=shift, fmt=fmt, bit_kind=bit_kind,
                    nch=nch, n_sum=n_sum, cfg=cfg, k=k, nacc=nacc, sat=sat, flags=flags, health=health, g=g,
                    dump_t=dump_t, utc_ns=utc_ns, base_ns=base_ns, if_mhz=if_mhz, df_hz=df_hz, data=data)
    if rtype == T_SPEC:
        (adc, win, ns, shift, fmt, g, _, cfg, k, nacc, sat, flags, health, dump_t, utc_ns, if_mhz) = SPEC_H.unpack_from(payload)
        data = np.frombuffer(payload, "<u8", NCH, SPEC_H.size)
        return dict(ver=1, adc=adc, win=win, ns=ns, shift=shift, fmt=fmt, g=g, cfg=cfg, k=k, nacc=nacc, sat=sat, flags=flags,
                    health=health, dump_t=dump_t, utc_ns=utc_ns, if_mhz=if_mhz, data=data, n_sum=1)
    if rtype == T_TP:
        adc, _, _, n = TP_H.unpack_from(payload)
        return dict(adc=adc, n=n, e=np.frombuffer(payload, TP_E, n, TP_H.size))
    if rtype == T_EVENT:
        return json.loads(bytes(payload).decode().rstrip())
    if rtype == T_SNAP:
        adc, kind, _, n, dump_t, utc_ns, frame, health, k = SNAP_H.unpack_from(payload)
        data = np.frombuffer(payload, "<i2", n, SNAP_H.size)
        return dict(adc=adc, kind=kind, n=n, dump_t=dump_t, utc_ns=utc_ns, frame=frame, health=health, k=k, data=data)
    raise ValueError(f"知らない記録の種類 {rtype}")


def crc32(*parts):
    c = 0
    for p in parts:
        c = zlib.crc32(p, c)
    return c & 0xFFFFFFFF
