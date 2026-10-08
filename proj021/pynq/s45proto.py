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

EVENT の中身  UTF-8 の JSON（後ろは空白で 8 の倍数に詰める）。{"ev": "START" | "STOP" | "DROP" | "SKIP" | "ERROR" | ...}
  DROP / SKIP は {"ev": ..., "from": 最初の seq, "to": 最後の seq, "n": 数}（両端を含む）
"""
import json
import struct
import zlib

import numpy as np

MAGIC = b"S45F"
VERSION = 1
T_PAD, T_SPEC, T_TP, T_EVENT, T_SNAP = 0, 1, 2, 3, 4
T_NAMES = {T_PAD: "PAD", T_SPEC: "SPEC", T_TP: "TP", T_EVENT: "EVENT", T_SNAP: "SNAP"}
FMT_RAW = 0
NCH = 4096

HDR = struct.Struct("<4sHHIIQ")                     # 24
SPEC_H = struct.Struct("<BBBBBBHIIIIIIqqd")          # 56
TP_H = struct.Struct("<BBHI")                       # 8
SNAP_H = struct.Struct("<BBHIqqQII")                 # 40
SNAP_N = 8192
TP_E = np.dtype([("t_beat", "<i8"), ("utc_ns", "<i8"), ("sum", "<u8"), ("nfr", "<u4"), ("flags", "<u4")])   # 32
SPEC_PLEN = SPEC_H.size + 8 * NCH                   # 32824
H_NOTIME, H_FORCED = 1 << 16, 1 << 17
TPF_NOTIME = 1 << 16

# 送る i 番目 = FFT の ch b = (2047 − i) mod 4096（IF の昇順）。送る配列 = raw[IF_ORDER]
IF_ORDER = (2047 - np.arange(NCH)) % NCH


def pad8(n):
    return (n + 7) & ~7


def header(rtype, plen, crc, seq):
    return HDR.pack(MAGIC, VERSION, rtype, plen, crc, seq)


def parse_header(b):
    magic, ver, rtype, plen, crc, seq = HDR.unpack_from(b)
    if magic != MAGIC:
        raise ValueError(f"記録の印が違う: {bytes(magic)!r}")
    if ver != VERSION:
        raise ValueError(f"記録の版 {ver}（この道具は {VERSION}）")
    return rtype, plen, crc, seq


def event_payload(d):
    b = json.dumps(d, ensure_ascii=False, separators=(",", ":")).encode()
    return b + b" " * (pad8(len(b)) - len(b))


def event_record(d, seq=0):
    p = event_payload(d)
    return header(T_EVENT, len(p), crc32(p), seq) + p


def decode(rtype, payload):
    """中身を辞書に（受け側）。SPEC の data は uint64 の 4096 個（IF の昇順）"""
    if rtype == T_SPEC:
        (adc, win, ns, shift, fmt, g, _, cfg, k, nacc, sat, flags, health, dump_t, utc_ns, if_mhz) = SPEC_H.unpack_from(payload)
        data = np.frombuffer(payload, "<u8", NCH, SPEC_H.size)
        return dict(adc=adc, win=win, ns=ns, shift=shift, fmt=fmt, g=g, cfg=cfg, k=k, nacc=nacc, sat=sat, flags=flags,
                    health=health, dump_t=dump_t, utc_ns=utc_ns, if_mhz=if_mhz, data=data)
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
