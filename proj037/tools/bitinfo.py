#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""YATSUGATAKE M5b — .bit を読み、焼いた USR_ACCESS（commit）と構成のフレームのデータ（FDRI）の sha256 を出す（標準ライブラリだけ）

.bit = ヘッダ（長さ付きの欄 a: 設計の名前・b: part・c: 日付・d: 時刻）＋ 欄 e（構成の流れ）。
構成の流れは同期語 0xAA995566 の後のパケットの列（UG570 の構成のパケット）:
  type 1: [31:29] 001・[28:27] op（2 = 書く）・[26:13] レジスタ・[10:0] 語数
  type 2: [31:29] 010・[26:0] 語数（直前の type 1 のレジスタへ。FDRI のフレームのデータ）
USR_ACCESS はレジスタ 0x0D。BITSTREAM.CONFIG.USR_ACCESS を設定したときだけ書き込みがある（設定しない bit には無い）。

USR_ACCESS の 32 bit（docs/migration.md の M5）: [31:4] commit の短いハッシュ 7 桁・[3:1] 0・[0] 作業ツリーの汚れ

    python3 bitinfo.py proj021.bit                     # USR_ACCESS・commit・FDRI の sha256 など
    python3 bitinfo.py proj021.bit --expect 0x1234567 0   # 焼くはずの値と照らす（違えば終了状態 1）。none = 焼いていないはず
"""
import argparse
import hashlib
import struct
import sys

SYNC = 0xAA995566
REG_USR_ACCESS = 0x0D


class BitError(Exception):
    pass


def _fields(d):
    """ヘッダの欄 a〜d と、欄 e（構成の流れ）を返す"""
    if len(d) < 16:
        raise BitError("短すぎる（.bit でない）")
    i = 2 + struct.unpack(">H", d[:2])[0]
    i += 2 + struct.unpack(">H", d[i:i + 2])[0] - 1     # 長さ 1 の欄（中身は欄 a の鍵 'a'）の直前まで
    head = {}
    while i < len(d):
        k = d[i:i + 1]
        i += 1
        if k == b"e":
            n = struct.unpack(">I", d[i:i + 4])[0]
            i += 4
            if i + n > len(d):
                raise BitError("欄 e の長さがファイルを越える")
            return head, d[i:i + n]
        if k not in (b"a", b"b", b"c", b"d"):
            raise BitError(f"ヘッダの欄 {k!r} が読めない（.bit でない）")
        n = struct.unpack(">H", d[i:i + 2])[0]
        i += 2
        head[k.decode()] = d[i:i + n].rstrip(b"\0").decode("ascii", "replace")
        i += n
    raise BitError("欄 e が無い")


def read(path):
    """戻り値 dict: design・part・date・time・usr_access（int か None）・usr_writes（書き込みの回数）・fdri_words・fdri_sha256・body_sha256"""
    with open(path, "rb") as f:
        d = f.read()
    try:
        head, body = _fields(d)
    except (struct.error, UnicodeDecodeError) as e:
        raise BitError(f"ヘッダが読めない（.bit でない）: {e}") from None
    s = body.find(struct.pack(">I", SYNC))
    if s < 0:
        raise BitError("同期語が無い")
    w, n_body = s + 4, len(body)
    usr, last, fdri = [], None, []
    while w + 4 <= n_body:
        x = struct.unpack(">I", body[w:w + 4])[0]
        w += 4
        t = x >> 29
        if t == 1:
            op, reg, n = (x >> 27) & 3, (x >> 13) & 0x3FFF, x & 0x7FF
            if op == 2 and reg == REG_USR_ACCESS and n == 1:
                usr.append(struct.unpack(">I", body[w:w + 4])[0])
            last = reg
            w += 4 * n
        elif t == 2:
            n = x & 0x7FFFFFF
            fdri.append(body[w:w + 4 * n])
            w += 4 * n
        elif x in (SYNC, 0xFFFFFFFF, 0):
            continue
        else:
            raise BitError(f"構成の流れの語 {x:#010x}（{w - 4} バイト目）が読めない")
    h = hashlib.sha256()
    for b in fdri:
        h.update(b)
    if len(set(usr)) > 1:
        raise BitError(f"USR_ACCESS の書き込みが値の違う {len(usr)} 回（{', '.join(f'{v:#010x}' for v in usr)}）")
    return dict(design=head.get("a", ""), part=head.get("b", ""), date=head.get("c", ""), time=head.get("d", ""),
                usr_access=usr[0] if usr else None, usr_writes=len(usr),
                fdri_words=sum(len(b) for b in fdri) // 4, fdri_sha256=h.hexdigest(),
                body_sha256=hashlib.sha256(body).hexdigest())


def usr_access(path):
    """載せる .bit の USR_ACCESS（int）。焼いていなければ None。読めなければ BitError"""
    return read(path)["usr_access"]


def describe(v):
    """USR_ACCESS → 「commit 1234567（汚れなし）」など"""
    if v is None:
        return "なし（焼いていない bit）"
    note = "" if (v >> 1) & 7 == 0 else f"・[3:1] {(v >> 1) & 7}（0 のはず）"
    return f"commit {v >> 4:07x}（{'汚れあり' if v & 1 else '汚れなし'}{note}）"


def fmt(v):
    """ids・EVENT に載せる形（16 進 8 桁、焼いていなければ none）"""
    return "none" if v is None else f"{v:08x}"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("bit")
    p.add_argument("--expect", default=None, help="焼くはずの USR_ACCESS（0x… の 32 bit）か none")
    a = p.parse_args()
    try:
        r = read(a.bit)
    except (OSError, BitError) as e:
        print(f"bitinfo: 読めない: {e}")
        return 1
    print(f"bitinfo: {a.bit}")
    print(f"  設計 {r['design']} / part {r['part']} / {r['date']} {r['time']}")
    print(f"  USR_ACCESS: {fmt(r['usr_access'])} = {describe(r['usr_access'])}（書き込み {r['usr_writes']} 回）")
    print(f"  FDRI: {r['fdri_words']} 語 / sha256 {r['fdri_sha256']}")
    print(f"  構成の流れ（欄 e）の sha256: {r['body_sha256']}")
    if a.expect is None:
        return 0
    want = None if a.expect.lower() == "none" else int(a.expect, 16)
    if want != r["usr_access"]:
        print(f"bitinfo: 照合: 失敗（焼くはず {fmt(want)}・読めた {fmt(r['usr_access'])}）")
        return 1
    print(f"bitinfo: 照合: 通過（{fmt(want)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
