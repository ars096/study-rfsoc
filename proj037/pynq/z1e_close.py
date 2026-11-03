#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-3-Clause
"""Ring.close() がバッファを返した後に、同じ番地を 2 度 munmap しないか（ボードの上で。PL は触らない・.bit は載せ替えない）

  python3 test_ring_close.py [--mod plring] [--mb 64]

study-rfsoc proj037 Z-1: bo_sync の lambda が pyxrt の BO を握ったまま freebuffer() すると、BO は Ring が消えるときまで残り、
XRT が同じ番地をもう一度 munmap する。間にそこへ取られたページが消え、触ると SIGSEGV（rc 139）。
返した番地に匿名のページを MAP_FIXED_NOREPLACE で置き、Ring を消してから読む。
レジスタの読み書きは差し替える（rd は 0 = 止まっている）。--mod で直す前の写しを読ませると陽性対照になる。
成否は rc と最後の「結果:」の行で見る（落ちれば「結果:」の行は出ない）。
"""
import argparse
import ctypes
import gc
import importlib
import sys

import numpy as np
import pynq


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mod", default="plring", help="Ring を読む module（陽性対照は直す前の写し）")
    ap.add_argument("--mb", type=int, default=64)
    a = ap.parse_args()
    m = importlib.import_module(a.mod)
    r = object.__new__(m.Ring)
    r.buf = pynq.allocate(a.mb << 17, dtype=np.uint64)
    r.a64 = r.buf.view(np.ndarray)
    r.a8 = r.a64.view(np.uint8)
    r.bo_sync = None
    import pyxrt
    bo = r.buf.bo
    d = pyxrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE
    r.bo_sync = lambda n, off: bo.sync(d, n, off)       # plring.Ring.__init__ と同じ握り方
    del bo
    r.enable = lambda on: None
    r.rd = lambda off: 0
    r.wr = lambda off, v: None
    va, n = r.a8.ctypes.data, r.a8.nbytes
    r.close()
    # 返した番地に、そのまま匿名のページを置く（numpy の配列が入るかどうかは malloc 任せで、陽性対照にならなかった）
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.restype = ctypes.c_void_p
    libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
    PROT_RW, MAP_PRIVATE_ANON, MAP_FIXED_NOREPLACE = 3, 0x22, 0x100000
    p = libc.mmap(va, n, PROT_RW, MAP_PRIVATE_ANON | MAP_FIXED_NOREPLACE, -1, 0)
    if p != va:
        print(f"判定できない: 返した番地 {va:#x} に置けない（{p}・errno {ctypes.get_errno()}。まだ返っていない）")
        return 2
    x = np.ctypeslib.as_array((ctypes.c_uint8 * n).from_address(va))
    x[::4096] = 0x5A
    del r
    gc.collect()                                          # 直す前はここで BO が消え、2 度目の munmap
    s = int(x[::4096].sum())                              # ページが消えていれば SIGSEGV
    want = len(x[::4096]) * 0x5A
    print(f"結果: {'通過' if s == want else '不合格'}（{a.mod}・{a.mb} MiB・{va:#x}・和 {s} / {want}）")
    return 0 if s == want else 1


if __name__ == "__main__":
    sys.exit(main())
