#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""proj031 R — 共有の係数 URAM（g24_cu_0）を specd の外から触る（実機の陽性対照用。root・pynq-venv、specd が Overlay を載せた後に）

  python3 cuctl.py status            # STAT・CRC・COEF_CRC・NROW を読むだけ
  python3 cuctl.py drop [--row R]    # 行 R を**正しい中身のまま**書き直す（URAM の中身は変わらず、OK だけが落ちる: g24_cu は ROW の書きで OK を下げる。
                                     #   走っている間ならコアの flags[0] = coef_mis が立つはず、次の START は PS が断るはず）。CLR は OK を変えない
  python3 cuctl.py corrupt [--row R] # 行 R の 1 bit を反転して 4096 行を書き VERIFY（不一致が立ち、OK は 0 のまま・CRC が違うはず）
  python3 cuctl.py load              # 正しく書き直す（g24cu.load と同じ）

番地は build の address_map（g24_cu_0 = 0xA000_0000 ＋4 KiB）。hex は .bit と同じ場所（このスクリプトのある所）
"""
import argparse
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import g24cu  # noqa: E402

BASE = 0xA000_0000
PROJ = 0x0031_0200


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=("status", "drop", "corrupt", "load"))
    p.add_argument("--row", type=int, default=1234)
    p.add_argument("--bit", type=int, default=5, help="反転する bit（行の 576 bit のうち）")
    a = p.parse_args()
    from pynq import MMIO
    mm = MMIO(BASE, 0x1000)
    cid = int(mm.read(g24cu.R_ID)) & 0xFFFFFFFF
    if cid != g24cu.CU_ID:
        sys.exit(f"ID {cid:#010x}（期待 {g24cu.CU_ID:#010x}）。proj031 の .bit が載っていない")
    lo, hi = os.path.join(HERE, "g24_coef_lo.hex"), os.path.join(HERE, "g24_coef_hi.hex")

    def show(tag):
        st = g24cu.status(mm)
        print(f"{tag}（{datetime.datetime.utcnow().strftime('%H:%M:%S.%f')[:-3]} UTC）: STAT {st['stat']:#04x}（ok {st['stat'] & 1}・vbusy {st['stat'] >> 1 & 1}・vdone {st['stat'] >> 2 & 1}・vmis {st['stat'] >> 3 & 1}・wrote {st['stat'] >> 4 & 1}）"
              f"・CRC {st['crc']:#010x}・COEF_CRC {st['coef_crc']:#010x}・NROW {st['nrow']}", flush=True)
        return st

    show("前")
    if a.cmd == "drop":
        w = g24cu.words(g24cu.rows(lo, hi))
        for k in range(g24cu.NWORD):
            mm.write(g24cu.R_DATA + 4 * k, int(w[a.row, k]))
        mm.write(g24cu.R_ROW, a.row)
        print(f"行 {a.row} を正しい中身のまま書き直した")
    elif a.cmd == "load":
        g24cu.load(mm, lo, hi, PROJ)
    elif a.cmd == "corrupt":
        r = g24cu.rows(lo, hi)
        w = g24cu.words(r).copy()
        w[a.row, a.bit // 32] ^= 1 << (a.bit % 32)
        mm.write(g24cu.R_CTRL, 2)
        for m in range(g24cu.M):
            for k in range(g24cu.NWORD):
                mm.write(g24cu.R_DATA + 4 * k, int(w[m, k]))
            mm.write(g24cu.R_ROW, m)
        mm.write(g24cu.R_CTRL, 1)
        while int(mm.read(g24cu.R_CTRL)) & g24cu.ST_VBUSY:
            pass
        print(f"行 {a.row} の bit {a.bit} を反転して書いた（正しい CRC {g24cu.crc(r):#010x}）")
    if a.cmd != "status":
        show("後")


if __name__ == "__main__":
    main()
