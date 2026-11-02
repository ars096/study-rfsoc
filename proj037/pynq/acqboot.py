# SPDX-License-Identifier: BSD-3-Clause
"""proj021 手順 2-3d — 取得のプロセス（s45acq）を、bit ごとの PS の道具の置き場所（pydir）から起こす（specd の LOAD）

specd は取得のプロセスを **spawn** で起こし、ここの boot() を走らせる。boot() は
  1. specd の置き場所から読み込まれた道具（s45proto・s45ring など）を sys.modules から外し、pydir を sys.path の頭に置いて、そこへ cd する
     （proj020.bit なら proj020 の s45acq・spectrometer・window … を、その版の s45proto（v1）のまま使う）
  2. specd が作った溜まり（共有メモリ）に、pydir の s45ring の形でつなぐ（s45ring は proj018 から同じ形。作り直さない）
  3. pydir の s45acq.main(conn, ring, opts) を呼ぶ
fork でなく spawn にするのは、親が読み込んだ版の道具を子に持ち込まないため（proj020 の s45acq が proj021 の s45proto v2 を使ってしまう）
"""
import os
import sys


def attach_ring(R, name, cap, lock):
    """specd が作った共有メモリに、モジュール R（s45ring）の Ring の形でつなぐ（作らない・片付けない）"""
    from multiprocessing import resource_tracker, shared_memory
    import numpy as np
    r = R.Ring.__new__(R.Ring)
    r.cap = cap
    try:
        r.shm = shared_memory.SharedMemory(name=name, track=False)        # Python 3.13 から
    except TypeError:
        r.shm = shared_memory.SharedMemory(name=name)
        try:
            # Python 3.10: つないだだけでも子の終わりに resource_tracker が共有メモリを消してしまう。持ち主は specd なので外す
            resource_tracker.unregister(r.shm._name, "shared_memory")
        except Exception:  # noqa: BLE001
            pass
    r._ctl_mv = r.shm.buf[:16]
    r.ctl = np.ndarray(2, np.uint64, r._ctl_mv)
    r.buf = r.shm.buf[R.CTL:R.CTL + cap]
    r.lock = lock
    r._r = 0
    return r


def boot(conn, shm_name, cap, lock, opts, pydir):
    own = os.path.dirname(os.path.abspath(__file__))
    pyd = os.path.abspath(pydir)
    if pyd != own:
        for name, m in list(sys.modules.items()):
            f = getattr(m, "__file__", None)
            if f and os.path.dirname(os.path.abspath(f)) == own and name not in ("acqboot", "__mp_main__", "__main__"):
                del sys.modules[name]
    sys.path.insert(0, pyd)
    os.chdir(pyd)
    import s45ring
    import s45proto
    ring = attach_ring(s45ring, shm_name, cap, lock)
    import s45acq
    seq0 = int(getattr(opts, "seq0", 0) or 0)
    if seq0:
        # 記録の通し番号を LOAD の前から続ける（どの版の s45acq でも Acq.__init__ が self.seq = 0 にするので、その後で上書きする）
        init0 = s45acq.Acq.__init__

        def init(self, *a, **k):
            init0(self, *a, **k)
            self.seq = seq0
        s45acq.Acq.__init__ = init
    print(f"[acqboot] 道具 {pyd}（s45proto {s45proto.__file__}・版 {s45proto.VERSION}）・番号は {seq0} から", flush=True)
    s45acq.main(conn, ring, opts)
