import ctypes, gc, sys, os, numpy as np, pynq, pyxrt
def maps(va, n, tag):
    h=[l.split()[0]+" "+l.split()[1]+" "+(l.split()[5] if len(l.split())>5 else "") for l in open("/proc/self/maps")
       if int(l.split()[0].split("-")[0],16) < va+n and int(l.split()[0].split("-")[1],16) > va]
    print(tag, h or "なし", flush=True)
def main():
    buf = pynq.allocate(64 << 17, dtype=np.uint64)
    va = buf.view(np.ndarray).ctypes.data; n = buf.nbytes
    bo = buf.bo
    d = pyxrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE
    f = lambda k, off: bo.sync(d, k, off)
    if sys.argv[1] == "fix": f = None
    del bo
    buf.freebuffer()
    maps(va, n, "freebuffer:")
    arrs = [np.full(8 << 20, 0x5A, np.uint8) for _ in range(8)]
    inside = sum(va <= x.ctypes.data < va + n for x in arrs)
    print("配列が穴に入った数", inside, flush=True)
    maps(va, n, "arrays:")
    return f, buf, arrs, va, n
f, buf, arrs, va, n = main()
f = None; buf = None; gc.collect()
maps(va, n, "drop:")
print("sum", sum(int(x[::4096].sum()) for x in arrs), flush=True)
arrs = None; gc.collect()
print("end", flush=True)
