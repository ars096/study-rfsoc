import ctypes, gc, sys, numpy as np, pynq, pyxrt
def maps(va, n, tag):
    hits = []
    for l in open("/proc/self/maps"):
        a, b = (int(x, 16) for x in l.split()[0].split("-"))
        if a < va + n and b > va:
            hits.append(l.strip())
    print(tag, hits or "なし")
buf = pynq.allocate(64 << 17, dtype=np.uint64)
va = buf.view(np.ndarray).ctypes.data; n = buf.nbytes
maps(va, n, "alloc:")
bo = buf.bo
d = pyxrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE
f = lambda k, off: bo.sync(d, k, off)
keep = sys.argv[1] == "keep"
if not keep: f = None
del bo
buf.freebuffer()
maps(va, n, "freebuffer:")
libc = ctypes.CDLL(None, use_errno=True); libc.mmap.restype = ctypes.c_void_p
libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
p = libc.mmap(va, n, 3, 0x22 | 0x100000, -1, 0)
print("mmap", hex(p or 0), "==va", p == va, "errno", ctypes.get_errno())
maps(va, n, "mmap:")
f = None; gc.collect()
maps(va, n, "drop:")
del buf; gc.collect()
maps(va, n, "del buf:")
